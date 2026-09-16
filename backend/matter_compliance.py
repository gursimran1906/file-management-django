"""Per-matter-per-client compliance: ensure a MatterClient row exists for every
client on a matter, and build the per-client display/edit data for the matter
home. Engagement-level checks (terms of engagement, NCBA, source of funds, PEP)
live on MatterClient — fresh for each file — while identity (proof of ID/address,
AML date) stays on the client and is reused across matters."""
from django.utils import timezone

from .models import MatterClient, MatterClientDocument

# The four engagement-level checks captured per matter-client.
COMPLIANCE_FIELDS = ('terms_of_engagement', 'ncba', 'source_of_funds', 'pep')
DOC_CATEGORY_LABELS = dict(MatterClientDocument.CATEGORY_CHOICES)


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


def matter_compliance(wip):
    """Per-client compliance rows for the matter home. Ensures the MatterClient
    rows exist, then merges the per-matter checks with the client's own identity
    status (kept per client) and any uploaded documents."""
    rows = ensure_matter_clients(wip)
    today = timezone.localdate()
    docs_by_mc = {}
    for doc in MatterClientDocument.objects.filter(
            matter_client__matter=wip).order_by('category', '-uploaded_at'):
        docs_by_mc.setdefault(doc.matter_client_id, []).append(doc)

    out = []
    for client in wip.all_clients:
        mc = rows.get(client.id)
        if not mc:
            continue
        # Identity documents (proof of ID/address) — per client, shared across
        # matters. Shown here so all of a client's documents live in one place.
        key_docs = [
            {
                'id': kd.id,
                'label': kd.get_category_display(),
                'document_type': kd.document_type,
                'expiry': kd.expiry_date,
                'verified_on': kd.verified_on,
                'has_file': bool(kd.file),
                'expired': bool(kd.expiry_date and kd.expiry_date < today),
            }
            for kd in client.key_documents.all().order_by('category', '-verified_on')
        ]
        out.append({
            'key_documents': key_docs,
            'mc': mc,
            'mc_id': mc.id,
            'client': client,
            'client_id': client.id,
            'is_lead': mc.is_lead,
            # per matter-client
            'terms_signed': mc.terms_of_engagement_signed,
            'terms_sent_on': mc.terms_sent_on,
            'terms_received_on': mc.terms_received_on,
            'ncba_required': mc.ncba_required,
            'ncba_signed': mc.ncba_signed,
            'ncba_sent_on': mc.ncba_sent_on,
            'ncba_received_on': mc.ncba_received_on,
            'sof_signed': mc.source_of_funds_signed,
            'sof_details': mc.source_of_funds_details,
            'pep_signed': mc.pep_signed,
            'source': mc.source,
            # per client (identity — reused across matters)
            'id_verified': bool(client.id_verified),
            'date_of_last_aml': client.date_of_last_aml,
            'documents': docs_by_mc.get(mc.id, []),
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
