from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0033_client_compliance_authorised_party_aml_zdrive'),
    ]

    operations = [
        migrations.AddField(
            model_name='clientcontactdetails',
            name='is_business',
            field=models.BooleanField(default=False),
        ),
    ]
