"""Cron entry point for the scheduled Teams call sync (wired in settings.CRONJOBS)."""
import logging

from .ingest import sync_calls

logger = logging.getLogger(__name__)


def sync_teams_calls():
    """Pull new Teams calls into attendance notes / the review inbox."""
    status = sync_calls()
    logger.info('Teams call sync: %s', status)
    return status
