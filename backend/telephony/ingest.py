"""Pull Teams phone calls from Microsoft Graph and record them against matters.

Flow per sync run (``sync_calls``):

1. Poll the enabled call-log report endpoints over a rolling look-back window.
2. For each *new* row (deduped by ``graph_row_id``): store a ``CallRecord``,
   normalise the external number and resolve the matter. A matched call
   auto-creates a ``MatterAttendanceNotes`` (mirroring the Granola flow); an
   unmatched/ambiguous/withheld call is left ``STATUS_PENDING`` in the review
   inbox.
3. Link calls to Granola notes for the same conversation (same fee earner + a
   nearby meeting time), so both share one attendance note. A second pass
   reconciles calls whose Granola note only arrived after the call.
"""
import logging
from datetime import timedelta, timezone as dt_timezone
from decimal import Decimal, InvalidOperation
from math import ceil

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from backend.models import (CallLogConfig, CallRecord, GranolaImportedNote,
                            MatterAttendanceNotes, WIP)
from users.models import CustomUser

from backend.granola.markdown_to_quill import markdown_to_quill_json

from .client import TeamsGraphClient, TelephonyError
from .match import build_matter_phone_index, match_call, normalize_phone

logger = logging.getLogger(__name__)


# --- field parsing ------------------------------------------------------------

def _parse_dt(value):
    if not value:
        return None
    dt = parse_datetime(value) if isinstance(value, str) else value
    if dt is None:
        return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, dt_timezone.utc)
    return dt


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _decimal(value):
    if value in (None, ''):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _resolve_direction(call_type):
    """Best-effort direction from the Graph ``callType`` (e.g. UserIn/UserOut)."""
    t = (call_type or '').lower()
    if 'out' in t:
        return CallRecord.DIRECTION_OUTBOUND
    if 'in' in t:
        return CallRecord.DIRECTION_INBOUND
    return CallRecord.DIRECTION_UNKNOWN


def _external_number(row, direction):
    """The external party leg: caller on inbound, callee on outbound."""
    caller = row.get('callerNumber') or ''
    callee = row.get('calleeNumber') or ''
    if direction == CallRecord.DIRECTION_OUTBOUND:
        return callee or caller
    if direction == CallRecord.DIRECTION_INBOUND:
        return caller or callee
    return caller or callee


def _build_call(row, source):
    call_type = row.get('callType') or ''
    direction = _resolve_direction(call_type)
    external = _external_number(row, direction)
    return CallRecord(
        source=source,
        graph_row_id=str(row.get('id') or ''),
        call_id=str(row.get('callId') or '')[:255],
        direction=direction,
        call_type=call_type[:64],
        internal_user_id=str(row.get('userId') or '')[:64],
        internal_upn=(row.get('userPrincipalName') or '')[:255],
        internal_display_name=(row.get('userDisplayName') or '')[:255],
        caller_number=(row.get('callerNumber') or '')[:64],
        callee_number=(row.get('calleeNumber') or '')[:64],
        external_number=external[:64],
        external_number_normalized=normalize_phone(external)[:32],
        start_datetime=_parse_dt(row.get('startDateTime')),
        end_datetime=_parse_dt(row.get('endDateTime')),
        duration_seconds=_int(row.get('duration')),
        charge=_decimal(row.get('charge')),
        currency=(row.get('currency') or '')[:8],
        raw=row,
    )


def _match_fee_earner(call):
    """Match the internal Teams user to a staff member by email/UPN."""
    if call.internal_upn:
        return CustomUser.objects.filter(
            email__iexact=call.internal_upn, is_active=True).first()
    return None


# --- attendance note creation -------------------------------------------------

def _compute_call_unit(duration_seconds):
    """6 minutes = 1 unit, minimum 1 for an answered call. Missed -> (0, False)."""
    secs = duration_seconds or 0
    if secs <= 0:
        return 0, False
    return max(1, ceil(secs / 360)), True


def _call_date_times(call):
    """Return (date, start_time, finish_time) localised from the call times."""
    start_local = timezone.localtime(call.start_datetime) if call.start_datetime else None
    end_local = timezone.localtime(call.end_datetime) if call.end_datetime else None
    now = timezone.localtime()
    date = (start_local or now).date()
    start_time = (start_local or now).time().replace(microsecond=0)
    finish_time = end_local.time().replace(microsecond=0) if end_local else start_time
    return date, start_time, finish_time


def _call_subject(call):
    number = call.external_number or 'unknown number'
    return f'Telephone call — {call.get_direction_display()} {number}'[:255]


def _call_stub_markdown(call):
    """A minimal note body for a call that has no Granola note attached."""
    lines = [f'**Telephone call** — {call.get_direction_display()}']
    if call.external_number:
        lines.append(f'- Number: {call.external_number}')
    lines.append(f'- Duration: {call.duration_display}'
                 + (' (no answer)' if call.is_missed else ''))
    if call.internal_display_name:
        lines.append(f'- Fee earner: {call.internal_display_name}')
    if call.start_datetime:
        lines.append(f'- Time: {timezone.localtime(call.start_datetime):%d/%m/%Y %H:%M}')
    lines.append('')
    lines.append('_Imported from Microsoft Teams. Add your note here._')
    return '\n'.join(lines)


def create_attendance_note_from_call(call, *, file, person_attended,
                                     is_charged=None, created_by=None,
                                     summary_md=None):
    """Build and persist a MatterAttendanceNotes from a call, linking it back.

    ``is_charged`` defaults to charged for an answered call and not-charged for a
    missed (zero-duration) call; pass a bool to override (e.g. a reviewer ticking
    "Charge time"). ``summary_md`` supplies richer note content (e.g. from a
    linked Granola note) instead of the auto-generated stub.
    """
    date, start_time, finish_time = _call_date_times(call)
    unit, auto_charged = _compute_call_unit(call.duration_seconds)
    if is_charged is None:
        is_charged = auto_charged
    if is_charged and unit == 0:
        unit = 1  # a call a reviewer chose to charge is at least one unit
    content_md = summary_md if summary_md else _call_stub_markdown(call)

    note = MatterAttendanceNotes.objects.create(
        file_number=file,
        date=date,
        start_time=start_time,
        finish_time=finish_time,
        subject_line=_call_subject(call),
        content=markdown_to_quill_json(content_md),
        is_charged=is_charged,
        person_attended=person_attended,
        unit=unit,
        created_by=created_by,
    )

    call.attendance_note = note
    call.matched_file = file
    if person_attended and not call.matched_fee_earner_id:
        call.matched_fee_earner = person_attended
    call.status = CallRecord.STATUS_CREATED
    call.error_message = ''
    call.save()
    return note


# --- Granola note linking -----------------------------------------------------

def find_granola_match(call, window_minutes):
    """Find a Granola attendance note for the same conversation, or None.

    Same fee earner (matched staff member or owner email == internal UPN) and a
    meeting time within ``window_minutes`` of the call. A note already bound to a
    different matter is never merged; a note already linked to a call is skipped.
    """
    if not (call.start_datetime and call.matched_file_id):
        return None
    window = timedelta(minutes=window_minutes)
    notes = (GranolaImportedNote.objects
             .filter(note_type=GranolaImportedNote.TYPE_ATTENDANCE,
                     meeting_start__isnull=False,
                     meeting_start__gte=call.start_datetime - window,
                     meeting_start__lte=call.start_datetime + window,
                     call_records__isnull=True))
    best = None
    for note in notes:
        if note.matched_file_id and note.matched_file_id != call.matched_file_id:
            continue  # belongs to a different matter — never merge
        same_matter = note.matched_file_id == call.matched_file_id
        same_fe = (
            (call.matched_fee_earner_id
             and note.matched_fee_earner_id == call.matched_fee_earner_id)
            or (call.internal_upn and note.owner_email
                and note.owner_email.lower() == call.internal_upn.lower()))
        if not (same_matter or same_fe):
            continue
        delta = abs((note.meeting_start - call.start_datetime).total_seconds())
        rank = (0 if same_matter else 1, delta)
        if best is None or rank < best[0]:
            best = (rank, note)
    return best[1] if best else None


@transaction.atomic
def merge_call_and_granola(call, note, created_by=None):
    """Ensure a call and its Granola note share exactly one attendance note."""
    call_note = call.attendance_note
    granola_note = note.attendance_note

    if granola_note and call_note and granola_note.pk != call_note.pk:
        # Cron race: both created a note. Keep the richer Granola note.
        call.attendance_note = granola_note
        call.save(update_fields=['attendance_note'])
        call_note.delete()
        target = granola_note
    elif granola_note:
        call.attendance_note = granola_note
        call.save(update_fields=['attendance_note'])
        target = granola_note
    elif call_note:
        # Enrich the call stub with the Granola summary; link the note to it.
        if note.summary_md:
            call_note.content = markdown_to_quill_json(note.summary_md)
            call_note.save(update_fields=['content'])
        note.attendance_note = call_note
        note.matched_file = call.matched_file
        note.status = GranolaImportedNote.STATUS_CREATED
        note.save()
        target = call_note
    else:
        # Neither has a note (defensive) — create one from the Granola summary.
        person = call.matched_fee_earner or (
            call.matched_file.fee_earner if call.matched_file_id else None)
        target = create_attendance_note_from_call(
            call, file=call.matched_file, person_attended=person,
            created_by=created_by, summary_md=note.summary_md or None)
        note.attendance_note = target
        note.matched_file = call.matched_file
        note.status = GranolaImportedNote.STATUS_CREATED
        note.save()

    call.granola_note = note
    call.save(update_fields=['granola_note'])
    return target


# --- ingest -------------------------------------------------------------------

def _existing_note_for_call(call, matter):
    """Segment de-dup: reuse the note already made for another row of this call."""
    if not call.call_id:
        return None
    prior = (CallRecord.objects
             .filter(call_id=call.call_id, matched_file=matter,
                     attendance_note__isnull=False)
             .first())
    return prior.attendance_note if prior else None


def _ingest_row(row, source, index, config, created_by=None):
    """Process one call-log row; returns the CallRecord (or None if skipped)."""
    row_id = str(row.get('id') or '')
    if not row_id:
        return None
    if CallRecord.objects.filter(graph_row_id=row_id).exists():
        return None  # already ingested — dedupe
    duration = _int(row.get('duration'))
    if config.min_duration_seconds and duration < config.min_duration_seconds:
        return None  # below the configured threshold — skip entirely

    call = _build_call(row, source)
    call.matched_fee_earner = _match_fee_earner(call)

    result = match_call(call.external_number_normalized, index,
                        allow_otherside_only=config.auto_create_on_otherside_only)
    call.match_reason = result.reason
    if result.candidates:
        call.ambiguous_candidates = result.candidates

    matter = (WIP.objects.filter(file_number__iexact=result.file_number).first()
              if result.file_number else None)

    if matter:
        call.matched_file = matter
        call.matched_role = result.role
        existing = _existing_note_for_call(call, matter)
        if existing:
            # Another row of the same call already owns the note. Log this
            # segment as processed but don't duplicate (or claim) the note.
            call.match_reason = 'additional segment of an already-recorded call'
            call.status = CallRecord.STATUS_CREATED
            call.save()
        else:
            person = call.matched_fee_earner or matter.fee_earner
            create_attendance_note_from_call(
                call, file=matter, person_attended=person,
                created_by=created_by)
            note = find_granola_match(call, config.granola_link_window_minutes)
            if note:
                merge_call_and_granola(call, note, created_by=created_by)
    else:
        call.status = CallRecord.STATUS_PENDING
        call.save()
    return call


def reconcile_granola_links(config):
    """Pass 2: attach Granola notes that arrived after their call was ingested."""
    since = timezone.now() - timedelta(hours=config.lookback_hours)
    calls = (CallRecord.objects
             .filter(status=CallRecord.STATUS_CREATED,
                     granola_note__isnull=True,
                     matched_file__isnull=False,
                     start_datetime__gte=since)
             .select_related('matched_file', 'matched_fee_earner',
                             'attendance_note'))
    linked = 0
    for call in calls:
        note = find_granola_match(call, config.granola_link_window_minutes)
        if note:
            merge_call_and_granola(call, note)
            linked += 1
    return linked


def sync_calls(force=False):
    """Run one poll cycle. Returns a short human-readable status string."""
    config = CallLogConfig.get_solo()
    if not force:
        if not config.enabled:
            return 'Teams call sync disabled.'
        if config.start_date and timezone.localdate() < config.start_date:
            msg = f'Teams call sync scheduled to start {config.start_date:%d/%m/%Y}.'
            if config.last_sync_status != msg:
                config.last_sync_status = msg
                config.save(update_fields=['last_sync_status'])
            return msg

    try:
        client = TeamsGraphClient()
    except TelephonyError as exc:
        msg = f'Teams call sync not configured: {exc}'
        config.last_sync_status = msg
        config.save(update_fields=['last_sync_status'])
        logger.warning(msg)
        return msg

    started = timezone.now()
    # A wider "catch-up" window on the first run of each day (and on manual sync)
    # picks up rows Graph published late; incremental runs use the rolling window.
    catchup = (
        force
        or config.last_full_scan_at is None
        or timezone.localtime(config.last_full_scan_at).date() < timezone.localdate())
    if catchup:
        from_dt = started - timedelta(days=config.catchup_lookback_days)
    else:
        from_dt = started - timedelta(hours=config.lookback_hours)
    earliest = started - timedelta(days=90)  # Graph caps the range at 90 days
    from_dt = max(from_dt, earliest)

    index = build_matter_phone_index()
    created = pending = errors = 0

    endpoints = []
    if config.poll_pstn:
        endpoints.append((CallRecord.SOURCE_PSTN, client.get_pstn_calls))
    if config.poll_direct_routing:
        endpoints.append(
            (CallRecord.SOURCE_DIRECT_ROUTING, client.get_direct_routing_calls))

    try:
        for source, fetch in endpoints:
            for row in fetch(from_dt, started):
                try:
                    call = _ingest_row(row, source, index, config)
                except Exception:  # one bad row must not abort the whole run
                    errors += 1
                    logger.exception('Failed to ingest a Teams call row')
                    continue
                if call is None:
                    continue
                if call.status == CallRecord.STATUS_CREATED:
                    created += 1
                elif call.status == CallRecord.STATUS_PENDING:
                    pending += 1
    except TelephonyError as exc:
        msg = f'Teams call sync error: {exc}'
        config.last_sync_status = msg
        config.save(update_fields=['last_sync_status'])
        logger.warning(msg)
        return msg

    linked = reconcile_granola_links(config)

    config.last_synced_at = started
    update_fields = ['last_synced_at', 'last_sync_status']
    if catchup:
        config.last_full_scan_at = started
        update_fields.append('last_full_scan_at')
    config.last_sync_status = (
        f'{timezone.localtime(started):%d/%m/%Y %H:%M} — '
        f'{created} created, {pending} pending review, {linked} linked to notes, '
        f'{errors} errors ({"catch-up" if catchup else "incremental"}).')
    config.save(update_fields=update_fields)
    logger.info(config.last_sync_status)
    return config.last_sync_status


def test_connection(config=None):
    """Dry run: verify credentials + endpoints, importing nothing.

    Returns ``(ok: bool, message: str)`` for display to a manager.
    """
    config = config or CallLogConfig.get_solo()
    try:
        client = TeamsGraphClient()
    except TelephonyError as exc:
        return False, f'Teams Graph not configured: {exc}'

    to_dt = timezone.now()
    from_dt = to_dt - timedelta(hours=1)
    try:
        counts = client.test_connection(
            from_dt, to_dt, pstn=config.poll_pstn,
            direct_routing=config.poll_direct_routing)
    except TelephonyError as exc:
        return False, f'Graph call-log request failed: {exc}'

    parts = []
    if config.poll_pstn:
        parts.append(f"{counts.get('pstn', 0)} PSTN")
    if config.poll_direct_routing:
        parts.append(f"{counts.get('directRouting', 0)} direct-routing")
    if not parts:
        return False, 'No call-log endpoints are enabled in settings.'
    return True, 'Connected — last hour: ' + ', '.join(parts) + ' call row(s) visible.'
