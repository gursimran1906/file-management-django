from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from users.models import CustomUser
from .models import ClientContactDetails, Invoices, MatterType, Modifications, PmtsSlips, WIP


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


def make_matter(file_number='PRB0001'):
    client = make_client()
    matter_type = MatterType.objects.create(type='Probate')
    return WIP.objects.create(
        file_number=file_number,
        client1=client,
        matter_description='Test matter',
        matter_type=matter_type,
        funding='Pvt',
    )


class InvoiceImmutabilityTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='invuser',
            email='inv@example.com',
            first_name='Inv',
            last_name='User',
            password='password',
            max_holidays_in_year=20,
        )
        self.manager = CustomUser.objects.create_user(
            username='invmgr',
            email='invmgr@example.com',
            first_name='Inv',
            last_name='Manager',
            password='password',
            max_holidays_in_year=20,
            is_manager=True,
        )
        self.matter = make_matter()
        self.invoice = Invoices.objects.create(
            file_number=self.matter,
            invoice_number=1001,
            state='F',
            date=date(2024, 6, 1),
            description='Probate costs',
            our_costs=['100.00'],
            our_costs_desc=['Work'],
            vat=Decimal('20.00'),
            total_due_left=Decimal('120.00'),
            created_by=self.user,
        )

    def test_final_invoice_cosmetic_update_allowed(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('edit_invoice', args=[self.invoice.id]),
            {
                'payable_by': 'Client',
                'description': 'Updated description',
                'by_email': 'on',
            },
        )
        self.assertEqual(response.status_code, 302)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.description, 'Updated description')
        self.assertTrue(self.invoice.by_email)
        self.assertEqual(self.invoice.our_costs, ['100.00'])
        self.assertEqual(
            Modifications.objects.filter(object_id=self.invoice.id).count(), 1)

    def test_locked_invoice_matter_final_flag_can_be_toggled(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('edit_invoice', args=[self.invoice.id]),
            {
                'payable_by': 'Client',
                'description': 'Probate costs',
                'is_matter_final_invoice': 'on',
            },
        )
        self.assertEqual(response.status_code, 302)
        self.invoice.refresh_from_db()
        self.assertTrue(self.invoice.is_matter_final_invoice)

    def test_final_invoice_financial_post_ignored(self):
        slip = PmtsSlips.objects.create(
            file_number=self.matter,
            ledger_account='C',
            mode_of_pmt='BT',
            amount=Decimal('500.00'),
            is_money_out=False,
            pmt_person='Client',
            description='Payment in',
            date=date(2024, 5, 1),
            balance_left=Decimal('500.00'),
            created_by=self.user,
        )
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('edit_invoice', args=[self.invoice.id]),
            {
                'payable_by': 'Client',
                'description': 'Probate costs',
                'our_costs_desc[]': ['999.00'],
                'our_costs[]': ['999.00'],
                'blue_slips[]': [str(slip.id)],
            },
        )
        self.assertEqual(response.status_code, 302)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.our_costs, ['100.00'])
        self.assertFalse(self.invoice.moa_ids.filter(id=slip.id).exists())

    def test_manager_can_reopen_final_invoice(self):
        self.client.force_login(self.manager)
        response = self.client.post(
            reverse('reopen_invoice', args=[self.invoice.id]),
        )
        self.assertEqual(response.status_code, 302)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.state, 'D')
        self.assertEqual(self.invoice.invoice_number, 1001)

    def test_non_manager_cannot_reopen(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('reopen_invoice', args=[self.invoice.id]),
        )
        self.assertEqual(response.status_code, 302)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.state, 'F')
