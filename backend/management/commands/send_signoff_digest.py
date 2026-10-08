"""Send (or preview) the morning sign-off digest emails."""

from django.core.management.base import BaseCommand

from backend.signoff_digest import build_digests, is_enabled, send_signoff_digests


class Command(BaseCommand):
    help = 'Email each fee earner what is waiting for their sign-off (cron runs this on weekday mornings).'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='List who would receive what; send nothing.')

    def handle(self, *args, **options):
        for user, items in build_digests().items():
            self.stdout.write(f'{user.username} <{user.email}>: {len(items)} item(s)')
            for item in items:
                self.stdout.write(f'  - {item.matter.file_number} {item.type_label} ({item.status_label})')
        if options['dry_run']:
            self.stdout.write('Dry run: nothing sent.')
            return
        if not is_enabled():
            self.stdout.write('SIGNOFF_DIGEST_EMAILS is off: nothing sent.')
            return
        summary = send_signoff_digests()
        self.stdout.write(f"Sent {summary['sent']}, skipped {summary['skipped']}.")
