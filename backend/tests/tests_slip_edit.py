from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from users.models import CustomUser
from ..utils import (
    green_slip_has_usage,
    pmt_slip_has_partial_invoice_usage,
    validate_green_slip_amount_change,
    validate_green_slip_file_change,
    validate_pmt_slip_amount_change,
)
from ..models import LedgerAccountTransfers, MatterType, Modifications, PmtsSlips, WIP
from ..models import ClientContactDetails


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


class SlipEditValidationTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='slipuser',
            email='slip@example.com',
            first_name='Slip',
            last_name='User',
            password='password',
            max_holidays_in_year=20,
        )
        self.matter = make_matter()
        self.other_matter = make_matter('PRB0002')

    def _make_blue_slip(self, **kwargs):
        defaults = {
            'file_number': self.matter,
            'ledger_account': 'C',
            'mode_of_pmt': 'BT',
            'amount': Decimal('1000.00'),
            'is_money_out': False,
            'pmt_person': 'Client',
            'description': 'Payment in',
            'date': date(2024, 1, 1),
            'balance_left': Decimal('600.00'),
            'amount_invoiced': {
                '1': {'amt_invoiced': '400.00', 'balance_left': '600.00'}
            },
            'created_by': self.user,
        }
        defaults.update(kwargs)
        return PmtsSlips.objects.create(**defaults)

    def test_partial_blue_slip_blocks_amount_change(self):
        slip = self._make_blue_slip()
        self.assertTrue(pmt_slip_has_partial_invoice_usage(slip))

        balance, error = validate_pmt_slip_amount_change(slip, Decimal('1100.00'))
        self.assertIsNone(balance)
        self.assertIn('partially used', error)

    def test_unused_slip_allows_amount_change(self):
        slip = PmtsSlips.objects.create(
            file_number=self.matter,
            ledger_account='C',
            mode_of_pmt='BT',
            amount=Decimal('500.00'),
            is_money_out=False,
            pmt_person='Client',
            description='Payment in',
            date=date(2024, 1, 1),
            balance_left=Decimal('500.00'),
            created_by=self.user,
        )
        balance, error = validate_pmt_slip_amount_change(slip, Decimal('750.00'))
        self.assertIsNone(error)
        self.assertEqual(balance, Decimal('750.00'))

    def test_cash_allocated_slip_recalculates_balance(self):
        slip = PmtsSlips.objects.create(
            file_number=self.matter,
            ledger_account='C',
            mode_of_pmt='BT',
            amount=Decimal('500.00'),
            is_money_out=False,
            pmt_person='Client',
            description='Payment in',
            date=date(2024, 1, 1),
            balance_left=Decimal('300.00'),
            amount_allocated={'10': '200.00'},
            created_by=self.user,
        )
        balance, error = validate_pmt_slip_amount_change(slip, Decimal('600.00'))
        self.assertIsNone(error)
        self.assertEqual(balance, Decimal('400.00'))

        balance, error = validate_pmt_slip_amount_change(slip, Decimal('150.00'))
        self.assertIsNone(balance)
        self.assertIn('200.00', error)

    def test_fully_invoiced_slip_on_final_invoice_blocks_amount_change(self):
        from ..models import Invoices
        invoice = Invoices.objects.create(
            file_number=self.matter,
            invoice_number=1001,
            state='F',
            date=date(2024, 1, 1),
            description='Costs',
            our_costs=['500.00'],
            vat=Decimal('0.00'),
            created_by=self.user,
        )
        slip = PmtsSlips.objects.create(
            file_number=self.matter,
            ledger_account='C',
            mode_of_pmt='BT',
            amount=Decimal('500.00'),
            is_money_out=True,
            pmt_person='Supplier',
            description='Disbursement',
            date=date(2024, 1, 1),
            balance_left=Decimal('0.00'),
            amount_invoiced='500.00',
            created_by=self.user,
        )
        invoice.disbs_ids.add(slip)

        balance, error = validate_pmt_slip_amount_change(slip, Decimal('600.00'))
        self.assertIsNone(balance)
        self.assertIn('final invoice', error)

    def test_cash_allocated_to_final_invoice_allows_amount_increase(self):
        from ..models import Invoices
        invoice = Invoices.objects.create(
            file_number=self.matter,
            invoice_number=1002,
            state='F',
            date=date(2024, 1, 1),
            description='Costs',
            our_costs=['500.00'],
            vat=Decimal('0.00'),
            created_by=self.user,
        )
        slip = PmtsSlips.objects.create(
            file_number=self.matter,
            ledger_account='C',
            mode_of_pmt='BT',
            amount=Decimal('500.00'),
            is_money_out=False,
            pmt_person='Client',
            description='Payment in',
            date=date(2024, 1, 1),
            balance_left=Decimal('300.00'),
            amount_allocated={str(invoice.id): '200.00'},
            created_by=self.user,
        )

        balance, error = validate_pmt_slip_amount_change(slip, Decimal('600.00'))
        self.assertIsNone(error)
        self.assertEqual(balance, Decimal('400.00'))

    def test_fully_invoiced_slip_allows_increase_on_draft_invoice(self):
        from ..models import Invoices
        invoice = Invoices.objects.create(
            file_number=self.matter,
            invoice_number=None,
            state='D',
            date=date(2024, 1, 1),
            description='Draft costs',
            our_costs=['500.00'],
            vat=Decimal('0.00'),
            created_by=self.user,
        )
        slip = PmtsSlips.objects.create(
            file_number=self.matter,
            ledger_account='C',
            mode_of_pmt='BT',
            amount=Decimal('500.00'),
            is_money_out=True,
            pmt_person='Supplier',
            description='Disbursement',
            date=date(2024, 1, 1),
            balance_left=Decimal('0.00'),
            amount_invoiced='500.00',
            created_by=self.user,
        )
        invoice.disbs_ids.add(slip)

        balance, error = validate_pmt_slip_amount_change(slip, Decimal('600.00'))
        self.assertIsNone(error)
        self.assertEqual(balance, Decimal('100.00'))

        balance, error = validate_pmt_slip_amount_change(slip, Decimal('400.00'))
        self.assertIsNone(balance)
        self.assertIn('500.00', error)

    def test_green_slip_with_usage_blocks_amount_change(self):
        slip = LedgerAccountTransfers.objects.create(
            file_number_from=self.matter,
            file_number_to=self.other_matter,
            from_ledger_account='C',
            to_ledger_account='C',
            amount=Decimal('300.00'),
            date=date(2024, 1, 1),
            description='Transfer',
            balance_left_from=Decimal('300.00'),
            balance_left_to=Decimal('100.00'),
            amount_invoiced_to={
                '5': {'amt_invoiced': '200.00', 'balance_left': '100.00'}
            },
            created_by=self.user,
        )
        self.assertTrue(green_slip_has_usage(slip))
        balances, error = validate_green_slip_amount_change(slip, Decimal('400.00'))
        self.assertIsNone(balances)
        self.assertIn('linked to', error)

    def test_green_slip_blocks_file_change_when_used(self):
        slip = LedgerAccountTransfers.objects.create(
            file_number_from=self.matter,
            file_number_to=self.other_matter,
            from_ledger_account='C',
            to_ledger_account='C',
            amount=Decimal('300.00'),
            date=date(2024, 1, 1),
            description='Transfer',
            balance_left_from=Decimal('300.00'),
            balance_left_to=Decimal('100.00'),
            amount_invoiced_to={
                '5': {'amt_invoiced': '200.00', 'balance_left': '100.00'}
            },
            created_by=self.user,
        )
        error = validate_green_slip_file_change(
            slip, self.other_matter.pk, self.matter.pk)
        self.assertIn('cannot be changed', error)


class SlipEditViewTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='slipview',
            email='slipview@example.com',
            first_name='Slip',
            last_name='Viewer',
            password='password',
            max_holidays_in_year=20,
        )
        self.client.force_login(self.user)
        self.matter = make_matter()

    def test_edit_unused_slip_logs_modification_with_balance(self):
        slip = PmtsSlips.objects.create(
            file_number=self.matter,
            ledger_account='C',
            mode_of_pmt='BT',
            amount=Decimal('500.00'),
            is_money_out=False,
            pmt_person='Client',
            description='Payment in',
            date=date(2024, 1, 1),
            balance_left=Decimal('500.00'),
            created_by=self.user,
        )
        response = self.client.post(
            reverse('edit_pmts_slip', args=[slip.id]),
            {
                'date': '2024-01-01',
                'ledger_account': 'C',
                'mode_of_pmt': 'BT',
                'amount': '750.00',
                'pmt_person': 'Client',
                'description': 'Payment in',
                'is_money_out': False,
            },
        )
        self.assertEqual(response.status_code, 302)
        slip.refresh_from_db()
        self.assertEqual(slip.amount, Decimal('750.00'))
        self.assertEqual(slip.balance_left, Decimal('750.00'))

        modification = Modifications.objects.filter(object_id=slip.id).latest('id')
        self.assertIn('amount', modification.changes)
        self.assertIn('balance_left', modification.changes)
        self.assertEqual(
            modification.changes['reason']['new_value'],
            'Edited payment slip',
        )

    def test_edit_partial_blue_slip_allows_description_only(self):
        slip = PmtsSlips.objects.create(
            file_number=self.matter,
            ledger_account='C',
            mode_of_pmt='BT',
            amount=Decimal('1000.00'),
            is_money_out=False,
            pmt_person='Client',
            description='Payment in',
            date=date(2024, 1, 1),
            balance_left=Decimal('600.00'),
            amount_invoiced={
                '1': {'amt_invoiced': '400.00', 'balance_left': '600.00'}
            },
            created_by=self.user,
        )
        response = self.client.post(
            reverse('edit_pmts_slip', args=[slip.id]),
            {
                'date': '2024-01-01',
                'ledger_account': 'C',
                'mode_of_pmt': 'BT',
                'amount': '1000.00',
                'pmt_person': 'Client',
                'description': 'Updated description',
                'is_money_out': False,
            },
        )
        self.assertEqual(response.status_code, 302)
        slip.refresh_from_db()
        self.assertEqual(slip.description, 'Updated description')
        self.assertEqual(slip.amount, Decimal('1000.00'))

    def test_edit_partial_blue_slip_rejects_amount_change(self):
        slip = PmtsSlips.objects.create(
            file_number=self.matter,
            ledger_account='C',
            mode_of_pmt='BT',
            amount=Decimal('1000.00'),
            is_money_out=False,
            pmt_person='Client',
            description='Payment in',
            date=date(2024, 1, 1),
            balance_left=Decimal('600.00'),
            amount_invoiced={
                '1': {'amt_invoiced': '400.00', 'balance_left': '600.00'}
            },
            created_by=self.user,
        )
        response = self.client.post(
            reverse('edit_pmts_slip', args=[slip.id]),
            {
                'date': '2024-01-01',
                'ledger_account': 'C',
                'mode_of_pmt': 'BT',
                'amount': '1100.00',
                'pmt_person': 'Client',
                'description': 'Updated description',
                'is_money_out': False,
            },
        )
        self.assertEqual(response.status_code, 200)
        slip.refresh_from_db()
        self.assertEqual(slip.amount, Decimal('1000.00'))
        self.assertEqual(slip.description, 'Payment in')

    def test_edit_slip_no_changes_skips_modification(self):
        slip = PmtsSlips.objects.create(
            file_number=self.matter,
            ledger_account='C',
            mode_of_pmt='BT',
            amount=Decimal('500.00'),
            is_money_out=False,
            pmt_person='Client',
            description='Payment in',
            date=date(2024, 1, 1),
            balance_left=Decimal('500.00'),
            created_by=self.user,
        )
        before_count = Modifications.objects.filter(object_id=slip.id).count()
        response = self.client.post(
            reverse('edit_pmts_slip', args=[slip.id]),
            {
                'date': '2024-01-01',
                'ledger_account': 'C',
                'mode_of_pmt': 'BT',
                'amount': '500.00',
                'pmt_person': 'Client',
                'description': 'Payment in',
                'is_money_out': False,
            },
        )
        self.assertEqual(response.status_code, 302)
        after_count = Modifications.objects.filter(object_id=slip.id).count()
        self.assertEqual(before_count, after_count)
