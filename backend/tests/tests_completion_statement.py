
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from users.models import CustomUser
from ..completion_statement import (
    get_completion_statement_data,
    get_or_create_completion_statement,
    matter_is_conveyancing,
)
from ..estate_account import calculate_invoice_total_with_vat
from ..models import (
    ClientContactDetails,
    CompletionStatement,
    CompletionStatementFinanceLineOverride,
    CompletionStatementManualEntry,
    CreditNote,
    Invoices,
    MatterType,
    PmtsSlips,
    WIP,
)


def make_client(name='Jane Seller'):
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


def make_matter(file_number, matter_type_name='Residential Conveyancing', client_name='Jane Seller'):
    client = make_client(client_name)
    matter_type = MatterType.objects.create(type=matter_type_name)
    return WIP.objects.create(
        file_number=file_number,
        client1=client,
        matter_description='10 Example Road, Benfleet',
        matter_type=matter_type,
        funding='Pvt',
    )


class CompletionStatementTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='convuser',
            email='conv@example.com',
            first_name='Conv',
            last_name='User',
            password='password',
            max_holidays_in_year=20,
        )
        self.client.force_login(self.user)
        self.conv_matter = make_matter('CV0001')
        self.probate_matter = make_matter('PRB0001', matter_type_name='Probate', client_name='John Deceased')

    def test_matter_is_conveyancing(self):
        self.assertTrue(matter_is_conveyancing(self.conv_matter))
        self.assertFalse(matter_is_conveyancing(self.probate_matter))

    def test_non_conveyancing_matter_returns_404(self):
        response = self.client.get(reverse('completion_statement_view', args=['PRB0001']))
        self.assertEqual(response.status_code, 404)

        response = self.client.get(reverse('download_completion_statement', args=['PRB0001']))
        self.assertEqual(response.status_code, 404)

    def test_conveyancing_page_loads(self):
        response = self.client.get(reverse('completion_statement_view', args=['CV0001']))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Completion statement')
        self.assertContains(response, 'Jane Seller')
        self.assertContains(response, 'Completion monies')

    def test_creates_default_template_lines(self):
        statement = get_or_create_completion_statement(self.conv_matter, self.user)
        self.assertEqual(statement.manual_entries.count(), 4)
        descriptions = list(
            statement.manual_entries.values_list('description', flat=True)
        )
        self.assertIn('Mortgage redemption', descriptions)

    def test_sale_completion_monies_defaults_to_add(self):
        statement = get_or_create_completion_statement(self.conv_matter, self.user)
        statement.completion_monies = Decimal('300000.00')
        statement.save()
        data = get_completion_statement_data(
            statement, self.conv_matter, calculate_invoice_total_with_vat
        )
        self.assertEqual(data['completion_monies_line']['direction'], 'add')
        self.assertEqual(data['completion_monies_line']['amount'], '300000.00')

    def test_purchase_completion_monies_defaults_to_less(self):
        statement = get_or_create_completion_statement(self.conv_matter, self.user)
        statement.transaction_type = CompletionStatement.TRANSACTION_PURCHASE
        statement.completion_monies = Decimal('250000.00')
        statement.save()
        data = get_completion_statement_data(
            statement, self.conv_matter, calculate_invoice_total_with_vat
        )
        self.assertEqual(data['completion_monies_line']['direction'], 'less')

    def test_manual_lines_update_balance(self):
        statement = get_or_create_completion_statement(self.conv_matter, self.user)
        statement.completion_monies = Decimal('300000.00')
        statement.save()
        statement.manual_entries.all().delete()
        CompletionStatementManualEntry.objects.create(
            completion_statement=statement,
            direction='less',
            description='Mortgage redemption',
            amount=Decimal('150000.00'),
            sort_order=1,
            created_by=self.user,
        )
        CompletionStatementManualEntry.objects.create(
            completion_statement=statement,
            direction='less',
            description='Estate agent',
            amount=Decimal('150000.00'),
            sort_order=2,
            created_by=self.user,
        )
        data = get_completion_statement_data(
            statement, self.conv_matter, calculate_invoice_total_with_vat
        )
        self.assertEqual(data['totals']['balance'], '0.00')
        self.assertTrue(data['totals']['is_balanced'])

    def test_finance_invoice_pull_through(self):
        statement = get_or_create_completion_statement(self.conv_matter, self.user)
        statement.completion_monies = Decimal('100000.00')
        statement.save()
        statement.manual_entries.all().delete()
        Invoices.objects.create(
            file_number=self.conv_matter,
            invoice_number=2001,
            state='F',
            date=date(2024, 6, 1),
            description='Conveyancing costs',
            our_costs=[1500.00],
            vat=Decimal('300.00'),
            created_by=self.user,
        )
        data = get_completion_statement_data(
            statement, self.conv_matter, calculate_invoice_total_with_vat
        )
        finance_lines = [line for line in data['lines'] if line['from_finances']]
        self.assertEqual(len(finance_lines), 1)
        self.assertEqual(finance_lines[0]['direction'], 'less')
        self.assertEqual(finance_lines[0]['amount'], '1800.00')

    def test_finance_override_excludes_line(self):
        statement = get_or_create_completion_statement(self.conv_matter, self.user)
        slip = PmtsSlips.objects.create(
            file_number=self.conv_matter,
            ledger_account='C',
            mode_of_pmt='BT',
            amount=Decimal('500.00'),
            is_money_out=False,
            pmt_person='Client',
            description='On account',
            date=date(2024, 5, 1),
            balance_left=Decimal('500.00'),
            created_by=self.user,
        )
        CompletionStatementFinanceLineOverride.objects.create(
            completion_statement=statement,
            source_type=CompletionStatementFinanceLineOverride.SOURCE_SLIP,
            source_id=slip.id,
            is_excluded=True,
        )
        data = get_completion_statement_data(
            statement, self.conv_matter, calculate_invoice_total_with_vat
        )
        finance_lines = [line for line in data['lines'] if line['from_finances']]
        self.assertEqual(len(finance_lines), 1)
        self.assertTrue(finance_lines[0]['is_excluded'])

    def test_finalise_blocked_when_not_balanced(self):
        statement = get_or_create_completion_statement(self.conv_matter, self.user)
        statement.completion_monies = Decimal('100000.00')
        statement.save()
        response = self.client.post(
            reverse('completion_statement_status', args=['CV0001']),
            data='{"action":"finalise"}',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('not balanced', response.json()['error'].lower())

    def test_finalise_succeeds_when_balanced(self):
        statement = get_or_create_completion_statement(self.conv_matter, self.user)
        statement.completion_monies = Decimal('100000.00')
        statement.save()
        statement.manual_entries.all().delete()
        CompletionStatementManualEntry.objects.create(
            completion_statement=statement,
            direction='less',
            description='Mortgage redemption',
            amount=Decimal('100000.00'),
            sort_order=1,
            created_by=self.user,
        )
        response = self.client.post(
            reverse('completion_statement_status', args=['CV0001']),
            data='{"action":"finalise"}',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        statement.refresh_from_db()
        self.assertEqual(statement.status, CompletionStatement.STATUS_FINALISED)
        self.assertIsNotNone(statement.finance_snapshot)

    def test_finalised_blocks_line_update(self):
        statement = get_or_create_completion_statement(self.conv_matter, self.user)
        statement.completion_monies = Decimal('100000.00')
        statement.save()
        statement.manual_entries.all().delete()
        entry = CompletionStatementManualEntry.objects.create(
            completion_statement=statement,
            direction='less',
            description='Mortgage redemption',
            amount=Decimal('100000.00'),
            sort_order=1,
            created_by=self.user,
        )
        self.client.post(
            reverse('completion_statement_status', args=['CV0001']),
            data='{"action":"finalise"}',
            content_type='application/json',
        )
        response = self.client.post(
            reverse('completion_statement_line_update', args=['CV0001']),
            data=(
                '{"line_kind":"manual","id":%s,"description":"Changed"}' % entry.id
            ),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 403)

    def test_credit_note_reduces_invoice_amount(self):
        statement = get_or_create_completion_statement(self.conv_matter, self.user)
        invoice = Invoices.objects.create(
            file_number=self.conv_matter,
            invoice_number=2002,
            state='F',
            date=date(2024, 6, 1),
            description='Conveyancing costs',
            our_costs=[1000.00],
            vat=Decimal('0.00'),
            created_by=self.user,
        )
        CreditNote.objects.create(
            invoice=invoice,
            file_number=self.conv_matter,
            date=date(2024, 6, 15),
            amount=Decimal('200.00'),
            reason='Adjustment',
            status='F',
            created_by=self.user,
        )
        data = get_completion_statement_data(
            statement, self.conv_matter, calculate_invoice_total_with_vat
        )
        finance_lines = [line for line in data['lines'] if line['from_finances']]
        self.assertEqual(len(finance_lines), 1)
        self.assertEqual(finance_lines[0]['amount'], '800.00')

    def test_download_returns_pdf(self):
        response = self.client.get(reverse('download_completion_statement', args=['CV0001']))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))
