import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0050_estate_account_distribution_section'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='MatterTimeEvent',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),
                ('started_at', models.DateTimeField()),
                ('ended_at', models.DateTimeField()),
                ('description', models.CharField(max_length=255)),
                ('detail', models.TextField(blank=True, default='')),
                ('activity_type', models.CharField(
                    choices=[
                        ('telephone', 'Telephone'),
                        ('attendance', 'Attendance'),
                        ('drafting', 'Drafting'),
                        ('perusal', 'Perusal'),
                        ('conference', 'Conference'),
                        ('research', 'Research'),
                        ('travel', 'Travel'),
                        ('admin', 'Admin'),
                        ('other', 'Other'),
                    ],
                    default='other',
                    max_length=20,
                )),
                ('source', models.CharField(
                    choices=[
                        ('timer', 'Timer'),
                        ('manual', 'Manual'),
                        ('email', 'Email'),
                        ('letter', 'Letter'),
                        ('attendance_note', 'Attendance note'),
                        ('task', 'Task'),
                        ('app_activity', 'App activity'),
                        ('sharepoint', 'SharePoint'),
                        ('agent', 'Agent'),
                    ],
                    default='manual',
                    max_length=20,
                )),
                ('source_id', models.PositiveIntegerField(blank=True, null=True)),
                ('is_charged', models.BooleanField(default=True)),
                ('status', models.CharField(
                    choices=[
                        ('draft', 'Draft'),
                        ('confirmed', 'Confirmed'),
                        ('discarded', 'Discarded'),
                    ],
                    default='draft',
                    max_length=12,
                )),
                ('units', models.IntegerField(default=1)),
                ('locked_at', models.DateTimeField(blank=True, null=True)),
                ('timestamp', models.DateTimeField(auto_now_add=True)),
                ('attendance_note', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='time_events',
                    to='backend.matterattendancenotes',
                )),
                ('created_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='matter_time_events_created',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('file_number', models.ForeignKey(
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    to='backend.wip',
                )),
                ('invoice', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    to='backend.invoices',
                )),
                ('user', models.ForeignKey(
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='matter_time_events',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
        ),
        migrations.CreateModel(
            name='MatterTimeSession',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),
                ('started_at', models.DateTimeField()),
                ('activity_type', models.CharField(
                    choices=[
                        ('telephone', 'Telephone'),
                        ('attendance', 'Attendance'),
                        ('drafting', 'Drafting'),
                        ('perusal', 'Perusal'),
                        ('conference', 'Conference'),
                        ('research', 'Research'),
                        ('travel', 'Travel'),
                        ('admin', 'Admin'),
                        ('other', 'Other'),
                    ],
                    default='other',
                    max_length=20,
                )),
                ('timestamp', models.DateTimeField(auto_now=True)),
                ('file_number', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    to='backend.wip',
                )),
                ('user', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='matter_time_session',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
        ),
        migrations.AddIndex(
            model_name='mattertimeevent',
            index=models.Index(
                fields=['file_number', 'user', 'status'],
                name='backend_mat_file_nu_6e8f0d_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='mattertimeevent',
            index=models.Index(
                fields=['file_number', 'ended_at'],
                name='backend_mat_file_nu_2a1c9e_idx',
            ),
        ),
    ]
