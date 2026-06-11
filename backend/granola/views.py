"""Central back-office UI for the Granola integration: settings, manual sync,
and the review inbox where unmatched notes are assigned to a matter."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from backend.models import GranolaConfig, GranolaImportedNote, WIP
from users.models import CustomUser

from .ingest import (create_attendance_note_from_imported,
                     create_free30_from_imported, resolve_api_key, sync_notes,
                     test_connection)


def _require_manager(request):
    """Granola back-office screens are manager-only."""
    return bool(getattr(request.user, 'is_manager', False))


@login_required
def granola_inbox(request):
    # Visible to all staff (the "Allocate › Meetings" tab). Settings/sync remain
    # manager-only and are hidden in the template for non-managers.
    pending = (GranolaImportedNote.objects
               .filter(status=GranolaImportedNote.STATUS_PENDING)
               .select_related('matched_fee_earner'))
    recent = (GranolaImportedNote.objects
              .filter(status=GranolaImportedNote.STATUS_CREATED)
              .select_related('matched_file', 'attendance_note', 'free30_meeting')[:25])
    dismissed = (GranolaImportedNote.objects
                 .filter(status=GranolaImportedNote.STATUS_IGNORED)
                 .order_by('-reviewed_at', '-timestamp')[:50])

    context = {
        'config': GranolaConfig.get_solo(),
        'pending_notes': pending,
        'recent_notes': recent,
        'dismissed_notes': dismissed,
        # Any active staff member can be the attendee / fee earner on a note.
        'fee_earners': CustomUser.objects.filter(is_active=True)
                                         .order_by('first_name', 'last_name'),
    }
    # AJAX tab swap fetches just the panel body.
    template = ('granola/_inbox_panel.html' if request.GET.get('partial')
                else 'granola/inbox.html')
    return render(request, template, context)


@login_required
@require_POST
def granola_assign_note(request, note_id):
    imported = get_object_or_404(GranolaImportedNote, id=note_id)
    file_number = (request.POST.get('file_number') or '').strip()
    matter = WIP.objects.filter(file_number__iexact=file_number).first()
    if not matter:
        messages.error(request, f'No matter found with file number "{file_number}".')
        return redirect('granola_inbox')

    person = None
    person_id = request.POST.get('person_attended')
    if person_id:
        person = CustomUser.objects.filter(id=person_id).first()
    person = person or imported.matched_fee_earner or matter.fee_earner
    is_charged = request.POST.get('is_charged') == 'on'

    note = create_attendance_note_from_imported(
        imported, file=matter, person_attended=person,
        is_charged=is_charged, created_by=request.user,
    )
    imported.reviewed_by = request.user
    imported.reviewed_at = timezone.now()
    imported.save(update_fields=['reviewed_by', 'reviewed_at'])
    messages.success(
        request,
        f'Attendance note created on {matter.file_number} ({note.unit} unit(s)).')
    return redirect('granola_inbox')


@login_required
@require_POST
def granola_create_free30(request, note_id):
    """Create a Free 30 minute meeting from a pending (party-less) note."""
    imported = get_object_or_404(GranolaImportedNote, id=note_id)
    fee_earner = None
    person_id = request.POST.get('fee_earner')
    if person_id:
        fee_earner = CustomUser.objects.filter(id=person_id).first()

    meeting = create_free30_from_imported(
        imported, fee_earner=fee_earner or imported.matched_fee_earner,
        created_by=request.user)
    imported.reviewed_by = request.user
    imported.reviewed_at = timezone.now()
    imported.save(update_fields=['reviewed_by', 'reviewed_at'])
    messages.success(
        request,
        f'Free 30 minute meeting created ({meeting.attendees.count()} attendee(s)).')
    return redirect('granola_inbox')


@login_required
@require_POST
def granola_ignore_note(request, note_id):
    imported = get_object_or_404(GranolaImportedNote, id=note_id)
    imported.status = GranolaImportedNote.STATUS_IGNORED
    imported.reviewed_by = request.user
    imported.reviewed_at = timezone.now()
    imported.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])
    messages.success(request, 'Note dismissed. You can restore it from the dismissed list.')
    return redirect('granola_inbox')


@login_required
@require_POST
def granola_restore_note(request, note_id):
    """Move a dismissed note back into the pending review queue."""
    imported = get_object_or_404(GranolaImportedNote, id=note_id)
    if imported.status == GranolaImportedNote.STATUS_IGNORED:
        imported.status = GranolaImportedNote.STATUS_PENDING
        imported.reviewed_by = None
        imported.reviewed_at = None
        imported.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])
        messages.success(request, 'Note restored to the review inbox.')
    return redirect('granola_inbox')


@login_required
def granola_guide(request):
    """How fee earners should format their notes — visible to all staff."""
    return render(request, 'granola/guide.html', {'config': GranolaConfig.get_solo()})


@login_required
def granola_settings(request):
    if not _require_manager(request):
        messages.error(request, 'You do not have access to Granola settings.')
        return redirect('user_dashboard')

    config = GranolaConfig.get_solo()
    if request.method == 'POST':
        config.api_key = (request.POST.get('api_key') or '').strip()
        config.enabled = request.POST.get('enabled') == 'on'
        config.attendance_folder = (request.POST.get('attendance_folder') or '').strip()
        config.free30_folder = (request.POST.get('free30_folder') or '').strip()
        config.start_date = (request.POST.get('start_date') or '').strip() or None
        config.updated_by = request.user
        config.save()
        messages.success(request, 'Granola settings saved.')
        return redirect('granola_settings')

    context = {
        'config': config,
        # True when a key is supplied via the environment (overrides the DB row).
        'key_from_env': bool(resolve_api_key(config)) and not config.api_key,
    }
    return render(request, 'granola/settings.html', context)


@login_required
@require_POST
def granola_sync_now(request):
    if not _require_manager(request):
        return redirect('user_dashboard')
    status = sync_notes(force=True)
    messages.success(request, f'Granola sync run: {status}')
    return redirect('granola_inbox')


@login_required
@require_POST
def granola_test_connection(request):
    """Dry run: check the API key + folders without importing anything."""
    if not _require_manager(request):
        return redirect('user_dashboard')
    ok, message = test_connection()
    (messages.success if ok else messages.error)(request, message)
    return redirect('granola_settings')
