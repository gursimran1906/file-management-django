"""File review cadence.

Every live matter must have a supervisor file review every
``FILE_REVIEW_INTERVAL_MONTHS`` months, counted from the date the file was
opened (its WIP record's creation) or from its last *completed* review,
whichever is later. The dashboard card, the "File reviews due" report, the
compliance stats and the matter home page all read this one rule.
"""
from datetime import datetime

from dateutil.relativedelta import relativedelta
from django.db.models import OuterRef, Q, Subquery
from django.utils import timezone

from .models import LIVE_FILE_STATUSES, MatterFileReview

FILE_REVIEW_INTERVAL_MONTHS = 4


def _as_date(value):
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return value.date()
    return value


def file_review_due_date(opened, last_review_completed=None):
    """Date the next file review falls due: the interval after the last
    completed review, or after the file was opened when it has never been
    reviewed. ``opened`` may be the WIP timestamp (aware datetime) or a date."""
    anchor = _as_date(last_review_completed) or _as_date(opened)
    if anchor is None:
        return None
    return anchor + relativedelta(months=FILE_REVIEW_INTERVAL_MONTHS)


def annotate_latest_file_review(wip_queryset):
    """Annotate matters with ``latest_review_date`` and ``latest_review_by``
    from their most recent completed review. Reviews still pending (no
    completion date) don't count."""
    completed = MatterFileReview.objects.filter(
        matter=OuterRef('pk'), date_review_completed__isnull=False,
    ).order_by('-date_review_completed')
    return wip_queryset.annotate(
        latest_review_date=Subquery(
            completed.values('date_review_completed')[:1]),
        latest_review_by=Subquery(
            completed.values('file_review_completed_by__first_name')[:1]),
    )


def get_file_reviews_due_queryset(wip_queryset):
    """Live matters whose next file review date has arrived: never reviewed
    and opened at least the interval ago, or last reviewed at least the
    interval ago."""
    cutoff = timezone.localdate() - relativedelta(months=FILE_REVIEW_INTERVAL_MONTHS)
    return annotate_latest_file_review(wip_queryset).filter(
        Q(file_status__status__in=LIVE_FILE_STATUSES) & (
            Q(latest_review_date__isnull=True, timestamp__date__lte=cutoff) |
            Q(latest_review_date__lte=cutoff)
        )
    ).order_by('file_number')
