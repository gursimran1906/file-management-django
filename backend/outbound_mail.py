"""Send matter correspondence via Microsoft Graph (app-only)."""

import base64
import json
import os
from datetime import datetime, timedelta, timezone as dt_timezone

import httpx
from azure.identity import ClientSecretCredential
from django.conf import settings

MAX_ATTACHMENT_BYTES = 3 * 1024 * 1024  # Graph inline attachment limit per file
MAX_ATTACHMENTS_TOTAL_BYTES = 10 * 1024 * 1024


class OutboundMailError(Exception):
    pass


def _graph_token():
    client_id = os.getenv('AZURE_CLIENT_ID', '')
    client_secret = os.getenv('AZURE_CLIENT_SECRET', '')
    tenant_id = os.getenv('AZURE_TENANT_ID', '')
    if not all([client_id, client_secret, tenant_id]):
        raise OutboundMailError(
            'Azure mail credentials are not configured (AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_TENANT_ID).',
        )
    credential = ClientSecretCredential(
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
    )
    return credential.get_token('https://graph.microsoft.com/.default').token


def build_matter_email_subject(file_number, user, user_subject):
    """Subject line format compatible with email_sorting parser."""
    prefix = f'{file_number} {user.username}/{user.id:02d}'
    subject = (user_subject or '').strip()
    if subject.upper().startswith(file_number.upper()):
        return subject
    return f'{prefix} - {subject}' if subject else prefix


def _recipient_list(addrs):
    return [
        {'emailAddress': {'address': addr.strip()}}
        for addr in addrs
        if addr and addr.strip()
    ]


def build_file_attachments(attachment_files):
    """
    attachment_files: iterable of dicts with keys name, content_type, data (bytes).
    Returns list of Graph fileAttachment objects.
    """
    attachments = []
    total = 0
    for item in attachment_files:
        data = item.get('data') or b''
        size = len(data)
        if size == 0:
            continue
        if size > MAX_ATTACHMENT_BYTES:
            raise OutboundMailError(
                f'Attachment "{item.get("name")}" exceeds 3 MB limit. '
                'Use smaller files or send from Outlook for large attachments.',
            )
        total += size
        if total > MAX_ATTACHMENTS_TOTAL_BYTES:
            raise OutboundMailError('Total attachment size exceeds 10 MB for in-app send.')
        attachments.append({
            '@odata.type': '#microsoft.graph.fileAttachment',
            'name': item.get('name') or 'attachment',
            'contentType': item.get('content_type') or 'application/octet-stream',
            'contentBytes': base64.b64encode(data).decode('ascii'),
        })
    return attachments


def send_matter_email(
    *,
    mailbox_address,
    to_addresses,
    subject,
    body_html,
    cc_addresses=None,
    bcc_addresses=None,
    attachment_files=None,
    request_read_receipt=False,
    request_delivery_receipt=False,
):
    """
    Send email from a shared mailbox via Graph sendMail.
    Returns dict with tracking metadata from Sent Items when found.
    """
    if not mailbox_address:
        raise OutboundMailError('Mailbox address is required.')
    if not to_addresses:
        raise OutboundMailError('At least one recipient is required.')

    token = _graph_token()
    endpoint = (
        f'https://graph.microsoft.com/v1.0/users/{mailbox_address}/sendMail'
    )

    message = {
        'subject': subject,
        'body': {
            'contentType': 'HTML',
            'content': body_html or '',
        },
        'toRecipients': _recipient_list(to_addresses),
        'isReadReceiptRequested': bool(request_read_receipt),
        'isDeliveryReceiptRequested': bool(request_delivery_receipt),
    }
    if cc_addresses:
        cc = _recipient_list(cc_addresses)
        if cc:
            message['ccRecipients'] = cc
    if bcc_addresses:
        bcc = _recipient_list(bcc_addresses)
        if bcc:
            message['bccRecipients'] = bcc

    graph_attachments = build_file_attachments(attachment_files or [])
    if graph_attachments:
        message['attachments'] = graph_attachments

    payload = {
        'message': message,
        'saveToSentItems': True,
    }

    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
    }
    sent_at = datetime.now(dt_timezone.utc)
    with httpx.Client(timeout=120.0) as client:
        response = client.post(endpoint, headers=headers, content=json.dumps(payload))

    if response.status_code not in (202, 200):
        raise OutboundMailError(
            f'Graph sendMail failed ({response.status_code}): {response.text[:500]}',
        )

    tracking = fetch_sent_message_metadata(mailbox_address, subject, sent_at, token=token)
    return {
        'sent_at': sent_at,
        'tracking': tracking,
        'attachment_count': len(graph_attachments),
    }


def fetch_sent_message_metadata(mailbox_address, subject, sent_after, token=None):
    """
    Locate the message in Sent Items to obtain webLink and Graph ids for tracking.
    """
    token = token or _graph_token()
    url = (
        f'https://graph.microsoft.com/v1.0/users/{mailbox_address}'
        f'/mailFolders/sentItems/messages'
    )
    params = {
        '$top': 20,
        '$orderby': 'sentDateTime desc',
        '$select': 'id,subject,webLink,conversationId,internetMessageId,sentDateTime,hasAttachments',
    }
    headers = {'Authorization': f'Bearer {token}'}
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, headers=headers, params=params)
        if response.status_code != 200:
            return {}
        cutoff = sent_after - timedelta(minutes=2)
        for msg in response.json().get('value', []):
            if (msg.get('subject') or '') != subject:
                continue
            sent_str = msg.get('sentDateTime')
            if sent_str:
                try:
                    sent_dt = datetime.fromisoformat(sent_str.replace('Z', '+00:00'))
                    if sent_dt < cutoff:
                        continue
                except ValueError:
                    pass
            return {
                'graph_message_id': msg.get('id'),
                'web_link': msg.get('webLink'),
                'conversation_id': msg.get('conversationId'),
                'internet_message_id': msg.get('internetMessageId'),
                'has_attachments': msg.get('hasAttachments'),
            }
    except httpx.HTTPError:
        return {}
    return {}
