# myapp/views.py
from decimal import Decimal
import math
from time import strftime
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth import authenticate, login, logout
from django.urls import reverse
from urllib.parse import unquote
from .models import AttendanceRecord, CustomUser, HolidayRecord, SicknessRecord
from django.utils import timezone
from .forms import CustomUserCreationForm, HolidayRecordForm
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from datetime import datetime, time
from datetime import timedelta
import holidays
from django.core.exceptions import ObjectDoesNotExist



def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request,user)
            today = timezone.now().date()
            attendance_record = AttendanceRecord.objects.filter(employee=user, date=today).first()
            if attendance_record is None:
                AttendanceRecord.objects.create(
                    employee=user,
                    date=today,
                    clock_in=timezone.now()
                )
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

from datetime import timedelta, datetime, time
import holidays
import math
from django.utils import timezone

def calculate_business_days(start_date, end_date):
    # Define work hours
    work_start = time(9, 0)  # 09:00 AM
    work_end = time(17, 0)   # 5:00 PM

    # Ensure both start_date and end_date are timezone-aware
    if timezone.is_naive(start_date):
        start_date = timezone.make_aware(start_date)
    if timezone.is_naive(end_date):
        end_date = timezone.make_aware(end_date)

    # Adjust the start_date according to the specified rules
    if start_date.time() < work_start:  # Before 9:00 AM
        # Set to today at 9:00 AM
        start_date = datetime.combine(start_date.date(), work_start, tzinfo=start_date.tzinfo)
    elif start_date.time() >= work_end:  # After 5:00 PM
        # Move to the next business day at 9:00 AM
        start_date = datetime.combine(start_date.date() + timedelta(days=1), work_start, tzinfo=start_date.tzinfo)
        # Skip weekends
        while start_date.weekday() >= 5:
            start_date += timedelta(days=1)

    # Adjust end_date if it's outside work hours
    if end_date.time() > work_end:
        # Set end_date to 5:00 PM on the same date
        end_date = datetime.combine(end_date.date(), work_end, tzinfo=end_date.tzinfo)
    elif end_date.time() < work_start:
        # If the end time is before the start of work hours, set it to 5:00 PM on the previous workday
        end_date = datetime.combine(end_date.date() - timedelta(days=1), work_end, tzinfo=end_date.tzinfo)
        # Skip weekends
        while end_date.weekday() >= 5:
            end_date -= timedelta(days=1)

    # Create UK holiday list
    holiday_list = holidays.country_holidays('GB', subdiv='ENG')
    
    # Initialize the total hours counter
    total_hours = 0
    current_date = start_date

    while current_date <= end_date:
        # Check if current date is a weekday and not a holiday
        if current_date.weekday() < 5:
            # Calculate workday start and end times for the current date
            day_start = datetime.combine(current_date.date(), work_start, tzinfo=current_date.tzinfo)
            day_end = datetime.combine(current_date.date(), work_end, tzinfo=current_date.tzinfo)
            
            # Determine the actual start and end for counting within the working hours
            actual_start = max(current_date, day_start)
            actual_end = min(end_date, day_end)
            
            # If within work hours, calculate the difference in hours
            if actual_start < actual_end:
                hours_worked = (actual_end - actual_start).total_seconds() / 3600
                total_hours += hours_worked

        # Move to the next day
        current_date += timedelta(days=1)

    # Convert hours to work days (8 hours = 1 work day)
    total_days = total_hours / 8
    
    # Round total_days to the nearest 0.5
    total_days = math.ceil(total_days * 2) / 2

    return total_days

@login_required
def profile_page(request):
    employees = CustomUser.objects.filter(is_active=True)
    user = request.user
    current_year = timezone.now().year
   
    holiday_requests = HolidayRecord.objects.filter(
        employee=user
    ).order_by('-timestamp')
    if request.user.is_manager:
        all_requests = HolidayRecord.objects.filter(checked_by=None)
    else:
        all_requests=None
    attendance_records = AttendanceRecord.objects.filter(employee=user).order_by('-date')
    sickness_records = SicknessRecord.objects.filter(employee=user).order_by('-start_date')
    requests_with_total_days = []
    total_paid_holidays = 0
    total_unpaid_holidays = 0
    for holiday_request in holiday_requests:
        total_days = 0
        if holiday_request.start_date and holiday_request.end_date:
            start_date = holiday_request.start_date
            end_date = holiday_request.end_date
            total_days = calculate_business_days(start_date, end_date)
            if start_date.year == current_year:
                if holiday_request.type == 'Paid':
                    total_paid_holidays  = total_paid_holidays + total_days
                else:
                    total_unpaid_holidays = total_unpaid_holidays + total_days

        requests_with_total_days.append({
            'request': holiday_request,
            'total_days': total_days,
        })
    total_paid_holidays_remaining = user.max_holidays_in_year - Decimal(total_paid_holidays)
    return render(request, 'profile_page.html', {'employees':employees,
                                                 'holiday_requests': requests_with_total_days,
                                                 'all_requests':all_requests,
                                                 'sickness_records':sickness_records,
                                                 'attendance_records': attendance_records, 
                                                 'total_paid_holidays': total_paid_holidays, 
                                                 'total_unpaid_holidays': total_unpaid_holidays,
                                                 'total_paid_holidays_remaining': total_paid_holidays_remaining})

@login_required
def holiday_records(request):
    if request.user.is_manager != True:
        messages.error(request,'You do not have right permissions to access the page.')
        return redirect('user_dashboard')
    requests_with_total_days = []
    current_year = timezone.now().year
    holiday_records = HolidayRecord.objects.all().select_related('employee')
    for holiday_request in holiday_records:
        total_days = 0
        if holiday_request.start_date and holiday_request.end_date:
            start_date = holiday_request.start_date
            end_date = holiday_request.end_date
            total_days = calculate_business_days(start_date, end_date)

        requests_with_total_days.append({
            'request': holiday_request,
            'total_days': total_days,
        })
    return render(request, 'holiday_records.html', {'holiday_records': requests_with_total_days})

@login_required
def sickness_records(request):
    if request.user.is_manager != True:
        messages.error(request,'You do not have right permissions to access the page.')
        return redirect('user_dashboard')
    sickness_records = SicknessRecord.objects.all().select_related('employee', 'created_by')
    return render(request, 'sickness_records.html', {'sickness_records': sickness_records})

# views.py
from django.http import JsonResponse
from .models import HolidayRecord, SicknessRecord
from datetime import timedelta

@login_required
def calendar_events(request):
    # Fetch holiday records
        
    holidays = HolidayRecord.objects.all()
    if request.user.is_manager:
        sickness_records = SicknessRecord.objects.all()
    else:
        sickness_records = SicknessRecord.objects.filter(employee=request.user)

    # Format data for FullCalendar
    '''
    Need colours for: 
    1. Paid Approved
    2. Unpaid Approved
    3. Paid Pending
    4. Unpaid Pending
    5. Sickness Record
    '''
    events = []
    for holiday in holidays:
        if holiday.checked_by != None and holiday.approved:
            event = {
                'title': f'{holiday.employee} - {'Annual Leave' if holiday.type == 'Paid' else 'Unpaid Leave'}',
                'start': holiday.start_date,
                'end': holiday.end_date,
                'description': f'Type: {holiday.type}, Approved: {holiday.approved}',
                'color': get_holiday_color(holiday),  
            }
            events.append(event)
        if holiday.checked_by == None and holiday.approved == False:
            event = {
                'title': f'(APPROVAL PENDING) {holiday.employee} - {'Annual Leave' if holiday.type == 'Paid' else 'Unpaid Leave'}',
                'start': holiday.start_date,
                'end': holiday.end_date,
                'description': f'Type: {holiday.type}, Approved: {holiday.approved}',
                'color': get_holiday_color(holiday),  
            }
            events.append(event)


    for sickness in sickness_records:
        event = {
            'title': f'{sickness.employee} - Sickness Record',
            'start': sickness.start_date,
            'end': sickness.end_date,
            'description': sickness.description,
            'color': '#6f42c1'  
        }
        events.append(event)

    return JsonResponse(events, safe=False)

def get_holiday_color(holiday):
    """ Determine color based on holiday type and approval status with eye-friendly colors. """
    if holiday.approved:
        return '#5cb85c' if holiday.type == 'Paid' else '#ffca66'  # Muted Green for Paid Approved, Soft Amber for Unpaid Approved
    else:
        return '#6699cc' if holiday.type == 'Paid' else '#ff9999'  # Muted Blue for Paid Pending, Soft Coral Red for Unpaid Pending

@login_required
def add_sickness_record(request):
    if not request.user.is_manager:
        messages.error(request, "You do not have permission to add a sickness record.")
        return redirect('profile_page')
    
    if request.method == 'POST':
        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date')
        employee_id = request.POST.get('employee')
        description = request.POST.get('description', '')
        
        try:
            # Attempt to retrieve the employee by ID
            employee_user = CustomUser.objects.get(id=employee_id)
            
            # Create the sickness record
            SicknessRecord.objects.create(
                start_date=start_date,
                end_date=end_date,
                employee=employee_user,
                description=description,
                created_by=request.user,
            )
            messages.success(request, "Sickness record added successfully.")
        
        except ObjectDoesNotExist:
            messages.error(request, "The specified employee does not exist.")
        except Exception as e:
            messages.error(request, f"An error occurred while adding the sickness record: {str(e)}")

    return redirect('profile_page')

@login_required
def add_holiday_request(request):
    if request.method == 'POST':
        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date')
        reason = request.POST.get('reason', '')
        holiday_type = request.POST.get('type')

        # Convert dates from string to datetime
        start_date_dt = datetime.fromisoformat(start_date)
        end_date_dt = datetime.fromisoformat(end_date)

        # Calculate the number of business days requested
        num_days_requested = calculate_business_days(start_date_dt, end_date_dt)

        user = request.user
        max_holidays_in_year = user.max_holidays_in_year

        # Determine the year of the requested holiday
        request_year = start_date_dt.year
        
        # Get all "Paid" holidays for the user within the requested year
        paid_holidays_in_request_year = HolidayRecord.objects.filter(
            employee=user,
            type='Paid',
            start_date__year=request_year
        )
        
        # Calculate the total number of paid holidays taken in that year
        total_paid_holidays_taken = sum(
            calculate_business_days(holiday.start_date, holiday.end_date)
            for holiday in paid_holidays_in_request_year
        )

        # Add the current request's days to the total
        total_holidays_after_request = total_paid_holidays_taken + num_days_requested

        # Check if the total number of paid holidays exceeds the user's maximum allowed holidays
        if total_holidays_after_request > max_holidays_in_year and holiday_type == 'Paid':
            exceeding_amount = total_holidays_after_request - max_holidays_in_year
            messages.error(request, f'You have requested {num_days_requested} business days in {request_year}, but this exceeds your yearly limit of {max_holidays_in_year} paid holidays by {exceeding_amount} days.')
        else:
            try:
                # Create the holiday request
                holiday_request = HolidayRecord(
                    employee=user,
                    start_date=start_date,
                    end_date=end_date,
                    type=holiday_type,
                    reason=reason,
                )
                holiday_request.save()

                messages.success(request, 'Holiday request submitted successfully.')
            except Exception as e:
                messages.error(request, 'There was an error submitting your holiday request. Please try again.')

        return redirect('profile_page')

    return redirect('profile_page')

@login_required
def approve_holiday_request(request, id):
    if request.user.is_manager:
        holiday_request = get_object_or_404(HolidayRecord, id=id)
        holiday_request.approved = True
        holiday_request.approved_by = request.user
        holiday_request.approved_on = timezone.now()
        holiday_request.checked_by = request.user
        holiday_request.checked_on = timezone.now()
        holiday_request.save()
    else:
        messages.error('You do not have right permissions.')
    return redirect('profile_page')

@login_required
def deny_holiday_request(request,id):
    if request.user.is_manager:
        holiday_request = get_object_or_404(HolidayRecord, id=id)
        holiday_request.approved = False
        holiday_request.checked_by = request.user
        holiday_request.checked_on = timezone.now()
        holiday_request.save()
    else:
        messages.error('You do not have right permissions.')
    return redirect('profile_page')

@login_required
def lunch_start(request):
    current_time = timezone.now()
    try:
        attendance_record = AttendanceRecord.objects.get(employee=request.user, date=current_time.date())
        
        # Check if lunch has already started
        if attendance_record.lunch_in:
            messages.error(
                request, 
                f'Your lunch break has already started at {attendance_record.lunch_in.astimezone(timezone.get_current_timezone()).strftime("%I:%M %p")}. '
                'Please inform your manager if this is incorrect.'
            )
        else:
            attendance_record.lunch_in = current_time
            attendance_record.save()
            messages.success(request, f'Your lunch break started at {current_time.astimezone(timezone.get_current_timezone()).strftime("%I:%M %p")}.')
    
    except AttendanceRecord.DoesNotExist:
        messages.error(request, 'Attendance record not found for today.')
    except Exception as e:
        messages.error(request, f'An error occurred: {e}')
    
    return redirect('user_dashboard')

@login_required
def lunch_out(request):
    current_time = timezone.now()
    try:
        attendance_record = AttendanceRecord.objects.get(employee=request.user, date=current_time.date())
        
        # Check if lunch has already ended
        if attendance_record.lunch_out:
            messages.error(
                request, 
                f'Your lunch break has already ended at {attendance_record.lunch_out.astimezone(timezone.get_current_timezone()).strftime("%I:%M %p")}. '
                'Please inform your manager if this is incorrect.'
            )
        elif not attendance_record.lunch_in:
            messages.error(request, 'You need to start lunch before ending it.')
        else:
            attendance_record.lunch_out = current_time
            attendance_record.save()
            messages.success(request, f'Your lunch break ended at {current_time.astimezone(timezone.get_current_timezone()).strftime("%I:%M %p")}.')
    
    except AttendanceRecord.DoesNotExist:
        messages.error(request, 'Attendance record not found for today.')
    except Exception as e:
        messages.error(request, f'An error occurred: {e}')
    
    return redirect('user_dashboard')

@login_required
def clock_out(request):
    current_time = timezone.now()
    try:
        attendance_record = AttendanceRecord.objects.get(employee=request.user, date=current_time.date())
        
        if attendance_record.clock_out:
            messages.error(
                request, 
                f'You have already clocked out at {attendance_record.clock_out.astimezone(timezone.get_current_timezone()).strftime("%I:%M %p")}. '
                'Please inform your manager if this is incorrect.'
            )
        else:
            attendance_record.clock_out = current_time
            attendance_record.save()
            messages.success(request, f'You have clocked out at {current_time.astimezone(timezone.get_current_timezone()).strftime("%I:%M %p")}.')
            
    except AttendanceRecord.DoesNotExist:
        messages.error(request, 'Attendance record not found for today.')
    except Exception as e:
        messages.error(request, f'An error occurred: {e}')
    
    return redirect('user_dashboard')


@login_required
def edit_holiday_record(request, holiday_id):
    """Edit an existing holiday record."""
    holiday = get_object_or_404(HolidayRecord, id=holiday_id)
    
    # Check if user has access to edit the record
    if not request.user.is_manager:
        if holiday.employee != request.user:
            messages.error(request, 'You do not have the right to access this page.')
            return redirect('profile_page')
        if holiday.checked_by is not None:
            messages.error(request, 'Please contact your manager to edit the record.')
            return redirect('profile_page')

    # Handle POST request with form submission
    if request.method == 'POST':
        form = HolidayRecordForm(request.POST, instance=holiday)
        if form.is_valid():
            updated_holiday = form.save(commit=False)
            
            # If the user is a manager, update approval fields
            if request.user.is_manager:
                updated_holiday.approved = request.POST.get('approved') == 'on'
                updated_holiday.checked_by = request.user
                updated_holiday.checked_on = timezone.now()
                
                if updated_holiday.approved:
                    updated_holiday.approved_by = request.user
                    updated_holiday.approved_on = timezone.now()
                    
            updated_holiday.save()
            messages.success(request, 'Holiday record updated successfully.')
            return redirect('profile_page')
        else:
            messages.error(request, 'Please correct the errors below.')
    
    # If GET request, pre-populate the form with the current holiday record
    else:
        form = HolidayRecordForm(instance=holiday)
    
    # Prepare context for rendering the form
    context = {
        'holiday': holiday,
        'form': form,
    }
    
    return render(request, 'edit_holiday.html', context)

# views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from .models import UserDocument
from .forms import UserDocumentForm

# View to add a new document
@login_required
def add_document(request):
    if request.method == 'POST':
        form = UserDocumentForm(request.POST, request.FILES)
        if form.is_valid():
            user_document = form.save(commit=False)
            user_document.added_by = request.user
            user_document.save()
            return redirect('document_list')
    else:
        form = UserDocumentForm()
    return render(request, 'add_document.html', {'form': form})

# View to delete a document
@login_required
def delete_document(request, uuid):
    user_document = get_object_or_404(UserDocument, uuid=uuid)
    if request.method == 'POST':
        user_document.delete()
        return redirect('document_list')
    return render(request, 'delete_document.html', {'document': user_document})

# View to access a document
@login_required
def access_document(request, uuid):
    user_document = get_object_or_404(UserDocument, uuid=uuid)
    return render(request, 'access_document.html', {'document': user_document})
