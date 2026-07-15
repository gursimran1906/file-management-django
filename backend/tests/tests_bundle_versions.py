import shutil
import tempfile
from datetime import timedelta

from django.core.files.storage import default_storage
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from backend.models import Bundle, BundleShareLink, BundleVersion
from backend.sharepoint.sharing import (
    SharePointSharingError,
    assert_bundle_final_pdf_path,
    bundle_version_storage_path,
)
from backend.views import _prune_bundle_versions, _save_bundle_version
from users.models import CustomUser


def pdf_bytes(marker):
    """Synthetic PDF-ish bytes. Content isn't parsed, only hashed and stored."""
    return b'%PDF-1.4\n' + marker.encode('utf-8') + b'\n%%EOF'


@override_settings(
    MEDIA_ROOT=tempfile.mkdtemp(),
    USE_SHAREPOINT=False,
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {
            'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'
        },
    },
)
class BundleVersioningTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        media_root = cls._overridden_settings['MEDIA_ROOT']
        super().tearDownClass()
        shutil.rmtree(media_root, ignore_errors=True)

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='ver-user',
            email='ver@example.com',
            first_name='V',
            last_name='User',
            password='password',
            max_holidays_in_year=20,
        )
        self.client.force_login(self.user)
        self.bundle = Bundle.objects.create(name='Version Bundle', created_by=self.user)

    def _generate(self, marker, **kwargs):
        return _save_bundle_version(
            self.bundle, pdf_bytes(marker), user=self.user, **kwargs)

    # -- version creation -------------------------------------------------

    def test_first_generation_creates_v1_and_sets_current(self):
        version, created = self._generate('one', page_count=3, document_count=2)
        self.assertTrue(created)
        self.assertEqual(version.version, 1)
        self.assertEqual(self.bundle.current_version_id, version.id)
        self.assertEqual(self.bundle.final_pdf.name, version.final_pdf.name)
        self.assertEqual(version.page_count, 3)
        self.assertEqual(version.size_bytes, len(pdf_bytes('one')))
        self.assertTrue(version.content_hash)
        self.assertTrue(default_storage.exists(version.final_pdf.name))
        self.assertIn(f'/{self.bundle.uuid}/v1.pdf', version.final_pdf.name)

    def test_regeneration_creates_new_version_and_keeps_old_file(self):
        v1, _ = self._generate('one')
        v2, created = self._generate('two')
        self.assertTrue(created)
        self.assertEqual(v2.version, 2)
        self.assertEqual(self.bundle.current_version_id, v2.id)
        # The previous version's file is NOT deleted, so its share links survive.
        self.assertTrue(default_storage.exists(v1.final_pdf.name))
        self.assertTrue(default_storage.exists(v2.final_pdf.name))
        self.assertEqual(self.bundle.versions.count(), 2)

    def test_identical_output_does_not_create_new_version(self):
        same = pdf_bytes('same')
        v1, created1 = _save_bundle_version(self.bundle, same, user=self.user)
        v2, created2 = _save_bundle_version(self.bundle, same, user=self.user)
        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertEqual(v1.id, v2.id)
        self.assertEqual(self.bundle.versions.count(), 1)

    # -- retention / pruning ---------------------------------------------

    def test_prune_keeps_last_three_and_current(self):
        versions = [self._generate(f'v{i}')[0] for i in range(1, 6)]  # v1..v5
        pruned = _prune_bundle_versions(self.bundle, keep_recent=3)
        self.assertEqual(pruned, 2)
        remaining = set(self.bundle.versions.values_list('version', flat=True))
        self.assertEqual(remaining, {3, 4, 5})
        # Pruned files are removed from storage.
        self.assertFalse(default_storage.exists(versions[0].final_pdf.name))
        self.assertFalse(default_storage.exists(versions[1].final_pdf.name))

    def test_prune_keeps_pinned_version(self):
        versions = [self._generate(f'v{i}')[0] for i in range(1, 6)]
        versions[0].pinned = True
        versions[0].save(update_fields=['pinned'])
        _prune_bundle_versions(self.bundle, keep_recent=3)
        self.assertTrue(self.bundle.versions.filter(version=1).exists())

    def test_prune_keeps_version_with_active_share_link(self):
        versions = [self._generate(f'v{i}')[0] for i in range(1, 6)]
        BundleShareLink.objects.create(
            bundle=self.bundle,
            version=versions[0],
            url='https://example/share',
            permission_id='perm-1',
            expires_at=timezone.now() + timedelta(days=10),
        )
        _prune_bundle_versions(self.bundle, keep_recent=3)
        self.assertTrue(self.bundle.versions.filter(version=1).exists())
        self.assertTrue(default_storage.exists(versions[0].final_pdf.name))

    def test_share_link_bound_to_version_survives_regeneration(self):
        v1, _ = self._generate('one')
        link = BundleShareLink.objects.create(
            bundle=self.bundle,
            version=v1,
            url='https://example/share',
            permission_id='perm-1',
            expires_at=timezone.now() + timedelta(days=10),
        )
        self._generate('two')  # regenerate -> v2 current
        _prune_bundle_versions(self.bundle, keep_recent=3)
        link.refresh_from_db()
        self.assertEqual(link.version_id, v1.id)
        with default_storage.open(v1.final_pdf.name, 'rb') as handle:
            self.assertEqual(handle.read(), pdf_bytes('one'))

    # -- path validation --------------------------------------------------

    def test_assert_accepts_versioned_path(self):
        v1, _ = self._generate('one')
        # Should not raise.
        assert_bundle_final_pdf_path(self.bundle, v1.final_pdf.name)
        self.assertEqual(bundle_version_storage_path(v1), v1.final_pdf.name)

    def test_assert_rejects_other_bundle_versioned_path(self):
        other = Bundle.objects.create(name='Other', created_by=self.user)
        bad_path = f'BundleFinal/unassigned/{other.uuid}/v1.pdf'
        with self.assertRaises(SharePointSharingError):
            assert_bundle_final_pdf_path(self.bundle, bad_path)

    # -- endpoints --------------------------------------------------------

    def test_promote_sets_current_and_final_pdf(self):
        v1, _ = self._generate('one')
        v2, _ = self._generate('two')
        self.assertEqual(self.bundle.current_version_id, v2.id)
        response = self.client.post(
            reverse('bundle_version_promote', args=[self.bundle.id, v1.id]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.bundle.refresh_from_db()
        self.assertEqual(self.bundle.current_version_id, v1.id)
        self.assertEqual(self.bundle.final_pdf.name, v1.final_pdf.name)

    def test_version_download_streams_file(self):
        v1, _ = self._generate('one')
        response = self.client.get(
            reverse('bundle_version_download', args=[self.bundle.id, v1.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertEqual(b''.join(response.streaming_content), pdf_bytes('one'))

    def test_pin_toggles_and_survives_prune(self):
        v1, _ = self._generate('one')
        for i in range(2, 6):
            self._generate(f'v{i}')
        response = self.client.post(
            reverse('bundle_version_pin', args=[self.bundle.id, v1.id]),
            data='{"pinned": true}',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        v1.refresh_from_db()
        self.assertTrue(v1.pinned)
        _prune_bundle_versions(self.bundle, keep_recent=3)
        self.assertTrue(self.bundle.versions.filter(version=1).exists())

    def test_versions_view_returns_version_list(self):
        self._generate('one')
        self._generate('two')
        response = self.client.get(
            reverse('bundle_versions', args=[self.bundle.id]))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload['versions']), 2)
        self.assertEqual(payload['current_version_id'], self.bundle.current_version_id)
        self.assertEqual(payload['versions'][0]['version'], 2)  # newest first
        self.assertTrue(payload['versions'][0]['is_current'])
