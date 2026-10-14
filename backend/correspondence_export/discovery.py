"""Find the emails that belong to a matter and build the preview list.

Two sources, unioned and de-duplicated by internet message id:

* system-filed: the MatterEmails rows the ingester attached to the matter
  (matter code in the subject). Older rows carry no Graph id, so they are
  located in the mailbox by received time + web link and the ids are saved back.
* client addresses: a Graph search per mailbox and address, kept only where the
  address is exactly the sender or a To/Cc/Bcc recipient.

Names are never searched for; they only drive flags.
"""
import logging
import re
from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

from backend.models import CorrespondenceExport, MatterEmails
from .classify import (EXCLUDED_REPORT_TYPES, NON_DELIVERY, classify_by_class, is_automatic_reply,
                       message_class)
from .graph_mail import GraphMail, GraphMailError, addr_only, fmt_addr, fmt_addrs, iso_utc, parse_graph_dt
from .mailboxes import shared_mailboxes

logger = logging.getLogger('backend')

EXCLUDED_FOLDERS = {'drafts', 'junk email', 'junk e-mail'}
REVIEW_FOLDERS = {'deleted items', 'junk email', 'junk e-mail', 'recoverable items'}
FOUND_BY_LABELS = {'system': 'filed under matter', 'address': 'client address', 'matter': 'matter code'}

FLAG_RECEIPT = 'Receipt'
FLAG_BOUNCE = 'Bounce (non-delivery report)'
FLAG_AUTO_REPLY = 'Automatic reply'
FLAG_DELETED = 'In Deleted Items'
FLAG_NO_REF_SUBJECT = 'No client name or matter ref in subject'
FLAG_NOT_FOUND = 'Not found in the mailboxes searched'


def date_bounds(params, tz=None):
    tz = tz or ZoneInfo(settings.TIME_ZONE)
    date_from = datetime.strptime(params['date_from'], '%Y-%m-%d').date()
    date_to = datetime.strptime(params['date_to'], '%Y-%m-%d').date()
    start = datetime.combine(date_from, datetime.min.time(), tzinfo=tz)
    end = datetime.combine(date_to + timedelta(days=1), datetime.min.time(), tzinfo=tz)
    return start, end


def participants_match(message, addresses):
    """Strict: one of `addresses` is exactly the sender or a To/Cc/Bcc recipient."""
    wanted = {a.lower() for a in addresses}
    found = {addr_only(message.get('from'))}
    for key in ('toRecipients', 'ccRecipients', 'bccRecipients'):
        found.update(addr_only(r) for r in (message.get(key) or []))
    found.discard('')
    return bool(found & wanted)


def hit_key(message):
    return (message.get('internetMessageId') or '').strip().lower() or f"graph:{message.get('id')}"


def keyword_in(text, names, matters):
    """Any name keyword (whole word) or matter code (ignoring separators) in `text`."""
    matched = []
    for name in names:
        if name and re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', text, flags=re.I):
            matched.append(name)
    squashed = re.sub(r'[\s/\-_.]', '', text).lower()
    for code in matters:
        if code and re.sub(r'[\s/\-_.]', '', code).lower() in squashed:
            matched.append(code)
    return matched


def candidate_from_message(message, mailbox, folder, found_by, firm_domain, matter_email_id=None):
    received = parse_graph_dt(message.get('receivedDateTime'))
    sent = parse_graph_dt(message.get('sentDateTime')) or received
    msg_class = message_class(message)
    from_addr = addr_only(message.get('from'))
    return {
        'key': hit_key(message),
        'mailbox': mailbox,
        'graph_id': message.get('id') or '',
        'folder': folder,
        'locations': [f'{mailbox} / {folder}'],
        'found_by': [found_by],
        'received': iso_utc(received) if received else '',
        'sent': iso_utc(sent) if sent else '',
        'from': fmt_addr(message.get('from')),
        'from_addr': from_addr,
        'to': fmt_addrs(message.get('toRecipients')),
        'cc': fmt_addrs(message.get('ccRecipients')),
        'subject': message.get('subject') or '(no subject)',
        'has_attachments': bool(message.get('hasAttachments')),
        'msg_class': msg_class,
        'report': classify_by_class(msg_class),
        'matter_email_id': matter_email_id,
        'direction': 'Sent' if from_addr.endswith('@' + firm_domain) else 'Received',
        'flags': [],
        'selected': True,
    }


def merge_candidate(candidates, candidate):
    existing = candidates.get(candidate['key'])
    if existing is None:
        candidates[candidate['key']] = candidate
        return True
    for location in candidate['locations']:
        if location not in existing['locations']:
            existing['locations'].append(location)
    for source in candidate['found_by']:
        if source not in existing['found_by']:
            existing['found_by'].append(source)
    if candidate.get('matter_email_id') and not existing.get('matter_email_id'):
        existing['matter_email_id'] = candidate['matter_email_id']
    if existing['folder'].lower() in REVIEW_FOLDERS and candidate['folder'].lower() not in REVIEW_FOLDERS:
        for field in ('mailbox', 'graph_id', 'folder'):
            existing[field] = candidate[field]
    return False


def apply_preview_flags(candidate, names, matters):
    flags = []
    report = candidate.get('report')
    if report in EXCLUDED_REPORT_TYPES:
        flags.append(f'{FLAG_RECEIPT}: {report}')
        candidate['selected'] = False
    elif report == NON_DELIVERY:
        flags.append(FLAG_BOUNCE)
    if is_automatic_reply(candidate.get('msg_class', '')):
        flags.append(FLAG_AUTO_REPLY)
    if (candidate.get('folder') or '').lower() in REVIEW_FOLDERS:
        flags.append(FLAG_DELETED)
    if (names or matters) and not keyword_in(candidate.get('subject', ''), names, matters):
        flags.append(FLAG_NO_REF_SUBJECT)
    if not candidate.get('graph_id'):
        flags.append(FLAG_NOT_FOUND)
        candidate['selected'] = False
    candidate['flags'] = flags
    return candidate


def resolve_matter_email(graph, row, mailboxes_to_try):
    """Locate a MatterEmails row in Microsoft 365. Returns (message, mailbox, folder) or (None, None, None).

    Rows written by the current ingester carry their ids. Older rows are found by
    received time (a two-second window) and web link, and the ids are saved back so
    the lookup happens once.
    """
    if row.graph_message_id and row.mailbox:
        try:
            message = graph.get_message(row.mailbox, row.graph_message_id)
            folder = row.folder_name or graph.folder_name(row.mailbox, message.get('parentFolderId'))
            return message, row.mailbox, folder
        except GraphMailError as exc:
            if exc.status not in (404, 400):
                raise
    if not (row.link and row.time):
        return None, None, None
    received = row.time if row.time.tzinfo else row.time.replace(tzinfo=dt_timezone.utc)
    start, end = received - timedelta(seconds=2), received + timedelta(seconds=2)
    for mailbox in mailboxes_to_try:
        try:
            messages = graph.list_window(mailbox, start, end)
        except GraphMailError as exc:
            if exc.status in (403, 404):
                continue
            raise
        match = next((m for m in messages if m.get('webLink') and m['webLink'] == row.link), None)
        if match is None:
            subject = (row.subject or '').strip()
            match = next((m for m in messages if (m.get('subject') or '').strip() == subject
                          and not m.get('isDraft')), None)
        if match is None:
            continue
        folder = graph.folder_name(mailbox, match.get('parentFolderId'))
        row.mailbox = mailbox
        row.graph_message_id = (match.get('id') or '')[:512]
        row.internet_message_id = (match.get('internetMessageId') or '')[:998]
        row.folder_name = folder[:255]
        row.message_class = message_class(match)[:255]
        row.has_attachments = match.get('hasAttachments')
        row.save(update_fields=['mailbox', 'graph_message_id', 'internet_message_id',
                                'folder_name', 'message_class', 'has_attachments'])
        return match, mailbox, folder
    return None, None, None


def _unresolved_candidate(row, firm_domain):
    import json
    sender = row.sender
    if isinstance(sender, str):
        try:
            sender = json.loads(sender)
        except ValueError:
            sender = {}
    receivers = row.receiver
    if isinstance(receivers, str):
        try:
            receivers = json.loads(receivers)
        except ValueError:
            receivers = []
    from_addr = addr_only(sender if isinstance(sender, dict) else {})
    received = row.time if row.time and row.time.tzinfo else (row.time.replace(tzinfo=dt_timezone.utc) if row.time else None)
    return {
        'key': f'row:{row.id}',
        'mailbox': '', 'graph_id': '', 'folder': '',
        'locations': ['filed under matter (original not located)'],
        'found_by': ['system'],
        'received': iso_utc(received) if received else '',
        'sent': iso_utc(received) if received else '',
        'from': fmt_addr(sender if isinstance(sender, dict) else {}),
        'from_addr': from_addr,
        'to': fmt_addrs(receivers if isinstance(receivers, list) else []),
        'cc': '',
        'subject': row.subject or '(no subject)',
        'has_attachments': bool(row.has_attachments),
        'msg_class': row.message_class or '',
        'report': classify_by_class(row.message_class or ''),
        'matter_email_id': row.id,
        'direction': 'Sent' if from_addr.endswith('@' + firm_domain) else 'Received',
        'flags': [],
        'selected': False,
    }


def _note(export, text, done=None, total=None):
    export.progress_note = text[:255]
    export.worker_heartbeat = timezone.now()
    fields = ['progress_note', 'worker_heartbeat']
    if done is not None:
        export.progress_done = done
        fields.append('progress_done')
    if total is not None:
        export.progress_total = total
        fields.append('progress_total')
    export.save(update_fields=fields)


def _cancelled(export):
    return CorrespondenceExport.objects.filter(id=export.id, status=CorrespondenceExport.STATUS_CANCELLED).exists()


def run_discovery(export, graph=None):
    params = export.params or {}
    matter = export.matter
    firm_domain = getattr(settings, 'CORRESPONDENCE_EXPORT_FIRM_DOMAIN', 'anpsolicitors.com').lower()
    start, end = date_bounds(params)
    graph = graph or GraphMail.from_settings()
    addresses = [a.lower() for a in params.get('addresses', [])]
    mailboxes = [m.lower() for m in params.get('mailboxes', [])]
    names = params.get('names', [])
    matters = params.get('matters', [])

    candidates = {}
    stats = {'by_system': 0, 'by_address': 0, 'by_matter': 0, 'unresolved': 0, 'strict_dropped': 0}
    lookup_order = []
    for address in mailboxes + [m['address'] for m in shared_mailboxes()]:
        if address not in lookup_order:
            lookup_order.append(address)

    # Source A: emails the system already filed under the matter.
    if params.get('include_system_filed', True):
        rows = list(MatterEmails.objects.filter(
            file_number=matter, time__gte=start, time__lt=end).order_by('time'))
        _note(export, f'Checking {len(rows)} email{"s" if len(rows) != 1 else ""} filed under the matter', 0, len(rows))
        for index, row in enumerate(rows, 1):
            try_order = ([row.mailbox] if row.mailbox else []) + [m for m in lookup_order if m != row.mailbox]
            message, mailbox, folder = resolve_matter_email(graph, row, try_order)
            if message is None:
                stats['unresolved'] += 1
                merge_candidate(candidates, _unresolved_candidate(row, firm_domain))
            else:
                if merge_candidate(candidates, candidate_from_message(
                        message, mailbox, folder, 'system', firm_domain, row.id)):
                    stats['by_system'] += 1
            if index % 10 == 0 or index == len(rows):
                _note(export, f'Checked {index} of {len(rows)} emails filed under the matter', index, len(rows))
            if index % 25 == 0 and _cancelled(export):
                return

    # Source B: the client's addresses, strictly as sender or recipient.
    searches = [(m, a) for m in mailboxes for a in addresses]
    for index, (mailbox, address) in enumerate(searches, 1):
        _note(export, f'Searching {mailbox} ({index} of {len(searches)})', index - 1, len(searches))
        try:
            found = graph.search_participant(mailbox, address, start, end)
        except GraphMailError as exc:
            if exc.status in (403, 404):
                logger.warning('Correspondence export %s: mailbox %s not readable (%s)', export.id, mailbox, exc.code)
                continue
            raise
        for message in found:
            if not participants_match(message, [address]):
                stats['strict_dropped'] += 1
                continue
            if message.get('isDraft'):
                continue
            folder = graph.folder_name(mailbox, message.get('parentFolderId'))
            if folder.lower() in EXCLUDED_FOLDERS:
                continue
            if merge_candidate(candidates, candidate_from_message(message, mailbox, folder, 'address', firm_domain)):
                stats['by_address'] += 1
        if _cancelled(export):
            return

    # Source C (opt-in): matter code anywhere in subject or body.
    if params.get('matter_search') and matters:
        searches = [(m, c) for m in mailboxes for c in matters]
        for index, (mailbox, code) in enumerate(searches, 1):
            _note(export, f'Searching {mailbox} for the matter code ({index} of {len(searches)})')
            try:
                found = graph.search_kql(mailbox, code, start, end)
            except GraphMailError as exc:
                if exc.status in (403, 404):
                    continue
                raise
            for message in found:
                if message.get('isDraft'):
                    continue
                folder = graph.folder_name(mailbox, message.get('parentFolderId'))
                if folder.lower() in EXCLUDED_FOLDERS:
                    continue
                if merge_candidate(candidates, candidate_from_message(message, mailbox, folder, 'matter', firm_domain)):
                    stats['by_matter'] += 1

    ordered = sorted(candidates.values(), key=lambda c: c.get('received') or '')
    for candidate in ordered:
        apply_preview_flags(candidate, names, matters)
    receipts = sum(1 for c in ordered if c.get('report') in EXCLUDED_REPORT_TYPES)

    if _cancelled(export):
        return
    export.candidates = ordered
    export.selected_keys = [c['key'] for c in ordered if c['selected']]
    export.counts = {
        **stats,
        'candidates': len(ordered),
        'selected': len(export.selected_keys),
        'receipts': receipts,
        'with_attachments': sum(1 for c in ordered if c.get('has_attachments')),
        'flagged': sum(1 for c in ordered if c.get('flags')),
    }
    export.status = CorrespondenceExport.STATUS_PREVIEW
    export.discovered_at = timezone.now()
    export.progress_done = export.progress_total = 0
    export.progress_note = ''
    export.error = ''
    export.save()
