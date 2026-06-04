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
