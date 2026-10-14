"""Runs correspondence export jobs: discovery (search) and build (download, render, store).

Where it runs is a setting: a cron worker in production, a background thread in
development, inline in tests. Progress is written to the model and polled by the
matter page.
"""
import html as html_mod
import logging
import os
import secrets
import threading
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import connection
from django.utils import timezone

from backend.models import CorrespondenceExport
from .classify import EXCLUDED_REPORT_TYPES, NON_DELIVERY, classify_by_class, classify_by_mime, is_automatic_reply
from .discovery import FOUND_BY_LABELS, REVIEW_FOLDERS, keyword_in, run_discovery
from .graph_mail import GraphMail, parse_graph_dt
from .index import excluded_csv, flagged_csv, index_csv, index_html, summary_text
from .mime import parse_message, subject_slug
from .render import RenderError, RenderWorker, Renderer, append_enclosures, clean_email_html, memo_html, merge_pdfs, strip_tags
from .storage import ExportStore, export_folder, temp_dir

logger = logging.getLogger('backend')

FLAG_NO_MATCH = 'No client name or matter ref found - review'


# ----------------------------------------------------------------------------- scheduling

def start_async(export):
    """Hand a discovering/queued export to the configured runner."""
    mode = getattr(settings, 'CORRESPONDENCE_EXPORT_RUNNER', 'cron')
    if mode == 'sync':
        run_job(export.id)
    elif mode == 'thread':
        thread = threading.Thread(target=_thread_main, args=(export.id,), daemon=True,
                                  name=f'correspondence-export-{export.id}')
        thread.start()
    # 'cron': the django-crontab worker picks it up within a minute.


def _thread_main(export_id):
    try:
        run_job(export_id)
    finally:
        connection.close()


def run_job(export_id):
    export = CorrespondenceExport.objects.select_related('matter').get(id=export_id)
    if export.status == CorrespondenceExport.STATUS_DISCOVERING:
        _guarded(export, run_discovery, 'Search failed')
    elif export.status == CorrespondenceExport.STATUS_QUEUED:
        _guarded(export, run_export, 'Export failed')


def _guarded(export, func, prefix):
    try:
        func(export)
    except Exception as exc:  # the job must always end in a terminal status
        logger.exception('Correspondence export %s: %s', export.id, prefix)
        fail(export, f'{prefix}: {describe(exc)}')


def describe(exc):
    text = str(exc)
    if not text:
        return type(exc).__name__
    return f'{type(exc).__name__}: {text[:300]}'


def fail(export, message):
    export.refresh_from_db(fields=['status'])
    if export.status == CorrespondenceExport.STATUS_CANCELLED:
        return
    export.status = CorrespondenceExport.STATUS_FAILED
    export.error = message[:2000]
    export.finished_at = timezone.now()
    export.save(update_fields=['status', 'error', 'finished_at', 'updated_at'])


def process_pending(max_jobs=3):
    """Cron entry: run queued work oldest first. Returns how many jobs ran."""
    ran = 0
    attempted = set()
    while ran < max_jobs:
        job = CorrespondenceExport.objects.filter(
            status__in=CorrespondenceExport.WORK_STATUSES).exclude(id__in=attempted).order_by('created_at').first()
        if job is None:
            break
        attempted.add(job.id)
        claimed = CorrespondenceExport.objects.filter(id=job.id, status=job.status).update(
            worker_heartbeat=timezone.now())
        if not claimed:
            continue
        run_job(job.id)
        ran += 1
    return ran


def mark_stale_jobs():
    """A discovering/running export whose worker stopped reporting is failed, so the page can offer a retry."""
    minutes = getattr(settings, 'CORRESPONDENCE_EXPORT_STALE_MINUTES', 20)
    cutoff = timezone.now() - timedelta(minutes=minutes)
    stale = CorrespondenceExport.objects.filter(
        status__in=(CorrespondenceExport.STATUS_DISCOVERING, CorrespondenceExport.STATUS_RUNNING),
        worker_heartbeat__lt=cutoff)
    count = 0
    for export in stale:
        fail(export, 'The worker stopped before finishing. Try again.')
        count += 1
    return count


def heartbeat(export, done=None, total=None, note=None):
    export.worker_heartbeat = timezone.now()
    fields = ['worker_heartbeat']
    if done is not None:
        export.progress_done = done
        fields.append('progress_done')
    if total is not None:
        export.progress_total = total
        fields.append('progress_total')
    if note is not None:
        export.progress_note = note[:255]
        fields.append('progress_note')
    export.save(update_fields=fields)


# ----------------------------------------------------------------------------- build

@dataclass
class Item:
    no: int
    candidate: dict
    local_dt: datetime
    enclosures: list = field(default_factory=list)
    pdf: bytes | None = None
    eml: bytes | None = None
    matched: list = field(default_factory=list)
    flags: list = field(default_factory=list)
    pdf_name: str = ''
    enc_dir: str = ''
    eml_name: str = ''


def build_item(no, candidate, raw, params, owner, printed, renderer, tz, fetch_error=None, report=None):
    received = parse_graph_dt(candidate.get('received')) or timezone.now()
    sent = parse_graph_dt(candidate.get('sent')) or received
    local = received.astimezone(tz)
    item = Item(no=no, candidate=candidate, local_dt=local)
    stamp = local.strftime('%Y-%m-%d_%H%M')
    item.pdf_name = f"{no:03d}_{stamp}_{subject_slug(candidate.get('subject', ''))}.pdf"
    item.enc_dir = f'{no:03d}_enclosures'
    item.eml_name = f'{no:03d}_{stamp}.eml'

    folder = candidate.get('folder') or ''
    if folder.lower() in REVIEW_FOLDERS:
        item.flags.append(f'Found in {folder}')
    if report == NON_DELIVERY:
        item.flags.append('Non-delivery report (bounce)')
    elif report:
        item.flags.append(report[0].upper() + report[1:])
    if is_automatic_reply(candidate.get('msg_class', '')):
        item.flags.append('Automatic reply')
    if raw is None:
        reason = type(fetch_error).__name__ if fetch_error else 'unknown'
        item.flags.append(f'Download failed ({reason}) - no PDF')
        return item

    item.eml = raw
    try:
        parsed = parse_message(raw)
    except Exception as exc:
        item.flags.append(f'Could not parse email ({type(exc).__name__}) - original .eml only')
        return item
    item.enclosures = parsed.enclosures

    # Keywords are looked for in both the plain-text and the HTML body: Outlook's
    # plain alternative does not always carry everything the HTML shows.
    html_text = strip_tags(parsed.html) if parsed.html else ''
    body_text = parsed.text or html_text
    haystack = '\n'.join([candidate.get('subject', ''), parsed.text or '', html_text,
                          ' '.join(e.name for e in parsed.enclosures)])
    names, matters = params.get('names', []), params.get('matters', [])
    item.matched = keyword_in(haystack, names, matters)
    if (names or matters) and not item.matched:
        item.flags.append(FLAG_NO_MATCH)

    rows = [
        ('From:', html_mod.escape(candidate.get('from', ''))),
        ('Sent:', sent.astimezone(tz).strftime('%d %B %Y %H:%M')),
        ('To:', html_mod.escape(candidate.get('to', ''))),
        ('Cc:', html_mod.escape(candidate.get('cc', ''))),
        ('Subject:', html_mod.escape(candidate.get('subject', ''))),
        ('Attachments:', html_mod.escape('; '.join(e.name for e in parsed.enclosures))),
    ]
    if parsed.html:
        extra_css, body_html = clean_email_html(parsed.html)
    else:
        extra_css, body_html = '', f"<pre>{html_mod.escape(parsed.text or '')}</pre>"
    try:
        email_pdf = renderer.pdf(memo_html(owner, printed, rows, body_html, extra_css))
    except Exception:
        try:
            email_pdf = renderer.pdf(memo_html(owner, printed, rows, f'<pre>{html_mod.escape(body_text)}</pre>'))
            item.flags.append('HTML layout failed - body rendered as plain text')
        except Exception as exc:
            item.flags.append(f'PDF render failed ({type(exc).__name__}) - original .eml only')
            return item

    if params.get('append_pdf_enclosures', True) and parsed.enclosures:
        item.pdf, extra_flags = append_enclosures(renderer, email_pdf, parsed.enclosures, owner, printed)
        item.flags.extend(extra_flags)
    else:
        item.pdf = email_pdf
        for enc in parsed.enclosures:
            enc.note = 'saved as file only'
    return item


def result_row(item):
    candidate = item.candidate
    return {
        'no': f'{item.no:03d}',
        'date': item.local_dt.strftime('%d/%m/%Y'),
        'time': item.local_dt.strftime('%H:%M'),
        'direction': candidate.get('direction', ''),
        'from': candidate.get('from', ''),
        'to': candidate.get('to', ''),
        'cc': candidate.get('cc', ''),
        'subject': candidate.get('subject', ''),
        'attachments': '; '.join(e.name + (f' [{e.note}]' if e.note else '') for e in item.enclosures),
        'attachment_count': str(len(item.enclosures)),
        'found_in': '; '.join(candidate.get('locations', [])),
        'found_by': ' + '.join(FOUND_BY_LABELS.get(s, s) for s in candidate.get('found_by', [])),
        'matched': '; '.join(item.matched),
        'flags': '; '.join(item.flags),
        'pdf_name': item.pdf_name if item.pdf else '',
        'enc_dir': item.enc_dir if item.enclosures else '',
        'eml_name': item.eml_name if item.eml else '',
        'enclosure_files': [e.name for e in item.enclosures],
    }


def excluded_row(candidate, report, tz):
    received = parse_graph_dt(candidate.get('received')) or timezone.now()
    local = received.astimezone(tz)
    return {
        'date': local.strftime('%d/%m/%Y'),
        'time': local.strftime('%H:%M'),
        'direction': candidate.get('direction', ''),
        'from': candidate.get('from', ''),
        'to': candidate.get('to', ''),
        'subject': candidate.get('subject', ''),
        'type': report,
        'found_in': '; '.join(candidate.get('locations', [])),
    }


def _summary_lines(export, params, results, excluded, generated, counts):
    matter = export.matter
    return [
        'EMAIL EXPORT SUMMARY',
        f'Matter: {matter.file_number} ({matter.all_client_names})',
        f"Generated: {generated.strftime('%d/%m/%Y %H:%M %Z')} by {export.requested_by or 'unknown'}",
        f"Email addresses: {', '.join(params.get('addresses', [])) or 'none'}",
        f"Date range (inclusive, {settings.TIME_ZONE}): {params.get('date_from')} to {params.get('date_to')}",
        f"Mailboxes searched (all folders except Drafts and Junk): {', '.join(params.get('mailboxes', []))}",
        f"Name / matter keywords (used for flagging only): {', '.join(params.get('names', []) + params.get('matters', [])) or 'none'}",
        'Selection: emails filed under the matter by the system plus emails where a listed address is '
        'the sender or a To/Cc/Bcc recipient; reviewed and ticked before building.'
        + (' Emails carrying the matter code in subject or body were also searched for.' if params.get('matter_search') else ''),
        f"Emails exported: {len(results)} (filed under matter: {counts.get('by_system_exported', 0)}; "
        f"by client address only: {counts.get('by_address_only_exported', 0)})",
        f"Emails with enclosures: {sum(1 for r in results if r.get('attachment_count') not in ('', '0'))}",
        f"Flagged for review: {sum(1 for r in results if r.get('flags'))} (see 00_flagged_for_review.csv)",
        f'Read / delivery receipts left out: {len(excluded)} (listed in 00_excluded_receipts.csv)',
        '',
        'Layout: NNN_<date>_<time>_<subject>.pdf is the email in Outlook memo style, with PDF and image enclosures appended;',
        '        NNN_enclosures/ holds every enclosure as an original file; originals/ holds the original .eml messages.',
    ]


def run_export(export, graph=None, renderer=None):
    params = export.params or {}
    matter = export.matter
    tz = ZoneInfo(settings.TIME_ZONE)
    graph = graph or GraphMail.from_settings()
    selected = set(export.selected_keys or [])
    by_key = {c['key']: c for c in export.candidates or []}
    items_in = sorted((by_key[k] for k in selected if k in by_key and by_key[k].get('graph_id')),
                      key=lambda c: c.get('received') or '')

    export.status = CorrespondenceExport.STATUS_RUNNING
    export.started_at = timezone.now()
    export.error = ''
    export.progress_done = 0
    export.progress_total = len(items_in)
    export.progress_note = 'Starting'
    export.worker_heartbeat = timezone.now()
    export.storage_folder = export_folder(matter, export.id)
    export.save()

    store = ExportStore(export.storage_folder)
    now_local = timezone.now().astimezone(tz)
    printed = now_local.strftime('%d %B %Y')
    header_name = params.get('header_name') or getattr(settings, 'CORRESPONDENCE_EXPORT_HEADER_NAME', '')
    include_receipts = bool(params.get('include_receipts'))
    combined = bool(params.get('combined_pdf'))
    include_originals = params.get('include_originals', True)

    worker = None
    if renderer is None:
        fontconfig = getattr(settings, 'CORRESPONDENCE_EXPORT_FONTCONFIG_FILE', '')
        if fontconfig and os.path.isfile(fontconfig):
            os.environ['FONTCONFIG_FILE'] = fontconfig
        worker = RenderWorker()
        worker.start()
        renderer = Renderer(worker)

    top = f"{matter.file_number}_emails_{params.get('date_from')}_to_{params.get('date_to')}"
    zip_name = f'{top}.zip'
    zip_tmp = os.path.join(temp_dir(), f'correspondence-export-{export.id}-{secrets.token_hex(4)}.zip')
    results, excluded, combined_blobs = [], [], []
    enclosure_total = failed = 0
    by_system_exported = by_address_only_exported = 0
    number = 0

    def zinfo(name, when):
        info = zipfile.ZipInfo(f'{top}/{name}', date_time=when.timetuple()[:6])
        info.compress_type = zipfile.ZIP_DEFLATED
        return info

    try:
        with zipfile.ZipFile(zip_tmp, 'w', zipfile.ZIP_DEFLATED) as zf:
            def add(name, data, when):
                zf.writestr(zinfo(name, when), data)
                store.put(name, data)

            for index, candidate in enumerate(items_in, 1):
                msg_class = candidate.get('msg_class', '')
                report = classify_by_class(msg_class)
                raw, fetch_error = None, None
                if not (report in EXCLUDED_REPORT_TYPES and not include_receipts):
                    try:
                        raw = graph.get_mime(candidate['mailbox'], candidate['graph_id'])
                    except Exception as exc:
                        fetch_error = exc
                        logger.warning('Correspondence export %s: download failed for item %s: %s',
                                       export.id, index, describe(exc))
                    if report is None and raw:
                        report = classify_by_mime(raw)
                if report in EXCLUDED_REPORT_TYPES and not include_receipts:
                    excluded.append(excluded_row(candidate, report, tz))
                else:
                    number += 1
                    owner = header_name or graph.user_display_name(candidate['mailbox'])
                    item = build_item(number, candidate, raw, params, owner, printed, renderer, tz,
                                      fetch_error=fetch_error, report=report)
                    if item.pdf:
                        add(item.pdf_name, item.pdf, item.local_dt)
                        if combined:
                            combined_blobs.append(item.pdf)
                    else:
                        failed += 1
                    for enc in item.enclosures:
                        add(f'{item.enc_dir}/{enc.name}', enc.data, item.local_dt)
                    if item.eml and include_originals:
                        add(f'originals/{item.eml_name}', item.eml, item.local_dt)
                    enclosure_total += len(item.enclosures)
                    sources = candidate.get('found_by', [])
                    if 'system' in sources:
                        by_system_exported += 1
                    elif sources == ['address']:
                        by_address_only_exported += 1
                    results.append(result_row(item))
                heartbeat(export, done=index, note=f'Rendered {index} of {len(items_in)}')

            counts = {
                'selected': len(items_in), 'exported': len(results), 'enclosures': enclosure_total,
                'flagged': sum(1 for r in results if r.get('flags')), 'receipts_excluded': len(excluded),
                'failed': failed, 'by_system_exported': by_system_exported,
                'by_address_only_exported': by_address_only_exported,
                'renderer_restarts': worker.crashes if worker else 0,
            }
            heartbeat(export, note='Writing the index')
            lines = _summary_lines(export, params, results, excluded, now_local, counts)
            add('00_summary.txt', summary_text(lines), now_local)
            add('00_index.csv', index_csv(results), now_local)
            add('00_index.html', index_html(top, lines[1:12], results), now_local)
            add('00_flagged_for_review.csv', flagged_csv(results), now_local)
            add('00_excluded_receipts.csv', excluded_csv(excluded), now_local)
            if combined and combined_blobs:
                try:
                    add('00_all_emails_combined.pdf', merge_pdfs(combined_blobs), now_local)
                except Exception as exc:
                    logger.warning('Correspondence export %s: combined PDF failed: %s', export.id, describe(exc))
        heartbeat(export, note='Uploading the zip')
        store.put_file(zip_name, zip_tmp)
        counts['zip_bytes'] = os.path.getsize(zip_tmp)
    finally:
        if worker is not None:
            worker.close()
        try:
            os.remove(zip_tmp)
        except OSError:
            pass

    export.refresh_from_db(fields=['status'])
    if export.status == CorrespondenceExport.STATUS_CANCELLED:
        return
    export.results = results
    export.excluded = excluded
    export.counts = {**(export.counts or {}), **counts}
    export.zip_name = zip_name
    export.folder_web_url = store.web_url('')
    export.zip_web_url = store.web_url(zip_name)
    export.status = CorrespondenceExport.STATUS_DONE
    export.finished_at = timezone.now()
    export.progress_done = export.progress_total = len(items_in)
    export.progress_note = ''
    export.save()
