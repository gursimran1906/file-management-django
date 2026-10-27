"""Cron entry point for the scheduled Teams call sync (wired in settings.CRONJOBS)."""
import logging

from . import pairing
from .ingest import sync_calls

logger = logging.getLogger(__name__)


def sync_teams_calls():
    """Pull new Teams calls into attendance notes / the review inbox."""
    status = sync_calls()
    # Notes pair up and settle even when the Graph poll is off or not yet
    # configured — otherwise a note typed during a call would wait for a row
    # that is never coming, and the register could never call it settled.
    paired, ambiguous, settled = pairing.pair_waiting_notes()
    if paired or ambiguous or settled:
        logger.info('Call notes: %s matched, %s awaiting a choice, %s with no '
                    'call row.', paired, ambiguous, settled)
    logger.info('Teams call sync: %s', status)
    return status
