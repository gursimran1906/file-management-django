from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def _resolve_user(CustomUser, value):
    raw_value = (value or '').strip()
    if not raw_value:
        return None

    user = CustomUser.objects.filter(username__iexact=raw_value).first()
    if user:
        return user

    user = CustomUser.objects.filter(first_name__iexact=raw_value).first()
    if user:
        return user

    user = CustomUser.objects.filter(last_name__iexact=raw_value).first()
    if user:
        return user

    if ' ' in raw_value:
        first_name, last_name = raw_value.split(' ', 1)
        user = CustomUser.objects.filter(
            first_name__iexact=first_name.strip(),
            last_name__iexact=last_name.strip()
        ).first()
        if user:
            return user

    return None


def forwards_map_text_to_users(apps, schema_editor):
    MatterFileReview = apps.get_model('backend', 'MatterFileReview')
    CustomUser = apps.get_model('users', 'CustomUser')

    for review in MatterFileReview.objects.all().iterator():
        reviewed_by_user = _resolve_user(
            CustomUser, getattr(review, 'file_reviewed_by', None))
        completed_by_user = _resolve_user(
            CustomUser, getattr(review, 'file_review_completed_by', None))

        update_fields = []
        if reviewed_by_user:
            review.file_reviewed_by_user_id = reviewed_by_user.id
            update_fields.append('file_reviewed_by_user')
        if completed_by_user:
            review.file_review_completed_by_user_id = completed_by_user.id
            update_fields.append('file_review_completed_by_user')

        if update_fields:
            review.save(update_fields=update_fields)


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0025_matterfilereview'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='matterfilereview',
            name='file_review_completed_by_user',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='matter_file_reviews_completed_by', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='matterfilereview',
            name='file_reviewed_by_user',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='matter_file_reviews_reviewed_by', to=settings.AUTH_USER_MODEL),
        ),
        migrations.RunPython(forwards_map_text_to_users, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='matterfilereview',
            name='file_review_completed_by',
        ),
        migrations.RemoveField(
            model_name='matterfilereview',
            name='file_reviewed_by',
        ),
        migrations.RenameField(
            model_name='matterfilereview',
            old_name='file_review_completed_by_user',
            new_name='file_review_completed_by',
        ),
        migrations.RenameField(
            model_name='matterfilereview',
            old_name='file_reviewed_by_user',
            new_name='file_reviewed_by',
        ),
    ]
