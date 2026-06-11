from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from users.models import CustomUser

from ..models import (
    ClientContactDetails,
    ClientKeyDocument,
    FileStatus,
    MatterType,
    WIP,
)


class ReportsHubTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='hub',
            email='hub@example.com',
            first_name='Hub',
            last_name='User',
            password='password',
            max_holidays_in_year=20,
        )
        self.client.force_login(self.user)

    def test_non_manager_sees_standard_reports_only(self):
        response = self.client.get(reverse('reports_hub'))
        self.assertEqual(response.status_code, 200)
        # Standard (compliance) reports are visible to everyone.
        self.assertContains(response, 'Compliance')
        self.assertContains(response, reverse('report_expired_ids'))
        # Management-level groups and their reports are hidden.
        self.assertNotContains(response, 'Management &amp; HR')
        self.assertNotContains(response, reverse('management_reports'))
        self.assertNotContains(response, reverse('download_cashier_data'))

    def test_manager_also_sees_management_groups(self):
        self.user.is_manager = True
        self.user.save()
        response = self.client.get(reverse('reports_hub'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Compliance')
        self.assertContains(response, 'Management &amp; HR')
        self.assertContains(response, reverse('management_reports'))
        self.assertContains(response, reverse('invoices_list'))

    def test_hub_shows_live_matter_id_issue_count(self):
        # A client on a live matter with an expired ID is one ID issue.
        client = ClientContactDetails.objects.create(
            name='Expired Ed', occupation='Retired', address_line1='1 St',
            address_line2='', county='Essex', postcode='SS7 1QT',
            email='e@example.com', contact_number='0123456789',
        )
        fs, _ = FileStatus.objects.get_or_create(status='Open')
        mt, _ = MatterType.objects.get_or_create(type='Probate')
        WIP.objects.create(
            file_number='HUB0001', client1=client, matter_description='m',
            matter_type=mt, file_status=fs, funding='Pvt',
        )
        ClientKeyDocument.objects.create(
            client=client, category='proof_of_id', document_type='Passport',
            expiry_date=timezone.localdate() - timedelta(days=5),
        )
        response = self.client.get(reverse('reports_hub'))
        self.assertEqual(response.context['id_issues_count'], 1)

    def test_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse('reports_hub'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.url.lower())
