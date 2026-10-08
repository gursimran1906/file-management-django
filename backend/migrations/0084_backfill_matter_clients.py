# Backfill MatterClient rows for every existing matter x client, using a mixture
# of reconstruct (from surviving per-matter evidence) and fan-out (from the
# client-level flags where no evidence exists). Documents are NOT backfilled.
from django.db import migrations


def backfill(apps, schema_editor):
    WIP = apps.get_model('backend', 'WIP')
    MatterClient = apps.get_model('backend', 'MatterClient')
    ClientContactDetails = apps.get_model('backend', 'ClientContactDetails')
    RiskAssessment = apps.get_model('backend', 'RiskAssessment')

    for wip in WIP.objects.all().iterator():
        pairs = []
        if wip.client1_id:
            pairs.append((wip.client1_id, True))
        for cid in wip.additional_clients.values_list('id', flat=True):
            pairs.append((cid, False))
        if not pairs:
            continue

        # Surviving per-matter evidence.
        ra = RiskAssessment.objects.filter(matter_id=wip.id).order_by('-id').first()
        toe_rcvd, toe_sent = wip.date_of_toe_rcvd, wip.date_of_toe_sent
        ncba_rcvd, ncba_sent = wip.date_of_ncba_rcvd, wip.date_of_ncba_sent
        toe_evidence = bool(toe_rcvd or toe_sent)
        ncba_evidence = bool(ncba_rcvd or ncba_sent)

        for cid, is_lead in pairs:
            client = ClientContactDetails.objects.filter(id=cid).first()
            if client is None:
                continue
            if MatterClient.objects.filter(matter_id=wip.id, client_id=cid).exists():
                continue  # idempotent

            reconstructed = False
            mc = MatterClient(matter_id=wip.id, client_id=cid, is_lead=is_lead)

            # Terms of engagement: reconstruct from the matter's TOE dates, else
            # fan out the client flag.
            if toe_evidence:
                # Received back = signed; sent-only means issued but not returned.
                mc.terms_of_engagement_signed = bool(toe_rcvd)
                mc.terms_of_engagement_on = toe_rcvd
                mc.terms_sent_on = toe_sent
                mc.terms_received_on = toe_rcvd
                reconstructed = True
            else:
                mc.terms_of_engagement_signed = bool(client.terms_of_engagement_signed)

            # NCBA: reconstruct from the matter's NCBA dates, else fan out.
            mc.ncba_required = True  # default; staff can clear per matter
            if ncba_evidence:
                mc.ncba_signed = bool(ncba_rcvd)  # received back = signed
                mc.ncba_on = ncba_rcvd
                mc.ncba_sent_on = ncba_sent
                mc.ncba_received_on = ncba_rcvd
                reconstructed = True
            else:
                mc.ncba_signed = bool(client.ncba_signed)

            # PEP / SOF: reconstruct from the matter's latest risk assessment
            # (the source the client flags were derived from in 0033), else fan out.
            if ra is not None:
                mc.pep_signed = (ra.is_pep_questionnaire_completed == 'Yes')
                # SOF counts as done if the questionnaire is marked complete OR a
                # source-of-funds narrative was recorded on the risk assessment.
                mc.source_of_funds_signed = (
                    ra.is_source_of_funds_questionnaire_completed == 'Yes'
                    or bool((ra.client_source_of_funds or '').strip()))
                if mc.source_of_funds_signed:
                    mc.source_of_funds_details = (ra.client_source_of_funds or '').strip()[:255]
                reconstructed = True
            else:
                mc.pep_signed = bool(client.pep_signed)
                mc.source_of_funds_signed = bool(client.source_of_funds_signed)

            mc.source = 'reconstructed' if reconstructed else 'carried_over'
            mc.save()


def unbackfill(apps, schema_editor):
    # Remove only the rows this migration created (never the 'captured' rows that
    # capture flows add going forward).
    MatterClient = apps.get_model('backend', 'MatterClient')
    MatterClient.objects.filter(source__in=['reconstructed', 'carried_over']).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0083_conveyancingdetails_matterclient_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill, unbackfill),
    ]
