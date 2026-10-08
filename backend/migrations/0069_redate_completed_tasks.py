from django.db import migrations
from django.utils import timezone


def redate_completed_tasks(apps, schema_editor):
    """LastWork rows created by completing a NextWork used to copy the task's
    own date (when it was raised / due) instead of the day it was completed.
    Re-date those rows to the day they were created, which is the moment the
    task was marked completed. Manually recorded LastWork rows are left alone:
    only rows that still match a completed task on (matter, person, task text,
    task date) are touched."""
    LastWork = apps.get_model('backend', 'LastWork')
    NextWork = apps.get_model('backend', 'NextWork')

    task_keys = set(
        NextWork.objects.filter(status='completed')
        .values_list('file_number_id', 'person_id', 'task', 'date')
    )
    if not task_keys:
        return

    for row in LastWork.objects.only('file_number_id', 'person_id', 'task', 'date', 'timestamp').iterator():
        if (row.file_number_id, row.person_id, row.task, row.date) not in task_keys:
            continue
        completed_on = timezone.localtime(row.timestamp).date()
        if row.date != completed_on:
            LastWork.objects.filter(pk=row.pk).update(date=completed_on)


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0068_backfill_ongoing_monitoring_signoff'),
    ]

    operations = [
        migrations.RunPython(redate_completed_tasks, migrations.RunPython.noop),
    ]
