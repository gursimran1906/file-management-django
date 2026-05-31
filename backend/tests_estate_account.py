
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from users.models import CustomUser
from .estate_account import (
    calculate_invoice_total_with_vat,
    get_estate_account_data,
    get_or_create_estate_account,
)
from .models import (
    ClientContactDetails,
    EstateAccount,
    EstateAccountFinanceLineOverride,
    EstateAccountManualEntry,
    MatterType,
    PmtsSlips,
    WIP,
)


def make_client(name='John Deceased'):
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


def make_matter(file_number, matter_type_name='Probate', client_name='John Deceased'):
    client = make_client(client_name)
    matter_type = MatterType.objects.create(type=matter_type_name)
    return WIP.objects.create(
        file_number=file_number,
        client1=client,
        matter_description='Estate of John Deceased',
        matter_type=matter_type,
        funding='Pvt',
    )


class EstateAccountTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='estateuser',
            email='estate@example.com',
            first_name='Estate',
            last_name='User',
            password='password',
            max_holidays_in_year=20,
        )
        self.client.force_login(self.user)
        self.probate_matter = make_matter('PRB0001')
        self.other_matter = make_matter('CV0001', matter_type_name='Conveyancing')

    def test_non_probate_matter_returns_404(self):
        response = self.client.get(reverse('estate_account_view', args=['CV0001']))
        self.assertEqual(response.status_code, 404)

        response = self.client.get(reverse('download_estate_account', args=['CV0001']))
        self.assertEqual(response.status_code, 404)

    def test_probate_page_loads(self):
        response = self.client.get(reverse('estate_account_view', args=['PRB0001']))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Estate account')
        self.assertContains(response, 'John Deceased')

    def test_signers_are_matter_clients(self):
        client2 = make_client('Jane Beneficiary')
        self.probate_matter.client2 = client2
        self.probate_matter.save(update_fields=['client2'])
        estate_account = get_or_create_estate_account(self.probate_matter, self.user)
        data = get_estate_account_data(
            estate_account,
            self.probate_matter,
            calculate_invoice_total_with_vat,
        )
        self.assertEqual(len(data['signers']), 2)
        self.assertEqual(data['signers'][0]['signer_name'], 'John Deceased')
        self.assertEqual(
            data['signers'][0]['signer_address'],
            '1 Test Street, Essex, SS7 1QT',
        )
        self.assertEqual(data['signers'][1]['signer_name'], 'Jane Beneficiary')

    def test_money_out_pink_slip_defaults_to_debt(self):
        estate_account = get_or_create_estate_account(self.probate_matter, self.user)
        PmtsSlips.objects.create(
            file_number=self.probate_matter,
            ledger_account='C',
            mode_of_pmt='BT',
            amount=Decimal('500.00'),
            is_money_out=True,
            pmt_person='Jane Beneficiary',
            description='Estate share',
            date=date(2023, 12, 1),
            balance_left=Decimal('0.00'),
            created_by=self.user,
        )
        data = get_estate_account_data(
            estate_account,
            self.probate_matter,
            calculate_invoice_total_with_vat,
        )
        self.assertEqual(len(data['distribution_payments']), 0)
        self.assertEqual(len(data['debts']), 1)
        self.assertEqual(data['totals']['total_debts_paid'], '500.00')

    def test_credit_note_reduces_invoice_debt(self):
        estate_account = get_or_create_estate_account(self.probate_matter, self.user)
        from .models import CreditNote, Invoices
        invoice = Invoices.objects.create(
            file_number=self.probate_matter,
            invoice_number=1001,
            state='F',
            date=date(2023, 6, 1),
            description='Probate costs',
            our_costs=[100.00],
            vat=Decimal('0.00'),
            created_by=self.user,
        )
        CreditNote.objects.create(
            invoice=invoice,
            file_number=self.probate_matter,
            date=date(2023, 6, 15),
            amount=Decimal('25.00'),
            reason='Adjustment',
            status='F',
            created_by=self.user,
        )
        data = get_estate_account_data(
            estate_account,
            self.probate_matter,
            calculate_invoice_total_with_vat,
        )
        self.assertEqual(len(data['debts']), 1)
        self.assertEqual(data['debts'][0]['amount'], '75.00')
        self.assertIn('less credit', data['debts'][0]['description'].lower())
        self.assertEqual(data['totals']['total_debts_paid'], '75.00')

    def test_money_out_pink_slip_with_invoice_defaults_to_debt(self):
        estate_account = get_or_create_estate_account(self.probate_matter, self.user)
        from .models import Invoices
        invoice = Invoices.objects.create(
            file_number=self.probate_matter,
            invoice_number=1001,
            state='F',
            date=date(2023, 6, 1),
            description='Probate costs',
            our_costs=[100.00],
            vat=Decimal('0.00'),
            created_by=self.user,
        )
        PmtsSlips.objects.create(
            file_number=self.probate_matter,
            ledger_account='C',
            mode_of_pmt='BT',
            amount=Decimal('100.00'),
            is_money_out=True,
            pmt_person='ANP',
            description='Invoice payment',
            date=date(2023, 6, 2),
            balance_left=Decimal('0.00'),
            amount_invoiced={str(invoice.id): {'amt_invoiced': '100.00'}},
            created_by=self.user,
        )
        data = get_estate_account_data(
            estate_account,
            self.probate_matter,
            calculate_invoice_total_with_vat,
        )
        self.assertEqual(len(data['debts']), 2)
        self.assertEqual(len(data['distribution_payments']), 0)

    def test_get_estate_account_data_merges_finance_and_manual_entries(self):
        estate_account = get_or_create_estate_account(self.probate_matter, self.user)
        PmtsSlips.objects.create(
            file_number=self.probate_matter,
            ledger_account='C',
            mode_of_pmt='BT',
            amount=Decimal('100.00'),
            is_money_out=False,
            pmt_person='HMRC',
            description='Refund',
            date=date(2023, 11, 7),
            balance_left=Decimal('100.00'),
            created_by=self.user,
        )
        EstateAccountManualEntry.objects.create(
            estate_account=estate_account,
            section=EstateAccountManualEntry.SECTION_DEBT,
            date=date(2023, 12, 14),
            description='ANP Costs',
            amount=Decimal('50.00'),
            is_pending=True,
            created_by=self.user,
        )
        data = get_estate_account_data(
            estate_account,
            self.probate_matter,
            calculate_invoice_total_with_vat,
        )
        self.assertEqual(len(data['assets']), 1)
        self.assertEqual(len(data['debts']), 1)
        self.assertEqual(data['totals']['gross_estate'], '100.00')
        self.assertEqual(data['totals']['total_debts_paid'], '50.00')
        self.assertEqual(data['totals']['net_estate'], '50.00')

    def test_finance_override_excludes_line_from_totals(self):
        estate_account = get_or_create_estate_account(self.probate_matter, self.user)
        slip = PmtsSlips.objects.create(
            file_number=self.probate_matter,
            ledger_account='C',
            mode_of_pmt='BT',
            amount=Decimal('200.00'),
            is_money_out=False,
            pmt_person='Barclays',
            description='Account balance',
            date=date(2023, 3, 29),
            balance_left=Decimal('200.00'),
            created_by=self.user,
        )
        EstateAccountFinanceLineOverride.objects.create(
            estate_account=estate_account,
            source_type=EstateAccountFinanceLineOverride.SOURCE_SLIP,
            source_id=slip.id,
            is_excluded=True,
        )
        data = get_estate_account_data(
            estate_account,
            self.probate_matter,
            calculate_invoice_total_with_vat,
        )
        self.assertEqual(len(data['assets']), 1)
        self.assertTrue(data['assets'][0]['is_excluded'])
        self.assertEqual(data['totals']['gross_estate'], '0.00')

    def test_finalise_snapshots_and_blocks_line_update(self):
        estate_account = get_or_create_estate_account(self.probate_matter, self.user)
        entry = EstateAccountManualEntry.objects.create(
            estate_account=estate_account,
            section=EstateAccountManualEntry.SECTION_ASSET,
            date=date(2023, 1, 1),
            description='Pending asset',
            amount=Decimal('10.00'),
            created_by=self.user,
        )
        response = self.client.post(
            reverse('estate_account_status', args=['PRB0001']),
            data='{"action":"finalise"}',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        estate_account.refresh_from_db()
        self.assertEqual(estate_account.status, EstateAccount.STATUS_FINALISED)
        self.assertIsNotNone(estate_account.finance_snapshot)

        response = self.client.post(
            reverse('estate_account_line_update', args=['PRB0001']),
            data=(
                '{"line_kind":"manual","id":%s,"description":"Changed"}' % entry.id
            ),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 403)

    def test_download_returns_pdf(self):
        response = self.client.get(reverse('download_estate_account', args=['PRB0001']))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))

    def test_legacy_finances_url_redirects_to_download(self):
        response = self.client.get(
            reverse('download_estate_account_legacy', args=['PRB0001'])
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn('/estate_account/download/', response.url)
