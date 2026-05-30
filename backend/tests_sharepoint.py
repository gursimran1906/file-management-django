import os
import shutil
import tempfile
from io import BytesIO
from unittest.mock import MagicMock, patch

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from reportlab.pdfgen import canvas

from backend.models import Bundle, BundleDocument, BundleSection, Undertaking
from backend.sharepoint.bundle_cache import BundleTempCache
from backend.sharepoint.client import SharePointClient
from backend.sharepoint.paths import (
    bundle_document_upload_path,
    bundle_final_pdf_upload_path,
    sanitize_filename,
    undertaking_file_upload_path,
)
from backend.views import _collect_bundle_documents, _generate_bundle_pdf
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
        self.assertEqual(sanitize_filename('letter (final).pdf'), 'letter _final.pdf')

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
