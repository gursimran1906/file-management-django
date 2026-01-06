# myapp/views.py
import logging
from .forms import UserDocumentForm
from .models import UserDocument
from django.shortcuts import render, redirect, get_object_or_404
from zipfile import ZipFile
from io import BytesIO
from .models import CustomUser, AttendanceRecord, HolidayRecord, SicknessRecord
from datetime import datetime, timedelta, date
from django.shortcuts import redirect
from decimal import Decimal
import math
import os
from time import strftime
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth import authenticate, login, logout
from django.urls import reverse
from urllib.parse import unquote

from weasyprint import HTML

from backend.forms import MemoForm
from backend.models import Memo
from .models import AttendanceRecord, CPDTrainingLog, CustomUser, HolidayRecord, SicknessRecord
from django.utils import timezone
from .forms import CPDTrainingLogForm, CustomUserCreationForm, HolidayRecordForm, OfficeClosureRecordForm
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.template.loader import render_to_string
import holidays
from django.core.exceptions import ObjectDoesNotExist

from django.http import JsonResponse
from datetime import date, timedelta, datetime, time
import csv
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_datetime
from .models import AttendanceRecord, HolidayRecord, SicknessRecord
from django.views.decorators.http import require_POST
from django.db.models import Q
import tempfile
import zipfile

logger = logging.getLogger('users')


def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            logger.info(
                f'User {username} successfully logged in from IP {request.META.get("REMOTE_ADDR", "unknown")}')
            today = timezone.now().date()
            attendance_record = AttendanceRecord.objects.filter(
                employee=user, date=today).first()
            if attendance_record is None:
                AttendanceRecord.objects.create(
                    employee=user,
                    date=today,
                    clock_in=timezone.now()
                )
                logger.info(
                    f'Created attendance record for user {username} on {today}')
            next_param = request.GET.get('next', '')
            next_page = unquote(next_param) if next_param else reverse(
                'user_dashboard')
            return redirect(next_page)
        else:
            logger.warning(
                f'Failed login attempt for username: {username} from IP {request.META.get("REMOTE_ADDR", "unknown")}')
            return render(request, 'login.html', {'error_message': 'Invalid login credentials, Please check username or password'})
    else:
        return render(request, 'login.html')


def logout_view(request):
    user = request.user.username
    logout(request)
    logger.info(
        f'User {user} successfully logged out from IP {request.META.get("REMOTE_ADDR", "unknown")}')
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
        start_date = datetime.combine(
            start_date.date(), work_start, tzinfo=start_date.tzinfo)
    elif start_date.time() >= work_end:  # After 5:00 PM
        # Move to the next business day at 9:00 AM
        start_date = datetime.combine(
            start_date.date() + timedelta(days=1), work_start, tzinfo=start_date.tzinfo)
        while start_date.weekday() >= 5:  # Skip weekends
            start_date += timedelta(days=1)

    # Adjust end_date if it's outside work hours
    if end_date.time() > work_end:
        end_date = datetime.combine(
            end_date.date(), work_end, tzinfo=end_date.tzinfo)
    elif end_date.time() < work_start:
        end_date = datetime.combine(
            end_date.date(), work_end, tzinfo=end_date.tzinfo)
        # Skip weekends
        while end_date.weekday() >= 5:
            end_date -= timedelta(days=1)

    # Create UK holiday list
    holiday_list = holidays.country_holidays('GB', subdiv='ENG')

    # Initialize the total hours counter
    total_hours = 0
    current_date = start_date

    while current_date.date() <= end_date.date():
        # Check if current date is a weekday and not a holiday
        if current_date.weekday() < 5 and current_date.date() not in holiday_list:
            # Calculate workday start and end times for the current date
            day_start = datetime.combine(
                current_date.date(), work_start, tzinfo=current_date.tzinfo)
            day_end = datetime.combine(
                current_date.date(), work_end, tzinfo=current_date.tzinfo)

            # Determine the actual start and end for counting within the working hours
            actual_start = max(current_date, day_start)
            actual_end = min(end_date, day_end)

            # If within work hours, calculate the difference in hours
            if actual_start < actual_end:
                hours_worked = (
                    actual_end - actual_start).total_seconds() / 3600
                total_hours += hours_worked

        # Move to the next day at 9:00 AM
        current_date = datetime.combine(current_date.date(
        ) + timedelta(days=1), work_start, tzinfo=current_date.tzinfo)

    # Convert hours to work days (8 hours = 1 work day)
    total_days = total_hours / 8

    # Round total_days to the nearest 0.5
    total_days = math.ceil(total_days * 2) / 2

    return total_days


@login_required
def profile_page(request):
    users = CustomUser.objects.filter(is_active=True).order_by('username')
    employees = CustomUser.objects.filter(is_active=True)
    user = request.user
    current_year = timezone.now().year

    holiday_requests = HolidayRecord.objects.filter(
        employee=user
    ).order_by('-timestamp')
    if request.user.is_manager:
        all_requests = HolidayRecord.objects.filter(checked_by=None)
    else:
        all_requests = None
    attendance_records = AttendanceRecord.objects.filter(
        employee=user).order_by('-date')
    sickness_records = SicknessRecord.objects.filter(
        employee=user).order_by('-start_date')
    requests_with_total_days = []
    total_paid_holidays = 0
    total_unpaid_holidays = 0
    for holiday_request in holiday_requests:
        total_days = 0
        if holiday_request.start_date and holiday_request.end_date:
            start_date = holiday_request.start_date
            end_date = holiday_request.end_date
            total_days = calculate_business_days(start_date, end_date)
            # Only count approved holidays in the allowance calculation
            # Exclude denied holidays (approved=False AND checked_by is not None)
            if start_date.year == current_year and holiday_request.approved:
                if holiday_request.type == 'Paid':
                    total_paid_holidays = total_paid_holidays + total_days
                else:
                    total_unpaid_holidays = total_unpaid_holidays + total_days

        requests_with_total_days.append({
            'request': holiday_request,
            'total_days': total_days,
            'is_bank_holiday': False
        })

    current_year = datetime.now().year

    holiday_list = holidays.country_holidays(
        'GB', subdiv='ENG', years=current_year)
    bank_holiday_records = []
    for holiday_date, holiday_name in holiday_list.items():
        holiday_datetime = datetime(
            holiday_date.year, holiday_date.month, holiday_date.day)

        record = {
            "employee": request.user,
            "start_date": holiday_datetime,
            "end_date": holiday_datetime,
            "reason": holiday_name,
            "type": 'Paid',
            "approved": True,
            "checked_by": "Director",  # or assign actual checker instance if available
            "checked_on": None,
            "approved_by": "Director",  # or assign actual approver instance if available
            "approved_on": None,

        }
        bank_holiday_records.append(
            {'request': record, 'total_days': 1, 'is_bank_holiday': True})

    requests_with_total_days = requests_with_total_days + bank_holiday_records

    # Only count bank holidays that fall on weekdays (Monday-Friday)
    # This matches the logic used elsewhere in the codebase
    bank_holiday_dates = [holiday_date for holiday_date in holiday_list.keys()
                          if holiday_date.weekday() < 5]
    total_bank_holidays = round(Decimal(len(bank_holiday_dates)), 2)
    total_paid_holidays_remaining = user.max_holidays_in_year - \
        Decimal(total_paid_holidays)
    total_paid_holidays_remaining = total_paid_holidays_remaining - total_bank_holidays
    current_year = datetime.now().year
    office_closure_holidays = HolidayRecord.objects.filter(
        reason="Office Closure",
        employee=request.user,
        start_date__year=current_year,
        approved=True  # Only count approved office closures
    )
    total_office_closure_holidays = 0
    for holiday in office_closure_holidays:
        total_days = calculate_business_days(
            holiday.start_date, holiday.end_date)

        total_office_closure_holidays = total_office_closure_holidays + total_days

    total_paid_holidays = total_paid_holidays - total_office_closure_holidays
    office_closure_form = OfficeClosureRecordForm()
    cpd_form = CPDTrainingLogForm()
    cpds = CPDTrainingLog.objects.filter(user=user).order_by('-date_completed')
    memo_form = MemoForm()
    if request.user.is_manager:
        memos = Memo.objects.all().order_by('-date')
    else:
        memos = Memo.objects.filter(is_final=True).order_by('-date')

    return render(request, 'profile_page.html', {'employees': employees,
                                                 'holiday_requests': requests_with_total_days,
                                                 'all_requests': all_requests,
                                                 'sickness_records': sickness_records,
                                                 'attendance_records': attendance_records,
                                                 'total_paid_holidays': total_paid_holidays,
                                                 'total_unpaid_holidays': total_unpaid_holidays,
                                                 'total_paid_holidays_remaining': total_paid_holidays_remaining,
                                                 'total_bank_holidays': total_bank_holidays,
                                                 'total_office_closure_holidays': total_office_closure_holidays,
                                                 'office_closure_form': office_closure_form,
                                                 'cpd_form': cpd_form,
                                                 'cpds': cpds,
                                                 'memo_form': memo_form,
                                                 'memos': memos,
                                                 'users': users})


def calculate_total_working_days_in_month(year, month, up_to_date=None):
    """
    Calculate total working days in a specific month (excluding weekends and bank holidays).
    If up_to_date is provided, only count days up to that date.

    Args:
        year: The year
        month: The month (1-12)
        up_to_date: Optional date to count up to

    Returns:
        Total working days in the month (or up to the specified date)
    """
    from datetime import date
    from calendar import monthrange

    # Get bank holidays for the year
    holiday_list = holidays.country_holidays('GB', subdiv='ENG', years=year)

    # Get first and last day of the month
    first_day = date(year, month, 1)
    last_day = date(year, month, monthrange(year, month)[1])

    # Determine end date
    if up_to_date:
        if up_to_date.year != year or up_to_date.month != month:
            if (up_to_date.year < year) or (up_to_date.year == year and up_to_date.month < month):
                return 0  # Date is before the month
            else:
                end_date = last_day  # Date is after the month
        else:
            end_date = up_to_date.date() if hasattr(up_to_date, 'date') else up_to_date
    else:
        end_date = last_day

    # Ensure end_date is not before first_day
    if end_date < first_day:
        return 0

    total_working_days = 0
    current_date = first_day

    while current_date <= end_date:
        # Check if it's a weekday (Monday=0, Sunday=6)
        if current_date.weekday() < 5:  # Monday to Friday
            # Check if it's not a bank holiday
            if current_date not in holiday_list:
                total_working_days += 1
        current_date += timedelta(days=1)

    return total_working_days


def get_accounted_dates_in_range(user, start_date, end_date, cutoff_date=None):
    """
    Get a set of dates that are already accounted for by holidays, sick leave, or bank holidays.
    This helps prevent double counting when calculating attendance records.

    Returns:
        set: Set of date objects that are already accounted for
    """
    accounted_dates = set()

    # Get bank holidays for the year to exclude them from holiday date ranges
    holiday_list_for_exclusion = holidays.country_holidays(
        'GB', subdiv='ENG', years=start_date.year)

    # Get all holidays (paid, unpaid, office closures)
    holidays_qs = HolidayRecord.objects.filter(
        employee=user,
        approved=True
    ).filter(
        Q(start_date__lte=end_date) & Q(end_date__gte=start_date)
    )

    for holiday in holidays_qs:
        holiday_start = max(holiday.start_date, start_date)
        holiday_end = min(holiday.end_date, end_date)
        if cutoff_date:
            holiday_end = min(holiday_end, timezone.make_aware(
                datetime.combine(cutoff_date, time(23, 59, 59))))

        current = holiday_start.date()
        end = holiday_end.date()
        while current <= end:
            # Only count business days (exclude weekends and bank holidays)
            # This matches calculate_business_days logic
            if current.weekday() < 5 and current not in holiday_list_for_exclusion:  # Monday = 0, Friday = 4
                accounted_dates.add(current)
            current += timedelta(days=1)

    # Get all sick leave records
    sickness_qs = SicknessRecord.objects.filter(
        employee=user
    ).filter(
        Q(start_date__lte=end_date) & (
            Q(end_date__gte=start_date) | Q(end_date__isnull=True))
    )

    for sickness in sickness_qs:
        sickness_start = max(sickness.start_date, start_date)
        if sickness.end_date:
            sickness_end = min(sickness.end_date, end_date)
        else:
            sickness_end = min(end_date, timezone.now())
        if cutoff_date:
            sickness_end = min(sickness_end, timezone.make_aware(
                datetime.combine(cutoff_date, time(23, 59, 59))))

        current = sickness_start.date()
        end = sickness_end.date()
        while current <= end:
            if current.weekday() < 5:  # Only business days
                accounted_dates.add(current)
            current += timedelta(days=1)

    # Get bank holidays in the range (only weekdays)
    # IMPORTANT: Bank holidays are ALWAYS counted separately, regardless of office closures
    # Office closures use calculate_business_days which already excludes bank holidays,
    # so bank holidays remain independent and should be counted
    holiday_list = holidays.country_holidays(
        'GB', subdiv='ENG', years=start_date.year)
    for holiday_date in holiday_list.keys():
        if start_date.date() <= holiday_date <= end_date.date():
            if cutoff_date is None or holiday_date <= cutoff_date:
                # Only count bank holidays on weekdays (Monday=0, Friday=4)
                if holiday_date.weekday() < 5:
                    accounted_dates.add(holiday_date)

    return accounted_dates


def calculate_missing_days_summary(user, year=None, month=None):
    """
    Calculate missing days summary for a user for a specific month or year.
    Handles edge cases to prevent double counting.

    Args:
        user: The user
        year: Optional year (defaults to current year)
        month: Optional month (1-12). If provided, calculates for that month only

    Returns:
        Dictionary with missing days information
    """
    from datetime import date
    from calendar import monthrange

    today = timezone.now().date()

    if year is None:
        year = today.year
    if month is None:
        # Year view
        is_current_year = (year == today.year)
        cutoff_date = today if is_current_year else None

        # Use existing function for year calculation
        total_working_days = calculate_total_working_days_in_year(
            year, cutoff_date)

        # Get all accounted days for the year (using existing logic)
        summary = calculate_holidays_summary(user, year)
        total_accounted_days = summary['total_accounted_days']
        missing_days = summary['unaccounted_days']

        # Ensure missing days is not negative (edge case: double counting)
        if missing_days < 0:
            missing_days = Decimal('0')

        return {
            'period_type': 'year',
            'year': year,
            'month': None,
            'total_working_days': float(total_working_days),
            'total_accounted_days': float(total_accounted_days),
            'missing_days': float(missing_days),
            'date_range_description': summary.get('date_range_description', 'for entire year')
        }
    else:
        # Month view
        first_day_of_month = date(year, month, 1)
        last_day_of_month = date(year, month, monthrange(year, month)[1])

        is_current_month = (year == today.year and month == today.month)
        cutoff_date = today if is_current_month else None

        # Calculate working days in the month
        total_working_days = calculate_total_working_days_in_month(
            year, month, cutoff_date)

        # Convert to datetime for calculations
        first_day_dt = timezone.make_aware(
            datetime.combine(first_day_of_month, time(0, 0, 0)))
        last_day_dt = timezone.make_aware(datetime.combine(
            last_day_of_month, time(23, 59, 59, 999999)))

        # Get accounted dates to prevent double counting
        accounted_dates = get_accounted_dates_in_range(
            user, first_day_dt, last_day_dt, cutoff_date)

        # Calculate accounted days for the month
        total_accounted_days = Decimal('0')

        # Paid holidays
        paid_holidays = HolidayRecord.objects.filter(
            employee=user,
            approved=True,
            type='Paid'
        ).exclude(reason="Office Closure").filter(
            Q(start_date__lte=last_day_dt) & Q(end_date__gte=first_day_dt)
        )
        for holiday in paid_holidays:
            days = calculate_holiday_days_in_month(
                holiday.start_date, holiday.end_date,
                first_day_of_month, last_day_of_month
            )
            total_accounted_days += Decimal(str(days))

        # Unpaid holidays
        unpaid_holidays = HolidayRecord.objects.filter(
            employee=user,
            approved=True,
            type='Unpaid'
        ).filter(
            Q(start_date__lte=last_day_dt) & Q(end_date__gte=first_day_dt)
        )
        for holiday in unpaid_holidays:
            days = calculate_holiday_days_in_month(
                holiday.start_date, holiday.end_date,
                first_day_of_month, last_day_of_month
            )
            total_accounted_days += Decimal(str(days))

        # Sick leave
        sickness_records = SicknessRecord.objects.filter(
            employee=user
        ).filter(
            Q(start_date__lte=last_day_dt) & (
                Q(end_date__gte=first_day_dt) | Q(end_date__isnull=True))
        )
        for sickness in sickness_records:
            if sickness.end_date is None:
                # Ongoing sickness
                overlap_start = max(sickness.start_date, first_day_dt)
                overlap_end = last_day_dt if cutoff_date is None else min(
                    timezone.make_aware(datetime.combine(
                        cutoff_date, time(23, 59, 59))),
                    last_day_dt
                )
                days = calculate_holiday_days_in_month(
                    overlap_start, overlap_end,
                    first_day_of_month, last_day_of_month
                )
            else:
                days = calculate_holiday_days_in_month(
                    sickness.start_date, sickness.end_date,
                    first_day_of_month, last_day_of_month
                )
            total_accounted_days += Decimal(str(days))

        # Office closures
        # IMPORTANT: calculate_holiday_days_in_month uses calculate_business_days which excludes weekends and bank holidays
        # So office closures count only business days (weekdays that aren't bank holidays)
        office_closures = HolidayRecord.objects.filter(
            employee=user,
            reason="Office Closure",
            approved=True
        ).filter(
            Q(start_date__lte=last_day_dt) & Q(end_date__gte=first_day_dt)
        )

        for holiday in office_closures:
            days = calculate_holiday_days_in_month(
                holiday.start_date, holiday.end_date,
                first_day_of_month, last_day_of_month
            )
            total_accounted_days += Decimal(str(days))

        # Bank holidays
        # IMPORTANT: Bank holidays are ALWAYS counted separately, regardless of office closures
        # Office closures use calculate_business_days which already excludes bank holidays,
        # so bank holidays remain independent and should be counted for the whole month/year
        holiday_list = holidays.country_holidays(
            'GB', subdiv='ENG', years=year)
        bank_holidays_in_month = []
        for holiday_date in holiday_list.keys():
            if holiday_date.year == year and holiday_date.month == month:
                # Only count weekdays (Monday=0, Friday=4)
                if holiday_date.weekday() < 5:
                    if cutoff_date is None or holiday_date <= cutoff_date:
                        bank_holidays_in_month.append(holiday_date)

        total_accounted_days += Decimal(str(len(bank_holidays_in_month)))

        # Attendance records - only count days NOT already accounted for by holidays/sick leave/bank holidays
        attendance_query = AttendanceRecord.objects.filter(
            employee=user,
            date__year=year,
            date__month=month
        )
        if cutoff_date:
            attendance_query = attendance_query.filter(date__lte=cutoff_date)

        attendance_dates = set(attendance_query.values_list(
            'date', flat=True).distinct())
        # Only count attendance on days that aren't already accounted for
        unaccounted_attendance_dates = attendance_dates - accounted_dates
        days_with_attendance = len(unaccounted_attendance_dates)
        total_accounted_days += Decimal(str(days_with_attendance))

        # Calculate missing days
        missing_days = Decimal(str(total_working_days)) - total_accounted_days

        # Ensure missing days is not negative (edge case: double counting or data issues)
        if missing_days < 0:
            missing_days = Decimal('0')

        date_range_desc = f"up to {cutoff_date.strftime('%d/%m/%Y')}" if cutoff_date else "for entire month"

        return {
            'period_type': 'month',
            'year': year,
            'month': month,
            'total_working_days': float(total_working_days),
            'total_accounted_days': float(total_accounted_days),
            'missing_days': float(missing_days),
            'date_range_description': date_range_desc
        }


def calculate_total_working_days_in_year(year, up_to_date=None):
    """
    Calculate total working days in a year (excluding weekends and bank holidays).
    If up_to_date is provided, only count days up to that date.

    Args:
        year: The year to calculate for
        up_to_date: Optional date to count up to (for current year, use today's date)

    Returns:
        Total working days in the year (or up to the specified date)
    """
    from datetime import date

    # Get bank holidays for the year
    holiday_list = holidays.country_holidays('GB', subdiv='ENG', years=year)

    # Start from January 1st
    start_date = date(year, 1, 1)

    # Determine end date
    if up_to_date:
        # Use the provided date, but ensure it's within the year
        if up_to_date.year != year:
            # If date is in a different year, use end of year or start of year
            if up_to_date.year < year:
                return 0  # Date is before the year
            else:
                # Date is after the year, use end of year
                end_date = date(year, 12, 31)
        else:
            end_date = up_to_date.date() if hasattr(up_to_date, 'date') else up_to_date
    else:
        # Use end of year
        end_date = date(year, 12, 31)

    # Ensure end_date is not before start_date
    if end_date < start_date:
        return 0

    total_working_days = 0
    current_date = start_date

    while current_date <= end_date:
        # Check if it's a weekday (Monday=0, Sunday=6)
        if current_date.weekday() < 5:  # Monday to Friday
            # Check if it's not a bank holiday
            if current_date not in holiday_list:
                total_working_days += 1
        current_date += timedelta(days=1)

    return total_working_days


def calculate_holidays_summary(user, year):
    """
    Calculate holidays summary for a given user and year.
    Smartly handles dates:
    - Current year: counts working days and holidays only up to today
    - Past years: counts all working days and holidays
    - Future years: counts working days up to today (if any), holidays up to today

    Returns a dictionary with all holiday totals and breakdown.
    """
    current_year = year
    today = timezone.now().date()
    is_current_year = (current_year == today.year)
    is_past_year = (current_year < today.year)
    is_future_year = (current_year > today.year)

    # Determine the cutoff date for calculations
    if is_current_year or is_future_year:
        # For current or future years, only count up to today
        cutoff_date = today
    else:
        # For past years, count the entire year
        cutoff_date = None

    # Get all holiday requests for the user
    holiday_requests = HolidayRecord.objects.filter(
        employee=user
    ).order_by('-timestamp')

    total_paid_holidays = 0
    total_unpaid_holidays = 0

    # Calculate paid and unpaid holidays for the year
    # Match the logic from profile_page: count all approved paid holidays first
    # IMPORTANT: Exclude office closures from paid holidays (they're counted separately)
    for holiday_request in holiday_requests:
        if holiday_request.start_date and holiday_request.end_date:
            start_date = holiday_request.start_date
            end_date = holiday_request.end_date

            # Only count holidays in the current year
            if start_date.year != current_year:
                continue

            # Skip office closures (they're counted separately)
            if holiday_request.reason == "Office Closure":
                continue

            # For current/future years, only count holidays up to today
            if cutoff_date:
                # If holiday ends before cutoff, count it fully
                if end_date.date() <= cutoff_date:
                    total_days = calculate_business_days(start_date, end_date)
                # If holiday starts before cutoff but ends after, count only up to cutoff
                elif start_date.date() <= cutoff_date:
                    cutoff_datetime = timezone.make_aware(
                        datetime.combine(cutoff_date, datetime.min.time())
                    )
                    total_days = calculate_business_days(
                        start_date, cutoff_datetime)
                else:
                    # Holiday is entirely in the future, skip it
                    continue
            else:
                # Past year - count all holidays
                total_days = calculate_business_days(start_date, end_date)

            # Only count approved holidays in the allowance calculation
            if holiday_request.approved:
                if holiday_request.type == 'Paid':
                    total_paid_holidays = total_paid_holidays + total_days
                else:
                    total_unpaid_holidays = total_unpaid_holidays + total_days

    # Calculate paid holidays for FULL YEAR (for Holidays Summary display)
    # This shows all paid holidays for the entire year, regardless of current date
    total_paid_holidays_full_year = 0
    for holiday_request in holiday_requests:
        if holiday_request.start_date and holiday_request.end_date:
            start_date = holiday_request.start_date
            end_date = holiday_request.end_date

            # Only count holidays in the current year
            if start_date.year != current_year:
                continue

            # Skip office closures (they're counted separately)
            if holiday_request.reason == "Office Closure":
                continue

            # Count all holidays for the full year (no cutoff)
            total_days = calculate_business_days(start_date, end_date)

            # Only count approved holidays
            if holiday_request.approved and holiday_request.type == 'Paid':
                total_paid_holidays_full_year = total_paid_holidays_full_year + total_days

    # Get office closure holidays for the year
    # IMPORTANT: calculate_business_days already excludes weekends and bank holidays
    # So office closures count only business days (weekdays that aren't bank holidays)
    # Example: Office closure from 24.12.2025 09:00 to 31.12.2025 17:00 = 8 calendar days
    # Out of which: 4 business days, 2 bank holidays, 2 weekends
    # Office closure should count as 4 days (business days only)
    office_closure_holidays = HolidayRecord.objects.filter(
        reason="Office Closure",
        employee=user,
        start_date__year=current_year,
        approved=True
    )

    # Calculate office closures "to date" (for Days Accounting Summary)
    total_office_closure_holidays = 0
    for holiday in office_closure_holidays:
        if cutoff_date:
            # If holiday ends before cutoff, count it fully
            if holiday.end_date.date() <= cutoff_date:
                total_days = calculate_business_days(
                    holiday.start_date, holiday.end_date)
            # If holiday starts before cutoff but ends after, count only up to cutoff
            elif holiday.start_date.date() <= cutoff_date:
                cutoff_datetime = timezone.make_aware(
                    datetime.combine(cutoff_date, datetime.min.time())
                )
                total_days = calculate_business_days(
                    holiday.start_date, cutoff_datetime)
            else:
                # Holiday is entirely in the future, skip it
                continue
        else:
            total_days = calculate_business_days(
                holiday.start_date, holiday.end_date)
        total_office_closure_holidays = total_office_closure_holidays + total_days

    # Calculate office closures for FULL YEAR (for Holidays Summary display)
    # This shows all office closures for the entire year, regardless of current date
    total_office_closure_holidays_full_year = 0
    for holiday in office_closure_holidays:
        total_days = calculate_business_days(
            holiday.start_date, holiday.end_date)
        total_office_closure_holidays_full_year = total_office_closure_holidays_full_year + total_days

    # Get bank holidays for the year
    # IMPORTANT: Bank holidays are ALWAYS counted separately, regardless of office closures
    # Office closures use calculate_business_days which already excludes bank holidays,
    # so bank holidays remain independent and should be counted for the whole year
    # Example: If there are 8 bank holidays in the year, they remain 8 even if some fall
    # within office closure periods
    holiday_list = holidays.country_holidays(
        'GB', subdiv='ENG', years=current_year)

    # Count bank holidays up to cutoff date if applicable (only weekdays)
    # This is for display purposes (showing bank holidays up to date)
    bank_holiday_dates = []
    if cutoff_date:
        bank_holiday_dates = [holiday_date for holiday_date in holiday_list.keys()
                              if holiday_date <= cutoff_date and holiday_date.weekday() < 5]
    else:
        bank_holiday_dates = [holiday_date for holiday_date in holiday_list.keys()
                              if holiday_date.weekday() < 5]

    total_bank_holidays = round(Decimal(len(bank_holiday_dates)), 2)

    # Calculate full year bank holidays for remaining calculation
    # Remaining holidays should use the full year's bank holidays, not just up to today
    bank_holiday_dates_full_year = [holiday_date for holiday_date in holiday_list.keys()
                                    if holiday_date.weekday() < 5]
    total_bank_holidays_full_year = round(
        Decimal(len(bank_holiday_dates_full_year)), 2)

    # Calculate sick leave for the year
    sickness_records = SicknessRecord.objects.filter(
        employee=user,
        start_date__year=current_year
    )
    total_sick_leave = 0
    for sickness in sickness_records:
        if sickness.start_date:
            # Only count days within the year
            start_date = sickness.start_date
            if start_date.year != current_year:
                continue

            if cutoff_date:
                # For current/future years, only count up to today
                if sickness.end_date:
                    end_date = sickness.end_date
                    # If sickness ends before cutoff, count it fully
                    if end_date.date() <= cutoff_date:
                        total_days = calculate_business_days(
                            start_date, end_date)
                    # If sickness starts before cutoff but ends after, count only up to cutoff
                    elif start_date.date() <= cutoff_date:
                        cutoff_datetime = timezone.make_aware(
                            datetime.combine(cutoff_date, datetime.min.time())
                        )
                        total_days = calculate_business_days(
                            start_date, cutoff_datetime)
                    else:
                        # Sickness is entirely in the future, skip it
                        continue
                else:
                    # Ongoing sickness - count from start to cutoff date
                    cutoff_datetime = timezone.make_aware(
                        datetime.combine(cutoff_date, datetime.min.time())
                    )
                    total_days = calculate_business_days(
                        start_date, cutoff_datetime)
            else:
                # Past year - count all sick leave
                if sickness.end_date:
                    end_date = sickness.end_date
                    # If end_date is in a future year, cap it at end of current year
                    if end_date.year > current_year:
                        end_of_year = datetime(
                            current_year, 12, 31, 23, 59, 59)
                        end_of_year = timezone.make_aware(end_of_year)
                        end_date = end_of_year
                    total_days = calculate_business_days(start_date, end_date)
                else:
                    # If end_date is None, it's ongoing - calculate from start_date to end of year
                    end_of_year = datetime(current_year, 12, 31, 23, 59, 59)
                    end_of_year = timezone.make_aware(end_of_year)
                    total_days = calculate_business_days(
                        start_date, end_of_year)

            total_sick_leave = total_sick_leave + total_days

    # Calculate total working days in the year (smartly based on date)
    total_working_days = calculate_total_working_days_in_year(
        current_year, cutoff_date)

    # Calculate remaining holidays (to date - for Days Accounting)
    # IMPORTANT:
    # - total_paid_holidays already excludes office closures (they're filtered out in the loop above)
    # - Remaining calculation should use FULL YEAR bank holidays, not "to date"
    # - Office closures ARE subtracted from remaining (they're taken out of the allowance)
    # Formula: Remaining = Allowance - Taken (excluding office closures) - Bank Holidays - Office Closures
    # Already excludes office closures
    total_paid_holidays_excluding_office_closure = total_paid_holidays
    total_paid_holidays_remaining = user.max_holidays_in_year - \
        Decimal(str(total_paid_holidays_excluding_office_closure))
    total_paid_holidays_remaining = total_paid_holidays_remaining - \
        Decimal(str(total_bank_holidays_full_year))
    # Subtract office closures from remaining (they're taken out of the allowance)
    total_paid_holidays_remaining = total_paid_holidays_remaining - \
        Decimal(str(total_office_closure_holidays_full_year))

    # Calculate remaining holidays for FULL YEAR (for Holidays Summary display)
    # Use full year values for all components
    total_paid_holidays_remaining_full_year = user.max_holidays_in_year - \
        Decimal(str(total_paid_holidays_full_year))
    total_paid_holidays_remaining_full_year = total_paid_holidays_remaining_full_year - \
        Decimal(str(total_bank_holidays_full_year))
    total_paid_holidays_remaining_full_year = total_paid_holidays_remaining_full_year - \
        Decimal(str(total_office_closure_holidays_full_year))

    # Get attendance records for the year (up to cutoff date if applicable)
    attendance_query = AttendanceRecord.objects.filter(
        employee=user,
        date__year=current_year
    )
    if cutoff_date:
        attendance_query = attendance_query.filter(date__lte=cutoff_date)

    attendance_records = set(
        attendance_query.values_list('date', flat=True).distinct())

    # Get accounted dates to prevent double counting with attendance
    year_start = timezone.make_aware(datetime(current_year, 1, 1, 0, 0, 0))
    year_end = timezone.make_aware(datetime(current_year, 12, 31, 23, 59, 59))
    if cutoff_date:
        year_end = timezone.make_aware(
            datetime.combine(cutoff_date, time(23, 59, 59)))

    accounted_dates = get_accounted_dates_in_range(
        user, year_start, year_end, cutoff_date)

    # Only count attendance on days that aren't already accounted for by holidays/sick leave/bank holidays
    unaccounted_attendance_dates = attendance_records - accounted_dates
    days_with_attendance = len(unaccounted_attendance_dates)

    # Calculate total accounted days
    # Convert all to Decimal first to avoid type mixing issues
    # Include attendance records as they represent days the employee worked (but exclude overlaps)
    total_accounted_days = (
        Decimal(str(total_paid_holidays_excluding_office_closure)) +
        Decimal(str(total_unpaid_holidays)) +
        Decimal(str(total_sick_leave)) +
        Decimal(str(total_bank_holidays)) +
        Decimal(str(total_office_closure_holidays)) +
        Decimal(str(days_with_attendance))
    )

    # Calculate unaccounted days
    unaccounted_days = Decimal(str(total_working_days)) - total_accounted_days

    # Ensure unaccounted days is not negative (edge case: double counting or data issues)
    if unaccounted_days < 0:
        unaccounted_days = Decimal('0')

    # Determine date range description
    if cutoff_date:
        date_range_description = f"up to {cutoff_date.strftime('%d/%m/%Y')}"
    else:
        date_range_description = "for entire year"

    return {
        'allowance': float(user.max_holidays_in_year),
        'total_paid_holidays': float(total_paid_holidays_excluding_office_closure),  # To date (for Days Accounting Summary)
        'total_paid_holidays_full_year': float(total_paid_holidays_full_year),  # Full year (for Holidays Summary display)
        'total_unpaid_holidays': float(total_unpaid_holidays),
        'total_bank_holidays': float(total_bank_holidays),  # To date (for Days Accounting Summary)
        'total_bank_holidays_full_year': float(total_bank_holidays_full_year),  # Full year (for Holidays Summary display)
        # To date (for Days Accounting Summary)
        'total_office_closure_holidays': float(total_office_closure_holidays),
        # Full year (for Holidays Summary display)
        'total_office_closure_holidays_full_year': float(total_office_closure_holidays_full_year),
        'total_paid_holidays_remaining': float(total_paid_holidays_remaining),  # To date (for Days Accounting Summary)
        'total_paid_holidays_remaining_full_year': float(total_paid_holidays_remaining_full_year),  # Full year (for Holidays Summary display)
        'total_sick_leave': float(total_sick_leave),
        'total_working_days': float(total_working_days),
        'total_accounted_days': float(total_accounted_days),
        'days_with_attendance': float(days_with_attendance),
        'unaccounted_days': float(unaccounted_days),
        'year': current_year,
        'date_range_description': date_range_description,
        'is_current_year': is_current_year,
        'is_past_year': is_past_year,
        'is_future_year': is_future_year
    }


@login_required
def holidays_summary_api(request):
    """AJAX endpoint to get holidays summary for a user and year"""
    if not request.user.is_manager:
        return JsonResponse({'error': 'Permission denied'}, status=403)

    user_id = request.GET.get('user_id')
    year = request.GET.get('year')

    if not user_id or not year:
        return JsonResponse({'error': 'user_id and year are required'}, status=400)

    try:
        user = CustomUser.objects.get(id=user_id)
        year = int(year)
    except (CustomUser.DoesNotExist, ValueError):
        return JsonResponse({'error': 'Invalid user_id or year'}, status=400)

    summary = calculate_holidays_summary(user, year)
    return JsonResponse(summary)


@login_required
def missing_days_api(request):
    """AJAX endpoint to get missing days summary for a user, year, and optional month"""
    user_id = request.GET.get('user_id')
    year = request.GET.get('year')
    month = request.GET.get('month')

    # If no user_id provided, use current user (for profile page)
    if user_id:
        try:
            user = CustomUser.objects.get(id=user_id)
            # Only managers can view other users' data
            if not request.user.is_manager:
                return JsonResponse({'error': 'Permission denied'}, status=403)
        except (CustomUser.DoesNotExist, ValueError):
            return JsonResponse({'error': 'Invalid user_id'}, status=400)
    else:
        user = request.user

    if not year:
        return JsonResponse({'error': 'year is required'}, status=400)

    try:
        year = int(year)
        month = int(month) if month else None
    except ValueError:
        return JsonResponse({'error': 'Invalid year or month'}, status=400)

    summary = calculate_missing_days_summary(user, year, month)
    return JsonResponse(summary)


@login_required
def holiday_records(request):
    if request.user.is_manager != True:
        messages.error(
            request, 'You do not have right permissions to access the page.')
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

    # Get users list for the summary component
    users = CustomUser.objects.filter(is_active=True).order_by('username')

    return render(request, 'holiday_records.html', {
        'holiday_records': requests_with_total_days,
        'users': users
    })


@login_required
def sickness_records(request):
    if request.user.is_manager != True:
        messages.error(
            request, 'You do not have right permissions to access the page.')
        return redirect('user_dashboard')
    sickness_records = SicknessRecord.objects.all(
    ).select_related('employee', 'created_by')
    return render(request, 'sickness_records.html', {'sickness_records': sickness_records})


@login_required
def calendar_events(request):
    # Fetch holiday records

    holiday_records = HolidayRecord.objects.all()
    if request.user.is_manager:
        sickness_records = SicknessRecord.objects.all()
    else:
        sickness_records = SicknessRecord.objects.filter(employee=request.user)
    events = []
    for holiday in holiday_records:
        # Determine the leave type title based on user role
        if request.user.is_manager:
            leave_type = 'Annual Leave' if holiday.type == 'Paid' else 'Unpaid Leave'
        else:
            leave_type = 'Leave'  # Non-managers just see "Leave"

        # Approved holiday events
        if holiday.checked_by is not None and holiday.approved:
            event = {
                'title': f'{holiday.employee} - {leave_type}',
                'start': holiday.start_date,
                'end': holiday.end_date,
                'description': f'Type: {holiday.type}, Approved: {holiday.approved}',
                'color': get_holiday_color(holiday, request.user.is_manager),
            }
            events.append(event)

        # Pending approval holiday events
        elif holiday.checked_by is None and not holiday.approved:
            event = {
                'title': f'(APPROVAL PENDING) {holiday.employee} - {leave_type}',
                'start': holiday.start_date,
                'end': holiday.end_date,
                'description': f'Type: {holiday.type}, Approved: {holiday.approved}',
                'color': '#5cb85c',
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
    current_year = timezone.now().year
    holiday_list = holidays.country_holidays(
        'GB', subdiv='ENG', years=range(current_year-5, current_year+5))
    for date, name in holiday_list.items():

        event = {
            'title': f'Bank Holiday - {name}',
            'start': date.strftime('%Y-%m-%d'),
            'end': date.strftime('%Y-%m-%d'),
            'description': 'Type: Bank Holiday',
            'color': '#80CBC4'
        }
        events.append(event)

    return JsonResponse(events, safe=False)


def get_holiday_color(holiday, is_manager):
    """Determine color based on holiday type and approval status with eye-friendly colors."""
    if holiday.approved:
        if is_manager:
            # Muted Green for Paid Approved, Soft Amber for Unpaid Approved
            return '#5cb85c' if holiday.type == 'Paid' else '#ffca66'
        else:
            return '#5cb85c'  # Same color for all users for approved holidays
    else:
        if is_manager:
            # Muted Blue for Paid Pending, Soft Coral Red for Unpaid Pending
            return '#6699cc' if holiday.type == 'Paid' else '#ff9999'
        else:
            return '#6699cc'  # Same color for all users for pending holidays


@login_required
def add_sickness_record(request):
    if not request.user.is_manager:
        messages.error(
            request, "You do not have permission to add a sickness record.")
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
            messages.error(
                request, f"An error occurred while adding the sickness record: {str(e)}")

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
        num_days_requested = calculate_business_days(
            start_date_dt, end_date_dt)

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
            messages.error(
                request, f'You have requested {num_days_requested} business days in {request_year}, but this exceeds your yearly limit of {max_holidays_in_year} paid holidays by {exceeding_amount} days.')
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

                messages.success(
                    request, 'Holiday request submitted successfully.')
            except Exception as e:
                messages.error(
                    request, 'There was an error submitting your holiday request. Please try again.')

        return redirect('profile_page')

    return redirect('profile_page')


@login_required
def add_office_closure(request):
    if request.method == 'POST':
        form = OfficeClosureRecordForm(request.POST)
        if form.is_valid():
            start_date = form.cleaned_data['start_date']
            end_date = form.cleaned_data['end_date']

            for employee in form.cleaned_data['employees']:
                HolidayRecord.objects.create(
                    employee=employee,
                    start_date=start_date,
                    end_date=end_date,
                    reason='Office Closure',
                    type='Paid',
                    approved=True,
                    approved_by=request.user,
                    approved_on=timezone.now(),
                    checked_by=request.user,
                    checked_on=timezone.now()
                )
            messages.success(
                request, "Office Closure succesfully added for selected employees.")
            return redirect('profile_page')

    return render(request, 'add_office_closure.html', {'form': form})


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
        num_days_requested = calculate_business_days(
            start_date_dt, end_date_dt)

        user = request.user
        max_holidays_in_year = user.max_holidays_in_year

        # Determine the year of the requested holiday
        request_year = start_date_dt.year

        # Get all approved "Paid" holidays for the user within the requested year
        # Exclude denied holidays (only count approved ones)
        paid_holidays_in_request_year = HolidayRecord.objects.filter(
            employee=user,
            type='Paid',
            start_date__year=request_year,
            approved=True  # Only count approved holidays
        ).exclude(reason="Office Closure")

        # Calculate the total number of paid holidays taken in that year
        total_paid_holidays_taken = sum(
            calculate_business_days(holiday.start_date, holiday.end_date)
            for holiday in paid_holidays_in_request_year
        )

        # Retrieve office closures and bank holidays for the requested year
        current_year = datetime.now().year
        office_closures = HolidayRecord.objects.filter(
            reason="Office Closure",
            employee=request.user,
            start_date__year=current_year,
            approved=True  # Only count approved office closures
        )
        total_office_closure_holidays = 0
        for holiday in office_closures:
            total_days = calculate_business_days(
                holiday.start_date, holiday.end_date)

            total_office_closure_holidays = total_office_closure_holidays + total_days

        holiday_list = holidays.country_holidays(
            'GB', subdiv='ENG', years=current_year)
        total_bank_holidays = sum(1 for name in holiday_list.values())

        non_working_days = total_office_closure_holidays + total_bank_holidays
        max_holidays_adjusted = max_holidays_in_year - \
            Decimal(non_working_days)

        total_holidays_after_request = total_paid_holidays_taken + num_days_requested

        # Check if the total number of paid holidays exceeds the adjusted max holidays
        if total_holidays_after_request > max_holidays_adjusted and holiday_type == 'Paid':
            exceeding_amount = Decimal(
                total_holidays_after_request) - max_holidays_adjusted
            remaining_days = max_holidays_adjusted - \
                Decimal(total_paid_holidays_taken)

            messages.error(
                request,
                f"You cannot take these holidays as it will exceed your yearly allowance. "
                f"You can request up to {remaining_days} more paid holiday days this year."
            )
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

                messages.success(
                    request, 'Holiday request submitted successfully.')
            except Exception as e:
                messages.error(
                    request, 'There was an error submitting your holiday request. Please try again.')

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
def deny_holiday_request(request, id):
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
        attendance_record = AttendanceRecord.objects.get(
            employee=request.user, date=current_time.date())

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
            messages.success(
                request, f'Your lunch break started at {current_time.astimezone(timezone.get_current_timezone()).strftime("%I:%M %p")}.')

    except AttendanceRecord.DoesNotExist:
        messages.error(request, 'Attendance record not found for today.')
    except Exception as e:
        messages.error(request, f'An error occurred: {e}')

    return redirect('user_dashboard')


@login_required
def lunch_out(request):
    current_time = timezone.now()
    try:
        attendance_record = AttendanceRecord.objects.get(
            employee=request.user, date=current_time.date())

        # Check if lunch has already ended
        if attendance_record.lunch_out:
            messages.error(
                request,
                f'Your lunch break has already ended at {attendance_record.lunch_out.astimezone(timezone.get_current_timezone()).strftime("%I:%M %p")}. '
                'Please inform your manager if this is incorrect.'
            )
        elif not attendance_record.lunch_in:
            messages.error(
                request, 'You need to start lunch before ending it.')
        else:
            attendance_record.lunch_out = current_time
            attendance_record.save()
            messages.success(
                request, f'Your lunch break ended at {current_time.astimezone(timezone.get_current_timezone()).strftime("%I:%M %p")}.')

    except AttendanceRecord.DoesNotExist:
        messages.error(request, 'Attendance record not found for today.')
    except Exception as e:
        messages.error(request, f'An error occurred: {e}')

    return redirect('user_dashboard')


@login_required
def clock_out(request):
    current_time = timezone.now()
    try:
        attendance_record = AttendanceRecord.objects.get(
            employee=request.user, date=current_time.date())

        if attendance_record.clock_out:
            messages.error(
                request,
                f'You have already clocked out at {attendance_record.clock_out.astimezone(timezone.get_current_timezone()).strftime("%I:%M %p")}. '
                'Please inform your manager if this is incorrect.'
            )
        else:
            attendance_record.clock_out = current_time
            attendance_record.save()
            messages.success(
                request, f'You have clocked out at {current_time.astimezone(timezone.get_current_timezone()).strftime("%I:%M %p")}.')

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
            messages.error(
                request, 'You do not have the right to access this page.')
            return redirect('profile_page')
        if holiday.checked_by is not None:
            messages.error(
                request, 'Please contact your manager to edit the record.')
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


def export_to_csv(queryset, fieldnames, filename):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow(fieldnames)

    for obj in queryset:
        row = []
        for field in fieldnames:
            value = getattr(obj, field)
            # Check if the value is a date or datetime field, and format it
            if isinstance(value, datetime):
                value = value.strftime('%d/%m/%Y %H:%M')
            elif isinstance(value, date):
                value = value.strftime('%d/%m/%Y')
            row.append(value)
        writer.writerow(row)

    return response


def parse_custom_date(date_str):
    return datetime.strptime(date_str, '%d/%m/%Y')


def generate_csv_report(attendance, holidays, sickness, filename):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow(['Employee', 'Date', 'Type', 'Details'])

    for record in attendance:
        writer.writerow([
            record.employee,
            record.date.strftime('%d/%m/%Y'),
            'Attendance',
            f'Clock In: {record.clock_in}, Clock Out: {record.clock_out}, Lunch: {record.lunch_in} - {record.lunch_out}'
        ])

    for record in holidays:
        writer.writerow([
            record.employee,
            record.start_date.strftime('%d/%m/%Y'),
            'Holiday',
            f'Reason: {record.reason}, Approved: {"Yes" if record.approved else "No"}'
        ])

    for record in sickness:
        writer.writerow([
            record.employee,
            record.start_date.strftime('%d/%m/%Y'),
            'Sickness',
            record.description
        ])

    return response


@login_required
@require_POST
def attendance_record_csv(request):
    if not request.user.is_manager:
        messages.error(
            request, "You do not have permission to download this data.")
        # Adjust 'dashboard' to your actual redirect path
        return redirect('user_dashboard')

    start_date = parse_custom_date(request.POST.get('start_date'))
    end_date = parse_custom_date(request.POST.get('end_date'))
    queryset = AttendanceRecord.objects.filter(
        date__gte=start_date, date__lte=end_date
    )
    fieldnames = ['employee', 'date', 'clock_in',
                  'clock_out', 'lunch_in', 'lunch_out']
    return export_to_csv(queryset, fieldnames, f'attendance_records_{timezone.now()}.csv')


@login_required
@require_POST
def holiday_record_csv(request):
    if not request.user.is_manager:
        messages.error(
            request, "You do not have permission to download this data.")
        # Adjust 'dashboard' to your actual redirect path
        return redirect('user_dashboard')

    start_date = parse_custom_date(request.POST.get('start_date'))
    end_date = parse_custom_date(request.POST.get('end_date'))
    queryset = HolidayRecord.objects.filter(
        start_date__gte=start_date, end_date__lte=end_date
    )

    # Create a custom CSV export with total holiday days calculation
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="holiday_records_{timezone.now()}.csv"'
    writer = csv.writer(response)

    # Write header with the new total_holiday_days column
    fieldnames = ['employee', 'start_date', 'end_date', 'total_holiday_days', 'reason', 'type',
                  'approved', 'checked_by', 'checked_on', 'approved_by', 'approved_on', 'timestamp']
    writer.writerow(fieldnames)

    # Write data rows with calculated total holiday days
    for obj in queryset:
        # Calculate total working days using the existing function
        total_days = calculate_business_days(obj.start_date, obj.end_date)

        row = []
        for field in fieldnames:
            if field == 'total_holiday_days':
                value = total_days
            else:
                value = getattr(obj, field)
                # Check if the value is a date or datetime field, and format it
                if isinstance(value, datetime):
                    value = value.strftime('%d/%m/%Y %H:%M')
                elif isinstance(value, date):
                    value = value.strftime('%d/%m/%Y')
            row.append(value)
        writer.writerow(row)

    return response


@login_required
@require_POST
def sickness_record_csv(request):
    if not request.user.is_manager:
        messages.error(
            request, "You do not have permission to download this data.")
        # Adjust 'dashboard' to your actual redirect path
        return redirect('user_dashboard')

    start_date = parse_custom_date(request.POST.get('start_date'))
    end_date = parse_custom_date(request.POST.get('end_date'))
    queryset = SicknessRecord.objects.filter(
        start_date__gte=start_date, end_date__lte=end_date
    )
    fieldnames = ['employee', 'start_date', 'end_date',
                  'description', 'created_by', 'timestamp']
    return export_to_csv(queryset, fieldnames, f'sickness_records_{timezone.now()}.csv')


def calculate_holiday_days_in_month(holiday_start, holiday_end, month_start, month_end):
    """
    Calculate the number of business days a holiday falls within a specific month.
    Handles holidays that span across multiple months.

    Args:
        holiday_start: datetime - Start date of the holiday
        holiday_end: datetime - End date of the holiday
        month_start: date - First day of the target month
        month_end: date - Last day of the target month

    Returns:
        float: Number of business days within the target month (rounded to 0.5)
    """
    # Ensure datetime objects are timezone-aware
    if timezone.is_naive(holiday_start):
        holiday_start = timezone.make_aware(holiday_start)
    if timezone.is_naive(holiday_end):
        holiday_end = timezone.make_aware(holiday_end)

    # Convert month boundaries to datetime for comparison
    month_start_dt = timezone.make_aware(
        datetime.combine(month_start, time(0, 0, 0)))
    month_end_dt = timezone.make_aware(
        datetime.combine(month_end, time(23, 59, 59, 999999)))

    # Find the overlap period within the month
    overlap_start = max(holiday_start, month_start_dt)
    overlap_end = min(holiday_end, month_end_dt)

    # If no overlap, return 0
    if overlap_start > overlap_end:
        return 0.0

    # Calculate business days for the overlap period
    days_in_month = calculate_business_days(overlap_start, overlap_end)
    return days_in_month


@login_required
def download_all_employee_reports(request):
    try:
        today = date.today()
        month_year = request.POST.get('month_year')  # Format: YYYY-MM

        # Parse month and year
        month_year_date = datetime.strptime(month_year, '%Y-%m').date()
        first_day_of_month = month_year_date.replace(day=1)
        last_day_of_month = (
            first_day_of_month + timedelta(days=32)).replace(day=1) - timedelta(days=1)

        # Get employees with attendance records in the specified month
        employees_with_attendance = CustomUser.objects.filter(
            attendancerecord__date__range=(
                first_day_of_month, last_day_of_month)
        ).distinct()

        if not employees_with_attendance.exists():
            messages.error(
                request, f'No employees have attendance records for {month_year_date.strftime("%B %Y")}.')
            return redirect('user_dashboard')

        mem_zip = BytesIO()

        with ZipFile(mem_zip, mode="w") as zf:
            invoices_failed = []
            for employee in employees_with_attendance:
                try:
                    # Filter records for the employee for the specified month
                    attendance_records = AttendanceRecord.objects.filter(
                        employee=employee,
                        date__range=(first_day_of_month, last_day_of_month)
                    ).order_by('date')

                    # Get holidays that overlap with the target month
                    # Only include approved holidays (excludes denied holidays and pending requests)
                    # A holiday overlaps if: start_date <= month_end AND end_date >= month_start
                    first_day_dt = timezone.make_aware(
                        datetime.combine(first_day_of_month, time(0, 0, 0)))
                    last_day_dt = timezone.make_aware(datetime.combine(
                        last_day_of_month, time(23, 59, 59, 999999)))

                    holiday_records = HolidayRecord.objects.filter(
                        employee=employee,
                        approved=True
                    ).filter(
                        # Holiday overlaps with month: start_date <= month_end AND end_date >= month_start
                        Q(start_date__lte=last_day_dt) & Q(
                            end_date__gte=first_day_dt)
                    ).order_by('start_date')

                    # Calculate days for each holiday within the target month
                    holidays_with_days = []
                    total_holiday_days = 0.0

                    for holiday in holiday_records:
                        days_in_month = calculate_holiday_days_in_month(
                            holiday.start_date,
                            holiday.end_date,
                            first_day_of_month,
                            last_day_of_month
                        )
                        holidays_with_days.append({
                            'record': holiday,
                            'days_in_month': days_in_month
                        })
                        total_holiday_days += days_in_month

                    # Get sickness records that overlap with the target month
                    # A sickness record overlaps if: start_date <= month_end AND (end_date >= month_start OR end_date is None)
                    # This handles:
                    # - Records that start before month and end during/after month
                    # - Records that start during month
                    # - Ongoing records (end_date is None) that started before or during month
                    sickness_records_query = SicknessRecord.objects.filter(
                        employee=employee
                    ).filter(
                        Q(start_date__lte=last_day_dt)
                    ).filter(
                        Q(end_date__gte=first_day_dt) | Q(
                            end_date__isnull=True)
                    ).order_by('start_date')

                    # Calculate days for each sickness record within the target month
                    sickness_with_days = []
                    total_sickness_days = 0.0

                    for sickness in sickness_records_query:
                        # Handle ongoing sickness (end_date is None)
                        if sickness.end_date is None:
                            # For ongoing sickness, calculate from start_date to end of month
                            # But only if start_date is before or during the month
                            if sickness.start_date.date() <= last_day_of_month:
                                # Use the same calculation function as holidays
                                # It will handle the overlap correctly
                                overlap_start = max(
                                    sickness.start_date, first_day_dt)
                                overlap_end = last_day_dt
                                days_in_month = calculate_holiday_days_in_month(
                                    overlap_start,
                                    overlap_end,
                                    first_day_of_month,
                                    last_day_of_month
                                )
                            else:
                                continue  # Sickness starts after the month
                        else:
                            # Calculate days for sickness record within the month
                            # This handles records that span multiple months correctly
                            days_in_month = calculate_holiday_days_in_month(
                                sickness.start_date,
                                sickness.end_date,
                                first_day_of_month,
                                last_day_of_month
                            )

                        # Only include records that have days in this month
                        if days_in_month > 0:
                            sickness_with_days.append({
                                'record': sickness,
                                'days_in_month': days_in_month
                            })
                            total_sickness_days += days_in_month

                    # Render the HTML template for the employee
                    html_string = render_to_string('employee_payroll_report.html', {
                        'employee': employee,
                        'month': month_year_date.strftime("%B %Y"),
                        'attendance': attendance_records,
                        'holidays': holidays_with_days,
                        'sickness': sickness_with_days,
                        'attendance_count': attendance_records.count(),
                        # Count of holidays, not days
                        'holiday_count': len(holidays_with_days),
                        # Total days within month
                        'holiday_days': round(total_holiday_days, 2),
                        'sickness_count': len(sickness_with_days),
                        'sickness_days': round(total_sickness_days, 2),
                    })

                    # Generate PDF
                    pdf_filename = f"{employee.username}_payroll_report.pdf"
                    pdf_file = HTML(string=html_string).write_pdf()

                    # Write PDF to zip
                    zf.writestr(pdf_filename, pdf_file)

                except Exception as e:
                    invoices_failed.append(employee.username)
                    messages.error(
                        request, f'Error generating report for {employee.username}: {str(e)}')

            if invoices_failed:
                messages.error(
                    request, f'Errors encountered for employees: {invoices_failed}')

        # Prepare the response
        mem_zip.seek(0)
        response = HttpResponse(mem_zip.read(), content_type='application/zip')
        response[
            'Content-Disposition'] = f'attachment; filename="employee_reports_{month_year_date.strftime("%Y-%m")}.zip"'

        return response

    except Exception as e:
        messages.error(
            request, f'An error was encountered. Please contact your administrators. Error: {str(e)}')

    return redirect('user_dashboard')

# views.py

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


def add_cpd_training_log(request):
    if request.method == 'POST':
        form = CPDTrainingLogForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'CPD Log successfully created.')
            return redirect('profile_page')

    return render(request, 'add_cpd_training_log.html', {'form': form})


def edit_cpd_training_log(request, pk):
    cpd_training_log = get_object_or_404(CPDTrainingLog, pk=pk)
    if request.method == 'POST':
        form = CPDTrainingLogForm(request.POST, instance=cpd_training_log)
        if form.is_valid():
            form.save()
            return redirect('profile_page')
    else:
        form = CPDTrainingLogForm(instance=cpd_training_log)

    return render(request, 'edit_cpd.html', {'form': form, 'cpd': cpd_training_log})
