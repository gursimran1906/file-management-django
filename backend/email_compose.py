"""Helpers for matter email compose (drafts + HTML body parsing + sent record)."""

import json
import re

from django.utils import timezone

from .models import MatterEmailDraft, MatterEmailDraftAttachment, MatterEmails, WIP
from .time_events import sync_time_event_from_email
from email_sorting.utils import calc_units_email


def parse_compose_body(body_field):
    """
    Accept Quill JSON {"delta":..., "html":...} or raw HTML/plain text.
    Returns HTML string for Graph send and storage.
    """
    raw = body_field or ''
    if not raw.strip():
        return ''
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data.get('html') or ''
    except (json.JSONDecodeError, TypeError):
        pass
    if '<' in raw and '>' in raw:
        return raw
    return raw.replace('\n', '<br>')


def html_to_plain_text(html):
    text = re.sub(r'<[^>]+>', ' ', html or '')
    return re.sub(r'\s+', ' ', text).strip()


def parse_address_list(raw):
    if not raw:
        return []
    return [a.strip() for a in raw.replace(';', ',').split(',') if a.strip()]


def draft_is_empty(draft):
    if not draft:
        return True
    has_fields = any([
        (draft.to_addresses or '').strip(),
        (draft.cc_addresses or '').strip(),
        (draft.bcc_addresses or '').strip(),
        (draft.subject or '').strip(),
        (draft.body_html or '').strip(),
    ])
    has_files = draft.attachments.exists() if hasattr(draft, 'attachments') else False
    return not has_fields and not has_files


def load_draft_attachment_bytes(draft):
    files = []
    for att in draft.attachments.all():
        att.file.open('rb')
        try:
            data = att.file.read()
        finally:
            att.file.close()
        files.append({
            'name': att.original_name,
            'content_type': att.content_type,
            'data': data,
        })
    return files


def attachment_meta_from_draft(draft):
    return [
        {
            'name': att.original_name,
            'size': att.size,
            'content_type': att.content_type,
        }
        for att in draft.attachments.all()
    ]


def record_sent_matter_email(
    *,
    matter,
    user,
    mailbox,
    to_list,
    cc_list,
    bcc_list,
    full_subject,
    body_html,
    units=None,
    tracking=None,
    attachment_meta=None,
    request_read_receipt=False,
    request_delivery_receipt=False,
):
    tracking = tracking or {}
    now = timezone.now()
    sender = {
        'emailAddress': {
            'name': user.get_full_name() or user.username,
            'address': mailbox,
        },
    }
    receiver = [
        {'emailAddress': {'name': addr, 'address': addr}}
        for addr in to_list
    ]
    bcc_json = [
        {'emailAddress': {'name': addr, 'address': addr}}
        for addr in (bcc_list or [])
    ]
    if units is None:
        units = calc_units_email(html_to_plain_text(body_html))

    email = MatterEmails.objects.create(
        file_number=matter,
        sender=json.dumps(sender),
        receiver=json.dumps(receiver),
        bcc=bcc_json or None,
        body=body_html,
        subject=full_subject,
        is_sent=True,
        time=now,
        fee_earner=user,
        units=units,
        link=tracking.get('web_link') or '',
        attachments=attachment_meta or [],
        graph_message_id=tracking.get('graph_message_id'),
        conversation_id=tracking.get('conversation_id'),
        internet_message_id=tracking.get('internet_message_id'),
        request_read_receipt=request_read_receipt,
        request_delivery_receipt=request_delivery_receipt,
        sent_via_app=True,
    )
    sync_time_event_from_email(email)
    return email


def delete_draft_with_attachments(draft):
    if not draft:
        return
    for att in list(draft.attachments.all()):
        att.file.delete(save=False)
        att.delete()
    draft.delete()
