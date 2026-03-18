from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0023_ledgeraccounttransfers_bank_transfer_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='ledgeraccounttransfers',
            name='is_cashier_co_transfer',
            field=models.BooleanField(default=False),
        ),
    ]
