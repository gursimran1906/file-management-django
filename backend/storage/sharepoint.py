import os
import tempfile
from io import BytesIO

from django.conf import settings
from django.core.files.base import File
from django.core.files.storage import Storage

from backend.sharepoint.client import SharePointClientError, get_sharepoint_client
from backend.sharepoint.paths import normalize_storage_path, resolve_storage_path


def resolve_local_media_path(name):
    """Return a disk path under MEDIA_ROOT for legacy/local files, if present."""
    if not name:
        return None

    candidates = [name.replace('\\', '/')]
    mapped = normalize_storage_path(name)
    if mapped not in candidates:
        candidates.append(mapped)

    for candidate in dict.fromkeys(candidates):
        path = os.path.join(settings.MEDIA_ROOT, candidate)
        if os.path.exists(path):
            return path
    return None


def read_storage_file_bytes(name):
    """Read file bytes from SharePoint, falling back to local MEDIA_ROOT."""
    if settings.USE_SHAREPOINT:
        client = get_sharepoint_client()
        resolved_name = resolve_storage_path(name, client=client)
        try:
            return client.download(resolved_name)
        except SharePointClientError as exc:
            if '404' not in str(exc):
                raise
            local_path = resolve_local_media_path(name)
            if local_path is None:
                raise
            with open(local_path, 'rb') as handle:
                return handle.read()

    local_path = resolve_local_media_path(name)
    if local_path is None:
        raise FileNotFoundError(name)
    with open(local_path, 'rb') as handle:
        return handle.read()


class SharePointFile(File):
    def __init__(self, name, content):
        self.name = name
        super().__init__(BytesIO(content), name)


class SharePointStorage(Storage):
    """Store files in SharePoint document libraries via Microsoft Graph."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def _storage_name(self, name):
        return normalize_storage_path(name)

    def _resolved_name(self, name):
        client = get_sharepoint_client()
        return resolve_storage_path(name, client=client)

    def _save(self, name, content):
        client = get_sharepoint_client()
        storage_name = self._storage_name(name)
        client.upload(storage_name, content)
        return storage_name

    def _open(self, name, mode='rb'):
        if 'w' in mode:
            raise ValueError('SharePoint storage is read-only via _open')
        return SharePointFile(name, read_storage_file_bytes(name))

    def delete(self, name):
        if not name:
            return
        client = get_sharepoint_client()
        client.delete(self._resolved_name(name))

    def exists(self, name):
        if not name:
            return False
        if settings.USE_SHAREPOINT:
            client = get_sharepoint_client()
            try:
                if client.exists(self._resolved_name(name)):
                    return True
            except SharePointClientError:
                pass
            return resolve_local_media_path(name) is not None
        return resolve_local_media_path(name) is not None

    def size(self, name):
        client = get_sharepoint_client()
        return client.size(self._resolved_name(name))

    def url(self, name):
        return ''

    def get_available_name(self, name, max_length=None):
        storage_name = self._storage_name(name)
        if self.exists(storage_name):
            base, ext = os.path.splitext(storage_name)
            counter = 1
            while self.exists(f'{base}_{counter}{ext}'):
                counter += 1
            storage_name = f'{base}_{counter}{ext}'
        if max_length and len(storage_name) > max_length:
            raise ValueError('Storage path exceeds max_length')
        return storage_name


def download_storage_file_to_path(name, dest_path):
    """Download a file from active storage to a local path."""
    content = read_storage_file_bytes(name)
    with open(dest_path, 'wb') as dest:
        dest.write(content)
