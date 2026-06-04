from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from backend.completion_statement import (
    get_completion_statement_data,
    get_or_create_completion_statement,
    sync_all,
)
from backend.estate_account import calculate_invoice_total_with_vat
from backend.models import (
    CompletionStatement,
    CompletionStatementApportionment,
    CompletionStatementManualEntry,
    CompletionStatementMortgageRedemption,
    CompletionStatementProceedsDistribution,
    Invoices,
    LedgerAccountTransfers,
    MatterType,
    PmtsSlips,
    WIP,
)
from users.models import CustomUser


class Command(BaseCommand):
    help = (
        'Seed completion statement demo data on conveyancing matters for frontend review. '
        'Creates draft sale (unbalanced), balanced sale via client payment, balanced sale '
        'via inter-matter transfer, and draft purchase (shortfall).'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--sale-file',
            default='ALL0070003',
            help='Sale matter — draft, amount still due to client.',
        )
        parser.add_argument(
            '--balanced-sale-file',
            default='MIL0110001',
            help='Sale matter — balanced £0 after pink slip payment to client.',
        )
        parser.add_argument(
            '--transfer-sale-file',
            default='JEN0030003',
            help='Sale matter — balanced £0 after green slip transfer out.',
        )
        parser.add_argument(
            '--transfer-target-file',
            default='BAN0010001',
            help='Purchase matter receiving inter-matter transfer (not the shortfall demo).',
        )
        parser.add_argument(
            '--purchase-file',
            default='ALL0070004',
            help='Purchase matter — draft shortfall demo.',
        )
        parser.add_argument(
            '--username',
            default='GB',
            help='User to attribute manual entries to (defaults to first superuser).',
        )

    def handle(self, *args, **options):
        user = self._resolve_user(options['username'])
        sale_matter = self._resolve_matter(options['sale_file'])
        balanced_sale_matter = self._resolve_matter(options['balanced_sale_file'])
        transfer_sale_matter = self._resolve_matter(options['transfer_sale_file'])
        transfer_target_matter = self._resolve_matter(options['transfer_target_file'])
        purchase_matter = self._resolve_matter(options['purchase_file'])

        self._seed_sale_unbalanced(sale_matter, user)
        self._seed_sale_balanced_payment(balanced_sale_matter, user)
        self._seed_sale_balanced_transfer(transfer_sale_matter, transfer_target_matter, user)
        self._seed_purchase(purchase_matter, user)

        for matter in (sale_matter, balanced_sale_matter, transfer_sale_matter, purchase_matter):
            cs = CompletionStatement.objects.get(matter=matter)
            sync_all(cs, matter, user, calculate_invoice_total_with_vat)

        self.stdout.write(self.style.SUCCESS('Completion statement demo data ready.'))
        self.stdout.write('')
        self.stdout.write('Open in the browser:')
        self.stdout.write(
            f'  Sale draft (amount due to client): /{sale_matter.file_number}/completion_statement/'
        )
        self.stdout.write(
            f'  Sale balanced (payment to client): /{balanced_sale_matter.file_number}/completion_statement/'
        )
        self.stdout.write(
            f'  Sale balanced (transfer to {transfer_target_matter.file_number}): '
            f'/{transfer_sale_matter.file_number}/completion_statement/'
        )
        self.stdout.write(
            f'  Purchase draft (shortfall): /{purchase_matter.file_number}/completion_statement/'
        )

    def _resolve_user(self, username):
        user = CustomUser.objects.filter(username__iexact=username).first()
        if not user:
            user = CustomUser.objects.filter(is_superuser=True).first()
        if not user:
            user = CustomUser.objects.first()
        if not user:
            raise SystemExit('No users found — create a user first.')
        return user

    def _resolve_matter(self, file_number):
        matter = WIP.objects.filter(file_number=file_number).select_related('matter_type').first()
        if not matter:
            raise SystemExit(f'Matter {file_number} not found.')
        if not matter.matter_type or 'conveyancing' not in matter.matter_type.type.lower():
            matter_type, _ = MatterType.objects.get_or_create(type='Residential Conveyancing')
            matter.matter_type = matter_type
            matter.save(update_fields=['matter_type'])
            self.stdout.write(
                self.style.WARNING(
                    f'{file_number}: matter type updated to Residential Conveyancing.'
                )
            )
        return matter

    def _reset_statement(self, matter, user, *, transaction_type):
        statement, _ = CompletionStatement.objects.update_or_create(
            matter=matter,
            defaults={
                'status': CompletionStatement.STATUS_DRAFT,
                'transaction_type': transaction_type,
                'completion_monies': Decimal('0.00'),
                'property_address': matter.matter_description or '',
                'completion_date': timezone.localdate(),
                'contract_date': date(2024, 3, 15),
                'notes': 'Demo data — safe to edit or delete.',
                'finance_snapshot': None,
                'finalised_at': None,
                'finalised_by': None,
            },
        )
        statement.finance_overrides.all().delete()
        statement.manual_entries.all().delete()
        get_or_create_completion_statement(matter, user)
        statement.refresh_from_db()
        statement.manual_entries.all().delete()
        return statement

    def _add_manual(self, statement, user, *, direction, description, amount, sort_order, entry_date=None):
        CompletionStatementManualEntry.objects.create(
            completion_statement=statement,
            direction=direction,
            description=description,
            amount=Decimal(str(amount)),
            sort_order=sort_order,
            is_pending=False,
            date=entry_date,
            created_by=user,
        )

    def _create_slip(self, matter, user, *, description, amount, is_money_out=False):
        from django.db import connection

        PmtsSlips.objects.create(
            file_number=matter,
            ledger_account='C',
            mode_of_pmt='BT',
            amount=amount,
            is_money_out=is_money_out,
            pmt_person='Client',
            description=description,
            date=date(2024, 4, 1) if not is_money_out else date(2024, 6, 28),
            balance_left=amount,
            created_by=user,
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT setval(pg_get_serial_sequence('backend_pmtsslips', 'id'), "
                "(SELECT COALESCE(MAX(id), 1) FROM backend_pmtsslips))"
            )

    def _ensure_demo_transfer(self, from_matter, to_matter, user, *, amount):
        from django.db import connection

        LedgerAccountTransfers.objects.filter(
            file_number_from=from_matter,
            description='[CS demo] Net proceeds to purchase',
        ).exclude(file_number_to=to_matter).delete()

        transfer = LedgerAccountTransfers.objects.filter(
            file_number_from=from_matter,
            file_number_to=to_matter,
            description='[CS demo] Net proceeds to purchase',
        ).first()
        if transfer:
            transfer.amount = amount
            transfer.balance_left_from = Decimal('0.00')
            transfer.balance_left_to = amount
            transfer.save(update_fields=['amount', 'balance_left_from', 'balance_left_to'])
            return transfer

        transfer = LedgerAccountTransfers.objects.create(
            file_number_from=from_matter,
            file_number_to=to_matter,
            from_ledger_account='C',
            to_ledger_account='C',
            amount=amount,
            date=date(2024, 6, 28),
            description='[CS demo] Net proceeds to purchase',
            amount_invoiced_from={},
            balance_left_from=Decimal('0.00'),
            amount_invoiced_to={},
            balance_left_to=amount,
            created_by=user,
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT setval(pg_get_serial_sequence('backend_ledgeraccounttransfers', 'id'), "
                "(SELECT COALESCE(MAX(id), 1) FROM backend_ledgeraccounttransfers))"
            )
        return transfer

    def _seed_sale_base(self, matter, user, *, invoice_number):
        """Shared sale figures: £320k completion, deductions, finance pull-through."""
        statement = self._reset_statement(
            matter, user, transaction_type=CompletionStatement.TRANSACTION_SALE
        )
        statement.completion_monies = Decimal('320000.00')
        statement.save(update_fields=['completion_monies'])

        slip = PmtsSlips.objects.filter(
            file_number=matter, description='[CS demo] Deposit on account'
        ).first()
        if slip:
            slip.amount = Decimal('5000.00')
            slip.balance_left = Decimal('5000.00')
            slip.is_money_out = False
            slip.save(update_fields=['amount', 'balance_left', 'is_money_out'])
        else:
            self._create_slip(
                matter, user,
                description='[CS demo] Deposit on account',
                amount=Decimal('5000.00'),
            )

        PmtsSlips.objects.filter(
            file_number=matter, description='[CS demo] Payment to client'
        ).delete()

        Invoices.objects.update_or_create(
            file_number=matter,
            description='[CS demo] Conveyancing costs',
            defaults={
                'invoice_number': invoice_number,
                'state': 'F',
                'date': date(2024, 6, 1),
                'our_costs': [1500.00],
                'vat': Decimal('300.00'),
                'created_by': user,
            },
        )

        self._add_manual(
            statement, user, direction='less', description='Mortgage redemption',
            amount='185000', sort_order=1, entry_date=date(2024, 6, 28),
        )
        self._add_manual(
            statement, user, direction='less', description='Estate agent commission',
            amount='4800', sort_order=2, entry_date=date(2024, 6, 28),
        )
        return statement

    def _net_sale_proceeds(self):
        """Completion + deposit on account minus mortgage, agent, and invoice."""
        return Decimal('133400.00')

    def _seed_sale_unbalanced(self, matter, user):
        statement = self._seed_sale_base(matter, user, invoice_number=99001)
        data = get_completion_statement_data(
            statement, matter, calculate_invoice_total_with_vat
        )
        self.stdout.write(
            f'Sale draft {matter.file_number}: {data["totals"]["outcome_label"]} '
            f'({len(data["lines"])} lines)'
        )

    def _seed_sale_balanced_payment(self, matter, user):
        statement = self._seed_sale_base(matter, user, invoice_number=99003)
        CompletionStatementMortgageRedemption.objects.update_or_create(
            completion_statement=statement,
            defaults={
                'lender_name': 'Demo Bank',
                'redemption_figure': Decimal('185000.00'),
                'redemption_statement_date': date(2024, 6, 1),
                'daily_interest_amount': Decimal('10.00'),
                'completion_date': date(2024, 6, 28),
            },
        )
        net = self._net_sale_proceeds()
        self._create_slip(
            matter, user,
            description='[CS demo] Payment to client',
            amount=net,
            is_money_out=True,
        )
        data = get_completion_statement_data(
            statement, matter, calculate_invoice_total_with_vat
        )
        self.stdout.write(
            f'Sale balanced (payment) {matter.file_number}: {data["totals"]["outcome_label"]} '
            f'({len(data["lines"])} lines)'
        )

    def _seed_sale_balanced_transfer(self, sale_matter, purchase_matter, user):
        statement = self._seed_sale_base(sale_matter, user, invoice_number=99004)
        net = self._net_sale_proceeds()
        self._ensure_demo_transfer(sale_matter, purchase_matter, user, amount=net)
        data = get_completion_statement_data(
            statement, sale_matter, calculate_invoice_total_with_vat
        )
        self.stdout.write(
            f'Sale balanced (transfer) {sale_matter.file_number}: {data["totals"]["outcome_label"]} '
            f'→ {purchase_matter.file_number} ({len(data["lines"])} lines)'
        )

    def _seed_purchase(self, matter, user):
        statement = self._reset_statement(
            matter, user, transaction_type=CompletionStatement.TRANSACTION_PURCHASE
        )
        statement.completion_monies = Decimal('350000.00')
        statement.is_leasehold = True
        statement.save(update_fields=['completion_monies', 'is_leasehold'])

        CompletionStatementApportionment.objects.filter(
            completion_statement=statement, description='[CS demo] Service charge'
        ).delete()
        CompletionStatementApportionment.objects.create(
            completion_statement=statement,
            item_type=CompletionStatementApportionment.ITEM_SERVICE_CHARGE,
            description='[CS demo] Service charge',
            annual_amount=Decimal('1200.00'),
            period_start=date(2024, 1, 1),
            period_end=date(2024, 12, 31),
            paid_in_advance=True,
            completion_date=date(2024, 6, 28),
            direction='add',
            sort_order=1,
        )

        self._add_manual(
            statement, user, direction='add', description='Deposit paid',
            amount='35000', sort_order=1, entry_date=date(2024, 5, 1),
        )
        self._add_manual(
            statement, user, direction='add', description='Mortgage advance',
            amount='310000', sort_order=2, entry_date=date(2024, 6, 28),
        )
        # SDLT and invoice omitted here so the draft clearly shows a £5k shortfall.

        data = get_completion_statement_data(
            statement, matter, calculate_invoice_total_with_vat
        )
        self.stdout.write(
            f'Purchase {matter.file_number}: {data["totals"]["outcome_label"]} '
            f'({len(data["lines"])} lines incl. finance pull-through)'
        )
