# File review questionnaire rework (Oct 2026):
#   - "File Opening Checklist completed?" dropped (file opening is now enforced
#     by the onboarding / open-file flow instead of checked after the fact).
#   - The whole "Matter Management" section dropped, except "Costs estimates
#     updated", which moves to the renamed "Client Care, Legal Advice And
#     Instructions" section.
#   - Several questions reworded; where the meaning shifted the column is
#     renamed (not recreated) so answers already recorded are kept.
#   - "Recommendations and further actions" + "Additional notes or comments"
#     merged into one "Additional comments, recommendations and further
#     actions" box; existing text from both is carried across.

from django.db import migrations, models


REMOVED_QUESTIONS = [
    'file_opening_checklist_completed',
    'key_dates_recorded_in_calendar_and_wip',
    'key_information_and_advice_shared',
    'matter_progressing_without_dormancy',
    'file_maintained_in_good_order',
]

RENAMED_QUESTIONS = [
    ('overdue_invoices', 'unpaid_invoices'),
    ('appropriate_advice_given', 'client_kept_updated'),
    ('matter_within_client_care_scope', 'matter_proceeding_per_client_instructions'),
    ('undertakings_discharged_or_released', 'undertakings_satisfied'),
]


def merge_outcome_text(recommendations, notes):
    parts = [
        (text or '').strip()
        for text in (recommendations, notes)
    ]
    return '\n\n'.join(part for part in parts if part) or None


def merge_outcome_fields(apps, schema_editor):
    MatterFileReview = apps.get_model('backend', 'MatterFileReview')
    for review in MatterFileReview.objects.all().iterator():
        combined = merge_outcome_text(
            review.recommendations_and_further_actions,
            review.additional_notes_or_comments,
        )
        if combined:
            review.comments_recommendations_and_further_actions = combined
            review.save(update_fields=['comments_recommendations_and_further_actions'])


def split_outcome_fields(apps, schema_editor):
    # The merged text can't be split back apart; keep it all under
    # recommendations so nothing is lost on a rollback.
    MatterFileReview = apps.get_model('backend', 'MatterFileReview')
    for review in MatterFileReview.objects.exclude(
            comments_recommendations_and_further_actions__isnull=True).iterator():
        review.recommendations_and_further_actions = (
            review.comments_recommendations_and_further_actions)
        review.save(update_fields=['recommendations_and_further_actions'])


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0087_merge_main_into_matter_compliance'),
    ]

    operations = [
        migrations.AddField(
            model_name='matterfilereview',
            name='comments_recommendations_and_further_actions',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.RunPython(merge_outcome_fields, split_outcome_fields),
        migrations.RemoveField(
            model_name='matterfilereview',
            name='recommendations_and_further_actions',
        ),
        migrations.RemoveField(
            model_name='matterfilereview',
            name='additional_notes_or_comments',
        ),
    ] + [
        migrations.RemoveField(model_name='matterfilereview', name=name)
        for question in REMOVED_QUESTIONS
        for name in (question, f'{question}_comments')
    ] + [
        migrations.RenameField(
            model_name='matterfilereview', old_name=old, new_name=new)
        for old_q, new_q in RENAMED_QUESTIONS
        for old, new in ((old_q, new_q), (f'{old_q}_comments', f'{new_q}_comments'))
    ]
