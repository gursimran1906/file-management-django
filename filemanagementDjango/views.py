"""
CSRF Token Management View

This module provides an endpoint to fetch a fresh CSRF token.
This is used by the global CSRF retry mechanism to refresh expired tokens.
"""

from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required


@require_http_methods(["GET"])
def get_csrf_token(request):
    """
    Returns a fresh CSRF token as JSON.

    This endpoint is used by the client-side JavaScript to fetch a new CSRF token
    when the current token has expired. This prevents users from losing their form
    data when submitting after a long period of inactivity.

    Args:
        request: The HTTP request object

    Returns:
        JsonResponse: A JSON object containing the CSRF token
        Example: {"csrfToken": "abc123..."}
    """
    # Generate a fresh CSRF token for this request
    csrf_token = get_token(request)

    return JsonResponse({
        'csrfToken': csrf_token
    })
