from datetime import date, timedelta
from decimal import Decimal

from django.contrib.messages import get_messages
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from users.models import CustomUser, Rate

from .. import fee_earners
from ..models import (
    ClientContactDetails,
    FileStatus,
    MatterKeyDate,
    MatterType,
    OngoingMonitoring,
    RiskAssessment,
    WIP,
)
from ..views import _matter_rate_amount, get_index_search_filter, get_user_dashboard_wip_ids
from .tests_ongoing_monitoring_signoff import build_monitoring_post
from .tests_risk_signoff import build_risk_assessment_post

ALIASES = '{"DC": "ND"}'


def make_user(code, first, last, **extra):
    return CustomUser.objects.create_user(
        username=code, email=f'{code.lower()}@example.com', first_name=first,
        last_name=last, password='password', max_holidays_in_year=20, **extra,
    )


def make_matter(file_number, fee_earner, client_name='Test Client'):
    client = ClientContactDetails.objects.create(
        name=client_name, occupation='Retired', address_line1='1 Test Street',
        address_line2='', county='Essex', postcode='SS7 1QT',
        email='test@example.com', contact_number='0123456789',
    )
    matter_type, _ = MatterType.objects.get_or_create(type='Probate')
    file_status, _ = FileStatus.objects.get_or_create(status='Open')
    return WIP.objects.create(
        file_number=file_number, client1=client, matter_description='Test matter',
        matter_type=matter_type, funding='Pvt', fee_earner=fee_earner,
        file_status=file_status,
    )


@override_settings(RESPONSIBLE_FEE_EARNER_ALIASES=ALIASES)
class ResponsibleFeeEarnerTests(TestCase):
    def setUp(self):
        self.nd = make_user('ND', 'Nadia', 'Dunn', is_matter_fee_earner=True)
        self.dc = make_user('DC', 'Debt', 'Collection', is_matter_fee_earner=True)
        self.abc = make_user('ABC', 'Alex', 'Brown', is_matter_fee_earner=True)
        self.staff = make_user('STF', 'Support', 'Staff')
        self.dc_matter = make_matter('DCM0000001', self.dc, 'Debtor Ltd')
        self.nd_matter = make_matter('NDM0000002', self.nd)
        self.abc_matter = make_matter('ABC0000003', self.abc)
        self.unassigned = make_matter('UNA0000004', None)

    def test_alias_parsing_is_tolerant(self):
        self.assertEqual(fee_earners.responsible_aliases(), {'DC': 'ND'})
        with override_settings(RESPONSIBLE_FEE_EARNER_ALIASES='not json'):
            self.assertEqual(fee_earners.responsible_aliases(), {})
            self.assertEqual(self.dc_matter.responsible_fee_earner, self.dc)
        with override_settings(RESPONSIBLE_FEE_EARNER_ALIASES='{"dc": " nd ", "XX": "XX"}'):
            self.assertEqual(fee_earners.responsible_aliases(), {'DC': 'ND'})

    def test_matter_properties_keep_the_raw_fee_earner(self):
        self.assertEqual(self.dc_matter.fee_earner, self.dc)
        self.assertEqual(self.dc_matter.responsible_fee_earner, self.nd)
        self.assertEqual(self.dc_matter.responsible_fee_earner_id, self.nd.id)
        self.assertEqual(self.nd_matter.responsible_fee_earner, self.nd)
        self.assertEqual(self.abc_matter.responsible_fee_earner, self.abc)
        self.assertIsNone(self.unassigned.responsible_fee_earner)

    def test_alias_to_unknown_user_falls_back_to_the_pseudo_user(self):
        with override_settings(RESPONSIBLE_FEE_EARNER_ALIASES='{"DC": "ZZZ"}'):
            self.assertEqual(self.dc_matter.responsible_fee_earner, self.dc)

    def test_responsible_user_ids(self):
        self.assertEqual(fee_earners.responsible_user_ids(self.nd), sorted([self.nd.id, self.dc.id]))
        self.assertEqual(fee_earners.responsible_user_ids(self.abc), [self.abc.id])
        self.assertEqual(fee_earners.responsible_user_ids_for_id(str(self.nd.id)),
                         sorted([self.nd.id, self.dc.id]))
        self.assertEqual(fee_earners.responsible_user_ids_for_id('nope'), [])

    def test_dashboard_files_include_dc_files_for_nd_only(self):
        self.assertIn(self.dc_matter.id, get_user_dashboard_wip_ids(self.nd))
        self.assertIn(self.nd_matter.id, get_user_dashboard_wip_ids(self.nd))
        self.assertNotIn(self.dc_matter.id, get_user_dashboard_wip_ids(self.abc))
        self.client.force_login(self.nd)
        response = self.client.get(reverse('user_dashboard'))
        self.assertContains(response, 'DCM0000001')

    def test_risk_assessment_signoff_on_dc_file_goes_to_nd(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse('add_risk_assessment', args=[self.dc_matter.file_number]),
            build_risk_assessment_post(self.dc_matter.id))
        self.assertEqual(response.status_code, 302)
        flashes = [m.message for m in get_messages(response.wsgi_request)]
        self.assertTrue(any('sent to Nadia Dunn for sign-off' in m for m in flashes), flashes)

        self.client.force_login(self.nd)
        response = self.client.get(reverse('user_dashboard'))
        queue = response.context['risk_assessments_awaiting_signoff']
        self.assertEqual([ra.matter_id for ra in queue], [self.dc_matter.id])
        self.assertTrue(queue[0].yours_to_sign_off)
        self.assertContains(response, 'Yours to sign off')

        self.client.force_login(self.abc)
        response = self.client.get(reverse('user_dashboard'))
        self.assertFalse(response.context['risk_assessments_awaiting_signoff'][0].yours_to_sign_off)
        self.assertNotContains(response, 'Yours to sign off')

    def test_ongoing_monitoring_signoff_on_dc_file_goes_to_nd(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse('add_ongoing_monitoring', args=[self.dc_matter.file_number]),
            build_monitoring_post())
        flashes = [m.message for m in get_messages(response.wsgi_request)]
        self.assertTrue(any('sent to Nadia Dunn for sign-off' in m for m in flashes), flashes)
        monitoring = OngoingMonitoring.objects.get()
        self.assertEqual(monitoring.file_number.fee_earner, self.dc)

        self.client.force_login(self.nd)
        response = self.client.get(reverse('user_dashboard'))
        queue = response.context['ongoing_monitorings_awaiting_signoff']
        self.assertTrue(queue[0].yours_to_sign_off)

    def test_search_dc_finds_dc_files_and_unassigned_finds_files_without_one(self):
        dc_files = WIP.objects.filter(get_index_search_filter('FeeEarner', 'DC', False))
        self.assertEqual(list(dc_files), [self.dc_matter])
        none_files = WIP.objects.filter(get_index_search_filter('FeeEarner', 'Unassigned', False))
        self.assertEqual(list(none_files), [self.unassigned])

    def test_file_reviews_report_groups_dc_files_under_nd(self):
        self.client.force_login(self.nd)
        response = self.client.get(reverse('report_file_reviews_due'))
        self.assertContains(response, 'DCM0000001')
        self.assertContains(response, 'Nadia Dunn')
        self.assertNotContains(response, 'Debt Collection')
        response = self.client.get(reverse('report_file_reviews_due'), {'fee_earner': self.nd.id})
        self.assertContains(response, 'DCM0000001')
        self.assertNotContains(response, 'ABC0000003')

    def test_key_dates_filter_by_nd_includes_dc_files(self):
        soon = timezone.localdate() + timedelta(days=2)
        MatterKeyDate.objects.create(matter=self.dc_matter, date_type='hearing',
                                     title='Debtor hearing', date=soon)
        MatterKeyDate.objects.create(matter=self.abc_matter, date_type='hearing',
                                     title='Alex hearing', date=soon)
        self.client.force_login(self.nd)
        response = self.client.get(reverse('central_key_dates'), {'fee_earner': self.nd.id})
        self.assertContains(response, 'Debtor hearing')
        self.assertNotContains(response, 'Alex hearing')

    def test_costs_fallback_rate_uses_nd(self):
        rate = Rate.objects.create(desc='Partner', hourly_amount=Decimal('250.00'))
        self.nd.hourly_rate = rate
        self.nd.save()
        self.assertEqual(_matter_rate_amount(self.dc_matter), Decimal('250.00'))
        self.assertEqual(_matter_rate_amount(self.abc_matter), Decimal('0'))
        self.assertEqual(_matter_rate_amount(None), Decimal('0'))
