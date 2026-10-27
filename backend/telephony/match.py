"""Match a Teams call's external phone number to a matter.

Phone numbers live as free-text ``contact_number`` on the client / other-side /
authorised-party models and are neither normalised nor indexed, so we build an
in-memory index once per sync run and match against a canonical (E.164) form of
the number. This mirrors how the Granola integration matches in-Python rather
than adding a denormalised column (which would be the upgrade path if realtime
matching or scale ever demanded it).
"""
import re
from collections import namedtuple

from backend.models import CallRecord, WIP

Candidate = namedtuple('Candidate', ['file_number', 'role', 'name'])

MatchResult = namedtuple(
    'MatchResult', ['file_number', 'role', 'ambiguous', 'candidates', 'reason'])

_WITHHELD_MARKERS = ('anonymous', 'restricted', 'withheld', 'unknown', 'private')

# Used to label a unique match and to break ties: a client beats an authorised
# party, which beats an other-side contact.
_ROLE_PRECEDENCE = {
    CallRecord.ROLE_CLIENT: 0,
    CallRecord.ROLE_AUTH_PARTY: 1,
    CallRecord.ROLE_OTHERSIDE: 2,
}


def normalize_phone(raw):
    """Best-effort UK phone-number normalisation to E.164 (e.g. +447700900123).

    Returns '' for empty, withheld/anonymous, or implausibly short values so
    that unusable numbers fall through to the review inbox.
    """
    if not raw:
        return ''
    text = str(raw).strip().lower()
    if any(marker in text for marker in _WITHHELD_MARKERS):
        return ''
    text = re.sub(r'^(tel|sip|callto):', '', text)  # drop URI schemes
    text = text.split('@', 1)[0]                     # drop sip host part
    has_plus = '+' in text
    digits = re.sub(r'\D', '', text)
    if not digits:
        return ''
    if digits.startswith('00'):        # international access code -> '+'
        digits = digits[2:]
        has_plus = True
    if has_plus:
        if digits.startswith('44'):
            return _uk(digits[2:])
        return '+' + digits if len(digits) >= 7 else ''  # non-UK international
    if digits.startswith('44'):
        return _uk(digits[2:])
    if digits.startswith('0'):
        return _uk(digits[1:])
    return _uk(digits)                  # bare national number (e.g. from a PBX)


def _uk(national):
    national = national.lstrip('0')
    if len(national) < 7:
        return ''
    return '+44' + national


def national_key(normalized):
    """Last 9 significant digits — tolerates +44 vs 0 vs missing country code."""
    digits = re.sub(r'\D', '', normalized or '')
    return digits[-9:] if len(digits) >= 9 else ''


def build_matter_phone_index():
    """Map ``normalized number -> [Candidate]`` across every matter.

    Sources by role: ``client1`` + ``additional_clients`` (client), ``other_side``
    (other side), ``authorised_party1/2`` (authorised party). Free-30 attendees
    are excluded — they feed the Free-30 route, not matter matching.
    """
    index = {}
    matters = (WIP.objects
               .select_related('client1', 'other_side',
                               'authorised_party1', 'authorised_party2')
               .prefetch_related('additional_clients'))
    for matter in matters:
        if not matter.file_number:
            continue
        for client in matter.all_clients:
            _add(index, matter, client, CallRecord.ROLE_CLIENT)
        _add(index, matter, matter.other_side, CallRecord.ROLE_OTHERSIDE)
        _add(index, matter, matter.authorised_party1, CallRecord.ROLE_AUTH_PARTY)
        _add(index, matter, matter.authorised_party2, CallRecord.ROLE_AUTH_PARTY)
    return index


def _add(index, matter, party, role):
    if party is None:
        return
    number = normalize_phone(getattr(party, 'contact_number', ''))
    if not number:
        return
    index.setdefault(number, []).append(Candidate(
        file_number=matter.file_number, role=role,
        name=getattr(party, 'name', '') or ''))


def match_call(normalized, index, *, allow_otherside_only=False):
    """Resolve a normalized external number to a matter.

    A single matter -> ``file_number`` set, ``ambiguous`` False. Multiple matters
    -> ``ambiguous`` True with a ``candidates`` pick-list. An other-side-only
    match (unless ``allow_otherside_only``) or no match -> empty ``file_number``
    with a reason, so the call lands in the review inbox.
    """
    if not normalized:
        return MatchResult('', '', False, [], 'withheld or unrecognised number')

    candidates = index.get(normalized)
    if not candidates:
        nk = national_key(normalized)
        if nk:
            candidates = [c for num, cs in index.items()
                          for c in cs if national_key(num) == nk]
    if not candidates:
        return MatchResult('', '', False, [], 'no matter matched this number')

    # Collapse to distinct matters, keeping the highest-precedence role reached.
    by_matter = {}
    for c in candidates:
        cur = by_matter.get(c.file_number)
        if cur is None or _ROLE_PRECEDENCE[c.role] < _ROLE_PRECEDENCE[cur.role]:
            by_matter[c.file_number] = c
    distinct = sorted(by_matter.values(), key=lambda c: c.file_number)

    if len(distinct) > 1:
        payload = [_payload(c) for c in distinct]
        return MatchResult('', '', True, payload,
                           f'number matches {len(distinct)} matters — pick one')

    only = distinct[0]
    if only.role == CallRecord.ROLE_OTHERSIDE and not allow_otherside_only:
        return MatchResult('', '', False, [_payload(only)],
                           'matched an other-side contact — confirm the matter')
    return MatchResult(only.file_number, only.role, False, [],
                       f'matched {only.role} on {only.file_number}')


def _payload(candidate):
    return {'file_number': candidate.file_number, 'role': candidate.role,
            'name': candidate.name}
