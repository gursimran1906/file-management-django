from .models import MatterEmails, WIP
from users.models import CustomUser
from django.db import connection
from django.contrib.contenttypes.models import ContentType
from .models import Modifications
import json
import os
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation


def insert_data(file_number, sender, receiver, description, subject, body, link, is_sent, rcvd_time, units, fee_earner_code):
    try:
        if file_number != None:
            file = WIP.objects.filter(file_number=file_number).first()
        else:
           file =  None
        
        user = CustomUser.objects.filter(id=fee_earner_code).first()
        email = MatterEmails(
            file_number=file ,
            sender=sender,
            receiver=receiver,
            description=description,
            subject=subject,
            body=body,
            link=link,
            is_sent=is_sent,
            time=rcvd_time,
            units=units,
            fee_earner=user
        )
        
        # Save the object to the database
        email.save()
        try:
            from .time_events import sync_time_event_from_email
            sync_time_event_from_email(email)
        except Exception:
            pass

        print("Data inserted successfully")

    except Exception as e:
        
        print(f"Error in inserting: {e}")
        print('in email','sender: '+sender , 'receiver: '+receiver, rcvd_time)



 
def create_modification(user, modified_obj, changes=None):
    """
    Utility method to create a modification instance.
    
    Args:
        user (CustomUser): The user who made the modification.
        modified_obj (Model): The object being modified.
        changes (dict): Optional. Changes made to the object (default is None).
        
    Returns:
        Modifications: The created Modifications instance.
    """
    content_type = ContentType.objects.get_for_model(modified_obj)
    
    modification = Modifications.objects.create(
        modified_by=user,
        content_type=content_type,
        object_id=modified_obj.pk,
        modified_obj=modified_obj,
        changes=changes
    )
    
    return modification


def parse_bundle_filename(filename):
    """Extract description and date from a PDF filename.

    Supported prefixes (date then description):
    - YYYY-MM-DD Letter to client.pdf
    - YYYYMMDD Letter to client.pdf
    - DD-MM-YYYY or DD.MM.YYYY Letter to client.pdf
    Separator after the date may be a space, hyphen, or underscore.
    """
    basename = os.path.splitext(os.path.basename(filename))[0]
    patterns = (
        (r'^(\d{4})-(\d{2})-(\d{2})[\s_-]+(.+)$', lambda m: (m.group(1), m.group(2), m.group(3), m.group(4))),
        (r'^(\d{4})(\d{2})(\d{2})[\s_-]+(.+)$', lambda m: (m.group(1), m.group(2), m.group(3), m.group(4))),
        (r'^(\d{2})[-.](\d{2})[-.](\d{4})[\s_-]+(.+)$', lambda m: (m.group(3), m.group(2), m.group(1), m.group(4))),
    )
    for pattern, extract in patterns:
        match = re.match(pattern, basename, re.IGNORECASE)
        if not match:
            continue
        year, month, day, description = extract(match)
        try:
            doc_date = datetime(int(year), int(month), int(day)).date()
        except ValueError:
            continue
        return description.replace('_', ' ').strip(), doc_date

    return basename.replace('_', ' ').strip(), None


def parse_json_field(value):
    """Normalise a JSONField value that may be dict, str, bytes, or empty."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        if not value or value == '{}':
            return {}
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return value
        return parsed
    if isinstance(value, (bytes, bytearray)):
        return parse_json_field(value.decode('utf-8'))
    if value in (None, ''):
        return {}
    return value


def _invoice_label(invoice):
    if invoice is None:
        return None
    if invoice.invoice_number is not None:
        return f'Invoice #{invoice.invoice_number}'
    return f'Invoice (draft, id {invoice.id})'


def _lookup_invoice(invoice_id):
    from .models import Invoices
    try:
        return Invoices.objects.filter(id=int(invoice_id)).first()
    except (TypeError, ValueError):
        return None


def get_pmt_slip_committed_amount(slip):
    """Amount of this slip already invoiced or allocated (derived from balance)."""
    return round(Decimal(str(slip.amount)) - Decimal(str(slip.balance_left)), 2)


def get_pmt_slip_allocated_total(slip):
    raw = parse_json_field(slip.amount_allocated)
    if not isinstance(raw, dict):
        return Decimal('0')
    total = Decimal('0')
    for amount in raw.values():
        try:
            total += Decimal(str(amount))
        except (InvalidOperation, TypeError):
            continue
    return round(total, 2)


def _invoice_is_final(invoice):
    return invoice is not None and invoice.state == 'F'


def _invoice_usage_row(invoice, invoice_id, amount):
    return {
        'invoice_id': invoice_id,
        'invoice_label': _invoice_label(invoice) or f'Invoice id {invoice_id}',
        'amount': amount,
        'invoice_state': invoice.state if invoice else None,
        'is_final': _invoice_is_final(invoice),
    }


def pmt_slip_has_invoiced_usage(slip):
    """True when any portion of this slip has been applied to an invoice."""
    raw = parse_json_field(slip.amount_invoiced)
    if isinstance(raw, dict) and raw:
        return True
    if raw not in (None, '', {}):
        return True
    return slip.disbs_invoices.exists() or slip.moa_invoices.exists()


def pmt_slip_linked_final_invoices(slip):
    """Final invoices this slip is invoiced on or allocated to."""
    final_invoices = []
    seen = set()

    raw_invoiced = parse_json_field(slip.amount_invoiced)
    if isinstance(raw_invoiced, dict):
        invoice_ids = raw_invoiced.keys()
    elif raw_invoiced not in (None, '', {}):
        invoice_ids = [
            inv.id for inv in
            list(slip.disbs_invoices.all()) + list(slip.moa_invoices.all())
        ]
    else:
        invoice_ids = []

    for invoice_id in invoice_ids:
        invoice = _lookup_invoice(invoice_id)
        if _invoice_is_final(invoice) and invoice.id not in seen:
            seen.add(invoice.id)
            final_invoices.append(invoice)

    raw_allocated = parse_json_field(slip.amount_allocated)
    if isinstance(raw_allocated, dict):
        for invoice_id in raw_allocated:
            invoice = _lookup_invoice(invoice_id)
            if _invoice_is_final(invoice) and invoice.id not in seen:
                seen.add(invoice.id)
                final_invoices.append(invoice)

    return final_invoices


def green_slip_linked_final_invoices(slip):
    final_invoices = []
    seen = set()

    def add_invoice(invoice_id):
        invoice = _lookup_invoice(invoice_id)
        if _invoice_is_final(invoice) and invoice.id not in seen:
            seen.add(invoice.id)
            final_invoices.append(invoice)

    raw_from = parse_json_field(slip.amount_invoiced_from)
    if isinstance(raw_from, dict):
        for invoice_id in raw_from:
            add_invoice(invoice_id)
    elif raw_from not in (None, '', {}):
        for invoice in slip.green_slips_invoices.filter(
                file_number=slip.file_number_from):
            add_invoice(invoice.id)

    raw_to = parse_json_field(slip.amount_invoiced_to)
    if isinstance(raw_to, dict):
        for invoice_id in raw_to:
            add_invoice(invoice_id)

    return final_invoices


def pmt_slip_has_partial_invoice_usage(slip):
    """True when amount_invoiced tracks per-invoice usage (blue slips, partial)."""
    raw = parse_json_field(slip.amount_invoiced)
    return isinstance(raw, dict) and bool(raw)


def green_slip_has_usage(slip):
    committed_from = round(
        Decimal(str(slip.amount)) - Decimal(str(slip.balance_left_from)), 2)
    committed_to = round(
        Decimal(str(slip.amount)) - Decimal(str(slip.balance_left_to)), 2)
    return committed_from > 0 or committed_to > 0


def validate_pmt_slip_amount_change(slip, new_amount):
    """
    Validate a payment slip amount change.

    Returns (new_balance_left, error_message). error_message is None on success.
    """
    new_amount = round(Decimal(str(new_amount)), 2)
    old_amount = round(Decimal(str(slip.amount)), 2)
    if new_amount == old_amount:
        return round(Decimal(str(slip.balance_left)), 2), None

    if new_amount <= 0:
        return None, 'Amount must be greater than 0.'

    if pmt_slip_has_partial_invoice_usage(slip):
        final_invoices = pmt_slip_linked_final_invoices(slip)
        if final_invoices:
            numbers = ', '.join(
                f'#{inv.invoice_number}' for inv in final_invoices if inv.invoice_number)
            return None, (
                'Amount cannot be changed while this slip is partially used on '
                f'a final invoice ({numbers or "see usage below"}). '
                'Edit the invoice to adjust how much is applied.'
            )
        return None, (
            'Amount cannot be changed while this slip is partially used on an invoice. '
            'Edit the invoice to adjust how much of this slip is applied.'
        )

    final_invoices = pmt_slip_linked_final_invoices(slip)
    if pmt_slip_has_invoiced_usage(slip) and final_invoices:
        numbers = ', '.join(
            f'#{inv.invoice_number}' for inv in final_invoices if inv.invoice_number)
        return None, (
            'Amount cannot be changed — this slip is invoiced on '
            f'a final invoice ({numbers or "see usage below"}). '
            'Edit the invoice to change usage, or raise a credit note to adjust the balance.'
        )

    committed = get_pmt_slip_committed_amount(slip)
    allocated_total = get_pmt_slip_allocated_total(slip)

    if allocated_total > 0:
        new_balance = round(new_amount - allocated_total, 2)
        if new_balance < 0:
            return None, (
                f'Amount cannot be less than £{allocated_total:.2f} '
                'already allocated to invoices.'
            )
        return new_balance, None

    new_balance = round(new_amount - committed, 2)
    if new_balance < 0:
        return None, (
            f'Amount cannot be less than £{committed:.2f} '
            'already invoiced or allocated.'
        )
    return new_balance, None


def validate_green_slip_amount_change(slip, new_amount):
    """Validate a green slip amount change. Returns (balances_dict, error_message)."""
    new_amount = round(Decimal(str(new_amount)), 2)
    old_amount = round(Decimal(str(slip.amount)), 2)
    if new_amount == old_amount:
        return {
            'balance_left_from': round(Decimal(str(slip.balance_left_from)), 2),
            'balance_left_to': round(Decimal(str(slip.balance_left_to)), 2),
        }, None

    if new_amount <= 0:
        return None, 'Amount must be greater than 0.'

    if green_slip_has_usage(slip):
        final_invoices = green_slip_linked_final_invoices(slip)
        if final_invoices:
            numbers = ', '.join(
                f'#{inv.invoice_number}' for inv in final_invoices if inv.invoice_number)
            return None, (
                'Amount cannot be changed — this transfer is linked to '
                f'a final invoice ({numbers or "see usage below"}). '
                'Edit the invoice to change usage.'
            )
        return None, (
            'Amount cannot be changed while this transfer is linked to a draft invoice. '
            'Edit the invoice to adjust how much of this transfer is applied.'
        )

    return {
        'balance_left_from': new_amount,
        'balance_left_to': new_amount,
    }, None


def validate_green_slip_file_change(slip, file_number_from, file_number_to):
    """Return an error message if file numbers cannot be changed, else None."""
    if not green_slip_has_usage(slip):
        return None
    if (file_number_from != slip.file_number_from_id
            or file_number_to != slip.file_number_to_id):
        final_invoices = green_slip_linked_final_invoices(slip)
        if final_invoices:
            return (
                'Source or destination file cannot be changed while this transfer '
                'is linked to a final invoice.'
            )
        return (
            'Source or destination file cannot be changed while this transfer '
            'is linked to an invoice.'
        )
    return None


def get_pmt_slip_amount_edit_status(slip):
    """Whether amount is editable on the slip edit form, and why not."""
    final_invoices = pmt_slip_linked_final_invoices(slip)
    final_numbers = ', '.join(
        f'#{inv.invoice_number}' for inv in final_invoices if inv.invoice_number)

    if pmt_slip_has_partial_invoice_usage(slip):
        if final_invoices:
            return False, (
                'Amount is locked — this slip is partially used on '
                f'a final invoice ({final_numbers or "see usage below"}). '
                'Edit the invoice to change how much is applied.'
            )
        return False, (
            'Amount is locked because this slip is partially used on a draft invoice. '
            'Edit the invoice to change how much is applied.'
        )

    if pmt_slip_has_invoiced_usage(slip) and final_invoices:
        return False, (
            'Amount is locked — this slip is invoiced on '
            f'a final invoice ({final_numbers or "see usage below"}). '
            'Edit the invoice or raise a credit note to adjust amounts.'
        )

    committed = get_pmt_slip_committed_amount(slip)
    allocated_total = get_pmt_slip_allocated_total(slip)
    if allocated_total > 0:
        note = (
            f'Amount can be changed, but not below £{allocated_total:.2f} '
            'already allocated to invoices.'
        )
        if final_invoices:
            note += (
                f' Cash is allocated to final invoice(s) ({final_numbers}).'
            )
        return True, note

    if committed > 0:
        return True, (
            f'Amount can be increased but not below £{committed:.2f} '
            'already invoiced on a draft invoice.'
        )
    return True, None


def get_green_slip_amount_edit_status(slip):
    final_invoices = green_slip_linked_final_invoices(slip)
    final_numbers = ', '.join(
        f'#{inv.invoice_number}' for inv in final_invoices if inv.invoice_number)

    if green_slip_has_usage(slip):
        if final_invoices:
            return False, (
                'Amount is locked — this transfer is linked to '
                f'a final invoice ({final_numbers or "see usage below"}). '
                'Edit the invoice to change usage.'
            )
        return False, (
            'Amount is locked because this transfer is linked to a draft invoice. '
            'Edit the invoice to change how much is applied.'
        )
    return True, None


def get_pmt_slip_usage_summary(slip):
    """Human-readable breakdown of how a payment slip has been used."""
    invoiced = []
    allocated = []

    raw_invoiced = parse_json_field(slip.amount_invoiced)
    if isinstance(raw_invoiced, dict):
        for invoice_id, data in raw_invoiced.items():
            invoice = _lookup_invoice(invoice_id)
            if isinstance(data, dict):
                amount = data.get('amt_invoiced', 0)
            else:
                amount = data
            invoiced.append(_invoice_usage_row(
                invoice, invoice_id, Decimal(str(amount))))
    elif raw_invoiced not in (None, '', {}):
        amount = Decimal(str(raw_invoiced))
        linked = list(slip.disbs_invoices.all()) + list(slip.moa_invoices.all())
        if linked:
            for invoice in linked:
                invoiced.append(_invoice_usage_row(invoice, invoice.id, amount))
        elif amount:
            invoiced.append(_invoice_usage_row(None, None, amount) | {
                'invoice_label': 'Invoiced (invoice link not found)',
            })

    raw_allocated = parse_json_field(slip.amount_allocated)
    if isinstance(raw_allocated, dict):
        for invoice_id, amount in raw_allocated.items():
            invoice = _lookup_invoice(invoice_id)
            try:
                amt = Decimal(str(amount))
            except (InvalidOperation, TypeError):
                continue
            if amt:
                allocated.append(_invoice_usage_row(
                    invoice, invoice_id, amt))

    committed = get_pmt_slip_committed_amount(slip)
    final_invoices = pmt_slip_linked_final_invoices(slip)
    amount_editable, amount_edit_note = get_pmt_slip_amount_edit_status(slip)
    return {
        'invoiced': invoiced,
        'allocated': allocated,
        'balance_left': slip.balance_left,
        'committed': committed,
        'has_usage': bool(invoiced or allocated),
        'has_final_invoice': bool(final_invoices),
        'amount_editable': amount_editable,
        'amount_edit_note': amount_edit_note,
        'slip_amount': slip.amount,
    }


def get_green_slip_usage_summary(slip):
    """Human-readable breakdown of how a green slip has been used on each side."""
    from_usages = []
    to_usages = []

    raw_from = parse_json_field(slip.amount_invoiced_from)
    if isinstance(raw_from, dict):
        for invoice_id, data in raw_from.items():
            invoice = _lookup_invoice(invoice_id)
            amount = data.get('amt_invoiced', 0) if isinstance(data, dict) else data
            from_usages.append(_invoice_usage_row(
                invoice, invoice_id, Decimal(str(amount))))
    elif raw_from not in (None, '', {}):
        amount = Decimal(str(raw_from))
        for invoice in slip.green_slips_invoices.filter(
                file_number=slip.file_number_from):
            from_usages.append(_invoice_usage_row(invoice, invoice.id, amount))

    raw_to = parse_json_field(slip.amount_invoiced_to)
    if isinstance(raw_to, dict):
        for invoice_id, data in raw_to.items():
            invoice = _lookup_invoice(invoice_id)
            amount = data.get('amt_invoiced', 0) if isinstance(data, dict) else data
            to_usages.append(_invoice_usage_row(
                invoice, invoice_id, Decimal(str(amount))))

    committed_from = round(
        Decimal(str(slip.amount)) - Decimal(str(slip.balance_left_from)), 2)
    committed_to = round(
        Decimal(str(slip.amount)) - Decimal(str(slip.balance_left_to)), 2)
    final_invoices = green_slip_linked_final_invoices(slip)
    amount_editable, amount_edit_note = get_green_slip_amount_edit_status(slip)
    return {
        'from_usages': from_usages,
        'to_usages': to_usages,
        'balance_left_from': slip.balance_left_from,
        'balance_left_to': slip.balance_left_to,
        'committed_from': committed_from,
        'committed_to': committed_to,
        'has_usage': bool(from_usages or to_usages),
        'has_final_invoice': bool(final_invoices),
        'amount_editable': amount_editable,
        'amount_edit_note': amount_edit_note,
        'slip_amount': slip.amount,
        'file_number_from': (
            slip.file_number_from.file_number if slip.file_number_from_id else ''
        ),
        'file_number_to': (
            slip.file_number_to.file_number if slip.file_number_to_id else ''
        ),
    }

       
