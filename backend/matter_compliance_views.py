"""Matter-home actions for per-matter-per-client compliance: mark the matter as
under an NCBA, record the engagement checks (terms / NCBA / source of funds /
PEP) for one client on one matter, upload the supporting documents — identity
documents onto the client record, engagement documents (including an AML/ID
check after the file is open) against the matter-client — and capture
conveyancing transaction detail."""
import mimetypes
import os
from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from .audit import log_created, log_field_change, snapshot_key_document
from .matter_compliance import IDENTITY_CATEGORIES
from .models import (ClientKeyDocument, ConveyancingDetails, MatterClient,
                     MatterClientDocument, WIP)

ALLOWED_DOC_EXTENSIONS = ('.pdf', '.jpg', '.jpeg', '.png', '.heic', '.doc', '.docx')
MAX_DOC_BYTES = 25 * 1024 * 1024
DOC_CATEGORIES = dict(MatterClientDocument.CATEGORY_CHOICES)
IDENTITY_LABELS = dict(ClientKeyDocument.DOCUMENT_CATEGORY_CHOICES)


def _parse_date(value):
    value = (value or '').strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        return None


def _checked(request, name):
    return request.POST.get(name) in ('1', 'on', 'true', 'True')


def _upload_problem(upload):
    """Why this upload can't be accepted, or None."""
    if not upload:
        return 'Choose a file to upload.'
    if os.path.splitext(upload.name)[1].lower() not in ALLOWED_DOC_EXTENSIONS:
        return 'Allowed file types: PDF, Word, JPG, PNG, HEIC.'
    if upload.size > MAX_DOC_BYTES:
        return 'File is too large (max 25MB).'
    return None


@login_required
@require_POST
def matter_save_ncba(request, file_number):
    """Record whether this matter is under an NCBA. When it is, every client on
    the file signs it (tracked per matter-client)."""
    matter = get_object_or_404(WIP, file_number=file_number)
    new_value = _checked(request, 'ncba_required')
    if new_value != matter.ncba_required:
        old_value = matter.ncba_required
        matter.ncba_required = new_value
        matter.save(update_fields=['ncba_required'])
        log_field_change(request.user, matter, 'ncba_required', old_value, new_value)
    messages.success(request, 'This matter is under an NCBA — each client signs it for this file.'
                     if new_value else 'This matter is not under an NCBA.')
    return redirect('home', file_number)


@login_required
@require_POST
def matter_save_client_compliance(request, file_number, mc_id):
    """Record the four engagement checks for one client on this matter."""
    mc = get_object_or_404(MatterClient, id=mc_id, matter__file_number=file_number)
    today = timezone.localdate()
    fields = []

    def flip(flag, date_field, by_field, checked):
        # Only stamp date/by on a False -> True transition; allow un-ticking.
        if checked and not getattr(mc, flag):
            setattr(mc, date_field, getattr(mc, date_field) or today)
            setattr(mc, by_field, request.user)
            fields.extend([date_field, by_field])
        setattr(mc, flag, checked)
        fields.append(flag)

    flip('terms_of_engagement_signed', 'terms_of_engagement_on', 'terms_of_engagement_by',
         _checked(request, 'terms_signed'))
    mc.terms_sent_on = _parse_date(request.POST.get('terms_sent_on'))
    mc.terms_received_on = _parse_date(request.POST.get('terms_received_on'))
    fields += ['terms_sent_on', 'terms_received_on']

    flip('ncba_signed', 'ncba_on', 'ncba_by', _checked(request, 'ncba_signed'))
    mc.ncba_sent_on = _parse_date(request.POST.get('ncba_sent_on'))
    mc.ncba_received_on = _parse_date(request.POST.get('ncba_received_on'))
    fields += ['ncba_sent_on', 'ncba_received_on']

    flip('source_of_funds_signed', 'source_of_funds_on', 'source_of_funds_by',
         _checked(request, 'sof_signed'))
    mc.source_of_funds_details = request.POST.get('sof_details', '').strip()[:255]
    fields.append('source_of_funds_details')

    flip('pep_signed', 'pep_on', 'pep_by', _checked(request, 'pep_signed'))

    mc.source = MatterClient.SOURCE_CAPTURED
    fields.append('source')
    mc.save(update_fields=list(set(fields)))
    messages.success(request, f'Compliance updated for {mc.client.name}.')
    return redirect('home', file_number)


@login_required
@require_POST
def matter_upload_client_doc(request, file_number, mc_id):
    """Upload a client-care document (or an AML/ID check) against a matter-client.
    An AML/ID check also refreshes the client's identity/AML status."""
    mc = get_object_or_404(MatterClient, id=mc_id, matter__file_number=file_number)
    category = request.POST.get('category', '')
    if category not in DOC_CATEGORIES:
        messages.error(request, 'Choose a document type.')
        return redirect('home', file_number)
    upload = request.FILES.get('document')
    problem = _upload_problem(upload)
    if problem:
        messages.error(request, problem)
        return redirect('home', file_number)

    issue = _parse_date(request.POST.get('issue_date'))
    expiry = _parse_date(request.POST.get('expiry_date'))
    MatterClientDocument.objects.create(
        matter_client=mc, category=category, file=upload,
        document_type=request.POST.get('document_type', '').strip(),
        document_reference=request.POST.get('document_reference', '').strip(),
        issue_date=issue, expiry_date=expiry, uploaded_by=request.user)

    # An AML / ID check carries the client's identity forward.
    if category == 'aml_id_check':
        client = mc.client
        client.id_verified = True
        client.date_of_last_aml = issue or timezone.localdate()
        client.save(update_fields=['id_verified', 'date_of_last_aml'])

    messages.success(
        request, f'{DOC_CATEGORIES[category]} uploaded for {mc.client.name}.')
    return redirect('home', file_number)


@login_required
def matter_preview_client_doc(request, doc_id):
    """Stream a matter-client document inline (login-protected; never public)."""
    doc = get_object_or_404(MatterClientDocument, id=doc_id)
    if not doc.file:
        raise Http404('No file for this document.')
    content_type, _ = mimetypes.guess_type(doc.file.name)
    return FileResponse(doc.file.open('rb'),
                        content_type=content_type or 'application/octet-stream')


@login_required
@require_POST
def matter_upload_identity_doc(request, file_number, mc_id):
    """Record an identity document (proof of ID / proof of address / selfie with
    ID) for a client on this matter, with its scan. Identity lives on the client
    record and is reused across matters, so this is how a client who was not
    onboarded through the portal gets the same documents on file. Uploading a
    proof of ID marks the client as ID-verified."""
    mc = get_object_or_404(MatterClient, id=mc_id, matter__file_number=file_number)
    category = request.POST.get('category', '')
    if category not in IDENTITY_CATEGORIES:
        messages.error(request, 'Choose a document type.')
        return redirect('home', file_number)
    upload = request.FILES.get('document')
    problem = _upload_problem(upload)
    if problem:
        messages.error(request, problem)
        return redirect('home', file_number)
    today = timezone.localdate()
    doc = ClientKeyDocument.objects.create(
        client=mc.client, category=category, file=upload,
        document_type=request.POST.get('document_type', '').strip()[:100],
        document_reference=request.POST.get('document_reference', '').strip()[:100],
        issue_date=_parse_date(request.POST.get('issue_date')),
        expiry_date=_parse_date(request.POST.get('expiry_date')),
        verified_on=today, verified_by=request.user)
    log_created(request.user, doc, snapshot_key_document(doc))
    if category == 'proof_of_id' and not mc.client.id_verified:
        mc.client.id_verified = True
        mc.client.save(update_fields=['id_verified'])
    messages.success(
        request, f'{IDENTITY_LABELS[category]} recorded for {mc.client.name}.')
    return redirect('home', file_number)


@login_required
@require_POST
def client_key_document_upload(request, file_number, doc_id):
    """Attach the actual scan to an existing client key document (proof of ID /
    address) — older records hold only metadata."""
    doc = get_object_or_404(ClientKeyDocument, id=doc_id)
    upload = request.FILES.get('document')
    problem = _upload_problem(upload)
    if problem:
        messages.error(request, problem)
        return redirect('home', file_number)
    doc.file = upload
    doc.save(update_fields=['file'])
    messages.success(
        request, f'{doc.get_category_display()} scan uploaded for {doc.client.name}.')
    return redirect('home', file_number)


@login_required
def client_key_document_preview(request, doc_id):
    """Stream a client key-document scan inline (login-protected; never public)."""
    doc = get_object_or_404(ClientKeyDocument, id=doc_id)
    if not doc.file:
        raise Http404('No file for this document.')
    content_type, _ = mimetypes.guess_type(doc.file.name)
    return FileResponse(doc.file.open('rb'),
                        content_type=content_type or 'application/octet-stream')


@login_required
@require_POST
def matter_save_conveyancing(request, file_number):
    """Save the property / price detail for a conveyancing matter."""
    matter = get_object_or_404(WIP, file_number=file_number)
    conv, _ = ConveyancingDetails.objects.get_or_create(matter=matter)
    conv.transaction_type = request.POST.get('transaction_type', '').strip()
    price = request.POST.get('property_price', '').strip().replace(',', '')
    conv.property_price = price or None
    conv.property_address = request.POST.get('property_address', '').strip()
    conv.completion_date = _parse_date(request.POST.get('completion_date'))
    conv.save()
    messages.success(request, 'Conveyancing details saved.')
    return redirect('home', file_number)
