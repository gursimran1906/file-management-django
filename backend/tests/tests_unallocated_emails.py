import json

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from users.models import CustomUser

from ..models import MatterEmails
from .tests_report_pages import make_client, make_live_matter


def make_email(to_recipients, *, matter=None, is_sent=False, subject='Hello',
               sender_name='Sam Sender', sender_address='sam@example.com'):
    """A row as the Graph sync stores it: sender/receiver are JSON strings."""
    return MatterEmails.objects.create(
        file_number=matter,
        sender=json.dumps(
            {'emailAddress': {'name': sender_name, 'address': sender_address}}),
        receiver=json.dumps(to_recipients),
        subject=subject, body='Body', is_sent=is_sent, units=1,
        time=timezone.now(), link='https://outlook/msg',
    )


class EmailsWithoutRecipientsTests(TestCase):
    """The sync stores bcc-only mail with an empty toRecipients list; pages
    that show the first recipient must render it rather than 500."""

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='eml', email='eml@example.com', first_name='Em',
            last_name='Ail', password='password', max_holidays_in_year=20,
        )
        self.client.force_login(self.user)

    def test_unallocated_page_renders_email_with_no_recipients(self):
        make_email([], subject='Bcc only')
        resp = self.client.get(reverse('unallocated_emails'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Bcc only')
        self.assertContains(resp, 'sam@example.com')

    def test_unallocated_page_still_shows_first_recipient(self):
        make_email([{'emailAddress': {'name': 'Mail Box',
                                      'address': 'mail@anpsolicitors.com'}}])
        resp = self.client.get(reverse('unallocated_emails'))
        self.assertContains(resp, 'Mail Box (mail@anpsolicitors.com)')
        self.assertContains(
            resp, 'data-email="mail@anpsolicitors.com sam@example.com"')

    def test_unallocated_page_tolerates_recipient_without_name(self):
        make_email([{'emailAddress': {'address': 'mail@anpsolicitors.com'}}])
        resp = self.client.get(reverse('unallocated_emails'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'mail@anpsolicitors.com')

    def test_unallocated_page_escapes_email_supplied_text(self):
        make_email([], subject='<script>alert(1)</script>',
                   sender_name='<b>Eve</b>')
        resp = self.client.get(reverse('unallocated_emails'))
        self.assertNotContains(resp, '<script>alert(1)</script>')
        self.assertNotContains(resp, '<b>Eve</b>')
        self.assertContains(resp, '&lt;script&gt;alert(1)&lt;/script&gt;')

    def test_schedule_of_costs_downloads_sent_email_with_no_recipients(self):
        matter = make_live_matter('EML0010001', make_client('Bcc Client'))
        make_email([], matter=matter, is_sent=True)
        resp = self.client.get(
            reverse('download_sowc', args=[matter.file_number]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Email sent', resp.content.decode())
