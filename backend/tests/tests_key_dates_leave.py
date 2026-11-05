from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from users.models import CustomUser, HolidayRecord


def make_user(code, first, last, **extra):
    return CustomUser.objects.create_user(
        username=code, email=f'{code.lower()}@example.com', first_name=first,
        last_name=last, password='password', max_holidays_in_year=20, **extra,
    )


class KeyDatesLeaveTypeVisibilityTests(TestCase):
    """Whether leave is paid or unpaid is only shown to managers and to the
    person on leave. Other staff just see that the colleague is off."""

    def setUp(self):
        self.manager = make_user('MGR', 'Molly', 'Manager', is_manager=True)
        self.on_leave = make_user('ONL', 'Oliver', 'Leave')
        self.colleague = make_user('COL', 'Clare', 'Colleague')
        start = timezone.now() + timedelta(days=2)
        HolidayRecord.objects.create(
            employee=self.on_leave, start_date=start, end_date=start,
            reason='', type='Unpaid', approved=True,
        )
        self.params = {}

    def get_page(self, user):
        self.client.force_login(user)
        return self.client.get(reverse('central_key_dates'), self.params)

    def test_manager_sees_leave_type(self):
        response = self.get_page(self.manager)
        self.assertContains(response, 'Unpaid leave')

    def test_person_on_leave_sees_own_leave_type(self):
        response = self.get_page(self.on_leave)
        self.assertContains(response, 'Unpaid leave')

    def test_other_staff_see_only_that_colleague_is_off(self):
        response = self.get_page(self.colleague)
        self.assertContains(response, 'ONL off')
        self.assertNotContains(response, 'Unpaid leave')
        self.assertNotContains(response, 'Annual leave')
        self.assertNotContains(response, 'Unpaid')

    def test_other_staff_export_hides_leave_type(self):
        self.client.force_login(self.colleague)
        response = self.client.get(
            reverse('download_central_key_dates', args=['csv', 'list']), self.params)
        body = response.content.decode()
        self.assertIn('ONL off', body)
        self.assertNotIn('Unpaid', body)
