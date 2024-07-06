from django.shortcuts import render
from django.contrib.auth.decorators import login_required


# Create your views here.
@login_required
def home_view(request, file_number):
    return render(request, 'home.html')

@login_required
def index_view(request):
    return render(request, 'index.html')