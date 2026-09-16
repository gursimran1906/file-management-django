"""MatterClient / MatterClientDocument / ConveyancingDetails models, and the
mixture backfill (reconstruct from per-matter evidence where it exists, fan-out
the client flags where it doesn't)."""
import importlib
import tempfile
from datetime import date
from decimal import Decimal

from django.apps import apps as global_apps
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from users.models import CustomUser

from ..models import (ClientContactDetails, ClientKeyDocument, ConveyancingDetails,
                      FileStatus, MatterClient, MatterClientDocument, WIP)

backfill_mig = importlib.import_module(
    'backend.migrations.0084_backfill_matter_clients')


def make_client(name='Jane Doe', **kw):
    defaults = dict(occupation='Retired', address_line1='1 Test Street',
                    address_line2='', county='Essex', postcode='SS7 1QT',
                    email='jane@example.com', contact_number='0123456789')
    defaults.update(kw)
    return ClientContactDetails.objects.create(name=name, **defaults)


def make_matter(client, file_number='ABC0000001', **kw):
    return WIP.objects.create(
        file_number=file_number, client1=client, funding='PRI', **kw)


class MatterClientModelTests(TestCase):
    def test_models_and_relations(self):
        c = make_client()
        m = make_matter(c)
        mc = MatterClient.objects.create(matter=m, client=c, is_lead=True)
        self.assertEqual(str(mc), f'{m.file_number} - {c.name}')
        self.assertEqual(list(m.matter_clients.all()), [mc])

        conv = ConveyancingDetails.objects.create(
            matter=m, transaction_type='purchase',
            property_price=Decimal('450000.00'),
            property_address='12 Oak Street')
        self.assertEqual(m.conveyancing.property_price, Decimal('450000.00'))
        self.assertEqual(conv.get_transaction_type_display(), 'Purchase')


class BackfillMixtureTests(TestCase):
    def test_reconstructs_terms_from_matter_dates(self):
        c = make_client(terms_of_engagement_signed=False)
        rcvd = date(2025, 5, 1)
        m = make_matter(c, date_of_toe_sent=date(2025, 4, 1), date_of_toe_rcvd=rcvd)

        backfill_mig.backfill(global_apps, None)

        mc = MatterClient.objects.get(matter=m, client=c)
        self.assertTrue(mc.terms_of_engagement_signed)       # from the matter date
        self.assertEqual(mc.terms_received_on, rcvd)
        self.assertEqual(mc.source, 'reconstructed')
        self.assertTrue(mc.is_lead)

    def test_terms_sent_but_not_received_is_not_signed(self):
        # Issued but not returned: reconstructed (we have evidence), but not signed.
        c = make_client(terms_of_engagement_signed=True)  # client flag ignored here
        m = make_matter(c, file_number='ABC0000005',
                        date_of_toe_sent=date(2025, 4, 1))  # no rcvd date

        backfill_mig.backfill(global_apps, None)

        mc = MatterClient.objects.get(matter=m, client=c)
        self.assertFalse(mc.terms_of_engagement_signed)
        self.assertEqual(mc.terms_sent_on, date(2025, 4, 1))
        self.assertIsNone(mc.terms_received_on)
        self.assertEqual(mc.source, 'reconstructed')

    def test_fans_out_client_flags_when_no_evidence(self):
        c = make_client(terms_of_engagement_signed=True, pep_signed=True,
                        ncba_signed=True, source_of_funds_signed=False)
        m = make_matter(c, file_number='ABC0000002')

        backfill_mig.backfill(global_apps, None)

        mc = MatterClient.objects.get(matter=m, client=c)
        self.assertTrue(mc.terms_of_engagement_signed)
        self.assertTrue(mc.pep_signed)
        self.assertTrue(mc.ncba_signed)
        self.assertFalse(mc.source_of_funds_signed)
        self.assertEqual(mc.source, 'carried_over')

    def test_is_idempotent(self):
        c = make_client()
        m = make_matter(c, file_number='ABC0000003')
        backfill_mig.backfill(global_apps, None)
        backfill_mig.backfill(global_apps, None)
        self.assertEqual(MatterClient.objects.filter(matter=m).count(), 1)

    def test_covers_lead_and_additional_clients(self):
        lead = make_client('Lead', email='l@example.com')
        second = make_client('Second', email='s@example.com')
        m = make_matter(lead, file_number='ABC0000004')
        m.additional_clients.add(second)

        backfill_mig.backfill(global_apps, None)

        rows = {r.client.name: r for r in MatterClient.objects.filter(matter=m)}
        self.assertEqual(set(rows), {'Lead', 'Second'})
        self.assertTrue(rows['Lead'].is_lead)
        self.assertFalse(rows['Second'].is_lead)


class MatterHomeRenderTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='abc', email='abc@example.com', first_name='A', last_name='B',
            password='pw', max_holidays_in_year=20)
        self.client.force_login(self.user)

    def test_home_renders_compliance_panel_and_creates_rows(self):
        c = make_client('Home Client')
        status = FileStatus.objects.create(status='Open')
        m = WIP.objects.create(file_number='HOM0000001', client1=c, funding='PRI',
                               file_status=status)

        resp = self.client.get(reverse('home', args=[m.file_number]))

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Client care &amp; compliance')
        self.assertContains(resp, 'Home Client')
        # MatterClient row is created lazily on view.
        self.assertTrue(MatterClient.objects.filter(matter=m, client=c).exists())

    @override_settings(MEDIA_ROOT=tempfile.mkdtemp())
    def test_key_document_file_upload_and_preview(self):
        c = make_client('Doc Client', email='doc@example.com')
        status = FileStatus.objects.create(status='Open')
        m = WIP.objects.create(file_number='KD00000001', client1=c, funding='PRI',
                               file_status=status)
        kd = ClientKeyDocument.objects.create(client=c, category='proof_of_id')
        self.assertFalse(bool(kd.file))

        upload = SimpleUploadedFile('passport.pdf', b'%PDF-1.4 test',
                                    content_type='application/pdf')
        resp = self.client.post(
            reverse('client_key_document_upload', args=[m.file_number, kd.id]),
            {'document': upload})
        self.assertEqual(resp.status_code, 302)
        kd.refresh_from_db()
        self.assertTrue(bool(kd.file))

        preview = self.client.get(
            reverse('client_key_document_preview', args=[kd.id]))
        self.assertEqual(preview.status_code, 200)

    def test_save_compliance_records_signed_flags(self):
        c = make_client('Save Client', email='save@example.com')
        status = FileStatus.objects.create(status='Open')
        m = WIP.objects.create(file_number='HOM0000002', client1=c, funding='PRI',
                               file_status=status)
        mc = MatterClient.objects.create(matter=m, client=c, is_lead=True)

        resp = self.client.post(
            reverse('matter_save_client_compliance', args=[m.file_number, mc.id]),
            {'terms_signed': '1', 'pep_signed': '1', 'sof_details': 'Savings'})

        self.assertEqual(resp.status_code, 302)
        mc.refresh_from_db()
        self.assertTrue(mc.terms_of_engagement_signed)
        self.assertTrue(mc.pep_signed)
        self.assertFalse(mc.ncba_signed)
        self.assertEqual(mc.source_of_funds_details, 'Savings')
        self.assertEqual(mc.source, MatterClient.SOURCE_CAPTURED)
        self.assertIsNotNone(mc.terms_of_engagement_on)
