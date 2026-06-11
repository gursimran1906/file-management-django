"""Thin client for Granola's official public REST API.

Docs: https://docs.granola.ai/introduction
Base URL: https://public-api.granola.ai/v1 — Bearer auth with a ``grn_...`` key.

Only notes that already have a generated AI summary *and* transcript are
returned by the API, so the poller naturally picks notes up on the cycle after
Granola finishes processing them. There are no webhooks; we poll
``GET /notes?created_after=...`` and page via the ``cursor`` / ``hasMore`` fields.
"""
import logging
import time

import requests

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = 'https://public-api.granola.ai/v1'


class GranolaError(Exception):
    """Raised when the Granola API returns an unrecoverable error."""


class GranolaClient:
    def __init__(self, api_key, base_url=DEFAULT_BASE_URL, timeout=30,
                 max_retries=4):
        if not api_key:
            raise GranolaError('No Granola API key configured.')
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {api_key}',
            'Accept': 'application/json',
        })

    def _get(self, path, params=None):
        url = f'{self.base_url}/{path.lstrip("/")}'
        for attempt in range(self.max_retries):
            resp = self.session.get(url, params=params, timeout=self.timeout)
            if resp.status_code == 429:
                # Respect the documented rate limit (5 req/s, burst 25/5s).
                wait = int(resp.headers.get('Retry-After', 2 ** attempt))
                logger.warning('Granola rate limited; sleeping %ss', wait)
                time.sleep(wait)
                continue
            if resp.status_code >= 500:
                wait = 2 ** attempt
                logger.warning('Granola %s on %s; retrying in %ss',
                               resp.status_code, path, wait)
                time.sleep(wait)
                continue
            if resp.status_code == 404:
                return None
            if not resp.ok:
                raise GranolaError(
                    f'Granola API {resp.status_code} on {path}: {resp.text[:300]}')
            return resp.json()
        raise GranolaError(f'Granola API kept failing on {path} after retries.')

    def iter_notes(self, created_after=None, updated_after=None, folder_id=None,
                   page_limit=2000):
        """Yield note summaries, transparently following cursor pagination.

        ``created_after`` / ``updated_after`` are RFC3339 timestamp strings (or
        ``None`` for the first ever sync). ``folder_id`` restricts to a folder
        (and its children). ``page_limit`` bounds paging (30 notes/page); a
        warning is logged if it is hit so coverage is never silently truncated.
        """
        cursor = None
        for _ in range(page_limit):
            params = {'page_size': 30}
            if created_after:
                params['created_after'] = created_after
            if updated_after:
                params['updated_after'] = updated_after
            if folder_id:
                params['folder_id'] = folder_id
            if cursor:
                params['cursor'] = cursor
            data = self._get('notes', params=params) or {}
            notes = data.get('notes') or data.get('data') or []
            for note in notes:
                yield note
            if not data.get('hasMore'):
                return
            cursor = data.get('cursor')
            if not cursor:
                return
        logger.warning('iter_notes hit page_limit (%s) for folder_id=%s — '
                       'coverage may be truncated; raise page_limit.',
                       page_limit, folder_id)

    def list_folders(self, page_limit=20):
        """Return all accessible folders as ``{id, name, parent_folder_id}`` dicts."""
        folders = []
        cursor = None
        for _ in range(page_limit):
            params = {'page_size': 30}
            if cursor:
                params['cursor'] = cursor
            data = self._get('folders', params=params) or {}
            folders.extend(data.get('folders') or data.get('data') or [])
            if not data.get('hasMore'):
                break
            cursor = data.get('cursor')
            if not cursor:
                break
        return folders

    def get_note(self, note_id, include_transcript=True):
        """Fetch a single note, optionally with its transcript. ``None`` if 404."""
        params = {'include': 'transcript'} if include_transcript else None
        return self._get(f'notes/{note_id}', params=params)
