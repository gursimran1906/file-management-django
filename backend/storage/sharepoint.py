import os
import tempfile
from io import BytesIO

from django.conf import settings
from django.core.files.base import File
from django.core.files.storage import Storage

from backend.sharepoint.client import SharePointClientError, get_sharepoint_client


class SharePointFile(File):
    def __init__(self, name, content):
        self.name = name
        super().__init__(BytesIO(content), name)


class SharePointStorage(Storage):
    """Store files in SharePoint document libraries via Microsoft Graph."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def _save(self, name, content):
        client = get_sharepoint_client()
        client.upload(name, content)
        return name

    def _open(self, name, mode='rb'):
        if 'w' in mode:
            raise ValueError('SharePoint storage is read-only via _open')
        client = get_sharepoint_client()
        return SharePointFile(name, client.download(name))

    def delete(self, name):
        if not name:
            return
        client = get_sharepoint_client()
        client.delete(name)

    def exists(self, name):
        if not name:
            return False
        client = get_sharepoint_client()
        return client.exists(name)

    def size(self, name):
        client = get_sharepoint_client()
        return client.size(name)

    def url(self, name):
        return ''

    def get_available_name(self, name, max_length=None):
        if self.exists(name):
            base, ext = os.path.splitext(name)
            counter = 1
            while self.exists(f'{base}_{counter}{ext}'):
                counter += 1
            name = f'{base}_{counter}{ext}'
        if max_length and len(name) > max_length:
            raise ValueError('Storage path exceeds max_length')
        return name


def download_storage_file_to_path(name, dest_path):
    """Download a file from active storage to a local path."""
    if settings.USE_SHAREPOINT:
        get_sharepoint_client().download_to_file(name, dest_path)
        return

    source = os.path.join(settings.MEDIA_ROOT, name)
    if not os.path.exists(source):
        raise FileNotFoundError(name)
    with open(source, 'rb') as src, open(dest_path, 'wb') as dest:
        dest.write(src.read())
