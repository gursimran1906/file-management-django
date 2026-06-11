from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from users.models import CustomUser
from ..models import ClientContactDetails, CreditNote, Invoices, MatterType, WIP
from ..views import (
    get_available_credit_amount,
    get_credit_note_max_amount,
    get_invoice_allocatable_due,
    get_invoice_amount_due,
)


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


def make_matter(file_number='CN0001'):
    client = make_client()
    matter_type = MatterType.objects.create(type='Probate')
    return WIP.objects.create(
        file_number=file_number,
        client1=client,
        matter_description='Test matter',
        matter_type=matter_type,
        funding='Pvt',
    )


class CreditNoteFlowTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='cnuser',
            email='cn@example.com',
            first_name='Credit',
            last_name='User',
            password='password',
            max_holidays_in_year=20,
        )
        self.manager = CustomUser.objects.create_user(
            username='cnmgr',
            email='cnmgr@example.com',
            first_name='Credit',
            last_name='Manager',
            password='password',
            max_holidays_in_year=20,
            is_manager=True,
        )
        self.matter = make_matter()
        self.invoice = Invoices.objects.create(
            file_number=self.matter,
            invoice_number=2001,
            state='F',
            date=date(2024, 6, 1),
            description='Probate costs',
            our_costs=['100.00'],
            our_costs_desc=['Work'],
            vat=Decimal('20.00'),
            total_due_left=Decimal('120.00'),
            created_by=self.user,
        )

    def test_pending_credit_note_reduces_available_headroom(self):
        CreditNote.objects.create(
            invoice=self.invoice,
            file_number=self.matter,
            date=date(2024, 6, 2),
            amount=Decimal('50.00'),
            reason='First pending',
            status='P',
            created_by=self.user,
        )
        self.assertEqual(get_available_credit_amount(self.invoice), Decimal('70.00'))

    def test_second_pending_credit_note_cannot_exceed_remaining_due(self):
        CreditNote.objects.create(
            invoice=self.invoice,
            file_number=self.matter,
            date=date(2024, 6, 2),
            amount=Decimal('80.00'),
            reason='First pending',
            status='P',
            created_by=self.user,
        )
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('add_credit_note', args=[self.matter.file_number]),
            {
                'invoice': self.invoice.id,
                'date': '2024-06-03',
                'amount': '80.00',
                'reason': 'Too much',
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            CreditNote.objects.filter(invoice=self.invoice, status='P').count(), 1)

    def test_approval_reduces_invoice_total_due_left(self):
        note = CreditNote.objects.create(
            invoice=self.invoice,
            file_number=self.matter,
            date=date(2024, 6, 2),
            amount=Decimal('30.00'),
            reason='Approved adjustment',
            status='P',
            created_by=self.user,
        )
        self.client.force_login(self.manager)
        response = self.client.get(reverse('approve_credit_note', args=[note.id]))
        self.assertEqual(response.status_code, 302)
        self.invoice.refresh_from_db()
        note.refresh_from_db()
        self.assertEqual(note.status, 'F')
        self.assertEqual(self.invoice.total_due_left, Decimal('90.00'))

    def test_rejected_credit_note_does_not_change_invoice_due(self):
        note = CreditNote.objects.create(
            invoice=self.invoice,
            file_number=self.matter,
            date=date(2024, 6, 2),
            amount=Decimal('30.00'),
            reason='Rejected adjustment',
            status='P',
            created_by=self.user,
        )
        self.client.force_login(self.manager)
        response = self.client.get(reverse('reject_credit_note', args=[note.id]))
        self.assertEqual(response.status_code, 302)
        self.invoice.refresh_from_db()
        note.refresh_from_db()
        self.assertEqual(note.status, 'R')
        self.assertEqual(self.invoice.total_due_left, Decimal('120.00'))


class InvoiceAllocatableDueTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='allocuser',
            email='alloc@example.com',
            first_name='Alloc',
            last_name='User',
            password='password',
            max_holidays_in_year=20,
        )
        self.matter = make_matter('ALC0001')
        self.invoice = Invoices.objects.create(
            file_number=self.matter,
            invoice_number=3001,
            state='F',
            date=date(2024, 6, 1),
            description='Probate costs',
            our_costs=['100.00'],
            our_costs_desc=['Work'],
            vat=Decimal('20.00'),
            total_due_left=Decimal('0.00'),
            created_by=self.user,
        )

    def test_allocatable_due_falls_back_to_computed_balance_after_credit_note(self):
        from ..views import get_invoice_allocatable_due

        CreditNote.objects.create(
            invoice=self.invoice,
            file_number=self.matter,
            date=date(2024, 6, 2),
            amount=Decimal('30.00'),
            reason='Partial credit',
            status='F',
            created_by=self.user,
        )
        due = get_invoice_allocatable_due(
            self.invoice, self.matter.file_number)
        self.assertEqual(due, Decimal('90.00'))

    def test_credit_note_max_uses_computed_due_when_stored_due_is_zero(self):
        CreditNote.objects.create(
            invoice=self.invoice,
            file_number=self.matter,
            date=date(2024, 6, 2),
            amount=Decimal('30.00'),
            reason='Partial credit',
            status='F',
            created_by=self.user,
        )
        max_amount = get_credit_note_max_amount(
            self.invoice, self.matter.file_number)
        self.assertEqual(max_amount, Decimal('90.00'))

    def test_allocatable_due_reduced_by_cash_allocation_after_credit_note(self):
        from ..models import PmtsSlips

        CreditNote.objects.create(
            invoice=self.invoice,
            file_number=self.matter,
            date=date(2024, 6, 2),
            amount=Decimal('30.00'),
            reason='Partial credit',
            status='F',
            created_by=self.user,
        )
        slip = PmtsSlips.objects.create(
            file_number=self.matter,
            ledger_account='C',
            mode_of_pmt='BT',
            amount=Decimal('50.00'),
            is_money_out=False,
            pmt_person='Client',
            description='Payment',
            date=date(2024, 5, 1),
            balance_left=Decimal('50.00'),
            amount_allocated={str(self.invoice.id): '20.00'},
            created_by=self.user,
        )
        self.invoice.cash_allocated_slips.add(slip)
        due = get_invoice_allocatable_due(
            self.invoice, self.matter.file_number)
        self.assertEqual(due, Decimal('70.00'))
