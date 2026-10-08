"""Report email-sync health from the EmailSyncState watermark.

Prints when the sync last succeeded and how long ago. Exits non-zero when the
last successful run is older than --max-age-minutes, so it can be wired to
external uptime monitoring (a channel that does not depend on the Graph secret,
unlike the built-in alert email).

Examples:
    python manage.py email_sync_health
    python manage.py email_sync_health --max-age-minutes 45
"""

import sys

from django.core.management.base import BaseCommand
from django.utils import timezone

from email_sorting.models import EmailSyncState


class Command(BaseCommand):
    help = ("Report email-sync health (minutes since last successful run). "
            "Exits non-zero if stale beyond --max-age-minutes.")

    def add_arguments(self, parser):
        parser.add_argument(
            '--max-age-minutes', type=int, default=60,
            help='Minutes since last success beyond which the sync is UNHEALTHY (default 60).')

    def handle(self, *args, **options):
        max_age = options['max_age_minutes']
        state = EmailSyncState.load()
        now = timezone.now()

        self.stdout.write(f"last_success_at : {state.last_success_at}")
        self.stdout.write(f"last_run_at     : {state.last_run_at}")
        self.stdout.write(f"last_status     : {state.last_status or '(never run)'}")
        if state.last_error:
            self.stdout.write(f"last_error      : {state.last_error}")

        if not state.last_success_at:
            self.stderr.write(self.style.WARNING(
                "UNHEALTHY: no successful run recorded yet."))
            sys.exit(1)

        age_min = (now - state.last_success_at).total_seconds() / 60
        self.stdout.write(f"minutes_since_success : {age_min:.1f}")
        if age_min > max_age:
            self.stderr.write(self.style.ERROR(
                f"UNHEALTHY: last success {age_min:.1f} min ago (> {max_age})."))
            sys.exit(1)
        self.stdout.write(self.style.SUCCESS(
            f"HEALTHY: last success {age_min:.1f} min ago."))
