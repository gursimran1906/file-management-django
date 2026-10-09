from datetime import timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from users.models import CustomUser

from ..models import Modifications, OngoingMonitoring, RiskAssessment
from ..signoff_digest import build_digests, render_digest_html, send_signoff_digests
from ..signoff_queue import TYPE_MONITORING, TYPE_RISK, build_queue, pending_count
from .tests_compliance_stats import make_user
from .tests_ongoing_monitoring_signoff import make_monitoring
from .tests_report_pages import make_client, make_live_matter
from .tests_risk_signoff import make_risk_assessment

FETCH = {'HTTP_X_REQUESTED_WITH': 'fetch', 'HTTP_ACCEPT': 'application/json'}


class QueueBuildTests(TestCase):
    def setUp(self):
        self.ann = make_user('AAA', 'Ann', 'Able')
        self.bob = make_user('BBB', 'Bob', 'Baker')
        self.staff = make_user('STF', 'Sam', 'Staff', is_matter_fee_earner=False)
        self.anns = make_live_matter('Q0001', make_client('Ann Client'), self.ann)
        self.bobs = make_live_matter('Q0002', make_client('Bob Client'), self.bob)
        self.ra_ann = make_risk_assessment(self.anns, completed_by=self.staff)
        self.om_bob = make_monitoring(self.bobs, completed_by=self.staff)
        make_risk_assessment(self.bobs, signoff_status=RiskAssessment.SIGNOFF_SIGNED)

    def test_yours_first_then_newest(self):
        items = build_queue(self.bob)
        self.assertEqual([(i.type, i.yours) for i in items],
                         [(TYPE_MONITORING, True), (TYPE_RISK, False)])
        self.assertTrue(items[0].record.yours_to_sign_off)
        self.assertFalse(items[1].record.yours_to_sign_off)

    def test_kind_filter_and_counts(self):
        self.assertEqual([i.type for i in build_queue(kind=TYPE_RISK)], [TYPE_RISK])
        self.assertEqual(pending_count(), 2)
        self.assertEqual(pending_count(self.ann), 1)
        self.assertEqual(pending_count(self.staff), 0)

    def test_returned_records_stay_in_the_queue(self):
        self.ra_ann.signoff_status = RiskAssessment.SIGNOFF_RETURNED
        self.ra_ann.signoff_comments = 'Check the source of funds.'
        self.ra_ann.save()
        item = next(i for i in build_queue(self.ann) if i.type == TYPE_RISK)
        self.assertTrue(item.is_returned)
        self.assertEqual(item.status_label, 'Returned for changes')

    @override_settings(RESPONSIBLE_FEE_EARNER_ALIASES='{"DC": "ND"}')
    def test_dc_files_queue_for_nd(self):
        dc = make_user('DC', 'Debt', 'Collection')
        nd = make_user('ND', 'Nadia', 'Dunn')
        make_risk_assessment(make_live_matter('Q0003', make_client('Debtor'), dc))
        self.assertTrue(next(i for i in build_queue(nd) if i.matter.file_number == 'Q0003').yours)
        self.assertEqual(pending_count(nd), 1)

    def test_item_urls(self):
        item = build_queue(kind=TYPE_RISK)[0]
        self.assertEqual(item.sign_off_url, reverse('sign_off_risk_assessment', args=[self.ra_ann.id]))
        self.assertEqual(item.return_url, reverse('return_risk_assessment', args=[self.ra_ann.id]))
        self.assertEqual(item.edit_url, reverse('edit_risk_assessment', args=[self.ra_ann.id]))
        self.assertEqual(item.home_url, reverse('home', args=['Q0001']))


class QueuePageTests(TestCase):
    def setUp(self):
        self.fe = make_user('AAA', 'Ann', 'Able')
        self.staff = make_user('STF', 'Sam', 'Staff', is_matter_fee_earner=False)
        self.matter = make_live_matter('Q0001', make_client('Queue Client'), self.fe)
        self.ra = make_risk_assessment(self.matter, completed_by=self.staff, adverse_media='Yes')
        self.om = make_monitoring(self.matter, completed_by=self.staff, any_changes_discovered='Yes')
        self.url = reverse('signoff_queue')

    def test_requires_login(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)

    def test_fee_earner_sees_items_flags_and_buttons(self):
        self.client.force_login(self.fe)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Q0001')
        self.assertContains(resp, 'Yours to sign off')
        self.assertContains(resp, 'Adverse media about client or beneficial owners')
        self.assertContains(resp, 'Changes discovered since the risk assessment')
        self.assertContains(resp, reverse('sign_off_risk_assessment', args=[self.ra.id]))
        self.assertContains(resp, reverse('return_ongoing_monitoring', args=[self.om.id]))
        self.assertContains(resp, '>Sign off</button>', count=2)
        self.assertEqual(resp.context['yours_count'], 2)

    def test_type_filter(self):
        self.client.force_login(self.fe)
        resp = self.client.get(self.url, {'type': 'ongoing_monitoring'})
        self.assertEqual([i.type for i in resp.context['items']], [TYPE_MONITORING])
        resp = self.client.get(self.url, {'type': 'bogus'})
        self.assertEqual(len(resp.context['items']), 2)

    def test_staff_see_the_list_without_buttons(self):
        self.client.force_login(self.staff)
        resp = self.client.get(self.url)
        self.assertContains(resp, 'Q0001')
        self.assertNotContains(resp, '>Sign off</button>')
        self.assertContains(resp, 'Only fee earners can sign off')

    def test_navbar_badge_and_hub_card(self):
        self.client.force_login(self.fe)
        resp = self.client.get(reverse('reports_hub'))
        self.assertEqual(resp.context['signoff_pending_count'], 2)
        self.assertContains(resp, 'Awaiting your sign-off')
        self.assertContains(resp, 'Sign-off queue')
        self.assertContains(resp, self.url)
        self.client.force_login(self.staff)
        resp = self.client.get(reverse('reports_hub'))
        self.assertEqual(resp.context['signoff_pending_count'], 0)
        self.assertNotContains(resp, 'Awaiting your sign-off')

    def test_dashboard_links_to_the_queue(self):
        self.client.force_login(self.fe)
        resp = self.client.get(reverse('user_dashboard'))
        self.assertContains(resp, f'{self.url}?type=risk_assessment')
        self.assertContains(resp, 'Yours to sign off')


class SignoffJsonTests(TestCase):
    def setUp(self):
        self.fe = make_user('AAA', 'Ann', 'Able')
        self.staff = make_user('STF', 'Sam', 'Staff', is_matter_fee_earner=False)
        self.matter = make_live_matter('J0001', make_client('Json Client'), self.fe)
        self.ra = make_risk_assessment(self.matter, completed_by=self.staff)
        self.om = make_monitoring(self.matter, completed_by=self.staff)

    def test_sign_off_answers_json_to_fetch(self):
        self.client.force_login(self.fe)
        resp = self.client.post(reverse('sign_off_risk_assessment', args=[self.ra.id]), **FETCH)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual((data['ok'], data['status'], data['status_label']),
                         (True, 'signed', 'Signed off'))
        self.ra.refresh_from_db()
        self.assertTrue(self.ra.is_signed_off)
        self.assertEqual(self.ra.signed_off_by, self.fe)
        self.assertEqual(Modifications.objects.filter(object_id=self.ra.id).count(), 1)
        # Doing it again is a conflict, not a silent success.
        resp = self.client.post(reverse('sign_off_risk_assessment', args=[self.ra.id]), **FETCH)
        self.assertEqual(resp.status_code, 409)
        self.assertFalse(resp.json()['ok'])

    def test_return_with_comments_answers_json(self):
        self.client.force_login(self.fe)
        url = reverse('return_ongoing_monitoring', args=[self.om.id])
        resp = self.client.post(url, {'comments': ''}, **FETCH)
        self.assertEqual(resp.status_code, 400)
        resp = self.client.post(url, {'comments': 'Say how it was monitored.'}, **FETCH)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['status'], 'returned')
        self.om.refresh_from_db()
        self.assertEqual(self.om.signoff_status, OngoingMonitoring.SIGNOFF_RETURNED)
        self.assertEqual(self.om.signoff_comments, 'Say how it was monitored.')

    def test_non_fee_earner_gets_403_json(self):
        self.client.force_login(self.staff)
        resp = self.client.post(reverse('sign_off_ongoing_monitoring', args=[self.om.id]), **FETCH)
        self.assertEqual(resp.status_code, 403)
        self.om.refresh_from_db()
        self.assertFalse(self.om.is_signed_off)

    def test_plain_post_still_redirects_with_a_message(self):
        self.client.force_login(self.fe)
        resp = self.client.post(reverse('sign_off_ongoing_monitoring', args=[self.om.id]), follow=True)
        self.assertRedirects(resp, reverse('home', args=['J0001']))
        self.assertContains(resp, 'Ongoing monitoring signed off.')


class DigestTests(TestCase):
    def setUp(self):
        self.ann = make_user('AAA', 'Ann', 'Able')
        self.bob = make_user('BBB', 'Bob', 'Baker')
        self.staff = make_user('STF', 'Sam', 'Staff', is_matter_fee_earner=False)
        self.anns = make_live_matter('G0001', make_client('Digest Client'), self.ann)
        self.ra = make_risk_assessment(self.anns, completed_by=self.staff, adverse_media='Yes')
        make_live_matter('G0002', make_client('Quiet Client'), self.bob)

    def test_only_fee_earners_with_items_get_a_digest(self):
        digests = build_digests()
        self.assertEqual([u.username for u in digests], ['AAA'])
        self.assertEqual([i.matter.file_number for i in digests[self.ann]], ['G0001'])

    def test_inactive_or_emailless_fee_earners_are_skipped(self):
        self.ann.email = ''
        self.ann.save()
        self.assertEqual(build_digests(), {})

    def test_html_lists_items_and_links_to_the_queue(self):
        html = render_digest_html(self.ann, build_queue(self.ann), base_url='https://wip.example.com')
        self.assertIn('Good morning Ann', html)
        self.assertIn('G0001', html)
        self.assertIn('answers flagged', html)
        self.assertIn('Sam Staff', html)
        self.assertIn('https://wip.example.com' + reverse('signoff_queue'), html)
        self.assertIn('https://wip.example.com' + reverse('home', args=['G0001']), html)

    def test_nothing_is_sent_unless_switched_on(self):
        with mock.patch('backend.signoff_digest.graph_mail.send_html_email') as send:
            summary = send_signoff_digests()
        send.assert_not_called()
        self.assertEqual(summary, {'sent': 0, 'skipped': 1, 'recipients': ['AAA']})

    def test_sends_one_email_per_fee_earner_when_on(self):
        with mock.patch('backend.signoff_digest.graph_mail.send_html_email', return_value=True) as send:
            summary = send_signoff_digests(send=True)
        send.assert_called_once()
        subject, to_email, html = send.call_args.args
        self.assertEqual((subject, to_email), ('Awaiting your sign-off (1)', 'aaa@example.com'))
        self.assertIn('G0001', html)
        self.assertEqual((summary['sent'], summary['skipped']), (1, 0))

    def test_a_failed_send_does_not_stop_the_others(self):
        make_risk_assessment(make_live_matter('G0003', make_client('Third'), self.bob), completed_by=self.staff)
        with mock.patch('backend.signoff_digest.graph_mail.send_html_email',
                        side_effect=[RuntimeError('graph down'), True]):
            summary = send_signoff_digests(send=True)
        self.assertEqual((summary['sent'], summary['skipped']), (1, 1))
