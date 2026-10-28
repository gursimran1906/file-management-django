"""Complaints register rules: references, the eight-week clock, who may see
and manage a complaint, the SRA annual-return figures and retention.

Regulatory anchors (checked 28 Oct 2026, see plans/complaints-register.md):
- SRA Code of Conduct 8.4 / Legal Ombudsman Scheme Rules 4.1: the complainant
  may go to the ombudsman once eight weeks have passed without resolution.
- Scheme Rules 4.4: the six-month limit for doing so only starts if the final
  response says the ombudsman is available, gives full contact details and
  warns of the six months.
- SRA annual return: complaints received, resolved (complainant satisfied) and
  referred to the ombudsman in the year to 31 August, by category.
- Retention: no rule fixes a period; the firm's choice is COMPLAINT_RETENTION_YEARS.
"""

from datetime import date, timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q

from users.models import CustomUser

from .audit import log_created
from .models import Complaint, ComplaintCategory, ComplaintEvent
from .utils import create_modification

EIGHT_WEEKS = Complaint.EIGHT_WEEKS_DAYS
# Inside this many days of the deadline the clock turns amber.
WARNING_DAYS = 14
# Legal Ombudsman best practice: acknowledge within two working days.
ACKNOWLEDGE_TARGET_WORKING_DAYS = 2
# "Regular updates" (LSB s.112 Requirements para 15): flag silence beyond this.
UPDATE_SILENCE_DAYS = 14


# ---------------------------------------------------------------------------
# References and years
# ---------------------------------------------------------------------------

def next_reference(received_on):
    """``C-2026-0007``: the year the complaint arrived, then a running number
    within that year. Gaps are fine; reuse is not."""
    year = (received_on or date.today()).year
    prefix = f'C-{year}-'
    last = (Complaint.objects.filter(reference__startswith=prefix)
            .order_by('-reference').values_list('reference', flat=True).first())
    n = int(last[len(prefix):]) + 1 if last else 1
    return f'{prefix}{n:04d}'


def reporting_year(when):
    """The SRA annual-return year (1 September to 31 August) that ``when`` falls
    in, labelled by the year it ends in: 15 Oct 2026 -> 2027."""
    return when.year + 1 if when.month >= 9 else when.year


def reporting_year_bounds(year):
    return date(year - 1, 9, 1), date(year, 8, 31)


def destruction_due_on(complaint):
    """Earliest date the complaint file may be destroyed: the retention period
    after it was closed (or the ombudsman decided), nothing while open."""
    anchor = complaint.leo_decision_on or complaint.closed_on
    if not anchor:
        return None
    years = int(getattr(settings, 'COMPLAINT_RETENTION_YEARS', 6))
    try:
        return anchor.replace(year=anchor.year + years)
    except ValueError:  # 29 February
        return anchor.replace(year=anchor.year + years, day=28)


def add_working_days(start, days):
    current = start
    while days > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            days -= 1
    return current


# ---------------------------------------------------------------------------
# The eight-week clock
# ---------------------------------------------------------------------------

def clock(complaint, today=None):
    """Where the complaint sits on its eight-week clock.

    Returns a dict the templates draw as the timeline bar:
    ``day`` (1 on the day received), ``days_left`` (negative when overdue),
    ``pct`` (0-100 of the eight weeks used), ``state`` one of ``ok``,
    ``warning`` (inside WARNING_DAYS of the deadline), ``overdue`` and
    ``stopped`` (final response sent or closed), plus ``stopped_on``,
    ``deadline`` and ``met`` (whether the response landed inside eight weeks).
    """
    today = today or date.today()
    stopped_on = complaint.clock_stopped_on
    end = stopped_on or today
    elapsed = (end - complaint.received_on).days
    deadline = complaint.eight_week_deadline
    days_left = (deadline - end).days
    pct = max(0, min(100, round(elapsed / EIGHT_WEEKS * 100)))
    if stopped_on:
        state = 'stopped'
    elif days_left < 0:
        state = 'overdue'
    elif days_left <= WARNING_DAYS:
        state = 'warning'
    else:
        state = 'ok'
    return {
        'day': elapsed + 1,
        'total': EIGHT_WEEKS,
        'days_left': days_left,
        'days_over': max(0, -days_left),
        'pct': pct,
        'state': state,
        'stopped_on': stopped_on,
        'deadline': deadline,
        'met': stopped_on is not None and stopped_on <= deadline,
    }


def attention(complaint, today=None):
    """Short reasons this complaint needs someone's attention today, in the
    order they should be dealt with. Empty when nothing is due."""
    today = today or date.today()
    reasons = []
    if not complaint.is_open:
        return reasons
    c = clock(complaint, today)
    if c['state'] == 'overdue':
        reasons.append(f"{-c['days_left']} day{'s' if c['days_left'] != -1 else ''} past the eight-week deadline")
    elif c['state'] == 'warning':
        reasons.append(f"{c['days_left']} day{'s' if c['days_left'] != 1 else ''} to the eight-week deadline")
    if not complaint.acknowledged_on and today > add_working_days(
            complaint.received_on, ACKNOWLEDGE_TARGET_WORKING_DAYS):
        reasons.append('Not yet acknowledged')
    if complaint.status in Complaint.CLOCK_RUNNING_STATUSES and complaint.acknowledged_on:
        last = complaint.last_update_sent_on or complaint.acknowledged_on
        if (today - last).days > UPDATE_SILENCE_DAYS:
            reasons.append(f'No update sent for {(today - last).days} days')
    if complaint.final_response_sent_on and not complaint.final_response_complete:
        reasons.append('Final response is missing ombudsman wording')
    if complaint.potential_claim and not complaint.pii_notified_on:
        reasons.append('Insurer not yet notified')
    return reasons


# ---------------------------------------------------------------------------
# Who sees and who manages
# ---------------------------------------------------------------------------

def complaints_officer_code():
    return (getattr(settings, 'COMPLAINTS_OFFICER', '') or '').strip().upper()


def complaints_officer():
    code = complaints_officer_code()
    return CustomUser.objects.filter(username__iexact=code).first() if code else None


def is_complaints_officer(user):
    code = complaints_officer_code()
    return bool(code) and (user.username or '').upper() == code


def can_see_all(user):
    """Managers and the designated complaints officer see the whole register."""
    return bool(user.is_manager or user.is_superuser or is_complaints_officer(user))


def visible_complaints(user):
    """Everything for managers and the complaints officer; otherwise the
    complaints a member of staff logged, handles, or is the subject of, plus
    those on files they are the fee earner for."""
    qs = Complaint.objects.all()
    if can_see_all(user):
        return qs
    return qs.filter(
        Q(created_by=user) | Q(received_by=user) | Q(handled_by=user)
        | Q(about_fee_earner=user) | Q(matters__fee_earner=user)
    ).distinct()


def can_manage(user, complaint):
    """Who may investigate, record the outcome and close: the handler, managers
    and the complaints officer. The fee earner complained about may read and
    add to the chronology but not decide."""
    return can_see_all(user) or complaint.handled_by_id == user.id


# ---------------------------------------------------------------------------
# Mutations with their audit rows
# ---------------------------------------------------------------------------

def record_event(complaint, user, kind, occurred_on=None, note='', **links):
    event = ComplaintEvent.objects.create(
        complaint=complaint, kind=kind, occurred_on=occurred_on or date.today(),
        by=user, note=note or '', **links)
    create_modification(user, complaint, {
        'event': {'old_value': '', 'new_value': f'{event.get_kind_display()} ({event.occurred_on:%d/%m/%Y})'}})
    return event


def create_complaint(user, form, matters=None):
    """Save a new complaint from its form, give it a reference, link matters
    and write the opening chronology entry."""
    with transaction.atomic():
        complaint = form.save(commit=False)
        complaint.created_by = user
        if not complaint.received_by_id:
            complaint.received_by = user
        if not complaint.handled_by_id:
            complaint.handled_by = complaints_officer()
        for _attempt in range(5):
            try:
                with transaction.atomic():
                    complaint.save()
                break
            except IntegrityError:
                complaint.reference = ''
        else:
            raise
        form.save_m2m()
        if matters is not None:
            complaint.matters.set(matters)
        log_created(user, complaint, f'Complaint {complaint.reference} logged')
        record_event(complaint, user, 'received', complaint.received_on,
                     f'Received by {complaint.get_received_via_display().lower()}.')
    return complaint


def set_milestone(complaint, user, action, when=None, note=''):
    """Move a complaint along: acknowledge, timeline, update, final response,
    resolve, close, escalate, reopen. Returns the message to show.

    Each action records the date, moves the status where that follows, writes
    a chronology entry and an audit row. Dates default to today.
    """
    when = when or date.today()
    old_status = complaint.status
    changes = {}
    fields = []

    def set_date(field):
        old = getattr(complaint, field)
        setattr(complaint, field, when)
        changes[field] = {'old_value': old.isoformat() if old else '', 'new_value': when.isoformat()}
        fields.append(field)

    if action == 'acknowledge':
        set_date('acknowledged_on')
        if complaint.status == Complaint.STATUS_RECEIVED:
            complaint.status = Complaint.STATUS_ACKNOWLEDGED
        kind, message = 'acknowledged', 'Acknowledgement recorded.'
    elif action == 'procedure_sent':
        set_date('complaints_procedure_sent_on')
        kind, message = 'update', 'Complaints procedure sent.'
    elif action == 'timeline':
        set_date('timeline_given_on')
        kind, message = 'update', 'Timeline for resolution recorded.'
    elif action == 'update_sent':
        set_date('last_update_sent_on')
        kind, message = 'update', 'Progress update recorded.'
    elif action == 'signposted':
        set_date('leo_signposted_on')
        kind, message = 'update', 'Legal Ombudsman signposting recorded.'
    elif action == 'investigating':
        complaint.status = Complaint.STATUS_INVESTIGATING
        kind, message = 'investigation', 'Investigation started.'
    elif action == 'final_response':
        set_date('final_response_sent_on')
        if complaint.status in Complaint.CLOCK_RUNNING_STATUSES:
            complaint.status = Complaint.STATUS_FINAL_RESPONSE
        kind, message = 'final_response', 'Final response recorded.'
    elif action == 'resolve':
        set_date('closed_on')
        complaint.status = Complaint.STATUS_RESOLVED
        complaint.closed_by = user
        fields.append('closed_by')
        kind, message = 'closed', 'Complaint closed as resolved.'
    elif action == 'close':
        set_date('closed_on')
        complaint.status = Complaint.STATUS_CLOSED_UNRESOLVED
        complaint.closed_by = user
        fields.append('closed_by')
        kind, message = 'closed', 'Complaint closed.'
    elif action == 'escalate_leo':
        set_date('leo_referred_on')
        complaint.status = Complaint.STATUS_ESCALATED_LEO
        kind, message = 'leo', 'Referred to the Legal Ombudsman.'
    elif action == 'escalate_sra':
        set_date('sra_reported_on')
        complaint.status = Complaint.STATUS_ESCALATED_SRA
        kind, message = 'sra', 'Reported to the SRA.'
    elif action == 'pii_notified':
        set_date('pii_notified_on')
        complaint.potential_claim = True
        fields.append('potential_claim')
        kind, message = 'pii', 'Insurer notified.'
    elif action == 'reopen':
        complaint.status = Complaint.STATUS_INVESTIGATING
        complaint.closed_on = None
        complaint.closed_by = None
        fields += ['closed_on', 'closed_by']
        kind, message = 'reopened', 'Complaint reopened.'
    else:
        raise ValueError(f'Unknown complaint action {action!r}')

    if complaint.status != old_status:
        changes['status'] = {'old_value': dict(Complaint.STATUS_CHOICES)[old_status],
                             'new_value': complaint.get_status_display()}
        fields.append('status')
    complaint.save(update_fields=list(dict.fromkeys(fields + ['updated_at'])))
    create_modification(user, complaint, changes or {'action': {'old_value': '', 'new_value': message}})
    record_event(complaint, user, kind, when, note)
    return message


def tag_correspondence(complaint, user, record, tag=True):
    """Mark a matter email / letter / attendance note as part of the complaint
    file (or untag it). Returns True when something changed."""
    if (record.complaint_id == complaint.id) == tag:
        return False
    record.complaint = complaint if tag else None
    record.save(update_fields=['complaint'])
    label = type(record).__name__.replace('Matter', '').rstrip('s').lower()
    create_modification(user, complaint, {
        'correspondence': {'old_value': '' if tag else f'{label} #{record.id}',
                           'new_value': f'{label} #{record.id}' if tag else ''}})
    return True


# ---------------------------------------------------------------------------
# Figures for the dashboard cards and the annual return
# ---------------------------------------------------------------------------

def summary(user=None, today=None):
    """Counts for the dashboard / management card: what is open, what is near
    or past the deadline, what awaits closing after the final response."""
    today = today or date.today()
    qs = (visible_complaints(user) if user else Complaint.objects.all())
    open_qs = list(qs.filter(status__in=Complaint.OPEN_STATUSES).prefetch_related('matters'))
    rows = []
    for c in open_qs:
        rows.append({'complaint': c, 'clock': clock(c, today), 'attention': attention(c, today)})
    overdue = [r for r in rows if r['clock']['state'] == 'overdue']
    warning = [r for r in rows if r['clock']['state'] == 'warning']
    rows.sort(key=lambda r: (
        {'overdue': 0, 'warning': 1, 'ok': 2, 'stopped': 3}[r['clock']['state']],
        r['clock']['days_left']))
    return {
        'rows': rows,
        'open': len(rows),
        'overdue': len(overdue),
        'warning': len(warning),
        'needs_attention': sum(1 for r in rows if r['attention']),
    }


def annual_return(year):
    """The SRA renewal figures for one reporting year (1 Sep - 31 Aug).

    received: complaints received in the year (informal ones excluded, as the
    return asks about formal complaints); resolved: of those, closed with the
    complainant satisfied; referred: referred to the Legal Ombudsman in the
    year, whether or not they were later resolved. Per category the same three.
    """
    start, end = reporting_year_bounds(year)
    received = list(Complaint.objects.filter(
        received_on__range=(start, end), is_informal=False).prefetch_related('categories'))
    referred = list(Complaint.objects.filter(
        leo_referred_on__range=(start, end)).prefetch_related('categories'))
    resolved = [c for c in received if c.status == Complaint.STATUS_RESOLVED]
    closed = [c for c in received if c.is_closed]

    by_category = {}
    for name in ComplaintCategory.objects.values_list('name', flat=True):
        by_category[name] = {'received': 0, 'resolved': 0, 'referred': 0}
    by_category.setdefault('Uncategorised', {'received': 0, 'resolved': 0, 'referred': 0})

    def bump(complaint, key):
        names = [c.name for c in complaint.categories.all()] or ['Uncategorised']
        for name in names:
            by_category.setdefault(name, {'received': 0, 'resolved': 0, 'referred': 0})[key] += 1

    for c in received:
        bump(c, 'received')
    for c in resolved:
        bump(c, 'resolved')
    for c in referred:
        bump(c, 'referred')

    response_days = [(c.final_response_sent_on - c.received_on).days
                     for c in received if c.final_response_sent_on]
    within_eight_weeks = sum(1 for d in response_days if d <= EIGHT_WEEKS)
    redress_total = sum((c.redress_amount or 0) for c in received)
    upheld = sum(1 for c in received if c.outcome in ('upheld', 'partially_upheld'))

    return {
        'year': year, 'start': start, 'end': end,
        'received': len(received), 'resolved': len(resolved), 'closed': len(closed),
        'referred': len(referred), 'open': len(received) - len(closed),
        'upheld': upheld,
        'responded': len(response_days),
        'within_eight_weeks': within_eight_weeks,
        'average_response_days': (round(sum(response_days) / len(response_days))
                                  if response_days else None),
        'redress_total': redress_total,
        'potential_claims': sum(1 for c in received if c.potential_claim),
        'by_category': [{'name': k, **v} for k, v in by_category.items()
                        if any(v.values()) or k != 'Uncategorised'],
        'complaints': received,
    }


def available_years():
    """Reporting years that have any complaint, newest first, plus this one."""
    years = {reporting_year(date.today())}
    for received_on in Complaint.objects.values_list('received_on', flat=True):
        years.add(reporting_year(received_on))
    return sorted(years, reverse=True)
