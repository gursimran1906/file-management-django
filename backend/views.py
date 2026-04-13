import logging
import html
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.db import transaction
from django.db.models import Q, F, OuterRef, Subquery, Max, CharField, TextField, BooleanField, Exists, Count, Sum, Case, When, Value, DateField
from django.db.models.functions import Cast, Coalesce, Greatest, Concat
from .models import WIP, Memo, NextWork, LastWork, FileStatus, FileLocation, MatterType, ClientContactDetails, AuthorisedParties
from .models import LedgerAccountTransfers, Modifications, Invoices, RiskAssessment, PoliciesRead, OngoingMonitoring, CreditNote, CURRENT_VAT_RATE
from .models import OthersideDetails, MatterAttendanceNotes, MatterEmails, MatterLetters, PmtsSlips, Free30Mins, Free30MinsAttendees
from .models import Undertaking, Policy, PolicyVersion, Bundle, BundleSection, BundleDocument, MatterFileReview
from .forms import MemoForm, OpenFileForm, NextWorkFormWithoutFileNumber, NextWorkForm, LastWorkFormWithoutFileNumber, LastWorkForm, AttendanceNoteForm, AttendanceNoteFormHalf, LetterForm, LetterHalfForm, PolicyForm
from .forms import PmtsForm, PmtsHalfForm, LedgerAccountTransfersHalfForm, LedgerAccountTransfersForm, InvoicesForm, CreditNoteHalfForm, ClientForm, AuthorisedPartyForm, RiskAssessmentForm, OngoingMonitoringForm, OtherSideForm
from .forms import Free30MinsForm, Free30MinsAttendeesForm, UndertakingForm, MatterFileReviewForm
from .utils import create_modification
from django.utils import timezone
from users.models import CPDTrainingLog, CustomUser, HolidayRecord
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST
import json
from weasyprint import HTML
from django.utils.safestring import mark_safe
from django.contrib.contenttypes.models import ContentType
import csv
from datetime import date, datetime, timedelta, time
from dateutil.relativedelta import relativedelta
import copy
from django.forms.models import model_to_dict
from decimal import Decimal
import ast
from .serializers import InvoicesSerializer
from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT
from docx.enum.table import WD_TABLE_ALIGNMENT
import io
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.conf import settings
import os
import PyPDF2
import zipfile
from io import BytesIO
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile

logger = logging.getLogger('backend')
CURRENT_VAT_RATE_PERCENT = int(CURRENT_VAT_RATE * 100)

MATTER_FILE_REVIEW_SECTIONS = [
    {
        'title': 'Client Onboarding',
        'rows': [
            {
                'question': 'File Opening Checklist completed?',
                'answer_field': 'file_opening_checklist_completed',
                'comments_field': 'file_opening_checklist_completed_comments',
            },
            {
                'question': 'Engagement documents sent to the client and copies kept on file?',
                'bullets': [
                    'Client care letter',
                    'Terms of business (including complaints procedure and cancellation procedure)',
                    'Non-contentious Business Agreement (if applicable)',
                    'PEP',
                    'SOF',
                ],
                'answer_field': 'engagement_documents_sent_and_filed',
                'comments_field': 'engagement_documents_sent_and_filed_comments',
            },
            {
                'question': 'Accurate and up-to-date details of our charging rates and basis provided?',
                'answer_field': 'charging_rates_and_basis_provided',
                'comments_field': 'charging_rates_and_basis_provided_comments',
            },
            {
                'question': 'Initial estimate of costs provided?',
                'answer_field': 'initial_costs_estimate_provided',
                'comments_field': 'initial_costs_estimate_provided_comments',
            },
            {
                'question': "Signed Letter of Authority obtained to enable us to receive advice and instructions on the client's behalf (if applicable)?",
                'answer_field': 'letter_of_authority_obtained',
                'comments_field': 'letter_of_authority_obtained_comments',
            },
            {
                'question': 'Initial Risk Assessment completed?',
                'answer_field': 'initial_risk_assessment_completed',
                'comments_field': 'initial_risk_assessment_completed_comments',
            },
        ],
    },
    {
        'title': 'Matter Management',
        'rows': [
            {
                'question': 'All key dates recorded in shared calendar and WIP?',
                'answer_field': 'key_dates_recorded_in_calendar_and_wip',
                'comments_field': 'key_dates_recorded_in_calendar_and_wip_comments',
            },
            {
                'question': 'Key information and advice shared with the client?',
                'answer_field': 'key_information_and_advice_shared',
                'comments_field': 'key_information_and_advice_shared_comments',
            },
            {
                'question': 'Costs estimates updated as necessary?',
                'answer_field': 'costs_estimates_updated',
                'comments_field': 'costs_estimates_updated_comments',
            },
            {
                'question': 'Overall, the matter is progressing without any long unexplained periods of dormancy?',
                'answer_field': 'matter_progressing_without_dormancy',
                'comments_field': 'matter_progressing_without_dormancy_comments',
            },
            {
                'question': 'Overall, the file appears to be maintained in good order?',
                'answer_field': 'file_maintained_in_good_order',
                'comments_field': 'file_maintained_in_good_order_comments',
            },
        ],
    },
    {
        'title': 'Ongoing Monitoring',
        'rows': [
            {
                'question': 'Ongoing AML, financial crime prevention and sanctions monitoring carried out at appropriate intervals or on appropriate triggers (if applicable)?',
                'answer_field': 'ongoing_aml_sanctions_monitoring_carried_out',
                'comments_field': 'ongoing_aml_sanctions_monitoring_carried_out_comments',
            },
            {
                'question': 'Copies of all documents obtained from ongoing monitoring activities kept and correctly filed?',
                'answer_field': 'ongoing_monitoring_documents_kept_and_filed',
                'comments_field': 'ongoing_monitoring_documents_kept_and_filed_comments',
            },
            {
                'question': 'Further conflict checks and consideration carried out appropriately, if parties have changed?',
                'answer_field': 'further_conflict_checks_completed',
                'comments_field': 'further_conflict_checks_completed_comments',
            },
        ],
    },
    {
        'title': 'Finance, Costs And Accounting',
        'rows': [
            {
                'question': 'Money on account (as appropriate to the matter) has been requested at appropriate times and received before significant work undertaken?',
                'answer_field': 'money_on_account_requested_and_received',
                'comments_field': 'money_on_account_requested_and_received_comments',
            },
            {
                'question': 'All disbursements paid in a timely manner?',
                'answer_field': 'disbursements_paid_timely',
                'comments_field': 'disbursements_paid_timely_comments',
            },
            {
                'question': 'Costs and disbursements billed at appropriate intervals?',
                'answer_field': 'costs_and_disbursements_billed_timely',
                'comments_field': 'costs_and_disbursements_billed_timely_comments',
            },
            {
                'question': 'Overdue invoices?',
                'answer_field': 'overdue_invoices',
                'comments_field': 'overdue_invoices_comments',
            },
        ],
    },
    {
        'title': 'Legal Advice And Instructions',
        'rows': [
            {
                'question': 'Appropriate advice given to the client on all substantive issues to date?',
                'answer_field': 'appropriate_advice_given',
                'comments_field': 'appropriate_advice_given_comments',
            },
            {
                'question': 'Matter proceeding within the scope set out in the client care letter? If not, why?',
                'answer_field': 'matter_within_client_care_scope',
                'comments_field': 'matter_within_client_care_scope_comments',
            },
        ],
    },
    {
        'title': 'Specific Risk Issues',
        'rows': [
            {
                'question': 'Undertakings given by the firm have been discharged appropriately and on time, or released in writing (if not ongoing)?',
                'answer_field': 'undertakings_discharged_or_released',
                'comments_field': 'undertakings_discharged_or_released_comments',
            },
            {
                'question': 'Have any complaints been raised by the client? If so, has the firms complaints procedure been followed?',
                'answer_field': 'complaints_raised_and_process_followed',
                'comments_field': 'complaints_raised_and_process_followed_comments',
            },
            {
                'question': 'Does the file review raise any internal concerns?',
                'answer_field': 'internal_concerns_raised',
                'comments_field': 'internal_concerns_raised_comments',
            },
            {
                'question': 'Does the file review raise any concerns or suspicions about potential money laundering, sanctions breaches, or any other economic crime?',
                'answer_field': 'economic_crime_or_sanctions_concerns',
                'comments_field': 'economic_crime_or_sanctions_concerns_comments',
            },
        ],
    },
]


def build_matter_file_review_display_data(reviews):
    output = []
    for review in reviews:
        section_data = []
        for section in MATTER_FILE_REVIEW_SECTIONS:
            rows = []
            for row in section['rows']:
                rows.append({
                    'question': row['question'],
                    'bullets': row.get('bullets', []),
                    'answer': getattr(review, row['answer_field']) or '---',
                    'comments': getattr(review, row['comments_field']) or '---',
                })
            section_data.append({
                'title': section['title'],
                'rows': rows,
            })
        output.append({
            'review': review,
            'sections': section_data,
        })
    return output


def calculate_invoice_total_with_vat(invoice):
    our_costs = invoice.our_costs
    costs = ast.literal_eval(our_costs) if not isinstance(our_costs, list) else our_costs
    total_cost_invoice = Decimal('0')
    for cost in costs:
        total_cost_invoice += Decimal(str(cost))
    vat_inv = Decimal(str(invoice.vat or 0))
    total_cost_and_vat = total_cost_invoice + vat_inv
    return round(total_cost_invoice, 2), round(vat_inv, 2), round(total_cost_and_vat, 2)


def calculate_credit_note_breakdown(gross_amount):
    gross = round(Decimal(str(gross_amount or 0)), 2)
    denominator = Decimal('1.00') + CURRENT_VAT_RATE
    if denominator == 0:
        return gross, Decimal('0.00'), gross

    vat_amount = round((gross * CURRENT_VAT_RATE) / denominator, 2)
    net_amount = round(gross - vat_amount, 2)
    return net_amount, vat_amount, gross


def get_approved_credit_note_totals(invoice_ids):
    totals = {}
    if not invoice_ids:
        return totals

    rows = CreditNote.objects.filter(
        invoice_id__in=invoice_ids,
        status='F'
    ).values('invoice_id').annotate(total=Sum('amount'))
    for row in rows:
        totals[row['invoice_id']] = row['total'] or Decimal('0')
    return totals


def get_invoice_approved_credit_total(invoice):
    return CreditNote.objects.filter(
        invoice=invoice,
        status='F'
    ).aggregate(total=Sum('amount')).get('total') or Decimal('0')


def get_invoice_max_credit_amount(invoice, excluded_credit_note_id=None):
    max_allowed = Decimal(str(invoice.total_due_left or 0))
    if excluded_credit_note_id:
        excluded_note = CreditNote.objects.filter(
            id=excluded_credit_note_id,
            status='F',
            invoice=invoice
        ).first()
        if excluded_note:
            max_allowed += Decimal(str(excluded_note.amount))
    if max_allowed < 0:
        return Decimal('0')
    return round(max_allowed, 2)


def get_effective_invoice_due(invoice, approved_credit_total=None):
    effective_due = Decimal(str(invoice.total_due_left or 0))
    if effective_due <= 0:
        return Decimal('0')
    return round(effective_due, 2)


def get_user_dashboard_wips(user):
    next_work_wips = NextWork.objects.filter(
        person=user,
        completed=False
    ).values_list('file_number', flat=True)
    last_work_wips = LastWork.objects.filter(
        person=user
    ).values_list('file_number', flat=True)

    fee_earner_files = WIP.objects.filter(
        fee_earner=user,
        file_status__status='Open'
    )

    combined_wip_ids = set(next_work_wips).union(set(last_work_wips))
    return (WIP.objects.filter(id__in=combined_wip_ids) | fee_earner_files).distinct()


def get_risk_assessments_due_queryset(wip_queryset):
    one_year_ago = timezone.localdate() - relativedelta(years=1)

    latest_assessment_subquery = RiskAssessment.objects.filter(
        matter=OuterRef('pk')
    ).order_by('-due_diligence_date').values('due_diligence_date')[:1]

    latest_monitoring_subquery = OngoingMonitoring.objects.filter(
        file_number=OuterRef('pk')
    ).order_by('-date_due_diligence_conducted').values('date_due_diligence_conducted')[:1]

    return wip_queryset.annotate(
        latest_assessment_date=Subquery(latest_assessment_subquery),
        latest_monitoring_date=Subquery(latest_monitoring_subquery)
    ).filter(
        Q(file_status__status__in=['Open', 'To Be Closed']) &
        (
            Q(latest_assessment_date__isnull=True) |
            (
                Q(latest_assessment_date__lte=one_year_ago) &
                (
                    Q(latest_monitoring_date__isnull=True) |
                    Q(latest_monitoring_date__lte=one_year_ago)
                )
            )
        )
    ).order_by('file_number')


def get_file_reviews_due_queryset(wip_queryset):
    one_year_ago = timezone.localdate() - relativedelta(years=1)

    latest_review_subquery = MatterFileReview.objects.filter(
        matter=OuterRef('pk')
    ).order_by('-date_review_completed').values('date_review_completed')[:1]

    latest_review_by_subquery = MatterFileReview.objects.filter(
        matter=OuterRef('pk')
    ).order_by('-date_review_completed').values('file_review_completed_by__first_name')[:1]

    return wip_queryset.annotate(
        latest_review_date=Subquery(latest_review_subquery),
        latest_review_by=Subquery(latest_review_by_subquery),
    ).filter(
        Q(file_status__status__in=['Open', 'To Be Closed']) &
        (
            Q(latest_review_date__isnull=True) |
            Q(latest_review_date__lte=one_year_ago)
        )
    ).order_by('file_number')


def get_dashboard_risk_scope_wips(user, risk_scope):
    if risk_scope == 'all_active':
        return WIP.objects.filter(
            file_status__status__in=['Open', 'To Be Closed']
        ).distinct(), 'all_active'

    associated_wips = get_user_dashboard_wips(user).filter(
        file_status__status__in=['Open', 'To Be Closed']
    ).distinct()
    return associated_wips, 'associated'


@login_required
def display_data_index_page(request):
    if 'valToSearch' in request.POST:
        search_by = request.POST.get('searchBy', 'FileNumber')
        val_to_search = request.POST.get('valToSearch', '')
        show_archived = 'showArchived' in request.POST

        data = get_index_search_data(
            search_by=search_by,
            val_to_search=val_to_search,
            show_archived=show_archived
        )

        context = {
            'search_by': search_by,
            'val_to_search': val_to_search,
            'show_archived': show_archived,
            'data': data,
        }

        return render(request, 'index.html', context)

    return render(request, 'index.html')


@login_required
def download_search_report(request):
    if 'valToSearch' in request.POST:
        search_by = request.POST.get('searchBy', 'FileNumber')
        val_to_search = request.POST.get('valToSearch', '')
        show_archived = 'showArchived' in request.POST

        data = get_index_search_data(
            search_by=search_by,
            val_to_search=val_to_search,
            show_archived=show_archived
        )

        context = {
            'search_by': search_by,
            'val_to_search': val_to_search,
            'show_archived': show_archived,
            'data': data,
            'user': request.user
        }

        html_string = render_to_string(
            'download_templates/search_report.html', context)

        pdf_file = HTML(string=html_string).write_pdf()

        response = HttpResponse(pdf_file, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="search_report_{search_by}+{val_to_search}.pdf"'
        return response


def get_index_search_filter(search_by, val_to_search, show_archived):
    file_status_field_name = 'file_status__status'

    if show_archived:
        file_status_list = ['Open', 'Archived']
        filter_factor = Q(**{f"{file_status_field_name}__in": file_status_list})
    elif search_by == 'ToBeClosed':
        filter_factor = Q(**{file_status_field_name: 'To Be Closed'})
    else:
        filter_factor = Q(**{file_status_field_name: 'Open'})

    if search_by == 'ClientName':
        filter_factor &= Q(client1__name__icontains=val_to_search) | Q(
            client2__name__icontains=val_to_search
        )
    elif search_by == 'FeeEarner':
        if val_to_search == "DC":
            filter_factor &= Q(fee_earner=None)
        else:
            filter_factor &= Q(fee_earner__username__icontains=val_to_search)
    else:
        filter_factor &= Q(file_number__icontains=val_to_search)

    return filter_factor


def get_index_search_data(search_by, val_to_search, show_archived):
    filter_factor = get_index_search_filter(search_by, val_to_search, show_archived)

    last_work_subquery = LastWork.objects.filter(
        file_number=OuterRef('pk')
    ).order_by('-timestamp')

    latest_email_subquery = MatterEmails.objects.filter(
        file_number=OuterRef('pk')
    ).annotate(
        email_activity_date=Coalesce(
            Cast('time', output_field=DateField()),
            Cast('timestamp', output_field=DateField())
        ),
        email_activity_desc=Coalesce(
            'description',
            'subject',
            Value('Email activity', output_field=TextField()),
            output_field=TextField()
        )
    ).order_by('-email_activity_date', '-timestamp')

    latest_attendance_subquery = MatterAttendanceNotes.objects.filter(
        file_number=OuterRef('pk'),
        date__isnull=False
    ).order_by('-date', '-timestamp')

    fallback_date = date(1900, 1, 1)

    data = WIP.objects.filter(filter_factor).annotate(
        latest_work_task_raw=Subquery(last_work_subquery.values('task')[:1], output_field=TextField()),
        latest_work_person_raw=Subquery(last_work_subquery.values('person__username')[:1]),
        latest_work_entry_date=Subquery(last_work_subquery.values('date')[:1], output_field=DateField()),
        latest_email_task_raw=Subquery(latest_email_subquery.values('email_activity_desc')[:1], output_field=TextField()),
        latest_email_person_raw=Subquery(latest_email_subquery.values('fee_earner__username')[:1]),
        latest_email_date=Subquery(latest_email_subquery.values('email_activity_date')[:1], output_field=DateField()),
        latest_attendance_task_raw=Subquery(latest_attendance_subquery.values('subject_line')[:1], output_field=TextField()),
        latest_attendance_is_charged_raw=Subquery(latest_attendance_subquery.values('is_charged')[:1], output_field=BooleanField()),
        latest_attendance_person_raw=Subquery(latest_attendance_subquery.values('person_attended__username')[:1]),
        latest_attendance_note_date=Subquery(latest_attendance_subquery.values('date')[:1], output_field=DateField())
    ).annotate(
        work_date_for_compare=Coalesce('latest_work_entry_date', Value(fallback_date, output_field=DateField())),
        email_date_for_compare=Coalesce('latest_email_date', Value(fallback_date, output_field=DateField())),
        attendance_date_for_compare=Coalesce('latest_attendance_note_date', Value(fallback_date, output_field=DateField()))
    ).annotate(
        latest_last_work_date=Case(
            When(
                latest_work_entry_date__isnull=True,
                latest_email_date__isnull=True,
                latest_attendance_note_date__isnull=True,
                then=Value(None, output_field=DateField())
            ),
            default=Greatest(
                'work_date_for_compare',
                'email_date_for_compare',
                'attendance_date_for_compare'
            ),
            output_field=DateField()
        ),
        latest_activity_source=Case(
            When(
                latest_work_entry_date__isnull=True,
                latest_email_date__isnull=True,
                latest_attendance_note_date__isnull=True,
                then=Value('none')
            ),
            When(
                Q(work_date_for_compare__gte=F('email_date_for_compare')) &
                Q(work_date_for_compare__gte=F('attendance_date_for_compare')),
                then=Value('work')
            ),
            When(
                email_date_for_compare__gte=F('attendance_date_for_compare'),
                then=Value('email')
            ),
            default=Value('attendance'),
            output_field=CharField()
        )
    ).annotate(
        latest_last_work_task=Case(
            When(
                latest_activity_source='work',
                then=Coalesce('latest_work_task_raw', Value('Work activity', output_field=TextField()), output_field=TextField())
            ),
            When(
                latest_activity_source='email',
                then=Coalesce('latest_email_task_raw', Value('Email activity', output_field=TextField()), output_field=TextField())
            ),
            When(
                latest_activity_source='attendance',
                then=Case(
                    When(
                        latest_attendance_is_charged_raw=False,
                        then=Concat(
                            Coalesce('latest_attendance_task_raw', Value('Attendance note', output_field=TextField()), output_field=TextField()),
                            Value(' (N/C)', output_field=TextField()),
                            output_field=TextField()
                        )
                    ),
                    default=Coalesce('latest_attendance_task_raw', Value('Attendance note', output_field=TextField()), output_field=TextField()),
                    output_field=TextField()
                )
            ),
            default=Value(None, output_field=TextField()),
            output_field=TextField()
        ),
        latest_last_work_person=Case(
            When(latest_activity_source='work', then=Coalesce('latest_work_person_raw', Value('-'))),
            When(latest_activity_source='email', then=Coalesce('latest_email_person_raw', Value('-'))),
            When(latest_activity_source='attendance', then=Coalesce('latest_attendance_person_raw', Value('-'))),
            default=Value(None, output_field=CharField()),
            output_field=CharField()
        )
    ).values(
        'file_number',
        'fee_earner__username',
        'matter_description',
        'client1__name',
        'client2__name',
        'comments',
        'latest_last_work_date',
        'latest_last_work_person',
        'latest_last_work_task',
    ).order_by('file_number')

    return data


@login_required
def user_dashboard(request):
    user = CustomUser.objects.get(username=request.user)
    risk_scope = request.GET.get('risk_scope', 'associated')
    user_next_works = NextWork.objects.filter(
        Q(person=user) & Q(completed=False)).order_by('date')
    user_last_works = LastWork.objects.filter(person=user).order_by('-date')

    # Check if user has pending tasks (for cookie logic)
    has_pending_tasks = NextWork.objects.filter(
        person=user,
        status__in=['to_do', 'in_progress']
    ).exists()
    # Check if user is manager and show pending holiday requests
    if user.is_manager:
        pending_holiday_requests = HolidayRecord.objects.filter(
            approved=False,
            checked_by__isnull=True
        ).count()

        if pending_holiday_requests > 0:
            if pending_holiday_requests == 1:
                messages.info(
                    request, f'You have {pending_holiday_requests} holiday request pending your approval.')
            else:
                messages.info(
                    request, f'You have {pending_holiday_requests} holiday requests pending your approval.')

    now = timezone.now()
    unique_wips = get_user_dashboard_wips(user)
    risk_scope_wips, validated_risk_scope = get_dashboard_risk_scope_wips(
        user, risk_scope
    )
    risk_assessments_due = get_risk_assessments_due_queryset(risk_scope_wips)
    file_reviews_due = get_file_reviews_due_queryset(unique_wips)

    # Calculate the date 11 months ago
    eleven_months_ago = timezone.now() - relativedelta(months=11)

    aml_checks_due_client1 = unique_wips.filter(
        Q(file_status__status='Open') &
        Q(client1__date_of_last_aml__lte=eleven_months_ago) &
        Q(fee_earner=user)
    ).annotate(
        client_id=F('client1__id'),
        client_name=F('client1__name'),
        date_of_last_aml=F('client1__date_of_last_aml')
    ).values('client_id', 'client_name', 'date_of_last_aml')

    # Filter WIPs where AML checks are due for client2
    aml_checks_due_client2 = unique_wips.filter(
        Q(file_status__status='Open') &
        Q(client2__date_of_last_aml__lte=eleven_months_ago) &
        Q(fee_earner=user)
    ).annotate(
        client_id=F('client2__id'),
        client_name=F('client2__name'),
        date_of_last_aml=F('client2__date_of_last_aml')
    ).values('client_id', 'client_name', 'date_of_last_aml')

    # Fetch the results from the database
    client1_results = list(aml_checks_due_client1)
    client2_results = list(aml_checks_due_client2)

    # Combine and ensure uniqueness
    unique_clients = {}
    for result in client1_results + client2_results:
        unique_clients[result['client_id']] = {
            'client_name': result['client_name'],
            'date_of_last_aml': result['date_of_last_aml']
        }

    # Convert the dictionary back to a list of dictionaries
    unique_aml_checks_due = [
        {'client_id': client_id,
            'client_name': data['client_name'], 'date_of_last_aml': data['date_of_last_aml']}
        for client_id, data in unique_clients.items()
    ]
    unique_aml_checks_due = sorted(
        unique_aml_checks_due, key=lambda x: x['date_of_last_aml'])
    # Filter for unsettled invoices
    last_100_emails = MatterEmails.objects.filter(
        fee_earner=user).order_by('-time')[:100]

    unsettled_invoice_candidates = Invoices.objects.filter(
        file_number__in=unique_wips,
        state='F'
    ).order_by('invoice_number')
    approved_credit_totals = get_approved_credit_note_totals(
        [invoice.id for invoice in unsettled_invoice_candidates]
    )
    unsettled_invoices = []
    for invoice in unsettled_invoice_candidates:
        effective_due = get_effective_invoice_due(
            invoice, approved_credit_totals.get(invoice.id, Decimal('0')))
        invoice.effective_total_due_left = effective_due
        if effective_due > 0:
            unsettled_invoices.append(invoice)

    latest_version_subquery = PolicyVersion.objects.filter(
        policy=OuterRef('pk')
    ).order_by('-version_number').values('pk')[:1]

    unread_policies_exist = Policy.objects.annotate(
        latest_version_id=Subquery(latest_version_subquery),
        is_read=Exists(
            PoliciesRead.objects.filter(
                policy=OuterRef('pk'),
                policy_version_id=OuterRef('latest_version_id'),
                read_by=user
            )
        )
    ).filter(is_read=False).exists()

    context = {
        'now': now,
        'user_next_works': user_next_works,
        'user_last_works': user_last_works,
        'risk_assessments_due_files': risk_assessments_due,
        'aml_checks_due': unique_aml_checks_due,
        'unsettled_invoices': unsettled_invoices,
        'last_100_emails': last_100_emails,
        'files': unique_wips,
        'unread_policies_exist': unread_policies_exist,
        'has_pending_tasks': has_pending_tasks,
        'risk_scope': validated_risk_scope,
        'file_reviews_due_files': file_reviews_due,
    }

    return render(request, 'dashboard.html', context)


@login_required
@require_POST
def update_task_status(request):
    """Update task status via AJAX"""
    try:
        data = json.loads(request.body)
        task_id = data.get('task_id')
        new_status = data.get('status')

        if not task_id or not new_status:
            return JsonResponse({
                'success': False,
                'error': 'Missing task_id or status'
            })

        # Allow both the assigned person and the creator to update the task
        task = get_object_or_404(NextWork, Q(id=task_id) & (
            Q(person=request.user) | Q(created_by=request.user)))
        task.status = new_status
        task.save()

        return JsonResponse({'success': True})

    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


@login_required
@require_POST
def load_initial_tasks(request):
    """Load initial tasks for all statuses via AJAX"""
    try:
        data = json.loads(request.body)
        count = data.get('count', 5)  # Default to 5 tasks per status
        filter_created_by_me = data.get('filter_created_by_me', False)

        # Handle "all" case - when count is "all", we don't limit the queryset
        show_all = count == 'all'

        task_data = {}
        total_counts = {}

        # Base query filters
        base_filter_nextwork = {'created_by': request.user} if filter_created_by_me else {
            'person': request.user}
        base_filter_lastwork = {'created_by': request.user} if filter_created_by_me else {
            'person': request.user}

        # Load To Do tasks with smart ordering (urgency priority, then due date)
        to_do_tasks = NextWork.objects.filter(
            **base_filter_nextwork,
            status='to_do'
        ).select_related('person', 'created_by', 'file_number').extra(
            select={
                'urgency_order': "CASE urgency WHEN 'urgent' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 WHEN 'low' THEN 4 ELSE 5 END"
            }
        ).order_by('urgency_order', 'date')

        total_counts['to_do'] = to_do_tasks.count()
        to_do_limited = to_do_tasks if show_all else to_do_tasks[:count]

        task_data['to_do'] = []
        for task in to_do_limited:
            task_data['to_do'].append({
                'id': task.id,
                'file_number': task.file_number.file_number if task.file_number else '',
                'task': task.task[:80] + '...' if task.task and len(task.task) > 80 else task.task,
                'date': task.date.isoformat() if task.date else None,
                'timestamp': task.timestamp.isoformat(),
                'urgency': task.urgency,
                'assigned_to': task.person.get_full_name() if task.person else 'Unassigned',
                'created_by': task.created_by.get_full_name() if task.created_by else 'Unknown',
                'is_created_by_me': task.created_by == request.user if task.created_by else False,
            })

        # Load In Progress tasks with smart ordering (urgency priority, then due date)
        in_progress_tasks = NextWork.objects.filter(
            **base_filter_nextwork,
            status='in_progress'
        ).select_related('person', 'created_by', 'file_number').extra(
            select={
                'urgency_order': "CASE urgency WHEN 'urgent' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 WHEN 'low' THEN 4 ELSE 5 END"
            }
        ).order_by('urgency_order', 'date')

        total_counts['in_progress'] = in_progress_tasks.count()
        in_progress_limited = in_progress_tasks if show_all else in_progress_tasks[:count]

        task_data['in_progress'] = []
        for task in in_progress_limited:
            task_data['in_progress'].append({
                'id': task.id,
                'file_number': task.file_number.file_number if task.file_number else '',
                'task': task.task[:80] + '...' if task.task and len(task.task) > 80 else task.task,
                'date': task.date.isoformat() if task.date else None,
                'timestamp': task.timestamp.isoformat(),
                'urgency': task.urgency,
                'assigned_to': task.person.get_full_name() if task.person else 'Unassigned',
                'created_by': task.created_by.get_full_name() if task.created_by else 'Unknown',
                'is_created_by_me': task.created_by == request.user if task.created_by else False,
            })

        # Load Completed tasks (last 7 days)
        completed_tasks = LastWork.objects.filter(
            **base_filter_lastwork,
            timestamp__gte=timezone.now() - timezone.timedelta(days=7)
        ).select_related('person', 'created_by', 'file_number').order_by('-timestamp')

        total_counts['completed'] = completed_tasks.count()
        completed_limited = completed_tasks if show_all else completed_tasks[:count]

        task_data['completed'] = []
        for task in completed_limited:
            task_data['completed'].append({
                'id': task.id,
                'file_number': task.file_number.file_number if task.file_number else '',
                'task': task.task[:80] + '...' if task.task and len(task.task) > 80 else task.task,
                'date': task.date.isoformat() if task.date else None,
                'timestamp': task.timestamp.isoformat(),
                'assigned_to': task.person.get_full_name() if task.person else 'Unassigned',
                'created_by': task.created_by.get_full_name() if task.created_by else 'Unknown',
                'is_created_by_me': task.created_by == request.user if task.created_by else False,
            })

        return JsonResponse({
            'success': True,
            'tasks': task_data,
            'total_counts': total_counts,
            'loaded_count': count,
            'filter_applied': filter_created_by_me
        })

    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


@login_required
@require_POST
def load_more_tasks(request):
    """Load more tasks for a specific status via AJAX"""
    try:
        data = json.loads(request.body)
        status = data.get('status')
        offset = data.get('offset', 0)
        count = data.get('count', 3)
        filter_created_by_me = data.get('filter_created_by_me', False)

        if not status:
            return JsonResponse({
                'success': False,
                'error': 'Missing status'
            })

        tasks_data = []
        total_count = 0

        # Base query filters
        base_filter_nextwork = {'created_by': request.user} if filter_created_by_me else {
            'person': request.user}
        base_filter_lastwork = {'created_by': request.user} if filter_created_by_me else {
            'person': request.user}

        if status in ['to_do', 'in_progress']:
            all_tasks = NextWork.objects.filter(
                **base_filter_nextwork,
                status=status
            ).select_related('person', 'created_by', 'file_number').extra(
                select={
                    'urgency_order': "CASE urgency WHEN 'urgent' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 WHEN 'low' THEN 4 ELSE 5 END"
                }
            ).order_by('urgency_order', 'date')

            total_count = all_tasks.count()
            tasks = all_tasks[offset:offset + count]

            for task in tasks:
                tasks_data.append({
                    'id': task.id,
                    'file_number': task.file_number.file_number if task.file_number else '',
                    'task': task.task[:80] + '...' if task.task and len(task.task) > 80 else task.task,
                    'date': task.date.isoformat() if task.date else None,
                    'timestamp': task.timestamp.isoformat(),
                    'urgency': task.urgency,
                    'assigned_to': task.person.get_full_name() if task.person else 'Unassigned',
                    'created_by': task.created_by.get_full_name() if task.created_by else 'Unknown',
                    'is_created_by_me': task.created_by == request.user if task.created_by else False,
                })

        elif status == 'completed':
            # For completed tasks, we show from LastWork
            all_tasks = LastWork.objects.filter(
                **base_filter_lastwork,
                timestamp__gte=timezone.now() - timezone.timedelta(days=7)
            ).select_related('person', 'created_by', 'file_number').order_by('-timestamp')

            total_count = all_tasks.count()
            tasks = all_tasks[offset:offset + count]

            for task in tasks:
                tasks_data.append({
                    'id': task.id,
                    'file_number': task.file_number.file_number if task.file_number else '',
                    'task': task.task[:80] + '...' if task.task and len(task.task) > 80 else task.task,
                    'date': task.date.isoformat() if task.date else None,
                    'timestamp': task.timestamp.isoformat(),
                    'assigned_to': task.person.get_full_name() if task.person else 'Unassigned',
                    'created_by': task.created_by.get_full_name() if task.created_by else 'Unknown',
                    'is_created_by_me': task.created_by == request.user if task.created_by else False,
                })

        has_more = (offset + count) < total_count

        return JsonResponse({
            'success': True,
            'tasks': tasks_data,
            'has_more': has_more,
            'total_count': total_count,
            'loaded_count': len(tasks_data)
        })

    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


@login_required
def get_files(request):
    """Get list of files for modal dropdown"""
    try:
        files = WIP.objects.filter(
            file_status__status='Open'
        ).values('id', 'file_number', 'matter_description').order_by('file_number')

        files_data = []
        for file in files:
            files_data.append({
                'id': file['id'],
                'file_number': file['file_number'],
                'description': file['matter_description'] or 'No description',
                'display_text': f"{file['file_number']} - {file['matter_description'] or 'No description'}"
            })

        return JsonResponse({
            'success': True,
            'files': files_data
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


@login_required
def get_users(request):
    """Get list of users for modal dropdown"""
    try:
        users = CustomUser.objects.all().values('id', 'first_name', 'last_name')

        users_data = []
        for user in users:
            name = f"{user['first_name']} {user['last_name']}".strip()
            if not name:
                name = f"User {user['id']}"
            users_data.append({
                'id': user['id'],
                'name': name
            })

        return JsonResponse({
            'success': True,
            'users': users_data
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


@login_required
def get_risk_assessments_due_data(request):
    """Get risk assessments due for dashboard without page reload."""
    try:
        user = CustomUser.objects.get(username=request.user)
        risk_scope = request.GET.get('risk_scope', 'associated')
        risk_scope_wips, validated_risk_scope = get_dashboard_risk_scope_wips(
            user, risk_scope
        )
        risk_assessments_due = get_risk_assessments_due_queryset(
            risk_scope_wips
        ).select_related('client1', 'client2')

        data = []
        for assessment in risk_assessments_due:
            reason_due = 'No risk assessment completed'
            if assessment.latest_assessment_date:
                reason_due = 'No ongoing monitoring in the last year'

            data.append({
                'file_number': assessment.file_number,
                'matter_description': assessment.matter_description or '',
                'client1_name': assessment.client1.name if assessment.client1 else '',
                'client2_name': assessment.client2.name if assessment.client2 else '',
                'latest_assessment_date_display': (
                    assessment.latest_assessment_date.strftime('%d/%m/%Y')
                    if assessment.latest_assessment_date else None
                ),
                'latest_monitoring_date_display': (
                    assessment.latest_monitoring_date.strftime('%d/%m/%Y')
                    if assessment.latest_monitoring_date else None
                ),
                'reason_due': reason_due,
                'home_url': reverse('home', args=[assessment.file_number])
            })

        return JsonResponse({
            'success': True,
            'risk_scope': validated_risk_scope,
            'count': len(data),
            'items': data
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


@login_required
@require_POST
def create_task(request):
    """Create a new NextWork task"""
    try:
        data = json.loads(request.body)

        # Create new NextWork instance
        task = NextWork(
            file_number_id=data.get('file_number'),
            person_id=data.get('person'),
            task=data.get('task'),
            date=data.get('date') if data.get('date') else None,
            urgency=data.get('urgency', 'medium'),
            status=data.get('status', 'to_do'),
            created_by=request.user
        )
        task.save()

        return JsonResponse({
            'success': True,
            'task_id': task.id
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


@login_required
def display_data_home_page(request, file_number):
    try:
        logger.info(
            f'User {request.user.username} accessing matter file {file_number}')
        matter = WIP.objects.get(file_number=file_number)
        matter_file_reviews = MatterFileReview.objects.filter(
            matter=matter).order_by('-date_review_completed', '-date_reviewed', '-timestamp')
        undertakings = Undertaking.objects.filter(file_number=matter)
        next_work_form = NextWorkFormWithoutFileNumber()
        next_work = NextWork.objects.filter(
            file_number=matter, completed=False).order_by('date')
        last_work = LastWork.objects.filter(
            file_number=matter).order_by('-date')
        last_work_form = LastWorkFormWithoutFileNumber()
        ongoing_monitorings = OngoingMonitoring.objects.filter(
            file_number=matter.id).order_by('-timestamp')
        risk_assessment = RiskAssessment.objects.filter(
            matter=matter
        ).order_by('-due_diligence_date')
        eleven_months_ago = (timezone.now() - relativedelta(months=11)).date()
        if risk_assessment.exists():
            risk_assessment = risk_assessment[0]
            if risk_assessment.due_diligence_date <= eleven_months_ago:
                if ongoing_monitorings.exists():
                    if ongoing_monitorings[0].date_due_diligence_conducted <= eleven_months_ago:
                        eleven_months_since_last_risk_assessment = True
                    else:
                        eleven_months_since_last_risk_assessment = False
                else:
                    eleven_months_since_last_risk_assessment = True
            else:
                eleven_months_since_last_risk_assessment = False
        else:
            risk_assessment = ""
            eleven_months_since_last_risk_assessment = False
        if matter.file_status.status == 'Archived':
            messages.error(
                request, "ARCHIVED MATTER. Please note this matter is archived.")
        return render(request, 'home.html', {'matter': matter,
                                             'undertakings': undertakings,
                                             'file_number': file_number,
                                             'next_work_form': next_work_form, 'next_work': next_work,
                                             'last_work': last_work, 'last_work_form': last_work_form,
                                             'ongoing_monitorings': ongoing_monitorings,
                                             'risk_assessment': risk_assessment, 'eleven_months_since_last_risk_assessment': eleven_months_since_last_risk_assessment,
                                             'matter_file_reviews': build_matter_file_review_display_data(matter_file_reviews),
                                             'logs': get_file_logs(file_number)})
    except WIP.DoesNotExist:
        logger.warning(
            f'User {request.user.username} attempted to access non-existent matter file {file_number}')
        messages.error(request, 'Matter file not found')
        return render(request, 'home.html', {'error': 'Matter file not found'})
    except Exception as e:
        logger.error(
            f'Error displaying matter file {file_number} for user {request.user.username}: {str(e)}', exc_info=True)
        messages.error(
            request, 'An error occurred while loading the matter file')
        return render(request, 'home.html', {'error': 'An error occurred while loading the matter file'})


def get_file_logs(file_number):
    file = WIP.objects.filter(file_number=file_number).first()
    """
    Log: {datetime:datetime, description, user, type_of_data}
    """
    logs = []
    logs.append({'timestamp': file.timestamp.strftime("%d/%m/%Y %H:%M:%S"),
                'desc': 'Matter created.',
                 'user': file.created_by,
                 'type': 'file_info'})
    file_modifications = Modifications.objects.filter(
        Q(content_type=ContentType.objects.get_for_model(file)) &
        Q(object_id=file.id)
    )
    for modification in file_modifications:
        # You can append modifications to logs similarly
        logs.append({
            'timestamp': modification.timestamp.strftime("%d/%m/%Y %H:%M:%S"),
            'desc': f'File updated. Changes = {modification.changes}',
            'user': modification.modified_by.username if modification.modified_by else None,
            'type': 'file_info'
        })
    file_modifications = Modifications.objects.filter(
        Q(content_type=ContentType.objects.get_for_model(file.client1)) &
        Q(object_id=file.client1.id)
    )
    for modification in file_modifications:
        logs.append({
            'timestamp': modification.timestamp.strftime("%d/%m/%Y %H:%M:%S"),
            'desc': f'Client updated. Changes = {modification.changes}',
            'user': modification.modified_by.username if modification.modified_by else None,
            'type': 'client_info'
        })
    logs.append({'timestamp': file.client1.timestamp.strftime("%d/%m/%Y %H:%M:%S"),
                 'desc': f'Client ({file.client1}) Created.',
                 'user': file.client1.created_by,
                 'type': 'client_info'})

    if file.client2:
        logs.append({'timestamp': file.client2.timestamp.strftime("%d/%m/%Y %H:%M:%S"),
                     'desc': f'Client ({file.client2}) Created.',
                     'user': file.client2.created_by,
                     'type': 'client_info'})
        file_modifications = Modifications.objects.filter(
            Q(content_type=ContentType.objects.get_for_model(file.client2)) &
            Q(object_id=file.client2.id)
        )
        for modification in file_modifications:

            logs.append({
                'timestamp': modification.timestamp.strftime("%d/%m/%Y %H:%M:%S"),
                'desc': f'Client updated. Changes = {modification.changes}',
                'user': modification.modified_by.username if modification.modified_by else None,
                'type': 'client_info'
            })

    if file.authorised_party1:

        logs.append({'timestamp': file.authorised_party1.timestamp.strftime("%d/%m/%Y %H:%M:%S"),
                     'desc': f'Authorised Party {file.authorised_party1} Created.',
                     'user': file.authorised_party1.created_by,
                     'type': 'authorised_party_info'})
        file_modifications = Modifications.objects.filter(
            Q(content_type=ContentType.objects.get_for_model(file.authorised_party1)) &
            Q(object_id=file.authorised_party1.id)
        )
        for modification in file_modifications:
            logs.append({
                'timestamp': modification.timestamp.strftime("%d/%m/%Y %H:%M:%S"),
                'desc': f'Authorised Party updated. Changes = {modification.changes}',
                'user': modification.modified_by.username if modification.modified_by else None,
                'type': 'authorised_party_info'
            })

    if file.authorised_party2:
        logs.append({'timestamp': file.authorised_party2.timestamp.strftime("%d/%m/%Y %H:%M:%S"),
                     'desc': f'Authorised Party ({file.authorised_party2.name}) Created.',
                     'user': file.authorised_party2.created_by,
                     'type': 'authorised_party_info'})
        file_modifications = Modifications.objects.filter(
            Q(content_type=ContentType.objects.get_for_model(file.authorised_party2)) &
            Q(object_id=file.authorised_party1.id)
        )
        for modification in file_modifications:
            logs.append({
                'timestamp': modification.timestamp.strftime("%d/%m/%Y %H:%M:%S"),
                'desc': f'Authorised Party updated. Changes = {modification.changes}',
                'user': modification.modified_by.username if modification.modified_by else None,
                'type': 'authorised_party_info'
            })

    if file.other_side:
        logs.append({'timestamp': file.other_side.timestamp.strftime("%d/%m/%Y %H:%M:%S"),
                     'desc': f'Other Side ({file.other_side}) Created.',
                     'user': file.other_side.created_by,
                     'type': 'other_side_info'})
        file_modifications = Modifications.objects.filter(
            Q(content_type=ContentType.objects.get_for_model(file.other_side)) &
            Q(object_id=file.other_side.id)
        )
        for modification in file_modifications:
            logs.append({
                'timestamp': modification.timestamp.strftime("%d/%m/%Y %H:%M:%S"),
                'desc': f'Other Side updated. Changes = {modification.changes}',
                'user': modification.modified_by.username if modification.modified_by else None,
                'type': 'other_side_info'
            })
    emails = MatterEmails.objects.filter(file_number=file.id)
    for email in emails:
        sender = json.loads(email.sender)
        receiver = json.loads(email.receiver)
        desc = f'Email to {
            receiver} - {email.subject}' if email.is_sent else f'Email from {sender} - {email.subject}'
        logs.append({'timestamp': email.time.strftime("%d/%m/%Y %H:%M:%S"),
                     'desc': desc, 'user': 'Automatic System',
                    'type': 'email'})

    attendance_notes = MatterAttendanceNotes.objects.filter(
        file_number=file.id)
    for note in attendance_notes:
        note_subject_with_charge_status = (
            f'{note.subject_line} (N/C)' if not note.is_charged else note.subject_line
        )
        logs.append({'timestamp': note.timestamp.strftime("%d/%m/%Y %H:%M:%S"),
                     'desc': f'Attendance note created - {note_subject_with_charge_status}',
                     'user': note.created_by,
                    'type': 'attendance_note'})

        note_modifications = Modifications.objects.filter(
            Q(content_type=ContentType.objects.get_for_model(note)) &
            Q(object_id=note.id)
        )
        for modification in note_modifications:
            # You can append modifications to logs similarly
            logs.append({
                'timestamp': modification.timestamp.strftime("%d/%m/%Y %H:%M:%S"),
                'desc': f'Attendance note modification, date of attendance note {note.date.strftime('%d/%m/%Y')}. Changes = {mark_safe(modification.changes)}',
                'user': modification.modified_by.username if modification.modified_by else None,
                'type': 'attendance_note'
            })

    letters = MatterLetters.objects.filter(file_number=file.id)
    for letter in letters:
        logs.append({'timestamp': letter.timestamp.strftime("%d/%m/%Y %H:%M:%S"),
                     'desc': f'Letter entered - {letter.subject_line}',
                     'user': letter.created_by,
                    'type': 'letter'})

        modifications = Modifications.objects.filter(
            Q(content_type=ContentType.objects.get_for_model(letter)) &
            Q(object_id=letter.id)
        )
        for modification in modifications:
            # You can append modifications to logs similarly
            logs.append({
                'timestamp': modification.timestamp.strftime("%d/%m/%Y %H:%M:%S"),
                'desc': f'Letter modification, date of letter {letter.date.strftime('%d/%m/%Y')}. Changes = {modification.changes}',
                'user': modification.modified_by.username if modification.modified_by else None,
                'type': 'letter'
            })

    next_work = NextWork.objects.filter(file_number=file.id)
    for work in next_work:
        logs.append({'timestamp': work.timestamp.strftime("%d/%m/%Y %H:%M:%S"),
                     'desc': f'Next work created - {work.task} - for {work.person}',
                     'user': work.created_by,
                    'type': 'next_work'
                     })
        modifications = Modifications.objects.filter(
            Q(content_type=ContentType.objects.get_for_model(work)) &
            Q(object_id=work.id)
        )
        for modification in modifications:

            logs.append({
                'timestamp': modification.timestamp.strftime("%d/%m/%Y %H:%M:%S"),
                'desc': f'Next Work modification, completed= {work.completed}, description of task {work.task}. Changes = {modification.changes}',
                'user': modification.modified_by.username if modification.modified_by else None,
                'type': 'next_work'
            })

    last_work = LastWork.objects.filter(file_number=file.id)
    for work in last_work:
        logs.append({'timestamp': work.timestamp.strftime("%d/%m/%Y %H:%M:%S"),
                     'desc': f'Last work created - {work.task} - done by {work.person}',
                     'user': work.created_by,
                    'type': 'last_work'
                     })
        modifications = Modifications.objects.filter(
            Q(content_type=ContentType.objects.get_for_model(work)) &
            Q(object_id=work.id)
        )
        for modification in modifications:

            logs.append({
                'timestamp': modification.timestamp.strftime("%d/%m/%Y %H:%M:%S"),
                'desc': f'Last Work modification, description of task {work.task}. Changes = {modification.changes}',
                'user': modification.modified_by.username if modification.modified_by else None,
                'type': 'last_work'
            })

    pmts_slips = PmtsSlips.objects.filter(file_number=file.id)
    for slip in pmts_slips:
        desc = f'Pink slip for amount £{
            slip.amount} - {slip.description}' if slip.is_money_out else f'Blue slip for amount £{slip.amount} - {slip.description}'
        logs.append({'timestamp': slip.timestamp.strftime("%d/%m/%Y %H:%M:%S"),
                     'desc': desc,
                     'user': slip.created_by,
                    'type': 'pmts_slip'})
        modifications = Modifications.objects.filter(
            Q(content_type=ContentType.objects.get_for_model(slip)) &
            Q(object_id=slip.id)
        )
        for modification in modifications:
            slip_type = 'Pink slip' if slip.is_money_out else 'Blue slip'
            logs.append({
                'timestamp': modification.timestamp.strftime("%d/%m/%Y %H:%M:%S"),
                'desc': f'{slip_type} modification. Changes = {modification.changes}',
                'user': modification.modified_by.username if modification.modified_by else None,
                'type': 'pmts_slip'
            })

    green_slips = LedgerAccountTransfers.objects.filter(
        Q(file_number_from=file.id) or Q(file_number_to=file.id))
    for slip in green_slips:
        desc = f'Green slip for amount £{
            slip.amount} - From: {slip.file_number_from} To: {slip.file_number_to} {slip.description}'
        logs.append({'timestamp': slip.timestamp.strftime("%d/%m/%Y %H:%M:%S"),
                     'desc': desc,
                     'user': slip.created_by,
                    'type': 'green_slip'})
        modifications = Modifications.objects.filter(
            Q(content_type=ContentType.objects.get_for_model(slip)) &
            Q(object_id=slip.id)
        )
        for modification in modifications:

            logs.append({
                'timestamp': modification.timestamp.strftime("%d/%m/%Y %H:%M:%S"),
                'desc': f'Green slip modification. Changes = {modification.changes}',
                'user': modification.modified_by.username if modification.modified_by else None,
                'type': 'green_slip'
            })

    invoices = Invoices.objects.filter(file_number=file.id)
    for invoice in invoices:
        desc = f'Invoice created for amount(s) {invoice.our_costs}'
        logs.append({'timestamp': invoice.timestamp.strftime("%d/%m/%Y %H:%M:%S"),
                     'desc': desc,
                     'user': invoice.created_by,
                    'type': 'invoice'})
        modifications = Modifications.objects.filter(
            Q(content_type=ContentType.objects.get_for_model(invoice)) &
            Q(object_id=invoice.id)
        )
        for modification in modifications:

            logs.append({
                'timestamp': modification.timestamp.strftime("%d/%m/%Y %H:%M:%S"),
                'desc': f'Invoice modification. Changes = {modification.changes}',
                'user': modification.modified_by.username if modification.modified_by else None,
                'type': 'invoice'
            })

    credit_notes = CreditNote.objects.filter(file_number=file.id)
    status_labels = dict(CreditNote.STATUSES)
    for credit_note in credit_notes:
        status_label = status_labels.get(credit_note.status, credit_note.status)
        invoice_number = credit_note.invoice.invoice_number or "Draft"
        desc = (
            f'Credit note for Invoice {invoice_number} of £{credit_note.amount} '
            f'created. Status: {status_label}'
        )
        logs.append({
            'timestamp': credit_note.timestamp.strftime("%d/%m/%Y %H:%M:%S"),
            'desc': desc,
            'user': credit_note.created_by,
            'type': 'credit_note'
        })
        modifications = Modifications.objects.filter(
            Q(content_type=ContentType.objects.get_for_model(credit_note)) &
            Q(object_id=credit_note.id)
        )
        for modification in modifications:
            logs.append({
                'timestamp': modification.timestamp.strftime("%d/%m/%Y %H:%M:%S"),
                'desc': f'Credit note modification. Changes = {modification.changes}',
                'user': modification.modified_by.username if modification.modified_by else None,
                'type': 'credit_note'
            })

    risk_assessment = RiskAssessment.objects.filter(matter=file.id).first()
    if risk_assessment:
        logs.append({'timestamp': risk_assessment.timestamp.strftime("%d/%m/%Y %H:%M:%S"),
                    'desc': f'Risk Assessment completed',
                     'user': risk_assessment.due_diligence_signed_by,
                     'type': 'risk_assessment'})
        modifications = Modifications.objects.filter(
            Q(content_type=ContentType.objects.get_for_model(risk_assessment)) &
            Q(object_id=risk_assessment.id)
        )
        for modification in modifications:
            logs.append({
                'timestamp': modification.timestamp.strftime("%d/%m/%Y %H:%M:%S"),
                'desc': f'Risk Assessment modification. Changes = {modification.changes}',
                'user': modification.modified_by.username if modification.modified_by else None,
                'type': 'risk_assessment'
            })
    ongoing_monitoring = OngoingMonitoring.objects.filter(file_number=file.id)
    for obj in ongoing_monitoring:
        logs.append({'timestamp': obj.timestamp.strftime("%d/%m/%Y %H:%M:%S"),
                     'desc': f'Ongoing Monitoring done.',
                     'user': obj.created_by,
                     'type': 'ongoing_monitoring'})
        modifications = Modifications.objects.filter(
            Q(content_type=ContentType.objects.get_for_model(obj)) &
            Q(object_id=obj.id)
        )
        for modification in modifications:
            logs.append({
                'timestamp': modification.timestamp.strftime("%d/%m/%Y %H:%M:%S"),
                'desc': f'Ongoing Monitoring modification. Changes = {modification.changes}',
                'user': modification.modified_by.username if modification.modified_by else None,
                'type': 'ongoing_monitoring'
            })
    sorted_logs = sorted(logs, key=lambda x: datetime.strptime(
        x['timestamp'], '%d/%m/%Y %H:%M:%S'), reverse=True)

    return sorted_logs


def add_new_client(request_post_copy, client_prefix, user):
    name = request_post_copy[f'ClientName{client_prefix}']
    dob = request_post_copy[f'Client{client_prefix}DOB']
    occupation = request_post_copy[f'Client{client_prefix}Occupation']

    address_line1 = request_post_copy[f'Client{client_prefix}AddressLine1']
    address_line2 = request_post_copy[f'Client{client_prefix}AddressLine2']
    county = request_post_copy[f'Client{client_prefix}County']
    postcode = request_post_copy[f'Client{client_prefix}Postcode']
    email = request_post_copy[f'Client{client_prefix}Email']
    contact_number = request_post_copy[f'Client{client_prefix}ContactNumber']
    date_of_last_aml = request_post_copy[f'Client{client_prefix}AMLCheckDate']
    id_verified = f'IDVer{client_prefix}' in request_post_copy

    client_contact = ClientContactDetails(
        name=name,
        dob=dob if dob != '' else None,
        occupation=occupation,
        address_line1=address_line1,
        address_line2=address_line2,
        county=county,
        postcode=postcode,
        email=email,
        contact_number=contact_number,
        date_of_last_aml=date_of_last_aml if date_of_last_aml != '' else None,
        id_verified=id_verified,
        created_by=user
    )

    client_contact.save()

    return client_contact.id


def add_new_authorised_party(request_post_copy, ap_prefix, user):
    name = request_post_copy[f'APName{ap_prefix}']
    relationship_to_client = request_post_copy[f'AP{ap_prefix}RelationshipToC']
    address_line1 = request_post_copy[f'AP{ap_prefix}AddressLine1']
    address_line2 = request_post_copy[f'AP{ap_prefix}AddressLine2']
    county = request_post_copy[f'AP{ap_prefix}County']
    postcode = request_post_copy[f'AP{ap_prefix}Postcode']
    email = request_post_copy[f'AP{ap_prefix}Email']
    contact_number = request_post_copy[f'AP{ap_prefix}ContactNumber']
    id_check = f'AP{ap_prefix}IDCheck' in request_post_copy
    date_of_id_check = request_post_copy[f'AP{ap_prefix}IDCheckDate']

    try:
        authorised_party = AuthorisedParties(
            name=name,
            relationship_to_client=relationship_to_client,
            address_line1=address_line1,
            address_line2=address_line2,
            county=county,
            postcode=postcode,
            email=email,
            contact_number=contact_number,
            id_check=id_check,
            date_of_id_check=date_of_id_check,
            created_by=user
        )
    except Exception as e:
        print(f'Error in adding Authorised Party {ap_prefix}: {str(e)}')

    authorised_party.save()

    return authorised_party.id


def add_new_otherside_details(request_post_copy, user):

    name = request_post_copy['OSName']
    address_line1 = request_post_copy['OSAddressLine1']
    address_line2 = request_post_copy['OSAddressLine2']
    county = request_post_copy['OSCounty']
    postcode = request_post_copy['OSPostcode']
    email = request_post_copy['OSEmail']
    contact_number = request_post_copy['OSContactNumber']
    solicitors = request_post_copy['OSSolicitors']
    solicitors_email = request_post_copy['OSSolicitorsEmail']

    otherside_details = OthersideDetails(
        name=name,
        address_line1=address_line1,
        address_line2=address_line2,
        county=county,
        postcode=postcode,
        email=email,
        contact_number=contact_number,
        solicitors=solicitors,
        solicitors_email=solicitors_email,
        created_by=user
    )

    otherside_details.save()

    # Return the ID of the newly added OthersideDetails
    return otherside_details.id


def preprocess_form_data(post_data):
    post_copy = post_data.copy()

    post_copy['client2'] = None if post_copy['client2'] == '0' else post_copy['client2']

    post_copy['authorised_party1'] = None if post_copy['authorised_party1'] == '0' else post_copy['authorised_party1']
    post_copy['authorised_party2'] = None if post_copy['authorised_party2'] == '0' else post_copy['authorised_party2']
    post_copy['other_side'] = None if post_copy['other_side'] == '0' else post_copy['other_side']

    return post_copy


def update_checkbox_values(data, *fields):
    for field in fields:
        data[field] = field in data

    return data


def get_standard_data():
    fee_earners = CustomUser.objects.filter(is_matter_fee_earner=True)
    file_status = FileStatus.objects.all()
    file_locations = FileLocation.objects.all()
    matter_types = MatterType.objects.all().order_by('type')
    clients = ClientContactDetails.objects.all().order_by('name')
    authorised_parties = AuthorisedParties.objects.all().order_by('name')
    othersides = OthersideDetails.objects.all().order_by('name')

    form_data = {
        'fee_earners': fee_earners,
        'file_status': file_status,
        'file_locations': file_locations,
        'matter_types': matter_types,
        'clients': clients,
        'authorised_parties': authorised_parties,
        'othersides': othersides,
    }

    return form_data


@login_required
def open_new_file_page(request):
    form_data = get_standard_data()

    if request.method == 'POST':
        request_post_copy = preprocess_form_data(request.POST)
        try:
            if request_post_copy['client1'] == '-1':
                request_post_copy['client1'] = add_new_client(
                    request_post_copy, 1, request.user)

            if request_post_copy['client2'] == '-1':
                request_post_copy['client2'] = add_new_client(
                    request_post_copy, 2, request.user)

            if request_post_copy['authorised_party1'] == '-1':
                request_post_copy['authorised_party1'] = add_new_authorised_party(
                    request_post_copy, 1, request.user)

            if request_post_copy['authorised_party2'] == '-1':
                request_post_copy['authorised_party2'] = add_new_authorised_party(
                    request_post_copy, 2, request.user)

            if request_post_copy['other_side'] == '-1':
                request_post_copy['other_side'] = add_new_otherside_details(
                    request_post_copy, request.user)

            update_checkbox_values(
                request_post_copy, 'terms_of_engagement_client1', 'terms_of_engagement_client2')
            update_checkbox_values(
                request_post_copy, 'ncba_client1', 'ncba_client2')

            request_post_copy['created_by'] = request.user

            form = OpenFileForm(request_post_copy)
            if form.is_valid():
                instance = form.save()
                messages.success(request, 'File opened successfully.')
                return redirect('index')
            else:
                # Add error messages to be displayed in the template
                for field, errors in form.errors.items():
                    for error in errors:
                        messages.error(
                            request, f"{form[field].label}: {error}")
                return render(request, 'open_file.html', {'form_data': form_data, 'form': form})

        except Exception as e:
            messages.error(request, f"Error during file opening: {str(e)}")
            return render(request, 'open_file.html', {'form_data': form_data})
    else:
        return render(request, 'open_file.html', {'form_data': form_data})


@login_required
def add_risk_assessment(request, file_number):
    try:
        matter = WIP.objects.get(file_number=file_number)
    except WIP.DoesNotExist:
        messages.error(
            request, 'Matter with the given file number does not exist.')
        return redirect('index')
    if request.method == 'POST':
        post_data = request.POST.copy()

        form = RiskAssessmentForm(post_data)

        if form.is_valid():
            risk_assessment = form.save()
            messages.success(request, 'Risk Assessment successfully added.')
            return redirect('home', risk_assessment.matter.file_number)
        else:
            error_message = 'Form is not valid. Please correct the errors:'
            for field, errors in form.errors.items():
                error_message += f'\n{field}: {", ".join(errors)}'
            messages.error(request, error_message)
    else:

        form = RiskAssessmentForm(initial={'matter': matter.id})

    return render(request, 'risk_assessment.html', {'form': form, 'file_number': file_number, 'title': 'Add'})


@login_required
def add_matter_file_review(request, file_number):
    matter = get_object_or_404(WIP, file_number=file_number)

    if request.method == 'POST':
        form = MatterFileReviewForm(request.POST)
        if form.is_valid():
            review = form.save(commit=False)
            review.matter = matter
            review.created_by = request.user
            review.save()
            messages.success(request, 'Matter file review added successfully.')
            return redirect('home', file_number=matter.file_number)

        for field, errors in form.errors.items():
            for error in errors:
                messages.error(request, f"{form[field].label}: {error}")
    else:
        form = MatterFileReviewForm(initial={
            'client_matter_reference': matter.file_number,
            'file_reviewed_by': request.user.id,
            'date_reviewed': timezone.localdate(),
            'file_review_completed_by': request.user.id,
            'date_review_completed': timezone.localdate(),
        })

    return render(request, 'matter_file_review.html', {
        'form': form,
        'file_number': matter.file_number,
        'matter': matter,
        'title': 'Add',
        'matter_file_review_sections': MATTER_FILE_REVIEW_SECTIONS,
    })


@login_required
def edit_matter_file_review(request, id):
    review = get_object_or_404(MatterFileReview, id=id)
    duplicate_obj = copy.deepcopy(review)

    if request.method == 'POST':
        form = MatterFileReviewForm(request.POST, instance=review)
        if form.is_valid():
            changed_fields = form.changed_data
            changes = {}
            for field in changed_fields:
                changes[field] = {
                    'old_value': str(getattr(duplicate_obj, field)),
                    'new_value': None
                }

            form.save()

            for field in changed_fields:
                changes[field]['new_value'] = str(getattr(review, field))

            if changes:
                create_modification(
                    user=request.user,
                    modified_obj=review,
                    changes=changes
                )

            messages.success(request, 'Matter file review updated successfully.')
            return redirect('home', file_number=review.matter.file_number)

        for field, errors in form.errors.items():
            for error in errors:
                messages.error(request, f"{form[field].label}: {error}")
    else:
        form = MatterFileReviewForm(instance=review)

    return render(request, 'matter_file_review.html', {
        'form': form,
        'file_number': review.matter.file_number,
        'matter': review.matter,
        'title': 'Edit',
        'matter_file_review_sections': MATTER_FILE_REVIEW_SECTIONS,
    })


@login_required
def download_matter_file_review(request, id):
    review = get_object_or_404(MatterFileReview, id=id)
    sections = []
    for section in MATTER_FILE_REVIEW_SECTIONS:
        rows = []
        for row in section['rows']:
            rows.append({
                'question': row['question'],
                'bullets': row.get('bullets', []),
                'answer': getattr(review, row['answer_field']) or '---',
                'comments': getattr(review, row['comments_field']) or '---',
            })
        sections.append({
            'title': section['title'],
            'rows': rows,
        })

    html_string = render_to_string(
        'download_templates/matter_file_review.html', {
            'review': review,
            'sections': sections,
        })

    pdf_file = HTML(string=html_string).write_pdf()

    response = HttpResponse(pdf_file, content_type='application/pdf')
    response['Content-Disposition'] = (
        f'attachment; filename="file_review_{review.matter.file_number}_{id}.pdf"'
    )
    return response


@login_required
def edit_client(request, id):
    client = ClientContactDetails.objects.get(id=id)
    if request.method == 'POST':
        duplicate_obj = copy.deepcopy(client)
        form = ClientForm(request.POST, instance=client)
        if form.is_valid():

            changed_fields = form.changed_data
            changes = {}
            for field in changed_fields:
                changes[field] = {
                    'old_value': str(getattr(duplicate_obj, field)),
                    'new_value': None
                }
            form.save()

            for field in changed_fields:
                changes[field]['new_value'] = str(
                    getattr(client, field))

            create_modification(
                user=request.user,
                modified_obj=client,
                changes=changes
            )

            messages.success(
                request, 'Successfully updated Client. Please search for File Number.')
            return redirect('index')
        else:
            error_message = 'Form is not valid. Please correct the errors:'
            for field, errors in form.errors.items():
                error_message += f'\n{field}: {", ".join(errors)}'
            messages.error(request, error_message)
    else:
        form = ClientForm(instance=client)
    return render(request, 'edit_models.html', {'form': form, 'title': 'Client Information'})


@login_required
def edit_authorised_party(request, id):
    ap = AuthorisedParties.objects.get(id=id)
    if request.method == 'POST':
        duplicate_obj = copy.deepcopy(ap)
        form = ClientForm(request.POST, instance=ap)
        if form.is_valid():
            changed_fields = form.changed_data
            changes = {}
            for field in changed_fields:
                changes[field] = {
                    'old_value': str(getattr(duplicate_obj, field)),
                    'new_value': None
                }
            form.save()
            for field in changed_fields:
                changes[field]['new_value'] = str(
                    getattr(ap, field))
            create_modification(
                user=request.user,
                modified_obj=ap,
                changes=changes
            )
            messages.success(
                request, 'Successfully updated Authorised Party. Please search for File Number.')
            return redirect('index')
        else:
            error_message = 'Form is not valid. Please correct the errors:'
            for field, errors in form.errors.items():
                error_message += f'\n{field}: {", ".join(errors)}'
            messages.error(request, error_message)
    else:
        form = AuthorisedPartyForm(instance=ap)
    return render(request, 'edit_models.html', {'form': form, 'title': 'Authorised Party Information'})


@login_required
def edit_otherside(request, id):
    os = OthersideDetails.objects.get(id=id)
    if request.method == 'POST':
        duplicate_obj = copy.deepcopy(os)
        form = OtherSideForm(request.POST, instance=os)
        if form.is_valid():
            changed_fields = form.changed_data
            changes = {}
            for field in changed_fields:
                changes[field] = {
                    'old_value': str(getattr(duplicate_obj, field)),
                    'new_value': None
                }
            form.save()
            for field in changed_fields:
                changes[field]['new_value'] = str(
                    getattr(os, field))
            create_modification(
                user=request.user,
                modified_obj=os,
                changes=changes
            )
            messages.success(
                request, 'Successfully updated Other Side Details on all applicable files. Please search for a File Number you were working on.')
            return redirect('index')
        else:
            error_message = 'Form is not valid. Please correct the errors:'
            for field, errors in form.errors.items():
                error_message += f'\n{field}: {", ".join(errors)}'
            messages.error(request, error_message)
    else:
        form = OtherSideForm(instance=os)
    return render(request, 'edit_models.html', {'form': form, 'title': 'Other Side Details'})


@login_required
def edit_file(request, file_number):
    file = WIP.objects.filter(file_number=file_number).first()
    form_data = get_standard_data()

    if request.method == 'POST':
        try:

            request_post_copy = preprocess_form_data(request.POST)

            if request_post_copy['client2'] == '-1':
                request_post_copy['client2'] = add_new_client(
                    request_post_copy, 2, request.user)

            if request_post_copy['authorised_party1'] == '-1':
                request_post_copy['authorised_party1'] = add_new_authorised_party(
                    request_post_copy, 1, request.user)

            if request_post_copy['authorised_party2'] == '-1':
                request_post_copy['authorised_party2'] = add_new_authorised_party(
                    request_post_copy, 2, request.user)

            if request_post_copy['other_side'] == '-1':
                request_post_copy['other_side'] = add_new_otherside_details(
                    request_post_copy, request.user)
            update_checkbox_values(
                request_post_copy, 'terms_of_engagement_client1', 'terms_of_engagement_client2')
            update_checkbox_values(
                request_post_copy, 'ncba_client1', 'ncba_client2')

            request_post_copy['created_by'] = file.created_by

            form = OpenFileForm(request_post_copy, instance=file)
            duplicate_obj = copy.deepcopy(file)
            if form.is_valid():
                changed_fields = form.changed_data
                changes = {}
                for field in changed_fields:
                    if field != 'created_by':
                        changes[field] = {
                            'old_value': str(getattr(duplicate_obj, field)),
                            'new_value': None
                        }
                form.save()

                for field in changed_fields:
                    if field != 'created_by':
                        changes[field]['new_value'] = str(getattr(file, field))
                if changes:
                    create_modification(
                        user=request.user,
                        modified_obj=file,
                        changes=changes
                    )

                messages.success(request, 'File successfully updated.')
                return redirect('home', file_number=file_number)
            else:

                for field, errors in form.errors.items():
                    for error in errors:
                        messages.error(
                            request, f"{form[field].label}: {error}")
                        print(f"{form[field].label}: {error}")
                return render(request, 'edit_file.html', {'form_data': form_data, 'form': form, 'file_number': file_number})

        except Exception as e:
            messages.error(request, f"Error during file editing: {str(e)}")
            print(f"Error during file editing: {e}")
            return render(request, 'edit_file.html', {'form_data': form_data, 'file_number': file_number})

    else:

        form = OpenFileForm(instance=file)

    return render(request, 'edit_file.html', {'form': form, 'form_data': form_data,
                                              'file_number': file_number})


@login_required
def add_new_work_file(request, file_number):
    if request.method == 'POST':
        request_post_copy = request.POST.copy()
        file_number_id = WIP.objects.filter(file_number=file_number).first().id
        request_post_copy['file_number'] = file_number_id
        request_post_copy['created_by'] = request.user
        form = NextWorkForm(request_post_copy)
        if form.is_valid():
            form.save()
            messages.success(request, 'Next work successfully added.')
            return redirect('home', file_number=file_number)
        else:
            error_message = 'Form is not valid. Please correct the errors:'
            for field, errors in form.errors.items():
                error_message += f'\n{field}: {", ".join(errors)}'
            messages.error(request, error_message)
    else:
        messages.error(request, 'Invalid request method.')
    return redirect('home', file_number=file_number)


@login_required
def edit_next_work(request, id):
    # Fetch the NextWork instance
    nextwork_instance = get_object_or_404(NextWork, pk=id)

    if request.method == 'POST':
        duplicate_obj = copy.deepcopy(nextwork_instance)
        form = NextWorkForm(request.POST, instance=nextwork_instance)
        if form.is_valid():

            changed_fields = form.changed_data
            changes = {}
            for field in changed_fields:

                changes[field] = {
                    'old_value': str(getattr(duplicate_obj, field)),
                    'new_value': None
                }
            form.save()

            for field in changed_fields:

                if field == 'completed':
                    if getattr(nextwork_instance, field):
                        link = reverse('attendance_note_view', args=[
                                       nextwork_instance.file_number.file_number])
                        add_attendance_note_link = f"<a href='{link}' class='link'>add an attendance note</a>"
                        messages.info(request, mark_safe(
                            f'Please remember to {add_attendance_note_link} for work just completed.'))
                changes[field]['new_value'] = str(
                    getattr(nextwork_instance, field))

            create_modification(
                user=request.user,
                modified_obj=nextwork_instance,
                changes=changes
            )

            messages.success(request, 'Successfully updated next work.')
            return redirect('home', nextwork_instance.file_number)
        else:
            error_message = 'Form is not valid. Please correct the errors:'
            for field, errors in form.errors.items():
                error_message += f'\n{field}: {", ".join(errors)}'
            messages.error(request, error_message)
    else:
        form = NextWorkForm(instance=nextwork_instance)

    # Render the template with the form
    return render(request, 'edit_models.html', {'form': form, 'title': 'Next Work', 'file_number': nextwork_instance.file_number.file_number})


@login_required
def add_last_work_file(request, file_number):
    if request.method == 'POST':
        request_post_copy = request.POST.copy()
        file_number_id = WIP.objects.filter(file_number=file_number).first().id
        request_post_copy['file_number'] = file_number_id
        request_post_copy['created_by'] = request.user
        form = LastWorkForm(request_post_copy)
        if form.is_valid():
            form.save()
            link = reverse('attendance_note_view', args=[file_number])
            add_attendance_note_link = f"<a href='{link}' class='link '>add an attendance note</a>"
            messages.info(request, mark_safe(
                f'Please remember to {add_attendance_note_link} for work just added.'))
            messages.success(request, 'Last work successfully added.')
            return redirect('home', file_number=file_number)
        else:
            error_message = 'Form is not valid. Please correct the errors:'
            for field, errors in form.errors.items():
                error_message += f'\n{field}: {", ".join(errors)}'
            messages.error(request, error_message)
    else:
        messages.error(request, 'Invalid request method.')
    return redirect('home', file_number=file_number)


@login_required
def edit_last_work(request, id):
    # Fetch the NextWork instance
    lastwork_instance = get_object_or_404(LastWork, pk=id)
    duplicate_obj = copy.deepcopy(lastwork_instance)
    if request.method == 'POST':
        form = LastWorkForm(request.POST, instance=lastwork_instance)
        if form.is_valid():
            changed_fields = form.changed_data
            changes = {}
            for field in changed_fields:
                changes[field] = {
                    'old_value': str(getattr(duplicate_obj, field)),
                    'new_value': None
                }
            form.save()

            for field in changed_fields:
                changes[field]['new_value'] = str(
                    getattr(lastwork_instance, field))

            create_modification(
                user=request.user,
                modified_obj=lastwork_instance,
                changes=changes
            )
            messages.success(request, 'Successfully updated last work.')
            return redirect('home', lastwork_instance.file_number)
        else:
            error_message = 'Form is not valid. Please correct the errors:'
            for field, errors in form.errors.items():
                error_message += f'\n{field}: {", ".join(errors)}'
            messages.error(request, error_message)
    else:
        form = LastWorkForm(instance=lastwork_instance)

    # Render the template with the form
    return render(request, 'edit_models.html', {'form': form, 'title': 'Last Work', 'file_number': lastwork_instance.file_number.file_number})


@login_required
def attendance_note_view(request, file_number):
    form = AttendanceNoteFormHalf()
    file_number_id = WIP.objects.filter(file_number=file_number).first().id
    attendance_notes = MatterAttendanceNotes.objects.filter(
        file_number=file_number_id).order_by('-date')
    return render(request, 'attendance_notes.html', {'form': form, 'file_number': file_number, 'attendance_notes': attendance_notes})


@login_required
def download_attendance_notes_bulk_template(request, file_number):
    if not WIP.objects.filter(file_number=file_number).exists():
        messages.error(request, f'File number "{file_number}" not found.')
        return redirect('user_dashboard')

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="attendance_notes_template_{file_number}.csv"'
    writer = csv.writer(response)
    writer.writerow([
        'date',
        'start_time',
        'finish_time',
        'subject_line',
        'content',
        'person',
        'is_charged'
    ])
    return response


def _get_row_value(row, keys):
    for key in keys:
        if key in row and row[key] is not None:
            value = str(row[key]).strip()
            if value:
                return value
    return ""


def _parse_bulk_note_date(value):
    value = (value or "").strip()
    formats = ['%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y']
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError("invalid date format")


def _parse_bulk_note_time(value):
    value = (value or "").strip()
    formats = ['%H:%M', '%H:%M:%S', '%I:%M %p', '%I:%M%p']
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).time()
        except ValueError:
            continue
    raise ValueError("invalid time format")


def _parse_bulk_note_bool(value, default=True):
    if value is None:
        return default

    normalized = str(value).strip().lower()
    if normalized == "":
        return default
    if normalized in {"1", "true", "t", "yes", "y"}:
        return True
    if normalized in {"0", "false", "f", "no", "n"}:
        return False
    raise ValueError("invalid boolean value")


def _to_quill_json(content):
    content = (content or "").replace('\r\n', '\n').replace('\r', '\n').strip()
    if not content:
        return json.dumps({"delta": "", "html": ""})

    if content.startswith('{') and '"delta"' in content and '"html"' in content:
        try:
            json.loads(content)
            return content
        except json.JSONDecodeError:
            pass

    escaped_lines = [html.escape(line) for line in content.split('\n')]
    html_content = "<p>" + "<br>".join(escaped_lines) + "</p>"
    delta_json = json.dumps({"ops": [{"insert": f"{content}\n"}]})
    return json.dumps({"delta": delta_json, "html": html_content})


def _resolve_user_for_bulk_note(raw_value, users_by_key, users_by_full_name):
    candidate = (raw_value or "").strip()
    if not candidate:
        return None, "missing initials/user"

    normalized = candidate.lower()
    if normalized in users_by_key:
        return users_by_key[normalized], None

    matches = users_by_full_name.get(normalized, [])
    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        return None, f"ambiguous user '{candidate}'"
    return None, f"user '{candidate}' not found"


@login_required
def bulk_upload_attendance_notes(request, file_number):
    if request.method != 'POST':
        messages.error(request, 'Invalid request method.')
        return redirect('attendance_note_view', file_number=file_number)

    wip = WIP.objects.filter(file_number=file_number).first()
    if not wip:
        messages.error(request, f'File number "{file_number}" not found.')
        return redirect('attendance_note_view', file_number=file_number)

    uploaded_file = request.FILES.get('bulk_attendance_file')
    if not uploaded_file:
        messages.error(request, 'Please upload a CSV file.')
        return redirect('attendance_note_view', file_number=file_number)

    try:
        decoded = uploaded_file.read().decode('utf-8-sig')
    except UnicodeDecodeError:
        messages.error(request, 'Could not read file. Please upload UTF-8 CSV.')
        return redirect('attendance_note_view', file_number=file_number)

    reader = csv.DictReader(io.StringIO(decoded))
    if not reader.fieldnames:
        messages.error(request, 'CSV is missing a header row.')
        return redirect('attendance_note_view', file_number=file_number)

    users = CustomUser.objects.all()
    users_by_key = {}
    users_by_full_name = {}
    for user in users:
        if user.username:
            users_by_key[user.username.strip().lower()] = user
        if user.email:
            users_by_key[user.email.strip().lower()] = user
        users_by_key[str(user.id)] = user

        full_name = f"{(user.first_name or '').strip()} {(user.last_name or '').strip()}".strip().lower()
        if full_name:
            users_by_full_name.setdefault(full_name, []).append(user)

    created_count = 0
    errors = []

    for line_number, row in enumerate(reader, start=2):
        if not any((value or "").strip() for value in row.values()):
            continue

        date_str = _get_row_value(row, ['date'])
        start_time_str = _get_row_value(
            row, ['start_time', 'start', 'starttime'])
        finish_time_str = _get_row_value(
            row, ['finish_time', 'finish', 'end_time', 'end'])
        subject_line = _get_row_value(row, ['subject_line', 'subject'])
        content_value = _get_row_value(row, ['content', 'note', 'notes'])
        user_value = _get_row_value(
            row, ['person_attended', 'person', 'initials', 'username', 'user', 'fee_earner'])
        charged_value = _get_row_value(row, ['is_charged', 'charged', 'billable'])

        missing_fields = []
        if not date_str:
            missing_fields.append('date')
        if not start_time_str:
            missing_fields.append('start_time')
        if not finish_time_str:
            missing_fields.append('finish_time')
        if not subject_line:
            missing_fields.append('subject_line')
        if not content_value:
            missing_fields.append('content')
        if not user_value:
            missing_fields.append('person/initials')

        if missing_fields:
            errors.append(
                f'Line {line_number}: missing {", ".join(missing_fields)}.')
            continue

        try:
            parsed_date = _parse_bulk_note_date(date_str)
            parsed_start_time = _parse_bulk_note_time(start_time_str)
            parsed_finish_time = _parse_bulk_note_time(finish_time_str)
            parsed_is_charged = _parse_bulk_note_bool(charged_value, default=True)
        except ValueError as exc:
            errors.append(f'Line {line_number}: {str(exc)}.')
            continue

        resolved_user, user_error = _resolve_user_for_bulk_note(
            user_value, users_by_key, users_by_full_name)
        if user_error:
            errors.append(f'Line {line_number}: {user_error}.')
            continue

        row_payload = {
            'file_number': wip.id,
            'date': parsed_date.isoformat(),
            'start_time': parsed_start_time.strftime('%H:%M'),
            'finish_time': parsed_finish_time.strftime('%H:%M'),
            'subject_line': subject_line,
            'content': _to_quill_json(content_value),
            'is_charged': str(parsed_is_charged),
            'person_attended': resolved_user.id
        }

        form = AttendanceNoteForm(row_payload)
        if not form.is_valid():
            field_errors = []
            for field, field_messages in form.errors.items():
                for field_message in field_messages:
                    field_errors.append(f'{field}: {field_message}')
            errors.append(
                f'Line {line_number}: {"; ".join(field_errors) or "invalid row"}.')
            continue

        instance = form.save(commit=False)
        instance.created_by = request.user
        instance.save()
        created_count += 1

    if created_count:
        messages.success(
            request, f'Created {created_count} attendance note(s) from bulk upload.')

    if errors:
        preview_errors = " ".join(errors[:5])
        suffix = f' (and {len(errors) - 5} more)' if len(errors) > 5 else ''
        messages.warning(
            request, f'{len(errors)} row(s) failed. {preview_errors}{suffix}')

    if created_count == 0 and not errors:
        messages.warning(request, 'No rows found in CSV.')

    return redirect('attendance_note_view', file_number=file_number)


@login_required
def add_attendance_note(request, file_number):
    if request.method == 'POST':
        request_post_copy = request.POST.copy()
        file_number_id = WIP.objects.filter(file_number=file_number).first().id
        request_post_copy['file_number'] = file_number_id

        request_post_copy['created_by'] = request.user
        form = AttendanceNoteForm(request_post_copy)
        if form.is_valid():
            form.save()
            messages.success(request, 'Attendance Note successfully added.')
            return redirect('attendance_note_view', file_number=file_number)
        else:
            error_message = 'Form is not valid. Please correct the errors:'
            for field, errors in form.errors.items():
                error_message += f'\n{field}: {", ".join(errors)}'
            messages.error(request, error_message)
    else:
        messages.error(request, 'Invalid request method.')

    return redirect(attendance_note_view, file_number=file_number)


@login_required
def download_attendance_note(request, id):
    a_n = get_object_or_404(MatterAttendanceNotes, id=id)

    context = {
        'client1_name': a_n.file_number.client1.name,
        'client2_name': a_n.file_number.client2.name if a_n.file_number.client2 else '',
        'file_number': a_n.file_number.file_number,
        'date': a_n.date.strftime('%d/%m/%Y'),
        'start_time': a_n.start_time,
        'finish_time': a_n.finish_time,
        'content': mark_safe(a_n.content.html),
        'is_charged': a_n.is_charged,
        'unit': a_n.unit,
        'person_attended': a_n.person_attended,
        'user': request.user
    }

    # Render the template with the provided context
    html_string = render_to_string(
        'download_templates/attendance_note.html', context)

    # Generate PDF from the rendered HTML using WeasyPrint
    pdf_file = HTML(string=html_string).write_pdf()

    return HttpResponse(pdf_file, content_type='application/pdf')


@login_required
def download_attendance_notes_bulk(request, file_number):
    wip = WIP.objects.filter(file_number=file_number).first()
    if not wip:
        messages.error(request, f'File number "{file_number}" not found.')
        return redirect('user_dashboard')

    attendance_notes = MatterAttendanceNotes.objects.filter(
        file_number=wip.id
    ).order_by('-date', '-start_time', '-id')

    if not attendance_notes.exists():
        messages.warning(request, 'No attendance notes found to download.')
        return redirect('attendance_note_view', file_number=file_number)

    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for note in attendance_notes:
            context = {
                'client1_name': note.file_number.client1.name,
                'client2_name': note.file_number.client2.name if note.file_number.client2 else '',
                'file_number': note.file_number.file_number,
                'date': note.date.strftime('%d/%m/%Y'),
                'start_time': note.start_time,
                'finish_time': note.finish_time,
                'content': mark_safe(note.content.html),
                'is_charged': note.is_charged,
                'unit': note.unit,
                'person_attended': note.person_attended,
                'user': request.user
            }

            html_string = render_to_string(
                'download_templates/attendance_note.html', context)
            pdf_file = HTML(string=html_string).write_pdf()
            file_name = f'attendance_note_{note.date.strftime("%Y%m%d")}_{note.id}.pdf'
            zip_file.writestr(file_name, pdf_file)

    zip_buffer.seek(0)
    response = HttpResponse(zip_buffer.getvalue(), content_type='application/zip')
    response['Content-Disposition'] = (
        f'attachment; filename="attendance_notes_{file_number}.zip"'
    )
    return response


@login_required
def edit_attendance_note(request, id):
    attendance_note_instance = get_object_or_404(MatterAttendanceNotes, pk=id)
    if request.method == 'POST':

        duplicate_obj = copy.deepcopy(attendance_note_instance)
        form = AttendanceNoteForm(
            request.POST, instance=attendance_note_instance)

        if form.is_valid():
            changed_fields = form.changed_data
            changes = {}
            for field in changed_fields:
                if field == 'content':
                    changes[field] = {
                        'old_value': duplicate_obj.content.html,
                        'new_value': None
                    }
                else:
                    changes[field] = {
                        'old_value': str(getattr(duplicate_obj, field)),
                        'new_value': None
                    }
            form.save()

            for field in changed_fields:
                if field == 'content':
                    changes[field]['new_value'] = attendance_note_instance.content.html
                else:
                    changes[field]['new_value'] = str(
                        getattr(attendance_note_instance, field))

            create_modification(
                user=request.user,
                modified_obj=attendance_note_instance,
                changes=changes
            )
            messages.success(request, 'Successfully updated Attendance Note.')
            return redirect('attendance_note_view', attendance_note_instance.file_number)
        else:
            error_message = 'Form is not valid. Please correct the errors:'
            for field, errors in form.errors.items():
                error_message += f'\n{field}: {", ".join(errors)}'
            messages.error(request, error_message)
    else:
        form = AttendanceNoteForm(instance=attendance_note_instance)

    return render(request, 'edit_models.html', {'form': form, 'title': 'Attendance Note', 'file_number': attendance_note_instance.file_number.file_number})


@login_required
def correspondence_view(request, file_number):
    letter_form = LetterHalfForm()
    file_number_id = WIP.objects.filter(file_number=file_number).first().id
    emails = MatterEmails.objects.filter(
        file_number=file_number_id).order_by('-time')
    letters = MatterLetters.objects.filter(
        file_number=file_number_id).order_by('-date')
    return render(request, 'correspondence.html', {'letter_form': letter_form, 'file_number': file_number,
                                                   'emails': emails, 'letters': letters})


@login_required
def add_letter(request, file_number):
    if request.method == 'POST':
        request_post_copy = request.POST.copy()
        file_number_id = WIP.objects.filter(file_number=file_number).first().id
        request_post_copy['file_number'] = file_number_id
        request_post_copy['created_by'] = request.user
        form = LetterForm(request_post_copy)
        if form.is_valid():
            form.save()
            messages.success(request, 'Letter successfully added.')
            return redirect('correspondence_view', file_number=file_number)
        else:
            error_message = 'Form is not valid. Please correct the errors:'
            for field, errors in form.errors.items():
                error_message += f'\n{field}: {", ".join(errors)}'
            messages.error(request, error_message)
    else:
        messages.error(request, 'Invalid request method.')

    return redirect('correspondence_view', file_number=file_number)


@login_required
def edit_letter(request, id):

    letter_instance = get_object_or_404(MatterLetters, pk=id)

    if request.method == 'POST':
        duplicate_obj = copy.deepcopy(letter_instance)
        form = LetterForm(request.POST, instance=letter_instance)
        if form.is_valid():
            changed_fields = form.changed_data
            changes = {}
            for field in changed_fields:
                changes[field] = {
                    'old_value': str(getattr(duplicate_obj, field)),
                    'new_value': None
                }
            form.save()

            for field in changed_fields:
                changes[field]['new_value'] = getattr(letter_instance, field)

            create_modification(
                user=request.user,
                modified_obj=letter_instance,
                changes=changes
            )
            messages.success(request, 'Successfully updated Letter.')
            return redirect('correspondence_view', letter_instance.file_number)
        else:
            error_message = 'Form is not valid. Please correct the errors:'
            for field, errors in form.errors.items():
                error_message += f'\n{field}: {", ".join(errors)}'
            messages.error(request, error_message)
    else:
        form = LetterForm(instance=letter_instance)

    return render(request, 'edit_models.html', {'form': form, 'title': 'Letter', 'file_number': letter_instance.file_number.file_number})


@login_required
def download_sowc(request, file_number):
    file = WIP.objects.filter(file_number=file_number).first()
    file_number_id = file.id
    emails = MatterEmails.objects.filter(file_number=file_number_id)
    attendance_notes = MatterAttendanceNotes.objects.filter(
        file_number=file_number_id)
    letters = MatterLetters.objects.filter(file_number=file_number_id)

    """
    {date, time, fee_earner, Description, Unit(s), Amount}
    """
    rows = []

    for note in attendance_notes:
        date = note.date.strftime('%d/%m/%Y')
        time = note.start_time.strftime('%H:%M')
        fee_earner = note.person_attended.username if note.person_attended != None else ''
        note_charge_status = " (N/C)" if not note.is_charged else ""
        desc = f"Attendance Note{note_charge_status} - {note.subject_line} from {note.start_time.strftime(
            '%I:%M %p')} to {note.finish_time.strftime('%I:%M %p')}"
        units = note.unit
        amount = ((note.person_attended.hourly_rate.hourly_amount/10) * units) if note.person_attended != None else (
            (note.file_number.fee_earner.hourly_rate.hourly_amount/10) * units)
        row = [date, time, fee_earner, desc, units, amount]
        rows.append(row)

    for email in emails:

        date = email.time.date().strftime('%d/%m/%Y')
        time = email.time.astimezone(
            timezone.get_current_timezone()).time().strftime('%H:%M')
        fee_earner = email.fee_earner.username if email.fee_earner != None else ''
        receiver = json.loads(email.receiver)
        sender = json.loads(email.sender)
        to_or_from = f"Email to {receiver[0]['emailAddress']['name']}" if email.is_sent else f"Perusal of email from {sender['emailAddress']['name']}"
        desc = to_or_from + f" @ {time}"
        units = email.units
        amount = ((email.fee_earner.hourly_rate.hourly_amount/10) * units) if email.fee_earner != None else (
            (email.file_number.fee_earner.hourly_rate.hourly_amount/10) * units)
        row = [date, time, fee_earner, desc, units, amount]
        rows.append(row)

    for letter in letters:
        date = letter.date.strftime('%d/%m/%Y')
        time = None
        fee_earner = letter.person_attended.username if letter.person_attended != None else ''
        to_or_from = f'Letter to {letter.to_or_from}' if letter.sent else f'Letter from {letter.to_or_from}'
        desc = f'{to_or_from} - {letter.subject_line}'
        units = 1
        amount = ((letter.person_attended.hourly_rate.hourly_amount/10) * units) if letter.person_attended != None else (
            (letter.file_number.fee_earner.hourly_rate.hourly_amount/10) * units)
        row = [date, time, fee_earner, desc, units, amount]
        rows.append(row)

    def sort_rows(rows):
        def get_sort_key(row):
            # Handling empty dates
            date_str = row[0] if row[0] else '01/01/0001'
            time_str = row[1] if row[1] else '00:00'
            date_time_str = f"{date_str} {time_str}"
            date_time = datetime.strptime(date_time_str, '%d/%m/%Y %H:%M')
            return date_time

        sorted_rows = sorted(rows, key=get_sort_key)
        return sorted_rows
    sorted_rows = sort_rows(rows)

    distinct_fee_earners = set(row[2] for row in rows)
    first_date = sorted_rows[0][0] if sorted_rows else None
    last_date = sorted_rows[-1][0] if sorted_rows else None

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="({file_number}) Schedule of Work and Costs from {first_date} to {last_date}.csv"'

    writer = csv.writer(response)

    writer.writerow(['', '', f'Client Name: {file.client1.name} Matter:{
                    file.matter_description}[{file.file_number}]'])
    writer.writerow(['', '', f'Schedule of Work and Costs from {
                    first_date} to {last_date}'])

    for fee_earner in distinct_fee_earners:
        user = CustomUser.objects.filter(username=fee_earner).first()
        if user != None:
            writer.writerow(
                ['', '', f'({user.first_name} {user.last_name}) {user.username} rate GBP{user.hourly_rate.hourly_amount} + VAT per hour, 6 minutes = 1 unit '])
    writer.writerow([])
    writer.writerow(['Date', 'Fee Earner', 'Description', 'Unit(s)', 'Amount'])
    for row in sorted_rows:
        writer.writerow([row[0], row[2], row[3], row[4], row[5]])
    writer.writerow([])

    sum_start_row = 4 + len(distinct_fee_earners) + 1
    sum_end_row = sum_start_row + len(sorted_rows)
    total_cost_row = sum_end_row + 1
    writer.writerow(['', '', 'Total Costs', '',
                    f'=sum(E{sum_start_row}:E{sum_end_row})'])
    writer.writerow(
        ['', '', f'VAT @{CURRENT_VAT_RATE_PERCENT}%', '', f'={CURRENT_VAT_RATE}*E{total_cost_row}'])
    writer.writerow(['', '', 'Total Costs and VAT', '',
                    f'=sum(E{total_cost_row}:E{total_cost_row+1})'])

    return response


@login_required
def finance_view(request, file_number):
    file_obj = WIP.objects.filter(file_number=file_number).first()
    if not file_obj:
        messages.error(request, 'File not found.')
        return redirect('index')

    file_number_id = file_obj.id
    pmts_slips = PmtsSlips.objects.filter(
        file_number=file_number_id).order_by('-date')
    pmts_form = PmtsHalfForm()
    green_slips_form = LedgerAccountTransfersHalfForm()
    credit_note_form = CreditNoteHalfForm()
    credit_note_form.fields['invoice'].queryset = Invoices.objects.filter(
        file_number=file_number_id, state='F').order_by('-invoice_number')
    green_slips = LedgerAccountTransfers.objects.filter(
        Q(file_number_from=file_number_id) | Q(file_number_to=file_number_id)).order_by('-date')
    invoices = Invoices.objects.filter(
        file_number=file_number_id).order_by('-date')
    credit_notes = CreditNote.objects.filter(
        file_number=file_number_id
    ).select_related('invoice', 'created_by', 'approved_by').order_by('-date', '-timestamp')

    credit_notes_by_invoice = {}
    approved_credit_totals = {}
    status_labels = dict(CreditNote.STATUSES)
    credit_notes_data = []
    for credit_note in credit_notes:
        credit_notes_by_invoice.setdefault(credit_note.invoice_id, []).append(credit_note)
        if credit_note.status == 'F':
            approved_credit_totals[credit_note.invoice_id] = approved_credit_totals.get(
                credit_note.invoice_id, Decimal('0')
            ) + credit_note.amount
        net_amount, vat_amount, gross_amount = calculate_credit_note_breakdown(
            credit_note.amount)

        credit_notes_data.append({
            'id': credit_note.id,
            'date': credit_note.date.strftime('%d/%m/%Y'),
            'invoice_number': credit_note.invoice.invoice_number,
            'amount': gross_amount,
            'net_amount': net_amount,
            'vat_amount': vat_amount,
            'reason': credit_note.reason,
            'status': credit_note.status,
            'status_display': status_labels.get(credit_note.status, credit_note.status),
            'created_by': credit_note.created_by,
            'approved_by': credit_note.approved_by,
            'approved_on': credit_note.approved_on,
            'can_review': request.user.is_manager and credit_note.status == 'P',
            'can_edit': (
                (credit_note.status == 'P' and (
                    credit_note.created_by_id == request.user.id or request.user.is_manager
                )) or
                (credit_note.status == 'F' and request.user.is_manager)
            ),
        })

    invoices_data = []

    total_invoices = Decimal('0')
    total_out = Decimal('0')
    total_approved_credit_notes = Decimal('0')
    for invoice in invoices:

        our_costs = invoice.our_costs

        costs = ast.literal_eval(our_costs) if type(
            our_costs) != type([]) else our_costs
        total_cost_invoice = Decimal('0')

        our_costs_desc_pre = invoice.our_costs_desc
        our_costs_desc = ast.literal_eval(our_costs_desc_pre) if type(
            our_costs_desc_pre) != type([]) else our_costs_desc_pre
        costs_display = "<div>"
        for i in range(len(costs)):
            total_cost_invoice = total_cost_invoice + Decimal(costs[i])
            costs_display = costs_display + \
                f"<b>{our_costs_desc[i]}</b>: £{costs[i]}<br>"
        _, vat_inv, total_cost_and_vat = calculate_invoice_total_with_vat(invoice)
        costs_display = costs_display + \
            f"Add VAT @{CURRENT_VAT_RATE_PERCENT}%: £{round(vat_inv, 2)}<br>"
        total_cost_and_vat = round(total_cost_and_vat, 2)
        costs_display = costs_display + \
            f"<b>Total Costs and VAT:</b> £{total_cost_and_vat}<br>"
        costs_display = costs_display + "</div>"

        blue_slips_display = "<div class='mt-2'><h5 class='text-xl font-medium' >Blues Slips attached</h5>"
        total_blue_slips = 0
        if invoice.moa_ids.exists():
            for slip in invoice.moa_ids.all():
                if isinstance(slip.amount_invoiced, str):
                    amount_invoiced = json.loads(slip.amount_invoiced)
                elif isinstance(slip.amount_invoiced, (bytes, bytearray)):
                    amount_invoiced = json.loads(
                        slip.amount_invoiced.decode('utf-8'))
                elif isinstance(slip.amount_invoiced, dict):
                    amount_invoiced = slip.amount_invoiced
                else:
                    raise ValueError(
                        "Unsupported type for slip.amount_invoiced")

                date = slip.date.strftime('%d/%m/%Y')
                amt = amount_invoiced[f"{invoice.id}"]['amt_invoiced']
                total_blue_slips = total_blue_slips + Decimal(amt)
                blue_slips_display = blue_slips_display + \
                    f"Payment from {slip.pmt_person} of <b>£{amt}</b> on <b>{date}</b><br>"
            blue_slips_display = blue_slips_display + \
                f"<b>Total Blue Slips:</b> £{round(total_blue_slips, 2)}<br>"
        else:
            blue_slips_display = blue_slips_display + "No Blue Slips Attached"

        blue_slips_display = blue_slips_display + "</div>"

        pink_slips_display = "<div><h5 class='text-xl font-medium' >Pink Slips attached</h5>"
        total_pink_slips = 0
        if invoice.disbs_ids.exists():
            for slip in invoice.disbs_ids.all():
                date = slip.date.strftime('%d/%m/%Y')
                total_pink_slips = total_pink_slips + slip.amount
                pink_slips_display = pink_slips_display + \
                    f"Payment to {slip.pmt_person} of £{
                        slip.amount} on {date}<br>"
            pink_slips_display = pink_slips_display + \
                f"<b>Total Pink Slips:</b> £{total_pink_slips}<br>"
        else:
            pink_slips_display = pink_slips_display + "No Pink Slips Attached"

        pink_slips_display = pink_slips_display + "</div>"

        green_slips_display = "<div><h5 class='text-xl font-medium' >Green Slips attached</h5>"
        total_green_slips = 0
        if invoice.green_slip_ids.exists():
            for slip in invoice.green_slip_ids.all():
                date = slip.date.strftime('%d/%m/%Y')
                if slip.file_number_from.file_number == file_number:
                    total_green_slips = total_green_slips - slip.amount
                    green_slips_display = green_slips_display + \
                        f"Transfer to {slip.file_number_to} of £{
                            slip.amount} on {date}<br>"
                else:

                    if isinstance(slip.amount_invoiced_to, str):
                        amount_invoiced = json.loads(slip.amount_invoiced_to)
                    elif isinstance(slip.amount_invoiced_to, (bytes, bytearray)):
                        amount_invoiced = json.loads(
                            slip.amount_invoiced_to.decode('utf-8'))
                    elif isinstance(slip.amount_invoiced_to, dict):
                        amount_invoiced = slip.amount_invoiced_to
                    else:
                        raise ValueError(
                            "Unsupported type for slip.amount_invoiced_to")

                    date = slip.date.strftime('%d/%m/%Y')
                    amt = amount_invoiced[f"{invoice.id}"]['amt_invoiced']

                    total_green_slips = total_green_slips + Decimal(amt)
                    green_slips_display = green_slips_display + \
                        f"Transfer from {slip.file_number_from} of £{
                            amt} on {date}<br>"
            green_slips_display = green_slips_display + \
                f"<b>Total Green Slips:</b> £{total_green_slips}<br>"
        else:
            green_slips_display = green_slips_display + "No Green Slips Attached"
        green_slips_display = green_slips_display + "</div>"

        cash_allocated_slips_display = "<div class='mt-2'><h5 class='text-xl font-medium' >Blue Slips attached (after invoice creation)</h5>"
        total_cash_allocated_slips = 0
        if invoice.cash_allocated_slips.exists():
            for slip in invoice.cash_allocated_slips.all():
                if isinstance(slip.amount_allocated, str):
                    amount_invoiced = json.loads(slip.amount_allocated)
                elif isinstance(slip.amount_allocated, (bytes, bytearray)):
                    amount_invoiced = json.loads(
                        slip.amount_allocated.decode('utf-8'))
                elif isinstance(slip.amount_allocated, dict):
                    amount_invoiced = slip.amount_allocated
                else:
                    raise ValueError(
                        "Unsupported type for slip.amount_invoiced")

                date = slip.date.strftime('%d/%m/%Y')
                invoice_id_str = f'{invoice.id}'
                if invoice_id_str in amount_invoiced:
                    amt = amount_invoiced[invoice_id_str]
                    total_cash_allocated_slips = total_cash_allocated_slips + \
                        Decimal(amt)
                    cash_allocated_slips_display = cash_allocated_slips_display + \
                        f"Payment from {slip.pmt_person} of <b>£{amt}</b> on <b>{date}</b><br>"

            cash_allocated_slips_display = cash_allocated_slips_display + \
                f"<b>Total Allocated Slips:</b> £{total_cash_allocated_slips}<br>"
        else:
            cash_allocated_slips_display = cash_allocated_slips_display + \
                "No Slips Attached After Invoice Creation"

        cash_allocated_slips_display = cash_allocated_slips_display + "</div>"

        invoice_credit_notes = credit_notes_by_invoice.get(invoice.id, [])
        approved_credit_total = approved_credit_totals.get(invoice.id, Decimal('0'))
        total_approved_credit_notes += approved_credit_total
        credit_notes_display = "<div><h5 class='text-xl font-medium'>Credit Notes</h5>"
        if invoice_credit_notes:
            for note in invoice_credit_notes:
                status_display = status_labels.get(note.status, note.status)
                net_amount, vat_amount, gross_amount = calculate_credit_note_breakdown(
                    note.amount)
                approved_meta = ""
                if note.approved_by:
                    approved_meta = (
                        f" (approved by {note.approved_by} on {note.approved_on.strftime('%d/%m/%Y %H:%M')})"
                        if note.approved_on else f" (approved by {note.approved_by})"
                    )
                credit_notes_display = credit_notes_display + (
                    f"{note.date.strftime('%d/%m/%Y')} - Ex VAT £{net_amount}, VAT £{vat_amount}, "
                    f"Total £{gross_amount} - {status_display}{approved_meta}<br>"
                )
            credit_notes_display = credit_notes_display + \
                f"<b>Total Final Credit Notes:</b> £{round(approved_credit_total, 2)}<br>"
        else:
            credit_notes_display = credit_notes_display + "No Credit Notes Issued"
        credit_notes_display = credit_notes_display + "</div>"

        balance = (total_cost_and_vat + total_pink_slips) - \
            total_green_slips - (total_blue_slips + total_cash_allocated_slips) - approved_credit_total

        if balance >= 0:
            total_due_display = f"<div><b>Total Due: </b> £{round(balance, 2)}<br></div>"
        else:
            balance = balance * -1
            total_due_display = f"<div><b>Balance remaining on account:</b> £{round(balance, 2)}<br></div>"

        effective_due_left = get_effective_invoice_due(invoice, approved_credit_total)

        data = {'id': invoice.id,
                'state': invoice.state,
                'number': invoice.invoice_number,
                'total_cost_and_vat': total_cost_and_vat,
                'desc': invoice.description,
                'date': invoice.date.strftime('%d/%m/%Y'),
                'costs': mark_safe(costs_display),
                'pink_slips': mark_safe(pink_slips_display),
                'blue_slips': mark_safe(blue_slips_display),
                'green_slips': mark_safe(green_slips_display),
                'cash_allocated_slips': mark_safe(cash_allocated_slips_display),
                'credit_notes': mark_safe(credit_notes_display),
                'total_due': mark_safe(total_due_display),
                'total_due_left': effective_due_left,
                }

        invoices_data.append(data)

        total_invoices = total_invoices + total_cost_and_vat

    total_out = total_out + total_invoices
    total_in = Decimal('0')
    for slip in pmts_slips:
        if slip.is_money_out == True:
            total_out = total_out + slip.amount
        else:
            total_in = total_in + slip.amount

    for slip in green_slips:
        if slip.file_number_from.file_number == slip.file_number_to.file_number:
            continue
        if slip.file_number_from.file_number == file_number:
            total_out = total_out + slip.amount

        else:
            total_in = total_in + slip.amount
    total_in = total_in + total_approved_credit_notes
    total_in = round(total_in, 2)
    total_out = round(total_out, 2)
    total_balance = round(total_in - total_out, 2)

    colors = {'draft_invoice': "#F9EBDF",
              "invoice": "#FFFCC9",
              'credit_note': "#FFEAEA",
              'green': "#90EE90",
              'temp': "#CCD1D1"}

    return render(request, 'finances.html', {'total_monies_in': total_in, 'total_monies_out': total_out, 'total_monies_balance': total_balance,
                                             'pmts_slips': pmts_slips, 'file_number': file_number,
                                             'colors': colors,
                                             'pmts_form': pmts_form, 'green_slip_form': green_slips_form,
                                             'green_slips': green_slips, 'invoices': invoices_data,
                                             'credit_notes': credit_notes_data, 'credit_note_form': credit_note_form,
                                             'current_vat_rate_percent': CURRENT_VAT_RATE_PERCENT})


@login_required
def add_credit_note(request, file_number):
    if request.method == 'POST':
        file_obj = WIP.objects.filter(file_number=file_number).first()
        if not file_obj:
            messages.error(request, 'File not found.')
            return redirect('index')

        request_post_copy = request.POST.copy()
        request_post_copy['file_number'] = file_obj.id
        form = CreditNoteHalfForm(request_post_copy)
        form.fields['invoice'].queryset = Invoices.objects.filter(
            file_number=file_obj.id, state='F'
        ).order_by('-invoice_number')
        if form.is_valid():
            credit_note = form.save(commit=False)
            if credit_note.invoice.file_number_id != file_obj.id:
                messages.error(request, 'Selected invoice does not belong to this matter.')
                return redirect('finance_view', file_number=file_number)
            if credit_note.amount <= 0:
                messages.error(request, 'Credit note amount must be greater than 0.')
                return redirect('finance_view', file_number=file_number)

            max_allowed_amount = get_effective_invoice_due(credit_note.invoice)
            if credit_note.amount > max_allowed_amount:
                messages.error(
                    request,
                    f'Credit note exceeds invoice due (£{max_allowed_amount}).'
                )
                return redirect('finance_view', file_number=file_number)

            credit_note.file_number = file_obj
            credit_note.created_by = request.user
            credit_note.status = 'P'
            credit_note.save()
            messages.success(
                request, 'Credit note submitted and is pending manager approval.')
            return redirect('finance_view', file_number=file_number)

        error_message = 'Form is not valid. Please correct the errors:'
        for field, errors in form.errors.items():
            error_message += f'\n{field}: {", ".join(errors)}'
        messages.error(request, error_message)
    else:
        messages.error(request, 'Invalid request method.')

    return redirect('finance_view', file_number=file_number)


@login_required
def approve_credit_note(request, id):
    credit_note = get_object_or_404(CreditNote, id=id)
    if not request.user.is_manager:
        messages.error(request, 'Only managers can approve credit notes.')
        return redirect('finance_view', file_number=credit_note.file_number.file_number)

    if credit_note.status != 'P':
        messages.info(request, 'This credit note has already been reviewed.')
        return redirect('finance_view', file_number=credit_note.file_number.file_number)

    max_allowed_amount = get_effective_invoice_due(credit_note.invoice)
    if credit_note.amount > max_allowed_amount:
        messages.error(
            request,
            f'Credit note cannot be approved because invoice due is £{max_allowed_amount}.'
        )
        return redirect('finance_view', file_number=credit_note.file_number.file_number)

    invoice = credit_note.invoice
    prev_invoice_due = Decimal(str(invoice.total_due_left or 0))
    new_invoice_due = prev_invoice_due - Decimal(str(credit_note.amount))
    if new_invoice_due < 0:
        new_invoice_due = Decimal('0')

    with transaction.atomic():
        invoice.total_due_left = new_invoice_due
        invoice.save(update_fields=['total_due_left'])

        old_status = credit_note.status
        credit_note.status = 'F'
        credit_note.approved_by = request.user
        credit_note.approved_on = timezone.now()
        credit_note.save(update_fields=['status', 'approved_by', 'approved_on'])

        create_modification(
            request.user,
            invoice,
            {
                'total_due_left': {
                    'old_value': str(prev_invoice_due),
                    'new_value': str(invoice.total_due_left)
                },
                'reason': f'Approved Credit Note {credit_note.id}'
            }
        )

        create_modification(
            request.user,
            credit_note,
            {
                'status': {'old_value': old_status, 'new_value': 'F'},
                'approved_by': {'old_value': None, 'new_value': str(request.user)},
                'approved_on': {'old_value': None, 'new_value': str(credit_note.approved_on)},
            }
        )
    messages.success(request, 'Credit note approved and finalized.')
    return redirect('finance_view', file_number=credit_note.file_number.file_number)


@login_required
def reject_credit_note(request, id):
    credit_note = get_object_or_404(CreditNote, id=id)
    if not request.user.is_manager:
        messages.error(request, 'Only managers can reject credit notes.')
        return redirect('finance_view', file_number=credit_note.file_number.file_number)

    if credit_note.status != 'P':
        messages.info(request, 'This credit note has already been reviewed.')
        return redirect('finance_view', file_number=credit_note.file_number.file_number)

    old_status = credit_note.status
    credit_note.status = 'R'
    credit_note.approved_by = request.user
    credit_note.approved_on = timezone.now()
    credit_note.save(update_fields=['status', 'approved_by', 'approved_on'])

    create_modification(
        request.user,
        credit_note,
        {
            'status': {'old_value': old_status, 'new_value': 'R'},
            'approved_by': {'old_value': None, 'new_value': str(request.user)},
            'approved_on': {'old_value': None, 'new_value': str(credit_note.approved_on)},
        }
    )
    messages.success(request, 'Credit note rejected.')
    return redirect('finance_view', file_number=credit_note.file_number.file_number)


@login_required
def edit_credit_note(request, id):
    credit_note = get_object_or_404(CreditNote, id=id)

    can_edit_pending = credit_note.status == 'P' and (
        credit_note.created_by_id == request.user.id or request.user.is_manager
    )
    can_edit_approved = credit_note.status == 'F' and request.user.is_manager
    if not (can_edit_pending or can_edit_approved):
        messages.error(request, 'You do not have permission to edit this credit note.')
        return redirect('finance_view', file_number=credit_note.file_number.file_number)

    if request.method == 'POST':
        duplicate_obj = copy.deepcopy(credit_note)
        form = CreditNoteHalfForm(request.POST, instance=credit_note)
        form.fields['invoice'].queryset = Invoices.objects.filter(
            file_number=credit_note.file_number_id, state='F'
        ).order_by('-invoice_number')
        if form.is_valid():
            edited_credit_note = form.save(commit=False)
            edited_credit_note.file_number = credit_note.file_number

            if edited_credit_note.amount <= 0:
                messages.error(request, 'Credit note amount must be greater than 0.')
                return redirect('edit_credit_note', id=credit_note.id)

            if edited_credit_note.status == 'F':
                max_allowed_amount = get_invoice_max_credit_amount(
                    edited_credit_note.invoice, excluded_credit_note_id=edited_credit_note.id)
            else:
                max_allowed_amount = get_effective_invoice_due(edited_credit_note.invoice)

            if edited_credit_note.amount > max_allowed_amount:
                messages.error(
                    request,
                    f'Credit note exceeds invoice due (£{max_allowed_amount}).'
                )
                return redirect('edit_credit_note', id=credit_note.id)

            with transaction.atomic():
                if duplicate_obj.status == 'F':
                    old_invoice = Invoices.objects.select_for_update().filter(
                        id=duplicate_obj.invoice_id
                    ).first()
                    new_invoice = Invoices.objects.select_for_update().filter(
                        id=edited_credit_note.invoice_id
                    ).first()

                    old_invoice_prev_due = Decimal(str(old_invoice.total_due_left or 0))
                    old_invoice.total_due_left = old_invoice_prev_due + \
                        Decimal(str(duplicate_obj.amount))
                    old_invoice.save(update_fields=['total_due_left'])

                    if old_invoice.id == new_invoice.id:
                        new_invoice_prev_due = Decimal(str(old_invoice.total_due_left or 0))
                    else:
                        new_invoice_prev_due = Decimal(str(new_invoice.total_due_left or 0))

                    new_invoice_due = new_invoice_prev_due - \
                        Decimal(str(edited_credit_note.amount))
                    if new_invoice_due < 0:
                        new_invoice_due = Decimal('0')
                    new_invoice.total_due_left = new_invoice_due
                    new_invoice.save(update_fields=['total_due_left'])

                    create_modification(
                        user=request.user,
                        modified_obj=old_invoice,
                        changes={
                            'total_due_left': {
                                'old_value': str(old_invoice_prev_due),
                                'new_value': str(old_invoice.total_due_left)
                            },
                            'reason': f'Edited Credit Note {edited_credit_note.id} (reverse old amount)'
                        }
                    )
                    create_modification(
                        user=request.user,
                        modified_obj=new_invoice,
                        changes={
                            'total_due_left': {
                                'old_value': str(new_invoice_prev_due),
                                'new_value': str(new_invoice.total_due_left)
                            },
                            'reason': f'Edited Credit Note {edited_credit_note.id} (apply new amount)'
                        }
                    )

                edited_credit_note.save()

                changed_fields = form.changed_data
                changes = {}
                for field in changed_fields:
                    changes[field] = {
                        'old_value': str(getattr(duplicate_obj, field)),
                        'new_value': str(getattr(edited_credit_note, field))
                    }
                if changes:
                    create_modification(
                        user=request.user,
                        modified_obj=edited_credit_note,
                        changes=changes
                    )
            messages.success(request, 'Credit note updated.')
            return redirect('finance_view', file_number=edited_credit_note.file_number.file_number)
        else:
            error_message = 'Form is not valid. Please correct the errors:'
            for field, errors in form.errors.items():
                error_message += f'\n{field}: {", ".join(errors)}'
            messages.error(request, error_message)
    else:
        form = CreditNoteHalfForm(instance=credit_note)
        form.fields['invoice'].queryset = Invoices.objects.filter(
            file_number=credit_note.file_number_id, state='F'
        ).order_by('-invoice_number')

    return render(request, 'edit_models.html', {
        'form': form,
        'title': 'Edit Credit Note',
        'file_number': credit_note.file_number.file_number
    })


@login_required
def add_pink_slip(request, file_number):
    if request.method == 'POST':
        request_post_copy = request.POST.copy()
        file_number_id = WIP.objects.filter(file_number=file_number).first().id
        request_post_copy['file_number'] = file_number_id
        request_post_copy['is_money_out'] = True
        request_post_copy['balance_left'] = request_post_copy['amount']
        request_post_copy['created_by'] = request.user
        form = PmtsForm(request_post_copy)
        if form.is_valid():
            form.save()
            messages.success(request, 'Pink Slip successfully added.')
            return redirect('finance_view', file_number=file_number)
        else:
            error_message = 'Form is not valid. Please correct the errors:'
            for field, errors in form.errors.items():
                error_message += f'\n{field}: {", ".join(errors)}'
            messages.error(request, error_message)
    else:
        messages.error(request, 'Invalid request method.')

    return redirect('finance_view', file_number=file_number)


@login_required
def add_blue_slip(request, file_number):
    if request.method == 'POST':
        request_post_copy = request.POST.copy()
        file_number_id = WIP.objects.filter(file_number=file_number).first().id
        request_post_copy['file_number'] = file_number_id
        request_post_copy['is_money_out'] = False
        request_post_copy['balance_left'] = request_post_copy['amount']
        request_post_copy['created_by'] = request.user
        form = PmtsForm(request_post_copy)
        if form.is_valid():
            form.save()
            messages.success(request, 'Blue Slip successfully added.')
            return redirect('finance_view', file_number=file_number)
        else:
            error_message = 'Form is not valid. Please correct the errors:'
            for field, errors in form.errors.items():
                error_message += f'\n{field}: {", ".join(errors)}'
            messages.error(request, error_message)
    else:
        messages.error(request, 'Invalid request method.')

    return redirect('finance_view', file_number=file_number)


@login_required
def add_green_slip(request, file_number):
    if request.method == 'POST':
        request_post_copy = request.POST.copy()
        file_number_id = WIP.objects.filter(file_number=file_number).first().id
        request_post_copy['file_number_from'] = file_number_id

        request_post_copy['balance_left_from'] = request_post_copy['amount']
        request_post_copy['balance_left_to'] = request_post_copy['amount']
        request_post_copy['created_by'] = request.user
        form = LedgerAccountTransfersForm(request_post_copy)
        if form.is_valid():
            form.save()
            messages.success(request, 'Green Slip successfully added.')
            return redirect('finance_view', file_number=file_number)
        else:
            error_message = 'Form is not valid. Please correct the errors:'
            for field, errors in form.errors.items():
                error_message += f'\n{field}: {", ".join(errors)}'
            messages.error(request, error_message)
    else:
        messages.error(request, 'Invalid request method.')

    return redirect('finance_view', file_number=file_number)


@login_required
def edit_pmts_slip(request, id):

    pmt_instance = get_object_or_404(PmtsSlips, pk=id)

    if request.method == 'POST':
        duplicate_obj = copy.deepcopy(pmt_instance)
        post_copy = request.POST.copy()

        form = PmtsForm(request.POST, instance=pmt_instance)
        if form.is_valid():
            changed_fields = form.changed_data
            changes = {}
            for field in changed_fields:
                changes[field] = {
                    'old_value': str(getattr(duplicate_obj, field)),
                    'new_value': None
                }
            form.save()

            for field in changed_fields:
                changes[field]['new_value'] = str(getattr(pmt_instance, field))

            create_modification(
                user=request.user,
                modified_obj=pmt_instance,
                changes=changes
            )
            messages.success(request, 'Successfully updated Slip.')
            return redirect('finance_view', pmt_instance.file_number)
        else:
            error_message = 'Form is not valid. Please correct the errors:'
            for field, errors in form.errors.items():
                error_message += f'\n{field}: {", ".join(errors)}'
            messages.error(request, error_message)
    else:
        form = PmtsForm(instance=pmt_instance)

    return render(request, 'edit_models.html', {'form': form, 'title': 'Slip', 'file_number': pmt_instance.file_number.file_number})


@login_required
def download_pmts_slip(request, id):
    slip = get_object_or_404(PmtsSlips, id=id)

    # Render the template with the provided context
    html_string = render_to_string(
        'download_templates/pmts_slip.html', {"slip": slip})

    # Generate PDF from the rendered HTML using WeasyPrint
    pdf_file = HTML(string=html_string).write_pdf()

    return HttpResponse(pdf_file, content_type='application/pdf')


@login_required
def edit_green_slip(request, id):

    pmt_instance = get_object_or_404(LedgerAccountTransfers, pk=id)

    if request.method == 'POST':
        duplicate_obj = copy.deepcopy(pmt_instance)
        form = LedgerAccountTransfersForm(request.POST, instance=pmt_instance)
        if form.is_valid():
            changed_fields = form.changed_data
            changes = {}
            for field in changed_fields:
                changes[field] = {
                    'old_value': str(getattr(duplicate_obj, field)),
                    'new_value': None
                }
            form.save()

            for field in changed_fields:
                changes[field]['new_value'] = str(getattr(pmt_instance, field))

            create_modification(
                user=request.user,
                modified_obj=pmt_instance,
                changes=changes
            )
            messages.success(request, 'Successfully updated Green Slip.')
            return redirect('finance_view', pmt_instance.file_number)
        else:
            error_message = 'Form is not valid. Please correct the errors:'
            for field, errors in form.errors.items():
                error_message += f'\n{field}: {", ".join(errors)}'
            messages.error(request, error_message)
    else:
        form = LedgerAccountTransfersForm(instance=pmt_instance)

    return render(request, 'edit_models.html', {'form': form, 'title': 'Edit Green Slip', 'file_number': pmt_instance.file_number_from.file_number})


@login_required
def download_green_slip(request, id):
    slip = get_object_or_404(LedgerAccountTransfers, id=id)

    # Render the template with the provided context
    html_string = render_to_string(
        'download_templates/green_slip.html', {"slip": slip})

    # Generate PDF from the rendered HTML using WeasyPrint
    pdf_file = HTML(string=html_string).write_pdf()

    return HttpResponse(pdf_file, content_type='application/pdf')


@login_required
def add_invoice(request, file_number):
    if request.method == 'POST':
        file_number_id = WIP.objects.filter(file_number=file_number).first().id
        request_post_copy = request.POST.copy()

        if request_post_copy['state'] == 'F':
            largest_invoice_number = Invoices.objects.aggregate(Max('invoice_number'))[
                'invoice_number__max']
            request_post_copy['invoice_number'] = largest_invoice_number+1

        if 'by_email' in request_post_copy:
            request_post_copy['by_email'] = True
        if 'by_post' in request_post_copy:
            request_post_copy['by_post'] = True

        request_post_copy['our_costs_desc'] = json.dumps(
            request.POST.getlist('our_costs_desc[]'))
        request_post_copy['our_costs'] = json.dumps(
            request.POST.getlist('our_costs[]'))

        total_costs = 0
        for cost in request.POST.getlist('our_costs[]'):
            total_costs = total_costs + Decimal(cost)
        vat_amount = round(total_costs * CURRENT_VAT_RATE, 2)
        total_costs_and_vat = vat_amount + total_costs

        request_post_copy['created_by'] = request.user
        request_post_copy['file_number'] = file_number_id
        request_post_copy['vat'] = str(vat_amount)

        form = InvoicesForm(request_post_copy)

        if form.is_valid():

            invoice_instance = form.save(commit=False)
            invoice_instance.save()

            disbs_ids = [int(id_str)
                         for id_str in request.POST.getlist('pink_slips[]')]
            total_disbs = 0
            for id in disbs_ids:
                obj = PmtsSlips.objects.filter(id=id).first()
                total_disbs = total_disbs + obj.amount
                obj.amount_invoiced = json.dumps(str(obj.amount))
                obj.balance_left = 0
                obj.save()

            total_costs_and_disbs = total_costs_and_vat + total_disbs
            temp_costs = total_costs_and_disbs

            green_slips_ids = [int(id_str)
                               for id_str in request.POST.getlist('green_slips[]')]
            for id in green_slips_ids:
                obj = LedgerAccountTransfers.objects.filter(id=id).first()
                if obj.file_number_from.file_number == file_number:
                    obj.amount_invoiced_from = json.dumps(str(obj.amount))
                    obj.balance_left_from = 0
                else:
                    temp_costs = temp_costs - obj.balance_left_to
                    invoice_slip_obj = {str(invoice_instance.id): {
                        'amt_invoiced': str(obj.balance_left_to), 'balance_left': ''}}
                    if temp_costs < 0:
                        obj.balance_left_to = obj.balance_left_to - total_costs_and_disbs
                    elif temp_costs >= 0:
                        obj.balance_left_to = 0
                    invoice_slip_obj[str(invoice_instance.id)]['balance_left'] = str(
                        obj.balance_left_to)
                    prev_amount_invoiced_to_obj = json.loads(
                        obj.amount_invoiced_to) if obj.amount_invoiced_to != {} else {}
                    prev_amount_invoiced_to_obj.update(invoice_slip_obj)
                    obj.amount_invoiced_to = json.dumps(
                        prev_amount_invoiced_to_obj)
                    total_costs_and_disbs = temp_costs
                obj.save()

            moa_ids = [int(id_str)
                       for id_str in request.POST.getlist('blue_slips[]')]
            for id in moa_ids:
                obj = PmtsSlips.objects.filter(id=id).first()
                temp_costs = temp_costs - obj.balance_left
                invoice_slip_obj = {str(invoice_instance.id): {
                    'amt_invoiced': str(obj.balance_left), 'balance_left': ''}}
                if temp_costs < 0:
                    obj.balance_left = obj.balance_left - total_costs_and_disbs
                elif temp_costs >= 0:
                    obj.balance_left = 0

                invoice_slip_obj[str(invoice_instance.id)
                                 ]['balance_left'] = str(obj.balance_left)
                prev_amount_invoiced_to_obj = json.loads(
                    obj.amount_invoiced) if obj.amount_invoiced != {} else {}
                prev_amount_invoiced_to_obj.update(invoice_slip_obj)
                obj.amount_invoiced = json.dumps(prev_amount_invoiced_to_obj)
                total_costs_and_disbs = temp_costs
                obj.save()

            if temp_costs <= 0:
                invoice_instance.total_due_left = 0
            else:
                invoice_instance.total_due_left = temp_costs

            invoice_instance.disbs_ids.set(disbs_ids)
            invoice_instance.moa_ids.set(moa_ids)
            invoice_instance.green_slip_ids.set(green_slips_ids)

            invoice_instance.save()
            messages.success(request, f'Invoice {
                             invoice_instance.invoice_number} successfully added. ')
            return redirect('finance_view', file_number=file_number)
        else:
            error_message = f'Form is not valid. Please correct the errors:'
            for field, errors in form.errors.items():
                error_message += f'\n{field}: {", ".join(errors)}'
            messages.error(request, error_message)
    else:
        messages.error(request, 'Invalid request method.')

    return redirect('finance_view', file_number=file_number)


@login_required
def allocate_monies(request):
    if request.method == 'POST':

        amt_to_allocate_raw = request.POST['amt_to_allocate']
        invoice_num = request.POST['invoice_num']
        slip_id = request.POST['slip_id']

        invoice = Invoices.objects.filter(invoice_number=invoice_num).first()
        slip = PmtsSlips.objects.filter(id=slip_id).first()
        if not invoice or not slip:
            messages.error(request, 'Invoice or slip not found.')
            if invoice:
                return redirect('finance_view', file_number=invoice.file_number.file_number)
            return redirect('index')

        try:
            amt_to_allocate = Decimal(amt_to_allocate_raw)
        except Exception:
            messages.error(request, 'Please provide a valid amount to allocate.')
            return redirect('finance_view', file_number=invoice.file_number.file_number)

        if amt_to_allocate <= 0:
            messages.error(request, 'Amount to allocate must be greater than 0.')
            return redirect('finance_view', file_number=invoice.file_number.file_number)

        if amt_to_allocate > slip.balance_left:
            messages.error(request, 'Amount to allocate cannot exceed slip balance.')
            return redirect('finance_view', file_number=invoice.file_number.file_number)

        due_left = invoice.total_due_left
        approved_credit_total = get_invoice_approved_credit_total(invoice)
        effective_due_left = get_effective_invoice_due(invoice, approved_credit_total)
        if amt_to_allocate > effective_due_left:
            messages.error(
                request,
                f'Amount to allocate cannot exceed invoice due after credit notes (£{effective_due_left}).'
            )
            return redirect('finance_view', file_number=invoice.file_number.file_number)

        balance = due_left - amt_to_allocate

        # Store previous values for modification tracking
        prev_slip_amount_allocated = slip.amount_allocated
        prev_slip_balance_left = slip.balance_left

        already_allocated = json.loads(
            slip.amount_allocated) if slip.amount_allocated != {} else {}
        already_allocated.update({str(invoice.id): str(amt_to_allocate_raw)})
        slip.amount_allocated = json.dumps(already_allocated)

        # Calculate total allocated amount from the slip
        total_allocated = sum(Decimal(str(amt))
                              for amt in already_allocated.values())

        # Fix balance calculation: original amount - total allocated
        slip.balance_left = slip.amount - total_allocated

        invoice.cash_allocated_slips.add(slip.id)
        if balance <= 0:
            invoice.total_due_left = 0
        else:
            invoice.total_due_left = balance

        # Create modification record for invoice
        invoice_changes = {'prev_total_due_left': str(due_left),
                           'after_total_due_left': str(invoice.total_due_left),
                           'amount_allocated': str(amt_to_allocate),
                           'approved_credit_notes_total': str(approved_credit_total)}

        create_modification(
            user=request.user,
            modified_obj=invoice,
            changes=invoice_changes
        )

        # Create modification record for slip
        slip_changes = {'prev_amount_allocated': prev_slip_amount_allocated,
                        'after_amount_allocated': slip.amount_allocated,
                        'prev_balance_left': str(prev_slip_balance_left),
                        'after_balance_left': str(slip.balance_left),
                        'amount_allocated_to_invoice': str(amt_to_allocate),
                        'invoice_number': invoice_num}

        create_modification(
            user=request.user,
            modified_obj=slip,
            changes=slip_changes
        )

        slip.save()
        invoice.save()
        messages.success(
            request, f"£{amt_to_allocate} successfully allocated to Invoice {invoice_num}.")

    return redirect('finance_view', invoice.file_number.file_number)


@login_required
def download_invoice(request, id):

    invoice = Invoices.objects.filter(id=id).first()

    our_costs = invoice.our_costs

    costs = ast.literal_eval(our_costs) if type(
        our_costs) != type([]) else our_costs
    total_cost_invoice = 0

    file_details_display = f"<tr><td><b>Our Ref:</b>{
        invoice.file_number.file_number}</td><td></td></tr>"
    file_details_display = file_details_display + \
        f"<tr><td><b>Invoice No:</b>{
            invoice.invoice_number}</td><td></td></tr>"
    file_details_display = file_details_display + \
        f"<tr><td><b>Date:</b>{invoice.date.strftime(
            '%d/%m/%Y')}</td><td></td></tr>"
    file_details_display = file_details_display + \
        f"<tr><td>&nbsp;</td><td></td></tr>"
    file_details_display = file_details_display + \
        f"<tr><td><b>Private & Confidential</b></td><td></td></tr>"
    file_details_display = file_details_display + \
        f"""<tr><td class='d-flex flex-row'>
        <div class="me-4 " >{invoice.file_number.client1.name}<br>
        {invoice.file_number.client1.address_line1}<br>
        {invoice.file_number.client1.address_line2}<br>
        {invoice.file_number.client1.county}, {invoice.file_number.client1.postcode}
        </div>"""
    if invoice.file_number.client2:
        file_details_display = file_details_display + f"""
            <div class="border-start ps-4">{invoice.file_number.client2.name}<br>
            {invoice.file_number.client2.address_line1}<br>
            {invoice.file_number.client2.address_line2}<br>
            {invoice.file_number.client2.county}, {invoice.file_number.client2.postcode}
            </div>"""
    file_details_display = file_details_display + """ </td><td></td></tr>"""
    if invoice.payable_by == 'Client':
        payable_by = "&nbsp;"
    else:
        payable_by = invoice.payable_by
        payable_by = f"<tr><td><b>Payable by: </b>{
            payable_by}</td><td></td></tr>"

    file_details_display = file_details_display + payable_by
    if invoice.by_email == True and invoice.by_post == True:
        send_via = f'<b>By post and email to: </b>{
            invoice.file_number.client1.email}'
    elif invoice.by_email == True:
        send_via = f'<b>By email to: </b>{invoice.file_number.client1.email}'
    elif invoice.by_post == True:
        send_via = f'<b>By post</b>'
    else:
        send_via = ""

    file_details_display = file_details_display + \
        f"<tr><td><b>Re: </b>{invoice.file_number.matter_description}</td><td></td></tr>"
    file_details_display = file_details_display + \
        f"<tr><td colspan='2' style='text-align: right;'>{send_via}</td></tr>"

    desc_and_cost_display = "<tr><td>&nbsp;</td><td></td></tr>"
    desc_and_cost_display = desc_and_cost_display + \
        f"<tr><td style='text-align: justify; text-justify: inter-word;' colspan='2'>{
            invoice.description}</td></tr>"
    desc_and_cost_display = desc_and_cost_display + \
        "<tr><td>&nbsp;</td><td></td></tr>"

    our_costs_desc_pre = invoice.our_costs_desc
    our_costs_desc = ast.literal_eval(our_costs_desc_pre) if type(
        our_costs_desc_pre) != type([]) else our_costs_desc_pre
    costs_display = ""
    for i in range(len(costs)):
        total_cost_invoice = total_cost_invoice + Decimal(costs[i])
        costs_display = costs_display + \
            f"<tr><td><b>{
                our_costs_desc[i]}</b>:</td><td style='text-align: center;"
        if i == 0:
            costs_display = costs_display + f"border-top: solid; border-top-width: thin;'"
        else:
            costs_display = costs_display + "'"
        costs_display = costs_display + \
            f">£{round(Decimal(costs[i]), 2)}</td></tr>"
    _, vat_inv, total_cost_and_vat = calculate_invoice_total_with_vat(invoice)
    costs_display = costs_display + \
        f"<tr><td >Add VAT @{CURRENT_VAT_RATE_PERCENT}%:</td><td style='text-align: center; border-top: solid; border-top-width: thin;'>£{
            round(vat_inv, 2)}</td></tr>"
    total_cost_and_vat = round(total_cost_and_vat, 2)
    costs_display = costs_display + \
        f"<tr><td ><b>Total Costs and VAT:</b></td><td style='text-align: center; border-bottom: solid; border-bottom-width: thin; border-top: solid; border-top-width: thin;'>£{
            total_cost_and_vat}</td></tr>"
    costs_display = costs_display + f"<tr><td>&nbsp;</td><td></td></tr>"

    desc_and_cost_display = desc_and_cost_display + costs_display

    total_pink_slips = 0
    if invoice.disbs_ids.exists():
        pink_slips_display = "<tr><td colspan='2'><b>Add Disbursement</b></td><tr>"
        for slip in invoice.disbs_ids.all():
            date = slip.date.strftime('%d/%m/%Y')
            pink_slips_display = pink_slips_display + \
                f"<tr><td>{
                    slip.description} - {date}</td><td style='text-align: center;"
            if total_pink_slips == 0:
                pink_slips_display = pink_slips_display + \
                    "border-top: solid; border-top-width: thin;'"
            else:
                pink_slips_display = pink_slips_display + "'"

            total_pink_slips = total_pink_slips + slip.amount
            pink_slips_display = pink_slips_display + \
                f">£{slip.amount}</td></tr>"
        pink_slips_display = pink_slips_display + \
            f"<tr><td><b>Total Disbursements:</b></td><td style='text-align: center; border-bottom: solid; border-bottom-width: thin; border-top: solid; border-top-width: thin;'>£{
                total_pink_slips}</td></tr>"

        pink_slips_display = pink_slips_display + f"<tr><td>&nbsp;</td><td></td></tr>"
    else:
        pink_slips_display = ''

    total_blue_slips = 0
    if invoice.moa_ids.exists():
        blue_slips_display = "<tr><td colspan='2'><b>Less Monies Received</b></td></tr>"
        for slip in invoice.moa_ids.all():

            if isinstance(slip.amount_invoiced, str):
                amount_invoiced = json.loads(slip.amount_invoiced)
            elif isinstance(slip.amount_invoiced, (bytes, bytearray)):
                amount_invoiced = json.loads(
                    slip.amount_invoiced.decode('utf-8'))
            elif isinstance(slip.amount_invoiced, dict):
                amount_invoiced = slip.amount_invoiced
            else:
                raise ValueError("Unsupported type for slip.amount_invoiced")
            date = slip.date.strftime('%d/%m/%Y')
            amt = amount_invoiced[f"{invoice.id}"]['amt_invoiced']

            blue_slips_display = blue_slips_display + f"<tr><td>Remittance {
                date} - balance of monies remaining on account</td><td style='text-align: center;"
            if total_blue_slips == 0:
                blue_slips_display = blue_slips_display + \
                    f"border-top: solid; border-top-width: thin;'"
            else:
                blue_slips_display = blue_slips_display + f"'"
            total_blue_slips = total_blue_slips + Decimal(amt)
            blue_slips_display = blue_slips_display + f" >£{amt}</td></tr>"
        blue_slips_display = blue_slips_display + \
            f"<tr><td><b>Total Monies Received:</b></td><td style='text-align: center; border-bottom: solid; border-bottom-width: thin; border-top: solid; border-top-width: thin;'>£{
                round(total_blue_slips, 2)}</td></tr>"
        blue_slips_display = blue_slips_display + f"<tr><td>&nbsp;</td><td></td></tr>"
    else:
        blue_slips_display = ''

    total_green_slips = 0
    if invoice.green_slip_ids.exists():
        green_slips_display = "<tr><td colspan='2'><b>Inter Matter(s) Transfers</b></td></tr>"
        for slip in invoice.green_slip_ids.all():
            date = slip.date.strftime('%d/%m/%Y')
            if slip.file_number_from.file_number == invoice.file_number.file_number:

                green_slips_display = green_slips_display + \
                    f"<tr><td>Transfer to {
                        slip.file_number_to} - {date}</td><td style='text-align: center;"
                if total_green_slips == 0:
                    green_slips_display = green_slips_display + \
                        "border-top: solid; border-top-width: thin;'"
                else:
                    green_slips_display = green_slips_display + "'"
                total_green_slips = total_green_slips - slip.amount
                green_slips_display = green_slips_display + \
                    f">£{slip.amount}</td></tr>"
            else:
                amount_invoiced = json.loads(slip.amount_invoiced_to)

                date = slip.date.strftime('%d/%m/%Y')
                amt = amount_invoiced[f"{invoice.id}"]['amt_invoiced']
                total_green_slips = total_green_slips + Decimal(amt)
                green_slips_display = green_slips_display + f"<tr><td>Transfer from {
                    slip.file_number_from} - {date}</td><td style='text-align: center;"
                if total_green_slips == 0:
                    green_slips_display = green_slips_display + \
                        "border-top: solid; border-top-width: thin;'"
                else:
                    green_slips_display = green_slips_display + "'"
                green_slips_display = green_slips_display + \
                    f">£{amt}</td></tr>"
        green_slips_display = green_slips_display + \
            f"<tr><td ><b>Total Green Slips:</b></td><td style='text-align: center; border-bottom: solid; border-bottom-width: thin; border-top: solid; border-top-width: thin;'>£{
                total_green_slips}</td></tr>"
        green_slips_display = green_slips_display + f"<tr><td>&nbsp;</td><td></td></tr>"
    else:
        green_slips_display = ""

    balance = (total_cost_and_vat + total_pink_slips) - \
        total_blue_slips - total_green_slips
    balance = round(balance, 2)
    if balance >= 0:
        total_due_display = f"<tr class='mt-5'><td><b>Total Due:</b></td><td style='text-align: center; border-top: solid; border-top-width: thin; border-bottom: solid;  border-bottom-style:double;'>£{balance}</td></tr>"
        bank_details = f"""
                <tr>
                        <td>&nbsp;</td>
                        <td></td>

                        </tr>
                    <tr>
                    <td style=" font-size: 12px"><b>Account Name:</b> ANP Solicitors Limited; <b>Sort Code:</b> 20-70-93; <b>Account No:</b> 13065049;  <b>Ref:</b>{invoice.file_number.file_number}<td>
                    </tr>
                 """
    else:
        balance = balance * -1
        bank_details = ""
        total_due_display = f"<tr><td><b>Balance Remaining on Account</b>&nbsp;</td><td style='text-align: center; border-top: solid; border-top-width: thin; border-bottom: solid;  border-bottom-style:double;'>£{
            balance}</td></tr>"

    if invoice.state == "D":
        state = """
                <div>
                    <h1 class="position-fixed top-50 start-50 translate-middle z-n1 text-secondary opacity-50 text-center strong" style="font-size: 1200%;">
                        DRAFT
                    <h1>
                </div>
                """
    else:
        state = ""

    footer = """
            ANP Solicitors is a trading name of ANP Solicitors Limited<br>
            Registered in England and Wales – Company No: 6948759 | Registered office at 290 Kiln Road, Benfleet, Essex SS7 1QT<br>
            T: 01702 556688 | F: 01702 556696 | E: info@anpsolicitors.com | www.anpsolicitors.com<br>
            This firm is authorised and regulated by the Solicitors Regulatory Authority<br>
            A list of directors is open to inspection at the office<br>
            VAT No. 977 542 767 | SRA No. 515388<br>
            """
    style = """
            @page :first {
                    size: A4;
                    margin-top: 0mm;
                    margin-bottom: 4px; 
                    margin-left: 40px;
                    margin-right: 40px;
            }
            @page {
                    size: A4; 
                    margin-top: 20px;
                    margin-bottom: 4px; 
                    margin-left: 40px;
                    margin-right: 40px;
            }
            .logoDiv{
                position: absolute;
                top: 15px;
                right: 40px;
                z-index: 1000;
                width: 75px;
                height: 50px;
                margin: 0;
                padding: 0;
            }
            .overflow-auto {
                padding-top: 0;
            }
            /* Ensure table respects page margins */
            table {
                margin-top: 0;
            }
            @media print {
                /* Logo only appears on first page - absolute positioning */
                .logoDiv {
                    position: absolute;
                    top: 15px;
                    right: 40px;
                }
                /* First page: no top margin, content can start at top */
                @page :first {
                    size: A4;
                    margin-top: 0mm;
                    margin-bottom: 4px;
                    margin-left: 40px;
                    margin-right: 40px;
                }
                /* Subsequent pages: small top margin for spacing */
                @page {
                    size: A4;
                    margin-top: 20px;
                    margin-bottom: 4px;
                    margin-left: 40px;
                    margin-right: 40px;
                }
            }
            img {
                width: 75px;
                height: 50px;
                margin: 0;
                padding: 0;
                display: block;
            }
            
            """

    html = render_to_string('download_templates/invoice.html', {'invoice_number': invoice.invoice_number,
                                                                'style': style,
                                                                'state': mark_safe(state),
                                                                'file_details_display': mark_safe(file_details_display),
                                                                'desc_and_cost_display': mark_safe(desc_and_cost_display),
                                                                'pink_slips_display': mark_safe(pink_slips_display),
                                                                'blue_slips_display': mark_safe(blue_slips_display),
                                                                'green_slips_display': mark_safe(green_slips_display),
                                                                'total_due_display': mark_safe(total_due_display),
                                                                'bank_details': mark_safe(bank_details),
                                                                'footer': mark_safe(footer)})

    pdf_file = HTML(
        string=html, base_url=request.build_absolute_uri()).write_pdf()

    response = HttpResponse(pdf_file, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="Invoice {invoice.invoice_number} - {
        invoice.file_number.client1.name} ({invoice.file_number.matter_description}).pdf"'
    return response


@login_required
def download_credit_note(request, id):
    credit_note = get_object_or_404(CreditNote, id=id)
    file_obj = credit_note.file_number
    invoice = credit_note.invoice
    net_amount, vat_amount, gross_amount = calculate_credit_note_breakdown(
        credit_note.amount)
    status_display = dict(CreditNote.STATUSES).get(
        credit_note.status, credit_note.status)

    client_address_block = f"""
        <div class="me-4">{file_obj.client1.name}<br>
        {file_obj.client1.address_line1}<br>
        {file_obj.client1.address_line2}<br>
        {file_obj.client1.county}, {file_obj.client1.postcode}
        </div>
    """
    if file_obj.client2:
        client_address_block = client_address_block + f"""
            <div class="border-start ps-4">{file_obj.client2.name}<br>
            {file_obj.client2.address_line1}<br>
            {file_obj.client2.address_line2}<br>
            {file_obj.client2.county}, {file_obj.client2.postcode}
            </div>
        """

    file_details_display = f"""
        <tr><td><b>Our Ref:</b> {file_obj.file_number}</td><td></td></tr>
        <tr><td><b>Credit Note No:</b> CN-{credit_note.id}</td><td></td></tr>
        <tr><td><b>Date:</b> {credit_note.date.strftime('%d/%m/%Y')}</td><td></td></tr>
        <tr><td>&nbsp;</td><td></td></tr>
        <tr><td><b>Private & Confidential</b></td><td></td></tr>
        <tr><td class='d-flex flex-row'>{client_address_block}</td><td></td></tr>
        <tr><td><b>Re:</b> {file_obj.matter_description}</td><td></td></tr>
        <tr><td>&nbsp;</td><td></td></tr>
    """

    amount_summary_display = f"""
        <div>
            <table style='width: 100%; border-collapse: collapse; table-layout: fixed;'>
                <tr>
                    <td style='padding: 4px 0; text-align: left;'><b>Credit Amount Excl. VAT:</b></td>
                    <td style='padding: 4px 0; text-align: right; width: 220px;'>
                        <span style='display: inline-block; border-top: solid 1px; padding-top: 2px;'>£{net_amount}</span>
                    </td>
                </tr>
                <tr>
                    <td style='padding: 4px 0; text-align: left;'><b>VAT @{CURRENT_VAT_RATE_PERCENT}% (included):</b></td>
                    <td style='padding: 4px 0; text-align: right;'>£{vat_amount}</td>
                </tr>
                <tr>
                    <td style='padding: 4px 0; text-align: left;'><b>Total Credit (Incl. VAT):</b></td>
                    <td style='padding: 4px 0; text-align: right;'>
                        <span style='display: inline-block; border-top: solid 1px; border-bottom: solid 1px; padding: 2px 0;'>£{gross_amount}</span>
                    </td>
                </tr>
            </table>
        </div>
    """
    desc_and_cost_display = f"""
        <tr><td colspan='2'><b>CREDIT NOTE FOR THE PARTIAL/FULL AMOUNT</b></td></tr>
        <tr><td colspan='2' style='text-align: justify; text-justify: inter-word;'><b>Reason:</b> {credit_note.reason}</td></tr>
        <tr><td>&nbsp;</td><td></td></tr>
        <tr><td colspan='2'>{amount_summary_display}</td></tr>
    """

    meta_line = f"Status: {status_display}"
    if credit_note.approved_by:
        approved_on_display = credit_note.approved_on.strftime(
            '%d/%m/%Y %H:%M') if credit_note.approved_on else ''
        meta_line = f"{meta_line} | Approved: {credit_note.approved_by}"
        if approved_on_display:
            meta_line = f"{meta_line} ({approved_on_display})"

    if credit_note.status == "P":
        state = """
                <div>
                    <h1 class="position-fixed top-50 start-50 translate-middle z-n1 text-secondary opacity-50 text-center strong" style="font-size: 600%;">
                        PENDING APPROVAL
                    <h1>
                </div>
                """
    else:
        state = ""

    footer = """
            ANP Solicitors is a trading name of ANP Solicitors Limited<br>
            Registered in England and Wales - Company No: 6948759 | Registered office at 290 Kiln Road, Benfleet, Essex SS7 1QT<br>
            T: 01702 556688 | F: 01702 556696 | E: info@anpsolicitors.com | www.anpsolicitors.com<br>
            This firm is authorised and regulated by the Solicitors Regulation Authority<br>
            A list of directors is open to inspection at the office<br>
            VAT No. 977 542 767 | SRA No. 515388<br>
            """
    style = """
            @page :first {
                    size: A4;
                    margin-top: 0mm;
                    margin-bottom: 4px;
                    margin-left: 40px;
                    margin-right: 40px;
            }
            @page {
                    size: A4;
                    margin-top: 20px;
                    margin-bottom: 4px;
                    margin-left: 40px;
                    margin-right: 40px;
            }
            .logoDiv{
                position: absolute;
                top: 15px;
                right: 40px;
                z-index: 1000;
                width: 75px;
                height: 50px;
                margin: 0;
                padding: 0;
            }
            img {
                width: 75px;
                height: 50px;
                margin: 0;
                padding: 0;
                display: block;
            }
            .docTitle {
                text-align: center;
                font-size: 32px;
                font-weight: bold;
                margin-top: 4px;
                margin-bottom: 12px;
            }
            .creditTable {
                width: 100%;
                table-layout: fixed;
            }
            """

    html = render_to_string('download_templates/credit_note.html', {
        'credit_note_number': credit_note.id,
        'style': style,
        'state': mark_safe(state),
        'file_details_display': mark_safe(file_details_display),
        'desc_and_cost_display': mark_safe(desc_and_cost_display),
        'meta_line': meta_line,
        'footer': mark_safe(footer),
    })
    pdf_file = HTML(
        string=html, base_url=request.build_absolute_uri()).write_pdf()
    response = HttpResponse(pdf_file, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="Credit_Note_CN-{credit_note.id}_{file_obj.file_number}.pdf"'
    return response


def get_all_financials(file_number):
    file = get_object_or_404(WIP, file_number=file_number)

    slips = PmtsSlips.objects.filter(file_number=file.id)
    green_slips = LedgerAccountTransfers.objects.filter(
        Q(file_number_from=file.id) | Q(file_number_to=file.id))
    invoices = Invoices.objects.filter(file_number=file.id)
    credit_notes = CreditNote.objects.filter(
        file_number=file.id,
        status='F'
    ).select_related('invoice')
    all_objects = []
    for slip in slips:
        if slip.is_money_out == True:
            type_obj = 'money_out'
            desc = f"Payment to {slip.pmt_person} - {slip.description}"
        else:
            type_obj = 'money_in'
            desc = f"Payment from {slip.pmt_person} - {slip.description}"

        obj = {'date': slip.date.strftime('%d/%m/%Y'),
               'desc': desc,
               'type': type_obj,
               'ledger': slip.ledger_account,
               'amount': slip.amount
               }
        all_objects.append(obj)

    for slip in green_slips:
        if slip.file_number_from == slip.file_number_to:
            type_obj = 'client_to_office_tfr'
            desc = f"Client to Office Transfer"
        elif slip.file_number_from.file_number == file_number:
            type_obj = 'money_out'
            desc = f"Transfer to {slip.file_number_to}"
        else:
            type_obj = 'money_in'
            desc = f"Transfer from {slip.file_number_from}"

        obj = {'date': slip.date.strftime('%d/%m/%Y'),
               'desc': desc,
               'type': type_obj,
               'ledger': slip.from_ledger_account,
               'amount': slip.amount
               }
        all_objects.append(obj)

    for invoice in invoices:
        if invoice.state == 'F':
            desc = f"ANP Invoice {invoice.invoice_number}"
        else:
            desc = f"DRAFT ANP Invoice"

        type_obj = "money_out"

        _, _, total_cost_invoice = calculate_invoice_total_with_vat(invoice)
        obj = {'date': invoice.date.strftime('%d/%m/%Y'),
               'desc': desc,
               'type': type_obj,
               'ledger': 'O',
               'amount': total_cost_invoice
               }
        all_objects.append(obj)

    for credit_note in credit_notes:
        invoice_number = credit_note.invoice.invoice_number or 'Draft'
        obj = {
            'date': credit_note.date.strftime('%d/%m/%Y'),
            'desc': f'Credit Note for ANP Invoice {invoice_number}',
            'type': 'money_in',
            'ledger': 'O',
            'amount': credit_note.amount
        }
        all_objects.append(obj)

    def sort_rows(rows):
        def get_sort_key(row):
            # Handling empty dates
            date_str = row['date'] if row['date'] else '01/01/0001'

            date_time = datetime.strptime(date_str, '%d/%m/%Y')
            return date_time

        sorted_rows = sorted(rows, key=get_sort_key)
        return sorted_rows

    sorted_rows = sort_rows(all_objects)
    return sorted_rows


@login_required
def download_statement_account(request, file_number):
    file = WIP.objects.filter(file_number=file_number).first()

    """
    Date | Desc | Money in | Money Out | Balance

    if pink slip, invoice or green_slip (file_from) then money out

    """
    sorted_rows = get_all_financials(file_number)
    now_time = datetime.now().strftime("%d_%m_%Y, %H_%M")
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="({
        file_number}) Statement of Account {now_time}.csv"'

    writer = csv.writer(response)

    writer.writerow(
        ['', f'Client Name: {file.client1.name} Matter:{file.matter_description}[{file.file_number}]'])
    writer.writerow(['', f'Statement of Account'])

    writer.writerow([])
    writer.writerow(
        ['Date', 'Description', 'Money In', 'Money Out', 'Balance'])
    balance = 0
    client_to_office_tfr_rows = 0
    for row in sorted_rows:
        if row['type'] == 'client_to_office_tfr':
            client_to_office_tfr_rows = client_to_office_tfr_rows + 1
            continue
        if row['type'] == 'money_out':
            balance = balance - row['amount']
        else:
            balance = balance + row['amount']
        writer.writerow([row['date'], row['desc'], row['amount'] if row['type'] ==
                        'money_in' else '', row['amount'] if row['type'] == 'money_out' else '', balance])
    writer.writerow([])
    final_cell = (len(sorted_rows)-client_to_office_tfr_rows) + 4
    writer.writerow(
        ['', 'Total', f'=sum(c5:c{final_cell})', f'=sum(d5:d{final_cell})'])
    return response


@login_required
def generate_ledgers_report(request, file_number):
    file = get_object_or_404(WIP, file_number=file_number)
    html_content = f"""
    <html>
        <head>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">

            <style>
                @page {{
                    size: landscape;
                }}
                .balance {{
                    font-weight: bold;
                }}
            </style>
        </head>
        <body style="font-family: Times New Roman, Times, serif">
            <h2>Ledger</h2>
            <h2>Client Name: {file.client1.name} Matter: {file.matter_description} [{file.file_number}]</h2>
            <table class='table table-striped'>
                <thead>
                    <tr>
                        <th>Date</th>
                        <th>Description</th>
                        <th colspan="2">Office Account</th>
                        <th colspan="2">Client Account</th>
                    </tr>
                    <tr>
                        <th></th>
                        <th></th>
                        <th>Amount</th>
                        <th>Balance</th>
                        <th>Amount</th>
                        <th>Balance</th>
                    </tr>
                </thead>
                <tbody>
    """
    office_balance = 0
    client_balance = 0
    all_objects = get_all_financials(file_number)

    for row in all_objects:

        if row['type'] == 'client_to_office_tfr':
            client_balance -= row['amount']
            client_amount = '-' + str(row['amount'])
            office_amount = ''
            html_content += f"""
                <tr>
                    <td>{row['date']}</td>
                    <td>{row['desc']}</td>
                    <td>{office_amount}</td>
                    <td class="balance">{office_balance}</td>
                    <td>{client_amount}</td>
                    <td class="balance">{client_balance}</td>
                </tr>
             """

            office_balance += row['amount']
            client_amount = ''
            office_amount = str(row['amount'])

            html_content += f"""
                <tr>
                    <td>{row['date']}</td>
                    <td>{row['desc']}</td>
                    <td>{office_amount}</td>
                    <td class="balance">{office_balance}</td>
                    <td>{client_amount}</td>
                    <td class="balance">{client_balance}</td>
                </tr>
            """
            continue

        if row['ledger'] == 'C':
            if row['type'] == 'money_out':
                client_balance -= row['amount']
                client_amount = '-' + str(row['amount'])
                office_amount = ''
            else:
                client_balance += row['amount']
                client_amount = str(row['amount'])
                office_amount = ''
        else:
            if row['type'] == 'money_out':
                office_balance -= row['amount']
                client_amount = ''
                office_amount = '-' + str(row['amount'])
            else:
                office_balance += row['amount']
                client_amount = ''
                office_amount = str(row['amount'])

        html_content += f"""
                <tr>
                    <td>{row['date']}</td>
                    <td>{row['desc']}</td>
                    <td>{office_amount}</td>
                    <td class="balance">{office_balance}</td>
                    <td>{client_amount}</td>
                    <td class="balance">{client_balance}</td>
                </tr>
        """

    html_content += f"""
                <tr class="bg-body-tertiary">
                    <td></td>
                    <td class="balance">Balance</td>
                    <td colspan='2' class="balance">{office_balance}</td>
                    <td colspan='2' class="balance">{client_balance}</td>
                </tr>
        """

    html_content += """
                </tbody>
            </table>
        </body>
    </html>
    """

    now_time = datetime.now().strftime("%d_%m_%Y_%H_%M")
    file_name = f"Ledger_Printout_{file_number}_{now_time}.pdf"

    pdf_file = HTML(string=html_content,
                    base_url=request.build_absolute_uri()).write_pdf()

    response = HttpResponse(pdf_file, content_type='application/pdf')

    response['Content-Disposition'] = f'attachment; filename="{file_name}'
    return response


@login_required
def edit_invoice(request, id):
    if request.method == 'POST':

        invoice = Invoices.objects.filter(id=id).first()

        serializer = InvoicesSerializer(invoice)
        prev_serialized_data = serializer.to_dict()
        if invoice.state == 'D':
            if request.POST['state'] == 'F':
                largest_invoice_number = Invoices.objects.aggregate(Max('invoice_number'))[
                    'invoice_number__max']
                invoice.invoice_number = largest_invoice_number + 1
                invoice.state = 'F'

        invoice.payable_by = request.POST['payable_by']
        if 'by_email' in request.POST:
            invoice.by_email = True

        if 'by_post' in request.POST:
            invoice.by_post = True

        desc = request.POST['description']
        invoice.description = desc
        date = request.POST['date']
        invoice.date = date
        our_costs_desc = request.POST.getlist('our_costs_desc[]')
        our_costs = request.POST.getlist('our_costs[]')

        our_costs_desc_filtered = [
            desc for desc in our_costs_desc if desc != '']

        our_costs_filtered = [cost for cost in our_costs if cost != '']

        invoice.our_costs_desc = json.dumps(our_costs_desc_filtered)
        invoice.our_costs = json.dumps(our_costs_filtered)

        total_costs = 0
        for cost in our_costs_filtered:

            total_costs = total_costs + Decimal(cost)
        vat_mode = request.POST.get('vat_mode', 'auto')
        if vat_mode != 'manual':
            vat_mode = 'auto'
        auto_vat_amount = round(total_costs * CURRENT_VAT_RATE, 2)
        if vat_mode == 'manual':
            manual_vat_raw = request.POST.get('manual_vat', '').strip()
            try:
                vat_amount = round(Decimal(manual_vat_raw), 2)
                if vat_amount < 0:
                    raise ValueError
            except Exception:
                messages.error(
                    request, 'Manual VAT must be a valid non-negative amount.')
                return redirect('edit_invoice', id=id)
        else:
            vat_amount = auto_vat_amount
        total_costs_and_vat = vat_amount + total_costs
        invoice.vat = vat_amount
        invoice.vat_calculation_mode = vat_mode

        prev_pink_slip_ids = list(
            invoice.disbs_ids.values_list('id', flat=True))
        for id in prev_pink_slip_ids:
            slip = PmtsSlips.objects.filter(id=id).first()
            slip.balance_left = slip.amount
            slip.amount_invoiced = json.dumps({})
            slip.save()

        prev_moa_ids = list(invoice.moa_ids.values_list('id', flat=True))

        for id in prev_moa_ids:
            slip = PmtsSlips.objects.filter(id=id).first()
            if isinstance(slip.amount_invoiced, str):
                amount_invoiced = json.loads(slip.amount_invoiced)
            elif isinstance(slip.amount_invoiced, (bytes, bytearray)):
                amount_invoiced = json.loads(
                    slip.amount_invoiced.decode('utf-8'))
            elif isinstance(slip.amount_invoiced, dict):
                amount_invoiced = slip.amount_invoiced
            else:
                raise ValueError("Unsupported type for slip.amount_invoiced")
            inv_data = amount_invoiced.get(str(str(invoice.id)), {})
            amount_inv = inv_data.get('amt_invoiced', 0)
            balance_left = inv_data.get('balance_left', 0)

            difference = round(Decimal(amount_inv) - Decimal(balance_left), 2)

            amount_invoiced.pop(str(invoice.id), None)
            slip.amount_invoiced = json.dumps(amount_invoiced)
            slip.balance_left += difference
            slip.save()

        prev_green_slip_ids = list(
            invoice.green_slip_ids.values_list('id', flat=True))

        for id in prev_green_slip_ids:
            slip = LedgerAccountTransfers.objects.filter(id=id).first()
            if slip.file_number_to == invoice.file_number:
                amount_invoiced = json.loads(slip.amount_invoiced_to)
                inv_data = amount_invoiced.get(str(str(invoice.id)), {})
                amount_inv = inv_data.get('amt_invoiced', 0)
                balance_left = inv_data.get('balance_left', 0)

                difference = round(Decimal(amount_inv) -
                                   Decimal(balance_left), 2)

                amount_invoiced.pop(str(invoice.id), None)
                slip.amount_invoiced_to = json.dumps(amount_invoiced)
                slip.balance_left_to += difference
                slip.save()
            else:
                slip.balance_left_from = slip.amount
                slip.amount_invoiced_from = json.dumps({})

        disbs_ids = [int(id_str)
                     for id_str in request.POST.getlist('pink_slips[]')]
        total_disbs = 0
        for id in disbs_ids:
            obj = PmtsSlips.objects.filter(id=id).first()
            total_disbs = total_disbs + obj.amount
            obj.amount_invoiced = json.dumps(str(obj.amount))
            obj.balance_left = 0
            obj.save()

        total_costs_and_disbs = total_costs_and_vat + total_disbs
        temp_costs = total_costs_and_disbs

        moa_ids = [int(id_str)
                   for id_str in request.POST.getlist('blue_slips[]')]
        for id in moa_ids:
            obj = PmtsSlips.objects.filter(id=id).first()
            temp_costs = temp_costs - obj.balance_left
            invoice_slip_obj = {str(invoice.id): {'amt_invoiced': str(
                obj.balance_left), 'balance_left': ''}}
            if temp_costs < 0:
                obj.balance_left = obj.balance_left - total_costs_and_disbs
            elif temp_costs >= 0:
                obj.balance_left = 0

            invoice_slip_obj[str(invoice.id)]['balance_left'] = str(
                obj.balance_left)
            prev_amount_invoiced_to_obj = json.loads(
                obj.amount_invoiced) if obj.amount_invoiced != {} else {}
            prev_amount_invoiced_to_obj.update(invoice_slip_obj)
            obj.amount_invoiced = json.dumps(prev_amount_invoiced_to_obj)
            total_costs_and_disbs = temp_costs
            obj.save()

        green_slips_ids = [int(id_str)
                           for id_str in request.POST.getlist('green_slips[]')]
        for id in green_slips_ids:
            obj = LedgerAccountTransfers.objects.filter(id=id).first()
            if obj.file_number_from == invoice.file_number:
                obj.amount_invoiced_from = json.dumps(str(obj.amount))
                obj.balance_left_from = 0
            else:
                temp_costs = temp_costs - obj.balance_left_to
                invoice_slip_obj = {str(invoice.id): {'amt_invoiced': str(
                    obj.balance_left_to), 'balance_left': ''}}
                if temp_costs < 0:
                    obj.balance_left_to = obj.balance_left_to - total_costs_and_disbs
                elif temp_costs >= 0:
                    obj.balance_left_to = 0
                invoice_slip_obj[str(invoice.id)]['balance_left'] = str(
                    obj.balance_left_to)
                prev_amount_invoiced_to_obj = json.loads(
                    obj.amount_invoiced_to) if obj.amount_invoiced_to != {} else {}
                prev_amount_invoiced_to_obj.update(invoice_slip_obj)
                obj.amount_invoiced_to = json.dumps(
                    prev_amount_invoiced_to_obj)
                total_costs_and_disbs = temp_costs
            obj.save()

        if temp_costs <= 0:
            invoice.total_due_left = 0
        else:
            invoice.total_due_left = temp_costs

        invoice.disbs_ids.set(disbs_ids)
        invoice.moa_ids.set(moa_ids)
        invoice.green_slip_ids.set(green_slips_ids)

        invoice.save()
        serializer = InvoicesSerializer(invoice)
        after_serialized_data = serializer.to_dict()
        create_modification(
            request.user,
            invoice,
            json.dumps({'prev': prev_serialized_data,
                        'after': after_serialized_data})
        )

        return redirect('finance_view', file_number=invoice.file_number)
    else:
        invoice = Invoices.objects.filter(id=id).first()

        our_costs = invoice.our_costs

        costs = ast.literal_eval(our_costs) if type(
            our_costs) != type([]) else our_costs

        our_costs_desc_pre = invoice.our_costs_desc
        our_costs_desc = ast.literal_eval(our_costs_desc_pre) if type(
            our_costs_desc_pre) != type([]) else our_costs_desc_pre
        our_costs_rows = []
        for i in range(len(costs)):

            our_costs_display = f"""
            <div class="grid grid-cols-1 md:grid-cols-12 gap-4 mt-2">
                <div class="col-span-5">
                    <input type="text" class="form-input" id="our_costs_description" placeholder="Costs Description"
                    name="our_costs_desc[]" value="{our_costs_desc[i]}">
                </div>
                <div class="col-span-5">
                    <input required type="number" step="0.01" class="form-input" name="our_costs[]" id="our_costs"
                    placeholder="£0.00" value={round(Decimal(costs[i]), 2)}>
                </div>
                <div class="col-span-2 flex items-center">
                    <span type='button' class='btn btn-danger px-4' onclick="removeField(this);" >-</span>
                </div>
            </div>
            """
            our_costs_rows.append(mark_safe(our_costs_display))

        slips = PmtsSlips.objects.filter(
            file_number=invoice.file_number).order_by('date')

        green_slips_objs = LedgerAccountTransfers.objects.filter(
            Q(file_number_from=invoice.file_number.id) | Q(
                file_number_to=invoice.file_number.id)
        ).exclude(
            file_number_from=F('file_number_to')
        ).order_by('date')

        disbs_ids = list(invoice.disbs_ids.values_list('id', flat=True))

        # Get IDs of moa_ids
        moa_ids = list(invoice.moa_ids.values_list('id', flat=True))

        # Get IDs of cash_allocated_slips
        cash_allocated_slips_ids = list(
            invoice.cash_allocated_slips.values_list('id', flat=True))

        # Get IDs of green_slip_ids
        green_slip_ids = list(
            invoice.green_slip_ids.values_list('id', flat=True))
        pink_slips = []
        blue_slips = []
        green_slips = []

        for slip in slips:
            if slip.id in disbs_ids or slip.id in moa_ids:
                checked = 'checked'
            else:
                checked = ''
            if slip.ledger_account == 'C':
                ledger_acc = 'Client'
            else:
                ledger_acc = 'Office'
            if (slip.is_money_out == True and slip.balance_left > 0) or slip.id in disbs_ids:

                slip_display = f"""
                 <div class="form-check">
                    <input class="form-check-input" name="pink_slips[]" type="checkbox" value="{slip.id}" {checked}>
                    <label class="form-check-label" data-toggle="tooltip" data-bs-title="Description: '{slip.description}'">
                    Payment to&nbsp;<b >'{slip.pmt_person}'</b>&nbsp;of £{slip.amount}
                    from {ledger_acc} Ledger on {slip.date.strftime('%d/%m/%Y')}</label>
                </div>
                """
                pink_slips.append(mark_safe(slip_display))
            elif slip.id in moa_ids or slip.balance_left > 0:
                if isinstance(slip.amount_invoiced, str):
                    amount_invoiced = json.loads(slip.amount_invoiced)
                elif isinstance(slip.amount_invoiced, (bytes, bytearray)):
                    amount_invoiced = json.loads(
                        slip.amount_invoiced.decode('utf-8'))
                elif isinstance(slip.amount_invoiced, dict):
                    amount_invoiced = slip.amount_invoiced
                else:
                    raise ValueError(
                        "Unsupported type for slip.amount_invoiced")

                if slip.id in moa_ids:
                    amt = amount_invoiced[f"{invoice.id}"]['amt_invoiced']
                else:
                    amt = slip.balance_left
                slip_display = f"""
                 <div class="form-check">
                    <input class="form-check-input" name="blue_slips[]" type="checkbox" value="{slip.id}" {checked}>
                    <label class="form-check-label" data-toggle="tooltip" data-bs-title="Description: '{slip.description}'">
                    Payment from&nbsp;<b >'{slip.pmt_person}'</b>&nbsp;of £{amt} from (£{slip.amount})
                    from {ledger_acc} Ledger on {slip.date.strftime('%d/%m/%Y')}</label>
                </div>
                """
                blue_slips.append(mark_safe(slip_display))

        for slip in green_slips_objs:

            if slip.id in green_slip_ids:
                checked = "checked"
            else:
                checked = ""

            if slip.file_number_from == invoice.file_number:
                if slip.balance_left_from > 0 or slip.id in green_slip_ids:
                    slip_display = f"""
                                    <div class="form-check">
                                        <input class="form-check-input" name="green_slips[]" type="checkbox" value="{slip.id}" {checked}>
                                        <label class="form-check-label" data-toggle="tooltip" data-bs-title="Description: '{slip.description}'">
                                            Transfer to&nbsp;<b >{slip.file_number_to}</b> of £{slip.amount} on {slip.date.strftime('%d/%m/%Y')}
                                        </label>
                                    </div>
                                    """
                    green_slips.append(mark_safe(slip_display))
            if slip.file_number_to == invoice.file_number:
                if slip.id in green_slip_ids or slip.balance_left_to > 0:

                    amount_invoiced = json.loads(slip.amount_invoiced_to) if slip.amount_invoiced_to != {
                    } else slip.amount_invoiced_to
                    if slip.id in green_slip_ids:
                        amt = amount_invoiced[f"{invoice.id}"]['amt_invoiced']
                    else:
                        amt = slip.balance_left_to
                    slip_display = f"""
                                    <div class="form-check">
                                        <input class="form-check-input" name="green_slips[]" type="checkbox" value="{slip.id}" {checked}>
                                        <label class="form-check-label" data-toggle="tooltip" data-bs-title="Description: '{slip.description}'">
                                        Transfer from&nbsp;<b >{slip.file_number_from}</b> of £{amt} (from £{slip.amount}) {slip.date.strftime('%d/%m/%Y')}</label>
                                    </div>
                                    """
                    green_slips.append(mark_safe(slip_display))

        context = {
            'invoice_id': invoice.id,
            'file_number': invoice.file_number.file_number,
            'state': invoice.state,
            'date': invoice.date.strftime('%Y-%m-%d'),
            'payable_by': invoice.payable_by,
            'by_email': invoice.by_email,
            'by_post': invoice.by_post,
            'description': invoice.description,
            'our_costs_rows': our_costs_rows,
            'vat_mode': invoice.vat_calculation_mode or 'auto',
            'manual_vat': round(Decimal(str(invoice.vat or 0)), 2),
            'current_vat_rate_percent': CURRENT_VAT_RATE_PERCENT,
            'pink_slips': pink_slips,
            'blue_slips': blue_slips,
            'green_slips': green_slips,
            'green_slip_ids': green_slip_ids

        }
        return render(request, 'edit_invoice.html', context)


@login_required
def download_estate_accounts(request, file_number):
    file = WIP.objects.filter(file_number=file_number).first()
    slips = PmtsSlips.objects.filter(file_number=file.id)
    green_slips = LedgerAccountTransfers.objects.filter(
        Q(file_number_from=file.id) | Q(file_number_to=file.id))
    invoices = Invoices.objects.filter(file_number=file.id)
    credit_notes = CreditNote.objects.filter(
        file_number=file.id, status='F').select_related('invoice')
    money_in_objects = []
    money_out_objects = []
    num_money_in_objs = 0
    for slip in slips:
        if slip.is_money_out == True:

            desc = f"Payment to {slip.pmt_person} - {slip.description}"
            obj = {'date': slip.date.strftime('%d/%m/%Y'),
                   'desc': desc,
                   'amount': slip.amount
                   }
            money_out_objects.append(obj)
        else:

            desc = f"Payment from {slip.pmt_person} - {slip.description}"

            obj = {'date': slip.date.strftime('%d/%m/%Y'),
                   'desc': desc,
                   'amount': slip.amount
                   }
            money_in_objects.append(obj)

    for slip in green_slips:
        if slip.file_number_from.file_number == file_number:

            desc = f"Transfer to {slip.file_number_to}"
            obj = {'date': slip.date.strftime('%d/%m/%Y'),
                   'desc': desc,
                   'amount': slip.amount
                   }
            money_out_objects.append(obj)

        else:

            desc = f"Transfer from {slip.file_number_from}"
            obj = {'date': slip.date.strftime('%d/%m/%Y'),
                   'desc': desc,
                   'amount': slip.amount
                   }
            money_in_objects.append(obj)

    for invoice in invoices:
        if invoice.state == 'F':
            desc = f"ANP Invoice {invoice.invoice_number}"
        else:
            desc = f"DRAFT ANP Invoice"

        _, _, total_cost_invoice = calculate_invoice_total_with_vat(invoice)
        obj = {'date': invoice.date.strftime('%d/%m/%Y'),
               'desc': desc,
               'amount': total_cost_invoice
               }
        money_out_objects.append(obj)

    for credit_note in credit_notes:
        invoice_number = credit_note.invoice.invoice_number or "Draft"
        obj = {'date': credit_note.date.strftime('%d/%m/%Y'),
               'desc': f"Credit Note for ANP Invoice {invoice_number}",
               'amount': credit_note.amount
               }
        money_in_objects.append(obj)

    def sort_rows(rows):
        def get_sort_key(row):
            # Handling empty dates
            date_str = row['date'] if row['date'] else '01/01/0001'

            date_time = datetime.strptime(date_str, '%d/%m/%Y')
            return date_time

        sorted_rows = sorted(rows, key=get_sort_key)
        return sorted_rows

    sorted_money_in_objs = sort_rows(money_in_objects)
    sorted_money_out_objs = sort_rows(money_out_objects)

    doc = Document()

    for style in doc.styles:
        if hasattr(style, 'font'):
            style.font.name = 'Times New Roman'
            style.font.color.rgb = RGBColor(0, 0, 0)

    '''Page 1'''

    # Add heading on the first page
    doc.add_paragraph('\n\n\n\n')

    heading = doc.add_paragraph("Document Heading\n\n\n")
    heading.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
    heading_run = heading.runs[0]
    heading_run.bold = True
    heading_run.font.size = Pt(46)

    doc.add_paragraph('')

    heading = doc.add_paragraph("Estate Account\n\n\n\n\n")
    heading.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
    heading_run = heading.runs[0]
    heading_run.bold = True
    heading_run.underline = True
    heading_run.font.size = Pt(32)

    heading = doc.add_paragraph(
        "Prepared by:\nANP Solicitors\n290 Kiln Road Benfleet\nEssex SS7 1QT")
    heading.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
    heading_run = heading.runs[0]
    heading_run.font.size = Pt(12)
    # Add page break
    doc.add_page_break()

    '''Page 2 Assets (money in)'''

    heading = doc.add_paragraph(
        "Person Decesased\nDate of Death\nEstate Account")
    heading.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
    heading_run = heading.runs[0]
    heading_run.bold = True
    heading_run.underline = True
    heading_run.font.size = Pt(16)

    heading = doc.add_paragraph("Assets")
    heading.alignment = WD_PARAGRAPH_ALIGNMENT.LEFT
    heading_run = heading.runs[0]
    heading_run.bold = True
    heading_run.underline = True
    heading_run.font.size = Pt(12)

    table = doc.add_table(rows=len(money_in_objects)+1,
                          cols=3, style='Light Shading')
    table.autofit = True
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    i = 0
    j = 0

    for row in table.rows:
        if i == 0:
            row.cells[0].text = "Date"
            row.cells[1].text = "Description"
            row.cells[2].text = "Amount"
            i = 1
        elif j < len(money_in_objects):
            row.cells[0].text = money_in_objects[j]['date']
            row.cells[1].text = money_in_objects[j]['desc']
            row.cells[2].text = '£' + str(money_in_objects[j]['amount'])
            j = j + 1

    heading = doc.add_paragraph(
        "\nGross Value of Estate Carried Forward\t\t\t£1000.00")
    heading.alignment = WD_PARAGRAPH_ALIGNMENT.LEFT
    heading_run = heading.runs[0]
    heading_run.bold = True
    heading_run.underline = True
    heading_run.font.size = Pt(12)

    doc.add_page_break()

    '''Page 3'''

    table = doc.add_table(rows=len(money_out_objects)+1,
                          cols=3, style='Light Shading')
    table.autofit = True
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    i = 0
    j = 0

    for row in table.rows:
        if i == 0:
            row.cells[0].text = "Date"
            row.cells[1].text = "Description"
            row.cells[2].text = "Amount"
            i = 1
        elif j < len(money_out_objects):
            row.cells[0].text = money_out_objects[j]['date']
            row.cells[1].text = money_out_objects[j]['desc']
            row.cells[2].text = '£' + str(money_out_objects[j]['amount'])
            j = j + 1

    heading = doc.add_paragraph(
        "Person Decesased\nDate of Death\nEstate Account")
    heading.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
    heading_run = heading.runs[0]
    heading_run.bold = True
    heading_run.underline = True
    heading_run.font.size = Pt(16)

    heading = doc.add_paragraph("Assets")
    heading.alignment = WD_PARAGRAPH_ALIGNMENT.LEFT
    heading_run = heading.runs[0]
    heading_run.bold = True
    heading_run.underline = True
    heading_run.font.size = Pt(12)

    heading = doc.add_paragraph(
        "\nGross Value of Estate Carried Forward\t\t\t£1000.00")
    heading.alignment = WD_PARAGRAPH_ALIGNMENT.LEFT
    heading_run = heading.runs[0]
    heading_run.bold = True
    heading_run.underline = True
    heading_run.font.size = Pt(12)
    # Create an in-memory stream to store the document
    output = io.BytesIO()

    # Save the document to the in-memory stream
    doc.save(output)

    # Create a response and set appropriate content type and headers
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    response['Content-Disposition'] = 'attachment; filename="example.docx"'

    # Set the content of the response to the content of the in-memory stream
    response.write(output.getvalue())

    return response


@login_required
def unallocated_emails(request):

    unallocated_emails_obj = MatterEmails.objects.filter(
        file_number=None).order_by('time').only()
    i = 0
    rows = []

    def file_number_options():
        files = WIP.objects.all().order_by('file_number')
        select = f"""<input list="file_options"  type="text" name="FileNumber[]" class="form-input"
                 placeholder="XYZ0010001" pattern="^(XXXXXXXXXX|[A-Z]{{3}}\\d{{7}})$" 
               title="Must be either XXXXXXXXXX or 3 uppercase letters followed by 7 digits">
                    <datalist id="file_options">
                    <option value=''></option>
                    <option value="XXXXXXXXXX">To be deleted</option>
                """
        options = [
            f'<option value="{file.file_number}">{file.file_number}</option>' for file in files]
        select += ''.join(options)

        select = select + """</datalist>
                """
        return select
    files_options = file_number_options()
    for email in unallocated_emails_obj:
        i = i + 1
        receiver = json.loads(email.receiver)
        sender = json.loads(email.sender)

        row = f"""<tr class="email-row even:bg-white odd:bg-gray-50 border-b text-gray-900 px-2" data-email="{receiver[0]['emailAddress']['address']} {sender['emailAddress']['address']}">
                        <td class='td'>{i}</td>
                        <td class='td'>{email.time.strftime('%d-%m-%Y <br> %H:%M %p')}</td>
                        <td>
                            <b>From:</b> {sender['emailAddress']['name']} ({sender['emailAddress']['address']})<br>
                            <b>To:</b> {receiver[0]['emailAddress']['name']} ({receiver[0]['emailAddress']['address']})
                        </td>
                        <td class='td'>{email.subject}</td>
                        <td class='td'><a class="link" target="_blank" href="{email.link}">See Email</a></td>
                        <td>
                            <input class="hidden" name="email_ids[]" value={email.id}></input>
                            {files_options}
                        </td>
                    </tr>
        """
        rows.append(mark_safe(row))

    context = {
        'emails': rows
    }

    return render(request, 'unallocated_emails.html', context=context)


@login_required
def allocate_emails(request):
    i = 0
    file_numbers = request.POST.getlist('FileNumber[]')
    email_ids = request.POST.getlist('email_ids[]')
    j = 0
    error_count = 0

    for file_number in file_numbers:

        if file_number != '':
            file_number = file_number
            email_id = email_ids[i]
            email = MatterEmails.objects.filter(id=email_id).first()

            # Check if file exists
            file = WIP.objects.filter(file_number=file_number).first()
            if not file:
                error_count += 1
                messages.error(
                    request, f'File with file number {file_number} does not exist. Please choose a correct file number.')
                i += 1
                continue

            email.file_number = file
            j += 1
            email.fee_earner = file.fee_earner if file.fee_earner is not None else None
            email.save()

        i += 1

    if j > 0:
        messages.success(request, f'Successfully allocated {j} emails')

    if error_count > 0:
        messages.error(
            request, f'{error_count} file(s) were not found. Please check the file numbers.')

    return redirect('unallocated_emails')


def get_client_to_office_transfers_context():
    transfers = LedgerAccountTransfers.objects.filter(
        is_cashier_co_transfer=True,
        from_ledger_account='C',
        to_ledger_account='O',
        file_number_from=F('file_number_to')
    ).select_related(
        'file_number_from',
        'created_by',
        'bank_transfer_done_by'
    ).order_by('-date', '-id')

    grouped_transfers = []
    current_group = None
    for transfer in transfers:
        if current_group is None or current_group['date'] != transfer.date:
            current_group = {
                'date': transfer.date,
                'rows': [],
                'total': Decimal('0.00'),
                'pending_count': 0,
                'completed_count': 0
            }
            grouped_transfers.append(current_group)
        current_group['rows'].append(transfer)
        current_group['total'] += transfer.amount
        if transfer.is_bank_transfer_done:
            current_group['completed_count'] += 1
        else:
            current_group['pending_count'] += 1

    overall_total = transfers.aggregate(total=Sum('amount')).get('total') or Decimal('0.00')
    pending_total = transfers.filter(
        is_bank_transfer_done=False
    ).aggregate(total=Sum('amount')).get('total') or Decimal('0.00')
    completed_total = transfers.filter(
        is_bank_transfer_done=True
    ).aggregate(total=Sum('amount')).get('total') or Decimal('0.00')

    return {
        'active_files': WIP.objects.order_by('file_number'),
        'grouped_client_to_office_transfers': grouped_transfers,
        'client_to_office_overall_total': overall_total,
        'client_to_office_pending_total': pending_total,
        'client_to_office_completed_total': completed_total,
        'client_to_office_pending_count': transfers.filter(is_bank_transfer_done=False).count(),
        'client_to_office_completed_count': transfers.filter(is_bank_transfer_done=True).count(),
    }


@login_required
def download_cashier_data(request):
    if request.method == 'POST':
        cashier_action = request.POST.get('cashier_action')

        if cashier_action == 'export_client_to_office_transfers':
            start_date_str = request.POST.get('start_date', '').strip()
            end_date_str = request.POST.get('end_date', '').strip()

            if not start_date_str or not end_date_str:
                messages.error(request, 'Start date and end date are required for export.')
                return redirect('download_cashier_data')

            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            except ValueError:
                messages.error(request, 'Export date range is invalid.')
                return redirect('download_cashier_data')

            if end_date < start_date:
                messages.error(request, 'End date cannot be before start date.')
                return redirect('download_cashier_data')

            transfers = LedgerAccountTransfers.objects.filter(
                is_cashier_co_transfer=True,
                from_ledger_account='C',
                to_ledger_account='O',
                file_number_from=F('file_number_to'),
                date__range=(start_date, end_date)
            ).select_related(
                'file_number_from',
                'created_by',
                'bank_transfer_done_by'
            ).order_by('date', 'id')

            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = (
                f'attachment; filename="CO_TFR_{start_date.strftime("%Y%m%d")}_{end_date.strftime("%Y%m%d")}.csv"'
            )

            writer = csv.writer(response)
            writer.writerow([
                'Date', 'File', 'Amount', 'Description', 'Created By',
                'Bank Status', 'Bank Done On', 'Bank Done By'
            ])

            if not transfers.exists():
                writer.writerow(['No C-O TFR rows found in selected date range.'])
                return response

            current_date = None
            group_total = Decimal('0.00')
            grand_total = Decimal('0.00')
            for transfer in transfers:
                if current_date is not None and current_date != transfer.date:
                    writer.writerow([
                        '', f'SUBTOTAL {current_date.strftime("%d/%m/%Y")}',
                        f'{group_total:.2f}', '', '', '', '', ''
                    ])
                    writer.writerow([])
                    group_total = Decimal('0.00')

                current_date = transfer.date
                group_total += transfer.amount
                grand_total += transfer.amount

                writer.writerow([
                    transfer.date.strftime('%d/%m/%Y'),
                    transfer.file_number_from.file_number if transfer.file_number_from else '-',
                    f'{transfer.amount:.2f}',
                    transfer.description,
                    str(transfer.created_by) if transfer.created_by else '-',
                    'Done' if transfer.is_bank_transfer_done else 'Pending',
                    transfer.bank_transfer_done_on.strftime('%d/%m/%Y') if transfer.bank_transfer_done_on else '-',
                    str(transfer.bank_transfer_done_by) if transfer.bank_transfer_done_by else '-'
                ])

            if current_date is not None:
                writer.writerow([
                    '', f'SUBTOTAL {current_date.strftime("%d/%m/%Y")}',
                    f'{group_total:.2f}', '', '', '', '', ''
                ])
            writer.writerow([])
            writer.writerow(['', 'GRAND TOTAL', f'{grand_total:.2f}', '', '', '', '', ''])
            return response

        if cashier_action == 'add_client_to_office_transfers':
            row_dates = request.POST.getlist('row_date[]')
            row_file_ids = request.POST.getlist('row_file_id[]')
            row_amounts = request.POST.getlist('row_amount[]')
            row_descriptions = request.POST.getlist('row_description[]')

            max_rows = max(
                len(row_dates),
                len(row_file_ids),
                len(row_amounts),
                len(row_descriptions),
                0
            )

            created_count = 0
            errors = []
            for i in range(max_rows):
                row_date = row_dates[i].strip() if i < len(row_dates) else ''
                row_file_id = row_file_ids[i].strip() if i < len(row_file_ids) else ''
                row_amount = row_amounts[i].strip() if i < len(row_amounts) else ''
                row_description = row_descriptions[i].strip() if i < len(row_descriptions) else ''

                has_core_values = any([row_file_id, row_amount])
                has_custom_description = row_description not in ['', 'C-O TFR']
                if not has_core_values and not has_custom_description:
                    continue

                if not row_date or not row_file_id or not row_amount:
                    errors.append(f'Row {i + 1}: date, file and amount are required.')
                    continue

                if len(row_description) > 100:
                    errors.append(f'Row {i + 1}: description must be 100 characters or fewer.')
                    continue

                try:
                    transfer_date = datetime.strptime(row_date, '%Y-%m-%d').date()
                except ValueError:
                    errors.append(f'Row {i + 1}: date is invalid.')
                    continue

                try:
                    amount = Decimal(row_amount)
                except Exception:
                    errors.append(f'Row {i + 1}: amount is invalid.')
                    continue

                if amount <= 0:
                    errors.append(f'Row {i + 1}: amount must be greater than zero.')
                    continue

                file_obj = WIP.objects.filter(id=row_file_id).first()
                if not file_obj:
                    errors.append(f'Row {i + 1}: selected file was not found.')
                    continue

                LedgerAccountTransfers.objects.create(
                    file_number_from=file_obj,
                    file_number_to=file_obj,
                    from_ledger_account='C',
                    to_ledger_account='O',
                    amount=amount,
                    date=transfer_date,
                    description=row_description or 'C-O TFR',
                    amount_invoiced_from={},
                    balance_left_from=amount,
                    amount_invoiced_to={},
                    balance_left_to=amount,
                    is_cashier_co_transfer=True,
                    created_by=request.user
                )
                created_count += 1

            if created_count > 0:
                messages.success(
                    request, f'Added {created_count} client to office transfer row(s).')
            if errors:
                messages.error(request, 'Some rows were not added: ' + ' | '.join(errors[:5]))
            if created_count == 0 and not errors:
                messages.error(request, 'No rows were provided to add.')
            return redirect('download_cashier_data')

        if cashier_action == 'mark_group_done':
            group_date_str = request.POST.get('group_date', '').strip()
            done_date_str = request.POST.get('bank_transfer_done_on', '').strip()

            if not group_date_str:
                messages.error(request, 'Group date is required.')
                return redirect('download_cashier_data')

            if not done_date_str:
                messages.error(request, 'Bank done date is required.')
                return redirect('download_cashier_data')

            try:
                group_date = datetime.strptime(group_date_str, '%Y-%m-%d').date()
            except ValueError:
                messages.error(request, 'Group date is invalid.')
                return redirect('download_cashier_data')

            try:
                done_date = datetime.strptime(done_date_str, '%Y-%m-%d').date()
            except ValueError:
                messages.error(request, 'Bank done date is invalid.')
                return redirect('download_cashier_data')

            pending_qs = LedgerAccountTransfers.objects.filter(
                is_cashier_co_transfer=True,
                from_ledger_account='C',
                to_ledger_account='O',
                file_number_from=F('file_number_to'),
                date=group_date,
                is_bank_transfer_done=False
            )
            updated_count = pending_qs.update(
                is_bank_transfer_done=True,
                bank_transfer_done_on=done_date,
                bank_transfer_done_by=request.user
            )

            if updated_count == 0:
                messages.error(request, 'No pending transfers found in this date group.')
            else:
                messages.success(
                    request, f'Marked {updated_count} transfer(s) as done for {group_date.strftime("%d/%m/%Y")}.')
            return redirect('download_cashier_data')

        start_date_str = request.POST['start_date']

        start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        start_datetime = datetime.combine(start_date.date(), time.min)
        get_pending_slips = request.POST['type_of_report'] == 'Pending Slips'

        if get_pending_slips:
            end_datetime = datetime.combine(datetime.today().date(), time.max)
            title = "Pending Slips"
            check_headings = ""
            check_body = ""
        else:
            end_date_str = request.POST['end_date']
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
            end_datetime = datetime.combine(end_date.date(), time.max)

            title = "Audit Slips"
            check_headings = """
                            <th>Checked Millenium</th>
                            <th>Checked Bank A/c</th>
                        """
            check_body = """
                            <td></td>
                            <td></td>
                        """
        start_date_only = start_datetime.date()
        end_date_only = end_datetime.date()
        invoices = Invoices.objects.filter(
            Q(date__range=(start_date_only, end_date_only)) & Q(state='F')).order_by('invoice_number')
        credit_notes = CreditNote.objects.filter(
            date__range=(start_date_only, end_date_only)
        ).select_related('invoice', 'file_number', 'created_by', 'approved_by').order_by('date')
        slips = PmtsSlips.objects.filter(
            timestamp__range=(start_datetime, end_datetime)).order_by('date')
        green_slips = LedgerAccountTransfers.objects.filter(
            timestamp__range=(start_datetime, end_datetime)).order_by('date')

        invoice_display_table = ''
        if get_pending_slips:
            invoice_display_table = invoice_display_table + """<h2 class='mt-3'>Invoices</h2><table class='table table-striped'>
                <thead>
                    <th>
                        File Number
                    </th>
                    <th>
                        Invoice Number
                    </th>
                    <th>
                        Date
                    </th>
                    <th>
                        Our Costs
                    </th>
                    <th>
                        VAT
                    </th>
                    <th>
                        Total Costs and VAT
                    </th>
                    <th>
                        Disbursements
                    </th>
                </thead>
            """
            for invoice in invoices:
                total_cost_invoice, vat, total_cost_and_vat = calculate_invoice_total_with_vat(
                    invoice)
                slip_display = ''
                for slip in invoice.disbs_ids.all():
                    slip_display = slip_display + \
                        f"({slip.date.strftime('%d/%m/%Y')}, £{slip.amount})"

                invoice_display_table = invoice_display_table + f"""
                <tr>
                    <td>{invoice.file_number.file_number}</td>
                    <td>{invoice.invoice_number}</td>
                    <td>{invoice.date.strftime('%d/%m/%Y')}</td>
                    <td>£{total_cost_invoice}</td>
                    <td>£{vat}</td>
                    <td>£{total_cost_and_vat}</td>
                    <td>{slip_display}</td>
                </tr>
                """
            invoice_display_table = invoice_display_table + "</table>"

        status_labels = dict(CreditNote.STATUSES)
        credit_notes_table = """
            <table class='table table-striped'>
                <thead>
                    <th>Date</th>
                    <th>File Number</th>
                    <th>Credit Amount Excl. VAT</th>
                    <th>VAT</th>
                    <th>Total Credit Incl. VAT</th>
                    <th>Status</th>
                    <th>Reason</th>
                    <th>Created By</th>
                    <th>Approved By</th>
                    <th>Approved On</th>
                </thead>
                <tbody>
        """
        for credit_note in credit_notes:
            approved_on = credit_note.approved_on.strftime(
                '%d/%m/%Y %H:%M') if credit_note.approved_on else '-'
            net_amount, vat_amount, gross_amount = calculate_credit_note_breakdown(
                credit_note.amount)
            credit_notes_table = credit_notes_table + f"""
            <tr>
                <td>{credit_note.date.strftime('%d/%m/%Y')}</td>
                <td>{credit_note.file_number.file_number}</td>
                <td>£{net_amount}</td>
                <td>£{vat_amount}</td>
                <td>£{gross_amount}</td>
                <td>{status_labels.get(credit_note.status, credit_note.status)}</td>
                <td>{credit_note.reason}</td>
                <td>{credit_note.created_by or '-'}</td>
                <td>{credit_note.approved_by or '-'}</td>
                <td>{approved_on}</td>
            </tr>
            """
        credit_notes_table = credit_notes_table + "</tbody></table>"

        common_slips_header = f"""
                <thead>
                    <th>
                        Date
                    </th>
                    <th>
                        File Number
                    </th>
                    <th>
                        Mode of Payment
                    </th>
                    <th>
                        Ledger Account
                    </th>
                    <th>
                        Amount
                    </th>
                    <th>
                        Payment to or from
                    </th>
                    <th>
                        Description
                    </th>
                    {check_headings}

                </thead>
            """

        client_blue_slips_table = f"""<table class='table table-striped'>{
            common_slips_header}"""
        client_pink_slips_table = f"""<table class='table table-striped'>{
            common_slips_header}"""

        office_blue_slips_table = f"""<table class='table table-striped'>{
            common_slips_header}"""
        office_pink_slips_table = f"""<table class='table table-striped'>{
            common_slips_header}"""

        for slip in slips:

            if (slip.is_money_out == False and slip.ledger_account == 'C'):
                client_blue_slips_table = client_blue_slips_table + f"""
                <tr>
                    <td>{slip.date.strftime('%d/%m/%Y')}</td>
                    <td>{slip.file_number}</td>
                    <td>{slip.mode_of_pmt}</td>
                    <td>Client</td>
                    <td>£{slip.amount}</td>
                    <td>{slip.pmt_person}</td>
                    <td>{slip.description}</td>
                    {check_body}
                </tr>
                """
            elif (slip.is_money_out == False and slip.ledger_account == 'O'):
                office_blue_slips_table = office_blue_slips_table + f"""
                <tr>
                    <td>{slip.date.strftime('%d/%m/%Y')}</td>
                    <td>{slip.file_number}</td>
                    <td>{slip.mode_of_pmt}</td>
                    <td>Office</td>
                    <td>£{slip.amount}</td>
                    <td>{slip.pmt_person}</td>
                    <td>{slip.description}</td>
                    {check_body}
                </tr>
                """
            elif (slip.is_money_out == True and slip.ledger_account == 'C'):
                client_pink_slips_table = client_pink_slips_table + f"""
                <tr>
                    <td>{slip.date.strftime('%d/%m/%Y')}</td>
                    <td>{slip.file_number}</td>
                    <td>{slip.mode_of_pmt}</td>
                    <td>Client</td>
                    <td>£{slip.amount}</td>
                    <td>{slip.pmt_person}</td>
                    <td>{slip.description}</td>
                    {check_body}
                </tr>
                """
            else:
                office_pink_slips_table = office_pink_slips_table + f"""
                <tr>
                    <td>{slip.date.strftime('%d/%m/%Y')}</td>
                    <td>{slip.file_number}</td>
                    <td>{slip.mode_of_pmt}</td>
                    <td>Office</td>
                    <td>£{slip.amount}</td>
                    <td>{slip.pmt_person}</td>
                    <td>{slip.description}</td>
                    {check_body}
                </tr>
                """

        client_blue_slips_table = client_blue_slips_table + "</table>"
        client_pink_slips_table = client_pink_slips_table + "</table>"
        office_blue_slips_table = office_blue_slips_table + "</table>"
        office_pink_slips_table = office_pink_slips_table + "</table>"

        green_slips_table = f"""
            <table class='table table-striped'>
                <thead>
                    <th>
                        Date
                    </th>
                    <th>
                        File Number From
                    </th>
                    <th>
                        File Number To
                    </th>
                    <th>
                        Ledger Account From
                    </th>
                    <th>
                        Ledget Account To
                    </th>
                    <th>
                        Description
                    </th>
                    <th>
                        Amount
                    </th>
                </thead>
                <tbody>
        """

        for slip in green_slips:
            green_slips_table = green_slips_table + f"""
            <tr>
                <td>{slip.date.strftime("%d/%m/%Y")}</td>
                <td>{slip.file_number_from.file_number if slip.file_number_from else '-'}</td>
                <td>{slip.file_number_to.file_number if slip.file_number_to else '-'}</td>
                <td>{slip.from_ledger_account}</td>
                <td>{slip.to_ledger_account}</td>
                <td>{slip.description}</td>
                <td>£{slip.amount}</td>
            </tr>
            """
        green_slips_table = green_slips_table + f"""</tbody></table>"""
        page_style = '@page { size: landscape; }'
        html = f"""
                <html>
                    <head>
                        <style>{page_style}</style>
                        <meta charset="UTF-8">
                        <meta name="viewport" content="width=device-width, initial-scale=1.0">
                        <title>{title}</title>
                        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet" integrity="sha384-T3c6CoIi6uLrA9TneNEoa7RxnatzjcDSCmG1MXxSR1GAsXEV/Dwwykc2MPK8M2HN" crossorigin="anonymous"/>

                    </head>
                    <body style="font-family: Times New Roman, Times, serif">
                        <h1 class="text-center">{title}</h1>
                        {invoice_display_table}
                        <h2 class='mt-3'>Credit Notes</h2>
                        {credit_notes_table}
                        <h2 class='mt-3'>Client Blue Slips</h2>
                        {client_blue_slips_table}
                        <h2 class='mt-3'>Client Pink Slips</h2>
                        {client_pink_slips_table}
                        <h2 class='mt-3'>Office Blue Slips</h2>
                        {office_blue_slips_table}
                        <h2 class='mt-3'>Office Pink Slips</h2>
                        {office_pink_slips_table}
                        <h2 class='mt-3'>Green Slips </h2>
                        {green_slips_table}
                        <div>
                            <br>
                            <p><b>Date:</b> {datetime.today().date().strftime('%d/%m/%Y')}</p>
                            <br>
                            <p><b>Signed:</b>...........................................</p>

                        </div>
                    </body>
                </html>
                """
        pdf_file = HTML(string=html).write_pdf()

        return HttpResponse(pdf_file, content_type='application/pdf')

    context = get_client_to_office_transfers_context()
    return render(request, 'cashier_data.html', context)


@login_required
def download_file_logs(request, file_number):
    logs = get_file_logs(file_number)

    page_style = '''@page {
                        @top-right{
                            content: "Page " counter(page) " of " counter(pages);
                        }
                        size: landscape;
                        
                    }
                    '''
    title = f"File Logs - {file_number}"
    html = f"""
            <html>
                <head>
                    <style>{page_style}</style>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <title>{title}</title>
                    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet" integrity="sha384-T3c6CoIi6uLrA9TneNEoa7RxnatzjcDSCmG1MXxSR1GAsXEV/Dwwykc2MPK8M2HN" crossorigin="anonymous"/>

                </head>
            <body style="font-family: Times New Roman, Times, serif">
            
            <div class="flex">
                <h1 class="text-center">WIP Logs - {file_number}</h1>
                <p class='text-end text-muted'>Downloaded by: {request.user}; Downloaded at: {datetime.now().strftime('%d/%m/%Y %H:%M %p')}</p>
            </div>
            <table class='table table-striped'>
                <thead>
                    <th>Type</th>
                    <th>Description</th>
                    <th>User</th>
                    <th>Datetime</th>
                </thead>
                <tbody>
            """
    for log in logs:
        html = html + f"""
                        <tr>
                            <td>{log['type']}</td>
                            <td>{log['desc']}</td>
                            <td>{log['user']}</td>
                            <td>{log['timestamp']}</td>
                        </tr>
                       """
    html = html + f"""</tbody>
            
            </body></html>"""
    pdf_file = HTML(string=html).write_pdf()
    response = HttpResponse(pdf_file, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="file_logs_{
        file_number}_{request.user}_{datetime.now().strftime('%d/%m/%Y %I:%M %p.pdf"')}'
    return response


@login_required
def download_frontsheet(request, file_number):
    file = WIP.objects.get(file_number=file_number)
    page_style = '@page { margin-top: 24pt; margin-bottom:0; font-size:7pt !important; size: A4;}'
    title = f"Frontsheet - {file_number}"

    if file.client2:
        client2_name = file.client2.name
        client2_address = f'{file.client2.address_line1},{
            file.client2.address_line2},<br>{file.client2.county}, {file.client2.postcode}'
        client2_contact_number = file.client2.contact_number
        client2_email = file.client2.email
        client2_dob = file.client2.dob.strftime(
            '%d/%m/%Y') if file.client2.dob != None else None
        client2_id_verified = 'Yes' if file.client2.id_verified else 'No'
        client2_date_of_last_aml = file.client2.date_of_last_aml.strftime(
            '%d/%m/%Y')
    else:
        client2_name = ''
        client2_address = ''
        client2_contact_number = ''
        client2_email = ''
        client2_dob = ''
        client2_id_verified = ''
        client2_date_of_last_aml = ''

    if file.authorised_party1:
        ap1_name = file.authorised_party1.name
        ap1_addr = f'{file.authorised_party1.address_line1}, {file.authorised_party1.address_line2},<br>{
            file.authorised_party1.county}, {file.authorised_party1.postcode}'
        ap1_email = file.authorised_party1.email
        ap1_contact_number = file.authorised_party1.contact_number
        ap1_date_id_check = file.authorised_party1.date_of_id_check
        ap1_relationship = file.authorised_party1.relationship_to_client
    else:
        ap1_name = ''
        ap1_addr = ''
        ap1_email = ''
        ap1_contact_number = ''
        ap1_date_id_check = ''
        ap1_relationship = ''

    if file.authorised_party2:
        ap2_name = file.authorised_party2.name
        ap2_addr = f'{file.authorised_party2.address_line1}, {file.authorised_party2.address_line2},<br>{
            file.authorised_party2.county}, {file.authorised_party2.postcode}'
        ap2_email = file.authorised_party2.email
        ap2_contact_number = file.authorised_party2.contact_number
        ap2_date_id_check = file.authorised_party2.date_of_id_check
        ap2_relationship = file.authorised_party2.relationship_to_client
    else:
        ap2_name = ''
        ap2_addr = ''
        ap2_email = ''
        ap2_contact_number = ''
        ap2_date_id_check = ''
        ap2_relationship = ''

    if file.other_side:
        other_side_name = file.other_side.name
        other_side_address = f'{file.other_side.name}, {file.other_side.address_line1},<br>{
            file.other_side.address_line2}, {file.other_side.postcode}'
        other_side_mobile = file.other_side.contact_number
        other_side_email = file.other_side.email
        other_side_solicitors = file.other_side.solicitors
        other_side_solicitors_email = file.other_side.solicitors_email
    else:
        other_side_name = ''
        other_side_address = ''
        other_side_mobile = ''
        other_side_email = ''
        other_side_solicitors = ''
        other_side_solicitors_email = ''
    undertakings = ''
    undertakings_obj = Undertaking.objects.filter(file_number=file)

    for undertaking in undertakings_obj:
        if undertaking.date_discharged:
            undertakings += f'''<li><s>{undertaking.description} to {undertaking.given_to} by {undertaking.given_by}</s>
              Discharged by {undertaking.discharged_by} on {undertaking.date_discharged.strftime('%d/%m/%Y')}
            </li>'''
        else:
            undertakings += f'<li>{undertaking.description} to {undertaking.given_to} by {undertaking.given_by}</li>'

    html = f"""
    <html>
        <head>
            <style>{page_style}</style>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=0.8">
            <title>{title}</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet" integrity="sha384-T3c6CoIi6uLrA9TneNEoa7RxnatzjcDSCmG1MXxSR1GAsXEV/Dwwykc2MPK8M2HN" crossorigin="anonymous"/>

        </head>
        <body style="font-family: Times New Roman, Times, serif; font-size:9pt !important;" class='vh-100'>
            <table class="table table-bordered table-sm" border="1" style="margin-left:50pt;  border-color: black;" cellpadding="2" cellspacing="0" >
                <tbody>
                <tr>
                    <td style="font-weight: 900; font-size:12px;" ><h3>FILE NUMBER</h3></td>
                    <td style="font-weight: 900 !important; font-size:16px; !important; text-align:center !important;" colspan='2'>{file.file_number}</td>

                </tr>
                <tr>
                    <td style="background-color:grey;"  colspan='3'></td>
                </tr>
                <tr>
                    <td class='' colspan='3'><b>CLIENT DETAILS</b></td>
                </tr>
                <tr>
                    <td></td>
                    <td class='text-center'><b>CLIENT 1</b></td>
                    <td class='text-center'><b>CLIENT 2</b></td>
                </tr>
                <tr>
                    <td>NAME</td>
                    <td class='text-center'>{file.client1.name}</td>
                    <td class='text-center'>{client2_name}</td>
                </tr>
                <tr>
                    <td>ADDRESS</td>
                    <td class='text-center'>{file.client1.address_line1}, {file.client1.address_line2},<br>{file.client1.county}, {file.client1.postcode}</td>
                    <td class='text-center'>{client2_address}</td>
                </tr>
                <tr>
                    <td>CONTACT NO.</td>
                    <td class='text-center'>{file.client1.contact_number}</td>
                    <td class='text-center'>{client2_contact_number}</td>
                </tr>
                <tr>
                    <td>EMAIL</td>
                    <td class='text-center'>{file.client1.email}</td>
                    <td class='text-center'>{client2_email}</td>
                </tr>
                 <tr >
                    <td>DATE OF BIRTH</td>
                    <td class='text-center'>{file.client1.dob.strftime('%d/%m/%Y') if file.client1.dob != None else None}</td>
                    <td class='text-center'>{client2_dob}</td>
                </tr>
                <tr >
                    <td>DATE OF LAST AML CHECK</td>
                    <td class='text-center'>{file.client1.date_of_last_aml.strftime('%d/%m/%Y') if file.client1.date_of_last_aml else None}</td>
                    <td class='text-center'>{client2_date_of_last_aml}</td>
                </tr>
                <tr>
                    <td>ID VERIFIED</td>
                    <td class='text-center'>{'Yes' if file.client1.id_verified else 'No'}</td>
                    <td class='text-center'>{client2_id_verified}</td>
                </tr>
                <tr>
                    <td style="background-color:grey;"  colspan='3'></td>
                </tr>
                <tr>
                    <td></td>
                    <td class='text-center'><b>SENT</b></td>
                    <td class='text-center'><b>RECEIVED</b></td>
                </tr>
                <tr>
                    <td>TERMS OF ENGAGEMENT</td>
                    <td class='text-center'>{file.date_of_toe_sent.strftime('%d/%m/%Y') if file.date_of_toe_sent else ''}</td>
                    <td class='text-center'>{file.date_of_toe_rcvd.strftime('%d/%m/%Y') if file.date_of_toe_rcvd else ''}</td>
                </tr>
                <tr>
                    <td>NCBA</td>
                    <td class='text-center'>{file.date_of_ncba_sent.strftime('%d/%m/%Y') if file.date_of_ncba_sent else ''}</td>
                    <td class='text-center'>{file.date_of_ncba_rcvd.strftime('%d/%m/%Y') if file.date_of_ncba_rcvd else ''}</td>
                </tr>
                <tr>
                    <td>CLIENT CARE LETTER SENT</td>
                    <td class='text-center' colspan='2'>{file.date_of_client_care_sent.strftime('%d/%m/%Y') if file.date_of_client_care_sent else ''}</td>
                </tr>
                <tr>
                    <td>FUNDING</td>
                    <td class='text-center' colspan='2'>{'Private Funding' if file.funding == 'PF' else file.funding}</td>
                </tr>
                <tr>
                    <td style="background-color:grey;"  colspan='3'></td>
                </tr>
                <tr>
                    <td class='' colspan='3'>AUTHORISED PARTIES</td>
                </tr>
                <tr>
                    <td></td>
                    <td class='text-center'><b>AUTHORISED PARTY 1</b></td>
                    <td class='text-center'><b>AUTHORISED PARTY 2</b></td>
                </tr>
                <tr>
                    <td>NAME</td>
                    <td class='text-center'>{ap1_name}</td>
                    <td class='text-center'>{ap2_name}</td>
                </tr>
                <tr>
                    <td>RELATIONSHIP</td>
                    <td class='text-center'>{ap1_relationship}</td>
                    <td class='text-center'>{ap2_relationship}</td>
                </tr>
                <tr>
                    <td>EMAIL</td>
                    <td class='text-center'>{ap1_email}</td>
                    <td class='text-center'>{ap2_email}</td>
                </tr>
                <tr>
                    <td>ADDRESS</td>
                    <td class='text-center'>{ap1_addr}</td>
                    <td class='text-center'>{ap2_addr}</td>
                </tr>
                <tr>
                    <td>CONTACT NUMBER</td>
                    <td class='text-center'>{ap1_contact_number}</td>
                    <td class='text-center'>{ap2_contact_number}</td>
                </tr>
                <tr>
                    <td>DATE OF ID CHECK</td>
                    <td class='text-center'>{ap1_date_id_check}</td>
                    <td class='text-center'>{ap2_date_id_check}</td>
                </tr>
                <tr>
                    <td style="background-color:grey;"  colspan='3'></td>
                </tr>
                <tr>
                    <td colspan='3'><b>OTHER SIDE'S DETAILS</b></td>
                </tr>
                <tr>
                    <td>NAME</td>
                    <td class='text-center' colspan='2'>{other_side_name}</td>
                </tr>
                <tr>
                    <td>ADDRESS</td>
                    <td class='text-center' colspan='2'>{other_side_address}</td>
                </tr>
                <tr>
                    <td>MOBILE</td>
                    <td class='text-center' colspan='2'>{other_side_mobile}</td>
                </tr>
                <tr>
                    <td>EMAIL</td>
                    <td class='text-center' colspan='2'>{other_side_email}</td>
                </tr>
                <tr>
                    <td>SOLICITORS</td>
                    <td class='text-center' colspan='2'>{other_side_solicitors}</td>
                </tr>
                <tr>
                    <td>SOLICITORS - EMAIL</td>
                    <td class='text-center' colspan='2'>{other_side_solicitors_email}</td>
                </tr>
                <tr>
                    <td style="background-color:grey;"  colspan='3'></td>
                </tr>
                <tr>
                    <td class='' colspan='3'><b>UNDERTAKINGS</b> (discharged undertakings will be striked through)</td>
                </tr>
                <tr>
                    <td class='' colspan='3'><ul>{undertakings}</ul></td>
                </tr>
                <tr>
                    <td style="background-color:grey;"  colspan='3'></td>
                </tr>
                <tr>
                    <td class='' colspan='3'><b>KEY INFORMATION</b></td>
                </tr>
                <tr>
                    <td class='' colspan='3'>{file.key_information}</td>
                </tr>

                </tbody>
            </table>
        </body>
    </html>
     """

    pdf_file = HTML(string=html).write_pdf()
    response = HttpResponse(pdf_file, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="frontsheet_{
        file_number}_{request.user}_{datetime.now().strftime('%d/%m/%Y %I:%M %p.pdf"')}'
    return response


@login_required
def download_risk_assessment(request, id):
    risk_assessment = get_object_or_404(RiskAssessment, pk=id)
    html_string = render_to_string(
        'download_templates/risk_assessment.html', {"obj": risk_assessment})

    pdf_file = HTML(string=html_string).write_pdf()

    response = HttpResponse(pdf_file, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="risk_assessment_{risk_assessment.matter.file_number}_{id}.pdf"'
    return response


@login_required
def add_ongoing_monitoring(request, file_number):
    try:
        matter = WIP.objects.get(file_number=file_number)
    except WIP.DoesNotExist:
        messages.error(
            request, 'Matter with the given file number does not exist.')
        return redirect('index')
    if request.method == 'POST':
        post_data = request.POST.copy()
        post_data['created_by'] = request.user
        post_data['file_number'] = matter.id
        form = OngoingMonitoringForm(post_data)

        if form.is_valid():
            ongoing_monitoring = form.save()
            messages.success(
                request, 'Ongoing Monitoring successfully recorded.')
            return redirect('home', ongoing_monitoring.file_number.file_number)
        else:
            error_message = 'Form is not valid. Please correct the errors:'
            for field, errors in form.errors.items():
                error_message += f'\n{field}: {", ".join(errors)}'
            messages.error(request, error_message)
    else:
        form = OngoingMonitoringForm()
        return render(request, 'ongoing_monitoring.html', {'form': form, 'file_number': file_number, 'title': 'Add'})


@login_required
def policies_display(request):
    latest_version_subquery = PolicyVersion.objects.filter(
        policy=OuterRef('pk')
    ).order_by('-version_number').values('pk')[:1]

    policies = Policy.objects.annotate(
        latest_version_id=Subquery(latest_version_subquery),
        is_read=Exists(
            PoliciesRead.objects.filter(
                policy=OuterRef('pk'),
                policy_version_id=OuterRef('latest_version_id'),
                read_by=request.user
            )
        )
    ).order_by('description')

    policies_read = PoliciesRead.objects.filter(
        read_by=request.user).order_by('-timestamp')
    any_unread = policies.filter(is_read=False).exists()
    context = {
        'policies': policies,
        'policies_read': policies_read,
        'all_read': not any_unread

    }

    return render(request, 'policies/policies_home.html', context)


@login_required
def policy_read(request, policy_id):
    policy = get_object_or_404(Policy, pk=policy_id)

    latest_version = policy.versions.order_by('-version_number').first()

    if not latest_version:
        messages.error(
            request, f"No versions available for policy '{policy.description}'.")
        return redirect('policies_display')

    try:
        PoliciesRead.objects.create(
            policy=policy, policy_version=latest_version, read_by=request.user)
        messages.success(
            request, f'Successfully marked the latest version of "{policy.description}" as read.')
    except Exception as e:
        messages.error(request, f"An error occurred: {str(e)}")

    return redirect('policies_display')


@login_required
def add_policy(request):
    if not request.user.is_manager:
        messages.error(request, "You do not have permission to add policies.")
        return redirect('policies_display')

    if request.method == 'POST':
        form = PolicyForm(request.POST)
        if form.is_valid():
            try:
                policy = form.save()
                PolicyVersion.objects.create(
                    policy=policy,
                    content=form.cleaned_data['content'],
                    version_number=1,
                    changes_by=request.user,
                    timestamp=timezone.now()
                )
                messages.success(request, "Policy added successfully.")
                return redirect('policies_display')
            except Exception as e:
                messages.error(
                    request, f"An error occurred while adding the policy: {str(e)}")
        else:
            messages.error(
                request, "There were errors in the form. Please correct them and try again.")
    else:
        form = PolicyForm()

    return render(request, 'policies/add_policy.html', {'form': form})


@login_required
def edit_policy(request, policy_id):
    policy = get_object_or_404(Policy, id=policy_id)

    if not request.user.is_manager:
        messages.error(request, "You do not have permission to edit policies.")
        return redirect('policies_display')

    if request.method == 'POST':
        form = PolicyForm(request.POST, instance=policy)
        if form.is_valid():
            try:

                new_content = form.cleaned_data['content']
                latest_version = policy.versions.order_by(
                    '-version_number').first()

                if latest_version is None or latest_version.content != new_content:
                    # Determine new version number
                    version_number = latest_version.version_number + 1 if latest_version else 1

                    # Create a new PolicyVersion with the updated content
                    PolicyVersion.objects.create(
                        policy=policy,
                        content=new_content,
                        version_number=version_number,
                        changes_by=request.user,
                        timestamp=timezone.now()
                    )

                form.save()
                messages.success(request, "Policy edited successfully.")
                return redirect('policies_display')
            except Exception as e:
                messages.error(
                    request, f"An error occurred while editing the policy: {str(e)}")
        else:
            messages.error(
                request, "There were errors in the form. Please correct them and try again.")
    else:
        form = PolicyForm(instance=policy)

    return render(request, 'policies/edit_policy.html', {'form': form, 'policy': policy})


@login_required
def download_policy_pdf(request, policy_version_id):
    #
    policy_version = get_object_or_404(PolicyVersion, id=policy_version_id)

    try:
        html_string = render_to_string('download_templates/policy_pdf.html', {
            'policy_version': policy_version
        })

        # Create the PDF using WeasyPrint
        html = HTML(string=html_string)
        pdf = html.write_pdf()

        response = HttpResponse(pdf, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="Policy_{policy_version.policy.id}_Version_{policy_version.version_number}.pdf"'

        return response

    except Exception as e:
        print(e)
        messages.error(
            request, f"An error occurred while generating the PDF: {str(e)}")
        return redirect('policies_display')


@login_required
def invoices_list(request):
    # Get start and end dates from GET parameters
    start_date = request.GET.get('start_date')

    # Calculate current financial year if start and end are not provided
    current_date = timezone.now()
    if not start_date:
        if current_date.month >= 11:  # November to October financial year
            start_date = datetime(current_date.year, 11, 1)
            end_date = datetime(current_date.year + 1, 10, 31)
        else:
            start_date = datetime(current_date.year - 1, 11, 1)
            end_date = datetime(current_date.year, 10, 31)
    else:
        # Parse dates from GET parameters
        try:
            start_date = datetime.strptime(start_date, '%Y-%m')
            end_date = start_date.replace(
                year=start_date.year + 1, month=10, day=31)

        except ValueError:
            messages.error(
                request, 'Invalid date format. Please use YYYY-MM-DD.')
            return redirect('index')

    # Filter invoices by finalized state and date range
    invoices = Invoices.objects.filter(
        state='F', date__range=[start_date, end_date])

    if request.user.is_manager:
        approved_credit_totals = get_approved_credit_note_totals(
            [invoice.id for invoice in invoices]
        )
        for invoice in invoices:
            total_cost_invoice, vat_inv, total_cost_and_vat = calculate_invoice_total_with_vat(
                invoice)
            effective_due = get_effective_invoice_due(
                invoice, approved_credit_totals.get(invoice.id, Decimal('0')))

            # Update invoice attributes dynamically
            invoice.our_costs = total_cost_invoice
            invoice.vat = round(vat_inv, 2)
            invoice.total_cost_and_vat = total_cost_and_vat
            invoice.total_due_left = effective_due

        # Render template with invoices and date range
        return render(request, 'invoices_list.html', {
            'invoices': invoices,
            'start_date': start_date,
            'end_date': end_date,
        })
    else:
        messages.error(
            request, 'You do not have the right level of permissions.')
        return redirect('index')


@login_required
def download_invoices(request):

    if request.method == 'POST' and request.user.is_manager:

        start_date_str = request.POST['start']
        end_date_str = request.POST['end']
        start_date = datetime.strptime(start_date_str, '%d/%m/%Y')
        end_date = datetime.strptime(end_date_str, '%d/%m/%Y')

        invoices = Invoices.objects.filter(
            state='F', date__range=[start_date, end_date])

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="Invoices_from_{start_date_str}_to_{end_date_str}.csv"'

        writer = csv.writer(response)

        writer.writerow(
            ['', f'Invoices from {start_date_str} to {end_date_str}'])

        writer.writerow([])
        writer.writerow(['Invoice Number', 'Matter Type', 'Date',
                        'File Number', 'Our Costs', 'VAT', 'Total Costs and VAT'])

        for invoice in invoices:
            total_cost_invoice, vat_inv, total_cost_and_vat = calculate_invoice_total_with_vat(
                invoice)

            writer.writerow([f'{invoice.invoice_number}', f'{invoice.file_number.matter_type.type}', f'{invoice.date.strftime("%d/%m/%Y")}',
                            f'{invoice.file_number.file_number}', f'{total_cost_invoice}', f'{vat_inv}', f'{total_cost_and_vat}'])

        return response


@login_required
def edit_risk_assessment(request, id):
    try:
        risk_assesssment = get_object_or_404(RiskAssessment, pk=id)
    except Exception as e:
        messages.error(request, f'Risk Assessment not found. {str(e)}')
        return redirect('index')
    if request.method == 'POST':
        duplicate_obj = copy.deepcopy(risk_assesssment)
        form = RiskAssessmentForm(request.POST, instance=risk_assesssment)
        if form.is_valid():
            changed_fields = form.changed_data
            changes = {}
            for field in changed_fields:
                changes[field] = {
                    'old_value': str(getattr(duplicate_obj, field)),
                    'new_value': None
                }
            form.save()

            for field in changed_fields:
                changes[field]['new_value'] = str(
                    getattr(risk_assesssment, field))

            create_modification(
                user=request.user,
                modified_obj=risk_assesssment,
                changes=changes
            )
            messages.success(request, 'Successfully updated Risk Assessment.')
            return redirect('home', risk_assesssment.matter.file_number)
        else:
            error_message = 'Form is not valid. Please correct the errors:'
            for field, errors in form.errors.items():
                error_message += f'\n{field}: {", ".join(errors)}'
            messages.error(request, error_message)
    else:
        form = RiskAssessmentForm(instance=risk_assesssment)

    return render(request, 'risk_assessment.html', {'form': form, 'file_number': risk_assesssment.matter.file_number, 'title': 'Edit'})


@login_required
def edit_ongoing_monitoring(request, id):
    try:
        ongoing_monitoring = get_object_or_404(OngoingMonitoring, pk=id)
    except Exception as e:
        messages.error(request, f'Ongoing Monitoring not found. {str(e)}')
        return redirect('index')
    if request.method == 'POST':
        duplicate_obj = copy.deepcopy(ongoing_monitoring)
        post_copy = request.POST.copy()
        post_copy['file_number'] = ongoing_monitoring.file_number.id
        post_copy['created_by'] = ongoing_monitoring.created_by
        form = OngoingMonitoringForm(post_copy, instance=ongoing_monitoring)
        if form.is_valid():
            changed_fields = form.changed_data
            changes = {}
            for field in changed_fields:
                changes[field] = {
                    'old_value': str(getattr(duplicate_obj, field)),
                    'new_value': None
                }
            form.save()

            for field in changed_fields:
                changes[field]['new_value'] = str(
                    getattr(ongoing_monitoring, field))

            create_modification(
                user=request.user,
                modified_obj=ongoing_monitoring,
                changes=changes
            )
            messages.success(
                request, 'Successfully updated Ongoing Monitoring.')
            return redirect('home', ongoing_monitoring.file_number.file_number)
        else:
            error_message = 'Form is not valid. Please correct the errors:'
            for field, errors in form.errors.items():
                error_message += f'\n{field}: {", ".join(errors)}'
            messages.error(request, error_message)
    else:
        form = OngoingMonitoringForm(instance=ongoing_monitoring)

    return render(request, 'ongoing_monitoring.html', {'form': form, 'file_number': ongoing_monitoring.file_number.file_number, 'title': 'Edit'})


@login_required
def download_ongoing_monitoring(request, id):
    obj = get_object_or_404(OngoingMonitoring, pk=id)
    html_string = render_to_string(
        'download_templates/ongoing_monitoring.html', {"obj": obj})

    pdf_file = HTML(string=html_string).write_pdf()

    response = HttpResponse(pdf_file, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="ongoing_monitoring_{obj.file_number.file_number}_{id}.pdf"'
    return response


@login_required
def onboarding_documents_display(request):
    if request.method == "POST":
        file = request.POST['file']
        html_string = render_to_string(file)

        pdf_file = HTML(string=html_string).write_pdf()

        response = HttpResponse(pdf_file, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{file}_document.pdf"'
        return response
    else:
        return render(request, 'onboarding_documents.html')


@login_required
def download_document(request):

    file_name = 'pep_questionnaire.doc'
    file_dir = 'files'
    file_path = None

    # Check each directory in STATICFILES_DIRS
    for static_dir in settings.STATICFILES_DIRS:
        potential_path = os.path.join(static_dir, file_dir, file_name)
        if os.path.exists(potential_path):
            file_path = potential_path
            break

    if file_path and os.path.exists(file_path):
        response = FileResponse(open(
            file_path, 'rb'), content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        response['Content-Disposition'] = f'attachment; filename={file_name}'
        return response
    else:
        raise Http404("File does not exist")


def free30mins(request):
    free_30mins_meetings = Free30Mins.objects.all().order_by('-date')
    free30_mins_form = Free30MinsForm()
    free30_mins_attendees_form = Free30MinsAttendeesForm()

    if request.method == 'POST':
        try:
            number_of_attendees = int(request.POST['number_of_attendees'])
            attendee_ids = []

            for i in range(number_of_attendees):
                index = f'{i}_' if i > 0 else ''
                name = request.POST[f'{index}name']
                address_line1 = request.POST[f'{index}address_line1']
                address_line2 = request.POST[f'{index}address_line2']
                county = request.POST[f'{index}county']
                postcode = request.POST[f'{index}postcode']
                email = request.POST[f'{index}email']
                contact_number = request.POST[f'{index}contact_number']
                created_by = request.user

                attendee = Free30MinsAttendees.objects.create(
                    name=name,
                    address_line1=address_line1,
                    address_line2=address_line2,
                    county=county,
                    postcode=postcode,
                    email=email,
                    contact_number=contact_number,
                    created_by=created_by,
                )
                attendee.save()
                attendee_ids.append(attendee.id)

            matter_type_id = request.POST['matter_type']
            matter_type = MatterType.objects.filter(
                pk=matter_type_id).first() if matter_type_id != '' else None
            notes = request.POST['notes']

            date = request.POST['date']
            start_time = request.POST['start_time']
            finish_time = request.POST['finish_time']
            fee_earner_id = request.POST['fee_earner']
            fee_earner = CustomUser.objects.filter(pk=fee_earner_id).first()
            created_by = request.user

            free_30_mins = Free30Mins.objects.create(
                matter_type=matter_type,
                notes=notes,
                date=date,
                start_time=start_time,
                finish_time=finish_time,
                fee_earner=fee_earner,
                created_by=created_by
            )

            # Assign attendees to the meeting
            free_30_mins.attendees.set(attendee_ids)

            free_30_mins.save()
            messages.success(request, "Meeting successfully created.")
            return redirect('free30mins')

        except Exception as e:
            messages.error(request, f"An error occurred: {e}")

    return render(request, 'free_30mins.html', {
        'free30_mins_form': free30_mins_form,
        'free30_mins_attendees_form': free30_mins_attendees_form,
        'meetings': free_30mins_meetings
    })


def download_free30mins(request, id):
    obj = Free30Mins.objects.filter(id=id).first()

    obj_dict = {
        'id': obj.id,
        # Adjust attribute if needed
        'matter_type': obj.matter_type.type if obj.matter_type else None,
        # Assuming QuillField stores HTML content
        'notes': mark_safe(obj.notes.html),
        'date': obj.date,
        'start_time': obj.start_time,
        'finish_time': obj.finish_time,
        # Adjust attribute if needed
        'attendees': [{
            'name': attendee.name,
            'address_line1': attendee.address_line1,
            'address_line2': attendee.address_line2,
            'county': attendee.county,
            'postcode': attendee.postcode,
            'email': attendee.email,
            'contact_number': attendee.contact_number,
        } for attendee in obj.attendees.all()],
        'fee_earner': obj.fee_earner.username if obj.fee_earner else None,
        'created_by': obj.created_by.username if obj.created_by else None,
        'timestamp': obj.timestamp,
    }

    html_string = render_to_string(
        'download_templates/free_30mins.html', obj_dict)
    pdf_file = HTML(string=html_string).write_pdf()

    return HttpResponse(pdf_file, content_type='application/pdf')


def edit_free30mins(request, id):
    instance = get_object_or_404(Free30Mins, pk=id)
    if request.method == 'POST':

        duplicate_obj = copy.deepcopy(instance)
        form = Free30MinsForm(
            request.POST, instance=instance)

        if form.is_valid():
            changed_fields = form.changed_data
            changes = {}
            for field in changed_fields:
                if field == 'content':
                    changes[field] = {
                        'old_value': duplicate_obj.content.html,
                        'new_value': None
                    }
                else:
                    changes[field] = {
                        'old_value': str(getattr(duplicate_obj, field)),
                        'new_value': None
                    }
            form.save()

            for field in changed_fields:
                if field == 'content':
                    changes[field]['new_value'] = instance.content.html
                else:
                    changes[field]['new_value'] = str(
                        getattr(instance, field))

            create_modification(
                user=request.user,
                modified_obj=instance,
                changes=changes
            )
            messages.success(request, 'Successfully updated Free 30 Mins.')
            return redirect('free30mins')
        else:
            error_message = 'Form is not valid. Please correct the errors:'
            for field, errors in form.errors.items():
                error_message += f'\n{field}: {", ".join(errors)}'
            messages.error(request, error_message)
    else:
        form = Free30MinsForm(instance=instance)

    return render(request, 'edit_models.html', {'form': form, 'title': 'Free 30 Mins'})


@login_required
def undertakings(request):
    # If the request is a POST (form submission), process the form data
    if request.method == 'POST':
        request_post_copy = request.POST.copy()

        file = WIP.objects.filter(
            file_number=request_post_copy.get('file_number')).first().id
        request_post_copy['file_number'] = file
        form = UndertakingForm(request_post_copy, request.FILES)
        if form.is_valid():
            undertaking = form.save(commit=False)

            # Automatically assign fields that are not user inputs
            undertaking.created_by = request.user
            undertaking.date_discharged = None
            undertaking.discharged_proof = None
            undertaking.discharged_by = None

            # Save the undertaking object
            undertaking.save()

            messages.success(
                request, "Undertaking has been successfully created.")
            return redirect('undertakings')
        else:
            # Iterate through form errors and display them
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")

    else:
        # If the request is a GET, load a blank form
        form = UndertakingForm()

    # Fetch all undertakings to display in the template
    undertakings = Undertaking.objects.all()

    undertakings_pending = undertakings.filter(date_discharged=None).count()

    return render(request, 'undertakings.html', {'form': form, 'undertakings': undertakings, 'undertakings_pending': undertakings_pending})


@login_required
def edit_undertaking(request, id):
    # Get the specific undertaking object
    undertaking = get_object_or_404(Undertaking, pk=id)

    # Get list of users and WIPs for the dropdowns
    users = CustomUser.objects.all().order_by('username')
    wips = WIP.objects.all().order_by('file_number')

    if request.method == 'POST':
        try:
            # Get the form data from the request
            undertaking.file_number_id = request.POST.get('file_number')
            undertaking.date_given = request.POST.get('date_given')
            undertaking.given_to = request.POST.get('given_to')
            undertaking.description = request.POST.get('description')
            undertaking.given_by_id = request.POST.get('given_by')

            # Handle file upload for document_given_on
            if request.FILES.get('document_given_on'):
                undertaking.document_given_on = request.FILES['document_given_on']

            undertaking.date_discharged = request.POST.get('date_discharged')
            undertaking.discharged_by_id = request.POST.get('discharged_by')

            # Handle file upload for discharged_proof
            if request.FILES.get('discharged_proof'):
                undertaking.discharged_proof = request.FILES['discharged_proof']

            # Save the updated undertaking
            undertaking.save()

            # Display success message
            messages.success(request, 'Undertaking updated successfully.')

            # Redirect to the list view or wherever appropriate
            return redirect('undertakings')

        except Exception as e:
            # If there was an error, log the exception (if needed) and display an error message
            messages.error(request, f'Error updating undertaking: {str(e)}')

    # Render the template with the undertaking object and other context
    context = {
        'undertaking': undertaking,
        'users': users,
        'wips': wips,
    }
    return render(request, 'forms/edit_undertaking.html', context)


@login_required
def management_reports(request):
    users = CustomUser.objects.filter(is_active=True).order_by('username')

    twelve_months_ago = timezone.now() - relativedelta(months=11)
    aml_checks_due_client1 = WIP.objects.filter(
        Q(file_status__status='Open') &
        Q(client1__date_of_last_aml__lte=twelve_months_ago)
    ).annotate(
        client_id=F('client1__id'),
        client_name=F('client1__name'),
        date_of_last_aml=F('client1__date_of_last_aml')
    ).values('client_id', 'client_name', 'date_of_last_aml')

    aml_checks_due_client2 = WIP.objects.filter(
        Q(file_status__status='Open') &
        Q(client2__date_of_last_aml__lte=twelve_months_ago)
    ).annotate(
        client_id=F('client2__id'),
        client_name=F('client2__name'),
        date_of_last_aml=F('client2__date_of_last_aml')
    ).values('client_id', 'client_name', 'date_of_last_aml')

    client1_results = list(aml_checks_due_client1)
    client2_results = list(aml_checks_due_client2)

    unique_clients = {}
    for result in client1_results + client2_results:
        unique_clients[result['client_id']] = {
            'client_name': result['client_name'],
            'date_of_last_aml': result['date_of_last_aml']
        }

    unique_aml_checks_due = [
        {'client_id': client_id,
            'client_name': data['client_name'], 'date_of_last_aml': data['date_of_last_aml']}
        for client_id, data in unique_clients.items()
    ]
    unique_aml_checks_due = sorted(
        unique_aml_checks_due, key=lambda x: x['client_name'])

    risk_assessments_due = get_risk_assessments_due_queryset(WIP.objects.all())
    cpds = CPDTrainingLog.objects.all()

    return render(request, 'management_reports.html', {
        'users': users,
        'aml_checks_due': unique_aml_checks_due,
        'risk_assessments_due': risk_assessments_due,
        'cpds': cpds
    })


@login_required
def export_user_tasks_pdf(request):
    """Export selected user's tasks as a PDF for printing and sending"""
    user_id = request.GET.get('user_id')

    if not user_id:
        return JsonResponse({'error': 'User ID is required'}, status=400)

    try:
        user = CustomUser.objects.get(id=user_id)
    except CustomUser.DoesNotExist:
        return JsonResponse({'error': 'User not found'}, status=404)

    # Get user's tasks
    tasks = NextWork.objects.filter(person=user).select_related(
        'file_number', 'created_by').order_by('status', 'urgency', 'date')

    # Separate by status
    to_do_tasks = tasks.filter(status='to_do')
    in_progress_tasks = tasks.filter(status='in_progress')
    completed_tasks = tasks.filter(status='completed')

    # Render HTML template for PDF
    html_string = render_to_string('download_templates/user_tasks_export.html', {
        'user': user,
        'to_do_tasks': to_do_tasks,
        'in_progress_tasks': in_progress_tasks,
        'completed_tasks': completed_tasks,
        'export_date': timezone.now(),
        'total_tasks': tasks.count(),
    })

    # Generate PDF
    pdf_file = HTML(string=html_string).write_pdf()

    response = HttpResponse(pdf_file, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="tasks_{user.first_name}_{user.last_name}_{timezone.now().strftime("%Y%m%d")}.pdf"'

    return response


@login_required
def load_management_tasks(request):
    """AJAX endpoint to load tasks for management kanban board"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'})

    try:
        data = json.loads(request.body)
        count = data.get('count', 5)
        filter_user_ids = data.get('filter_user_ids', [])

        # Base query
        tasks_query = NextWork.objects.select_related(
            'file_number', 'person', 'created_by')

        # Apply user filter
        if filter_user_ids:
            tasks_query = tasks_query.filter(person_id__in=filter_user_ids)

        # Get tasks by status
        tasks_data = {}
        total_counts = {}

        for status in ['to_do', 'in_progress', 'completed']:
            if status == 'completed':
                # For completed, only show this week's tasks
                one_week_ago = timezone.now() - timedelta(days=7)
                status_tasks = tasks_query.filter(
                    status=status,
                    timestamp__gte=one_week_ago
                ).order_by('-timestamp')
            else:
                # For to_do and in_progress, sort by urgency and due date
                status_tasks = tasks_query.filter(status=status).order_by(
                    '-urgency', 'date', '-timestamp'
                )

            total_counts[status] = status_tasks.count()

            # Limit tasks if count is specified
            if count != 'all':
                status_tasks = status_tasks[:int(count)]

            # Serialize tasks
            tasks_data[status] = []
            for task in status_tasks:
                tasks_data[status].append({
                    'id': task.id,
                    'file_number': task.file_number.file_number if task.file_number else 'N/A',
                    'task': task.task,
                    'date': task.date.isoformat() if task.date else None,
                    'urgency': task.urgency,
                    'status': task.status,
                    'assigned_to': f"{task.person.first_name} {task.person.last_name}" if task.person else 'Unassigned',
                    'created_by': f"{task.created_by.first_name} {task.created_by.last_name}" if task.created_by else 'Unknown',
                    'timestamp': task.timestamp.isoformat() if task.timestamp else None,
                })

        return JsonResponse({
            'success': True,
            'tasks': tasks_data,
            'total_counts': total_counts
        })

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


def calculate_minutes_for_date(user, date):
    billed_minutes = 0
    non_billed_minutes = 0

    # Free 30-Minute Meetings (Non-Billed)
    free_30_mins = Free30Mins.objects.filter(fee_earner=user, date=date)
    for meeting in free_30_mins:
        duration = (datetime.combine(date, meeting.finish_time) -
                    # Convert to minutes
                    datetime.combine(date, meeting.start_time)).seconds / 60
        non_billed_minutes += duration

    # Matter Emails (Billed)
    matter_emails = MatterEmails.objects.filter(
        fee_earner=user, time__date=date)
    for email in matter_emails:
        billed_minutes += (email.units or 0) * 6  # Assuming 1 unit = 6 minutes

    # Attendance Notes
    attendance_notes = MatterAttendanceNotes.objects.filter(
        person_attended=user, date=date)
    for note in attendance_notes:
        duration = (datetime.combine(date, note.finish_time) -
                    # Convert to minutes
                    datetime.combine(date, note.start_time)).seconds / 60
        if note.is_charged:
            billed_minutes += duration
        else:
            non_billed_minutes += duration

    # Total minutes in a day
    total_minutes = 7.5 * 60  # 7.5 hours in minutes
    missing_minutes = max(
        0, total_minutes - (billed_minutes + non_billed_minutes))

    return {
        "billed_minutes": round(billed_minutes),
        "non_billed_minutes": round(non_billed_minutes),
        "missing_minutes": round(missing_minutes),
    }


def calculate_weekly_report(user, start_date):
    weekly_report = []
    for i in range(7):  # Iterate through the week
        date = start_date + timedelta(days=i)
        # Skip Saturdays and Sundays
        if date.weekday() in [5, 6]:
            continue
        daily_data = calculate_minutes_for_date(user, date)
        weekly_report.append({
            "date": date.strftime("%a, %d/%m/%Y "),
            **daily_data,
        })
    return weekly_report


@login_required
def weekly_report_view(request):
    user_id = request.GET.get("user")
    week_start = request.GET.get("week_start")

    if not user_id or not week_start:
        return JsonResponse({"error": "Invalid parameters"}, status=400)

    try:
        user = CustomUser.objects.get(id=user_id)
        week_start_date = datetime.strptime(week_start, "%Y-%m-%d").date()
        data = calculate_weekly_report(user, week_start_date)
        return JsonResponse(data, safe=False)
    except CustomUser.DoesNotExist:
        return JsonResponse({"error": "User not found"}, status=404)


@login_required
def policies_read_per_user(request):
    user_id = request.GET.get("user_id")

    if not user_id:
        return JsonResponse({"error": "User ID is required"}, status=400)

    try:
        user = CustomUser.objects.get(id=user_id)
    except CustomUser.DoesNotExist:
        return JsonResponse({"error": "User not found"}, status=404)

    # Total number of policies
    total_policies = Policy.objects.count()

    # Get the latest version of each policy
    latest_versions = PolicyVersion.objects.annotate(
        max_version=Max('policy__versions__version_number')
    ).filter(version_number=F('max_version'))

    # IDs of latest policy versions
    latest_version_ids = latest_versions.values_list('id', flat=True)

    # Policies read by the user (matching the latest versions)
    read_policy_ids = PoliciesRead.objects.filter(
        read_by=user,
        policy_version_id__in=latest_version_ids
    ).values_list('policy_id', flat=True).distinct()

    # Count of latest versions read
    latest_versions_read_count = read_policy_ids.count()

    # Get unread policies
    unread_policies = Policy.objects.filter(
        ~Q(id__in=read_policy_ids)).order_by('description')

    # Prepare unread policies descriptions
    unread_policies_descriptions = list(
        unread_policies.values('id', 'description'))

    # Response
    return JsonResponse({
        "user": user.username,
        "total_policies": total_policies,
        "latest_versions_read": latest_versions_read_count,
        "policies_unread": total_policies - latest_versions_read_count,
        "unread_policies": unread_policies_descriptions
    })


@login_required
def download_aml_checks_due(request):
    twelve_months_ago = timezone.now() - relativedelta(months=11)
    aml_checks_due_client1 = WIP.objects.filter(
        Q(file_status__status='Open') &
        Q(client1__date_of_last_aml__lte=twelve_months_ago)
    ).annotate(
        client_id=F('client1__id'),
        client_name=F('client1__name'),
        date_of_last_aml=F('client1__date_of_last_aml')
    ).values('client_id', 'client_name', 'date_of_last_aml')

    aml_checks_due_client2 = WIP.objects.filter(
        Q(file_status__status='Open') &
        Q(client2__date_of_last_aml__lte=twelve_months_ago)
    ).annotate(
        client_id=F('client2__id'),
        client_name=F('client2__name'),
        date_of_last_aml=F('client2__date_of_last_aml')
    ).values('client_id', 'client_name', 'date_of_last_aml')

    client1_results = list(aml_checks_due_client1)
    client2_results = list(aml_checks_due_client2)

    unique_clients = {}
    for result in client1_results + client2_results:
        unique_clients[result['client_id']] = {
            'client_name': result['client_name'],
            'date_of_last_aml': result['date_of_last_aml']
        }

    unique_aml_checks_due = [
        {'client_id': client_id,
            'client_name': data['client_name'], 'date_of_last_aml': data['date_of_last_aml']}
        for client_id, data in unique_clients.items()
    ]
    unique_aml_checks_due = sorted(
        unique_aml_checks_due, key=lambda x: x['client_name'])

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="aml_checks_due_{timezone.now()}.csv"'

    writer = csv.writer(response)

    writer.writerow(['AML Checks Due'])
    writer.writerow(['Client Name', 'Date of Last AML Check'])

    for client in unique_aml_checks_due:
        writer.writerow([client['client_name'], client['date_of_last_aml']])

    return response


@login_required
def download_user_risk_assessments_due(request):
    user = CustomUser.objects.get(username=request.user)
    risk_scope = request.GET.get('risk_scope', 'associated')
    risk_scope_wips, validated_risk_scope = get_dashboard_risk_scope_wips(
        user, risk_scope
    )
    risk_assessments_due = get_risk_assessments_due_queryset(
        risk_scope_wips
    )

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = (
        f'attachment; filename="risk_assessments_due_{user.username}_{validated_risk_scope}_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'
    )
    writer = csv.writer(response)

    writer.writerow(['Risk Assessments Due'])
    if validated_risk_scope == 'all_active':
        writer.writerow(['Scope', 'All Open and To Be Closed files'])
    else:
        writer.writerow(['Scope', 'My associated files'])
    writer.writerow([
        'File Number',
        'Matter Description',
        'Client 1',
        'Client 2',
        'Last Risk Assessment Date',
        'Last Ongoing Monitoring Date',
        'Reason Due'
    ])

    for assessment in risk_assessments_due:
        reason_due = 'No risk assessment completed'
        if assessment.latest_assessment_date:
            reason_due = 'No ongoing monitoring in the last year'

        writer.writerow([
            assessment.file_number,
            assessment.matter_description,
            assessment.client1.name if assessment.client1 else '',
            assessment.client2.name if assessment.client2 else '',
            assessment.latest_assessment_date,
            assessment.latest_monitoring_date,
            reason_due
        ])

    return response


@login_required
def download_risk_assessments_due(request):
    risk_assessments_due = get_risk_assessments_due_queryset(WIP.objects.all())

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="risk_assessments_due_{timezone.now()}.csv"'

    writer = csv.writer(response)

    writer.writerow(['Risk Assessments Due'])
    writer.writerow([
        'File Number',
        'Matter Description',
        'Client 1',
        'Client 2',
        'Last Risk Assessment Date',
        'Last Ongoing Monitoring Date',
        'Reason Due'
    ])

    for assessment in risk_assessments_due:
        reason_due = 'No risk assessment completed'
        if assessment.latest_assessment_date:
            reason_due = 'No ongoing monitoring in the last year'

        writer.writerow([
            assessment.file_number,
            assessment.matter_description,
            assessment.client1.name if assessment.client1 else '',
            assessment.client2.name if assessment.client2 else '',
            assessment.latest_assessment_date,
            assessment.latest_monitoring_date,
            reason_due
        ])

    return response


@login_required
def add_memo(request):
    if request.method == 'POST':
        form = MemoForm(request.POST)
        if form.is_valid():
            memo = form.save(commit=False)
            memo.created_by = request.user
            memo.save()
            messages.success(request, 'Memo successfully added.')

        else:
            messages.error(
                request, 'There was an error adding the memo. Please check the form and try again.')

    return redirect('profile_page')


@login_required
def edit_memo(request, memo_id):
    memo = get_object_or_404(Memo, id=memo_id)
    if request.method == 'POST':
        form = MemoForm(request.POST, instance=memo)
        if form.is_valid():
            form.save()
            messages.success(request, 'Memo successfully updated.')
            return redirect('profile_page')
        else:
            messages.error(
                request, 'There was an error updating the memo. Please check the form and try again.')
    else:
        form = MemoForm(instance=memo)
    return render(request, 'edit_memo.html', {'form': form})


@login_required
def delete_memo(request, memo_id):
    memo = get_object_or_404(Memo, id=memo_id)
    if request.method == 'POST':
        memo.delete()
        messages.success(request, 'Memo successfully deleted.')
        return redirect('profile_page')
    else:
        messages.warning(request, 'Are you sure you want to delete this memo?')
    return render(request, 'confirm_delete.html', {'memo': memo})


@login_required
def read_memo(request, memo_id):
    memo = get_object_or_404(Memo, id=memo_id)
    PoliciesRead.objects.get_or_create(memo=memo, read_by=request.user)
    messages.success(request, 'Memo marked as read.')
    return redirect('profile_page')


# Bundle Views
@login_required
def bundle_create(request, file_number=None):
    """Create a new bundle or show existing bundles"""
    if request.method == 'POST':
        bundle_name = request.POST.get('bundle_name')
        file_number_str = request.POST.get('file_number', file_number)

        if not bundle_name:
            if request.headers.get('Content-Type') == 'application/json' or 'application/json' in request.headers.get('Accept', ''):
                return JsonResponse({'error': 'Bundle name is required.'}, status=400)
            messages.error(request, 'Bundle name is required.')
            return redirect('bundle_create')

        # Find the file if file_number is provided
        wip_file = None
        if file_number_str:
            try:
                wip_file = WIP.objects.get(file_number=file_number_str)
            except WIP.DoesNotExist:
                if request.headers.get('Content-Type') == 'application/json' or 'application/json' in request.headers.get('Accept', ''):
                    return JsonResponse({'error': f'File {file_number_str} not found.'}, status=400)
                messages.error(request, f'File {file_number_str} not found.')
                return redirect('bundle_create')

        # Create the bundle
        bundle = Bundle.objects.create(
            name=bundle_name,
            file_number=wip_file,
            created_by=request.user
        )

        # Return JSON response for AJAX requests
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.content_type.startswith('multipart/form-data'):
            return JsonResponse({
                'success': True,
                'bundle_id': bundle.id,
                'message': f'Bundle "{bundle_name}" created successfully.'
            })

        messages.success(
            request, f'Bundle "{bundle_name}" created successfully.')
        return redirect('bundle_edit', bundle_id=bundle.id)

    # Get existing bundles for the user
    bundles = Bundle.objects.filter(
        created_by=request.user).order_by('-created_at')

    # Get available files for dropdown
    files = WIP.objects.filter(
        file_status__status='Open').order_by('file_number')

    context = {
        'bundles': bundles,
        'files': files,
        'file_number': file_number
    }
    return render(request, 'bundle_create.html', context)


@login_required
def bundle_edit(request, bundle_id):
    """Edit bundle - manage sections and documents"""
    bundle = get_object_or_404(Bundle, id=bundle_id, created_by=request.user)

    if bundle.is_finalized:
        messages.warning(
            request, 'This bundle has been finalized and cannot be edited.')
        return redirect('bundle_view', bundle_id=bundle.id)

    sections = bundle.sections.all().order_by('order')

    context = {
        'bundle': bundle,
        'sections': sections
    }
    return render(request, 'bundle_edit.html', context)


@login_required
def bundle_section_add(request, bundle_id):
    """Add a new section to the bundle"""
    bundle = get_object_or_404(Bundle, id=bundle_id, created_by=request.user)

    if bundle.is_finalized:
        return JsonResponse({'error': 'Bundle is finalized'}, status=400)

    if request.method == 'POST':
        heading = request.POST.get('heading')

        if not heading:
            return JsonResponse({'error': 'Section heading is required'}, status=400)

        # Get the next order number
        last_section = bundle.sections.order_by('-order').first()
        next_order = (last_section.order + 1) if last_section else 1

        section = BundleSection.objects.create(
            bundle=bundle,
            heading=heading,
            order=next_order
        )

        return JsonResponse({
            'success': True,
            'section_id': section.id,
            'section': {
                'id': section.id,
                'heading': section.heading,
                'order': section.order
            }
        })

    return JsonResponse({'error': 'Invalid request'}, status=400)


@login_required
def bundle_section_delete(request, section_id):
    """Delete a bundle section"""
    section = get_object_or_404(
        BundleSection, id=section_id, bundle__created_by=request.user)

    if section.bundle.is_finalized:
        return JsonResponse({'error': 'Bundle is finalized'}, status=400)

    if request.method == 'POST':
        section.delete()
        return JsonResponse({'success': True})

    return JsonResponse({'error': 'Invalid request'}, status=400)


@login_required
def bundle_section_reorder(request, bundle_id):
    """Reorder sections in the bundle"""
    bundle = get_object_or_404(Bundle, id=bundle_id, created_by=request.user)

    if bundle.is_finalized:
        return JsonResponse({'error': 'Bundle is finalized'}, status=400)

    if request.method == 'POST':
        section_orders = request.POST.getlist('section_orders[]')

        for i, section_id in enumerate(section_orders):
            BundleSection.objects.filter(
                id=section_id,
                bundle=bundle
            ).update(order=i + 1)

        return JsonResponse({'success': True})

    return JsonResponse({'error': 'Invalid request'}, status=400)


@login_required
def bundle_document_upload(request, section_id):
    """Upload a document to a section"""
    section = get_object_or_404(
        BundleSection, id=section_id, bundle__created_by=request.user)

    if section.bundle.is_finalized:
        return JsonResponse({'error': 'Bundle is finalized'}, status=400)

    if request.method == 'POST':
        files = request.FILES.getlist('files[]')
        descriptions = request.POST.getlist('descriptions[]')
        dates = request.POST.getlist('dates[]')

        if not files:
            return JsonResponse({'error': 'No files uploaded'}, status=400)

        uploaded_docs = []

        for i, file in enumerate(files):
            description = descriptions[i] if i < len(descriptions) else ''
            date_str = dates[i] if i < len(dates) and dates[i] else None

            if not description:
                return JsonResponse({'error': f'Description required for file {file.name}'}, status=400)

            # Parse date
            doc_date = None
            if date_str:
                try:
                    doc_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                except ValueError:
                    return JsonResponse({'error': f'Invalid date format for {file.name}'}, status=400)

            # Get next order
            last_doc = section.documents.order_by('-order').first()
            next_order = (last_doc.order + 1) if last_doc else 1

            # Create document
            document = BundleDocument.objects.create(
                section=section,
                file=file,
                description=description,
                date=doc_date,
                order=next_order
            )

            uploaded_docs.append({
                'id': document.id,
                'description': document.description,
                'date': document.date.strftime('%Y-%m-%d') if document.date else '',
                'filename': document.file.name,
                'order': document.order
            })

        return JsonResponse({
            'success': True,
            'documents': uploaded_docs
        })

    return JsonResponse({'error': 'Invalid request'}, status=400)


@login_required
def bundle_document_delete(request, document_id):
    """Delete a bundle document"""
    document = get_object_or_404(
        BundleDocument, id=document_id, section__bundle__created_by=request.user)

    if document.section.bundle.is_finalized:
        return JsonResponse({'error': 'Bundle is finalized'}, status=400)

    if request.method == 'POST':
        # Delete the file
        if document.file:
            try:
                default_storage.delete(document.file.name)
            except:
                pass  # File might not exist

        document.delete()
        return JsonResponse({'success': True})

    return JsonResponse({'error': 'Invalid request'}, status=400)


@login_required
def bundle_document_reorder(request, section_id):
    """Reorder documents within a section"""
    section = get_object_or_404(
        BundleSection, id=section_id, bundle__created_by=request.user)

    if section.bundle.is_finalized:
        return JsonResponse({'error': 'Bundle is finalized'}, status=400)

    if request.method == 'POST':
        document_orders = request.POST.getlist('document_orders[]')

        for i, document_id in enumerate(document_orders):
            BundleDocument.objects.filter(
                id=document_id,
                section=section
            ).update(order=i + 1)

        return JsonResponse({'success': True})

    return JsonResponse({'error': 'Invalid request'}, status=400)


@login_required
def bundle_generate(request, bundle_id):
    """Generate the final PDF bundle"""
    bundle = get_object_or_404(Bundle, id=bundle_id, created_by=request.user)

    if request.method == 'POST':
        try:
            # Generate the bundle PDF
            pdf_content = _generate_bundle_pdf(bundle)

            # Save the PDF
            filename = f"bundle_{bundle.id}_{timezone.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            bundle.final_pdf.save(filename, ContentFile(pdf_content))
            bundle.is_finalized = True
            bundle.save()

            messages.success(request, 'Bundle generated successfully!')
            return redirect('bundle_view', bundle_id=bundle.id)

        except Exception as e:
            messages.error(request, f'Error generating bundle: {str(e)}')
            return redirect('bundle_edit', bundle_id=bundle.id)

    return JsonResponse({'error': 'Invalid request'}, status=400)


@login_required
def bundle_view(request, bundle_id):
    """View a finalized bundle"""
    bundle = get_object_or_404(Bundle, id=bundle_id, created_by=request.user)
    sections = bundle.sections.all().order_by('order')

    # Calculate total documents
    total_docs = sum(section.documents.count() for section in sections)

    context = {
        'bundle': bundle,
        'sections': sections,
        'total_docs': total_docs
    }
    return render(request, 'bundle_view.html', context)


@login_required
def bundle_download(request, bundle_id):
    """Download the final bundle PDF"""
    bundle = get_object_or_404(Bundle, id=bundle_id, created_by=request.user)

    if not bundle.is_finalized or not bundle.final_pdf:
        messages.error(request, 'Bundle has not been generated yet.')
        return redirect('bundle_edit', bundle_id=bundle.id)

    response = FileResponse(
        bundle.final_pdf.open('rb'),
        content_type='application/pdf'
    )
    response['Content-Disposition'] = f'attachment; filename="{bundle.name}.pdf"'
    return response


def _generate_bundle_pdf(bundle):
    """Generate the final PDF bundle with index and pagination"""
    from PyPDF2 import PdfWriter, PdfReader
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    import tempfile

    # Collect all documents with their page information
    documents_info = []
    current_page = 1

    # First, create the index (we'll know page numbers after processing docs)
    sections = bundle.sections.all().order_by('order')

    # Process documents to get page counts
    temp_pdfs = []
    for section in sections:
        documents = section.documents.all().order_by('order')
        for document in documents:
            try:
                # Read the uploaded PDF
                with document.file.open('rb') as pdf_file:
                    reader = PdfReader(pdf_file)
                    page_count = len(reader.pages)

                    # Store document info
                    page_start = current_page + 1  # +1 because index will be page 1
                    page_end = page_start + page_count - 1

                    documents_info.append({
                        'section': section.heading,
                        'description': document.description,
                        'date': document.date.strftime('%d/%m/%Y') if document.date else '',
                        'page_start': page_start,
                        'page_end': page_end,
                        'file_path': document.file.path
                    })

                    current_page += page_count

            except Exception as e:
                print(f"Error processing document {document.id}: {e}")
                continue

    # Generate index HTML and convert to PDF
    index_html = _generate_index_html(bundle, documents_info)

    # Create temporary file for index PDF
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as index_temp:
        index_pdf_content = HTML(string=index_html).write_pdf()
        index_temp.write(index_pdf_content)
        index_temp.flush()
        temp_pdfs.append(index_temp.name)

    # Create final PDF writer
    writer = PdfWriter()
    page_number = 1

    # Add index page
    with open(temp_pdfs[0], 'rb') as index_file:
        index_reader = PdfReader(index_file)
        for page in index_reader.pages:
            # Add page number to index
            page_with_number = _add_page_number(page, page_number)
            writer.add_page(page_with_number)
            page_number += 1

    # Add documents with page numbers
    for doc_info in documents_info:
        try:
            with open(doc_info['file_path'], 'rb') as doc_file:
                doc_reader = PdfReader(doc_file)
                for page in doc_reader.pages:
                    # Add page number to each page
                    page_with_number = _add_page_number(page, page_number)
                    writer.add_page(page_with_number)
                    page_number += 1
        except Exception as e:
            print(f"Error adding document pages: {e}")
            continue

    # Write to bytes
    output_buffer = BytesIO()
    writer.write(output_buffer)
    pdf_content = output_buffer.getvalue()
    output_buffer.close()

    # Clean up temporary files
    for temp_file in temp_pdfs:
        try:
            os.unlink(temp_file)
        except:
            pass

    return pdf_content


def _generate_index_html(bundle, documents_info):
    """Generate HTML for the index page"""
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Bundle Index - {bundle.name}</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; }}
            h1 {{ text-align: center; margin-bottom: 30px; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
            th, td {{ padding: 8px; text-align: left; border-bottom: 1px solid #ddd; }}
            th {{ background-color: #f5f5f5; font-weight: bold; }}
            .page-range {{ text-align: center; }}
            .section-header {{ font-weight: bold; background-color: #e9e9e9; }}
        </style>
    </head>
    <body>
        <h1>Bundle Index: {bundle.name}</h1>
        {f"<p><strong>File Number:</strong> {bundle.file_number.file_number}</p>" if bundle.file_number else ""}
        <p><strong>Generated on:</strong> {timezone.now().strftime('%d/%m/%Y at %H:%M')}</p>
        
        <table>
            <thead>
                <tr>
                    <th>Sr No.</th>
                    <th>Description</th>
                    <th>Date</th>
                    <th>Page Range</th>
                </tr>
            </thead>
            <tbody>
    """

    current_section = None
    sr_no = 1

    for doc in documents_info:
        if current_section != doc['section']:
            # Add section header
            html += f"""
                <tr class="section-header">
                    <td colspan="4">{doc['section']}</td>
                </tr>
            """
            current_section = doc['section']

        # Add document row
        page_range = f"{doc['page_start']}-{doc['page_end']}" if doc['page_start'] != doc['page_end'] else str(
            doc['page_start'])
        html += f"""
            <tr>
                <td>{sr_no}</td>
                <td>{doc['description']}</td>
                <td>{doc['date']}</td>
                <td class="page-range">{page_range}</td>
            </tr>
        """
        sr_no += 1

    html += """
            </tbody>
        </table>
    </body>
    </html>
    """

    return html


def _add_page_number(page, page_number):
    """Add page number to bottom-right of PDF page"""
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    import tempfile

    # Create a temporary PDF with just the page number
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as temp_file:
        temp_canvas = canvas.Canvas(temp_file.name, pagesize=A4)

        # Add page number at bottom-right (bold, size 40, black)
        temp_canvas.setFont("Helvetica-Bold", 40)
        temp_canvas.setFillColorRGB(0, 0, 0)  # Black

        # Position at bottom-right (A4 size: 595 x 842 points)
        x_position = 545  # Right margin
        y_position = 30   # Bottom margin

        temp_canvas.drawRightString(x_position, y_position, str(page_number))
        temp_canvas.save()

        # Merge with original page
        with open(temp_file.name, 'rb') as number_file:
            number_reader = PdfReader(number_file)
            number_page = number_reader.pages[0]

            # Merge the page number onto the original page
            page.merge_page(number_page)

        # Clean up
        os.unlink(temp_file.name)

    return page


@login_required
def bundle_delete(request, bundle_id):
    """Delete a bundle"""
    bundle = get_object_or_404(Bundle, id=bundle_id, created_by=request.user)

    if request.method == 'POST':
        # Delete all associated files
        for section in bundle.sections.all():
            for document in section.documents.all():
                if document.file:
                    try:
                        default_storage.delete(document.file.name)
                    except:
                        pass

        # Delete final PDF if exists
        if bundle.final_pdf:
            try:
                default_storage.delete(bundle.final_pdf.name)
            except:
                pass

        bundle_name = bundle.name
        bundle.delete()

        messages.success(
            request, f'Bundle "{bundle_name}" deleted successfully.')
        return redirect('bundle_create')

    return JsonResponse({'error': 'Invalid request'}, status=400)


@login_required
@require_POST
def update_comment(request):
    """Update comment for a file via AJAX"""
    try:
        data = json.loads(request.body)
        file_number = data.get('file_number')
        comment = data.get('comment', '')

        if not file_number:
            return JsonResponse({'success': False, 'error': 'File number is required'}, status=400)

        # Get the WIP object
        wip = get_object_or_404(WIP, file_number=file_number)

        # Store old value for modification tracking
        old_comment = wip.comments

        # Update the comment
        wip.comments = comment
        wip.save()

        # Create modification record
        changes = {
            'comments': {
                'old': old_comment,
                'new': comment
            }
        }
        create_modification(request.user, wip, changes)

        return JsonResponse({
            'success': True,
            'message': 'Comment updated successfully'
        })

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
