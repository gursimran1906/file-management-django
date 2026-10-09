"""Weekday morning email to each fee earner: what is waiting for their sign-off.

Built from the same queue as the sign-off page, so the email and the page
always agree. Sending is opt-in (``SIGNOFF_DIGEST_EMAILS``) and goes through
the Graph mailbox used for onboarding invites. Wired to cron in
``settings.CRONJOBS``; ``manage.py send_signoff_digest --dry-run`` shows who
would get what without sending.
"""

import logging
from collections import defaultdict
from html import escape

from django.conf import settings
from django.urls import reverse

from users.models import CustomUser

from . import onboarding_email as graph_mail
from .signoff_queue import build_queue

logger = logging.getLogger('backend')

SUBJECT = 'Awaiting your sign-off'


def is_enabled():
    return bool(getattr(settings, 'SIGNOFF_DIGEST_EMAILS', False))


def build_digests():
    """{fee earner: [QueueItem, ...]} for every active fee earner with an
    email address and something in their own queue, newest completed first."""
    by_user = defaultdict(list)
    for item in build_queue():
        if item.responsible_id:
            by_user[item.responsible_id].append(item)
    users = CustomUser.objects.filter(
        id__in=by_user, is_active=True, is_matter_fee_earner=True,
    ).exclude(email='').order_by('username')
    return {user: by_user[user.id] for user in users}


def _row(item, base_url):
    record = item.record
    completed_by = (f'{record.completed_by.first_name} {record.completed_by.last_name}'.strip()
                    if record.completed_by else 'staff')
    flags = item.flags
    flag_text = (f'{len(flags)} answer{"s" if len(flags) != 1 else ""} flagged'
                 if flags else 'nothing flagged')
    status = 'Returned for changes' if item.is_returned else 'Awaiting sign-off'
    return (
        '<tr>'
        f'<td style="padding:6px 10px 6px 0;white-space:nowrap;">'
        f'<a href="{base_url}{item.home_url}" style="color:#2563eb;font-weight:600;">'
        f'{escape(item.matter.file_number)}</a></td>'
        f'<td style="padding:6px 10px 6px 0;">{escape(item.type_label)}</td>'
        f'<td style="padding:6px 10px 6px 0;">{escape(item.matter.client1.name)}</td>'
        f'<td style="padding:6px 10px 6px 0;color:#4b5563;">{escape(completed_by)}, '
        f'{item.completed_at.strftime("%d/%m/%Y")}</td>'
        f'<td style="padding:6px 0;color:#4b5563;">{escape(status)} &middot; {escape(flag_text)}</td>'
        '</tr>'
    )


def render_digest_html(user, items, base_url=None):
    base_url = (base_url or settings.SITE_BASE_URL).rstrip('/')
    queue_url = f"{base_url}{reverse('signoff_queue')}"
    rows = ''.join(_row(item, base_url) for item in items)
    count = len(items)
    return (
        '<div style="font-family:Arial,Helvetica,sans-serif;color:#111827;'
        'max-width:720px;line-height:1.5;">'
        f'<p>Good morning {escape(user.first_name)},</p>'
        f'<p>{count} item{"s are" if count != 1 else " is"} waiting for your sign-off:</p>'
        '<table style="border-collapse:collapse;font-size:14px;width:100%;">'
        '<thead><tr style="text-align:left;color:#6b7280;font-size:12px;">'
        '<th style="padding:0 10px 4px 0;">File</th><th style="padding:0 10px 4px 0;">Type</th>'
        '<th style="padding:0 10px 4px 0;">Client</th><th style="padding:0 10px 4px 0;">Completed by</th>'
        '<th style="padding:0 0 4px;">Status</th></tr></thead>'
        f'<tbody>{rows}</tbody></table>'
        f'<p style="margin:24px 0;"><a href="{queue_url}" '
        'style="background:#2563eb;color:#ffffff;padding:12px 22px;border-radius:6px;'
        'text-decoration:none;display:inline-block;font-weight:600;">Open the sign-off queue</a></p>'
        '<p style="font-size:12px;color:#6b7280;">You can sign off or return each item from the '
        'queue without opening the file. This is sent on weekday mornings while anything is pending.</p>'
        '</div>'
    )


def send_signoff_digests(send=None):
    """Email every fee earner with a non-empty queue. Returns
    {'sent': n, 'skipped': n, 'recipients': [codes]}; ``send`` overrides the
    setting (the management command's --dry-run passes False)."""
    send = is_enabled() if send is None else send
    summary = {'sent': 0, 'skipped': 0, 'recipients': []}
    for user, items in build_digests().items():
        summary['recipients'].append(user.username)
        if not send:
            summary['skipped'] += 1
            continue
        try:
            sent = graph_mail.send_html_email(
                f'{SUBJECT} ({len(items)})', user.email, render_digest_html(user, items))
        except Exception:  # noqa: BLE001 - one bad send must not stop the others
            logger.exception('Sign-off digest to %s failed', user.username)
            summary['skipped'] += 1
            continue
        summary['sent' if sent else 'skipped'] += 1
    logger.info('Sign-off digest: %s', summary)
    return summary
