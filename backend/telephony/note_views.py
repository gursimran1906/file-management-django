"""Taking a note while the phone is in your hand, and the call register.

The phone rings, you press *Take a call*, and you are typing within a second —
no matter chosen, no number known, nothing to fill in first. Everything else
(which number it was, inbound or outbound, the exact timings) is stapled on
afterwards by :mod:`backend.telephony.pairing`, because Microsoft does not
publish the call log until long after the call.
"""
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from backend.audit import log_created
from backend.granola.markdown_to_quill import markdown_to_quill_json
from backend.models import (CallLogConfig, CallNote, CallRecord, Free30Mins,
                            Free30MinsAttendees, MatterAttendanceNotes,
                            MatterType, WIP)
from users.models import CustomUser

from . import pairing
from .match import build_matter_phone_index, match_call, normalize_phone
from .register import build_register, group_by_day, notes_without_calls

# How long the register looks back by default.
REGISTER_DEFAULT_DAYS = 14


def _may_edit(request, note):
    """The author owns their note; managers can tidy anyone's."""
    return (note.taken_by_id == request.user.id
            or note.created_by_id == request.user.id
            or bool(getattr(request.user, 'is_manager', False)))


def _file_numbers():
    return (WIP.objects
            .exclude(file_number__isnull=True).exclude(file_number='')
            .order_by('file_number').values_list('file_number', flat=True))


# --- taking the call ----------------------------------------------------------

# A second click on "Take a call" within this many seconds means the button was
# pressed twice, not that a second call started.
DOUBLE_CLICK_SECONDS = 120


@login_required
@require_POST
def call_note_start(request):
    """Open a blank note, clock already running. One click, no questions."""
    direction = (request.POST.get('direction') or '').strip()
    if direction not in (CallNote.DIRECTION_INBOUND, CallNote.DIRECTION_OUTBOUND):
        direction = CallNote.DIRECTION_INBOUND

    # Someone clicking twice should land back in the note they just opened,
    # not start a rival one that then has to be tidied up.
    just_opened = (CallNote.objects
                   .filter(taken_by=request.user, ended_at__isnull=True,
                           outcome=CallNote.OUTCOME_DRAFTING,
                           started_at__gte=timezone.now() - timedelta(
                               seconds=DOUBLE_CLICK_SECONDS))
                   .first())
    if just_opened is not None:
        return redirect('call_note_detail', note_id=just_opened.id)

    note = CallNote.objects.create(
        taken_by=request.user, created_by=request.user,
        direction=direction, started_at=timezone.now(),
        caller_number=(request.POST.get('caller_number') or '').strip()[:64],
    )
    return redirect('call_note_detail', note_id=note.id)


@login_required
def call_note_detail(request, note_id):
    note = get_object_or_404(
        CallNote.objects.select_related('taken_by', 'matter', 'call_record',
                                        'attendance_note', 'free30_meeting'),
        id=note_id)
    config = CallLogConfig.get_solo()
    candidates = []
    if note.pairing_status == CallNote.PAIR_AMBIGUOUS and note.candidate_calls:
        ids = [c.get('id') for c in note.candidate_calls if c.get('id')]
        found = {c.id: c for c in CallRecord.objects.filter(id__in=ids)
                 .select_related('matched_file')}
        # Keep the pairing engine's order: the model's own ordering would put
        # the latest call first, which is not the same as the best fit, and the
        # first one offered is the one that comes pre-selected.
        candidates = [found[i] for i in ids if i in found]
    other_open = (CallNote.objects
                  .filter(taken_by=note.taken_by_id, ended_at__isnull=True,
                          outcome=CallNote.OUTCOME_DRAFTING)
                  .exclude(pk=note.pk)
                  .first())
    return render(request, 'telephony/call_note.html', {
        'note': note,
        'other_open': other_open,
        'config': config,
        'can_edit': _may_edit(request, note),
        'candidates': candidates,
        'file_numbers': _file_numbers(),
        'matter_types': MatterType.objects.all().order_by('type'),
        'fee_earners': CustomUser.objects.filter(is_active=True)
                                 .order_by('first_name', 'last_name'),
    })


@login_required
@require_POST
def call_note_autosave(request, note_id):
    """Keep the typing safe while the call is still going on.

    Deliberately a plain textarea rather than a rich editor: autosaving an
    editor's internal state mid-call is a good way to lose a client's words.
    """
    note = get_object_or_404(CallNote, id=note_id)
    if not _may_edit(request, note):
        return JsonResponse({'ok': False, 'error': 'Not your note.'}, status=403)
    fields = []
    for field, limit in (('subject', 255), ('caller_name', 255),
                         ('caller_number', 64), ('caller_email', 255)):
        if field in request.POST:
            setattr(note, field, (request.POST.get(field) or '').strip()[:limit])
            fields.append(field)
    if 'content_md' in request.POST:
        note.content_md = request.POST.get('content_md') or ''
        fields.append('content_md')
    if 'direction' in request.POST:
        value = request.POST.get('direction')
        if value in (CallNote.DIRECTION_INBOUND, CallNote.DIRECTION_OUTBOUND):
            note.direction = value
            fields.append('direction')
    if fields:
        note.save(update_fields=fields + ['updated_at'])
    return JsonResponse({'ok': True, 'saved_at': timezone.localtime().strftime('%H:%M:%S')})


@login_required
@require_POST
def call_note_end(request, note_id):
    """Mark the call over. The clock stops; the number may still be on its way."""
    note = get_object_or_404(CallNote, id=note_id)
    if not _may_edit(request, note):
        messages.error(request, 'That note belongs to someone else.')
        return redirect('calls_register')
    if note.ended_at is None:
        note.ended_at = timezone.now()
        note.save(update_fields=['ended_at', 'updated_at'])
    pairing.pair_note(note)
    return redirect('call_note_detail', note_id=note.id)


@login_required
@require_POST
def call_note_lookup_number(request, note_id):
    """Which matters have this number on file? (Explicit, not on every keystroke.)"""
    note = get_object_or_404(CallNote, id=note_id)
    number = (request.POST.get('caller_number') or note.caller_number or '').strip()
    normalized = normalize_phone(number)
    if not normalized:
        return JsonResponse({'ok': True, 'results': [],
                             'message': 'Not a number we can look up.'})
    result = match_call(normalized, build_matter_phone_index(),
                        allow_otherside_only=True)
    results = result.candidates or ([] if not result.file_number else [{
        'file_number': result.file_number, 'role': result.role, 'name': ''}])
    return JsonResponse({'ok': True, 'results': results,
                         'message': result.reason})


# --- turning the note into a record ------------------------------------------

def _note_times(note):
    """(date, start, finish) in local time, from the note's own clock."""
    start = timezone.localtime(note.started_at)
    end = timezone.localtime(note.ended_at or note.started_at)
    return start.date(), start.time().replace(microsecond=0), end.time().replace(microsecond=0)


def _apply_posted_fields(note, request):
    note.subject = (request.POST.get('subject') or note.subject or '').strip()[:255]
    if 'content_md' in request.POST:
        note.content_md = request.POST.get('content_md') or ''
    note.caller_name = (request.POST.get('caller_name') or '').strip()[:255]
    note.caller_number = (request.POST.get('caller_number') or '').strip()[:64]
    note.caller_email = (request.POST.get('caller_email') or '').strip()[:255]
    note.follow_up = (request.POST.get('follow_up') or '').strip()
    note.is_charged = request.POST.get('is_charged') == 'on'
    direction = request.POST.get('direction')
    if direction in (CallNote.DIRECTION_INBOUND, CallNote.DIRECTION_OUTBOUND):
        note.direction = direction
    type_id = request.POST.get('matter_type')
    if type_id:
        note.matter_type = MatterType.objects.filter(id=type_id).first()
    if note.ended_at is None:
        note.ended_at = timezone.now()


def _subject_or_default(note):
    if note.subject:
        return note.subject[:255]
    who = note.caller_name or note.display_number or 'unknown number'
    return f'Telephone call — {note.get_direction_display().lower()} {who}'[:255]


def _write_attendance_note(note, matter, user):
    """Create (or update) the matter attendance note this call note produced."""
    date, start_time, finish_time = _note_times(note)
    body = note.content_md or '_No note was typed during the call._'
    if note.follow_up:
        body = f'{body}\n\n**Follow up:** {note.follow_up}'
    existing = note.attendance_note
    if existing is not None:
        existing.file_number = matter
        existing.date = date
        existing.start_time = start_time
        existing.finish_time = finish_time
        existing.subject_line = _subject_or_default(note)
        existing.content = markdown_to_quill_json(body)
        existing.is_charged = note.is_charged
        existing.unit = note.unit
        existing.save()
        return existing
    created = MatterAttendanceNotes.objects.create(
        file_number=matter, date=date, start_time=start_time,
        finish_time=finish_time, subject_line=_subject_or_default(note),
        content=markdown_to_quill_json(body), is_charged=note.is_charged,
        person_attended=note.taken_by, unit=note.unit, created_by=user)
    log_created(user, created,
                f'Attendance note from a telephone call on {matter.file_number}')
    return created


def _write_free30(note, user):
    """Create (or update) the Free 30 minute enquiry this call note produced."""
    date, start_time, finish_time = _note_times(note)
    body = note.content_md or '_No note was typed during the call._'
    if note.follow_up:
        body = f'{body}\n\n**Follow up:** {note.follow_up}'
    meeting = note.free30_meeting
    if meeting is None:
        meeting = Free30Mins.objects.create(
            matter_type=note.matter_type, notes=markdown_to_quill_json(body),
            date=date, start_time=start_time, finish_time=finish_time,
            fee_earner=note.taken_by, created_by=user)
        log_created(user, meeting, 'Free 30 minutes from a telephone enquiry')
    else:
        meeting.matter_type = note.matter_type
        meeting.notes = markdown_to_quill_json(body)
        meeting.date = date
        meeting.start_time = start_time
        meeting.finish_time = finish_time
        meeting.save()
    attendee = meeting.attendees.first()
    name = note.caller_name or note.display_number or 'Caller'
    if attendee is None:
        attendee = Free30MinsAttendees.objects.create(
            name=name[:255], email=note.caller_email[:50],
            contact_number=note.display_number[:50], created_by=user)
        meeting.attendees.set([attendee])
    else:
        attendee.name = name[:255]
        attendee.email = note.caller_email[:50]
        attendee.contact_number = note.display_number[:50]
        attendee.save()
    return meeting


@login_required
@require_POST
def call_note_save(request, note_id):
    """Save the note as the kind of record it turned out to be."""
    note = get_object_or_404(CallNote.objects.select_related('taken_by'), id=note_id)
    if not _may_edit(request, note):
        messages.error(request, 'That note belongs to someone else.')
        return redirect('calls_register')

    outcome = request.POST.get('outcome') or CallNote.OUTCOME_ENQUIRY
    _apply_posted_fields(note, request)

    if outcome == CallNote.OUTCOME_DISCARDED:
        note.outcome = CallNote.OUTCOME_DISCARDED
        note.save()
        messages.success(request, 'Call note discarded.')
        return redirect('calls_register')

    if outcome == CallNote.OUTCOME_ATTENDANCE:
        file_number = (request.POST.get('file_number') or '').strip()
        matter = WIP.objects.filter(file_number__iexact=file_number).first()
        if matter is None:
            note.save()
            messages.error(
                request,
                f'No matter found with file number "{file_number}" — the note is '
                'saved, nothing has been filed yet.')
            return redirect('call_note_detail', note_id=note.id)
        note.matter = matter
        note.outcome = CallNote.OUTCOME_ATTENDANCE
        note.attendance_note = _write_attendance_note(note, matter, request.user)
        note.save()
        pairing.pair_note(note)
        messages.success(
            request,
            f'Attendance note added to {matter.file_number} '
            f'({note.attendance_note.unit} unit(s)).')
        return redirect('call_note_detail', note_id=note.id)

    if outcome == CallNote.OUTCOME_FREE30:
        note.outcome = CallNote.OUTCOME_FREE30
        note.free30_meeting = _write_free30(note, request.user)
        note.save()
        pairing.pair_note(note)
        messages.success(request, 'Saved as a Free 30 minute enquiry.')
        return redirect('call_note_detail', note_id=note.id)

    # Enquiry: the note itself is the record. No matter, no Free 30 — but the
    # caller, the number and what they wanted are all captured, which is what
    # the old "general enquiry" tick box could never do.
    note.outcome = CallNote.OUTCOME_ENQUIRY
    note.save()
    pairing.pair_note(note)
    messages.success(request, 'Enquiry recorded.')
    return redirect('call_note_detail', note_id=note.id)


@login_required
@require_POST
def call_note_choose_call(request, note_id):
    """Resolve an ambiguous pairing — the author says which call was theirs."""
    note = get_object_or_404(CallNote, id=note_id)
    if not _may_edit(request, note):
        messages.error(request, 'That note belongs to someone else.')
        return redirect('calls_register')
    choice = request.POST.get('call_record')
    if choice == 'none':
        note.pairing_status = CallNote.PAIR_NONE
        note.candidate_calls = None
        note.save(update_fields=['pairing_status', 'candidate_calls', 'updated_at'])
        messages.success(request, 'Noted — no Teams call matches this note.')
        return redirect('call_note_detail', note_id=note.id)
    offered = {str(c.get('id')) for c in (note.candidate_calls or [])}
    if choice not in offered:
        # Only the calls this note was actually offered — nobody gets to claim
        # a colleague's call by posting its id.
        messages.error(request, 'That call was not one of the options.')
        return redirect('call_note_detail', note_id=note.id)
    call = CallRecord.objects.filter(id=choice).first()
    if call is None:
        messages.error(request, 'That call could not be found.')
        return redirect('call_note_detail', note_id=note.id)
    try:
        pairing.choose_call(note, call)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect('call_note_detail', note_id=note.id)
    messages.success(request, f'Note matched to the call on {call.external_number}.')
    return redirect('call_note_detail', note_id=note.id)


# --- the register -------------------------------------------------------------

@login_required
def calls_register(request):
    """Every call in and out, and whether it has been written up."""
    config = CallLogConfig.get_solo()
    today = timezone.localdate()
    preset = request.GET.get('preset', '')
    presets = {'today': 0, 'week': 7, 'month': 30}
    if preset in presets:
        date_from, date_to = today - timedelta(days=presets[preset]), today
    else:
        date_from = parse_date(request.GET.get('from') or '') or (
            today - timedelta(days=REGISTER_DEFAULT_DAYS))
        date_to = parse_date(request.GET.get('to') or '') or today
    if date_from > date_to:
        date_from, date_to = date_to, date_from
    direction = request.GET.get('direction') or ''
    only_unallocated = request.GET.get('unallocated') == '1'
    mine = request.GET.get('mine') == '1'

    rows, counts = build_register(
        date_from, date_to, direction=direction,
        fee_earner_id=request.user.id if mine else None,
        only_unallocated=only_unallocated, config=config)
    context = {
        'config': config,
        'rows': rows,
        'day_groups': group_by_day(rows),
        'counts': counts,
        'orphan_notes': notes_without_calls(date_from, date_to, config=config),
        'date_from': date_from,
        'date_to': date_to,
        'direction': direction,
        'only_unallocated': only_unallocated,
        'mine': mine,
        'preset': preset,
        'presets': [('today', 'Today'), ('week', 'Last 7 days'),
                    ('month', 'Last 30 days')],
        'file_numbers': _file_numbers(),
    }
    template = ('telephony/_register_panel.html' if request.GET.get('partial')
                else 'telephony/register.html')
    return render(request, template, context)
