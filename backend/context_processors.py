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
