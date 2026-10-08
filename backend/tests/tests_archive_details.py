from datetime import date

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from ..forms import OpenFileForm
from ..models import WIP, Modifications
from .tests_compliance_stats import make_user
from .tests_report_pages import make_client, make_live_matter


class ArchiveDetailsTests(TestCase):
    def setUp(self):
        self.user = make_user('AAA', 'Ann', 'Able')
        self.client.force_login(self.user)
        self.archived = make_live_matter('AR0001', make_client('Archived Client'), self.user, status='Archived')
        self.open = make_live_matter('AR0002', make_client('Open Client'), self.user, status='Open')
        self.url = reverse('matter_archive_details', args=['AR0001'])

    def test_edit_file_form_leaves_archive_fields_alone(self):
        for name in ('latest_destruction_date', 'actual_destruction_date', 'brought_down_on'):
            self.assertNotIn(name, OpenFileForm().fields)

    def test_saves_destruction_dates_with_an_audit_trail(self):
        resp = self.client.post(self.url, {
            'latest_destruction_date': '2032-10-08', 'actual_destruction_date': '', 'brought_down_on': ''})
        self.assertRedirects(resp, reverse('home', args=['AR0001']))
        self.archived.refresh_from_db()
        self.assertEqual(self.archived.latest_destruction_date, date(2032, 10, 8))
        self.assertIsNone(self.archived.actual_destruction_date)
        change = Modifications.objects.get(object_id=self.archived.id)
        self.assertEqual(change.modified_by, self.user)
        self.assertEqual(change.changes['latest_destruction_date']['new_value'], '2032-10-08')

    def test_brought_down_today_then_returned(self):
        self.client.post(self.url, {'latest_destruction_date': '', 'actual_destruction_date': '',
                                    'brought_down_on': '', 'action': 'brought_down'})
        self.archived.refresh_from_db()
        self.assertEqual(self.archived.brought_down_on, timezone.localdate())

        resp = self.client.post(self.url, {'action': 'returned'}, follow=True)
        self.assertContains(resp, 'returned to archive')
        self.archived.refresh_from_db()
        self.assertIsNone(self.archived.brought_down_on)
        self.assertEqual(Modifications.objects.filter(object_id=self.archived.id).count(), 2)

    def test_invalid_date_is_rejected(self):
        resp = self.client.post(self.url, {'latest_destruction_date': 'soon'}, follow=True)
        self.assertContains(resp, 'Latest destruction date')
        self.archived.refresh_from_db()
        self.assertIsNone(self.archived.latest_destruction_date)

    def test_home_shows_the_card_only_where_it_applies(self):
        resp = self.client.get(reverse('home', args=['AR0001']))
        self.assertContains(resp, 'Archive &amp; retention')
        self.assertContains(resp, 'Record the latest date this file may be destroyed')
        self.assertContains(resp, 'Brought down today')
        resp = self.client.get(reverse('home', args=['AR0002']))
        self.assertNotContains(resp, 'Archive &amp; retention')

    def test_brought_down_file_is_listed_amongst_open_files(self):
        other = make_live_matter('AR0003', make_client('Stored Client'), self.user, status='Archived')
        WIP.objects.filter(pk=self.archived.pk).update(brought_down_on=date(2026, 10, 1))
        resp = self.client.post(reverse('display_data_index_page'),
                                {'searchBy': 'FileNumber', 'valToSearch': 'AR'})
        files = [row['file_number'] for row in resp.context['data']]
        self.assertEqual(files, ['AR0001', 'AR0002'])
        self.assertContains(resp, 'File in office')
        resp = self.client.get(reverse('home', args=['AR0001']))
        self.assertContains(resp, 'Physical file in office since 01/10/2026')
        self.assertContains(resp, 'Returned to archive')
        self.assertNotContains(resp, 'Brought down today')
