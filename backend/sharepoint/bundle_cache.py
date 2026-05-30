import os
import shutil
import tempfile

from backend.storage.sharepoint import download_storage_file_to_path


class BundleTempCache:
    """Download bundle source PDFs once per request for local PDF processing."""

    def __init__(self, bundle):
        self.bundle = bundle
        self.temp_dir = tempfile.mkdtemp(prefix=f'bundle_{bundle.id}_')
        self._local = {}

    def local_path(self, document):
        if document.id not in self._local:
            dest = os.path.join(self.temp_dir, f'{document.id}.pdf')
            download_storage_file_to_path(document.file.name, dest)
            self._local[document.id] = dest
        return self._local[document.id]

    def cleanup(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.cleanup()
        return False
