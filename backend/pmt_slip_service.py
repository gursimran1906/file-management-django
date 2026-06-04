from .forms import PmtsForm
from .models import PmtsSlips


def create_pmt_slip(
    *,
    matter,
    user,
    is_money_out,
    ledger_account,
    amount,
    description,
    pmt_person,
    date,
    mode_of_pmt='BT',
):
    """
    Create a payment slip (pink or blue) on the matter.

    ledger_account: 'C' (Client) or 'O' (Office)
    """
    data = {
        'file_number': matter.id,
        'ledger_account': ledger_account,
        'mode_of_pmt': mode_of_pmt,
        'amount': amount,
        'is_money_out': is_money_out,
        'pmt_person': pmt_person,
        'description': description,
        'date': date,
        'balance_left': amount,
        'created_by': user,
    }
    form = PmtsForm(data)
    if not form.is_valid():
        raise ValueError(form.errors.as_json())
    return form.save()
