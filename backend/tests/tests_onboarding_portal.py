"""The office side of the portal contract (backend/onboarding_portal.py,
onboarding_storage.py and the invite flow in onboarding_views.py), pinned to the
portal's actual response shapes:

- a submission is normalised into items / files / address / status, with the
  terms-of-engagement "Client copy" taken from ``acceptance_item_id``;
- a portal refusal surfaces the portal's own ``detail`` text;
- the folder-listing fallback matches the portal's real filename prefixes;
- an invite is delivered then the live link is dropped, a resend expires the
  previous link first, and a persisted SharePoint id still counts as provided.
"""
from unittest import mock

import requests
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from users.models import CustomUser

from .. import onboarding_email as invite_email
from .. import onboarding_portal as portal
from .. import onboarding_storage as storage
from ..models import Onboarding, OnboardingGroup, OnboardingItem
from ..onboarding_views import _member_progress


def _response(status_code, body=None, text=''):
    resp = requests.Response()
    resp.status_code = status_code
    resp.reason = 'Unprocessable Entity' if status_code == 422 else 'Error'
    if body is not None:
        import json
        text = json.dumps(body)
    resp._content = text.encode()
    return resp


class NormaliseSubmissionTests(SimpleTestCase):
    """``_normalise_submission`` against the shape of the portal's SubmissionOut."""

    def test_documents_and_declarations(self):
        out = portal._normalise_submission({
            'status': 'in_progress',
            'documents': [
                {'type': 'proof_id', 'scan_state': 'clean',
                 'sharepoint_item_id': 'sp-id', 'sharepoint_path': 'p/proof_id-1'},
                {'type': 'proof_address', 'scan_state': 'quarantined',
                 'sharepoint_item_id': None, 'sharepoint_path': None},
            ],
            'declarations': [
                {'type': 'pep', 'pdf_item_id': 'sp-pep'},
                {'type': 'source_of_funds', 'pdf_item_id': None},
            ],
            'terms': None,
            'address': None,
        })
        self.assertEqual(out['items'], {
            'proof_id': 'provided', 'proof_address': 'awaited',
            'pep': 'provided', 'source_of_funds': 'awaited'})
        self.assertEqual(out['files']['proof_id'], {'item_id': 'sp-id', 'path': 'p/proof_id-1'})
        self.assertEqual(out['files']['pep'], {'item_id': 'sp-pep', 'path': ''})
        self.assertNotIn('source_of_funds', out['files'])
        self.assertEqual(out['status'], 'in_progress')
        self.assertEqual(out['address'], {})

    def test_terms_on_screen_uses_acceptance_certificate(self):
        out = portal._normalise_submission({'terms': {
            'id': 1, 'method': 'on_screen', 'agreed_at': '2026-10-05T10:00:00Z',
            'acceptance_item_id': 'sp-cert', 'signature_item_id': 'sp-sig',
            'signed_doc_item_id': None, 'terms_item_id': 'sp-terms',
        }})
        self.assertEqual(out['items']['terms_of_engagement'], 'provided')
        self.assertEqual(out['files']['terms_of_engagement'], {'item_id': 'sp-cert', 'path': ''})

    def test_terms_wet_ink_prefers_certificate_then_signed_scan(self):
        out = portal._normalise_submission({'terms': {
            'method': 'wet_ink', 'agreed_at': '2026-10-05T10:00:00Z',
            'acceptance_item_id': 'sp-cert', 'signed_doc_item_id': 'sp-scan',
        }})
        self.assertEqual(out['files']['terms_of_engagement']['item_id'], 'sp-cert')
        out = portal._normalise_submission({'terms': {
            'method': 'wet_ink', 'agreed_at': '2026-10-05T10:00:00Z',
            'acceptance_item_id': None, 'signed_doc_item_id': 'sp-scan',
        }})
        self.assertEqual(out['files']['terms_of_engagement']['item_id'], 'sp-scan')

    def test_capacity_passes_through(self):
        out = portal._normalise_submission({'capacity': {
            'acting_for': 'company', 'company_name': 'Acme Ltd',
            'company_number': '01234567', 'signatory_role': 'director'}})
        self.assertEqual(out['capacity']['company_name'], 'Acme Ltd')
        self.assertEqual(portal._normalise_submission({})['capacity'], {})

    def test_address_passes_through_under_client_record_field_names(self):
        out = portal._normalise_submission({'address': {
            'address_line1': '12 Acacia Avenue', 'address_line2': '',
            'county': 'Essex', 'postcode': 'SS7 1QT',
            'recorded_at': '2026-10-05T10:00:00Z'}})
        self.assertEqual(out['address']['address_line1'], '12 Acacia Avenue')
        self.assertEqual(out['address']['postcode'], 'SS7 1QT')


class PortalErrorDetailTests(SimpleTestCase):
    def test_422_validation_list_is_flattened(self):
        resp = _response(422, {'detail': [
            {'loc': ['body', 'email'], 'msg': 'value is not a valid email address',
             'type': 'value_error'},
            {'loc': ['body', 'client_ref'],
             'msg': "Value error, Invalid client_ref: 1-128 chars", 'type': 'value_error'},
        ]})
        err = portal._portal_error(requests.HTTPError(response=resp))
        self.assertEqual(
            str(err),
            '422 email: value is not a valid email address; '
            'client_ref: Invalid client_ref: 1-128 chars')

    def test_string_detail_and_plain_text_bodies(self):
        err = portal._portal_error(
            requests.HTTPError(response=_response(401, {'detail': 'Invalid internal API key'})))
        self.assertEqual(str(err), '401 Invalid internal API key')
        err = portal._portal_error(
            requests.HTTPError(response=_response(403, text='Forbidden by Caddy')))
        self.assertEqual(str(err), '403 Forbidden by Caddy')

    def test_transport_error_without_response(self):
        err = portal._portal_error(requests.ConnectionError('boom'))
        self.assertEqual(str(err), 'boom')


class StoragePrefixTests(SimpleTestCase):
    def test_prefixes_match_portal_filenames(self):
        self.assertEqual(storage._prefixes_for('proof_id'), ('proof_id-',))
        self.assertEqual(storage._prefixes_for('pep'), ('declaration-pep-',))
        self.assertIn('terms-acceptance-', storage._prefixes_for('terms_of_engagement'))

    @mock.patch.object(storage, '_token', return_value='tok')
    @mock.patch.object(storage, 'is_configured', return_value=True)
    @mock.patch.object(storage, '_drive_id', return_value='drive')
    def test_listing_fallback_finds_declaration_pdf(self, *_):
        listing = _response(200, {'value': [
            {'id': 'a', 'name': 'proof_id-3.pdf'},
            {'id': 'b', 'name': 'declaration-pep-7.pdf'},
        ]})
        download = _response(200, text='%PDF-1.7')
        download.headers['Content-Type'] = 'application/pdf'
        member = mock.Mock(client_ref='ONB-1', portal_submission_id='9')
        with mock.patch.object(storage.requests, 'get', side_effect=[listing, download]):
            content, content_type, name = storage.read_document(member, 'pep')
        self.assertEqual(name, 'declaration-pep-7.pdf')
        self.assertEqual(content, b'%PDF-1.7')


def make_user(username='abc'):
    return CustomUser.objects.create_user(
        username=username, email=f'{username}@example.com', first_name='A',
        last_name='B', password='password', max_holidays_in_year=20)


INVITE = {'invite_id': 11, 'submission_id': 12,
          'expires_at': '2026-10-12T10:00:00Z',
          'redeem_url': 'https://portal.example/redeem?token=secret'}


class InviteFlowTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        self.group = OnboardingGroup.objects.create(label='Case', created_by=self.user)
        self.member = Onboarding.objects.create(
            group=self.group, client_name='Jane', email='jane@example.com',
            created_by=self.user)

    def _send(self, email_sent=True):
        with mock.patch('backend.onboarding_views.portal.is_mock', return_value=False), \
             mock.patch('backend.onboarding_views.portal.create_invite', return_value=INVITE), \
             mock.patch('backend.onboarding_views.portal.expire_invite') as expire, \
             mock.patch('backend.onboarding_views.email.send_invite_email',
                        return_value=email_sent) as send:
            resp = self.client.post(reverse('onboarding_send_invite', args=[self.member.id]))
        self.assertEqual(resp.status_code, 302)
        self.member.refresh_from_db()
        return send, expire

    def test_ids_recorded_and_link_dropped_once_emailed(self):
        send, expire = self._send(email_sent=True)
        # The email lists what this invite asks for and how long the link lasts.
        send.assert_called_once_with(
            'Jane', 'jane@example.com', INVITE['redeem_url'],
            required_items=['proof_id', 'proof_address', 'selfie_id',
                            'source_of_funds', 'pep', 'terms_of_engagement'],
            expires_at=INVITE['expires_at'])
        self.assertEqual(self.member.portal_submission_id, '12')
        self.assertEqual(self.member.portal_invite_id, '11')
        self.assertEqual(self.member.portal_invite_link, '')
        self.assertIsNotNone(self.member.invite_sent_at)
        expire.assert_not_called()  # nothing to expire on a first send

    def test_link_kept_when_email_not_sent(self):
        self._send(email_sent=False)
        self.assertEqual(self.member.portal_invite_link, INVITE['redeem_url'])

    def test_resend_expires_previous_live_link_first(self):
        self.member.portal_invite_id = '5'
        self.member.invite_sent_at = timezone.now()
        self.member.save()
        _, expire = self._send()
        expire.assert_called_once()
        self.assertEqual(self.member.portal_invite_id, '11')

    def test_resend_after_expiry_does_not_expire_again(self):
        self.member.portal_invite_id = '5'
        self.member.invite_sent_at = timezone.now()
        self.member.invite_expired_at = timezone.now()
        self.member.save()
        _, expire = self._send()
        expire.assert_not_called()
        self.assertIsNone(self.member.invite_expired_at)


class MemberProgressTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.group = OnboardingGroup.objects.create(label='Case', created_by=self.user)
        self.member = Onboarding.objects.create(
            group=self.group, client_name='Jane', email='jane@example.com',
            portal_submission_id='12', created_by=self.user)

    def test_persisted_item_id_counts_as_provided_and_status_is_surfaced(self):
        OnboardingItem.objects.create(
            onboarding=self.member, item_type='proof_id', sharepoint_item_id='sp-old')
        fresh = {'items': {'proof_id': 'awaited'}, 'files': {}, 'address': {},
                 'status': 'submitted'}
        with mock.patch('backend.onboarding_views.portal.get_submission', return_value=fresh), \
             mock.patch('backend.onboarding_views.portal.is_mock', return_value=False):
            items, flags = _member_progress(self.member)
        by_key = {i['key']: i for i in items}
        self.assertTrue(by_key['proof_id']['provided'])
        self.assertTrue(by_key['proof_id']['portal_provided'])
        self.assertEqual(flags['portal_status'], 'submitted')

    def test_portal_address_prefills_empty_fields_only(self):
        self.member.county = 'Kent'
        self.member.save()
        sub = {'items': {}, 'files': {}, 'status': 'in_progress',
               'address': {'address_line1': '12 Acacia Avenue', 'address_line2': '',
                           'county': 'Essex', 'postcode': 'SS7 1QT'}}
        with mock.patch('backend.onboarding_views.portal.get_submission', return_value=sub), \
             mock.patch('backend.onboarding_views.portal.is_mock', return_value=False):
            _member_progress(self.member)
        self.member.refresh_from_db()
        self.assertEqual(self.member.address_line1, '12 Acacia Avenue')
        self.assertEqual(self.member.postcode, 'SS7 1QT')
        self.assertEqual(self.member.county, 'Kent')  # staff value not overwritten


class DetailPageRenderTests(TestCase):
    """The case page renders the portal status and explains the absent link."""

    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        self.group = OnboardingGroup.objects.create(label='Case', created_by=self.user)
        self.member = Onboarding.objects.create(
            group=self.group, client_name='Jane', email='jane@example.com',
            portal_submission_id='12', portal_invite_id='11',
            invite_sent_at=timezone.now(), created_by=self.user)

    def test_submitted_tag_and_link_note(self):
        sub = {'items': {}, 'files': {}, 'address': {}, 'status': 'submitted'}
        with mock.patch('backend.onboarding_views.portal.get_submission', return_value=sub), \
             mock.patch('backend.onboarding_views.portal.is_mock', return_value=False):
            resp = self.client.get(reverse('onboarding_detail', args=[self.group.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'submitted by client')
        self.assertContains(resp, 'link not kept here')
        self.assertNotContains(resp, 'redeem?token=')

    def test_company_capacity_is_shown_to_staff(self):
        sub = {'items': {}, 'files': {}, 'address': {}, 'status': 'in_progress',
               'capacity': {'acting_for': 'company', 'company_name': 'Acme Ltd',
                            'company_number': '01234567', 'signatory_role': 'director'}}
        with mock.patch('backend.onboarding_views.portal.get_submission', return_value=sub), \
             mock.patch('backend.onboarding_views.portal.is_mock', return_value=False):
            resp = self.client.get(reverse('onboarding_detail', args=[self.group.id]))
        self.assertContains(resp, 'Completing on behalf of')
        self.assertContains(resp, 'Acme Ltd')
        self.assertContains(resp, 'company no. 01234567')

    def test_link_shown_while_still_to_be_delivered(self):
        self.member.portal_invite_link = 'https://portal.example/redeem?token=abc'
        self.member.save()
        sub = {'items': {}, 'files': {}, 'address': {}, 'status': 'invited'}
        with mock.patch('backend.onboarding_views.portal.get_submission', return_value=sub), \
             mock.patch('backend.onboarding_views.portal.is_mock', return_value=False):
            resp = self.client.get(reverse('onboarding_detail', args=[self.group.id]))
        self.assertContains(resp, 'https://portal.example/redeem?token=abc')
        self.assertNotContains(resp, 'link not kept here')
        self.assertNotContains(resp, 'submitted by client')


class InviteEmailGuardTests(SimpleTestCase):
    """Outbound invite email is opt-in: nothing is sent unless
    ONBOARDING_SEND_INVITE_EMAILS is on, whatever credentials are configured."""

    CONFIGURED = dict(ONBOARDING_MAIL_CLIENT_ID='id', ONBOARDING_MAIL_CLIENT_SECRET='s',
                      ONBOARDING_MAIL_TENANT_ID='t', ONBOARDING_INVITE_FROM='mail@example.com')

    @override_settings(ONBOARDING_SEND_INVITE_EMAILS=False, **CONFIGURED)
    def test_off_by_default_even_when_configured(self):
        with mock.patch('backend.onboarding_email.requests.post') as post, \
             mock.patch('backend.onboarding_email._token') as token:
            sent = invite_email.send_invite_email('Jane', 'jane@example.com', 'https://x')
        self.assertFalse(sent)
        post.assert_not_called()
        token.assert_not_called()

    @override_settings(ONBOARDING_SEND_INVITE_EMAILS=True, **CONFIGURED)
    def test_sends_when_switched_on(self):
        with mock.patch('backend.onboarding_email.requests.post') as post, \
             mock.patch('backend.onboarding_email._token', return_value='tok'):
            post.return_value.raise_for_status.return_value = None
            sent = invite_email.send_invite_email('Jane', 'jane@example.com', 'https://x')
        self.assertTrue(sent)
        post.assert_called_once()
        self.assertEqual(post.call_args.kwargs['json']['message']['toRecipients'],
                         [{'emailAddress': {'address': 'jane@example.com'}}])

    def test_test_runner_forces_the_flag_off(self):
        from django.conf import settings
        self.assertFalse(settings.ONBOARDING_SEND_INVITE_EMAILS)


class InviteEmailContentTests(SimpleTestCase):
    """The invite email tells the client what the portal will ask for — only the
    items this invite requires, in the portal's own words — and how long the
    link lasts."""

    def test_lists_only_the_items_this_invite_requires(self):
        html = invite_email._html_body(
            'Jane', 'https://x', ['source_of_funds', 'pep', 'terms_of_engagement'],
            '2026-10-21T10:00:00Z')
        self.assertIn('What we will ask you for', html)
        self.assertIn('Source of funds declaration', html)
        self.assertIn('Politically exposed persons declaration', html)
        self.assertIn('Terms of engagement', html)
        self.assertNotIn('Photo ID', html)
        self.assertNotIn('proof of address', html)
        self.assertIn('until 21 October 2026', html)
        self.assertIn('camera', html)  # terms are signed with a photo of you holding your ID
        self.assertIn('for a company', html)
        self.assertIn('https://x', html)

    def test_everything_when_no_subset_and_selfie_folds_into_terms(self):
        titles = [t for t, _ in invite_email.required_item_lines(None)]
        self.assertEqual(titles, ['Photo ID', 'Current address and proof of address',
                                  'Source of funds declaration',
                                  'Politically exposed persons declaration',
                                  'Terms of engagement'])
        # Selfie on its own (terms not requested) gets its own line.
        titles = [t for t, _ in invite_email.required_item_lines(['selfie_id', 'proof_id'])]
        self.assertEqual(titles, ['Photo ID', 'A photo of you holding your ID'])
        self.assertEqual(invite_email.required_item_lines(['bogus']), [])

    def test_escapes_the_client_name_and_tolerates_a_bad_expiry(self):
        html = invite_email._html_body('Jane <Doe>', 'https://x', ['proof_id'], 'not-a-date')
        self.assertIn('Dear Jane &lt;Doe&gt;,', html)
        self.assertNotIn('until', html)
        self.assertNotIn('camera', html)
