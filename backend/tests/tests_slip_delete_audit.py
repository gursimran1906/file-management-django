"""Tests that deleting a slip via the Django admin records a durable
'slip removed' audit event on the owning matter, so the audit trail survives
the hard delete (single-object and bulk paths)."""

from datetime import date
from decimal import Decimal

from django.contrib import admin
from django.contrib.contenttypes.models import ContentType
from django.test import RequestFactory, TestCase

from users.models import CustomUser

from ..admin import (
    LedgerAccountTransfersAdmin,
    PmtsSlipsAdmin,
    TempSlipsAdmin,
)
from ..models import (
    ClientContactDetails,
    LedgerAccountTransfers,
    MatterType,
    Modifications,
    PmtsSlips,
    TempSlips,
    WIP,
)


def make_matter(file_number, client_name='Jane Seller'):
    client = ClientContactDetails.objects.create(
        name=client_name,
        occupation='Retired',
        address_line1='1 Test Street',
        address_line2='',
        county='Essex',
        postcode='SS7 1QT',
        email='test@example.com',
        contact_number='0123456789',
    )
    matter_type = MatterType.objects.create(type='Residential Conveyancing')
    return WIP.objects.create(
        file_number=file_number,
        client1=client,
        matter_description='10 Example Road, Benfleet',
        matter_type=matter_type,
        funding='Pvt',
    )


class SlipDeleteAuditTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='adm',
            email='adm@example.com',
            first_name='Ada',
            last_name='Min',
            password='password',
            max_holidays_in_year=20,
        )
        self.matter = make_matter('CV0001')
        self.wip_ct = ContentType.objects.get_for_model(WIP)
        self.factory = RequestFactory()

    def _request(self):
        request = self.factory.post('/admin/')
        request.user = self.user
        return request

    def _deletion_logs(self, matter, field):
        """Modifications recording `field` removal, keyed to `matter` (the WIP)."""
        logs = []
        for mod in Modifications.objects.filter(
                content_type=self.wip_ct, object_id=matter.pk):
            if (mod.changes or {}).get(field):
                logs.append(mod)
        return logs

    def _make_pmts_slip(self):
        return PmtsSlips.objects.create(
            file_number=self.matter,
            ledger_account='C',
            mode_of_pmt='BT',
            amount=Decimal('500.00'),
            is_money_out=True,
            pmt_person='Client',
            description='Deposit',
            date=date(2026, 5, 1),
            balance_left=Decimal('500.00'),
            created_by=self.user,
        )

    def test_delete_model_logs_event_that_survives(self):
        slip = self._make_pmts_slip()
        slip_id = slip.id

        PmtsSlipsAdmin(PmtsSlips, admin.site).delete_model(
            self._request(), slip)

        # Slip is gone...
        self.assertFalse(PmtsSlips.objects.filter(id=slip_id).exists())

        # ...but a durable deletion event survives on the matter.
        logs = self._deletion_logs(self.matter, 'pmts_slip_deleted')
        self.assertEqual(len(logs), 1)
        change = logs[0].changes['pmts_slip_deleted']
        self.assertEqual(change['new_value'], '(deleted)')
        self.assertIn('Pink slip', change['old_value'])
        self.assertIn('Deposit', change['old_value'])
        self.assertEqual(logs[0].modified_by, self.user)

    def test_delete_queryset_bulk_logs_each(self):
        slip1 = self._make_pmts_slip()
        slip2 = self._make_pmts_slip()

        queryset = PmtsSlips.objects.filter(id__in=[slip1.id, slip2.id])
        PmtsSlipsAdmin(PmtsSlips, admin.site).delete_queryset(
            self._request(), queryset)

        self.assertEqual(PmtsSlips.objects.count(), 0)
        logs = self._deletion_logs(self.matter, 'pmts_slip_deleted')
        self.assertEqual(len(logs), 2)

    def test_green_slip_logs_on_both_matters(self):
        matter_to = make_matter('CV0002', client_name='John Buyer')
        transfer = LedgerAccountTransfers.objects.create(
            file_number_from=self.matter,
            file_number_to=matter_to,
            from_ledger_account='C',
            to_ledger_account='O',
            amount=Decimal('250.00'),
            date=date(2026, 6, 1),
            description='Costs transfer',
            balance_left_from=Decimal('0.00'),
            balance_left_to=Decimal('250.00'),
        )

        LedgerAccountTransfersAdmin(
            LedgerAccountTransfers, admin.site).delete_model(
            self._request(), transfer)

        self.assertEqual(
            len(self._deletion_logs(self.matter, 'green_slip_deleted')), 1)
        self.assertEqual(
            len(self._deletion_logs(matter_to, 'green_slip_deleted')), 1)

    def test_green_slip_same_matter_logged_once(self):
        transfer = LedgerAccountTransfers.objects.create(
            file_number_from=self.matter,
            file_number_to=self.matter,
            from_ledger_account='C',
            to_ledger_account='O',
            amount=Decimal('250.00'),
            date=date(2026, 6, 1),
            description='Client-to-office',
            balance_left_from=Decimal('0.00'),
            balance_left_to=Decimal('250.00'),
        )

        LedgerAccountTransfersAdmin(
            LedgerAccountTransfers, admin.site).delete_model(
            self._request(), transfer)

        self.assertEqual(
            len(self._deletion_logs(self.matter, 'green_slip_deleted')), 1)

    def test_temp_slip_resolves_matter_from_file_number(self):
        temp = TempSlips.objects.create(
            file_number=self.matter.file_number,  # CharField, not an FK
            date=date(2026, 6, 1),
            amount=Decimal('75.00'),
            description='Sundry',
            created_by=self.user,
        )

        TempSlipsAdmin(TempSlips, admin.site).delete_model(
            self._request(), temp)

        logs = self._deletion_logs(self.matter, 'temp_slip_deleted')
        self.assertEqual(len(logs), 1)

    def test_temp_slip_unknown_matter_is_skipped(self):
        temp = TempSlips.objects.create(
            file_number='NOPE9999',
            date=date(2026, 6, 1),
            amount=Decimal('75.00'),
            description='Orphan',
            created_by=self.user,
        )

        # No matching WIP -> no crash, no modification row created.
        TempSlipsAdmin(TempSlips, admin.site).delete_model(
            self._request(), temp)

        self.assertFalse(TempSlips.objects.filter(id=temp.id).exists())
        self.assertEqual(Modifications.objects.count(), 0)
