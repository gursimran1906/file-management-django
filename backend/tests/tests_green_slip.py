from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from users.models import CustomUser
from ..models import ClientContactDetails, LedgerAccountTransfers, MatterType, WIP


def make_client(name='Test Client'):
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


def make_matter(file_number='GRN0001'):
    client = make_client()
    matter_type = MatterType.objects.create(type='Probate')
    return WIP.objects.create(
        file_number=file_number,
        client1=client,
        matter_description='Test matter',
        matter_type=matter_type,
        funding='Pvt',
    )


class GreenSlipAddTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='greenuser',
            email='green@example.com',
            first_name='Green',
            last_name='User',
            password='password',
            max_holidays_in_year=20,
        )
        self.matter_a = make_matter('GRN0001')
        self.matter_b = make_matter('GRN0002')

    def _post_green_slip(self, from_matter, to_matter):
        self.client.force_login(self.user)
        return self.client.post(
            reverse('add_green_slip', args=[from_matter.file_number]),
            {
                'date': '2024-06-01',
                'from_ledger_account': 'C',
                'file_number_from': from_matter.id,
                'to_ledger_account': 'C',
                'file_number_to': to_matter.id,
                'amount': '250.00',
                'description': 'Transfer between files',
            },
        )

    def test_outgoing_green_slip_from_current_matter(self):
        response = self._post_green_slip(self.matter_a, self.matter_b)
        self.assertEqual(response.status_code, 302)
        slip = LedgerAccountTransfers.objects.get()
        self.assertEqual(slip.file_number_from_id, self.matter_a.id)
        self.assertEqual(slip.file_number_to_id, self.matter_b.id)
        self.assertEqual(slip.balance_left_from, Decimal('250.00'))
        self.assertEqual(slip.balance_left_to, Decimal('250.00'))
        self.assertEqual(slip.created_by_id, self.user.id)

    def test_incoming_green_slip_to_current_matter(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('add_green_slip', args=[self.matter_b.file_number]),
            {
                'date': '2024-06-01',
                'from_ledger_account': 'C',
                'file_number_from': self.matter_a.id,
                'to_ledger_account': 'C',
                'file_number_to': self.matter_b.id,
                'amount': '100.00',
                'description': 'Incoming transfer',
            },
        )
        self.assertEqual(response.status_code, 302)
        slip = LedgerAccountTransfers.objects.get()
        self.assertEqual(slip.file_number_from_id, self.matter_a.id)
        self.assertEqual(slip.file_number_to_id, self.matter_b.id)

    def test_rejects_transfer_not_involving_current_matter(self):
        self.client.force_login(self.user)
        other = make_matter('GRN0003')
        response = self.client.post(
            reverse('add_green_slip', args=[self.matter_a.file_number]),
            {
                'date': '2024-06-01',
                'from_ledger_account': 'C',
                'file_number_from': self.matter_b.id,
                'to_ledger_account': 'C',
                'file_number_to': other.id,
                'amount': '100.00',
                'description': 'Unrelated transfer',
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(LedgerAccountTransfers.objects.count(), 0)
