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
    MatterType,
    WIP,
)


def make_client(name):
    return ClientContactDetails.objects.create(
        name=name,
        occupation='Retired',
        address_line1='1 Test Street',
        address_line2='',
        county='Essex',
        postcode='SS7 1QT',
        email='test@example.com',
        contact_number='0123456789',
    )


class ExpiredClientIdReportTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='cmp',
            email='cmp@example.com',
            first_name='Comp',
            last_name='Officer',
            password='password',
            max_holidays_in_year=20,
        )
        self.client.force_login(self.user)
        self.today = timezone.localdate()

    def _add_id(self, client, *, category='proof_of_id', expiry_offset_days=None,
                document_type='Passport', reference='P123'):
        return ClientKeyDocument.objects.create(
            client=client,
            category=category,
            document_type=document_type,
            document_reference=reference,
            expiry_date=(self.today + timedelta(days=expiry_offset_days)
                         if expiry_offset_days is not None else None),
        )

    def test_only_expired_proof_of_id_is_reported(self):
        from ..views import get_clients_with_expired_id

        expired = make_client('Expired Ed')
        self._add_id(expired, expiry_offset_days=-10)

        valid = make_client('Valid Val')
        self._add_id(valid, expiry_offset_days=30)

        no_expiry = make_client('Noexpiry Ned')
        self._add_id(no_expiry, expiry_offset_days=None)

        expired_address = make_client('Address Al')
        self._add_id(expired_address, category='proof_of_address',
                     expiry_offset_days=-5)

        rows = get_clients_with_expired_id()
        names = [r['client_name'] for r in rows]

        self.assertEqual(names, ['Expired Ed'])
        self.assertEqual(rows[0]['days_overdue'], 10)

    def test_rows_ordered_most_overdue_first(self):
        from ..views import get_clients_with_expired_id

        self._add_id(make_client('Recently Rex'), expiry_offset_days=-2)
        self._add_id(make_client('Ancient Ann'), expiry_offset_days=-200)

        rows = get_clients_with_expired_id()
        self.assertEqual(
            [r['client_name'] for r in rows],
            ['Ancient Ann', 'Recently Rex'],
        )

    def test_report_includes_associated_file_numbers(self):
        from ..views import get_clients_with_expired_id

        client = make_client('Filed Fay')
        self._add_id(client, expiry_offset_days=-1)
        mt = MatterType.objects.create(type='Probate')
        WIP.objects.create(file_number='PRB9001', client1=client,
                           matter_description='m', matter_type=mt, funding='Pvt')
        secondary = WIP.objects.create(
            file_number='CV9002', client1=make_client('Lead Len'),
            matter_description='m', matter_type=mt, funding='Pvt')
        secondary.additional_clients.add(client)

        rows = get_clients_with_expired_id()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['file_numbers'], ['CV9002', 'PRB9001'])

    def test_csv_download(self):
        self._add_id(make_client('Expired Ed'), expiry_offset_days=-10)

        response = self.client.get(reverse('download_expired_client_ids'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        self.assertIn('attachment; filename="expired_client_ids_',
                      response['Content-Disposition'])

        content = response.content.decode('utf-8')
        reader = list(csv.reader(io.StringIO(content)))
        self.assertEqual(reader[0], ['Clients with Expired ID'])
        header = reader[2]
        self.assertEqual(header[0], 'Client')
        self.assertIn('Expiry Date', header)
        self.assertIn('File Number(s)', header)
        # The expired client appears in a data row.
        self.assertTrue(any('Expired Ed' in row for row in reader[3:]))

    def test_management_reports_page_lists_expired_ids(self):
        # Management reports are now hard-gated to managers.
        self.user.is_manager = True
        self.user.save()
        self._add_id(make_client('Expired Ed'), expiry_offset_days=-10)
        response = self.client.get(reverse('management_reports'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Clients with Expired ID')
        self.assertContains(response, 'Expired Ed')
