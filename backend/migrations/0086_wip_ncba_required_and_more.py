"""NCBA becomes a matter-level fact.

Whether a file is under a non-contentious business agreement is recorded once on
the matter (``WIP.ncba_required``, off by default); when it is, every client signs
it for that file (still tracked per MatterClient). The old per-client
``ncba_required`` flag defaulted to True for everyone, so it carried no signal —
it is dropped after seeding the matter flag from any NCBA evidence (a signed or
sent/received NCBA on a matter-client, or the legacy NCBA dates on the matter).

Also lets identity documents record a selfie with ID (the third identity item the
onboarding portal collects), so staff can upload one for clients onboarded in
the office.
"""
from django.db import migrations, models
from django.db.models import Q


def seed_matter_ncba(apps, schema_editor):
    WIP = apps.get_model('backend', 'WIP')
    MatterClient = apps.get_model('backend', 'MatterClient')
    under = set(MatterClient.objects.filter(
        Q(ncba_signed=True) | Q(ncba_sent_on__isnull=False)
        | Q(ncba_received_on__isnull=False)
    ).values_list('matter_id', flat=True))
    under |= set(WIP.objects.filter(
        Q(date_of_ncba_sent__isnull=False) | Q(date_of_ncba_rcvd__isnull=False)
    ).values_list('id', flat=True))
    if under:
        WIP.objects.filter(id__in=under).update(ncba_required=True)


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0085_clientkeydocument_file'),
    ]

    operations = [
        migrations.AddField(
            model_name='wip',
            name='ncba_required',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(seed_matter_ncba, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='matterclient',
            name='ncba_required',
        ),
        migrations.AlterField(
            model_name='clientkeydocument',
            name='category',
            field=models.CharField(choices=[('proof_of_id', 'Proof of ID'), ('proof_of_address', 'Proof of Address'), ('selfie_id', 'Selfie with ID')], max_length=50),
        ),
    ]
