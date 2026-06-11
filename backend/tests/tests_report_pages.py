import csv
import io
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from users.models import CustomUser

from ..models import (
    ClientContactDetails,
    ClientKeyDocument,
    FileStatus,
    MatterType,
    WIP,
)


def make_client(name, is_business=False):
    return ClientContactDetails.objects.create(
        name=name, occupation='Retired', address_line1='1 St', address_line2='',
        county='Essex', postcode='SS7 1QT', email='e@example.com',
        contact_number='0123456789', is_business=is_business,
    )


def make_live_matter(file_number, client, fee_earner=None, status='Open'):
    fs, _ = FileStatus.objects.get_or_create(status=status)
    mt, _ = MatterType.objects.get_or_create(type='Probate')
    return WIP.objects.create(
        file_number=file_number, client1=client, matter_description='Matter',
        matter_type=mt, file_status=fs, fee_earner=fee_earner, funding='Pvt',
    )


class ClientDocumentIssueReportTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='rpt', email='rpt@example.com', first_name='Rep',
            last_name='Ort', password='password', max_holidays_in_year=20,
        )
        self.client.force_login(self.user)
        self.today = timezone.localdate()

    def _doc(self, client, category, *, days=None, doc_type='Passport'):
        return ClientKeyDocument.objects.create(
            client=client, category=category, document_type=doc_type,
            expiry_date=(self.today + timedelta(days=days)) if days is not None else None,
        )

    def test_missing_document_flags_live_matter_client(self):
        client = make_client('Missing Mo')
        make_live_matter('LM0001', client)  # no ID document at all
        resp = self.client.get(reverse('report_expired_ids'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Proof of ID issues')
        self.assertContains(resp, 'Missing Mo')
        self.assertContains(resp, 'Missing')

    def test_expired_document_flags_client(self):
        client = make_client('Expired Ed')
        make_live_matter('LM0002', client)
        self._doc(client, 'proof_of_id', days=-30)
        resp = self.client.get(reverse('report_expired_ids'))
        self.assertContains(resp, 'Expired Ed')
        self.assertContains(resp, 'Expired')

    def test_valid_document_not_flagged(self):
        client = make_client('Valid Val')
        make_live_matter('LM0003', client)
        self._doc(client, 'proof_of_id', days=365)
        resp = self.client.get(reverse('report_expired_ids'))
        self.assertNotContains(resp, 'Valid Val')

    def test_client_without_live_matter_excluded(self):
        client = make_client('Orphan Olly')  # expired ID but on no matter
        self._doc(client, 'proof_of_id', days=-30)
        resp = self.client.get(reverse('report_expired_ids'))
        self.assertNotContains(resp, 'Orphan Olly')

    def test_status_filter_missing_vs_expired(self):
        missing = make_client('Missing Mo')
        make_live_matter('LM0010', missing)
        expired = make_client('Expired Ed')
        make_live_matter('LM0011', expired)
        self._doc(expired, 'proof_of_id', days=-10)

        resp = self.client.get(reverse('report_expired_ids'), {'status': 'missing'})
        self.assertContains(resp, 'Missing Mo')
        self.assertNotContains(resp, 'Expired Ed')

        resp = self.client.get(reverse('report_expired_ids'), {'status': 'expired'})
        self.assertContains(resp, 'Expired Ed')
        self.assertNotContains(resp, 'Missing Mo')

    def test_text_and_client_type_filters(self):
        biz = make_client('Acme Ltd', is_business=True)
        make_live_matter('LM0020', biz)
        person = make_client('Jane Person')
        make_live_matter('LM0021', person)

        resp = self.client.get(reverse('report_expired_ids'), {'q': 'acme'})
        self.assertContains(resp, 'Acme Ltd')
        self.assertNotContains(resp, 'Jane Person')

        resp = self.client.get(reverse('report_expired_ids'), {'client_type': 'business'})
        self.assertContains(resp, 'Acme Ltd')
        self.assertNotContains(resp, 'Jane Person')

    def test_min_days_filter_only_narrows_expired(self):
        old = make_client('Old Ollie')
        make_live_matter('LM0030', old)
        self._doc(old, 'proof_of_id', days=-100)
        recent = make_client('Recent Rex')
        make_live_matter('LM0031', recent)
        self._doc(recent, 'proof_of_id', days=-5)

        resp = self.client.get(reverse('report_expired_ids'), {'min_days': '30'})
        self.assertContains(resp, 'Old Ollie')
        self.assertNotContains(resp, 'Recent Rex')

    def test_sort_by_client_name(self):
        a = make_client('Amy First')
        make_live_matter('LM0040', a)
        z = make_client('Zoe Last')
        make_live_matter('LM0041', z)
        resp = self.client.get(reverse('report_expired_ids'), {'sort': 'client'})
        content = resp.content.decode()
        self.assertLess(content.index('Amy First'), content.index('Zoe Last'))

    def test_export_csv_filename_and_filter(self):
        keep = make_client('Keep Kim')
        make_live_matter('LM0050', keep)
        drop = make_client('Drop Dan')
        make_live_matter('LM0051', drop)

        resp = self.client.get(reverse('report_expired_ids'),
                               {'q': 'keep', 'export': 'csv'})
        self.assertEqual(resp['Content-Type'], 'text/csv')
        self.assertIn('attachment; filename="proof_of_id_issues_',
                      resp['Content-Disposition'])
        rows = list(csv.reader(io.StringIO(resp.content.decode())))
        body = '\n'.join(','.join(r) for r in rows)
        self.assertIn('Keep Kim', body)
        self.assertNotIn('Drop Dan', body)

    def test_proof_of_address_report_is_separate(self):
        # Client flagged only for address: has a valid ID but expired address.
        addr = make_client('Addr Al')
        make_live_matter('LM0060', addr)
        self._doc(addr, 'proof_of_id', days=365)
        self._doc(addr, 'proof_of_address', days=-20, doc_type='Bank statement')

        # Client flagged only for ID: valid address, expired ID.
        idc = make_client('Id Ian')
        make_live_matter('LM0061', idc)
        self._doc(idc, 'proof_of_id', days=-20)
        self._doc(idc, 'proof_of_address', days=365)

        poa = self.client.get(reverse('report_expired_proof_of_address'))
        self.assertContains(poa, 'Proof of Address issues')
        self.assertContains(poa, 'Addr Al')
        self.assertNotContains(poa, 'Id Ian')

        ids = self.client.get(reverse('report_expired_ids'))
        self.assertContains(ids, 'Id Ian')
        self.assertNotContains(ids, 'Addr Al')


class FileReviewsReportTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='rpt2', email='rpt2@example.com', first_name='Rep',
            last_name='Two', password='password', max_holidays_in_year=20,
        )
        self.client.force_login(self.user)

    def test_file_reviews_due_report_and_filter(self):
        fee_earner = CustomUser.objects.create_user(
            username='fe1', email='fe1@example.com', first_name='Fee',
            last_name='Earner', password='password', max_holidays_in_year=20,
        )
        make_live_matter('REV0001', make_client('Rev Client'), fee_earner=fee_earner)

        resp = self.client.get(reverse('report_file_reviews_due'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'REV0001')
        self.assertContains(resp, 'Never reviewed')

        resp = self.client.get(reverse('report_file_reviews_due'),
                               {'fee_earner': str(fee_earner.id)})
        self.assertContains(resp, 'REV0001')
        resp = self.client.get(reverse('report_file_reviews_due'),
                               {'fee_earner': '999999'})
        self.assertNotContains(resp, 'REV0001')


class HardEnforcementTests(TestCase):
    def setUp(self):
        self.staff = CustomUser.objects.create_user(
            username='stf', email='stf@example.com', first_name='Staff',
            last_name='Member', password='password', max_holidays_in_year=20,
        )
        self.manager = CustomUser.objects.create_user(
            username='mgr', email='mgr@example.com', first_name='Man',
            last_name='Ager', password='password', max_holidays_in_year=20,
            is_manager=True,
        )

    def test_non_manager_gets_403_on_management_reports(self):
        self.client.force_login(self.staff)
        for name in ['management_reports', 'invoices_list', 'user_weekly_report',
                     'download_cashier_data', 'download_invoices']:
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)

    def test_manager_can_open_management_pages(self):
        self.client.force_login(self.manager)
        self.assertEqual(
            self.client.get(reverse('management_reports')).status_code, 200)
        self.assertEqual(
            self.client.get(reverse('invoices_list')).status_code, 200)

    def test_standard_reports_open_to_all_staff(self):
        self.client.force_login(self.staff)
        for name in ['reports_hub', 'report_expired_ids',
                     'report_expired_proof_of_address', 'report_file_reviews_due']:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
