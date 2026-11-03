from django.db import migrations

# Starting points for the matter risk score, per type of work. Conveyancing
# leads because the SRA's sectoral risk assessment and its MLRO reports
# consistently put it at the highest inherent risk; most family work falls
# outside the MLRs unless it moves property or funds. The firm can retune any
# of these in admin afterwards — this only sets the initial value.
INHERENT_RISK_BY_TYPE = {
    'conveyancing': 'High',
    'probate': 'Medium',
    'family': 'Low',
}

LEVELS = {'Low': 0, 'Medium': 1, 'High': 2}


def seed(apps, schema_editor):
    MatterType = apps.get_model('backend', 'MatterType')
    for matter_type in MatterType.objects.all():
        key = (matter_type.type or '').strip().lower()
        for name, level in INHERENT_RISK_BY_TYPE.items():
            if name in key:
                matter_type.inherent_risk = level
                matter_type.save(update_fields=['inherent_risk'])
                break

    RiskAssessment = apps.get_model('backend', 'RiskAssessment')
    for ra in RiskAssessment.objects.all().iterator():
        # Assessments completed before scoring existed are left as they were
        # rated. Re-scoring them now would be misleading: the questions added
        # for the 2026 sectoral risks were never put to the fee earner, so they
        # all sit at their defaults. Recording the rating as both computed and
        # recorded keeps them out of the "overridden" reports; they get a real
        # score the next time they are reviewed.
        ra.computed_client_risk_level = ra.client_risk_level
        ra.computed_matter_risk_level = ra.matter_risk_level
        ra.computed_due_diligence_level = ra.customer_due_diligence_level
        ra.overall_risk_level = (
            ra.client_risk_level
            if LEVELS.get(ra.client_risk_level, 0) >= LEVELS.get(ra.matter_risk_level, 0)
            else ra.matter_risk_level
        )
        ra.scoring_version = 'legacy'
        # A PEP recorded without a type is treated as the higher risk of the
        # two, matching RiskAssessment.save().
        if ra.politically_exposed_person == 'Yes' and ra.pep_type == 'N/A':
            ra.pep_type = 'Non-domestic'
        ra.save(update_fields=[
            'computed_client_risk_level', 'computed_matter_risk_level',
            'computed_due_diligence_level', 'overall_risk_level',
            'scoring_version', 'pep_type',
        ])


def unseed(apps, schema_editor):
    # Nothing to undo: 0091 drops the columns these values live in.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0091_mattertype_inherent_risk_and_more'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
