"""Backfill emails missed during an email-sync outage.

The live cron only ever looks back a short window, so mail that arrives while the
sync is down (e.g. an expired Graph secret) is never re-fetched automatically.
This command re-fetches an explicit [--start, --end] window across all six
mailboxes (Inbox + Sent Items) and stores anything not already present. It is
de-duplicated by webLink in ``process_email``, so it is safe to re-run and safe
to overlap with the live cron.

Examples:
    python manage.py backfill_emails --start 2026-08-05T00:00:00Z --dry-run
    python manage.py backfill_emails --start 2026-08-05T00:00:00Z
    python manage.py backfill_emails --start 2026-08-05T00:00:00Z \\
        --end 2026-08-06T09:00:00Z --mailboxes conveyancing@anpsolicitors.com
"""

import asyncio
from datetime import datetime, timezone as dt_timezone

from django.core.management.base import BaseCommand, CommandError

from email_sorting.utils import MAIL_FOLDERS, Sorting


def _parse_dt(label, value):
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        raise CommandError(
            f"--{label} must be ISO-8601 (e.g. 2026-08-05T09:00:00Z); got {value!r}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=dt_timezone.utc)
    return dt


class Command(BaseCommand):
    help = ("Backfill emails missed during a sync outage. Fetches every message in "
            "[--start, --end] across all six mailboxes (Inbox + Sent Items) and stores "
            "any not already present (de-duped by webLink, so it is safe to re-run).")

    def add_arguments(self, parser):
        parser.add_argument(
            '--start', required=True,
            help='ISO-8601 UTC datetime to backfill from, e.g. 2026-08-05T00:00:00Z.')
        parser.add_argument(
            '--end', default=None,
            help='ISO-8601 UTC datetime to backfill to (default: open-ended / now).')
        parser.add_argument(
            '--mailboxes', default=None,
            help='Comma-separated subset of mailboxes to fetch (default: all six).')
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Fetch and report counts without writing anything to the database.')

    def handle(self, *args, **options):
        start = _parse_dt('start', options['start'])
        end = _parse_dt('end', options['end']) if options['end'] else None
        if end is not None and end <= start:
            raise CommandError('--end must be after --start.')

        mailboxes = None
        if options['mailboxes']:
            mailboxes = [m.strip() for m in options['mailboxes'].split(',') if m.strip()]
            unknown = [m for m in mailboxes if m not in MAIL_FOLDERS]
            if unknown:
                raise CommandError(
                    f"Unknown mailbox(es): {', '.join(unknown)}. "
                    f"Valid: {', '.join(MAIL_FOLDERS)}")

        dry_run = options['dry_run']
        window = f"{start.isoformat()} .. {end.isoformat() if end else 'now'}"
        mode = 'DRY RUN' if dry_run else 'LIVE'
        scope = ', '.join(mailboxes) if mailboxes else f'all ({len(MAIL_FOLDERS)})'
        self.stdout.write(f"[{mode}] Backfilling emails for {window}")
        self.stdout.write(f"Mailboxes: {scope}")

        summary = asyncio.run(
            Sorting().backfill_emails_between(start, end, mailboxes, dry_run))

        self.stdout.write('')
        self.stdout.write('Per-folder fetched counts:')
        for row in summary['per_folder']:
            flag = f"  ERROR: {row['error']}" if row['error'] else ''
            self.stdout.write(
                f"  {row['user_email']:<34} {row['folder']:<12} "
                f"{row['count']:>6}{flag}")

        self.stdout.write('')
        self.stdout.write(f"Total fetched : {summary['fetched']}")
        if dry_run:
            self.stdout.write(self.style.WARNING(
                "Dry run — nothing written. Re-run without --dry-run to store."))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"Stored (new)  : {summary['added']}"))
            skipped = summary['processed'] - summary['added']
            self.stdout.write(
                f"Processed     : {summary['processed']} "
                f"({skipped} skipped as duplicates/filtered)")

        if summary['failed_folders']:
            self.stdout.write('')
            self.stdout.write(self.style.ERROR(
                f"{len(summary['failed_folders'])} folder(s) failed to fetch:"))
            for f in summary['failed_folders']:
                self.stdout.write(self.style.ERROR(f"  {f}"))
            self.stdout.write(self.style.ERROR(
                "Re-run the backfill for the same window to retry (safe; de-duped)."))
