from django.contrib import admin

from .models import EmailSyncState


@admin.register(EmailSyncState)
class EmailSyncStateAdmin(admin.ModelAdmin):
    list_display = ('id', 'last_success_at', 'last_run_at', 'last_status')
    readonly_fields = ('last_success_at', 'last_run_at', 'last_status', 'last_error')
