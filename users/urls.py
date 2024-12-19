from django.urls import path
from .views import add_cpd_training_log, edit_cpd_training_log, login_view, logout_view, register_view, profile_page, add_holiday_request, lunch_start, lunch_out, clock_out
from .views import deny_holiday_request, approve_holiday_request, add_sickness_record, holiday_records, sickness_records, calendar_events
from .views import edit_holiday_record, add_document, delete_document, access_document, add_office_closure, holiday_record_csv, attendance_record_csv, sickness_record_csv
from .views import download_all_employee_reports


urlpatterns = [
    path('login/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),
    path('register/', register_view, name='register'),
    path('profile/', profile_page, name='profile_page'),

    path('add_document/', add_document, name='add_document'),
    path('delete/<uuid:uuid>/', delete_document, name='delete_document'),
    path('access_document/<uuid:uuid>/', access_document, name='access_document'),
    
    path('add_holiday_request/', add_holiday_request, name='add_holiday_request'),
    path('holiday/edit/<int:holiday_id>/', edit_holiday_record, name='edit_holiday_record'),
    path('holiday_records/', holiday_records, name='holiday_records'),
    path('add_office_closure/', add_office_closure, name='add_office_closure'),

    path('add_sickness_record/', add_sickness_record, name='add_sickness_record'),
    path('sickness_records/', sickness_records, name='sickness_records'),
    path('calendar/events/', calendar_events, name='calendar_events'),
    path('lunch_start/', lunch_start, name='lunch_start'),    
    path('lunch_end/', lunch_out, name='lunch_end'),          
    path('clock_out/', clock_out, name='clock_out'),
    path('approve_holiday_request/<int:id>/', approve_holiday_request, name='approve_holiday_request'),
    path('deny_holiday_request/<int:id>/', deny_holiday_request, name='deny_holiday_request'),


    path('download/attendance/', attendance_record_csv, name='attendance_record_csv'),
    path('download/holiday/',holiday_record_csv, name='holiday_record_csv'),
    path('download/sickness/', sickness_record_csv, name='sickness_record_csv'),
    path('download/payroll-data',download_all_employee_reports, name='payroll_reports_zip' ),

    path('cpd/add/', add_cpd_training_log, name='add_cpd'),
    path('cpd/edit/<int:pk>/', edit_cpd_training_log, name='edit_cpd'),

    # Other URL patterns
]
