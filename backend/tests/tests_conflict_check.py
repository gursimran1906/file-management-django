from datetime import date

from django.test import TestCase
from django.urls import reverse

from users.models import CustomUser

from ..conflict_utils import (
    SOURCE_AUTHORISED,
    SOURCE_CLIENT,
    SOURCE_OPPOSING,
    run_conflict_check,
)
from ..models import (
    AuthorisedParties,
    ClientContactDetails,
    ConflictCheck,
    Onboarding,
    OnboardingGroup,
    OthersideDetails,
    WIP,
)


def make_client(name, dob=None):
    return ClientContactDetails.objects.create(
        name=name,
        dob=dob,
        occupation='Retired',
        address_line1='1 Test Street',
        address_line2='',
        county='Essex',
        postcode='SS7 1QT',
        email='test@example.com',
        contact_number='0123456789',
    )


def make_matter(file_number, client, **kwargs):
    return WIP.objects.create(
        file_number=file_number, client1=client, funding='PRI', **kwargs)


class RunConflictCheckTests(TestCase):
    def test_clear_name_returns_no_matches(self):
        make_client('Existing Client')
        self.assertEqual(run_conflict_check('Completely Different'), [])

    def test_empty_name_returns_no_matches(self):
        self.assertEqual(run_conflict_check(''), [])
        self.assertEqual(run_conflict_check('   '), [])

    def test_matches_existing_client_with_matter(self):
        client = make_client('John Smith')
        make_matter('ABC1234567', client)

        matches = run_conflict_check('John Smith')

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['source'], SOURCE_CLIENT)
        self.assertEqual(matches[0]['name'], 'John Smith')
        self.assertEqual(matches[0]['matters'], ['ABC1234567'])

    def test_matches_opposing_party(self):
        client = make_client('Our Client')
        other = OthersideDetails.objects.create(name='Jane Doe')
        make_matter('ABC1234567', client, other_side=other)

        matches = run_conflict_check('Jane Doe')

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['source'], SOURCE_OPPOSING)
        self.assertEqual(matches[0]['matters'], ['ABC1234567'])

    def test_matches_authorised_party(self):
        client = make_client('Our Client')
        ap = AuthorisedParties.objects.create(
            name='Attorney Adam', relationship_to_client='Attorney',
            address_line1='', address_line2='', county='', postcode='',
            email='', contact_number='')
        make_matter('ABC1234567', client, authorised_party1=ap)

        matches = run_conflict_check('Attorney Adam')

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['source'], SOURCE_AUTHORISED)

    def test_opposing_party_sorts_before_client(self):
        client = make_client('Sam Taylor')
        make_matter('ABC1111111', client)
        other = OthersideDetails.objects.create(name='Sam Taylor')
        other_client = make_client('Unrelated')
        make_matter('ABC2222222', other_client, other_side=other)

        matches = run_conflict_check('Sam Taylor')

        self.assertEqual(len(matches), 2)
        self.assertEqual(matches[0]['source'], SOURCE_OPPOSING)
        self.assertEqual(matches[1]['source'], SOURCE_CLIENT)

    def test_reordered_name_matches(self):
        make_client('Smith, John')
        self.assertEqual(len(run_conflict_check('John Smith')), 1)

    def test_shared_name_part_without_dob_is_flagged(self):
        # A single shared name part and no DOB to disambiguate -> flagged, so
        # nothing slips through.
        make_client('John Smith')
        matches = run_conflict_check('John Brown')
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['match_strength'], 'partial')
        self.assertTrue(matches[0]['is_conflict'])

    def test_shared_name_part_with_different_dob_is_ruled_out(self):
        make_client('John Smith', dob=date(1980, 1, 1))
        matches = run_conflict_check('John Brown', dob=date(1990, 5, 5))
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['dob_status'], 'differs')
        self.assertFalse(matches[0]['is_conflict'])

    def test_shared_name_part_confirmed_by_matching_dob(self):
        make_client('John Smith', dob=date(1980, 1, 1))
        matches = run_conflict_check('John Brown', dob=date(1980, 1, 1))
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['dob_status'], 'match')
        self.assertTrue(matches[0]['is_conflict'])

    def test_full_name_match_with_different_dob_is_ruled_out(self):
        other = OthersideDetails.objects.create(
            name='Jane Doe', dob=date(1975, 3, 3))
        make_matter('ABC1234567', make_client('Client'), other_side=other)
        matches = run_conflict_check('Jane Doe', dob=date(1999, 9, 9))
        self.assertEqual(len(matches), 1)
        self.assertFalse(matches[0]['is_conflict'])

    def test_full_name_match_with_same_dob_is_conflict(self):
        other = OthersideDetails.objects.create(
            name='Jane Doe', dob=date(1975, 3, 3))
        make_matter('ABC1234567', make_client('Client'), other_side=other)
        matches = run_conflict_check('Jane Doe', dob=date(1975, 3, 3))
        self.assertEqual(len(matches), 1)
        self.assertTrue(matches[0]['is_conflict'])
        self.assertEqual(matches[0]['dob_status'], 'match')


class OnboardingConflictCheckTests(TestCase):
    """The conflict-of-interest gate on the onboarding → matter conversion. The
    member lives in a group; converting creates the client record(s) and hands
    off to the open-file form (it does not create the WIP itself — that happens
    when the form is submitted, via link_group_to_matter)."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='fe', email='fe@example.com', first_name='Fee',
            last_name='Earner', password='password', max_holidays_in_year=20)
        self.client.force_login(self.user)
        self.group = OnboardingGroup.objects.create(
            label='Prospect Pat', created_by=self.user)
        self.onboarding = Onboarding.objects.create(
            group=self.group, is_lead=True, client_name='Prospect Pat',
            email='pat@example.com', address_line1='1 Test Street',
            postcode='SS7 1QT', created_by=self.user)

    def _run_check(self):
        return self.client.post(
            reverse('onboarding_run_conflict_check', args=[self.onboarding.id]))

    def _acknowledge(self, note='Different person'):
        return self.client.post(
            reverse('onboarding_acknowledge_conflict', args=[self.onboarding.id]),
            {'conflict_ack_note': note})

    def _convert(self):
        return self.client.post(
            reverse('onboarding_convert_to_matter', args=[self.group.id]))

    def _seed_conflicting_party(self):
        other = OthersideDetails.objects.create(name='Prospect Pat')
        make_matter('ABC1234567', make_client('Someone'), other_side=other)

    def test_run_check_creates_record_linked_to_onboarding(self):
        response = self._run_check()
        self.assertEqual(response.status_code, 302)
        check = self.onboarding.conflict_checks.first()
        self.assertIsNotNone(check)
        self.assertEqual(check.searched_name, 'Prospect Pat')
        self.assertEqual(check.result, ConflictCheck.RESULT_CLEAR)
        self.assertEqual(check.performed_by, self.user)

    def test_run_check_flags_potential_conflict(self):
        self._seed_conflicting_party()
        self._run_check()
        check = self.onboarding.conflict_checks.first()
        self.assertEqual(check.result, ConflictCheck.RESULT_POTENTIAL)
        self.assertEqual(len(check.matches), 1)

    def test_convert_blocked_without_check(self):
        before = ClientContactDetails.objects.count()
        self._convert()
        self.onboarding.refresh_from_db()
        self.assertIsNone(self.onboarding.client_id)
        self.assertEqual(ClientContactDetails.objects.count(), before)

    def test_convert_blocked_when_potential_not_acknowledged(self):
        self._seed_conflicting_party()
        self._run_check()
        before = ClientContactDetails.objects.count()
        self._convert()  # no acknowledgement
        self.onboarding.refresh_from_db()
        self.assertIsNone(self.onboarding.client_id)
        self.assertEqual(ClientContactDetails.objects.count(), before)

    def test_convert_creates_client_and_hands_off_when_clear(self):
        self._run_check()  # clear
        response = self._convert()
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('new_file'), response.url)
        self.onboarding.refresh_from_db()
        self.assertIsNotNone(self.onboarding.client_id)
        check = self.onboarding.conflict_checks.first()
        self.assertEqual(check.client_id, self.onboarding.client_id)

    def test_convert_succeeds_after_acknowledgement(self):
        self._seed_conflicting_party()
        self._run_check()
        self._acknowledge('Different person')
        response = self._convert()
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('new_file'), response.url)
        self.onboarding.refresh_from_db()
        self.assertIsNotNone(self.onboarding.client_id)
        check = self.onboarding.conflict_checks.first()
        self.assertTrue(check.acknowledged)
        self.assertEqual(check.acknowledgement_note, 'Different person')
