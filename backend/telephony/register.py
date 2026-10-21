"""The call register: every call in and out, and whether it was written up.

The question this answers is "has this call been recorded anywhere?", so it
deliberately looks wider than the rows this app created. A fee earner who rang a
client and then typed an ordinary attendance note by hand has recorded that
call, and the register must say so — otherwise it nags people about work they
have already done, and nobody trusts it.

Evidence that a call is recorded, in order of directness:

1. a live ``CallNote`` paired to it (attendance note, Free 30, or enquiry);
2. an attendance note or Free 30 the sync created from it;
3. the reviewer flagging it an enquiry, or dismissing it;
4. a hand-written attendance note by the same person overlapping the call;
5. a Free 30 by the same fee earner overlapping it, or one whose attendee's
   phone number is the number that was called.

Anything with no evidence and older than the grace window (the Teams log can
lag by a day) is **unallocated** — a real worklist, not noise. Unanswered calls
are listed but never counted as unallocated: nobody spoke, so there is nothing
to write up.
"""
from datetime import datetime, time, timedelta

from django.urls import reverse
from django.utils import timezone

from backend.models import (CallLogConfig, CallNote, CallRecord, Free30Mins,
                            MatterAttendanceNotes)

from .match import national_key, normalize_phone

# How much slack to allow when comparing a typed note's clock times with the
# call log's seconds-accurate times. People round to the nearest few minutes.
HAND_WRITTEN_SLACK = timedelta(minutes=10)


def _aware(date, clock):
    """Combine a local date + time into an aware datetime."""
    return timezone.make_aware(datetime.combine(date, clock or time(0, 0)))


def _overlaps(a_start, a_end, b_start, b_end, slack=HAND_WRITTEN_SLACK):
    if None in (a_start, a_end, b_start, b_end):
        return False
    return a_start - slack <= b_end and b_start - slack <= a_end


def _call_window(call):
    start = call.start_datetime
    if start is None:
        return None, None
    end = call.end_datetime or start + timedelta(
        seconds=max(0, call.duration_seconds or 0))
    return start, end


def _row(call, kind, label, link=None, detail=''):
    return {'call': call, 'kind': kind, 'label': label, 'link': link,
            'detail': detail, 'unallocated': kind == 'unallocated'}


def _hand_written_note(call, notes_by_user):
    """A note the author typed themselves that already covers this call."""
    if not call.matched_fee_earner_id:
        return None
    c_start, c_end = _call_window(call)
    for note in notes_by_user.get(call.matched_fee_earner_id, []):
        n_start = _aware(note.date, note.start_time)
        n_end = _aware(note.date, note.finish_time)
        if _overlaps(n_start, n_end, c_start, c_end):
            return note
    return None


def _hand_written_free30(call, free30_by_user, free30_by_number):
    """A Free 30 that covers this call — by fee earner + time, or by number."""
    c_start, c_end = _call_window(call)
    if call.matched_fee_earner_id:
        for meeting in free30_by_user.get(call.matched_fee_earner_id, []):
            m_start = _aware(meeting.date, meeting.start_time)
            m_end = _aware(meeting.date, meeting.finish_time)
            if _overlaps(m_start, m_end, c_start, c_end):
                return meeting
    key = national_key(call.external_number_normalized)
    if key:
        for meeting in free30_by_number.get(key, []):
            if meeting.date == timezone.localtime(c_start).date():
                return meeting
    return None


def _note_label(note):
    """How a paired live note describes itself in the register."""
    if note.outcome == CallNote.OUTCOME_ATTENDANCE and note.matter_id:
        return ('call_note', f'Attendance note · {note.matter.file_number}',
                reverse('attendance_note_view', args=[note.matter.file_number]))
    if note.outcome == CallNote.OUTCOME_FREE30:
        return ('call_note', 'Free 30 minutes', reverse('free30mins'))
    if note.outcome == CallNote.OUTCOME_ENQUIRY:
        return ('call_note', 'Enquiry recorded', reverse('call_note_detail',
                                                         args=[note.id]))
    if note.outcome == CallNote.OUTCOME_DISCARDED:
        return ('dismissed', 'Note discarded', None)
    return ('waiting', 'Note still being written',
            reverse('call_note_detail', args=[note.id]))


def build_register(start_date, end_date, *, direction='', fee_earner_id=None,
                   only_unallocated=False, config=None):
    """Rows for the register, newest first, plus the counts for the header."""
    config = config or CallLogConfig.get_solo()
    begin = _aware(start_date, time(0, 0))
    finish = _aware(end_date, time(23, 59, 59))

    calls = (CallRecord.objects
             .filter(start_datetime__gte=begin, start_datetime__lte=finish)
             .select_related('matched_file', 'matched_fee_earner',
                             'attendance_note', 'free30_meeting',
                             'granola_note', 'call_note', 'call_note__matter'))
    if direction in (CallRecord.DIRECTION_INBOUND, CallRecord.DIRECTION_OUTBOUND):
        calls = calls.filter(direction=direction)
    if fee_earner_id:
        calls = calls.filter(matched_fee_earner_id=fee_earner_id)
    calls = list(calls)

    # Bulk-load the hand-written evidence once, then match in Python: these are
    # time-overlap comparisons that SQL cannot express cheaply, and the daily
    # volumes here are small.
    people = {c.matched_fee_earner_id for c in calls if c.matched_fee_earner_id}
    notes_by_user, free30_by_user, free30_by_number = {}, {}, {}
    day_from, day_to = begin.date(), finish.date()
    if people:
        for note in (MatterAttendanceNotes.objects
                     .filter(person_attended_id__in=people,
                             date__gte=day_from - timedelta(days=1),
                             date__lte=day_to + timedelta(days=1))
                     .select_related('file_number')):
            notes_by_user.setdefault(note.person_attended_id, []).append(note)
    if calls:
        # Free 30s are also matched by the attendee's phone number, so these are
        # needed even for calls whose Teams account we could not map to a person.
        for meeting in (Free30Mins.objects
                        .filter(date__gte=day_from - timedelta(days=1),
                                date__lte=day_to + timedelta(days=1))
                        .prefetch_related('attendees')):
            if meeting.fee_earner_id:
                free30_by_user.setdefault(meeting.fee_earner_id, []).append(meeting)
            for attendee in meeting.attendees.all():
                key = national_key(normalize_phone(attendee.contact_number))
                if key:
                    free30_by_number.setdefault(key, []).append(meeting)

    grace = timedelta(hours=max(1, config.note_grace_hours))
    now = timezone.now()
    rows = []
    for call in calls:
        live_note = getattr(call, 'call_note', None)
        if live_note is not None:
            kind, label, link = _note_label(live_note)
            who = (live_note.taken_by.get_full_name() or live_note.taken_by.username
                   if live_note.taken_by_id else 'someone')
            rows.append(_row(call, kind, label, link, detail=f'Taken by {who}'))
            continue
        if call.attendance_note_id and call.matched_file_id:
            rows.append(_row(
                call, 'attendance',
                f'Attendance note · {call.matched_file.file_number}',
                reverse('attendance_note_view',
                        args=[call.matched_file.file_number]),
                detail='Created automatically from the call log'))
            continue
        if call.free30_meeting_id:
            rows.append(_row(call, 'free30', 'Free 30 minutes',
                             reverse('free30mins')))
            continue
        if call.status == CallRecord.STATUS_ENQUIRY:
            rows.append(_row(call, 'enquiry', 'Enquiry (flagged, no note)'))
            continue
        if call.status == CallRecord.STATUS_IGNORED:
            rows.append(_row(call, 'dismissed', 'Dismissed by a reviewer'))
            continue
        hand_note = _hand_written_note(call, notes_by_user)
        if hand_note is not None:
            where = (hand_note.file_number.file_number
                     if hand_note.file_number_id else 'no matter')
            rows.append(_row(
                call, 'hand_written', f'Attendance note · {where}',
                (reverse('attendance_note_view',
                         args=[hand_note.file_number.file_number])
                 if hand_note.file_number_id else None),
                detail='Written up by hand, matched on time'))
            continue
        meeting = _hand_written_free30(call, free30_by_user, free30_by_number)
        if meeting is not None:
            rows.append(_row(call, 'hand_written', 'Free 30 minutes',
                             reverse('free30mins'),
                             detail='Recorded by hand, matched on time/number'))
            continue
        if call.is_missed:
            # Nobody spoke, so there is nothing to write up. Still listed — you
            # may want to ring back — but it is not a hole in the records.
            rows.append(_row(call, 'missed', 'No answer'))
            continue
        if call.start_datetime and now - call.start_datetime < grace:
            rows.append(_row(call, 'waiting', 'Not yet written up',
                             detail='Still inside the grace window'))
            continue
        rows.append(_row(call, 'unallocated', 'Unallocated'))

    if only_unallocated:
        rows = [r for r in rows if r['unallocated']]

    counts = {
        'total': len(rows),
        'unallocated': sum(1 for r in rows if r['unallocated']),
        'waiting': sum(1 for r in rows if r['kind'] == 'waiting'),
        'inbound': sum(1 for r in rows
                       if r['call'].direction == CallRecord.DIRECTION_INBOUND),
        'outbound': sum(1 for r in rows
                        if r['call'].direction == CallRecord.DIRECTION_OUTBOUND),
    }
    return rows, counts


def notes_without_calls(start_date, end_date, *, config=None):
    """Live notes in the period that no call row ever matched.

    Shown beside the register so the two sides reconcile: a note with no call is
    just as interesting as a call with no note (it may be an ambiguous pairing
    waiting on its author, or simply a mobile call the Teams log never saw).
    """
    begin = _aware(start_date, time(0, 0))
    finish = _aware(end_date, time(23, 59, 59))
    return list(CallNote.objects
                .filter(started_at__gte=begin, started_at__lte=finish,
                        call_record__isnull=True)
                .exclude(outcome=CallNote.OUTCOME_DISCARDED)
                .select_related('taken_by', 'matter'))
