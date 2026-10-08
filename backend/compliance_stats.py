"""Compliance stats: done vs not done for every compliance item the firm tracks.

The page shows one donut per metric (green = done, red = not done), firm-wide
and then broken down by *responsible* fee earner, and every red number links to
a list of the outstanding items.

Everything here is computed from one ``Snapshot`` built per request, so the
number of queries does not grow with the number of fee earners or matters.
Metrics are declared once in ``METRICS``; the page and the drill-down both read
that registry, so adding a metric is one entry plus its collector.

Rules reused from elsewhere in the app rather than re-stated:
- a review is current for a year: the same rule as the "Risk assessments due"
  report (``get_risk_assessments_due_queryset``)
- three-monthly file review: ``get_file_reviews_due_queryset``
- missing / expired proof of ID and address: ``get_live_matter_client_document_issues``
- responsible fee earner aliases (DC -> ND): ``backend.fee_earners``
"""

from collections import defaultdict
from dataclasses import dataclass, field

from dateutil.relativedelta import relativedelta
from django.db.models import Max
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
    MatterAttendanceNotes,
    MatterEmails,
    MatterLetters,
    OngoingMonitoring,
    PmtsSlips,
    RiskAssessment,
    Undertaking,
)

LIVE_STATUSES = ['Open', 'To Be Closed']
AML_MONTHS = 11       # matches the dashboard / management reports "AML checks due" threshold
REVIEW_MONTHS = 12    # a risk assessment or monitoring record keeps a matter current for a year
DORMANT_MONTHS = 3    # matches the file review question "matter progressing without dormancy"

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
    'Practising certificates, insurance, DBS and training expiry',
    'Client account reconciliations',
    'Data protection and retention policy reviews',
]


# ---------------------------------------------------------------------------
# Donut maths (same approach as backend/staff_timeline.py)
# ---------------------------------------------------------------------------

def donut_segments(done, not_done, labels=('Done', 'Not done')):
    """Dash/offset values for a two-segment inline SVG ring.

    Returns ``{'na': True, 'segments': []}`` when there is nothing to count, so
    the template can draw a grey ring instead of a misleading 0% red one.
    The done percentage is floored so 100% is only ever shown when everything
    is done. ``labels`` name the two segments for the ring's tooltips.
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
        ('done', labels[0], done, pct_done, display_done, GREEN),
        ('not_done', labels[1], not_done, pct_not_done, display_not_done, RED),
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
    """One counted thing: a matter, a client, a third party or a record."""
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
    # How the two states read on the page: "done / not done" for most metrics,
    # "active / not active" for dormancy and so on.
    labels: tuple = ('done', 'not done')
    # Reason keys whose legend link goes somewhere better than the generic
    # drill-down, e.g. "awaiting sign-off" -> the sign-off queue. Values are
    # callables so URLs are only reversed when the page is built.
    reason_urls: dict = field(default_factory=dict)

    def help_for(self, snapshot):
        """Help text; a callable help receives the snapshot (for dates in the text)."""
        return self.help(snapshot) if callable(self.help) else self.help

    @property
    def detail_url(self):
        return reverse('compliance_stats_detail', args=[self.key])

    def reason_url(self, reason_key):
        builder = self.reason_urls.get(reason_key)
        return builder() if builder else f'{self.detail_url}?reason={reason_key}'


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
        'description': 'Veriphy AML / ID checks, identity documents and client care declarations for every client and third party on a live matter.',
        'scope': 'client',
        'footnote': 'A client or third party on files for two fee earners counts for both, so the rows add up to more than the firm figure.',
    },
    {
        'key': 'client_care',
        'title': 'Client care paperwork',
        'description': 'Engagement paperwork recorded on live matters, and undertakings given on them.',
        'scope': 'matter',
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
    _col('party', 'Third party', truncate=True),
    _col('role', 'Role'),
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


THIRD_PARTY_ID_FIELDS = tuple(f'{name}_id' for name, _role in WIP.THIRD_PARTY_FIELDS)


class Snapshot:
    """Live matters, their clients / third parties and fee earners."""

    WIP_FIELDS = (
        'id', 'file_number', 'matter_description', 'timestamp',
        'fee_earner_id', 'fee_earner__username',
        'client1_id', 'client1__name',
        *THIRD_PARTY_ID_FIELDS,
        'date_of_client_care_sent', 'date_of_toe_sent', 'date_of_toe_rcvd',
        'date_of_ncba_sent', 'date_of_ncba_rcvd',
    )

    def __init__(self, today=None):
        self.today = today or timezone.localdate()
        self._cache = {}

        users = list(CustomUser.objects.values(
            'id', 'username', 'first_name', 'last_name'))
        self.users = {u['id']: u for u in users}
        users_by_code = {(u['username'] or '').upper(): u['id'] for u in users}

        self.live = list(WIP.objects.filter(
            file_status__status__in=LIVE_STATUSES
        ).values(*self.WIP_FIELDS).order_by('file_number'))
        self.matters = {m['id']: m for m in self.live}
        self.matter_fee_earner = {
            m['id']: self._responsible_id(m, users_by_code) for m in self.live}
        self.live_ids = list(self.matters)

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
                'id', 'name', 'is_business', 'date_of_last_aml',
                'terms_of_engagement_signed', 'pep_signed',
                'source_of_funds_signed', 'ncba_signed',
            )
        } if self.matters_of_client else {}

        # Third parties (authorised and paying) share one table; a party may
        # play either role on different files, so remember every role it has.
        self.matters_of_party = defaultdict(set)
        self.roles_of_party = defaultdict(set)
        for m in self.live:
            for name, role in WIP.THIRD_PARTY_FIELDS:
                party_id = m[f'{name}_id']
                if party_id:
                    self.matters_of_party[party_id].add(m['id'])
                    self.roles_of_party[party_id].add(role)
        self.parties = {
            p['id']: p for p in AuthorisedParties.objects.filter(
                id__in=self.matters_of_party.keys()
            ).values('id', 'name', 'relationship_to_client', 'date_of_last_aml')
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

    def latest_ongoing_monitoring(self):
        """Latest OngoingMonitoring row per live matter (by date, then id)."""
        def load():
            rows = OngoingMonitoring.objects.filter(
                file_number_id__in=self.live_ids
            ).values(
                'id', 'file_number_id', 'signoff_status', 'date_due_diligence_conducted',
            ).order_by('file_number_id', '-date_due_diligence_conducted', '-id')
            latest = {}
            for row in rows:
                latest.setdefault(row['file_number_id'], row)
            return latest
        return self.cached('latest_om', load)

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
    roles = ' / '.join(sorted(snap.roles_of_party.get(party['id'], ())))
    all_cells = {
        'party': {'value': party['name'] or '', 'href': reverse('edit_authorised_party', args=[party['id']])},
        'role': {'value': roles, 'href': None},
        'relationship': {'value': party['relationship_to_client'] or '', 'href': None},
        'files': {'value': files, 'href': None},
        'fee_earners': {'value': codes, 'href': None},
    }
    all_cells.update(cells or {})
    all_sort = {'party': (party['name'] or '').lower(), 'role': roles.lower(),
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


def _link_cell(label, url_name, *args):
    return {'value': label, 'href': reverse(url_name, args=args)}


def _far_past():
    return timezone.localdate().replace(year=1900)


# ---------------------------------------------------------------------------
# Collectors: matter risk & reviews
# ---------------------------------------------------------------------------

RA_STATUS_LABELS = dict(RiskAssessment.SIGNOFF_STATUS_CHOICES)
OM_STATUS_LABELS = dict(OngoingMonitoring.SIGNOFF_STATUS_CHOICES)


def _risk_assessment_action(m, ra):
    if ra:
        return _link_cell('Review', 'edit_risk_assessment', ra['id'])
    if m['file_number']:
        return _link_cell('Add', 'add_risk_assessment', m['file_number'])
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


def _latest_review(ra, om):
    """The review that counts for a matter: its most recent risk assessment or
    ongoing monitoring record, as (kind, row, date, signoff_status)."""
    ra_date = ra['due_diligence_date'] if ra else None
    om_date = om['date_due_diligence_conducted'] if om else None
    if om and (ra_date is None or (om_date and om_date >= ra_date)):
        return 'Ongoing monitoring', om, om_date, om['signoff_status']
    if ra:
        return 'Risk assessment', ra, ra_date, ra['signoff_status']
    return None, None, None, None


def collect_ongoing_monitoring(snap):
    """One item per live matter: is its risk review current and signed off?

    Monitoring is due at least annually or whenever anything changes. A matter
    is reviewed by its initial risk assessment and then by each ongoing
    monitoring record; the most recent of those must be less than a year old
    (the "Risk assessments due" rule) and signed off by a fee earner.
    """
    latest_ra = snap.latest_risk_assessments()
    latest_om = snap.latest_ongoing_monitoring()
    cutoff = snap.today - relativedelta(months=REVIEW_MONTHS)
    items = []
    for m in snap.live:
        kind, row, reviewed, signoff = _latest_review(latest_ra.get(m['id']), latest_om.get(m['id']))
        if row is None:
            done, reason, status = False, 'never', 'Never done'
        elif reviewed is None or reviewed <= cutoff:
            done, reason, status = False, 'overdue', 'Review overdue'
        elif signoff == OngoingMonitoring.SIGNOFF_SIGNED:
            done, reason, status = True, '', 'Up to date'
        else:
            done, reason = False, 'awaiting'
            status = OM_STATUS_LABELS.get(signoff, signoff)

        if m['file_number'] is None:
            action = {'value': '', 'href': None}
        elif reason == 'awaiting' and kind == 'Ongoing monitoring':
            action = _link_cell('Review', 'edit_ongoing_monitoring', row['id'])
        elif reason == 'awaiting':
            action = _link_cell('Review', 'edit_risk_assessment', row['id'])
        elif row is None:
            action = _link_cell('Add assessment', 'add_risk_assessment', m['file_number'])
        else:
            action = _link_cell('Add monitoring', 'add_ongoing_monitoring', m['file_number'])

        items.append(_matter_item(
            snap, m, done, reason,
            cells={
                'status': {'value': status, 'href': None},
                'last_review': _date_cell(reviewed),
                'kind': {'value': kind or '', 'href': None},
                'action': action,
            },
            sort={'status': status, 'last_review': reviewed or _far_past(),
                  'kind': (kind or '').lower(), 'action': ''},
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
                'action': (_link_cell('Add review', 'add_matter_file_review', m['file_number'])
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

def _aml_id_state(snap, last_check):
    """(done, reason, status, months ago) for a Veriphy AML / ID check date."""
    threshold = snap.today - relativedelta(months=AML_MONTHS)
    if last_check is None:
        return False, 'never', 'Never checked', ''
    if last_check > threshold:
        return True, '', 'Current', str(_months_between(last_check, snap.today))
    return False, 'overdue', 'Overdue', str(_months_between(last_check, snap.today))


def _aml_id_cells(snap, last_check):
    done, reason, status, months = _aml_id_state(snap, last_check)
    cells = {
        'last_check': _date_cell(last_check),
        'months': {'value': months, 'href': None},
        'status': {'value': status, 'href': None},
    }
    sort = {'last_check': last_check or _far_past(), 'months': int(months or 0), 'status': status}
    return done, reason, cells, sort


def collect_aml_id_check(snap):
    items = []
    for client in snap.clients.values():
        done, reason, cells, sort = _aml_id_cells(snap, client['date_of_last_aml'])
        items.append(_client_item(snap, client, done, reason, cells=cells, sort=sort))
    return items


def collect_party_aml_id_check(snap):
    items = []
    for party in snap.parties.values():
        done, reason, cells, sort = _aml_id_cells(snap, party['date_of_last_aml'])
        items.append(_party_item(snap, party, done, reason, cells=cells, sort=sort))
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


def collect_undertakings_discharged(snap):
    rows = Undertaking.objects.filter(
        file_number_id__in=snap.live_ids
    ).values('id', 'file_number_id', 'date_given', 'given_to', 'description', 'date_discharged')
    items = []
    for row in rows:
        m = snap.matters[row['file_number_id']]
        done = row['date_discharged'] is not None
        items.append(_record_item(
            snap, m, row['id'], done, 'outstanding',
            cells={
                'given': _date_cell(row['date_given']),
                'given_to': {'value': row['given_to'] or '', 'href': None},
                'description': {'value': row['description'] or '', 'href': None},
                'discharged': _date_cell(row['date_discharged']),
                'action': _link_cell('Open', 'edit_undertaking', row['id']),
            },
            sort={'given': row['date_given'] or _far_past(),
                  'given_to': (row['given_to'] or '').lower(),
                  'description': (row['description'] or '').lower(),
                  'discharged': row['date_discharged'] or _far_past(), 'action': ''},
        ))
    return items


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------

def _metric(key, label, short_label, group, help, collect, columns, reasons=None, **extra):
    return Metric(key=key, label=label, short_label=short_label, group=group,
                  help=help, collect=collect, columns=columns, reasons=reasons or {}, **extra)


def _signoff_queue_url(kind):
    return lambda: f"{reverse('signoff_queue')}?type={kind}"


ACTION_COLUMN = _col('action', '', sortable=False)
AML_ID_COLUMNS = [_col('last_check', 'Last check'), _col('months', 'Months ago'), _col('status', 'Status')]

METRICS = {m.key: m for m in [
    # -- Matter risk & reviews --------------------------------------------
    _metric(
        'risk_assessment', 'Risk assessment signed off', 'Risk assessment', 'matter_risk',
        'Live matters whose latest risk assessment has been signed off by a fee earner.',
        collect_risk_assessment,
        MATTER_COLUMNS + [_col('status', 'Status'), _col('assessed', 'Assessed'),
                          _col('days_open', 'Days open'), ACTION_COLUMN],
        reasons={'awaiting': 'awaiting sign-off', 'none': 'no assessment'},
        reason_urls={'awaiting': _signoff_queue_url('risk_assessment')},
    ),
    _metric(
        'ongoing_monitoring', 'Ongoing monitoring up to date', 'Ongoing monitoring', 'matter_risk',
        'Live matters whose latest risk review - the initial risk assessment or a later ongoing monitoring '
        'record - is less than a year old and signed off by a fee earner. Monitoring is due at least '
        'annually, or whenever anything changes. Same yearly rule as the "Risk assessments due" report.',
        collect_ongoing_monitoring,
        MATTER_COLUMNS + [_col('status', 'Status'), _col('last_review', 'Last review'),
                          _col('kind', 'Latest record'), ACTION_COLUMN],
        reasons={'awaiting': 'awaiting sign-off', 'overdue': 'review overdue', 'never': 'never done'},
        labels=('done', 'not completed'),
        reason_urls={'awaiting': _signoff_queue_url('ongoing_monitoring')},
    ),
    _metric(
        'file_review_current', 'File review up to date', 'File review', 'matter_risk',
        'Live matters reviewed by a supervisor in the last three months. Same rule as the "File reviews due" report.',
        collect_file_review_current,
        MATTER_COLUMNS + [_col('status', 'Status'), _col('last_review', 'Last review'),
                          _col('reviewed_by', 'Reviewed by'), ACTION_COLUMN],
        reasons={'never': 'never reviewed', 'overdue': 'review overdue'},
    ),
    _metric(
        'high_risk_signed_off', 'High-risk matters signed off', 'High risk', 'matter_risk',
        'Live matters whose latest assessment is high risk (High client or matter risk, Enhanced CDD, PEP or sanctions) and has fee earner sign-off. Enhanced due diligence needs senior approval under the Money Laundering Regulations.',
        collect_high_risk_signed_off,
        MATTER_COLUMNS + [_col('risk', 'Why high risk', truncate=True), _col('status', 'Status'),
                          _col('assessed', 'Assessed'), ACTION_COLUMN],
    ),
    _metric(
        'not_dormant', 'Matters active in the last 3 months', 'Active', 'matter_risk',
        'Live matters with an attendance note, letter, email, completed task, payment slip or invoice in the last three months. Newly opened files always count as active.',
        collect_not_dormant,
        MATTER_COLUMNS + [_col('last_activity', 'Last activity'), _col('kind', 'What'), _col('days', 'Days ago')],
        labels=('active', 'not active'),
    ),
    # -- Client due diligence ---------------------------------------------
    _metric(
        'aml_id_check', 'AML / ID check within 11 months', 'AML / ID check', 'client_dd',
        'Clients on live matters whose last Veriphy AML / ID check (UK business check for a company) is less '
        'than 11 months old. Veriphy verifies identity and screens for AML in one check, so the check date '
        'covers both. Unlike the "AML checks due" export this counts To Be Closed matters and clients who have never been checked.',
        collect_aml_id_check,
        CLIENT_COLUMNS + AML_ID_COLUMNS,
        reasons={'never': 'never checked', 'overdue': 'overdue'},
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
        'party_aml_id_check', 'Third-party AML / ID check within 11 months', 'Third-party AML / ID', 'client_dd',
        'Authorised and paying parties on live matters whose last Veriphy AML / ID check is less than 11 months old.',
        collect_party_aml_id_check,
        PARTY_COLUMNS + AML_ID_COLUMNS,
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
                          _col('discharged', 'Discharged'), ACTION_COLUMN],
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
    ring = donut_segments(done, not_done, labels=tuple(l.capitalize() for l in metric.labels))
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
                    'url': metric.reason_url(key),
                })
    return {
        'key': metric.key,
        'label': metric.label,
        'short_label': metric.short_label,
        'help': metric.help_for(snap),
        'done': done,
        'total': total,
        'not_done': not_done,
        'done_label': metric.labels[0],
        'not_done_label': metric.labels[1],
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
                # "3 outstanding" for most metrics; dormancy says "3 not active".
                'not_done_label': 'outstanding' if metric.labels == Metric.labels else metric.labels[1],
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
                   f' and {len(snap.parties)} third part{"ies" if len(snap.parties) != 1 else "y"} on live matters'),
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
