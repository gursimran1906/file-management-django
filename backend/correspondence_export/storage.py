"""Where export files go: the SharePoint library when enabled, else local media."""
import os
import shutil
from pathlib import Path

from django.conf import settings


def export_folder(matter, export_id):
    library = getattr(settings, 'CORRESPONDENCE_EXPORT_LIBRARY', 'BundleFinal')
    return f'{library}/{matter.file_number}/correspondence-exports/{export_id}'


class ExportStore:
    """put/open/url helpers over one export folder. Paths are relative to the folder."""

    def __init__(self, folder):
        self.folder = folder.strip('/')
        self.use_sharepoint = bool(settings.USE_SHAREPOINT)
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from backend.sharepoint.client import get_sharepoint_client
            self._client = get_sharepoint_client()
        return self._client

    def full_path(self, relpath):
        return f"{self.folder}/{relpath.strip('/')}"

    def local_path(self, relpath):
        return Path(settings.MEDIA_ROOT) / self.full_path(relpath)

    def put(self, relpath, data):
        path = self.full_path(relpath)
        if self.use_sharepoint:
            self.client.upload(path, data)
        else:
            target = self.local_path(relpath)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        return path

    def put_file(self, relpath, local_file):
        """Store a file from disk without reading it all into memory."""
        path = self.full_path(relpath)
        if self.use_sharepoint:
            self.client.upload_file(path, local_file)
        else:
            target = self.local_path(relpath)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(local_file, target)
        return path

    def exists(self, relpath):
        if self.use_sharepoint:
            return self.client.exists(self.full_path(relpath))
        return self.local_path(relpath).is_file()

    def open(self, relpath):
        if self.use_sharepoint:
            import io
            return io.BytesIO(self.client.download(self.full_path(relpath)))
        return open(self.local_path(relpath), 'rb')

    def web_url(self, relpath=''):
        """Browser URL of a file or of the folder itself (SharePoint only)."""
        if not self.use_sharepoint:
            return ''
        try:
            item = self.client.get_item(self.full_path(relpath) if relpath else self.folder)
        except Exception:
            return ''
        return item.get('webUrl') or ''

    def download_url(self, relpath):
        """Short-lived pre-authenticated download URL (SharePoint only)."""
        if not self.use_sharepoint:
            return ''
        try:
            return self.client.download_url(self.full_path(relpath)) or ''
        except Exception:
            return ''

    def remove_tree(self):
        if self.use_sharepoint:
            try:
                self.client.delete(self.folder)
            except Exception:
                pass
        else:
            shutil.rmtree(Path(settings.MEDIA_ROOT) / self.folder, ignore_errors=True)


def temp_dir():
    configured = getattr(settings, 'CORRESPONDENCE_EXPORT_TMP_DIR', '') or ''
    if configured:
        os.makedirs(configured, exist_ok=True)
        return configured
    import tempfile
    return tempfile.gettempdir()
