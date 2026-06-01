from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0053_email_attachments_tracking'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='matteremaildraft',
            name='unique_email_draft_per_user_matter',
        ),
        migrations.AlterModelOptions(
            name='matteremaildraft',
            options={'ordering': ['-updated_at']},
        ),
    ]
