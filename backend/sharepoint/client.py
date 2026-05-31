import json
import logging
import time
from urllib.parse import quote

import httpx
from azure.identity import ClientSecretCredential
from django.conf import settings

logger = logging.getLogger(__name__)

GRAPH_BASE = 'https://graph.microsoft.com/v1.0'
CHUNK_SIZE = 10 * 1024 * 1024
SIMPLE_UPLOAD_LIMIT = 4 * 1024 * 1024
MAX_RETRIES = 5


class SharePointClientError(Exception):
    pass


class SharePointClient:
    """Sync Microsoft Graph client for SharePoint document library I/O."""

    def __init__(self):
        self.credential = ClientSecretCredential(
            tenant_id=settings.SHAREPOINT_AZURE_TENANT_ID,
            client_id=settings.SHAREPOINT_AZURE_CLIENT_ID,
            client_secret=settings.SHAREPOINT_AZURE_CLIENT_SECRET,
        )
        self.drive_ids = json.loads(settings.SHAREPOINT_DRIVE_IDS)

    def _token(self):
        return self.credential.get_token(
            'https://graph.microsoft.com/.default'
        ).token

    def _headers(self, extra=None):
        headers = {'Authorization': f'Bearer {self._token()}'}
        if extra:
            headers.update(extra)
        return headers

    def _split_path(self, name):
        parts = name.replace('\\', '/').split('/')
        if len(parts) < 2:
            raise SharePointClientError(f'Invalid storage path: {name}')
        library = parts[0]
        item_path = '/'.join(parts[1:])
        drive_id = self.drive_ids.get(library)
        if not drive_id:
            raise SharePointClientError(f'Unknown SharePoint library: {library}')
        return drive_id, item_path

    def _item_url(self, name, suffix=''):
        drive_id, item_path = self._split_path(name)
        encoded = quote(item_path, safe='/')
        return f'{GRAPH_BASE}/drives/{drive_id}/root:/{encoded}{suffix}'

    def _request(self, method, url, *, follow_redirects=False, **kwargs):
        delay = 1
        for attempt in range(MAX_RETRIES):
            with httpx.Client(timeout=120.0, follow_redirects=follow_redirects) as client:
                response = client.request(method, url, **kwargs)

            if response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', delay))
                logger.warning(
                    'SharePoint throttled (429), retry in %ss (attempt %s)',
                    retry_after,
                    attempt + 1,
                )
                time.sleep(retry_after)
                delay = min(delay * 2, 60)
                continue

            if response.status_code == 503 and attempt < MAX_RETRIES - 1:
                retry_after = int(response.headers.get('Retry-After', delay))
                time.sleep(retry_after)
                delay = min(delay * 2, 60)
                continue

            return response

        raise SharePointClientError('SharePoint request failed after retries')

    def exists(self, name):
        response = self._request(
            'GET',
            self._item_url(name),
            headers=self._headers(),
        )
        return response.status_code == 200

    def list_children(self, folder_path):
        """List files/folders directly under folder_path (e.g. Undertakings/ALL0030001)."""
        normalized = folder_path.replace('\\', '/').strip('/')
        parts = normalized.split('/')
        if len(parts) < 2:
            raise SharePointClientError(f'Invalid folder path: {folder_path}')
        library = parts[0]
        drive_id = self.drive_ids.get(library)
        if not drive_id:
            raise SharePointClientError(f'Unknown SharePoint library: {library}')
        sub_path = '/'.join(parts[1:])
        encoded = quote(sub_path, safe='/')
        url = f'{GRAPH_BASE}/drives/{drive_id}/root:/{encoded}:/children'
        response = self._request('GET', url, headers=self._headers())
        if response.status_code == 404:
            return []
        if response.status_code != 200:
            raise SharePointClientError(
                f'Failed to list {folder_path}: {response.status_code} {response.text}'
            )
        items = []
        for entry in response.json().get('value', []):
            name = entry.get('name', '')
            if entry.get('folder') is not None:
                items.append({
                    'name': name,
                    'path': f'{normalized}/{name}',
                    'is_folder': True,
                    'size': 0,
                })
            elif entry.get('file') is not None:
                items.append({
                    'name': name,
                    'path': f'{normalized}/{name}',
                    'is_folder': False,
                    'size': entry.get('size', 0),
                })
        return items

    def size(self, name):
        response = self._request(
            'GET',
            self._item_url(name),
            headers=self._headers(),
        )
        if response.status_code != 200:
            raise SharePointClientError(
                f'Failed to stat {name}: {response.status_code}'
            )
        return response.json().get('size', 0)

    def download(self, name):
        response = self._request(
            'GET',
            self._item_url(name, ':/content'),
            headers=self._headers(),
            follow_redirects=True,
        )
        if response.status_code != 200:
            raise SharePointClientError(
                f'Failed to download {name}: {response.status_code}'
            )
        return response.content

    def download_to_file(self, name, dest_path):
        content = self.download(name)
        with open(dest_path, 'wb') as handle:
            handle.write(content)

    def delete(self, name):
        response = self._request(
            'DELETE',
            self._item_url(name),
            headers=self._headers(),
        )
        if response.status_code not in (204, 404):
            raise SharePointClientError(
                f'Failed to delete {name}: {response.status_code}'
            )

    def get_item(self, name):
        response = self._request(
            'GET',
            self._item_url(name),
            headers=self._headers(),
        )
        if response.status_code != 200:
            raise SharePointClientError(
                f'Failed to get item {name}: {response.status_code} {response.text}'
            )
        return response.json()

    def create_share_link(
        self,
        name,
        *,
        link_type='view',
        scope='anonymous',
        expiration_datetime=None,
        password=None,
    ):
        """Create a Microsoft sharing link for a single file."""
        body = {
            'type': link_type,
            'scope': scope,
            'retainInheritedPermissions': False,
        }
        if expiration_datetime:
            body['expirationDateTime'] = expiration_datetime
        if password:
            body['password'] = password

        response = self._request(
            'POST',
            self._item_url(name, ':/createLink'),
            headers=self._headers({'Content-Type': 'application/json'}),
            json=body,
        )
        if response.status_code not in (200, 201):
            raise SharePointClientError(
                f'Failed to create share link for {name}: '
                f'{response.status_code} {response.text}'
            )

        data = response.json()
        link = data.get('link') or {}
        return {
            'permission_id': data.get('id'),
            'web_url': link.get('webUrl'),
            'expiration_datetime': link.get('expirationDateTime') or expiration_datetime,
        }

    def revoke_permission(self, name, permission_id):
        """Remove a sharing permission from a file."""
        if not permission_id:
            return

        item = self.get_item(name)
        drive_id, _ = self._split_path(name)
        item_id = item['id']
        url = (
            f'{GRAPH_BASE}/drives/{drive_id}/items/{item_id}'
            f'/permissions/{permission_id}'
        )
        response = self._request('DELETE', url, headers=self._headers())
        if response.status_code not in (204, 404):
            raise SharePointClientError(
                f'Failed to revoke permission {permission_id} on {name}: '
                f'{response.status_code} {response.text}'
            )

    def upload(self, name, content):
        if hasattr(content, 'read'):
            data = content.read()
            if hasattr(content, 'seek'):
                content.seek(0)
        elif isinstance(content, (bytes, bytearray)):
            data = bytes(content)
        else:
            data = bytes(content)

        if len(data) <= SIMPLE_UPLOAD_LIMIT:
            self._upload_simple(name, data)
        else:
            self._upload_session(name, data)

    def _upload_simple(self, name, data):
        response = self._request(
            'PUT',
            self._item_url(name, ':/content'),
            headers=self._headers({'Content-Type': 'application/octet-stream'}),
            content=data,
        )
        if response.status_code not in (200, 201):
            raise SharePointClientError(
                f'Failed to upload {name}: {response.status_code} {response.text}'
            )

    def _upload_session(self, name, data):
        response = self._request(
            'POST',
            self._item_url(name, ':/createUploadSession'),
            headers=self._headers({'Content-Type': 'application/json'}),
            json={
                'item': {
                    '@microsoft.graph.conflictBehavior': 'replace',
                }
            },
        )
        if response.status_code not in (200, 201):
            raise SharePointClientError(
                f'Failed to create upload session for {name}: {response.status_code}'
            )
        upload_url = response.json()['uploadUrl']
        total = len(data)
        offset = 0
        while offset < total:
            chunk = data[offset:offset + CHUNK_SIZE]
            end = offset + len(chunk) - 1
            headers = {
                'Content-Length': str(len(chunk)),
                'Content-Range': f'bytes {offset}-{end}/{total}',
            }
            with httpx.Client(timeout=120.0) as client:
                chunk_response = client.put(upload_url, headers=headers, content=chunk)
            if chunk_response.status_code not in (200, 201, 202):
                raise SharePointClientError(
                    f'Chunk upload failed for {name}: {chunk_response.status_code}'
                )
            offset += len(chunk)


_client = None


def get_sharepoint_client():
    global _client
    if _client is None:
        _client = SharePointClient()
    return _client
