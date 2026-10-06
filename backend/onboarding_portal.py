"""Thin client for the external client onboarding portal (separate FastAPI app).

The office only ever calls the portal *outbound* — it never accepts inbound
connections from it. When ONBOARDING_PORTAL_BASE_URL is unset the client runs in
mock mode so the staff console works before the portal is deployed.

See plans/lets-plan-for-separate-bubbly-pony.md for the full architecture.
"""
import logging

import requests
from django.conf import settings

logger = logging.getLogger('backend')

# The documents/declarations a client provides during onboarding. Order is the
# display order on the status board. Keep in step with OnboardingItem.ITEM_CHOICES.
ONBOARDING_ITEMS = [
    ('proof_id', 'Proof of ID'),
    ('proof_address', 'Proof of address'),
    ('selfie_id', 'Selfie with ID'),
    ('source_of_funds', 'Source of funds declaration'),
    ('pep', 'PEP declaration'),
    ('terms_of_engagement', 'Terms of engagement'),
]

# Portal-side state for a single item. The portal only ever forwards documents
# that passed its malware scan, so the office sees just 'awaited' (not provided
# yet) or 'provided' (uploaded + clean, ready to KYC-accept). KYC acceptance is
# tracked office-side.
PORTAL_STATUSES = ('awaited', 'provided')

_TIMEOUT = 15


class PortalError(Exception):
    """Raised when the portal cannot be reached or returns an error."""


def _portal_error(exc):
    """Build a PortalError whose message carries the portal's own ``detail``
    (a string, or for 422s a list of ``{loc, msg}``) so staff see *why* a call
    was refused — e.g. "422 email: value is not a valid email address" — rather
    than a bare status line."""
    resp = getattr(exc, 'response', None)
    if resp is None:
        return PortalError(str(exc))
    try:
        body = resp.json()
    except ValueError:
        body = None
    detail = body.get('detail') if isinstance(body, dict) else body
    if isinstance(detail, list):
        parts = []
        for err in detail:
            if not isinstance(err, dict):
                continue
            loc = [str(x) for x in err.get('loc', []) if x != 'body']
            msg = str(err.get('msg', '')).replace('Value error, ', '', 1)
            parts.append(f'{loc[-1]}: {msg}' if loc else msg)
        detail = '; '.join(p for p in parts if p)
    if not isinstance(detail, str) or not detail.strip():
        detail = (resp.text or '').strip()[:200] or (resp.reason or '')
    return PortalError(f'{resp.status_code} {detail}'.strip())


def _base_url():
    return (getattr(settings, 'ONBOARDING_PORTAL_BASE_URL', '') or '').rstrip('/')


def is_mock():
    """True when no portal is configured and we serve mock data instead."""
    return not _base_url()


def _headers():
    return {
        'X-Internal-Api-Key': getattr(settings, 'ONBOARDING_PORTAL_API_KEY', ''),
        'Content-Type': 'application/json',
    }


def create_invite(onboarding):
    """Ask the portal to mint a single-use magic link. Returns the portal's
    response: ``invite_id``, ``submission_id``, ``expires_at`` and ``redeem_url``
    (the link; the office delivers it — the portal does not email it)."""
    if is_mock():
        logger.info('Onboarding portal (mock): create_invite for %s', onboarding.client_ref)
        public = (getattr(settings, 'ONBOARDING_PORTAL_PUBLIC_URL', '') or '').rstrip('/')
        return {
            'submission_id': f'mock-{onboarding.client_ref}',
            'link': f'{public}/onboard/{onboarding.client_ref}',
        }
    try:
        resp = requests.post(
            f'{_base_url()}/invites',
            json={
                'client_name': onboarding.client_name,
                'email': onboarding.email,
                'client_ref': onboarding.client_ref,
                # The documents/declarations this link should collect. The portal
                # shows only these; omit/empty means all (see required_item_types).
                'required_documents': onboarding.required_item_types(),
            },
            headers=_headers(),
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        logger.warning('Onboarding portal create_invite failed: %s', exc)
        raise _portal_error(exc)


def get_submission(onboarding):
    """Return the normalised submission for this onboarding (see
    :func:`_normalise_submission`): per-item status, file ids, the client's
    typed current address, and the portal-side status.

    ``address`` is what the client typed before uploading proof of address
    (the portal refuses that upload until an address is recorded), so the
    conflict check and convert step can pre-fill from it. In mock mode there is
    none.

    In mock mode, once an invite has been sent every item is reported as
    ``provided`` so the console is exercisable end to end; before that they are
    ``awaited``.
    """
    if is_mock():
        portal_status = 'provided' if onboarding.invite_sent_at else 'awaited'
        return {
            'items': {key: portal_status for key, _ in ONBOARDING_ITEMS},
            'address': {},
            'files': {},
            'status': 'submitted' if onboarding.invite_sent_at else 'invited',
            'capacity': {},
        }
    # No submission yet (invite not minted) — nothing to fetch.
    if not onboarding.portal_submission_id:
        return {'items': {}, 'address': {}, 'files': {}, 'status': '', 'capacity': {}}
    try:
        resp = requests.get(
            f'{_base_url()}/submissions/{onboarding.portal_submission_id}',
            headers=_headers(),
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return _normalise_submission(resp.json())
    except requests.RequestException as exc:
        logger.warning('Onboarding portal get_submission failed: %s', exc)
        raise _portal_error(exc)


def _normalise_submission(data):
    """Adapt the portal's submission shape to what the office consumes.

    The office exposes, per type:
      - items:   {type: 'provided'|'awaited'}
      - files:   {type: {'item_id': ..., 'path': ...}}  for direct SharePoint reads
      - address: {address_line1, address_line2, county, postcode} the client
                 typed (same field names as ClientContactDetails), or {}.
      - status:  the portal's submission status — 'invited', 'in_progress',
                 'submitted' (the client pressed Submit) or 'accepted'.
      - capacity: {acting_for: 'self'|'company', company_name, company_number,
                 signatory_role} — who completed it; {} until told. A director
                 completing for a company that is the client shows up here.

    Documents and declarations differ:
      - documents:    provided when scan_state == 'clean'; id = sharepoint_item_id
                      (+ a sharepoint_path).
      - declarations: a rendered PDF, no scan_state/path; id = pdf_item_id, which
                      is null until the render+upload succeeds — so it's only
                      'provided' once that id exists.
    """
    items = {}
    files = {}

    for entry in data.get('documents') or []:
        dtype = entry.get('type')
        if not dtype:
            continue
        items[dtype] = 'provided' if entry.get('scan_state') == 'clean' else 'awaited'
        item_id = entry.get('sharepoint_item_id') or ''
        path = entry.get('sharepoint_path') or ''
        if item_id or path:
            files[dtype] = {'item_id': item_id, 'path': path}

    for entry in data.get('declarations') or []:
        dtype = entry.get('type')
        if not dtype:
            continue
        pdf_item_id = entry.get('pdf_item_id') or ''  # null until upload succeeds
        items[dtype] = 'provided' if pdf_item_id else 'awaited'
        if pdf_item_id:
            files[dtype] = {'item_id': pdf_item_id, 'path': ''}

    # Terms of engagement: a single block (agreement + live selfie + signature).
    # Provided once accepted. The portal renders an acceptance certificate PDF
    # for both signing methods (``acceptance_item_id``) — that is the evidence we
    # surface as the "Client copy"; the wet-ink signed scan
    # (``signed_doc_item_id``) is the fallback if the certificate id is missing.
    terms = data.get('terms')
    if terms:
        cert_id = terms.get('acceptance_item_id') or terms.get('signed_doc_item_id') or ''
        accepted = bool(terms.get('agreed_at') or cert_id)
        items['terms_of_engagement'] = 'provided' if accepted else 'awaited'
        if cert_id:
            files['terms_of_engagement'] = {'item_id': cert_id, 'path': ''}

    return {
        'items': items,
        'address': data.get('address') or {},
        'files': files,
        'status': data.get('status') or '',
        'capacity': data.get('capacity') or {},
    }


def expire_invite(onboarding):
    """Expire the client's active magic link via the portal."""
    if is_mock():
        logger.info('Onboarding portal (mock): expire_invite for %s', onboarding.client_ref)
        return
    invite_id = onboarding.portal_invite_id or onboarding.portal_submission_id
    if not invite_id:
        raise PortalError('No invite id stored to expire.')
    try:
        resp = requests.post(
            f'{_base_url()}/invites/{invite_id}/expire',
            headers=_headers(),
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning('Onboarding portal expire_invite failed: %s', exc)
        raise _portal_error(exc)


def attach_matter(onboarding, matter_ref):
    """Tell the portal that this onboarding now belongs to a real matter."""
    if is_mock():
        logger.info('Onboarding portal (mock): attach_matter %s -> %s',
                    onboarding.client_ref, matter_ref)
        return
    try:
        resp = requests.patch(
            f'{_base_url()}/submissions/{onboarding.portal_submission_id}',
            json={'matter_ref': matter_ref},
            headers=_headers(),
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning('Onboarding portal attach_matter failed: %s', exc)
        raise _portal_error(exc)
