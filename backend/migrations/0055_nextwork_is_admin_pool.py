from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0054_multi_client_support'),
    ]

    operations = [
        migrations.AddField(
            model_name='nextwork',
            name='is_admin_pool',
            field=models.BooleanField(default=False),
        ),
    ]
