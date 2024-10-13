from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.db.models import Q, Q, F, OuterRef, Subquery, Max, CharField, Exists
from django.db.models.functions import Cast
from .models import WIP, NextWork, LastWork, FileStatus, FileLocation, MatterType, ClientContactDetails, AuthorisedParties
from .models import LedgerAccountTransfers, Modifications, Invoices, RiskAssessment, PoliciesRead, OngoingMonitoring
from .models import OthersideDetails, MatterAttendanceNotes, MatterEmails, MatterLetters, PmtsSlips, Free30Mins, Free30MinsAttendees
from .models import Undertaking, Policy, PolicyVersion
from .forms import OpenFileForm, NextWorkFormWithoutFileNumber, NextWorkForm, LastWorkFormWithoutFileNumber, LastWorkForm, AttendanceNoteForm, AttendanceNoteFormHalf, LetterForm, LetterHalfForm, PolicyForm
from .forms import PmtsForm, PmtsHalfForm, LedgerAccountTransfersHalfForm, LedgerAccountTransfersForm, InvoicesForm, ClientForm, AuthorisedPartyForm, RiskAssessmentForm, OngoingMonitoringForm,OtherSideForm
from .forms import Free30MinsForm, Free30MinsAttendeesForm, UndertakingForm
from .utils import create_modification
from django.utils import timezone
from users.models import CustomUser
from django.contrib import messages
from django.http import HttpResponse
from django.template.loader import render_to_string
from weasyprint import HTML
from django.utils.safestring import mark_safe
from django.contrib.contenttypes.models import ContentType
import csv
import json
from datetime import datetime, timedelta, time
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


@login_required
def display_data_index_page(request):
    if 'valToSearch' in request.POST:
        search_by = request.POST['searchBy']
        val_to_search = request.POST['valToSearch']
        show_archived = 'showArchived' in request.POST

        file_status_field_name = 'file_status__status'
        
        if show_archived:
            file_status_list = ['Open', 'Archived']
            filter_factor = Q(**{f"{file_status_field_name}__in": file_status_list})
        elif search_by == 'ToBeClosed':
            file_status = 'To Be Closed'
            filter_factor = Q(**{file_status_field_name: file_status})
        else:
            file_status = 'Open'
            filter_factor = Q(**{file_status_field_name: file_status})

        if search_by == 'ClientName':
            filter_factor &= Q(client1__name__icontains=val_to_search) | Q(
                client2__name__icontains=val_to_search)
        elif search_by == 'FeeEarner':
            if val_to_search == "DC":
                print('DC')
                filter_factor &= Q(fee_earner=None)
            else:
                filter_factor &= Q(fee_earner__username__icontains=val_to_search)
        else:
            filter_factor &= Q(file_number__icontains=val_to_search)

        last_work_subquery = LastWork.objects.filter(file_number=OuterRef('pk')).order_by(
            '-timestamp').values('task', 'date', 'person__username')[:1]

        data = WIP.objects.filter(filter_factor).annotate(
            latest_last_work_task=Subquery(last_work_subquery.values('task')),
            latest_last_work_date=Subquery(last_work_subquery.values('date')),
            latest_last_work_person=Subquery(
                last_work_subquery.values('person__username'))
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
        search_by = request.POST['searchBy']
        val_to_search = request.POST['valToSearch']
        show_archived = 'showArchived' in request.POST

        file_status_field_name = 'file_status__status'
        
        if show_archived:
            file_status_list = ['Open', 'Archived']
            filter_factor = Q(**{f"{file_status_field_name}__in": file_status_list})
        elif search_by == 'ToBeClosed':
            file_status = 'To Be Closed'
            filter_factor = Q(**{file_status_field_name: file_status})
        else:
            file_status = 'Open'
            filter_factor = Q(**{file_status_field_name: file_status})

        if search_by == 'ClientName':
            filter_factor &= Q(client1__name__icontains=val_to_search) | Q(
                client2__name__icontains=val_to_search)
        elif search_by == 'FeeEarner':
            filter_factor &= Q(fee_earner__username__icontains=val_to_search)
        else:
            filter_factor &= Q(file_number__icontains=val_to_search)

        last_work_subquery = LastWork.objects.filter(file_number=OuterRef('pk')).order_by(
            '-timestamp').values('task', 'date', 'person__username')[:1]

        data = WIP.objects.filter(filter_factor).annotate(
            latest_last_work_task=Subquery(last_work_subquery.values('task')),
            latest_last_work_date=Subquery(last_work_subquery.values('date')),
            latest_last_work_person=Subquery(
                last_work_subquery.values('person__username'))
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

@login_required
def user_dashboard(request):
    user = CustomUser.objects.get(username=request.user)
    user_next_works = NextWork.objects.filter(Q(person=user) & Q(completed=False)).order_by('date')
    user_last_works = LastWork.objects.filter(person=user).order_by('-date')
    now = timezone.now()
    # Collect unique WIP objects from user_next_works and user_last_works
    next_work_wips = user_next_works.values_list('file_number', flat=True)
    last_work_wips = user_last_works.values_list('file_number', flat=True)

    fee_earner_files = WIP.objects.filter(Q(fee_earner=user) & Q(file_status__status='Open'))

    next_work_wips_set = set(next_work_wips)
    last_work_wips_set = set(last_work_wips)

    # Perform union of sets and combine with fee_earner_files
    combined_wips_set = next_work_wips_set.union(last_work_wips_set)
    unique_wips = WIP.objects.filter(id__in=combined_wips_set) | fee_earner_files

    
    # Calculate the date 11 months ago
    eleven_months_ago = timezone.now() - relativedelta(months=11)
    
    latest_assessment_subquery = RiskAssessment.objects.filter(
    matter=OuterRef('pk')
    ).order_by('-due_diligence_date').values('due_diligence_date')[:1]

    # Filter files based on the latest risk assessment date
    risk_assessments_due = unique_wips.annotate(
        latest_assessment_date=Subquery(latest_assessment_subquery)
    ).filter(
        Q(file_status__status='Open') &
        (Q(latest_assessment_date__lte=eleven_months_ago) | Q(latest_assessment_date__isnull=True))
    )
    
    
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
        {'client_id': client_id, 'client_name': data['client_name'], 'date_of_last_aml': data['date_of_last_aml']}
        for client_id, data in unique_clients.items()
    ]
    unique_aml_checks_due = sorted(unique_aml_checks_due, key=lambda x: x['date_of_last_aml'])
    # Filter for unsettled invoices
    last_100_emails = MatterEmails.objects.filter(fee_earner=user).order_by('-time')[:100]

    unsettled_invoices = Invoices.objects.filter(
        file_number__in=unique_wips,
        state='F',
        total_due_left__gt=0
    ).order_by('invoice_number')

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
        'now':now,
        'user_next_works': user_next_works,
        'user_last_works': user_last_works,
        'risk_assessments_due_files': risk_assessments_due,
        'aml_checks_due': unique_aml_checks_due,
        'unsettled_invoices': unsettled_invoices,
        'last_100_emails': last_100_emails,
        'files':unique_wips,
        'unread_policies_exist': unread_policies_exist,
    }

    return render(request, 'dashboard.html', context)

@login_required
def display_data_home_page(request, file_number):
    try:
        matter = WIP.objects.get(file_number=file_number)
        undertakings = Undertaking.objects.filter(file_number=matter)
        next_work_form = NextWorkFormWithoutFileNumber()
        next_work = NextWork.objects.filter(
            file_number=matter, completed=False).order_by('date')
        last_work = LastWork.objects.filter(
            file_number=matter).order_by('-date')
        last_work_form = LastWorkFormWithoutFileNumber()
        ongoing_monitorings = OngoingMonitoring.objects.filter(file_number=matter.id).order_by('-timestamp')
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
                    eleven_months_since_last_risk_assessment = True
            else:
                eleven_months_since_last_risk_assessment = False
        else:
            risk_assessment = ""
            eleven_months_since_last_risk_assessment = False
        if matter.file_status.status == 'Archived':
            messages.error(request,"ARCHIVED MATTER. Please note this matter is archived.")
        return render(request, 'home.html', {'matter': matter,
                                             'undertakings':undertakings,
                                             'file_number':file_number,
                                             'next_work_form': next_work_form, 'next_work': next_work,
                                             'last_work': last_work, 'last_work_form': last_work_form,
                                             'ongoing_monitorings':ongoing_monitorings,
                                             'risk_assessment':risk_assessment, 'eleven_months_since_last_risk_assessment':eleven_months_since_last_risk_assessment,
                                             'logs': get_file_logs(file_number)})
    except WIP.DoesNotExist:
        messages.error(request, 'Matter file not found')
        return render(request, 'home.html', {'error': 'Matter file not found'})

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
        logs.append({'timestamp': note.timestamp.strftime("%d/%m/%Y %H:%M:%S"),
                     'desc': f'Attendance note created - {note.subject_line}',
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
        logs.append({'timestamp':obj.timestamp.strftime("%d/%m/%Y %H:%M:%S"),
                     'desc': f'Ongoing Monitoring done.',
                     'user':obj.created_by,
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
        messages.error(request, 'Matter with the given file number does not exist.')
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

        form = RiskAssessmentForm(initial={'matter':matter.id})

    
    return render(request, 'risk_assessment.html', {'form': form, 'file_number':file_number, 'title':'Add'})

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
                        link = reverse('attendance_note_view', args=[nextwork_instance.file_number.file_number])
                        add_attendance_note_link = f"<a href='{link}' class='link'>add an attendance note</a>"
                        messages.info(request, mark_safe(f'Please remember to {add_attendance_note_link} for work just completed.'))
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
    return render(request, 'edit_models.html', {'form': form, 'title': 'Next Work','file_number':nextwork_instance.file_number.file_number})

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
            messages.info(request, mark_safe(f'Please remember to {add_attendance_note_link} for work just added.'))
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
    return render(request, 'edit_models.html', {'form': form, 'title': 'Last Work','file_number':lastwork_instance.file_number.file_number})

@login_required
def attendance_note_view(request, file_number):
    form = AttendanceNoteFormHalf()
    file_number_id = WIP.objects.filter(file_number=file_number).first().id
    attendance_notes = MatterAttendanceNotes.objects.filter(
        file_number=file_number_id).order_by('-date')
    return render(request, 'attendance_notes.html', {'form': form, 'file_number': file_number, 'attendance_notes': attendance_notes})

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

    return render(request, 'edit_models.html', {'form': form, 'title': 'Attendance Note','file_number':attendance_note_instance.file_number.file_number})

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

    return render(request, 'edit_models.html', {'form': form, 'title': 'Letter', 'file_number':letter_instance.file_number.file_number})

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
        desc = f"Attendance Note - {note.subject_line} from {note.start_time.strftime(
            '%I:%M %p')} to {note.finish_time.strftime('%I:%M %p')}"
        units = note.unit
        amount = ((note.person_attended.hourly_rate.hourly_amount/10) * units) if note.person_attended != None else ((note.file_number.fee_earner.hourly_rate.hourly_amount/10) * units)
        row = [date, time, fee_earner, desc, units, amount]
        rows.append(row)

    for email in emails:
        
        date = email.time.date().strftime('%d/%m/%Y')
        time = email.time.astimezone(timezone.get_current_timezone()).time().strftime('%H:%M')
        fee_earner = email.fee_earner.username if email.fee_earner != None else ''
        receiver = json.loads(email.receiver)
        sender = json.loads(email.sender)
        to_or_from = f"Email to {receiver[0]['emailAddress']['name']}" if email.is_sent else f"Perusal of email from {sender['emailAddress']['name']}"
        desc = to_or_from + f" @ {time}"
        units = email.units
        amount = ((email.fee_earner.hourly_rate.hourly_amount/10) * units) if email.fee_earner != None else ((email.file_number.fee_earner.hourly_rate.hourly_amount/10)* units)
        row = [date, time, fee_earner, desc, units, amount]
        rows.append(row)

    for letter in letters:
        date = letter.date.strftime('%d/%m/%Y')
        time = None
        fee_earner = letter.person_attended.username if letter.person_attended != None else ''
        to_or_from = f'Letter to {letter.to_or_from}' if letter.sent else f'Letter from {letter.to_or_from}'
        desc = f'{to_or_from} - {letter.subject_line}'
        units = 1
        amount = ((letter.person_attended.hourly_rate.hourly_amount/10) * units) if letter.person_attended != None else ((letter.file_number.fee_earner.hourly_rate.hourly_amount/10)* units)
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
            writer.writerow(['', '', f'({user.first_name} {user.last_name}) {user.username} rate GBP{user.hourly_rate.hourly_amount} + VAT per hour, 6 minutes = 1 unit '])
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
    writer.writerow(['', '', 'VAT @20%', '', f'=0.2*E{total_cost_row}'])
    writer.writerow(['', '', 'Total Costs and VAT', '',
                    f'=sum(E{total_cost_row}:E{total_cost_row+1})'])

    return response

@login_required
def finance_view(request, file_number):
    file_number_id = WIP.objects.filter(file_number=file_number).first().id
    pmts_slips = PmtsSlips.objects.filter(
        file_number=file_number_id).order_by('-date')
    pmts_form = PmtsHalfForm()
    green_slips_form = LedgerAccountTransfersHalfForm()
    green_slips = LedgerAccountTransfers.objects.filter(
        Q(file_number_from=file_number_id) | Q(file_number_to=file_number_id)).order_by('-date')
    invoices = Invoices.objects.filter(
        file_number=file_number_id).order_by('-date')

    invoices_data = []

    total_invoices = 0
    total_out = 0
    for invoice in invoices:

        our_costs = invoice.our_costs

        costs = ast.literal_eval(our_costs) if type(
            our_costs) != type([]) else our_costs
        total_cost_invoice = 0

        our_costs_desc_pre = invoice.our_costs_desc
        our_costs_desc = ast.literal_eval(our_costs_desc_pre) if type(
            our_costs_desc_pre) != type([]) else our_costs_desc_pre
        costs_display = "<div>"
        for i in range(len(costs)):
            total_cost_invoice = total_cost_invoice + Decimal(costs[i])
            costs_display = costs_display + \
                f"<b>{our_costs_desc[i]}</b>: £{costs[i]}<br>"
        vat_inv = total_cost_invoice * Decimal(0.20)
        costs_display = costs_display + \
            f"Add VAT @20%: £{round(vat_inv, 2)}<br>"
        total_cost_and_vat = round(total_cost_invoice + vat_inv, 2)
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
                    amount_invoiced = json.loads(slip.amount_invoiced.decode('utf-8'))
                elif isinstance(slip.amount_invoiced, dict):
                    amount_invoiced = slip.amount_invoiced
                else:
                    raise ValueError("Unsupported type for slip.amount_invoiced")

                date = slip.date.strftime('%d/%m/%Y')
                amt = amount_invoiced[f"{invoice.id}"]['amt_invoiced']
                total_blue_slips = total_blue_slips + Decimal(amt)
                blue_slips_display = blue_slips_display + \
                    f"Payment from {slip.pmt_person} of <b>£{amt}</b> on <b>{date}</b><br>"
            blue_slips_display = blue_slips_display + \
                f"<b>Total Blue Slips:</b> £{round(total_blue_slips,2)}<br>"
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
                        amount_invoiced = json.loads(slip.amount_invoiced_to.decode('utf-8'))
                    elif isinstance(slip.amount_invoiced_to, dict):
                        amount_invoiced = slip.amount_invoiced_to
                    else:
                        raise ValueError("Unsupported type for slip.amount_invoiced_to")

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
                if isinstance(slip.amount_invoiced, str):
                    amount_invoiced = json.loads(slip.amount_invoiced)
                elif isinstance(slip.amount_invoiced, (bytes, bytearray)):
                    amount_invoiced = json.loads(slip.amount_invoiced.decode('utf-8'))
                elif isinstance(slip.amount_invoiced, dict):
                    amount_invoiced = slip.amount_invoiced
                else:
                    raise ValueError("Unsupported type for slip.amount_invoiced")
                
                date = slip.date.strftime('%d/%m/%Y')
                invoice_id_str = f'{invoice.id}'
                if invoice_id_str in amount_invoiced:
                    amt = amount_invoiced[invoice_id_str]
                    total_cash_allocated_slips = total_cash_allocated_slips + Decimal(amt)
                    cash_allocated_slips_display = cash_allocated_slips_display + \
                        f"Payment from {slip.pmt_person} of <b>£{amt}</b> on <b>{date}</b><br>"
                
            cash_allocated_slips_display = cash_allocated_slips_display + \
                f"<b>Total Allocated Slips:</b> £{total_cash_allocated_slips}<br>"
        else:
            cash_allocated_slips_display = cash_allocated_slips_display + "No Slips Attached After Invoice Creation"

        cash_allocated_slips_display = cash_allocated_slips_display + "</div>"

        balance = (total_cost_and_vat + total_pink_slips) - total_green_slips - (total_blue_slips + total_cash_allocated_slips)

        if balance >= 0:
            total_due_display = f"<div><b>Total Due: </b> £{round(balance,2)}<br></div>"
        else:
            balance = balance * -1
            total_due_display = f"<div><b>Balance remaining on account:</b> £{round(balance,2)}<br></div>"

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
                'total_due': mark_safe(total_due_display),
                'total_due_left': invoice.total_due_left,
                }

        invoices_data.append(data)

        total_invoices = total_invoices + total_cost_and_vat

    total_out = total_out + total_invoices
    total_in = 0
    for slip in pmts_slips:
        if slip.is_money_out == True:
            total_out = total_out + slip.amount
        else:
            total_in = total_in + slip.amount

    for slip in green_slips:
        if slip.file_number_from.file_number == file_number:
            total_out = total_out + slip.amount

        else:
            total_in = total_in + slip.amount
    total_in = round(total_in, 2)
    total_out = round(total_out, 2)
    total_balance = total_in - total_out

    colors = {'draft_invoice': "#F9EBDF",
              "invoice": "#FFFCC9",
              'green': "#90EE90",
              'temp': "#CCD1D1"}

    return render(request, 'finances.html', {'total_monies_in': total_in, 'total_monies_out': total_out, 'total_monies_balance': total_balance,
                                             'pmts_slips': pmts_slips, 'file_number': file_number,
                                             'colors': colors,
                                             'pmts_form': pmts_form, 'green_slip_form': green_slips_form,
                                             'green_slips': green_slips, 'invoices': invoices_data})

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

    return render(request, 'edit_models.html', {'form': form, 'title': 'Slip','file_number':pmt_instance.file_number.file_number})

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
        total_costs_and_vat = (Decimal('0.20')*total_costs)+total_costs

        request_post_copy['created_by'] = request.user
        request_post_copy['file_number'] = file_number_id

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

        amt_to_allocate = request.POST['amt_to_allocate']
        invoice_num = request.POST['invoice_num']
        slip_id = request.POST['slip_id']

        invoice = Invoices.objects.filter(invoice_number=invoice_num).first()
        slip = PmtsSlips.objects.filter(id=slip_id).first()

        due_left = invoice.total_due_left
        balance = due_left - Decimal(amt_to_allocate)

        

        already_allocated = json.loads(
            slip.amount_allocated) if slip.amount_allocated != {} else {}
        already_allocated.update({str(invoice.id): str(amt_to_allocate)})
        slip.amount_allocated = json.dumps(already_allocated)

        slip.balance_left = Decimal(amt_to_allocate)- invoice.total_due_left
        invoice.cash_allocated_slips.add(slip.id)
        if balance <= 0:
            invoice.total_due_left = 0
        else:
            invoice.total_due_left = balance
        

        changes = {'prev_total_due_left': str(due_left),
                   'after_total_due_left': str(invoice.total_due_left),
                   'amount_allocated': amt_to_allocate}

        create_modification(
            user=request.user,
            modified_obj=invoice,
            changes=changes
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
    if invoice.file_number.client2 :
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
    vat_inv = total_cost_invoice * Decimal(0.20)
    costs_display = costs_display + \
        f"<tr><td >Add VAT @20%:</td><td style='text-align: center; border-top: solid; border-top-width: thin;'>£{
            round(vat_inv, 2)}</td></tr>"
    total_cost_and_vat = round(total_cost_invoice + vat_inv, 2)
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
                amount_invoiced = json.loads(slip.amount_invoiced.decode('utf-8'))
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
            @page {
                    size: A4; 
                    margin-top: 0mm;
                    margin-bottom: 4px; 
                    margin-left: 40px;
                    margin-right: 40px;
           
            }
            .logoDiv{
                position:fixed;
                top:15px;
                right:0px;
                
            }
            img {
            
            width: 75px;
            height: 50px;
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

def get_all_financials(file_number):
    file = get_object_or_404(WIP,file_number=file_number)

    slips = PmtsSlips.objects.filter(file_number=file.id)
    green_slips = LedgerAccountTransfers.objects.filter(
        Q(file_number_from=file.id) | Q(file_number_to=file.id))
    invoices = Invoices.objects.filter(file_number=file.id)
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
        if slip.file_number_from.file_number == file_number:
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

        our_costs = invoice.our_costs

        costs = ast.literal_eval(our_costs) if type(
            our_costs) != type([]) else our_costs
        total_cost_invoice = 0

        for cost in costs:
            total_cost_invoice = total_cost_invoice + Decimal(cost)
        total_cost_invoice = round(
            ((total_cost_invoice*Decimal(0.2)) + total_cost_invoice), 2)
        obj = {'date': invoice.date.strftime('%d/%m/%Y'),
               'desc': desc,
               'type': type_obj,
               'ledger': 'O',
               'amount': total_cost_invoice
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

    writer.writerow(['', f'Client Name: {file.client1.name} Matter:{
                    file.matter_description}[{file.file_number}]'])
    writer.writerow(['', f'Statement of Account'])

    writer.writerow([])
    writer.writerow(
        ['Date', 'Description', 'Money In', 'Money Out', 'Balance'])
    balance = 0
    for row in sorted_rows:
        if row['type'] == 'money_out':
            balance = balance - row['amount']
        else:
            balance = balance + row['amount']
        writer.writerow([row['date'], row['desc'], row['amount'] if row['type'] ==
                        'money_in' else '', row['amount'] if row['type'] == 'money_out' else '', balance])
    writer.writerow([])
    final_cell = len(sorted_rows) + 4
    writer.writerow(
        ['', 'Total', f'=sum(c5:c{final_cell})', f'=sum(d5:d{final_cell})'])
    return response

@login_required
def generate_ledgers_report(request, file_number):
    file = get_object_or_404(WIP,file_number=file_number)
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
        
        if row['ledger'] == 'C':
            if row['type'] == 'money_out':
                client_balance -= row['amount']
                client_amount = '-'+ str(row['amount'])
                office_amount = ''
            else:
                client_balance += row['amount']
                client_amount = str(row['amount'])
                office_amount = ''
        else:
            if row['type'] == 'money_out':
                office_balance -= row['amount']
                client_amount = ''
                office_amount = '-'+ str(row['amount'])
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
    
    pdf_file = HTML(string=html_content, base_url=request.build_absolute_uri()).write_pdf()

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
        total_costs_and_vat = (Decimal('0.20')*total_costs)+total_costs

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
                amount_invoiced = json.loads(slip.amount_invoiced.decode('utf-8'))
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
                <div class="col-span-2">
                    <span type='button' class='btn btn-danger' onclick="removeField(this);" >-</span>
                </div>
            </div>
            """
            our_costs_rows.append(mark_safe(our_costs_display))

        slips = PmtsSlips.objects.filter(
            file_number=invoice.file_number).order_by('date')

        green_slips_objs = LedgerAccountTransfers.objects.filter(
            Q(file_number_from=invoice.file_number.id) | Q(file_number_to=invoice.file_number.id)).order_by('date')

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
                    amount_invoiced = json.loads(slip.amount_invoiced.decode('utf-8'))
                elif isinstance(slip.amount_invoiced, dict):
                    amount_invoiced = slip.amount_invoiced
                else:
                    raise ValueError("Unsupported type for slip.amount_invoiced")
                
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
                                    </div
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

        obj = {'date': slip.date.strftime('%d/%m/%Y'),
               'desc': desc,
               'type': type_obj,
               'amount': slip.amount
               }
        money_in_objects.append(obj)

    for invoice in invoices:
        if invoice.state == 'F':
            desc = f"ANP Invoice {invoice.invoice_number}"
        else:
            desc = f"DRAFT ANP Invoice"

        type_obj = "money_out"

        our_costs = invoice.our_costs

        costs = ast.literal_eval(our_costs) if type(
            our_costs) != type([]) else our_costs
        total_cost_invoice = 0

        for cost in costs:
            total_cost_invoice = total_cost_invoice + Decimal(cost)
        total_cost_invoice = round(
            ((total_cost_invoice*Decimal(0.2)) + total_cost_invoice), 2)
        obj = {'date': slip.date.strftime('%d/%m/%Y'),
               'desc': desc,
               'amount': total_cost_invoice
               }
        money_out_objects.append(obj)

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
        elif j < len(money_in_objects):
            row.cells[0].text = money_out_objects[j]['date']
            row.cells[1].text = money_out_objects[j]['desc']
            row.cells[2].text = '£' + str(money_in_objects[j]['amount'])
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

    unallocated_emails_obj = MatterEmails.objects.filter(file_number=None).order_by('time').only()
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
        options = [f'<option value="{file.file_number}">{file.file_number}</option>' for file in files]
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
    emails_ids = request.POST.getlist('email_ids[]')
    j = 0
    for file_number in file_numbers:
        
        if file_number != '':
            file_number= file_number
            email_id = emails_ids[i]
            email = MatterEmails.objects.filter(id=email_id).first()
            file = WIP.objects.filter(file_number=file_number).first()
            email.file_number = file
            j = j + 1
            email.fee_earner = file.fee_earner if file.fee_earner != None else None
            email.save()
        i = i+1

                
            
    messages.success(request, f'Successfully allocated {j} emails')
   
    return redirect('unallocated_emails')

@login_required
def download_cashier_data(request):
    if request.method == 'POST':

        start_date_str = request.POST['start_date']

        start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        get_pending_slips = request.POST['type_of_report'] == 'Pending Slips'

        if get_pending_slips:
            end_date = datetime.combine(datetime.today().date(), time.min)
            title = "Pending Slips"
            check_headings = ""
            check_body = ""
        else:
            end_date_str = request.POST['end_date']
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d')

            title = "Audit Slips"
            check_headings = """
                            <th>Checked Millenium</th>
                            <th>Checked Bank A/c</th>
                        """
            check_body = """
                            <td></td>
                            <td></td>
                        """
        invoices = Invoices.objects.filter(Q(date__range=(start_date, end_date)) & Q(state='F')).order_by('invoice_number')
        slips = PmtsSlips.objects.filter(
            timestamp__range=(start_date, end_date)).order_by('date')
        green_slips = LedgerAccountTransfers.objects.filter(
            timestamp__range=(start_date, end_date)).order_by('date')

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
                our_costs = invoice.our_costs
                costs = ast.literal_eval(our_costs) if type(
                    our_costs) != type([]) else our_costs
                total_cost_invoice = 0
                for cost in costs:
                    total_cost_invoice = round(
                        total_cost_invoice + Decimal(cost), 2)
                vat = round(total_cost_invoice * Decimal(0.2), 2)

                total_cost_and_vat = total_cost_invoice + vat
                slip_display = ''
                for slip in invoice.disbs_ids.all():
                    slip_display = slip_display + \
                        f'({slip.date.strftime('%d/%m%/%Y')}, £{slip.amount})'

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
                <td>{slip.file_number_from.file_number}</td>
                <td>{slip.file_number_to.file_number}</td>
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

    else:
        return render(request, 'cashier_data.html')


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
    page_style = '@page { margin-top: 2pt; margin-bottom:0; font-size:7pt !important; size: A4;}'
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
        ap1_name = file.authorised_party2.name
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
def download_risk_assessment(request,id):
    risk_assessment = get_object_or_404(RiskAssessment,pk=id)
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
        messages.error(request, 'Matter with the given file number does not exist.')
        return redirect('index')
    if request.method == 'POST':
        post_data = request.POST.copy()
        post_data['created_by'] = request.user
        post_data['file_number'] = matter.id
        form = OngoingMonitoringForm(post_data)
        
        if form.is_valid():
            ongoing_monitoring = form.save()
            messages.success(request, 'Ongoing Monitoring successfully recorded.')
            return redirect('home', ongoing_monitoring.file_number.file_number)
        else:
            error_message = 'Form is not valid. Please correct the errors:'
            for field, errors in form.errors.items():
                error_message += f'\n{field}: {", ".join(errors)}'
            messages.error(request, error_message)
    else:
        form = OngoingMonitoringForm()
        return render(request, 'ongoing_monitoring.html', {'form':form, 'file_number': file_number, 'title':'Add'})

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
    )

    policies_read = PoliciesRead.objects.filter(read_by=request.user).order_by('-timestamp')

    context = {
        'policies': policies,
        'policies_read': policies_read,
    }
    
    return render(request, 'policies/policies_home.html', context)


@login_required
def policy_read(request, policy_id):
    policy = get_object_or_404(Policy, pk=policy_id)

    
    latest_version = policy.versions.order_by('-version_number').first()

    
    if not latest_version:
        messages.error(request, f"No versions available for policy '{policy.description}'.")
        return redirect('policies_display')

    try:
        PoliciesRead.objects.create(policy=policy, policy_version=latest_version, read_by=request.user)
        messages.success(request, f'Successfully marked the latest version of "{policy.description}" as read.')
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
                messages.error(request, f"An error occurred while adding the policy: {str(e)}")
        else:
            messages.error(request, "There were errors in the form. Please correct them and try again.")
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
                latest_version = policy.versions.order_by('-version_number').first()
                
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
                messages.error(request, f"An error occurred while editing the policy: {str(e)}")
        else:
            messages.error(request, "There were errors in the form. Please correct them and try again.")
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
        messages.error(request, f"An error occurred while generating the PDF: {str(e)}")
        return redirect('policies_display')


@login_required
def invoices_list(request):
    invoices = Invoices.objects.filter(state='F')
    if request.user.is_manager:
        for invoice in invoices:

            our_costs = invoice.our_costs
            costs = ast.literal_eval(our_costs) if type(our_costs) != type([]) else our_costs
            total_cost_invoice = 0
        
            for i in range(len(costs)):
                total_cost_invoice = total_cost_invoice + Decimal(costs[i])
            vat_inv = total_cost_invoice * Decimal(0.20)
        
            total_cost_and_vat = round(total_cost_invoice + vat_inv, 2)
            
            invoice.our_costs = total_cost_invoice
            invoice.vat = round(vat_inv, 2)
            invoice.total_cost_and_vat = total_cost_and_vat
        return render(request, 'invoices_list.html', {'invoices':invoices})
    else:
        messages.error(request, 'You do not have right level of permissions.')
        return redirect('index')

@login_required
def download_invoices(request):

    if request.method == 'POST' and request.user.is_manager :
        
        start_date_str =  request.POST['start']
        end_date_str = request.POST['end']
        start_date = datetime.strptime(start_date_str, '%d/%m/%Y')
        end_date = datetime.strptime(end_date_str, '%d/%m/%Y')
        
        
        invoices = Invoices.objects.filter(state='F',date__range=[start_date, end_date])
        
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="Invoices_from_{start_date_str}_to_{end_date_str}.csv"'

        writer = csv.writer(response)

        writer.writerow(['', f'Invoices from {start_date_str} to {end_date_str}'])

        writer.writerow([])
        writer.writerow(['Invoice Number','Date','File Number','Our Costs', 'VAT', 'Total Costs and VAT'])

      
        for invoice in invoices:
            our_costs = invoice.our_costs
            costs = ast.literal_eval(our_costs) if type(our_costs) != type([]) else our_costs
            total_cost_invoice = 0
        
            for i in range(len(costs)):
                total_cost_invoice = total_cost_invoice + Decimal(costs[i])
            vat_inv = total_cost_invoice * Decimal(0.20)
        
            total_cost_and_vat = round(total_cost_invoice + vat_inv, 2)
            
            
            writer.writerow([f'{invoice.invoice_number}',f'{invoice.date.strftime("%d/%m/%Y")}',f'{invoice.file_number.file_number}',f'{total_cost_invoice}', f'{vat_inv}', f'{total_cost_and_vat}'])

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
                changes[field]['new_value'] = str(getattr(risk_assesssment, field))

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
    
    return render(request, 'risk_assessment.html', {'form':form, 'file_number':risk_assesssment.matter.file_number,'title':'Edit'})

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
                changes[field]['new_value'] = str(getattr(ongoing_monitoring, field))

            create_modification(
                user=request.user,
                modified_obj=ongoing_monitoring,
                changes=changes
            )
            messages.success(request, 'Successfully updated Ongoing Monitoring.')
            return redirect('home', ongoing_monitoring.file_number.file_number)
        else:
            error_message = 'Form is not valid. Please correct the errors:'
            for field, errors in form.errors.items():
                error_message += f'\n{field}: {", ".join(errors)}'
            messages.error(request, error_message)
    else:
        form = OngoingMonitoringForm(instance=ongoing_monitoring)
    
    return render(request, 'ongoing_monitoring.html', {'form':form, 'file_number': ongoing_monitoring.file_number.file_number, 'title':'Edit'})

@login_required
def download_ongoing_monitoring(request,id):
    obj = get_object_or_404(OngoingMonitoring,pk=id)
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
        return render(request,'onboarding_documents.html')

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
        response = FileResponse(open(file_path, 'rb'), content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
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
            matter_type = MatterType.objects.filter(pk=matter_type_id).first()
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
        'matter_type': obj.matter_type.type if obj.matter_type else None,  # Adjust attribute if needed
        'notes': mark_safe(obj.notes.html),  # Assuming QuillField stores HTML content
        'date': obj.date,
        'start_time': obj.start_time,
        'finish_time': obj.finish_time,
        'attendees': [attendee.name for attendee in obj.attendees.all()],  # Adjust attribute if needed
        'fee_earner': obj.fee_earner.username if obj.fee_earner else None,
        'created_by': obj.created_by.username if obj.created_by else None,
        'timestamp': obj.timestamp,
    }

    html_string = render_to_string('download_templates/free_30mins.html', obj_dict)
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
    
        file = WIP.objects.filter(file_number=request_post_copy.get('file_number')).first().id
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

            messages.success(request, "Undertaking has been successfully created.")
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

    return render(request, 'undertakings.html', {'form': form, 'undertakings': undertakings, 'undertakings_pending':undertakings_pending})

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

