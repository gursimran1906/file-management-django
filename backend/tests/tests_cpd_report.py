from datetime import date

from django.test import TestCase
from django.urls import reverse

from users.models import CPDTrainingLog

from .tests_compliance_stats import make_user


def make_cpd(user, title, when, added_by=None, **extra):
    defaults = dict(delivered_by='Law Society', delivery_of_course='online',
                    impact='Useful', certificate_provided=True)
    defaults.update(extra)
    return CPDTrainingLog.objects.create(
        user=user, course_title=title, date_completed=when, added_by=added_by, **defaults)


class CpdReportTests(TestCase):
    def setUp(self):
        self.ann = make_user('AAA', 'Ann', 'Able')
        self.bob = make_user('BBB', 'Bob', 'Baker', is_matter_fee_earner=False)
        self.client.force_login(self.bob)
        self.url = reverse('report_cpd')
        make_cpd(self.ann, 'AML update 2026', date(2026, 3, 1), added_by=self.bob)
        make_cpd(self.bob, 'Probate practice', date(2026, 9, 15), delivery_of_course='in_person',
                 certificate_provided=False)

    def test_requires_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_lists_everyone_with_who_added_it(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'AML update 2026')
        self.assertContains(resp, 'Probate practice')
        self.assertContains(resp, 'Added by')
        rows = resp.context['rows']
        # Newest completed first; BBB added Ann's record.
        self.assertEqual([r[1]['value'] for r in rows], ['Probate practice', 'AML update 2026'])
        self.assertEqual(rows[1][7]['value'], 'BBB')
        self.assertEqual(rows[0][7]['value'], '—')
        self.assertContains(resp, 'cpd-crud-modal')
        self.assertContains(resp, reverse('add_cpd'))

    def test_filters(self):
        resp = self.client.get(self.url, {'staff': self.ann.id})
        self.assertEqual(len(resp.context['rows']), 1)
        resp = self.client.get(self.url, {'from': '2026-06-01', 'to': '2026-12-31'})
        self.assertEqual([r[1]['value'] for r in resp.context['rows']], ['Probate practice'])
        resp = self.client.get(self.url, {'method': 'in_person'})
        self.assertEqual(len(resp.context['rows']), 1)
        resp = self.client.get(self.url, {'certificate': 'yes'})
        self.assertEqual([r[1]['value'] for r in resp.context['rows']], ['AML update 2026'])
        resp = self.client.get(self.url, {'q': 'society'})
        self.assertEqual(len(resp.context['rows']), 2)
        resp = self.client.get(self.url, {'from': 'not-a-date'})
        self.assertEqual(len(resp.context['rows']), 2)

    def test_csv_export(self):
        resp = self.client.get(self.url, {'export': 'csv', 'staff': self.ann.id})
        body = resp.content.decode()
        self.assertIn('AML update 2026', body)
        self.assertNotIn('Probate practice', body)
        self.assertIn('Added by', body)

    def test_anyone_can_add_for_anyone_and_it_records_who(self):
        resp = self.client.post(reverse('add_cpd'), {
            'user': self.ann.id, 'course_title': 'Conveyancing fraud', 'delivered_by': 'CLC',
            'delivery_of_course': 'online', 'date_completed': '2026-10-01', 'impact': 'Good',
            'certificate_provided': 'on', 'next': f'{self.url}?staff={self.ann.id}',
        })
        self.assertRedirects(resp, f'{self.url}?staff={self.ann.id}')
        log = CPDTrainingLog.objects.get(course_title='Conveyancing fraud')
        self.assertEqual((log.user, log.added_by), (self.ann, self.bob))

    def test_invalid_add_reports_the_error(self):
        resp = self.client.post(reverse('add_cpd'), {'user': self.ann.id, 'next': self.url}, follow=True)
        self.assertRedirects(resp, self.url)
        self.assertContains(resp, 'CPD record not saved')
        self.assertEqual(CPDTrainingLog.objects.count(), 2)

    def test_unsafe_next_falls_back_to_profile(self):
        resp = self.client.post(reverse('add_cpd'), {
            'user': self.ann.id, 'course_title': 'X', 'delivered_by': 'Y', 'delivery_of_course': 'online',
            'date_completed': '2026-10-01', 'impact': 'Z', 'next': 'https://evil.example.com/',
        })
        self.assertRedirects(resp, reverse('profile_page'), fetch_redirect_response=False)

    def test_edit_returns_to_the_report(self):
        log = CPDTrainingLog.objects.get(course_title='AML update 2026')
        edit_url = reverse('edit_cpd', args=[log.id])
        resp = self.client.get(edit_url, {'next': self.url})
        self.assertContains(resp, f'href="{self.url}"')
        self.assertContains(resp, 'Added by BBB')
        resp = self.client.post(edit_url, {
            'user': self.ann.id, 'course_title': 'AML update 2026 (v2)', 'delivered_by': 'Law Society',
            'delivery_of_course': 'online', 'date_completed': '2026-03-01', 'impact': 'Useful',
            'certificate_provided': 'on', 'next': self.url,
        })
        self.assertRedirects(resp, self.url)
        log.refresh_from_db()
        self.assertEqual(log.course_title, 'AML update 2026 (v2)')

    def test_hub_lists_the_report(self):
        resp = self.client.get(reverse('reports_hub'))
        self.assertContains(resp, self.url)
        self.assertContains(resp, 'CPD records')
