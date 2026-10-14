"""django-crontab entry point: run queued correspondence exports (see settings.CRONJOBS)."""
from datetime import datetime

from django.core.cache import cache

LOCK_KEY = 'correspondence_export_worker'
LOCK_SECONDS = 30 * 60


def run_pending():
    if not cache.add(LOCK_KEY, '1', timeout=LOCK_SECONDS):
        return 0
    try:
        from .runner import mark_stale_jobs, process_pending
        stale = mark_stale_jobs()
        ran = process_pending(max_jobs=3)
        if stale or ran:
            print(f'{datetime.now().isoformat(timespec="seconds")} correspondence exports: '
                  f'{ran} job(s) run, {stale} stale job(s) failed')
        return ran
    finally:
        cache.delete(LOCK_KEY)
