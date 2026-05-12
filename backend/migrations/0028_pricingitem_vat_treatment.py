from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0027_pricingitem'),
    ]

    operations = [
        migrations.AddField(
            model_name='pricingitem',
            name='vat_treatment',
            field=models.CharField(
                choices=[
                    ('excluding', 'Excluding VAT'),
                    ('including', 'Including VAT'),
                    ('none', 'No VAT'),
                ],
                default='excluding',
                max_length=10,
            ),
        ),
    ]
