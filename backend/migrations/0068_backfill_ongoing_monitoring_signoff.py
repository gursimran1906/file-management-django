from django.db import migrations
from django.db.models import F


def mark_existing_monitoring_signed(apps, schema_editor):
    """Existing ongoing monitoring records predate the sign-off workflow:
    treat them as signed off by their recorded signer so dashboards don't
    flood with historical 'awaiting sign-off' entries."""
    OngoingMonitoring = apps.get_model('backend', 'OngoingMonitoring')
    OngoingMonitoring.objects.update(
        signoff_status='signed',
        signed_off_by=F('signed_by'),
        signed_off_at=F('timestamp'),
    )


def unmark(apps, schema_editor):
    OngoingMonitoring = apps.get_model('backend', 'OngoingMonitoring')
    OngoingMonitoring.objects.update(
        signoff_status='awaiting',
        signed_off_by=None,
        signed_off_at=None,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0067_ongoingmonitoring_signoff'),
    ]

    operations = [
        migrations.RunPython(mark_existing_monitoring_signed, unmark),
    ]
