"""The risk assessment rating is scored from the answers, not chosen.

These tests pin the behaviour LSAG AML Guidance 5.13 requires of a scoring
system: weighted factors, automatic high-risk triggers, serious risks that
cannot be diluted by clean answers elsewhere, one fact counted once, and an
override that has to be documented.
"""

from datetime import date

from django.test import TestCase
from django.urls import reverse

from users.models import CustomUser
from ..forms import RiskAssessmentForm
from ..models import MatterType, RiskAssessment
from ..risk_scoring import (
    HIGH_BAND,
    SCORING_VERSION,
    apply_scores,
    score_risk_assessment,
)
from frontend.templatetags.utils import question_weight
from .tests_risk_signoff import (
    build_risk_assessment_post,
    make_matter,
    make_risk_assessment,
)


def clean_assessment(matter, **answers):
    """An assessment answered the low-risk way, with ``answers`` applied."""
    safe = {
        'matter': matter,
        'matter_transaction_value': '1000.00',
        'due_diligence_date': date(2026, 10, 1),
        'third_party_authority': 'N/A',
        'meeting_in_person': 'Yes',
        'id_verified_reliable_source': 'Yes',
        'companies_house_checked': 'N/A',
        'nominee_or_unconnected_directors': 'N/A',
        'usual_work': 'Yes',
        'consistent_with_client_profile': 'Yes',
        'makes_sense_for_client': 'Yes',
        'is_pep_questionnaire_completed': 'Yes',
        'is_source_of_funds_questionnaire_completed': 'Yes',
        'make_sense_location_of_instructions': 'Yes',
        'transactional_matter': 'Yes',
    }
    safe.update(answers)
    return RiskAssessment(**safe)


class ScoringTests(TestCase):
    """What the answers score."""

    def setUp(self):
        # Probate: medium inherent risk, so a clean file still comes out low.
        self.matter = make_matter('RS0001')

    def score(self, **answers):
        return score_risk_assessment(clean_assessment(self.matter, **answers))

    def test_clean_assessment_is_low_risk_with_standard_due_diligence(self):
        breakdown = self.score()
        self.assertEqual(breakdown['client']['level'], 'Low')
        self.assertEqual(breakdown['matter']['level'], 'Low')
        self.assertEqual(breakdown['overall_level'], 'Low')
        self.assertEqual(breakdown['due_diligence_level'], 'Standard')
        self.assertEqual(breakdown['version'], SCORING_VERSION)

    def test_factors_are_weighted_not_counted(self):
        """Two answers of different seriousness do not score the same."""
        adverse = self.score(adverse_media='Yes')['client']['score']
        unusual = self.score(unusual_client='Yes')['client']['score']
        self.assertGreater(adverse, unusual)

    def test_sanctions_make_it_high_whatever_the_total(self):
        breakdown = self.score(financial_sanctions='Yes')
        self.assertEqual(breakdown['overall_level'], 'High')
        self.assertEqual(breakdown['due_diligence_level'], 'Enhanced')
        self.assertIn('Financial sanctions concerns', breakdown['auto_high'])

    def test_no_apparent_purpose_makes_it_high_whatever_the_total(self):
        breakdown = self.score(lack_of_economic_or_legal_purpose='Yes')
        self.assertEqual(breakdown['matter']['level'], 'High')
        self.assertEqual(breakdown['overall_level'], 'High')

    def test_one_serious_section_is_not_diluted_by_clean_answers(self):
        """LSAG's inappropriate-scoring example, the other way round.

        A client not met in person whose identity was never verified from a
        reliable source maxes out the delivery channel section. The total is
        well under the high band, and the rating is still High.
        """
        breakdown = self.score(meeting_in_person='No',
                               id_verified_reliable_source='No')
        self.assertLess(breakdown['client']['score'], HIGH_BAND)
        self.assertEqual(breakdown['client']['band_level'], 'Medium')
        self.assertEqual(breakdown['client']['level'], 'High')

    def test_a_section_cannot_score_beyond_its_cap(self):
        """No one section can dominate the total (LSAG 5.13)."""
        breakdown = self.score(adverse_media='Yes', concerns_about_parties='Yes',
                               client_concerns='Yes', unusual_client='Yes',
                               third_party_authority='No')
        section = next(c for c in breakdown['client']['categories']
                       if c['key'] == 'client_party')
        self.assertGreater(section['raw'], section['cap'])
        self.assertEqual(section['score'], section['cap'])

    def test_cash_intensity_asked_twice_counts_once(self):
        """The retired duplicate question cannot inflate the score."""
        once = self.score(cash_intensive_industry='Yes')
        twice = self.score(cash_intensive_industry='Yes',
                           cash_intensive_business_activity='Yes')
        self.assertEqual(once['matter']['score'], twice['matter']['score'])

    def test_older_assessments_still_score_on_a_retired_question(self):
        """A retired question answered Yes on an old assessment still counts."""
        breakdown = self.score(cash_intensive_business_activity='Yes')
        section = next(c for c in breakdown['matter']['categories']
                       if c['key'] == 'sector')
        self.assertEqual(section['score'], 12)

    def test_a_default_is_not_read_as_an_answer(self):
        """``makes_sense_for_client`` defaults to its own risky answer.

        Assessments completed before that question was merged into
        ``consistent_with_client_profile`` all carry 'No' whether or not anyone
        answered it, so it cannot be scored without inventing a risk.
        """
        breakdown = self.score(makes_sense_for_client='No')
        section = next(c for c in breakdown['matter']['categories']
                       if c['key'] == 'nature_of_work')
        self.assertEqual(section['score'], 0)

    def test_domestic_pep_starts_lower_than_a_non_domestic_pep(self):
        """MLRs reg 35(3A), in force since 10 January 2024."""
        domestic = self.score(pep_type='Domestic')
        foreign = self.score(pep_type='Non-domestic')
        self.assertEqual(domestic['client']['level'], 'Medium')
        self.assertEqual(foreign['client']['level'], 'High')
        # Either way enhanced due diligence is required.
        self.assertEqual(domestic['due_diligence_level'], 'Enhanced')
        self.assertEqual(foreign['due_diligence_level'], 'Enhanced')
        self.assertTrue(any('lesser extent' in note for note in domestic['notes']))

    def test_enhanced_due_diligence_follows_the_regulations_not_the_score(self):
        """A low total still gets enhanced due diligence where the MLRs say so."""
        breakdown = self.score(unusual_complex_transaction='Yes')
        self.assertEqual(breakdown['due_diligence_level'], 'Enhanced')
        self.assertTrue(breakdown['edd_reasons'])

    def test_high_risk_work_and_a_large_transaction_is_high_risk(self):
        """LSAG 5.12's own example: conveyancing at £1m or more."""
        self.matter.matter_type = MatterType.objects.create(
            type='Conveyancing', inherent_risk='High')
        self.matter.save()
        breakdown = self.score(matter_transaction_value='1250000.00')
        self.assertEqual(breakdown['matter']['level'], 'High')

    def test_low_risk_work_starts_from_nothing(self):
        self.matter.matter_type = MatterType.objects.create(
            type='Family', inherent_risk='Low')
        self.matter.save()
        self.assertEqual(self.score()['matter']['score'], 0)

    def test_it_is_possible_to_score_high_from_ordinary_answers(self):
        """Weighting must not make a high rating unreachable (LSAG 5.13)."""
        breakdown = self.score(receiving_funds_from_overseas='Yes',
                               receiving_funds_from_third_parties='Yes',
                               unusual_complex_transaction='Yes',
                               unusual_pattern_of_transactions='Yes')
        self.assertEqual(breakdown['matter']['level'], 'High')
        self.assertEqual(breakdown['auto_high'], [])


class ApplyScoresTests(TestCase):
    """Writing the scoring onto the assessment."""

    def setUp(self):
        self.matter = make_matter('RS0002')

    def test_scores_fill_in_the_recorded_rating(self):
        ra = clean_assessment(self.matter, financial_sanctions='Yes')
        apply_scores(ra)
        self.assertEqual(ra.client_risk_level, 'High')
        self.assertEqual(ra.overall_risk_level, 'High')
        self.assertEqual(ra.customer_due_diligence_level, 'Enhanced')
        self.assertEqual(ra.computed_client_risk_level, 'High')
        self.assertEqual(ra.scoring_version, SCORING_VERSION)
        self.assertEqual(ra.risk_score_breakdown['overall_level'], 'High')

    def test_an_override_with_a_reason_is_kept(self):
        ra = clean_assessment(self.matter, adverse_media='Yes')
        ra.client_risk_level = 'High'
        ra.matter_risk_level = 'Low'
        ra.customer_due_diligence_level = 'Standard'
        ra.risk_override_reason = 'Known client; the article is about a namesake.'
        apply_scores(ra)
        self.assertEqual(ra.client_risk_level, 'High')
        self.assertEqual(ra.computed_client_risk_level, 'Medium')
        self.assertEqual(ra.overall_risk_level, 'High')
        self.assertTrue(ra.is_risk_overridden)

    def test_an_override_that_rates_down_is_identifiable(self):
        ra = clean_assessment(self.matter, adverse_media='Yes')
        ra.client_risk_level = 'Low'
        ra.matter_risk_level = 'Low'
        ra.customer_due_diligence_level = 'Standard'
        ra.risk_override_reason = 'Checked: the adverse media is a different person.'
        apply_scores(ra)
        self.assertTrue(ra.is_rated_below_computed)

    def test_the_reason_goes_when_the_rating_catches_up(self):
        """An old reason must not stop the rating following the score again."""
        ra = clean_assessment(self.matter, adverse_media='Yes')
        ra.client_risk_level = 'Low'
        ra.matter_risk_level = 'Low'
        ra.customer_due_diligence_level = 'Standard'
        ra.risk_override_reason = 'Wrong person.'
        apply_scores(ra)
        ra.client_risk_level = 'Medium'
        apply_scores(ra)
        self.assertEqual(ra.risk_override_reason, '')
        self.assertFalse(ra.is_risk_overridden)

    def test_outstanding_enhanced_measures_are_listed(self):
        ra = clean_assessment(self.matter, pep_type='Domestic')
        apply_scores(ra)
        outstanding = ra.outstanding_edd_measures
        self.assertIn('Enhanced measures taken not recorded', outstanding)
        self.assertTrue(any('Senior management approval' in item
                            for item in outstanding))

    def test_a_pep_without_a_type_is_treated_as_the_higher_risk(self):
        ra = make_risk_assessment(self.matter, politically_exposed_person='Yes')
        ra.refresh_from_db()
        self.assertEqual(ra.pep_type, 'Non-domestic')

    def test_recording_a_pep_type_answers_the_pep_question(self):
        ra = make_risk_assessment(self.matter, pep_type='Domestic')
        ra.refresh_from_db()
        self.assertEqual(ra.politically_exposed_person, 'Yes')


class RiskAssessmentFormTests(TestCase):
    """What the form will and will not accept."""

    def setUp(self):
        self.matter = make_matter('RS0003')
        self.user = CustomUser.objects.create_user(
            username='rsf', email='rsf@example.com', first_name='Risk',
            last_name='Scorer', password='password', max_holidays_in_year=20)

    def post(self, **overrides):
        return build_risk_assessment_post(self.matter.id, **overrides)

    def test_a_clean_assessment_is_accepted(self):
        form = RiskAssessmentForm(data=self.post())
        self.assertTrue(form.is_valid(), form.errors.as_data())
        self.assertEqual(form.breakdown['overall_level'], 'Low')

    def test_a_new_assessment_starts_with_every_question_blank(self):
        """A model default is not an answer, and must not be scored as one."""
        form = RiskAssessmentForm()
        self.assertEqual(form.fields['meeting_in_person'].initial, '')
        self.assertEqual(form.fields['usual_work'].initial, '')
        self.assertIn('', [choice[0] for choice in form.fields['usual_work'].choices])
        # The rating is not a question, so it keeps following the score.
        self.assertNotEqual(form.fields['client_risk_level'].initial, '')

    def test_an_unanswered_question_is_rejected(self):
        form = RiskAssessmentForm(data=self.post(meeting_in_person=''))
        self.assertFalse(form.is_valid())
        self.assertIn('meeting_in_person', form.errors)

    def test_an_existing_assessment_keeps_its_answers(self):
        ra = make_risk_assessment(self.matter, meeting_in_person='No')
        form = RiskAssessmentForm(instance=ra)
        self.assertEqual(form['meeting_in_person'].value(), 'No')

    def test_the_duplicated_questions_are_no_longer_asked(self):
        form = RiskAssessmentForm()
        for name in ('makes_sense_for_client', 'higher_risk_sector',
                     'cash_intensive_business_activity'):
            self.assertNotIn(name, form.fields)

    def test_a_rating_below_the_score_needs_a_reason(self):
        form = RiskAssessmentForm(data=self.post(adverse_media='Yes'))
        self.assertFalse(form.is_valid())
        self.assertIn('risk_override_reason', form.errors)

    def test_a_rating_below_the_score_is_accepted_with_a_reason(self):
        form = RiskAssessmentForm(data=self.post(
            adverse_media='Yes',
            risk_override_reason='The article concerns a different individual.'))
        self.assertTrue(form.is_valid(), form.errors.as_data())

    def test_mandatory_enhanced_due_diligence_cannot_be_reduced(self):
        """A rating is a judgement; enhanced due diligence under the MLRs is not."""
        form = RiskAssessmentForm(data=self.post(
            high_risk_third_country_or_jurisdiction='Yes',
            client_risk_level='High', matter_risk_level='Low',
            customer_due_diligence_level='Standard',
            risk_override_reason='Reason for the rating.'))
        self.assertFalse(form.is_valid())
        self.assertIn('customer_due_diligence_level', form.errors)

    def test_enhanced_due_diligence_has_to_say_what_was_done(self):
        form = RiskAssessmentForm(data=self.post(
            unusual_complex_transaction='Yes',
            customer_due_diligence_level='Enhanced'))
        self.assertFalse(form.is_valid())
        self.assertIn('edd_measures_taken', form.errors)
        self.assertIn('edd_enhanced_monitoring', form.errors)
        self.assertIn('evidence_of_source_of_wealth', form.errors)

    def test_a_pep_needs_senior_management_approval(self):
        """MLRs reg 35(1): approval before the relationship is entered into."""
        form = RiskAssessmentForm(data=self.post(
            pep_type='Domestic',
            client_risk_level='Medium',
            customer_due_diligence_level='Enhanced',
            edd_measures_taken='Open source checks on the client and spouse.',
            edd_enhanced_monitoring='Reviewed every three months.',
            evidence_of_source_of_wealth='True'))
        self.assertFalse(form.is_valid())
        self.assertIn('edd_senior_approval_by', form.errors)

    def test_a_complete_enhanced_assessment_is_accepted(self):
        form = RiskAssessmentForm(data=self.post(
            pep_type='Domestic',
            client_risk_level='Medium',
            customer_due_diligence_level='Enhanced',
            edd_measures_taken='Open source checks on the client and spouse.',
            edd_enhanced_monitoring='Reviewed every three months.',
            evidence_of_source_of_wealth='True',
            edd_senior_approval_by=self.user.id,
            edd_senior_approval_date='2026-10-01'))
        self.assertTrue(form.is_valid(), form.errors.as_data())


class DetailBoxTests(TestCase):
    """The free-text boxes are required when the answers call for them."""

    def setUp(self):
        self.matter = make_matter('RS0005')

    def post(self, **overrides):
        return build_risk_assessment_post(self.matter.id, **overrides)

    def blank(self, *fields, **overrides):
        data = self.post(**overrides)
        for field in fields:
            data[field] = ''
        return RiskAssessmentForm(data=data)

    def test_a_clean_assessment_needs_no_free_text(self):
        """Nothing is flagged, so there is nothing to write in the boxes."""
        form = self.blank(
            'issues_identified_client_risks_sec',
            'issues_identified_jurisdiction_risks_sec',
            'issues_identified_matter_risks_sec',
            'issues_identified_enhanced_due_dilligence',
            'who_they_are',
            'product_service_risk_details',
            'beneficial_owners_details',
            'ultimate_beneficial_owners',
            'matter_description',
        )
        self.assertTrue(form.is_valid(), form.errors.as_data())

    def test_a_flagged_section_has_to_be_written_up(self):
        form = self.blank('issues_identified_client_risks_sec',
                          adverse_media='Yes', client_concerns='Yes',
                          risk_override_reason='')
        self.assertFalse(form.is_valid())
        self.assertIn('issues_identified_client_risks_sec', form.errors)

    def test_a_flagged_section_does_not_demand_the_other_sections(self):
        form = self.blank('issues_identified_jurisdiction_risks_sec',
                          'issues_identified_matter_risks_sec',
                          client_concerns='Yes',
                          issues_identified_client_risks_sec='Known to us for years.')
        self.assertTrue(form.is_valid(), form.errors.as_data())

    def test_not_meeting_the_client_needs_an_explanation(self):
        form = self.blank('who_they_are', meeting_in_person='No',
                          id_verified_reliable_source='Yes')
        self.assertFalse(form.is_valid())
        self.assertIn('who_they_are', form.errors)

    def test_an_instruction_that_does_not_fit_needs_details(self):
        form = self.blank('product_service_risk_details',
                          consistent_with_client_profile='No',
                          issues_identified_matter_risks_sec='Queried with the client.',
                          client_risk_level='Low', matter_risk_level='High')
        self.assertFalse(form.is_valid())
        self.assertIn('product_service_risk_details', form.errors)

    def test_an_entity_client_needs_its_beneficial_ownership(self):
        self.matter.client1.is_business = True
        self.matter.client1.save()
        form = self.blank('beneficial_owners_details', 'ultimate_beneficial_owners')
        self.assertFalse(form.is_valid())
        self.assertIn('beneficial_owners_details', form.errors)
        self.assertIn('ultimate_beneficial_owners', form.errors)

    def test_an_individual_client_does_not(self):
        form = self.blank('beneficial_owners_details', 'ultimate_beneficial_owners')
        self.assertTrue(form.is_valid(), form.errors.as_data())


class QuestionWeightTests(TestCase):
    """The form tells you what a question is worth, from the weights it scores by."""

    def test_every_scored_question_has_a_weight_to_show(self):
        from ..risk_scoring import QUESTION_WEIGHTS
        for field, weights in QUESTION_WEIGHTS.items():
            self.assertTrue(weights, field)
            for weight in weights:
                self.assertGreater(weight['points'], 0, field)
                self.assertTrue(weight['answer'], field)

    def test_the_weight_shown_is_the_weight_scored(self):
        """The displayed figure comes from the scoring, so it cannot drift."""
        self.assertEqual(question_weight('adverse_media'), 'Yes adds 12')
        self.assertEqual(question_weight('meeting_in_person'), 'No adds 8')

    def test_an_automatic_trigger_says_so_rather_than_showing_points(self):
        self.assertEqual(question_weight('financial_sanctions'),
                         'Yes \u2192 high risk outright')

    def test_a_question_weighted_two_ways_shows_both(self):
        shown = question_weight('pep_type')
        self.assertIn('Non-domestic \u2192 high risk outright', shown)
        self.assertIn('Domestic adds 20', shown)

    def test_an_unscored_question_says_nothing(self):
        self.assertEqual(question_weight('transactional_matter'), '')

    def test_the_form_shows_the_weights_beside_the_questions(self):
        matter = make_matter('RS0006')
        user = CustomUser.objects.create_user(
            username='qwt', email='qwt@example.com', first_name='Q', last_name='W',
            password='password', max_holidays_in_year=20)
        self.client.force_login(user)
        response = self.client.get(
            reverse('add_risk_assessment', args=[matter.file_number]))
        body = response.content.decode()
        self.assertIn('Yes adds 12', body)
        self.assertIn('high risk outright', body)
        # ...and the panel explains the section ceilings and floors.
        self.assertIn('Each section is capped', body)
        self.assertIn('sets the rating on its own', body)


class RiskAssessmentViewTests(TestCase):
    """The form and the live scoring endpoint."""

    def setUp(self):
        self.matter = make_matter('RS0004')
        self.user = CustomUser.objects.create_user(
            username='rsv', email='rsv@example.com', first_name='View',
            last_name='Tester', password='password', max_holidays_in_year=20)
        self.client.force_login(self.user)

    def test_saving_an_assessment_scores_it(self):
        response = self.client.post(
            reverse('add_risk_assessment', args=[self.matter.file_number]),
            build_risk_assessment_post(self.matter.id, financial_sanctions='Yes',
                                       client_risk_level='High',
                                       customer_due_diligence_level='Enhanced',
                                       edd_measures_taken='Escalated to the MLRO.',
                                       edd_enhanced_monitoring='Monthly review.',
                                       evidence_of_source_of_wealth='True'))
        self.assertEqual(response.status_code, 302)
        ra = RiskAssessment.objects.get(matter=self.matter)
        self.assertEqual(ra.overall_risk_level, 'High')
        self.assertEqual(ra.customer_due_diligence_level, 'Enhanced')
        self.assertEqual(ra.risk_override_reason, '')
        self.assertEqual(ra.scoring_version, SCORING_VERSION)

    def test_the_score_preview_explains_the_rating(self):
        response = self.client.post(
            reverse('score_risk_assessment_preview'),
            {'matter': self.matter.id, 'financial_sanctions': 'Yes',
             'matter_transaction_value': '1000'})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['breakdown']['overall_level'], 'High')
        self.assertIn('High risk regardless of score', payload['html'])

    def test_the_score_preview_saves_nothing(self):
        self.client.post(reverse('score_risk_assessment_preview'),
                         {'matter': self.matter.id, 'financial_sanctions': 'Yes'})
        self.assertFalse(RiskAssessment.objects.exists())

    def test_the_form_opens_on_the_inherent_risk_of_the_work(self):
        self.matter.matter_type = MatterType.objects.create(
            type='Conveyancing', inherent_risk='High')
        self.matter.save()
        response = self.client.get(
            reverse('add_risk_assessment', args=[self.matter.file_number]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['breakdown']['matter']['score'], 15)

    def test_the_matter_page_shows_the_rating_and_the_working(self):
        """Covers the summary card and the detail tables on the matter page."""
        ra = clean_assessment(self.matter, adverse_media='Yes')
        apply_scores(ra)
        ra.save()
        response = self.client.get(
            reverse('home', args=[self.matter.file_number]))
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn('Overall: Medium', body)
        self.assertIn('How this rating was scored', body)

    def test_the_pdf_explains_the_rating(self):
        ra = clean_assessment(self.matter, financial_sanctions='Yes')
        apply_scores(ra)
        ra.save()
        response = self.client.get(
            reverse('download_risk_assessment', args=[ra.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
