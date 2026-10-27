"""Tests for notes taken during a call, the call/note pairing, and the register.

The cases that matter most here are the collisions: two people on the phone at
once, one person with back-to-back calls, and a shared sign-in where the call
log cannot name the human at all.
"""
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from users.models import CustomUser

from ..models import (CallLogConfig, CallNote, CallRecord, Free30Mins,
                      Free30MinsAttendees, MatterAttendanceNotes)
from ..granola.markdown_to_quill import markdown_to_quill_json
from ..telephony import ingest, pairing
from ..telephony.match import build_matter_phone_index
from ..telephony.register import (build_register, group_by_day,
                                  notes_without_calls)
from .tests_telephony import call_row, make_client, make_matter, make_user


def make_call(start, *, duration=300, upn='fee@example.com', fee_earner=None,
              number='+447700900123', direction=CallRecord.DIRECTION_INBOUND,
              row_id='r1', call_id='c1', status=CallRecord.STATUS_PENDING):
    return CallRecord.objects.create(
        graph_row_id=row_id, call_id=call_id, direction=direction,
        internal_upn=upn, matched_fee_earner=fee_earner,
        external_number=number, external_number_normalized=number,
        start_datetime=start, end_datetime=start + timedelta(seconds=duration),
        duration_seconds=duration, status=status)


def make_note(user, start, *, minutes=5, direction=CallNote.DIRECTION_INBOUND,
              content='Spoke to the client about the sale.', **kw):
    return CallNote.objects.create(
        taken_by=user, created_by=user, direction=direction,
        started_at=start, ended_at=start + timedelta(minutes=minutes),
        content_md=content, **kw)


class PairingTests(TestCase):
    def setUp(self):
        self.config = CallLogConfig.get_solo()
        self.user = make_user('one', 'fee@example.com')
        self.now = timezone.now() - timedelta(minutes=30)

    def test_single_clear_candidate_is_attached_and_backfills_the_number(self):
        note = make_note(self.user, self.now, minutes=5)
        call = make_call(self.now + timedelta(seconds=5),
                         fee_earner=self.user, number='+447700900999')

        self.assertEqual(pairing.pair_note(note, self.config),
                         CallNote.PAIR_PAIRED)
        note.refresh_from_db()
        self.assertEqual(note.call_record_id, call.id)
        self.assertEqual(note.caller_number, '+447700900999')
        self.assertIsNotNone(note.paired_at)

    def test_the_call_log_wins_on_direction(self):
        note = make_note(self.user, self.now, direction=CallNote.DIRECTION_INBOUND)
        make_call(self.now, fee_earner=self.user,
                  direction=CallRecord.DIRECTION_OUTBOUND)

        pairing.pair_note(note, self.config)
        note.refresh_from_db()
        self.assertEqual(note.direction, CallNote.DIRECTION_OUTBOUND)

    def test_a_typed_number_is_not_overwritten(self):
        note = make_note(self.user, self.now, caller_number='07700 111222')
        make_call(self.now, fee_earner=self.user, number='+447700900123')

        pairing.pair_note(note, self.config)
        note.refresh_from_db()
        self.assertEqual(note.caller_number, '07700 111222')

    def test_pairing_marks_the_call_as_recorded(self):
        note = make_note(self.user, self.now)
        call = make_call(self.now, fee_earner=self.user)

        pairing.pair_note(note, self.config)
        call.refresh_from_db()
        self.assertEqual(call.status, CallRecord.STATUS_CREATED)
        self.assertIn('live call note', call.match_reason)

    # --- the concurrency cases ------------------------------------------------

    def test_two_people_on_the_phone_at_once_never_collide(self):
        other = make_user('two', 'other@example.com')
        call_a = make_call(self.now, fee_earner=self.user, row_id='a',
                           call_id='ca', number='+447700900111')
        call_b = make_call(self.now, fee_earner=other, upn='other@example.com',
                           row_id='b', call_id='cb', number='+447700900222')
        note_a = make_note(self.user, self.now)
        note_b = make_note(other, self.now)

        pairing.pair_note(note_a, self.config)
        pairing.pair_note(note_b, self.config)
        note_a.refresh_from_db(); note_b.refresh_from_db()
        self.assertEqual(note_a.call_record_id, call_a.id)
        self.assertEqual(note_b.call_record_id, call_b.id)

    def test_one_person_two_calls_that_fit_equally_asks_rather_than_guesses(self):
        make_call(self.now, fee_earner=self.user, row_id='a', call_id='ca',
                  number='+447700900111')
        make_call(self.now + timedelta(seconds=10), fee_earner=self.user,
                  row_id='b', call_id='cb', number='+447700900222')
        note = make_note(self.user, self.now, minutes=5)

        self.assertEqual(pairing.pair_note(note, self.config),
                         CallNote.PAIR_AMBIGUOUS)
        note.refresh_from_db()
        self.assertIsNone(note.call_record_id)
        self.assertEqual(len(note.candidate_calls), 2)
        self.assertEqual({c['number'] for c in note.candidate_calls},
                         {'+447700900111', '+447700900222'})

    def test_back_to_back_calls_go_to_the_one_that_actually_overlaps(self):
        overlapping = make_call(self.now, fee_earner=self.user, row_id='a',
                                call_id='ca', number='+447700900111')
        make_call(self.now + timedelta(minutes=9), fee_earner=self.user,
                  row_id='b', call_id='cb', number='+447700900222')
        note = make_note(self.user, self.now, minutes=5)

        self.assertEqual(pairing.pair_note(note, self.config),
                         CallNote.PAIR_PAIRED)
        note.refresh_from_db()
        self.assertEqual(note.call_record_id, overlapping.id)

    def test_a_call_already_taken_by_another_note_is_not_offered_twice(self):
        call = make_call(self.now, fee_earner=self.user)
        first = make_note(self.user, self.now)
        pairing.pair_note(first, self.config)

        second = make_note(self.user, self.now)
        pairing.pair_note(second, self.config)
        second.refresh_from_db()
        self.assertIsNone(second.call_record_id)
        self.assertEqual(CallNote.objects.filter(call_record=call).count(), 1)

    def test_a_call_the_sync_already_wrote_up_is_never_paired_again(self):
        call = make_call(self.now, fee_earner=self.user)
        matter = make_matter('ABC0010001', fee_earner=self.user)
        call.attendance_note = MatterAttendanceNotes.objects.create(
            file_number=matter, date=timezone.localdate(),
            start_time=timezone.localtime().time().replace(microsecond=0),
            finish_time=timezone.localtime().time().replace(microsecond=0),
            subject_line='Auto', person_attended=self.user, unit=1,
            content=markdown_to_quill_json('Created by the sync.'))
        call.status = CallRecord.STATUS_CREATED
        call.save()

        note = make_note(self.user, self.now)
        pairing.pair_note(note, self.config)
        note.refresh_from_db()
        self.assertIsNone(note.call_record_id)
        self.assertEqual(MatterAttendanceNotes.objects.count(), 1)

    # --- shared sign-ins ------------------------------------------------------

    def test_a_shared_signin_pairs_with_whoever_wrote_the_note(self):
        self.config.shared_line_upns = 'reception@example.co.uk'
        self.config.save()
        call = make_call(self.now, upn='reception@example.co.uk',
                         fee_earner=None)
        note = make_note(self.user, self.now)

        self.assertEqual(pairing.pair_note(note, self.config),
                         CallNote.PAIR_PAIRED)
        note.refresh_from_db()
        self.assertEqual(note.call_record_id, call.id)

    def test_a_shared_signin_with_two_notes_asks_both_authors(self):
        self.config.shared_line_upns = 'reception@example.co.uk'
        self.config.save()
        make_call(self.now, upn='reception@example.co.uk', fee_earner=None)
        other = make_user('two', 'other@example.com')
        note_a = make_note(self.user, self.now)
        make_note(other, self.now)

        self.assertEqual(pairing.pair_note(note_a, self.config),
                         CallNote.PAIR_AMBIGUOUS)
        note_a.refresh_from_db()
        self.assertIsNone(note_a.call_record_id)
        self.assertEqual(len(note_a.candidate_calls), 1)

    def test_an_unshared_signin_stays_with_its_own_user(self):
        make_call(self.now, upn='someone@example.com', fee_earner=None)
        note = make_note(self.user, self.now)

        pairing.pair_note(note, self.config)
        note.refresh_from_db()
        self.assertIsNone(note.call_record_id)
        self.assertEqual(note.pairing_status, CallNote.PAIR_WAITING)

    # --- waiting and giving up ------------------------------------------------

    def test_a_note_waits_inside_the_grace_window(self):
        note = make_note(self.user, timezone.now() - timedelta(hours=3))
        self.assertEqual(pairing.pair_note(note, self.config),
                         CallNote.PAIR_WAITING)

    def test_a_note_settles_as_unmatched_once_the_grace_is_up(self):
        note = make_note(self.user, timezone.now() - timedelta(hours=60))
        self.assertEqual(pairing.pair_note(note, self.config),
                         CallNote.PAIR_NONE)

    def test_outside_the_pairing_window_nothing_is_offered(self):
        make_call(self.now + timedelta(minutes=40), fee_earner=self.user)
        note = make_note(self.user, self.now, minutes=5)
        pairing.pair_note(note, self.config)
        note.refresh_from_db()
        self.assertIsNone(note.call_record_id)

    def test_the_bulk_pass_reports_what_it_did(self):
        make_call(self.now, fee_earner=self.user)
        make_note(self.user, self.now)
        make_note(self.user, timezone.now() - timedelta(hours=60))

        paired, ambiguous, settled = pairing.pair_waiting_notes(self.config)
        self.assertEqual((paired, ambiguous, settled), (1, 0, 1))

    # --- resolving by hand ----------------------------------------------------

    def test_the_author_can_pick_which_call_was_theirs(self):
        mine = make_call(self.now, fee_earner=self.user, row_id='a',
                         call_id='ca', number='+447700900111')
        make_call(self.now + timedelta(seconds=10), fee_earner=self.user,
                  row_id='b', call_id='cb', number='+447700900222')
        note = make_note(self.user, self.now)
        pairing.pair_note(note, self.config)

        pairing.choose_call(note, mine)
        note.refresh_from_db()
        self.assertEqual(note.call_record_id, mine.id)
        self.assertEqual(note.pairing_status, CallNote.PAIR_PAIRED)
        self.assertIsNone(note.candidate_calls)

    def test_two_authors_cannot_both_claim_the_same_call(self):
        call = make_call(self.now, fee_earner=self.user)
        first = make_note(self.user, self.now)
        pairing.choose_call(first, call)

        second = make_note(self.user, self.now)
        with self.assertRaises(ValueError):
            pairing.choose_call(second, call)


class IngestGuardTests(TestCase):
    """A call someone wrote up live must not also get an auto-generated note."""

    def setUp(self):
        self.config = CallLogConfig.get_solo()
        self.user = make_user('one', 'fee@example.com')
        self.matter = make_matter('ABC0010001', fee_earner=self.user,
                                  client_number='07700 900123')
        self.index = build_matter_phone_index()
        self.start = timezone.now() - timedelta(minutes=20)

    def _row(self, **kw):
        row = call_row(**kw)
        row['startDateTime'] = self.start.strftime('%Y-%m-%dT%H:%M:%SZ')
        row['endDateTime'] = (self.start + timedelta(minutes=5)).strftime(
            '%Y-%m-%dT%H:%M:%SZ')
        return row

    def test_a_live_note_stops_the_second_note_being_generated(self):
        note = make_note(self.user, self.start, minutes=5)
        call = ingest._ingest_row(self._row(), CallRecord.SOURCE_PSTN,
                                  self.index, self.config)

        self.assertEqual(MatterAttendanceNotes.objects.count(), 0)
        self.assertEqual(call.status, CallRecord.STATUS_CREATED)
        note.refresh_from_db()
        self.assertEqual(note.call_record_id, call.id)
        self.assertEqual(call.matched_file_id, self.matter.id)

    def test_without_a_live_note_the_sync_still_auto_creates(self):
        call = ingest._ingest_row(self._row(), CallRecord.SOURCE_PSTN,
                                  self.index, self.config)
        self.assertEqual(MatterAttendanceNotes.objects.count(), 1)
        self.assertEqual(call.status, CallRecord.STATUS_CREATED)

    def test_two_possible_notes_leave_the_call_to_the_pairing_pass(self):
        self.config.shared_line_upns = 'fee@example.com'
        self.config.save()
        make_note(self.user, self.start, minutes=5)
        make_note(make_user('two', 'other@example.com'), self.start, minutes=5)

        call = ingest._ingest_row(self._row(), CallRecord.SOURCE_PSTN,
                                  self.index, self.config)
        # Ambiguous: the sync neither invents a note nor picks an author.
        self.assertEqual(MatterAttendanceNotes.objects.count(), 1)
        self.assertEqual(call.status, CallRecord.STATUS_CREATED)


class RegisterTests(TestCase):
    def setUp(self):
        self.config = CallLogConfig.get_solo()
        self.user = make_user('one', 'fee@example.com')
        self.matter = make_matter('ABC0010001', fee_earner=self.user)
        self.today = timezone.localdate()
        self.long_ago = timezone.now() - timedelta(hours=72)

    def _register(self, **kw):
        return build_register(self.today - timedelta(days=7), self.today,
                              config=self.config, **kw)

    def test_a_call_nobody_wrote_up_is_unallocated(self):
        make_call(self.long_ago, fee_earner=self.user)
        rows, counts = self._register()
        self.assertEqual(counts['unallocated'], 1)
        self.assertTrue(rows[0]['unallocated'])

    def test_a_recent_call_is_still_inside_the_grace_window(self):
        make_call(timezone.now() - timedelta(minutes=5), fee_earner=self.user)
        rows, counts = self._register()
        self.assertEqual(counts['unallocated'], 0)
        self.assertEqual(rows[0]['kind'], 'waiting')

    def test_a_paired_note_reports_where_the_call_was_filed(self):
        call = make_call(self.long_ago, fee_earner=self.user)
        note = make_note(self.user, self.long_ago, matter=self.matter,
                         outcome=CallNote.OUTCOME_ATTENDANCE)
        pairing.attach(note, call)

        rows, counts = self._register()
        self.assertEqual(counts['unallocated'], 0)
        self.assertEqual(rows[0]['kind'], 'call_note')
        self.assertIn('ABC0010001', rows[0]['label'])

    def test_a_hand_written_attendance_note_counts_as_recorded(self):
        local = timezone.localtime(self.long_ago)
        make_call(self.long_ago, fee_earner=self.user, duration=300)
        MatterAttendanceNotes.objects.create(
            file_number=self.matter, date=local.date(),
            start_time=local.time().replace(microsecond=0),
            finish_time=(local + timedelta(minutes=6)).time().replace(microsecond=0),
            subject_line='Call with client', is_charged=True,
            content=markdown_to_quill_json('Rang the client.'),
            person_attended=self.user, unit=1)

        rows, counts = self._register()
        self.assertEqual(counts['unallocated'], 0)
        self.assertEqual(rows[0]['kind'], 'hand_written')

    def test_a_note_by_someone_else_does_not_cover_the_call(self):
        local = timezone.localtime(self.long_ago)
        other = make_user('two', 'other@example.com')
        make_call(self.long_ago, fee_earner=self.user)
        MatterAttendanceNotes.objects.create(
            file_number=self.matter, date=local.date(),
            start_time=local.time().replace(microsecond=0),
            finish_time=(local + timedelta(minutes=6)).time().replace(microsecond=0),
            subject_line='Someone else', is_charged=True,
            content=markdown_to_quill_json('Someone else.'),
            person_attended=other, unit=1)

        rows, counts = self._register()
        self.assertEqual(counts['unallocated'], 1)

    def test_a_free30_recorded_against_the_number_counts_as_recorded(self):
        local = timezone.localtime(self.long_ago)
        make_call(self.long_ago, fee_earner=None, upn='nobody@example.com',
                  number='+447700900123')
        attendee = Free30MinsAttendees.objects.create(
            name='Caller', email='', contact_number='07700 900123')
        meeting = Free30Mins.objects.create(
            notes=markdown_to_quill_json('New enquiry.'), date=local.date(),
            start_time=local.time().replace(microsecond=0),
            finish_time=(local + timedelta(minutes=30)).time().replace(microsecond=0))
        meeting.attendees.set([attendee])

        rows, counts = self._register()
        self.assertEqual(counts['unallocated'], 0)
        self.assertEqual(rows[0]['kind'], 'hand_written')

    def test_an_unanswered_call_is_listed_but_not_unallocated(self):
        make_call(self.long_ago, fee_earner=self.user, duration=0)
        rows, counts = self._register()
        self.assertEqual(counts['unallocated'], 0)
        self.assertEqual(rows[0]['kind'], 'missed')
        self.assertEqual(rows[0]['label'], 'No answer')

    def test_an_enquiry_flag_and_a_dismissal_are_not_unallocated(self):
        make_call(self.long_ago, fee_earner=self.user, row_id='a', call_id='ca',
                  status=CallRecord.STATUS_ENQUIRY)
        make_call(self.long_ago, fee_earner=self.user, row_id='b', call_id='cb',
                  status=CallRecord.STATUS_IGNORED)
        rows, counts = self._register()
        self.assertEqual(counts['unallocated'], 0)
        self.assertEqual({r['kind'] for r in rows}, {'enquiry', 'dismissed'})

    def test_direction_and_unallocated_filters(self):
        make_call(self.long_ago, fee_earner=self.user, row_id='a', call_id='ca',
                  direction=CallRecord.DIRECTION_OUTBOUND)
        call = make_call(self.long_ago, fee_earner=self.user, row_id='b',
                         call_id='cb', direction=CallRecord.DIRECTION_INBOUND)
        note = make_note(self.user, self.long_ago, matter=self.matter,
                         outcome=CallNote.OUTCOME_ATTENDANCE)
        pairing.attach(note, call)

        rows, counts = self._register(direction=CallRecord.DIRECTION_OUTBOUND)
        self.assertEqual(len(rows), 1)
        self.assertEqual(counts['outbound'], 1)

        rows, _ = self._register(only_unallocated=True)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]['unallocated'])

    def test_the_register_groups_calls_by_day(self):
        make_call(self.long_ago, fee_earner=self.user, row_id='a', call_id='ca')
        make_call(self.long_ago - timedelta(days=1), fee_earner=self.user,
                  row_id='b', call_id='cb')
        rows, _ = self._register()
        groups = group_by_day(rows)
        self.assertEqual(len(groups), 2)
        self.assertEqual(sum(len(g['rows']) for g in groups), 2)
        self.assertEqual(groups[0]['unallocated'], 1)

    def test_notes_with_no_call_are_listed_for_reconciliation(self):
        make_note(self.user, timezone.now() - timedelta(hours=2))
        orphans = notes_without_calls(self.today - timedelta(days=7), self.today)
        self.assertEqual(len(orphans), 1)


class CallNoteViewTests(TestCase):
    def setUp(self):
        self.config = CallLogConfig.get_solo()
        self.user = make_user('one', 'fee@example.com')
        self.user.set_password('pw')
        self.user.save()
        self.matter = make_matter('ABC0010001', fee_earner=self.user)
        self.client.force_login(self.user)

    def test_one_click_starts_a_note_and_the_clock(self):
        response = self.client.post(reverse('call_note_start'))
        note = CallNote.objects.get()
        self.assertRedirects(response,
                             reverse('call_note_detail', args=[note.id]))
        self.assertEqual(note.taken_by_id, self.user.id)
        self.assertEqual(note.direction, CallNote.DIRECTION_INBOUND)
        self.assertTrue(note.is_live)
        self.assertIsNone(note.ended_at)

    def test_clicking_take_a_call_twice_returns_to_the_same_note(self):
        self.client.post(reverse('call_note_start'))
        first = CallNote.objects.get()
        response = self.client.post(reverse('call_note_start'))
        self.assertEqual(CallNote.objects.count(), 1)
        self.assertRedirects(response,
                             reverse('call_note_detail', args=[first.id]))

    def test_a_genuinely_new_call_later_gets_its_own_note(self):
        stale = make_note(self.user, timezone.now() - timedelta(hours=2))
        stale.ended_at = None
        stale.save()
        self.client.post(reverse('call_note_start'))
        self.assertEqual(CallNote.objects.count(), 2)

    def test_a_note_left_open_elsewhere_is_surfaced_not_abandoned(self):
        stale = make_note(self.user, timezone.now() - timedelta(hours=2))
        stale.ended_at = None
        stale.save()
        self.client.post(reverse('call_note_start'))
        fresh = CallNote.objects.exclude(pk=stale.pk).get()
        response = self.client.get(reverse('call_note_detail', args=[fresh.id]))
        self.assertEqual(response.context['other_open'].pk, stale.pk)
        self.assertContains(response, 'another note still open')

    def test_writing_up_an_unallocated_call_prefills_the_number(self):
        self.client.post(reverse('call_note_start'),
                         {'direction': 'outbound',
                          'caller_number': '+447700900123'})
        note = CallNote.objects.get()
        self.assertEqual(note.direction, CallNote.DIRECTION_OUTBOUND)
        self.assertEqual(note.caller_number, '+447700900123')

    def test_autosave_keeps_the_typing(self):
        self.client.post(reverse('call_note_start'))
        note = CallNote.objects.get()
        response = self.client.post(
            reverse('call_note_autosave', args=[note.id]),
            {'content_md': 'Client rang about the survey.',
             'caller_name': 'Mrs Patel'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])
        note.refresh_from_db()
        self.assertEqual(note.content_md, 'Client rang about the survey.')
        self.assertEqual(note.caller_name, 'Mrs Patel')

    def test_someone_elses_note_is_not_yours_to_edit(self):
        note = make_note(make_user('two', 'other@example.com'), timezone.now())
        response = self.client.post(
            reverse('call_note_autosave', args=[note.id]), {'content_md': 'x'})
        self.assertEqual(response.status_code, 403)

    def test_ending_the_call_stops_the_clock(self):
        self.client.post(reverse('call_note_start'))
        note = CallNote.objects.get()
        self.client.post(reverse('call_note_end', args=[note.id]))
        note.refresh_from_db()
        self.assertIsNotNone(note.ended_at)
        self.assertFalse(note.is_live)

    def test_saving_to_a_matter_writes_the_attendance_note(self):
        start = timezone.now() - timedelta(minutes=13)
        note = make_note(self.user, start, minutes=13)
        response = self.client.post(
            reverse('call_note_save', args=[note.id]),
            {'outcome': 'attendance', 'file_number': 'ABC0010001',
             'content_md': 'Discussed the completion date.', 'is_charged': 'on',
             'subject': 'Completion date'})
        self.assertRedirects(response,
                             reverse('call_note_detail', args=[note.id]))
        note.refresh_from_db()
        self.assertEqual(note.outcome, CallNote.OUTCOME_ATTENDANCE)
        written = MatterAttendanceNotes.objects.get()
        self.assertEqual(written.file_number_id, self.matter.id)
        self.assertEqual(written.person_attended_id, self.user.id)
        self.assertEqual(written.subject_line, 'Completion date')
        self.assertEqual(written.unit, 3)          # 13 minutes -> 3 units
        self.assertTrue(written.is_charged)
        self.assertEqual(note.attendance_note_id, written.id)

    def test_saving_twice_updates_rather_than_duplicates(self):
        note = make_note(self.user, timezone.now() - timedelta(minutes=5))
        data = {'outcome': 'attendance', 'file_number': 'ABC0010001',
                'content_md': 'First pass.'}
        self.client.post(reverse('call_note_save', args=[note.id]), data)
        data['content_md'] = 'Second pass.'
        self.client.post(reverse('call_note_save', args=[note.id]), data)
        self.assertEqual(MatterAttendanceNotes.objects.count(), 1)

    def test_an_unknown_file_number_keeps_the_note_and_files_nothing(self):
        note = make_note(self.user, timezone.now() - timedelta(minutes=5))
        self.client.post(reverse('call_note_save', args=[note.id]),
                         {'outcome': 'attendance', 'file_number': 'NOPE',
                          'content_md': 'Typed words survive.'})
        note.refresh_from_db()
        self.assertEqual(MatterAttendanceNotes.objects.count(), 0)
        self.assertEqual(note.content_md, 'Typed words survive.')
        self.assertEqual(note.outcome, CallNote.OUTCOME_DRAFTING)

    def test_saving_as_a_free30_records_the_caller_as_the_attendee(self):
        note = make_note(self.user, timezone.now() - timedelta(minutes=20),
                         minutes=20)
        self.client.post(reverse('call_note_save', args=[note.id]),
                         {'outcome': 'free30', 'caller_name': 'Mr New',
                          'caller_number': '07700 900555',
                          'caller_email': 'new@example.com',
                          'content_md': 'Wants to sell a flat.'})
        note.refresh_from_db()
        meeting = Free30Mins.objects.get()
        self.assertEqual(note.free30_meeting_id, meeting.id)
        self.assertEqual(meeting.fee_earner_id, self.user.id)
        attendee = meeting.attendees.get()
        self.assertEqual(attendee.name, 'Mr New')
        self.assertEqual(attendee.contact_number, '07700 900555')

    def test_an_enquiry_is_a_record_in_its_own_right(self):
        note = make_note(self.user, timezone.now() - timedelta(minutes=4))
        self.client.post(reverse('call_note_save', args=[note.id]),
                         {'outcome': 'enquiry', 'caller_name': 'Ms Caller',
                          'caller_number': '07700 900777',
                          'content_md': 'Asked whether we do lasting powers.',
                          'follow_up': 'Sending the LPA leaflet.'})
        note.refresh_from_db()
        self.assertEqual(note.outcome, CallNote.OUTCOME_ENQUIRY)
        self.assertEqual(note.caller_name, 'Ms Caller')
        self.assertEqual(note.follow_up, 'Sending the LPA leaflet.')
        self.assertEqual(MatterAttendanceNotes.objects.count(), 0)
        self.assertEqual(Free30Mins.objects.count(), 0)

    def test_discarding_records_nothing(self):
        note = make_note(self.user, timezone.now() - timedelta(minutes=1))
        self.client.post(reverse('call_note_save', args=[note.id]),
                         {'outcome': 'discarded'})
        note.refresh_from_db()
        self.assertEqual(note.outcome, CallNote.OUTCOME_DISCARDED)
        self.assertEqual(MatterAttendanceNotes.objects.count(), 0)

    def test_the_author_resolves_an_ambiguous_pairing_from_the_page(self):
        start = timezone.now() - timedelta(minutes=30)
        mine = make_call(start, fee_earner=self.user, row_id='a', call_id='ca',
                         number='+447700900111')
        make_call(start + timedelta(seconds=10), fee_earner=self.user,
                  row_id='b', call_id='cb', number='+447700900222')
        note = make_note(self.user, start)
        pairing.pair_note(note, self.config)

        self.client.post(reverse('call_note_choose_call', args=[note.id]),
                         {'call_record': str(mine.id)})
        note.refresh_from_db()
        self.assertEqual(note.call_record_id, mine.id)

    def test_the_best_fitting_call_is_the_one_offered_first(self):
        start = timezone.now() - timedelta(minutes=30)
        # The better fit starts earlier, so the model's own "latest first"
        # ordering would offer the wrong one as the default choice.
        best = make_call(start, duration=330, fee_earner=self.user, row_id='a',
                         call_id='ca', number='+447700900111')
        make_call(start + timedelta(minutes=1), duration=300,
                  fee_earner=self.user, row_id='b', call_id='cb',
                  number='+447700900222')
        note = make_note(self.user, start, minutes=6)
        pairing.pair_note(note, self.config)

        response = self.client.get(reverse('call_note_detail', args=[note.id]))
        self.assertEqual([c.id for c in response.context['candidates']][0],
                         best.id)

    def test_a_call_that_was_not_offered_cannot_be_claimed(self):
        start = timezone.now() - timedelta(minutes=30)
        other = make_user('two', 'other@example.com')
        theirs = make_call(start, fee_earner=other, upn='other@example.com',
                           row_id='x', call_id='cx')
        note = make_note(self.user, start)
        pairing.mark_ambiguous(note, [])

        self.client.post(reverse('call_note_choose_call', args=[note.id]),
                         {'call_record': str(theirs.id)})
        note.refresh_from_db()
        self.assertIsNone(note.call_record_id)

    def test_the_author_can_say_it_was_not_a_teams_call(self):
        start = timezone.now() - timedelta(minutes=30)
        make_call(start, fee_earner=self.user, row_id='a', call_id='ca')
        make_call(start + timedelta(seconds=10), fee_earner=self.user,
                  row_id='b', call_id='cb')
        note = make_note(self.user, start)
        pairing.pair_note(note, self.config)

        self.client.post(reverse('call_note_choose_call', args=[note.id]),
                         {'call_record': 'none'})
        note.refresh_from_db()
        self.assertEqual(note.pairing_status, CallNote.PAIR_NONE)
        self.assertIsNone(note.candidate_calls)

    def test_the_number_lookup_finds_the_matter(self):
        note = make_note(self.user, timezone.now() - timedelta(minutes=5))
        response = self.client.post(
            reverse('call_note_lookup_number', args=[note.id]),
            {'caller_number': '07700 900123'})
        self.assertEqual(response.status_code, 200)
        results = response.json()['results']
        self.assertEqual(results[0]['file_number'], 'ABC0010001')

    def test_the_note_page_renders(self):
        note = make_note(self.user, timezone.now() - timedelta(minutes=5))
        response = self.client.get(reverse('call_note_detail', args=[note.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'The note')

    def test_the_register_page_renders_and_counts_unallocated(self):
        make_call(timezone.now() - timedelta(hours=72), fee_earner=self.user)
        response = self.client.get(reverse('calls_register'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Unallocated')
        self.assertEqual(response.context['counts']['unallocated'], 1)

    def test_the_register_panel_is_fetchable_on_its_own(self):
        response = self.client.get(reverse('calls_register'), {'partial': '1'})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'telephony/_register_panel.html')

    def test_settings_flags_staff_whose_calls_can_never_be_attributed(self):
        self.user.is_manager = True
        self.user.save()
        CustomUser.objects.create_user(username='nom', email='', password='pw',
                                       first_name='No', last_name='Mail',
                                       max_holidays_in_year=0)
        response = self.client.get(reverse('calls_settings'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No Mail')

    def test_the_dashboard_offers_take_a_call(self):
        response = self.client.get(reverse('user_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Take a call')
