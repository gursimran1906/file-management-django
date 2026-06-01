from datetime import date

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from users.models import CustomUser

from .models import (
    ClientContactDetails,
    Invoices,
    MatterAttendanceNotes,
    MatterTimeEvent,
    MatterTimeSession,
    MatterType,
    WIP,
)
from .time_events import (
    compute_units_from_minutes,
    compute_units_from_times,
    lock_time_events_for_invoice,
)


def make_client(name='Test Client'):
    return ClientContactDetails.objects.create(
        name=name,
        occupation='Retired',
        address_line1='1 Test Street',
        address_line2='',
        county='Essex',
        postcode='SS7 1QT',
        email='test@example.com',
        contact_number='0123456789',
    )


def make_matter(file_number='TST0000001'):
    client = make_client()
    matter_type = MatterType.objects.create(type='Probate')
    return WIP.objects.create(
        file_number=file_number,
        client1=client,
        matter_description='Test matter',
        matter_type=matter_type,
        funding='Pvt',
    )


class TimeEventHelpersTests(TestCase):
    def test_compute_units_from_minutes(self):
        self.assertEqual(compute_units_from_minutes(1), 1)
        self.assertEqual(compute_units_from_minutes(6), 1)
        self.assertEqual(compute_units_from_minutes(7), 2)

    def test_compute_units_from_times(self):
        from datetime import time
        self.assertEqual(
            compute_units_from_times(time(9, 0), time(9, 12)),
            2,
        )


class MatterTimeEventAPITests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='tim',
            email='time@example.com',
            first_name='Time',
            last_name='User',
            password='testpass123',
            max_holidays_in_year=20,
        )
        self.matter = make_matter()

    def test_quick_log_creates_attendance_note(self):
        self.client.force_login(self.user)
        url = reverse(
            'time_event_quick_log',
            kwargs={'file_number': self.matter.file_number},
        )
        response = self.client.post(
            url,
            data={
                'description': 'Telephone call with client',
                'minutes': 12,
                'activity_type': 'telephone',
                'is_charged': True,
            },
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(MatterTimeEvent.objects.count(), 1)
        self.assertEqual(MatterAttendanceNotes.objects.count(), 1)
        note = MatterAttendanceNotes.objects.get()
        self.assertEqual(note.unit, 2)

    def test_timer_start_stop(self):
        self.client.force_login(self.user)
        start_url = reverse(
            'time_event_start',
            kwargs={'file_number': self.matter.file_number},
        )
        stop_url = reverse(
            'time_event_stop',
            kwargs={'file_number': self.matter.file_number},
        )
        self.client.post(
            start_url,
            data={'activity_type': 'drafting'},
            content_type='application/json',
        )
        self.assertEqual(MatterTimeSession.objects.count(), 1)
        response = self.client.post(
            stop_url,
            data={
                'description': 'Drafting witness statement',
                'activity_type': 'drafting',
            },
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(MatterTimeSession.objects.count(), 0)
        self.assertEqual(
            MatterTimeEvent.objects.filter(status='confirmed').count(), 1,
        )


class TimeEventLockTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='lck',
            email='lock@example.com',
            first_name='Lock',
            last_name='User',
            password='testpass123',
            max_holidays_in_year=20,
        )
        self.matter = make_matter('TST0000002')

    def test_lock_time_events_sets_locked_at(self):
        event = MatterTimeEvent.objects.create(
            file_number=self.matter,
            user=self.user,
            started_at=timezone.now(),
            ended_at=timezone.now(),
            description='Work',
            status=MatterTimeEvent.STATUS_CONFIRMED,
            units=1,
        )
        invoice = Invoices.objects.create(
            file_number=self.matter,
            state='F',
            date=date.today(),
            description='Test',
            our_costs=['0'],
            our_costs_desc=['Work'],
        )
        lock_time_events_for_invoice(invoice)
        event.refresh_from_db()
        self.assertIsNotNone(event.locked_at)
        self.assertEqual(event.invoice_id, invoice.id)
