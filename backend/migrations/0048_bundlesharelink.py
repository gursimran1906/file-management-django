from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from django.utils import timezone


def migrate_legacy_bundle_share_links(apps, schema_editor):
    Bundle = apps.get_model('backend', 'Bundle')
    BundleShareLink = apps.get_model('backend', 'BundleShareLink')
    for bundle in Bundle.objects.exclude(share_link_url='').exclude(share_link_url__isnull=True):
        if not bundle.share_link_url:
            continue
        BundleShareLink.objects.create(
            bundle=bundle,
            url=bundle.share_link_url,
            permission_id=bundle.share_link_permission_id or '',
            password=bundle.share_link_password or '',
            use_password=bool(bundle.share_link_password),
            expires_at=bundle.share_link_expires_at,
            created_at=bundle.share_link_created_at or timezone.now(),
            created_by=bundle.created_by,
        )


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('backend', '0047_bundle_share_link_fields'),
    ]

    operations = [
        migrations.CreateModel(
            name='BundleShareLink',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('url', models.URLField(max_length=512)),
                ('permission_id', models.CharField(max_length=255)),
                ('password', models.CharField(blank=True, default='', max_length=128)),
                ('use_password', models.BooleanField(default=False)),
                ('expires_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('revoked_at', models.DateTimeField(blank=True, null=True)),
                ('bundle', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='share_links', to='backend.bundle')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.RunPython(migrate_legacy_bundle_share_links, migrations.RunPython.noop),
    ]
