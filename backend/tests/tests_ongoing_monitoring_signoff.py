from datetime import date

from django import forms
from django.test import TestCase
from django.urls import reverse

from users.models import CustomUser
from ..forms import OngoingMonitoringForm
from ..models import (
    ClientContactDetails,
    FileStatus,
    MatterType,
    OngoingMonitoring,
    RiskAssessment,
    WIP,
)


def make_matter(file_number='OM0001', fee_earner=None):
    client = ClientContactDetails.objects.create(
        name='Test Client',
        occupation='Retired',
        address_line1='1 Test Street',
        address_line2='',
        county='Essex',
        postcode='SS7 1QT',
        email='test@example.com',
        contact_number='0123456789',
    )
    matter_type, _ = MatterType.objects.get_or_create(type='Probate')
    file_status, _ = FileStatus.objects.get_or_create(status='Open')
    return WIP.objects.create(
        file_number=file_number,
        client1=client,
        matter_description='Test matter',
        matter_type=matter_type,
        funding='Pvt',
        fee_earner=fee_earner,
        file_status=file_status,
    )


def make_monitoring(matter, **overrides):
    defaults = {
        'file_number': matter,
        'how_was_monitioring_of_risks_coducted': 'Reviewed the file',
        'any_changes_discovered': 'No',
        'details_of_changes': '',
        'updated_risk_level_matter': 'Low',
        'updated_risk_level_client': 'Low',
        'how_it_will_be_monitored': 'Quarterly review',
        'date_due_diligence_conducted': date(2026, 9, 1),
        'signoff_status': OngoingMonitoring.SIGNOFF_AWAITING,
    }
    defaults.update(overrides)
    return OngoingMonitoring.objects.create(**defaults)


def build_monitoring_post(**overrides):
    """A valid POST for OngoingMonitoringForm built from the form's own fields."""
    form = OngoingMonitoringForm()
    data = {}
    for name, field in form.fields.items():
        if isinstance(field, forms.BooleanField):
            data[name] = 'True'
        elif getattr(field, 'choices', None):
            choices = [choice[0] for choice in field.choices if choice[0]]
            data[name] = 'No' if 'No' in choices else choices[0]
        elif isinstance(field, forms.DateField):
            data[name] = '2026-09-01'
        else:
            data[name] = 'Test answer'
    data.update(overrides)
    return data


class OngoingMonitoringSignoffTests(TestCase):
    def setUp(self):
        self.staff = CustomUser.objects.create_user(
            username='stf', email='staff@example.com', first_name='Support',
            last_name='Staff', password='password', max_holidays_in_year=20,
        )
        self.fee_earner = CustomUser.objects.create_user(
            username='fee', email='fee@example.com', first_name='Fee',
            last_name='Earner', password='password', max_holidays_in_year=20,
            is_matter_fee_earner=True,
        )
        self.matter = make_matter(fee_earner=self.fee_earner)
        # The matter page only shows ongoing monitoring once a risk assessment exists.
        RiskAssessment.objects.create(
            matter=self.matter, matter_transaction_value='1000.00',
            due_diligence_date=date(2026, 1, 1),
            signoff_status=RiskAssessment.SIGNOFF_SIGNED,
        )

    def test_form_excludes_workflow_fields(self):
        form = OngoingMonitoringForm()
        for name in ('file_number', 'created_by', 'signed_by', 'signoff_status',
                     'completed_by', 'signed_off_by', 'signoff_comments'):
            self.assertNotIn(name, form.fields)
        self.assertIn('how_it_will_be_monitored', form.fields)

    def test_staff_submission_goes_to_awaiting_signoff(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse('add_ongoing_monitoring', args=[self.matter.file_number]),
            build_monitoring_post())
        self.assertEqual(response.status_code, 302)
        monitoring = OngoingMonitoring.objects.get()
        self.assertEqual(monitoring.file_number, self.matter)
        self.assertEqual(monitoring.created_by, self.staff)
        self.assertEqual(monitoring.completed_by, self.staff)
        self.assertEqual(monitoring.signoff_status, OngoingMonitoring.SIGNOFF_AWAITING)
        self.assertIsNone(monitoring.signed_off_by)
        self.assertIsNone(monitoring.signed_by)

    def test_fee_earner_submission_auto_signs_off(self):
        self.client.force_login(self.fee_earner)
        self.client.post(
            reverse('add_ongoing_monitoring', args=[self.matter.file_number]),
            build_monitoring_post())
        monitoring = OngoingMonitoring.objects.get()
        self.assertEqual(monitoring.signoff_status, OngoingMonitoring.SIGNOFF_SIGNED)
        self.assertEqual(monitoring.completed_by, self.fee_earner)
        self.assertEqual(monitoring.signed_off_by, self.fee_earner)
        self.assertEqual(monitoring.signed_by, self.fee_earner)
        self.assertIsNotNone(monitoring.signed_off_at)

    def test_invalid_submission_re_renders_the_form(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse('add_ongoing_monitoring', args=[self.matter.file_number]),
            build_monitoring_post(date_due_diligence_conducted='not-a-date'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ongoing monitoring')
        self.assertFalse(OngoingMonitoring.objects.exists())

    def test_fee_earner_can_sign_off(self):
        monitoring = make_monitoring(self.matter, completed_by=self.staff)
        self.client.force_login(self.fee_earner)
        response = self.client.post(
            reverse('sign_off_ongoing_monitoring', args=[monitoring.id]))
        self.assertEqual(response.status_code, 302)
        monitoring.refresh_from_db()
        self.assertTrue(monitoring.is_signed_off)
        self.assertEqual(monitoring.signed_off_by, self.fee_earner)
        self.assertEqual(monitoring.signed_by, self.fee_earner)

    def test_non_fee_earner_cannot_sign_off(self):
        monitoring = make_monitoring(self.matter)
        self.client.force_login(self.staff)
        self.client.post(reverse('sign_off_ongoing_monitoring', args=[monitoring.id]))
        monitoring.refresh_from_db()
        self.assertEqual(monitoring.signoff_status, OngoingMonitoring.SIGNOFF_AWAITING)
        self.assertIsNone(monitoring.signed_off_by)

    def test_return_requires_comments_and_sets_status(self):
        monitoring = make_monitoring(self.matter)
        self.client.force_login(self.fee_earner)
        self.client.post(reverse('return_ongoing_monitoring', args=[monitoring.id]),
                         {'comments': '   '})
        monitoring.refresh_from_db()
        self.assertEqual(monitoring.signoff_status, OngoingMonitoring.SIGNOFF_AWAITING)

        self.client.post(reverse('return_ongoing_monitoring', args=[monitoring.id]),
                         {'comments': 'Please add the source of the change'})
        monitoring.refresh_from_db()
        self.assertEqual(monitoring.signoff_status, OngoingMonitoring.SIGNOFF_RETURNED)
        self.assertEqual(monitoring.signoff_comments, 'Please add the source of the change')

    def test_staff_edit_of_signed_record_reopens_signoff(self):
        monitoring = make_monitoring(
            self.matter, signoff_status=OngoingMonitoring.SIGNOFF_SIGNED,
            signed_off_by=self.fee_earner, signed_by=self.fee_earner)
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse('edit_ongoing_monitoring', args=[monitoring.id]),
            build_monitoring_post(any_changes_discovered='Yes'))
        self.assertEqual(response.status_code, 302)
        monitoring.refresh_from_db()
        self.assertEqual(monitoring.any_changes_discovered, 'Yes')
        self.assertEqual(monitoring.signoff_status, OngoingMonitoring.SIGNOFF_AWAITING)
        self.assertIsNone(monitoring.signed_off_by)
        self.assertEqual(monitoring.completed_by, self.staff)
        self.assertEqual(monitoring.file_number, self.matter)

    def test_flagged_and_review_answers(self):
        monitoring = make_monitoring(
            self.matter, any_changes_discovered='Yes', details_of_changes='New director',
            updated_risk_level_client='Medium', updated_risk_level_matter='High')
        flags = monitoring.flagged_answers()
        self.assertIn('Changes discovered since the risk assessment', flags)
        self.assertIn('Client risk now Medium', flags)
        self.assertIn('Matter risk now High', flags)
        self.assertTrue(monitoring.has_high_risk_outcome)

        answers = monitoring.review_answers()
        self.assertEqual(len(answers), 6)
        by_label = {a['label']: a for a in answers}
        self.assertTrue(by_label['Changes discovered since the risk assessment']['risky'])
        self.assertTrue(by_label['Details of changes discovered']['risky'])
        self.assertTrue(by_label['Updated matter risk level']['risky'])
        self.assertFalse(by_label['How the client and matter will be monitored']['risky'])

        calm = make_monitoring(self.matter)
        self.assertEqual(calm.flagged_answers(), [])
        self.assertFalse(calm.has_high_risk_outcome)
        self.assertEqual(len(calm.review_answers()), 6)

    def test_dashboard_lists_awaiting_signoff_for_fee_earner(self):
        make_monitoring(self.matter, completed_by=self.staff)
        self.client.force_login(self.fee_earner)
        response = self.client.get(reverse('user_dashboard'))
        self.assertEqual(len(response.context['ongoing_monitorings_awaiting_signoff']), 1)
        self.assertContains(response, 'Ongoing monitoring awaiting sign-off (1)')
        self.assertContains(response, 'Yours to sign off')

    def test_dashboard_hides_awaiting_list_for_staff(self):
        make_monitoring(self.matter)
        self.client.force_login(self.staff)
        response = self.client.get(reverse('user_dashboard'))
        self.assertEqual(response.context['ongoing_monitorings_awaiting_signoff'], [])

    def test_matter_home_shows_review_controls_to_fee_earner(self):
        monitoring = make_monitoring(
            self.matter, any_changes_discovered='Yes', details_of_changes='New director')
        self.client.force_login(self.fee_earner)
        response = self.client.get(reverse('home', args=[self.matter.file_number]))
        self.assertContains(response, 'Awaiting sign-off')
        self.assertContains(response, 'Review &amp; sign off')
        self.assertContains(response, 'Changes discovered since the risk assessment')
        self.assertContains(response, 'New director')
        self.assertContains(response, reverse('sign_off_ongoing_monitoring', args=[monitoring.id]))

    def test_matter_home_hides_signoff_controls_from_staff(self):
        make_monitoring(self.matter)
        self.client.force_login(self.staff)
        response = self.client.get(reverse('home', args=[self.matter.file_number]))
        self.assertContains(response, 'Awaiting sign-off')
        self.assertNotContains(response, 'sign-off/')

    def test_download_shows_signoff(self):
        monitoring = make_monitoring(
            self.matter, signoff_status=OngoingMonitoring.SIGNOFF_SIGNED,
            completed_by=self.staff, signed_off_by=self.fee_earner)
        self.client.force_login(self.staff)
        response = self.client.get(
            reverse('download_ongoing_monitoring', args=[monitoring.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
