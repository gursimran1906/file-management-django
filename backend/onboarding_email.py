"""Send the onboarding invite email to a client via Microsoft Graph (app-only),
from the configured ANP mailbox, with the ANP logo embedded.

Sending is opt-in via ONBOARDING_SEND_INVITE_EMAILS and skipped (logged) when
that is off or the Graph mail credentials are not configured, so the onboarding
flow still works in development and tests without emailing anyone.
"""
import base64
import logging
import os
from datetime import datetime
from html import escape

import requests
from azure.identity import ClientSecretCredential
from django.conf import settings

logger = logging.getLogger('backend')

_GRAPH_SCOPE = 'https://graph.microsoft.com/.default'
_TIMEOUT = 20

# What the portal asks for, per item an invite can require. The wording mirrors
# the portal's own upload page (client_onboarding_portal/frontend/app/upload/
# page.tsx) so the email and the page say the same thing. The selfie is taken
# inside the terms step, so it only gets its own line when terms aren't asked for.
ITEM_GUIDANCE = {
    'proof_id': (
        'Photo ID',
        'Your passport or driving licence. Make sure all four corners are in the '
        'picture and the text is readable.'),
    'proof_address': (
        'Current address and proof of address',
        'Tell us where you live now, then upload a utility bill or bank statement '
        'from the last 3 months showing that address. A driving licence with your '
        'current address also works.'),
    'source_of_funds': (
        'Source of funds declaration',
        'Where the money for this matter is coming from. We may ask for more '
        'detail or supporting documents, such as bank statements, before your '
        'matter proceeds.'),
    'pep': (
        'Politically exposed persons declaration',
        'Whether you, a family member or a close associate holds a prominent '
        'public position. We have to ask every client this.'),
    'terms_of_engagement': (
        'Terms of engagement',
        'Read and sign on screen \u2014 you draw your signature and take a photo of '
        'yourself holding your ID \u2014 or download the terms, print and sign the '
        'last page, and upload a scan or a clear photo of it.'),
    'selfie_id': (
        'A photo of you holding your ID',
        'Taken with your phone or computer camera.'),
}
_ITEM_ORDER = ('proof_id', 'proof_address', 'source_of_funds', 'pep',
               'terms_of_engagement', 'selfie_id')


def required_item_lines(required_items):
    """(title, guidance) pairs for the items this invite asks for, in the order
    the portal shows them. Unknown keys are ignored; an empty/None list means
    everything."""
    wanted = set(required_items or ITEM_GUIDANCE)
    if 'terms_of_engagement' in wanted:
        wanted.discard('selfie_id')  # captured as part of signing the terms
    return [ITEM_GUIDANCE[k] for k in _ITEM_ORDER if k in wanted]


def _expiry_phrase(expires_at):
    """'until 21 October 2026' from the portal's ISO timestamp, or '' if unknown."""
    if not expires_at:
        return ''
    try:
        when = datetime.fromisoformat(str(expires_at).replace('Z', '+00:00'))
    except ValueError:
        return ''
    return f'until {when.day} {when.strftime("%B %Y")}'


def is_enabled():
    """Outbound invite email is opt-in (ONBOARDING_SEND_INVITE_EMAILS) so test and
    development environments never email real people."""
    return bool(getattr(settings, 'ONBOARDING_SEND_INVITE_EMAILS', False))


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


def _html_body(client_name, link, required_items=None, expires_at=None):
    logo = ('<img src="cid:anplogo" alt="ANP Solicitors" '
            'style="height:44px;">')
    items = ''.join(
        f'<li style="margin:0 0 10px;"><strong>{escape(title)}</strong><br>'
        f'<span style="color:#4b5563;">{escape(guidance)}</span></li>'
        for title, guidance in required_item_lines(required_items))
    needs_camera = any(k in (required_items or ITEM_GUIDANCE)
                       for k in ('terms_of_engagement', 'selfie_id'))
    expiry = _expiry_phrase(expires_at)
    what_block = (
        '<p style="margin:20px 0 6px;"><strong>What we will ask you for</strong></p>'
        f'<ul style="margin:0;padding-left:20px;">{items}</ul>'
        '<p style="font-size:13px;color:#4b5563;">We will also ask whether you are '
        'completing this for yourself or for a company. If it is for a company, '
        'have its name and registration number to hand.'
        + (' You will need a phone or computer with a camera.' if needs_camera else '')
        + '</p>'
        '<p style="font-size:13px;color:#4b5563;">This usually takes about 10 '
        'minutes. Your progress is saved after each item, so you can leave and '
        'come back to the same link any time before you submit'
        + (f', {expiry}' if expiry else '') + '.</p>'
    ) if items else ''
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
        f'<p>Dear {escape(client_name)},</p>'
        '<p>ANP Solicitors has requested to onboard you as a client. Please use '
        'the link below to upload your ID and documents.</p>'
        f'{what_block}'
        f'{link_block}'
        '<p>Alternatively, you can attend our offices and our staff can do the '
        'same for you.</p>'
        '<p style="margin-top:24px;">Kind regards,<br>ANP Solicitors</p>'
        '<div style="margin-top:28px;padding-top:16px;border-top:1px solid '
        f'#e5e7eb;">{logo}</div>'
        '</div>'
    )


def send_invite_email(client_name, to_email, link, required_items=None, expires_at=None):
    """Send the branded invite email, listing what the portal will ask this
    client for (``required_items`` — the invite's item keys; None means all)
    and how long the link lasts (``expires_at``, the portal's ISO timestamp).
    Returns True if sent, False if skipped (sending switched off, or not
    configured). Raises on a Graph/transport error."""
    if not is_enabled():
        logger.info('Onboarding invite email suppressed (ONBOARDING_SEND_INVITE_EMAILS '
                    'is off) — not sent to %s', to_email)
        return False
    if not is_configured():
        logger.info('Onboarding invite email not configured — skipping send to %s', to_email)
        return False

    attachments = [a for a in [_logo_attachment()] if a]
    message = {
        'message': {
            'subject': 'ANP Solicitors — client onboarding',
            'body': {'contentType': 'HTML', 'content': _html_body(
                client_name, link, required_items, expires_at)},
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
