"""Pull notes from Granola and turn them into attendance notes.

Flow per sync run:

1. Resolve the central API key (env/setting first, then ``GranolaConfig`` row).
2. Page through notes created since the last successful sync.
3. For each *new* note (deduped by ``granola_note_id``): store it, parse the
   matter code from the title, and either auto-create a ``MatterAttendanceNotes``
   (matter resolved) or leave it pending in the central review inbox.
"""
import logging
from datetime import datetime, timedelta, timezone as dt_timezone
from math import ceil

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from backend.models import (Free30Mins, Free30MinsAttendees, GranolaConfig,
                            GranolaImportedNote, MatterAttendanceNotes, WIP)
from users.models import CustomUser

from .client import GranolaClient, GranolaError
from .markdown_to_quill import markdown_to_html, markdown_to_quill_json
from .parse import (extract_file_ref, parse_meeting_times, parse_parties,
                    parse_title)

logger = logging.getLogger(__name__)

# Re-scan a short window before the last sync so notes added to a folder right
# around the boundary aren't missed. Overlap is free thanks to id-based dedupe.
SYNC_OVERLAP = timedelta(minutes=5)

# How often the scheduled sync does a complete folder re-scan (the authoritative,
# nothing-missed pass). Incremental passes run in between for fast pickup.
FULL_SCAN_INTERVAL = timedelta(hours=6)


def resolve_api_key(config=None):
    """Env/Django setting takes precedence over the stored config row."""
    key = getattr(settings, 'GRANOLA_API_KEY', '') or ''
    if key:
        return key.strip()
    config = config or GranolaConfig.get_solo()
    return (config.api_key or '').strip()


def _api_timestamp(dt):
    """Format a datetime as the strict RFC3339 UTC ``Z`` timestamp the API wants.

    Granola's validator rejects offset-style isoformat (e.g. ``+01:00``) and
    microseconds, so normalise to UTC seconds precision: ``2026-06-10T12:52:56Z``.
    """
    if dt is None:
        return None
    return dt.astimezone(dt_timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


# --- normalising Granola's response shape -------------------------------------
# The public API is new and field names are still settling, so read defensively.

def _first(d, *keys, default=None):
    for key in keys:
        if isinstance(d, dict) and d.get(key) not in (None, ''):
            return d[key]
    return default


def _parse_dt(value):
    if not value:
        return None
    if isinstance(value, str):
        dt = parse_datetime(value)
    else:
        dt = value
    if dt is None:
        return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, dt_timezone.utc)
    return dt


def _combine_local(date, clock):
    """Anchor a body-parsed clock time to a date in the active timezone."""
    return timezone.make_aware(
        datetime.combine(date, clock), timezone.get_current_timezone())


def _resolve_meeting_window(note, summary_md):
    """Best-effort (meeting_start, meeting_end) for a Granola note.

    Granola only returns meeting times via the note's ``calendar_event`` (present
    only when the meeting was on a calendar). When the calendar event is missing
    a start and/or end, we fall back to ``Start Time:`` / ``Finish Time:`` lines
    in the note body, anchored to the meeting date. The flat top-level keys are
    kept as defensive fallbacks. ``meeting_start`` finally falls back to the
    note's creation time so the attendance note still gets a date.
    """
    cal = note.get('calendar_event')
    cal = cal if isinstance(cal, dict) else {}
    start = _parse_dt(_first(cal, 'scheduled_start_time', 'start_time', 'start')
                      or _first(note, 'start_time', 'meeting_start', 'started_at'))
    end = _parse_dt(_first(cal, 'scheduled_end_time', 'end_time', 'end')
                    or _first(note, 'end_time', 'meeting_end', 'ended_at'))
    created = _parse_dt(_first(note, 'created_at', 'created'))

    if start is None or end is None:
        times = parse_meeting_times(summary_md)
        anchor = timezone.localtime(start or created or timezone.now()).date()
        if start is None and times.start:
            start = _combine_local(anchor, times.start)
        if end is None and times.finish:
            end = _combine_local(anchor, times.finish)

    if start is None:
        start = created
    # Discard a finish that isn't after the start (e.g. a stray body time) so the
    # unit count and displayed window stay sane.
    if start and end and end <= start:
        end = None
    return start, end


def _extract_owner_email(note):
    for key in ('owner', 'user', 'created_by', 'creator'):
        sub = note.get(key)
        if isinstance(sub, dict) and sub.get('email'):
            return sub['email']
    return _first(note, 'owner_email', 'email', default='') or ''


def _extract_summary_markdown(note):
    val = _first(note, 'summary_markdown', 'summary_md', 'summary', 'notes',
                 'content', 'markdown', default='')
    if isinstance(val, dict):
        val = _first(val, 'markdown', 'md', 'text', 'content', default='')
    return val or ''


def _format_transcript(note):
    """Return (plain_text, raw_json) for whatever transcript shape we get."""
    raw = _first(note, 'transcript', 'transcript_segments', 'utterances',
                 default=None)
    if raw is None:
        return '', None
    if isinstance(raw, str):
        return raw.strip(), raw
    if isinstance(raw, list):
        lines = []
        for utt in raw:
            if not isinstance(utt, dict):
                lines.append(str(utt))
                continue
            speaker = _first(utt, 'speaker_name', 'speaker', 'source',
                             default='')
            if isinstance(speaker, dict):
                speaker = _first(speaker, 'name', 'label', 'source', default='')
            text = _first(utt, 'text', 'content', 'transcript', default='')
            lines.append(f'{speaker}: {text}'.strip(': ').strip())
        return '\n'.join(l for l in lines if l), raw
    return '', raw


# --- attendance note creation -------------------------------------------------

def _compute_unit(start_dt, end_dt):
    """6 minutes = 1 unit, minimum 1 (mirrors AttendanceNoteForm.save)."""
    if not start_dt or not end_dt:
        return 1
    minutes = (end_dt - start_dt).total_seconds() / 60
    return max(1, ceil(minutes / 6))


def create_attendance_note_from_imported(imported, *, file, person_attended,
                                         is_charged, created_by=None):
    """Build and persist a MatterAttendanceNotes from an imported Granola note.

    Used by both the auto-create path and the manual review inbox. Links the
    created note back onto ``imported`` and marks it as created.
    """
    date, start_time, finish_time = _meeting_date_times(imported)
    parsed = parse_title(imported.title)
    subject = (parsed.subject or imported.title or 'Granola note')[:255]

    note = MatterAttendanceNotes.objects.create(
        file_number=file,
        date=date,
        start_time=start_time,
        finish_time=finish_time,
        subject_line=subject,
        content=markdown_to_quill_json(imported.summary_md),
        is_charged=is_charged,
        person_attended=person_attended,
        unit=_compute_unit(imported.meeting_start, imported.meeting_end),
        created_by=created_by,
    )

    imported.attendance_note = note
    imported.matched_file = file
    imported.matched_fee_earner = person_attended
    imported.parsed_is_charged = is_charged
    imported.status = GranolaImportedNote.STATUS_CREATED
    imported.error_message = ''
    imported.save()
    return note


def _meeting_date_times(imported):
    """Return (date, start_time, finish_time) localised from the meeting times."""
    start_local = timezone.localtime(imported.meeting_start) if imported.meeting_start else None
    end_local = timezone.localtime(imported.meeting_end) if imported.meeting_end else None
    now = timezone.localtime()
    date = (start_local or now).date()
    start_time = (start_local or now).time().replace(microsecond=0)
    finish_time = end_local.time().replace(microsecond=0) if end_local else start_time
    return date, start_time, finish_time


def create_free30_from_imported(imported, *, fee_earner=None, created_by=None):
    """Build a Free30Mins meeting (plus parsed attendees) from an imported note."""
    date, start_time, finish_time = _meeting_date_times(imported)

    meeting = Free30Mins.objects.create(
        matter_type=None,
        notes=markdown_to_quill_json(imported.summary_md),
        date=date,
        start_time=start_time,
        finish_time=finish_time,
        fee_earner=fee_earner or imported.matched_fee_earner,
        created_by=created_by,
    )

    parties = parse_parties(imported.summary_md)
    attendees = []
    for p in parties:
        attendees.append(Free30MinsAttendees.objects.create(
            name=p.get('name', '')[:255],
            address_line1=p.get('address_line1', '') or None,
            address_line2=p.get('address_line2', '') or None,
            county=p.get('county', '') or None,
            postcode=(p.get('postcode', '') or '')[:10] or None,
            email=p.get('email', '')[:50],
            contact_number=p.get('contact_number', '')[:50],
            created_by=created_by,
        ))
    if attendees:
        meeting.attendees.set(attendees)

    imported.free30_meeting = meeting
    imported.matched_fee_earner = meeting.fee_earner
    imported.status = GranolaImportedNote.STATUS_CREATED
    imported.error_message = '' if attendees else 'No parties parsed from the note.'
    imported.save()
    return meeting


# --- ingest -------------------------------------------------------------------

def _ingest_note(client, summary_note,
                 note_type=GranolaImportedNote.TYPE_ATTENDANCE):
    """Process a single note from the listing; returns the GranolaImportedNote."""
    note_id = _first(summary_note, 'id', 'note_id', 'document_id')
    if not note_id:
        return None
    if GranolaImportedNote.objects.filter(granola_note_id=note_id).exists():
        return None  # already ingested — dedupe

    # Pull the full note (summary + transcript). Fall back to the listing payload.
    full = client.get_note(note_id, include_transcript=True) or summary_note
    note = full.get('note') if isinstance(full.get('note'), dict) else full

    title = (_first(note, 'title', 'name', default='') or '')[:500]
    summary_md = _extract_summary_markdown(note)
    transcript_text, transcript_json = _format_transcript(note)

    # File number is recorded in the note body; fall back to the title for
    # backward compatibility with the old [FILENUMBER] title convention.
    ref = extract_file_ref(summary_md)
    if not ref.file_number:
        ref = extract_file_ref(title)

    meeting_start, meeting_end = _resolve_meeting_window(note, summary_md)

    imported = GranolaImportedNote(
        note_type=note_type,
        granola_note_id=str(note_id),
        title=title,
        summary_md=summary_md,
        summary_html=markdown_to_html(summary_md),
        transcript=transcript_text,
        transcript_json=transcript_json,
        meeting_start=meeting_start,
        meeting_end=meeting_end,
        note_created_at=_parse_dt(_first(note, 'created_at', 'created')),
        owner_email=_extract_owner_email(note),
        parsed_file_number=ref.file_number or '',
        parsed_is_charged=ref.is_charged,
    )

    # Match a fee earner by the Granola note owner's email (active staff only).
    if imported.owner_email:
        imported.matched_fee_earner = CustomUser.objects.filter(
            email__iexact=imported.owner_email, is_active=True).first()

    if note_type == GranolaImportedNote.TYPE_FREE30:
        # Free 30 minute meetings need no matter. Auto-create only when we found
        # at least one party; otherwise send it to the review inbox so a person
        # can add the attendees before the meeting record is created.
        if parse_parties(summary_md):
            create_free30_from_imported(
                imported, created_by=imported.matched_fee_earner)
        else:
            imported.status = GranolaImportedNote.STATUS_PENDING
            imported.error_message = 'No party details found — review and add attendees.'
            imported.save()
        return imported

    # Attendance note: try to auto-resolve the matter from the parsed file number.
    matter = None
    if ref.file_number:
        matter = WIP.objects.filter(file_number__iexact=ref.file_number).first()

    if matter:
        person = imported.matched_fee_earner or matter.fee_earner
        create_attendance_note_from_imported(
            imported, file=matter, person_attended=person,
            is_charged=ref.is_charged, created_by=imported.matched_fee_earner,
        )
    else:
        # No matter (or unknown file number) -> central review inbox.
        imported.status = GranolaImportedNote.STATUS_PENDING
        imported.save()
    return imported


def _resolve_folder_id(folders, name):
    """Find a folder id by (case-insensitive) name from a list_folders result."""
    target = (name or '').strip().lower()
    if not target:
        return None
    for folder in folders:
        if (folder.get('name') or '').strip().lower() == target:
            return folder.get('id')
    return None


def sync_notes(force=False):
    """Run one sync cycle. Returns a short human-readable status string."""
    config = GranolaConfig.get_solo()
    if not force:
        if not config.enabled:
            return 'Granola sync disabled.'
        # Stay dormant until the configured go-live date (manual Sync now bypasses).
        if config.start_date and timezone.localdate() < config.start_date:
            msg = f'Granola sync scheduled to start {config.start_date:%d/%m/%Y}.'
            if config.last_sync_status != msg:
                config.last_sync_status = msg
                config.save(update_fields=['last_sync_status'])
            return msg

    try:
        api_key = resolve_api_key(config)
        client = GranolaClient(api_key)
    except GranolaError as exc:
        msg = f'Granola not configured: {exc}'
        config.last_sync_status = msg
        config.save(update_fields=['last_sync_status'])
        logger.warning(msg)
        return msg

    # Granola does not document whether adding a note to a folder bumps its
    # updated_at, so an incremental (updated_after) pass alone could MISS a note
    # that was generated before the last sync and foldered later. To guarantee
    # nothing is missed we periodically do a FULL folder scan: list every note in
    # the folder and let id-based dedupe ingest whatever is new. Manual "Sync now"
    # (force) always does a full scan; the first run of each day does one to catch
    # up on the overnight gap (we only run during office hours); and we re-scan
    # every FULL_SCAN_INTERVAL as a mid-day safety net. Incremental in between.
    started = timezone.now()
    full_scan = (
        force
        or config.last_full_scan_at is None
        or timezone.localtime(config.last_full_scan_at).date() < timezone.localdate()
        or (started - config.last_full_scan_at) >= FULL_SCAN_INTERVAL
    )
    updated_after = None
    if not full_scan and config.last_synced_at:
        updated_after = _api_timestamp(config.last_synced_at - SYNC_OVERLAP)
    created = pending = errors = 0

    # Resolve the two shared folders to their Granola ids so each note's
    # provenance (attendance vs free-30) is unambiguous.
    try:
        folders = client.list_folders()
    except GranolaError as exc:
        msg = f'Granola sync error listing folders: {exc}'
        config.last_sync_status = msg
        config.save(update_fields=['last_sync_status'])
        logger.warning(msg)
        return msg

    routes = []  # (folder_id, note_type, folder_name)
    att_id = _resolve_folder_id(folders, config.attendance_folder)
    free_id = _resolve_folder_id(folders, config.free30_folder)
    if att_id:
        routes.append((att_id, GranolaImportedNote.TYPE_ATTENDANCE, config.attendance_folder))
    if free_id:
        routes.append((free_id, GranolaImportedNote.TYPE_FREE30, config.free30_folder))
    if not routes:
        msg = ('Granola sync: no matching folders found. Check the folder names '
               'in settings against Granola.')
        config.last_sync_status = msg
        config.save(update_fields=['last_sync_status'])
        logger.warning(msg)
        return msg

    try:
        for folder_id, note_type, _folder_name in routes:
            for summary_note in client.iter_notes(updated_after=updated_after,
                                                  folder_id=folder_id):
                try:
                    imported = _ingest_note(client, summary_note, note_type)
                except Exception:  # one bad note must not abort the whole run
                    errors += 1
                    logger.exception('Failed to ingest a Granola note')
                    continue
                if imported is None:
                    continue
                if imported.status == GranolaImportedNote.STATUS_CREATED:
                    created += 1
                elif imported.status == GranolaImportedNote.STATUS_PENDING:
                    pending += 1
    except GranolaError as exc:
        msg = f'Granola sync error: {exc}'
        config.last_sync_status = msg
        config.save(update_fields=['last_sync_status'])
        logger.warning(msg)
        return msg

    config.last_synced_at = started
    update_fields = ['last_synced_at', 'last_sync_status']
    if full_scan:
        config.last_full_scan_at = started
        update_fields.append('last_full_scan_at')
    config.last_sync_status = (
        f'{timezone.localtime(started):%d/%m/%Y %H:%M} — '
        f'{created} created, {pending} pending review, {errors} errors '
        f'({"full scan" if full_scan else "incremental"}).'
    )
    config.save(update_fields=update_fields)
    logger.info(config.last_sync_status)
    return config.last_sync_status


def test_connection(config=None):
    """Dry run: verify the API key works and the folders resolve, importing
    nothing. Returns ``(ok: bool, message: str)`` for display to a manager."""
    config = config or GranolaConfig.get_solo()
    try:
        client = GranolaClient(resolve_api_key(config))
    except GranolaError as exc:
        return False, f'No API key configured: {exc}'

    try:
        folders = client.list_folders()
    except GranolaError as exc:
        return False, f'API key did not work: {exc}'

    ok = True
    lines = [f'Connected — {len(folders)} folder(s) visible to this key.']
    for label, folder_name in (('Attendance', config.attendance_folder),
                               ('Free 30', config.free30_folder)):
        folder_id = _resolve_folder_id(folders, folder_name)
        if not folder_id:
            ok = False
            lines.append(f'✗ {label} folder “{folder_name}” not found in Granola.')
            continue
        try:
            peek = list(client.iter_notes(folder_id=folder_id, page_limit=1))
        except GranolaError as exc:
            ok = False
            lines.append(f'✗ {label} folder “{folder_name}”: {exc}')
            continue
        new = sum(
            1 for n in peek
            if not GranolaImportedNote.objects.filter(
                granola_note_id=str(_first(n, 'id', 'note_id', 'document_id'))
            ).exists()
        )
        lines.append(
            f'✓ {label} folder “{folder_name}” found — {len(peek)} note(s) on '
            f'the first page, {new} not yet imported.')
    return ok, ' '.join(lines)
