from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.db.models import Q
from django.utils import timezone

from .estate_account import calculate_invoice_total_with_vat
from .money_split import split_amount_with_penny_adjustment
from .models import (
    CompletionStatement,
    CompletionStatementApportionment,
    CompletionStatementFinanceLineOverride,
    CompletionStatementManualEntry,
    CompletionStatementMortgageRedemption,
    CompletionStatementProceedsDistribution,
    CompletionStatementScheduledPayment,
    CreditNote,
    Invoices,
    LedgerAccountTransfers,
    PmtsSlips,
    WIP,
)


def matter_is_conveyancing(matter):
    return bool(
        matter.matter_type
        and 'conveyancing' in matter.matter_type.type.lower()
    )


def _parse_date(value):
    if not value:
        return None
    if hasattr(value, 'strftime'):
        return value
    for fmt in ('%Y-%m-%d', '%d/%m/%Y'):
        try:
            return datetime.strptime(str(value), fmt).date()
        except ValueError:
            continue
    return None


def _format_date(value):
    if not value:
        return ''
    if isinstance(value, str):
        parsed = _parse_date(value)
        if parsed:
            value = parsed
        else:
            return value
    return value.strftime('%d/%m/%Y')


def _format_date_iso(value):
    parsed = _parse_date(value)
    return parsed.isoformat() if parsed else ''


def _format_money(amount):
    amount = Decimal(str(amount or 0)).quantize(Decimal('0.01'))
    return f'£{amount:,.2f}'


def _decimal(value, default=Decimal('0')):
    try:
        return Decimal(str(value)).quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError):
        return default


def _client_address(client):
    if not client:
        return ''
    address_parts = [
        client.address_line1,
        client.address_line2,
        client.county,
        client.postcode,
    ]
    return ', '.join(part for part in address_parts if part)


def _completion_monies_direction(transaction_type):
    if transaction_type == CompletionStatement.TRANSACTION_PURCHASE:
        return CompletionStatementFinanceLineOverride.DIRECTION_LESS
    return CompletionStatementFinanceLineOverride.DIRECTION_ADD


def _default_template_lines(transaction_type):
    if transaction_type == CompletionStatement.TRANSACTION_PURCHASE:
        return [
            ('add', 'Deposit paid'),
            ('add', 'Mortgage advance'),
            ('add', 'Legal fees and disbursements'),
            ('add', 'Stamp duty land tax (SDLT)'),
            ('add', 'Apportionments'),
        ]
    return [
        ('less', 'Mortgage redemption'),
        ('less', 'Estate agent commission'),
        ('less', 'Legal fees and disbursements'),
        ('less', 'Apportionments'),
    ]


def get_or_create_completion_statement(matter, user=None):
    statement, created = CompletionStatement.objects.get_or_create(
        matter=matter,
        defaults={
            'property_address': matter.matter_description or '',
            'completion_date': timezone.localdate(),
        },
    )
    if created:
        for sort_order, (direction, description) in enumerate(
            _default_template_lines(statement.transaction_type), start=1
        ):
            CompletionStatementManualEntry.objects.create(
                completion_statement=statement,
                direction=direction,
                description=description,
                amount=Decimal('0.00'),
                is_pending=True,
                sort_order=sort_order,
                created_by=user,
            )
    return statement


FINANCE_SOURCE_LABELS = {
    CompletionStatementFinanceLineOverride.SOURCE_GREEN_SLIP: 'Green slip',
    CompletionStatementFinanceLineOverride.SOURCE_INVOICE: 'Invoice',
    CompletionStatementFinanceLineOverride.SOURCE_CREDIT_NOTE: 'Credit note',
}


def _source_label_for_slip(slip):
    return 'Pink slip' if slip.is_money_out else 'Blue slip'


def _default_direction_for_slip(slip, transaction_type):
    if slip.is_money_out:
        return CompletionStatementFinanceLineOverride.DIRECTION_LESS
    return CompletionStatementFinanceLineOverride.DIRECTION_ADD


def _default_direction_for_green_slip(slip, matter, transaction_type):
    if slip.file_number_from_id == matter.id:
        return CompletionStatementFinanceLineOverride.DIRECTION_LESS
    return CompletionStatementFinanceLineOverride.DIRECTION_ADD


def _default_direction_for_invoice(transaction_type):
    if transaction_type == CompletionStatement.TRANSACTION_PURCHASE:
        return CompletionStatementFinanceLineOverride.DIRECTION_ADD
    return CompletionStatementFinanceLineOverride.DIRECTION_LESS


def _credit_notes_by_invoice(matter):
    credits = {}
    for credit_note in CreditNote.objects.filter(
        file_number=matter.id, status='F'
    ):
        credits[credit_note.invoice_id] = (
            credits.get(credit_note.invoice_id, Decimal('0')) + credit_note.amount
        )
    return credits


def _finance_rows_for_matter(matter, transaction_type, calculate_invoice_total):
    file_number = matter.file_number
    rows = []

    for slip in PmtsSlips.objects.filter(file_number=matter.id):
        desc = f'{slip.pmt_person} - {slip.description}'.strip(' -')
        rows.append({
            'line_kind': 'finance',
            'source_type': CompletionStatementFinanceLineOverride.SOURCE_SLIP,
            'source_id': slip.id,
            'source_label': _source_label_for_slip(slip),
            'is_money_out': bool(slip.is_money_out),
            'default_direction': _default_direction_for_slip(slip, transaction_type),
            'date': slip.date,
            'description': desc,
            'amount': slip.amount,
        })

    for slip in LedgerAccountTransfers.objects.filter(
        Q(file_number_from=matter.id) | Q(file_number_to=matter.id)
    ):
        if slip.file_number_from_id == slip.file_number_to_id:
            continue
        if slip.file_number_from.file_number == file_number:
            desc = f'Transfer to {slip.file_number_to}'
        else:
            desc = f'Transfer from {slip.file_number_from}'
        rows.append({
            'line_kind': 'finance',
            'source_type': CompletionStatementFinanceLineOverride.SOURCE_GREEN_SLIP,
            'source_id': slip.id,
            'source_label': FINANCE_SOURCE_LABELS[
                CompletionStatementFinanceLineOverride.SOURCE_GREEN_SLIP
            ],
            'default_direction': _default_direction_for_green_slip(
                slip, matter, transaction_type
            ),
            'date': slip.date,
            'description': desc,
            'amount': slip.amount,
        })

    credit_notes_by_invoice = _credit_notes_by_invoice(matter)

    for invoice in Invoices.objects.filter(file_number=matter.id):
        if invoice.state == 'F':
            desc = f'ANP Invoice {invoice.invoice_number}'
        else:
            desc = 'DRAFT ANP Invoice'
        _, _, total_cost_invoice = calculate_invoice_total(invoice)
        credit_total = credit_notes_by_invoice.pop(invoice.id, Decimal('0'))
        net_amount = max(Decimal('0'), total_cost_invoice - credit_total)
        if credit_total > 0:
            desc = f'{desc} (less credit {_format_money(credit_total)})'
        rows.append({
            'line_kind': 'finance',
            'source_type': CompletionStatementFinanceLineOverride.SOURCE_INVOICE,
            'source_id': invoice.id,
            'source_label': FINANCE_SOURCE_LABELS[
                CompletionStatementFinanceLineOverride.SOURCE_INVOICE
            ],
            'default_direction': _default_direction_for_invoice(transaction_type),
            'date': invoice.date,
            'description': desc,
            'amount': net_amount,
        })

    return rows


def _override_map(completion_statement):
    overrides = {}
    for override in completion_statement.finance_overrides.all():
        overrides[(override.source_type, override.source_id)] = override
    return overrides


def _signed_amount(direction, amount):
    value = _decimal(amount)
    if direction == CompletionStatementFinanceLineOverride.DIRECTION_LESS:
        return -value
    return value


def _line_sort_key(line):
    sort_order = line.get('sort_order', 0)
    date_str = line.get('date_iso') or line.get('date') or '0001-01-01'
    return (sort_order, date_str, line.get('id') or 0)


def _serialize_line(line):
    amount = _decimal(line['amount'])
    direction = line['direction']
    signed = _signed_amount(direction, amount)
    return {
        **line,
        'amount': str(amount),
        'amount_display': _format_money(amount),
        'add_amount': str(amount) if direction == 'add' else '',
        'add_amount_display': _format_money(amount) if direction == 'add' else '',
        'less_amount': str(amount) if direction == 'less' else '',
        'less_amount_display': _format_money(amount) if direction == 'less' else '',
        'signed_amount': str(signed),
        'date': _format_date(line.get('date')),
        'date_iso': _format_date_iso(line.get('date')),
    }


def _build_completion_monies_line(completion_statement):
    direction = _completion_monies_direction(completion_statement.transaction_type)
    amount = completion_statement.completion_monies
    line = {
        'line_kind': 'completion_monies',
        'id': None,
        'direction': direction,
        'date': completion_statement.completion_date,
        'description': 'Completion monies',
        'amount': amount,
        'is_excluded': False,
        'is_pending': False,
        'from_finances': False,
        'is_pinned': True,
        'sort_order': 0,
    }
    return _serialize_line(line)


def _compute_running_balances(completion_monies_line, lines):
    running = Decimal('0')
    if not completion_monies_line.get('is_excluded'):
        running += _decimal(completion_monies_line['signed_amount'])

    enriched_completion_monies = {
        **completion_monies_line,
        'running_balance': str(running.quantize(Decimal('0.01'))),
        'running_balance_display': _format_money(running),
    }

    enriched = []
    for line in lines:
        if not line.get('is_excluded'):
            running += _decimal(line['signed_amount'])
        enriched.append({
            **line,
            'running_balance': str(running.quantize(Decimal('0.01'))),
            'running_balance_display': _format_money(running),
        })
    return enriched_completion_monies, enriched


def _compute_totals(completion_statement, completion_monies_line, lines):
    active_lines = [completion_monies_line] + [
        line for line in lines if not line.get('is_excluded')
    ]
    balance = sum(_decimal(line['signed_amount']) for line in active_lines)
    add_total = sum(
        _decimal(line['amount'])
        for line in active_lines
        if line['direction'] == CompletionStatementFinanceLineOverride.DIRECTION_ADD
    )
    less_total = sum(
        _decimal(line['amount'])
        for line in active_lines
        if line['direction'] == CompletionStatementFinanceLineOverride.DIRECTION_LESS
    )
    is_balanced = balance == Decimal('0.00')
    if is_balanced:
        outcome_label = 'Balanced at £0.00'
    elif balance > 0:
        outcome_label = f'Amount due to you: {_format_money(balance)}'
    else:
        outcome_label = (
            f'Amount required to complete: {_format_money(abs(balance))}'
        )

    return {
        'balance': str(balance),
        'balance_display': _format_money(balance),
        'is_balanced': is_balanced,
        'outcome_label': outcome_label,
        'add_total': str(add_total),
        'add_total_display': _format_money(add_total),
        'less_total': str(less_total),
        'less_total_display': _format_money(less_total),
        'money_in_total': str(add_total),
        'money_in_total_display': _format_money(add_total),
        'money_out_total': str(less_total),
        'money_out_total_display': _format_money(less_total),
    }


def _statement_metadata(completion_statement, matter):
    client_names = []
    if matter.client1:
        client_names.append(matter.client1.name)
    if matter.client2:
        client_names.append(matter.client2.name)
    return {
        'id': completion_statement.id,
        'status': completion_statement.status,
        'status_display': completion_statement.get_status_display(),
        'transaction_type': completion_statement.transaction_type,
        'transaction_type_display': completion_statement.get_transaction_type_display(),
        'completion_monies': str(completion_statement.completion_monies),
        'completion_monies_display': _format_money(completion_statement.completion_monies),
        'property_address': completion_statement.property_address,
        'completion_date': _format_date_iso(completion_statement.completion_date),
        'completion_date_display': _format_date(completion_statement.completion_date),
        'contract_date': _format_date_iso(completion_statement.contract_date),
        'contract_date_display': _format_date(completion_statement.contract_date),
        'prepared_by_name': completion_statement.prepared_by_name,
        'prepared_by_address': completion_statement.prepared_by_address,
        'notes': completion_statement.notes,
        'client_names': ', '.join(client_names),
        'file_number': matter.file_number,
        'is_editable': completion_statement.status == CompletionStatement.STATUS_DRAFT,
        'is_leasehold': completion_statement.is_leasehold,
        'finalised_at': (
            completion_statement.finalised_at.isoformat()
            if completion_statement.finalised_at else ''
        ),
    }


def _lines_summary_text(completion_monies_line, lines, totals):
    active_count = sum(
        1 for line in lines if not line.get('is_excluded')
    ) + (0 if completion_monies_line.get('is_excluded') else 1)
    if not active_count:
        return 'No lines'
    line_word = 'line' if active_count == 1 else 'lines'
    return f'{active_count} {line_word} · {totals["outcome_label"]}'


def _lines_summary_text(completion_monies_line, lines, totals):
    active_count = sum(
        1 for line in lines if not line.get('is_excluded')
    ) + (0 if completion_monies_line.get('is_excluded') else 1)
    if not active_count:
        return 'No lines'
    line_word = 'line' if active_count == 1 else 'lines'
    return f'{active_count} {line_word} · {totals["outcome_label"]}'


def _serialize_mortgage_redemption(redemption):
    if not redemption:
        return None
    return {
        'id': redemption.id,
        'lender_name': redemption.lender_name,
        'loan_account_ref': redemption.loan_account_ref,
        'redemption_figure': str(redemption.redemption_figure),
        'redemption_figure_display': _format_money(redemption.redemption_figure),
        'redemption_statement_date': _format_date_iso(redemption.redemption_statement_date),
        'redemption_statement_date_display': _format_date(redemption.redemption_statement_date),
        'daily_interest_amount': str(redemption.daily_interest_amount),
        'completion_date': _format_date_iso(redemption.completion_date),
        'calculated_days': redemption.calculated_days,
        'calculated_interest': str(redemption.calculated_interest),
        'calculated_interest_display': _format_money(redemption.calculated_interest),
        'total_amount': str(redemption.total_amount),
        'total_amount_display': _format_money(redemption.total_amount),
    }


def _serialize_apportionment(row):
    return {
        'id': row.id,
        'item_type': row.item_type,
        'description': row.description,
        'annual_amount': str(row.annual_amount),
        'annual_amount_display': _format_money(row.annual_amount),
        'period_start': _format_date_iso(row.period_start),
        'period_end': _format_date_iso(row.period_end),
        'paid_in_advance': row.paid_in_advance,
        'completion_date': _format_date_iso(row.completion_date),
        'seller_days': row.seller_days,
        'buyer_days': row.buyer_days,
        'calculated_amount': str(row.calculated_amount),
        'calculated_amount_display': _format_money(row.calculated_amount),
        'direction': row.direction,
        'sort_order': row.sort_order,
    }


def _serialize_distribution(row, *, is_finalised):
    projected = row.projected_amount
    actual = row.actual_amount
    display_amount = actual if is_finalised and actual is not None else projected
    return {
        'id': row.id,
        'payee_name': row.payee_name,
        'reference': row.reference,
        'share_mode': row.share_mode,
        'share_value': row.share_value,
        'projected_amount': str(projected),
        'projected_amount_display': _format_money(projected),
        'actual_amount': str(actual) if actual is not None else '',
        'actual_amount_display': _format_money(actual) if actual is not None else '',
        'display_amount': str(display_amount),
        'display_amount_display': _format_money(display_amount),
        'display_label': 'Received' if is_finalised and actual is not None else 'Will receive',
        'penny_adjustment': str(row.penny_adjustment),
        'linked_slip_id': row.linked_slip_id,
        'sort_order': row.sort_order,
    }


def _serialize_schedule_row(row):
    slip = row.linked_slip
    ledger_variance = False
    if slip and slip.ledger_account != row.ledger_account:
        ledger_variance = True
    amount_variance = False
    if row.actual_amount is not None and row.actual_amount != row.projected_amount:
        amount_variance = True
    return {
        'id': row.id,
        'payee_name': row.payee_name,
        'description': row.description,
        'reference': row.reference,
        'direction': row.direction,
        'ledger_account': row.ledger_account,
        'ledger_account_display': row.get_ledger_account_display(),
        'projected_amount': str(row.projected_amount),
        'projected_amount_display': _format_money(row.projected_amount),
        'actual_amount': str(row.actual_amount) if row.actual_amount is not None else '',
        'actual_amount_display': (
            _format_money(row.actual_amount) if row.actual_amount is not None else ''
        ),
        'payment_date': _format_date_iso(row.payment_date),
        'payment_date_display': _format_date(row.payment_date),
        'status': row.status,
        'status_display': row.get_status_display(),
        'linked_slip_id': row.linked_slip_id,
        'source_kind': row.source_kind,
        'source_id': row.source_id,
        'sort_order': row.sort_order,
        'ledger_variance': ledger_variance,
        'amount_variance': amount_variance,
        'slip_ledger_account': slip.ledger_account if slip else '',
        'slip_ledger_account_display': (
            slip.get_ledger_account_display() if slip else ''
        ),
    }


def _serialize_tabs(completion_statement, is_finalised):
    redemption = getattr(completion_statement, 'mortgage_redemption', None)
    try:
        redemption = completion_statement.mortgage_redemption
    except CompletionStatementMortgageRedemption.DoesNotExist:
        redemption = None

    distributions = completion_statement.proceeds_distributions.order_by('sort_order', 'id')
    dist_total = sum(d.projected_amount for d in distributions)

    return {
        'mortgage_redemption': _serialize_mortgage_redemption(redemption),
        'apportionments': [
            _serialize_apportionment(row)
            for row in completion_statement.apportionments.order_by('sort_order', 'id')
        ],
        'proceeds_distribution': {
            'pool_total': str(dist_total),
            'pool_total_display': _format_money(dist_total),
            'penny_check': '0.00',
            'rows': [
                _serialize_distribution(row, is_finalised=is_finalised)
                for row in distributions
            ],
        },
        'schedule': [
            _serialize_schedule_row(row)
            for row in completion_statement.scheduled_payments.order_by('sort_order', 'id')
        ],
    }


def compute_positive_balance_excluding_manual_ids(
    completion_statement, matter, calculate_invoice_total, exclude_manual_ids
):
    """Signed balance excluding specific manual entries (for distribution pool)."""
    exclude_manual_ids = set(exclude_manual_ids or [])
    overrides = _override_map(completion_statement)
    balance = Decimal('0')

    cm_direction = _completion_monies_direction(completion_statement.transaction_type)
    balance += _signed_amount(cm_direction, completion_statement.completion_monies)

    for finance_row in _finance_rows_for_matter(
        matter, completion_statement.transaction_type, calculate_invoice_total
    ):
        key = (finance_row['source_type'], finance_row['source_id'])
        override = overrides.get(key)
        if override and override.is_excluded:
            continue
        direction = (
            override.direction_override if override and override.direction_override
            else finance_row['default_direction']
        )
        amount = (
            override.amount_override if override and override.amount_override is not None
            else finance_row['amount']
        )
        balance += _signed_amount(direction, amount)

    for manual in completion_statement.manual_entries.all():
        if manual.id in exclude_manual_ids:
            continue
        balance += _signed_amount(manual.direction, manual.amount)

    return max(Decimal('0.00'), balance)


def get_completion_statement_data(
    completion_statement, matter, calculate_invoice_total=calculate_invoice_total_with_vat
):
    if (
        completion_statement.status == CompletionStatement.STATUS_FINALISED
        and completion_statement.finance_snapshot
    ):
        return completion_statement.finance_snapshot

    overrides = _override_map(completion_statement)
    lines = []

    for finance_row in _finance_rows_for_matter(
        matter,
        completion_statement.transaction_type,
        calculate_invoice_total,
    ):
        key = (finance_row['source_type'], finance_row['source_id'])
        override = overrides.get(key)
        is_excluded = bool(override and override.is_excluded)
        date_value = (
            override.date_override if override and override.date_override
            else finance_row['date']
        )
        description = (
            override.description_override if override and override.description_override
            else finance_row['description']
        )
        amount = (
            override.amount_override if override and override.amount_override is not None
            else finance_row['amount']
        )
        direction = (
            override.direction_override if override and override.direction_override
            else finance_row['default_direction']
        )
        sort_order = override.sort_order if override else 0
        line = {
            'line_kind': 'finance',
            'id': override.id if override else None,
            'override_id': override.id if override else None,
            'source_type': finance_row['source_type'],
            'source_id': finance_row['source_id'],
            'source_label': finance_row.get('source_label', 'Finances'),
            'is_money_out': finance_row.get('is_money_out'),
            'direction': direction,
            'date': date_value,
            'description': description,
            'amount': amount,
            'is_excluded': is_excluded,
            'is_pending': False,
            'from_finances': True,
            'is_pinned': False,
            'sort_order': sort_order,
        }
        lines.append(line)

    for manual in completion_statement.manual_entries.all():
        lines.append({
            'line_kind': 'manual',
            'id': manual.id,
            'override_id': None,
            'source_type': '',
            'source_id': None,
            'direction': manual.direction,
            'date': manual.date,
            'description': manual.description,
            'amount': manual.amount,
            'is_excluded': False,
            'is_pending': manual.is_pending,
            'from_finances': False,
            'is_pinned': False,
            'is_system_managed': manual.is_system_managed,
            'sort_order': manual.sort_order,
        })

    lines = [_serialize_line(line) for line in sorted(lines, key=_line_sort_key)]
    completion_monies_line = _build_completion_monies_line(completion_statement)
    completion_monies_line, lines = _compute_running_balances(completion_monies_line, lines)
    metadata = _statement_metadata(completion_statement, matter)
    totals = _compute_totals(completion_statement, completion_monies_line, lines)
    is_finalised = completion_statement.status == CompletionStatement.STATUS_FINALISED
    tabs = _serialize_tabs(completion_statement, is_finalised)

    return {
        'metadata': metadata,
        'completion_monies_line': completion_monies_line,
        'lines': lines,
        'totals': totals,
        'summaries': {
            'header': ' · '.join(filter(None, [
                metadata['transaction_type_display'],
                metadata['property_address'][:60] if metadata['property_address'] else '',
                metadata['completion_date_display'],
            ])) or 'Header details not set',
            'lines': _lines_summary_text(completion_monies_line, lines, totals),
        },
        **tabs,
    }


def build_completion_statement_snapshot(
    completion_statement, matter, calculate_invoice_total=calculate_invoice_total_with_vat
):
    return get_completion_statement_data(
        completion_statement, matter, calculate_invoice_total
    )


def totals_payload(
    completion_statement, matter, calculate_invoice_total=calculate_invoice_total_with_vat
):
    data = get_completion_statement_data(
        completion_statement, matter, calculate_invoice_total
    )
    return {
        'totals': data['totals'],
        'metadata': {
            'status': data['metadata']['status'],
            'is_editable': data['metadata']['is_editable'],
            'transaction_type': data['metadata']['transaction_type'],
            'completion_monies': data['metadata']['completion_monies'],
            'completion_monies_display': data['metadata']['completion_monies_display'],
            'is_leasehold': data['metadata'].get('is_leasehold', False),
        },
        'completion_monies_line': data['completion_monies_line'],
        'lines': data['lines'],
        'summaries': data['summaries'],
        'mortgage_redemption': data.get('mortgage_redemption'),
        'apportionments': data.get('apportionments', []),
        'proceeds_distribution': data.get('proceeds_distribution', {}),
        'schedule': data.get('schedule', []),
    }


def _calc_as_date(value):
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return None


def calculate_mortgage_redemption(
    *,
    redemption_figure,
    redemption_statement_date,
    daily_interest_amount,
    completion_date,
):
    figure = Decimal(str(redemption_figure or 0)).quantize(Decimal('0.01'))
    daily = Decimal(str(daily_interest_amount or 0)).quantize(Decimal('0.0001'))
    start = _calc_as_date(redemption_statement_date)
    end = _calc_as_date(completion_date)

    days = 0
    if start and end and end >= start:
        days = (end - start).days

    interest = (Decimal(days) * daily).quantize(Decimal('0.01'))
    total = (figure + interest).quantize(Decimal('0.01'))
    return {
        'calculated_days': days,
        'calculated_interest': interest,
        'total_amount': total,
    }


def _days_inclusive(start, end):
    if not start or not end or end < start:
        return 0
    return (end - start).days + 1


def calculate_apportionment(
    *,
    annual_amount,
    period_start,
    period_end,
    completion_date,
    paid_in_advance,
    transaction_type,
):
    """
    Standard day-count apportionment for leasehold items.

    paid_in_advance=True: seller credited for days after completion.
    paid_in_advance=False: buyer credited for days before completion.
    """
    annual = Decimal(str(annual_amount or 0)).quantize(Decimal('0.01'))
    start = _calc_as_date(period_start)
    end = _calc_as_date(period_end)
    completion = _calc_as_date(completion_date)

    if not annual or not start or not end or not completion:
        return {
            'seller_days': 0,
            'buyer_days': 0,
            'calculated_amount': Decimal('0.00'),
            'direction': 'add',
        }

    period_days = _days_inclusive(start, end) or 1
    daily_rate = annual / Decimal(period_days)

    if paid_in_advance:
        seller_days = max(0, _days_inclusive(completion, end) - 1) if completion <= end else 0
        if completion > end:
            seller_days = 0
        elif completion >= start:
            seller_days = (end - completion).days
        else:
            seller_days = (end - start).days + 1
        buyer_days = period_days - seller_days
        amount = (daily_rate * Decimal(seller_days)).quantize(Decimal('0.01'))
        if transaction_type == 'purchase':
            direction = 'add'
        else:
            direction = 'less'
    else:
        if completion >= start:
            buyer_days = (completion - start).days
        else:
            buyer_days = 0
        seller_days = period_days - buyer_days
        amount = (daily_rate * Decimal(buyer_days)).quantize(Decimal('0.01'))
        if transaction_type == 'purchase':
            direction = 'add'
        else:
            direction = 'less'

    return {
        'seller_days': max(0, seller_days),
        'buyer_days': max(0, buyer_days),
        'calculated_amount': amount,
        'direction': direction,
    }


def _upsert_managed_manual(
    completion_statement,
    user,
    *,
    linked_entry,
    direction,
    description,
    amount,
    sort_order,
    entry_date=None,
):
    amount = Decimal(str(amount or 0)).quantize(Decimal('0.01'))
    if linked_entry:
        linked_entry.direction = direction
        linked_entry.description = description
        linked_entry.amount = amount
        linked_entry.sort_order = sort_order
        linked_entry.is_pending = False
        linked_entry.is_system_managed = True
        if entry_date:
            linked_entry.date = entry_date
        linked_entry.save()
        return linked_entry

    return CompletionStatementManualEntry.objects.create(
        completion_statement=completion_statement,
        direction=direction,
        description=description,
        amount=amount,
        sort_order=sort_order,
        is_pending=False,
        is_system_managed=True,
        date=entry_date,
        created_by=user,
    )


def _upsert_schedule_row(
    completion_statement,
    *,
    source_kind,
    source_id,
    payee_name,
    description,
    direction,
    ledger_account,
    projected_amount,
    payment_date=None,
    sort_order=0,
):
    defaults = {
        'payee_name': payee_name,
        'description': description or '',
        'direction': direction,
        'ledger_account': ledger_account,
        'projected_amount': Decimal(str(projected_amount or 0)).quantize(Decimal('0.01')),
        'payment_date': payment_date,
        'sort_order': sort_order,
    }
    row, created = CompletionStatementScheduledPayment.objects.get_or_create(
        completion_statement=completion_statement,
        source_kind=source_kind,
        source_id=source_id,
        defaults=defaults,
    )
    if not created and row.status == CompletionStatementScheduledPayment.STATUS_PENDING:
        for key, value in defaults.items():
            setattr(row, key, value)
        row.save()
    return row


def sync_mortgage_redemption(completion_statement, user):
    if completion_statement.transaction_type != CompletionStatement.TRANSACTION_SALE:
        return None

    redemption, _ = CompletionStatementMortgageRedemption.objects.get_or_create(
        completion_statement=completion_statement,
        defaults={
            'completion_date': completion_statement.completion_date,
        },
    )
    if not redemption.redemption_figure and not redemption.daily_interest_amount:
        return redemption

    completion_date = redemption.completion_date or completion_statement.completion_date
    calc = calculate_mortgage_redemption(
        redemption_figure=redemption.redemption_figure,
        redemption_statement_date=redemption.redemption_statement_date,
        daily_interest_amount=redemption.daily_interest_amount,
        completion_date=completion_date,
    )
    redemption.calculated_days = calc['calculated_days']
    redemption.calculated_interest = calc['calculated_interest']
    redemption.total_amount = calc['total_amount']
    redemption.completion_date = completion_date

    entry = _upsert_managed_manual(
        completion_statement,
        user,
        linked_entry=redemption.linked_manual_entry,
        direction=CompletionStatementManualEntry.DIRECTION_LESS,
        description='Mortgage redemption',
        amount=calc['total_amount'],
        sort_order=10,
        entry_date=completion_date,
    )
    redemption.linked_manual_entry = entry
    redemption.save()

    _upsert_schedule_row(
        completion_statement,
        source_kind=CompletionStatementScheduledPayment.SOURCE_MORTGAGE,
        source_id=redemption.id,
        payee_name=redemption.lender_name or 'Mortgage lender',
        description='Mortgage redemption',
        direction=CompletionStatementScheduledPayment.DIRECTION_LESS,
        ledger_account=CompletionStatementScheduledPayment.LEDGER_CLIENT,
        projected_amount=calc['total_amount'],
        payment_date=completion_date,
        sort_order=10,
    )
    return redemption


def sync_apportionments(completion_statement, user):
    for apportionment in completion_statement.apportionments.all():
        completion_date = (
            apportionment.completion_date or completion_statement.completion_date
        )
        calc = calculate_apportionment(
            annual_amount=apportionment.annual_amount,
            period_start=apportionment.period_start,
            period_end=apportionment.period_end,
            completion_date=completion_date,
            paid_in_advance=apportionment.paid_in_advance,
            transaction_type=completion_statement.transaction_type,
        )
        apportionment.seller_days = calc['seller_days']
        apportionment.buyer_days = calc['buyer_days']
        apportionment.calculated_amount = calc['calculated_amount']
        apportionment.direction = calc['direction']
        apportionment.completion_date = completion_date

        entry = _upsert_managed_manual(
            completion_statement,
            user,
            linked_entry=apportionment.linked_manual_entry,
            direction=apportionment.direction,
            description=apportionment.description,
            amount=calc['calculated_amount'],
            sort_order=20 + apportionment.sort_order,
            entry_date=completion_date,
        )
        apportionment.linked_manual_entry = entry
        apportionment.save()

        _upsert_schedule_row(
            completion_statement,
            source_kind=CompletionStatementScheduledPayment.SOURCE_APPORTIONMENT,
            source_id=apportionment.id,
            payee_name=apportionment.description[:255],
            description=apportionment.description,
            direction=apportionment.direction,
            ledger_account=CompletionStatementScheduledPayment.LEDGER_CLIENT,
            projected_amount=calc['calculated_amount'],
            payment_date=completion_date,
            sort_order=20 + apportionment.sort_order,
        )


def compute_distribution_pool(completion_statement, matter, calculate_invoice_total):
    exclude_ids = list(
        completion_statement.proceeds_distributions.exclude(
            linked_manual_entry_id__isnull=True
        ).values_list('linked_manual_entry_id', flat=True)
    )
    return compute_positive_balance_excluding_manual_ids(
        completion_statement, matter, calculate_invoice_total, exclude_ids
    )


def sync_proceeds_distribution(completion_statement, user, matter, calculate_invoice_total):
    if completion_statement.transaction_type != CompletionStatement.TRANSACTION_SALE:
        return

    distributions = list(completion_statement.proceeds_distributions.order_by('sort_order', 'id'))
    if not distributions:
        return

    pool = compute_distribution_pool(completion_statement, matter, calculate_invoice_total)
    shares = [
        {
            'mode': row.share_mode,
            'value': row.share_value,
            'sort_order': row.sort_order,
        }
        for row in distributions
    ]
    split_results = split_amount_with_penny_adjustment(pool, shares)
    result_by_sort = {r['sort_order']: r for r in split_results}

    for row in distributions:
        result = result_by_sort.get(row.sort_order, {})
        projected = result.get('projected_amount', Decimal('0.00'))
        penny = result.get('penny_adjustment', Decimal('0.00'))
        row.projected_amount = projected
        row.penny_adjustment = penny
        if row.linked_slip_id:
            row.actual_amount = row.linked_slip.amount

        entry = _upsert_managed_manual(
            completion_statement,
            user,
            linked_entry=row.linked_manual_entry,
            direction=CompletionStatementManualEntry.DIRECTION_LESS,
            description=f'Proceeds to {row.payee_name}',
            amount=projected,
            sort_order=30 + row.sort_order,
            entry_date=completion_statement.completion_date,
        )
        row.linked_manual_entry = entry
        row.save()

        _upsert_schedule_row(
            completion_statement,
            source_kind=CompletionStatementScheduledPayment.SOURCE_DISTRIBUTION,
            source_id=row.id,
            payee_name=row.payee_name,
            description=f'Proceeds to {row.payee_name}',
            direction=CompletionStatementScheduledPayment.DIRECTION_LESS,
            ledger_account=CompletionStatementScheduledPayment.LEDGER_CLIENT,
            projected_amount=projected,
            payment_date=completion_statement.completion_date,
            sort_order=30 + row.sort_order,
        )


def refresh_schedule_from_slips(completion_statement):
    for row in completion_statement.scheduled_payments.filter(linked_slip__isnull=False):
        slip = row.linked_slip
        row.actual_amount = slip.amount
        row.status = CompletionStatementScheduledPayment.STATUS_SLIP_CREATED
        row.save(update_fields=['actual_amount', 'status'])


def sync_all(completion_statement, matter, user, calculate_invoice_total):
    sync_mortgage_redemption(completion_statement, user)
    sync_apportionments(completion_statement, user)
    sync_proceeds_distribution(completion_statement, user, matter, calculate_invoice_total)
    refresh_schedule_from_slips(completion_statement)
    return completion_statement


def validate_for_finalise(completion_statement):
    errors = []
    pending = completion_statement.scheduled_payments.filter(
        status=CompletionStatementScheduledPayment.STATUS_PENDING
    )
    if pending.exists():
        errors.append(
            f'{pending.count()} scheduled payment(s) still pending — create slips or mark complete.'
        )
    missing_ledger = completion_statement.scheduled_payments.filter(
        ledger_account=''
    )
    if missing_ledger.exists():
        errors.append('Scheduled payments missing client/office account.')

    distributions = completion_statement.proceeds_distributions.all()
    if distributions:
        total = sum(d.projected_amount for d in distributions)
        pool = sum(d.projected_amount for d in distributions)
        if total != pool:
            pass
    return errors
