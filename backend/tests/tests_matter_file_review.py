import importlib

from django.test import TestCase
from django.urls import reverse

from users.models import CustomUser

from ..models import (
    ClientContactDetails,
    FileLocation,
    FileStatus,
    MatterFileReview,
    MatterType,
    Modifications,
    WIP,
)
from ..views import MATTER_FILE_REVIEW_SECTIONS


def _section(title):
    return next(s for s in MATTER_FILE_REVIEW_SECTIONS if s['title'] == title)


def _questions(title):
    return [row['question'] for row in _section(title)['rows']]


class MatterFileReviewQuestionnaireTests(TestCase):
    """The questionnaire reworked in Oct 2026: fewer sections, reworded
    questions, and a single comments/recommendations box."""

    def test_section_titles(self):
        self.assertEqual(
            [s['title'] for s in MATTER_FILE_REVIEW_SECTIONS],
            [
                'Client Onboarding',
                'Ongoing Monitoring',
                'Finance, Costs And Accounting',
                'Client Care, Legal Advice And Instructions',
                'Specific Risk Issues',
            ],
        )

    def test_every_row_maps_to_model_fields(self):
        field_names = {f.name for f in MatterFileReview._meta.get_fields()}
        for section in MATTER_FILE_REVIEW_SECTIONS:
            for row in section['rows']:
                self.assertIn(row['answer_field'], field_names)
                self.assertIn(row['comments_field'], field_names)
                self.assertEqual(
                    row['comments_field'], f"{row['answer_field']}_comments")

    def test_client_onboarding_drops_checklist_and_adds_filed(self):
        questions = _questions('Client Onboarding')
        self.assertNotIn('File Opening Checklist completed?', questions)
        self.assertEqual(questions[-1], 'Initial Risk Assessment completed & filed?')
        self.assertEqual(len(questions), 5)

    def test_ongoing_monitoring_wording(self):
        self.assertEqual(_questions('Ongoing Monitoring')[:2], [
            'Ongoing AML, financial crime prevention and sanctions monitoring '
            'carried out in accordance with company policy and procedures?',
            'Ongoing monitoring documents correctly filed?',
        ])

    def test_finance_wording(self):
        questions = _questions('Finance, Costs And Accounting')
        self.assertEqual(
            questions[0],
            'Has Money on Account been received as requested in the client care letter?')
        self.assertEqual(questions[-1], 'Are there any unpaid invoices?')

    def test_client_care_section(self):
        self.assertEqual(_questions('Client Care, Legal Advice And Instructions'), [
            'Has the client been kept updated?',
            'Is the matter proceeding in accordance with client instructions?',
            'Have cost estimates been updated as necessary?',
        ])

    def test_specific_risk_first_question(self):
        self.assertEqual(
            _questions('Specific Risk Issues')[0],
            'Undertakings given by the firm have been satisfied?')

    def test_removed_fields_are_gone(self):
        field_names = {f.name for f in MatterFileReview._meta.get_fields()}
        for name in (
            'file_opening_checklist_completed',
            'key_dates_recorded_in_calendar_and_wip',
            'key_information_and_advice_shared',
            'matter_progressing_without_dormancy',
            'file_maintained_in_good_order',
            'recommendations_and_further_actions',
            'additional_notes_or_comments',
            'overdue_invoices',
            'appropriate_advice_given',
            'matter_within_client_care_scope',
            'undertakings_discharged_or_released',
        ):
            self.assertNotIn(name, field_names)
            self.assertNotIn(f'{name}_comments', field_names)
        self.assertIn('comments_recommendations_and_further_actions', field_names)


class OutcomeMergeMigrationTests(TestCase):
    """The data step of 0088 folds the two old outcome boxes into one."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.migration = importlib.import_module(
            'backend.migrations.0088_matterfilereview_question_rework')

    def test_both_present_joined_with_blank_line(self):
        self.assertEqual(
            self.migration.merge_outcome_text('Chase client.', 'File is tidy.'),
            'Chase client.\n\nFile is tidy.')

    def test_single_value_kept_as_is(self):
        self.assertEqual(self.migration.merge_outcome_text(None, '  Notes '), 'Notes')
        self.assertEqual(self.migration.merge_outcome_text('Recs', ''), 'Recs')

    def test_nothing_to_merge_stays_null(self):
        self.assertIsNone(self.migration.merge_outcome_text(None, None))
        self.assertIsNone(self.migration.merge_outcome_text('', '   '))


class MatterFileReviewViewTests(TestCase):

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='fr1', email='fr1@example.com', first_name='File',
            last_name='Reviewer', password='password', max_holidays_in_year=20,
            is_matter_fee_earner=True,
        )
        self.client.force_login(self.user)
        client = ClientContactDetails.objects.create(
            name='Review Client', address_line1='1 St', address_line2='',
            county='Essex', postcode='SS7 1QT', email='rc@example.com',
            contact_number='0123456789', occupation='Chef',
        )
        self.matter = WIP.objects.create(
            file_number='FRV0010001', fee_earner=self.user, client1=client,
            matter_description='Review test matter', funding='PF',
            matter_type=MatterType.objects.create(type='Probate'),
            file_status=FileStatus.objects.create(status='Open'),
            file_location=FileLocation.objects.create(location='Cabinet B'),
            created_by=self.user,
        )

    def _payload(self, **overrides):
        payload = {
            'client_matter_reference': 'FRV0010001',
            'supervisor': 'Sue Pervisor',
            'file_reviewed_by': str(self.user.id),
            'date_reviewed': '2026-10-08',
            'file_review_completed_by': str(self.user.id),
            'date_review_completed': '2026-10-08',
            'unpaid_invoices': 'No',
            'client_kept_updated': 'Yes',
            'client_kept_updated_comments': 'Monthly update letters on file.',
            'undertakings_satisfied': 'Yes',
            'comments_recommendations_and_further_actions': 'Chase the search fee.\n\nOtherwise in good order.',
        }
        payload.update(overrides)
        return payload

    def test_add_page_renders_new_questions_only(self):
        resp = self.client.get(
            reverse('add_matter_file_review', args=[self.matter.file_number]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Client Care, Legal Advice And Instructions')
        self.assertContains(resp, 'Are there any unpaid invoices?')
        self.assertContains(
            resp, 'Additional comments, recommendations and further actions')
        self.assertNotContains(resp, 'Matter Management')
        self.assertNotContains(resp, 'File Opening Checklist')
        self.assertNotContains(resp, 'Recommendations and further action required')
        self.assertNotContains(resp, 'Additional notes or comments')

    def test_add_saves_answers_and_combined_comments(self):
        resp = self.client.post(
            reverse('add_matter_file_review', args=[self.matter.file_number]),
            self._payload())
        self.assertRedirects(
            resp, reverse('home', args=[self.matter.file_number]),
            fetch_redirect_response=False)
        review = MatterFileReview.objects.get(matter=self.matter)
        self.assertEqual(review.unpaid_invoices, 'No')
        self.assertEqual(review.client_kept_updated, 'Yes')
        self.assertEqual(review.undertakings_satisfied, 'Yes')
        self.assertEqual(
            review.comments_recommendations_and_further_actions,
            'Chase the search fee.\n\nOtherwise in good order.')
        self.assertEqual(review.created_by, self.user)

    def test_edit_logs_change_to_combined_comments(self):
        review = MatterFileReview.objects.create(
            matter=self.matter, created_by=self.user,
            comments_recommendations_and_further_actions='Old text')
        resp = self.client.post(
            reverse('edit_matter_file_review', args=[review.id]),
            self._payload(comments_recommendations_and_further_actions='New text'))
        self.assertEqual(resp.status_code, 302)
        review.refresh_from_db()
        self.assertEqual(review.comments_recommendations_and_further_actions, 'New text')
        mod = Modifications.objects.filter(object_id=review.id).latest('id')
        self.assertIn('comments_recommendations_and_further_actions', mod.changes)

    def test_matter_home_shows_combined_comments(self):
        MatterFileReview.objects.create(
            matter=self.matter, created_by=self.user,
            date_review_completed='2026-10-08',
            file_review_completed_by=self.user,
            unpaid_invoices='Yes',
            comments_recommendations_and_further_actions='Chase the search fee.')
        resp = self.client.get(reverse('home', args=[self.matter.file_number]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Comments, recommendations and further actions')
        self.assertContains(resp, 'Chase the search fee.')
        self.assertContains(resp, 'Are there any unpaid invoices?')
        self.assertNotContains(resp, 'Matter Management')

    def test_download_pdf(self):
        review = MatterFileReview.objects.create(
            matter=self.matter, created_by=self.user,
            comments_recommendations_and_further_actions='Chase the search fee.')
        resp = self.client.get(
            reverse('download_matter_file_review', args=[review.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')
        self.assertTrue(resp.content.startswith(b'%PDF'))
