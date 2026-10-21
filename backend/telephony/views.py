"""Back-office UI for the Teams call log: the review inbox (Allocate › Calls),
manual assignment, and manager-only settings/sync."""
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from backend.granola.markdown_to_quill import markdown_to_quill_json
from backend.models import (CallLogConfig, CallRecord, Free30Mins,
                            Free30MinsAttendees, WIP)
from users.models import CustomUser

from .ingest import (_call_date_times, _call_stub_markdown,
                     create_attendance_note_from_call, find_granola_match,
                     merge_call_and_granola, sync_calls, test_connection)


def _require_manager(request):
    """Call-log settings/sync screens are manager-only."""
    return bool(getattr(request.user, 'is_manager', False))


def _int_field(value, default):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


@login_required
def calls_inbox(request):
    # Visible to all staff (the "Allocate › Calls" tab). Settings/sync remain
    # manager-only and are hidden in the template for non-managers.
    pending = (CallRecord.objects
               .filter(status=CallRecord.STATUS_PENDING)
               .select_related('matched_fee_earner'))
    recent = (CallRecord.objects
              .filter(status=CallRecord.STATUS_CREATED)
              .select_related('matched_file', 'attendance_note', 'granola_note',
                              'free30_meeting', 'matched_fee_earner')[:25])
    enquiries = (CallRecord.objects
                 .filter(status=CallRecord.STATUS_ENQUIRY)
                 .select_related('matched_fee_earner')
                 .order_by('-reviewed_at', '-timestamp')[:50])
    dismissed = (CallRecord.objects
                 .filter(status=CallRecord.STATUS_IGNORED)
                 .order_by('-reviewed_at', '-timestamp')[:50])

    context = {
        'config': CallLogConfig.get_solo(),
        'pending_calls': pending,
        'recent_calls': recent,
        'enquiry_calls': enquiries,
        'dismissed_calls': dismissed,
        'fee_earners': CustomUser.objects.filter(is_active=True)
                                         .order_by('first_name', 'last_name'),
        'file_numbers': (WIP.objects
                         .exclude(file_number__isnull=True)
                         .exclude(file_number='')
                         .order_by('file_number')
                         .values_list('file_number', flat=True)),
    }
    # AJAX tab swap fetches just the panel body.
    template = ('telephony/_inbox_panel.html' if request.GET.get('partial')
                else 'telephony/inbox.html')
    return render(request, template, context)


@login_required
@require_POST
def call_assign_matter(request, call_id):
    call = get_object_or_404(CallRecord, id=call_id)
    file_number = (request.POST.get('file_number') or '').strip()
    matter = WIP.objects.filter(file_number__iexact=file_number).first()
    if not matter:
        messages.error(request, f'No matter found with file number "{file_number}".')
        return redirect('calls_inbox')

    person = None
    person_id = request.POST.get('person_attended')
    if person_id:
        person = CustomUser.objects.filter(id=person_id).first()
    person = person or call.matched_fee_earner or matter.fee_earner
    is_charged = request.POST.get('is_charged') == 'on'

    call.ambiguous_candidates = None
    note = create_attendance_note_from_call(
        call, file=matter, person_attended=person,
        is_charged=is_charged, created_by=request.user)

    linked = find_granola_match(
        call, CallLogConfig.get_solo().granola_link_window_minutes)
    if linked:
        merge_call_and_granola(call, linked, created_by=request.user)

    call.reviewed_by = request.user
    call.reviewed_at = timezone.now()
    call.save(update_fields=['reviewed_by', 'reviewed_at'])
    messages.success(
        request,
        f'Attendance note created on {matter.file_number} ({note.unit} unit(s)).')
    return redirect('calls_inbox')


@login_required
@require_POST
def call_mark_enquiry(request, call_id):
    """Log the call as a general enquiry (kept searchable, no attendance note)."""
    call = get_object_or_404(CallRecord, id=call_id)
    call.status = CallRecord.STATUS_ENQUIRY
    call.reviewed_by = request.user
    call.reviewed_at = timezone.now()
    call.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])
    messages.success(request, 'Call logged as a general enquiry.')
    return redirect('calls_inbox')


@login_required
@require_POST
def call_route_free30(request, call_id):
    """Turn the call into a Free 30 minute enquiry seeded from the caller."""
    call = get_object_or_404(CallRecord, id=call_id)
    fee_earner = None
    person_id = request.POST.get('fee_earner')
    if person_id:
        fee_earner = CustomUser.objects.filter(id=person_id).first()
    fee_earner = fee_earner or call.matched_fee_earner

    date, start_time, finish_time = _call_date_times(call)
    meeting = Free30Mins.objects.create(
        matter_type=None,
        notes=markdown_to_quill_json(_call_stub_markdown(call)),
        date=date, start_time=start_time, finish_time=finish_time,
        fee_earner=fee_earner, created_by=request.user)

    name = (request.POST.get('caller_name') or '').strip()
    attendee = Free30MinsAttendees.objects.create(
        name=(name or call.external_number or 'Caller')[:255],
        email='',
        contact_number=(call.external_number or '')[:50],
        created_by=request.user)
    meeting.attendees.set([attendee])

    call.free30_meeting = meeting
    call.status = CallRecord.STATUS_CREATED
    call.reviewed_by = request.user
    call.reviewed_at = timezone.now()
    call.save()
    messages.success(request, 'Free 30 minute enquiry created from the call.')
    return redirect('calls_inbox')


@login_required
@require_POST
def call_ignore(request, call_id):
    call = get_object_or_404(CallRecord, id=call_id)
    call.status = CallRecord.STATUS_IGNORED
    call.reviewed_by = request.user
    call.reviewed_at = timezone.now()
    call.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])
    messages.success(request, 'Call dismissed. You can restore it from the dismissed list.')
    return redirect('calls_inbox')


@login_required
@require_POST
def call_restore(request, call_id):
    """Move a dismissed/enquiry call back into the pending review queue."""
    call = get_object_or_404(CallRecord, id=call_id)
    if call.status in (CallRecord.STATUS_IGNORED, CallRecord.STATUS_ENQUIRY):
        call.status = CallRecord.STATUS_PENDING
        call.reviewed_by = None
        call.reviewed_at = None
        call.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])
        messages.success(request, 'Call restored to the review inbox.')
    return redirect('calls_inbox')


@login_required
def calls_settings(request):
    if not _require_manager(request):
        messages.error(request, 'You do not have access to call log settings.')
        return redirect('user_dashboard')

    config = CallLogConfig.get_solo()
    if request.method == 'POST':
        config.enabled = request.POST.get('enabled') == 'on'
        config.start_date = (request.POST.get('start_date') or '').strip() or None
        config.lookback_hours = _int_field(
            request.POST.get('lookback_hours'), config.lookback_hours)
        config.catchup_lookback_days = _int_field(
            request.POST.get('catchup_lookback_days'), config.catchup_lookback_days)
        config.min_duration_seconds = _int_field(
            request.POST.get('min_duration_seconds'), config.min_duration_seconds)
        config.granola_link_window_minutes = _int_field(
            request.POST.get('granola_link_window_minutes'),
            config.granola_link_window_minutes)
        config.poll_pstn = request.POST.get('poll_pstn') == 'on'
        config.poll_direct_routing = request.POST.get('poll_direct_routing') == 'on'
        config.auto_create_on_otherside_only = (
            request.POST.get('auto_create_on_otherside_only') == 'on')
        config.pair_window_minutes = _int_field(
            request.POST.get('pair_window_minutes'), config.pair_window_minutes)
        config.pair_margin_seconds = _int_field(
            request.POST.get('pair_margin_seconds'), config.pair_margin_seconds)
        config.note_grace_hours = _int_field(
            request.POST.get('note_grace_hours'), config.note_grace_hours)
        config.shared_line_upns = (request.POST.get('shared_line_upns') or '').strip()
        config.updated_by = request.user
        config.save()
        messages.success(request, 'Call log settings saved.')
        return redirect('calls_settings')

    context = {
        'config': config,
        'creds_configured': bool(settings.TEAMS_AZURE_CLIENT_ID
                                 and settings.TEAMS_AZURE_CLIENT_SECRET
                                 and settings.TEAMS_AZURE_TENANT_ID),
    }
    return render(request, 'telephony/settings.html', context)


@login_required
@require_POST
def calls_sync_now(request):
    if not _require_manager(request):
        return redirect('user_dashboard')
    status = sync_calls(force=True)
    messages.success(request, f'Teams call sync run: {status}')
    return redirect('calls_inbox')


@login_required
@require_POST
def calls_test_connection(request):
    """Dry run: check the Graph credentials + endpoints without importing."""
    if not _require_manager(request):
        return redirect('user_dashboard')
    ok, message = test_connection()
    (messages.success if ok else messages.error)(request, message)
    return redirect('calls_settings')
