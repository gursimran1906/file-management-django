"""CPD report: every member of staff's training records in one filterable
list, with an "add" form so anyone can record CPD for anyone (who entered it
is kept on the record)."""

from datetime import date

from django.contrib.auth.decorators import login_required
from django.urls import reverse

from users.forms import CPDTrainingLogForm
from users.models import CPDTrainingLog, CustomUser

from .views import render_report

METHOD_LABELS = dict(CPDTrainingLog.DELIVERY_METHOD_CHOICES)


def _parse_date(raw):
    try:
        return date.fromisoformat(raw) if raw else None
    except ValueError:
        return None


def _staff_label(user):
    if user is None:
        return '—'
    return f'{user.username} — {user.first_name} {user.last_name}'.strip(' —')


@login_required
def report_cpd(request):
    staff = request.GET.get('staff', '').strip()
    date_from = _parse_date(request.GET.get('from', '').strip())
    date_to = _parse_date(request.GET.get('to', '').strip())
    method = request.GET.get('method', '').strip()
    certificate = request.GET.get('certificate', '').strip()
    q = request.GET.get('q', '').strip().lower()

    logs = CPDTrainingLog.objects.select_related('user', 'added_by').order_by(
        '-date_completed', '-id')
    if staff.isdigit():
        logs = logs.filter(user_id=int(staff))
    if date_from:
        logs = logs.filter(date_completed__gte=date_from)
    if date_to:
        logs = logs.filter(date_completed__lte=date_to)
    if method in METHOD_LABELS:
        logs = logs.filter(delivery_of_course=method)
    if certificate in ('yes', 'no'):
        logs = logs.filter(certificate_provided=(certificate == 'yes'))

    rows = []
    for log in logs:
        text = ' '.join([log.course_title, log.delivered_by, log.impact,
                         _staff_label(log.user)]).lower()
        if q and q not in text:
            continue
        rows.append({
            'cells': {
                'staff': {'value': log.user.username if log.user else '—', 'href': None},
                'course': {'value': log.course_title, 'href': None},
                'delivered_by': {'value': log.delivered_by, 'href': None},
                'method': {'value': METHOD_LABELS.get(log.delivery_of_course, log.delivery_of_course), 'href': None},
                'completed': {'value': log.date_completed.strftime('%d/%m/%Y'), 'href': None},
                'certificate': {'value': 'Yes' if log.certificate_provided else 'No', 'href': None},
                'impact': {'value': log.impact, 'href': None},
                'added_by': {'value': log.added_by.username if log.added_by else '—', 'href': None},
                'added_on': {'value': log.created_at.strftime('%d/%m/%Y'), 'href': None},
                'action': {'value': 'Edit', 'href': f"{reverse('edit_cpd', args=[log.id])}?next={request.get_full_path()}"},
            },
            'sort': {
                'staff': (log.user.username if log.user else '').lower(),
                'course': log.course_title.lower(),
                'delivered_by': log.delivered_by.lower(),
                'method': log.delivery_of_course,
                'completed': log.date_completed,
                'certificate': log.certificate_provided,
                'impact': log.impact.lower(),
                'added_by': (log.added_by.username if log.added_by else '').lower(),
                'added_on': log.created_at,
            },
        })

    staff_options = [{'value': '', 'label': 'All staff'}] + [
        {'value': str(u.id), 'label': _staff_label(u)}
        for u in CustomUser.objects.filter(is_active=True).order_by('username')
    ]
    filters = [
        {'name': 'staff', 'label': 'Staff member', 'type': 'select', 'value': staff, 'options': staff_options},
        {'name': 'from', 'label': 'Completed from', 'type': 'date', 'value': date_from.isoformat() if date_from else ''},
        {'name': 'to', 'label': 'Completed to', 'type': 'date', 'value': date_to.isoformat() if date_to else ''},
        {'name': 'method', 'label': 'Method', 'type': 'select', 'value': method,
         'options': [{'value': '', 'label': 'All'}] + [{'value': k, 'label': v} for k, v in METHOD_LABELS.items()]},
        {'name': 'certificate', 'label': 'Certificate', 'type': 'select', 'value': certificate,
         'options': [{'value': '', 'label': 'All'}, {'value': 'yes', 'label': 'Provided'}, {'value': 'no', 'label': 'Not provided'}]},
        {'name': 'q', 'label': 'Search', 'type': 'text', 'value': request.GET.get('q', ''),
         'placeholder': 'Course, provider, impact…'},
    ]
    columns = [
        {'key': 'staff', 'label': 'Staff', 'sortable': True},
        {'key': 'course', 'label': 'Course', 'sortable': True, 'truncate': True},
        {'key': 'delivered_by', 'label': 'Delivered by', 'sortable': True, 'truncate': True},
        {'key': 'method', 'label': 'Method', 'sortable': True},
        {'key': 'completed', 'label': 'Completed', 'sortable': True},
        {'key': 'certificate', 'label': 'Certificate', 'sortable': True},
        {'key': 'impact', 'label': 'Impact', 'sortable': False, 'truncate': True},
        {'key': 'added_by', 'label': 'Added by', 'sortable': True},
        {'key': 'added_on', 'label': 'Added on', 'sortable': True},
        {'key': 'action', 'label': '', 'sortable': False},
    ]
    return render_report(
        request,
        slug='cpd_records',
        title='CPD records',
        description='Continuing professional development logged for every member of staff. '
                    'Anyone can add a record for anyone; who added it is kept.',
        filters=filters, columns=columns, rows=rows,
        actions=[{'label': 'Add CPD', 'modal': 'cpd-crud-modal'}],
        extra_template='add_cpd.html',
        extra_context={'cpd_form': CPDTrainingLogForm(initial={'user': request.user.id})},
    )
