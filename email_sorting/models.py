from django.db import models


class EmailSyncState(models.Model):
    """Singleton row tracking the progress/health of the email ingestion cron.

    The live sync uses ``last_success_at`` as a watermark: each run looks back to
    (last_success_at - overlap buffer) instead of a fixed 15-minute window, so any
    outage (e.g. an expired Graph secret) self-recovers once the sync resumes,
    rather than silently dropping every message received while it was down.

    Only ever one row (``pk=1``); see ``load()``.
    """

    STATUS_SUCCESS = 'success'
    STATUS_PARTIAL = 'partial'
    STATUS_FAILED = 'failed'

    # Watermark: start time of the last fully-successful run. Advanced only when
    # every mailbox/folder was fetched without error, so a partial/failed run
    # never moves the watermark past mail it did not manage to read.
    last_success_at = models.DateTimeField(null=True, blank=True)
    # Bookkeeping for the most recent run of any outcome (for the health check).
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_status = models.CharField(max_length=20, blank=True, default='')
    last_error = models.TextField(blank=True, default='')

    class Meta:
        verbose_name = 'Email sync state'
        verbose_name_plural = 'Email sync state'

    def __str__(self):
        return f'EmailSyncState(last_success_at={self.last_success_at}, status={self.last_status})'

    @classmethod
    def load(cls):
        """Return the singleton row, creating it on first use."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
