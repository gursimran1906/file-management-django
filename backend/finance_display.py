"""Structured finance activity data for templates (no HTML strings)."""

from decimal import Decimal

from .estate_account import calculate_invoice_total_with_vat
from .models import CURRENT_VAT_RATE
from .utils import parse_invoice_list_field, parse_json_field


def _credit_note_breakdown(gross_amount):
    gross = round(Decimal(str(gross_amount or 0)), 2)
    denominator = Decimal('1.00') + CURRENT_VAT_RATE
    if denominator == 0:
        return gross, Decimal('0.00'), gross
    vat_amount = round((gross * CURRENT_VAT_RATE) / denominator, 2)
    net_amount = round(gross - vat_amount, 2)
    return net_amount, vat_amount, gross


def _slip_invoiced_amount(slip, invoice_id, field_name='amount_invoiced'):
    raw = parse_json_field(getattr(slip, field_name))
    if isinstance(raw, dict):
        data = raw.get(str(invoice_id), {})
        if isinstance(data, dict):
            return Decimal(str(data.get('amt_invoiced', 0) or 0))
        return Decimal(str(data or 0))
    if raw not in (None, '', {}):
        return Decimal(str(slip.amount))
    return Decimal('0')


def compute_invoice_balance_due(invoice, file_number, approved_credit_total):
    """Recalculate amount due / account credit from invoice components."""
    _, _, total_cost_and_vat = calculate_invoice_total_with_vat(invoice)

    total_pink = sum(
        slip.amount for slip in invoice.disbs_ids.all())

    total_blue = Decimal('0')
    for slip in invoice.moa_ids.all():
        total_blue += _slip_invoiced_amount(slip, invoice.id)

    total_green = Decimal('0')
    for slip in invoice.green_slip_ids.all():
        if slip.file_number_from.file_number == file_number:
            total_green -= slip.amount
        else:
            total_green += _slip_invoiced_amount(
                slip, invoice.id, field_name='amount_invoiced_to')

    total_cash = Decimal('0')
    for slip in invoice.cash_allocated_slips.all():
        raw = parse_json_field(slip.amount_allocated)
        amt_str = raw.get(str(invoice.id)) if isinstance(raw, dict) else None
        if amt_str is not None:
            total_cash += Decimal(str(amt_str))

    balance = (
        (total_cost_and_vat + total_pink)
        - total_green
        - (total_blue + total_cash)
        - approved_credit_total
    )
    is_account_credit = balance < 0
    if is_account_credit:
        balance = abs(balance)
    return round(balance, 2), is_account_credit


def build_invoice_finance_detail(
        invoice,
        file_number,
        invoice_credit_notes,
        approved_credit_total,
        status_labels,
        current_vat_rate_percent,
):
    costs = parse_invoice_list_field(invoice.our_costs)
    our_costs_desc = parse_invoice_list_field(invoice.our_costs_desc)

    cost_lines = []
    for i, cost in enumerate(costs):
        cost_lines.append({
            'description': our_costs_desc[i] if i < len(our_costs_desc) else f'Line {i + 1}',
            'amount': round(Decimal(str(cost)), 2),
        })

    costs_ex_vat, vat_amount, total_cost_and_vat = calculate_invoice_total_with_vat(invoice)

    pink_slips = []
    total_pink = Decimal('0')
    for slip in invoice.disbs_ids.all():
        pink_slips.append({
            'person': slip.pmt_person,
            'amount': slip.amount,
            'date': slip.date.strftime('%d/%m/%Y'),
        })
        total_pink += slip.amount

    blue_slips = []
    total_blue = Decimal('0')
    for slip in invoice.moa_ids.all():
        amt = _slip_invoiced_amount(slip, invoice.id)
        blue_slips.append({
            'person': slip.pmt_person,
            'amount': amt,
            'date': slip.date.strftime('%d/%m/%Y'),
        })
        total_blue += amt

    green_slips = []
    total_green = Decimal('0')
    for slip in invoice.green_slip_ids.all():
        if slip.file_number_from.file_number == file_number:
            green_slips.append({
                'direction': 'out',
                'label': f'To {slip.file_number_to}',
                'amount': slip.amount,
                'date': slip.date.strftime('%d/%m/%Y'),
            })
            total_green -= slip.amount
        else:
            amt = _slip_invoiced_amount(
                slip, invoice.id, field_name='amount_invoiced_to')
            green_slips.append({
                'direction': 'in',
                'label': f'From {slip.file_number_from}',
                'amount': amt,
                'date': slip.date.strftime('%d/%m/%Y'),
            })
            total_green += amt

    cash_allocated = []
    total_cash = Decimal('0')
    for slip in invoice.cash_allocated_slips.all():
        raw = parse_json_field(slip.amount_allocated)
        amt_str = raw.get(str(invoice.id)) if isinstance(raw, dict) else None
        if amt_str is None:
            continue
        amt = Decimal(str(amt_str))
        cash_allocated.append({
            'person': slip.pmt_person,
            'amount': amt,
            'date': slip.date.strftime('%d/%m/%Y'),
        })
        total_cash += amt

    credit_note_rows = []
    pending_credit_note_rows = []
    for note in invoice_credit_notes:
        net_amount, vat_amt, gross_amount = _credit_note_breakdown(note.amount)
        row = {
            'id': note.id,
            'date': note.date.strftime('%d/%m/%Y'),
            'net_amount': net_amount,
            'vat_amount': vat_amt,
            'gross_amount': gross_amount,
            'status': note.status,
            'status_display': status_labels.get(note.status, note.status),
            'approved_by': str(note.approved_by) if note.approved_by else None,
            'approved_on': note.approved_on.strftime('%d/%m/%Y %H:%M') if note.approved_on else None,
        }
        if note.status == 'F':
            credit_note_rows.append(row)
        elif note.status == 'P':
            pending_credit_note_rows.append(row)

    balance = (total_cost_and_vat + total_pink) - total_green - (total_blue + total_cash) - approved_credit_total
    is_account_credit = balance < 0
    if is_account_credit:
        balance = abs(balance)

    return {
        'cost_lines': cost_lines,
        'costs_ex_vat': costs_ex_vat,
        'vat_amount': vat_amount,
        'total_cost_and_vat': total_cost_and_vat,
        'vat_rate_percent': current_vat_rate_percent,
        'pink_slips': pink_slips,
        'pink_total': total_pink,
        'blue_slips': blue_slips,
        'blue_total': total_blue,
        'green_slips': green_slips,
        'green_total': total_green,
        'cash_allocated': cash_allocated,
        'cash_allocated_total': total_cash,
        'credit_notes': credit_note_rows,
        'pending_credit_notes': pending_credit_note_rows,
        'credit_notes_total': round(approved_credit_total, 2),
        'balance_due': round(balance, 2),
        'is_account_credit': is_account_credit,
    }
