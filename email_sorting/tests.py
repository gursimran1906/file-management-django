from datetime import datetime, timedelta

from django.test import TestCase
from django.utils import timezone

from backend.models import MatterEmails
from email_sorting import utils
from email_sorting.models import EmailSyncState
from email_sorting.utils import (
    DEFAULT_WINDOW,
    MAX_LOOKBACK,
    OVERLAP_BUFFER,
    Sorting,
    _save_sync_state,
)


def _email(web_link, subject='Hello ABC1234567', from_addr='client@example.com',
           to_addr='mail@anpsolicitors.com'):
    return {
        'subject': subject,
        'from': {'emailAddress': {'address': from_addr, 'name': 'Sender'}},
        'toRecipients': [{'emailAddress': {'address': to_addr}}],
        'body': {'content': 'This is a short test email body.'},
        'receivedDateTime': '2026-08-05T09:00:00Z',
        'webLink': web_link,
    }


class ProcessEmailDedupTests(TestCase):
    def setUp(self):
        self.sorting = Sorting()

    def test_inserts_new_email(self):
        added = self.sorting.process_email(_email('https://outlook/msg-new'))
        self.assertTrue(added)
        self.assertEqual(MatterEmails.objects.filter(link='https://outlook/msg-new').count(), 1)

    def test_skips_duplicate_weblink(self):
        link = 'https://outlook/msg-dup'
        MatterEmails.objects.create(link=link, subject='pre-existing')
        result = self.sorting.process_email(_email(link))
        self.assertFalse(result)
        # Still exactly one row — no duplicate created.
        self.assertEqual(MatterEmails.objects.filter(link=link).count(), 1)

    def test_reprocessing_is_idempotent(self):
        email = _email('https://outlook/msg-idem')
        self.assertTrue(self.sorting.process_email(email))
        self.assertFalse(self.sorting.process_email(email))
        self.assertEqual(MatterEmails.objects.filter(link='https://outlook/msg-idem').count(), 1)


class WatermarkWindowTests(TestCase):
    def setUp(self):
        self.sorting = Sorting()

    def test_uses_default_window_when_no_watermark(self):
        run_start = timezone.now()
        start = self.sorting._compute_live_start(run_start)
        self.assertEqual(start, run_start - DEFAULT_WINDOW)

    def test_looks_back_to_watermark_over_a_long_outage(self):
        run_start = timezone.now()
        state = EmailSyncState.load()
        state.last_success_at = run_start - timedelta(hours=6)
        state.save()
        start = self.sorting._compute_live_start(run_start)
        # Spans the whole outage (minus the small overlap buffer), not a fixed 15 min.
        self.assertEqual(start, run_start - timedelta(hours=6) - OVERLAP_BUFFER)

    def test_safety_cap_bounds_a_very_old_watermark(self):
        run_start = timezone.now()
        state = EmailSyncState.load()
        state.last_success_at = run_start - timedelta(days=90)
        state.save()
        start = self.sorting._compute_live_start(run_start)
        self.assertEqual(start, run_start - MAX_LOOKBACK)


class SyncStateTests(TestCase):
    def test_success_advances_watermark(self):
        run_start = timezone.now()
        _save_sync_state(run_start, EmailSyncState.STATUS_SUCCESS, '', advance_success=True)
        state = EmailSyncState.load()
        self.assertEqual(state.last_success_at, run_start)
        self.assertEqual(state.last_status, EmailSyncState.STATUS_SUCCESS)

    def test_partial_does_not_advance_watermark(self):
        first = timezone.now() - timedelta(hours=1)
        _save_sync_state(first, EmailSyncState.STATUS_SUCCESS, '', advance_success=True)
        later = timezone.now()
        _save_sync_state(later, EmailSyncState.STATUS_PARTIAL, 'conveyancing/Inbox: 500',
                         advance_success=False)
        state = EmailSyncState.load()
        # Watermark stayed at the last clean run; last_run/status reflect the partial.
        self.assertEqual(state.last_success_at, first)
        self.assertEqual(state.last_run_at, later)
        self.assertEqual(state.last_status, EmailSyncState.STATUS_PARTIAL)
        self.assertIn('conveyancing/Inbox', state.last_error)

    def test_singleton_load_reuses_one_row(self):
        a = EmailSyncState.load()
        b = EmailSyncState.load()
        self.assertEqual(a.pk, b.pk)
        self.assertEqual(EmailSyncState.objects.count(), 1)


class GraphTimeTests(TestCase):
    def test_aware_datetime_formatted_as_utc(self):
        # 09:00 in Europe/London (BST, +1) -> 08:00Z
        dt = datetime(2026, 8, 5, 9, 0, 0,
                      tzinfo=timezone.get_fixed_timezone(60))
        self.assertEqual(utils._graph_time(dt), '2026-08-05T08:00:00Z')
