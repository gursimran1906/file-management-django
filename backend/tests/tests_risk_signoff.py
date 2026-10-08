from datetime import date

from django import forms
from django.test import TestCase
from django.urls import reverse

from users.models import CustomUser
from ..forms import RiskAssessmentForm
from ..models import ClientContactDetails, FileStatus, MatterType, RiskAssessment, WIP


def make_matter(file_number='RA0001', fee_earner=None):
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
    matter_type = MatterType.objects.create(type='Probate')
    file_status = FileStatus.objects.create(status='Open')
    return WIP.objects.create(
        file_number=file_number,
        client1=client,
        matter_description='Test matter',
        matter_type=matter_type,
        funding='Pvt',
        fee_earner=fee_earner,
        file_status=file_status,
    )


def make_risk_assessment(matter, **overrides):
    defaults = {
        'matter': matter,
        'matter_transaction_value': '1000.00',
        'due_diligence_date': date(2026, 9, 1),
        'signoff_status': RiskAssessment.SIGNOFF_AWAITING,
    }
    defaults.update(overrides)
    return RiskAssessment.objects.create(**defaults)


def build_risk_assessment_post(matter_id):
    """A valid POST for RiskAssessmentForm built from the form's own fields."""
    form = RiskAssessmentForm()
    data = {}
    for name, field in form.fields.items():
        if name == 'matter':
            data[name] = matter_id
        elif isinstance(field, forms.BooleanField):
            data[name] = 'True'
        elif getattr(field, 'choices', None):
            choices = [choice[0] for choice in field.choices if choice[0]]
            data[name] = 'No' if 'No' in choices else choices[0]
        elif isinstance(field, forms.DecimalField):
            data[name] = '100'
        elif isinstance(field, forms.DateField):
            data[name] = '2026-09-01'
        else:
            data[name] = 'Test answer'
    return data


class RiskAssessmentSignoffTests(TestCase):
    def setUp(self):
        self.staff = CustomUser.objects.create_user(
            username='stf',
            email='staff@example.com',
            first_name='Support',
            last_name='Staff',
            password='password',
            max_holidays_in_year=20,
        )
        self.fee_earner = CustomUser.objects.create_user(
            username='fee',
            email='fee@example.com',
            first_name='Fee',
            last_name='Earner',
            password='password',
            max_holidays_in_year=20,
            is_matter_fee_earner=True,
        )
        self.matter = make_matter(fee_earner=self.fee_earner)

    def test_form_excludes_signoff_fields(self):
        form = RiskAssessmentForm()
        for field in ('due_diligence_signed_by', 'signoff_status',
                      'signed_off_by', 'completed_by', 'signoff_comments'):
            self.assertNotIn(field, form.fields)

    def test_staff_submission_goes_to_awaiting_signoff(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse('add_risk_assessment', args=[self.matter.file_number]),
            build_risk_assessment_post(self.matter.id),
        )
        self.assertEqual(response.status_code, 302)
        assessment = RiskAssessment.objects.get(matter=self.matter)
        self.assertEqual(assessment.signoff_status, RiskAssessment.SIGNOFF_AWAITING)
        self.assertEqual(assessment.completed_by, self.staff)
        self.assertIsNone(assessment.signed_off_by)
        self.assertIsNone(assessment.due_diligence_signed_by)

    def test_fee_earner_submission_auto_signs_off(self):
        self.client.force_login(self.fee_earner)
        response = self.client.post(
            reverse('add_risk_assessment', args=[self.matter.file_number]),
            build_risk_assessment_post(self.matter.id),
        )
        self.assertEqual(response.status_code, 302)
        assessment = RiskAssessment.objects.get(matter=self.matter)
        self.assertEqual(assessment.signoff_status, RiskAssessment.SIGNOFF_SIGNED)
        self.assertEqual(assessment.completed_by, self.fee_earner)
        self.assertEqual(assessment.signed_off_by, self.fee_earner)
        self.assertEqual(assessment.due_diligence_signed_by, self.fee_earner)
        self.assertIsNotNone(assessment.signed_off_at)

    def test_fee_earner_can_sign_off(self):
        assessment = make_risk_assessment(self.matter, completed_by=self.staff)
        self.client.force_login(self.fee_earner)
        response = self.client.post(
            reverse('sign_off_risk_assessment', args=[assessment.id]))
        self.assertEqual(response.status_code, 302)
        assessment.refresh_from_db()
        self.assertTrue(assessment.is_signed_off)
        self.assertEqual(assessment.signed_off_by, self.fee_earner)
        self.assertEqual(assessment.due_diligence_signed_by, self.fee_earner)

    def test_non_fee_earner_cannot_sign_off(self):
        assessment = make_risk_assessment(self.matter, completed_by=self.staff)
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse('sign_off_risk_assessment', args=[assessment.id]))
        self.assertEqual(response.status_code, 302)
        assessment.refresh_from_db()
        self.assertEqual(assessment.signoff_status, RiskAssessment.SIGNOFF_AWAITING)
        self.assertIsNone(assessment.signed_off_by)

    def test_return_requires_comments_and_sets_status(self):
        assessment = make_risk_assessment(self.matter, completed_by=self.staff)
        self.client.force_login(self.fee_earner)

        self.client.post(reverse('return_risk_assessment', args=[assessment.id]),
                         {'comments': ''})
        assessment.refresh_from_db()
        self.assertEqual(assessment.signoff_status, RiskAssessment.SIGNOFF_AWAITING)

        self.client.post(reverse('return_risk_assessment', args=[assessment.id]),
                         {'comments': 'Source of funds section is incomplete.'})
        assessment.refresh_from_db()
        self.assertEqual(assessment.signoff_status, RiskAssessment.SIGNOFF_RETURNED)
        self.assertEqual(assessment.signoff_comments,
                         'Source of funds section is incomplete.')

    def test_staff_edit_of_signed_assessment_reopens_signoff(self):
        assessment = make_risk_assessment(
            self.matter,
            signoff_status=RiskAssessment.SIGNOFF_SIGNED,
            signed_off_by=self.fee_earner,
            due_diligence_signed_by=self.fee_earner,
        )
        self.client.force_login(self.staff)
        post_data = build_risk_assessment_post(self.matter.id)
        post_data['client_source_of_funds'] = 'Updated answer'
        response = self.client.post(
            reverse('edit_risk_assessment', args=[assessment.id]), post_data)
        self.assertEqual(response.status_code, 302)
        assessment.refresh_from_db()
        self.assertEqual(assessment.signoff_status, RiskAssessment.SIGNOFF_AWAITING)
        self.assertIsNone(assessment.signed_off_by)
        self.assertEqual(assessment.completed_by, self.staff)

    def test_flagged_answers_reports_risky_values(self):
        assessment = make_risk_assessment(
            self.matter,
            politically_exposed_person='Yes',
            usual_work='No',
            meeting_in_person='No',
            adverse_media='Yes',
        )
        flags = assessment.flagged_answers()
        self.assertIn('EDD: PEP, family member or close associate', flags)
        self.assertIn('Not our usual type of work', flags)
        self.assertIn('Client will not be met in person', flags)
        self.assertIn('Adverse media about client or beneficial owners', flags)

    def test_high_risk_outcome_property(self):
        low = make_risk_assessment(self.matter)
        self.assertFalse(low.has_high_risk_outcome)
        high = make_risk_assessment(
            self.matter, matter_risk_level='High')
        self.assertTrue(high.has_high_risk_outcome)
        pep = make_risk_assessment(
            self.matter, politically_exposed_person='Yes')
        self.assertTrue(pep.has_high_risk_outcome)

    def test_dashboard_lists_awaiting_signoff_for_fee_earner(self):
        make_risk_assessment(self.matter, completed_by=self.staff)
        self.client.force_login(self.fee_earner)
        response = self.client.get(reverse('user_dashboard'))
        self.assertEqual(response.status_code, 200)
        awaiting = response.context['risk_assessments_awaiting_signoff']
        self.assertEqual(len(awaiting), 1)
        self.assertContains(response, 'Awaiting sign-off (1)')

    def test_matter_home_shows_review_controls_to_fee_earner(self):
        make_risk_assessment(
            self.matter,
            completed_by=self.staff,
            politically_exposed_person='Yes',
        )
        self.client.force_login(self.fee_earner)
        response = self.client.get(
            reverse('home', args=[self.matter.file_number]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Awaiting sign-off')
        self.assertContains(response, 'Review &amp; sign off')
        self.assertContains(response, 'EDD: PEP, family member or close associate')
        self.assertContains(response, 'sign-off/')

    def test_matter_home_hides_signoff_controls_from_staff(self):
        make_risk_assessment(self.matter, completed_by=self.staff)
        self.client.force_login(self.staff)
        response = self.client.get(
            reverse('home', args=[self.matter.file_number]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Awaiting sign-off')
        self.assertNotContains(response, 'Review &amp; sign off')

    def test_dashboard_hides_awaiting_list_for_staff(self):
        make_risk_assessment(self.matter, completed_by=self.staff)
        self.client.force_login(self.staff)
        response = self.client.get(reverse('user_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context['risk_assessments_awaiting_signoff'], [])
