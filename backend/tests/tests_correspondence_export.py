"""Correspondence export: receipt classification, message parsing and memo rendering,
discovery of a matter's emails, the build runner on local storage, and the matter-page views."""
import io
import json
import shutil
import tempfile
import zipfile
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from email.message import EmailMessage
from unittest.mock import patch

import pikepdf
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from backend.correspondence_export import classify, discovery, mime, render, runner
from backend.correspondence_export.graph_mail import GraphMailError, parse_graph_dt
from backend.correspondence_export import mailboxes as mailbox_config
from backend.models import (ClientContactDetails, CorrespondenceExport, MatterEmails, MatterType,
                            Modifications, WIP)
from users.models import CustomUser

UTC = dt_timezone.utc
CLIENT = 'jane.doe@example.com'
FIRM_BOX = 'family@anpsolicitors.com'


# ----------------------------------------------------------------------------- fixtures

def make_user(username='FEX', email='fee.earner@anpsolicitors.com'):
    return CustomUser.objects.create_user(
        username=username, email=email, first_name='Fee', last_name='Earner',
        password='password', max_holidays_in_year=20, is_matter_fee_earner=True)


def make_client(name='Jane Doe', email=CLIENT):
    return ClientContactDetails.objects.create(
        name=name, occupation='Retired', address_line1='1 Test Street', address_line2='',
        county='Essex', postcode='SS7 1QT', email=email, contact_number='0123456789')


def make_matter(client, user, file_number='FAM0000001', matter_type='Family'):
    mt, _ = MatterType.objects.get_or_create(type=matter_type)
    return WIP.objects.create(file_number=file_number, client1=client, funding='PRI',
                              matter_type=mt, fee_earner=user)


def graph_message(mid, subject, received, from_addr, to_addrs, cc_addrs=(), folder='f-inbox',
                  msg_class='IPM.Note', has_attachments=False, internet_id=None, web_link=None,
                  from_name='', fuzzy=()):
    def entry(address):
        return {'emailAddress': {'name': '', 'address': address}}
    return {
        'id': mid,
        'internetMessageId': internet_id or f'<{mid}@example.com>',
        'subject': subject,
        'receivedDateTime': received,
        'sentDateTime': received,
        'hasAttachments': has_attachments,
        'from': {'emailAddress': {'name': from_name, 'address': from_addr}},
        'toRecipients': [entry(a) for a in to_addrs],
        'ccRecipients': [entry(a) for a in cc_addrs],
        'bccRecipients': [],
        'parentFolderId': folder,
        'isDraft': False,
        'webLink': web_link or f'https://outlook.office365.com/owa/?ItemID={mid}',
        'singleValueExtendedProperties': [{'id': 'String 0x1a', 'value': msg_class}],
        '_fuzzy': list(fuzzy),
    }


def mime_bytes(subject, from_addr, to_addr, html=None, text='Hello there', attachments=()):
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = from_addr
    msg['To'] = to_addr
    msg['Date'] = 'Tue, 04 Mar 2025 10:12:00 +0000'
    msg['Message-ID'] = f'<{abs(hash(subject))}@example.com>'
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype='html')
    for name, data, maintype, subtype in attachments:
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    return msg.as_bytes()


def sample_pdf():
    return render.Renderer().pdf('<html><body><p>Sample enclosure page.</p></body></html>')


class FakeGraph:
    """Enough of GraphMail for discovery and the runner: in-memory mailboxes."""

    def __init__(self):
        self.messages = {}
        self.mime = {}
        self.folders = {'f-inbox': 'Inbox', 'f-sent': 'Sent Items', 'f-deleted': 'Deleted Items',
                        'f-drafts': 'Drafts'}

    def add(self, mailbox, message, raw=None):
        self.messages.setdefault(mailbox, []).append(message)
        if raw is not None:
            self.mime[(mailbox, message['id'])] = raw

    def search_participant(self, mailbox, address, start, end):
        out = []
        for m in self.messages.get(mailbox, []):
            received = parse_graph_dt(m['receivedDateTime'])
            if not (start <= received < end):
                continue
            if discovery.participants_match(m, [address]) or address in m.get('_fuzzy', []):
                out.append(m)
        return out

    def search_kql(self, mailbox, kql, start, end):
        return [m for m in self.messages.get(mailbox, []) if kql.lower() in (m.get('subject') or '').lower()]

    def list_window(self, mailbox, start, end):
        return [m for m in self.messages.get(mailbox, [])
                if start <= parse_graph_dt(m['receivedDateTime']) <= end]

    def get_message(self, mailbox, message_id):
        for m in self.messages.get(mailbox, []):
            if m['id'] == message_id:
                return m
        raise GraphMailError(404, 'ErrorItemNotFound', 'not found')

    def get_mime(self, mailbox, message_id):
        return self.mime[(mailbox, message_id)]

    def folder_name(self, mailbox, folder_id):
        return self.folders.get(folder_id, 'Unknown folder')

    def user_display_name(self, mailbox):
        return 'Family'


def base_params(**overrides):
    params = {
        'addresses': [CLIENT], 'mailboxes': [FIRM_BOX], 'date_from': '2025-01-01', 'date_to': '2025-12-31',
        'names': ['Jane Doe', 'Jane', 'Doe'], 'matters': ['FAM0000001'], 'header_name': 'ANP Solicitors',
        'include_system_filed': True, 'append_pdf_enclosures': True, 'include_originals': True,
        'combined_pdf': False, 'matter_search': False, 'include_receipts': False,
    }
    params.update(overrides)
    return params


# ----------------------------------------------------------------------------- unit

class ClassifyTests(TestCase):
    def test_message_class_mapping(self):
        self.assertEqual(classify.classify_by_class('REPORT.IPM.Note.IPNRN'), classify.READ_RECEIPT)
        self.assertEqual(classify.classify_by_class('REPORT.IPM.Note.IPNNRN'), classify.NOT_READ)
        self.assertEqual(classify.classify_by_class('REPORT.IPM.Note.DR'), classify.DELIVERY_RECEIPT)
        self.assertEqual(classify.classify_by_class('REPORT.IPM.Note.NDR'), classify.NON_DELIVERY)
        self.assertIsNone(classify.classify_by_class('IPM.Note'))
        self.assertIsNone(classify.classify_by_class(''))
        self.assertTrue(classify.is_automatic_reply('IPM.Note.Rules.OofTemplate.Microsoft'))

    def test_mime_report_detection(self):
        receipt = (b'From: a@example.com\r\nTo: b@example.com\r\nSubject: Read: hi\r\nMIME-Version: 1.0\r\n'
                   b'Content-Type: multipart/report; report-type=disposition-notification; boundary="b"\r\n\r\n'
                   b'--b\r\nContent-Type: text/plain\r\n\r\nread\r\n--b\r\n'
                   b'Content-Type: message/disposition-notification\r\n\r\nDisposition: displayed\r\n--b--\r\n')
        self.assertEqual(classify.classify_by_mime(receipt), classify.READ_RECEIPT)
        bounce = (b'From: postmaster@example.com\r\nTo: b@example.com\r\nSubject: Undeliverable\r\nMIME-Version: 1.0\r\n'
                  b'Content-Type: multipart/report; report-type=delivery-status; boundary="b"\r\n\r\n'
                  b'--b\r\nContent-Type: text/plain\r\n\r\nfailed\r\n--b\r\n'
                  b'Content-Type: message/delivery-status\r\n\r\nAction: failed\r\nStatus: 5.1.1\r\n--b--\r\n')
        self.assertEqual(classify.classify_by_mime(bounce), classify.NON_DELIVERY)
        self.assertIsNone(classify.classify_by_mime(mime_bytes('plain', 'a@x.com', 'b@x.com')))

    def test_message_class_from_graph_property(self):
        self.assertEqual(classify.message_class({'singleValueExtendedProperties': [
            {'id': 'String 0x1a', 'value': 'REPORT.IPM.Note.DR'}]}), 'REPORT.IPM.Note.DR')
        self.assertEqual(classify.message_class({}), '')


class ParseAndRenderTests(TestCase):
    def test_parse_message_separates_inline_images_from_enclosures(self):
        png = (b'\x89PNG\r\n\x1a\n' + b'\x00' * 20)
        msg = EmailMessage()
        msg['Subject'] = 'Re: Sale'
        msg['From'] = 'Jane <jane@example.com>'
        msg['To'] = FIRM_BOX
        msg.set_content('plain alternative')
        msg.add_alternative('<html><body><p>Hi</p><img src="cid:logo1"></body></html>', subtype='html')
        msg.get_payload()[1].add_related(png, maintype='image', subtype='png', cid='<logo1>')
        msg.add_attachment(b'%PDF-1.4 fake', maintype='application', subtype='pdf', filename='contract.pdf')
        msg.add_attachment(b'a,b\n1,2\n', maintype='text', subtype='csv', filename='figures.csv')
        parsed = mime.parse_message(msg.as_bytes())
        self.assertIn('data:image/png;base64', parsed.html)
        self.assertEqual([e.name for e in parsed.enclosures], ['contract.pdf', 'figures.csv'])
        self.assertEqual(parsed.text.strip(), 'plain alternative')

    def test_duplicate_enclosure_names_are_made_unique(self):
        msg = EmailMessage()
        msg['Subject'] = 'x'
        msg.set_content('t')
        msg.add_attachment(b'1', maintype='text', subtype='plain', filename='note.txt')
        msg.add_attachment(b'2', maintype='text', subtype='plain', filename='note.txt')
        names = [e.name for e in mime.parse_message(msg.as_bytes()).enclosures]
        self.assertEqual(names, ['note.txt', 'note (2).txt'])

    def test_clean_email_html_removes_named_pages_scripts_and_web_fonts(self):
        html = ('<html><head><style>@font-face{font-family:X;src:url(http://x)} @page WordSection1 {margin:72pt} '
                'div.WordSection1 {page:WordSection1;} .sig{color:red}</style><script>alert(1)</script></head>'
                '<body><div class=WordSection1 style="page:WordSection1; color:blue"><p>Dear Sirs</p>'
                '<img src="https://tracker.example/pixel.png"><o:p></o:p></div></body></html>')
        styles, inner = render.clean_email_html(html)
        self.assertNotIn('@font-face', styles)
        self.assertNotIn('@page', styles)
        self.assertNotIn('page:', styles)
        self.assertIn('.sig{color:red}', styles)
        self.assertNotIn('page:WordSection1', inner)
        self.assertIn('color:blue', inner)
        self.assertNotIn('<script', inner)
        self.assertNotIn('<o:p>', inner)

    def test_memo_render_puts_body_on_page_one_and_appends_enclosures(self):
        renderer = render.Renderer()
        html = ('<html><head><style>@page WordSection1 {size:612pt 792pt} div.WordSection1 {page:WordSection1;}</style></head>'
                '<body><div class="WordSection1"><p>Please find the contract attached.</p></div></body></html>')
        styles, inner = render.clean_email_html(html)
        rows = [('From:', 'Jane Doe &lt;jane@example.com&gt;'), ('Sent:', '04 March 2025 10:12'),
                ('To:', FIRM_BOX), ('Cc:', ''), ('Subject:', 'Re: Sale'), ('Attachments:', 'contract.pdf')]
        email_pdf = renderer.pdf(render.memo_html('ANP Solicitors', '14 October 2026', rows, inner, styles))
        self.assertEqual(email_pdf[:4], b'%PDF')
        self.assertEqual(len(pikepdf.open(io.BytesIO(email_pdf)).pages), 1)
        enclosures = [mime.Enclosure('contract.pdf', sample_pdf(), 'application/pdf'),
                      mime.Enclosure('figures.csv', b'a,b', 'text/csv')]
        merged, flags = render.append_enclosures(renderer, email_pdf, enclosures, 'ANP Solicitors', '14 October 2026')
        self.assertEqual(flags, [])
        self.assertEqual(len(pikepdf.open(io.BytesIO(merged)).pages), 3)  # email + divider + enclosure
        self.assertTrue(enclosures[0].appended)
        self.assertFalse(enclosures[1].appended)
        self.assertEqual(enclosures[1].note, 'saved as file only')

    def test_encrypted_enclosure_is_kept_as_file_and_flagged(self):
        renderer = render.Renderer()
        pdf = pikepdf.open(io.BytesIO(sample_pdf()))
        buf = io.BytesIO()
        pdf.save(buf, encryption=pikepdf.Encryption(owner='o', user='u'))
        enclosures = [mime.Enclosure('secret.pdf', buf.getvalue(), 'application/pdf')]
        email_pdf = renderer.pdf('<html><body>x</body></html>')
        merged, flags = render.append_enclosures(renderer, email_pdf, enclosures, 'ANP', 'today')
        self.assertEqual(merged, email_pdf)
        self.assertIn('Enclosure not appended: secret.pdf', flags)
        self.assertIn('not appended', enclosures[0].note)

    def test_render_worker_survives_a_crash(self):
        worker = render.RenderWorker(timeout=60)
        worker.start()
        try:
            with self.assertRaises(render.RenderError):
                worker.render('__crash__')
            self.assertEqual(worker.render('<html><body>after</body></html>')[:4], b'%PDF')
            self.assertEqual(worker.crashes, 1)
        finally:
            worker.close()


class MailboxDefaultsTests(TestCase):
    def test_defaults_follow_matter_type_and_clients(self):
        user = make_user()
        client = make_client()
        matter = make_matter(client, user)
        self.assertEqual(mailbox_config.department_mailbox_for(matter), FIRM_BOX)
        self.assertEqual(mailbox_config.default_mailboxes_for(matter), [FIRM_BOX, user.email])
        self.assertEqual(mailbox_config.default_addresses_for(matter), [CLIENT])
        self.assertEqual(mailbox_config.name_keywords_for(matter), ['Jane Doe', 'Jane', 'Doe'])
        self.assertEqual(mailbox_config.parse_address_list('A@x.com, b@y.com; a@x.com'), ['a@x.com', 'b@y.com'])

    def test_unknown_matter_type_falls_back_to_main_mailbox(self):
        user = make_user()
        matter = make_matter(make_client(), user, matter_type='Something Else')
        self.assertEqual(mailbox_config.department_mailbox_for(matter), 'mail@anpsolicitors.com')


# ----------------------------------------------------------------------------- discovery + runner

class DiscoveryTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client_obj = make_client()
        self.matter = make_matter(self.client_obj, self.user)
        self.graph = FakeGraph()

    def _export(self, **overrides):
        return CorrespondenceExport.objects.create(
            matter=self.matter, requested_by=self.user, params=base_params(**overrides),
            status=CorrespondenceExport.STATUS_DISCOVERING)

    def test_discovery_merges_sources_strictly_and_flags(self):
        # Filed under the matter with ids already stored (resolved directly).
        filed = graph_message('m1', 'FAM0000001 Sale of house', '2025-03-04T10:12:33Z', CLIENT, [FIRM_BOX],
                              has_attachments=True)
        self.graph.add(FIRM_BOX, filed)
        MatterEmails.objects.create(file_number=self.matter, subject=filed['subject'], link=filed['webLink'],
                                    time=datetime(2025, 3, 4, 10, 12, 33, tzinfo=UTC), mailbox=FIRM_BOX,
                                    graph_message_id='m1')
        # Legacy row: no ids, located by received time + web link, ids written back.
        legacy = graph_message('m2', 'FAM0000001 Decree', '2025-03-05T09:00:00Z', FIRM_BOX, ['court@example.org'])
        self.graph.add(FIRM_BOX, legacy)
        legacy_row = MatterEmails.objects.create(
            file_number=self.matter, subject=legacy['subject'], link=legacy['webLink'],
            time=datetime(2025, 3, 5, 9, 0, 0, tzinfo=UTC),
            sender=json.dumps({'emailAddress': {'name': 'Family', 'address': FIRM_BOX}}),
            receiver=json.dumps([{'emailAddress': {'name': '', 'address': 'court@example.org'}}]))
        # Legacy row that is nowhere to be found.
        MatterEmails.objects.create(file_number=self.matter, subject='FAM0000001 Lost', link='https://x/?ItemID=lost',
                                    time=datetime(2025, 3, 6, 9, 0, 0, tzinfo=UTC), sender='{}', receiver='[]')
        # Found by client address only, no matter ref in subject -> flagged.
        self.graph.add(FIRM_BOX, graph_message('m3', 'Quick question', '2025-04-01T12:00:00Z', CLIENT, [FIRM_BOX]))
        # Address appears only in the body: the search returns it but the strict check drops it.
        self.graph.add(FIRM_BOX, graph_message('m4', 'Agent chat', '2025-04-02T12:00:00Z', 'agent@example.org',
                                               [FIRM_BOX], fuzzy=[CLIENT]))
        # Read receipt from the client: listed, unticked.
        self.graph.add(FIRM_BOX, graph_message('m5', 'Read: FAM0000001 Sale of house', '2025-04-03T12:00:00Z', CLIENT,
                                               [FIRM_BOX], msg_class='REPORT.IPM.Note.IPNRN'))
        # Draft and out-of-range messages are ignored.
        draft = graph_message('m6', 'Draft to Jane', '2025-04-04T12:00:00Z', FIRM_BOX, [CLIENT], folder='f-drafts')
        draft['isDraft'] = True
        self.graph.add(FIRM_BOX, draft)
        self.graph.add(FIRM_BOX, graph_message('m7', 'Old', '2024-04-04T12:00:00Z', CLIENT, [FIRM_BOX]))

        export = self._export()
        discovery.run_discovery(export, graph=self.graph)
        export.refresh_from_db()

        self.assertEqual(export.status, CorrespondenceExport.STATUS_PREVIEW)
        by_subject = {c['subject']: c for c in export.candidates}
        self.assertEqual(set(by_subject), {'FAM0000001 Sale of house', 'FAM0000001 Decree', 'FAM0000001 Lost',
                                           'Quick question', 'Read: FAM0000001 Sale of house'})
        self.assertEqual(by_subject['FAM0000001 Sale of house']['found_by'], ['system', 'address'])
        self.assertEqual(by_subject['FAM0000001 Decree']['found_by'], ['system'])
        self.assertEqual(by_subject['Quick question']['found_by'], ['address'])
        self.assertIn(discovery.FLAG_NO_REF_SUBJECT, by_subject['Quick question']['flags'])
        self.assertFalse(by_subject['Read: FAM0000001 Sale of house']['selected'])
        self.assertFalse(by_subject['FAM0000001 Lost']['selected'])
        self.assertIn(discovery.FLAG_NOT_FOUND, by_subject['FAM0000001 Lost']['flags'])
        self.assertEqual(export.counts['strict_dropped'], 1)
        self.assertEqual(export.counts['unresolved'], 1)
        self.assertEqual(export.counts['receipts'], 1)
        self.assertEqual(export.counts['by_system'], 2)
        self.assertEqual(export.counts['by_address'], 2)  # the question and the receipt; the filed one was merged
        self.assertEqual(len(export.selected_keys), 3)
        legacy_row.refresh_from_db()
        self.assertEqual(legacy_row.graph_message_id, 'm2')
        self.assertEqual(legacy_row.mailbox, FIRM_BOX)
        self.assertEqual(legacy_row.folder_name, 'Inbox')

    def test_matter_search_is_opt_in(self):
        third_party = graph_message('t1', 'FAM0000001 valuation', '2025-05-01T10:00:00Z', 'agent@example.org', [FIRM_BOX])
        self.graph.add(FIRM_BOX, third_party)
        export = self._export()
        discovery.run_discovery(export, graph=self.graph)
        self.assertEqual(export.candidates, [])
        export2 = self._export(matter_search=True)
        discovery.run_discovery(export2, graph=self.graph)
        self.assertEqual([c['found_by'] for c in export2.candidates], [['matter']])

    def test_cancelled_export_is_not_overwritten(self):
        export = self._export()
        CorrespondenceExport.objects.filter(id=export.id).update(status=CorrespondenceExport.STATUS_CANCELLED)
        discovery.run_discovery(export, graph=self.graph)
        export.refresh_from_db()
        self.assertEqual(export.status, CorrespondenceExport.STATUS_CANCELLED)
        self.assertEqual(export.candidates, [])


@override_settings(USE_SHAREPOINT=False, CORRESPONDENCE_EXPORT_RUNNER='sync', MEDIA_ROOT=tempfile.mkdtemp())
class RunnerTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        media_root = cls._overridden_settings['MEDIA_ROOT']
        super().tearDownClass()
        shutil.rmtree(media_root, ignore_errors=True)

    def setUp(self):
        self.user = make_user()
        self.matter = make_matter(make_client(), self.user)
        self.graph = FakeGraph()
        self.graph.add(FIRM_BOX, graph_message('m1', 'FAM0000001 Sale of house', '2025-03-04T10:12:33Z', CLIENT,
                                               [FIRM_BOX], has_attachments=True),
                       mime_bytes('FAM0000001 Sale of house', CLIENT, FIRM_BOX,
                                  html='<html><body><p>Contract attached, Jane Doe</p></body></html>',
                                  attachments=[('contract.pdf', sample_pdf(), 'application', 'pdf'),
                                               ('plan.csv', b'a,b', 'text', 'csv')]))
        self.graph.add(FIRM_BOX, graph_message('m2', 'Quick question', '2025-03-05T16:40:00Z', FIRM_BOX, [CLIENT]),
                       mime_bytes('Quick question', FIRM_BOX, CLIENT, text='Are you free on Friday?'))
        self.graph.add(FIRM_BOX, graph_message('m3', 'Read: FAM0000001 Sale of house', '2025-03-05T17:00:00Z', CLIENT,
                                               [FIRM_BOX], msg_class='REPORT.IPM.Note.IPNRN'))
        self.graph.add(FIRM_BOX, graph_message('m4', 'FAM0000001 Missing original', '2025-03-06T17:00:00Z', CLIENT,
                                               [FIRM_BOX]))  # no MIME registered -> download fails
        self.export = CorrespondenceExport.objects.create(
            matter=self.matter, requested_by=self.user, params=base_params(),
            status=CorrespondenceExport.STATUS_DISCOVERING)
        discovery.run_discovery(self.export, graph=self.graph)
        self.export.refresh_from_db()

    def test_build_writes_files_index_and_zip(self):
        keys = [c['key'] for c in self.export.candidates]
        self.export.selected_keys = keys  # include the receipt on purpose: it must still be excluded
        self.export.status = CorrespondenceExport.STATUS_QUEUED
        self.export.save()
        with self.assertLogs('backend', level='WARNING'):  # the missing original is logged, not fatal
            runner.run_export(self.export, graph=self.graph, renderer=render.Renderer())
        self.export.refresh_from_db()

        self.assertEqual(self.export.status, CorrespondenceExport.STATUS_DONE, self.export.error)
        self.assertEqual(self.export.counts['exported'], 3)
        self.assertEqual(self.export.counts['receipts_excluded'], 1)
        self.assertEqual(self.export.counts['enclosures'], 2)
        self.assertEqual(self.export.counts['failed'], 1)
        self.assertEqual(len(self.export.excluded), 1)
        self.assertEqual(self.export.excluded[0]['type'], classify.READ_RECEIPT)
        rows = {r['subject']: r for r in self.export.results}
        self.assertEqual(rows['FAM0000001 Sale of house']['attachment_count'], '2')
        self.assertEqual(rows['FAM0000001 Sale of house']['flags'], '')
        self.assertIn('Jane Doe', rows['FAM0000001 Sale of house']['matched'])
        self.assertIn(runner.FLAG_NO_MATCH, rows['Quick question']['flags'])
        self.assertIn('Download failed', rows['FAM0000001 Missing original']['flags'])
        self.assertEqual(rows['FAM0000001 Missing original']['pdf_name'], '')

        from backend.correspondence_export.storage import ExportStore
        store = ExportStore(self.export.storage_folder)
        self.assertTrue(store.local_path(self.export.zip_name).is_file())
        self.assertTrue(store.local_path('00_index.csv').is_file())
        self.assertTrue(store.local_path(rows['FAM0000001 Sale of house']['pdf_name']).is_file())
        self.assertTrue(store.local_path('001_enclosures/contract.pdf').is_file())
        with zipfile.ZipFile(store.local_path(self.export.zip_name)) as zf:
            names = zf.namelist()
        top = f'{self.matter.file_number}_emails_2025-01-01_to_2025-12-31/'
        self.assertIn(top + '00_summary.txt', names)
        self.assertIn(top + '00_excluded_receipts.csv', names)
        self.assertEqual(sum(1 for n in names if '/originals/' in n), 2)  # the failed download has no original
        self.assertEqual(sum(1 for n in names if n.endswith('.pdf') and '_enclosures/' not in n), 2)
        with zipfile.ZipFile(store.local_path(self.export.zip_name)) as zf:
            pdf = zf.read(top + rows['FAM0000001 Sale of house']['pdf_name'])
        self.assertEqual(len(pikepdf.open(io.BytesIO(pdf)).pages), 3)  # email + divider + contract
        self.assertEqual(self.export.percent, 100)

    def test_stale_running_job_is_failed(self):
        self.export.status = CorrespondenceExport.STATUS_RUNNING
        self.export.worker_heartbeat = timezone.now() - timedelta(hours=1)
        self.export.save()
        self.assertEqual(runner.mark_stale_jobs(), 1)
        self.export.refresh_from_db()
        self.assertEqual(self.export.status, CorrespondenceExport.STATUS_FAILED)
        self.assertIn('stopped', self.export.error)

    def test_process_pending_runs_queued_jobs(self):
        self.export.selected_keys = [c['key'] for c in self.export.candidates if c['selected']]
        self.export.status = CorrespondenceExport.STATUS_QUEUED
        self.export.save()
        with patch('backend.correspondence_export.runner.run_export') as run_export:
            self.assertEqual(runner.process_pending(), 1)
        run_export.assert_called_once()

    def test_failed_job_records_error(self):
        self.export.status = CorrespondenceExport.STATUS_QUEUED
        self.export.selected_keys = [self.export.candidates[0]['key']]
        self.export.save()
        with patch('backend.correspondence_export.runner.run_export', side_effect=RuntimeError('boom')), \
                self.assertLogs('backend', level='ERROR'):
            runner.run_job(self.export.id)
        self.export.refresh_from_db()
        self.assertEqual(self.export.status, CorrespondenceExport.STATUS_FAILED)
        self.assertIn('boom', self.export.error)


# ----------------------------------------------------------------------------- views

@override_settings(USE_SHAREPOINT=False, CORRESPONDENCE_EXPORT_RUNNER='sync', MEDIA_ROOT=tempfile.mkdtemp())
class ViewTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        media_root = cls._overridden_settings['MEDIA_ROOT']
        super().tearDownClass()
        shutil.rmtree(media_root, ignore_errors=True)

    def setUp(self):
        self.user = make_user()
        self.matter = make_matter(make_client(), self.user)
        self.client.force_login(self.user)
        self.fn = self.matter.file_number

    def _fake_discovery(self, export, graph=None):
        export.candidates = [{
            'key': 'k1', 'mailbox': FIRM_BOX, 'graph_id': 'm1', 'folder': 'Inbox', 'locations': [f'{FIRM_BOX} / Inbox'],
            'found_by': ['system', 'address'], 'received': '2025-03-04T10:12:33Z', 'sent': '2025-03-04T10:12:33Z',
            'from': f'Jane Doe <{CLIENT}>', 'from_addr': CLIENT, 'to': FIRM_BOX, 'cc': '',
            'subject': 'FAM0000001 Sale', 'has_attachments': True, 'msg_class': 'IPM.Note', 'report': None,
            'matter_email_id': None, 'direction': 'Received', 'flags': [], 'selected': True,
        }, {
            'key': 'k2', 'mailbox': FIRM_BOX, 'graph_id': 'm2', 'folder': 'Inbox', 'locations': [f'{FIRM_BOX} / Inbox'],
            'found_by': ['address'], 'received': '2025-03-05T10:12:33Z', 'sent': '2025-03-05T10:12:33Z',
            'from': CLIENT, 'from_addr': CLIENT, 'to': FIRM_BOX, 'cc': '', 'subject': 'Read: FAM0000001 Sale',
            'has_attachments': False, 'msg_class': 'REPORT.IPM.Note.IPNRN', 'report': classify.READ_RECEIPT,
            'matter_email_id': None, 'direction': 'Received', 'flags': ['Receipt: read receipt'], 'selected': False,
        }]
        export.selected_keys = ['k1']
        export.counts = {'candidates': 2, 'selected': 1, 'by_system': 1, 'by_address': 1, 'receipts': 1,
                         'unresolved': 0, 'strict_dropped': 0, 'flagged': 1}
        export.status = CorrespondenceExport.STATUS_PREVIEW
        export.discovered_at = timezone.now()
        export.save()

    def test_list_page_prefills_from_matter(self):
        response = self.client.get(reverse('correspondence_exports', args=[self.fn]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, CLIENT)
        self.assertContains(response, 'Search mailboxes')
        form = response.context['form']
        self.assertEqual(form['addresses'], [CLIENT])
        checked = [m['address'] for m in form['shared_mailboxes'] if m['checked']]
        self.assertEqual(checked, [FIRM_BOX])
        self.assertTrue(any(m['checked'] for m in form['staff_mailboxes'] if m['address'] == self.user.email))

    def test_create_validates(self):
        response = self.client.post(reverse('correspondence_export_create', args=[self.fn]), {
            'addresses': 'not-an-email', 'date_from': '2025-01-01', 'date_to': '2024-01-01'})
        self.assertEqual(response.status_code, 400)
        errors = response.context['form']['errors']
        self.assertIn('addresses', errors)
        self.assertIn('mailboxes', errors)
        self.assertIn('dates', errors)
        self.assertEqual(CorrespondenceExport.objects.count(), 0)

    def test_full_flow_through_the_views(self):
        with patch('backend.correspondence_export.runner.run_discovery', side_effect=self._fake_discovery):
            response = self.client.post(reverse('correspondence_export_create', args=[self.fn]), {
                'addresses': f'{CLIENT}, other@example.com', 'mailboxes': [FIRM_BOX],
                'extra_mailboxes': 'someone@anpsolicitors.com', 'date_from': '2025-01-01',
                'date_to': '2025-12-31', 'include_system_filed': 'on', 'append_pdf_enclosures': 'on',
                'include_originals': 'on', 'header_name': 'ANP Solicitors'})
        export = CorrespondenceExport.objects.get()
        self.assertRedirects(response, reverse('correspondence_export_detail', args=[self.fn, export.id]))
        self.assertEqual(export.params['addresses'], [CLIENT, 'other@example.com'])
        self.assertEqual(export.params['mailboxes'], [FIRM_BOX, 'someone@anpsolicitors.com'])
        self.assertEqual(export.params['matters'], [self.fn])
        self.assertEqual(export.status, CorrespondenceExport.STATUS_PREVIEW)
        self.assertTrue(Modifications.objects.filter(object_id=export.id).exists())

        detail = self.client.get(reverse('correspondence_export_detail', args=[self.fn, export.id]))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, 'Build export')
        self.assertContains(detail, 'FAM0000001 Sale')
        self.assertContains(detail, 'Receipt: read receipt')

        panel = self.client.get(reverse('correspondence_export_panel', args=[self.fn, export.id]))
        self.assertEqual(panel['X-Export-Status'], 'preview')
        self.assertEqual(panel['X-Export-Stage'], '2')

        with patch('backend.correspondence_export.runner.run_export') as run_export:
            response = self.client.post(reverse('correspondence_export_generate', args=[self.fn, export.id]),
                                        {'selected': ['k1', 'bogus']})
        self.assertRedirects(response, reverse('correspondence_export_detail', args=[self.fn, export.id]))
        export.refresh_from_db()
        self.assertEqual(export.selected_keys, ['k1'])
        self.assertEqual(export.status, CorrespondenceExport.STATUS_QUEUED)
        run_export.assert_called_once()

        # Simulate the worker finishing with local files.
        from backend.correspondence_export.storage import ExportStore, export_folder
        export.storage_folder = export_folder(self.matter, export.id)
        store = ExportStore(export.storage_folder)
        store.put('001_2025-03-04_1012_FAM0000001_Sale.pdf', b'%PDF-1.4 fake')
        store.put('00_index.csv', b'No,Date\r\n')
        store.put('export.zip', b'PK\x05\x06' + b'\x00' * 18)
        export.zip_name = 'export.zip'
        export.results = [{'no': '001', 'date': '04/03/2025', 'time': '10:12', 'direction': 'Received',
                           'from': CLIENT, 'to': FIRM_BOX, 'cc': '', 'subject': 'FAM0000001 Sale',
                           'attachments': 'contract.pdf', 'attachment_count': '1', 'found_in': f'{FIRM_BOX} / Inbox',
                           'found_by': 'filed under matter', 'matched': 'Jane Doe', 'flags': '',
                           'pdf_name': '001_2025-03-04_1012_FAM0000001_Sale.pdf', 'enc_dir': '001_enclosures',
                           'eml_name': '001_2025-03-04_1012.eml', 'enclosure_files': ['contract.pdf']}]
        export.counts = {**export.counts, 'exported': 1, 'enclosures': 1, 'receipts_excluded': 1, 'failed': 0,
                         'zip_bytes': 22}
        export.status = CorrespondenceExport.STATUS_DONE
        export.finished_at = timezone.now()
        export.save()

        done = self.client.get(reverse('correspondence_export_detail', args=[self.fn, export.id]))
        self.assertContains(done, 'Download zip')
        self.assertContains(done, 'File transfer record')
        self.assertContains(done, 'Share links need SharePoint storage')
        download = self.client.get(reverse('correspondence_export_download', args=[self.fn, export.id]))
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download['Content-Type'], 'application/zip')
        download.close()
        pdf = self.client.get(reverse('correspondence_export_file',
                                      args=[self.fn, export.id, '001_2025-03-04_1012_FAM0000001_Sale.pdf']))
        self.assertEqual(pdf.status_code, 200)
        pdf.close()
        self.assertEqual(self.client.get(reverse('correspondence_export_file',
                                                 args=[self.fn, export.id, '../secret'])).status_code, 404)

        response = self.client.post(reverse('correspondence_export_share_create', args=[self.fn, export.id]), {})
        self.assertRedirects(response, reverse('correspondence_export_detail', args=[self.fn, export.id]))
        export.refresh_from_db()
        self.assertEqual(export.share_url, '')

        response = self.client.post(reverse('correspondence_export_transfer', args=[self.fn, export.id]), {
            'transfer_to': 'New Firm LLP', 'transfer_contact': 'Ms Smith', 'client_authority_date': '2026-10-01',
            'lien_checked': 'on', 'transfer_notes': 'Sent by SharePoint link'})
        self.assertRedirects(response, reverse('correspondence_export_detail', args=[self.fn, export.id]))
        export.refresh_from_db()
        self.assertEqual(export.transfer_to, 'New Firm LLP')
        self.assertTrue(export.lien_checked)
        self.assertFalse(export.retention_copy_kept)
        self.assertEqual(export.transfer_recorded_by, self.user)
        self.assertTrue(Modifications.objects.filter(object_id=export.id).count() >= 3)

    def test_cancel_and_retry(self):
        export = CorrespondenceExport.objects.create(
            matter=self.matter, requested_by=self.user, params=base_params(),
            status=CorrespondenceExport.STATUS_FAILED, error='Search failed: boom')
        with patch('backend.correspondence_export.runner.run_discovery') as run_discovery:
            response = self.client.post(reverse('correspondence_export_retry', args=[self.fn, export.id]))
        self.assertEqual(response.status_code, 302)
        run_discovery.assert_called_once()
        export.refresh_from_db()
        self.assertEqual(export.error, '')
        export.status = CorrespondenceExport.STATUS_PREVIEW
        export.save()
        response = self.client.post(reverse('correspondence_export_cancel', args=[self.fn, export.id]))
        self.assertRedirects(response, reverse('correspondence_exports', args=[self.fn]))
        export.refresh_from_db()
        self.assertEqual(export.status, CorrespondenceExport.STATUS_CANCELLED)
        self.assertEqual(self.client.get(reverse('correspondence_export_download', args=[self.fn, export.id])).status_code, 404)

    def test_other_matter_cannot_see_export(self):
        other = make_matter(make_client('Other', 'o@example.com'), self.user, file_number='FAM0000002')
        export = CorrespondenceExport.objects.create(matter=other, requested_by=self.user, params=base_params(),
                                                     status=CorrespondenceExport.STATUS_PREVIEW)
        self.assertEqual(self.client.get(reverse('correspondence_export_detail', args=[self.fn, export.id])).status_code, 404)

    def test_correspondence_page_links_to_export(self):
        response = self.client.get(reverse('correspondence_view', args=[self.fn]))
        self.assertContains(response, reverse('correspondence_exports', args=[self.fn]))
