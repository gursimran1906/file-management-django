"""Tests for the Teams call-log integration: phone normalisation, matter
matching, unit calc, the ingest decision logic (auto-create vs review inbox vs
dedupe), Granola note linking, the sync loop, and the inbox/dashboard UI."""
from datetime import datetime, time, timedelta, timezone as dt_timezone
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from users.models import CustomUser
from ..models import (AuthorisedParties, CallLogConfig, CallRecord,
                     ClientContactDetails, GranolaImportedNote,
                     MatterAttendanceNotes, MatterType, OthersideDetails, WIP)
from ..telephony import ingest
from ..telephony.match import (build_matter_phone_index, match_call,
                              national_key, normalize_phone)


# --- fixtures ----------------------------------------------------------------

def make_user(username='fee', email='fee@example.com', **kw):
    kw.setdefault('first_name', 'Fee')
    kw.setdefault('last_name', 'Earner')
    kw.setdefault('max_holidays_in_year', 0)
    return CustomUser.objects.create_user(
        username=username[:3], email=email, password='pw', **kw)


def make_client(number='07700 900123', name='Test Client', email='c@example.com'):
    return ClientContactDetails.objects.create(
        name=name, occupation='Retired', address_line1='1 Test St',
        address_line2='', county='Essex', postcode='SS7 1QT',
        email=email, contact_number=number)


def make_matter(file_number='ABC0010001', client=None, fee_earner=None,
                other_side=None, client_number='07700 900123'):
    client = client or make_client(number=client_number)
    return WIP.objects.create(
        file_number=file_number, client1=client, matter_description='Matter',
        matter_type=MatterType.objects.create(type='Probate'), funding='Pvt',
        fee_earner=fee_earner, other_side=other_side)


def call_row(**overrides):
    row = {
        'id': 'row-1',
        'callId': 'call-1',
        'userId': 'user-guid',
        'userPrincipalName': 'fee@example.com',
        'userDisplayName': 'Fee Earner',
        'startDateTime': '2026-07-15T09:00:00Z',
        'endDateTime': '2026-07-15T09:06:00Z',
        'duration': 360,
        'callType': 'UserIn',
        'callerNumber': '+447700900123',
        'calleeNumber': '+441234567890',
    }
    row.update(overrides)
    return row


class FakeGraphClient:
    """Stands in for TeamsGraphClient in sync_calls."""
    def __init__(self, pstn=None, direct=None):
        self._pstn = list(pstn or [])
        self._direct = list(direct or [])
        self.calls = []

    def get_pstn_calls(self, from_dt, to_dt):
        self.calls.append(('pstn', from_dt, to_dt))
        return iter(self._pstn)

    def get_direct_routing_calls(self, from_dt, to_dt):
        self.calls.append(('direct', from_dt, to_dt))
        return iter(self._direct)


# --- phone normalisation ------------------------------------------------------

class NormalizePhoneTests(TestCase):
    def test_uk_forms_all_canonicalise(self):
        for raw in ('07700 900123', '+44 7700 900123', '0044 7700900123',
                    '447700900123', 'tel:+447700900123'):
            self.assertEqual(normalize_phone(raw), '+447700900123', raw)

    def test_landline(self):
        self.assertEqual(normalize_phone('020 7946 0958'), '+442079460958')

    def test_withheld_and_garbage(self):
        for raw in ('Anonymous', 'withheld', '', None, '123', 'abc'):
            self.assertEqual(normalize_phone(raw), '', repr(raw))

    def test_idempotent(self):
        once = normalize_phone('07700 900123')
        self.assertEqual(normalize_phone(once), once)

    def test_national_key_equivalence(self):
        self.assertEqual(national_key(normalize_phone('07700900123')),
                         national_key(normalize_phone('+447700900123')))


# --- matter matching ----------------------------------------------------------

class MatterMatchTests(TestCase):
    def test_unique_client_match(self):
        make_matter('ABC0010001', client_number='07700 900123')
        index = build_matter_phone_index()
        r = match_call('+447700900123', index)
        self.assertEqual(r.file_number, 'ABC0010001')
        self.assertEqual(r.role, CallRecord.ROLE_CLIENT)
        self.assertFalse(r.ambiguous)

    def test_otherside_only_goes_to_inbox_by_default(self):
        os_ = OthersideDetails.objects.create(name='Opponent',
                                              contact_number='07811 111222')
        make_matter('ABC0010002', client_number='07000 000000', other_side=os_)
        index = build_matter_phone_index()
        r = match_call('+447811111222', index)
        self.assertEqual(r.file_number, '')
        self.assertEqual(len(r.candidates), 1)

    def test_otherside_only_matches_when_allowed(self):
        os_ = OthersideDetails.objects.create(name='Opponent',
                                              contact_number='07811 111222')
        make_matter('ABC0010003', client_number='07000 000000', other_side=os_)
        index = build_matter_phone_index()
        r = match_call('+447811111222', index, allow_otherside_only=True)
        self.assertEqual(r.file_number, 'ABC0010003')
        self.assertEqual(r.role, CallRecord.ROLE_OTHERSIDE)

    def test_ambiguous_multiple_matters(self):
        make_matter('ABC0010004', client=make_client(number='07700 900123',
                                                      email='a@x.com'))
        make_matter('ABC0010005', client=make_client(number='07700 900123',
                                                      email='b@x.com'))
        index = build_matter_phone_index()
        r = match_call('+447700900123', index)
        self.assertTrue(r.ambiguous)
        self.assertEqual(len(r.candidates), 2)

    def test_authorised_party_match(self):
        ap = AuthorisedParties.objects.create(
            name='Attorney', relationship_to_client='Son', address_line1='1 St',
            address_line2='', county='Essex', postcode='SS7 1QT',
            email='ap@x.com', contact_number='07999 000111')
        m = make_matter('ABC0010006', client_number='07000 000000')
        m.authorised_party1 = ap
        m.save()
        index = build_matter_phone_index()
        r = match_call('+447999000111', index)
        self.assertEqual(r.file_number, 'ABC0010006')
        self.assertEqual(r.role, CallRecord.ROLE_AUTH_PARTY)

    def test_no_match(self):
        make_matter('ABC0010007', client_number='07000 000000')
        r = match_call('+447700900123', build_matter_phone_index())
        self.assertEqual(r.file_number, '')
        self.assertFalse(r.ambiguous)


# --- unit calc / direction ----------------------------------------------------

class ComputeCallUnitTests(TestCase):
    def test_missed_call(self):
        self.assertEqual(ingest._compute_call_unit(0), (0, False))

    def test_six_minutes_one_unit(self):
        self.assertEqual(ingest._compute_call_unit(360), (1, True))

    def test_seven_minutes_two_units(self):
        self.assertEqual(ingest._compute_call_unit(420), (2, True))

    def test_short_answered_call_is_one_unit(self):
        self.assertEqual(ingest._compute_call_unit(30), (1, True))


class DirectionResolutionTests(TestCase):
    def test_inbound_uses_caller(self):
        call = ingest._build_call(call_row(callType='UserIn'), CallRecord.SOURCE_PSTN)
        self.assertEqual(call.direction, CallRecord.DIRECTION_INBOUND)
        self.assertEqual(call.external_number, '+447700900123')

    def test_outbound_uses_callee(self):
        call = ingest._build_call(call_row(callType='UserOut'), CallRecord.SOURCE_PSTN)
        self.assertEqual(call.direction, CallRecord.DIRECTION_OUTBOUND)
        self.assertEqual(call.external_number, '+441234567890')


# --- ingest row ---------------------------------------------------------------

class IngestRowTests(TestCase):
    def setUp(self):
        self.fe = make_user('fee', 'fee@example.com', is_matter_fee_earner=True)
        self.matter = make_matter('ABC0010001', fee_earner=self.fe,
                                   client_number='07700 900123')
        self.config = CallLogConfig.get_solo()
        self.index = build_matter_phone_index()

    def _ingest(self, **row_kw):
        return ingest._ingest_row(call_row(**row_kw), CallRecord.SOURCE_PSTN,
                                  self.index, self.config)

    def test_matched_call_creates_charged_note(self):
        call = self._ingest()
        self.assertEqual(call.status, CallRecord.STATUS_CREATED)
        self.assertEqual(call.matched_file, self.matter)
        self.assertEqual(call.matched_fee_earner, self.fe)
        note = call.attendance_note
        self.assertIsNotNone(note)
        self.assertEqual(note.unit, 1)
        self.assertTrue(note.is_charged)
        self.assertEqual(note.person_attended, self.fe)
        self.assertIn('Inbound', note.subject_line)

    def test_missed_call_note_is_zero_units_uncharged(self):
        call = self._ingest(id='row-miss', callId='c-miss', duration=0,
                            endDateTime='2026-07-15T09:00:00Z')
        self.assertEqual(call.status, CallRecord.STATUS_CREATED)
        self.assertEqual(call.attendance_note.unit, 0)
        self.assertFalse(call.attendance_note.is_charged)

    def test_no_match_goes_to_inbox(self):
        call = self._ingest(id='row-x', callId='c-x',
                            callerNumber='+447000000000')
        self.assertEqual(call.status, CallRecord.STATUS_PENDING)
        self.assertIsNone(call.attendance_note)

    def test_ambiguous_goes_to_inbox_with_candidates(self):
        make_matter('ABC0010002',
                    client=make_client(number='07700 900123', email='b@x.com'))
        self.index = build_matter_phone_index()
        call = self._ingest(id='row-amb', callId='c-amb')
        self.assertEqual(call.status, CallRecord.STATUS_PENDING)
        self.assertIsNone(call.attendance_note)
        self.assertEqual(len(call.ambiguous_candidates), 2)

    def test_withheld_number_goes_to_inbox(self):
        call = self._ingest(id='row-w', callId='c-w', callerNumber='anonymous')
        self.assertEqual(call.status, CallRecord.STATUS_PENDING)

    def test_dedupe_by_graph_row_id(self):
        self._ingest()
        again = self._ingest()
        self.assertIsNone(again)
        self.assertEqual(CallRecord.objects.count(), 1)

    def test_segment_dedupe_one_note_per_call_id(self):
        self._ingest(id='seg-1')
        self._ingest(id='seg-2')  # same callId 'call-1'
        self.assertEqual(CallRecord.objects.count(), 2)
        self.assertEqual(MatterAttendanceNotes.objects.count(), 1)

    def test_min_duration_skips_row(self):
        self.config.min_duration_seconds = 60
        call = self._ingest(id='row-short', callId='c-short', duration=10)
        self.assertIsNone(call)
        self.assertEqual(CallRecord.objects.count(), 0)


# --- Granola linking ----------------------------------------------------------

class GranolaLinkTests(TestCase):
    def setUp(self):
        self.fe = make_user('fee', 'fee@example.com', is_matter_fee_earner=True)
        self.matter = make_matter('ABC0010001', fee_earner=self.fe)
        self.config = CallLogConfig.get_solo()
        self.index = build_matter_phone_index()
        # Use now-relative, UTC-consistent times so the call sits inside the
        # reconcile look-back window and lines up with the note's meeting time.
        self.base = timezone.now().replace(microsecond=0)

    def _iso(self, dt):
        return dt.astimezone(dt_timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    def _granola(self, minutes_offset=2, **kw):
        defaults = dict(
            note_type=GranolaImportedNote.TYPE_ATTENDANCE,
            granola_note_id='gn-1', title='Call note',
            summary_md='## Discussion\n\n- agreed next steps',
            meeting_start=self.base + timedelta(minutes=minutes_offset),
            owner_email='fee@example.com',
            matched_fee_earner=self.fe,
            status=GranolaImportedNote.STATUS_PENDING)
        defaults.update(kw)
        return GranolaImportedNote.objects.create(**defaults)

    def _ingest_call(self, **row_kw):
        row = call_row(startDateTime=self._iso(self.base),
                       endDateTime=self._iso(self.base + timedelta(minutes=6)),
                       **row_kw)
        return ingest._ingest_row(row, CallRecord.SOURCE_PSTN, self.index,
                                  self.config)

    def test_call_first_then_pending_note_shares_one_note(self):
        note = self._granola()
        call = self._ingest_call()
        call.refresh_from_db()
        note.refresh_from_db()
        self.assertEqual(call.granola_note, note)
        self.assertEqual(call.attendance_note, note.attendance_note)
        self.assertEqual(MatterAttendanceNotes.objects.count(), 1)

    def test_granola_already_created_note_wins_race(self):
        pre_note = MatterAttendanceNotes.objects.create(
            file_number=self.matter, date=timezone.localdate(),
            start_time=time(10, 0), finish_time=time(10, 30), subject_line='Granola',
            content='{"delta":"","html":""}', person_attended=self.fe, unit=5)
        note = self._granola(matched_file=self.matter, attendance_note=pre_note,
                             status=GranolaImportedNote.STATUS_CREATED)
        call = self._ingest_call()
        call.refresh_from_db()
        self.assertEqual(call.attendance_note, pre_note)
        self.assertEqual(call.granola_note, note)
        self.assertEqual(MatterAttendanceNotes.objects.count(), 1)

    def test_out_of_window_note_not_linked(self):
        self._granola(minutes_offset=240)  # 4 hours away
        call = self._ingest_call()
        self.assertIsNone(call.granola_note)
        self.assertEqual(MatterAttendanceNotes.objects.count(), 1)

    def test_reconcile_links_late_note(self):
        call = self._ingest_call()
        self.assertIsNone(call.granola_note)
        note = self._granola()  # note appears after the call
        linked = ingest.reconcile_granola_links(self.config)
        self.assertEqual(linked, 1)
        call.refresh_from_db()
        self.assertEqual(call.granola_note, note)
        self.assertEqual(MatterAttendanceNotes.objects.count(), 1)


# --- sync loop ----------------------------------------------------------------

class SyncCallsTests(TestCase):
    def setUp(self):
        self.fe = make_user('fee', 'fee@example.com', is_matter_fee_earner=True)
        self.matter = make_matter('ABC0010001', fee_earner=self.fe)
        self.config = CallLogConfig.get_solo()

    def test_dormant_when_disabled(self):
        self.config.enabled = False
        self.config.save()
        with patch('backend.telephony.ingest.TeamsGraphClient') as m:
            status = ingest.sync_calls()
        m.assert_not_called()
        self.assertIn('disabled', status)

    def test_polls_both_endpoints_and_creates(self):
        self.config.enabled = True
        self.config.save()
        fake = FakeGraphClient(
            pstn=[call_row(id='p1', callId='p1')],
            direct=[call_row(id='d1', callId='d1', callType='ByotOut',
                             calleeNumber='+447700900123')])
        with patch('backend.telephony.ingest.TeamsGraphClient', return_value=fake):
            status = ingest.sync_calls()
        self.assertEqual(CallRecord.objects.count(), 2)
        self.assertEqual(
            CallRecord.objects.filter(status=CallRecord.STATUS_CREATED).count(), 2)
        self.assertIn('created', status)
        # both endpoints queried
        self.assertEqual({c[0] for c in fake.calls}, {'pstn', 'direct'})

    def test_endpoint_toggle_respected(self):
        self.config.enabled = True
        self.config.poll_direct_routing = False
        self.config.save()
        fake = FakeGraphClient(pstn=[call_row(id='p1', callId='p1')])
        with patch('backend.telephony.ingest.TeamsGraphClient', return_value=fake):
            ingest.sync_calls()
        self.assertEqual({c[0] for c in fake.calls}, {'pstn'})

    def test_start_date_keeps_dormant(self):
        self.config.enabled = True
        self.config.start_date = timezone.localdate() + timedelta(days=5)
        self.config.save()
        with patch('backend.telephony.ingest.TeamsGraphClient') as m:
            status = ingest.sync_calls()
        m.assert_not_called()
        self.assertIn('scheduled to start', status)

    def test_force_bypasses_disabled(self):
        self.config.enabled = False
        self.config.save()
        fake = FakeGraphClient(pstn=[call_row(id='p1', callId='p1')])
        with patch('backend.telephony.ingest.TeamsGraphClient', return_value=fake):
            ingest.sync_calls(force=True)
        self.assertEqual(CallRecord.objects.count(), 1)


# --- inbox / dashboard UI -----------------------------------------------------

class InboxActionTests(TestCase):
    def setUp(self):
        self.mgr = make_user('mgr', 'mgr@example.com', is_manager=True,
                             is_matter_fee_earner=True)
        self.matter = make_matter('ABC0010001', fee_earner=self.mgr)
        self.client.force_login(self.mgr)

    def _pending_call(self, **kw):
        return CallRecord.objects.create(
            source=CallRecord.SOURCE_PSTN, graph_row_id=kw.get('graph_row_id', 'r1'),
            call_id='c1', direction=CallRecord.DIRECTION_INBOUND,
            external_number='+447700900123',
            external_number_normalized='+447700900123',
            start_datetime=timezone.now(), duration_seconds=360,
            status=CallRecord.STATUS_PENDING)

    def test_inbox_renders(self):
        self._pending_call()
        resp = self.client.get(reverse('calls_inbox'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '+447700900123')

    def test_assign_creates_note(self):
        call = self._pending_call()
        resp = self.client.post(reverse('call_assign_matter', args=[call.id]),
                                {'file_number': 'ABC0010001', 'is_charged': 'on'})
        self.assertEqual(resp.status_code, 302)
        call.refresh_from_db()
        self.assertEqual(call.status, CallRecord.STATUS_CREATED)
        self.assertIsNotNone(call.attendance_note)
        self.assertEqual(call.attendance_note.file_number, self.matter)

    def test_mark_enquiry(self):
        call = self._pending_call()
        self.client.post(reverse('call_mark_enquiry', args=[call.id]))
        call.refresh_from_db()
        self.assertEqual(call.status, CallRecord.STATUS_ENQUIRY)

    def test_route_free30_creates_meeting(self):
        call = self._pending_call()
        self.client.post(reverse('call_route_free30', args=[call.id]),
                         {'caller_name': 'Jane Caller'})
        call.refresh_from_db()
        self.assertEqual(call.status, CallRecord.STATUS_CREATED)
        self.assertIsNotNone(call.free30_meeting)
        self.assertEqual(call.free30_meeting.attendees.first().name, 'Jane Caller')

    def test_ignore_then_restore(self):
        call = self._pending_call()
        self.client.post(reverse('call_ignore', args=[call.id]))
        call.refresh_from_db()
        self.assertEqual(call.status, CallRecord.STATUS_IGNORED)
        self.client.post(reverse('call_restore', args=[call.id]))
        call.refresh_from_db()
        self.assertEqual(call.status, CallRecord.STATUS_PENDING)

    def test_attendance_page_shows_call_metadata(self):
        call = self._pending_call()
        self.client.post(reverse('call_assign_matter', args=[call.id]),
                         {'file_number': 'ABC0010001', 'is_charged': 'on'})
        resp = self.client.get(
            reverse('attendance_note_view', args=['ABC0010001']))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '+447700900123')

    def test_dashboard_widget_lists_calls(self):
        call = self._pending_call()
        call.matched_fee_earner = self.mgr
        call.matched_file = self.matter
        call.status = CallRecord.STATUS_CREATED
        call.save()
        resp = self.client.get(reverse('user_dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Recent calls')
        self.assertContains(resp, '+447700900123')

    def test_settings_renders_for_manager(self):
        resp = self.client.get(reverse('calls_settings'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Teams call log settings')

    def test_settings_requires_manager(self):
        other = make_user('oth', 'oth@example.com', is_manager=False)
        self.client.force_login(other)
        resp = self.client.get(reverse('calls_settings'))
        self.assertEqual(resp.status_code, 302)  # redirected away


class GraphPermissionErrorTests(TestCase):
    """A refused call log should say what is actually wrong."""

    def test_403_names_the_permission_that_is_missing(self):
        from unittest.mock import MagicMock
        from ..telephony.client import TeamsGraphClient, TelephonyError

        client = TeamsGraphClient.__new__(TeamsGraphClient)   # skip credentials
        client.base = 'https://graph.microsoft.com/v1.0'
        refused = MagicMock(status_code=403, is_success=False, text='UnknownError')
        client._request = lambda url: refused

        with self.assertRaises(TelephonyError) as caught:
            list(client.get_pstn_calls(timezone.now(), timezone.now()))
        message = str(caught.exception)
        self.assertIn('CallRecords.Read.All', message)
        self.assertIn('admin consent', message)
        # The bare Graph wording tells a reader nothing, so it is not repeated.
        self.assertNotIn('UnknownError', message)
