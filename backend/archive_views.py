"""The Archive card on the matter home: retention dates and whether the paper
file is back in the office. Separate from the edit-file form so a routine edit
can never blank these, and so "brought down" / "returned" is one click."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from .audit import log_field_change
from .forms import ArchiveDetailsForm
from .models import WIP


@login_required
@require_POST
def matter_archive_details(request, file_number):
    matter = get_object_or_404(WIP, file_number=file_number)
    back = redirect('home', file_number=file_number)

    if request.POST.get('action') == 'returned':
        # The paper file has gone back to storage.
        if matter.brought_down_on:
            log_field_change(request.user, matter, 'brought_down_on', matter.brought_down_on, None)
            matter.brought_down_on = None
            matter.save(update_fields=['brought_down_on'])
        messages.success(request, 'Recorded: physical file returned to archive.')
        return back

    data = request.POST.copy()
    if data.get('action') == 'brought_down' and not data.get('brought_down_on'):
        data['brought_down_on'] = timezone.localdate().isoformat()
    form = ArchiveDetailsForm(data, instance=matter)
    if not form.is_valid():
        for name, errors in form.errors.items():
            messages.error(request, f"{form.fields[name].label}: {', '.join(errors)}")
        return back

    before = {name: getattr(matter, name) for name in form.changed_data}
    form.save()
    for name, old in before.items():
        log_field_change(request.user, matter, name, old, getattr(matter, name))
    messages.success(request, 'Archive details saved.')
    return back
