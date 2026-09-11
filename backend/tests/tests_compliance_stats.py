from datetime import date, timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from users.models import CustomUser

from ..compliance_stats import (
    GREEN,
    METRICS,
    RED,
    Snapshot,
    build_compliance_stats,
    build_metric_detail,
    donut_segments,
)
from ..models import (
    WIP,
    AuthorisedParties,
    ClientKeyDocument,
    FileStatus,
    MatterFileReview,
    OngoingMonitoring,
    PmtsSlips,
    RiskAssessment,
    Undertaking,
)
from .tests_ongoing_monitoring_signoff import make_monitoring
from .tests_report_pages import make_client, make_live_matter
from .tests_risk_signoff import make_risk_assessment

ALIASES = '{"DC": "ND"}'


def make_user(code, first='Fee', last='Earner', **extra):
    extra.setdefault('is_matter_fee_earner', True)
    return CustomUser.objects.create_user(
        username=code, email=f'{code.lower()}@example.com', first_name=first,
        last_name=last, password='password', max_holidays_in_year=20, **extra,
    )


def make_party(name='Pat Attorney', **overrides):
    defaults = dict(
        name=name, relationship_to_client='Attorney', address_line1='2 St',
        address_line2='', county='Essex', postcode='SS7 1QT',
        email='p@example.com', contact_number='0123456789',
    )
    defaults.update(overrides)
    return AuthorisedParties.objects.create(**defaults)


def make_slip(matter, amount, *, money_out=False, ledger='C', when=None):
    return PmtsSlips.objects.create(
        file_number=matter, ledger_account=ledger, mode_of_pmt='BT',
        amount=Decimal(amount), is_money_out=money_out, pmt_person='Someone',
        description='Slip', date=when or timezone.localdate(),
        balance_left=Decimal('0.00'),
    )


def make_undertaking(matter, discharged=None):
    return Undertaking.objects.create(
        file_number=matter, date_given=date(2026, 1, 5), given_to='Other side',
        description='To pay the balance', date_discharged=discharged,
    )


def metric_ctx(stats, key):
    for group in stats['groups']:
        for metric in group['metrics']:
            if metric['key'] == key:
                return metric
    raise KeyError(key)


def group_ctx(stats, key):
    return next(g for g in stats['groups'] if g['key'] == key)


def row_cell(stats, group_key, code, metric_key):
    for row in group_ctx(stats, group_key)['fee_earner_rows']:
        if row['code'] == code:
            return next(c for c in row['cells'] if c['metric_key'] == metric_key)
    raise KeyError((code, metric_key))


def not_done_rows(metric_key, **kwargs):
    _, rows, _ = build_metric_detail(METRICS[metric_key], **kwargs)
    return rows


class DonutHelperTests(SimpleTestCase):
    def test_first_segment_starts_at_twelve_oclock(self):
        ring = donut_segments(3, 1)
        self.assertFalse(ring['na'])
        done, not_done = ring['segments']
        self.assertEqual(done['offset'], 125.0)
        self.assertEqual(done['dash'], 75.0)
        self.assertEqual(done['gap'], 25.0)

    def test_second_segment_starts_where_first_ended(self):
        done, not_done = donut_segments(1, 2)['segments']
        self.assertAlmostEqual(not_done['offset'], 125 - done['pct'], places=1)

    def test_display_percentages_sum_to_100_and_floor_done(self):
        ring = donut_segments(199, 1)
        done, not_done = ring['segments']
        self.assertEqual(ring['pct'], 99)   # never 100% while something is outstanding
        self.assertEqual(done['pct_display'] + not_done['pct_display'], 100)
        self.assertEqual(donut_segments(5, 0)['pct'], 100)

    def test_zero_total_is_na(self):
        ring = donut_segments(0, 0)
        self.assertTrue(ring['na'])
        self.assertIsNone(ring['pct'])
        self.assertEqual(ring['segments'], [])

    def test_colours(self):
        done, not_done = donut_segments(1, 1)['segments']
        self.assertEqual((done['color'], not_done['color']), (GREEN, RED))


class ComplianceSnapshotTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.fe = make_user('AAA', 'Ann', 'Able')

    def test_live_rule_includes_to_be_closed_and_excludes_archived(self):
        make_live_matter('L0001', make_client('One'), self.fe, status='Open')
        make_live_matter('L0002', make_client('Two'), self.fe, status='To Be Closed')
        make_live_matter('L0003', make_client('Three'), self.fe, status='Archived')
        stats = build_compliance_stats()
        self.assertEqual(stats['live_matter_count'], 2)
        self.assertEqual(stats['archived_matter_count'], 1)
        self.assertEqual(metric_ctx(stats, 'client_care_sent')['total'], 2)
        self.assertEqual(metric_ctx(stats, 'closed_no_open_undertakings')['total'], 1)

    def test_risk_assessment_signed_awaiting_none(self):
        signed = make_live_matter('R0001', make_client('S'), self.fe)
        awaiting = make_live_matter('R0002', make_client('A'), self.fe)
        make_live_matter('R0003', make_client('N'), self.fe)
        make_risk_assessment(signed, signoff_status=RiskAssessment.SIGNOFF_SIGNED)
        make_risk_assessment(awaiting)
        stats = build_compliance_stats()
        ra = metric_ctx(stats, 'risk_assessment')
        self.assertEqual((ra['done'], ra['not_done'], ra['pct']), (1, 2, 33))
        self.assertEqual({r['key']: r['count'] for r in ra['reasons']}, {'awaiting': 1, 'none': 1})
        rows = not_done_rows('risk_assessment', reason='none')
        self.assertEqual([r['cells']['file_number']['value'] for r in rows], ['R0003'])

    def test_latest_assessment_wins(self):
        matter = make_live_matter('R0010', make_client('Late'), self.fe)
        make_risk_assessment(matter, due_diligence_date=date(2025, 1, 1),
                             signoff_status=RiskAssessment.SIGNOFF_SIGNED)
        make_risk_assessment(matter, due_diligence_date=date(2026, 6, 1))
        self.assertEqual(metric_ctx(build_compliance_stats(), 'risk_assessment')['done'], 0)

    def test_risk_review_current_follows_due_queryset(self):
        never = make_live_matter('V0001', make_client('Never'), self.fe)
        old = make_live_matter('V0002', make_client('Old'), self.fe)
        fresh = make_live_matter('V0003', make_client('Fresh'), self.fe)
        make_risk_assessment(old, due_diligence_date=self.today - relativedelta(years=2))
        make_risk_assessment(fresh, due_diligence_date=self.today - timedelta(days=30))
        stats = build_compliance_stats()
        rr = metric_ctx(stats, 'risk_review_current')
        self.assertEqual((rr['done'], rr['not_done']), (1, 2))
        self.assertEqual({r['key']: r['count'] for r in rr['reasons']}, {'never': 1, 'overdue': 1})
        self.assertEqual({r['cells']['file_number']['value'] for r in not_done_rows('risk_review_current')},
                         {'V0001', 'V0002'})

    def test_ongoing_monitoring_counts_records(self):
        matter = make_live_matter('M0001', make_client('Mon'), self.fe)
        make_monitoring(matter, signoff_status=OngoingMonitoring.SIGNOFF_SIGNED)
        make_monitoring(matter)
        make_monitoring(matter, signoff_status=OngoingMonitoring.SIGNOFF_RETURNED)
        om = metric_ctx(build_compliance_stats(), 'ongoing_monitoring_signoff')
        self.assertEqual((om['total'], om['done']), (3, 1))
        self.assertEqual({r['key']: r['count'] for r in om['reasons']}, {'awaiting': 1, 'returned': 1})

    def test_file_review_current(self):
        never = make_live_matter('F0001', make_client('Never'), self.fe)
        old = make_live_matter('F0002', make_client('Old'), self.fe)
        fresh = make_live_matter('F0003', make_client('Fresh'), self.fe)
        MatterFileReview.objects.create(matter=old, date_review_completed=self.today - relativedelta(months=4))
        MatterFileReview.objects.create(matter=fresh, date_review_completed=self.today - timedelta(days=7))
        fr = metric_ctx(build_compliance_stats(), 'file_review_current')
        self.assertEqual((fr['done'], fr['not_done']), (1, 2))
        rows = not_done_rows('file_review_current', reason='overdue')
        self.assertEqual([r['cells']['file_number']['value'] for r in rows], ['F0002'])

    def test_high_risk_only_counts_high_risk_assessments(self):
        low = make_live_matter('H0001', make_client('Low'), self.fe)
        pep = make_live_matter('H0002', make_client('Pep'), self.fe)
        high_signed = make_live_matter('H0003', make_client('High'), self.fe)
        make_risk_assessment(low, signoff_status=RiskAssessment.SIGNOFF_SIGNED)
        make_risk_assessment(pep, politically_exposed_person='Yes')
        make_risk_assessment(high_signed, client_risk_level='High',
                             signoff_status=RiskAssessment.SIGNOFF_SIGNED)
        hr = metric_ctx(build_compliance_stats(), 'high_risk_signed_off')
        self.assertEqual((hr['total'], hr['done']), (2, 1))
        rows = not_done_rows('high_risk_signed_off')
        self.assertEqual(rows[0]['cells']['risk']['value'], 'PEP')

    def test_high_risk_is_na_when_there_are_none(self):
        make_live_matter('H0010', make_client('Low'), self.fe)
        self.assertTrue(metric_ctx(build_compliance_stats(), 'high_risk_signed_off')['na'])

    def test_dormancy(self):
        new = make_live_matter('D0001', make_client('New'), self.fe)
        active = make_live_matter('D0002', make_client('Active'), self.fe)
        quiet = make_live_matter('D0003', make_client('Quiet'), self.fe)
        four_months_ago = timezone.now() - relativedelta(months=4)
        WIP.objects.filter(pk__in=[active.pk, quiet.pk]).update(timestamp=four_months_ago)
        make_slip(active, '10.00', when=self.today - timedelta(days=5))
        stats = build_compliance_stats()
        nd = metric_ctx(stats, 'not_dormant')
        self.assertEqual((nd['done'], nd['not_done']), (2, 1))
        rows = not_done_rows('not_dormant')
        self.assertEqual(rows[0]['cells']['file_number']['value'], 'D0003')
        self.assertEqual(rows[0]['cells']['kind']['value'], 'File opened')
        self.assertEqual(rows[0]['cells']['last_activity']['value'],
                         four_months_ago.date().strftime('%d/%m/%Y'))

    def test_aml_null_and_boundary(self):
        never = make_client('Never')
        boundary = make_client('Boundary')
        boundary.date_of_last_aml = self.today - relativedelta(months=11)
        boundary.save()
        fresh = make_client('Fresh')
        fresh.date_of_last_aml = self.today - relativedelta(months=11) + timedelta(days=1)
        fresh.save()
        for i, client in enumerate([never, boundary, fresh]):
            make_live_matter(f'A000{i}', client, self.fe)
        aml = metric_ctx(build_compliance_stats(), 'aml_check')
        self.assertEqual((aml['done'], aml['not_done']), (1, 2))
        self.assertEqual({r['key']: r['count'] for r in aml['reasons']}, {'never': 1, 'overdue': 1})

    def test_id_verified_null_is_not_done(self):
        yes = make_client('Yes'); yes.id_verified = True; yes.save()
        no = make_client('No'); no.id_verified = False; no.save()
        make_live_matter('I0001', yes, self.fe)
        make_live_matter('I0002', no, self.fe)
        make_live_matter('I0003', make_client('Null'), self.fe)
        idv = metric_ctx(build_compliance_stats(), 'id_verified')
        self.assertEqual((idv['done'], idv['not_done']), (1, 2))

    def test_proof_of_id_missing_and_expired(self):
        missing = make_client('Missing Mo')
        expired = make_client('Expired Ed')
        valid = make_client('Valid Val')
        for i, client in enumerate([missing, expired, valid]):
            make_live_matter(f'P000{i}', client, self.fe)
        ClientKeyDocument.objects.create(client=expired, category='proof_of_id', document_type='Passport',
                                         expiry_date=self.today - timedelta(days=3))
        ClientKeyDocument.objects.create(client=valid, category='proof_of_id', document_type='Licence',
                                         expiry_date=None)
        stats = build_compliance_stats()
        pid = metric_ctx(stats, 'proof_of_id')
        self.assertEqual((pid['done'], pid['not_done']), (1, 2))
        self.assertEqual({r['key']: r['count'] for r in pid['reasons']}, {'missing': 1, 'expired': 1})
        rows = not_done_rows('proof_of_id', reason='expired')
        self.assertEqual(rows[0]['cells']['client']['value'], 'Expired Ed')
        self.assertEqual(rows[0]['cells']['days_overdue']['value'], '3')
        # Proof of address has no documents at all here: everyone is missing.
        self.assertEqual(metric_ctx(stats, 'proof_of_address')['not_done'], 3)

    def test_signed_flags_and_client_care_dates(self):
        client = make_client('Signed')
        client.terms_of_engagement_signed = True
        client.pep_signed = True
        client.save()
        matter = make_live_matter('C0001', client, self.fe)
        matter.date_of_client_care_sent = self.today
        matter.date_of_toe_sent = self.today
        matter.save()
        stats = build_compliance_stats()
        self.assertEqual(metric_ctx(stats, 'terms_signed')['done'], 1)
        self.assertEqual(metric_ctx(stats, 'pep_signed')['done'], 1)
        self.assertEqual(metric_ctx(stats, 'source_of_funds_signed')['done'], 0)
        self.assertEqual(metric_ctx(stats, 'ncba_signed')['done'], 0)
        self.assertEqual(metric_ctx(stats, 'client_care_sent')['done'], 1)
        self.assertEqual(metric_ctx(stats, 'toe_received')['done'], 0)
        rows = not_done_rows('toe_received')
        self.assertEqual(rows[0]['cells']['sent']['value'], self.today.strftime('%d/%m/%Y'))
        self.assertEqual(metric_ctx(stats, 'ncba_received')['done'], 0)

    def test_authorised_parties_counted_once(self):
        party = make_party(id_check=True, date_of_last_aml=self.today - relativedelta(years=2))
        m1 = make_live_matter('U0001', make_client('One'), self.fe)
        m2 = make_live_matter('U0002', make_client('Two'), self.fe)
        WIP.objects.filter(pk=m1.pk).update(authorised_party1=party)
        WIP.objects.filter(pk=m2.pk).update(authorised_party2=party)
        stats = build_compliance_stats()
        self.assertEqual(metric_ctx(stats, 'authorised_party_id')['total'], 1)
        self.assertEqual(metric_ctx(stats, 'authorised_party_id')['done'], 1)
        ap_aml = metric_ctx(stats, 'authorised_party_aml')
        self.assertEqual((ap_aml['total'], ap_aml['done']), (1, 0))
        rows = not_done_rows('authorised_party_aml')
        self.assertEqual(rows[0]['cells']['files']['value'], 'U0001, U0002')

    def test_undertakings_on_live_matters(self):
        matter = make_live_matter('K0001', make_client('Und'), self.fe)
        make_undertaking(matter)
        make_undertaking(matter, discharged=self.today)
        ut = metric_ctx(build_compliance_stats(), 'undertakings_discharged')
        self.assertEqual((ut['total'], ut['done']), (2, 1))

    def test_shared_client_once_firm_wide_but_under_each_fee_earner(self):
        other = make_user('BBB', 'Bob', 'Baker')
        shared = make_client('Shared')
        make_live_matter('S0001', shared, self.fe)
        second = make_live_matter('S0002', make_client('Solo'), other)
        second.additional_clients.add(shared)
        stats = build_compliance_stats()
        self.assertEqual(metric_ctx(stats, 'aml_check')['total'], 2)
        self.assertEqual(row_cell(stats, 'client_dd', 'AAA', 'aml_check')['total'], 1)
        self.assertEqual(row_cell(stats, 'client_dd', 'BBB', 'aml_check')['total'], 2)
        rows = not_done_rows('aml_check', fee_earner=str(self.fe.id))
        self.assertEqual([r['cells']['client']['value'] for r in rows], ['Shared'])
        self.assertEqual(rows[0]['cells']['fee_earners']['value'], 'AAA, BBB')

    @override_settings(RESPONSIBLE_FEE_EARNER_ALIASES=ALIASES)
    def test_dc_matters_roll_into_nd(self):
        dc = make_user('DC', 'Debt', 'Collection')
        nd = make_user('ND', 'Nadia', 'Dunn')
        make_live_matter('X0001', make_client('Debtor'), dc)
        make_live_matter('X0002', make_client('Own'), nd)
        stats = build_compliance_stats()
        codes = [row['code'] for row in group_ctx(stats, 'client_care')['fee_earner_rows']]
        self.assertEqual(codes, ['ND'])
        self.assertEqual(row_cell(stats, 'client_care', 'ND', 'client_care_sent')['total'], 2)
        rows = not_done_rows('client_care_sent', fee_earner=str(nd.id))
        self.assertEqual({r['cells']['file_number']['value'] for r in rows}, {'X0001', 'X0002'})
        self.assertEqual(rows[0]['cells']['fee_earner']['value'], 'Nadia Dunn')

    def test_unassigned_row(self):
        make_live_matter('N0001', make_client('Nobody'), None)
        make_live_matter('N0002', make_client('Somebody'), self.fe)
        stats = build_compliance_stats()
        rows = group_ctx(stats, 'client_care')['fee_earner_rows']
        self.assertEqual([r['name'] for r in rows], ['Ann Able', 'Unassigned'])
        cell = row_cell(stats, 'client_care', '—', 'client_care_sent')
        self.assertTrue(cell['detail_url'].endswith('?fee_earner=none'))
        self.assertFalse(cell['ok'])
        detail = not_done_rows('client_care_sent', fee_earner='none')
        self.assertEqual([r['cells']['file_number']['value'] for r in detail], ['N0001'])

    def test_query_count_does_not_grow_with_data(self):
        fee_earners = [self.fe, make_user('BBB'), make_user('CCC')]
        for i in range(3):
            make_live_matter(f'Q00{i}', make_client(f'Q{i}'), fee_earners[i % 3])
        with CaptureQueriesContext(connection) as small:
            build_compliance_stats()
        for i in range(3, 15):
            m = make_live_matter(f'Q0{i:02d}', make_client(f'Q{i}'), fee_earners[i % 3])
            make_risk_assessment(m)
            make_undertaking(m)
        with CaptureQueriesContext(connection) as large:
            build_compliance_stats()
        self.assertEqual(len(small), len(large))
        self.assertLessEqual(len(large), 40)


class FileClosureTests(TestCase):
    def setUp(self):
        self.fe = make_user('AAA')
        self.archived = make_live_matter('Z0001', make_client('Closed'), self.fe, status='Archived')

    def test_open_undertakings_on_archived_files(self):
        make_undertaking(self.archived)
        live = make_live_matter('Z0003', make_client('Live'), self.fe)
        make_undertaking(live)
        stats = build_compliance_stats()
        m = metric_ctx(stats, 'closed_no_open_undertakings')
        self.assertEqual((m['total'], m['done']), (1, 0))
        rows = not_done_rows('closed_no_open_undertakings')
        self.assertEqual(rows[0]['cells']['open_count']['value'], '1')
        Undertaking.objects.filter(file_number=self.archived).update(date_discharged=date(2026, 2, 1))
        self.assertEqual(metric_ctx(build_compliance_stats(), 'closed_no_open_undertakings')['done'], 1)


class ComplianceStatsPageTests(TestCase):
    def setUp(self):
        self.staff = CustomUser.objects.create_user(
            username='stf', email='stf@example.com', first_name='Sam', last_name='Staff',
            password='password', max_holidays_in_year=20)
        self.fe = make_user('AAA', 'Ann', 'Able')

    def test_requires_login(self):
        resp = self.client.get(reverse('compliance_stats'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login', resp.url.lower())

    def test_non_manager_sees_empty_page_with_na_rings(self):
        self.client.force_login(self.staff)
        resp = self.client.get(reverse('compliance_stats'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Matter risk &amp; reviews')
        self.assertContains(resp, 'Client due diligence')
        self.assertContains(resp, 'Client care paperwork')
        self.assertContains(resp, 'File closure')
        self.assertContains(resp, '>n/a<')
        self.assertNotContains(resp, f'stroke="{GREEN}"')
        self.assertContains(resp, 'Not tracked in this system')

    def test_page_renders_rings_and_fee_earner_links(self):
        matter = make_live_matter('PG0001', make_client('Page'), self.fe)
        matter.date_of_client_care_sent = timezone.localdate()
        matter.save()
        make_live_matter('PG0002', make_client('Gap'), self.fe)
        self.client.force_login(self.staff)
        resp = self.client.get(reverse('compliance_stats'))
        self.assertContains(resp, f'stroke="{GREEN}"')
        self.assertContains(resp, f'stroke="{RED}"')
        self.assertContains(resp, '>50%<')
        detail = reverse('compliance_stats_detail', args=['client_care_sent'])
        self.assertContains(resp, f'{detail}?fee_earner={self.fe.id}')
        self.assertContains(resp, '1 outstanding')

    def test_reports_hub_lists_compliance_stats(self):
        self.client.force_login(self.staff)
        resp = self.client.get(reverse('reports_hub'))
        self.assertContains(resp, reverse('compliance_stats'))
        self.assertContains(resp, 'Compliance stats')


class ComplianceStatsDetailTests(TestCase):
    def setUp(self):
        self.fe = make_user('AAA', 'Ann', 'Able')
        self.other = make_user('BBB', 'Bob', 'Baker')
        self.client.force_login(self.fe)
        self.today = timezone.localdate()
        self.missing = make_client('Missing Mo')
        self.expired = make_client('Expired Ed')
        self.valid = make_client('Valid Val')
        make_live_matter('DT0001', self.missing, self.fe)
        make_live_matter('DT0002', self.expired, self.other)
        make_live_matter('DT0003', self.valid, self.fe)
        ClientKeyDocument.objects.create(client=self.expired, category='proof_of_id',
                                         document_type='Passport', expiry_date=self.today - timedelta(days=9))
        ClientKeyDocument.objects.create(client=self.valid, category='proof_of_id',
                                         document_type='Passport', expiry_date=self.today + timedelta(days=90))
        self.url = reverse('compliance_stats_detail', args=['proof_of_id'])

    def test_unknown_metric_404(self):
        self.assertEqual(self.client.get(reverse('compliance_stats_detail', args=['nope'])).status_code, 404)

    def test_lists_only_not_done_items(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Proof of ID valid')
        self.assertContains(resp, 'Missing Mo')
        self.assertContains(resp, 'Expired Ed')
        self.assertNotContains(resp, 'Valid Val')
        self.assertContains(resp, reverse('compliance_stats'))
        self.assertContains(resp, 'Compliance stats</a>')

    def test_fee_earner_filter(self):
        resp = self.client.get(self.url, {'fee_earner': self.other.id})
        self.assertContains(resp, 'Expired Ed')
        self.assertNotContains(resp, 'Missing Mo')
        resp = self.client.get(self.url, {'fee_earner': 'none'})
        self.assertNotContains(resp, 'Expired Ed')
        self.assertNotContains(resp, 'Missing Mo')

    def test_reason_and_search_filters(self):
        resp = self.client.get(self.url, {'reason': 'expired'})
        self.assertContains(resp, 'Expired Ed')
        self.assertNotContains(resp, 'Missing Mo')
        resp = self.client.get(self.url, {'q': 'mo'})
        self.assertContains(resp, 'Missing Mo')
        self.assertNotContains(resp, 'Expired Ed')
        resp = self.client.get(self.url, {'reason': 'bogus'})
        self.assertContains(resp, 'Missing Mo')

    def test_csv_export(self):
        resp = self.client.get(self.url, {'export': 'csv', 'reason': 'missing'})
        self.assertEqual(resp['Content-Type'], 'text/csv')
        self.assertIn('compliance_proof_of_id_', resp['Content-Disposition'])
        body = resp.content.decode()
        self.assertIn('Missing Mo', body)
        self.assertNotIn('Expired Ed', body)
        self.assertIn('Days overdue', body)
