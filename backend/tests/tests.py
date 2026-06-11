import shutil
import tempfile
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PyPDF2 import PdfReader
from reportlab.pdfgen import canvas

from users.models import CustomUser
from ..models import Bundle, BundleDocument, BundleSection
from ..views import _generate_bundle_pdf


def bundle_pdf_bytes(pdf_result):
    """Normalise fast-path dict or legacy bytes from _generate_bundle_pdf."""
    if isinstance(pdf_result, dict):
        if pdf_result.get('path'):
            import shutil
            try:
                with open(pdf_result['path'], 'rb') as pdf_file:
                    return pdf_file.read()
            finally:
                work_dir = pdf_result.get('work_dir')
                if work_dir:
                    shutil.rmtree(work_dir, ignore_errors=True)
        return pdf_result['bytes']
    return pdf_result


def make_pdf(filename, text):
    buffer = BytesIO()
    pdf_canvas = canvas.Canvas(buffer)
    pdf_canvas.drawString(72, 720, text)
    pdf_canvas.showPage()
    pdf_canvas.save()
    return SimpleUploadedFile(
        filename,
        buffer.getvalue(),
        content_type='application/pdf',
    )


def make_pdf_with_blank_page(filename):
    buffer = BytesIO()
    pdf_canvas = canvas.Canvas(buffer)
    pdf_canvas.drawString(72, 720, 'First page')
    pdf_canvas.showPage()
    pdf_canvas.showPage()
    pdf_canvas.drawString(72, 720, 'Third page')
    pdf_canvas.showPage()
    pdf_canvas.save()
    return SimpleUploadedFile(
        filename,
        buffer.getvalue(),
        content_type='application/pdf',
    )


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class BundleTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        media_root = cls._overridden_settings['MEDIA_ROOT']
        super().tearDownClass()
        shutil.rmtree(media_root, ignore_errors=True)

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username='abc',
            email='abc@example.com',
            first_name='A',
            last_name='User',
            password='password',
            max_holidays_in_year=20,
        )
        self.client.force_login(self.user)
        self.bundle = Bundle.objects.create(name='Test Bundle', created_by=self.user)

    def test_section_reorder_handles_unique_order_constraint(self):
        first = BundleSection.objects.create(bundle=self.bundle, heading='First', order=1)
        second = BundleSection.objects.create(bundle=self.bundle, heading='Second', order=2)

        response = self.client.post(
            reverse('bundle_section_reorder', args=[self.bundle.id]),
            {'section_orders[]': [second.id, first.id]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(self.bundle.sections.order_by('order')), [second, first])

    def test_section_update_changes_heading(self):
        section = BundleSection.objects.create(bundle=self.bundle, heading='Old heading', order=1)

        response = self.client.post(
            reverse('bundle_section_update', args=[section.id]),
            {'heading': 'Updated heading'},
        )

        self.assertEqual(response.status_code, 200)
        section.refresh_from_db()
        self.assertEqual(section.heading, 'Updated heading')

    def test_section_update_changes_date_sort(self):
        section = BundleSection.objects.create(
            bundle=self.bundle,
            heading='Section',
            order=1,
            date_sort=BundleSection.DATE_SORT_MANUAL,
        )
        newer = BundleDocument.objects.create(
            section=section,
            file=make_pdf('newer.pdf', 'Newer'),
            description='Newer',
            date='2024-03-01',
            order=1,
        )
        older = BundleDocument.objects.create(
            section=section,
            file=make_pdf('older.pdf', 'Older'),
            description='Older',
            date='2024-01-01',
            order=2,
        )

        response = self.client.post(
            reverse('bundle_section_update', args=[section.id]),
            {'date_sort': BundleSection.DATE_SORT_ASC},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['section']['document_ids'], [older.id, newer.id])
        section.refresh_from_db()
        self.assertEqual(section.date_sort, BundleSection.DATE_SORT_ASC)

    def test_document_reorder_handles_unique_order_constraint(self):
        section = BundleSection.objects.create(bundle=self.bundle, heading='Section', order=1)
        first = BundleDocument.objects.create(
            section=section,
            file=make_pdf('first.pdf', 'First'),
            description='First',
            order=1,
        )
        second = BundleDocument.objects.create(
            section=section,
            file=make_pdf('second.pdf', 'Second'),
            description='Second',
            order=2,
        )

        response = self.client.post(
            reverse('bundle_document_reorder', args=[section.id]),
            {'document_orders[]': [second.id, first.id]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(section.documents.order_by('order')), [second, first])

    def test_section_ordered_documents_by_date_asc(self):
        section = BundleSection.objects.create(
            bundle=self.bundle,
            heading='Section',
            order=1,
            date_sort=BundleSection.DATE_SORT_ASC,
        )
        newer = BundleDocument.objects.create(
            section=section,
            file=make_pdf('newer.pdf', 'Newer'),
            description='Newer',
            date='2024-03-01',
            order=2,
        )
        older = BundleDocument.objects.create(
            section=section,
            file=make_pdf('older.pdf', 'Older'),
            description='Older',
            date='2024-01-01',
            order=1,
        )

        self.assertEqual(section.ordered_documents(), [older, newer])

    def test_section_ordered_documents_by_date_desc(self):
        section = BundleSection.objects.create(
            bundle=self.bundle,
            heading='Section',
            order=1,
            date_sort=BundleSection.DATE_SORT_DESC,
        )
        newer = BundleDocument.objects.create(
            section=section,
            file=make_pdf('newer.pdf', 'Newer'),
            description='Newer',
            date='2024-03-01',
            order=1,
        )
        older = BundleDocument.objects.create(
            section=section,
            file=make_pdf('older.pdf', 'Older'),
            description='Older',
            date='2024-01-01',
            order=2,
        )

        self.assertEqual(section.ordered_documents(), [newer, older])

    def test_generate_bundle_pdf_uses_section_date_sort(self):
        section = BundleSection.objects.create(
            bundle=self.bundle,
            heading='Section',
            order=1,
            date_sort=BundleSection.DATE_SORT_ASC,
        )
        BundleDocument.objects.create(
            section=section,
            file=make_pdf('newer.pdf', 'Newer page'),
            description='Newer',
            date='2024-03-01',
            order=1,
        )
        BundleDocument.objects.create(
            section=section,
            file=make_pdf('older.pdf', 'Older page'),
            description='Older',
            date='2024-01-01',
            order=2,
        )

        pdf_content = bundle_pdf_bytes(_generate_bundle_pdf(self.bundle))
        reader = PdfReader(BytesIO(pdf_content))

        self.assertEqual(len(reader.pages), 3)
        self.assertIn('Older page', reader.pages[1].extract_text())
        self.assertIn('Newer page', reader.pages[2].extract_text())

    def test_document_file_serves_uploaded_pdf(self):
        section = BundleSection.objects.create(bundle=self.bundle, heading='Section', order=1)
        document = BundleDocument.objects.create(
            section=section,
            file=make_pdf('preview.pdf', 'Preview text'),
            description='Preview document',
            order=1,
        )

        response = self.client.get(reverse('bundle_document_file', args=[document.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(b''.join(response.streaming_content).startswith(b'%PDF'))

    def test_document_update_changes_description(self):
        section = BundleSection.objects.create(bundle=self.bundle, heading='Section', order=1)
        document = BundleDocument.objects.create(
            section=section,
            file=make_pdf('doc.pdf', 'Content'),
            description='Old name',
            order=1,
        )

        response = self.client.post(
            reverse('bundle_document_update', args=[document.id]),
            {'description': 'New name', 'date': ''},
        )

        self.assertEqual(response.status_code, 200)
        document.refresh_from_db()
        self.assertEqual(document.description, 'New name')
        self.assertIsNone(document.date)

    def test_document_update_changes_date(self):
        section = BundleSection.objects.create(bundle=self.bundle, heading='Section', order=1)
        document = BundleDocument.objects.create(
            section=section,
            file=make_pdf('doc.pdf', 'Content'),
            description='Document',
            order=1,
        )

        response = self.client.post(
            reverse('bundle_document_update', args=[document.id]),
            {'description': 'Document', 'date': '2024-03-15'},
        )

        self.assertEqual(response.status_code, 200)
        document.refresh_from_db()
        self.assertEqual(document.date.isoformat(), '2024-03-15')

    def test_bundle_update_changes_name(self):
        response = self.client.post(
            reverse('bundle_update', args=[self.bundle.id]),
            {'bundle_name': 'Renamed bundle'},
        )

        self.assertEqual(response.status_code, 200)
        self.bundle.refresh_from_db()
        self.assertEqual(self.bundle.name, 'Renamed bundle')

    def test_document_pages_update_saves_manual_page_order(self):
        section = BundleSection.objects.create(bundle=self.bundle, heading='Section', order=1)
        document = BundleDocument.objects.create(
            section=section,
            file=make_pdf_with_blank_page('with_blank.pdf'),
            description='Document with blank page',
            order=1,
        )

        response = self.client.post(
            reverse('bundle_document_pages_update', args=[document.id]),
            {'page_order[]': [3, 1]},
        )

        self.assertEqual(response.status_code, 200)
        document.refresh_from_db()
        self.assertEqual(document.page_order, [3, 1])

    def test_document_pages_get_returns_page_metadata(self):
        section = BundleSection.objects.create(bundle=self.bundle, heading='Section', order=1)
        document = BundleDocument.objects.create(
            section=section,
            file=make_pdf_with_blank_page('with_blank.pdf'),
            description='Document with blank page',
            order=1,
        )

        response = self.client.get(reverse('bundle_document_pages_update', args=[document.id]))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['page_count'], 3)
        self.assertEqual(len(payload['page_choices']), 3)
        self.assertEqual(payload['page_summary'], 'All 3 pages')

    def test_generate_bundle_pdf_updates_document_page_ranges(self):
        section = BundleSection.objects.create(bundle=self.bundle, heading='Section', order=1)
        first = BundleDocument.objects.create(
            section=section,
            file=make_pdf('first.pdf', 'First'),
            description='First',
            order=1,
        )
        second = BundleDocument.objects.create(
            section=section,
            file=make_pdf('second.pdf', 'Second'),
            description='Second',
            order=2,
        )

        pdf_content = bundle_pdf_bytes(_generate_bundle_pdf(self.bundle))

        self.assertEqual(len(PdfReader(BytesIO(pdf_content)).pages), 3)
        index_page = PdfReader(BytesIO(pdf_content)).pages[0]
        self.assertTrue(index_page.get('/Annots'))
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((first.page_start, first.page_end), (2, 2))
        self.assertEqual((second.page_start, second.page_end), (3, 3))

    def test_generate_bundle_pdf_includes_outline_bookmarks(self):
        section = BundleSection.objects.create(bundle=self.bundle, heading='Letters', order=1)
        first = BundleDocument.objects.create(
            section=section,
            file=make_pdf('first.pdf', 'First'),
            description='First document',
            order=1,
        )
        second = BundleDocument.objects.create(
            section=section,
            file=make_pdf('second.pdf', 'Second'),
            description='Second document',
            order=2,
        )

        pdf_content = bundle_pdf_bytes(_generate_bundle_pdf(self.bundle))
        reader = PdfReader(BytesIO(pdf_content))

        def collect_outline_titles(outline):
            titles = []
            for item in outline:
                if isinstance(item, list):
                    titles.extend(collect_outline_titles(item))
                else:
                    titles.append(item.title)
            return titles

        outline_titles = collect_outline_titles(reader.outline)
        self.assertIn('Index', outline_titles)
        self.assertNotIn('Bundle', outline_titles)
        self.assertTrue(any(title.startswith('Letters (p.') for title in outline_titles))
        self.assertTrue(any(title.startswith('1. First document (p.') for title in outline_titles))
        self.assertTrue(any(title.startswith('2. Second document (p.') for title in outline_titles))

    def test_generate_bundle_pdf_omits_date_column_when_no_document_dates(self):
        section = BundleSection.objects.create(bundle=self.bundle, heading='Pleadings', order=1)
        BundleDocument.objects.create(
            section=section,
            file=make_pdf('claim.pdf', 'Claim'),
            description='Particulars of claim',
            order=1,
        )

        index_text = PdfReader(BytesIO(bundle_pdf_bytes(_generate_bundle_pdf(self.bundle)))).pages[0].extract_text()

        self.assertNotIn('Date', index_text)
        self.assertIn('Description', index_text)
        self.assertIn('Page', index_text)

    def test_generate_bundle_pdf_includes_date_column_when_any_document_has_date(self):
        section = BundleSection.objects.create(bundle=self.bundle, heading='Evidence', order=1)
        BundleDocument.objects.create(
            section=section,
            file=make_pdf('report.pdf', 'Report'),
            description='Medical report',
            date='2024-06-01',
            order=1,
        )
        BundleDocument.objects.create(
            section=section,
            file=make_pdf('photo.pdf', 'Photo'),
            description='Photograph',
            order=2,
        )

        index_text = PdfReader(BytesIO(bundle_pdf_bytes(_generate_bundle_pdf(self.bundle)))).pages[0].extract_text()

        self.assertIn('Date', index_text)
        self.assertIn('01/06/2024', index_text)

    def test_generate_bundle_pdf_uses_court_heading_when_enabled(self):
        self.bundle.is_court_bundle = True
        self.bundle.court_name = 'County Court at Southend'
        self.bundle.case_number = '12338123223'
        self.bundle.case_number_type = Bundle.CASE_NUMBER_CLAIM
        self.bundle.index_title = 'Index to the Bundle'
        self.bundle.hearing_line = 'for hearing on 15 June 2026 at 10:00 am'
        self.bundle.court_parties = [
            {'side': 'claimant', 'name': 'Party A', 'role': 'Claimant 1'},
            {'side': 'defendant', 'name': 'Party B', 'role': 'Defendant 1'},
        ]
        self.bundle.save()

        section = BundleSection.objects.create(bundle=self.bundle, heading='Pleadings', order=1)
        BundleDocument.objects.create(
            section=section,
            file=make_pdf('claim.pdf', 'Claim'),
            description='Particulars of claim',
            order=1,
        )

        index_text = PdfReader(BytesIO(bundle_pdf_bytes(_generate_bundle_pdf(self.bundle)))).pages[0].extract_text()

        self.assertIn('COUNTY COURT AT SOUTHEND', index_text)
        self.assertIn('CLAIM NO. 12338123223', index_text)
        self.assertIn('PARTY A', index_text)
        self.assertIn('CLAIMANT 1', index_text)
        self.assertIn('-V-', index_text)
        self.assertIn('PARTY B', index_text)
        self.assertIn('DEFENDANT 1', index_text)
        self.assertIn('INDEX TO THE BUNDLE', index_text)
        self.assertIn('FOR HEARING ON 15 JUNE 2026 AT 10:00 AM', index_text)
        self.assertNotIn('File:', index_text)

    def test_generate_bundle_pdf_uses_centered_standard_index_header(self):
        self.bundle.name = 'Witness Statement Bundle'
        self.bundle.save()

        section = BundleSection.objects.create(bundle=self.bundle, heading='Evidence', order=1)
        BundleDocument.objects.create(
            section=section,
            file=make_pdf('statement.pdf', 'Statement'),
            description='Witness statement',
            order=1,
        )

        index_text = PdfReader(BytesIO(bundle_pdf_bytes(_generate_bundle_pdf(self.bundle)))).pages[0].extract_text()

        self.assertIn('Witness Statement Bundle', index_text)
        self.assertIn('Index', index_text)
        self.assertNotIn('COUNTY COURT', index_text)

    def test_generate_bundle_pdf_wraps_long_index_descriptions(self):
        section = BundleSection.objects.create(bundle=self.bundle, heading='Section', order=1)
        long_description = (
            'Witness statement of John Smith regarding the incident on 12 March 2024 '
            'and subsequent correspondence with the defendant'
        )
        BundleDocument.objects.create(
            section=section,
            file=make_pdf('long-desc.pdf', 'Long description document'),
            description=long_description,
            order=1,
        )

        index_text = PdfReader(BytesIO(bundle_pdf_bytes(_generate_bundle_pdf(self.bundle)))).pages[0].extract_text()

        self.assertNotIn('...', index_text)
        self.assertIn('Witness statement of John Smith', index_text)
        self.assertIn('subsequent correspondence with the defendant', index_text)

    def test_generate_bundle_pdf_preserves_all_source_pages_by_default(self):
        section = BundleSection.objects.create(bundle=self.bundle, heading='Section', order=1)
        document = BundleDocument.objects.create(
            section=section,
            file=make_pdf_with_blank_page('with_blank.pdf'),
            description='Document with blank page',
            order=1,
        )

        pdf_content = bundle_pdf_bytes(_generate_bundle_pdf(self.bundle))

        self.assertEqual(len(PdfReader(BytesIO(pdf_content)).pages), 4)
        document.refresh_from_db()
        self.assertEqual((document.page_start, document.page_end), (2, 4))

    def test_generate_bundle_pdf_uses_manual_page_order(self):
        section = BundleSection.objects.create(bundle=self.bundle, heading='Section', order=1)
        document = BundleDocument.objects.create(
            section=section,
            file=make_pdf_with_blank_page('with_blank.pdf'),
            description='Document with blank page',
            order=1,
            page_order=[3, 1],
        )

        pdf_content = bundle_pdf_bytes(_generate_bundle_pdf(self.bundle))
        reader = PdfReader(BytesIO(pdf_content))

        self.assertEqual(len(reader.pages), 3)
        self.assertIn('Third page', reader.pages[1].extract_text())
        self.assertIn('First page', reader.pages[2].extract_text())
        document.refresh_from_db()
        self.assertEqual((document.page_start, document.page_end), (2, 3))


class FinanceActivityLedgerDeltaTests(TestCase):
    def test_invoice_affects_office_only(self):
        from decimal import Decimal
        from unittest.mock import MagicMock

        from ..views import _finance_activity_ledger_deltas

        invoice = {'total_cost_and_vat': Decimal('120.00')}
        client_delta, office_delta = _finance_activity_ledger_deltas(
            'invoice', 'CV0001', invoice=invoice)
        self.assertEqual(client_delta, Decimal('0'))
        self.assertEqual(office_delta, Decimal('-120.00'))

    def test_client_slip_affects_client_ledger_only(self):
        from decimal import Decimal
        from unittest.mock import MagicMock

        from ..views import _finance_activity_ledger_deltas

        slip = MagicMock()
        slip.ledger_account = 'C'
        slip.is_money_out = False
        slip.amount = Decimal('50.00')
        client_delta, office_delta = _finance_activity_ledger_deltas(
            'pmts_slip', 'CV0001', pmts_slip=slip)
        self.assertEqual(client_delta, Decimal('50.00'))
        self.assertEqual(office_delta, Decimal('0'))

    def test_same_file_client_to_office_transfer(self):
        from decimal import Decimal
        from unittest.mock import MagicMock

        from ..views import _finance_activity_ledger_deltas

        slip = MagicMock()
        slip.file_number_from.file_number = 'CV0001'
        slip.file_number_to.file_number = 'CV0001'
        slip.amount = Decimal('100.00')
        client_delta, office_delta = _finance_activity_ledger_deltas(
            'green_slip', 'CV0001', green_slip=slip)
        self.assertEqual(client_delta, Decimal('-100.00'))
        self.assertEqual(office_delta, Decimal('100.00'))


class FinanceActivitySortTests(TestCase):
    def test_same_date_items_sort_by_kind_order_then_id(self):
        from datetime import date

        from ..views import FINANCE_KIND_SORT_ORDER, _finance_activity_sort_key

        shared_date = date(2024, 6, 15)

        items = [
            {
                'kind': 'invoice',
                'sort_date': shared_date,
                'sort_kind_order': FINANCE_KIND_SORT_ORDER['invoice'],
                'sort_id': 5,
            },
            {
                'kind': 'pmts_slip',
                'sort_date': shared_date,
                'sort_kind_order': FINANCE_KIND_SORT_ORDER['pmts_slip'],
                'sort_id': 10,
            },
            {
                'kind': 'green_slip',
                'sort_date': shared_date,
                'sort_kind_order': FINANCE_KIND_SORT_ORDER['green_slip'],
                'sort_id': 3,
            },
        ]

        sorted_items = sorted(items, key=_finance_activity_sort_key)

        self.assertEqual([item['sort_id'] for item in sorted_items], [10, 3, 5])
