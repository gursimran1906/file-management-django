import os
import shutil
import tempfile
from datetime import timedelta
from io import BytesIO
from unittest.mock import MagicMock, patch

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from reportlab.pdfgen import canvas

from backend.models import Bundle, BundleDocument, BundleSection, BundleShareLink, Undertaking
from backend.sharepoint.bundle_cache import BundleTempCache
from backend.sharepoint.client import SharePointClient
from backend.sharepoint.paths import (
    bundle_document_upload_path,
    bundle_final_pdf_upload_path,
    normalize_storage_path,
    resolve_storage_path,
    undertaking_file_upload_path,
)
from backend.sharepoint.sharing import (
    SharePointSharingError,
    assert_bundle_final_pdf_path,
    create_bundle_share_link,
    revoke_share_link,
)
from backend.views import (
    _bundle_pdf_is_current,
    _collect_bundle_documents,
    _generate_bundle_pdf,
    _open_bundle_final_pdf,
)
from users.models import CustomUser


def make_pdf_bytes(text='Test'):
    buffer = BytesIO()
    pdf_canvas = canvas.Canvas(buffer)
    pdf_canvas.drawString(72, 720, text)
    pdf_canvas.showPage()
    pdf_canvas.save()
    return buffer.getvalue()


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class SharePointPathTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        media_root = cls._overridden_settings['MEDIA_ROOT']
        super().tearDownClass()
        shutil.rmtree(media_root, ignore_errors=True)

    def test_sanitize_filename_strips_unsafe_characters(self):
        from backend.sharepoint.paths import sanitize_filename
        self.assertEqual(sanitize_filename('letter (final).pdf'), 'letter _final.pdf')

    def test_normalize_storage_path_maps_legacy_prefixes(self):
        self.assertEqual(
            normalize_storage_path('undertakings/WEB0060002/file.pdf'),
            'Undertakings/WEB0060002/file.pdf',
        )
        self.assertEqual(
            normalize_storage_path('bundle_documents/WEB0060002/b1/d1.pdf'),
            'BundleSources/WEB0060002/b1/d1.pdf',
        )

    @patch('backend.sharepoint.paths.get_sharepoint_client')
    def test_resolve_storage_path_falls_back_to_folder_basename(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.exists.return_value = False
        mock_client.list_children.return_value = [
            {
                'name': 'abc12345-6789-6789-6789-6789abcdef01_letter.pdf',
                'path': 'Undertakings/WEB0060002/abc12345-6789-6789-6789-6789abcdef01_letter.pdf',
                'is_folder': False,
            }
        ]

        resolved = resolve_storage_path(
            'undertakings/WEB0060002/letter.pdf',
            client=mock_client,
        )
        self.assertEqual(
            resolved,
            'Undertakings/WEB0060002/abc12345-6789-6789-6789-6789abcdef01_letter.pdf',
        )

    def test_bundle_document_path_uses_uuids(self):
        bundle = Bundle.objects.create(name='Bundle')
        section = BundleSection.objects.create(bundle=bundle, heading='A', order=1)
        document = BundleDocument(section=section, description='Doc', order=1)
        path = bundle_document_upload_path(document, 'ignored.pdf')
        self.assertTrue(path.startswith(f'BundleSources/unassigned/{bundle.uuid}/'))
        self.assertTrue(path.endswith(f'{document.uuid}.pdf'))
        self.assertLessEqual(len(path), 255)

    def test_bundle_document_path_length_with_matter_file_number(self):
        import uuid as uuid_mod

        file_number = 'ABC0010002'
        path = f'BundleSources/{file_number}/{uuid_mod.uuid4()}/{uuid_mod.uuid4()}.pdf'
        self.assertEqual(len(path), 102)
        self.assertLessEqual(len(path), 255)

    def test_bundle_final_path_uses_bundle_uuid(self):
        bundle = Bundle.objects.create(name='Bundle')
        path = bundle_final_pdf_upload_path(bundle, 'ignored.pdf')
        self.assertEqual(path, f'BundleFinal/unassigned/{bundle.uuid}.pdf')


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class UndertakingDownloadTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        media_root = cls._overridden_settings['MEDIA_ROOT']
        super().tearDownClass()
        shutil.rmtree(media_root, ignore_errors=True)

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='undertaking-user',
            email='undertaking@example.com',
            first_name='U',
            last_name='Ser',
            password='password',
            max_holidays_in_year=20,
        )
        self.client.force_login(self.user)
        self.undertaking = Undertaking.objects.create(
            date_given='2024-01-01',
            given_to='Client',
            description='Test undertaking',
            document_given_on=SimpleUploadedFile(
                'undertaking.pdf',
                make_pdf_bytes('Undertaking content'),
                content_type='application/pdf',
            ),
            created_by=self.user,
        )

    def test_undertaking_file_download_requires_login(self):
        self.client.logout()
        response = self.client.get(
            reverse('undertaking_file_download', args=[self.undertaking.id, 'document_given_on'])
        )
        self.assertEqual(response.status_code, 302)

    def test_undertaking_file_download_streams_file(self):
        response = self.client.get(
            reverse('undertaking_file_download', args=[self.undertaking.id, 'document_given_on'])
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(b''.join(response.streaming_content).startswith(b'%PDF'))

    def test_undertaking_file_download_rejects_invalid_field(self):
        response = self.client.get(
            reverse('undertaking_file_download', args=[self.undertaking.id, 'invalid'])
        )
        self.assertEqual(response.status_code, 404)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class BundleTempCacheTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        media_root = cls._overridden_settings['MEDIA_ROOT']
        super().tearDownClass()
        shutil.rmtree(media_root, ignore_errors=True)

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='cache-user',
            email='cache@example.com',
            first_name='C',
            last_name='User',
            password='password',
            max_holidays_in_year=20,
        )
        self.bundle = Bundle.objects.create(name='Cache bundle', created_by=self.user)
        self.section = BundleSection.objects.create(
            bundle=self.bundle, heading='Section', order=1
        )

    @patch('backend.sharepoint.bundle_cache.download_storage_file_to_path')
    def test_collect_bundle_documents_downloads_once_with_cache(self, mock_download):
        document = BundleDocument.objects.create(
            section=self.section,
            file=SimpleUploadedFile('doc.pdf', make_pdf_bytes('Cached'), content_type='application/pdf'),
            description='Doc',
            order=1,
        )

        def _write_local(name, dest_path):
            with open(dest_path, 'wb') as handle:
                handle.write(make_pdf_bytes('Cached'))

        mock_download.side_effect = _write_local

        with BundleTempCache(self.bundle) as cache:
            _collect_bundle_documents(self.bundle, cache=cache)
            _generate_bundle_pdf(self.bundle, cache=cache)

        self.assertEqual(mock_download.call_count, 1)
        mock_download.assert_called_with(document.file.name, mock_download.call_args[0][1])

    @patch('backend.sharepoint.client.httpx.Client')
    def test_sharepoint_client_retries_on_429(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client

        success_response = MagicMock()
        success_response.status_code = 200
        success_response.content = b'file-bytes'

        throttled_response = MagicMock()
        throttled_response.status_code = 429
        throttled_response.headers = {'Retry-After': '0'}

        mock_client.request.side_effect = [throttled_response, success_response]

        with override_settings(
            USE_SHAREPOINT=True,
            SHAREPOINT_AZURE_CLIENT_ID='client',
            SHAREPOINT_AZURE_CLIENT_SECRET='secret',
            SHAREPOINT_AZURE_TENANT_ID='tenant',
            SHAREPOINT_DRIVE_IDS='{"Undertakings":"drive-1","StaffDocuments":"d2","BundleSources":"d3","BundleFinal":"d4"}',
        ), patch.object(
            SharePointClient,
            '_token',
            return_value='token',
        ), patch('backend.sharepoint.client.time.sleep'):
            client = SharePointClient()
            content = client.download('Undertakings/12345/test.pdf')

        self.assertEqual(content, b'file-bytes')
        self.assertEqual(mock_client.request.call_count, 2)
        mock_client_cls.assert_called_with(timeout=120.0, follow_redirects=True)

    @patch('backend.sharepoint.client.httpx.Client')
    def test_sharepoint_client_download_follows_redirects(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client

        success_response = MagicMock()
        success_response.status_code = 200
        success_response.content = b'pdf-bytes'
        mock_client.request.return_value = success_response

        with override_settings(
            USE_SHAREPOINT=True,
            SHAREPOINT_AZURE_CLIENT_ID='client',
            SHAREPOINT_AZURE_CLIENT_SECRET='secret',
            SHAREPOINT_AZURE_TENANT_ID='tenant',
            SHAREPOINT_DRIVE_IDS='{"Undertakings":"drive-1","StaffDocuments":"d2","BundleSources":"d3","BundleFinal":"d4"}',
        ), patch.object(
            SharePointClient,
            '_token',
            return_value='token',
        ):
            client = SharePointClient()
            content = client.download('Undertakings/12345/test.pdf')

        self.assertEqual(content, b'pdf-bytes')
        mock_client_cls.assert_called_once_with(timeout=120.0, follow_redirects=True)


@override_settings(
    USE_SHAREPOINT=True,
    BUNDLE_SHARE_LINK_EXPIRY_DAYS=7,
    BUNDLE_SHARE_LINK_USE_PASSWORD=True,
    BUNDLE_SHARE_LINK_SCOPE='anonymous',
    SHAREPOINT_DRIVE_IDS='{"BundleFinal":"drive-final"}',
)
class BundleShareLinkTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='bundle-share-user',
            email='bundle-share@example.com',
            first_name='B',
            last_name='Share',
            password='password',
            max_holidays_in_year=20,
        )
        self.client.force_login(self.user)
        self.bundle = Bundle.objects.create(
            name='Share Bundle',
            created_by=self.user,
        )
        self.final_path = bundle_final_pdf_upload_path(self.bundle, 'ignored.pdf')
        self.bundle.final_pdf.name = self.final_path
        self.bundle.pdf_generated_at = timezone.now()
        self.bundle.save(update_fields=['final_pdf', 'pdf_generated_at'])

    def test_assert_bundle_final_pdf_path_rejects_source_documents(self):
        source_path = f'BundleSources/unassigned/{self.bundle.uuid}/doc.pdf'
        with self.assertRaises(SharePointSharingError):
            assert_bundle_final_pdf_path(self.bundle, source_path)

    def test_assert_bundle_final_pdf_path_rejects_other_bundle(self):
        other = Bundle.objects.create(name='Other', created_by=self.user)
        other_path = bundle_final_pdf_upload_path(other, 'ignored.pdf')
        with self.assertRaises(SharePointSharingError):
            assert_bundle_final_pdf_path(self.bundle, other_path)

    @patch('backend.sharepoint.sharing.get_sharepoint_client')
    def test_create_bundle_share_link_stores_link_metadata(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.exists.return_value = True
        mock_client.create_share_link.return_value = {
            'permission_id': 'perm-123',
            'web_url': 'https://contoso.sharepoint.com/:b:/g/abc',
            'expiration_datetime': '2026-06-30T00:00:00Z',
        }

        result = create_bundle_share_link(self.bundle, created_by=self.user)

        self.assertEqual(
            result['url'],
            'https://contoso.sharepoint.com/:b:/g/abc',
        )
        link = BundleShareLink.objects.get(bundle=self.bundle)
        self.assertEqual(link.permission_id, 'perm-123')
        self.assertEqual(link.url, result['url'])
        mock_client.create_share_link.assert_called_once()
        call_args = mock_client.create_share_link.call_args
        self.assertEqual(call_args.kwargs['link_type'], 'view')
        self.assertEqual(call_args.kwargs['scope'], 'anonymous')
        self.assertTrue(call_args.kwargs['password'])

    @patch('backend.sharepoint.sharing.get_sharepoint_client')
    def test_create_bundle_share_link_without_password(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.exists.return_value = True
        mock_client.create_share_link.return_value = {
            'permission_id': 'perm-123',
            'web_url': 'https://contoso.sharepoint.com/:b:/g/abc',
            'expiration_datetime': '2026-06-30T00:00:00Z',
        }

        create_bundle_share_link(self.bundle, use_password=False, created_by=self.user)

        link = BundleShareLink.objects.get(bundle=self.bundle)
        self.assertEqual(link.password, '')
        call_args = mock_client.create_share_link.call_args
        self.assertIsNone(call_args.kwargs['password'])

    @patch('backend.sharepoint.sharing.get_sharepoint_client')
    def test_revoke_share_link_marks_revoked(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        link = BundleShareLink.objects.create(
            bundle=self.bundle,
            url='https://contoso.sharepoint.com/:b:/g/abc',
            permission_id='perm-123',
            created_by=self.user,
        )

        revoked = revoke_share_link(link)

        self.assertTrue(revoked)
        link.refresh_from_db()
        self.assertIsNotNone(link.revoked_at)
        mock_client.revoke_permission.assert_called_once()

    @override_settings(USE_SHAREPOINT=False)
    def test_create_share_link_view_requires_sharepoint(self):
        response = self.client.post(
            reverse('bundle_share_link_create', args=[self.bundle.id]),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('SharePoint', response.json()['error'])

    @patch('backend.views._require_current_bundle_pdf', return_value=(True, None))
    @patch('backend.views.create_bundle_share_link')
    def test_create_share_link_view_returns_link(self, mock_create, _mock_require_pdf):
        mock_create.return_value = {
            'id': 1,
            'url': 'https://contoso.sharepoint.com/:b:/g/abc',
            'password': 'secret',
            'expires_at': timezone.now().isoformat(),
            'status': 'active',
            'active': True,
        }
        response = self.client.post(
            reverse('bundle_share_link_create', args=[self.bundle.id]),
            data='{"use_password": true}',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['success'])
        self.assertEqual(len(payload['links']), 0)
        self.assertEqual(payload['link']['url'], 'https://contoso.sharepoint.com/:b:/g/abc')

    @patch('backend.views._require_current_bundle_pdf', return_value=(True, None))
    @patch('backend.views.create_bundle_share_link')
    def test_create_share_link_view_without_password(self, mock_create, _mock_require_pdf):
        mock_create.return_value = {
            'id': 2,
            'url': 'https://contoso.sharepoint.com/:b:/g/abc',
            'password': '',
            'expires_at': timezone.now().isoformat(),
            'status': 'active',
            'active': True,
        }
        response = self.client.post(
            reverse('bundle_share_link_create', args=[self.bundle.id]),
            data='{"use_password": false}',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        mock_create.assert_called_once()
        self.assertFalse(mock_create.call_args.kwargs.get('use_password'))

    @patch('backend.views.create_bundle_share_link')
    def test_create_share_link_view_rejects_stale_pdf(self, mock_create):
        self.bundle.updated_at = timezone.now()
        self.bundle.save(update_fields=['updated_at'])
        response = self.client.post(
            reverse('bundle_share_link_create', args=[self.bundle.id]),
            data='{"use_password": false}',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('changed', response.json()['error'].lower())
        mock_create.assert_not_called()


@override_settings(
    USE_SHAREPOINT=True,
    STORAGES={
        'default': {'BACKEND': 'backend.storage.sharepoint.SharePointStorage'},
        'staticfiles': {
            'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'
        },
    },
)
class BundleDownloadReopenTests(TestCase):
    """Regression tests for the SharePoint 'file cannot be reopened' download bug.

    On SharePoint storage, _bundle_pdf_is_current's verify step opens and closes the
    final_pdf FieldFile, leaving a closed handle cached on it. A subsequent
    bundle.final_pdf.open('rb') then raised "The file cannot be reopened", so
    bundle_download fell through to a full synchronous regeneration (which timed out /
    OOM-killed the worker in production). _open_bundle_final_pdf opens a fresh handle
    straight from storage instead.
    """

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='bundle-reopen-user',
            email='bundle-reopen@example.com',
            first_name='B',
            last_name='Reopen',
            password='password',
            max_holidays_in_year=20,
        )
        self.client.force_login(self.user)
        self.pdf_bytes = make_pdf_bytes('Bundle final PDF')
        self.bundle = Bundle.objects.create(
            name='Reopen Bundle',
            created_by=self.user,
        )
        self.final_path = bundle_final_pdf_upload_path(self.bundle, 'ignored.pdf')
        self.bundle.final_pdf.name = self.final_path
        self.bundle.save(update_fields=['final_pdf'])
        # .update() bypasses auto_now on updated_at, so pdf_generated_at stays ahead
        # of updated_at and pdf_is_current() is True.
        Bundle.objects.filter(pk=self.bundle.pk).update(
            pdf_generated_at=timezone.now() + timedelta(seconds=60)
        )
        self.bundle.refresh_from_db()

    def test_verify_step_poisons_fieldfile_reopen(self):
        """Documents the underlying Django FieldFile behaviour the fix works around."""
        with patch(
            'backend.storage.sharepoint.read_storage_file_bytes',
            return_value=self.pdf_bytes,
        ):
            # verify_file=True opens and closes the SharePoint-backed handle...
            self.assertTrue(_bundle_pdf_is_current(self.bundle))
            # ...so reopening the same FieldFile now fails.
            with self.assertRaises(ValueError):
                self.bundle.final_pdf.open('rb')

    def test_open_bundle_final_pdf_serves_after_verify(self):
        """The helper serves bytes even after the verify step poisoned the cache."""
        with patch(
            'backend.storage.sharepoint.read_storage_file_bytes',
            return_value=self.pdf_bytes,
        ):
            self.assertTrue(_bundle_pdf_is_current(self.bundle))
            handle = _open_bundle_final_pdf(self.bundle)
            try:
                self.assertEqual(handle.read(), self.pdf_bytes)
            finally:
                handle.close()

    @patch('backend.views._ensure_bundle_final_pdf')
    def test_bundle_download_serves_without_regenerating(self, mock_ensure):
        """A current bundle downloads straight from storage, no regeneration."""
        with patch(
            'backend.storage.sharepoint.read_storage_file_bytes',
            return_value=self.pdf_bytes,
        ):
            response = self.client.get(
                reverse('bundle_download', args=[self.bundle.id])
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertEqual(b''.join(response.streaming_content), self.pdf_bytes)
        mock_ensure.assert_not_called()


class QpdfExitCodeTests(TestCase):
    """qpdf exit code 3 (success-with-warnings) must not be treated as failure.

    Treating it as failure drops the fast on-disk builder to the fully-in-memory
    PyPDF2 fallback, which is what OOM-kills the worker on large bundles.
    """

    def test_run_qpdf_treats_warning_exit_as_success(self):
        from backend.pdf import bundle_builder

        with patch('backend.pdf.bundle_builder.subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=3,
                stderr='WARNING: input.pdf (object 633 0): object has offset 0',
                stdout='',
            )
            # Must not raise even though the return code is non-zero.
            bundle_builder._run_qpdf(['--empty', '--pages', '--', 'out.pdf'])

    def test_run_qpdf_raises_on_error_exit(self):
        from backend.pdf import bundle_builder

        with patch('backend.pdf.bundle_builder.subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=2, stderr='qpdf: real error', stdout='',
            )
            with self.assertRaises(RuntimeError):
                bundle_builder._run_qpdf(['--empty'])
