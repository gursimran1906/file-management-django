import logging
import secrets
from datetime import timedelta
from datetime import timezone as datetime_timezone

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from backend.models import BundleShareLink
from backend.sharepoint.client import SharePointClientError, get_sharepoint_client
from backend.sharepoint.paths import normalize_storage_path, resolve_storage_path

logger = logging.getLogger(__name__)


class SharePointSharingError(Exception):
    pass


def assert_bundle_final_pdf_path(bundle, storage_path):
    """Ensure a storage path refers only to this bundle's final PDF."""
    if not storage_path:
        raise SharePointSharingError('Bundle has no final PDF to share.')

    normalized = normalize_storage_path(storage_path)
    if not normalized.startswith('BundleFinal/'):
        raise SharePointSharingError(
            'Sharing is restricted to the bundle final PDF only.'
        )

    parts = normalized.split('/')
    if len(parts) != 3 or not normalized.endswith('.pdf'):
        raise SharePointSharingError('Invalid bundle final PDF storage path.')

    if str(bundle.uuid) not in parts[-1]:
        raise SharePointSharingError('Storage path does not match this bundle.')

    if not bundle.final_pdf or not bundle.final_pdf.name:
        raise SharePointSharingError('Bundle has no final PDF to share.')

    expected = normalize_storage_path(bundle.final_pdf.name)
    if normalized != expected:
        raise SharePointSharingError('Storage path does not match this bundle final PDF.')


def bundle_final_pdf_storage_path(bundle):
    if not bundle.final_pdf or not bundle.final_pdf.name:
        raise SharePointSharingError('Bundle has no final PDF to share.')
    path = normalize_storage_path(bundle.final_pdf.name)
    assert_bundle_final_pdf_path(bundle, path)
    return path


def _parse_graph_datetime(value):
    if not value:
        return None
    parsed = parse_datetime(value)
    if parsed and timezone.is_naive(parsed):
        return timezone.make_aware(parsed, datetime_timezone.utc)
    return parsed


def _serialize_share_link(link):
    return {
        'id': link.id,
        'url': link.url,
        'password': link.password or '',
        'use_password': link.use_password,
        'expires_at': link.expires_at.isoformat() if link.expires_at else '',
        'created_at': link.created_at.isoformat() if link.created_at else '',
        'revoked_at': link.revoked_at.isoformat() if link.revoked_at else '',
        'status': link.status_label(),
        'active': link.is_active(),
    }


def _revoke_share_link_record(link, *, save=True):
    if link.revoked_at:
        return False

    if settings.USE_SHAREPOINT and link.permission_id:
        try:
            storage_path = bundle_final_pdf_storage_path(link.bundle)
            client = get_sharepoint_client()
            resolved_path = resolve_storage_path(storage_path, client=client)
            client.revoke_permission(resolved_path, link.permission_id)
        except (SharePointClientError, SharePointSharingError) as exc:
            logger.warning(
                'Could not revoke SharePoint link %s for bundle %s: %s',
                link.id,
                link.bundle_id,
                exc,
            )

    link.revoked_at = timezone.now()
    if save:
        link.save(update_fields=['revoked_at'])
    return True


def revoke_share_link(link):
    """Revoke one stored Microsoft share link."""
    return _revoke_share_link_record(link)


def revoke_all_bundle_share_links(bundle):
    """Revoke all active share links for a bundle."""
    revoked_any = False
    for link in bundle.share_links.filter(revoked_at__isnull=True):
        if _revoke_share_link_record(link):
            revoked_any = True
    return revoked_any


def _graph_error_detail(exc):
    """Extract a readable message from a Graph API error response."""
    message = str(exc)
    lowered = message.lower()
    if 'sharingdisabled' in lowered or 'sharing has been disabled' in lowered:
        return (
            'Anonymous ("Anyone with the link") sharing is disabled on the SharePoint site. '
            'A SharePoint admin must enable external sharing for the ANP File Management site '
            '(SharePoint Admin Center → Sites → Active sites → select site → Policies → '
            'External sharing, or tenant-wide Sharing policy). '
            'Until that is enabled, set BUNDLE_SHARE_LINK_SCOPE=organization in .env to create '
            'links for signed-in organisation users only.'
        )
    if 'accessdenied' in lowered or '403' in lowered:
        return (
            'Microsoft denied the sharing request. Ensure the SharePoint app has '
            'Files.ReadWrite.All (application) with admin consent.'
        )
    if 'password' in lowered and 'not' in lowered:
        return (
            'Microsoft rejected the link password. Try creating the link without a password '
            'or enable password-protected sharing in SharePoint.'
        )
    return (
        'Microsoft could not create a sharing link. '
        f'Details: {message}'
    )


def create_bundle_share_link(bundle, *, use_password=None, created_by=None):
    """Create a view-only Microsoft share link for this bundle's final PDF."""
    if not settings.USE_SHAREPOINT:
        raise SharePointSharingError(
            'SharePoint storage must be enabled to create external links.'
        )

    storage_path = bundle_final_pdf_storage_path(bundle)
    client = get_sharepoint_client()
    resolved_path = resolve_storage_path(storage_path, client=client)

    if not resolved_path.startswith('BundleFinal/'):
        raise SharePointSharingError(
            'Sharing is restricted to the bundle final PDF only.'
        )
    if str(bundle.uuid) not in resolved_path:
        raise SharePointSharingError('Storage path does not match this bundle.')

    if not client.exists(resolved_path):
        raise SharePointSharingError(
            'Final PDF is not available in SharePoint yet. Download or generate it first.'
        )

    expiry_days = getattr(settings, 'BUNDLE_SHARE_LINK_EXPIRY_DAYS', 30)
    expires_at = timezone.now() + timedelta(days=expiry_days)
    expiration_datetime = expires_at.astimezone(datetime_timezone.utc).strftime(
        '%Y-%m-%dT%H:%M:%SZ'
    )

    link_scope = getattr(settings, 'BUNDLE_SHARE_LINK_SCOPE', 'anonymous')
    if link_scope not in ('anonymous', 'organization'):
        raise SharePointSharingError(
            'BUNDLE_SHARE_LINK_SCOPE must be "anonymous" or "organization".'
        )

    if use_password is None:
        use_password = getattr(settings, 'BUNDLE_SHARE_LINK_USE_PASSWORD', True)

    password = None
    if link_scope == 'anonymous' and use_password:
        password = secrets.token_urlsafe(12)

    try:
        link_data = client.create_share_link(
            resolved_path,
            link_type='view',
            scope=link_scope,
            expiration_datetime=expiration_datetime,
            password=password,
        )
    except SharePointClientError as exc:
        logger.error(
            'SharePoint createLink failed for bundle %s at %s: %s',
            bundle.id,
            resolved_path,
            exc,
        )
        raise SharePointSharingError(_graph_error_detail(exc)) from exc

    web_url = link_data.get('web_url')
    permission_id = link_data.get('permission_id')
    if not web_url or not permission_id:
        raise SharePointSharingError('Microsoft did not return a sharing link.')

    graph_expires_at = _parse_graph_datetime(link_data.get('expiration_datetime'))
    share_link = BundleShareLink.objects.create(
        bundle=bundle,
        url=web_url,
        permission_id=permission_id,
        password=password or '',
        use_password=bool(password),
        expires_at=graph_expires_at or expires_at,
        created_by=created_by,
    )

    serialized = _serialize_share_link(share_link)
    return {
        **serialized,
        'expires_at_dt': share_link.expires_at,
        'permission_id': permission_id,
    }


def bundle_share_link_status(bundle):
    """Return share-link metadata for API/UI consumption."""
    links = [
        _serialize_share_link(link)
        for link in bundle.share_links.all()
    ]
    stale = bool(
        bundle.final_pdf
        and not bundle.pdf_is_current()
        and bundle.share_links.filter(revoked_at__isnull=True).exists()
    )

    return {
        'links': links,
        'stale': stale,
        'sharepoint_enabled': settings.USE_SHAREPOINT,
        'link_scope': getattr(settings, 'BUNDLE_SHARE_LINK_SCOPE', 'anonymous'),
    }
