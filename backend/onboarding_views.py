"""Staff onboarding console: start an onboarding group (one or more clients for a
future matter), watch each client's documents arrive through the portal,
KYC-accept them, run conflict checks, and convert the group into a matter.

The client-facing uploads live in the separate portal app; here we orchestrate
and review. See plans/lets-plan-for-separate-bubbly-pony.md.
"""
import io
import logging
import mimetypes
import os
from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.html import escape
from django.views.decorators.http import require_POST

ALLOWED_DOC_EXTENSIONS = ('.pdf', '.jpg', '.jpeg', '.png', '.heic')
MAX_DOC_BYTES = 25 * 1024 * 1024  # matches the portal's upload cap

from . import onboarding_email as email
from . import onboarding_portal as portal
from . import onboarding_storage as storage
from .conflict_utils import run_conflict_check
from .matter_compliance import ensure_matter_clients, apply_declarations
from .models import (ClientContactDetails, ClientKeyDocument, ConflictCheck,
                     Onboarding, OnboardingGroup, OnboardingItem)

logger = logging.getLogger('backend')

ITEM_LABELS = dict(portal.ONBOARDING_ITEMS)


def _parse_date(value):
    value = (value or '').strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        return None


def _send_invite(request, member):
    """Request a magic link from the portal for one member, deliver it by
    email, and record the portal ids.

    Only one link per client is ever live: a previous still-active link is
    expired first. The link itself is a credential, so it is kept on the row
    only while we still need to deliver it by hand (email not configured or
    failed) and cleared once the email has gone."""
    if (member.portal_invite_id and member.invite_sent_at
            and not member.invite_expired_at):
        try:
            portal.expire_invite(member)
        except portal.PortalError as exc:
            logger.warning('Could not expire the previous invite for %s: %s',
                           member.client_ref, exc)
    try:
        result = portal.create_invite(member)
    except portal.PortalError as exc:
        messages.error(request, f'Could not send the invite to {member.client_name}: {exc}')
        return False
    # ``redeem_url`` is the portal's field; ``link`` is the built-in mock's.
    link = result.get('redeem_url') or result.get('link') or ''
    if not link and not portal.is_mock():
        logger.warning('Portal /invites returned no redeem_url; '
                       'response keys: %s', list(result.keys()))

    member.portal_submission_id = result.get('submission_id', '')
    member.portal_invite_id = str(result.get('invite_id') or result.get('id') or '')
    member.portal_invite_link = link
    member.invite_sent_at = timezone.now()
    member.invite_expired_at = None  # a fresh invite reactivates the link
    if member.status == Onboarding.STATUS_INVITED:
        member.status = Onboarding.STATUS_COLLECTING
    member.save()
    try:
        sent = email.send_invite_email(member.client_name, member.email, link)
    except Exception as exc:  # noqa: BLE001 - email must not break the invite
        logger.warning('Invite email failed for %s: %s', member.email, exc)
        messages.warning(
            request, f'Invite recorded for {member.client_name}, but the email to '
            f'{member.email} could not be sent.')
        return True
    if sent:
        # Delivered — don't retain the live link. Staff can expire it, or
        # resend to issue a fresh one.
        member.portal_invite_link = ''
        member.save(update_fields=['portal_invite_link'])
        messages.success(request, f'Invite emailed to {member.email}.')
    else:
        messages.success(
            request, f'Invite recorded for {member.client_name}. The email was not '
            'sent from here (invite emails are switched off or not configured), so '
            'copy the link from the case page to send it.')
    return True


def _format_address(member):
    parts = [member.address_line1, member.address_line2, member.county, member.postcode]
    return ', '.join(p.strip() for p in parts if p and p.strip())


def _persist_item_id(member, item_type, item_id):
    """Store the portal's SharePoint item id on this member's existing
    OnboardingItem row (creates nothing). This is the durable recovery handle: the
    matter's Client Care section links the client copy from it without a live
    portal call, and previews resolve the file by id even if the portal is briefly
    unreachable. No-op when there is no id or no local row for that type yet."""
    if not item_id:
        return
    (OnboardingItem.objects
     .filter(onboarding=member, item_type=item_type)
     .exclude(sharepoint_item_id=item_id)
     .update(sharepoint_item_id=item_id))


def _persist_submission_item_ids(member, submission):
    """Copy every SharePoint item id a portal submission reports onto the matching
    OnboardingItem rows. Best-effort; a no-op in mock mode (which returns no file
    ids) and for item types that have no local row yet."""
    files = (submission or {}).get('files') or {}
    for item_type, info in files.items():
        _persist_item_id(member, item_type, (info or {}).get('item_id') or '')


def _snapshot_portal_documents(member, submission):
    """At convert time, make each portal-provided document a durable OnboardingItem
    row carrying its SharePoint item id, so the matter's Client Care section shows
    the client copy for every client — including documents the client provided but
    that weren't separately KYC-accepted. Creates rows as needed; never marks
    anything accepted. No-op in mock mode (no file ids)."""
    valid = dict(OnboardingItem.ITEM_CHOICES)
    files = (submission or {}).get('files') or {}
    for item_type, info in files.items():
        item_id = (info or {}).get('item_id') or ''
        if not item_id or item_type not in valid:
            continue
        row, _ = OnboardingItem.objects.get_or_create(
            onboarding=member, item_type=item_type)
        if row.sharepoint_item_id != item_id:
            row.sharepoint_item_id = item_id
            row.save(update_fields=['sharepoint_item_id'])


def _provided_item_types(member, submission):
    """The item types this member actually provided — a portal upload (or a
    declaration/terms acceptance) the portal reports as 'provided', or a document
    staff uploaded on their behalf (office copy / snapshotted portal id). This is
    what drives the client's KYC record at convert time: documents are recorded on
    provision, with no separate staff acceptance step."""
    provided = {k for k, v in ((submission or {}).get('items') or {}).items()
                if v == 'provided'}
    for it in member.items.all():
        if it.file or it.sharepoint_item_id:
            provided.add(it.item_type)
    return provided


def _member_progress(member):
    """Merge the portal's per-item status with local KYC acceptance for one
    member. Returns (items, flags)."""
    records = {i.item_type: i for i in member.items.all()}
    portal_address = {}
    portal_status = ''
    portal_capacity = {}
    try:
        submission = portal.get_submission(member)
        portal_items = submission.get('items', {})
        portal_address = submission.get('address') or {}
        portal_status = submission.get('status') or ''
        portal_capacity = submission.get('capacity') or {}
        portal_error = None
        _persist_submission_item_ids(member, submission)
    except portal.PortalError as exc:
        portal_items = {}
        portal_error = str(exc)

    # Pre-fill the member's address from the portal-provided one, but only into
    # fields that are still empty — never overwrite an address a staff member has
    # corrected (a wrong pickup from the ID must stay fixed). No-op in mock mode.
    if portal_address and not portal.is_mock():
        changed = False
        for field in ('address_line1', 'address_line2', 'county', 'postcode'):
            value = (portal_address.get(field) or '').strip()
            if value and not getattr(member, field):
                setattr(member, field, value)
                changed = True
        if changed:
            member.save(update_fields=['address_line1', 'address_line2', 'county', 'postcode'])

    # Identity docs already valid on file for an existing client count as
    # satisfied — shown (linked to the record we hold), but never re-requested.
    today = timezone.localdate()
    on_file_docs = (_valid_on_file_key_docs(member.client, today)
                    if member.client_id else {})
    canonical = [k for k, _ in OnboardingItem.ITEM_CHOICES]
    required = set(member.required_item_types())

    items = []
    all_provided = True
    any_provided = False
    for key in [k for k in canonical if k in required or k in on_file_docs]:
        label = ITEM_LABELS.get(key, key)
        record = records.get(key)
        has_file = bool(record and record.file)
        # A SharePoint id persisted from an earlier submission (e.g. before an
        # invite was reissued) is still the client's upload — the preview view
        # resolves it by id — so it counts as provided too.
        portal_provided = (portal_items.get(key, 'awaited') == 'provided'
                           or bool(record and record.sharepoint_item_id))
        # Reused from the client's record only when there's no fresh copy.
        key_doc = on_file_docs.get(key) if not (portal_provided or has_file) else None
        provided = portal_provided or has_file or bool(key_doc)
        if provided:
            any_provided = True
        else:
            all_provided = False
        items.append({
            'key': key,
            'label': label,
            'provided': provided,
            'portal_provided': portal_provided,
            'has_file': has_file,
            'on_file': bool(key_doc),
            'verified_on': key_doc.verified_on if key_doc else None,
            'expiry': key_doc.expiry_date if key_doc else None,
            # Identity docs (proof of ID/address) carry metadata captured during
            # onboarding and copied to the ClientKeyDocument at convert.
            'is_identity': key in IDENTITY_DOC_CATEGORIES,
            'meta_type': record.document_type if record else '',
            'meta_reference': record.document_reference if record else '',
            'meta_issue_date': record.issue_date if record else None,
            'meta_expiry_date': record.expiry_date if record else None,
        })
    total = len(items)
    provided_count = sum(1 for i in items if i['provided'])
    return items, {
        'all_provided': all_provided,
        'any_provided': any_provided,
        'portal_error': portal_error,
        'portal_status': portal_status,
        # Set when the client told the portal they act for a company that is
        # the real client (a director completing on the company's behalf).
        'portal_capacity': portal_capacity,
        'address_display': _format_address(member),
        'total_count': total,
        'provided_count': provided_count,
        'provided_pct': round(provided_count * 100 / total) if total else 0,
    }


# Onboarding item type -> the client key-document category that satisfies it.
IDENTITY_DOC_CATEGORIES = {
    'proof_id': 'proof_of_id',
    'proof_address': 'proof_of_address',
}


def _twelve_months_ago(today):
    """The date 12 calendar months before ``today`` (handles 29 Feb)."""
    try:
        return today.replace(year=today.year - 1)
    except ValueError:
        return today.replace(year=today.year - 1, day=28)


def _valid_on_file_key_docs(client, today):
    """For an existing client, the identity document record on file that already
    satisfies each onboarding item type — proof of ID/address provided within the
    last 12 calendar months and not past its expiry. Maps ``item_type`` to the
    ClientKeyDocument, so callers can link straight to the record we already hold.
    Empty when there is no client or no valid document."""
    if client is None:
        return {}
    cutoff = _twelve_months_ago(today)
    out = {}
    for item_type, category in IDENTITY_DOC_CATEGORIES.items():
        doc = (client.key_documents.filter(category=category)
               .order_by('-verified_on').first())
        if (doc and doc.verified_on and doc.verified_on >= cutoff
                and not (doc.expiry_date and doc.expiry_date < today)):
            out[item_type] = doc
    return out


def _valid_on_file_item_types(client, today):
    """The set of onboarding item types satisfied by a valid document on file —
    the keys of :func:`_valid_on_file_key_docs`."""
    return set(_valid_on_file_key_docs(client, today))


def _existing_client_key_docs(member, today):
    """For an existing-client member, the latest proof-of-id / proof-of-address on
    file with expiry, an 'expired' flag and a 'valid' flag (provided within the
    last 12 calendar months and not expired) — so identity docs that are still
    valid needn't be re-requested. Empty for new clients."""
    out = {}
    if not member.client_id:
        return out
    cutoff = _twelve_months_ago(today)
    for cat in ('proof_of_id', 'proof_of_address'):
        doc = (member.client.key_documents.filter(category=cat)
               .order_by('-verified_on').first())
        expired = bool(doc and doc.expiry_date and doc.expiry_date < today)
        recent = bool(doc and doc.verified_on and doc.verified_on >= cutoff)
        out[cat] = {
            'has': bool(doc),
            'expiry': doc.expiry_date if doc else None,
            'verified_on': doc.verified_on if doc else None,
            'expired': expired,
            'valid': bool(doc) and recent and not expired,
        }
    return out


def _add_existing_client_member(group, client, is_lead, user):
    """Add an onboarding member backed by an *existing* client record. The member
    reuses that ClientContactDetails (convert never creates a duplicate) and its
    contact fields are copied across so the member card and conflict check work
    without re-keying.

    Proof of ID/address still valid on file (verified within 12 months, not
    expired) are dropped from the requested documents by default — we already hold
    them, so we don't ask again. Everything else (declarations, terms) is still
    requested. Staff can re-tick any of them on the detail page."""
    valid = _valid_on_file_item_types(client, timezone.localdate())
    required = ([k for k, _ in OnboardingItem.ITEM_CHOICES if k not in valid]
                if valid else [])
    return Onboarding.objects.create(
        group=group, client=client, is_lead=is_lead, created_by=user,
        client_name=client.name, email=client.email or '',
        dob=client.dob, occupation=client.occupation or '',
        address_line1=client.address_line1 or '',
        address_line2=client.address_line2 or '',
        county=client.county or '', postcode=client.postcode or '',
        contact_number=client.contact_number or '',
        required_documents=required,
        status=Onboarding.STATUS_COLLECTING,
    )


@login_required
def client_search_json(request):
    """Typeahead source for the 'existing client' picker on the onboarding start
    form. Returns up to 20 matches by name/email for ?q=."""
    q = request.GET.get('q', '').strip()
    clients = ClientContactDetails.objects.all()
    if q:
        clients = clients.filter(Q(name__icontains=q) | Q(email__icontains=q))
    clients = clients.order_by('name')[:20]
    return JsonResponse({'results': [
        {'id': c.id, 'name': c.name, 'email': c.email or ''} for c in clients
    ]})


@login_required
def onboarding_list(request):
    groups = (OnboardingGroup.objects
              .select_related('matter', 'created_by')
              .prefetch_related('members')
              .all())
    return render(request, 'onboarding_list.html', {
        'groups': groups,
        'portal_is_mock': portal.is_mock(),
    })


@login_required
@require_POST
def onboarding_start(request):
    """Start an onboarding group. Each client row is either a *new* client
    (name + email) or an *existing* client picked from the searchable dropdown
    (submitted as existing_client_id). The three lists are index-aligned, one
    entry per row."""
    names = request.POST.getlist('client_name')
    emails = request.POST.getlist('email')
    existing_ids = request.POST.getlist('existing_client_id')
    label = request.POST.get('label', '').strip()
    send = bool(request.POST.get('send_invite'))

    rows = []  # (mode, payload) preserving the on-screen order
    for idx in range(max(len(names), len(emails), len(existing_ids))):
        existing_id = (existing_ids[idx] if idx < len(existing_ids) else '').strip()
        name = (names[idx] if idx < len(names) else '').strip()
        email_addr = (emails[idx] if idx < len(emails) else '').strip()
        if existing_id:
            rows.append(('existing', existing_id))
        elif name and email_addr:
            rows.append(('new', (name, email_addr)))
    if not rows:
        messages.error(
            request, 'Add at least one client — a new one (name + email) or an existing one.')
        return redirect('onboarding_list')

    group = OnboardingGroup.objects.create(label=label, created_by=request.user)
    created = 0
    for idx, (mode, payload) in enumerate(rows):
        is_lead = (idx == 0)
        if mode == 'existing':
            client = ClientContactDetails.objects.filter(id=payload).first()
            if not client:
                continue
            # Existing client: the required documents are chosen automatically —
            # proof of ID/address still valid on file are skipped, everything else
            # is requested. Invited too when 'send' is ticked.
            member = _add_existing_client_member(group, client, is_lead, request.user)
            if send:
                _send_invite(request, member)
        else:
            # New client: request everything (nothing on file to reuse).
            name, email_addr = payload
            member = Onboarding.objects.create(
                group=group, client_name=name, email=email_addr,
                is_lead=is_lead, created_by=request.user)
            if send:
                _send_invite(request, member)
        created += 1

    if not created:
        group.delete()
        messages.error(request, 'Could not start onboarding — no valid clients were provided.')
        return redirect('onboarding_list')
    if not group.label:
        lead = group.members.order_by('-is_lead', 'timestamp').first()
        if lead:
            group.label = lead.client_name
            group.save(update_fields=['label'])
    messages.success(request, f'Onboarding started for {created} client(s).')
    return redirect('onboarding_detail', group.id)


@login_required
@require_POST
def onboarding_add_member(request, group_id):
    group = get_object_or_404(OnboardingGroup, id=group_id)
    existing_id = request.POST.get('existing_client_id', '').strip()
    if existing_id:
        client = ClientContactDetails.objects.filter(id=existing_id).first()
        if not client:
            messages.error(request, 'Could not find that existing client.')
            return redirect('onboarding_detail', group.id)
        member = _add_existing_client_member(group, client, False, request.user)
        if request.POST.get('send_invite'):
            _send_invite(request, member)
        else:
            messages.success(request, f'{client.name} added to the onboarding.')
        return redirect('onboarding_detail', group.id)

    name = request.POST.get('client_name', '').strip()
    email = request.POST.get('email', '').strip()
    if not name or not email:
        messages.error(request, 'Client name and email are both required.')
        return redirect('onboarding_detail', group.id)
    member = Onboarding.objects.create(
        group=group, client_name=name, email=email, created_by=request.user)
    if request.POST.get('send_invite'):
        _send_invite(request, member)
    else:
        messages.success(request, f'{name} added to the onboarding.')
    return redirect('onboarding_detail', group.id)


@login_required
@require_POST
def onboarding_edit_address(request, id):
    """Correct the address (and other contact details) held for a member — used
    when the address picked up from the ID/portal is wrong, so the conflict
    check and the converted client record carry the right address."""
    member = get_object_or_404(Onboarding, id=id)
    email = request.POST.get('email', '').strip()
    if email:
        member.email = email
    member.dob = _parse_date(request.POST.get('dob'))
    member.occupation = request.POST.get('occupation', '').strip()
    member.address_line1 = request.POST.get('address_line1', '').strip()
    member.address_line2 = request.POST.get('address_line2', '').strip()
    member.county = request.POST.get('county', '').strip()
    member.postcode = request.POST.get('postcode', '').strip()
    member.contact_number = request.POST.get('contact_number', '').strip()
    member.save(update_fields=['email', 'dob', 'occupation', 'address_line1',
                               'address_line2', 'county', 'postcode', 'contact_number'])
    messages.success(request, f'Details updated for {member.client_name}.')
    return redirect('onboarding_detail', member.group_id)


def _save_required_documents(request, member):
    """Persist the per-member 'documents to request' checklist from the detail
    page. Only known item types are stored; an empty selection falls back to
    'ask for everything' (see Onboarding.required_item_types)."""
    valid = [k for k, _ in portal.ONBOARDING_ITEMS]
    chosen = [k for k in request.POST.getlist('required_documents') if k in valid]
    member.required_documents = chosen
    member.save(update_fields=['required_documents'])


@login_required
@require_POST
def onboarding_set_required_docs(request, id):
    """Save which documents to request from a member without sending the invite —
    lets staff trim an existing client's list (e.g. drop proof of ID/address)
    before inviting."""
    member = get_object_or_404(Onboarding, id=id)
    _save_required_documents(request, member)
    messages.success(request, f'Document requirements saved for {member.client_name}.')
    return redirect('onboarding_detail', member.group_id)


@login_required
@require_POST
def onboarding_send_invite(request, id):
    member = get_object_or_404(Onboarding, id=id)
    if 'doc_requirements_submitted' in request.POST:
        _save_required_documents(request, member)
    _send_invite(request, member)
    return redirect('onboarding_detail', member.group_id)


@login_required
@require_POST
def onboarding_expire_invite(request, id):
    member = get_object_or_404(Onboarding, id=id)
    try:
        portal.expire_invite(member)
    except portal.PortalError as exc:
        messages.error(request, f'Could not expire the link: {exc}')
        return redirect('onboarding_detail', member.group_id)
    member.invite_expired_at = timezone.now()
    member.save(update_fields=['invite_expired_at'])
    messages.success(request, f'Invite link expired for {member.client_name}.')
    return redirect('onboarding_detail', member.group_id)


@login_required
@require_POST
def onboarding_send_all_invites(request, group_id):
    group = get_object_or_404(OnboardingGroup, id=group_id)
    for member in group.members.all():
        _send_invite(request, member)
    return redirect('onboarding_detail', group.id)


@login_required
def onboarding_detail(request, id):
    group = get_object_or_404(
        OnboardingGroup.objects.select_related('matter'), id=id)
    converted = group.status == OnboardingGroup.STATUS_CONVERTED

    members_ctx = []
    group_all_ready = True
    today = timezone.localdate()
    for member in group.members.order_by('-is_lead', 'timestamp'):
        items, flags = _member_progress(member)
        required_keys = set(member.required_item_types())
        doc_choices = [{'key': k, 'label': lbl, 'required': k in required_keys}
                       for k, lbl in portal.ONBOARDING_ITEMS]
        existing_docs = _existing_client_key_docs(member, today)

        if member.status != Onboarding.STATUS_CONVERTED:
            new_status = member.status
            if flags['all_provided'] and not flags['portal_error']:
                new_status = Onboarding.STATUS_READY
            elif flags['any_provided']:
                new_status = Onboarding.STATUS_COLLECTING
            if new_status != member.status:
                member.status = new_status
                member.save(update_fields=['status'])

        if not flags['all_provided']:
            group_all_ready = False

        conflict = member.conflict_checks.first()
        conflict_ok = bool(conflict) and (
            conflict.result == ConflictCheck.RESULT_CLEAR or conflict.acknowledged)
        # Split stored matches into blocking conflicts and those ruled out by a
        # differing DOB (default True keeps pre-DOB records counting as conflicts).
        all_matches = (conflict.matches or []) if conflict else []
        conflict_blocking = [m for m in all_matches if m.get('is_conflict', True)]
        conflict_ruled_out = [m for m in all_matches if not m.get('is_conflict', True)]
        members_ctx.append({
            'member': member,
            'items': items,
            'flags': flags,
            'conflict': conflict,
            'conflict_ok': conflict_ok,
            'conflict_blocking': conflict_blocking,
            'conflict_ruled_out': conflict_ruled_out,
            'is_existing': bool(member.client_id),
            'doc_choices': doc_choices,
            'required_count': len(required_keys),
            'existing_docs': existing_docs,
        })

    if not converted:
        new_status = (OnboardingGroup.STATUS_READY
                      if group_all_ready and members_ctx
                      else OnboardingGroup.STATUS_COLLECTING)
        if new_status != group.status:
            group.status = new_status
            group.save(update_fields=['status'])

    all_conflicts_ok = bool(members_ctx) and all(m['conflict_ok'] for m in members_ctx)
    # Only new clients get a record created; if every client is existing we're
    # just opening the file.
    has_new_clients = any(not m['is_existing'] for m in members_ctx)

    return render(request, 'onboarding_detail.html', {
        'group': group,
        'members': members_ctx,
        'portal_is_mock': portal.is_mock(),
        'all_conflicts_ok': all_conflicts_ok,
        'has_new_clients': has_new_clients,
    })


@login_required
@require_POST
def onboarding_run_conflict_check(request, id):
    """Run an extensive conflict check for one member across existing clients,
    opposing parties and authorised parties, and log it. Required (and gating)
    for every member before the group can be converted to a matter."""
    member = get_object_or_404(Onboarding, id=id)
    if not _format_address(member):
        messages.error(
            request, f"Enter {member.client_name}'s address before running the conflict check.")
        return redirect('onboarding_detail', member.group_id)
    matches = run_conflict_check(member.client_name, dob=member.dob)
    blocking = [m for m in matches if m.get('is_conflict')]
    ruled_out = len(matches) - len(blocking)
    result = (ConflictCheck.RESULT_POTENTIAL if blocking
              else ConflictCheck.RESULT_CLEAR)
    ConflictCheck.objects.create(
        searched_name=member.client_name,
        searched_dob=member.dob,
        result=result,
        matches=matches,
        onboarding=member,
        performed_by=request.user,
    )
    dob_note = f' ({ruled_out} ruled out by date of birth)' if ruled_out else ''
    if blocking:
        messages.warning(
            request,
            f'Conflict check for {member.client_name} found {len(blocking)} '
            f'potential match(es) — review and acknowledge before converting.{dob_note}')
    elif not member.dob:
        messages.success(
            request, f'Conflict check for {member.client_name} — no conflicts found. '
            f'Add a date of birth to sharpen the check.{dob_note}')
    else:
        messages.success(
            request, f'Conflict check for {member.client_name} — no conflicts found.{dob_note}')
    return redirect('onboarding_detail', member.group_id)


@login_required
@require_POST
def onboarding_acknowledge_conflict(request, id):
    member = get_object_or_404(Onboarding, id=id)
    conflict = member.conflict_checks.first()
    if conflict and conflict.result == ConflictCheck.RESULT_POTENTIAL:
        conflict.acknowledged = True
        conflict.acknowledgement_note = request.POST.get('conflict_ack_note', '').strip()
        conflict.save(update_fields=['acknowledged', 'acknowledgement_note'])
        messages.success(request, f'Potential conflict for {member.client_name} acknowledged.')
    return redirect('onboarding_detail', member.group_id)


@login_required
@require_POST
def onboarding_upload_doc(request, id, item_type):
    """Upload (or replace) a document on the client's behalf — e.g. when they
    email it in rather than using the portal."""
    member = get_object_or_404(Onboarding, id=id)
    if item_type not in ITEM_LABELS:
        messages.error(request, 'Unknown document type.')
        return redirect('onboarding_detail', member.group_id)
    upload = request.FILES.get('document')
    if not upload:
        messages.error(request, 'Choose a file to upload.')
        return redirect('onboarding_detail', member.group_id)
    if os.path.splitext(upload.name)[1].lower() not in ALLOWED_DOC_EXTENSIONS:
        messages.error(request, 'Allowed file types: PDF, JPG, PNG, HEIC.')
        return redirect('onboarding_detail', member.group_id)
    if upload.size > MAX_DOC_BYTES:
        messages.error(request, 'File is too large (max 25MB).')
        return redirect('onboarding_detail', member.group_id)

    item, _ = OnboardingItem.objects.get_or_create(
        onboarding=member, item_type=item_type)
    item.file = upload
    item.save()
    messages.success(request, f'{ITEM_LABELS[item_type]} uploaded for {member.client_name}.')
    return redirect('onboarding_detail', member.group_id)


@login_required
@require_POST
def onboarding_save_doc_details(request, id, item_type):
    """Capture identity-document metadata (type / reference / issue / expiry) while
    onboarding, so the ClientKeyDocument created at convert is complete — with an
    expiry to track — rather than skeletal. Identity documents only."""
    member = get_object_or_404(Onboarding, id=id)
    if item_type not in IDENTITY_DOC_CATEGORIES:
        messages.error(request, 'Details can only be recorded for identity documents.')
        return redirect('onboarding_detail', member.group_id)
    item, _ = OnboardingItem.objects.get_or_create(
        onboarding=member, item_type=item_type)
    item.document_type = request.POST.get('document_type', '').strip()
    item.document_reference = request.POST.get('document_reference', '').strip()
    item.issue_date = _parse_date(request.POST.get('issue_date'))
    item.expiry_date = _parse_date(request.POST.get('expiry_date'))
    item.save(update_fields=['document_type', 'document_reference',
                             'issue_date', 'expiry_date'])
    messages.success(
        request, f'{ITEM_LABELS.get(item_type, item_type)} details saved for {member.client_name}.')
    return redirect('onboarding_detail', member.group_id)


@login_required
def onboarding_preview_doc(request, id, item_type):
    """Stream a staff-uploaded ("office copy") document inline for review
    (login-protected; never a public URL)."""
    item = get_object_or_404(OnboardingItem, onboarding_id=id, item_type=item_type)
    if not item.file:
        raise Http404('No document on file for this item.')
    content_type, _ = mimetypes.guess_type(item.file.name)
    return FileResponse(item.file.open('rb'),
                        content_type=content_type or 'application/octet-stream')


@login_required
def onboarding_preview_portal_doc(request, id, item_type):
    """Preview the document the client uploaded through the portal ("client
    copy"). Fetches it from the portal in real mode; shows a clear placeholder
    in preview mode (no portal connected, so no client files exist yet)."""
    member = get_object_or_404(Onboarding, id=id)
    if item_type not in ITEM_LABELS:
        raise Http404('Unknown document type.')
    if not storage.is_configured():
        html = (
            '<!doctype html><html><body style="font-family:Arial,Helvetica,'
            'sans-serif;max-width:540px;margin:48px auto;color:#374151;'
            'line-height:1.55;">'
            f'<h2 style="color:#111827;">{escape(ITEM_LABELS[item_type])} '
            f'— client upload</h2>'
            f'<p>This is <strong>preview mode</strong>. The copy '
            f'{escape(member.client_name)} uploads through the client portal '
            'will appear here once the intake SharePoint library is connected.'
            '</p></body></html>'
        )
        return HttpResponse(html)
    # Prefer the exact SharePoint item id the portal reports; persist it so later
    # reads (and the matter page) resolve by id. If the portal is unreachable or
    # silent on this item, fall back to the id we stored earlier — that also covers
    # declaration/terms PDFs, whose filenames the folder-listing fallback below
    # can't match by prefix. The {type}- prefix listing is the last resort.
    item_id = ''
    try:
        submission = portal.get_submission(member)
        item_id = ((submission.get('files') or {}).get(item_type) or {}).get('item_id', '')
    except portal.PortalError:
        pass
    if item_id:
        _persist_item_id(member, item_type, item_id)
    else:
        item_id = (OnboardingItem.objects
                   .filter(onboarding=member, item_type=item_type)
                   .values_list('sharepoint_item_id', flat=True).first() or '')
    try:
        if item_id:
            content, content_type, filename = storage.read_document_by_id(item_id)
        else:
            content, content_type, filename = storage.read_document(member, item_type)
    except storage.OnboardingStorageError as exc:
        return HttpResponse(f'Could not load the client document: {exc}',
                            status=502, content_type='text/plain')
    return FileResponse(io.BytesIO(content),
                        content_type=content_type or 'application/octet-stream',
                        filename=filename)


@login_required
@require_POST
def onboarding_convert_to_matter(request, id):
    """Create the client records for the group, then hand off to the normal Open
    File page with those clients pre-selected so the matter is opened there. The
    matter is linked back to the group when that form is submitted."""
    group = get_object_or_404(OnboardingGroup, id=id)
    if group.status == OnboardingGroup.STATUS_CONVERTED:
        messages.info(request, 'This onboarding has already been converted.')
        return redirect('onboarding_detail', group.id)

    members = list(group.members.order_by('-is_lead', 'timestamp'))
    if not members:
        messages.error(request, 'Add at least one client before converting.')
        return redirect('onboarding_detail', group.id)
    # Existing members already carry a client_id; new members get a record created
    # below. Captured now so the success message reflects create-vs-open.
    created_new = sum(1 for m in members if not m.client_id)

    # Conflict-of-interest gate: every member must have a check run, and any
    # potential conflict acknowledged, before clients are created.
    for member in members:
        conflict = member.conflict_checks.first()
        if conflict is None:
            messages.error(
                request, f'Run a conflict check for {member.client_name} before converting.')
            return redirect('onboarding_detail', group.id)
        if (conflict.result == ConflictCheck.RESULT_POTENTIAL
                and not conflict.acknowledged):
            messages.error(
                request, f'Acknowledge the potential conflict for {member.client_name} before converting.')
            return redirect('onboarding_detail', group.id)

    # Fetch each member's portal submission once (best-effort, outside the
    # client-creation transaction so a portal hiccup can't block a conversion or
    # hold the DB transaction open across network I/O). It drives two things: the
    # Client Care snapshot (durable SharePoint ids, so the matter home page needs
    # no live call) and the set of documents the client provided, which is what
    # records the KYC declarations below.
    member_submissions = {}
    for member in members:
        try:
            submission = portal.get_submission(member)
        except portal.PortalError:
            submission = None
        member_submissions[member.id] = submission
        if submission is not None:
            _snapshot_portal_documents(member, submission)

    today = timezone.localdate()
    try:
        with transaction.atomic():
            for member in members:
                provided = _provided_item_types(
                    member, member_submissions.get(member.id))
                if member.client_id:
                    # Existing client (picked at the start, or a retry of this
                    # convert): reuse the record, never duplicate it. Record only
                    # the freshly collected declarations and only ever set flags
                    # True — never downgrade an existing client.
                    client = member.client
                    fields = []
                    if 'pep' in provided and not client.pep_signed:
                        client.pep_signed = True
                        fields.append('pep_signed')
                    if 'source_of_funds' in provided and not client.source_of_funds_signed:
                        client.source_of_funds_signed = True
                        fields.append('source_of_funds_signed')
                    if 'terms_of_engagement' in provided and not client.terms_of_engagement_signed:
                        client.terms_of_engagement_signed = True
                        fields.append('terms_of_engagement_signed')
                    if 'proof_id' in provided:
                        if not client.id_verified:
                            client.id_verified = True
                            fields.append('id_verified')
                        client.date_of_last_aml = today
                        fields.append('date_of_last_aml')
                    if fields:
                        client.save(update_fields=fields)
                else:
                    # New client — create the record from the collected details.
                    client = ClientContactDetails.objects.create(
                        name=member.client_name,
                        email=member.email,
                        dob=member.dob,
                        occupation=member.occupation,
                        address_line1=member.address_line1,
                        address_line2=member.address_line2,
                        county=member.county,
                        postcode=member.postcode,
                        contact_number=member.contact_number,
                        id_verified='proof_id' in provided,
                        date_of_last_aml=today if 'proof_id' in provided else None,
                        pep_signed='pep' in provided,
                        source_of_funds_signed='source_of_funds' in provided,
                        terms_of_engagement_signed='terms_of_engagement' in provided,
                        created_by=request.user,
                    )
                    member.client = client
                    member.save(update_fields=['client'])

                # Record any (re)collected identity documents, carrying the metadata
                # captured during onboarding (type/reference/issue/expiry) so the
                # record is complete. get_or_create keeps a repeated convert (same
                # day) from stacking duplicate rows.
                for item_type, category in (('proof_id', 'proof_of_id'),
                                            ('proof_address', 'proof_of_address')):
                    if item_type in provided:
                        meta = member.items.filter(item_type=item_type).first()
                        ClientKeyDocument.objects.get_or_create(
                            client=client,
                            category=category,
                            verified_on=today,
                            defaults={
                                'verified_by': request.user,
                                'document_type': meta.document_type if meta else '',
                                'document_reference': meta.document_reference if meta else '',
                                'issue_date': meta.issue_date if meta else None,
                                'expiry_date': meta.expiry_date if meta else None,
                                'notes': 'Provided via the client onboarding portal.',
                            },
                        )

                conflict = member.conflict_checks.first()
                if conflict and conflict.client_id is None:
                    conflict.client = client
                    conflict.save(update_fields=['client'])
    except Exception as exc:  # noqa: BLE001 - surface any failure to the user
        logger.exception('Onboarding client creation failed for group %s', group.id)
        messages.error(request, f'Could not create the client records: {exc}')
        return redirect('onboarding_detail', group.id)

    # Hand off to the Open File page with these clients pre-selected. The page
    # reads this and renders a hidden onboarding_group_id that links the matter
    # back to this group when the file is opened.
    primary = members[0]
    request.session['onboarding_prefill'] = {
        'group_id': group.id,
        'client1': primary.client_id,
        'additional': [m.client_id for m in members[1:]],
    }
    if created_new:
        msg = f'{created_new} client record(s) created — complete the new matter to finish.'
    else:
        msg = 'Clients already on file — complete the new matter to finish.'
    messages.success(request, msg)
    return redirect('new_file')


def link_group_to_matter(request, matter):
    """Called from the Open File view once a matter is created. If the submitted
    form carries an onboarding_group_id (rendered when the page was opened from a
    conversion), link the group to the new matter, mark it converted and notify
    the portal. Safe no-op for ordinary file opens."""
    group_id = request.POST.get('onboarding_group_id')
    if not group_id:
        return
    try:
        group = OnboardingGroup.objects.get(id=group_id)
    except (OnboardingGroup.DoesNotExist, ValueError, TypeError):
        return
    if group.status == OnboardingGroup.STATUS_CONVERTED:
        return

    group.matter = matter
    group.status = OnboardingGroup.STATUS_CONVERTED
    group.save(update_fields=['matter', 'status'])
    mc_rows = ensure_matter_clients(matter)
    for member in group.members.all():
        member.status = Onboarding.STATUS_CONVERTED
        member.save(update_fields=['status'])
        # Record the declarations collected in onboarding on this matter's
        # MatterClient (engagement checks are per file, not per client).
        mc = mc_rows.get(member.client_id)
        if mc is not None:
            try:
                submission = portal.get_submission(member)
            except portal.PortalError:
                submission = None
            apply_declarations(mc, _provided_item_types(member, submission), request.user)
        conflict = member.conflict_checks.first()
        if conflict and conflict.wip_id is None:
            conflict.wip = matter
            conflict.save(update_fields=['wip'])
        try:
            portal.attach_matter(member, matter.file_number)
        except portal.PortalError as exc:
            messages.warning(
                request, f'Matter opened, but the portal could not be notified for {member.client_name}: {exc}')
    messages.success(request, f'Matter linked to onboarding “{group.label or group.id}”.')
