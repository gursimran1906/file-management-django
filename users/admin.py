from django.contrib import admin
from .models import CustomUser, Rate
# Register your models here.
admin.site.register(CustomUser)

admin.site.register(Rate)