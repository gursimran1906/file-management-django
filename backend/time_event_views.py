import json
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .email_compose import (
    attachment_meta_from_draft,
    delete_draft_with_attachments,
    load_draft_attachment_bytes,
    parse_address_list,
    parse_compose_body,
    record_sent_matter_email,
)
from .models import MatterEmailDraft, MatterTimeEvent, MatterTimeSession, NextWork, WIP
from .outbound_mail import OutboundMailError, build_matter_email_subject, send_matter_email
from .time_events import (
    compute_units_from_datetimes,
    confirm_time_event,
    create_quick_log_event,
    get_active_session,
    get_matter_for_file_number,
)


def _json_body(request):
    try:
        return json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return None


def _session_payload(session):
    if not session:
        return None
    return {
        'file_number': session.file_number.file_number,
        'started_at': session.started_at.isoformat(),
        'activity_type': session.activity_type,
    }


@login_required
@require_GET
def time_event_session(request, file_number):
    matter = get_object_or_404(WIP, file_number=file_number)
    session = get_active_session(request.user)
    events = (
        MatterTimeEvent.objects.filter(
            file_number=matter,
            status=MatterTimeEvent.STATUS_CONFIRMED,
        )
        .select_related('user')
        .order_by('-ended_at')[:20]
    )
    return JsonResponse({
        'matter_file_number': file_number,
        'active_session': _session_payload(session),
        'session_on_this_file': (
            session is not None and session.file_number_id == matter.id
        ),
        'recent_events': [
            {
                'id': e.id,
                'description': e.description,
                'activity_type': e.activity_type,
                'units': e.units,
                'is_charged': e.is_charged,
                'ended_at': timezone.localtime(e.ended_at).strftime('%d/%m/%Y %H:%M'),
                'user': e.user.username if e.user else '',
            }
            for e in events
        ],
    })


@login_required
@require_POST
def time_event_start(request, file_number):
    matter = get_object_or_404(WIP, file_number=file_number)
    data = _json_body(request) or {}
    activity_type = data.get(
        'activity_type', MatterTimeEvent.ACTIVITY_OTHER,
    )
    if activity_type not in dict(MatterTimeEvent.ACTIVITY_CHOICES):
        activity_type = MatterTimeEvent.ACTIVITY_OTHER

    session, _created = MatterTimeSession.objects.update_or_create(
        user=request.user,
        defaults={
            'file_number': matter,
            'started_at': timezone.now(),
            'activity_type': activity_type,
        },
    )
    return JsonResponse({
        'success': True,
        'active_session': _session_payload(session),
    })


@login_required
@require_POST
def time_event_stop(request, file_number):
    matter = get_object_or_404(WIP, file_number=file_number)
    data = _json_body(request)
    if data is None:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)

    description = (data.get('description') or '').strip()
    if not description:
        return JsonResponse({'success': False, 'error': 'Description is required'}, status=400)

    activity_type = data.get('activity_type') or MatterTimeEvent.ACTIVITY_OTHER
    if activity_type not in dict(MatterTimeEvent.ACTIVITY_CHOICES):
        activity_type = MatterTimeEvent.ACTIVITY_OTHER

    is_charged = data.get('is_charged', True)
    if isinstance(is_charged, str):
        is_charged = is_charged.lower() in ('true', '1', 'yes')

    session = get_active_session(request.user)
    if not session or session.file_number_id != matter.id:
        return JsonResponse({
            'success': False,
            'error': 'No active timer on this matter',
        }, status=400)

    ended_at = timezone.now()
    units = compute_units_from_datetimes(session.started_at, ended_at)
    event = MatterTimeEvent.objects.create(
        file_number=matter,
        user=request.user,
        created_by=request.user,
        started_at=session.started_at,
        ended_at=ended_at,
        description=description[:255],
        detail=data.get('detail', ''),
        activity_type=activity_type,
        source=MatterTimeEvent.SOURCE_TIMER,
        is_charged=is_charged,
        status=MatterTimeEvent.STATUS_CONFIRMED,
        units=units,
    )
    confirm_time_event(event, mirror_attendance=True)
    session.delete()

    return JsonResponse({
        'success': True,
        'event_id': event.id,
        'units': event.units,
        'attendance_note_id': event.attendance_note_id,
    })


@login_required
@require_POST
def time_event_cancel(request, file_number):
    get_object_or_404(WIP, file_number=file_number)
    session = get_active_session(request.user)
    if session:
        session.delete()
    return JsonResponse({'success': True})


@login_required
@require_POST
def time_event_quick_log(request, file_number):
    matter = get_object_or_404(WIP, file_number=file_number)
    data = _json_body(request)
    if data is None:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)

    description = (data.get('description') or '').strip()
    if not description:
        return JsonResponse({'success': False, 'error': 'Description is required'}, status=400)

    try:
        minutes = int(data.get('minutes', 6))
    except (TypeError, ValueError):
        minutes = 6
    minutes = max(6, min(minutes, 8 * 60))

    activity_type = data.get('activity_type') or MatterTimeEvent.ACTIVITY_OTHER
    if activity_type not in dict(MatterTimeEvent.ACTIVITY_CHOICES):
        activity_type = MatterTimeEvent.ACTIVITY_OTHER

    is_charged = data.get('is_charged', True)
    if isinstance(is_charged, str):
        is_charged = is_charged.lower() in ('true', '1', 'yes')

    event = create_quick_log_event(
        matter=matter,
        user=request.user,
        created_by=request.user,
        description=description,
        minutes=minutes,
        activity_type=activity_type,
        is_charged=is_charged,
    )
    return JsonResponse({
        'success': True,
        'event_id': event.id,
        'units': event.units,
        'attendance_note_id': event.attendance_note_id,
    })


@login_required
@require_POST
def time_event_from_task(request):
    """Log time after completing a NextWork task."""
    data = _json_body(request)
    if data is None:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)

    task_id = data.get('task_id')
    description = (data.get('description') or '').strip()
    if not task_id or not description:
        return JsonResponse({'success': False, 'error': 'task_id and description required'}, status=400)

    task = get_object_or_404(NextWork, id=task_id)
    if not task.file_number_id:
        return JsonResponse({'success': False, 'error': 'Task has no matter'}, status=400)

    try:
        minutes = int(data.get('minutes', 6))
    except (TypeError, ValueError):
        minutes = 6
    minutes = max(6, min(minutes, 8 * 60))

    activity_type = data.get('activity_type') or MatterTimeEvent.ACTIVITY_ADMIN
    event = create_quick_log_event(
        matter=task.file_number,
        user=request.user,
        created_by=request.user,
        description=description,
        minutes=minutes,
        activity_type=activity_type,
        is_charged=data.get('is_charged', True),
    )
    event.source = MatterTimeEvent.SOURCE_TASK
    event.source_id = task.id
    event.save(update_fields=['source', 'source_id'])

    return JsonResponse({
        'success': True,
        'event_id': event.id,
        'file_number': task.file_number.file_number,
    })


def _agent_authorized(request):
    token = getattr(settings, 'MATTER_TIME_AGENT_TOKEN', '') or ''
    if not token:
        return request.user.is_authenticated
    header = request.headers.get('X-Matter-Time-Agent-Token', '')
    return header == token


@login_required
def matter_time_review(request, file_number):
    matter = get_object_or_404(WIP, file_number=file_number)
    events = MatterTimeEvent.objects.filter(
        file_number=matter,
    ).exclude(status=MatterTimeEvent.STATUS_DISCARDED).select_related(
        'user', 'attendance_note',
    ).order_by('-ended_at')

    if request.method == 'POST':
        event_id = request.POST.get('event_id')
        action = request.POST.get('action')
        event = get_object_or_404(MatterTimeEvent, id=event_id, file_number=matter)
        if event.locked_at:
            messages.error(request, 'This time entry is locked after billing.')
            return redirect('matter_time_review', file_number=file_number)

        if action == 'discard':
            event.status = MatterTimeEvent.STATUS_DISCARDED
            event.save(update_fields=['status'])
            messages.success(request, 'Time entry discarded.')
        elif action == 'confirm':
            try:
                units = int(request.POST.get('units', event.units))
                units = max(1, units)
            except (TypeError, ValueError):
                units = event.units
            event.units = units
            event.is_charged = request.POST.get('is_charged') == 'on'
            event.description = (request.POST.get('description') or event.description)[:255]
            confirm_time_event(event, mirror_attendance=not event.attendance_note_id)
            messages.success(request, 'Time entry confirmed.')
        elif action == 'write_down':
            try:
                units = int(request.POST.get('units', 1))
                units = max(1, units)
            except (TypeError, ValueError):
                units = 1
            event.units = units
            event.save(update_fields=['units'])
            if event.attendance_note_id:
                note = event.attendance_note
                note.unit = units
                note.save(update_fields=['unit'])
            messages.success(request, 'Units updated.')
        return redirect('matter_time_review', file_number=file_number)

    return render(request, 'matter_time_review.html', {
        'matter': matter,
        'file_number': file_number,
        'events': events,
    })


@login_required
@require_POST
def correspondence_send_email(request, file_number):
    matter = get_object_or_404(WIP, file_number=file_number)
    to_raw = (request.POST.get('to') or '').strip()
    cc_raw = (request.POST.get('cc') or '').strip()
    bcc_raw = (request.POST.get('bcc') or '').strip()
    user_subject = (request.POST.get('subject') or '').strip()
    body_html = parse_compose_body(request.POST.get('body') or '')
    mailbox = (
        request.POST.get('from_mailbox')
        or getattr(settings, 'DEFAULT_OUTBOUND_MAILBOX', '')
        or 'mail@anpsolicitors.com'
    )
    request_read_receipt = request.POST.get('request_read_receipt') == 'on'
    request_delivery_receipt = request.POST.get('request_delivery_receipt') == 'on'

    if not to_raw or not user_subject:
        messages.error(request, 'Recipient and subject are required.')
        return redirect('correspondence_view', file_number=file_number)

    if not body_html.strip():
        messages.error(request, 'Email body is required.')
        return redirect('correspondence_view', file_number=file_number)

    to_list = parse_address_list(to_raw)
    cc_list = parse_address_list(cc_raw)
    bcc_list = parse_address_list(bcc_raw)
    full_subject = build_matter_email_subject(file_number, request.user, user_subject)

    draft_id = request.POST.get('draft_id')
    draft = None
    if draft_id:
        try:
            draft = MatterEmailDraft.objects.filter(
                file_number=matter, user=request.user, id=int(draft_id),
            ).prefetch_related('attachments').first()
        except (TypeError, ValueError):
            pass
    attachment_files = load_draft_attachment_bytes(draft) if draft else []
    attachment_meta = attachment_meta_from_draft(draft) if draft else []

    try:
        result = send_matter_email(
            mailbox_address=mailbox,
            to_addresses=to_list,
            subject=full_subject,
            body_html=body_html,
            cc_addresses=cc_list,
            bcc_addresses=bcc_list,
            attachment_files=attachment_files,
            request_read_receipt=request_read_receipt,
            request_delivery_receipt=request_delivery_receipt,
        )
    except OutboundMailError as exc:
        messages.error(request, str(exc))
        return redirect('correspondence_view', file_number=file_number)

    tracking = result.get('tracking') or {}
    record_sent_matter_email(
        matter=matter,
        user=request.user,
        mailbox=mailbox,
        to_list=to_list,
        cc_list=cc_list,
        bcc_list=bcc_list,
        full_subject=full_subject,
        body_html=body_html,
        tracking=tracking,
        attachment_meta=attachment_meta,
        request_read_receipt=request_read_receipt,
        request_delivery_receipt=request_delivery_receipt,
    )

    delete_draft_with_attachments(draft)

    track_note = ' Open in Outlook for full tracking' if tracking.get('web_link') else ''
    messages.success(
        request,
        f'Email sent and recorded on this matter.{track_note}',
    )
    return redirect('correspondence_view', file_number=file_number)


@csrf_exempt
@require_POST
def time_event_agent_create(request, file_number):
    if not _agent_authorized(request):
        return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)

    data = _json_body(request)
    if data is None:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)

    matter = get_object_or_404(WIP, file_number=file_number)
    description = (data.get('activity') or data.get('description') or '').strip()
    if not description:
        return JsonResponse({'success': False, 'error': 'description required'}, status=400)

    try:
        duration_seconds = int(data.get('duration_seconds', 360))
    except (TypeError, ValueError):
        duration_seconds = 360
    duration_seconds = max(60, min(duration_seconds, 8 * 3600))

    ended_at = timezone.now()
    started_at = ended_at - timedelta(seconds=duration_seconds)
    units = compute_units_from_datetimes(started_at, ended_at)

    is_charged = data.get('is_charged', True)
    status = data.get('status', MatterTimeEvent.STATUS_DRAFT)
    if status not in dict(MatterTimeEvent.STATUS_CHOICES):
        status = MatterTimeEvent.STATUS_DRAFT

    user = request.user if request.user.is_authenticated else None
    event = MatterTimeEvent.objects.create(
        file_number=matter,
        user=user,
        created_by=user,
        started_at=started_at,
        ended_at=ended_at,
        description=description[:255],
        detail=json.dumps(data.get('evidence') or {}),
        activity_type=data.get('activity_type', MatterTimeEvent.ACTIVITY_OTHER),
        source=MatterTimeEvent.SOURCE_AGENT,
        source_id=None,
        is_charged=is_charged,
        status=status,
        units=units,
    )
    if data.get('agent_id'):
        event.detail = f"agent={data.get('agent_id')}; {event.detail}"
        event.save(update_fields=['detail'])

    if status == MatterTimeEvent.STATUS_CONFIRMED and request.user.is_authenticated:
        confirm_time_event(event, mirror_attendance=True)

    return JsonResponse({
        'success': True,
        'event_id': event.id,
        'status': event.status,
    })
