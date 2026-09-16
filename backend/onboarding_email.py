"""Send the onboarding invite email to a client via Microsoft Graph (app-only),
from the configured ANP mailbox, with the ANP logo embedded.

If the Graph mail credentials are not configured the send is skipped (logged),
so the onboarding flow still works in development.
"""
import base64
import logging
import os

import requests
from azure.identity import ClientSecretCredential
from django.conf import settings

logger = logging.getLogger('backend')

_GRAPH_SCOPE = 'https://graph.microsoft.com/.default'
_TIMEOUT = 20


def is_configured():
    return all([
        getattr(settings, 'ONBOARDING_MAIL_CLIENT_ID', ''),
        getattr(settings, 'ONBOARDING_MAIL_CLIENT_SECRET', ''),
        getattr(settings, 'ONBOARDING_MAIL_TENANT_ID', ''),
        getattr(settings, 'ONBOARDING_INVITE_FROM', ''),
    ])


def _token():
    credential = ClientSecretCredential(
        tenant_id=settings.ONBOARDING_MAIL_TENANT_ID,
        client_id=settings.ONBOARDING_MAIL_CLIENT_ID,
        client_secret=settings.ONBOARDING_MAIL_CLIENT_SECRET,
    )
    return credential.get_token(_GRAPH_SCOPE).token


def _logo_attachment():
    path = os.path.join(settings.BASE_DIR, 'static', 'images', 'logo.png')
    try:
        with open(path, 'rb') as handle:
            content = base64.b64encode(handle.read()).decode()
    except OSError:
        return None
    return {
        '@odata.type': '#microsoft.graph.fileAttachment',
        'name': 'logo.png',
        'contentType': 'image/png',
        'contentId': 'anplogo',
        'isInline': True,
        'contentBytes': content,
    }


def _html_body(client_name, link):
    logo = ('<img src="cid:anplogo" alt="ANP Solicitors" '
            'style="height:44px;">')
    if link:
        link_block = (
            f'<p style="margin:24px 0;">'
            f'<a href="{link}" '
            f'style="background:#2563eb;color:#ffffff;padding:12px 22px;'
            f'border-radius:6px;text-decoration:none;display:inline-block;'
            f'font-weight:600;">Upload your documents</a></p>'
            f'<p style="font-size:12px;color:#6b7280;">'
            f'If the button does not work, copy this link into your browser:<br>'
            f'<a href="{link}">{link}</a></p>'
        )
    else:
        link_block = ''
    return (
        '<div style="font-family:Arial,Helvetica,sans-serif;color:#111827;'
        'max-width:560px;line-height:1.5;">'
        f'<p>Dear {client_name},</p>'
        '<p>ANP Solicitors has requested to onboard you as a client. Please use '
        'the link below to upload your ID and documents.</p>'
        f'{link_block}'
        '<p>Alternatively, you can attend our offices and our staff can do the '
        'same for you.</p>'
        '<p style="margin-top:24px;">Kind regards,<br>ANP Solicitors</p>'
        '<div style="margin-top:28px;padding-top:16px;border-top:1px solid '
        f'#e5e7eb;">{logo}</div>'
        '</div>'
    )


def send_invite_email(client_name, to_email, link):
    """Send the branded invite email. Returns True if sent, False if skipped
    (not configured). Raises on a Graph/transport error."""
    if not is_configured():
        logger.info('Onboarding invite email not configured — skipping send to %s', to_email)
        return False

    attachments = [a for a in [_logo_attachment()] if a]
    message = {
        'message': {
            'subject': 'ANP Solicitors — client onboarding',
            'body': {'contentType': 'HTML', 'content': _html_body(client_name, link)},
            'toRecipients': [{'emailAddress': {'address': to_email}}],
            'attachments': attachments,
        },
        'saveToSentItems': True,
    }
    url = (f'https://graph.microsoft.com/v1.0/users/'
           f'{settings.ONBOARDING_INVITE_FROM}/sendMail')
    response = requests.post(
        url,
        headers={'Authorization': f'Bearer {_token()}',
                 'Content-Type': 'application/json'},
        json=message,
        timeout=_TIMEOUT,
    )
    response.raise_for_status()
    logger.info('Onboarding invite email sent to %s', to_email)
    return True
