"""HTTP layer for the complaints register.

The rules live in ``backend/complaints.py``; these views read the request,
check who may do what, and render. Everything a complaint links to (matters,
correspondence, credit notes) stays where it is: the complaint only points.
"""

import csv
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from users.models import CustomUser

from . import complaints as rules
from .audit import build_form_field_changes
from .models import (
    WIP, ClientContactDetails, Complaint, ComplaintCategory, ComplaintEvent,
    MatterAttendanceNotes, MatterEmails, MatterLetters, Modifications,
)
from .audit_display import enrich_log_entry
from .forms import ComplaintEventForm, ComplaintForm, ComplaintOutcomeForm
from .utils import create_modification

SHOW_CHOICES = [('open', 'Open'), ('closed', 'Closed'), ('all', 'All')]


def _visible_or_404(request, reference):
    complaint = get_object_or_404(
        Complaint.objects.select_related(
            'complainant_client', 'received_by', 'about_fee_earner', 'handled_by',
            'closed_by', 'created_by', 'redress_credit_note'),
        reference=reference.upper())
    if not rules.visible_complaints(request.user).filter(pk=complaint.pk).exists():
        raise Http404('No such complaint')
    return complaint


def _manage_or_403(request, complaint):
    if not rules.can_manage(request.user, complaint):
        raise PermissionDenied('Only the handler, a manager or the complaints officer can do that.')


def _parse_date(value):
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _person(user):
    if not user:
        return ''
    full = f'{user.first_name} {user.last_name}'.strip()
    return full or user.username


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------

@login_required
def complaints_register(request):
    today = timezone.localdate()
    show = request.GET.get('show', 'open')
    if show not in dict(SHOW_CHOICES):
        show = 'open'
    year = request.GET.get('year', '').strip()
    fee_earner = request.GET.get('fee_earner', '').strip()
    category = request.GET.get('category', '').strip()
    q = request.GET.get('q', '').strip()

    qs = rules.visible_complaints(request.user).select_related(
        'about_fee_earner', 'handled_by', 'complainant_client'
    ).prefetch_related('matters', 'categories')
    if show == 'open':
        qs = qs.filter(status__in=Complaint.OPEN_STATUSES)
    elif show == 'closed':
        qs = qs.filter(status__in=Complaint.CLOSED_STATUSES)
    if year.isdigit():
        start, end = rules.reporting_year_bounds(int(year))
        qs = qs.filter(received_on__range=(start, end))
    if fee_earner.isdigit():
        qs = qs.filter(about_fee_earner_id=int(fee_earner))
    if category.isdigit():
        qs = qs.filter(categories__id=int(category))
    if q:
        from django.db.models import Q
        qs = qs.filter(
            Q(reference__icontains=q) | Q(complainant_name__icontains=q)
            | Q(summary__icontains=q) | Q(matters__file_number__icontains=q)
            | Q(matters__matter_description__icontains=q)
        ).distinct()

    rows = []
    for c in qs:
        rows.append({'complaint': c, 'clock': rules.clock(c, today),
                     'attention': rules.attention(c, today),
                     'matters': list(c.matters.all()),
                     'categories': [cat.name for cat in c.categories.all()]})
    if show == 'open':
        order = {'overdue': 0, 'warning': 1, 'ok': 2, 'stopped': 3}
        rows.sort(key=lambda r: (order[r['clock']['state']], r['clock']['days_left'], r['complaint'].reference))

    if request.GET.get('export') == 'csv':
        return _register_csv(rows)

    counts = rules.summary(request.user, today)
    fee_earners = CustomUser.objects.filter(
        complaints_about__isnull=False).distinct().order_by('username')
    return render(request, 'complaints/register.html', {
        'rows': rows, 'show': show, 'show_choices': SHOW_CHOICES,
        'year': year, 'years': rules.available_years(),
        'fee_earner': fee_earner, 'fee_earners': fee_earners,
        'category': category, 'categories': ComplaintCategory.objects.filter(is_active=True),
        'q': q, 'counts': counts, 'today': today,
        'can_see_all': rules.can_see_all(request.user),
        'filters_active': bool(year or fee_earner or category or q),
    })


def _register_csv(rows):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = (
        f'attachment; filename="complaints_register_{timezone.now():%Y%m%d_%H%M%S}.csv"')
    writer = csv.writer(response)
    writer.writerow([
        'Reference', 'Received', 'Complainant', 'Type', 'Files', 'About', 'Handled by',
        'Categories', 'Status', 'Acknowledged', 'Final response', 'Eight-week deadline',
        'Within eight weeks', 'Outcome', 'Redress', 'Redress £', 'Ombudsman referred',
        'Closed', 'Informal', 'Potential claim', 'Insurer notified', 'Reporting year'])
    for r in rows:
        c = r['complaint']
        writer.writerow([
            c.reference, c.received_on.isoformat(), c.complainant_name,
            c.get_complainant_type_display(), ' '.join(m.file_number for m in r['matters']),
            _person(c.about_fee_earner), _person(c.handled_by), '; '.join(r['categories']),
            c.get_status_display(), c.acknowledged_on or '', c.final_response_sent_on or '',
            c.eight_week_deadline.isoformat(),
            ('Yes' if r['clock']['met'] else 'No') if r['clock']['stopped_on'] else '',
            c.get_outcome_display() if c.outcome else '',
            c.get_redress_type_display() if c.redress_type else '', c.redress_amount or '',
            c.leo_referred_on or '', c.closed_on or '', 'Yes' if c.is_informal else 'No',
            'Yes' if c.potential_claim else 'No', c.pii_notified_on or '', c.reporting_year])
    return response


# ---------------------------------------------------------------------------
# Log a complaint
# ---------------------------------------------------------------------------

@login_required
def complaint_add(request):
    initial = {'received_on': timezone.localdate(), 'received_by': request.user}
    prefill_matter = None
    file_number = request.GET.get('file_number', '').strip().upper()
    if file_number:
        prefill_matter = WIP.objects.filter(file_number=file_number).select_related('client1', 'fee_earner').first()
    if prefill_matter:
        initial['matter_numbers'] = prefill_matter.file_number
        initial['about_fee_earner'] = prefill_matter.fee_earner
        if prefill_matter.client1_id:
            initial['complainant_client'] = prefill_matter.client1
            initial['complainant_name'] = prefill_matter.client1.name
            initial['complainant_email'] = prefill_matter.client1.email or ''
            initial['complainant_phone'] = prefill_matter.client1.contact_number or ''
    officer = rules.complaints_officer()
    if officer:
        initial['handled_by'] = officer

    if request.method == 'POST':
        form = ComplaintForm(request.POST)
        if form.is_valid():
            complaint = rules.create_complaint(
                request.user, form, matters=form.cleaned_data['matter_numbers'])
            messages.success(request, f'Complaint {complaint.reference} logged.')
            return redirect('complaint_detail', reference=complaint.reference)
        messages.error(request, 'Please check the highlighted fields.')
    else:
        form = ComplaintForm(initial=initial)

    return render(request, 'complaints/form.html', {
        'form': form, 'prefill_matter': prefill_matter,
        'file_numbers': WIP.objects.order_by('-id').values_list('file_number', flat=True)[:2000],
        'officer': officer,
    })


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------

def _linked_correspondence(complaint):
    emails = list(complaint.emails.select_related('file_number').order_by('-time'))
    letters = list(complaint.letters.select_related('file_number', 'person_attended').order_by('-date'))
    notes = list(complaint.attendance_notes.select_related('file_number', 'person_attended').order_by('-date'))
    return emails, letters, notes


def _history(complaint):
    """The complaint's audit rows in the shape the matter home's activity log
    uses, so the same enricher labels them."""
    logs = Modifications.objects.filter(
        content_type__model='complaint', object_id=complaint.pk
    ).select_related('modified_by').order_by('-timestamp')[:100]
    return [enrich_log_entry({
        'timestamp': timezone.localtime(log.timestamp).strftime('%d/%m/%Y %H:%M'),
        'desc': f'Complaint {complaint.reference}',
        'changes': log.changes,
        'user': log.modified_by.username if log.modified_by else None,
        'type': 'complaint',
    }) for log in logs]


@login_required
def complaint_detail(request, reference):
    complaint = _visible_or_404(request, reference)
    today = timezone.localdate()
    emails, letters, notes = _linked_correspondence(complaint)
    matters = list(complaint.matters.select_related('client1', 'fee_earner'))
    milestones = [
        # (action, label, date field value, help, is a status move)
        ('acknowledge', 'Acknowledged', complaint.acknowledged_on,
         'Best practice: within two working days of receipt.'),
        ('procedure_sent', 'Complaints procedure sent', complaint.complaints_procedure_sent_on,
         'A copy of the procedure, including how to reach the Legal Ombudsman.'),
        ('timeline', 'Timeline for resolution given', complaint.timeline_given_on,
         'Tell them when they will hear from us (LSB requirement).'),
        ('update_sent', 'Last progress update', complaint.last_update_sent_on,
         'Regular updates while the investigation runs.'),
        ('signposted', 'Ombudsman signposted', complaint.leo_signposted_on,
         'Must also appear in the final response.'),
        ('final_response', 'Final response sent', complaint.final_response_sent_on,
         'Stops the eight-week clock. Complete the wording checklist below.'),
    ]
    return render(request, 'complaints/detail.html', {
        'complaint': complaint,
        'clock': rules.clock(complaint, today),
        'attention': rules.attention(complaint, today),
        'can_manage': rules.can_manage(request.user, complaint),
        'matters': matters,
        'events': complaint.events.select_related('by', 'email', 'letter', 'attendance_note'),
        'emails': emails, 'letters': letters, 'notes': notes,
        'linked_count': len(emails) + len(letters) + len(notes),
        'event_form': ComplaintEventForm(initial={'occurred_on': today}),
        'outcome_form': ComplaintOutcomeForm(instance=complaint),
        'details_form': ComplaintForm(instance=complaint),
        'file_numbers': WIP.objects.order_by('-id').values_list('file_number', flat=True)[:2000],
        'milestones': milestones,
        'history': _history(complaint),
        'today': today,
        'destruction_due_on': complaint.destruction_due_on,
    })


@login_required
@require_POST
def complaint_edit(request, reference):
    complaint = _visible_or_404(request, reference)
    _manage_or_403(request, complaint)
    before = Complaint.objects.get(pk=complaint.pk)
    form = ComplaintForm(request.POST, instance=complaint)
    if not form.is_valid():
        for name, errors in form.errors.items():
            label = form.fields[name].label if name in form.fields else name
            messages.error(request, f"{label}: {', '.join(errors)}")
        return redirect('complaint_detail', reference=complaint.reference)
    saved = form.save()
    old_matters = set(before.matters.values_list('file_number', flat=True))
    saved.matters.set(form.cleaned_data['matter_numbers'])
    new_matters = set(saved.matters.values_list('file_number', flat=True))
    changes = build_form_field_changes(
        before, saved, form.changed_data, exclude={'matter_numbers', 'categories'})
    if old_matters != new_matters:
        changes['matters'] = {'old_value': ' '.join(sorted(old_matters)),
                              'new_value': ' '.join(sorted(new_matters)), '_label': 'Files'}
    if 'categories' in form.changed_data:
        changes['categories'] = {'old_value': '', 'new_value': ', '.join(
            saved.categories.values_list('name', flat=True)), '_label': 'Categories'}
    if changes:
        create_modification(request.user, saved, changes)
    messages.success(request, 'Complaint details saved.')
    return redirect('complaint_detail', reference=complaint.reference)


@login_required
@require_POST
def complaint_outcome(request, reference):
    complaint = _visible_or_404(request, reference)
    _manage_or_403(request, complaint)
    before = Complaint.objects.get(pk=complaint.pk)
    form = ComplaintOutcomeForm(request.POST, instance=complaint)
    if not form.is_valid():
        for name, errors in form.errors.items():
            messages.error(request, f"{form.fields[name].label}: {', '.join(errors)}")
        return redirect('complaint_detail', reference=complaint.reference)
    saved = form.save()
    changes = build_form_field_changes(before, saved, form.changed_data)
    if changes:
        create_modification(request.user, saved, changes)
    messages.success(request, 'Outcome saved.')
    return redirect(reverse('complaint_detail', args=[complaint.reference]) + '#outcome')


@login_required
@require_POST
def complaint_action(request, reference):
    complaint = _visible_or_404(request, reference)
    _manage_or_403(request, complaint)
    action = request.POST.get('action', '')
    when = _parse_date(request.POST.get('when', '')) or timezone.localdate()
    note = (request.POST.get('note') or '').strip()
    if action in ('resolve', 'close') and not complaint.outcome:
        messages.error(request, 'Record the outcome before closing the complaint.')
        return redirect(reverse('complaint_detail', args=[complaint.reference]) + '#outcome')
    try:
        message = rules.set_milestone(complaint, request.user, action, when, note)
    except ValueError:
        raise Http404('Unknown action')
    messages.success(request, message)
    return redirect('complaint_detail', reference=complaint.reference)


@login_required
@require_POST
def complaint_add_event(request, reference):
    complaint = _visible_or_404(request, reference)
    form = ComplaintEventForm(request.POST, request.FILES)
    if not form.is_valid():
        for name, errors in form.errors.items():
            messages.error(request, f"{form.fields[name].label}: {', '.join(errors)}")
        return redirect('complaint_detail', reference=complaint.reference)
    event = form.save(commit=False)
    event.complaint = complaint
    event.by = request.user
    if event.document:
        event.document_name = event.document.name
    event.save()
    create_modification(request.user, complaint, {
        'event': {'old_value': '', 'new_value': f'{event.get_kind_display()} ({event.occurred_on:%d/%m/%Y})'}})
    messages.success(request, 'Added to the chronology.')
    return redirect(reverse('complaint_detail', args=[complaint.reference]) + '#chronology')


@login_required
def complaint_document(request, event_id):
    event = get_object_or_404(ComplaintEvent.objects.select_related('complaint'), pk=event_id)
    if not rules.visible_complaints(request.user).filter(pk=event.complaint_id).exists():
        raise Http404('No such document')
    if not event.document:
        raise Http404('No document')
    return FileResponse(event.document.open('rb'), as_attachment=False,
                        filename=event.document_name or event.document.name.rsplit('/', 1)[-1])


# ---------------------------------------------------------------------------
# Tagging correspondence from the matter's correspondence page
# ---------------------------------------------------------------------------

KINDS = {'email': MatterEmails, 'letter': MatterLetters, 'note': MatterAttendanceNotes}


@login_required
@require_POST
def complaint_tag_correspondence(request, file_number):
    matter = get_object_or_404(WIP, file_number=file_number)
    model = KINDS.get(request.POST.get('kind', ''))
    if model is None:
        raise Http404('Unknown correspondence type')
    record = get_object_or_404(model, pk=request.POST.get('id'), file_number=matter)
    untag = request.POST.get('untag') == '1'
    if untag:
        if not record.complaint_id:
            return redirect(request.POST.get('next') or reverse('correspondence_view', args=[file_number]))
        complaint = record.complaint
    else:
        complaint = get_object_or_404(
            rules.visible_complaints(request.user), pk=request.POST.get('complaint'))
    if rules.tag_correspondence(complaint, request.user, record, tag=not untag):
        messages.success(request, (f'Removed from complaint {complaint.reference}.' if untag
                                   else f'Added to complaint {complaint.reference}.'))
    return redirect(request.POST.get('next') or reverse('correspondence_view', args=[file_number]))


# ---------------------------------------------------------------------------
# Annual return
# ---------------------------------------------------------------------------

@login_required
def complaints_annual_return(request):
    if not rules.can_see_all(request.user):
        raise PermissionDenied('Managers and the complaints officer only.')
    years = rules.available_years()
    try:
        year = int(request.GET.get('year', years[0]))
    except (TypeError, ValueError):
        year = years[0]
    data = rules.annual_return(year)
    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="complaints_annual_return_{year}.csv"'
        writer = csv.writer(response)
        writer.writerow([f'Complaints: SRA annual return figures, 1 Sep {year - 1} to 31 Aug {year}'])
        writer.writerow(['Received', data['received']])
        writer.writerow(['Resolved (complainant satisfied)', data['resolved']])
        writer.writerow(['Referred to the Legal Ombudsman', data['referred']])
        writer.writerow([])
        writer.writerow(['Category', 'Received', 'Resolved', 'Referred to LeO'])
        for row in data['by_category']:
            writer.writerow([row['name'], row['received'], row['resolved'], row['referred']])
        return response
    today = timezone.localdate()
    rows = [{'complaint': c, 'clock': rules.clock(c, today), 'matters': list(c.matters.all())}
            for c in data['complaints']]
    return render(request, 'complaints/annual_return.html', {
        'data': data, 'year': year, 'years': years, 'rows': rows, 'today': today,
    })
