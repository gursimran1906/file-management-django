from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0022_invoices_vat_calculation_mode'),
    ]

    operations = [
        migrations.AddField(
            model_name='ledgeraccounttransfers',
            name='bank_transfer_done_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='bank_transfer_done_by', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='ledgeraccounttransfers',
            name='bank_transfer_done_on',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='ledgeraccounttransfers',
            name='is_bank_transfer_done',
            field=models.BooleanField(default=False),
        ),
    ]
