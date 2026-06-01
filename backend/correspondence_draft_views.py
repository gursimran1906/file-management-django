import json

from django.contrib.auth.decorators import login_required
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .email_compose import draft_is_empty, parse_compose_body
from .models import MatterEmailDraft, MatterEmailDraftAttachment, WIP
from .outbound_mail import MAX_ATTACHMENT_BYTES

MAX_UPLOAD_FILES = 10
MAX_DRAFTS_PER_MATTER = 25


def _json_body(request):
    try:
        return json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return None


def _user_drafts_qs(matter, user):
    return MatterEmailDraft.objects.filter(
        file_number=matter, user=user,
    ).prefetch_related('attachments')


def _get_user_draft(matter, user, draft_id):
    if not draft_id:
        return None
    return _user_drafts_qs(matter, user).filter(id=draft_id).first()


def _draft_label(draft):
    subject = (draft.subject or '').strip()
    if subject:
        return subject[:80]
    to_addr = (draft.to_addresses or '').strip()
    if to_addr:
        first = to_addr.replace(';', ',').split(',')[0].strip()
        return f'To: {first[:50]}'
    return timezone.localtime(draft.updated_at).strftime('Draft · %d/%m/%Y %H:%M')


def _attachment_payload(att):
    return {
        'id': att.id,
        'name': att.original_name,
        'size': att.size,
        'content_type': att.content_type,
    }


def _draft_payload(draft, *, include_empty=False):
    if not draft:
        return None
    if not include_empty and draft_is_empty(draft):
        return None
    return {
        'id': draft.id,
        'label': _draft_label(draft),
        'from_mailbox': draft.from_mailbox,
        'to': draft.to_addresses,
        'cc': draft.cc_addresses,
        'bcc': draft.bcc_addresses,
        'subject': draft.subject,
        'body_html': draft.body_html,
        'request_read_receipt': draft.request_read_receipt,
        'request_delivery_receipt': draft.request_delivery_receipt,
        'attachments': [_attachment_payload(a) for a in draft.attachments.all()],
        'updated_at': timezone.localtime(draft.updated_at).strftime('%d/%m/%Y %H:%M'),
        'is_empty': draft_is_empty(draft),
    }


def _draft_list_item(draft):
    return {
        'id': draft.id,
        'label': _draft_label(draft),
        'subject': (draft.subject or '').strip(),
        'to': (draft.to_addresses or '')[:80],
        'updated_at': timezone.localtime(draft.updated_at).strftime('%d/%m/%Y %H:%M'),
        'attachment_count': draft.attachments.count(),
        'is_empty': draft_is_empty(draft),
    }


def _cleanup_empty_drafts(matter, user, except_id=None):
    from .email_compose import delete_draft_with_attachments
    qs = _user_drafts_qs(matter, user)
    if except_id:
        qs = qs.exclude(id=except_id)
    for draft in qs:
        if draft_is_empty(draft):
            delete_draft_with_attachments(draft)


def _create_blank_draft(matter, user, from_mailbox=''):
    if _user_drafts_qs(matter, user).count() >= MAX_DRAFTS_PER_MATTER:
        return None, f'Maximum {MAX_DRAFTS_PER_MATTER} drafts per matter.'
    return MatterEmailDraft.objects.create(
        file_number=matter,
        user=user,
        from_mailbox=(from_mailbox or '')[:255],
    ), None


@login_required
@require_GET
def correspondence_email_draft(request, file_number):
    matter = get_object_or_404(WIP, file_number=file_number)
    draft_id = request.GET.get('draft_id')
    drafts = list(_user_drafts_qs(matter, request.user))
    active = None
    if draft_id:
        try:
            active = _get_user_draft(matter, request.user, int(draft_id))
        except (TypeError, ValueError):
            pass
    if not active and drafts:
        for d in drafts:
            if not draft_is_empty(d):
                active = d
                break
        if not active:
            active = drafts[0]
    return JsonResponse({
        'success': True,
        'draft': _draft_payload(active, include_empty=True) if active else None,
        'drafts': [_draft_list_item(d) for d in drafts if not draft_is_empty(d) or d == active],
        'active_draft_id': active.id if active else None,
    })


@login_required
@require_POST
def correspondence_email_draft_new(request, file_number):
    matter = get_object_or_404(WIP, file_number=file_number)
    data = _json_body(request) or {}
    from_mailbox = data.get('from_mailbox') or ''
    _cleanup_empty_drafts(matter, request.user)
    draft, err = _create_blank_draft(matter, request.user, from_mailbox)
    if err:
        return JsonResponse({'success': False, 'error': err}, status=400)
    drafts = list(_user_drafts_qs(matter, request.user))
    return JsonResponse({
        'success': True,
        'draft': _draft_payload(draft, include_empty=True),
        'drafts': [_draft_list_item(d) for d in drafts],
        'active_draft_id': draft.id,
    })


@login_required
@require_POST
def correspondence_email_draft_save(request, file_number):
    matter = get_object_or_404(WIP, file_number=file_number)
    data = _json_body(request)
    if data is None:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)

    draft_id = data.get('draft_id')
    draft = None
    if draft_id:
        try:
            draft = _get_user_draft(matter, request.user, int(draft_id))
        except (TypeError, ValueError):
            pass
    if not draft:
        draft, err = _create_blank_draft(
            matter, request.user, data.get('from_mailbox') or '',
        )
        if err:
            return JsonResponse({'success': False, 'error': err}, status=400)

    body_html = parse_compose_body(data.get('body', ''))
    if not body_html and data.get('body_html'):
        body_html = data.get('body_html', '')

    draft.from_mailbox = (data.get('from_mailbox') or draft.from_mailbox or '')[:255]
    draft.to_addresses = data.get('to', '') or ''
    draft.cc_addresses = data.get('cc', '') or ''
    draft.bcc_addresses = data.get('bcc', '') or ''
    draft.subject = (data.get('subject') or '')[:500]
    draft.body_html = body_html
    draft.request_read_receipt = bool(data.get('request_read_receipt'))
    draft.request_delivery_receipt = bool(data.get('request_delivery_receipt'))
    draft.save()

    if draft_is_empty(draft):
        from .email_compose import delete_draft_with_attachments
        deleted_id = draft.id
        delete_draft_with_attachments(draft)
        drafts = list(_user_drafts_qs(matter, request.user))
        next_active = drafts[0] if drafts else None
        return JsonResponse({
            'success': True,
            'draft': None,
            'cleared': True,
            'deleted_draft_id': deleted_id,
            'drafts': [_draft_list_item(d) for d in drafts if not draft_is_empty(d)],
            'active_draft_id': next_active.id if next_active else None,
        })

    drafts = list(_user_drafts_qs(matter, request.user))
    return JsonResponse({
        'success': True,
        'draft': _draft_payload(draft),
        'drafts': [_draft_list_item(d) for d in drafts if not draft_is_empty(d)],
        'active_draft_id': draft.id,
        'saved_at': timezone.localtime(draft.updated_at).strftime('%H:%M'),
    })


@login_required
@require_POST
def correspondence_email_draft_delete(request, file_number, draft_id=None):
    matter = get_object_or_404(WIP, file_number=file_number)
    if draft_id is None:
        data = _json_body(request) or {}
        draft_id = data.get('draft_id')
    draft = _get_user_draft(matter, request.user, draft_id)
    from .email_compose import delete_draft_with_attachments
    deleted_id = draft.id if draft else None
    delete_draft_with_attachments(draft)
    _cleanup_empty_drafts(matter, request.user)
    drafts = list(_user_drafts_qs(matter, request.user))
    next_active = None
    for d in drafts:
        if not draft_is_empty(d):
            next_active = d
            break
    if not next_active and drafts:
        next_active = drafts[0]
    return JsonResponse({
        'success': True,
        'deleted_draft_id': deleted_id,
        'draft': _draft_payload(next_active, include_empty=True) if next_active else None,
        'drafts': [_draft_list_item(d) for d in drafts if not draft_is_empty(d)],
        'active_draft_id': next_active.id if next_active else None,
    })


@login_required
@require_POST
def correspondence_email_draft_upload_attachment(request, file_number):
    matter = get_object_or_404(WIP, file_number=file_number)
    upload = request.FILES.get('file')
    if not upload:
        return JsonResponse({'success': False, 'error': 'No file uploaded'}, status=400)

    if upload.size > MAX_ATTACHMENT_BYTES:
        return JsonResponse({
            'success': False,
            'error': f'File exceeds 3 MB limit ({upload.name}).',
        }, status=400)

    draft_id = request.POST.get('draft_id')
    draft = _get_user_draft(matter, request.user, draft_id)
    if not draft:
        draft, err = _create_blank_draft(matter, request.user)
        if err:
            return JsonResponse({'success': False, 'error': err}, status=400)

    if draft.attachments.count() >= MAX_UPLOAD_FILES:
        return JsonResponse({
            'success': False,
            'error': f'Maximum {MAX_UPLOAD_FILES} attachments per draft.',
        }, status=400)

    att = MatterEmailDraftAttachment.objects.create(
        draft=draft,
        file=upload,
        original_name=upload.name[:255],
        content_type=getattr(upload, 'content_type', '') or '',
        size=upload.size,
    )
    draft.save(update_fields=['updated_at'])

    return JsonResponse({
        'success': True,
        'attachment': _attachment_payload(att),
        'draft': _draft_payload(draft),
        'active_draft_id': draft.id,
    })


@login_required
@require_POST
def correspondence_email_draft_delete_attachment(request, file_number, attachment_id):
    matter = get_object_or_404(WIP, file_number=file_number)
    att = get_object_or_404(
        MatterEmailDraftAttachment,
        id=attachment_id,
        draft__file_number=matter,
        draft__user=request.user,
    )
    att.file.delete(save=False)
    att.delete()
    draft = att.draft
    return JsonResponse({
        'success': True,
        'draft': _draft_payload(draft),
        'active_draft_id': draft.id,
    })


@login_required
@require_GET
def correspondence_email_draft_download_attachment(request, file_number, attachment_id):
    matter = get_object_or_404(WIP, file_number=file_number)
    att = get_object_or_404(
        MatterEmailDraftAttachment,
        id=attachment_id,
        draft__file_number=matter,
        draft__user=request.user,
    )
    return FileResponse(
        att.file.open('rb'),
        as_attachment=True,
        filename=att.original_name,
    )
