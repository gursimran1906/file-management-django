# myapp/views.py
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.urls import reverse
from urllib.parse import unquote
from .forms import CustomUserCreationForm

def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request,user)
            
            next_param = request.GET.get('next', '')
            next_page = unquote(next_param) if next_param else reverse('user_dashboard')
            return redirect(next_page)
        else:
            
            return render(request, 'login.html', {'error_message': 'Invalid login credentials, Please check username or password'})
    else:
        return render(request, 'login.html')
    

def logout_view(request):
    user = request.user.username
    logout(request)
    log_out_msg = 'Successfully Logged ' + str(user) + ' out!!'
    return render(request, 'login.html', {'message': log_out_msg})

def register_view(request):
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect(reverse('user_dashboard'))
    else:
        form = CustomUserCreationForm()
    return render(request, 'register.html', {'form': form})