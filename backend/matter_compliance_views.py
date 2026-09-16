"""Matter-home actions for per-matter-per-client compliance: record the
engagement checks (terms / NCBA / source of funds / PEP) for one client on one
matter, upload the supporting documents (including an AML/ID check after the file
is open), and capture conveyancing transaction detail."""
import mimetypes
import os
from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import (ClientKeyDocument, ConveyancingDetails, MatterClient,
                     MatterClientDocument, WIP)

ALLOWED_DOC_EXTENSIONS = ('.pdf', '.jpg', '.jpeg', '.png', '.heic', '.doc', '.docx')
MAX_DOC_BYTES = 25 * 1024 * 1024
DOC_CATEGORIES = dict(MatterClientDocument.CATEGORY_CHOICES)


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

    mc.ncba_required = _checked(request, 'ncba_required')
    fields.append('ncba_required')
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
    if not upload:
        messages.error(request, 'Choose a file to upload.')
        return redirect('home', file_number)
    if os.path.splitext(upload.name)[1].lower() not in ALLOWED_DOC_EXTENSIONS:
        messages.error(request, 'Allowed file types: PDF, Word, JPG, PNG, HEIC.')
        return redirect('home', file_number)
    if upload.size > MAX_DOC_BYTES:
        messages.error(request, 'File is too large (max 25MB).')
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
def client_key_document_upload(request, file_number, doc_id):
    """Attach the actual scan to an existing client key document (proof of ID /
    address) — older records hold only metadata."""
    doc = get_object_or_404(ClientKeyDocument, id=doc_id)
    upload = request.FILES.get('document')
    if not upload:
        messages.error(request, 'Choose a file to upload.')
        return redirect('home', file_number)
    if os.path.splitext(upload.name)[1].lower() not in ALLOWED_DOC_EXTENSIONS:
        messages.error(request, 'Allowed file types: PDF, Word, JPG, PNG, HEIC.')
        return redirect('home', file_number)
    if upload.size > MAX_DOC_BYTES:
        messages.error(request, 'File is too large (max 25MB).')
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
