"""Tests for the unified onboarding-first new-file flow:
- onboarding is the only front door for opening a file,
- onboarding members can reuse an existing client (no duplicate record),
- the per-invite 'required documents' selection,
- and the Client Care documents surfaced on the matter home page.
"""
from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from users.models import CustomUser

from ..models import (ClientContactDetails, ClientKeyDocument, ConflictCheck,
                      Onboarding, OnboardingGroup, OnboardingItem, WIP)
from ..onboarding_views import (matter_client_care_documents,
                                _valid_on_file_item_types)


def make_user(username='abc'):
    return CustomUser.objects.create_user(
        username=username, email=f'{username}@example.com', first_name='A',
        last_name='B', password='password', max_holidays_in_year=20)


def make_client(name='Jane Doe', **kw):
    defaults = dict(occupation='Retired', address_line1='1 Test Street',
                    address_line2='', county='Essex', postcode='SS7 1QT',
                    email='jane@example.com', contact_number='0123456789')
    defaults.update(kw)
    return ClientContactDetails.objects.create(name=name, **defaults)


ALL_ITEMS = [k for k, _ in OnboardingItem.ITEM_CHOICES]


class OnboardingFirstGuardTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)

    def test_new_file_without_prefill_redirects_to_onboarding(self):
        resp = self.client.get(reverse('new_file'))
        self.assertRedirects(resp, reverse('onboarding_list'))


class RequiredItemTypesTests(TestCase):
    def test_default_is_all_documents(self):
        m = Onboarding.objects.create(client_name='X', email='x@example.com')
        self.assertEqual(m.required_item_types(), ALL_ITEMS)

    def test_explicit_subset_is_kept_in_order(self):
        m = Onboarding.objects.create(
            client_name='X', email='x@example.com',
            required_documents=['pep', 'source_of_funds'])
        self.assertEqual(m.required_item_types(), ['pep', 'source_of_funds'])

    def test_unknown_keys_are_dropped(self):
        m = Onboarding.objects.create(
            client_name='X', email='x@example.com',
            required_documents=['pep', 'made_up'])
        self.assertEqual(m.required_item_types(), ['pep'])


class ClientSearchJsonTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)

    def test_search_matches_by_name(self):
        make_client('Findable Person', email='find@example.com')
        make_client('Someone Else', email='else@example.com')
        resp = self.client.get(reverse('client_search_json'), {'q': 'Findable'})
        self.assertEqual(resp.status_code, 200)
        results = resp.json()['results']
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['name'], 'Findable Person')


class OnboardingStartExistingClientTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)

    def test_existing_client_is_linked_without_duplicate(self):
        existing = make_client('Existing Client')
        before = ClientContactDetails.objects.count()
        resp = self.client.post(reverse('onboarding_start'), {
            'label': 'Case', 'client_name': [''], 'email': [''],
            'existing_client_id': [str(existing.id)], 'send_invite': '1',
        })
        self.assertEqual(resp.status_code, 302)
        # No new client record is created for an existing pick.
        self.assertEqual(ClientContactDetails.objects.count(), before)
        member = Onboarding.objects.get(client=existing)
        self.assertEqual(member.client_id, existing.id)
        self.assertEqual(member.client_name, 'Existing Client')
        # Existing clients ARE invited when 'send' is ticked (docs auto-chosen).
        self.assertIsNotNone(member.invite_sent_at)

    def test_existing_client_with_valid_id_on_file_is_invited_for_only_what_is_needed(self):
        today = timezone.localdate()
        existing = make_client('Repeat Client', email='r@example.com')
        ClientKeyDocument.objects.create(
            client=existing, category='proof_of_id', verified_on=today,
            expiry_date=today + timedelta(days=300))
        resp = self.client.post(reverse('onboarding_start'), {
            'label': 'Case', 'client_name': [''], 'email': [''],
            'existing_client_id': [str(existing.id)], 'send_invite': '1',
        })
        self.assertEqual(resp.status_code, 302)
        member = Onboarding.objects.get(client=existing)
        self.assertIsNotNone(member.invite_sent_at)         # invited
        requested = member.required_item_types()
        self.assertNotIn('proof_id', requested)             # valid on file — skipped
        self.assertIn('source_of_funds', requested)         # still needed
        self.assertIn('terms_of_engagement', requested)

    def test_new_client_row_creates_member_without_client(self):
        resp = self.client.post(reverse('onboarding_start'), {
            'label': '', 'client_name': ['Brand New'],
            'email': ['new@example.com'], 'existing_client_id': [''],
        })
        self.assertEqual(resp.status_code, 302)
        member = Onboarding.objects.get(client_name='Brand New')
        self.assertIsNone(member.client_id)


class ExistingClientConvertTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        self.existing = make_client('Existing Client')
        self.group = OnboardingGroup.objects.create(
            label='Case', created_by=self.user)
        self.member = Onboarding.objects.create(
            group=self.group, client=self.existing, is_lead=True,
            client_name='Existing Client', email='e@example.com',
            address_line1='1 Test Street', postcode='SS7 1QT',
            created_by=self.user)
        ConflictCheck.objects.create(
            searched_name='Existing Client', result=ConflictCheck.RESULT_CLEAR,
            matches=[], onboarding=self.member, performed_by=self.user)

    def _convert(self, submission):
        with mock.patch('backend.onboarding_views.portal.get_submission',
                        return_value=submission):
            return self.client.post(
                reverse('onboarding_convert_to_matter', args=[self.group.id]))

    def test_convert_reuses_existing_client_and_records_declarations(self):
        # Declarations the client provided through the portal are recorded on the
        # existing record — there is no separate acceptance step.
        before = ClientContactDetails.objects.count()
        resp = self._convert({
            'items': {'pep': 'provided', 'source_of_funds': 'provided',
                      'terms_of_engagement': 'provided'},
            'address': {}, 'files': {},
        })
        # Hands off to the open-file form.
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('new_file'), resp.url)
        # No duplicate client created.
        self.assertEqual(ClientContactDetails.objects.count(), before)
        self.member.refresh_from_db()
        self.assertEqual(self.member.client_id, self.existing.id)
        # Fresh declarations recorded on the existing record.
        self.existing.refresh_from_db()
        self.assertTrue(self.existing.pep_signed)
        self.assertTrue(self.existing.source_of_funds_signed)
        self.assertTrue(self.existing.terms_of_engagement_signed)
        # ID/address were not provided, so identity stays as-is.
        self.assertFalse(bool(self.existing.id_verified))

    def test_convert_records_id_verification_on_provision(self):
        # Providing proof of ID (no acceptance click) verifies identity and stamps
        # the AML date.
        resp = self._convert({
            'items': {'proof_id': 'provided'}, 'address': {},
            'files': {'proof_id': {'item_id': 'sp-id-1', 'path': ''}},
        })
        self.assertEqual(resp.status_code, 302)
        self.existing.refresh_from_db()
        self.assertTrue(self.existing.id_verified)
        self.assertIsNotNone(self.existing.date_of_last_aml)

    def test_convert_persists_portal_item_ids_for_client_copy(self):
        # The portal reports a SharePoint item id for the PEP declaration but not
        # for source-of-funds. Convert must snapshot the id onto the row so the
        # matter's Client Care "Client copy" link resolves without a live call.
        resp = self._convert({
            'items': {'pep': 'provided'}, 'address': {},
            'files': {'pep': {'item_id': 'sp-pep-42', 'path': ''}},
        })
        self.assertEqual(resp.status_code, 302)
        pep = OnboardingItem.objects.get(onboarding=self.member, item_type='pep')
        self.assertEqual(pep.sharepoint_item_id, 'sp-pep-42')
        # An item the portal reported no file for gets no row.
        self.assertFalse(OnboardingItem.objects.filter(
            onboarding=self.member, item_type='source_of_funds').exists())


class ClientCareDocumentsTests(TestCase):
    def test_matter_documents_grouped_by_client(self):
        user = make_user()
        client = make_client('Jane Doe')
        matter = WIP.objects.create(
            file_number='ABC1234567', client1=client, funding='PRI')
        group = OnboardingGroup.objects.create(
            label='Case', matter=matter, created_by=user)
        member = Onboarding.objects.create(
            group=group, client=client, client_name='Jane Doe',
            email='j@example.com', created_by=user)
        # proof_id has a client copy (held); pep has an empty row (nothing held).
        OnboardingItem.objects.create(
            onboarding=member, item_type='proof_id', sharepoint_item_id='sp-1')
        OnboardingItem.objects.create(onboarding=member, item_type='pep')

        folders = matter_client_care_documents(matter)

        self.assertEqual(len(folders), 1)
        self.assertEqual(folders[0]['client_name'], 'Jane Doe')
        by_type = {d['item_type']: d for d in folders[0]['documents']}
        # Only documents we actually hold are listed.
        self.assertIn('proof_id', by_type)
        self.assertTrue(by_type['proof_id']['has_client_copy'])
        self.assertNotIn('pep', by_type)

    def test_no_onboarding_returns_empty(self):
        client = make_client('No Onboarding')
        matter = WIP.objects.create(
            file_number='ABC7654321', client1=client, funding='PRI')
        self.assertEqual(matter_client_care_documents(matter), [])

    def test_every_client_is_shown_even_without_held_documents(self):
        # Two clients on the matter: the lead holds a document, the second holds
        # nothing. Both must appear — the lead lists the held document, the second
        # gets an empty folder.
        user = make_user()
        lead = make_client('Lead Client', email='lead@example.com')
        second = make_client('Second Client', email='second@example.com')
        matter = WIP.objects.create(
            file_number='ABC1112223', client1=lead, funding='PRI')
        group = OnboardingGroup.objects.create(
            label='Case', matter=matter, created_by=user)
        lead_member = Onboarding.objects.create(
            group=group, client=lead, is_lead=True, client_name='Lead Client',
            email='lead@example.com', created_by=user)
        second_member = Onboarding.objects.create(
            group=group, client=second, client_name='Second Client',
            email='second@example.com', created_by=user)
        OnboardingItem.objects.create(
            onboarding=lead_member, item_type='proof_id',
            sharepoint_item_id='sp-lead-id')

        folders = matter_client_care_documents(matter)

        names = {f['client_name'] for f in folders}
        self.assertEqual(names, {'Lead Client', 'Second Client'})
        by_name = {f['client_name']: f for f in folders}
        # Only the held document is listed; the second client's folder is empty.
        lead_types = {d['item_type'] for d in by_name['Lead Client']['documents']}
        self.assertEqual(lead_types, {'proof_id'})
        self.assertEqual(by_name['Second Client']['documents'], [])

    def test_convert_snapshots_provided_doc_without_prior_row(self):
        # A document provided through the portal must become a durable row with its
        # client copy at convert time — there is no separate acceptance step.
        user = make_user()
        client = make_client('Portal Client')
        group = OnboardingGroup.objects.create(label='Case', created_by=user)
        member = Onboarding.objects.create(
            group=group, client=client, is_lead=True, client_name='Portal Client',
            email='p@example.com', address_line1='1 Test Street', postcode='SS7 1QT',
            created_by=user)
        ConflictCheck.objects.create(
            searched_name='Portal Client', result=ConflictCheck.RESULT_CLEAR,
            matches=[], onboarding=member, performed_by=user)
        submission = {
            'items': {'proof_id': 'provided'},
            'address': {},
            'files': {'proof_id': {'item_id': 'sp-id-99', 'path': ''}},
        }
        self.client.force_login(user)
        with mock.patch('backend.onboarding_views.portal.get_submission',
                        return_value=submission):
            resp = self.client.post(
                reverse('onboarding_convert_to_matter', args=[group.id]))
        self.assertEqual(resp.status_code, 302)
        row = OnboardingItem.objects.get(onboarding=member, item_type='proof_id')
        self.assertEqual(row.sharepoint_item_id, 'sp-id-99')

    def test_existing_client_valid_id_links_to_record(self):
        # No fresh upload, but a valid proof-of-ID is on file — Client Care lists
        # it, flagged on_file and linked to that client record.
        user = make_user()
        today = timezone.localdate()
        client = make_client('On File Client')
        ClientKeyDocument.objects.create(
            client=client, category='proof_of_id', verified_on=today,
            expiry_date=today + timedelta(days=200))
        matter = WIP.objects.create(
            file_number='ABC5556667', client1=client, funding='PRI')
        group = OnboardingGroup.objects.create(
            label='Case', matter=matter, created_by=user)
        Onboarding.objects.create(
            group=group, client=client, is_lead=True, client_name='On File Client',
            email='o@example.com', created_by=user)

        folders = matter_client_care_documents(matter)

        by_type = {d['item_type']: d for d in folders[0]['documents']}
        self.assertIn('proof_id', by_type)
        self.assertTrue(by_type['proof_id']['on_file'])
        self.assertEqual(by_type['proof_id']['record_client_id'], client.id)
        self.assertFalse(by_type['proof_id']['has_client_copy'])


class ValidOnFileDocsTests(TestCase):
    """Identity docs still valid on file (verified within 12 months, not expired)
    are reused for existing clients rather than re-requested."""

    def setUp(self):
        self.today = timezone.localdate()
        self.rec = make_client('Repeat Client')

    def _keydoc(self, category, verified_days_ago=30, expiry_days_ahead=365):
        return ClientKeyDocument.objects.create(
            client=self.rec, category=category,
            verified_on=self.today - timedelta(days=verified_days_ago),
            expiry_date=self.today + timedelta(days=expiry_days_ahead))

    def test_recent_non_expired_id_is_valid(self):
        self._keydoc('proof_of_id')
        self.assertEqual(_valid_on_file_item_types(self.rec, self.today), {'proof_id'})

    def test_both_identity_docs_valid(self):
        self._keydoc('proof_of_id')
        self._keydoc('proof_of_address')
        self.assertEqual(_valid_on_file_item_types(self.rec, self.today),
                         {'proof_id', 'proof_address'})

    def test_expired_id_is_not_valid(self):
        self._keydoc('proof_of_id', expiry_days_ahead=-1)
        self.assertEqual(_valid_on_file_item_types(self.rec, self.today), set())

    def test_verification_older_than_12_months_is_not_valid(self):
        self._keydoc('proof_of_id', verified_days_ago=400)
        self.assertEqual(_valid_on_file_item_types(self.rec, self.today), set())

    def test_none_client_returns_empty(self):
        self.assertEqual(_valid_on_file_item_types(None, self.today), set())


class ExistingClientDefaultRequestTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)

    def test_valid_id_on_file_is_not_requested_by_default(self):
        today = timezone.localdate()
        existing = make_client('Valid Client')
        ClientKeyDocument.objects.create(
            client=existing, category='proof_of_id', verified_on=today,
            expiry_date=today + timedelta(days=365))
        group = OnboardingGroup.objects.create(label='Case', created_by=self.user)

        resp = self.client.post(
            reverse('onboarding_add_member', args=[group.id]),
            {'existing_client_id': str(existing.id)})

        self.assertEqual(resp.status_code, 302)
        member = Onboarding.objects.get(client=existing)
        # ID is already held and valid — not re-requested; declarations still are.
        self.assertNotIn('proof_id', member.required_documents)
        self.assertIn('source_of_funds', member.required_documents)
        self.assertIn('proof_address', member.required_documents)

    def test_no_docs_on_file_requests_everything(self):
        existing = make_client('Fresh Client')
        group = OnboardingGroup.objects.create(label='Case', created_by=self.user)

        resp = self.client.post(
            reverse('onboarding_add_member', args=[group.id]),
            {'existing_client_id': str(existing.id)})

        self.assertEqual(resp.status_code, 302)
        member = Onboarding.objects.get(client=existing)
        # Nothing valid on file → default (empty) asks for the full set.
        self.assertEqual(member.required_documents, [])
        self.assertIn('proof_id', member.required_item_types())


class OnboardingDocDetailsTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        self.group = OnboardingGroup.objects.create(label='Case', created_by=self.user)
        self.member = Onboarding.objects.create(
            group=self.group, client_name='New Client', email='n@example.com',
            address_line1='1 Test Street', postcode='SS7 1QT', created_by=self.user)

    def test_saving_details_persists_metadata(self):
        resp = self.client.post(
            reverse('onboarding_save_doc_details', args=[self.member.id, 'proof_id']),
            {'document_type': 'Passport', 'document_reference': 'P123',
             'issue_date': '2020-01-01', 'expiry_date': '2030-01-01'})
        self.assertEqual(resp.status_code, 302)
        item = OnboardingItem.objects.get(onboarding=self.member, item_type='proof_id')
        self.assertEqual(item.document_type, 'Passport')
        self.assertEqual(item.document_reference, 'P123')
        self.assertEqual(str(item.expiry_date), '2030-01-01')

    def test_details_rejected_for_non_identity_item(self):
        resp = self.client.post(
            reverse('onboarding_save_doc_details', args=[self.member.id, 'pep']),
            {'document_type': 'X'})
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(OnboardingItem.objects.filter(
            onboarding=self.member, item_type='pep').exists())

    def test_detail_page_renders_metadata_capture_form(self):
        resp = self.client.get(reverse('onboarding_detail', args=[self.group.id]))
        self.assertEqual(resp.status_code, 200)
        # The identity metadata capture form is present for proof of ID.
        self.assertContains(resp, 'doc-meta-{}-proof_id'.format(self.member.id))

    def test_convert_copies_metadata_to_key_document(self):
        expiry = timezone.localdate() + timedelta(days=1000)
        OnboardingItem.objects.create(
            onboarding=self.member, item_type='proof_id',
            document_type='Passport', document_reference='P999', expiry_date=expiry)
        ConflictCheck.objects.create(
            searched_name='New Client', result=ConflictCheck.RESULT_CLEAR,
            matches=[], onboarding=self.member, performed_by=self.user)
        submission = {
            'items': {'proof_id': 'provided'}, 'address': {},
            'files': {'proof_id': {'item_id': 'sp-x', 'path': ''}},
        }
        with mock.patch('backend.onboarding_views.portal.get_submission',
                        return_value=submission):
            resp = self.client.post(
                reverse('onboarding_convert_to_matter', args=[self.group.id]))
        self.assertEqual(resp.status_code, 302)
        self.member.refresh_from_db()
        kd = ClientKeyDocument.objects.get(
            client=self.member.client, category='proof_of_id')
        self.assertEqual(kd.document_type, 'Passport')
        self.assertEqual(kd.document_reference, 'P999')
        self.assertEqual(kd.expiry_date, expiry)
