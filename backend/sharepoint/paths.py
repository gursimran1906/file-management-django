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


def bundle_version_pdf_upload_path(instance, filename):
    """Immutable per-version path: BundleFinal/{file_number}/{uuid}/v{n}.pdf.

    Each generation is stored as its own file so previously created share
    links (bound to a specific version) keep resolving after a regeneration.
    """
    bundle = instance.bundle
    file_number = 'unassigned'
    if bundle.file_number_id and bundle.file_number:
        file_number = bundle.file_number.file_number
    return f'BundleFinal/{file_number}/{bundle.uuid}/v{instance.version}.pdf'


LEGACY_PATH_PREFIXES = {
    'undertakings/': 'Undertakings/',
    'bundle_documents/': 'BundleSources/',
    'bundles/': 'BundleFinal/',
}

UUID_FILE_PREFIX = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}_',
    re.I,
)


def normalize_storage_path(name):
    """Map legacy local media paths to SharePoint library paths."""
    normalized = (name or '').replace('\\', '/')
    for legacy_prefix, new_prefix in LEGACY_PATH_PREFIXES.items():
        if normalized.startswith(legacy_prefix):
            return new_prefix + normalized[len(legacy_prefix):]
    return normalized


def storage_basename_key(name):
    return UUID_FILE_PREFIX.sub('', os.path.basename(name or '')).lower()


def resolve_storage_path(name, client=None):
    """Resolve the SharePoint path to use for reads/deletes.

    Handles legacy DB paths and files uploaded under a different name in the
    same folder (for example UUID-prefixed filenames after migration).
    """
    if not name:
        return name

    from backend.sharepoint.client import SharePointClientError, get_sharepoint_client

    if client is None:
        client = get_sharepoint_client()

    normalized = normalize_storage_path(name)
    try:
        if client.exists(normalized):
            return normalized
    except SharePointClientError:
        pass

    parts = normalized.split('/')
    if len(parts) < 3:
        return normalized

    library = parts[0]
    if library not in ('Undertakings', 'StaffDocuments', 'BundleSources', 'BundleFinal'):
        return normalized

    target_name = parts[-1]
    target_key = storage_basename_key(target_name)
    folder_path = '/'.join(parts[:-1])

    try:
        items = client.list_children(folder_path)
    except SharePointClientError:
        return normalized

    for item in items or []:
        if item.get('is_folder'):
            continue
        if item['name'] == target_name:
            return item['path']
        if storage_basename_key(item['name']) == target_key:
            return item['path']

    return normalized
