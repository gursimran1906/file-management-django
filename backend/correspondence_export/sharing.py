"""Microsoft share links for a finished export's zip (SharePoint storage only)."""
import logging
import secrets
from datetime import timedelta
from datetime import timezone as datetime_timezone

from django.conf import settings
from django.utils import timezone

from backend.sharepoint.client import SharePointClientError, get_sharepoint_client
from backend.sharepoint.sharing import _graph_error_detail, _parse_graph_datetime
from .storage import ExportStore

logger = logging.getLogger('backend')


class ExportSharingError(Exception):
    pass


def _zip_storage_path(export):
    if not export.zip_name or not export.storage_folder:
        raise ExportSharingError('This export has no zip to share yet.')
    return ExportStore(export.storage_folder).full_path(export.zip_name)


def create_export_share_link(export, *, use_password=None, created_by=None):
    if not settings.USE_SHAREPOINT:
        raise ExportSharingError('SharePoint storage must be enabled to create share links.')
    path = _zip_storage_path(export)
    client = get_sharepoint_client()
    if not client.exists(path):
        raise ExportSharingError('The zip is not in SharePoint yet. Wait for the export to finish.')

    expiry_days = getattr(settings, 'BUNDLE_SHARE_LINK_EXPIRY_DAYS', 30)
    expires_at = timezone.now() + timedelta(days=expiry_days)
    expiration = expires_at.astimezone(datetime_timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    link_scope = getattr(settings, 'BUNDLE_SHARE_LINK_SCOPE', 'anonymous')
    if link_scope not in ('anonymous', 'organization'):
        raise ExportSharingError('BUNDLE_SHARE_LINK_SCOPE must be "anonymous" or "organization".')
    if use_password is None:
        use_password = getattr(settings, 'BUNDLE_SHARE_LINK_USE_PASSWORD', True)
    password = secrets.token_urlsafe(12) if (link_scope == 'anonymous' and use_password) else None

    if export.share_permission_id and not export.share_revoked_at:
        try:
            client.revoke_permission(path, export.share_permission_id)
        except SharePointClientError:
            logger.warning('Could not revoke previous share link on export %s', export.id)

    try:
        link = client.create_share_link(path, link_type='view', scope=link_scope,
                                        expiration_datetime=expiration, password=password)
    except SharePointClientError as exc:
        logger.error('SharePoint createLink failed for export %s: %s', export.id, exc)
        raise ExportSharingError(_graph_error_detail(exc)) from exc

    web_url, permission_id = link.get('web_url'), link.get('permission_id')
    if not web_url or not permission_id:
        raise ExportSharingError('Microsoft did not return a sharing link.')
    export.share_url = web_url
    export.share_permission_id = permission_id
    export.share_password = password or ''
    export.share_use_password = bool(password)
    export.share_expires_at = _parse_graph_datetime(link.get('expiration_datetime')) or expires_at
    export.share_created_at = timezone.now()
    export.share_created_by = created_by
    export.share_revoked_at = None
    export.save(update_fields=['share_url', 'share_permission_id', 'share_password', 'share_use_password',
                               'share_expires_at', 'share_created_at', 'share_created_by',
                               'share_revoked_at', 'updated_at'])
    return {'url': web_url, 'password': password or '', 'expires_at': export.share_expires_at,
            'scope': link_scope}


def revoke_export_share_link(export):
    if not export.share_permission_id or export.share_revoked_at:
        return False
    if settings.USE_SHAREPOINT:
        try:
            get_sharepoint_client().revoke_permission(_zip_storage_path(export), export.share_permission_id)
        except SharePointClientError as exc:
            raise ExportSharingError(_graph_error_detail(exc)) from exc
    export.share_revoked_at = timezone.now()
    export.save(update_fields=['share_revoked_at', 'updated_at'])
    return True
