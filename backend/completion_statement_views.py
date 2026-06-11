import json
import re
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from weasyprint import HTML

from .completion_statement import (
    build_completion_statement_snapshot,
    get_completion_statement_data,
    get_or_create_completion_statement,
    matter_is_conveyancing,
    sync_all,
    totals_payload,
    validate_for_finalise,
    _decimal,
    _parse_date,
    _serialize_line,
)
from .estate_account import calculate_invoice_total_with_vat
from .models import (
    CompletionStatement,
    CompletionStatementApportionment,
    CompletionStatementFinanceLineOverride,
    CompletionStatementManualEntry,
    CompletionStatementMortgageRedemption,
    CompletionStatementProceedsDistribution,
    CompletionStatementScheduledPayment,
    WIP,
)
from .pmt_slip_service import create_pmt_slip


def _require_conveyancing_matter(file_number):
    matter = get_object_or_404(
        WIP.objects.select_related(
            'matter_type', 'client1', 'fee_earner'
        ).prefetch_related('additional_clients'),
        file_number=file_number,
    )
    if not matter_is_conveyancing(matter):
        raise Http404
    return matter


def _require_editable(completion_statement):
    if completion_statement.status == CompletionStatement.STATUS_FINALISED:
        return JsonResponse({'error': 'Completion statement is finalised.'}, status=403)
    return None


def _json_body(request):
    if request.content_type == 'application/json':
        try:
            return json.loads(request.body.decode() or '{}')
        except json.JSONDecodeError:
            return {}
    return request.POST


def _success_response(completion_statement, matter, extra=None):
    payload = {
        'success': True,
        **totals_payload(completion_statement, matter, calculate_invoice_total_with_vat),
    }
    if extra:
        payload.update(extra)
    return JsonResponse(payload)


@login_required
@require_GET
def completion_statement_view(request, file_number):
    matter = _require_conveyancing_matter(file_number)
    completion_statement = get_or_create_completion_statement(matter, request.user)
    data = get_completion_statement_data(
        completion_statement, matter, calculate_invoice_total_with_vat
    )
    return render(request, 'completion_statement.html', {
        'matter': matter,
        'file_number': file_number,
        'completion_statement': completion_statement,
        'statement_data': data,
        'statement_data_json': json.dumps(data),
    })


@login_required
@require_POST
def completion_statement_update(request, file_number):
    matter = _require_conveyancing_matter(file_number)
    completion_statement = get_or_create_completion_statement(matter, request.user)
    blocked = _require_editable(completion_statement)
    if blocked:
        return blocked

    data = _json_body(request)

    if 'transaction_type' in data and data.get('transaction_type') in {
        CompletionStatement.TRANSACTION_SALE,
        CompletionStatement.TRANSACTION_PURCHASE,
    }:
        completion_statement.transaction_type = data.get('transaction_type')

    if 'completion_monies' in data:
        completion_statement.completion_monies = _decimal(data.get('completion_monies'))

    if 'property_address' in data:
        completion_statement.property_address = data.get('property_address') or ''

    completion_date = data.get('completion_date')
    if completion_date is not None:
        completion_statement.completion_date = _parse_date(completion_date)

    contract_date = data.get('contract_date')
    if contract_date is not None:
        completion_statement.contract_date = _parse_date(contract_date)

    if 'prepared_by_name' in data:
        completion_statement.prepared_by_name = (
            data.get('prepared_by_name') or ''
        ).strip()
    if 'prepared_by_address' in data:
        completion_statement.prepared_by_address = data.get('prepared_by_address') or ''
    if 'notes' in data:
        completion_statement.notes = data.get('notes') or ''
    if 'is_leasehold' in data:
        completion_statement.is_leasehold = str(data.get('is_leasehold')).lower() in {
            '1', 'true', 'on', 'yes'
        }

    completion_statement.save()
    sync_all(completion_statement, matter, request.user, calculate_invoice_total_with_vat)
    return _success_response(completion_statement, matter)


@login_required
@require_GET
def completion_statement_totals(request, file_number):
    matter = _require_conveyancing_matter(file_number)
    completion_statement = get_or_create_completion_statement(matter, request.user)
    return JsonResponse(totals_payload(
        completion_statement, matter, calculate_invoice_total_with_vat
    ))


def _get_or_create_override(completion_statement, source_type, source_id):
    override, _ = CompletionStatementFinanceLineOverride.objects.get_or_create(
        completion_statement=completion_statement,
        source_type=source_type,
        source_id=source_id,
    )
    return override


@login_required
@require_POST
def completion_statement_line_update(request, file_number):
    matter = _require_conveyancing_matter(file_number)
    completion_statement = get_or_create_completion_statement(matter, request.user)
    blocked = _require_editable(completion_statement)
    if blocked:
        return blocked

    data = _json_body(request)
    line_kind = data.get('line_kind')

    if line_kind == 'manual':
        entry = get_object_or_404(
            CompletionStatementManualEntry,
            id=data.get('id'),
            completion_statement=completion_statement,
        )
        if 'date' in data:
            entry.date = _parse_date(data.get('date'))
        if 'description' in data:
            description = (data.get('description') or '').strip()
            if not description:
                return JsonResponse({'error': 'Description is required.'}, status=400)
            entry.description = description
        if 'amount' in data:
            entry.amount = _decimal(data.get('amount'))
        if 'direction' in data and data.get('direction') in {
            CompletionStatementManualEntry.DIRECTION_ADD,
            CompletionStatementManualEntry.DIRECTION_LESS,
        }:
            entry.direction = data.get('direction')
        if 'is_pending' in data:
            entry.is_pending = str(data.get('is_pending')).lower() in {
                '1', 'true', 'on', 'yes'
            }
        if 'sort_order' in data:
            entry.sort_order = int(data.get('sort_order') or 0)
        entry.save()
        line_data = {
            'line_kind': 'manual',
            'id': entry.id,
            **_serialize_line({
                'id': entry.id,
                'direction': entry.direction,
                'date': entry.date,
                'description': entry.description,
                'amount': entry.amount,
                'is_pending': entry.is_pending,
                'from_finances': False,
                'is_pinned': False,
                'is_excluded': False,
                'sort_order': entry.sort_order,
            }),
        }
        return _success_response(completion_statement, matter, {'line': line_data})

    source_type = data.get('source_type')
    source_id = data.get('source_id')
    if not source_type or not source_id:
        return JsonResponse({'error': 'Finance line reference required.'}, status=400)

    override = _get_or_create_override(
        completion_statement, source_type, int(source_id)
    )
    if 'is_excluded' in data:
        override.is_excluded = str(data.get('is_excluded')).lower() in {
            '1', 'true', 'on', 'yes'
        }
    if 'date' in data:
        override.date_override = _parse_date(data.get('date'))
    if 'description' in data:
        override.description_override = (data.get('description') or '').strip()
    if 'amount' in data:
        amount = data.get('amount')
        override.amount_override = (
            _decimal(amount) if amount not in (None, '') else None
        )
    if 'direction' in data and data.get('direction') in {
        CompletionStatementFinanceLineOverride.DIRECTION_ADD,
        CompletionStatementFinanceLineOverride.DIRECTION_LESS,
    }:
        override.direction_override = data.get('direction')
    if 'sort_order' in data:
        override.sort_order = int(data.get('sort_order') or 0)
    override.save()
    return _success_response(completion_statement, matter, {'override_id': override.id})


@login_required
@require_POST
def completion_statement_line_add(request, file_number):
    matter = _require_conveyancing_matter(file_number)
    completion_statement = get_or_create_completion_statement(matter, request.user)
    blocked = _require_editable(completion_statement)
    if blocked:
        return blocked

    data = _json_body(request)
    direction = data.get('direction')
    if direction not in {
        CompletionStatementManualEntry.DIRECTION_ADD,
        CompletionStatementManualEntry.DIRECTION_LESS,
    }:
        direction = CompletionStatementManualEntry.DIRECTION_LESS

    description = (data.get('description') or 'New entry').strip()
    entry = CompletionStatementManualEntry.objects.create(
        completion_statement=completion_statement,
        direction=direction,
        date=_parse_date(data.get('date')) or timezone.localdate(),
        description=description,
        amount=_decimal(data.get('amount')),
        is_pending=str(data.get('is_pending', 'true')).lower() in {
            '1', 'true', 'on', 'yes'
        },
        sort_order=int(data.get('sort_order') or 0),
        created_by=request.user,
    )
    line = {
        'line_kind': 'manual',
        'id': entry.id,
        **_serialize_line({
            'id': entry.id,
            'direction': entry.direction,
            'date': entry.date,
            'description': entry.description,
            'amount': entry.amount,
            'is_pending': entry.is_pending,
            'from_finances': False,
            'is_pinned': False,
            'is_excluded': False,
            'sort_order': entry.sort_order,
        }),
    }
    return _success_response(completion_statement, matter, {'line': line})


@login_required
@require_POST
def completion_statement_line_delete(request, file_number):
    matter = _require_conveyancing_matter(file_number)
    completion_statement = get_or_create_completion_statement(matter, request.user)
    blocked = _require_editable(completion_statement)
    if blocked:
        return blocked

    data = _json_body(request)
    line_kind = data.get('line_kind')

    if line_kind == 'manual':
        entry = get_object_or_404(
            CompletionStatementManualEntry,
            id=data.get('id'),
            completion_statement=completion_statement,
        )
        entry.delete()
        return _success_response(completion_statement, matter)

    source_type = data.get('source_type')
    source_id = data.get('source_id')
    override = _get_or_create_override(
        completion_statement, source_type, int(source_id)
    )
    override.is_excluded = True
    override.save()
    return _success_response(completion_statement, matter)


@login_required
@require_POST
def completion_statement_line_reorder(request, file_number):
    matter = _require_conveyancing_matter(file_number)
    completion_statement = get_or_create_completion_statement(matter, request.user)
    blocked = _require_editable(completion_statement)
    if blocked:
        return blocked

    data = _json_body(request)
    orders = data.get('orders') or []
    if isinstance(orders, str):
        try:
            orders = json.loads(orders)
        except json.JSONDecodeError:
            orders = []

    for index, item in enumerate(orders):
        sort_order = index + 1
        if item.get('line_kind') == 'manual':
            CompletionStatementManualEntry.objects.filter(
                completion_statement=completion_statement,
                id=item.get('id'),
            ).update(sort_order=sort_order)
        else:
            override = _get_or_create_override(
                completion_statement,
                item.get('source_type'),
                int(item.get('source_id')),
            )
            override.sort_order = sort_order
            override.save(update_fields=['sort_order'])

    return _success_response(completion_statement, matter)


@login_required
@require_POST
def completion_statement_status(request, file_number):
    matter = _require_conveyancing_matter(file_number)
    completion_statement = get_or_create_completion_statement(matter, request.user)
    data = _json_body(request)
    action = data.get('action')

    if action == 'finalise':
        sync_all(completion_statement, matter, request.user, calculate_invoice_total_with_vat)
        validation_errors = validate_for_finalise(completion_statement)
        if validation_errors:
            return JsonResponse({'error': ' '.join(validation_errors)}, status=400)
        snapshot = build_completion_statement_snapshot(
            completion_statement, matter, calculate_invoice_total_with_vat
        )
        if not snapshot['totals']['is_balanced']:
            return JsonResponse({
                'error': (
                    'Cannot finalise: statement is not balanced. '
                    f'{snapshot["totals"]["outcome_label"]}'
                ),
            }, status=400)
        completion_statement.finance_snapshot = snapshot
        completion_statement.status = CompletionStatement.STATUS_FINALISED
        completion_statement.finalised_at = timezone.now()
        completion_statement.finalised_by = request.user
        completion_statement.save()
        return JsonResponse({'success': True, 'status': completion_statement.status})

    if action == 'reopen':
        if not request.user.is_manager:
            return JsonResponse({'error': 'Only managers can reopen.'}, status=403)
        completion_statement.status = CompletionStatement.STATUS_DRAFT
        completion_statement.finance_snapshot = None
        completion_statement.finalised_at = None
        completion_statement.finalised_by = None
        completion_statement.save()
        return JsonResponse({'success': True, 'status': completion_statement.status})

    return JsonResponse({'error': 'Invalid action.'}, status=400)


def _slugify_filename(value):
    value = re.sub(r'[^\w\s-]', '', value or '').strip().replace(' ', '_')
    return value[:60] or 'completion_statement'


@login_required
@require_GET
def download_completion_statement(request, file_number):
    matter = _require_conveyancing_matter(file_number)
    completion_statement = get_or_create_completion_statement(matter, request.user)
    data = get_completion_statement_data(
        completion_statement, matter, calculate_invoice_total_with_vat
    )
    html = render_to_string(
        'completion_statement_export.html',
        {'data': data, 'matter': matter},
        request=request,
    )
    pdf_file = HTML(
        string=html, base_url=request.build_absolute_uri('/')
    ).write_pdf()
    completion_date = data['metadata'].get('completion_date_display') or 'draft'
    tx_type = data['metadata'].get('transaction_type', 'sale')
    filename = (
        f'Completion_Statement_{tx_type}_{matter.file_number}_'
        f'{_slugify_filename(data["metadata"]["client_names"])}_'
        f'{completion_date.replace("/", "-")}.pdf'
    )
    response = HttpResponse(pdf_file, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def _sync_and_respond(completion_statement, matter, user, extra=None):
    sync_all(completion_statement, matter, user, calculate_invoice_total_with_vat)
    return _success_response(completion_statement, matter, extra)


@login_required
@require_POST
def completion_statement_mortgage_update(request, file_number):
    matter = _require_conveyancing_matter(file_number)
    completion_statement = get_or_create_completion_statement(matter, request.user)
    blocked = _require_editable(completion_statement)
    if blocked:
        return blocked

    data = _json_body(request)
    redemption, _ = CompletionStatementMortgageRedemption.objects.get_or_create(
        completion_statement=completion_statement,
        defaults={'completion_date': completion_statement.completion_date},
    )

    for field in ('lender_name', 'loan_account_ref'):
        if field in data:
            setattr(redemption, field, (data.get(field) or '').strip())

    if 'redemption_figure' in data:
        redemption.redemption_figure = _decimal(data.get('redemption_figure'))
    if 'daily_interest_amount' in data:
        redemption.daily_interest_amount = _decimal(data.get('daily_interest_amount'))
    if 'redemption_statement_date' in data:
        redemption.redemption_statement_date = _parse_date(data.get('redemption_statement_date'))
    if 'completion_date' in data:
        redemption.completion_date = _parse_date(data.get('completion_date'))
    elif completion_statement.completion_date:
        redemption.completion_date = completion_statement.completion_date

    redemption.save()
    return _sync_and_respond(completion_statement, matter, request.user)


@login_required
@require_POST
def completion_statement_apportionment_add(request, file_number):
    matter = _require_conveyancing_matter(file_number)
    completion_statement = get_or_create_completion_statement(matter, request.user)
    blocked = _require_editable(completion_statement)
    if blocked:
        return blocked

    data = _json_body(request)
    direction = data.get('direction', 'add')
    if direction not in ('add', 'less'):
        direction = 'add'

    row = CompletionStatementApportionment.objects.create(
        completion_statement=completion_statement,
        item_type=data.get('item_type', CompletionStatementApportionment.ITEM_OTHER),
        description=(data.get('description') or 'Apportionment').strip(),
        annual_amount=_decimal(data.get('annual_amount')),
        period_start=_parse_date(data.get('period_start')),
        period_end=_parse_date(data.get('period_end')),
        paid_in_advance=str(data.get('paid_in_advance', 'true')).lower() in {'1', 'true', 'on', 'yes'},
        completion_date=_parse_date(data.get('completion_date')) or completion_statement.completion_date,
        direction=direction,
        sort_order=int(data.get('sort_order') or 0),
    )
    return _sync_and_respond(
        completion_statement, matter, request.user, {'id': row.id}
    )


@login_required
@require_POST
def completion_statement_apportionment_update(request, file_number):
    matter = _require_conveyancing_matter(file_number)
    completion_statement = get_or_create_completion_statement(matter, request.user)
    blocked = _require_editable(completion_statement)
    if blocked:
        return blocked

    data = _json_body(request)
    row = get_object_or_404(
        CompletionStatementApportionment,
        id=data.get('id'),
        completion_statement=completion_statement,
    )

    for field in ('item_type', 'description', 'direction'):
        if field in data:
            setattr(row, field, data.get(field))
    for field in ('annual_amount',):
        if field in data:
            setattr(row, field, _decimal(data.get(field)))
    for field in ('period_start', 'period_end', 'completion_date'):
        if field in data:
            setattr(row, field, _parse_date(data.get(field)))
    if 'paid_in_advance' in data:
        row.paid_in_advance = str(data.get('paid_in_advance')).lower() in {'1', 'true', 'on', 'yes'}
    if 'sort_order' in data:
        row.sort_order = int(data.get('sort_order') or 0)

    row.save()
    return _sync_and_respond(completion_statement, matter, request.user)


@login_required
@require_POST
def completion_statement_apportionment_delete(request, file_number):
    matter = _require_conveyancing_matter(file_number)
    completion_statement = get_or_create_completion_statement(matter, request.user)
    blocked = _require_editable(completion_statement)
    if blocked:
        return blocked

    data = _json_body(request)
    row = get_object_or_404(
        CompletionStatementApportionment,
        id=data.get('id'),
        completion_statement=completion_statement,
    )
    if row.linked_manual_entry_id:
        row.linked_manual_entry.delete()
    CompletionStatementScheduledPayment.objects.filter(
        completion_statement=completion_statement,
        source_kind=CompletionStatementScheduledPayment.SOURCE_APPORTIONMENT,
        source_id=row.id,
    ).delete()
    row.delete()
    return _sync_and_respond(completion_statement, matter, request.user)


@login_required
@require_POST
def completion_statement_distribution_add(request, file_number):
    matter = _require_conveyancing_matter(file_number)
    completion_statement = get_or_create_completion_statement(matter, request.user)
    blocked = _require_editable(completion_statement)
    if blocked:
        return blocked

    data = _json_body(request)
    row = CompletionStatementProceedsDistribution.objects.create(
        completion_statement=completion_statement,
        payee_name=(data.get('payee_name') or 'Payee').strip(),
        reference=(data.get('reference') or '').strip(),
        share_mode=data.get('share_mode', CompletionStatementProceedsDistribution.SHARE_REMAINDER),
        share_value=(data.get('share_value') or '').strip(),
        sort_order=int(data.get('sort_order') or 0),
    )
    return _sync_and_respond(completion_statement, matter, request.user, {'id': row.id})


@login_required
@require_POST
def completion_statement_distribution_update(request, file_number):
    matter = _require_conveyancing_matter(file_number)
    completion_statement = get_or_create_completion_statement(matter, request.user)
    blocked = _require_editable(completion_statement)
    if blocked:
        return blocked

    data = _json_body(request)
    row = get_object_or_404(
        CompletionStatementProceedsDistribution,
        id=data.get('id'),
        completion_statement=completion_statement,
    )
    for field in ('payee_name', 'reference', 'share_mode', 'share_value'):
        if field in data:
            setattr(row, field, (data.get(field) or '').strip())
    if 'sort_order' in data:
        row.sort_order = int(data.get('sort_order') or 0)
    row.save()
    return _sync_and_respond(completion_statement, matter, request.user)


@login_required
@require_POST
def completion_statement_distribution_delete(request, file_number):
    matter = _require_conveyancing_matter(file_number)
    completion_statement = get_or_create_completion_statement(matter, request.user)
    blocked = _require_editable(completion_statement)
    if blocked:
        return blocked

    data = _json_body(request)
    row = get_object_or_404(
        CompletionStatementProceedsDistribution,
        id=data.get('id'),
        completion_statement=completion_statement,
    )
    if row.linked_manual_entry_id:
        row.linked_manual_entry.delete()
    CompletionStatementScheduledPayment.objects.filter(
        completion_statement=completion_statement,
        source_kind=CompletionStatementScheduledPayment.SOURCE_DISTRIBUTION,
        source_id=row.id,
    ).delete()
    row.delete()
    return _sync_and_respond(completion_statement, matter, request.user)


@login_required
@require_POST
def completion_statement_schedule_add(request, file_number):
    matter = _require_conveyancing_matter(file_number)
    completion_statement = get_or_create_completion_statement(matter, request.user)
    blocked = _require_editable(completion_statement)
    if blocked:
        return blocked

    data = _json_body(request)
    direction = data.get('direction', 'less')
    if direction not in ('add', 'less'):
        direction = 'less'
    ledger = data.get('ledger_account', 'C')
    if ledger not in ('C', 'O'):
        ledger = 'C'

    row = CompletionStatementScheduledPayment.objects.create(
        completion_statement=completion_statement,
        payee_name=(data.get('payee_name') or 'Payee').strip(),
        description=(data.get('description') or '').strip(),
        reference=(data.get('reference') or '').strip(),
        direction=direction,
        ledger_account=ledger,
        projected_amount=_decimal(data.get('projected_amount')),
        payment_date=_parse_date(data.get('payment_date')) or timezone.localdate(),
        source_kind=CompletionStatementScheduledPayment.SOURCE_MANUAL,
        source_id=0,
        sort_order=int(data.get('sort_order') or 0),
    )
    row.source_id = row.id
    row.save(update_fields=['source_id'])
    return _success_response(completion_statement, matter, {'id': row.id})


@login_required
@require_POST
def completion_statement_schedule_update(request, file_number):
    matter = _require_conveyancing_matter(file_number)
    completion_statement = get_or_create_completion_statement(matter, request.user)
    blocked = _require_editable(completion_statement)
    if blocked:
        return blocked

    data = _json_body(request)
    row = get_object_or_404(
        CompletionStatementScheduledPayment,
        id=data.get('id'),
        completion_statement=completion_statement,
    )
    if row.status != CompletionStatementScheduledPayment.STATUS_PENDING:
        return JsonResponse({'error': 'Cannot edit after slip created.'}, status=400)

    for field in ('payee_name', 'description', 'reference'):
        if field in data:
            setattr(row, field, (data.get(field) or '').strip())
    if 'direction' in data and data.get('direction') in ('add', 'less'):
        row.direction = data.get('direction')
    if 'ledger_account' in data and data.get('ledger_account') in ('C', 'O'):
        row.ledger_account = data.get('ledger_account')
    if 'projected_amount' in data:
        row.projected_amount = _decimal(data.get('projected_amount'))
    if 'payment_date' in data:
        row.payment_date = _parse_date(data.get('payment_date'))
    if 'sort_order' in data:
        row.sort_order = int(data.get('sort_order') or 0)
    row.save()
    return _success_response(completion_statement, matter)


@login_required
@require_POST
def completion_statement_schedule_delete(request, file_number):
    matter = _require_conveyancing_matter(file_number)
    completion_statement = get_or_create_completion_statement(matter, request.user)
    blocked = _require_editable(completion_statement)
    if blocked:
        return blocked

    data = _json_body(request)
    row = get_object_or_404(
        CompletionStatementScheduledPayment,
        id=data.get('id'),
        completion_statement=completion_statement,
    )
    if row.source_kind != CompletionStatementScheduledPayment.SOURCE_MANUAL:
        return JsonResponse({'error': 'Only manual schedule rows can be deleted.'}, status=400)
    row.delete()
    return _success_response(completion_statement, matter)


@login_required
@require_POST
def completion_statement_schedule_create_slip(request, file_number, schedule_id):
    matter = _require_conveyancing_matter(file_number)
    completion_statement = get_or_create_completion_statement(matter, request.user)
    blocked = _require_editable(completion_statement)
    if blocked:
        return blocked

    row = get_object_or_404(
        CompletionStatementScheduledPayment,
        id=schedule_id,
        completion_statement=completion_statement,
    )
    if row.status != CompletionStatementScheduledPayment.STATUS_PENDING:
        return JsonResponse({'error': 'Slip already created for this payment.'}, status=400)
    if not row.ledger_account:
        return JsonResponse({'error': 'Client or office account is required.'}, status=400)

    data = _json_body(request)
    amount = _decimal(data.get('amount', row.projected_amount))
    ledger_account = data.get('ledger_account', row.ledger_account)
    if ledger_account not in ('C', 'O'):
        ledger_account = row.ledger_account
    payee = (data.get('payee_name') or row.payee_name).strip()
    description = (data.get('description') or row.description or row.payee_name).strip()
    payment_date = _parse_date(data.get('payment_date')) or row.payment_date or timezone.localdate()
    is_money_out = row.direction == 'less'

    try:
        slip = create_pmt_slip(
            matter=matter,
            user=request.user,
            is_money_out=is_money_out,
            ledger_account=ledger_account,
            amount=amount,
            description=description,
            pmt_person=payee,
            date=payment_date,
        )
    except ValueError as exc:
        return JsonResponse({'error': str(exc)}, status=400)

    row.linked_slip = slip
    row.actual_amount = slip.amount
    row.status = CompletionStatementScheduledPayment.STATUS_SLIP_CREATED
    row.ledger_account = ledger_account
    row.save()

    sync_all(completion_statement, matter, request.user, calculate_invoice_total_with_vat)
    return _success_response(
        completion_statement, matter, {'slip_id': slip.id, 'schedule_id': row.id}
    )
