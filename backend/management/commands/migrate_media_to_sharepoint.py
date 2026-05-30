import os
import re
from collections import defaultdict

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand

from backend.models import Bundle, BundleDocument, Undertaking
from backend.sharepoint.paths import (
    bundle_document_upload_path,
    bundle_final_pdf_upload_path,
    LEGACY_PATH_PREFIXES,
)
from users.models import UserDocument

UUID_FILE_PREFIX = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}_',
    re.I,
)


class Command(BaseCommand):
    help = (
        'Upload existing local media files to SharePoint and update DB paths. '
        'Use --audit to inspect undertaking files without uploading.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report actions without uploading or updating the database.',
        )
        parser.add_argument(
            '--skip-existing',
            action='store_true',
            help='Skip files that already exist in SharePoint storage.',
        )
        parser.add_argument(
            '--only',
            choices=('undertakings', 'staff', 'bundles', 'all'),
            default='all',
            help='Limit migration to one category (default: all).',
        )
        parser.add_argument(
            '--audit',
            action='store_true',
            help='Print a readiness report and exit (implies --dry-run for undertakings when --only undertakings).',
        )
        parser.add_argument(
            '--local-media-root',
            help='Override MEDIA_ROOT when reading files from disk (e.g. rsync copy of server media).',
        )

    def handle(self, *args, **options):
        self.local_media_root = options.get('local_media_root') or settings.MEDIA_ROOT
        self.sp_folder_cache = {}
        only = options['only']
        audit = options['audit']
        dry_run = options['dry_run'] or audit

        if audit:
            if only != 'undertakings':
                self.stderr.write('--audit currently supports --only undertakings')
                return
            self._audit_undertakings()
            return

        if not settings.USE_SHAREPOINT:
            self.stderr.write(
                'USE_SHAREPOINT is false. Set USE_SHAREPOINT=true to upload to SharePoint.'
            )
            return

        stats = {'uploaded': 0, 'skipped': 0, 'missing': 0, 'updated': 0, 'errors': 0}

        if only in ('undertakings', 'all'):
            self.stdout.write('Migrating undertaking files...')
            for undertaking in Undertaking.objects.select_related('file_number').iterator():
                self._migrate_file_field(
                    undertaking,
                    'document_given_on',
                    stats,
                    dry_run,
                    options['skip_existing'],
                )
                self._migrate_file_field(
                    undertaking,
                    'discharged_proof',
                    stats,
                    dry_run,
                    options['skip_existing'],
                )

        if only in ('staff', 'all'):
            self.stdout.write('Migrating staff documents...')
            for user_document in UserDocument.objects.all().iterator():
                self._migrate_file_field(
                    user_document,
                    'document',
                    stats,
                    dry_run,
                    options['skip_existing'],
                )

        if only in ('bundles', 'all'):
            self.stdout.write('Migrating bundle source documents...')
            for document in BundleDocument.objects.select_related(
                'section__bundle__file_number'
            ).iterator():
                self._migrate_bundle_document(document, stats, dry_run, options['skip_existing'])

            self.stdout.write('Migrating final bundle PDFs...')
            for bundle in Bundle.objects.select_related('file_number').iterator():
                self._migrate_bundle_final(bundle, stats, dry_run, options['skip_existing'])

        self.stdout.write(self.style.SUCCESS(
            f"Done. uploaded={stats['uploaded']} skipped={stats['skipped']} "
            f"missing={stats['missing']} updated={stats['updated']} errors={stats['errors']}"
        ))

    def _local_path(self, name):
        return os.path.join(self.local_media_root, name)

    def _map_legacy_path(self, name):
        normalized = name.replace('\\', '/')
        for legacy_prefix, new_prefix in LEGACY_PATH_PREFIXES.items():
            if normalized.startswith(legacy_prefix):
                return new_prefix + normalized[len(legacy_prefix):]
        return normalized

    def _resolve_local_path(self, name):
        """Return disk path if the file exists, trying legacy prefix mapping."""
        if not name:
            return None, None

        candidates = [name.replace('\\', '/')]
        mapped = self._map_legacy_path(name)
        if mapped not in candidates:
            candidates.append(mapped)

        for candidate in candidates:
            path = self._local_path(candidate)
            if os.path.exists(path):
                return candidate, path

        return None, None

    def _read_local_bytes(self, name):
        resolved_name, path = self._resolve_local_path(name)
        if path:
            with open(path, 'rb') as handle:
                return handle.read()
        return None

    def _sharepoint_exists(self, name):
        if not name or not settings.USE_SHAREPOINT:
            return False
        try:
            target_name = self._map_legacy_path(name)
            return default_storage.exists(target_name)
        except Exception as exc:
            self.stderr.write(f'SharePoint check failed for {name}: {exc}')
            return False

    def _basename_key(self, name):
        return UUID_FILE_PREFIX.sub('', os.path.basename(name or '')).lower()

    def _sharepoint_folder_items(self, matter_code):
        if matter_code in self.sp_folder_cache:
            return self.sp_folder_cache[matter_code]

        if not settings.USE_SHAREPOINT:
            self.sp_folder_cache[matter_code] = []
            return []

        try:
            from backend.sharepoint.client import get_sharepoint_client
            folder_path = f'Undertakings/{matter_code}'
            items = get_sharepoint_client().list_children(folder_path)
            self.sp_folder_cache[matter_code] = items
            return items
        except Exception as exc:
            self.sp_folder_cache[matter_code] = None
            self.stderr.write(f'SharePoint folder list failed for {matter_code}: {exc}')
            return None

    def _find_sharepoint_match(self, db_path, matter_code):
        mapped_path = self._map_legacy_path(db_path)
        if self._sharepoint_exists(db_path):
            return 'exact_db_path', mapped_path

        folder_items = self._sharepoint_folder_items(matter_code)
        if not folder_items:
            return None, None

        target_name = os.path.basename(mapped_path)
        target_key = self._basename_key(target_name)
        basename_match = None

        for item in folder_items:
            if item.get('is_folder'):
                continue
            if item['name'] == target_name or item['path'] == mapped_path:
                return 'folder_exact_name', item['path']
            if self._basename_key(item['name']) == target_key:
                basename_match = item['path']

        if basename_match:
            return 'folder_same_basename', basename_match
        return None, None

    def _audit_undertakings(self):
        self.stdout.write('Undertaking media audit')
        self.stdout.write(f'  MEDIA_ROOT (settings): {settings.MEDIA_ROOT}')
        self.stdout.write(f'  Local read root:       {self.local_media_root}')
        self.stdout.write(f'  USE_SHAREPOINT:        {settings.USE_SHAREPOINT}')
        self.stdout.write('')

        undertakings = list(
            Undertaking.objects.select_related('file_number').order_by('file_number_id', 'id')
        )
        by_matter = defaultdict(list)
        path_refs = defaultdict(list)

        for undertaking in undertakings:
            matter_code = (
                undertaking.file_number.file_number
                if undertaking.file_number_id and undertaking.file_number
                else 'unassigned'
            )
            by_matter[matter_code].append(undertaking)
            for field_name in ('document_given_on', 'discharged_proof'):
                file_field = getattr(undertaking, field_name, None)
                if file_field and file_field.name:
                    path_refs[file_field.name].append((undertaking.id, field_name))

        if path_refs:
            shared_paths = {path: refs for path, refs in path_refs.items() if len(refs) > 1}
            if shared_paths:
                self.stdout.write(self.style.WARNING('DB paths referenced by multiple undertakings:'))
                for path, refs in shared_paths.items():
                    self.stdout.write(f'  {path} -> {refs}')
                self.stdout.write('')

        totals = {
            'records': len(undertakings),
            'fields_with_file': 0,
            'local_ok': 0,
            'local_missing': 0,
            'sharepoint_exact': 0,
            'sharepoint_folder_match': 0,
            'sharepoint_missing': 0,
            'ready_to_upload': 0,
            'db_path_mismatch_sp': 0,
        }

        for matter_code, matter_undertakings in sorted(by_matter.items()):
            undertaking_ids = [u.id for u in matter_undertakings]
            self.stdout.write(self.style.HTTP_INFO(
                f'=== Matter {matter_code} ({len(matter_undertakings)} undertaking'
                f'{"s" if len(matter_undertakings) != 1 else ""}: #{", #".join(map(str, undertaking_ids))}) ==='
            ))

            folder_items = self._sharepoint_folder_items(matter_code)
            if folder_items is None:
                self.stdout.write('  SharePoint folder: unavailable')
            elif not folder_items:
                self.stdout.write('  SharePoint folder: empty or missing')
            else:
                file_names = [item['name'] for item in folder_items if not item.get('is_folder')]
                self.stdout.write(f'  SharePoint folder: {len(file_names)} file(s)')
                for name in file_names:
                    self.stdout.write(f'    - {name}')

            for undertaking in matter_undertakings:
                for field_name in ('document_given_on', 'discharged_proof'):
                    file_field = getattr(undertaking, field_name, None)
                    if not file_field or not file_field.name:
                        continue

                    totals['fields_with_file'] += 1
                    db_path = file_field.name
                    mapped_path = self._map_legacy_path(db_path)
                    resolved_name, disk_path = self._resolve_local_path(db_path)
                    local_ok = disk_path is not None
                    match_type, sp_path = self._find_sharepoint_match(db_path, matter_code)

                    if local_ok:
                        totals['local_ok'] += 1
                    else:
                        totals['local_missing'] += 1

                    if match_type == 'exact_db_path':
                        totals['sharepoint_exact'] += 1
                        sp_status = self.style.SUCCESS(f'SharePoint OK ({match_type})')
                    elif match_type in ('folder_exact_name', 'folder_same_basename'):
                        totals['sharepoint_folder_match'] += 1
                        totals['db_path_mismatch_sp'] += 1
                        sp_status = self.style.WARNING(
                            f'SharePoint folder match ({match_type}): {sp_path}'
                        )
                    else:
                        totals['sharepoint_missing'] += 1
                        sp_status = self.style.ERROR('SharePoint missing')

                    if local_ok and not match_type:
                        totals['ready_to_upload'] += 1

                    local_status = self.style.SUCCESS('local OK') if local_ok else self.style.ERROR('local MISSING')
                    shared_note = ''
                    if len(path_refs.get(db_path, [])) > 1:
                        others = [
                            f'#{uid}:{field}'
                            for uid, field in path_refs[db_path]
                            if uid != undertaking.id or field != field_name
                        ]
                        shared_note = f'\n    shared db path with {", ".join(others)}'

                    self.stdout.write(
                        f'  #{undertaking.id} {field_name}\n'
                        f'    db:     {db_path}\n'
                        f'    mapped: {mapped_path}\n'
                        f'    disk:   {disk_path or "—"}\n'
                        f'    {local_status} | {sp_status}'
                        f'{shared_note}'
                    )

            self.stdout.write('')

        self.stdout.write(self.style.SUCCESS(
            'Summary: '
            f'{totals["records"]} undertakings, '
            f'{totals["fields_with_file"]} file fields, '
            f'{totals["local_ok"]} on disk, '
            f'{totals["local_missing"]} missing on disk, '
            f'{totals["sharepoint_exact"]} exact SharePoint path, '
            f'{totals["sharepoint_folder_match"]} folder match (db path differs), '
            f'{totals["sharepoint_missing"]} not in SharePoint, '
            f'{totals["ready_to_upload"]} ready to upload'
        ))
        if totals['db_path_mismatch_sp']:
            self.stdout.write(self.style.WARNING(
                'Some files exist in SharePoint under a different path than the DB record. '
                'Consider updating undertaking file paths to the matched SharePoint path.'
            ))
        if totals['ready_to_upload']:
            self.stdout.write(
                'Run: python manage.py migrate_media_to_sharepoint --only undertakings --dry-run'
            )
            self.stdout.write(
                'Then: python manage.py migrate_media_to_sharepoint --only undertakings --skip-existing'
            )

    def _matter_code_for(self, instance):
        file_number = getattr(instance, 'file_number', None)
        if getattr(instance, 'file_number_id', None) and file_number:
            return file_number.file_number
        return 'unassigned'

    def _sharepoint_already_has_file(self, db_path, matter_code):
        if self._sharepoint_exists(db_path):
            return True
        match_type, _ = self._find_sharepoint_match(db_path, matter_code)
        return bool(match_type)

    def _migrate_file_field(self, instance, field_name, stats, dry_run, skip_existing):
        file_field = getattr(instance, field_name, None)
        if not file_field or not file_field.name:
            return

        current_name = file_field.name
        target_name = self._map_legacy_path(current_name)

        matter_code = self._matter_code_for(instance) if isinstance(instance, Undertaking) else None
        if skip_existing:
            if default_storage.exists(target_name):
                stats['skipped'] += 1
                return
            if matter_code and self._sharepoint_already_has_file(current_name, matter_code):
                stats['skipped'] += 1
                self.stdout.write(
                    f'Skipping (already in SharePoint folder {matter_code}): {current_name}'
                )
                return

        content = self._read_local_bytes(current_name)
        if content is None:
            stats['missing'] += 1
            self.stdout.write(f'Missing local file: {current_name}')
            return

        if dry_run:
            resolved_name, disk_path = self._resolve_local_path(current_name)
            self.stdout.write(
                f'Would upload {current_name} -> {target_name}'
                + (f' (from {disk_path})' if disk_path else '')
            )
            stats['uploaded'] += 1
            return

        try:
            if default_storage.exists(target_name):
                default_storage.delete(target_name)
            saved_name = default_storage.save(
                target_name,
                ContentFile(content, name=os.path.basename(target_name)),
            )
            if saved_name != current_name:
                file_field.name = saved_name
                instance.save(update_fields=[field_name])
                stats['updated'] += 1
            stats['uploaded'] += 1
        except Exception as exc:
            stats['errors'] += 1
            self.stderr.write(f'Error uploading {current_name}: {exc}')

    def _migrate_bundle_document(self, document, stats, dry_run, skip_existing):
        if not document.file or not document.file.name:
            return

        target_name = bundle_document_upload_path(document, 'document.pdf')
        if skip_existing and default_storage.exists(target_name):
            stats['skipped'] += 1
            return

        content = self._read_local_bytes(document.file.name)
        if content is None:
            stats['missing'] += 1
            self.stdout.write(f'Missing local file: {document.file.name}')
            return

        if dry_run:
            self.stdout.write(f'Would upload bundle doc {document.id} -> {target_name}')
            stats['uploaded'] += 1
            return

        try:
            if default_storage.exists(target_name):
                default_storage.delete(target_name)
            saved_name = default_storage.save(
                target_name,
                ContentFile(content, name=os.path.basename(target_name)),
            )
            if document.file.name != saved_name:
                document.file.name = saved_name
                document.save(update_fields=['file'])
                stats['updated'] += 1
            stats['uploaded'] += 1
        except Exception as exc:
            stats['errors'] += 1
            self.stderr.write(f'Error uploading bundle document {document.id}: {exc}')

    def _migrate_bundle_final(self, bundle, stats, dry_run, skip_existing):
        if not bundle.final_pdf or not bundle.final_pdf.name:
            return

        target_name = bundle_final_pdf_upload_path(bundle, f'{bundle.uuid}.pdf')
        if skip_existing and default_storage.exists(target_name):
            stats['skipped'] += 1
            return

        content = self._read_local_bytes(bundle.final_pdf.name)
        if content is None:
            stats['missing'] += 1
            self.stdout.write(f'Missing local file: {bundle.final_pdf.name}')
            return

        if dry_run:
            self.stdout.write(f'Would upload bundle final {bundle.id} -> {target_name}')
            stats['uploaded'] += 1
            return

        try:
            if default_storage.exists(target_name):
                default_storage.delete(target_name)
            saved_name = default_storage.save(
                target_name,
                ContentFile(content, name=os.path.basename(target_name)),
            )
            if bundle.final_pdf.name != saved_name:
                bundle.final_pdf.name = saved_name
                bundle.save(update_fields=['final_pdf'])
                stats['updated'] += 1
            stats['uploaded'] += 1
        except Exception as exc:
            stats['errors'] += 1
            self.stderr.write(f'Error uploading bundle final {bundle.id}: {exc}')
