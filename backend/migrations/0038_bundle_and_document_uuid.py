import uuid

from django.db import migrations, models


def populate_uuids(apps, schema_editor):
    Bundle = apps.get_model('backend', 'Bundle')
    BundleDocument = apps.get_model('backend', 'BundleDocument')

    for bundle in Bundle.objects.all().only('id', 'uuid'):
        Bundle.objects.filter(pk=bundle.pk).update(uuid=uuid.uuid4())

    for document in BundleDocument.objects.all().only('id', 'uuid'):
        BundleDocument.objects.filter(pk=document.pk).update(uuid=uuid.uuid4())


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0037_bundledocument_page_order'),
    ]

    operations = [
        migrations.AddField(
            model_name='bundle',
            name='uuid',
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.AddField(
            model_name='bundledocument',
            name='uuid',
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.RunPython(populate_uuids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='bundle',
            name='uuid',
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
        migrations.AlterField(
            model_name='bundledocument',
            name='uuid',
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
