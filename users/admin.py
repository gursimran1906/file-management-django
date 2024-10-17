from django.contrib import admin
from .models import Rate, CustomUser, AttendanceRecord, HolidayRecord, SicknessRecord, UserDocument

@admin.register(Rate)
class RateAdmin(admin.ModelAdmin):
    list_display = ('desc', 'hourly_amount', 'is_active', 'timestamp')
    list_filter = ('is_active', 'archive_from')
    search_fields = ('desc',)
    ordering = ('desc',)
    actions = ['archive_rates']

    def archive_rates(self, request, queryset):
        """Custom action to archive selected rates."""
        queryset.update(is_active=False, archive_from=None)
        self.message_user(request, "Selected rates have been archived.")

    archive_rates.short_description = "Archive selected rates"

@admin.register(CustomUser)
class CustomUserAdmin(admin.ModelAdmin):
    list_display = ('username', 'email', 'first_name', 'last_name', 'is_matter_fee_earner', 'is_manager', 'hourly_rate')
    list_filter = ('is_matter_fee_earner', 'is_manager', 'hourly_rate')
    search_fields = ('username', 'email', 'first_name', 'last_name')
    ordering = ('username',)
    list_editable = ('is_matter_fee_earner', 'is_manager')

@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ('employee', 'date', 'clock_in', 'clock_out', 'lunch_in', 'lunch_out')
    list_filter = ('employee', 'date')
    search_fields = ('employee__username', 'date')
    ordering = ('-date',)

@admin.register(HolidayRecord)
class HolidayRecordAdmin(admin.ModelAdmin):
    list_display = ('employee', 'start_date', 'end_date', 'type', 'approved', 'checked_by', 'approved_by')
    list_filter = ('type', 'approved', 'employee')
    search_fields = ('employee__username', 'reason')
    ordering = ('-start_date',)
    actions = ['approve_holidays']

    def approve_holidays(self, request, queryset):
        """Custom action to approve selected holidays."""
        queryset.update(approved=True)
        self.message_user(request, "Selected holidays have been approved.")

    approve_holidays.short_description = "Approve selected holidays"

@admin.register(SicknessRecord)
class SicknessRecordAdmin(admin.ModelAdmin):
    list_display = ('employee', 'start_date', 'end_date', 'description')
    list_filter = ('employee', 'start_date')
    search_fields = ('employee__username', 'description')
    ordering = ('-start_date',)

@admin.register(UserDocument)
class UserDocumentAdmin(admin.ModelAdmin):
    list_display = ('employee', 'description', 'timestamp')
    list_filter = ('employee',)
    search_fields = ('description', 'employee__username')
    ordering = ('-timestamp',)

