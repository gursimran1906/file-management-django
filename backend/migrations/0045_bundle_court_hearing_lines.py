from django.db import migrations, models


def migrate_court_dates_to_lines(apps, schema_editor):
    Bundle = apps.get_model('backend', 'Bundle')
    for bundle in Bundle.objects.all():
        updates = {}
        if bundle.hearing_date:
            updates['hearing_line'] = (
                f'for hearing on {bundle.hearing_date.strftime("%d %B %Y")}'
            )
        if bundle.conference_date:
            updates['conference_line'] = (
                f'for conference on {bundle.conference_date.strftime("%d %B %Y")}'
            )
        if updates:
            Bundle.objects.filter(pk=bundle.pk).update(**updates)


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0044_bundle_court_settings'),
    ]

    operations = [
        migrations.AddField(
            model_name='bundle',
            name='hearing_line',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='bundle',
            name='conference_line',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.RunPython(migrate_court_dates_to_lines, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='bundle',
            name='hearing_date',
        ),
        migrations.RemoveField(
            model_name='bundle',
            name='conference_date',
        ),
    ]
