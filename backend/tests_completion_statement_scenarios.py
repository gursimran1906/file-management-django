"""
Completion statement scenario tests — sale & purchase walkthroughs.

These tests document how a conveyancing completion statement is expected to
balance, what draft vs finalised behaviour looks like, and how common edge
cases are handled in the product.

Signed balance rule
-------------------
Every line contributes a signed amount: **add** lines are positive, **less**
lines are negative. Completion monies is the anchor:

  * **Sale** — completion monies is an **add** (funds received from buyer).
  * **Purchase** — completion monies is a **less** (funds sent to seller).

The statement is **balanced** when the signed sum of all active lines is
£0.00. Draft statements with a non-zero balance show a projected outcome:

  * Positive balance → "Amount due to you" (net payable to client).
  * Negative balance → "Amount required to complete" (shortfall from client).

Finalise is blocked until balance == 0. On finalise, a JSON snapshot is stored
so later finance changes do not alter the published statement.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from users.models import CustomUser
from .completion_statement import get_completion_statement_data, get_or_create_completion_statement
from .estate_account import calculate_invoice_total_with_vat
from .models import (
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


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

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


def make_matter(file_number, client_name='Jane Seller', description='10 Example Road, Benfleet'):
    client = make_client(client_name)
    matter_type = MatterType.objects.create(type='Residential Conveyancing')
    return WIP.objects.create(
        file_number=file_number,
        client1=client,
        matter_description=description,
        matter_type=matter_type,
        funding='Pvt',
    )


def statement_data(matter, user):
    statement = get_or_create_completion_statement(matter, user)
    return statement, get_completion_statement_data(
        statement, matter, calculate_invoice_total_with_vat
    )


def clear_template_lines(statement):
    """Remove zero-amount template placeholders so scenarios start clean."""
    statement.manual_entries.all().delete()


def add_manual(statement, user, *, direction, description, amount, sort_order=1):
    return CompletionStatementManualEntry.objects.create(
        completion_statement=statement,
        direction=direction,
        description=description,
        amount=Decimal(str(amount)),
        sort_order=sort_order,
        created_by=user,
    )


def add_final_invoice(matter, user, *, number, costs, vat=Decimal('0.00')):
    return Invoices.objects.create(
        file_number=matter,
        invoice_number=number,
        state='F',
        date=date(2024, 6, 1),
        description='Conveyancing costs',
        our_costs=costs,
        vat=vat,
        created_by=user,
    )


# ---------------------------------------------------------------------------
# Sale scenarios
# ---------------------------------------------------------------------------

class SaleCompletionStatementScenarios(TestCase):
    """
    Typical residential sale: buyer's completion monies arrive, deductions are
    made for mortgage, agent, legal fees, and the net balance is paid to the
    client.
    """

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='saleuser',
            email='sale@example.com',
            first_name='Sale',
            last_name='User',
            password='password',
            max_holidays_in_year=20,
        )
        self.matter = make_matter('CV-SALE01', client_name='Jane Seller')
        self.client.force_login(self.user)

    def test_balanced_sale_all_funds_accounted_for(self):
        """
        Sale at £320,000 — every pound is allocated; statement finalises.

        | Line                    | Direction | Amount    |
        |-------------------------|-----------|-----------|
        | Completion monies       | add       | 320,000   |
        | Mortgage redemption     | less      | 185,000   |
        | Estate agent commission | less      |   4,800   |
        | Legal fees (invoice)    | less      |   1,800   |
        | Net payment to client   | less      | 128,400   |
        | **Balance**             |           | **0**     |
        """
        statement = get_or_create_completion_statement(self.matter, self.user)
        clear_template_lines(statement)
        statement.completion_monies = Decimal('320000.00')
        statement.save()

        add_manual(statement, self.user, direction='less', description='Mortgage redemption', amount='185000', sort_order=1)
        add_manual(statement, self.user, direction='less', description='Estate agent commission', amount='4800', sort_order=2)
        add_final_invoice(
            self.matter, self.user, number=3001, costs=[1500.00], vat=Decimal('300.00')
        )
        add_manual(statement, self.user, direction='less', description='Net payment to client', amount='128400', sort_order=3)

        data = get_completion_statement_data(
            statement, self.matter, calculate_invoice_total_with_vat
        )

        self.assertEqual(data['completion_monies_line']['direction'], 'add')
        self.assertEqual(data['totals']['balance'], '0.00')
        self.assertTrue(data['totals']['is_balanced'])
        self.assertEqual(data['totals']['outcome_label'], 'Balanced at £0.00')
        # Running balance on the last active line matches the footer total.
        active_lines = [l for l in data['lines'] if not l['is_excluded']]
        self.assertEqual(active_lines[-1]['running_balance'], '0.00')

        response = self.client.post(
            reverse('completion_statement_status', args=['CV-SALE01']),
            data='{"action":"finalise"}',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)

    def test_draft_sale_shows_amount_due_to_client(self):
        """
        Same sale but client payment not yet entered — draft shows surplus.

        Without the "Net payment to client" line the signed balance is
        +£128,400. The UI labels this "Amount due to you" so the fee earner
        knows what still needs paying out before finalising.
        """
        statement = get_or_create_completion_statement(self.matter, self.user)
        clear_template_lines(statement)
        statement.completion_monies = Decimal('320000.00')
        statement.save()

        add_manual(statement, self.user, direction='less', description='Mortgage redemption', amount='185000', sort_order=1)
        add_manual(statement, self.user, direction='less', description='Estate agent commission', amount='4800', sort_order=2)
        add_final_invoice(
            self.matter, self.user, number=3002, costs=[1500.00], vat=Decimal('300.00')
        )

        data = get_completion_statement_data(
            statement, self.matter, calculate_invoice_total_with_vat
        )

        self.assertEqual(data['totals']['balance'], '128400.00')
        self.assertFalse(data['totals']['is_balanced'])
        self.assertIn('Amount due to you', data['totals']['outcome_label'])
        self.assertIn('128,400.00', data['totals']['outcome_label'])

        response = self.client.post(
            reverse('completion_statement_status', args=['CV-SALE01']),
            data='{"action":"finalise"}',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)

    def test_sale_blue_slip_deposit_increases_balance(self):
        """
        Client deposit received on account (blue slip) is an **add** on a sale.

        Edge case: deposit held in client account must appear on the statement
        so it is not forgotten when netting completion funds.
        """
        statement = get_or_create_completion_statement(self.matter, self.user)
        clear_template_lines(statement)
        statement.completion_monies = Decimal('320000.00')
        statement.save()

        PmtsSlips.objects.create(
            file_number=self.matter,
            ledger_account='C',
            mode_of_pmt='BT',
            amount=Decimal('5000.00'),
            is_money_out=False,
            pmt_person='Client',
            description='Deposit on account',
            date=date(2024, 4, 1),
            balance_left=Decimal('5000.00'),
            created_by=self.user,
        )
        add_manual(statement, self.user, direction='less', description='Mortgage redemption', amount='185000', sort_order=1)
        add_manual(statement, self.user, direction='less', description='Estate agent commission', amount='4800', sort_order=2)
        add_manual(statement, self.user, direction='less', description='Net payment to client', amount='135200', sort_order=3)

        data = get_completion_statement_data(
            statement, self.matter, calculate_invoice_total_with_vat
        )
        blue_slip = next(
            line for line in data['lines']
            if line['from_finances'] and line['source_label'] == 'Blue slip'
        )
        self.assertEqual(blue_slip['direction'], 'add')
        self.assertEqual(blue_slip['amount'], '5000.00')
        self.assertEqual(data['totals']['balance'], '0.00')

    def test_sale_pink_slip_payment_balances_statement(self):
        """
        After completion, net proceeds paid to client via pink slip (money out).

        The payment pulls through from finances as a **less** line — no manual
        "net to client" row needed once the slip is posted.
        """
        statement = get_or_create_completion_statement(self.matter, self.user)
        clear_template_lines(statement)
        statement.completion_monies = Decimal('320000.00')
        statement.save()

        add_manual(statement, self.user, direction='less', description='Mortgage redemption', amount='185000', sort_order=1)
        add_manual(statement, self.user, direction='less', description='Estate agent commission', amount='4800', sort_order=2)
        add_final_invoice(
            self.matter, self.user, number=3010, costs=[1500.00], vat=Decimal('300.00')
        )
        PmtsSlips.objects.create(
            file_number=self.matter,
            ledger_account='C',
            mode_of_pmt='BT',
            amount=Decimal('128400.00'),
            is_money_out=True,
            pmt_person='Client',
            description='Net payment to client',
            date=date(2024, 6, 28),
            balance_left=Decimal('0.00'),
            created_by=self.user,
        )

        data = get_completion_statement_data(
            statement, self.matter, calculate_invoice_total_with_vat
        )
        pink_slip = next(
            line for line in data['lines']
            if line['from_finances'] and line['source_label'] == 'Pink slip'
        )
        self.assertEqual(pink_slip['direction'], 'less')
        self.assertEqual(data['totals']['balance'], '0.00')
        self.assertTrue(data['totals']['is_balanced'])

    def test_sale_green_slip_transfer_balances_statement(self):
        """
        Net proceeds transferred inter-matter (green slip out) also balances sale.

        Transfer from this sale file to the client's purchase file appears as a
        **less** line on the sale completion statement.
        """
        from .models import LedgerAccountTransfers

        purchase_matter = make_matter('CV-PUR-XFER', client_name='Bob Buyer')
        statement = get_or_create_completion_statement(self.matter, self.user)
        clear_template_lines(statement)
        statement.completion_monies = Decimal('320000.00')
        statement.save()

        add_manual(statement, self.user, direction='less', description='Mortgage redemption', amount='185000', sort_order=1)
        add_manual(statement, self.user, direction='less', description='Estate agent commission', amount='4800', sort_order=2)
        add_final_invoice(
            self.matter, self.user, number=3011, costs=[1500.00], vat=Decimal('300.00')
        )
        LedgerAccountTransfers.objects.create(
            file_number_from=self.matter,
            file_number_to=purchase_matter,
            from_ledger_account='C',
            to_ledger_account='C',
            amount=Decimal('128400.00'),
            date=date(2024, 6, 28),
            description='Net proceeds to purchase file',
            amount_invoiced_from={},
            balance_left_from=Decimal('0.00'),
            amount_invoiced_to={},
            balance_left_to=Decimal('128400.00'),
            created_by=self.user,
        )

        data = get_completion_statement_data(
            statement, self.matter, calculate_invoice_total_with_vat
        )
        transfer_line = next(
            line for line in data['lines']
            if line['from_finances'] and line['source_label'] == 'Green slip'
        )
        self.assertEqual(transfer_line['direction'], 'less')
        self.assertEqual(data['totals']['balance'], '0.00')
        self.assertTrue(data['totals']['is_balanced'])


# ---------------------------------------------------------------------------
# Purchase scenarios
# ---------------------------------------------------------------------------

class PurchaseCompletionStatementScenarios(TestCase):
    """
    Typical residential purchase: completion monies leave to the seller;
    deposit and mortgage advance are **add** lines funding the purchase.
    """

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='purchaseuser',
            email='purchase@example.com',
            first_name='Purchase',
            last_name='User',
            password='password',
            max_holidays_in_year=20,
        )
        self.matter = make_matter('CV-PUR01', client_name='Bob Buyer')
        self.client.force_login(self.user)

    def test_balanced_purchase_deposit_plus_mortgage_equals_price(self):
        """
        Purchase at £350,000 funded by £35k deposit + £315k mortgage.

        | Line              | Direction | Amount   |
        |-------------------|-----------|----------|
        | Completion monies | less      | 350,000  |
        | Deposit paid      | add       |  35,000  |
        | Mortgage advance  | add       | 315,000  |
        | **Balance**       |           | **0**    |
        """
        statement = get_or_create_completion_statement(self.matter, self.user)
        clear_template_lines(statement)
        statement.transaction_type = CompletionStatement.TRANSACTION_PURCHASE
        statement.completion_monies = Decimal('350000.00')
        statement.save()

        add_manual(statement, self.user, direction='add', description='Deposit paid', amount='35000', sort_order=1)
        add_manual(statement, self.user, direction='add', description='Mortgage advance', amount='315000', sort_order=2)

        data = get_completion_statement_data(
            statement, self.matter, calculate_invoice_total_with_vat
        )

        self.assertEqual(data['completion_monies_line']['direction'], 'less')
        self.assertEqual(data['totals']['balance'], '0.00')
        self.assertTrue(data['totals']['is_balanced'])

    def test_draft_purchase_shows_shortfall(self):
        """
        Mortgage advance £5k short — client must bring additional funds.

        Negative signed balance → "Amount required to complete".
        """
        statement = get_or_create_completion_statement(self.matter, self.user)
        clear_template_lines(statement)
        statement.transaction_type = CompletionStatement.TRANSACTION_PURCHASE
        statement.completion_monies = Decimal('350000.00')
        statement.save()

        add_manual(statement, self.user, direction='add', description='Deposit paid', amount='35000', sort_order=1)
        add_manual(statement, self.user, direction='add', description='Mortgage advance', amount='310000', sort_order=2)

        data = get_completion_statement_data(
            statement, self.matter, calculate_invoice_total_with_vat
        )

        self.assertEqual(data['totals']['balance'], '-5000.00')
        self.assertIn('Amount required to complete', data['totals']['outcome_label'])
        self.assertIn('5,000.00', data['totals']['outcome_label'])

    def test_purchase_invoice_and_sdtl_are_add_lines(self):
        """
        On a purchase, legal fees and SDLT increase funds required from client.

        Final invoices default to **add** (costs the buyer must fund). Until those
        costs are paid out (less lines), the draft shows a surplus — fee earner
        adds disbursement rows when SDLT and fees leave the client account.
        """
        statement = get_or_create_completion_statement(self.matter, self.user)
        clear_template_lines(statement)
        statement.transaction_type = CompletionStatement.TRANSACTION_PURCHASE
        statement.completion_monies = Decimal('350000.00')
        statement.save()

        add_manual(statement, self.user, direction='add', description='Deposit paid', amount='35000', sort_order=1)
        add_manual(statement, self.user, direction='add', description='Mortgage advance', amount='315000', sort_order=2)
        add_manual(statement, self.user, direction='add', description='Stamp duty land tax (SDLT)', amount='5250', sort_order=3)
        add_final_invoice(
            self.matter, self.user, number=4001, costs=[1200.00], vat=Decimal('240.00')
        )

        draft = get_completion_statement_data(
            statement, self.matter, calculate_invoice_total_with_vat
        )
        invoice_line = next(
            line for line in draft['lines']
            if line['from_finances'] and line['source_label'] == 'Invoice'
        )
        self.assertEqual(invoice_line['direction'], 'add')
        self.assertEqual(invoice_line['amount'], '1440.00')
        # Price funded but SDLT + fees not yet disbursed → surplus until paid out.
        self.assertEqual(draft['totals']['balance'], '6690.00')
        self.assertIn('Amount due to you', draft['totals']['outcome_label'])

        add_manual(statement, self.user, direction='less', description='SDLT and legal fees paid', amount='6690', sort_order=4)
        balanced = get_completion_statement_data(
            statement, self.matter, calculate_invoice_total_with_vat
        )
        self.assertEqual(balanced['totals']['balance'], '0.00')


# ---------------------------------------------------------------------------
# Edge cases & mitigations
# ---------------------------------------------------------------------------

class CompletionStatementEdgeCases(TestCase):
    """
    Edge cases that commonly break real-world completion statements and how
    the application handles each one.
    """

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='edgeuser',
            email='edge@example.com',
            first_name='Edge',
            last_name='User',
            password='password',
            max_holidays_in_year=20,
        )
        self.matter = make_matter('CV-EDGE01')
        self.client.force_login(self.user)

    def test_zero_completion_monies_with_offsetting_lines(self):
        """
        Edge: remortgage / transfer at nil consideration — completion monies £0.

        Statement can still balance when manual lines net to zero. Completion
        monies line remains visible at £0 as the anchor.
        """
        statement = get_or_create_completion_statement(self.matter, self.user)
        clear_template_lines(statement)
        statement.completion_monies = Decimal('0.00')
        statement.save()

        add_manual(statement, self.user, direction='add', description='Mortgage advance', amount='100000', sort_order=1)
        add_manual(statement, self.user, direction='less', description='Mortgage redemption', amount='100000', sort_order=2)

        data = get_completion_statement_data(
            statement, self.matter, calculate_invoice_total_with_vat
        )
        self.assertEqual(data['completion_monies_line']['amount'], '0.00')
        self.assertEqual(data['totals']['balance'], '0.00')

    def test_template_placeholder_lines_at_zero_do_not_affect_balance(self):
        """
        Edge: default template lines are created at £0 on first open.

        Pending zero-amount placeholders must not skew totals. Fee earners fill
        them in or delete unused rows.
        """
        statement = get_or_create_completion_statement(self.matter, self.user)
        statement.completion_monies = Decimal('100000.00')
        statement.save()
        add_manual(statement, self.user, direction='less', description='Mortgage redemption', amount='100000', sort_order=99)

        data = get_completion_statement_data(
            statement, self.matter, calculate_invoice_total_with_vat
        )
        self.assertEqual(data['totals']['balance'], '0.00')

    def test_excluded_finance_line_removed_from_balance(self):
        """
        Edge: finance line pulled through twice (auto + manual duplicate).

        Solution: exclude the finance row via override; balance ignores it but
        the row stays visible (struck through) for audit.
        """
        statement = get_or_create_completion_statement(self.matter, self.user)
        clear_template_lines(statement)
        statement.completion_monies = Decimal('100000.00')
        statement.save()

        invoice = add_final_invoice(
            self.matter, self.user, number=5001, costs=[1000.00], vat=Decimal('0.00')
        )
        CompletionStatementFinanceLineOverride.objects.create(
            completion_statement=statement,
            source_type=CompletionStatementFinanceLineOverride.SOURCE_INVOICE,
            source_id=invoice.id,
            is_excluded=True,
        )
        add_manual(statement, self.user, direction='less', description='Legal fees (agreed)', amount='1000', sort_order=1)
        add_manual(statement, self.user, direction='less', description='Mortgage redemption', amount='99000', sort_order=2)

        data = get_completion_statement_data(
            statement, self.matter, calculate_invoice_total_with_vat
        )
        excluded = next(line for line in data['lines'] if line['from_finances'])
        self.assertTrue(excluded['is_excluded'])
        self.assertEqual(data['totals']['balance'], '0.00')

    def test_credit_note_reduces_invoice_before_balance(self):
        """
        Edge: invoice already on statement, credit note issued later.

        Net invoice amount (invoice total minus finalised credits) is used so
        the statement does not over-charge the client.
        """
        statement = get_or_create_completion_statement(self.matter, self.user)
        clear_template_lines(statement)
        statement.completion_monies = Decimal('100000.00')
        statement.save()

        invoice = add_final_invoice(
            self.matter, self.user, number=5002, costs=[1000.00], vat=Decimal('0.00')
        )
        CreditNote.objects.create(
            invoice=invoice,
            file_number=self.matter,
            date=date(2024, 6, 15),
            amount=Decimal('250.00'),
            reason='Fee reduction agreed',
            status='F',
            created_by=self.user,
        )
        add_manual(statement, self.user, direction='less', description='Mortgage redemption', amount='99250', sort_order=1)

        data = get_completion_statement_data(
            statement, self.matter, calculate_invoice_total_with_vat
        )
        invoice_line = next(
            line for line in data['lines']
            if line['from_finances'] and 'credit' in line['description'].lower()
        )
        self.assertEqual(invoice_line['amount'], '750.00')
        self.assertEqual(data['totals']['balance'], '0.00')

    def test_transaction_type_switch_flips_completion_monies_direction(self):
        """
        Edge: matter opened as sale but completes as purchase (or vice versa).

        Changing transaction_type recalculates completion monies direction on
        the next load; fee earner must re-check all line directions.
        """
        statement = get_or_create_completion_statement(self.matter, self.user)
        statement.completion_monies = Decimal('250000.00')
        statement.save()

        sale_data = get_completion_statement_data(
            statement, self.matter, calculate_invoice_total_with_vat
        )
        self.assertEqual(sale_data['completion_monies_line']['direction'], 'add')

        statement.transaction_type = CompletionStatement.TRANSACTION_PURCHASE
        statement.save()
        purchase_data = get_completion_statement_data(
            statement, self.matter, calculate_invoice_total_with_vat
        )
        self.assertEqual(purchase_data['completion_monies_line']['direction'], 'less')

    def test_finalised_snapshot_ignores_later_finance_changes(self):
        """
        Edge: new invoice or slip posted after completion statement finalised.

        Solution: finance_snapshot frozen at finalise; live finances no longer
        alter the published PDF or totals.
        """
        statement = get_or_create_completion_statement(self.matter, self.user)
        clear_template_lines(statement)
        statement.completion_monies = Decimal('100000.00')
        statement.save()
        add_manual(statement, self.user, direction='less', description='Mortgage redemption', amount='100000', sort_order=1)

        before = get_completion_statement_data(
            statement, self.matter, calculate_invoice_total_with_vat
        )
        self.client.post(
            reverse('completion_statement_status', args=['CV-EDGE01']),
            data='{"action":"finalise"}',
            content_type='application/json',
        )
        statement.refresh_from_db()

        add_final_invoice(
            self.matter, self.user, number=5003, costs=[5000.00], vat=Decimal('0.00')
        )
        after = get_completion_statement_data(
            statement, self.matter, calculate_invoice_total_with_vat
        )

        self.assertEqual(after['lines'], before['lines'])
        self.assertEqual(after['totals'], before['totals'])
        self.assertEqual(len(after['lines']), len(before['lines']))
        finance_after = [l for l in after['lines'] if l.get('from_finances')]
        self.assertEqual(len(finance_after), 0)

    def test_running_balance_skips_excluded_lines(self):
        """
        Edge: excluded line in the middle of the list must not move running total.

        Running balance column should match a hand-calculated cumulative sum
        over active lines only.
        """
        statement = get_or_create_completion_statement(self.matter, self.user)
        clear_template_lines(statement)
        statement.completion_monies = Decimal('100000.00')
        statement.save()

        slip = PmtsSlips.objects.create(
            file_number=self.matter,
            ledger_account='C',
            mode_of_pmt='BT',
            amount=Decimal('10000.00'),
            is_money_out=False,
            pmt_person='Client',
            description='On account',
            date=date(2024, 5, 1),
            balance_left=Decimal('10000.00'),
            created_by=self.user,
        )
        CompletionStatementFinanceLineOverride.objects.create(
            completion_statement=statement,
            source_type=CompletionStatementFinanceLineOverride.SOURCE_SLIP,
            source_id=slip.id,
            is_excluded=True,
        )
        add_manual(statement, self.user, direction='less', description='Mortgage redemption', amount='100000', sort_order=1)

        data = get_completion_statement_data(
            statement, self.matter, calculate_invoice_total_with_vat
        )
        excluded = next(line for line in data['lines'] if line['is_excluded'])
        active = next(line for line in data['lines'] if not line['is_excluded'])

        # After completion monies (+100k), excluded slip does not change running total.
        self.assertEqual(excluded['running_balance'], '100000.00')
        self.assertEqual(active['running_balance'], '0.00')

    def test_direction_override_on_finance_line(self):
        """
        Edge: rare case where default slip direction is wrong for this matter.

        Solution: direction_override on the finance line override record.
        """
        statement = get_or_create_completion_statement(self.matter, self.user)
        clear_template_lines(statement)
        statement.completion_monies = Decimal('100000.00')
        statement.save()

        slip = PmtsSlips.objects.create(
            file_number=self.matter,
            ledger_account='C',
            mode_of_pmt='BT',
            amount=Decimal('5000.00'),
            is_money_out=False,
            pmt_person='Client',
            description='Refund to client',
            date=date(2024, 5, 1),
            balance_left=Decimal('5000.00'),
            created_by=self.user,
        )
        CompletionStatementFinanceLineOverride.objects.create(
            completion_statement=statement,
            source_type=CompletionStatementFinanceLineOverride.SOURCE_SLIP,
            source_id=slip.id,
            direction_override='less',
        )
        add_manual(statement, self.user, direction='less', description='Mortgage redemption', amount='95000', sort_order=1)

        data = get_completion_statement_data(
            statement, self.matter, calculate_invoice_total_with_vat
        )
        slip_line = next(line for line in data['lines'] if line['source_id'] == slip.id)
        self.assertEqual(slip_line['direction'], 'less')
        self.assertEqual(data['totals']['balance'], '0.00')
