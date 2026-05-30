from django.db import migrations, models


def set_pdf_generated_at(apps, schema_editor):
    Bundle = apps.get_model('backend', 'Bundle')
    for bundle in Bundle.objects.filter(is_finalized=True).exclude(final_pdf='').exclude(final_pdf__isnull=True):
        Bundle.objects.filter(pk=bundle.pk).update(pdf_generated_at=bundle.updated_at)


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0042_alter_bundlesection_date_sort_default'),
    ]

    operations = [
        migrations.AddField(
            model_name='bundle',
            name='pdf_generated_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(set_pdf_generated_at, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='bundle',
            name='is_finalized',
        ),
    ]
