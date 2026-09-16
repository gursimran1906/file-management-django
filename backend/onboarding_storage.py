"""Read client-uploaded onboarding documents back from the intake SharePoint
library (where the portal wrote them).

The portal stores files at::

    [testing/]{root}/Onboarding/{client_ref}/{submission_id}/{type}-{id}.{ext}

The office reads them with its own (broader) Graph credential — the portal only
ever hands back ids/paths, never bytes. See the Phase 0 SharePoint setup guide.
The exact filename carries a portal-side id we don't know, so we list the
submission folder and match on the ``{item_type}-`` prefix.
"""
import logging
import mimetypes
from urllib.parse import quote

import requests
from azure.identity import ClientSecretCredential
from django.conf import settings

logger = logging.getLogger('backend')

_GRAPH = 'https://graph.microsoft.com/v1.0'
_TIMEOUT = 60


class OnboardingStorageError(Exception):
    pass


def _drive_id():
    return getattr(settings, 'ONBOARDING_INTAKE_DRIVE_ID', '') or ''


def _root():
    return (getattr(settings, 'ONBOARDING_SHAREPOINT_ROOT', 'client_portal') or 'client_portal').strip('/')


def _testing():
    return bool(getattr(settings, 'ONBOARDING_SHAREPOINT_TESTING', True))


def is_configured():
    return bool(
        _drive_id()
        and settings.SHAREPOINT_AZURE_CLIENT_ID
        and settings.SHAREPOINT_AZURE_CLIENT_SECRET
        and settings.SHAREPOINT_AZURE_TENANT_ID
    )


def submission_folder(member):
    """The folder the portal wrote this member's uploads into."""
    base = f'{_root()}/Onboarding/{member.client_ref}/{member.portal_submission_id}'
    return f'testing/{base}' if _testing() else base


def _token():
    credential = ClientSecretCredential(
        tenant_id=settings.SHAREPOINT_AZURE_TENANT_ID,
        client_id=settings.SHAREPOINT_AZURE_CLIENT_ID,
        client_secret=settings.SHAREPOINT_AZURE_CLIENT_SECRET,
    )
    return credential.get_token('https://graph.microsoft.com/.default').token


def read_document_by_id(item_id):
    """Read a file from the intake drive by its SharePoint item id (the exact id
    the portal reported in get_submission — no filename guessing)."""
    if not is_configured():
        raise OnboardingStorageError('Intake SharePoint is not configured.')
    drive = _drive_id()
    headers = {'Authorization': f'Bearer {_token()}'}
    try:
        meta = requests.get(f'{_GRAPH}/drives/{drive}/items/{item_id}',
                            headers=headers, timeout=_TIMEOUT)
        meta.raise_for_status()
        name = meta.json().get('name', 'document')
        download = requests.get(f'{_GRAPH}/drives/{drive}/items/{item_id}/content',
                                headers=headers, timeout=_TIMEOUT)
        download.raise_for_status()
    except requests.RequestException as exc:
        logger.warning('Onboarding intake read-by-id failed: %s', exc)
        raise OnboardingStorageError(str(exc))
    content_type = (download.headers.get('Content-Type')
                    or mimetypes.guess_type(name)[0]
                    or 'application/octet-stream')
    return download.content, content_type, name


def read_document(member, item_type):
    """Return (content_bytes, content_type, filename) for the client's upload of
    ``item_type``. Raises OnboardingStorageError if not configured or not found."""
    if not is_configured():
        raise OnboardingStorageError('Intake SharePoint is not configured.')

    folder = submission_folder(member)
    headers = {'Authorization': f'Bearer {_token()}'}
    drive = _drive_id()
    try:
        listing = requests.get(
            f'{_GRAPH}/drives/{drive}/root:/{quote(folder)}:/children',
            headers=headers, timeout=_TIMEOUT)
        if listing.status_code == 404:
            raise OnboardingStorageError('No documents found for this submission yet.')
        listing.raise_for_status()

        children = listing.json().get('value', [])
        # The portal names files with a "{item_type}-" prefix (Phase 0 spec). Match
        # on that; if nothing matches, log the actual filenames so we can confirm
        # the convention against the running portal.
        target = next((c for c in children
                       if c.get('name', '').startswith(f'{item_type}-')), None)
        if not target:
            logger.info('No "%s-" file in %s; files present: %s',
                        item_type, folder, [c.get('name') for c in children])
            raise OnboardingStorageError('That document has not been uploaded yet.')

        download = requests.get(
            f'{_GRAPH}/drives/{drive}/items/{target["id"]}/content',
            headers=headers, timeout=_TIMEOUT)
        download.raise_for_status()
    except requests.RequestException as exc:
        logger.warning('Onboarding intake read failed: %s', exc)
        raise OnboardingStorageError(str(exc))

    content_type = (download.headers.get('Content-Type')
                    or mimetypes.guess_type(target['name'])[0]
                    or 'application/octet-stream')
    return download.content, content_type, target['name']
