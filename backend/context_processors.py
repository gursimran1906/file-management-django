from .models import WIP


def matter_nav(request):
    file_number = None
    matter_is_probate = False
    matter_is_conveyancing = False
    resolver_match = getattr(request, 'resolver_match', None)
    if resolver_match:
        file_number = resolver_match.kwargs.get('file_number')
    if file_number:
        matter = WIP.objects.select_related('matter_type').filter(
            file_number=file_number
        ).first()
        if matter and matter.matter_type:
            matter_type_lower = matter.matter_type.type.lower()
            matter_is_probate = matter_type_lower == 'probate'
            matter_is_conveyancing = 'conveyancing' in matter_type_lower
    return {
        'file_number': file_number,
        'matter_is_probate': matter_is_probate,
        'matter_is_conveyancing': matter_is_conveyancing,
    }


def signoff_pending(request):
    """How many items await the signed-in fee earner's sign-off, for the
    navbar badge. Zero (and no query) for anyone who cannot sign off."""
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated or not user.is_matter_fee_earner:
        return {'signoff_pending_count': 0}
    from .signoff_queue import pending_count
    return {'signoff_pending_count': pending_count(user)}
