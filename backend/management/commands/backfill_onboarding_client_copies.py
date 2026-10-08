"""Backfill the SharePoint item ids of client-uploaded onboarding documents onto
matters that were converted before client-copy capture existed, so the matter
home page's Client Care section can link the client copies without a live portal
call.

For each onboarding member it fetches the portal submission and stores the item
id of every provided document onto (or into a new) OnboardingItem row — exactly
what conversion now does automatically. Safe to re-run: it only fills ids that
are missing and never overwrites. A no-op in mock mode (the mock returns no file
ids) since there are no real client files to link.

    python manage.py backfill_onboarding_client_copies          # converted groups
    python manage.py backfill_onboarding_client_copies --all     # every group
"""
from django.core.management.base import BaseCommand

from backend import onboarding_portal as portal
from backend.models import Onboarding, OnboardingGroup
from backend.onboarding_views import _snapshot_portal_documents


class Command(BaseCommand):
    help = ("Store client-document SharePoint ids on already-onboarded members so "
            "Client Care can link the client copies on the matter home page.")

    def add_arguments(self, parser):
        parser.add_argument(
            '--all', action='store_true',
            help='Include onboarding groups that are not yet converted, too.')

    def handle(self, *args, **options):
        if portal.is_mock():
            self.stdout.write(self.style.WARNING(
                'Onboarding portal is in mock mode (ONBOARDING_PORTAL_BASE_URL '
                'unset) — there are no real client files to link. Nothing to do.'))
            return

        groups = OnboardingGroup.objects.all()
        if not options['all']:
            groups = groups.filter(status=OnboardingGroup.STATUS_CONVERTED)
        members = Onboarding.objects.filter(group__in=groups)

        total = members.count()
        updated = 0
        failed = 0
        for member in members:
            try:
                submission = portal.get_submission(member)
            except portal.PortalError as exc:
                failed += 1
                self.stderr.write(f'  ! {member.client_ref}: portal error: {exc}')
                continue
            before = set(member.items.exclude(sharepoint_item_id='')
                         .values_list('item_type', flat=True))
            _snapshot_portal_documents(member, submission)
            added = set(member.items.exclude(sharepoint_item_id='')
                        .values_list('item_type', flat=True)) - before
            if added:
                updated += 1
                self.stdout.write(
                    f'  ✓ {member.client_ref}: stored {len(added)} client '
                    f'copy id(s) ({", ".join(sorted(added))})')

        self.stdout.write(self.style.SUCCESS(
            f'Backfill complete: {updated}/{total} member(s) updated, '
            f'{failed} portal error(s).'))
