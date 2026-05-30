from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0043_bundle_pdf_generated_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='bundle',
            name='is_court_bundle',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='bundle',
            name='court_name',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='bundle',
            name='case_number_type',
            field=models.CharField(
                blank=True,
                choices=[('claim', 'Claim No.'), ('case', 'Case No.')],
                default='claim',
                max_length=8,
            ),
        ),
        migrations.AddField(
            model_name='bundle',
            name='case_number',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='bundle',
            name='index_title',
            field=models.CharField(blank=True, default='Index to the Bundle', max_length=255),
        ),
        migrations.AddField(
            model_name='bundle',
            name='hearing_date',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='bundle',
            name='conference_date',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='bundle',
            name='court_parties',
            field=models.JSONField(blank=True, default=list),
        ),
    ]
