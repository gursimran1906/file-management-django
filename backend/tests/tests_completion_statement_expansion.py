from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from users.models import CustomUser
from backend.completion_statement import get_completion_statement_data, get_or_create_completion_statement
from backend.completion_statement import sync_all
from backend.estate_account import calculate_invoice_total_with_vat
from backend.models import (
    CompletionStatement,
    CompletionStatementManualEntry,
    CompletionStatementMortgageRedemption,
    CompletionStatementScheduledPayment,
    MatterType,
    WIP,
    ClientContactDetails,
)
from backend.pmt_slip_service import create_pmt_slip


def make_matter(file_number):
    client = ClientContactDetails.objects.create(
        name='Test Client', occupation='X', address_line1='1 St',
        address_line2='', county='Essex', postcode='SS1 1AA',
        email='t@t.com', contact_number='0123456789',
    )
    mt = MatterType.objects.create(type='Residential Conveyancing')
    return WIP.objects.create(
        file_number=file_number, client1=client,
        matter_description='Test property', matter_type=mt, funding='Pvt',
    )


class CompletionStatementExpansionTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='expuser', email='exp@example.com',
            first_name='Exp', last_name='User', password='password',
            max_holidays_in_year=20,
        )
        self.client.force_login(self.user)
        self.matter = make_matter('CV-EXP01')

    def test_mortgage_sync_creates_manual_and_schedule(self):
        cs = get_or_create_completion_statement(self.matter, self.user)
        cs.completion_monies = Decimal('320000')
        cs.save()
        CompletionStatementMortgageRedemption.objects.create(
            completion_statement=cs,
            redemption_figure=Decimal('185000'),
            redemption_statement_date=date(2024, 6, 1),
            daily_interest_amount=Decimal('10'),
            completion_date=date(2024, 6, 11),
        )
        sync_all(cs, self.matter, self.user, calculate_invoice_total_with_vat)
        cs.refresh_from_db()
        self.assertTrue(cs.manual_entries.filter(description='Mortgage redemption').exists())
        self.assertTrue(cs.scheduled_payments.filter(source_kind='mortgage').exists())

    def test_schedule_create_slip(self):
        cs = get_or_create_completion_statement(self.matter, self.user)
        row = CompletionStatementScheduledPayment.objects.create(
            completion_statement=cs,
            payee_name='Client',
            description='Test payment',
            direction='less',
            ledger_account='C',
            projected_amount=Decimal('500.00'),
            payment_date=date(2024, 6, 28),
            source_kind='manual',
            source_id=1,
        )
        row.source_id = row.id
        row.save()
        url = reverse('completion_statement_schedule_create_slip', args=['CV-EXP01', row.id])
        response = self.client.post(url, data='{}', content_type='application/json')
        self.assertEqual(response.status_code, 200)
        row.refresh_from_db()
        self.assertIsNotNone(row.linked_slip_id)
        self.assertEqual(row.status, CompletionStatementScheduledPayment.STATUS_SLIP_CREATED)

    def test_pending_main_line_creates_schedule_row(self):
        cs = get_or_create_completion_statement(self.matter, self.user)
        entry = CompletionStatementManualEntry.objects.create(
            completion_statement=cs, direction='less',
            description='Pay estate agent', amount=Decimal('1200.00'),
            is_pending=True, sort_order=2, created_by=self.user,
        )
        sync_all(cs, self.matter, self.user, calculate_invoice_total_with_vat)
        row = cs.scheduled_payments.get(source_kind='main_line', source_id=entry.id)
        self.assertEqual(row.projected_amount, Decimal('1200.00'))
        self.assertEqual(row.direction, 'less')
        self.assertEqual(row.payee_name, 'Pay estate agent')

    def test_main_line_edits_preserved_on_resync(self):
        cs = get_or_create_completion_statement(self.matter, self.user)
        entry = CompletionStatementManualEntry.objects.create(
            completion_statement=cs, direction='less',
            description='Pay estate agent', amount=Decimal('1200.00'),
            is_pending=True, created_by=self.user,
        )
        sync_all(cs, self.matter, self.user, calculate_invoice_total_with_vat)
        row = cs.scheduled_payments.get(source_kind='main_line', source_id=entry.id)
        # Caseworker fills in the real payee and bank details.
        row.payee_name = 'ACME Estate Agents Ltd'
        row.bank_sort_code = '20-00-00'
        row.bank_account_number = '12345678'
        row.save()
        # The main-statement amount later changes; re-sync.
        entry.amount = Decimal('1500.00')
        entry.save()
        sync_all(cs, self.matter, self.user, calculate_invoice_total_with_vat)
        row.refresh_from_db()
        self.assertEqual(row.projected_amount, Decimal('1500.00'))  # fact refreshed
        self.assertEqual(row.payee_name, 'ACME Estate Agents Ltd')  # edit preserved
        self.assertEqual(row.bank_account_number, '12345678')       # edit preserved

    def test_unflagging_pending_removes_main_line_row(self):
        cs = get_or_create_completion_statement(self.matter, self.user)
        entry = CompletionStatementManualEntry.objects.create(
            completion_statement=cs, direction='less',
            description='Pay estate agent', amount=Decimal('1200.00'),
            is_pending=True, created_by=self.user,
        )
        sync_all(cs, self.matter, self.user, calculate_invoice_total_with_vat)
        self.assertTrue(
            cs.scheduled_payments.filter(source_kind='main_line').exists()
        )
        entry.is_pending = False
        entry.save()
        sync_all(cs, self.matter, self.user, calculate_invoice_total_with_vat)
        self.assertFalse(
            cs.scheduled_payments.filter(source_kind='main_line').exists()
        )

    def test_main_line_row_with_slip_survives_unflag(self):
        cs = get_or_create_completion_statement(self.matter, self.user)
        entry = CompletionStatementManualEntry.objects.create(
            completion_statement=cs, direction='less',
            description='Pay estate agent', amount=Decimal('1200.00'),
            is_pending=True, created_by=self.user,
        )
        sync_all(cs, self.matter, self.user, calculate_invoice_total_with_vat)
        row = cs.scheduled_payments.get(source_kind='main_line', source_id=entry.id)
        url = reverse('completion_statement_schedule_create_slip', args=['CV-EXP01', row.id])
        self.client.post(url, data='{}', content_type='application/json')
        entry.is_pending = False
        entry.save()
        sync_all(cs, self.matter, self.user, calculate_invoice_total_with_vat)
        row.refresh_from_db()
        self.assertEqual(row.status, CompletionStatementScheduledPayment.STATUS_SLIP_CREATED)

    def test_slip_from_main_line_not_double_counted(self):
        cs = get_or_create_completion_statement(self.matter, self.user)
        cs.transaction_type = 'sale'
        cs.completion_monies = Decimal('5000.00')
        cs.save()
        entry = CompletionStatementManualEntry.objects.create(
            completion_statement=cs, direction='less',
            description='Pay agent', amount=Decimal('5000.00'),
            is_pending=True, created_by=self.user,
        )
        sync_all(cs, self.matter, self.user, calculate_invoice_total_with_vat)
        row = cs.scheduled_payments.get(source_kind='main_line', source_id=entry.id)
        before = get_completion_statement_data(
            cs, self.matter, calculate_invoice_total_with_vat
        )
        self.assertTrue(before['totals']['is_balanced'])

        url = reverse('completion_statement_schedule_create_slip', args=['CV-EXP01', row.id])
        resp = self.client.post(url, data='{}', content_type='application/json')
        self.assertEqual(resp.status_code, 200)

        after = get_completion_statement_data(
            cs, self.matter, calculate_invoice_total_with_vat
        )
        # No double count: the pending line is removed and the slip stands in its
        # place, so the statement stays balanced.
        self.assertTrue(after['totals']['is_balanced'])
        slip_lines = [l for l in after['lines'] if l.get('source_type') == 'slip']
        self.assertTrue(slip_lines)
        self.assertFalse(any(l['is_excluded'] for l in slip_lines))
        # The originating pending line has been removed.
        self.assertFalse(
            CompletionStatementManualEntry.objects.filter(id=entry.id).exists()
        )

    def test_bank_reference_folded_onto_slip(self):
        cs = get_or_create_completion_statement(self.matter, self.user)
        row = CompletionStatementScheduledPayment.objects.create(
            completion_statement=cs,
            payee_name='Lender',
            description='Mortgage redemption',
            direction='less',
            ledger_account='C',
            projected_amount=Decimal('500.00'),
            payment_date=date(2024, 6, 28),
            source_kind='manual',
            source_id=1,
            bank_reference='ABC123/REDEMPTION',
        )
        row.source_id = row.id
        row.save()
        url = reverse('completion_statement_schedule_create_slip', args=['CV-EXP01', row.id])
        self.client.post(url, data='{}', content_type='application/json')
        row.refresh_from_db()
        self.assertIn('ABC123/REDEMPTION', row.linked_slip.description)

    def test_payee_editable_and_update_persists(self):
        cs = get_or_create_completion_statement(self.matter, self.user)
        entry = CompletionStatementManualEntry.objects.create(
            completion_statement=cs, direction='less',
            description='Pay agent', amount=Decimal('100.00'),
            is_pending=True, created_by=self.user,
        )
        sync_all(cs, self.matter, self.user, calculate_invoice_total_with_vat)
        row = cs.scheduled_payments.get(source_kind='main_line', source_id=entry.id)
        self.client.post(
            reverse('completion_statement_schedule_update', args=['CV-EXP01']),
            data=('{"id": %d, "payee_name": "ACME Ltd", "description": "Final fee"}' % row.id),
            content_type='application/json',
        )
        row.refresh_from_db()
        self.assertEqual(row.payee_name, 'ACME Ltd')
        self.assertEqual(row.description, 'Final fee')
        # Payee/description survive a re-sync for main-line rows.
        sync_all(cs, self.matter, self.user, calculate_invoice_total_with_vat)
        row.refresh_from_db()
        self.assertEqual(row.payee_name, 'ACME Ltd')
        # Serializer marks main-line rows payee-editable but not amount-editable.
        data = get_completion_statement_data(
            cs, self.matter, calculate_invoice_total_with_vat
        )
        srow = next(r for r in data['schedule'] if r['id'] == row.id)
        self.assertTrue(srow['payee_editable'])
        self.assertFalse(srow['amount_editable'])

    def test_manual_schedule_row_fully_editable(self):
        cs = get_or_create_completion_statement(self.matter, self.user)
        row = CompletionStatementScheduledPayment.objects.create(
            completion_statement=cs, payee_name='X', direction='less',
            ledger_account='C', projected_amount=Decimal('5.00'),
            source_kind='manual', source_id=1,
        )
        row.source_id = row.id
        row.save()
        data = get_completion_statement_data(
            cs, self.matter, calculate_invoice_total_with_vat
        )
        srow = next(r for r in data['schedule'] if r['id'] == row.id)
        self.assertTrue(srow['payee_editable'])
        self.assertTrue(srow['amount_editable'])

    def test_schedule_update_saves_bank_fields(self):
        cs = get_or_create_completion_statement(self.matter, self.user)
        row = CompletionStatementScheduledPayment.objects.create(
            completion_statement=cs, payee_name='Payee', direction='less',
            ledger_account='C', projected_amount=Decimal('10.00'),
            source_kind='manual', source_id=1,
        )
        row.source_id = row.id
        row.save()
        self.client.post(
            reverse('completion_statement_schedule_update', args=['CV-EXP01']),
            data=('{"id": %d, "bank_sort_code": "30-00-00", '
                  '"bank_account_number": "87654321"}' % row.id),
            content_type='application/json',
        )
        row.refresh_from_db()
        self.assertEqual(row.bank_sort_code, '30-00-00')
        self.assertEqual(row.bank_account_number, '87654321')

    def test_finalise_blocked_with_pending_schedule(self):
        cs = get_or_create_completion_statement(self.matter, self.user)
        cs.completion_monies = Decimal('100000')
        cs.save()
        CompletionStatementManualEntry.objects.create(
            completion_statement=cs, direction='less',
            description='Mortgage redemption', amount=Decimal('100000'),
            sort_order=1, created_by=self.user,
        )
        CompletionStatementScheduledPayment.objects.create(
            completion_statement=cs,
            payee_name='Lender',
            direction='less',
            ledger_account='C',
            projected_amount=Decimal('100000'),
            source_kind='manual',
            source_id=99,
        )
        response = self.client.post(
            reverse('completion_statement_status', args=['CV-EXP01']),
            data='{"action":"finalise"}',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)
