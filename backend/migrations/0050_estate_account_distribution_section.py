from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0049_alter_bundlesharelink_id'),
    ]

    operations = [
        migrations.AlterField(
            model_name='estateaccountfinancelineoverride',
            name='section_override',
            field=models.CharField(
                blank=True,
                choices=[
                    ('asset', 'Asset'),
                    ('debt', 'Debt'),
                    ('distribution', 'Distribution'),
                ],
                max_length=12,
                null=True,
            ),
        ),
    ]
