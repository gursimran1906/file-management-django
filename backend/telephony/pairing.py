"""Staple a Teams call-log row onto the note someone typed during the call.

Why this exists: Microsoft publishes the PSTN call log minutes to a day after
the call, so when the phone rings nothing in the building knows who is calling.
The person answering therefore writes the note first (``CallNote``) and the call
row is matched to it later — backfilling the number, the direction and the
timings.

The matching rule is **(who took it, when)**, never "the most recent number":

* The call log names an *account*, so a call is only offered to notes taken by
  that account's staff member — which means two people on the phone at the same
  time can never collide, the usual case.
* One person with back-to-back or held calls is the case that can collide. We
  rank candidates by how much the intervals genuinely overlap (then direction,
  then how close the start times are) and attach the winner only when it is a
  *clear* winner. Two calls that fit equally well are both recorded as
  candidates and the author picks — the same "ask a human rather than guess"
  rule the Granola inbox follows.
* A shared sign-in (reception, a hot desk) is the one case where the account
  does not identify the person: the log has no device or endpoint field, so
  there is nothing to tell two handsets apart. UPNs listed in
  ``CallLogConfig.shared_line_upns`` are therefore allowed to pair with a note
  from any member of staff, leaning on the overlap/ambiguity rules instead.
"""
import logging
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from backend.models import CallLogConfig, CallNote, CallRecord

logger = logging.getLogger(__name__)


# --- intervals ----------------------------------------------------------------

def note_interval(note):
    """The window the note claims, as (start, end). An unfinished note is a point."""
    start = note.started_at
    return start, (note.ended_at or start)


def call_interval(call):
    """The window the call log reports, as (start, end)."""
    start = call.start_datetime
    if start is None:
        return None, None
    end = call.end_datetime
    if end is None:
        end = start + timedelta(seconds=max(0, call.duration_seconds or 0))
    return start, end


def overlap_seconds(a_start, a_end, b_start, b_end):
    """Seconds the two closed intervals share (0 when they merely touch)."""
    if None in (a_start, a_end, b_start, b_end):
        return 0
    latest_start = max(a_start, b_start)
    earliest_end = min(a_end, b_end)
    return max(0, int((earliest_end - latest_start).total_seconds()))


def _score(note, call):
    """Rank key for one candidate, highest wins.

    ``(direction agrees, shared seconds, -distance between starts)`` — overlap
    is the real signal; direction and proximity only separate near-ties. A call
    whose direction is unknown never loses points for it.
    """
    n_start, n_end = note_interval(note)
    c_start, c_end = call_interval(call)
    overlap = overlap_seconds(n_start, n_end, c_start, c_end)
    delta = abs(int((c_start - n_start).total_seconds())) if c_start else 10 ** 6
    agrees = (call.direction == CallRecord.DIRECTION_UNKNOWN
              or call.direction == note.direction)
    return (1 if agrees else 0, overlap, -delta)


# --- candidate selection ------------------------------------------------------

def _staff_filter(note, config):
    """Which call rows this note's author is allowed to claim."""
    shared = config.shared_upn_set
    allowed = Q()
    if note.taken_by_id:
        allowed |= Q(matched_fee_earner_id=note.taken_by_id)
        if note.taken_by.email:
            allowed |= Q(internal_upn__iexact=note.taken_by.email)
    for upn in shared:
        # A shared sign-in names no person, so anyone's note may claim it.
        allowed |= Q(internal_upn__iexact=upn)
    return allowed


def candidates_for_note(note, config=None):
    """Call rows that could be this note's call, best first.

    Excludes rows already owned by another note, and rows a reviewer dismissed.
    """
    config = config or CallLogConfig.get_solo()
    n_start, n_end = note_interval(note)
    window = timedelta(minutes=max(1, config.pair_window_minutes))
    allowed = _staff_filter(note, config)
    if not allowed:
        return []
    calls = (CallRecord.objects
             .filter(allowed,
                     start_datetime__isnull=False,
                     start_datetime__gte=n_start - window,
                     start_datetime__lte=n_end + window,
                     call_note__isnull=True,
                     # A call the sync already wrote up is accounted for;
                     # pairing it again would double-record the conversation.
                     attendance_note__isnull=True,
                     free30_meeting__isnull=True)
             .exclude(status=CallRecord.STATUS_IGNORED)
             .select_related('matched_file', 'matched_fee_earner'))
    return sorted(calls, key=lambda c: _score(note, c), reverse=True)


def _is_ambiguous(note, best, runner_up, config):
    """True when the two best candidates fit too similarly to choose between."""
    margin = max(0, config.pair_margin_seconds)
    b_dir, b_overlap, b_delta = _score(note, best)
    r_dir, r_overlap, r_delta = _score(note, runner_up)
    if b_dir != r_dir:
        return False                        # direction settles it
    if abs(b_overlap - r_overlap) > margin:
        return False                        # one clearly overlaps more
    return abs(abs(b_delta) - abs(r_delta)) <= margin


def _candidate_payload(call):
    return {
        'id': call.id,
        'number': call.external_number or '',
        'direction': call.direction,
        'start': (timezone.localtime(call.start_datetime).strftime('%d/%m/%Y %H:%M:%S')
                  if call.start_datetime else ''),
        'duration': call.duration_display,
        'file_number': (call.matched_file.file_number
                        if call.matched_file_id else ''),
    }


# --- attaching ----------------------------------------------------------------

def attach(note, call, *, save=True):
    """Bind a call to a note and backfill what the call log knows best.

    The number and direction come from the log (authoritative); the times the
    author typed are left alone, because those are what was actually billed.
    """
    note.call_record = call
    note.pairing_status = CallNote.PAIR_PAIRED
    note.candidate_calls = None
    note.paired_at = timezone.now()
    if not note.caller_number and call.external_number:
        note.caller_number = call.external_number[:64]
    if call.direction in (CallRecord.DIRECTION_INBOUND,
                          CallRecord.DIRECTION_OUTBOUND):
        note.direction = call.direction
    if save:
        note.save(update_fields=['call_record', 'pairing_status',
                                 'candidate_calls', 'paired_at',
                                 'caller_number', 'direction', 'updated_at'])
    # The note is the record of this call, so the call is accounted for.
    if call.status in (CallRecord.STATUS_PENDING, ''):
        call.status = CallRecord.STATUS_CREATED
        call.match_reason = 'recorded by a live call note'
        call.save(update_fields=['status', 'match_reason'])
    return note


def mark_ambiguous(note, candidates, *, save=True):
    """Record the tie and leave the choice to the author."""
    note.call_record = None
    note.pairing_status = CallNote.PAIR_AMBIGUOUS
    note.candidate_calls = [_candidate_payload(c) for c in candidates[:5]]
    if save:
        note.save(update_fields=['call_record', 'pairing_status',
                                 'candidate_calls', 'updated_at'])
    return note


def pair_note(note, config=None):
    """Try to find this note's call. Returns the resulting pairing status."""
    config = config or CallLogConfig.get_solo()
    if note.call_record_id:
        return CallNote.PAIR_PAIRED
    if note.outcome == CallNote.OUTCOME_DISCARDED:
        return note.pairing_status
    candidates = candidates_for_note(note, config)
    if not candidates:
        # Nothing yet. Only give up once the log has had long enough.
        settle_note(note, config)
        return note.pairing_status
    if len(candidates) > 1 and _is_ambiguous(note, candidates[0], candidates[1],
                                             config):
        mark_ambiguous(note, candidates)
        return CallNote.PAIR_AMBIGUOUS
    best = candidates[0]
    if contending_notes(best, note, config):
        # Someone else's note fits this call just as well (a shared sign-in, or
        # overlapping notes). Offer it rather than claim it.
        mark_ambiguous(note, [best])
        return CallNote.PAIR_AMBIGUOUS
    attach(note, best)
    return CallNote.PAIR_PAIRED


def choose_call(note, call):
    """Resolve an ambiguous note: the author says which call it was.

    Raises ``ValueError`` if another note has meanwhile claimed that call, so
    two people resolving at once cannot both take it.
    """
    taken = CallNote.objects.filter(call_record=call).exclude(pk=note.pk).first()
    if taken is not None:
        raise ValueError('That call has already been recorded by another note.')
    attach(note, call)
    return note


def settle_note(note, config=None):
    """Flip a long-unmatched note to 'no matching call' once the grace is up.

    Plenty of calls legitimately never appear in the Teams log — a mobile, a
    withheld number, someone at the front desk — so this is a normal resting
    state, not an error.
    """
    config = config or CallLogConfig.get_solo()
    if note.pairing_status != CallNote.PAIR_WAITING:
        return note.pairing_status
    deadline = note.started_at + timedelta(hours=max(1, config.note_grace_hours))
    if timezone.now() >= deadline:
        note.pairing_status = CallNote.PAIR_NONE
        note.save(update_fields=['pairing_status', 'updated_at'])
    return note.pairing_status


# --- the call's point of view (called from the sync) --------------------------

def eligible_notes_for_call(call, config=None):
    """Notes whose author is allowed to claim this call and whose window fits.

    Mirror image of :func:`candidates_for_note`. Used during ingest, so a call
    that someone has already written up by hand is never given a second,
    auto-generated note, and used to detect contention (below).
    """
    config = config or CallLogConfig.get_solo()
    if call.start_datetime is None:
        return []
    if call.attendance_note_id or call.free30_meeting_id:
        return []                           # already written up by the sync
    window = timedelta(minutes=max(1, config.pair_window_minutes))
    c_start, c_end = call_interval(call)
    shared = config.shared_upn_set
    upn = (call.internal_upn or '').lower()
    notes = (CallNote.objects
             .filter(started_at__gte=c_start - window - timedelta(hours=12),
                     started_at__lte=c_end + window)
             .exclude(outcome=CallNote.OUTCOME_DISCARDED)
             .select_related('taken_by', 'matter'))
    eligible = []
    for note in notes:
        if note.call_record_id and note.call_record_id != call.id:
            continue                        # already settled on another call
        n_start, n_end = note_interval(note)
        if n_start > c_end + window or n_end < c_start - window:
            continue
        if upn and upn in shared:
            eligible.append(note)           # shared sign-in: anyone's note
        elif call.matched_fee_earner_id and note.taken_by_id == call.matched_fee_earner_id:
            eligible.append(note)
        elif upn and note.taken_by and (note.taken_by.email or '').lower() == upn:
            eligible.append(note)
    eligible.sort(key=lambda n: _score(n, call), reverse=True)
    return eligible


def contending_notes(call, note, config=None):
    """Other notes that fit this call just as well as ``note`` does.

    Only happens on a shared sign-in or genuinely overlapping notes. The call
    log carries no device or endpoint field, so there is nothing that could
    separate them — the authors confirm instead of us guessing.
    """
    config = config or CallLogConfig.get_solo()
    others = [n for n in eligible_notes_for_call(call, config) if n.pk != note.pk]
    return [n for n in others if _is_ambiguous_notes(n, note, call, config)]


def _is_ambiguous_notes(note_a, note_b, call, config):
    """True when two notes fit one call too similarly to choose between."""
    margin = max(0, config.pair_margin_seconds)
    a_dir, a_overlap, a_delta = _score(note_a, call)
    b_dir, b_overlap, b_delta = _score(note_b, call)
    if a_dir != b_dir:
        return False
    if abs(a_overlap - b_overlap) > margin:
        return False
    return abs(abs(a_delta) - abs(b_delta)) <= margin


# --- bulk passes (run by the scheduled sync) ----------------------------------

def pair_waiting_notes(config=None):
    """Second pass over notes still waiting: counts (paired, ambiguous, settled)."""
    config = config or CallLogConfig.get_solo()
    since = timezone.now() - timedelta(hours=max(1, config.note_grace_hours) + 24)
    waiting = (CallNote.objects
               .filter(call_record__isnull=True,
                       pairing_status__in=[CallNote.PAIR_WAITING,
                                           CallNote.PAIR_AMBIGUOUS],
                       started_at__gte=since)
               .exclude(outcome=CallNote.OUTCOME_DISCARDED)
               .select_related('taken_by'))
    paired = ambiguous = settled = 0
    for note in waiting:
        before = note.pairing_status
        status = pair_note(note, config)
        if status == CallNote.PAIR_PAIRED:
            paired += 1
        elif status == CallNote.PAIR_AMBIGUOUS and before != CallNote.PAIR_AMBIGUOUS:
            ambiguous += 1
        elif status == CallNote.PAIR_NONE:
            settled += 1
    return paired, ambiguous, settled
