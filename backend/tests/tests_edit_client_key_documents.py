"""The client edit page renders its key-documents editor: status badges for
existing docs, and the Add document / Renew affordances that add a new record
(keeping expired documents on file) rather than overwriting."""
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from users.models import CustomUser

from ..models import ClientContactDetails, ClientKeyDocument


class EditClientKeyDocumentsRenderTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='abc', email='abc@example.com', first_name='A', last_name='B',
            password='password', max_holidays_in_year=20)
        self.client.force_login(self.user)
        self.rec = ClientContactDetails.objects.create(
            name='Jane Doe', occupation='Retired', address_line1='1 Test Street',
            address_line2='', county='Essex', postcode='SS7 1QT',
            email='jane@example.com', contact_number='0123456789')

    def test_expired_document_shows_status_and_add_controls(self):
        today = timezone.localdate()
        ClientKeyDocument.objects.create(
            client=self.rec, category='proof_of_id', verified_on=today,
            expiry_date=today - timedelta(days=1))  # expired

        resp = self.client.get(reverse('edit_client', args=[self.rec.id]))

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Add document')
        self.assertContains(resp, 'Renew')
        self.assertContains(resp, 'Expired')
        # The inert template row for JS-added documents is present.
        self.assertContains(resp, 'key-document-empty-form')

    def test_valid_document_shows_valid_status(self):
        today = timezone.localdate()
        ClientKeyDocument.objects.create(
            client=self.rec, category='proof_of_address', verified_on=today,
            expiry_date=today + timedelta(days=200))

        resp = self.client.get(reverse('edit_client', args=[self.rec.id]))

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Valid')

    def test_document_without_expiry_is_not_shown_as_current(self):
        # No expiry date recorded — we can't claim it's current.
        ClientKeyDocument.objects.create(
            client=self.rec, category='proof_of_address',
            verified_on=timezone.localdate(), expiry_date=None)

        resp = self.client.get(reverse('edit_client', args=[self.rec.id]))

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'No expiry date')
        self.assertNotContains(resp, '>Current<')

    def test_document_due_soon_shows_due_soon(self):
        today = timezone.localdate()
        ClientKeyDocument.objects.create(
            client=self.rec, category='proof_of_id', verified_on=today,
            expiry_date=today + timedelta(days=10))

        resp = self.client.get(reverse('edit_client', args=[self.rec.id]))

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Due soon')
