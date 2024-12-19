from django.db import models

# Create your models here.
from django.contrib.auth.models import AbstractUser
from django.db import models
import uuid


class Rate(models.Model):
    id = models.AutoField(primary_key=True)
    desc = models.CharField(max_length=255)
    hourly_amount = models.DecimalField(decimal_places=2,max_digits=6)
    is_active=models.BooleanField(null=True,default=True)
    archive_from = models.DateField(blank=True,null=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.desc} - Hourly rate £{self.hourly_amount} - is_active = {self.is_active}'

class CustomUser(AbstractUser):
   
    username = models.CharField(max_length=3, unique=True)
    email = models.EmailField(blank=False, null=False)
    first_name = models.CharField(max_length=30, blank=False, null=False)
    last_name = models.CharField(max_length=30, blank=False, null=False)
    is_matter_fee_earner = models.BooleanField(default=False)
    is_manager = models.BooleanField(default=False)
    hourly_rate = models.ForeignKey(Rate,null=True, on_delete=models.SET_NULL)
    max_holidays_in_year=models.DecimalField(decimal_places=2, max_digits=4)
    def __str__(self):
        return self.username
    
class AttendanceRecord(models.Model):
    employee = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    date = models.DateField()
    clock_in = models.DateTimeField()
    clock_out = models.DateTimeField(null=True, blank=True)
    lunch_in = models.DateTimeField(null=True, blank=True)
    lunch_out = models.DateTimeField(null=True, blank=True)


class HolidayRecord(models.Model):
    TYPE_CHOICES = [
        ('Paid', 'Paid'),
        ('Unpaid', 'Unpaid')  
    ]
    employee = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    reason = models.TextField(null=True, blank=True)
    type=models.CharField(max_length=10, choices=TYPE_CHOICES, default='Paid')
    approved = models.BooleanField(default=False)
    checked_by=models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='holiday_checked_by')
    checked_on = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='holiday_approved_by')
    approved_on = models.DateTimeField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

class SicknessRecord(models.Model):
    employee = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    start_date = models.DateTimeField()
    end_date = models.DateTimeField(null=True, blank=True)
    description = models.TextField()
    created_by=models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='sickness_record_created_by')
    timestamp = models.DateTimeField(auto_now_add=True)

def user_document_file_upload_path(instance, filename):
    return f'undertakings/{instance.file_number.file_number}/{filename}'
 
class UserDocument(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    document = models.FileField(upload_to=user_document_file_upload_path)
    employee = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    description = models.TextField()
    added_by=models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='added_by')
    timestamp=models.DateTimeField(auto_now_add=True)

class CPDTrainingLog(models.Model):
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True)
    course_title = models.TextField()
    delivered_by = models.TextField()
    DELIVERY_METHOD_CHOICES = [
        ('in_person', 'In-person'),
        ('online', 'Online'),
    ]
    delivery_of_course = models.CharField(max_length=20, choices=DELIVERY_METHOD_CHOICES)
    date_completed = models.DateField()
    impact = models.TextField()
    certificate_provided = models.BooleanField()
    created_at = models.DateTimeField(auto_now_add=True) 
    updated_at = models.DateTimeField(auto_now=True) 

    def __str__(self):
        return self.course_title
    