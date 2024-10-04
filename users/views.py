# myapp/views.py
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.urls import reverse
from urllib.parse import unquote
from .models import CustomUser, HolidayRecord

from .forms import CustomUserCreationForm
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from datetime import datetime
from datetime import timedelta
import holidays


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

@login_required
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

def calculate_business_days(start_date, end_date):
    holiday_list = holidays.country_holidays('GB', subdiv='ENG')
    current_date = start_date
    total_days = 0
    while current_date <= end_date:
        if current_date.weekday() < 5 and current_date not in holiday_list:
            total_days += 1
        current_date += timedelta(days=1)
    return total_days

@login_required
def profile_page(request):
    holiday_requests = HolidayRecord.objects.filter(employee=request.user)

    requests_with_total_days = []
    total_paid_holidays = 0
    total_unpaid_holidays = 0
    for holiday_request in holiday_requests:
        total_days = 0
        if holiday_request.start_date and holiday_request.end_date:
            start_date = holiday_request.start_date
            end_date = holiday_request.end_date
            total_days = calculate_business_days(start_date, end_date)
            if holiday_request.type == 'Paid':
                total_paid_holidays  = total_paid_holidays + total_days
            else:
                total_unpaid_holidays = total_unpaid_holidays + total_days

        requests_with_total_days.append({
            'request': holiday_request,
            'total_days': total_days,
        })

    return render(request, 'profile_page.html', {'holiday_requests': requests_with_total_days, 
                                                 'total_paid_holidays': total_paid_holidays, 
                                                 'total_unpaid_holidays': total_unpaid_holidays})

@login_required
def add_holiday_request(request):
    if request.method == 'POST':
        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date')
        reason = request.POST.get('reason', '')
        type = request.POST.get('type')
        
        start_date_dt = datetime.fromisoformat(start_date)
        end_date_dt = datetime.fromisoformat(end_date)

        num_days_requested = calculate_business_days(start_date_dt, end_date_dt)

        user = request.user
        holidays_remaining = user.remaining_holidays

        if num_days_requested > holidays_remaining and type == 'Paid':
            exceeding_amount = num_days_requested - holidays_remaining
            messages.error(request, f'You have requested {num_days_requested} business days, but only have {holidays_remaining} holidays remaining. You are exceeding by {exceeding_amount} days.')
        else:
            try:
                holiday_request = HolidayRecord(
                    employee=user,
                    start_date=start_date,
                    end_date=end_date,
                    type=type,
                    reason=reason,
                )
                holiday_request.save()
                if type == 'Paid':
                    user.remaining_holidays -= num_days_requested
                    user.save()

                messages.success(request, 'Holiday request submitted successfully.')
            except Exception as e:
                messages.error(request, 'There was an error submitting your holiday request. Please try again.')

        return redirect('profile_page')

    return redirect('profile_page')