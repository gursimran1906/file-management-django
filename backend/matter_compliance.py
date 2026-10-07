"""Per-matter-per-client compliance for the matter home page.

Every client on a matter gets a MatterClient row holding the engagement checks
redone for each file — terms of engagement, NCBA (when the matter is under one),
source of funds and PEP. Identity (proof of ID/address, selfie, AML date) stays on
the client record and is reused across matters.

This module also builds one documents list per client that brings together what
the client sent through the onboarding portal, scans staff uploaded, and the
identity documents held on the client record — so a client who never went
through the portal has the same folder, with an upload on every row.
"""
from django.db.models import F
from django.urls import reverse
from django.utils import timezone

from .models import MatterClient, MatterClientDocument

# The four engagement-level checks captured per matter-client.
COMPLIANCE_FIELDS = ('terms_of_engagement', 'ncba', 'source_of_funds', 'pep')
DOC_CATEGORY_LABELS = dict(MatterClientDocument.CATEGORY_CHOICES)

# Identity documents live on the client record (ClientKeyDocument) and are reused
# across matters: (key-document category, label, onboarding item type).
IDENTITY_KINDS = (
    ('proof_of_id', 'Proof of ID', 'proof_id'),
    ('proof_of_address', 'Proof of address', 'proof_address'),
    ('selfie_id', 'Selfie with ID', 'selfie_id'),
)
IDENTITY_CATEGORIES = tuple(k for k, _, _ in IDENTITY_KINDS)

# Engagement documents belong to this matter (MatterClientDocument):
# (matter-document category, label, onboarding item type or None).
MATTER_KINDS = (
    ('terms', 'Terms of engagement', 'terms_of_engagement'),
    ('ncba', 'NCBA', None),
    ('source_of_funds', 'Source of funds declaration', 'source_of_funds'),
    ('pep', 'PEP declaration', 'pep'),
    ('aml_id_check', 'AML / ID check', None),
    ('other', 'Other', None),
)
# Rows that are nice to have rather than expected on every file; they don't count
# towards the "n of m documents" summary.
OPTIONAL_KINDS = ('aml_id_check', 'other')


def ensure_matter_clients(wip):
    """Make sure every client on the matter has a MatterClient row. Returns them
    keyed by client id. Idempotent — safe to call on every matter view."""
    existing = {mc.client_id: mc for mc in wip.matter_clients.all()}
    lead_id = wip.client1_id
    for client in wip.all_clients:
        if client.id not in existing:
            existing[client.id] = MatterClient.objects.create(
                matter=wip, client=client, is_lead=(client.id == lead_id),
                source=MatterClient.SOURCE_CAPTURED)
    return existing


def onboarding_copies(wip):
    """Documents collected through onboarding for this matter, keyed by client id
    then item type. Only items that actually carry a copy — the client's portal
    upload (SharePoint id) or a staff "office copy" — are included."""
    out = {}
    for group in wip.onboarding_groups.all():
        members = group.members.exclude(client__isnull=True).prefetch_related('items')
        for member in members:
            for item in member.items.all():
                if item.file or item.sharepoint_item_id:
                    out.setdefault(member.client_id, {})[item.item_type] = item
    return out


def _fmt(day):
    return day.strftime('%d/%m/%Y') if day else ''


def _copy_links(item):
    """Links to the copies an onboarding item carries (portal upload, office scan)."""
    links = []
    if item is None:
        return links
    if item.sharepoint_item_id:
        links.append({'label': 'Client copy', 'url': reverse(
            'onboarding_preview_portal_doc', args=[item.onboarding_id, item.item_type])})
    if item.file:
        links.append({'label': 'Office copy', 'url': reverse(
            'onboarding_preview_doc', args=[item.onboarding_id, item.item_type])})
    return links


def _expiry_note(expiry, today):
    """('expires dd/mm/yyyy' | 'expired dd/mm/yyyy' | '', expired?)"""
    if not expiry:
        return '', False
    if expiry < today:
        return f'expired {_fmt(expiry)}', True
    return f'expires {_fmt(expiry)}', False


def _identity_row(category, label, item, records, today, mc):
    """One identity document for a client: the latest record on the client
    record (metadata + optional scan) plus any onboarding copies. ``records`` are
    this client's ClientKeyDocument rows for the category, newest first."""
    latest = records[0] if records else None
    links = _copy_links(item)
    for kd in records:
        if kd.file:
            links.append({
                'label': 'View scan' if kd is latest else f'Scan {_fmt(kd.verified_on)}'.strip(),
                'url': reverse('client_key_document_preview', args=[kd.id])})
    meta, expired = [], False
    source = latest if latest is not None else item
    if source is not None:
        if source.document_type:
            meta.append(source.document_type)
        if source.document_reference:
            meta.append(source.document_reference)
        note, expired = _expiry_note(source.expiry_date, today)
        if note:
            meta.append(note)
    if latest is not None and latest.verified_on:
        meta.append(f'verified {_fmt(latest.verified_on)}')
    held = bool(links) or latest is not None
    if latest is not None and not latest.file and not links:
        # A record with no scan (older data): attach the scan to it.
        upload = {'mode': 'attach', 'url': reverse(
            'client_key_document_upload', args=[mc.matter.file_number, latest.id])}
    else:
        upload = {'mode': 'new', 'category': category, 'url': reverse(
            'matter_upload_identity_doc', args=[mc.matter.file_number, mc.id])}
    return {
        'key': category, 'label': label, 'scope': 'identity', 'held': held,
        'required': True, 'expired': expired, 'meta': ' · '.join(meta),
        'links': links, 'upload': upload, 'older': max(len(records) - 1, 0),
    }


def _matter_row(category, label, item, docs, today, mc):
    """One engagement document for a client on this matter: uploads against the
    matter-client (newest first) plus any onboarding copies."""
    latest = docs[0] if docs else None
    links = _copy_links(item)
    for doc in docs:
        links.append({
            'label': 'View' if doc is latest else f'View {_fmt(doc.uploaded_at.date())}',
            'url': reverse('matter_preview_client_doc', args=[doc.id])})
    meta, expired = [], False
    if latest is not None:
        if latest.document_type:
            meta.append(latest.document_type)
        note, expired = _expiry_note(latest.expiry_date, today)
        if note:
            meta.append(note)
        meta.append(f'uploaded {_fmt(latest.uploaded_at.date())}')
    elif item is not None and item.document_type:
        meta.append(item.document_type)
    return {
        'key': category, 'label': label, 'scope': 'matter', 'held': bool(links),
        'required': category not in OPTIONAL_KINDS,
        'expired': expired, 'meta': ' · '.join(meta), 'links': links,
        'upload': {'mode': 'new', 'category': category, 'url': reverse(
            'matter_upload_client_doc', args=[mc.matter.file_number, mc.id])},
        'older': max(len(docs) - 1, 0),
    }


def client_documents(wip, client, mc, copies, today=None):
    """The documents list for one client on this matter — identity documents
    first (held on the client record, reused across matters), then the
    engagement documents for this file. ``copies`` is this client's entry from
    :func:`onboarding_copies`. Every row has an upload, so clients who were not
    onboarded through the portal get the same folder."""
    today = today or timezone.localdate()
    key_docs = {}
    for kd in client.key_documents.all().order_by(
            F('verified_on').desc(nulls_last=True), '-id'):
        key_docs.setdefault(kd.category, []).append(kd)
    matter_docs = {}
    for doc in mc.documents.all().order_by('-uploaded_at', '-id'):
        matter_docs.setdefault(doc.category, []).append(doc)
    rows = [_identity_row(cat, label, copies.get(item_type), key_docs.get(cat, []), today, mc)
            for cat, label, item_type in IDENTITY_KINDS]
    for cat, label, item_type in MATTER_KINDS:
        if cat == 'ncba' and not wip.ncba_required:
            continue
        rows.append(_matter_row(cat, label, copies.get(item_type) if item_type else None,
                                matter_docs.get(cat, []), today, mc))
    return rows


def matter_compliance(wip):
    """Per-client compliance rows for the matter home, in the matter's client
    order. Ensures the MatterClient rows exist, then merges the per-matter checks
    with the client's own identity status and their documents list."""
    rows = ensure_matter_clients(wip)
    today = timezone.localdate()
    copies = onboarding_copies(wip)

    out = []
    for client in wip.all_clients:
        mc = rows.get(client.id)
        if not mc:
            continue
        documents = client_documents(wip, client, mc, copies.get(client.id, {}), today)
        checks_ok = (mc.terms_of_engagement_signed and mc.source_of_funds_signed
                     and mc.pep_signed and (mc.ncba_signed or not wip.ncba_required))
        out.append({
            'mc': mc,
            'mc_id': mc.id,
            'client': client,
            'client_id': client.id,
            # per matter-client
            'terms_signed': mc.terms_of_engagement_signed,
            'terms_sent_on': mc.terms_sent_on,
            'terms_received_on': mc.terms_received_on,
            'ncba_signed': mc.ncba_signed,
            'ncba_sent_on': mc.ncba_sent_on,
            'ncba_received_on': mc.ncba_received_on,
            'sof_signed': mc.source_of_funds_signed,
            'sof_details': mc.source_of_funds_details,
            'pep_signed': mc.pep_signed,
            'source': mc.source,
            'checks_complete': bool(checks_ok),
            # per client (identity — reused across matters)
            'id_verified': bool(client.id_verified),
            'date_of_last_aml': client.date_of_last_aml,
            # documents
            'documents': documents,
            'documents_held': sum(1 for r in documents if r['required'] and r['held']),
            'documents_total': sum(1 for r in documents if r['required']),
            'documents_expired': any(r['expired'] for r in documents),
        })
    return out


def apply_declarations(mc, provided, user, today=None):
    """Set the engagement checks on a MatterClient from a set of provided item
    types (e.g. at onboarding convert). Only ever flips a flag to True and stamps
    the date/by — never downgrades. Returns the list of changed field names."""
    today = today or timezone.localdate()
    changed = []

    def sign(flag, date_field, by_field):
        if not getattr(mc, flag):
            setattr(mc, flag, True)
            setattr(mc, date_field, today)
            setattr(mc, by_field, user)
            changed.extend([flag, date_field, by_field])

    if 'terms_of_engagement' in provided:
        sign('terms_of_engagement_signed', 'terms_of_engagement_on', 'terms_of_engagement_by')
        if not mc.terms_received_on:
            mc.terms_received_on = today
            changed.append('terms_received_on')
    if 'source_of_funds' in provided:
        sign('source_of_funds_signed', 'source_of_funds_on', 'source_of_funds_by')
    if 'pep' in provided:
        sign('pep_signed', 'pep_on', 'pep_by')
    if 'ncba' in provided:
        sign('ncba_signed', 'ncba_on', 'ncba_by')

    if changed:
        mc.save(update_fields=list(set(changed)))
    return changed
