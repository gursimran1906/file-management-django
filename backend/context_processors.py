from .models import WIP


def matter_nav(request):
    file_number = None
    matter_is_probate = False
    resolver_match = getattr(request, 'resolver_match', None)
    if resolver_match:
        file_number = resolver_match.kwargs.get('file_number')
    matter = None
    if file_number:
        matter = WIP.objects.select_related('matter_type').filter(
            file_number=file_number
        ).first()
        if matter and matter.matter_type:
            matter_is_probate = matter.matter_type.type.lower() == 'probate'
    matter_wip_id = None
    if file_number and matter:
        matter_wip_id = matter.id
    return {
        'file_number': file_number,
        'matter_is_probate': matter_is_probate,
        'matter_wip_id': matter_wip_id,
    }
