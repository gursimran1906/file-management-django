"""Compliance stats: done vs not done for every compliance item the firm tracks.

The page shows one donut per metric (green = done, red = not done), firm-wide
and then broken down by *responsible* fee earner, and every red number links to
a list of the outstanding items.

Everything here is computed from one ``Snapshot`` built per request, so the
number of queries does not grow with the number of fee earners or matters.
Metrics are declared once in ``METRICS``; the page and the drill-down both read
that registry, so adding a metric is one entry plus its collector.

Rules reused from elsewhere in the app rather than re-stated:
- annual risk review: ``get_risk_assessments_due_queryset``
- three-monthly file review: ``get_file_reviews_due_queryset``
- missing / expired proof of ID and address: ``get_live_matter_client_document_issues``
- responsible fee earner aliases (DC -> ND): ``backend.fee_earners``
- client account balance: the ledger sign rules of ``_finance_activity_ledger_deltas``
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.db.models import F, Max, Sum
from django.urls import reverse
from django.utils import timezone

from users.models import CustomUser

from .fee_earners import responsible_username
from .models import (
    WIP,
    AuthorisedParties,
    ClientContactDetails,
    Invoices,
    LastWork,
    LedgerAccountTransfers,
    MatterAttendanceNotes,
    MatterEmails,
    MatterLetters,
    OngoingMonitoring,
    PmtsSlips,
    RiskAssessment,
    Undertaking,
)

LIVE_STATUSES = ['Open', 'To Be Closed']
ARCHIVED_STATUS = 'Archived'
AML_MONTHS = 11       # matches the dashboard / management reports "AML checks due" threshold
DORMANT_MONTHS = 3    # matches the file review question "matter progressing without dormancy"
CLIENT_MONEY_RECENT_MONTHS = 12  # fallback window for the archived client-money check

def client_money_cutoff(today):
    """Archived files opened on or after this date are checked for client money.

    Older matters were not run through this system's ledgers (client-to-office
    transfers and payments in/out were recorded elsewhere), so a balance
    computed for them would be wrong. ``COMPLIANCE_CLIENT_MONEY_FROM`` (an ISO
    date in the environment) pins the start of reliable ledgers; without it
    the check covers files opened in the last ``CLIENT_MONEY_RECENT_MONTHS``.
    """
    raw = str(getattr(settings, 'COMPLIANCE_CLIENT_MONEY_FROM', '') or '').strip()
    if raw:
        try:
            return date.fromisoformat(raw)
        except ValueError:
            pass
    return today - relativedelta(months=CLIENT_MONEY_RECENT_MONTHS)


GREEN = '#16a34a'     # green-600, as the staff timeline donut
RED = '#dc2626'       # red-600
TRACK = '#e5e7eb'     # gray-200 ring behind the segments
DONUT_CIRCUMFERENCE = 100  # r = 15.9155 in a 36x36 viewBox, so dash lengths are percentages
UNASSIGNED = 'none'   # GET value / row id for matters with no fee earner

# What the SRA expects that this system has no data for yet. Shown on the page
# so a screen of green never reads as "fully compliant".
NOT_TRACKED = [
    'Complaints log and response times',
    'Costs updates and estimate reviews',
    'Conflict checks',
    'Practising certificates, insurance, DBS and training expiry',
    'Client account reconciliations',
    'Data protection, retention and file destruction dates',
]


# ---------------------------------------------------------------------------
# Donut maths (same approach as backend/staff_timeline.py)
# ---------------------------------------------------------------------------

def donut_segments(done, not_done):
    """Dash/offset values for a two-segment inline SVG ring.

    Returns ``{'na': True, 'segments': []}`` when there is nothing to count, so
    the template can draw a grey ring instead of a misleading 0% red one.
    The done percentage is floored so 100% is only ever shown when everything
    is done.
    """
    total = done + not_done
    if total <= 0:
        return {'na': True, 'pct': None, 'segments': []}
    pct_done = round(done / total * 100, 1)
    pct_not_done = round(DONUT_CIRCUMFERENCE - pct_done, 1)
    display_done = done * 100 // total
    display_not_done = 100 - display_done
    start = 0.0
    segments = []
    for key, label, count, pct, display, colour in (
        ('done', 'Done', done, pct_done, display_done, GREEN),
        ('not_done', 'Not done', not_done, pct_not_done, display_not_done, RED),
    ):
        segments.append({
            'key': key,
            'label': label,
            'count': count,
            'pct': pct,
            'pct_display': display,
            'dash': pct,
            'gap': round(DONUT_CIRCUMFERENCE - pct, 1),
            # 25 puts the first segment's start at 12 o'clock; the next segment
            # starts where the previous one ended (offset by a full turn so it
            # never goes negative).
            'offset': round(DONUT_CIRCUMFERENCE + 25 - start, 1),
            'color': colour,
        })
        start += pct
    return {'na': False, 'pct': display_done, 'segments': segments}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

@dataclass
class Item:
    """One counted thing: a matter, a client, an authorised party or a record."""
    key: object
    fee_earner_ids: frozenset
    done: bool
    reason: str = ''
    cells: dict = field(default_factory=dict)
    sort: dict = field(default_factory=dict)

    @property
    def search_text(self):
        return ' '.join(str(c.get('value', '')) for c in self.cells.values()).lower()


@dataclass
class Metric:
    key: str
    label: str
    short_label: str
    group: str
    help: str
    collect: object                       # callable(snapshot) -> list[Item]
    columns: list                         # [{'key', 'label', 'sortable', 'truncate'}]
    reasons: dict = field(default_factory=dict)   # reason key -> legend label (not-done split)

    def help_for(self, snapshot):
        """Help text; a callable help receives the snapshot (for dates in the text)."""
        return self.help(snapshot) if callable(self.help) else self.help

    @property
    def detail_url(self):
        return reverse('compliance_stats_detail', args=[self.key])


GROUPS = [
    {
        'key': 'matter_risk',
        'title': 'Matter risk & reviews',
        'description': 'Risk assessments and their sign-off, ongoing monitoring, file reviews and dormancy on live matters.',
        'scope': 'matter',
    },
    {
        'key': 'client_dd',
        'title': 'Client due diligence',
        'description': 'AML, identity and client care documents for every client and authorised party on a live matter.',
        'scope': 'client',
        'footnote': 'A client or authorised party on files for two fee earners counts for both, so the rows add up to more than the firm figure.',
    },
    {
        'key': 'client_care',
        'title': 'Client care paperwork',
        'description': 'Engagement paperwork recorded on live matters, and undertakings given on them.',
        'scope': 'matter',
    },
    {
        'key': 'closure',
        'title': 'File closure',
        'description': 'Archived files that still carry an undischarged undertaking, and recently opened archived files that still hold client money.',
        'scope': 'archived',
    },
]


def _col(key, label, sortable=True, truncate=False):
    return {'key': key, 'label': label, 'sortable': sortable, 'truncate': truncate}


MATTER_COLUMNS = [
    _col('file_number', 'File'),
    _col('matter', 'Matter', truncate=True),
    _col('client', 'Client', truncate=True),
    _col('fee_earner', 'Fee earner', truncate=True),
]
CLIENT_COLUMNS = [
    _col('client', 'Client', truncate=True),
    _col('files', 'Files', truncate=True),
    _col('fee_earners', 'Fee earners'),
]
PARTY_COLUMNS = [
    _col('party', 'Authorised party', truncate=True),
    _col('relationship', 'Relationship', truncate=True),
    _col('files', 'Files', truncate=True),
    _col('fee_earners', 'Fee earners'),
]


# ---------------------------------------------------------------------------
# Snapshot: everything the collectors need, loaded once
# ---------------------------------------------------------------------------

def _fmt_date(value):
    return value.strftime('%d/%m/%Y') if value else ''


def _as_date(value):
    """Date part of a DateField/DateTimeField value (local time when aware)."""
    if value is None:
        return None
    if hasattr(value, 'tzinfo'):
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return value.date()
    return value


def _months_between(earlier, later):
    delta = relativedelta(later, earlier)
    return delta.years * 12 + delta.months


class Snapshot:
    """Live and archived matters, their clients/parties and fee earners."""

    WIP_FIELDS = (
        'id', 'file_number', 'matter_description', 'timestamp',
        'fee_earner_id', 'fee_earner__username',
        'client1_id', 'client1__name',
        'authorised_party1_id', 'authorised_party2_id',
        'date_of_client_care_sent', 'date_of_toe_sent', 'date_of_toe_rcvd',
        'date_of_ncba_sent', 'date_of_ncba_rcvd', 'file_status__status',
    )

    def __init__(self, today=None):
        self.today = today or timezone.localdate()
        self._cache = {}

        users = list(CustomUser.objects.values(
            'id', 'username', 'first_name', 'last_name'))
        self.users = {u['id']: u for u in users}
        users_by_code = {(u['username'] or '').upper(): u['id'] for u in users}

        rows = WIP.objects.filter(
            file_status__status__in=LIVE_STATUSES + [ARCHIVED_STATUS]
        ).values(*self.WIP_FIELDS).order_by('file_number')
        self.live, self.archived = [], []
        self.matters = {}
        self.matter_fee_earner = {}
        for row in rows:
            self.matters[row['id']] = row
            (self.archived if row['file_status__status'] == ARCHIVED_STATUS
             else self.live).append(row)
            self.matter_fee_earner[row['id']] = self._responsible_id(row, users_by_code)
        self.live_ids = [m['id'] for m in self.live]
        self.archived_ids = [m['id'] for m in self.archived]
        self.client_money_cutoff = client_money_cutoff(self.today)
        self.recent_archived = [
            m for m in self.archived
            if _as_date(m['timestamp']) and _as_date(m['timestamp']) >= self.client_money_cutoff
        ]
        self.recent_archived_ids = [m['id'] for m in self.recent_archived]

        # Clients: client1 plus the additional_clients M2M, without WIP.all_clients
        # (which is a query per matter).
        self.clients_of_matter = defaultdict(list)
        self.matters_of_client = defaultdict(set)
        for m in self.live:
            if m['client1_id']:
                self.clients_of_matter[m['id']].append(m['client1_id'])
                self.matters_of_client[m['client1_id']].add(m['id'])
        through = WIP.additional_clients.through.objects.filter(
            wip_id__in=self.live_ids
        ).values_list('wip_id', 'clientcontactdetails_id')
        for wip_id, client_id in through:
            if client_id not in self.clients_of_matter[wip_id]:
                self.clients_of_matter[wip_id].append(client_id)
            self.matters_of_client[client_id].add(wip_id)
        self.clients = {
            c['id']: c for c in ClientContactDetails.objects.filter(
                id__in=self.matters_of_client.keys()
            ).values(
                'id', 'name', 'is_business', 'date_of_last_aml', 'id_verified',
                'terms_of_engagement_signed', 'pep_signed',
                'source_of_funds_signed', 'ncba_signed',
            )
        } if self.matters_of_client else {}

        self.matters_of_party = defaultdict(set)
        for m in self.live:
            for key in ('authorised_party1_id', 'authorised_party2_id'):
                if m[key]:
                    self.matters_of_party[m[key]].add(m['id'])
        self.parties = {
            p['id']: p for p in AuthorisedParties.objects.filter(
                id__in=self.matters_of_party.keys()
            ).values('id', 'name', 'relationship_to_client', 'id_check', 'date_of_last_aml')
        } if self.matters_of_party else {}

    # -- fee earners -------------------------------------------------------

    def _responsible_id(self, row, users_by_code):
        if row['fee_earner_id'] is None:
            return None
        code = row['fee_earner__username'] or ''
        target = responsible_username(code)
        if target and target.upper() != code.upper():
            return users_by_code.get(target.upper(), row['fee_earner_id'])
        return row['fee_earner_id']

    def fee_earners_of(self, matter_ids):
        return frozenset(self.matter_fee_earner.get(mid) for mid in matter_ids)

    def fee_earner_label(self, fee_earner_id):
        if fee_earner_id is None:
            return 'Unassigned'
        user = self.users.get(fee_earner_id)
        if not user:
            return ''
        full = f"{user['first_name']} {user['last_name']}".strip()
        return full or user['username']

    def fee_earner_code(self, fee_earner_id):
        if fee_earner_id is None:
            return '—'
        user = self.users.get(fee_earner_id)
        return user['username'] if user else ''

    # -- cached per-request lookups ----------------------------------------

    def cached(self, key, loader):
        if key not in self._cache:
            self._cache[key] = loader()
        return self._cache[key]

    def latest_risk_assessments(self):
        """Latest RiskAssessment row per live matter (by date, then id)."""
        def load():
            rows = RiskAssessment.objects.filter(
                matter_id__in=self.live_ids
            ).values(
                'id', 'matter_id', 'signoff_status', 'due_diligence_date',
                'client_risk_level', 'matter_risk_level',
                'customer_due_diligence_level', 'politically_exposed_person',
                'financial_sanctions', 'country_subject_to_sanctions',
            ).order_by('matter_id', '-due_diligence_date', '-id')
            latest = {}
            for row in rows:
                latest.setdefault(row['matter_id'], row)
            return latest
        return self.cached('latest_ra', load)

    def risk_reviews_due(self):
        from .views import get_risk_assessments_due_queryset
        return self.cached('risk_due', lambda: {
            r['id']: r for r in get_risk_assessments_due_queryset(WIP.objects.all()).values(
                'id', 'latest_assessment_date', 'latest_monitoring_date')
        })

    def file_reviews_due(self):
        from .views import get_file_reviews_due_queryset
        return self.cached('file_reviews_due', lambda: {
            r['id']: r for r in get_file_reviews_due_queryset(WIP.objects.all()).values(
                'id', 'latest_review_date', 'latest_review_by')
        })

    def document_issues(self, category):
        from .views import get_live_matter_client_document_issues
        return self.cached(f'doc_issues_{category}', lambda: {
            r['client_id']: r for r in get_live_matter_client_document_issues(category)
        })

    def last_activity(self):
        """Most recent recorded activity date per live matter, and its kind."""
        def load():
            last = {m['id']: (m['timestamp'] and _as_date(m['timestamp']), 'File opened')
                    for m in self.live}
            sources = [
                (MatterAttendanceNotes, 'date', 'Attendance note'),
                (MatterLetters, 'date', 'Letter'),
                (MatterEmails, 'time', 'Email'),
                (LastWork, 'date', 'Completed task'),
                (PmtsSlips, 'date', 'Payment slip'),
                (Invoices, 'date', 'Invoice'),
            ]
            for model, date_field, label in sources:
                rows = model.objects.filter(
                    file_number_id__in=self.live_ids
                ).values('file_number_id').annotate(last=Max(date_field))
                for row in rows:
                    when = _as_date(row['last'])
                    if when is None:
                        continue
                    current = last.get(row['file_number_id'], (None, ''))[0]
                    if current is None or when > current:
                        last[row['file_number_id']] = (when, label)
            return last
        return self.cached('last_activity', load)


    def client_balances(self):
        """Client account balance per recently opened archived matter.

        Uses the ledger sign rules of the finances page
        (``_finance_activity_ledger_deltas``): only client-ledger slips and
        client-ledger transfers move it; invoices and credit notes never do.
        """
        def load():
            balances = defaultdict(lambda: Decimal('0'))
            slips = PmtsSlips.objects.filter(
                ledger_account='C', file_number_id__in=self.recent_archived_ids,
            ).values('file_number_id', 'is_money_out').annotate(total=Sum('amount'))
            for row in slips:
                sign = -1 if row['is_money_out'] else 1
                balances[row['file_number_id']] += sign * (row['total'] or Decimal('0'))
            archived = set(self.recent_archived_ids)
            transfers = LedgerAccountTransfers.objects.filter(
                from_ledger_account='C',
            ).values('file_number_from_id', 'file_number_to_id').annotate(total=Sum('amount'))
            for row in transfers:
                amount = row['total'] or Decimal('0')
                src, dst = row['file_number_from_id'], row['file_number_to_id']
                if src == dst:
                    # Same-matter client -> office transfer.
                    if src in archived:
                        balances[src] -= amount
                    continue
                if src in archived:
                    balances[src] -= amount
                if dst in archived:
                    balances[dst] += amount
            office_to_client = LedgerAccountTransfers.objects.filter(
                from_ledger_account='O', file_number_from_id=F('file_number_to_id'),
                file_number_from_id__in=self.archived_ids,
            ).values('file_number_from_id').annotate(total=Sum('amount'))
            for row in office_to_client:
                balances[row['file_number_from_id']] += row['total'] or Decimal('0')
            return {mid: round(bal, 2) for mid, bal in balances.items()}
        return self.cached('client_balances', load)


# ---------------------------------------------------------------------------
# Item builders
# ---------------------------------------------------------------------------

def _home_href(file_number):
    return reverse('home', args=[file_number]) if file_number else None


def _matter_cells(snap, m):
    fee_earner_id = snap.matter_fee_earner.get(m['id'])
    return {
        'file_number': {'value': m['file_number'] or '', 'href': _home_href(m['file_number'])},
        'matter': {'value': m['matter_description'] or '—', 'href': None},
        'client': {'value': m['client1__name'] or '—', 'href': None},
        'fee_earner': {'value': snap.fee_earner_label(fee_earner_id), 'href': None},
    }


def _matter_sort(snap, m):
    fee_earner_id = snap.matter_fee_earner.get(m['id'])
    return {
        'file_number': m['file_number'] or '',
        'matter': (m['matter_description'] or '').lower(),
        'client': (m['client1__name'] or '').lower(),
        'fee_earner': snap.fee_earner_label(fee_earner_id).lower(),
    }


def _matter_item(snap, m, done, reason='', cells=None, sort=None):
    all_cells = _matter_cells(snap, m)
    all_cells.update(cells or {})
    all_sort = _matter_sort(snap, m)
    all_sort.update(sort or {})
    return Item(
        key=m['id'],
        fee_earner_ids=frozenset([snap.matter_fee_earner.get(m['id'])]),
        done=done, reason='' if done else reason,
        cells=all_cells, sort=all_sort,
    )


def _files_and_fee_earners(snap, matter_ids):
    matters = sorted(
        (snap.matters[mid] for mid in matter_ids if mid in snap.matters),
        key=lambda m: m['file_number'] or '')
    files = ', '.join(m['file_number'] for m in matters if m['file_number'])
    codes = sorted({snap.fee_earner_code(snap.matter_fee_earner.get(m['id'])) for m in matters})
    return files, ', '.join(codes)


def _client_item(snap, client, done, reason='', cells=None, sort=None):
    matter_ids = snap.matters_of_client.get(client['id'], set())
    files, codes = _files_and_fee_earners(snap, matter_ids)
    all_cells = {
        'client': {'value': client['name'] or '', 'href': reverse('edit_client', args=[client['id']])},
        'files': {'value': files, 'href': None},
        'fee_earners': {'value': codes, 'href': None},
    }
    all_cells.update(cells or {})
    all_sort = {'client': (client['name'] or '').lower(), 'files': files, 'fee_earners': codes}
    all_sort.update(sort or {})
    return Item(
        key=client['id'],
        fee_earner_ids=snap.fee_earners_of(matter_ids),
        done=done, reason='' if done else reason,
        cells=all_cells, sort=all_sort,
    )


def _party_item(snap, party, done, reason='', cells=None, sort=None):
    matter_ids = snap.matters_of_party.get(party['id'], set())
    files, codes = _files_and_fee_earners(snap, matter_ids)
    all_cells = {
        'party': {'value': party['name'] or '', 'href': reverse('edit_authorised_party', args=[party['id']])},
        'relationship': {'value': party['relationship_to_client'] or '', 'href': None},
        'files': {'value': files, 'href': None},
        'fee_earners': {'value': codes, 'href': None},
    }
    all_cells.update(cells or {})
    all_sort = {'party': (party['name'] or '').lower(),
                'relationship': (party['relationship_to_client'] or '').lower(),
                'files': files, 'fee_earners': codes}
    all_sort.update(sort or {})
    return Item(
        key=party['id'],
        fee_earner_ids=snap.fee_earners_of(matter_ids),
        done=done, reason='' if done else reason,
        cells=all_cells, sort=all_sort,
    )


def _record_item(snap, m, record_id, done, reason='', cells=None, sort=None):
    item = _matter_item(snap, m, done, reason, cells, sort)
    item.key = record_id
    return item


def _date_cell(value):
    return {'value': _fmt_date(value) or '—', 'href': None}


def _far_past():
    return timezone.localdate().replace(year=1900)


# ---------------------------------------------------------------------------
# Collectors: matter risk & reviews
# ---------------------------------------------------------------------------

RA_STATUS_LABELS = dict(RiskAssessment.SIGNOFF_STATUS_CHOICES)
OM_STATUS_LABELS = dict(OngoingMonitoring.SIGNOFF_STATUS_CHOICES)


def _risk_assessment_action(m, ra):
    if ra:
        return {'value': 'Review', 'href': reverse('edit_risk_assessment', args=[ra['id']])}
    if m['file_number']:
        return {'value': 'Add', 'href': reverse('add_risk_assessment', args=[m['file_number']])}
    return {'value': '', 'href': None}


def collect_risk_assessment(snap):
    latest = snap.latest_risk_assessments()
    items = []
    for m in snap.live:
        ra = latest.get(m['id'])
        if ra is None:
            done, reason, status = False, 'none', 'No assessment'
        elif ra['signoff_status'] == RiskAssessment.SIGNOFF_SIGNED:
            done, reason, status = True, '', 'Signed off'
        else:
            done, reason = False, 'awaiting'
            status = RA_STATUS_LABELS.get(ra['signoff_status'], ra['signoff_status'])
        assessed = ra['due_diligence_date'] if ra else None
        opened = _as_date(m['timestamp'])
        days_open = (snap.today - opened).days if opened else None
        items.append(_matter_item(
            snap, m, done, reason,
            cells={
                'status': {'value': status, 'href': None},
                'assessed': _date_cell(assessed),
                'days_open': {'value': str(days_open) if days_open is not None else '', 'href': None},
                'action': _risk_assessment_action(m, ra),
            },
            sort={'status': status, 'assessed': assessed or _far_past(),
                  'days_open': days_open or 0, 'action': ''},
        ))
    return items


def collect_risk_review_current(snap):
    due = snap.risk_reviews_due()
    items = []
    for m in snap.live:
        row = due.get(m['id'])
        if row is None:
            done, reason, status = True, '', 'Up to date'
        elif row['latest_assessment_date'] is None:
            done, reason, status = False, 'never', 'Never assessed'
        else:
            done, reason, status = False, 'overdue', 'Annual review overdue'
        last_ra = row['latest_assessment_date'] if row else None
        last_om = row['latest_monitoring_date'] if row else None
        items.append(_matter_item(
            snap, m, done, reason,
            cells={
                'status': {'value': status, 'href': None},
                'last_assessment': _date_cell(last_ra),
                'last_monitoring': _date_cell(last_om),
                'action': ({'value': 'Add monitoring', 'href': reverse('add_ongoing_monitoring', args=[m['file_number']])}
                           if (m['file_number'] and last_ra) else
                           {'value': 'Add assessment', 'href': reverse('add_risk_assessment', args=[m['file_number']])}
                           if m['file_number'] else {'value': '', 'href': None}),
            },
            sort={'status': status, 'last_assessment': last_ra or _far_past(),
                  'last_monitoring': last_om or _far_past(), 'action': ''},
        ))
    return items


def collect_ongoing_monitoring_signoff(snap):
    rows = OngoingMonitoring.objects.filter(
        file_number_id__in=snap.live_ids
    ).values('id', 'file_number_id', 'signoff_status', 'date_due_diligence_conducted')
    items = []
    for row in rows:
        m = snap.matters[row['file_number_id']]
        done = row['signoff_status'] == OngoingMonitoring.SIGNOFF_SIGNED
        reason = '' if done else ('returned' if row['signoff_status'] == OngoingMonitoring.SIGNOFF_RETURNED else 'awaiting')
        status = OM_STATUS_LABELS.get(row['signoff_status'], row['signoff_status'])
        items.append(_record_item(
            snap, m, row['id'], done, reason,
            cells={
                'conducted': _date_cell(row['date_due_diligence_conducted']),
                'status': {'value': status, 'href': None},
                'action': {'value': 'Review', 'href': reverse('edit_ongoing_monitoring', args=[row['id']])},
            },
            sort={'conducted': row['date_due_diligence_conducted'] or _far_past(),
                  'status': status, 'action': ''},
        ))
    return items


def collect_file_review_current(snap):
    due = snap.file_reviews_due()
    items = []
    for m in snap.live:
        row = due.get(m['id'])
        if row is None:
            done, reason, status = True, '', 'Up to date'
        elif row['latest_review_date'] is None:
            done, reason, status = False, 'never', 'Never reviewed'
        else:
            done, reason, status = False, 'overdue', 'Review overdue'
        last = row['latest_review_date'] if row else None
        items.append(_matter_item(
            snap, m, done, reason,
            cells={
                'status': {'value': status, 'href': None},
                'last_review': _date_cell(last),
                'reviewed_by': {'value': (row or {}).get('latest_review_by') or '', 'href': None},
                'action': ({'value': 'Add review', 'href': reverse('add_matter_file_review', args=[m['file_number']])}
                           if m['file_number'] else {'value': '', 'href': None}),
            },
            sort={'status': status, 'last_review': last or _far_past(),
                  'reviewed_by': ((row or {}).get('latest_review_by') or '').lower(), 'action': ''},
        ))
    return items


def _high_risk_factors(ra):
    """Why the latest assessment counts as high risk (same rule as
    RiskAssessment.has_high_risk_outcome, evaluated on the values() row)."""
    probe = RiskAssessment(**{k: ra[k] for k in (
        'client_risk_level', 'matter_risk_level', 'customer_due_diligence_level',
        'politically_exposed_person', 'financial_sanctions', 'country_subject_to_sanctions')})
    if not probe.has_high_risk_outcome:
        return []
    factors = []
    if ra['client_risk_level'] == 'High':
        factors.append('Client: High')
    if ra['matter_risk_level'] == 'High':
        factors.append('Matter: High')
    if ra['customer_due_diligence_level'] == 'Enhanced':
        factors.append('Enhanced CDD')
    if ra['politically_exposed_person'] == 'Yes':
        factors.append('PEP')
    if ra['financial_sanctions'] == 'Yes':
        factors.append('Financial sanctions')
    if ra['country_subject_to_sanctions'] == 'Yes':
        factors.append('Sanctioned country')
    return factors


def collect_high_risk_signed_off(snap):
    latest = snap.latest_risk_assessments()
    items = []
    for m in snap.live:
        ra = latest.get(m['id'])
        if ra is None:
            continue
        factors = _high_risk_factors(ra)
        if not factors:
            continue
        done = ra['signoff_status'] == RiskAssessment.SIGNOFF_SIGNED
        status = RA_STATUS_LABELS.get(ra['signoff_status'], ra['signoff_status'])
        items.append(_matter_item(
            snap, m, done, 'awaiting',
            cells={
                'risk': {'value': ', '.join(factors), 'href': None},
                'status': {'value': status, 'href': None},
                'assessed': _date_cell(ra['due_diligence_date']),
                'action': _risk_assessment_action(m, ra),
            },
            sort={'risk': ', '.join(factors).lower(), 'status': status,
                  'assessed': ra['due_diligence_date'] or _far_past(), 'action': ''},
        ))
    return items


def collect_not_dormant(snap):
    last = snap.last_activity()
    cutoff = snap.today - relativedelta(months=DORMANT_MONTHS)
    items = []
    for m in snap.live:
        when, kind = last.get(m['id'], (None, ''))
        done = when is not None and when >= cutoff
        days = (snap.today - when).days if when else None
        items.append(_matter_item(
            snap, m, done, 'dormant',
            cells={
                'last_activity': _date_cell(when),
                'kind': {'value': kind, 'href': None},
                'days': {'value': str(days) if days is not None else '', 'href': None},
            },
            sort={'last_activity': when or _far_past(), 'kind': kind.lower(), 'days': days or 0},
        ))
    return items


# ---------------------------------------------------------------------------
# Collectors: client due diligence
# ---------------------------------------------------------------------------

def _aml_state(snap, last_aml):
    threshold = snap.today - relativedelta(months=AML_MONTHS)
    if last_aml is None:
        return False, 'never', 'Never checked', ''
    if last_aml > threshold:
        return True, '', 'Current', str(_months_between(last_aml, snap.today))
    return False, 'overdue', 'Overdue', str(_months_between(last_aml, snap.today))


def collect_aml_check(snap):
    items = []
    for client in snap.clients.values():
        done, reason, status, months = _aml_state(snap, client['date_of_last_aml'])
        items.append(_client_item(
            snap, client, done, reason,
            cells={
                'last_aml': _date_cell(client['date_of_last_aml']),
                'months': {'value': months, 'href': None},
                'status': {'value': status, 'href': None},
            },
            sort={'last_aml': client['date_of_last_aml'] or _far_past(),
                  'months': int(months or 0), 'status': status},
        ))
    return items


def _client_flag_collector(field_name, not_done_label):
    def collect(snap):
        items = []
        for client in snap.clients.values():
            done = client[field_name] is True
            items.append(_client_item(
                snap, client, done, 'missing',
                cells={'status': {'value': 'Yes' if done else not_done_label, 'href': None}},
                sort={'status': done},
            ))
        return items
    return collect


def _document_collector(category):
    def collect(snap):
        issues = snap.document_issues(category)
        items = []
        for client in snap.clients.values():
            issue = issues.get(client['id'])
            if issue is None:
                done, reason, status = True, '', 'Valid'
            else:
                done = False
                reason = 'expired' if issue['status'] == 'Expired' else 'missing'
                status = issue['status']
            expiry = issue['expiry_date'] if issue else None
            overdue = issue['days_overdue'] if issue else None
            items.append(_client_item(
                snap, client, done, reason,
                cells={
                    'status': {'value': status, 'href': None},
                    'document': {'value': (issue or {}).get('document_type') or '', 'href': None},
                    'expiry': _date_cell(expiry),
                    'days_overdue': {'value': str(overdue) if overdue else '', 'href': None},
                },
                sort={'status': status, 'document': ((issue or {}).get('document_type') or '').lower(),
                      'expiry': expiry or _far_past(), 'days_overdue': overdue or 0},
            ))
        return items
    return collect


def collect_authorised_party_id(snap):
    items = []
    for party in snap.parties.values():
        done = party['id_check'] is True
        items.append(_party_item(
            snap, party, done, 'missing',
            cells={'status': {'value': 'Checked' if done else 'Not checked', 'href': None}},
            sort={'status': done},
        ))
    return items


def collect_authorised_party_aml(snap):
    items = []
    for party in snap.parties.values():
        done, reason, status, months = _aml_state(snap, party['date_of_last_aml'])
        items.append(_party_item(
            snap, party, done, reason,
            cells={
                'last_aml': _date_cell(party['date_of_last_aml']),
                'months': {'value': months, 'href': None},
                'status': {'value': status, 'href': None},
            },
            sort={'last_aml': party['date_of_last_aml'] or _far_past(),
                  'months': int(months or 0), 'status': status},
        ))
    return items


# ---------------------------------------------------------------------------
# Collectors: client care paperwork
# ---------------------------------------------------------------------------

def _matter_date_collector(received_field, sent_field=None):
    def collect(snap):
        items = []
        for m in snap.live:
            received = m[received_field]
            cells = {'received': _date_cell(received)}
            sort = {'received': received or _far_past()}
            if sent_field:
                cells['sent'] = _date_cell(m[sent_field])
                sort['sent'] = m[sent_field] or _far_past()
            items.append(_matter_item(snap, m, received is not None, 'missing', cells=cells, sort=sort))
        return items
    return collect


def collect_client_care_sent(snap):
    items = []
    for m in snap.live:
        sent = m['date_of_client_care_sent']
        items.append(_matter_item(
            snap, m, sent is not None, 'missing',
            cells={'sent': _date_cell(sent)}, sort={'sent': sent or _far_past()},
        ))
    return items


def _undertaking_cells(row):
    return {
        'given': _date_cell(row['date_given']),
        'given_to': {'value': row['given_to'] or '', 'href': None},
        'description': {'value': row['description'] or '', 'href': None},
        'action': {'value': 'Open', 'href': reverse('edit_undertaking', args=[row['id']])},
    }


def _undertaking_sort(row):
    return {'given': row['date_given'] or _far_past(),
            'given_to': (row['given_to'] or '').lower(),
            'description': (row['description'] or '').lower(), 'action': ''}


def collect_undertakings_discharged(snap):
    rows = Undertaking.objects.filter(
        file_number_id__in=snap.live_ids
    ).values('id', 'file_number_id', 'date_given', 'given_to', 'description', 'date_discharged')
    items = []
    for row in rows:
        m = snap.matters[row['file_number_id']]
        done = row['date_discharged'] is not None
        cells = _undertaking_cells(row)
        cells['discharged'] = _date_cell(row['date_discharged'])
        sort = _undertaking_sort(row)
        sort['discharged'] = row['date_discharged'] or _far_past()
        items.append(_record_item(snap, m, row['id'], done, 'outstanding', cells=cells, sort=sort))
    return items


# ---------------------------------------------------------------------------
# Collectors: file closure (archived matters)
# ---------------------------------------------------------------------------

def collect_closed_no_client_money(snap):
    balances = snap.client_balances()
    items = []
    for m in snap.recent_archived:
        balance = balances.get(m['id'], Decimal('0'))
        done = balance == 0
        items.append(_matter_item(
            snap, m, done, 'holding',
            cells={'opened': _date_cell(_as_date(m['timestamp'])),
                   'balance': {'value': f'£{balance:,.2f}', 'href': None}},
            sort={'opened': _as_date(m['timestamp']) or _far_past(), 'balance': balance},
        ))
    return items


def collect_closed_no_open_undertakings(snap):
    rows = Undertaking.objects.filter(
        file_number_id__in=snap.archived_ids, date_discharged__isnull=True,
    ).values('id', 'file_number_id', 'date_given', 'given_to', 'description')
    open_by_matter = defaultdict(list)
    for row in rows:
        open_by_matter[row['file_number_id']].append(row)
    items = []
    for m in snap.archived:
        open_rows = sorted(open_by_matter.get(m['id'], []), key=lambda r: r['date_given'] or _far_past())
        done = not open_rows
        first = open_rows[0] if open_rows else None
        cells = {'open_count': {'value': str(len(open_rows)) if open_rows else '0', 'href': None}}
        sort = {'open_count': len(open_rows)}
        if first:
            cells.update(_undertaking_cells(first))
            sort.update(_undertaking_sort(first))
        else:
            cells.update({k: {'value': '', 'href': None} for k in ('given', 'given_to', 'description', 'action')})
            sort.update({'given': _far_past(), 'given_to': '', 'description': '', 'action': ''})
        items.append(_matter_item(snap, m, done, 'outstanding', cells=cells, sort=sort))
    return items


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------

def _metric(key, label, short_label, group, help, collect, columns, reasons=None):
    return Metric(key=key, label=label, short_label=short_label, group=group,
                  help=help, collect=collect, columns=columns, reasons=reasons or {})


METRICS = {m.key: m for m in [
    # -- Matter risk & reviews --------------------------------------------
    _metric(
        'risk_assessment', 'Risk assessment signed off', 'Risk assessment', 'matter_risk',
        'Live matters whose latest risk assessment has been signed off by a fee earner.',
        collect_risk_assessment,
        MATTER_COLUMNS + [_col('status', 'Status'), _col('assessed', 'Assessed'),
                          _col('days_open', 'Days open'), _col('action', '', sortable=False)],
        reasons={'awaiting': 'awaiting sign-off', 'none': 'no assessment'},
    ),
    _metric(
        'risk_review_current', 'Annual risk review up to date', 'Annual review', 'matter_risk',
        'Live matters with a risk assessment in the last year, or older ones with ongoing monitoring in the last year. Same rule as the "Risk assessments due" report.',
        collect_risk_review_current,
        MATTER_COLUMNS + [_col('status', 'Status'), _col('last_assessment', 'Last assessment'),
                          _col('last_monitoring', 'Last monitoring'), _col('action', '', sortable=False)],
        reasons={'never': 'never assessed', 'overdue': 'review overdue'},
    ),
    _metric(
        'ongoing_monitoring_signoff', 'Ongoing monitoring signed off', 'Monitoring sign-off', 'matter_risk',
        'Ongoing monitoring records on live matters that a fee earner has signed off. Counts records, so a matter with no monitoring is covered by the annual review figure instead.',
        collect_ongoing_monitoring_signoff,
        MATTER_COLUMNS + [_col('conducted', 'Conducted'), _col('status', 'Status'), _col('action', '', sortable=False)],
        reasons={'awaiting': 'awaiting sign-off', 'returned': 'returned for changes'},
    ),
    _metric(
        'file_review_current', 'File review up to date', 'File review', 'matter_risk',
        'Live matters reviewed by a supervisor in the last three months. Same rule as the "File reviews due" report.',
        collect_file_review_current,
        MATTER_COLUMNS + [_col('status', 'Status'), _col('last_review', 'Last review'),
                          _col('reviewed_by', 'Reviewed by'), _col('action', '', sortable=False)],
        reasons={'never': 'never reviewed', 'overdue': 'review overdue'},
    ),
    _metric(
        'high_risk_signed_off', 'High-risk matters signed off', 'High risk', 'matter_risk',
        'Live matters whose latest assessment is high risk (High client or matter risk, Enhanced CDD, PEP or sanctions) and has fee earner sign-off. Enhanced due diligence needs senior approval under the Money Laundering Regulations.',
        collect_high_risk_signed_off,
        MATTER_COLUMNS + [_col('risk', 'Why high risk', truncate=True), _col('status', 'Status'),
                          _col('assessed', 'Assessed'), _col('action', '', sortable=False)],
    ),
    _metric(
        'not_dormant', 'Matters active in the last 3 months', 'Not dormant', 'matter_risk',
        'Live matters with an attendance note, letter, email, completed task, payment slip or invoice in the last three months. Newly opened files always count as active.',
        collect_not_dormant,
        MATTER_COLUMNS + [_col('last_activity', 'Last activity'), _col('kind', 'What'), _col('days', 'Days ago')],
    ),
    # -- Client due diligence ---------------------------------------------
    _metric(
        'aml_check', 'AML check within 11 months', 'AML check', 'client_dd',
        'Clients on live matters whose last AML / UK business check is less than 11 months old. Unlike the "AML checks due" export this counts To Be Closed matters and clients who have never been checked.',
        collect_aml_check,
        CLIENT_COLUMNS + [_col('last_aml', 'Last AML check'), _col('months', 'Months ago'), _col('status', 'Status')],
        reasons={'never': 'never checked', 'overdue': 'overdue'},
    ),
    _metric(
        'id_verified', 'ID verified', 'ID verified', 'client_dd',
        'Clients on live matters marked as ID verified.',
        _client_flag_collector('id_verified', 'Not verified'),
        CLIENT_COLUMNS + [_col('status', 'Status')],
    ),
    _metric(
        'proof_of_id', 'Proof of ID valid', 'Proof of ID', 'client_dd',
        'Clients on live matters holding a proof of ID that has not expired. Same rule as the "Proof of ID issues" report.',
        _document_collector('proof_of_id'),
        CLIENT_COLUMNS + [_col('status', 'Status'), _col('document', 'Document'),
                          _col('expiry', 'Expiry'), _col('days_overdue', 'Days overdue')],
        reasons={'missing': 'missing', 'expired': 'expired'},
    ),
    _metric(
        'proof_of_address', 'Proof of address valid', 'Proof of address', 'client_dd',
        'Clients on live matters holding a proof of address that has not expired. Same rule as the "Proof of Address issues" report.',
        _document_collector('proof_of_address'),
        CLIENT_COLUMNS + [_col('status', 'Status'), _col('document', 'Document'),
                          _col('expiry', 'Expiry'), _col('days_overdue', 'Days overdue')],
        reasons={'missing': 'missing', 'expired': 'expired'},
    ),
    _metric(
        'terms_signed', 'Terms of engagement signed', 'Terms signed', 'client_dd',
        'Clients on live matters who have signed the terms of engagement.',
        _client_flag_collector('terms_of_engagement_signed', 'Not signed'),
        CLIENT_COLUMNS + [_col('status', 'Status')],
    ),
    _metric(
        'pep_signed', 'PEP declaration signed', 'PEP', 'client_dd',
        'Clients on live matters who have signed the politically exposed person declaration.',
        _client_flag_collector('pep_signed', 'Not signed'),
        CLIENT_COLUMNS + [_col('status', 'Status')],
    ),
    _metric(
        'source_of_funds_signed', 'Source of funds signed', 'Source of funds', 'client_dd',
        'Clients on live matters who have signed the source of funds declaration.',
        _client_flag_collector('source_of_funds_signed', 'Not signed'),
        CLIENT_COLUMNS + [_col('status', 'Status')],
    ),
    _metric(
        'ncba_signed', 'NCBA signed', 'NCBA signed', 'client_dd',
        'Clients on live matters who have signed the non-contentious business agreement.',
        _client_flag_collector('ncba_signed', 'Not signed'),
        CLIENT_COLUMNS + [_col('status', 'Status')],
    ),
    _metric(
        'authorised_party_id', 'Authorised party ID checked', 'Auth. party ID', 'client_dd',
        'Authorised parties on live matters whose identity has been checked.',
        collect_authorised_party_id,
        PARTY_COLUMNS + [_col('status', 'Status')],
    ),
    _metric(
        'authorised_party_aml', 'Authorised party AML within 11 months', 'Auth. party AML', 'client_dd',
        'Authorised parties on live matters whose last AML check is less than 11 months old.',
        collect_authorised_party_aml,
        PARTY_COLUMNS + [_col('last_aml', 'Last AML check'), _col('months', 'Months ago'), _col('status', 'Status')],
        reasons={'never': 'never checked', 'overdue': 'overdue'},
    ),
    # -- Client care paperwork --------------------------------------------
    _metric(
        'client_care_sent', 'Client care letter sent', 'Client care letter', 'client_care',
        'Live matters with a client care letter sent date recorded.',
        collect_client_care_sent,
        MATTER_COLUMNS + [_col('sent', 'Sent')],
    ),
    _metric(
        'toe_received', 'Terms of engagement received', 'Terms received', 'client_care',
        'Live matters with the signed terms of engagement received back.',
        _matter_date_collector('date_of_toe_rcvd', 'date_of_toe_sent'),
        MATTER_COLUMNS + [_col('sent', 'Sent'), _col('received', 'Received')],
    ),
    _metric(
        'ncba_received', 'NCBA received', 'NCBA received', 'client_care',
        'Live matters with the signed non-contentious business agreement received back.',
        _matter_date_collector('date_of_ncba_rcvd', 'date_of_ncba_sent'),
        MATTER_COLUMNS + [_col('sent', 'Sent'), _col('received', 'Received')],
    ),
    _metric(
        'undertakings_discharged', 'Undertakings discharged', 'Undertakings', 'client_care',
        'Undertakings given on live matters that have been discharged. Counts undertakings, not matters.',
        collect_undertakings_discharged,
        MATTER_COLUMNS + [_col('given', 'Given'), _col('given_to', 'Given to', truncate=True),
                          _col('description', 'Undertaking', truncate=True),
                          _col('discharged', 'Discharged'), _col('action', '', sortable=False)],
    ),
    # -- File closure -----------------------------------------------------
    _metric(
        'closed_no_client_money', 'Recent archived files with no client money held', 'No client money', 'closure',
        lambda snap: (
            f'Archived files opened on or after {_fmt_date(snap.client_money_cutoff)} whose client account '
            'balance is nil. Client money must be returned promptly once a matter ends (SRA Accounts Rules 2.5). '
            'Older files were not run through this system\'s ledgers, so they are left out; the balance follows '
            'the ledger on the finances page.'
        ),
        collect_closed_no_client_money,
        MATTER_COLUMNS + [_col('opened', 'Opened'), _col('balance', 'Client balance')],
    ),
    _metric(
        'closed_no_open_undertakings', 'Archived files with no open undertakings', 'No open undertakings', 'closure',
        'Archived files with every undertaking discharged.',
        collect_closed_no_open_undertakings,
        MATTER_COLUMNS + [_col('open_count', 'Open'), _col('given', 'Given'),
                          _col('given_to', 'Given to', truncate=True),
                          _col('description', 'Undertaking', truncate=True),
                          _col('action', '', sortable=False)],
    ),
]}


# ---------------------------------------------------------------------------
# Page context
# ---------------------------------------------------------------------------

def _pct(done, total):
    return done * 100 // total if total else None


def _counter():
    return {'done': 0, 'total': 0}


def _metric_context(snap, metric, items):
    done = sum(1 for i in items if i.done)
    total = len(items)
    not_done = total - done
    ring = donut_segments(done, not_done)
    reasons = []
    if metric.reasons:
        counts = defaultdict(int)
        for item in items:
            if not item.done:
                counts[item.reason] += 1
        for key, label in metric.reasons.items():
            if counts.get(key):
                reasons.append({
                    'key': key, 'label': label, 'count': counts[key],
                    'url': f'{metric.detail_url}?reason={key}',
                })
    return {
        'key': metric.key,
        'label': metric.label,
        'short_label': metric.short_label,
        'help': metric.help_for(snap),
        'done': done,
        'total': total,
        'not_done': not_done,
        'pct': ring['pct'],
        'na': ring['na'],
        'donut': ring['segments'],
        'reasons': reasons,
        'detail_url': metric.detail_url,
    }


def _fee_earner_rows(snap, group_metrics, items_by_metric):
    buckets = defaultdict(lambda: defaultdict(_counter))
    for metric in group_metrics:
        for item in items_by_metric[metric.key]:
            for fee_earner_id in item.fee_earner_ids:
                counter = buckets[fee_earner_id][metric.key]
                counter['total'] += 1
                counter['done'] += 1 if item.done else 0

    def row_key(fee_earner_id):
        return (fee_earner_id is None, snap.fee_earner_label(fee_earner_id).lower())

    rows = []
    for fee_earner_id in sorted(buckets, key=row_key):
        cells = []
        for metric in group_metrics:
            counter = buckets[fee_earner_id].get(metric.key, _counter())
            total, done = counter['total'], counter['done']
            not_done = total - done
            param = UNASSIGNED if fee_earner_id is None else fee_earner_id
            cells.append({
                'metric_key': metric.key,
                'done': done,
                'total': total,
                'not_done': not_done,
                'pct': _pct(done, total),
                'ok': total > 0 and done == total,
                'na': total == 0,
                'detail_url': f'{metric.detail_url}?fee_earner={param}',
            })
        rows.append({
            'id': fee_earner_id,
            'code': snap.fee_earner_code(fee_earner_id),
            'name': snap.fee_earner_label(fee_earner_id),
            'cells': cells,
        })
    return rows


def build_compliance_stats(snapshot=None):
    snap = snapshot or Snapshot()
    items_by_metric = {key: metric.collect(snap) for key, metric in METRICS.items()}
    scope_counts = {
        'matter': f'{len(snap.live)} live matter{"s" if len(snap.live) != 1 else ""}',
        'client': (f'{len(snap.clients)} client{"s" if len(snap.clients) != 1 else ""}'
                   f' and {len(snap.parties)} authorised part{"ies" if len(snap.parties) != 1 else "y"} on live matters'),
        'archived': (f'{len(snap.archived)} archived file{"s" if len(snap.archived) != 1 else ""}'
                     f' ({len(snap.recent_archived)} opened since {_fmt_date(snap.client_money_cutoff)})'),
    }
    groups = []
    for group in GROUPS:
        group_metrics = [m for m in METRICS.values() if m.group == group['key']]
        groups.append({
            'key': group['key'],
            'title': group['title'],
            'description': group['description'],
            'scope_line': scope_counts[group['scope']],
            'footnote': group.get('footnote', ''),
            'metrics': [_metric_context(snap, m, items_by_metric[m.key]) for m in group_metrics],
            'fee_earner_rows': _fee_earner_rows(snap, group_metrics, items_by_metric),
        })
    return {
        'generated': snap.today,
        'live_matter_count': len(snap.live),
        'live_client_count': len(snap.clients),
        'archived_matter_count': len(snap.archived),
        'groups': groups,
        'not_tracked': NOT_TRACKED,
    }


# ---------------------------------------------------------------------------
# Drill-down
# ---------------------------------------------------------------------------

def _matches_fee_earner(item, fee_earner):
    if not fee_earner:
        return True
    if fee_earner == UNASSIGNED:
        return None in item.fee_earner_ids
    try:
        return int(fee_earner) in item.fee_earner_ids
    except (TypeError, ValueError):
        return True


def build_metric_detail(metric, fee_earner='', reason='', q='', snapshot=None):
    """Not-done items for one metric, in render_report's row shape.

    Returns (columns, rows, fee_earner_options). fee_earner_options lists every
    responsible fee earner with items in this metric (done or not), so the
    filter offers people who are fully compliant too.
    """
    snap = snapshot or Snapshot()
    items = metric.collect(snap)

    fee_earner_ids = set()
    for item in items:
        fee_earner_ids.update(item.fee_earner_ids)
    options = [
        {'value': str(fid), 'label': f'{snap.fee_earner_code(fid)} — {snap.fee_earner_label(fid)}'}
        for fid in sorted((f for f in fee_earner_ids if f is not None),
                          key=lambda f: snap.fee_earner_label(f).lower())
    ]
    if None in fee_earner_ids:
        options.append({'value': UNASSIGNED, 'label': 'Unassigned'})

    q_lower = q.lower()
    rows = []
    for item in items:
        if item.done or not _matches_fee_earner(item, fee_earner):
            continue
        if reason and item.reason != reason:
            continue
        if q_lower and q_lower not in item.search_text:
            continue
        rows.append({'cells': item.cells, 'sort': item.sort})
    return metric.columns, rows, options
