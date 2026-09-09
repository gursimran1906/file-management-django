"""Per-employee timeline of recorded work.

Builds the data behind the "My time" / "Staff timeline" panel: everything a
member of staff has recorded against matters for a day, a working week or a
month, normalised into one list of events and laid out on a time grid.

Sources and how they are attributed to a person:

* attendance notes  - ``MatterAttendanceNotes.person_attended``
* emails            - ``MatterEmails.fee_earner`` (sent and received)
* letters           - ``MatterLetters.person_attended`` (untimed)
* free-30 meetings  - ``Free30Mins.fee_earner`` (always non-chargeable)
* completed tasks   - ``LastWork.person`` (untimed markers, no time value)

Time basis: totals use **billing units × 6 minutes** so the figures reconcile
with the schedule of work and costs (notes use their ``unit`` field, emails
their ``units``, letters count as one unit, meetings ``ceil(minutes / 6)``).
Grid positions use the real start/finish span where one exists.

All event ``start``/``end`` values are *naive* Europe/London wall-clock
datetimes so that lane and grid maths never mixes aware and naive values.
"""

import calendar
import json
import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from html import unescape
from urllib.parse import urlencode

import holidays
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.html import strip_tags

from users.models import AttendanceRecord, HolidayRecord, SicknessRecord

from .models import (
    Free30Mins,
    LastWork,
    MatterAttendanceNotes,
    MatterEmails,
    MatterLetters,
)

UNIT_MINUTES = 6
TARGET_MINUTES_PER_DAY = 450  # 7.5h - the firm's existing convention
DAY_MINUTES = 24 * 60

VIEWS = ('day', 'week', 'month')
VIEW_LABELS = {'day': 'Day', 'week': 'Work week', 'month': 'Month'}

KINDS = ('note', 'email', 'letter', 'meeting', 'task')
KIND_META = {
    'note': {'label': 'Attendance note', 'plural': 'notes', 'timed': True},
    'email': {'label': 'Email', 'plural': 'emails', 'timed': True},
    'letter': {'label': 'Letter', 'plural': 'letters', 'timed': False},
    'meeting': {'label': 'Free 30 mins', 'plural': 'meetings', 'timed': True},
    'task': {'label': 'Completed task', 'plural': 'tasks', 'timed': False},
}

GRID_START_MIN = 7 * 60
GRID_END_MIN = 19 * 60
MIN_BLOCK_MINUTES = 20  # visual floor so a one-unit entry is still clickable


# ---------------------------------------------------------------------------
# Request parameters
# ---------------------------------------------------------------------------

def parse_view(value):
    return value if value in VIEWS else 'week'


def parse_anchor(value):
    if value:
        try:
            parsed = parse_date(str(value))
        except ValueError:
            parsed = None
        if parsed:
            return parsed
    return timezone.localdate()


def parse_kinds(values):
    """Canonically ordered subset of KINDS; anything empty/invalid means all."""
    wanted = set(values or [])
    selected = [kind for kind in KINDS if kind in wanted]
    return selected or list(KINDS)


def parse_timeline_params(params):
    """(view, anchor, kinds) from a QueryDict (or plain dict) of ``tl_*`` params."""
    if hasattr(params, 'getlist'):
        raw_kinds = params.getlist('tl_types')
    else:
        raw_kinds = params.get('tl_types') or []
        if isinstance(raw_kinds, str):
            raw_kinds = [raw_kinds]
    return (
        parse_view(params.get('tl_view')),
        parse_anchor(params.get('tl_date')),
        parse_kinds(raw_kinds),
    )


# ---------------------------------------------------------------------------
# Date ranges
# ---------------------------------------------------------------------------

def _span_label(start, end):
    if start == end:
        return start.strftime('%-d %b %Y')
    if start.year != end.year:
        return f"{start.strftime('%-d %b %Y')} – {end.strftime('%-d %b %Y')}"
    if start.month != end.month:
        return f"{start.strftime('%-d %b')} – {end.strftime('%-d %b %Y')}"
    return f"{start.strftime('%-d')} – {end.strftime('%-d %b %Y')}"


def resolve_range(view, anchor):
    """Visible range plus the (padded) range to query, and prev/next anchors."""
    if view == 'day':
        return {
            'view': view, 'anchor': anchor,
            'start': anchor, 'end': anchor,
            'grid_start': anchor, 'grid_end': anchor,
            'prev_anchor': anchor - timedelta(days=1),
            'next_anchor': anchor + timedelta(days=1),
            'label': anchor.strftime('%A %-d %B %Y'),
        }
    if view == 'week':
        start = anchor - timedelta(days=anchor.weekday())
        end = start + timedelta(days=6)  # weekend fetched so it can be shown if used
        return {
            'view': view, 'anchor': anchor,
            'start': start, 'end': end,
            'grid_start': start, 'grid_end': end,
            'prev_anchor': start - timedelta(days=7),
            'next_anchor': start + timedelta(days=7),
            'label': _span_label(start, start + timedelta(days=4)),
        }
    start = anchor.replace(day=1)
    end = start.replace(day=calendar.monthrange(start.year, start.month)[1])
    return {
        'view': 'month', 'anchor': anchor,
        'start': start, 'end': end,
        'grid_start': start - timedelta(days=start.weekday()),
        'grid_end': end + timedelta(days=6 - end.weekday()),
        'prev_anchor': (start - timedelta(days=1)).replace(day=1),
        'next_anchor': end + timedelta(days=1),
        'label': start.strftime('%B %Y'),
    }


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_minutes(minutes):
    hours, mins = divmod(max(0, int(minutes or 0)), 60)
    return f'{hours}:{mins:02d}'


def format_units(units):
    if units is None:
        return ''
    return f'{units} unit' if units == 1 else f'{units} units'


def _matter_bits(matter):
    if matter is None:
        return '', '', None
    file_number = matter.file_number or ''
    try:
        client_names = matter.all_client_names or ''
    except Exception:  # pragma: no cover - defensive against odd client rows
        client_names = ''
    href = reverse('home', args=[file_number]) if file_number else None
    return file_number, client_names, href


def _quill_plain(field, limit=200):
    try:
        html = field.html
    except Exception:
        return ''
    text = ' '.join(unescape(strip_tags(html or '')).split())
    if len(text) > limit:
        return text[:limit].rstrip() + '…'
    return text


def _decode_json_field(value):
    """MatterEmails stores a JSON string inside a JSONField; tolerate both."""
    for _ in range(2):
        if value is None or isinstance(value, (dict, list)):
            return value
        if not isinstance(value, (str, bytes)):
            return None
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return None
    return value if isinstance(value, (dict, list)) else None


def _email_party(email):
    raw = _decode_json_field(email.receiver if email.is_sent else email.sender)
    if isinstance(raw, list):
        raw = raw[0] if raw else None
    if not isinstance(raw, dict):
        return ''
    address = raw.get('emailAddress')
    if not isinstance(address, dict):
        address = raw
    return str(address.get('name') or address.get('address') or '')


def _span_minutes(day, start_time, finish_time):
    if start_time is None or finish_time is None:
        return 0
    delta = datetime.combine(day, finish_time) - datetime.combine(day, start_time)
    return int(delta.total_seconds() // 60)


def _clamp_end(start, minutes):
    """start + minutes, never past 23:59 of the same day."""
    end = start + timedelta(minutes=max(1, minutes))
    day_end = datetime.combine(start.date(), datetime.max.time()).replace(microsecond=0)
    return min(end, day_end)


def make_event(*, kind, id, date, start=None, end=None, untimed=False, minutes=0,
               units=None, is_charged=None, title='', matter=None, direction=None,
               href=None, edit_href=None, detail='', suspect=False):
    file_number, client_names, matter_href = _matter_bits(matter)
    if untimed or start is None:
        time_label = ''
    elif kind in ('note', 'meeting') and end is not None:
        time_label = f"{start:%H:%M}–{end:%H:%M}"
    else:
        time_label = f"{start:%H:%M}"
    if kind == 'note':
        css = 'tl-ev-note' if is_charged else 'tl-ev-note-nc'
    elif kind == 'email':
        css = 'tl-ev-email'
    elif kind == 'meeting':
        css = 'tl-ev-meeting'
    elif kind == 'letter':
        css = 'tl-chip-letter'
    else:
        css = 'tl-chip-task'
    if is_charged is None:
        charge_label = ''
    else:
        charge_label = 'Chargeable' if is_charged else 'Non-chargeable'
    return {
        'kind': kind,
        'kind_label': KIND_META[kind]['label'],
        'id': id,
        'dom_id': f'tl-{kind}-{id}',
        'date': date,
        'start': start,
        'end': end,
        'untimed': untimed,
        'minutes': int(minutes or 0),
        'units': units,
        'is_charged': is_charged,
        'charge_label': charge_label,
        'title': title or '',
        'matter': matter,
        'file_number': file_number,
        'client_names': client_names,
        'matter_href': matter_href,
        'direction': direction,
        'direction_label': {'sent': 'Sent', 'received': 'Received'}.get(direction, ''),
        'href': href,
        'edit_href': edit_href,
        'detail': detail or '',
        'time_label': time_label,
        'duration_label': format_minutes(minutes) if minutes else '',
        'units_label': format_units(units),
        'suspect': suspect,
        'css': css,
    }


# ---------------------------------------------------------------------------
# Collectors
# ---------------------------------------------------------------------------

def _with_matter(queryset):
    return queryset.select_related('file_number', 'file_number__client1').prefetch_related(
        'file_number__additional_clients')


def _collect_notes(user, start, end):
    events = []
    notes = _with_matter(MatterAttendanceNotes.objects.filter(
        person_attended=user, date__range=(start, end)))
    for note in notes:
        span = _span_minutes(note.date, note.start_time, note.finish_time)
        if note.unit is not None:
            units = max(0, int(note.unit))
        else:
            units = max(1, math.ceil(max(span, 0) / UNIT_MINUTES))
        minutes = units * UNIT_MINUTES
        if note.start_time is None:
            started = datetime.combine(note.date, datetime.min.time().replace(hour=9))
        else:
            started = datetime.combine(note.date, note.start_time)
        suspect = False
        if note.finish_time is not None and span > 0:
            ended = datetime.combine(note.date, note.finish_time)
        else:
            ended = _clamp_end(started, minutes or UNIT_MINUTES)
            suspect = note.finish_time is not None
        file_number = note.file_number.file_number if note.file_number else ''
        events.append(make_event(
            kind='note', id=note.id, date=note.date, start=started, end=ended,
            minutes=minutes, units=units, is_charged=bool(note.is_charged),
            title=note.subject_line or 'Attendance note', matter=note.file_number,
            href=reverse('attendance_note_view', args=[file_number]) if file_number else None,
            edit_href=reverse('edit_attendance_note', args=[note.id]),
            detail=_quill_plain(note.content), suspect=suspect,
        ))
    return events


def _collect_emails(user, start, end):
    events = []
    emails = _with_matter(MatterEmails.objects.filter(
        fee_earner=user, time__isnull=False, time__date__range=(start, end)))
    for email in emails:
        local = timezone.localtime(email.time).replace(tzinfo=None, second=0, microsecond=0)
        units = max(0, int(email.units or 0))
        minutes = units * UNIT_MINUTES
        sent = bool(email.is_sent)
        file_number = email.file_number.file_number if email.file_number else ''
        if file_number:
            matter_page = reverse('correspondence_view', args=[file_number])
        else:
            matter_page = reverse('unallocated_emails')
        party = _email_party(email)
        detail = f"{'To' if sent else 'From'}: {party}" if party else ''
        events.append(make_event(
            kind='email', id=email.id, date=local.date(), start=local,
            end=_clamp_end(local, minutes or UNIT_MINUTES), minutes=minutes, units=units,
            is_charged=True, title=(email.subject or '').strip() or '(No subject)',
            matter=email.file_number, direction='sent' if sent else 'received',
            href=email.link or matter_page, edit_href=matter_page, detail=detail,
        ))
    return events


def _collect_letters(user, start, end):
    events = []
    letters = _with_matter(MatterLetters.objects.filter(
        person_attended=user, date__range=(start, end)))
    for letter in letters:
        sent = letter.sent if letter.sent is not None else True
        charged = letter.is_charged if letter.is_charged is not None else True
        file_number = letter.file_number.file_number if letter.file_number else ''
        party = (letter.to_or_from or '').strip()
        events.append(make_event(
            kind='letter', id=letter.id, date=letter.date, untimed=True,
            minutes=UNIT_MINUTES, units=1, is_charged=bool(charged),
            title=letter.subject_line or 'Letter', matter=letter.file_number,
            direction='sent' if sent else 'received',
            href=reverse('correspondence_view', args=[file_number]) if file_number else None,
            edit_href=reverse('edit_letter', args=[letter.id]),
            detail=f"{'To' if sent else 'From'} {party}" if party else '',
        ))
    return events


def _collect_meetings(user, start, end):
    events = []
    meetings = Free30Mins.objects.filter(
        fee_earner=user, date__range=(start, end),
    ).select_related('matter_type').prefetch_related('attendees')
    for meeting in meetings:
        span = _span_minutes(meeting.date, meeting.start_time, meeting.finish_time)
        if span <= 0:
            span = 30
        units = max(1, math.ceil(span / UNIT_MINUTES))
        started = datetime.combine(meeting.date, meeting.start_time)
        ended = datetime.combine(meeting.date, meeting.finish_time)
        if ended <= started:
            ended = _clamp_end(started, span)
        names = ', '.join(a.name for a in meeting.attendees.all() if a.name)
        matter_type = meeting.matter_type.type if meeting.matter_type else ''
        title = 'Free 30 mins'
        if names:
            title = f'{title} – {names}'
        elif matter_type:
            title = f'{title} – {matter_type}'
        events.append(make_event(
            kind='meeting', id=meeting.id, date=meeting.date, start=started, end=ended,
            minutes=units * UNIT_MINUTES, units=units, is_charged=False, title=title,
            href=reverse('free30mins'),
            edit_href=reverse('edit_free30mins', args=[meeting.id]),
            detail=_quill_plain(meeting.notes) or matter_type,
        ))
    return events


def _collect_tasks(user, start, end):
    events = []
    tasks = _with_matter(LastWork.objects.filter(person=user).filter(
        Q(date__range=(start, end))
        | Q(date__isnull=True, timestamp__date__range=(start, end))))
    for task in tasks:
        day = task.date or timezone.localdate(task.timestamp)
        file_number = task.file_number.file_number if task.file_number else ''
        text = ' '.join((task.task or '').split())
        events.append(make_event(
            kind='task', id=task.id, date=day, untimed=True, minutes=0, units=None,
            is_charged=None, title=text[:120] or 'Completed task', matter=task.file_number,
            href=reverse('home', args=[file_number]) if file_number else None,
            edit_href=reverse('edit_last_work', args=[task.id]),
            detail=text if len(text) > 120 else '',
        ))
    return events


COLLECTORS = {
    'note': _collect_notes,
    'email': _collect_emails,
    'letter': _collect_letters,
    'meeting': _collect_meetings,
    'task': _collect_tasks,
}


def collect_events(user, start, end, kinds=KINDS):
    events = []
    for kind in KINDS:
        if kind in kinds:
            events.extend(COLLECTORS[kind](user, start, end))
    events.sort(key=lambda ev: (
        ev['date'],
        0 if ev['untimed'] else 1,
        ev['start'] or datetime.combine(ev['date'], datetime.min.time()),
        -ev['minutes'],
    ))
    return events


# ---------------------------------------------------------------------------
# Grid layout
# ---------------------------------------------------------------------------

def _minutes_of_day(value):
    return value.hour * 60 + value.minute


def _event_span(event):
    """(start_min, end_min) used for layout; the end is floored to MIN_BLOCK."""
    start_min = _minutes_of_day(event['start'])
    if event['end'] is None:
        end_min = start_min
    elif event['end'].date() > event['start'].date():
        end_min = DAY_MINUTES
    else:
        end_min = _minutes_of_day(event['end'])
    end_min = min(DAY_MINUTES, max(end_min, start_min + MIN_BLOCK_MINUTES))
    return start_min, end_min


def grid_bounds(timed_events):
    """Hour-aligned grid window: 07:00–19:00, widened to fit any outliers."""
    grid_start, grid_end = GRID_START_MIN, GRID_END_MIN
    for event in timed_events:
        start_min, end_min = _event_span(event)
        grid_start = min(grid_start, (start_min // 60) * 60)
        grid_end = max(grid_end, min(DAY_MINUTES, math.ceil(end_min / 60) * 60))
    return grid_start, grid_end


def assign_lanes(timed_events):
    """Place overlapping events side by side (mutates the event dicts)."""
    ordered = sorted(timed_events, key=lambda ev: (
        _event_span(ev)[0], -(_event_span(ev)[1] - _event_span(ev)[0])))
    cluster, lane_ends = [], []

    def close_cluster():
        lanes = len(lane_ends) or 1
        for ev in cluster:
            ev['lanes'] = lanes
            ev['left_pct'] = round(ev['lane'] * 100 / lanes, 3)
            ev['width_pct'] = round(100 / lanes, 3)
        cluster.clear()
        lane_ends.clear()

    for event in ordered:
        start_min, end_min = _event_span(event)
        if lane_ends and start_min >= max(lane_ends):
            close_cluster()
        for index, lane_end in enumerate(lane_ends):
            if lane_end <= start_min:
                lane_ends[index] = end_min
                event['lane'] = index
                break
        else:
            lane_ends.append(end_min)
            event['lane'] = len(lane_ends) - 1
        cluster.append(event)
    close_cluster()


def position_events(timed_events, grid_start, grid_end):
    span = max(1, grid_end - grid_start)
    for event in timed_events:
        start_min, end_min = _event_span(event)
        start_min = min(max(start_min, grid_start), grid_end - 1)
        end_min = max(min(end_min, grid_end), start_min + 1)
        event['top_pct'] = round((start_min - grid_start) / span * 100, 3)
        event['height_pct'] = round((end_min - start_min) / span * 100, 3)


def axis_hours(grid_start, grid_end):
    return [f'{hour:02d}:00' for hour in range(grid_start // 60, grid_end // 60 + 1)]


# ---------------------------------------------------------------------------
# Totals
# ---------------------------------------------------------------------------

def _empty_totals():
    return {
        'recorded_minutes': 0,
        'chargeable_minutes': 0,
        'non_chargeable_minutes': 0,
        'units_chargeable': 0,
        'units_non_chargeable': 0,
        'counts': {kind: 0 for kind in KINDS},
    }


def _label_totals(totals):
    totals['recorded_label'] = format_minutes(totals['recorded_minutes'])
    totals['chargeable_label'] = format_minutes(totals['chargeable_minutes'])
    totals['non_chargeable_label'] = format_minutes(totals['non_chargeable_minutes'])
    totals['units_total'] = totals['units_chargeable'] + totals['units_non_chargeable']
    totals['units_total_label'] = format_units(totals['units_total'])
    totals['units_chargeable_label'] = format_units(totals['units_chargeable'])
    totals['units_non_chargeable_label'] = format_units(totals['units_non_chargeable'])
    totals['count_items'] = [
        {'kind': kind, 'count': totals['counts'][kind],
         'label': KIND_META[kind]['plural'] if totals['counts'][kind] != 1
         else KIND_META[kind]['plural'][:-1]}
        for kind in KINDS if totals['counts'][kind]
    ]
    totals['counts_sentence'] = ' · '.join(
        f"{item['count']} {item['label']}" for item in totals['count_items'])
    totals['has_time'] = totals['recorded_minutes'] > 0
    chargeable_bar = min(100, round(totals['chargeable_minutes'] / TARGET_MINUTES_PER_DAY * 100))
    totals['chargeable_bar_pct'] = chargeable_bar
    totals['non_chargeable_bar_pct'] = min(
        100 - chargeable_bar,
        round(totals['non_chargeable_minutes'] / TARGET_MINUTES_PER_DAY * 100))
    totals['total_items'] = sum(totals['counts'].values())
    return totals


def summarise(events):
    totals = _empty_totals()
    for event in events:
        totals['counts'][event['kind']] += 1
        if event['is_charged'] is None:
            continue
        units = event['units'] or 0
        totals['recorded_minutes'] += event['minutes']
        if event['is_charged']:
            totals['chargeable_minutes'] += event['minutes']
            totals['units_chargeable'] += units
        else:
            totals['non_chargeable_minutes'] += event['minutes']
            totals['units_non_chargeable'] += units
    return _label_totals(totals)


def range_totals(day_totals, working_days, hourly_rate=None):
    totals = _empty_totals()
    for day in day_totals:
        for key in ('recorded_minutes', 'chargeable_minutes', 'non_chargeable_minutes',
                    'units_chargeable', 'units_non_chargeable'):
            totals[key] += day[key]
        for kind in KINDS:
            totals['counts'][kind] += day['counts'][kind]
    _label_totals(totals)
    totals['working_days'] = working_days
    totals['target_minutes'] = TARGET_MINUTES_PER_DAY * working_days
    totals['target_label'] = format_minutes(totals['target_minutes'])
    if totals['target_minutes']:
        totals['progress_pct'] = min(
            100, round(totals['recorded_minutes'] / totals['target_minutes'] * 100))
    else:
        totals['progress_pct'] = 0
    if totals['recorded_minutes']:
        totals['chargeable_pct'] = round(
            totals['chargeable_minutes'] / totals['recorded_minutes'] * 100)
    else:
        totals['chargeable_pct'] = 0
    hourly_amount = getattr(hourly_rate, 'hourly_amount', None)
    if hourly_amount is not None:
        value = (Decimal(totals['units_chargeable']) * Decimal(hourly_amount) / Decimal(10))
        totals['value'] = value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        totals['value_label'] = f"£{totals['value']:,.2f}"
    else:
        totals['value'] = None
        totals['value_label'] = ''
    return totals


# ---------------------------------------------------------------------------
# Working-day context (holidays, sickness, clock-in)
# ---------------------------------------------------------------------------

def _local_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return timezone.localtime(value).date() if timezone.is_aware(value) else value.date()
    return value


def _local_naive(value):
    if value is None:
        return None
    if timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.replace(tzinfo=None)


def _holiday_label(record):
    if (record.reason or '').strip().lower() == 'office closure':
        return 'Office closure'
    if record.type == 'Unpaid':
        return 'Unpaid leave'
    return 'Holiday'


def working_day_contexts(user, start, end):
    """Per-date flags and clock times for every day in [start, end]."""
    days = [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
    bank_holidays = holidays.country_holidays(
        'GB', subdiv='ENG', years={start.year, end.year})
    holiday_records = list(HolidayRecord.objects.filter(
        employee=user, approved=True,
        start_date__date__lte=end, end_date__date__gte=start))
    sickness_records = list(SicknessRecord.objects.filter(
        employee=user, start_date__date__lte=end,
    ).filter(Q(end_date__isnull=True) | Q(end_date__date__gte=start)))
    attendance = {}
    for record in AttendanceRecord.objects.filter(
            employee=user, date__range=(start, end)).order_by('clock_in'):
        attendance.setdefault(record.date, record)

    contexts = {}
    for day in days:
        context = {
            'is_weekend': day.weekday() >= 5,
            'bank_holiday': bank_holidays.get(day),
            'on_holiday': False,
            'holiday_label': '',
            'off_sick': False,
            'clock_in': None,
            'clock_out': None,
            'lunch_out': None,
            'lunch_in': None,
        }
        for record in holiday_records:
            if _local_date(record.start_date) <= day <= _local_date(record.end_date):
                context['on_holiday'] = True
                context['holiday_label'] = _holiday_label(record)
                break
        for record in sickness_records:
            started = _local_date(record.start_date)
            ended = _local_date(record.end_date)
            if started <= day and (ended is None or day <= ended):
                context['off_sick'] = True
                break
        record = attendance.get(day)
        if record is not None:
            context['clock_in'] = _local_naive(record.clock_in)
            context['clock_out'] = _local_naive(record.clock_out)
            context['lunch_out'] = _local_naive(record.lunch_out)
            context['lunch_in'] = _local_naive(record.lunch_in)
        context['is_working_day'] = not (
            context['is_weekend'] or context['bank_holiday']
            or context['on_holiday'] or context['off_sick'])
        contexts[day] = context
    return contexts


def working_day_context(user, day):
    return working_day_contexts(user, day, day)[day]


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

def timeline_query(view, anchor, *, user_id=None, kinds=None):
    params = [('tl_view', view), ('tl_date', anchor.isoformat())]
    if user_id is not None:
        params.append(('tl_user', str(user_id)))
    if kinds is not None and set(kinds) != set(KINDS):
        params.extend(('tl_types', kind) for kind in KINDS if kind in kinds)
    return urlencode(params)


def build_nav(view, anchor, rng, *, user_id=None, kinds=None, today=None):
    today = today or timezone.localdate()
    kinds = list(kinds or KINDS)

    def query(target_view, target_anchor, target_kinds=kinds):
        return timeline_query(target_view, target_anchor, user_id=user_id, kinds=target_kinds)

    current = query(view, anchor)
    toggles = []
    for kind in KINDS:
        active = kind in kinds
        if active and len(kinds) == 1:
            toggles.append({'kind': kind, 'label': KIND_META[kind]['label'],
                            'plural': KIND_META[kind]['plural'], 'active': True,
                            'query': current, 'locked': True})
            continue
        if active:
            next_kinds = [k for k in kinds if k != kind]
        else:
            next_kinds = [k for k in KINDS if k in kinds or k == kind]
        toggles.append({'kind': kind, 'label': KIND_META[kind]['label'],
                        'plural': KIND_META[kind]['plural'], 'active': active,
                        'query': query(view, anchor, next_kinds), 'locked': False})
    return {
        'current': current,
        'prev': query(view, rng['prev_anchor']),
        'next': query(view, rng['next_anchor']),
        'today': query(view, today),
        'views': [
            {'key': key, 'label': VIEW_LABELS[key], 'query': query(key, anchor),
             'active': key == view}
            for key in VIEWS
        ],
        'kind_toggles': toggles,
    }


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def _shade(context, grid_start, grid_end, is_today, now=None):
    """Clock-in band (top/height %) for the day column, or None."""
    clock_in = context.get('clock_in')
    if clock_in is None:
        return None
    clock_out = context.get('clock_out')
    if clock_out is None:
        if not is_today:
            return None
        clock_out = now or timezone.localtime().replace(tzinfo=None)
    span = max(1, grid_end - grid_start)
    start_min = min(max(_minutes_of_day(clock_in), grid_start), grid_end)
    end_min = min(max(_minutes_of_day(clock_out), start_min), grid_end)
    if end_min <= start_min:
        return None
    return {
        'top_pct': round((start_min - grid_start) / span * 100, 3),
        'height_pct': round((end_min - start_min) / span * 100, 3),
        'label': f"{clock_in:%H:%M}–{clock_out:%H:%M}",
    }


def _build_day(day, events, context, today, in_month, *, user_id, kinds):
    timed = [ev for ev in events if not ev['untimed']]
    untimed = [ev for ev in events if ev['untimed']]
    return {
        'date': day,
        'iso': day.isoformat(),
        'weekday_label': day.strftime('%a'),
        'day_label': day.strftime('%-d %b'),
        'day_number': day.day,
        'is_today': day == today,
        'is_weekend': day.weekday() >= 5,
        'in_month': in_month,
        'ctx': context,
        'timed': timed,
        'untimed': untimed,
        'events': events,
        'has_events': bool(events),
        'totals': summarise(events),
        'day_query': timeline_query('day', day, user_id=user_id, kinds=kinds),
        'shade': None,
    }


def build_timeline(user, view, anchor, kinds=None, *, user_id_for_links=None, today=None):
    view = parse_view(view)
    kinds = parse_kinds(kinds)
    today = today or timezone.localdate()
    rng = resolve_range(view, anchor)

    events = collect_events(user, rng['grid_start'], rng['grid_end'], kinds)
    contexts = working_day_contexts(user, rng['grid_start'], rng['grid_end'])
    by_day = defaultdict(list)
    for event in events:
        by_day[event['date']].append(event)

    if view == 'day':
        visible = [anchor]
    elif view == 'week':
        weekdays = [rng['start'] + timedelta(days=offset) for offset in range(5)]
        weekend = [rng['start'] + timedelta(days=offset) for offset in (5, 6)]
        visible = weekdays + [day for day in weekend if by_day.get(day)]
    else:
        visible = [rng['grid_start'] + timedelta(days=offset)
                   for offset in range((rng['grid_end'] - rng['grid_start']).days + 1)]

    days = [
        _build_day(day, by_day.get(day, []), contexts[day], today,
                   rng['start'] <= day <= rng['end'],
                   user_id=user_id_for_links, kinds=kinds)
        for day in visible
    ]

    hours, grid_start, grid_end, hour_slots, now_pct = [], None, None, 0, None
    if view in ('day', 'week'):
        timed_all = [ev for day in days for ev in day['timed']]
        grid_start, grid_end = grid_bounds(timed_all)
        now_local = timezone.localtime().replace(tzinfo=None)
        for day in days:
            assign_lanes(day['timed'])
            position_events(day['timed'], grid_start, grid_end)
            day['shade'] = _shade(day['ctx'], grid_start, grid_end, day['is_today'], now_local)
        hours = axis_hours(grid_start, grid_end)
        hour_slots = (grid_end - grid_start) // 60
        if any(day['is_today'] for day in days):
            now_min = _minutes_of_day(now_local)
            if grid_start <= now_min <= grid_end:
                now_pct = round((now_min - grid_start) / (grid_end - grid_start) * 100, 3)

    counted_days = [day for day in days if day['in_month']]
    working_days = sum(1 for day in counted_days if day['ctx']['is_working_day'])
    totals = range_totals([day['totals'] for day in counted_days], working_days,
                          getattr(user, 'hourly_rate', None))
    nav = build_nav(view, anchor, rng, user_id=user_id_for_links, kinds=kinds, today=today)

    weeks = [days[index:index + 7] for index in range(0, len(days), 7)] if view == 'month' else []
    kind_info = []
    for toggle in nav['kind_toggles']:
        kind_info.append({**toggle, 'count': totals['counts'][toggle['kind']]})

    return {
        'view': view,
        'view_label': VIEW_LABELS[view],
        'anchor': anchor,
        'range': rng,
        'days': days,
        'weeks': weeks,
        'hours': hours,
        'hour_slots': hour_slots,
        'grid_start_min': grid_start,
        'grid_end_min': grid_end,
        'now_pct': now_pct,
        'totals': totals,
        'nav': nav,
        'kinds': kind_info,
        'selected_kinds': kinds,
        'has_events': bool(events),
        'query': nav['current'],
    }
