from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0046_estate_account'),
    ]

    operations = [
        migrations.AddField(
            model_name='bundle',
            name='share_link_created_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='bundle',
            name='share_link_expires_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='bundle',
            name='share_link_password',
            field=models.CharField(blank=True, default='', max_length=128),
        ),
        migrations.AddField(
            model_name='bundle',
            name='share_link_permission_id',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='bundle',
            name='share_link_url',
            field=models.URLField(blank=True, default='', max_length=512),
        ),
    ]
