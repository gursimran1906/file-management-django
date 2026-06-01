"""Matter time recording helpers."""

from datetime import timedelta
from math import ceil

from django.utils import timezone

from .models import (
    MatterAttendanceNotes,
    MatterEmails,
    MatterLetters,
    MatterTimeEvent,
    MatterTimeSession,
    WIP,
)


def compute_units_from_minutes(minutes):
    if minutes <= 0:
        return 1
    return max(1, ceil(minutes / 6))


def compute_units_from_times(start_time, finish_time):
    start_minutes = start_time.hour * 60 + start_time.minute
    finish_minutes = finish_time.hour * 60 + finish_time.minute
    diff = finish_minutes - start_minutes
    if diff <= 0:
        diff += 24 * 60
    return compute_units_from_minutes(diff)


def compute_units_from_datetimes(started_at, ended_at):
    delta = ended_at - started_at
    minutes = max(1, int(delta.total_seconds() // 60))
    return compute_units_from_minutes(minutes)


def get_matter_for_file_number(file_number):
    return WIP.objects.filter(file_number=file_number).first()


def get_active_session(user):
    return (
        MatterTimeSession.objects.select_related('file_number')
        .filter(user=user)
        .first()
    )


def mirror_event_to_attendance_note(event):
    if event.attendance_note_id:
        return event.attendance_note

    local_start = timezone.localtime(event.started_at)
    local_end = timezone.localtime(event.ended_at)
    detail_html = event.detail or event.description
    note = MatterAttendanceNotes.objects.create(
        file_number=event.file_number,
        start_time=local_start.time(),
        finish_time=local_end.time(),
        subject_line=event.description[:255],
        content={'html': f'<p>{detail_html}</p>'},
        is_charged=event.is_charged,
        person_attended=event.user,
        date=local_start.date(),
        unit=event.units,
        created_by=event.created_by,
    )
    event.attendance_note = note
    event.save(update_fields=['attendance_note'])
    return note


def confirm_time_event(event, mirror_attendance=True):
    event.status = MatterTimeEvent.STATUS_CONFIRMED
    event.save(update_fields=['status'])
    if mirror_attendance:
        mirror_event_to_attendance_note(event)
    return event


def create_quick_log_event(
    *,
    matter,
    user,
    created_by,
    description,
    minutes,
    activity_type,
    is_charged=True,
    mirror_attendance=True,
):
    ended_at = timezone.now()
    started_at = ended_at - timedelta(minutes=minutes)
    units = compute_units_from_minutes(minutes)
    event = MatterTimeEvent.objects.create(
        file_number=matter,
        user=user,
        created_by=created_by,
        started_at=started_at,
        ended_at=ended_at,
        description=description[:255],
        activity_type=activity_type,
        source=MatterTimeEvent.SOURCE_MANUAL,
        is_charged=is_charged,
        status=MatterTimeEvent.STATUS_CONFIRMED,
        units=units,
    )
    if mirror_attendance:
        mirror_event_to_attendance_note(event)
    return event


def get_unlogged_dashboard_files(user, dashboard_wips, days=1):
    """Files on the dashboard with recent task activity but no confirmed time."""
    if not dashboard_wips:
        return []

    since = timezone.now() - timedelta(days=days)
    wip_ids = [w.id for w in dashboard_wips]
    logged_wip_ids = set(
        MatterTimeEvent.objects.filter(
            file_number_id__in=wip_ids,
            user=user,
            status=MatterTimeEvent.STATUS_CONFIRMED,
            ended_at__gte=since,
        ).values_list('file_number_id', flat=True)
    )
    unlogged = []
    for wip in dashboard_wips:
        if wip.id in logged_wip_ids:
            continue
        from .models import LastWork, NextWork
        has_recent_task = (
            NextWork.objects.filter(
                file_number=wip, person=user, timestamp__gte=since,
            ).exists()
            or LastWork.objects.filter(
                file_number=wip, person=user, timestamp__gte=since,
            ).exists()
        )
        if has_recent_task:
            unlogged.append(wip)
    return unlogged


def lock_time_events_for_invoice(invoice):
    """Lock confirmed time on a matter when an invoice is finalised."""
    if not invoice or not invoice.file_number_id:
        return 0
    now = timezone.now()
    return MatterTimeEvent.objects.filter(
        file_number_id=invoice.file_number_id,
        status=MatterTimeEvent.STATUS_CONFIRMED,
        locked_at__isnull=True,
    ).update(locked_at=now, invoice=invoice)


def sync_time_event_from_email(email):
    """Upsert a MatterTimeEvent for a synced MatterEmails row."""
    if not email or not email.file_number_id:
        return None
    units = email.units or 1
    ended = email.time or timezone.now()
    started = ended
    desc = (email.subject or 'Email')[:255]
    activity = (
        MatterTimeEvent.ACTIVITY_DRAFTING
        if email.is_sent
        else MatterTimeEvent.ACTIVITY_PERUSAL
    )
    event, created = MatterTimeEvent.objects.update_or_create(
        source=MatterTimeEvent.SOURCE_EMAIL,
        source_id=email.id,
        defaults={
            'file_number': email.file_number,
            'user': email.fee_earner,
            'created_by': email.fee_earner,
            'started_at': started,
            'ended_at': ended,
            'description': desc,
            'activity_type': activity,
            'is_charged': True,
            'status': MatterTimeEvent.STATUS_CONFIRMED,
            'units': units,
        },
    )
    return event


def sync_time_event_from_letter(letter):
    """Upsert a MatterTimeEvent for a MatterLetters row."""
    if not letter or not letter.file_number_id:
        return None
    from datetime import datetime, time as dt_time
    if letter.date:
        ended = timezone.make_aware(datetime.combine(letter.date, dt_time.min))
    else:
        ended = timezone.now()
    desc = (letter.subject_line or 'Letter')[:255]
    event, _created = MatterTimeEvent.objects.update_or_create(
        source=MatterTimeEvent.SOURCE_LETTER,
        source_id=letter.id,
        defaults={
            'file_number': letter.file_number,
            'user': letter.person_attended,
            'created_by': letter.created_by,
            'started_at': ended,
            'ended_at': ended,
            'description': desc,
            'activity_type': MatterTimeEvent.ACTIVITY_DRAFTING,
            'is_charged': letter.is_charged if letter.is_charged is not None else True,
            'status': MatterTimeEvent.STATUS_CONFIRMED,
            'units': 1,
        },
    )
    return event


def sowc_rows_from_time_events(file_number_id, exclude_attendance_note_ids=None):
    """
    Return SOWC-style rows for confirmed events not already mirrored to attendance notes.
    Normally empty because timer/quick-log mirror to attendance notes.
    """
    exclude_attendance_note_ids = exclude_attendance_note_ids or set()
    qs = MatterTimeEvent.objects.filter(
        file_number_id=file_number_id,
        status=MatterTimeEvent.STATUS_CONFIRMED,
    ).select_related('user', 'file_number__fee_earner')
    rows = []
    for event in qs:
        if event.attendance_note_id and event.attendance_note_id in exclude_attendance_note_ids:
            continue
        if event.attendance_note_id:
            continue
        local_end = timezone.localtime(event.ended_at)
        fee_earner = event.user.username if event.user else ''
        nc = ' (N/C)' if not event.is_charged else ''
        desc = f'{event.get_activity_type_display()}{nc} - {event.description}'
        amount_user = event.user or (event.file_number.fee_earner if event.file_number else None)
        if amount_user and getattr(amount_user, 'hourly_rate', None):
            amount = (amount_user.hourly_rate.hourly_amount / 10) * event.units
        else:
            amount = 0
        rows.append([
            local_end.strftime('%d/%m/%Y'),
            local_end.strftime('%H:%M'),
            fee_earner,
            desc,
            event.units,
            amount,
        ])
    return rows
