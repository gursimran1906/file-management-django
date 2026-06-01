import backend.models
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0052_matter_email_draft'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='matteremaildraft',
            name='bcc_addresses',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='matteremaildraft',
            name='request_read_receipt',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='matteremaildraft',
            name='request_delivery_receipt',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='matteremails',
            name='bcc',
            field=models.JSONField(blank=True, default=list, null=True),
        ),
        migrations.AddField(
            model_name='matteremails',
            name='attachments',
            field=models.JSONField(blank=True, default=list, null=True),
        ),
        migrations.AddField(
            model_name='matteremails',
            name='graph_message_id',
            field=models.CharField(blank=True, max_length=512, null=True),
        ),
        migrations.AddField(
            model_name='matteremails',
            name='conversation_id',
            field=models.CharField(blank=True, max_length=512, null=True),
        ),
        migrations.AddField(
            model_name='matteremails',
            name='internet_message_id',
            field=models.CharField(blank=True, max_length=512, null=True),
        ),
        migrations.AddField(
            model_name='matteremails',
            name='request_read_receipt',
            field=models.BooleanField(default=False, null=True),
        ),
        migrations.AddField(
            model_name='matteremails',
            name='request_delivery_receipt',
            field=models.BooleanField(default=False, null=True),
        ),
        migrations.AddField(
            model_name='matteremails',
            name='sent_via_app',
            field=models.BooleanField(default=False, null=True),
        ),
        migrations.CreateModel(
            name='MatterEmailDraftAttachment',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),
                ('original_name', models.CharField(max_length=255)),
                ('content_type', models.CharField(blank=True, default='', max_length=128)),
                ('size', models.PositiveIntegerField(default=0)),
                ('file', models.FileField(upload_to=backend.models.email_draft_attachment_upload_path)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('draft', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='attachments',
                    to='backend.matteremaildraft',
                )),
            ],
        ),
    ]
