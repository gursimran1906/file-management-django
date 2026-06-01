from django.shortcuts import redirect, render
from django.contrib.auth.decorators import login_required
from django.urls import reverse


# Create your views here.
@login_required
def home_view(request, file_number):
    return render(request, 'home.html')


def root_view(request):
    """Site root: dashboard for signed-in users, login otherwise."""
    if request.user.is_authenticated:
        return redirect('user_dashboard')
    login_url = reverse('login')
    dashboard_url = reverse('user_dashboard')
    return redirect(f'{login_url}?next={dashboard_url}')


@login_required
def index_view(request):
    return render(request, 'index.html')