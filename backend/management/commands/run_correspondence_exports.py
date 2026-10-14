"""Run queued correspondence exports (search + build) from the command line.

The production cron entry (settings.CRONJOBS -> backend.correspondence_export.cron)
does the same every minute. Use this to run jobs by hand, e.g. in development
without the thread runner, or to keep a worker loop running:

    python manage.py run_correspondence_exports            # run whatever is queued, once
    python manage.py run_correspondence_exports --loop 10  # keep polling every 10 seconds
"""
import time

from django.core.management.base import BaseCommand

from backend.correspondence_export.runner import mark_stale_jobs, process_pending


class Command(BaseCommand):
    help = 'Run queued correspondence exports (discovery and build jobs).'

    def add_arguments(self, parser):
        parser.add_argument('--loop', type=int, default=0, metavar='SECONDS',
                            help='Keep polling for new jobs every SECONDS (default: run once).')
        parser.add_argument('--max-jobs', type=int, default=3)

    def handle(self, *args, **options):
        interval = options['loop']
        while True:
            stale = mark_stale_jobs()
            ran = process_pending(max_jobs=options['max_jobs'])
            self.stdout.write(f'{ran} job(s) run, {stale} stale job(s) failed')
            if not interval:
                break
            time.sleep(interval)
