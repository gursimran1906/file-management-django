import json
import re
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from weasyprint import HTML

from .estate_account import (
    build_estate_account_snapshot,
    calculate_invoice_total_with_vat,
    get_estate_account_data,
    get_or_create_estate_account,
    matter_is_probate,
    totals_payload,
    _decimal,
    _parse_date,
    _serialize_distribution,
    _serialize_line,
    _serialize_signer,
)
from .models import (
    EstateAccount,
    EstateAccountDistribution,
    EstateAccountFinanceLineOverride,
    EstateAccountManualEntry,
    EstateAccountSigner,
    WIP,
)


def _require_probate_matter(file_number):
    matter = get_object_or_404(
        WIP.objects.select_related(
            'matter_type', 'client1', 'fee_earner', 'authorised_party1'
        ).prefetch_related('additional_clients'),
        file_number=file_number,
    )
    if not matter_is_probate(matter):
        raise Http404
    return matter


def _require_editable(estate_account):
    if estate_account.status == EstateAccount.STATUS_FINALISED:
        return JsonResponse({'error': 'Estate account is finalised.'}, status=403)
    return None


def _json_body(request):
    if request.content_type == 'application/json':
        try:
            return json.loads(request.body.decode() or '{}')
        except json.JSONDecodeError:
            return {}
    return request.POST


def _success_response(estate_account, matter, extra=None):
    payload = {
        'success': True,
        **totals_payload(estate_account, matter, calculate_invoice_total_with_vat),
    }
    if extra:
        payload.update(extra)
    return JsonResponse(payload)


@login_required
@require_GET
def estate_account_view(request, file_number):
    matter = _require_probate_matter(file_number)
    estate_account = get_or_create_estate_account(matter, request.user)
    data = get_estate_account_data(
        estate_account, matter, calculate_invoice_total_with_vat
    )
    return render(request, 'estate_account.html', {
        'matter': matter,
        'file_number': file_number,
        'estate_account': estate_account,
        'account_data': data,
        'account_data_json': json.dumps(data),
    })


@login_required
@require_POST
def estate_account_update(request, file_number):
    matter = _require_probate_matter(file_number)
    estate_account = get_or_create_estate_account(matter, request.user)
    blocked = _require_editable(estate_account)
    if blocked:
        return blocked

    data = _json_body(request)
    deceased_name = (data.get('deceased_name') or '').strip()
    if deceased_name:
        estate_account.deceased_name = deceased_name

    date_of_death = data.get('date_of_death')
    if date_of_death is not None:
        estate_account.date_of_death = _parse_date(date_of_death)

    account_date = data.get('account_date')
    if account_date is not None:
        estate_account.account_date = _parse_date(account_date)

    if 'prepared_by_name' in data:
        estate_account.prepared_by_name = (data.get('prepared_by_name') or '').strip()
    if 'prepared_by_address' in data:
        estate_account.prepared_by_address = data.get('prepared_by_address') or ''
    if 'will_clause_text' in data:
        estate_account.will_clause_text = data.get('will_clause_text') or ''
    if 'distribution_notes' in data:
        estate_account.distribution_notes = data.get('distribution_notes') or ''
    if 'acknowledgement_text' in data:
        estate_account.acknowledgement_text = data.get('acknowledgement_text') or ''

    if 'inheritance_tax' in data:
        estate_account.inheritance_tax = _decimal(data.get('inheritance_tax'))

    if 'use_manual_totals' in data:
        estate_account.use_manual_totals = str(
            data.get('use_manual_totals')
        ).lower() in {'1', 'true', 'on', 'yes'}

    for field in (
        'manual_gross_estate',
        'manual_total_debts',
        'manual_net_estate',
        'manual_balance_for_distribution',
    ):
        if field in data:
            value = data.get(field)
            setattr(
                estate_account,
                field,
                _decimal(value) if value not in (None, '') else None,
            )

    estate_account.save()
    return _success_response(estate_account, matter)


@login_required
@require_GET
def estate_account_totals(request, file_number):
    matter = _require_probate_matter(file_number)
    estate_account = get_or_create_estate_account(matter, request.user)
    return JsonResponse(totals_payload(
        estate_account, matter, calculate_invoice_total_with_vat
    ))


def _get_or_create_override(estate_account, source_type, source_id):
    override, _ = EstateAccountFinanceLineOverride.objects.get_or_create(
        estate_account=estate_account,
        source_type=source_type,
        source_id=source_id,
    )
    return override


@login_required
@require_POST
def estate_account_line_update(request, file_number):
    matter = _require_probate_matter(file_number)
    estate_account = get_or_create_estate_account(matter, request.user)
    blocked = _require_editable(estate_account)
    if blocked:
        return blocked

    data = _json_body(request)
    line_kind = data.get('line_kind')

    if line_kind == 'manual':
        entry = get_object_or_404(
            EstateAccountManualEntry,
            id=data.get('id'),
            estate_account=estate_account,
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
                'section': entry.section,
                'date': entry.date,
                'description': entry.description,
                'amount': entry.amount,
                'is_pending': entry.is_pending,
                'from_finances': False,
                'sort_order': entry.sort_order,
            }),
        }
        return _success_response(estate_account, matter, {'line': line_data})

    source_type = data.get('source_type')
    source_id = data.get('source_id')
    if not source_type or not source_id:
        return JsonResponse({'error': 'Finance line reference required.'}, status=400)

    override = _get_or_create_override(
        estate_account, source_type, int(source_id)
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
        override.amount_override = _decimal(amount) if amount not in (None, '') else None
    if 'section' in data and data.get('section') in {
        EstateAccountFinanceLineOverride.SECTION_ASSET,
        EstateAccountFinanceLineOverride.SECTION_DEBT,
        EstateAccountFinanceLineOverride.SECTION_DISTRIBUTION,
    }:
        override.section_override = data.get('section')
    if 'sort_order' in data:
        override.sort_order = int(data.get('sort_order') or 0)
    override.save()
    return _success_response(estate_account, matter, {'override_id': override.id})


@login_required
@require_POST
def estate_account_line_add(request, file_number):
    matter = _require_probate_matter(file_number)
    estate_account = get_or_create_estate_account(matter, request.user)
    blocked = _require_editable(estate_account)
    if blocked:
        return blocked

    data = _json_body(request)
    section = data.get('section')
    if section not in {
        EstateAccountManualEntry.SECTION_ASSET,
        EstateAccountManualEntry.SECTION_DEBT,
    }:
        return JsonResponse({'error': 'Invalid section.'}, status=400)

    description = (data.get('description') or 'New entry').strip()
    entry = EstateAccountManualEntry.objects.create(
        estate_account=estate_account,
        section=section,
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
            'section': entry.section,
            'date': entry.date,
            'description': entry.description,
            'amount': entry.amount,
            'is_pending': entry.is_pending,
            'from_finances': False,
            'sort_order': entry.sort_order,
        }),
    }
    return _success_response(estate_account, matter, {'line': line})


@login_required
@require_POST
def estate_account_line_delete(request, file_number):
    matter = _require_probate_matter(file_number)
    estate_account = get_or_create_estate_account(matter, request.user)
    blocked = _require_editable(estate_account)
    if blocked:
        return blocked

    data = _json_body(request)
    line_kind = data.get('line_kind')

    if line_kind == 'manual':
        entry = get_object_or_404(
            EstateAccountManualEntry,
            id=data.get('id'),
            estate_account=estate_account,
        )
        entry.delete()
        return _success_response(estate_account, matter)

    source_type = data.get('source_type')
    source_id = data.get('source_id')
    override = _get_or_create_override(
        estate_account, source_type, int(source_id)
    )
    override.is_excluded = True
    override.save()
    return _success_response(estate_account, matter)


@login_required
@require_POST
def estate_account_line_reorder(request, file_number):
    matter = _require_probate_matter(file_number)
    estate_account = get_or_create_estate_account(matter, request.user)
    blocked = _require_editable(estate_account)
    if blocked:
        return blocked

    data = _json_body(request)
    section = data.get('section')
    orders = data.get('orders') or []
    if isinstance(orders, str):
        try:
            orders = json.loads(orders)
        except json.JSONDecodeError:
            orders = []

    for index, item in enumerate(orders):
        sort_order = index + 1
        if item.get('line_kind') == 'manual':
            EstateAccountManualEntry.objects.filter(
                estate_account=estate_account,
                id=item.get('id'),
                section=section,
            ).update(sort_order=sort_order)
        else:
            override = _get_or_create_override(
                estate_account,
                item.get('source_type'),
                int(item.get('source_id')),
            )
            override.sort_order = sort_order
            override.save(update_fields=['sort_order'])

    return _success_response(estate_account, matter)


@login_required
@require_POST
def estate_account_distribution_update(request, file_number):
    matter = _require_probate_matter(file_number)
    estate_account = get_or_create_estate_account(matter, request.user)
    blocked = _require_editable(estate_account)
    if blocked:
        return blocked

    data = _json_body(request)
    row = get_object_or_404(
        EstateAccountDistribution,
        id=data.get('id'),
        estate_account=estate_account,
    )
    if 'beneficiary_name' in data:
        name = (data.get('beneficiary_name') or '').strip()
        if not name:
            return JsonResponse({'error': 'Beneficiary name is required.'}, status=400)
        row.beneficiary_name = name
    if 'share_fraction' in data:
        row.share_fraction = data.get('share_fraction') or ''
    if 'gross_amount' in data:
        row.gross_amount = _decimal(data.get('gross_amount'))
    if 'adjustment_description' in data:
        row.adjustment_description = data.get('adjustment_description') or ''
    if 'adjustment_amount' in data:
        amount = data.get('adjustment_amount')
        row.adjustment_amount = _decimal(amount) if amount not in (None, '') else None
    if 'sort_order' in data:
        row.sort_order = int(data.get('sort_order') or 0)
    row.save()
    return _success_response(
        estate_account, matter, {'distribution': _serialize_distribution(row)}
    )


@login_required
@require_POST
def estate_account_distribution_add(request, file_number):
    matter = _require_probate_matter(file_number)
    estate_account = get_or_create_estate_account(matter, request.user)
    blocked = _require_editable(estate_account)
    if blocked:
        return blocked

    data = _json_body(request)
    row = EstateAccountDistribution.objects.create(
        estate_account=estate_account,
        beneficiary_name=(data.get('beneficiary_name') or 'Beneficiary').strip(),
        share_fraction=data.get('share_fraction') or '',
        gross_amount=_decimal(data.get('gross_amount')),
        adjustment_description=data.get('adjustment_description') or '',
        adjustment_amount=(
            _decimal(data.get('adjustment_amount'))
            if data.get('adjustment_amount') not in (None, '') else None
        ),
        net_amount=Decimal('0'),
        sort_order=int(data.get('sort_order') or 0),
        created_by=request.user,
    )
    return _success_response(
        estate_account, matter, {'distribution': _serialize_distribution(row)}
    )


@login_required
@require_POST
def estate_account_distribution_delete(request, file_number):
    matter = _require_probate_matter(file_number)
    estate_account = get_or_create_estate_account(matter, request.user)
    blocked = _require_editable(estate_account)
    if blocked:
        return blocked

    data = _json_body(request)
    row = get_object_or_404(
        EstateAccountDistribution,
        id=data.get('id'),
        estate_account=estate_account,
    )
    row.delete()
    return _success_response(estate_account, matter)


@login_required
@require_POST
def estate_account_signer_update(request, file_number):
    matter = _require_probate_matter(file_number)
    estate_account = get_or_create_estate_account(matter, request.user)
    blocked = _require_editable(estate_account)
    if blocked:
        return blocked

    data = _json_body(request)
    row = get_object_or_404(
        EstateAccountSigner,
        id=data.get('id'),
        estate_account=estate_account,
    )
    if 'signer_name' in data:
        row.signer_name = (data.get('signer_name') or '').strip()
    if 'signer_address' in data:
        row.signer_address = data.get('signer_address') or ''
    if 'sort_order' in data:
        row.sort_order = int(data.get('sort_order') or 0)
    row.save()
    return _success_response(
        estate_account, matter, {'signer': _serialize_signer(row)}
    )


@login_required
@require_POST
def estate_account_signer_add(request, file_number):
    matter = _require_probate_matter(file_number)
    estate_account = get_or_create_estate_account(matter, request.user)
    blocked = _require_editable(estate_account)
    if blocked:
        return blocked

    data = _json_body(request)
    row = EstateAccountSigner.objects.create(
        estate_account=estate_account,
        signer_name=(data.get('signer_name') or 'Signer').strip(),
        signer_address=data.get('signer_address') or '',
        sort_order=int(data.get('sort_order') or 0),
    )
    return _success_response(
        estate_account, matter, {'signer': _serialize_signer(row)}
    )


@login_required
@require_POST
def estate_account_signer_delete(request, file_number):
    matter = _require_probate_matter(file_number)
    estate_account = get_or_create_estate_account(matter, request.user)
    blocked = _require_editable(estate_account)
    if blocked:
        return blocked

    data = _json_body(request)
    row = get_object_or_404(
        EstateAccountSigner,
        id=data.get('id'),
        estate_account=estate_account,
    )
    row.delete()
    return _success_response(estate_account, matter)


@login_required
@require_POST
def estate_account_status(request, file_number):
    matter = _require_probate_matter(file_number)
    estate_account = get_or_create_estate_account(matter, request.user)
    data = _json_body(request)
    action = data.get('action')

    if action == 'finalise':
        snapshot = build_estate_account_snapshot(
            estate_account, matter, calculate_invoice_total_with_vat
        )
        estate_account.finance_snapshot = snapshot
        estate_account.status = EstateAccount.STATUS_FINALISED
        estate_account.finalised_at = timezone.now()
        estate_account.finalised_by = request.user
        estate_account.save()
        return JsonResponse({'success': True, 'status': estate_account.status})

    if action == 'reopen':
        if not request.user.is_manager:
            return JsonResponse({'error': 'Only managers can reopen.'}, status=403)
        estate_account.status = EstateAccount.STATUS_INTERIM
        estate_account.finance_snapshot = None
        estate_account.finalised_at = None
        estate_account.finalised_by = None
        estate_account.save()
        return JsonResponse({'success': True, 'status': estate_account.status})

    return JsonResponse({'error': 'Invalid action.'}, status=400)


def _slugify_filename(value):
    value = re.sub(r'[^\w\s-]', '', value or '').strip().replace(' ', '_')
    return value[:60] or 'estate_account'


@login_required
@require_GET
def download_estate_account(request, file_number):
    matter = _require_probate_matter(file_number)
    estate_account = get_or_create_estate_account(matter, request.user)
    data = get_estate_account_data(
        estate_account, matter, calculate_invoice_total_with_vat
    )
    html = render_to_string(
        'estate_account_export.html',
        {'data': data, 'matter': matter},
        request=request,
    )
    pdf_file = HTML(
        string=html, base_url=request.build_absolute_uri('/')
    ).write_pdf()
    account_date = data['metadata'].get('account_date_display') or 'draft'
    filename = (
        f'Estate_and_Distribution_Account_{matter.file_number}_'
        f'{_slugify_filename(data["metadata"]["deceased_name"])}_{account_date.replace("/", "-")}.pdf'
    )
    response = HttpResponse(pdf_file, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
@require_GET
def download_estate_accounts_redirect(request, file_number):
    return redirect('download_estate_account', file_number=file_number)
