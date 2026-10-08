"""Tests for the Granola integration: title parsing, markdown conversion and
the ingest decision logic (auto-create vs review inbox vs dedupe)."""
import json

from django.test import TestCase

from users.models import CustomUser
from ..models import (ClientContactDetails, Free30Mins, GranolaImportedNote,
                     MatterAttendanceNotes, MatterType, WIP)
from ..granola.parse import (extract_file_ref, parse_fee_earner,
                             parse_meeting_times, parse_parties, parse_title)
from ..granola.markdown_to_quill import markdown_to_html, markdown_to_quill_json
from ..granola import ingest


def make_matter(file_number='GRN0001', fee_earner=None):
    client = ClientContactDetails.objects.create(
        name='Test Client', occupation='Retired', address_line1='1 Test Street',
        address_line2='', county='Essex', postcode='SS7 1QT',
        email='client@example.com', contact_number='0123456789',
    )
    matter_type = MatterType.objects.create(type='Probate')
    return WIP.objects.create(
        file_number=file_number, client1=client, matter_description='Test matter',
        matter_type=matter_type, funding='Pvt', fee_earner=fee_earner,
    )


class FakeClient:
    """Stands in for GranolaClient: get_note returns a canned payload."""
    def __init__(self, note):
        self.note = note

    def get_note(self, note_id, include_transcript=True):
        return self.note


class ParseTitleTests(TestCase):
    def test_charged_code(self):
        p = parse_title('[A12345] Call with client')
        self.assertEqual(p.file_number, 'A12345')
        self.assertTrue(p.is_charged)
        self.assertEqual(p.subject, 'Call with client')

    def test_not_charged_flag(self):
        for title in ('[A12345 NC] Catch-up', '[A12345/NC] Catch-up'):
            p = parse_title(title)
            self.assertEqual(p.file_number, 'A12345')
            self.assertFalse(p.is_charged, title)

    def test_no_code_routes_to_inbox(self):
        p = parse_title('Meeting with no code')
        self.assertIsNone(p.file_number)
        self.assertTrue(p.is_charged)

    def test_file_number_uppercased_and_trimmed(self):
        p = parse_title('[ b-99 ] Spaced')
        self.assertEqual(p.file_number, 'B-99')


class ExtractFileRefTests(TestCase):
    def test_labelled_form(self):
        ref = extract_file_ref('Meeting summary\n\nFile number: ABC0010001')
        self.assertEqual(ref.file_number, 'ABC0010001')
        self.assertTrue(ref.is_charged)

    def test_bracketed_form(self):
        ref = extract_file_ref('notes\n[ABC0010001]\nmore')
        self.assertEqual(ref.file_number, 'ABC0010001')

    def test_not_charged(self):
        ref = extract_file_ref('Matter no ABC0010001 (NC)')
        self.assertEqual(ref.file_number, 'ABC0010001')
        self.assertFalse(ref.is_charged)

    def test_lowercased_is_normalised(self):
        self.assertEqual(extract_file_ref('ref: abc0010001').file_number, 'ABC0010001')

    def test_none_when_absent(self):
        self.assertIsNone(extract_file_ref('just a chat, no file').file_number)


class ParseFeeEarnerTests(TestCase):
    def test_staff_code(self):
        self.assertEqual(parse_fee_earner('Notes\nFee earner: ABC\nmore'), 'ABC')

    def test_hyphen_and_case_insensitive(self):
        self.assertEqual(parse_fee_earner('FEE-EARNER: xy'), 'xy')

    def test_attended_by_and_full_name(self):
        self.assertEqual(parse_fee_earner('Attended by: Jane Smith'), 'Jane Smith')

    def test_none_when_absent(self):
        self.assertIsNone(parse_fee_earner('a chat with no attribution'))


class MarkdownConversionTests(TestCase):
    def test_html_renders_and_sanitises(self):
        html = markdown_to_html('# Title\n\n- a\n- b\n\n**bold**')
        self.assertIn('<h1>Title</h1>', html)
        self.assertIn('<li>a</li>', html)
        self.assertIn('<strong>bold</strong>', html)

    def test_script_is_stripped(self):
        html = markdown_to_html('hi <script>alert(1)</script> there')
        self.assertNotIn('<script>', html)

    def test_quill_json_shape(self):
        data = json.loads(markdown_to_quill_json('**hi** there'))
        self.assertIn('delta', data)
        self.assertIn('<strong>hi</strong>', data['html'])

    def test_empty_input(self):
        data = json.loads(markdown_to_quill_json(''))
        self.assertEqual(data, {'delta': '', 'html': ''})


class IngestTests(TestCase):
    def _note(self, **overrides):
        note = {
            'id': 'note-1',
            'title': '[GRN0001] Call with client',
            'summary': '## Discussion\n\nFee earner: FEE\n\n- agreed next steps',
            'transcript': [
                {'speaker': 'Lawyer', 'text': 'Hello'},
                {'speaker': 'Client', 'text': 'Hi'},
            ],
            'created_at': '2026-06-10T10:05:00+01:00',
            'calendar_event': {
                'scheduled_start_time': '2026-06-10T10:00:00+01:00',
                'scheduled_end_time': '2026-06-10T10:30:00+01:00',
            },
            'owner': {'email': 'fee@example.com'},
        }
        note.update(overrides)
        return note

    def setUp(self):
        self.fee_earner = CustomUser.objects.create_user(
            username='FEE', email='fee@example.com', first_name='Fee',
            last_name='Earner', password='x', max_holidays_in_year=20,
            is_matter_fee_earner=True,
        )

    def test_auto_create_when_matter_matches(self):
        matter = make_matter('GRN0001', fee_earner=self.fee_earner)
        note = self._note()
        imported = ingest._ingest_note(FakeClient(note), note)

        self.assertEqual(imported.status, GranolaImportedNote.STATUS_CREATED)
        self.assertIsNotNone(imported.attendance_note)
        an = imported.attendance_note
        self.assertEqual(an.file_number, matter)
        self.assertEqual(an.person_attended, self.fee_earner)
        self.assertEqual(an.unit, 5)  # 30 minutes / 6 = 5 units
        self.assertTrue(an.is_charged)
        self.assertEqual(an.subject_line, 'Call with client')
        self.assertIn('Discussion', an.content.html)
        # transcript captured on the ledger row
        self.assertIn('Lawyer: Hello', imported.transcript)

    def test_file_number_picked_up_from_body(self):
        matter = make_matter('GRN0001', fee_earner=self.fee_earner)
        note = self._note(title='Client call',  # no code in the title
                          summary='## Notes\n\nFile number: GRN0001\nFee earner: FEE\n\n- agreed steps')
        imported = ingest._ingest_note(FakeClient(note), note)
        self.assertEqual(imported.status, GranolaImportedNote.STATUS_CREATED)
        self.assertEqual(imported.parsed_file_number, 'GRN0001')
        self.assertEqual(imported.attendance_note.file_number, matter)
        # Title (no code) is used verbatim as the subject line.
        self.assertEqual(imported.attendance_note.subject_line, 'Client call')

    def test_not_charged_from_body(self):
        make_matter('GRN0001', fee_earner=self.fee_earner)
        note = self._note(title='Client call',
                          summary='File number: GRN0001 (NC)\nFee earner: FEE')
        imported = ingest._ingest_note(FakeClient(note), note)
        self.assertFalse(imported.attendance_note.is_charged)

    def test_not_charged_flag_propagates(self):
        make_matter('GRN0001', fee_earner=self.fee_earner)
        note = self._note(title='[GRN0001 NC] Internal call')
        imported = ingest._ingest_note(FakeClient(note), note)
        self.assertFalse(imported.attendance_note.is_charged)

    def test_unknown_file_number_goes_to_inbox(self):
        note = self._note(title='[NOPE99] Mystery matter')
        imported = ingest._ingest_note(FakeClient(note), note)
        self.assertEqual(imported.status, GranolaImportedNote.STATUS_PENDING)
        self.assertIsNone(imported.attendance_note)
        self.assertEqual(imported.parsed_file_number, 'NOPE99')
        self.assertEqual(MatterAttendanceNotes.objects.count(), 0)

    def test_no_code_goes_to_inbox(self):
        note = self._note(title='Just a chat')
        imported = ingest._ingest_note(FakeClient(note), note)
        self.assertEqual(imported.status, GranolaImportedNote.STATUS_PENDING)
        self.assertEqual(imported.parsed_file_number, '')

    def test_dedupe_skips_already_imported(self):
        make_matter('GRN0001', fee_earner=self.fee_earner)
        note = self._note()
        ingest._ingest_note(FakeClient(note), note)
        again = ingest._ingest_note(FakeClient(note), note)
        self.assertIsNone(again)
        self.assertEqual(GranolaImportedNote.objects.count(), 1)
        self.assertEqual(MatterAttendanceNotes.objects.count(), 1)

    def test_fee_earner_matched_from_body(self):
        # The default fixture carries a "Fee earner: FEE" line in the body.
        note = self._note(title='Unmatched matter')
        imported = ingest._ingest_note(FakeClient(note), note)
        self.assertEqual(imported.matched_fee_earner, self.fee_earner)

    def test_no_fee_earner_line_leaves_unmatched(self):
        note = self._note(title='Unmatched matter', summary='Just a chat, no code.')
        imported = ingest._ingest_note(FakeClient(note), note)
        self.assertIsNone(imported.matched_fee_earner)

    def test_missing_fee_earner_goes_to_inbox(self):
        # Matter + a calendar window, but no fee-earner code -> Allocate.
        make_matter('GRN0001', fee_earner=self.fee_earner)
        note = self._note(summary='File number: GRN0001\nDiscussion, no code.')
        imported = ingest._ingest_note(FakeClient(note), note)
        self.assertEqual(imported.status, GranolaImportedNote.STATUS_PENDING)
        self.assertIsNone(imported.attendance_note)

    def test_unit_from_calendar_event(self):
        # The default fixture carries a 10:00–10:30 calendar event (30 min -> 5).
        make_matter('GRN0001', fee_earner=self.fee_earner)
        note = self._note()
        imported = ingest._ingest_note(FakeClient(note), note)
        self.assertEqual(imported.attendance_note.unit, 5)

    def test_meeting_window_from_body_when_no_calendar_event(self):
        # Ad-hoc recording: no calendar_event, so the window comes from the body.
        make_matter('GRN0001', fee_earner=self.fee_earner)
        note = self._note(summary=('File number: GRN0001\nFee earner: FEE\n'
                                   'Start Time: 10:00 ; Finish Time: 10:30\n'))
        note.pop('calendar_event')
        imported = ingest._ingest_note(FakeClient(note), note)
        self.assertEqual(imported.status, GranolaImportedNote.STATUS_CREATED)
        self.assertIsNotNone(imported.meeting_end)
        self.assertEqual(imported.attendance_note.unit, 5)  # 30 min / 6

    def test_body_finish_completes_calendar_start(self):
        # Calendar event with a start but no end -> body supplies the finish.
        make_matter('GRN0001', fee_earner=self.fee_earner)
        note = self._note(summary='File number: GRN0001\nFee earner: FEE\nFinish Time: 11:00\n')
        note['calendar_event'] = {
            'scheduled_start_time': '2026-06-10T10:00:00+01:00'}
        imported = ingest._ingest_note(FakeClient(note), note)
        self.assertEqual(imported.attendance_note.unit, 10)  # 60 min / 6

    def test_no_end_time_goes_to_inbox(self):
        # An incomplete window (no finish) can't produce a reliable unit, so the
        # note waits in Allocate for the times to be filled in rather than filing.
        make_matter('GRN0001', fee_earner=self.fee_earner)
        note = self._note(summary='File number: GRN0001\nFee earner: FEE\nNo times given.')
        note.pop('calendar_event')
        imported = ingest._ingest_note(FakeClient(note), note)
        self.assertIsNone(imported.meeting_end)
        self.assertEqual(imported.status, GranolaImportedNote.STATUS_PENDING)
        self.assertIsNone(imported.attendance_note)


class ParsePartiesTests(TestCase):
    def test_multiple_parties_with_inline_address(self):
        md = ('## Info of Parties\n'
              'Party 1\n'
              '- Name: John Smith\n'
              '- Email: john@example.com\n'
              '- Phone: 07123 456789\n'
              '- Address: 1 High Street, London, Greater London, SW1A 1AA\n\n'
              'Party 2\n'
              '- Name: Jane Doe\n'
              '- Email: jane@example.com\n')
        parties = parse_parties(md)
        self.assertEqual(len(parties), 2)
        self.assertEqual(parties[0]['name'], 'John Smith')
        self.assertEqual(parties[0]['contact_number'], '07123 456789')
        self.assertEqual(parties[0]['postcode'], 'SW1A 1AA')
        self.assertEqual(parties[0]['county'], 'Greater London')
        self.assertEqual(parties[1]['name'], 'Jane Doe')

    def test_explicit_address_fields(self):
        md = ('Name: Bob Roberts\n'
              'Address Line 1: 2 Test Road\n'
              'Address Line 2: Hadleigh\n'
              'County: Essex\n'
              'Postcode: SS7 1QT\n'
              'Contact: 01268 000000\n')
        parties = parse_parties(md)
        self.assertEqual(len(parties), 1)
        self.assertEqual(parties[0]['address_line1'], '2 Test Road')
        self.assertEqual(parties[0]['county'], 'Essex')
        self.assertEqual(parties[0]['postcode'], 'SS7 1QT')

    def test_no_parties(self):
        self.assertEqual(parse_parties('Just some meeting chatter.'), [])


class ParseMeetingTimesTests(TestCase):
    def test_one_line_template(self):
        t = parse_meeting_times('Start Time: 10:30 ; Finish Time: 11:15')
        self.assertEqual((t.start.hour, t.start.minute), (10, 30))
        self.assertEqual((t.finish.hour, t.finish.minute), (11, 15))

    def test_separate_lines_and_end_label(self):
        t = parse_meeting_times('Start Time: 9:00\nEnd Time: 9:45\n')
        self.assertEqual((t.start.hour, t.start.minute), (9, 0))
        self.assertEqual((t.finish.hour, t.finish.minute), (9, 45))

    def test_am_pm_and_dot_separator(self):
        t = parse_meeting_times('Start: 9.30am\nFinish: 1.15pm')
        self.assertEqual((t.start.hour, t.start.minute), (9, 30))
        self.assertEqual((t.finish.hour, t.finish.minute), (13, 15))

    def test_blank_values_return_none(self):
        t = parse_meeting_times('Start Time: ; Finish Time:')
        self.assertIsNone(t.start)
        self.assertIsNone(t.finish)

    def test_no_labels_return_none(self):
        t = parse_meeting_times('We talked about the matter for a while.')
        self.assertIsNone(t.start)
        self.assertIsNone(t.finish)


class Free30IngestTests(TestCase):
    def _note(self, **overrides):
        note = {
            'id': 'free-1',
            'title': 'Initial consultation',
            'summary': ('Fee earner: FEE\n'
                        '## Info of Parties\n'
                        'Party 1\n'
                        '- Name: Alice Brown\n'
                        '- Email: alice@example.com\n'
                        '- Phone: 07000 111222\n'),
            'start_time': '2026-06-10T14:00:00+01:00',
            'end_time': '2026-06-10T14:30:00+01:00',
            'owner': {'email': 'fee@example.com'},
        }
        note.update(overrides)
        return note

    def setUp(self):
        self.fee_earner = CustomUser.objects.create_user(
            username='FEE', email='fee@example.com', first_name='Fee',
            last_name='Earner', password='x', max_holidays_in_year=20,
            is_matter_fee_earner=True,
        )

    def test_free30_meeting_created_with_attendees(self):
        note = self._note()
        imported = ingest._ingest_note(
            FakeClient(note), note, GranolaImportedNote.TYPE_FREE30)

        self.assertEqual(imported.status, GranolaImportedNote.STATUS_CREATED)
        self.assertEqual(imported.note_type, GranolaImportedNote.TYPE_FREE30)
        self.assertIsNotNone(imported.free30_meeting)
        meeting = imported.free30_meeting
        self.assertEqual(meeting.fee_earner, self.fee_earner)
        self.assertEqual(meeting.attendees.count(), 1)
        attendee = meeting.attendees.first()
        self.assertEqual(attendee.name, 'Alice Brown')
        self.assertEqual(attendee.email, 'alice@example.com')
        # No attendance note created for a free-30 note.
        self.assertEqual(MatterAttendanceNotes.objects.count(), 0)

    def test_free30_without_parties_goes_to_review(self):
        note = self._note(summary='General chat, no party details.')
        imported = ingest._ingest_note(
            FakeClient(note), note, GranolaImportedNote.TYPE_FREE30)
        # No attendees -> sent to the Allocate inbox, not auto-created.
        self.assertEqual(imported.status, GranolaImportedNote.STATUS_PENDING)
        self.assertIsNone(imported.free30_meeting)
        self.assertEqual(Free30Mins.objects.count(), 0)
        self.assertIn('attendees', imported.error_message)

    def test_free30_without_fee_earner_goes_to_review(self):
        # Parties present but no fee-earner code -> Allocate to complete.
        note = self._note(summary=('## Info of Parties\nParty 1\n'
                                   '- Name: Alice Brown\n- Email: a@x.com\n'))
        imported = ingest._ingest_note(
            FakeClient(note), note, GranolaImportedNote.TYPE_FREE30)
        self.assertEqual(imported.status, GranolaImportedNote.STATUS_PENDING)
        self.assertIsNone(imported.free30_meeting)

    def test_folder_id_resolution(self):
        folders = [
            {'id': 'fol_aaa', 'name': 'Attendance Note'},
            {'id': 'fol_bbb', 'name': 'Free 30 min'},
        ]
        self.assertEqual(ingest._resolve_folder_id(folders, 'free 30 min'), 'fol_bbb')
        self.assertEqual(ingest._resolve_folder_id(folders, 'Attendance Note'), 'fol_aaa')
        self.assertIsNone(ingest._resolve_folder_id(folders, 'Nonexistent'))


class SyncRoutingTests(TestCase):
    """End-to-end: folders resolve and notes route to the right record type."""

    def setUp(self):
        from backend.models import GranolaConfig
        self.fee_earner = CustomUser.objects.create_user(
            username='FEE', email='fee@example.com', first_name='Fee',
            last_name='Earner', password='x', max_holidays_in_year=20,
            is_matter_fee_earner=True)
        make_matter('GRN0001', fee_earner=self.fee_earner)
        cfg = GranolaConfig.get_solo()
        cfg.enabled = True
        cfg.api_key = 'grn_test'
        cfg.save()

    def test_routes_each_folder_to_its_type(self):
        from unittest import mock

        att_note = {
            'id': 'att-1', 'title': '[GRN0001] Client call',
            'summary': 'Fee earner: FEE\n- discussed matters',
            'owner': {'email': 'fee@example.com'},
            'start_time': '2026-06-10T09:00:00+01:00',
            'end_time': '2026-06-10T09:12:00+01:00',
        }
        free_note = {
            'id': 'free-1', 'title': 'Consultation',
            'summary': 'Fee earner: FEE\nParty 1\n- Name: Alice Brown\n- Email: a@x.com',
            'owner': {'email': 'fee@example.com'},
            'start_time': '2026-06-10T14:00:00+01:00',
            'end_time': '2026-06-10T14:30:00+01:00',
        }

        class FakeAPI:
            def __init__(self, *a, **k):
                pass

            def list_folders(self, *a, **k):
                return [{'id': 'fol_att', 'name': 'Attendance Note'},
                        {'id': 'fol_free', 'name': 'Free 30 min'}]

            def iter_notes(self, created_after=None, folder_id=None, **k):
                if folder_id == 'fol_att':
                    return iter([att_note])
                if folder_id == 'fol_free':
                    return iter([free_note])
                return iter([])

            def get_note(self, note_id, include_transcript=True):
                return {'att-1': att_note, 'free-1': free_note}[note_id]

        with mock.patch.object(ingest, 'GranolaClient', FakeAPI):
            ingest.sync_notes(force=True)

        self.assertEqual(MatterAttendanceNotes.objects.count(), 1)
        self.assertEqual(Free30Mins.objects.count(), 1)
        att = GranolaImportedNote.objects.get(granola_note_id='att-1')
        free = GranolaImportedNote.objects.get(granola_note_id='free-1')
        self.assertEqual(att.note_type, GranolaImportedNote.TYPE_ATTENDANCE)
        self.assertIsNotNone(att.attendance_note)
        self.assertEqual(free.note_type, GranolaImportedNote.TYPE_FREE30)
        self.assertEqual(free.free30_meeting.attendees.count(), 1)

    def _capture_iter_kwargs(self):
        from unittest import mock
        calls = []

        class FakeAPI:
            def __init__(self, *a, **k):
                pass

            def list_folders(self, *a, **k):
                return [{'id': 'fol_att', 'name': 'Attendance Note'}]

            def iter_notes(self, **kwargs):
                calls.append(kwargs)
                return iter([])

        return mock.patch.object(ingest, 'GranolaClient', FakeAPI), calls

    def test_incremental_pass_filters_on_updated_after(self):
        """Between full scans, a cheap incremental pass filters on updated_after
        (not created_after) so foldered-later notes aren't missed by time."""
        from django.utils import timezone as djtz
        from backend.models import GranolaConfig
        cfg = GranolaConfig.get_solo()
        cfg.last_synced_at = djtz.now()
        cfg.last_full_scan_at = djtz.now()   # recent -> not due for a full scan
        cfg.enabled = True
        cfg.save()

        patch, calls = self._capture_iter_kwargs()
        with patch:
            ingest.sync_notes()  # scheduled run, not forced

        self.assertTrue(calls)
        self.assertIsNotNone(calls[0].get('updated_after'))
        self.assertIsNone(calls[0].get('created_after'))

    def test_full_scan_lists_everything_without_time_filter(self):
        """A full scan (forced, or when due) lists the whole folder with no time
        filter, so id-dedupe catches notes added to the folder out-of-band."""
        from django.utils import timezone as djtz
        from backend.models import GranolaConfig
        cfg = GranolaConfig.get_solo()
        cfg.last_synced_at = djtz.now()
        cfg.last_full_scan_at = djtz.now()
        cfg.enabled = True
        cfg.save()

        patch, calls = self._capture_iter_kwargs()
        with patch:
            ingest.sync_notes(force=True)  # "Sync now" -> full scan

        self.assertTrue(calls)
        self.assertIsNone(calls[0].get('updated_after'))
        self.assertIsNone(calls[0].get('created_after'))
        cfg.refresh_from_db()
        self.assertIsNotNone(cfg.last_full_scan_at)

    def test_first_run_of_day_does_full_scan(self):
        """The first scheduled run of a new day catches up the overnight gap
        with a full scan, even if the 6-hour interval hasn't elapsed."""
        from datetime import timedelta
        from django.utils import timezone as djtz
        from backend.models import GranolaConfig
        cfg = GranolaConfig.get_solo()
        yesterday = djtz.now() - timedelta(hours=14)  # last night
        cfg.last_synced_at = yesterday
        cfg.last_full_scan_at = yesterday
        cfg.enabled = True
        cfg.save()

        patch, calls = self._capture_iter_kwargs()
        with patch:
            ingest.sync_notes()  # scheduled morning run

        self.assertTrue(calls)
        self.assertIsNone(calls[0].get('updated_after'))  # full scan, no time filter

    def test_start_date_keeps_sync_dormant(self):
        """Before the start date, the scheduled sync makes no API calls."""
        from datetime import timedelta
        from django.utils import timezone as djtz
        from backend.models import GranolaConfig
        cfg = GranolaConfig.get_solo()
        cfg.enabled = True
        cfg.start_date = djtz.localdate() + timedelta(days=3)
        cfg.save()

        patch, calls = self._capture_iter_kwargs()
        with patch:
            status = ingest.sync_notes()  # scheduled run, before go-live

        self.assertIn('scheduled to start', status)
        self.assertEqual(calls, [])  # nothing hit the API

    def test_force_bypasses_start_date(self):
        """Manual Sync now works even before the start date."""
        from datetime import timedelta
        from django.utils import timezone as djtz
        from backend.models import GranolaConfig
        cfg = GranolaConfig.get_solo()
        cfg.enabled = True
        cfg.start_date = djtz.localdate() + timedelta(days=3)
        cfg.save()

        patch, calls = self._capture_iter_kwargs()
        with patch:
            ingest.sync_notes(force=True)

        self.assertTrue(calls)  # the API was queried despite the future start date

    def test_test_connection_reports_folders(self):
        from unittest import mock

        class FakeAPI:
            def __init__(self, *a, **k):
                pass

            def list_folders(self, *a, **k):
                return [{'id': 'fol_att', 'name': 'Attendance Note'},
                        {'id': 'fol_free', 'name': 'Free 30 min'}]

            def iter_notes(self, folder_id=None, **k):
                return iter([{'id': 'n1'}]) if folder_id else iter([])

        with mock.patch.object(ingest, 'GranolaClient', FakeAPI):
            ok, message = ingest.test_connection()

        self.assertTrue(ok)
        self.assertIn('Connected', message)
        self.assertIn('Attendance Note', message)


class ComputeUnitTests(TestCase):
    def test_minimum_one_unit(self):
        self.assertEqual(ingest._compute_unit(None, None), 1)

    def test_rounds_up(self):
        from django.utils.dateparse import parse_datetime
        start = parse_datetime('2026-06-10T10:00:00+01:00')
        end = parse_datetime('2026-06-10T10:07:00+01:00')  # 7 min -> 2 units
        self.assertEqual(ingest._compute_unit(start, end), 2)


class InboxActionTests(TestCase):
    def setUp(self):
        from django.urls import reverse
        self.reverse = reverse
        self.mgr = CustomUser.objects.create_user(
            username='MGR', email='m@x.com', first_name='M', last_name='G',
            password='x', max_holidays_in_year=20, is_manager=True,
            is_matter_fee_earner=True)
        self.client.force_login(self.mgr)

    def _pending(self, note_type=GranolaImportedNote.TYPE_ATTENDANCE, **kw):
        defaults = dict(granola_note_id='x1', title='A note', summary_md='hi',
                        note_type=note_type,
                        status=GranolaImportedNote.STATUS_PENDING)
        defaults.update(kw)
        return GranolaImportedNote.objects.create(**defaults)

    def test_dismiss_then_restore(self):
        note = self._pending()
        self.client.post(self.reverse('granola_ignore_note', args=[note.id]))
        note.refresh_from_db()
        self.assertEqual(note.status, GranolaImportedNote.STATUS_IGNORED)

        self.client.post(self.reverse('granola_restore_note', args=[note.id]))
        note.refresh_from_db()
        self.assertEqual(note.status, GranolaImportedNote.STATUS_PENDING)
        self.assertIsNone(note.reviewed_at)

    def test_create_free30_from_pending(self):
        # The reviewer completes the missing info (attendees + times) in Allocate.
        note = self._pending(
            note_type=GranolaImportedNote.TYPE_FREE30, summary_md='chat')
        r = self.client.post(self.reverse('granola_create_free30', args=[note.id]), {
            'fee_earner': self.mgr.id,
            'number_of_attendees': '1',
            'name': 'Alice Brown', 'email': 'a@x.com', 'contact_number': '',
            'address_line1': '', 'address_line2': '', 'county': '', 'postcode': '',
            'date': '2026-06-10', 'start_time': '14:00', 'finish_time': '14:30',
        })
        self.assertEqual(r.status_code, 302)
        note.refresh_from_db()
        self.assertEqual(note.status, GranolaImportedNote.STATUS_CREATED)
        self.assertIsNotNone(note.free30_meeting)
        self.assertEqual(Free30Mins.objects.count(), 1)
        meeting = note.free30_meeting
        self.assertEqual(meeting.attendees.count(), 1)
        self.assertEqual(meeting.attendees.first().name, 'Alice Brown')
        self.assertEqual(str(meeting.start_time), '14:00:00')
        self.assertEqual(str(meeting.finish_time), '14:30:00')

    def test_assign_attendance_with_times(self):
        make_matter('GRN0001', fee_earner=self.mgr)
        note = self._pending(note_type=GranolaImportedNote.TYPE_ATTENDANCE,
                             parsed_file_number='GRN0001')
        r = self.client.post(self.reverse('granola_assign_note', args=[note.id]), {
            'file_number': 'GRN0001', 'person_attended': self.mgr.id,
            'is_charged': 'on', 'date': '2026-06-10',
            'start_time': '10:00', 'finish_time': '10:30',
        })
        self.assertEqual(r.status_code, 302)
        note.refresh_from_db()
        self.assertEqual(note.status, GranolaImportedNote.STATUS_CREATED)
        self.assertIsNotNone(note.attendance_note)
        self.assertEqual(note.attendance_note.unit, 5)  # 30 min / 6

    def test_inbox_shows_dismissed_section(self):
        self._pending(status=GranolaImportedNote.STATUS_IGNORED, title='Gone note')
        body = self.client.get(self.reverse('granola_inbox')).content.decode()
        self.assertIn('Gone note', body)
        self.assertIn('Restore', body)

    def test_inbox_renders_completion_forms(self):
        # Free 30 completion (attendees + times) and attendance time-capture forms.
        self._pending(note_type=GranolaImportedNote.TYPE_FREE30,
                      granola_note_id='f30', title='F30')
        self._pending(note_type=GranolaImportedNote.TYPE_ATTENDANCE,
                      granola_note_id='att', title='Att')
        body = self.client.get(self.reverse('granola_inbox')).content.decode()
        self.assertIn('data-add-attendee', body)
        self.assertIn('number_of_attendees', body)
        self.assertIn('name="start_time"', body)
        self.assertIn('name="finish_time"', body)
