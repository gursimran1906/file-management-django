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
    """Ask the portal to mint a single-use magic link and email it to the client.
    Returns a dict containing at least ``submission_id``."""
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
        raise PortalError(str(exc))


def get_submission(onboarding):
    """Return ``{'items': {item_type: portal_status}}`` for this onboarding.

    The real portal also returns ``address`` — the address the client typed in
    (verified by their proof-of-address upload) — which the conflict check and
    convert step use. In mock mode there is none.

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
        }
    # No submission yet (invite not minted) — nothing to fetch.
    if not onboarding.portal_submission_id:
        return {'items': {}, 'address': {}, 'files': {}}
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
        raise PortalError(str(exc))


def _normalise_submission(data):
    """Adapt the portal's submission shape to what the office consumes.

    The office exposes, per type:
      - items:   {type: 'provided'|'awaited'}
      - files:   {type: {'item_id': ..., 'path': ...}}  for direct SharePoint reads
      - address: the client's details, if the portal returns them.

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
    # Provided once accepted; the acceptance certificate PDF is the evidence we
    # surface as the "Client copy".
    terms = data.get('terms')
    if terms:
        cert_id = (terms.get('acceptance_certificate_item_id')
                   or terms.get('acceptance_certificate_id')
                   or terms.get('certificate_item_id')
                   or terms.get('signed_doc_item_id')
                   or terms.get('signed_document_item_id') or '')
        accepted = bool(terms.get('agreed_at') or terms.get('accepted') or cert_id)
        items['terms_of_engagement'] = 'provided' if accepted else 'awaited'
        if cert_id:
            files['terms_of_engagement'] = {'item_id': cert_id, 'path': ''}
        elif accepted:
            logger.info('Terms block present but no recognised certificate id; '
                        'keys: %s', list(terms.keys()))

    return {'items': items, 'address': data.get('address') or {}, 'files': files}


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
        raise PortalError(str(exc))


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
        raise PortalError(str(exc))
