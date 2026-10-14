"""Save Microsoft 365 identifiers on MatterEmails rows written before the ingester stored them.

The correspondence export needs a row's Graph message id to fetch the original
message with its attachments. Rows are located in the mailbox by received time
(a two-second window) and web link, then the ids are written back. The export
does the same lazily for any row it meets, so this command is optional: it just
moves the cost out of the first export of each matter.

    python manage.py backfill_matter_email_ids --dry-run
    python manage.py backfill_matter_email_ids --limit 500
    python manage.py backfill_matter_email_ids --file-number ABC1234567
"""
from django.core.management.base import BaseCommand

from backend.correspondence_export.discovery import resolve_matter_email
from backend.correspondence_export.graph_mail import GraphMail, GraphMailError
from backend.correspondence_export.mailboxes import shared_mailboxes
from backend.models import MatterEmails


class Command(BaseCommand):
    help = 'Locate matter emails in Microsoft 365 and store their Graph ids on the rows.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=0, help='Stop after this many rows (0 = all).')
        parser.add_argument('--file-number', default='', help='Only rows filed under this matter.')
        parser.add_argument('--mailboxes', default='',
                            help='Comma-separated mailboxes to search (default: the shared department mailboxes).')
        parser.add_argument('--dry-run', action='store_true', help='Count the rows that need ids; change nothing.')

    def handle(self, *args, **options):
        rows = MatterEmails.objects.filter(graph_message_id='').exclude(link__isnull=True).exclude(link='')
        rows = rows.exclude(time__isnull=True).order_by('-time')
        if options['file_number']:
            rows = rows.filter(file_number__file_number=options['file_number'])
        total = rows.count()
        self.stdout.write(f'{total} row(s) without a Graph message id')
        if options['dry_run'] or not total:
            return
        if options['limit']:
            rows = rows[:options['limit']]
        mailboxes = [m.strip().lower() for m in options['mailboxes'].split(',') if m.strip()] \
            or [m['address'] for m in shared_mailboxes()]
        graph = GraphMail.from_settings()
        resolved = missing = errors = 0
        for index, row in enumerate(rows, 1):
            try:
                message, _mailbox, _folder = resolve_matter_email(graph, row, mailboxes)
            except GraphMailError as exc:
                errors += 1
                self.stderr.write(f'row {row.id}: Graph error {exc.code}')
                continue
            if message is None:
                missing += 1
            else:
                resolved += 1
            if index % 50 == 0:
                self.stdout.write(f'  {index} processed: {resolved} resolved, {missing} not found, {errors} errors')
        self.stdout.write(f'Done: {resolved} resolved, {missing} not found, {errors} errors')
