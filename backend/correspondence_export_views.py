"""Email export, under a matter's correspondence.

A fee earner starts an export from the matter: the system searches the chosen
mailboxes for the matter's emails (filed under the matter, or to/from the
client's addresses), shows the list for review, then builds memo-style PDFs
with enclosures into the matter's SharePoint folder. See backend/correspondence_export.
"""
import mimetypes
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .audit import log_created, log_field_change
from .correspondence_export import mailboxes as mailbox_config
from .correspondence_export.classify import EXCLUDED_REPORT_TYPES
from .correspondence_export.discovery import FOUND_BY_LABELS
from .correspondence_export.graph_mail import parse_graph_dt
from .correspondence_export.runner import mark_stale_jobs, start_async
from .correspondence_export.sharing import (ExportSharingError, create_export_share_link,
                                            revoke_export_share_link)
from .correspondence_export.storage import ExportStore
from .models import CorrespondenceExport, WIP

MAX_ADDRESSES = 20
MAX_MAILBOXES = 30
POLL_SECONDS = 2.5


# ----------------------------------------------------------------------------- helpers

def _matter(file_number):
    matter = WIP.objects.select_related('fee_earner', 'matter_type', 'file_status', 'client1',
                                        'other_side').filter(file_number=file_number).first()
    if matter is None:
        raise Http404('Matter not found')
    return matter


def _export(matter, export_id):
    return get_object_or_404(CorrespondenceExport.objects.select_related('requested_by', 'share_created_by',
                                                                         'transfer_recorded_by'),
                             id=export_id, matter=matter)


def _tz():
    return ZoneInfo(settings.TIME_ZONE)


def _parse_date(value):
    for fmt in ('%Y-%m-%d', '%d/%m/%Y'):
        try:
            return datetime.strptime((value or '').strip(), fmt).date()
        except ValueError:
            continue
    return None


def _checkbox(data, name, default=False):
    if name not in data:
        return default
    return (data.get(name) or '').lower() in ('1', 'on', 'true', 'yes')


def _mailbox_groups(matter, selected):
    selected = {s.lower() for s in selected}
    shared = [{'address': m['address'], 'label': m['label'], 'checked': m['address'] in selected}
              for m in mailbox_config.shared_mailboxes()]
    staff = [{'address': m['address'], 'label': m['label'], 'checked': m['address'] in selected}
             for m in mailbox_config.staff_mailboxes()]
    known = {m['address'] for m in shared} | {m['address'] for m in staff}
    extra = [s for s in selected if s not in known]
    return shared, staff, extra


def _form_context(matter, data=None, errors=None):
    """Context for the new-export form; `data` is the submitted form on a validation error."""
    if data is None:
        addresses = mailbox_config.default_addresses_for(matter)
        selected_mailboxes = mailbox_config.default_mailboxes_for(matter)
        date_from = mailbox_config.default_date_from(matter)
        date_to = date.today()
        options = {'include_system_filed': True, 'append_pdf_enclosures': True,
                   'include_originals': True, 'combined_pdf': False, 'matter_search': False,
                   'include_receipts': False}
        header_name = getattr(settings, 'CORRESPONDENCE_EXPORT_HEADER_NAME', '')
    else:
        addresses = mailbox_config.parse_address_list(data.get('addresses', ''))
        selected_mailboxes = [m.lower() for m in data.getlist('mailboxes')] + \
            mailbox_config.parse_address_list(data.get('extra_mailboxes', ''))
        date_from = _parse_date(data.get('date_from')) or mailbox_config.default_date_from(matter)
        date_to = _parse_date(data.get('date_to')) or date.today()
        options = {key: _checkbox(data, key) for key in (
            'include_system_filed', 'append_pdf_enclosures', 'include_originals', 'combined_pdf',
            'matter_search', 'include_receipts')}
        header_name = (data.get('header_name') or '').strip()
    shared, staff, extra = _mailbox_groups(matter, selected_mailboxes)
    suggested = [s for s in mailbox_config.suggested_addresses_for(matter) if s['address'] not in addresses]
    return {
        'addresses': addresses,
        'suggested_addresses': suggested,
        'shared_mailboxes': shared,
        'staff_mailboxes': staff,
        'extra_mailboxes': ', '.join(extra),
        'date_from': date_from.isoformat(),
        'date_to': date_to.isoformat(),
        'options': options,
        'header_name': header_name,
        'name_keywords': mailbox_config.name_keywords_for(matter),
        'errors': errors or {},
    }


def _validate_params(matter, data):
    errors = {}
    addresses = mailbox_config.parse_address_list(data.get('addresses', ''))
    bad = [a for a in addresses if not mailbox_config.is_email(a)]
    if bad:
        errors['addresses'] = f"Not an email address: {', '.join(bad[:3])}"
    if len(addresses) > MAX_ADDRESSES:
        errors['addresses'] = f'Up to {MAX_ADDRESSES} addresses per export.'
    mailboxes = []
    for value in [m.lower() for m in data.getlist('mailboxes')] + \
            mailbox_config.parse_address_list(data.get('extra_mailboxes', '')):
        if value not in mailboxes:
            mailboxes.append(value)
    bad_boxes = [m for m in mailboxes if not mailbox_config.is_email(m)]
    if bad_boxes:
        errors['mailboxes'] = f"Not a mailbox address: {', '.join(bad_boxes[:3])}"
    elif not mailboxes:
        errors['mailboxes'] = 'Choose at least one mailbox to search.'
    elif len(mailboxes) > MAX_MAILBOXES:
        errors['mailboxes'] = f'Up to {MAX_MAILBOXES} mailboxes per export.'
    include_system = _checkbox(data, 'include_system_filed')
    if not addresses and not include_system:
        errors['addresses'] = 'Add at least one address, or include the emails filed under the matter.'
    date_from, date_to = _parse_date(data.get('date_from')), _parse_date(data.get('date_to'))
    if not date_from or not date_to:
        errors['dates'] = 'Enter both dates.'
    elif date_to < date_from:
        errors['dates'] = 'The end date is before the start date.'
    elif date_to > date.today() + timedelta(days=1):
        errors['dates'] = 'The end date is in the future.'
    if errors:
        return None, errors
    params = {
        'addresses': addresses,
        'mailboxes': mailboxes,
        'date_from': date_from.isoformat(),
        'date_to': date_to.isoformat(),
        'names': mailbox_config.name_keywords_for(matter),
        'matters': [matter.file_number],
        'header_name': (data.get('header_name') or '').strip()[:120],
        'include_system_filed': include_system,
        'append_pdf_enclosures': _checkbox(data, 'append_pdf_enclosures'),
        'include_originals': _checkbox(data, 'include_originals'),
        'combined_pdf': _checkbox(data, 'combined_pdf'),
        'matter_search': _checkbox(data, 'matter_search'),
        'include_receipts': _checkbox(data, 'include_receipts'),
    }
    return params, {}


def _local(iso_value, tz):
    parsed = parse_graph_dt(iso_value)
    return parsed.astimezone(tz) if parsed else None


def _preview_rows(export):
    tz = _tz()
    selected = set(export.selected_keys or [])
    rows = []
    for candidate in export.candidates or []:
        when = _local(candidate.get('received'), tz)
        rows.append({
            'key': candidate['key'],
            'date': when.strftime('%d/%m/%Y') if when else '',
            'time': when.strftime('%H:%M') if when else '',
            'direction': candidate.get('direction', ''),
            'from': candidate.get('from', ''),
            'to': candidate.get('to', ''),
            'cc': candidate.get('cc', ''),
            'subject': candidate.get('subject', ''),
            'has_attachments': candidate.get('has_attachments', False),
            'found_by': [FOUND_BY_LABELS.get(s, s) for s in candidate.get('found_by', [])],
            'locations': candidate.get('locations', []),
            'flags': candidate.get('flags', []),
            'is_receipt': candidate.get('report') in EXCLUDED_REPORT_TYPES,
            'unavailable': not candidate.get('graph_id'),
            'selected': candidate['key'] in selected,
        })
    return rows


def _result_rows(export):
    rows = []
    for row in export.results or []:
        rows.append({
            **row,
            'flag_list': [f for f in (row.get('flags') or '').split('; ') if f],
            'enclosure_links': [{'name': name, 'path': f"{row.get('enc_dir')}/{name}"}
                                for name in row.get('enclosure_files', [])],
            'eml_path': f"originals/{row['eml_name']}" if row.get('eml_name') else '',
        })
    return rows


def _panel_context(request, matter, export):
    counts = export.counts or {}
    context = {
        'matter': matter,
        'file_number': matter.file_number,
        'export': export,
        'counts': counts,
        'poll_seconds': POLL_SECONDS,
        'runner_mode': getattr(settings, 'CORRESPONDENCE_EXPORT_RUNNER', 'cron'),
        'use_sharepoint': bool(settings.USE_SHAREPOINT),
        'link_scope': getattr(settings, 'BUNDLE_SHARE_LINK_SCOPE', 'anonymous'),
        'share_expiry_days': getattr(settings, 'BUNDLE_SHARE_LINK_EXPIRY_DAYS', 30),
        'found_by_labels': FOUND_BY_LABELS,
    }
    if export.status == CorrespondenceExport.STATUS_PREVIEW:
        rows = _preview_rows(export)
        context['rows'] = rows
        context['selected_count'] = sum(1 for r in rows if r['selected'])
        context['flagged_count'] = sum(1 for r in rows if r['flags'])
        context['receipt_count'] = sum(1 for r in rows if r['is_receipt'])
    elif export.status == CorrespondenceExport.STATUS_DONE:
        rows = _result_rows(export)
        context['rows'] = rows
        context['flagged_rows'] = [r for r in rows if r['flag_list']]
        context['zip_mb'] = round((counts.get('zip_bytes') or 0) / 1_000_000, 1)
    if export.started_at and export.status == CorrespondenceExport.STATUS_RUNNING:
        context['running_seconds'] = int((timezone.now() - export.started_at).total_seconds())
    return context


def _panel_html(request, matter, export):
    from django.template.loader import render_to_string
    return render_to_string('correspondence_export/_panel.html', _panel_context(request, matter, export),
                            request=request)


def _history(matter):
    return CorrespondenceExport.objects.filter(matter=matter).select_related('requested_by')[:20]


# ----------------------------------------------------------------------------- pages

@login_required
def correspondence_exports(request, file_number):
    matter = _matter(file_number)
    mark_stale_jobs()
    context = {
        'matter': matter,
        'file_number': file_number,
        'exports': _history(matter),
        'form': _form_context(matter),
        'runner_mode': getattr(settings, 'CORRESPONDENCE_EXPORT_RUNNER', 'cron'),
    }
    return render(request, 'correspondence_export/list.html', context)


@login_required
@require_POST
def correspondence_export_create(request, file_number):
    matter = _matter(file_number)
    params, errors = _validate_params(matter, request.POST)
    if errors:
        context = {
            'matter': matter,
            'file_number': file_number,
            'exports': _history(matter),
            'form': _form_context(matter, request.POST, errors),
            'runner_mode': getattr(settings, 'CORRESPONDENCE_EXPORT_RUNNER', 'cron'),
        }
        return render(request, 'correspondence_export/list.html', context, status=400)
    export = CorrespondenceExport.objects.create(
        matter=matter, requested_by=request.user, params=params,
        status=CorrespondenceExport.STATUS_DISCOVERING, worker_heartbeat=timezone.now())
    log_created(request.user, export, (
        f"Email export started: {len(params['addresses'])} address(es), "
        f"{len(params['mailboxes'])} mailbox(es), {params['date_from']} to {params['date_to']}"))
    start_async(export)
    return redirect('correspondence_export_detail', file_number=file_number, export_id=export.id)


@login_required
def correspondence_export_detail(request, file_number, export_id):
    matter = _matter(file_number)
    export = _export(matter, export_id)
    mark_stale_jobs()
    export.refresh_from_db()
    context = _panel_context(request, matter, export)
    context['panel_html'] = _panel_html(request, matter, export)
    return render(request, 'correspondence_export/detail.html', context)


@login_required
def correspondence_export_panel(request, file_number, export_id):
    """The polled part of the page: stage strip + status-specific content."""
    matter = _matter(file_number)
    export = _export(matter, export_id)
    if export.is_transient:
        mark_stale_jobs()
        export.refresh_from_db()
    response = HttpResponse(_panel_html(request, matter, export))
    response['X-Export-Status'] = export.status
    response['X-Export-Stage'] = str(export.stage)
    response['Cache-Control'] = 'no-store'
    return response


# ----------------------------------------------------------------------------- actions

@login_required
@require_POST
def correspondence_export_generate(request, file_number, export_id):
    matter = _matter(file_number)
    export = _export(matter, export_id)
    if export.status != CorrespondenceExport.STATUS_PREVIEW:
        messages.error(request, 'This export is not waiting for review.')
        return redirect('correspondence_export_detail', file_number=file_number, export_id=export.id)
    available = {c['key'] for c in export.candidates or [] if c.get('graph_id')}
    chosen = [k for k in request.POST.getlist('selected') if k in available]
    if not chosen:
        messages.error(request, 'Tick at least one email to build the export.')
        return redirect('correspondence_export_detail', file_number=file_number, export_id=export.id)
    export.selected_keys = chosen
    export.status = CorrespondenceExport.STATUS_QUEUED
    export.error = ''
    export.worker_heartbeat = timezone.now()
    export.counts = {**(export.counts or {}), 'selected': len(chosen)}
    export.save()
    log_field_change(request.user, export, 'build requested', '', f'{len(chosen)} email(s) selected')
    start_async(export)
    return redirect('correspondence_export_detail', file_number=file_number, export_id=export.id)


@login_required
@require_POST
def correspondence_export_cancel(request, file_number, export_id):
    matter = _matter(file_number)
    export = _export(matter, export_id)
    if export.status in (CorrespondenceExport.STATUS_DISCOVERING, CorrespondenceExport.STATUS_PREVIEW,
                         CorrespondenceExport.STATUS_QUEUED):
        export.status = CorrespondenceExport.STATUS_CANCELLED
        export.finished_at = timezone.now()
        export.save(update_fields=['status', 'finished_at', 'updated_at'])
        log_field_change(request.user, export, 'status', 'in progress', 'cancelled')
        messages.success(request, 'Export cancelled.')
    else:
        messages.error(request, 'This export can no longer be cancelled.')
    return redirect('correspondence_exports', file_number=file_number)


@login_required
@require_POST
def correspondence_export_retry(request, file_number, export_id):
    matter = _matter(file_number)
    export = _export(matter, export_id)
    if export.status != CorrespondenceExport.STATUS_FAILED:
        messages.error(request, 'Only a failed export can be retried.')
        return redirect('correspondence_export_detail', file_number=file_number, export_id=export.id)
    if export.candidates and export.selected_keys:
        export.status = CorrespondenceExport.STATUS_QUEUED
    else:
        export.status = CorrespondenceExport.STATUS_DISCOVERING
    export.error = ''
    export.finished_at = None
    export.worker_heartbeat = timezone.now()
    export.save()
    log_field_change(request.user, export, 'status', 'failed', export.status)
    start_async(export)
    return redirect('correspondence_export_detail', file_number=file_number, export_id=export.id)


def _safe_relpath(relpath):
    relpath = (relpath or '').replace('\\', '/').strip('/')
    if not relpath or '..' in relpath.split('/') or relpath.startswith('/'):
        raise Http404('File not found')
    return relpath


def _serve(export, relpath, as_attachment):
    if not export.storage_folder:
        raise Http404('File not found')
    store = ExportStore(export.storage_folder)
    if store.use_sharepoint:
        url = store.download_url(relpath)
        if not url:
            raise Http404('File not found')
        return redirect(url)
    path = store.local_path(relpath)
    if not path.is_file():
        raise Http404('File not found')
    content_type = mimetypes.guess_type(str(path))[0] or 'application/octet-stream'
    return FileResponse(open(path, 'rb'), as_attachment=as_attachment, filename=os.path.basename(path),
                        content_type=content_type)


@login_required
def correspondence_export_download(request, file_number, export_id):
    matter = _matter(file_number)
    export = _export(matter, export_id)
    if export.status != CorrespondenceExport.STATUS_DONE or not export.zip_name:
        raise Http404('The zip is not ready')
    return _serve(export, export.zip_name, as_attachment=True)


@login_required
def correspondence_export_file(request, file_number, export_id, relpath):
    matter = _matter(file_number)
    export = _export(matter, export_id)
    if export.status != CorrespondenceExport.STATUS_DONE:
        raise Http404('The export is not ready')
    return _serve(export, _safe_relpath(relpath), as_attachment=False)


@login_required
@require_POST
def correspondence_export_share_create(request, file_number, export_id):
    matter = _matter(file_number)
    export = _export(matter, export_id)
    if export.status != CorrespondenceExport.STATUS_DONE:
        messages.error(request, 'The export is not ready to share.')
        return redirect('correspondence_export_detail', file_number=file_number, export_id=export.id)
    use_password = _checkbox(request.POST, 'use_password', default=True)
    try:
        link = create_export_share_link(export, use_password=use_password, created_by=request.user)
    except ExportSharingError as exc:
        messages.error(request, str(exc))
    else:
        log_field_change(request.user, export, 'share link', '', f"created, expires {link['expires_at']:%d/%m/%Y}")
        messages.success(request, 'Share link created.')
    return redirect('correspondence_export_detail', file_number=file_number, export_id=export.id)


@login_required
@require_POST
def correspondence_export_share_revoke(request, file_number, export_id):
    matter = _matter(file_number)
    export = _export(matter, export_id)
    try:
        revoked = revoke_export_share_link(export)
    except ExportSharingError as exc:
        messages.error(request, str(exc))
    else:
        if revoked:
            log_field_change(request.user, export, 'share link', 'active', 'revoked')
            messages.success(request, 'Share link revoked.')
    return redirect('correspondence_export_detail', file_number=file_number, export_id=export.id)


@login_required
@require_POST
def correspondence_export_transfer(request, file_number, export_id):
    matter = _matter(file_number)
    export = _export(matter, export_id)
    data = request.POST
    before = {
        'transfer_to': export.transfer_to, 'transfer_contact': export.transfer_contact,
        'client_authority_date': export.client_authority_date, 'lien_checked': export.lien_checked,
        'retention_copy_kept': export.retention_copy_kept, 'transfer_notes': export.transfer_notes,
    }
    export.transfer_to = (data.get('transfer_to') or '').strip()[:255]
    export.transfer_contact = (data.get('transfer_contact') or '').strip()[:255]
    export.client_authority_date = _parse_date(data.get('client_authority_date'))
    export.lien_checked = _checkbox(data, 'lien_checked')
    export.retention_copy_kept = _checkbox(data, 'retention_copy_kept')
    export.transfer_notes = (data.get('transfer_notes') or '').strip()[:4000]
    export.transfer_recorded_by = request.user
    export.transfer_recorded_at = timezone.now()
    export.save()
    for field, old in before.items():
        new = getattr(export, field)
        if old != new:
            log_field_change(request.user, export, field, old, new)
    messages.success(request, 'File transfer record saved.')
    return redirect('correspondence_export_detail', file_number=file_number, export_id=export.id)
