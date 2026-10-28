from datetime import date, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .. import complaints as rules
from ..compliance_stats import METRICS, Snapshot
from ..models import Complaint, ComplaintCategory, ComplaintEvent, MatterEmails, MatterLetters, Modifications
from .tests_compliance_stats import make_user
from .tests_report_pages import make_client, make_live_matter


def make_complaint(received_on, matters=(), **overrides):
    fields = dict(complainant_name='Pat Complainant', summary='Nobody rang me back.', received_on=received_on)
    fields.update(overrides)
    complaint = Complaint.objects.create(**fields)
    complaint.matters.set(matters)
    return complaint


class ReferenceAndClockTests(TestCase):
    def test_reference_counts_within_the_year(self):
        a = make_complaint(date(2026, 3, 1))
        b = make_complaint(date(2026, 10, 1))
        c = make_complaint(date(2027, 1, 5))
        self.assertEqual([a.reference, b.reference, c.reference], ['C-2026-0001', 'C-2026-0002', 'C-2027-0001'])

    def test_reporting_year_runs_september_to_august(self):
        self.assertEqual(rules.reporting_year(date(2026, 8, 31)), 2026)
        self.assertEqual(rules.reporting_year(date(2026, 9, 1)), 2027)
        self.assertEqual(rules.reporting_year_bounds(2027), (date(2026, 9, 1), date(2027, 8, 31)))

    def test_clock_states(self):
        today = date(2026, 10, 28)
        fresh = make_complaint(today - timedelta(days=10))
        self.assertEqual(rules.clock(fresh, today)['state'], 'ok')
        self.assertEqual(rules.clock(fresh, today)['day'], 11)
        self.assertEqual(rules.clock(fresh, today)['days_left'], 46)
        near = make_complaint(today - timedelta(days=50))
        self.assertEqual(rules.clock(near, today)['state'], 'warning')
        late = make_complaint(today - timedelta(days=60))
        self.assertEqual(rules.clock(late, today)['state'], 'overdue')
        self.assertEqual(rules.clock(late, today)['days_left'], -4)
        answered = make_complaint(today - timedelta(days=60), final_response_sent_on=today - timedelta(days=20))
        c = rules.clock(answered, today)
        self.assertEqual(c['state'], 'stopped')
        self.assertTrue(c['met'])
        self.assertEqual(c['day'], 41)

    def test_attention_reasons(self):
        today = date(2026, 10, 28)
        c = make_complaint(today - timedelta(days=60))
        reasons = rules.attention(c, today)
        self.assertIn('4 days past the eight-week deadline', reasons)
        self.assertIn('Not yet acknowledged', reasons)
        c.final_response_sent_on = today
        c.status = Complaint.STATUS_FINAL_RESPONSE
        c.save()
        self.assertIn('Final response is missing ombudsman wording', rules.attention(c, today))
        c.fr_states_leo_available = c.fr_has_leo_contact_details = c.fr_has_six_month_warning = True
        c.save()
        self.assertNotIn('Final response is missing ombudsman wording', rules.attention(c, today))

    def test_destruction_date_follows_closure(self):
        c = make_complaint(date(2026, 1, 1), closed_on=date(2026, 3, 1), status=Complaint.STATUS_RESOLVED)
        self.assertEqual(c.destruction_due_on, date(2032, 3, 1))
        self.assertIsNone(make_complaint(date(2026, 1, 1)).destruction_due_on)


class VisibilityTests(TestCase):
    def setUp(self):
        self.manager = make_user('MGR', 'Mo', 'Manager', is_manager=True)
        self.ann = make_user('AAA', 'Ann', 'Able')
        self.bob = make_user('BBB', 'Bob', 'Baker')
        self.staff = make_user('STF', 'Sam', 'Staff', is_matter_fee_earner=False)
        self.anns = make_live_matter('Q0001', make_client('Ann Client'), self.ann)
        self.about_ann = make_complaint(date(2026, 10, 1), [self.anns], about_fee_earner=self.ann)
        self.handled_by_staff = make_complaint(date(2026, 10, 2), handled_by=self.staff)
        self.other = make_complaint(date(2026, 10, 3))

    def test_manager_and_officer_see_everything(self):
        self.assertEqual(rules.visible_complaints(self.manager).count(), 3)
        with override_settings(COMPLAINTS_OFFICER='bbb'):
            self.assertTrue(rules.can_see_all(self.bob))
            self.assertEqual(rules.visible_complaints(self.bob).count(), 3)

    def test_staff_see_their_own(self):
        self.assertEqual(set(rules.visible_complaints(self.ann)), {self.about_ann})
        self.assertEqual(set(rules.visible_complaints(self.staff)), {self.handled_by_staff})
        self.assertEqual(rules.visible_complaints(self.bob).count(), 0)

    def test_handler_manages_subject_does_not(self):
        self.assertTrue(rules.can_manage(self.staff, self.handled_by_staff))
        self.assertFalse(rules.can_manage(self.ann, self.about_ann))
        self.assertTrue(rules.can_manage(self.manager, self.about_ann))

    def test_detail_hidden_outside_visibility(self):
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(reverse('complaint_detail', args=[self.other.reference])).status_code, 404)
        self.client.force_login(self.ann)
        self.assertEqual(self.client.get(reverse('complaint_detail', args=[self.about_ann.reference])).status_code, 200)
        response = self.client.post(reverse('complaint_action', args=[self.about_ann.reference]),
                                    {'action': 'acknowledge'})
        self.assertEqual(response.status_code, 403)


class WorkflowTests(TestCase):
    def setUp(self):
        self.manager = make_user('MGR', 'Mo', 'Manager', is_manager=True)
        self.ann = make_user('AAA', 'Ann', 'Able')
        self.matter = make_live_matter('Q0001', make_client('Ann Client'), self.ann)
        self.client.force_login(self.manager)
        ComplaintCategory.objects.get_or_create(name='Delay')

    def test_log_complaint_from_form(self):
        response = self.client.post(reverse('complaint_add'), {
            'complainant_name': 'Ann Client', 'complainant_type': 'client',
            'received_on': '2026-10-20', 'received_via': 'email', 'summary': 'Took too long.',
            'matter_numbers': 'q0001', 'about_fee_earner': self.ann.id,
            'categories': [ComplaintCategory.objects.get(name='Delay').id],
        })
        complaint = Complaint.objects.get()
        self.assertRedirects(response, reverse('complaint_detail', args=[complaint.reference]))
        self.assertEqual(list(complaint.matters.all()), [self.matter])
        self.assertEqual(complaint.received_by, self.manager)
        self.assertEqual(complaint.created_by, self.manager)
        self.assertEqual(complaint.events.get().kind, 'received')
        self.assertTrue(Modifications.objects.filter(object_id=complaint.id).exists())

    def test_unknown_file_number_rejected(self):
        response = self.client.post(reverse('complaint_add'), {
            'complainant_name': 'X', 'complainant_type': 'client', 'received_on': '2026-10-20',
            'received_via': 'email', 'summary': 'Y', 'matter_numbers': 'ZZZ9999999',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No file with number ZZZ9999999')
        self.assertFalse(Complaint.objects.exists())

    def test_milestones_move_status_and_write_chronology(self):
        c = make_complaint(date(2026, 10, 1), [self.matter])
        url = reverse('complaint_action', args=[c.reference])
        self.client.post(url, {'action': 'acknowledge', 'when': '2026-10-02'})
        c.refresh_from_db()
        self.assertEqual((c.status, c.acknowledged_on), (Complaint.STATUS_ACKNOWLEDGED, date(2026, 10, 2)))
        self.client.post(url, {'action': 'final_response', 'when': '2026-11-10'})
        c.refresh_from_db()
        self.assertEqual(c.status, Complaint.STATUS_FINAL_RESPONSE)
        self.assertEqual(rules.clock(c, date(2026, 12, 1))['state'], 'stopped')
        # Closing needs an outcome first.
        response = self.client.post(url, {'action': 'resolve'})
        c.refresh_from_db()
        self.assertTrue(c.is_open)
        self.client.post(reverse('complaint_outcome', args=[c.reference]), {
            'outcome': 'upheld', 'redress_type': 'apology', 'root_cause': 'Diary not checked.',
            'fr_states_leo_available': 'on', 'fr_has_leo_contact_details': 'on', 'fr_has_six_month_warning': 'on',
        })
        self.client.post(url, {'action': 'resolve', 'when': '2026-11-12'})
        c.refresh_from_db()
        self.assertEqual((c.status, c.closed_by, c.closed_on), (Complaint.STATUS_RESOLVED, self.manager, date(2026, 11, 12)))
        self.assertTrue(c.final_response_complete)
        self.assertEqual(list(c.events.values_list('kind', flat=True)),
                         ['closed', 'final_response', 'acknowledged'])
        self.client.post(url, {'action': 'reopen'})
        c.refresh_from_db()
        self.assertEqual((c.status, c.closed_on), (Complaint.STATUS_INVESTIGATING, None))

    def test_chronology_entry_with_document(self):
        c = make_complaint(date(2026, 10, 1))
        response = self.client.post(reverse('complaint_add_event', args=[c.reference]), {
            'kind': 'call', 'occurred_on': '2026-10-03', 'note': 'Rang Pat; apologised.',
            'document': SimpleUploadedFile('note.txt', b'hello'),
        })
        self.assertEqual(response.status_code, 302)
        event = c.events.get(kind='call')
        self.assertEqual(event.document_name, 'note.txt')
        download = self.client.get(reverse('complaint_document', args=[event.id]))
        self.assertEqual(download.status_code, 200)
        self.assertEqual(b''.join(download.streaming_content), b'hello')

    def test_tag_and_untag_correspondence(self):
        c = make_complaint(date(2026, 10, 1), [self.matter])
        email = MatterEmails.objects.create(file_number=self.matter, subject='Where is my money', sender='{}', receiver='[]')
        letter = MatterLetters.objects.create(file_number=self.matter, date=date(2026, 10, 2), to_or_from='Pat', subject_line='Reply')
        url = reverse('complaint_tag_correspondence', args=[self.matter.file_number])
        self.client.post(url, {'kind': 'email', 'id': email.id, 'complaint': c.id})
        self.client.post(url, {'kind': 'letter', 'id': letter.id, 'complaint': c.id})
        email.refresh_from_db(); letter.refresh_from_db()
        self.assertEqual((email.complaint, letter.complaint), (c, c))
        page = self.client.get(reverse('complaint_detail', args=[c.reference]))
        self.assertContains(page, 'Where is my money')
        self.client.post(url, {'kind': 'email', 'id': email.id, 'untag': '1'})
        email.refresh_from_db()
        self.assertIsNone(email.complaint)
        corr = self.client.get(reverse('correspondence_view', args=[self.matter.file_number]))
        self.assertContains(corr, f'Add to complaint {c.reference}')

    def test_edit_details_relinks_matters_and_audits(self):
        c = make_complaint(date(2026, 10, 1), [self.matter])
        other = make_live_matter('Q0002', make_client('Second'), self.ann)
        self.client.post(reverse('complaint_edit', args=[c.reference]), {
            'complainant_name': 'Pat Complainant', 'complainant_type': 'former_client',
            'received_on': '2026-10-01', 'received_via': 'letter', 'summary': 'Nobody rang me back.',
            'matter_numbers': 'Q0001, Q0002',
        })
        c.refresh_from_db()
        self.assertEqual(c.complainant_type, 'former_client')
        self.assertEqual(set(c.matters.all()), {self.matter, other})
        changes = Modifications.objects.filter(object_id=c.id).latest('id').changes
        self.assertIn('matters', changes)
        self.assertIn('complainant_type', changes)

    def test_matter_home_shows_banner_and_card(self):
        c = make_complaint(date.today() - timedelta(days=3), [self.matter])
        page = self.client.get(reverse('home', args=[self.matter.file_number]))
        self.assertContains(page, f'Open complaint {c.reference}')
        self.assertContains(page, 'Log a complaint')


class RegisterAndReportTests(TestCase):
    def setUp(self):
        self.manager = make_user('MGR', 'Mo', 'Manager', is_manager=True)
        self.ann = make_user('AAA', 'Ann', 'Able')
        self.matter = make_live_matter('Q0001', make_client('Ann Client'), self.ann)
        delay, _ = ComplaintCategory.objects.get_or_create(name='Delay')
        costs, _ = ComplaintCategory.objects.get_or_create(name='Costs excessive')
        self.resolved = make_complaint(
            date(2026, 10, 1), [self.matter], about_fee_earner=self.ann,
            acknowledged_on=date(2026, 10, 2), final_response_sent_on=date(2026, 10, 20),
            status=Complaint.STATUS_RESOLVED, closed_on=date(2026, 10, 25), outcome='upheld',
            root_cause='Diary', redress_amount=150, fr_states_leo_available=True,
            fr_has_leo_contact_details=True, fr_has_six_month_warning=True)
        self.resolved.categories.set([delay, costs])
        self.overdue = make_complaint(date(2026, 8, 1), about_fee_earner=self.ann, leo_referred_on=date(2026, 10, 5),
                                      status=Complaint.STATUS_ESCALATED_LEO)
        self.overdue.categories.set([delay])
        self.informal = make_complaint(date(2026, 10, 10), is_informal=True)
        self.client.force_login(self.manager)

    def test_register_filters_and_csv(self):
        page = self.client.get(reverse('complaints_register'))
        self.assertContains(page, self.overdue.reference)
        self.assertNotContains(page, self.resolved.reference)
        page = self.client.get(reverse('complaints_register'), {'show': 'closed'})
        self.assertContains(page, self.resolved.reference)
        page = self.client.get(reverse('complaints_register'), {'show': 'all', 'q': 'Q0001'})
        self.assertContains(page, self.resolved.reference)
        self.assertNotContains(page, self.informal.reference)
        csv_response = self.client.get(reverse('complaints_register'), {'show': 'all', 'export': 'csv'})
        self.assertEqual(csv_response['Content-Type'], 'text/csv')
        self.assertIn(self.resolved.reference, csv_response.content.decode())

    def test_annual_return_figures(self):
        data = rules.annual_return(2027)   # Sep 2026 - Aug 2027
        self.assertEqual((data['received'], data['resolved'], data['referred']), (1, 1, 1))
        self.assertEqual(data['within_eight_weeks'], 1)
        self.assertEqual(data['average_response_days'], 19)
        self.assertEqual(data['redress_total'], 150)
        by = {row['name']: row for row in data['by_category']}
        self.assertEqual((by['Delay']['received'], by['Delay']['referred']), (1, 1))
        self.assertEqual(by['Costs excessive']['received'], 1)
        page = self.client.get(reverse('complaints_annual_return'), {'year': 2027})
        self.assertContains(page, 'Complaints annual return')
        self.client.force_login(self.ann)
        self.assertEqual(self.client.get(reverse('complaints_annual_return')).status_code, 403)

    def test_summary_counts(self):
        # The escalated complaint's clock stopped when it went to the ombudsman,
        # so only a plain one past eight weeks counts as overdue.
        late = make_complaint(date(2026, 8, 20))
        s = rules.summary(self.manager, today=date(2026, 10, 28))
        self.assertEqual((s['open'], s['overdue']), (3, 1))
        self.assertEqual(s['rows'][0]['complaint'], late)
        self.assertEqual(s['rows'][-1]['complaint'], self.overdue)

    def test_compliance_metrics(self):
        snap = Snapshot(today=date(2026, 10, 28))
        ack = {i.key: i for i in METRICS['complaints_acknowledged'].collect(snap)}
        self.assertTrue(ack[self.resolved.id].done)
        self.assertEqual(ack[self.overdue.id].reason, 'never')
        self.assertEqual(ack[self.resolved.id].fee_earner_ids, frozenset({self.ann.id}))
        weeks = {i.key: i for i in METRICS['complaints_eight_weeks'].collect(snap)}
        self.assertTrue(weeks[self.resolved.id].done)
        self.assertNotIn(self.informal.id, weeks)          # still inside eight weeks
        wording = {i.key: i for i in METRICS['complaints_final_response_wording'].collect(snap)}
        self.assertEqual(list(wording), [self.resolved.id])
        root = {i.key: i for i in METRICS['complaints_root_cause'].collect(snap)}
        self.assertTrue(root[self.resolved.id].done)
        page = self.client.get(reverse('compliance_stats'))
        self.assertContains(page, 'Final response within eight weeks')
        self.assertNotContains(page, 'Complaints log and response times')
        detail = self.client.get(reverse('compliance_stats_detail', args=['complaints_eight_weeks']))
        self.assertContains(detail, self.overdue.reference)

    def test_dashboard_and_reports_hub(self):
        self.assertContains(self.client.get(reverse('user_dashboard')), self.overdue.reference)
        hub = self.client.get(reverse('reports_hub'))
        self.assertContains(hub, 'Complaints register')
        self.assertContains(hub, 'Complaints annual return')
