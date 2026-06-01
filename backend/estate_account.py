import ast
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.db.models import Q
from django.utils import timezone

from .models import (
    CURRENT_VAT_RATE,
    CreditNote,
    EstateAccount,
    EstateAccountDistribution,
    EstateAccountFinanceLineOverride,
    EstateAccountManualEntry,
    Invoices,
    LedgerAccountTransfers,
    MatterKeyDate,
    PmtsSlips,
    WIP,
)


def calculate_invoice_total_with_vat(invoice):
    our_costs = invoice.our_costs
    costs = ast.literal_eval(our_costs) if not isinstance(
        our_costs, list) else our_costs
    total_cost_invoice = Decimal('0')
    for cost in costs:
        total_cost_invoice += Decimal(str(cost))
    vat_inv = Decimal(str(invoice.vat or 0))
    total_cost_and_vat = total_cost_invoice + vat_inv
    return (
        round(total_cost_invoice, 2),
        round(vat_inv, 2),
        round(total_cost_and_vat, 2),
    )


def matter_is_probate(matter):
    return bool(
        matter.matter_type
        and matter.matter_type.type.lower() == 'probate'
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


def _default_date_of_death(matter):
    key_date = matter.key_dates.filter(
        title__icontains='death'
    ).order_by('date').first()
    return key_date.date if key_date else None


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


def _matter_client_signers(matter):
    signers = []
    for sort_order, client in enumerate(
        client for client in (matter.client1, matter.client2) if client
    ):
        signers.append({
            'id': client.id,
            'signer_name': client.name,
            'signer_address': _client_address(client),
            'sort_order': sort_order,
        })
    return signers


def get_or_create_estate_account(matter, user=None):
    account, created = EstateAccount.objects.get_or_create(
        matter=matter,
        defaults={
            'deceased_name': matter.client1.name if matter.client1_id else '',
            'date_of_death': _default_date_of_death(matter),
            'account_date': timezone.localdate(),
        },
    )
    return account


FINANCE_SOURCE_LABELS = {
    EstateAccountFinanceLineOverride.SOURCE_GREEN_SLIP: 'Green slip',
    EstateAccountFinanceLineOverride.SOURCE_INVOICE: 'Invoice',
    EstateAccountFinanceLineOverride.SOURCE_CREDIT_NOTE: 'Credit note',
}


def _source_label_for_slip(slip):
    return 'Pink slip' if slip.is_money_out else 'Blue slip'


def _default_section_for_slip(slip):
    if slip.is_money_out:
        return EstateAccountFinanceLineOverride.SECTION_DEBT
    return EstateAccountFinanceLineOverride.SECTION_ASSET


def _credit_notes_by_invoice(matter):
    credits = {}
    for credit_note in CreditNote.objects.filter(
        file_number=matter.id, status='F'
    ):
        credits[credit_note.invoice_id] = (
            credits.get(credit_note.invoice_id, Decimal('0')) + credit_note.amount
        )
    return credits


def _finance_rows_for_matter(matter, calculate_invoice_total_with_vat):
    file_number = matter.file_number
    rows = []

    for slip in PmtsSlips.objects.filter(file_number=matter.id):
        section = _default_section_for_slip(slip)
        desc = f'{slip.pmt_person} - {slip.description}'.strip(' -')
        rows.append({
            'line_kind': 'finance',
            'source_type': EstateAccountFinanceLineOverride.SOURCE_SLIP,
            'source_id': slip.id,
            'source_label': _source_label_for_slip(slip),
            'is_money_out': bool(slip.is_money_out),
            'default_section': section,
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
            section = EstateAccountFinanceLineOverride.SECTION_DEBT
            desc = f'Transfer to {slip.file_number_to}'
        else:
            section = EstateAccountFinanceLineOverride.SECTION_ASSET
            desc = f'Transfer from {slip.file_number_from}'
        rows.append({
            'line_kind': 'finance',
            'source_type': EstateAccountFinanceLineOverride.SOURCE_GREEN_SLIP,
            'source_id': slip.id,
            'source_label': FINANCE_SOURCE_LABELS[
                EstateAccountFinanceLineOverride.SOURCE_GREEN_SLIP
            ],
            'default_section': section,
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
        _, _, total_cost_invoice = calculate_invoice_total_with_vat(invoice)
        credit_total = credit_notes_by_invoice.pop(invoice.id, Decimal('0'))
        net_amount = max(Decimal('0'), total_cost_invoice - credit_total)
        if credit_total > 0:
            desc = f'{desc} (less credit {_format_money(credit_total)})'
        rows.append({
            'line_kind': 'finance',
            'source_type': EstateAccountFinanceLineOverride.SOURCE_INVOICE,
            'source_id': invoice.id,
            'source_label': FINANCE_SOURCE_LABELS[
                EstateAccountFinanceLineOverride.SOURCE_INVOICE
            ],
            'default_section': EstateAccountFinanceLineOverride.SECTION_DEBT,
            'date': invoice.date,
            'description': desc,
            'amount': net_amount,
        })

    return rows


def _override_map(estate_account):
    overrides = {}
    for override in estate_account.finance_overrides.all():
        overrides[(override.source_type, override.source_id)] = override
    return overrides


def _line_sort_key(line):
    sort_order = line.get('sort_order', 0)
    date_str = line.get('date_iso') or line.get('date') or '0001-01-01'
    return (sort_order, date_str, line.get('id') or 0)


def _serialize_line(line):
    amount = _decimal(line['amount'])
    return {
        **line,
        'amount': str(amount),
        'amount_display': _format_money(amount),
        'date': _format_date(line.get('date')),
        'date_iso': _format_date_iso(line.get('date')),
    }


def _serialize_distribution(row):
    return {
        'id': row.id,
        'beneficiary_name': row.beneficiary_name,
        'share_fraction': row.share_fraction,
        'gross_amount': str(row.gross_amount),
        'gross_amount_display': _format_money(row.gross_amount),
        'adjustment_description': row.adjustment_description,
        'adjustment_amount': str(row.adjustment_amount or Decimal('0')),
        'adjustment_amount_display': _format_money(row.adjustment_amount or 0),
        'net_amount': str(row.net_amount),
        'net_amount_display': _format_money(row.net_amount),
        'sort_order': row.sort_order,
    }


def _serialize_signer(row):
    return {
        'id': row.id,
        'signer_name': row.signer_name,
        'signer_address': row.signer_address,
        'sort_order': row.sort_order,
    }


def _lines_summary_text(lines):
    active = [line for line in lines if not line.get('is_excluded')]
    excluded_count = len(lines) - len(active)
    total = sum(_decimal(line['amount']) for line in active)
    if not active:
        text = 'No lines'
    else:
        line_word = 'line' if len(active) == 1 else 'lines'
        text = f'{len(active)} {line_word} · {_format_money(total)}'
        if excluded_count:
            excluded_word = 'line' if excluded_count == 1 else 'lines'
            text += f' · {excluded_count} excluded {excluded_word}'
    return text


def _cover_summary_text(metadata):
    parts = []
    if metadata.get('deceased_name'):
        parts.append(metadata['deceased_name'])
    if metadata.get('date_of_death_display'):
        parts.append(f'DOD {metadata["date_of_death_display"]}')
    if metadata.get('account_date_display'):
        parts.append(f'Account {metadata["account_date_display"]}')
    if metadata.get('inheritance_tax_display'):
        parts.append(f'IHT {metadata["inheritance_tax_display"]}')
    return ' · '.join(parts) if parts else 'Cover details not set'


def _distribution_summary_text(distribution_payments, distributions, totals):
    parts = []
    active_payments = [
        line for line in distribution_payments if not line.get('is_excluded')
    ]
    if active_payments:
        payment_word = 'payment' if len(active_payments) == 1 else 'payments'
        parts.append(
            f'{len(active_payments)} finance {payment_word} · '
            f'{totals["distribution_payments_total_display"]}'
        )
    beneficiary_count = len(distributions)
    if beneficiary_count:
        beneficiary_word = 'beneficiary' if beneficiary_count == 1 else 'beneficiaries'
        parts.append(f'{beneficiary_count} {beneficiary_word}')
    parts.append(f'Total {totals["distribution_total_display"]}')
    return ' · '.join(parts)


def _acknowledgement_summary_text(signers, acknowledgement_text):
    parts = []
    signer_count = len(signers)
    if signer_count:
        client_word = 'client' if signer_count == 1 else 'clients'
        parts.append(f'{signer_count} signing {client_word}')
    text = (acknowledgement_text or '').strip()
    if text:
        preview = text.replace('\n', ' ')
        if len(preview) > 72:
            preview = f'{preview[:69].rstrip()}…'
        parts.append(preview)
    return ' · '.join(parts) if parts else 'Acknowledgement not set'


def _build_section_summaries(
    metadata, assets, debts, distribution_payments, distributions, signers, totals
):
    return {
        'cover': _cover_summary_text(metadata),
        'assets': _lines_summary_text(assets),
        'debts': _lines_summary_text(debts),
        'distribution': _distribution_summary_text(
            distribution_payments, distributions, totals
        ),
        'acknowledgement': _acknowledgement_summary_text(
            signers, metadata.get('acknowledgement_text')
        ),
    }


def _account_metadata(estate_account, matter):
    return {
        'id': estate_account.id,
        'status': estate_account.status,
        'status_display': estate_account.get_status_display(),
        'deceased_name': estate_account.deceased_name,
        'date_of_death': _format_date_iso(estate_account.date_of_death),
        'date_of_death_display': _format_date(estate_account.date_of_death),
        'account_date': _format_date_iso(estate_account.account_date),
        'account_date_display': _format_date(estate_account.account_date),
        'prepared_by_name': estate_account.prepared_by_name,
        'prepared_by_address': estate_account.prepared_by_address,
        'inheritance_tax': str(estate_account.inheritance_tax),
        'inheritance_tax_display': _format_money(estate_account.inheritance_tax),
        'will_clause_text': estate_account.will_clause_text,
        'distribution_notes': estate_account.distribution_notes,
        'acknowledgement_text': estate_account.acknowledgement_text,
        'use_manual_totals': estate_account.use_manual_totals,
        'manual_gross_estate': str(estate_account.manual_gross_estate or ''),
        'manual_total_debts': str(estate_account.manual_total_debts or ''),
        'manual_net_estate': str(estate_account.manual_net_estate or ''),
        'manual_balance_for_distribution': str(
            estate_account.manual_balance_for_distribution or ''
        ),
        'file_number': matter.file_number,
        'is_editable': estate_account.status == EstateAccount.STATUS_INTERIM,
        'finalised_at': estate_account.finalised_at.isoformat() if estate_account.finalised_at else '',
    }


def _compute_totals(estate_account, assets, debts, distributions, distribution_payments=None):
    distribution_payments = distribution_payments or []
    gross = sum(
        _decimal(line['amount']) for line in assets if not line.get('is_excluded')
    )
    total_debts = sum(
        _decimal(line['amount']) for line in debts if not line.get('is_excluded')
    )
    distribution_payments_total = sum(
        _decimal(line['amount'])
        for line in distribution_payments
        if not line.get('is_excluded')
    )
    net_estate = gross - total_debts
    balance_for_distribution = net_estate - _decimal(estate_account.inheritance_tax)
    distribution_total = sum(_decimal(row['net_amount']) for row in distributions)

    if estate_account.use_manual_totals:
        if estate_account.manual_gross_estate is not None:
            gross = _decimal(estate_account.manual_gross_estate)
        if estate_account.manual_total_debts is not None:
            total_debts = _decimal(estate_account.manual_total_debts)
        if estate_account.manual_net_estate is not None:
            net_estate = _decimal(estate_account.manual_net_estate)
        if estate_account.manual_balance_for_distribution is not None:
            balance_for_distribution = _decimal(
                estate_account.manual_balance_for_distribution
            )

    return {
        'gross_estate': str(gross),
        'gross_estate_display': _format_money(gross),
        'total_debts_paid': str(total_debts),
        'total_debts_paid_display': _format_money(total_debts),
        'net_estate': str(net_estate),
        'net_estate_display': _format_money(net_estate),
        'inheritance_tax': str(estate_account.inheritance_tax),
        'inheritance_tax_display': _format_money(estate_account.inheritance_tax),
        'balance_for_distribution': str(balance_for_distribution),
        'balance_for_distribution_display': _format_money(balance_for_distribution),
        'distribution_total': str(distribution_total),
        'distribution_total_display': _format_money(distribution_total),
        'distribution_payments_total': str(distribution_payments_total),
        'distribution_payments_total_display': _format_money(
            distribution_payments_total
        ),
    }


def get_estate_account_data(estate_account, matter, calculate_invoice_total_with_vat):
    if estate_account.status == EstateAccount.STATUS_FINALISED and estate_account.finance_snapshot:
        snapshot = estate_account.finance_snapshot
        if 'summaries' not in snapshot:
            snapshot = {
                **snapshot,
                'summaries': _build_section_summaries(
                    snapshot.get('metadata', {}),
                    snapshot.get('assets', []),
                    snapshot.get('debts', []),
                    snapshot.get('distribution_payments', []),
                    snapshot.get('distributions', []),
                    snapshot.get('signers', []),
                    snapshot.get('totals', {}),
                ),
            }
        return snapshot

    overrides = _override_map(estate_account)
    assets = []
    debts = []
    distribution_payments = []

    for finance_row in _finance_rows_for_matter(matter, calculate_invoice_total_with_vat):
        key = (finance_row['source_type'], finance_row['source_id'])
        override = overrides.get(key)
        is_excluded = bool(override and override.is_excluded)

        section = (
            override.section_override if override and override.section_override
            else finance_row['default_section']
        )
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
        sort_order = override.sort_order if override else 0
        line = {
            'line_kind': 'finance',
            'id': override.id if override else None,
            'override_id': override.id if override else None,
            'source_type': finance_row['source_type'],
            'source_id': finance_row['source_id'],
            'source_label': finance_row.get('source_label', 'Finances'),
            'is_money_out': finance_row.get('is_money_out'),
            'section': section,
            'date': date_value,
            'description': description,
            'amount': amount,
            'is_excluded': is_excluded,
            'is_pending': False,
            'from_finances': True,
            'sort_order': sort_order,
        }
        if section == EstateAccountFinanceLineOverride.SECTION_ASSET:
            assets.append(line)
        elif section == EstateAccountFinanceLineOverride.SECTION_DISTRIBUTION:
            distribution_payments.append(line)
        else:
            debts.append(line)

    for manual in estate_account.manual_entries.all():
        line = {
            'line_kind': 'manual',
            'id': manual.id,
            'override_id': None,
            'source_type': '',
            'source_id': None,
            'section': manual.section,
            'date': manual.date,
            'description': manual.description,
            'amount': manual.amount,
            'is_excluded': False,
            'is_pending': manual.is_pending,
            'from_finances': False,
            'sort_order': manual.sort_order,
        }
        if manual.section == EstateAccountManualEntry.SECTION_ASSET:
            assets.append(line)
        else:
            debts.append(line)

    assets = [_serialize_line(line) for line in sorted(assets, key=_line_sort_key)]
    debts = [_serialize_line(line) for line in sorted(debts, key=_line_sort_key)]
    distribution_payments = [
        _serialize_line(line)
        for line in sorted(distribution_payments, key=_line_sort_key)
    ]

    distributions = [
        _serialize_distribution(row)
        for row in estate_account.distributions.all()
    ]
    signers = _matter_client_signers(matter)
    metadata = _account_metadata(estate_account, matter)
    totals = _compute_totals(
        estate_account, assets, debts, distributions, distribution_payments
    )
    summaries = _build_section_summaries(
        metadata,
        assets,
        debts,
        distribution_payments,
        distributions,
        signers,
        totals,
    )

    return {
        'metadata': metadata,
        'assets': assets,
        'debts': debts,
        'distribution_payments': distribution_payments,
        'distributions': distributions,
        'signers': signers,
        'totals': totals,
        'summaries': summaries,
    }


def build_estate_account_snapshot(estate_account, matter, calculate_invoice_total_with_vat):
    return get_estate_account_data(
        estate_account, matter, calculate_invoice_total_with_vat
    )


def totals_payload(estate_account, matter, calculate_invoice_total_with_vat):
    data = get_estate_account_data(
        estate_account, matter, calculate_invoice_total_with_vat
    )
    return {
        'totals': data['totals'],
        'metadata': {
            'status': data['metadata']['status'],
            'is_editable': data['metadata']['is_editable'],
        },
    }
