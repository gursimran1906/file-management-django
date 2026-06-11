"""Cron entry point for the scheduled Granola sync (wired in settings.CRONJOBS)."""
import logging

from .ingest import sync_notes

logger = logging.getLogger(__name__)


def sync_granola_notes():
    """Pull new Granola notes into attendance notes / the review inbox."""
    status = sync_notes()
    logger.info('Granola sync: %s', status)
    return status
