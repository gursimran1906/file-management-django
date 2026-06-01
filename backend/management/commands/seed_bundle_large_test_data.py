import os
import time
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from backend.models import Bundle, BundleDocument, BundleSection


def build_multipage_pdf_bytes(pages, label):
    """Build a multi-page PDF with minimal content (fast for large page counts)."""
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    for page_num in range(1, pages + 1):
        pdf.drawString(72, 800, f'{label} — page {page_num} of {pages}')
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()


class Command(BaseCommand):
    help = (
        'Create a local bundle with many pages for PDF generation benchmarking. '
        'Use --generate to run the merge immediately and print timings.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--pages',
            type=int,
            default=1000,
            help='Total pages across all documents (default: 1000).',
        )
        parser.add_argument(
            '--documents',
            type=int,
            default=10,
            help='Number of source PDFs to create (default: 10).',
        )
        parser.add_argument(
            '--sections',
            type=int,
            default=2,
            help='Number of bundle sections (default: 2).',
        )
        parser.add_argument(
            '--username',
            default='abc',
            help='Username for created_by (default: abc). Creates user if missing.',
        )
        parser.add_argument(
            '--name',
            default='Large test bundle',
            help='Bundle name (default: Large test bundle).',
        )
        parser.add_argument(
            '--generate',
            action='store_true',
            help='Run PDF generation after seeding and print stage timings.',
        )
        parser.add_argument(
            '--delete-existing',
            action='store_true',
            help='Delete an existing bundle with the same name before seeding.',
        )
        parser.add_argument(
            '--bundle-id',
            type=int,
            default=None,
            help='Skip seeding; generate PDF for an existing bundle id.',
        )

    def handle(self, *args, **options):
        if options['bundle_id']:
            bundle = Bundle.objects.get(pk=options['bundle_id'])
            total_pages = sum(
                doc.page_count or 0
                for section in bundle.sections.all()
                for doc in section.documents.all()
            ) or options['pages']
            self.stdout.write(f'Using existing bundle id={bundle.id} ({total_pages} pages est.)')
            if options['generate']:
                self._run_generation(bundle, total_pages)
            return

        total_pages = options['pages']
        doc_count = options['documents']
        section_count = max(1, options['sections'])

        if total_pages < 1:
            self.stderr.write(self.style.ERROR('--pages must be at least 1'))
            return
        if doc_count < 1:
            self.stderr.write(self.style.ERROR('--documents must be at least 1'))
            return
        if total_pages < doc_count:
            self.stderr.write(self.style.ERROR('--pages must be >= --documents'))
            return

        User = get_user_model()
        user = User.objects.filter(username=options['username']).first()
        if user is None:
            user = User.objects.order_by('id').first()
        if user is None:
            self.stderr.write(
                self.style.ERROR(
                    'No users in database. Create a user first or fix the users sequence.'
                )
            )
            return
        user_created = user.username == options['username']

        if options['delete_existing']:
            deleted, _ = Bundle.objects.filter(name=options['name']).delete()
            if deleted:
                self.stdout.write(f'Deleted existing bundle "{options["name"]}".')

        base_pages, remainder = divmod(total_pages, doc_count)
        pages_per_doc = [
            base_pages + (1 if i < remainder else 0) for i in range(doc_count)
        ]

        self.stdout.write(
            f'Creating bundle "{options["name"]}" with {total_pages} pages '
            f'across {doc_count} documents in {section_count} section(s)...'
        )

        t0 = time.perf_counter()
        bundle = Bundle.objects.create(
            name=options['name'],
            created_by=user,
        )

        docs_per_section = (doc_count + section_count - 1) // section_count
        doc_index = 0
        for section_idx in range(section_count):
            section = BundleSection.objects.create(
                bundle=bundle,
                heading=f'Section {section_idx + 1}',
                order=section_idx + 1,
            )
            section_doc_count = min(docs_per_section, doc_count - doc_index)
            for order in range(1, section_doc_count + 1):
                page_count = pages_per_doc[doc_index]
                label = f'Document {doc_index + 1}'
                pdf_bytes = build_multipage_pdf_bytes(page_count, label)
                document = BundleDocument(
                    section=section,
                    description=f'{label} ({page_count} pages)',
                    order=order,
                )
                document.file.save(
                    f'large_test_doc_{doc_index + 1}.pdf',
                    ContentFile(pdf_bytes),
                    save=False,
                )
                document.save()
                doc_index += 1
                self.stdout.write(f'  {label}: {page_count} pages saved')

        seed_seconds = time.perf_counter() - t0
        self.stdout.write(
            self.style.SUCCESS(
                f'Seeded bundle id={bundle.id} in {seed_seconds:.1f}s '
                f'({total_pages} pages, user={user.username}).'
            )
        )

        if options['generate']:
            self._run_generation(bundle, total_pages)

    def _run_generation(self, bundle, total_pages):
        from backend.views import _ensure_bundle_final_pdf

        self.stdout.write('')
        self.stdout.write(
            f'Generating PDF for bundle {bundle.id} ({total_pages} pages)...'
        )

        def progress(percent, message):
            if percent in (5, 15, 20, 88, 92, 95, 100):
                self.stdout.write(f'  [{percent:3d}%] {message}')

        t0 = time.perf_counter()
        success, error, regenerated = _ensure_bundle_final_pdf(
            bundle,
            progress_callback=progress,
        )
        elapsed = time.perf_counter() - t0

        bundle.refresh_from_db()
        if not success:
            self.stderr.write(self.style.ERROR(f'Generation failed: {error}'))
            return

        output_path = None
        output_size_mb = 0
        if bundle.final_pdf:
            try:
                output_path = bundle.final_pdf.path
                output_size_mb = os.path.getsize(output_path) / (1024 * 1024)
            except Exception:
                if bundle.final_pdf.size:
                    output_size_mb = bundle.final_pdf.size / (1024 * 1024)

        self.stdout.write('')
        self.stdout.write(
            self.style.SUCCESS(
                f'PDF generated in {elapsed:.1f}s '
                f'({elapsed / max(total_pages, 1) * 1000:.0f} ms/page)'
            )
        )
        if output_path:
            self.stdout.write(f'Output: {output_path} ({output_size_mb:.1f} MB)')
        self.stdout.write(f'pdf_is_current: {bundle.pdf_is_current()}')
        self.stdout.write(f'regenerated: {regenerated}')
