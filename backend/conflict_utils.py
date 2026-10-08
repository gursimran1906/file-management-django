"""Conflict-of-interest checking for client onboarding.

Before a firm takes on a new client the SRA (Code of Conduct for Firms, rule
6.2) requires a search of the firm's records to confirm it is not already
acting for, or against, that person on a related matter. ``run_conflict_check``
performs that search across the three party tables that make up the firm's
record of who it deals with:

* opposing parties (``OthersideDetails``) - the clearest conflict: the new
  client is already an opponent on another matter;
* existing clients (``ClientContactDetails``) - duplicate / client-to-client;
* authorised parties (``AuthorisedParties``).

Email correspondence is deliberately NOT searched - it is not a party-to-matter
record and produces heavy false positives that would weaken a blocking check.

Matching is by name, refined by date of birth. To avoid missed conflicts we
cast a wide net on the name (a full-name match OR a single shared name part),
then use DOB to separate true hits from coincidental name overlaps:

* DOB present on both records and DIFFERENT -> ruled out (not the same person);
* DOB present on both and the SAME            -> confirmed conflict;
* DOB missing on either side                  -> kept as a conflict to review
  (we never silently drop a name match we cannot rule out by DOB).

Each returned match carries ``is_conflict`` (False only when ruled out by DOB),
so the caller blocks on, and counts, the conflicts and can show the rest as
"ruled out by DOB" for transparency. The function is pure (no writes) so it can
be unit tested directly; the audit record is created by the view that calls it.
"""

import re
from datetime import date, datetime

from django.db.models import Q

from .models import (
    AuthorisedParties,
    ClientContactDetails,
    OthersideDetails,
    WIP,
)

SOURCE_OPPOSING = 'opposing_party'
SOURCE_CLIENT = 'client'
SOURCE_AUTHORISED = 'authorised_party'

# Opposing-party matches are the real conflict of interest, so they sort first.
_SOURCE_PRIORITY = {SOURCE_OPPOSING: 0, SOURCE_CLIENT: 1, SOURCE_AUTHORISED: 2}
_SOURCE_LABELS = {
    SOURCE_OPPOSING: 'Opposing party',
    SOURCE_CLIENT: 'Existing client',
    SOURCE_AUTHORISED: 'Authorised party',
}

DOB_MATCH = 'match'
DOB_DIFFERS = 'differs'
DOB_UNKNOWN = 'unknown'


def normalise_name(name):
    """Lower-case, trimmed, single-spaced form used for comparison."""
    return re.sub(r'\s+', ' ', (name or '').strip().lower())


def _tokens(name):
    return set(re.findall(r'[a-z0-9]+', (name or '').lower()))


def _coerce_date(value):
    """Accept a date, datetime or ISO 'YYYY-MM-DD' string; else None."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], '%Y-%m-%d').date()
    except ValueError:
        return None


def _name_match_strength(query_norm, query_tokens, candidate_name):
    """'full', 'partial' or None for how well a candidate name matches.

    full    - exact, substring either way ("John" within "John Smith"), or every
              word of the shorter multi-word name is present (so "Smith, John"
              matches "John Smith").
    partial - shares at least one significant (2+ char) word but is not a full
              match (e.g. only a surname or only a forename in common).
    """
    cand_norm = normalise_name(candidate_name)
    if not cand_norm or not query_norm:
        return None
    if query_norm == cand_norm or query_norm in cand_norm or cand_norm in query_norm:
        return 'full'
    cand_tokens = _tokens(candidate_name)
    if query_tokens and cand_tokens:
        smaller, larger = sorted((query_tokens, cand_tokens), key=len)
        if len(smaller) >= 2 and smaller.issubset(larger):
            return 'full'
    if {t for t in (query_tokens & cand_tokens) if len(t) >= 2}:
        return 'partial'
    return None


def _dob_status(query_dob, candidate_dob):
    if query_dob and candidate_dob:
        return DOB_MATCH if query_dob == candidate_dob else DOB_DIFFERS
    return DOB_UNKNOWN


def _party_detail(obj):
    """Short disambiguating string (address / postcode / email)."""
    pieces = [
        getattr(obj, 'address_line1', '') or '',
        getattr(obj, 'postcode', '') or '',
        getattr(obj, 'email', '') or '',
    ]
    return ' · '.join(p for p in pieces if p)


def _build_match(source, obj, file_numbers, strength, dob_status, candidate_dob):
    # Ruled out only when DOBs are present on both records and differ.
    is_conflict = dob_status != DOB_DIFFERS
    return {
        'source': source,
        'source_label': _SOURCE_LABELS.get(source, source),
        'id': obj.id,
        'name': obj.name or '',
        'matters': sorted(fn for fn in file_numbers if fn),
        'detail': _party_detail(obj),
        'match_strength': strength,
        'dob_status': dob_status,
        'dob': candidate_dob.isoformat() if candidate_dob else '',
        'is_conflict': is_conflict,
    }


def run_conflict_check(name, dob=None):
    """Search the party tables for possible conflicts with ``name``/``dob``.

    Returns a list of match dicts (conflicts first, opposing parties before
    clients). Each carries ``is_conflict`` - False only for name matches ruled
    out because the date of birth differs. An empty list means the name is
    clear; a list with no ``is_conflict`` entries means every name match was
    ruled out by DOB.
    """
    query_norm = normalise_name(name)
    if not query_norm:
        return []
    query_tokens = _tokens(name)
    query_dob = _coerce_date(dob)

    # Cheap DB prefilter: any record sharing a significant word with the query.
    # Refinement (word order, substring, single-part, DOB) happens in Python.
    name_filter = Q()
    for token in query_tokens:
        if len(token) >= 2:
            name_filter |= Q(name__icontains=token)
    if not name_filter:
        name_filter = Q(name__icontains=query_norm)

    results = []

    def consider(source, obj, file_numbers, candidate_dob):
        strength = _name_match_strength(query_norm, query_tokens, obj.name)
        if not strength:
            return
        status = _dob_status(query_dob, _coerce_date(candidate_dob))
        results.append(_build_match(
            source, obj, file_numbers, strength, status, _coerce_date(candidate_dob)))

    for other in OthersideDetails.objects.filter(name_filter):
        file_numbers = WIP.objects.filter(other_side=other).exclude(
            file_number__isnull=True).values_list('file_number', flat=True)
        consider(SOURCE_OPPOSING, other, list(file_numbers),
                 getattr(other, 'dob', None))

    for client in ClientContactDetails.objects.filter(name_filter):
        file_numbers = WIP.objects.filter(
            Q(client1=client) | Q(additional_clients=client)
        ).exclude(file_number__isnull=True).values_list(
            'file_number', flat=True).distinct()
        consider(SOURCE_CLIENT, client, list(file_numbers),
                 getattr(client, 'dob', None))

    for party in AuthorisedParties.objects.filter(name_filter):
        file_numbers = WIP.objects.filter(
            Q(authorised_party1=party) | Q(authorised_party2=party)
        ).exclude(file_number__isnull=True).values_list(
            'file_number', flat=True).distinct()
        consider(SOURCE_AUTHORISED, party, list(file_numbers),
                 getattr(party, 'dob', None))

    # Conflicts first; then opposing > client > authorised; full before partial.
    results.sort(key=lambda m: (
        not m['is_conflict'],
        _SOURCE_PRIORITY.get(m['source'], 9),
        m['match_strength'] == 'partial',
        m['name'].lower()))
    return results
