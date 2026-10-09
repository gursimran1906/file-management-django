"""What is waiting for a fee earner's sign-off.

Risk assessments and ongoing monitoring records completed by staff sit in
``awaiting`` (or ``returned``) until a fee earner signs them off. This module
gathers them once for the sign-off queue page, the dashboard, the navbar
count, the reports hub and the morning digest email. The matter's
*responsible* fee earner (DC -> ND, see ``backend.fee_earners``) decides whose
queue an item is in; any fee earner may still sign it off.
"""

from dataclasses import dataclass

from django.urls import reverse

from .fee_earners import responsible_user_ids
from .models import OngoingMonitoring, RiskAssessment

TYPE_RISK = 'risk_assessment'
TYPE_MONITORING = 'ongoing_monitoring'
TYPES = {TYPE_RISK: 'Risk assessment', TYPE_MONITORING: 'Ongoing monitoring'}
# Both models use the same status values.
PENDING_STATUSES = (RiskAssessment.SIGNOFF_AWAITING, RiskAssessment.SIGNOFF_RETURNED)


def pending_risk_assessments():
    return RiskAssessment.objects.filter(
        signoff_status__in=PENDING_STATUSES, matter__isnull=False,
    ).select_related('matter', 'matter__fee_earner', 'matter__client1', 'completed_by')


def pending_ongoing_monitoring():
    return OngoingMonitoring.objects.filter(
        signoff_status__in=PENDING_STATUSES, file_number__isnull=False,
    ).select_related('file_number', 'file_number__fee_earner', 'file_number__client1', 'completed_by')


@dataclass
class QueueItem:
    type: str
    record: object          # RiskAssessment or OngoingMonitoring
    matter: object          # WIP
    responsible_id: object  # id of the fee earner expected to sign it off
    yours: bool = False

    @property
    def type_label(self):
        return TYPES[self.type]

    @property
    def is_returned(self):
        return self.record.signoff_status == RiskAssessment.SIGNOFF_RETURNED

    @property
    def status_label(self):
        return self.record.get_signoff_status_display()

    @property
    def completed_at(self):
        return self.record.completed_at or self.record.timestamp

    @property
    def reviewed_on(self):
        if self.type == TYPE_RISK:
            return self.record.due_diligence_date
        return self.record.date_due_diligence_conducted

    @property
    def flags(self):
        return self.record.flagged_answers()

    @property
    def sign_off_url(self):
        return reverse(f'sign_off_{self.type}', args=[self.record.id])

    @property
    def return_url(self):
        return reverse(f'return_{self.type}', args=[self.record.id])

    @property
    def edit_url(self):
        return reverse(f'edit_{self.type}', args=[self.record.id])

    @property
    def home_url(self):
        return reverse('home', args=[self.matter.file_number])


def build_queue(user=None, kind=''):
    """Every pending item, the given user's own first, newest completed first.

    ``kind`` limits the list to one type. Each record is also tagged with
    ``yours_to_sign_off`` so templates written against the raw records (the
    dashboard) keep working.
    """
    items = []
    if kind in ('', TYPE_RISK):
        items += [QueueItem(TYPE_RISK, ra, ra.matter, ra.matter.responsible_fee_earner_id)
                  for ra in pending_risk_assessments()]
    if kind in ('', TYPE_MONITORING):
        items += [QueueItem(TYPE_MONITORING, om, om.file_number, om.file_number.responsible_fee_earner_id)
                  for om in pending_ongoing_monitoring()]
    for item in items:
        item.yours = user is not None and item.responsible_id == user.id
        item.record.yours_to_sign_off = item.yours
    items.sort(key=lambda i: (not i.yours, -i.completed_at.timestamp()))
    return items


def pending_count(user=None):
    """How many items await sign-off; only the user's own queue when given."""
    assessments = pending_risk_assessments()
    monitorings = pending_ongoing_monitoring()
    if user is not None:
        ids = responsible_user_ids(user)
        assessments = assessments.filter(matter__fee_earner_id__in=ids)
        monitorings = monitorings.filter(file_number__fee_earner_id__in=ids)
    return assessments.count() + monitorings.count()
