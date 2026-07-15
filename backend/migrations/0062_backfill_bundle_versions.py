from django.db import migrations


def backfill_versions(apps, schema_editor):
    """Create a v1 for every bundle that already has a rendered PDF.

    v1 points at the existing (legacy, overwrite-path) final_pdf so the file is
    left exactly where it is. The bundle's current_version is set to it, and any
    existing share links are repointed at v1 so they keep resolving.
    """
    Bundle = apps.get_model('backend', 'Bundle')
    BundleVersion = apps.get_model('backend', 'BundleVersion')

    for bundle in Bundle.objects.all().iterator():
        if not bundle.final_pdf:
            continue
        if bundle.versions.exists():
            continue
        version = BundleVersion.objects.create(
            bundle=bundle,
            version=1,
            final_pdf=bundle.final_pdf.name,
            pdf_generated_at=bundle.pdf_generated_at,
            created_by=bundle.created_by,
        )
        bundle.current_version = version
        bundle.save(update_fields=['current_version'])
        bundle.share_links.filter(version__isnull=True).update(version=version)


def unbackfill_versions(apps, schema_editor):
    Bundle = apps.get_model('backend', 'Bundle')
    BundleVersion = apps.get_model('backend', 'BundleVersion')
    BundleShareLink = apps.get_model('backend', 'BundleShareLink')

    BundleShareLink.objects.update(version=None)
    Bundle.objects.update(current_version=None)
    BundleVersion.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0061_bundleversion_bundle_current_version_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_versions, unbackfill_versions),
    ]
