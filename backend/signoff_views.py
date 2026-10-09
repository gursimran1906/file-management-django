"""The sign-off queue page: everything awaiting a fee earner, signed off in
place without leaving the page (the buttons post to the existing sign-off and
return views, which answer JSON to fetch requests)."""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .signoff_queue import TYPES, build_queue


@login_required
def signoff_queue(request):
    kind = request.GET.get('type', '')
    if kind not in TYPES:
        kind = ''
    items = build_queue(request.user, kind=kind)
    return render(request, 'signoff_queue.html', {
        'items': items,
        'type': kind,
        'types': TYPES,
        'yours_count': sum(1 for item in items if item.yours),
        'can_sign_off': request.user.is_matter_fee_earner,
    })
