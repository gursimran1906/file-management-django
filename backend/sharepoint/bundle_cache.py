import os
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed

from backend.storage.sharepoint import download_storage_file_to_path

DEFAULT_PREFETCH_WORKERS = 8


class BundleTempCache:
    """Download bundle source PDFs once per request for local PDF processing."""

    def __init__(self, bundle, prefetch_workers=DEFAULT_PREFETCH_WORKERS):
        self.bundle = bundle
        self.temp_dir = tempfile.mkdtemp(prefix=f'bundle_{bundle.id}_')
        self._local = {}
        self._page_counts = {}
        self._prefetch_workers = prefetch_workers

    def local_path(self, document):
        if document.id not in self._local:
            dest = os.path.join(self.temp_dir, f'{document.id}.pdf')
            download_storage_file_to_path(document.file.name, dest)
            self._local[document.id] = dest
        return self._local[document.id]

    def has_page_count(self, document):
        return document.id in self._page_counts

    def get_page_count(self, document):
        return self._page_counts.get(document.id)

    def prefetch_all(self, documents):
        """Download all documents in parallel and cache page counts."""
        from PyPDF2 import PdfReader

        unique_docs = list({document.id: document for document in documents}.values())
        if not unique_docs:
            return

        def fetch(document):
            path = self.local_path(document)
            with open(path, 'rb') as pdf_file:
                reader = PdfReader(pdf_file)
                page_count = len(reader.pages)
            return document.id, page_count

        workers = min(self._prefetch_workers, len(unique_docs))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(fetch, document) for document in unique_docs]
            for future in as_completed(futures):
                document_id, page_count = future.result()
                self._page_counts[document_id] = page_count

    def cleanup(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.cleanup()
        return False
