import json
from datetime import date, datetime, time, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal

from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from users.models import (
    AttendanceRecord,
    CustomUser,
    HolidayRecord,
    Rate,
    SicknessRecord,
)

from .. import staff_timeline as tl
from ..models import (
    ClientContactDetails,
    FileStatus,
    Free30Mins,
    Free30MinsAttendees,
    LastWork,
    MatterAttendanceNotes,
    MatterEmails,
    MatterLetters,
    MatterType,
    WIP,
)

MON = date(2026, 9, 7)
WED = date(2026, 9, 9)
SAT = date(2026, 9, 12)


def quill(html):
    return json.dumps({'delta': '', 'html': html})


def aware(day, hhmm):
    return timezone.make_aware(datetime.combine(day, time.fromisoformat(hhmm)))


def make_user(code, manager=False, rate=None):
    return CustomUser.objects.create_user(
        username=code, email=f'{code.lower()}@example.com', first_name=code.title(),
        last_name='Tester', password='password', max_holidays_in_year=20,
        is_manager=manager, hourly_rate=rate,
    )


def make_client(name):
    return ClientContactDetails.objects.create(
        name=name, occupation='Retired', address_line1='1 St', address_line2='',
        county='Essex', postcode='SS7 1QT', email='e@example.com',
        contact_number='0123456789', is_business=False,
    )


def make_matter(file_number, client, fee_earner=None):
    fs, _ = FileStatus.objects.get_or_create(status='Open')
    mt, _ = MatterType.objects.get_or_create(type='Probate')
    return WIP.objects.create(
        file_number=file_number, client1=client, matter_description='Matter',
        matter_type=mt, file_status=fs, fee_earner=fee_earner, funding='Pvt',
    )


def make_note(user, matter, day, start, finish, *, charged=True, unit=5,
              subject='Call with client', created_by=None):
    return MatterAttendanceNotes.objects.create(
        file_number=matter, date=day, start_time=time.fromisoformat(start),
        finish_time=time.fromisoformat(finish), subject_line=subject,
        content=quill('<p>Discussed the matter</p>'), is_charged=charged,
        person_attended=user, unit=unit, created_by=created_by,
    )


def make_email(user, matter, when, units=2, *, sent=True, subject='Re: contract',
               link='https://outlook.example/message/1', sender=None, receiver=None):
    party = {'emailAddress': {'name': 'Bob Client', 'address': 'bob@example.com'}}
    return MatterEmails.objects.create(
        file_number=matter,
        sender=json.dumps(party) if sender is None else sender,
        receiver=json.dumps([party]) if receiver is None else receiver,
        subject=subject, is_sent=sent, time=when, fee_earner=user, units=units, link=link,
    )


def make_letter(user, matter, day, *, sent=True, charged=True):
    return MatterLetters.objects.create(
        file_number=matter, date=day, to_or_from='Other side solicitors', sent=sent,
        subject_line='Letter about completion', person_attended=user, is_charged=charged,
    )


def make_meeting(user, day, start, finish, attendee='Alice Enquirer'):
    mt, _ = MatterType.objects.get_or_create(type='Probate')
    meeting = Free30Mins.objects.create(
        matter_type=mt, notes=quill('<p>Initial chat</p>'), date=day,
        start_time=time.fromisoformat(start), finish_time=time.fromisoformat(finish),
        fee_earner=user,
    )
    meeting.attendees.add(Free30MinsAttendees.objects.create(name=attendee, email='a@example.com'))
    return meeting


def make_task(user, matter, day, text='File the claim form'):
    return LastWork.objects.create(file_number=matter, person=user, task=text, date=day)


def events_of(user, view='week', anchor=WED, kinds=None, **kwargs):
    data = tl.build_timeline(user, view, anchor, kinds, today=WED, **kwargs)
    return [ev for day in data['days'] for ev in day['events']], data


# ---------------------------------------------------------------------------
# Pure range / navigation maths
# ---------------------------------------------------------------------------

class RangeTests(SimpleTestCase):
    def test_week_snaps_to_monday(self):
        rng = tl.resolve_range('week', WED)
        self.assertEqual(rng['start'], MON)
        self.assertEqual(rng['end'], MON + timedelta(days=6))
        self.assertEqual(rng['prev_anchor'], MON - timedelta(days=7))
        self.assertEqual(rng['next_anchor'], MON + timedelta(days=7))
        self.assertEqual(rng['label'], '7 – 11 Sep 2026')

    def test_month_pads_to_full_weeks(self):
        rng = tl.resolve_range('month', WED)
        self.assertEqual(rng['start'], date(2026, 9, 1))
        self.assertEqual(rng['end'], date(2026, 9, 30))
        self.assertEqual(rng['grid_start'], date(2026, 8, 31))
        self.assertEqual(rng['grid_end'], date(2026, 10, 4))
        self.assertEqual(rng['prev_anchor'], date(2026, 8, 1))
        self.assertEqual(rng['next_anchor'], date(2026, 10, 1))
        self.assertEqual(rng['label'], 'September 2026')

    def test_month_that_starts_on_monday_has_no_padding(self):
        rng = tl.resolve_range('month', date(2027, 2, 14))
        self.assertEqual(rng['grid_start'], date(2027, 2, 1))
        self.assertEqual(rng['grid_end'], date(2027, 2, 28))

    def test_day_prev_next(self):
        rng = tl.resolve_range('day', WED)
        self.assertEqual((rng['prev_anchor'], rng['next_anchor']),
                         (WED - timedelta(days=1), WED + timedelta(days=1)))
        self.assertEqual(rng['label'], 'Wednesday 9 September 2026')

    def test_timeline_query_omits_types_when_all_selected(self):
        self.assertEqual(tl.timeline_query('week', WED, user_id=3),
                         'tl_view=week&tl_date=2026-09-09&tl_user=3')
        query = tl.timeline_query('day', WED, kinds=['email', 'note'])
        self.assertIn('tl_types=note&tl_types=email', query)
        self.assertNotIn('tl_user', query)

    def test_last_selected_kind_cannot_be_toggled_off(self):
        rng = tl.resolve_range('week', WED)
        nav = tl.build_nav('week', WED, rng, kinds=['note'], today=WED)
        note = next(t for t in nav['kind_toggles'] if t['kind'] == 'note')
        self.assertTrue(note['locked'])
        self.assertEqual(note['query'], nav['current'])
        email = next(t for t in nav['kind_toggles'] if t['kind'] == 'email')
        self.assertIn('tl_types=note&tl_types=email', email['query'])

    def test_params_fall_back_safely(self):
        view, anchor, kinds = tl.parse_timeline_params(
            {'tl_view': 'bogus', 'tl_date': 'not-a-date', 'tl_types': ['nope']})
        self.assertEqual(view, 'week')
        self.assertEqual(anchor, timezone.localdate())
        self.assertEqual(kinds, list(tl.KINDS))


class LayoutTests(SimpleTestCase):
    @staticmethod
    def timed(start, finish, day=WED):
        started = datetime.combine(day, time.fromisoformat(start))
        ended = datetime.combine(day, time.fromisoformat(finish))
        minutes = int((ended - started).total_seconds() // 60)
        return {'start': started, 'end': ended, 'minutes': minutes}

    def test_overlapping_events_share_the_column(self):
        a, b = self.timed('09:00', '10:00'), self.timed('09:30', '10:30')
        tl.assign_lanes([a, b])
        self.assertEqual((a['lanes'], b['lanes']), (2, 2))
        self.assertEqual({a['lane'], b['lane']}, {0, 1})
        self.assertEqual(a['width_pct'], 50)

    def test_chain_reuses_a_freed_lane(self):
        a, b, c = self.timed('09:00', '10:00'), self.timed('09:30', '10:30'), self.timed('10:00', '11:00')
        tl.assign_lanes([a, b, c])
        self.assertEqual(a['lanes'], 2)
        self.assertEqual(c['lane'], a['lane'])

    def test_disjoint_events_get_full_width(self):
        a, b = self.timed('09:00', '09:30'), self.timed('11:00', '11:30')
        tl.assign_lanes([a, b])
        self.assertEqual((a['lanes'], b['lanes'], a['width_pct']), (1, 1, 100))

    def test_grid_widens_for_early_and_late_entries(self):
        early = self.timed('06:30', '07:00')
        late = self.timed('19:30', '20:10')
        self.assertEqual(tl.grid_bounds([early, late]), (6 * 60, 21 * 60))
        self.assertEqual(tl.grid_bounds([]), (7 * 60, 19 * 60))

    def test_tiny_entries_keep_a_minimum_height(self):
        tiny = self.timed('09:00', '09:06')
        tl.position_events([tiny], 7 * 60, 19 * 60)
        self.assertGreaterEqual(tiny['height_pct'], tl.MIN_BLOCK_MINUTES / 720 * 100)
        self.assertEqual(tiny['top_pct'], round(120 / 720 * 100, 3))


# ---------------------------------------------------------------------------
# Aggregation against real rows
# ---------------------------------------------------------------------------

class AggregationTests(TestCase):
    def setUp(self):
        self.user = make_user('ABC')
        self.other = make_user('XYZ')
        self.matter = make_matter('ABC0010001', make_client('Mo Client'), fee_earner=self.user)

    def test_note_units_drive_totals_and_charge_split(self):
        make_note(self.user, self.matter, WED, '09:00', '09:30', unit=5)
        make_note(self.user, self.matter, WED, '11:00', '11:12', unit=2, charged=False)
        events, data = events_of(self.user)
        self.assertEqual([e['kind'] for e in events], ['note', 'note'])
        totals = data['totals']
        self.assertEqual(totals['chargeable_minutes'], 30)
        self.assertEqual(totals['non_chargeable_minutes'], 12)
        self.assertEqual(totals['recorded_label'], '0:42')
        self.assertEqual(totals['units_chargeable'], 5)
        self.assertEqual(events[0]['time_label'], '09:00–09:30')
        self.assertEqual(events[0]['href'], reverse('attendance_note_view', args=['ABC0010001']))
        self.assertEqual(events[0]['edit_href'], reverse('edit_attendance_note', args=[events[0]['id']]))
        self.assertEqual(events[0]['client_names'], 'Mo Client')
        self.assertIn('Discussed the matter', events[0]['detail'])

    def test_note_unit_field_beats_the_clock_span(self):
        make_note(self.user, self.matter, WED, '09:00', '09:20', unit=3)
        events, _ = events_of(self.user)
        self.assertEqual((events[0]['units'], events[0]['minutes']), (3, 18))

    def test_note_without_unit_falls_back_to_span(self):
        make_note(self.user, self.matter, WED, '09:00', '09:20', unit=None)
        events, _ = events_of(self.user)
        self.assertEqual((events[0]['units'], events[0]['minutes']), (4, 24))

    def test_finish_before_start_is_flagged_not_fatal(self):
        make_note(self.user, self.matter, WED, '10:00', '09:30', unit=1)
        events, data = events_of(self.user, view='day')
        self.assertTrue(events[0]['suspect'])
        self.assertEqual(events[0]['end'], events[0]['start'] + timedelta(minutes=6))
        self.assertEqual(data['totals']['recorded_minutes'], 6)

    def test_emails_count_as_chargeable_units_with_direction(self):
        make_email(self.user, self.matter, aware(WED, '10:15'), units=2, sent=True)
        make_email(self.user, self.matter, aware(WED, '14:00'), units=None, sent=False, subject='')
        events, data = events_of(self.user)
        sent, received = events
        self.assertEqual((sent['direction'], sent['minutes'], sent['time_label']), ('sent', 12, '10:15'))
        self.assertEqual(sent['detail'], 'To: Bob Client')
        self.assertEqual(sent['href'], 'https://outlook.example/message/1')
        self.assertEqual(sent['edit_href'], reverse('correspondence_view', args=['ABC0010001']))
        self.assertEqual((received['direction'], received['minutes'], received['title']),
                         ('received', 0, '(No subject)'))
        self.assertEqual(received['detail'], 'From: Bob Client')
        self.assertEqual(data['totals']['chargeable_minutes'], 12)

    def test_email_is_placed_on_its_local_date(self):
        make_email(self.user, self.matter,
                   datetime(2026, 9, 8, 23, 30, tzinfo=dt_timezone.utc), units=1)
        events, _ = events_of(self.user, view='day', anchor=WED)
        self.assertEqual(len(events), 1)
        self.assertEqual((events[0]['date'], events[0]['time_label']), (WED, '00:30'))

    def test_email_party_tolerates_dicts_and_garbage(self):
        party = {'emailAddress': {'name': 'Dict Party', 'address': 'd@example.com'}}
        make_email(self.user, self.matter, aware(WED, '09:00'), sender=party, receiver=[party])
        make_email(self.user, self.matter, aware(WED, '09:30'), sender='{not json', receiver='')
        events, _ = events_of(self.user)
        self.assertEqual(events[0]['detail'], 'To: Dict Party')
        self.assertEqual(events[1]['detail'], '')

    def test_letters_are_untimed_single_units(self):
        make_letter(self.user, self.matter, WED, sent=False, charged=None)
        events, data = events_of(self.user)
        letter = events[0]
        self.assertTrue(letter['untimed'])
        self.assertEqual((letter['units'], letter['minutes'], letter['direction']), (1, 6, 'received'))
        self.assertTrue(letter['is_charged'])
        self.assertEqual(letter['detail'], 'From Other side solicitors')
        self.assertEqual(letter['edit_href'], reverse('edit_letter', args=[letter['id']]))
        self.assertEqual(data['totals']['chargeable_minutes'], 6)

    def test_meetings_are_non_chargeable(self):
        make_meeting(self.user, WED, '15:00', '15:30')
        make_meeting(self.user, WED, '16:00', '16:00', attendee='Zero Span')
        events, data = events_of(self.user)
        self.assertEqual(events[0]['title'], 'Free 30 mins – Alice Enquirer')
        self.assertEqual((events[0]['units'], events[0]['minutes'], events[0]['is_charged']), (5, 30, False))
        self.assertEqual(events[1]['minutes'], 30)
        self.assertEqual(events[0]['edit_href'], reverse('edit_free30mins', args=[events[0]['id']]))
        self.assertEqual(data['totals']['non_chargeable_minutes'], 60)
        self.assertEqual(data['totals']['chargeable_minutes'], 0)

    def test_tasks_are_zero_time_markers(self):
        make_task(self.user, self.matter, WED)
        undated = LastWork.objects.create(file_number=self.matter, person=self.user,
                                          task='Undated but completed today', date=None)
        LastWork.objects.filter(pk=undated.pk).update(timestamp=aware(WED, '16:45'))
        events, data = events_of(self.user, view='day')
        self.assertEqual([e['title'] for e in events],
                         ['File the claim form', 'Undated but completed today'])
        self.assertTrue(all(e['untimed'] and e['minutes'] == 0 and e['is_charged'] is None for e in events))
        self.assertEqual(data['totals']['recorded_minutes'], 0)
        self.assertEqual(data['totals']['counts']['task'], 2)
        self.assertEqual(events[0]['href'], reverse('home', args=['ABC0010001']))

    def test_type_filter_limits_sources(self):
        make_note(self.user, self.matter, WED, '09:00', '09:30')
        make_email(self.user, self.matter, aware(WED, '10:00'))
        events, data = events_of(self.user, kinds=['email'])
        self.assertEqual([e['kind'] for e in events], ['email'])
        self.assertEqual(data['selected_kinds'], ['email'])
        self.assertEqual(data['totals']['counts']['note'], 0)

    def test_weekend_column_only_when_used(self):
        make_note(self.user, self.matter, WED, '09:00', '09:30')
        _, data = events_of(self.user)
        self.assertEqual([d['weekday_label'] for d in data['days']], ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'])
        make_note(self.user, self.matter, SAT, '09:00', '09:30')
        _, data = events_of(self.user)
        self.assertEqual([d['weekday_label'] for d in data['days']],
                         ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'])
        self.assertEqual(data['totals']['recorded_minutes'], 60)

    def test_only_work_attributed_to_the_person_counts(self):
        make_note(self.other, self.matter, WED, '09:00', '09:30')
        make_note(self.other, self.matter, WED, '10:00', '10:30', created_by=self.user)
        make_email(self.other, self.matter, aware(WED, '11:00'))
        make_note(self.user, self.matter, WED, '12:00', '12:30', subject='Mine')
        events, _ = events_of(self.user)
        self.assertEqual([e['title'] for e in events], ['Mine'])

    def test_working_day_context_flags(self):
        tue = MON + timedelta(days=1)
        HolidayRecord.objects.create(employee=self.user, start_date=aware(tue, '00:00'),
                                     end_date=aware(tue, '23:59'), approved=True)
        HolidayRecord.objects.create(employee=self.user, start_date=aware(WED, '00:00'),
                                     end_date=aware(WED, '23:59'), approved=False)
        SicknessRecord.objects.create(employee=self.user, start_date=aware(MON + timedelta(days=3), '09:00'),
                                      end_date=None, description='Flu', created_by=self.user)
        AttendanceRecord.objects.create(employee=self.user, date=WED,
                                        clock_in=aware(WED, '08:30'), clock_out=aware(WED, '17:00'))
        ctx = tl.working_day_contexts(self.user, MON, MON + timedelta(days=6))
        self.assertTrue(ctx[tue]['on_holiday'])
        self.assertEqual(ctx[tue]['holiday_label'], 'Holiday')
        self.assertFalse(ctx[WED]['on_holiday'])
        self.assertTrue(ctx[MON + timedelta(days=3)]['off_sick'])
        self.assertTrue(ctx[MON + timedelta(days=4)]['off_sick'])
        self.assertTrue(ctx[MON + timedelta(days=5)]['is_weekend'])
        self.assertEqual(ctx[WED]['clock_in'].strftime('%H:%M'), '08:30')
        working = [d for d in ctx if ctx[d]['is_working_day']]
        self.assertEqual(working, [MON, WED])

        _, data = events_of(self.user, view='day')
        self.assertEqual(data['days'][0]['shade']['label'], '08:30–17:00')

    def test_week_target_and_value(self):
        rate = Rate.objects.create(desc='Associate', hourly_amount=Decimal('200.00'))
        self.user.hourly_rate = rate
        self.user.save()
        HolidayRecord.objects.create(employee=self.user, start_date=aware(MON, '00:00'),
                                     end_date=aware(MON, '23:59'), approved=True)
        make_note(self.user, self.matter, WED, '09:00', '09:30', unit=5)
        make_note(self.user, self.matter, WED, '10:00', '10:30', unit=5, charged=False)
        _, data = events_of(self.user)
        totals = data['totals']
        self.assertEqual(totals['working_days'], 4)
        self.assertEqual(totals['target_minutes'], 1800)
        self.assertEqual(totals['progress_pct'], 3)
        self.assertEqual(totals['value'], Decimal('100.00'))
        self.assertEqual(totals['value_label'], '£100.00')

        self.user.hourly_rate = None
        self.user.save()
        _, data = events_of(self.user)
        self.assertIsNone(data['totals']['value'])

    def test_month_view_sums_only_days_in_month(self):
        make_note(self.user, self.matter, date(2026, 8, 31), '09:00', '09:30', unit=5)
        make_note(self.user, self.matter, WED, '09:00', '09:30', unit=5)
        _, data = events_of(self.user, view='month')
        self.assertEqual(len(data['weeks']), 5)
        self.assertEqual(data['totals']['recorded_minutes'], 30)
        first_cell = data['weeks'][0][0]
        self.assertFalse(first_cell['in_month'])
        self.assertEqual(first_cell['totals']['recorded_minutes'], 30)
        self.assertIn('tl_view=day', first_cell['day_query'])


# ---------------------------------------------------------------------------
# Views: access and rendering
# ---------------------------------------------------------------------------

class HostPageTests(TestCase):
    def setUp(self):
        self.staff = make_user('STF')
        self.other = make_user('OTH')
        self.manager = make_user('MGR', manager=True)
        self.matter = make_matter('STF0010001', make_client('Mo Client'), fee_earner=self.staff)
        make_note(self.staff, self.matter, WED, '09:00', '09:30', subject='Staff call note')
        make_note(self.other, make_matter('OTH0010001', make_client('Other Client')),
                  WED, '09:00', '09:30', subject='Other persons note')
        self.panel = reverse('staff_timeline_panel')
        self.week = {'tl_view': 'week', 'tl_date': WED.isoformat()}

    def test_panel_requires_login(self):
        response = self.client.get(self.panel, self.week)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.url.lower())

    def test_dashboard_shows_my_time_card(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('user_dashboard'), self.week)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'My time')
        self.assertContains(response, 'data-tl-root')
        self.assertContains(response, 'Staff call note')
        self.assertContains(response, "js/staff-timeline.js")
        self.assertNotContains(response, 'data-tl-value')
        self.assertEqual(response.context['tl_subject'], self.staff)

    def test_dashboard_ignores_tl_user(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('user_dashboard'),
                                   {**self.week, 'tl_user': self.other.id})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Staff call note')
        self.assertNotContains(response, 'Other persons note')

    def test_panel_self_and_other_access(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(self.panel, self.week).status_code, 200)
        self.assertEqual(self.client.get(self.panel, {**self.week, 'tl_user': self.staff.id}).status_code, 200)
        self.assertEqual(self.client.get(self.panel, {**self.week, 'tl_user': self.other.id}).status_code, 403)
        self.assertEqual(self.client.get(self.panel, {**self.week, 'tl_user': 'abc'}).status_code, 404)

    def test_manager_can_view_anyone(self):
        self.client.force_login(self.manager)
        response = self.client.get(self.panel, {**self.week, 'tl_user': self.other.id})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Other persons note')
        self.assertNotContains(response, 'Staff call note')
        self.assertContains(response, 'data-tl-value')
        self.assertContains(response, reverse('management_reports') + '?tl_view=day')
        self.assertContains(response, f'tl_user={self.other.id}')
        self.assertEqual(self.client.get(self.panel, {**self.week, 'tl_user': 999999}).status_code, 404)

    def test_management_reports_embeds_timeline_for_selected_user(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse('management_reports'),
                                   {**self.week, 'tl_user': self.other.id})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Staff timeline')
        self.assertContains(response, 'Other persons note')
        self.assertContains(response, f'<option value="{self.other.id}" selected>')
        self.assertContains(response, 'policies-progress-bar')
        self.assertNotContains(response, 'prev-week')
        self.assertContains(response, 'data-tl-value')

    def test_management_reports_defaults_to_the_manager(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse('management_reports'))
        self.assertEqual(response.context['tl_subject'], self.manager)

    def test_management_reports_still_manager_only(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse('management_reports')).status_code, 403)

    def test_reports_hub_no_longer_links_the_json_endpoint(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse('reports_hub'))
        self.assertNotContains(response, reverse('user_weekly_report'))
        self.assertContains(response, reverse('management_reports'))

    def test_bad_params_fall_back(self):
        self.client.force_login(self.staff)
        response = self.client.get(self.panel, {'tl_view': 'bogus', 'tl_date': '2026-99-99'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['tl']['view'], 'week')
        self.assertEqual(response.context['tl']['anchor'], timezone.localdate())

    def test_week_panel_markup(self):
        self.client.force_login(self.staff)
        response = self.client.get(self.panel, self.week)
        host = reverse('user_dashboard')
        self.assertContains(response, 'Staff call note')
        self.assertContains(response, reverse('attendance_note_view', args=['STF0010001']))
        self.assertContains(response, reverse('home', args=['STF0010001']))
        self.assertContains(response, f'href="{host}?tl_view=week&amp;tl_date=2026-08-31"')
        self.assertContains(response, f'href="{host}?tl_view=week&amp;tl_date=2026-09-14"')
        self.assertContains(response, 'data-tl-query="tl_view=week&amp;tl_date=2026-09-09"')
        self.assertContains(response, '7 – 11 Sep 2026')
        self.assertContains(response, '0:30')
        self.assertContains(response, 'tl-ev-note')

    def test_day_view_shows_detail_and_nc_badge(self):
        make_note(self.staff, self.matter, WED, '11:00', '11:30', charged=False, subject='Admin catch-up')
        self.client.force_login(self.staff)
        response = self.client.get(self.panel, {'tl_view': 'day', 'tl_date': WED.isoformat()})
        self.assertContains(response, 'Mo Client')
        self.assertContains(response, 'N/C')
        self.assertContains(response, 'tl-ev-note-nc')
        self.assertContains(response, 'Wednesday 9 September 2026')

    def test_month_view_cells_link_to_day(self):
        self.client.force_login(self.staff)
        response = self.client.get(self.panel, {'tl_view': 'month', 'tl_date': WED.isoformat()})
        self.assertContains(response, 'September 2026')
        self.assertContains(response, 'tl_view=day&amp;tl_date=2026-09-09')
        self.assertContains(response, 'tl-dot-note')

    def test_type_chip_and_email_template(self):
        make_email(self.staff, self.matter, aware(WED, '10:00'), subject='Completion funds')
        self.client.force_login(self.staff)
        response = self.client.get(self.panel, {**self.week, 'tl_types': 'email'})
        self.assertContains(response, 'Completion funds')
        self.assertNotContains(response, 'Staff call note')
        self.assertContains(response, 'https://outlook.example/message/1')
        self.assertContains(response, 'tl_types=note&amp;tl_types=email')
