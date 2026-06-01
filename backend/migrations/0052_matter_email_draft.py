import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0051_matter_time_events'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='MatterEmailDraft',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),
                ('from_mailbox', models.CharField(blank=True, default='', max_length=255)),
                ('to_addresses', models.TextField(blank=True, default='')),
                ('cc_addresses', models.TextField(blank=True, default='')),
                ('subject', models.CharField(blank=True, default='', max_length=500)),
                ('body_html', models.TextField(blank=True, default='')),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('file_number', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    to='backend.wip',
                )),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='email_drafts',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
        ),
        migrations.AddConstraint(
            model_name='matteremaildraft',
            constraint=models.UniqueConstraint(
                fields=('file_number', 'user'),
                name='unique_email_draft_per_user_matter',
            ),
        ),
    ]
