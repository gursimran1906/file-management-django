from django.contrib import admin
from .models import CustomUser, Rate, AttendanceRecord, HolidayRecord, SicknessRecord
# Register your models here.
admin.site.register(CustomUser)

admin.site.register(Rate)

admin.site.register(AttendanceRecord)
admin.site.register(HolidayRecord)
admin.site.register(SicknessRecord)