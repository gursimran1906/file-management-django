def matter_nav(request):
    file_number = None
    resolver_match = getattr(request, 'resolver_match', None)
    if resolver_match:
        file_number = resolver_match.kwargs.get('file_number')
    return {'file_number': file_number}
