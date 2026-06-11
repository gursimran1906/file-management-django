from datetime import date

from django.db import migrations


GO_LIVE = date(2026, 6, 15)  # Monday 15/06/2026


def set_start_date(apps, schema_editor):
    GranolaConfig = apps.get_model('backend', 'GranolaConfig')
    GranolaConfig.objects.filter(start_date__isnull=True).update(start_date=GO_LIVE)


def unset_start_date(apps, schema_editor):
    GranolaConfig = apps.get_model('backend', 'GranolaConfig')
    GranolaConfig.objects.filter(start_date=GO_LIVE).update(start_date=None)


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0059_granolaconfig_start_date'),
    ]

    operations = [
        migrations.RunPython(set_start_date, unset_start_date),
    ]
