import os
import re
import uuid


def sanitize_filename(filename):
    """Return a safe basename preserving the file extension."""
    name = os.path.basename(filename or 'file')
    stem, ext = os.path.splitext(name)
    stem = re.sub(r'[^\w.\- ]', '_', stem).strip('._ ') or 'file'
    ext = re.sub(r'[^\w.]', '', ext.lower())[:10]
    return f'{stem}{ext}'


def undertaking_file_upload_path(instance, filename):
    file_number = 'unassigned'
    if instance.file_number_id and instance.file_number:
        file_number = instance.file_number.file_number
    safe_name = sanitize_filename(filename)
    return f'Undertakings/{file_number}/{uuid.uuid4()}_{safe_name}'


def staff_document_upload_path(instance, filename):
    employee_id = instance.employee_id or 'unassigned'
    safe_name = sanitize_filename(filename)
    return f'StaffDocuments/{employee_id}/{uuid.uuid4()}_{safe_name}'


def bundle_document_upload_path(instance, filename):
    bundle = instance.section.bundle
    file_number = 'unassigned'
    if bundle.file_number_id and bundle.file_number:
        file_number = bundle.file_number.file_number
    doc_uuid = instance.uuid or uuid.uuid4()
    return f'BundleSources/{file_number}/{bundle.uuid}/{doc_uuid}.pdf'


def bundle_final_pdf_upload_path(instance, filename):
    file_number = 'unassigned'
    if instance.file_number_id and instance.file_number:
        file_number = instance.file_number.file_number
    bundle_uuid = instance.uuid or uuid.uuid4()
    return f'BundleFinal/{file_number}/{bundle_uuid}.pdf'


LEGACY_PATH_PREFIXES = {
    'undertakings/': 'Undertakings/',
    'bundle_documents/': 'BundleSources/',
    'bundles/': 'BundleFinal/',
}
