from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0052_completion_statement_expansion'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoices',
            name='is_matter_final_invoice',
            field=models.BooleanField(
                default=False,
                help_text='Marks this as the closing invoice for the matter (shown on printed invoices).',
            ),
        ),
    ]
