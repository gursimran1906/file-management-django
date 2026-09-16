"""Parse the matter / billing metadata that fee earners encode in note titles.

Title template given to fee earners (as a Granola note-title template):

    [A12345] Subject of the call        -> matter A12345, charged (default)
    [A12345 NC] Subject of the call     -> matter A12345, NOT charged
    [A12345/NC] Subject                 -> same; separator may be space or slash

The bracketed code is parsed out; the remaining text becomes the subject line.
Titles with no recognisable code return ``file_number=None`` so the note is
routed to the central review inbox instead of being auto-created.
"""
import re
from dataclasses import dataclass
from datetime import time as dt_time

# File numbers in this system are short alphanumeric strings (WIP.file_number is
# max_length=10). The optional trailing flag marks the note as not charged.
_TITLE_CODE_RE = re.compile(
    r'\[\s*(?P<file_number>[A-Za-z0-9][A-Za-z0-9\-/]{0,9}?)'
    r'(?:[\s/]+(?P<flag>NC|NOCHARGE|NOT[\s_-]?CHARGED))?\s*\]',
    re.IGNORECASE,
)


@dataclass
class ParsedTitle:
    file_number: str | None     # None when no code was found
    is_charged: bool            # True unless an NC flag was present
    subject: str                # title with the code stripped out


def parse_title(title: str) -> ParsedTitle:
    """Extract the matter file number and charged flag from a note title."""
    raw = (title or '').strip()
    match = _TITLE_CODE_RE.search(raw)
    if not match:
        return ParsedTitle(file_number=None, is_charged=True, subject=raw)

    file_number = match.group('file_number').strip().upper()
    is_charged = match.group('flag') is None

    # Remove the matched code from the title to derive the subject line.
    subject = (raw[:match.start()] + raw[match.end():]).strip()
    # Tidy leftover separators left behind once the code is removed.
    subject = re.sub(r'^[\s\-:–—]+', '', subject).strip()

    return ParsedTitle(
        file_number=file_number,
        is_charged=is_charged,
        subject=subject or raw,
    )


# --- File number in the note BODY ---------------------------------------------
#
# Fee earners record the matter file number in the note body (e.g. via a Granola
# note template), either as a bracketed code or a labelled line:
#
#     [ABC0010001]            -> matter ABC0010001, charged
#     [ABC0010001 NC]         -> matter ABC0010001, not charged
#     File number: ABC0010001
#     Matter no: ABC0010001 (NC)
#
# A bare token form is two-to-five letters followed by digits (file numbers here
# look like ABC0010001).

@dataclass
class FileRef:
    file_number: str | None     # None when nothing recognisable was found
    is_charged: bool            # True unless an NC flag was present


_NC_FLAG_RE = r'(?P<flag>NC|NO[\s-]?CHARGE|NOT[\s_-]?CHARGED)'

# "File number: ABC0010001", "Matter no ABC0010001", "Ref: ABC0010001 (NC)"
_FILE_LABEL_RE = re.compile(
    r'(?:file|matter|ref(?:erence)?)\s*(?:number|no\.?|ref(?:erence)?|#)?\s*[:#\-–]?\s*'
    r'(?P<file_number>[A-Za-z]{2,5}\d{4,8})'
    r'(?:[\s,(/-]+' + _NC_FLAG_RE + r')?',
    re.IGNORECASE,
)


def extract_file_ref(text: str) -> FileRef:
    """Find a matter file number (and NC flag) anywhere in a note body."""
    raw = text or ''
    # 1) Bracketed code, e.g. [ABC0010001] / [ABC0010001 NC].
    match = _TITLE_CODE_RE.search(raw)
    if match:
        return FileRef(match.group('file_number').strip().upper(),
                       match.group('flag') is None)
    # 2) Labelled line, e.g. "File number: ABC0010001".
    match = _FILE_LABEL_RE.search(raw)
    if match:
        return FileRef(match.group('file_number').strip().upper(),
                       match.group('flag') is None)
    return FileRef(file_number=None, is_charged=True)


# --- Meeting start / finish times in the note BODY ----------------------------
#
# Granola only exposes start/end times via a note's ``calendar_event`` (i.e. when
# the meeting was on someone's calendar). For ad-hoc recordings there is no end
# time, so fee earners record the window in the note body using a template line:
#
#     Start Time: 10:30 ; Finish Time: 11:15
#     Start Time: 10.30am
#     Finish Time: 12 noon
#
# We parse clock times only (no date); the ingest layer anchors them to the
# meeting date so the attendance-note unit count reflects the real duration.

# A clock time: "10", "10:30", "10.30", optional am/pm (with/without dots/space).
_CLOCK = r'(\d{1,2})(?:[:.](\d{2}))?\s*(a\.?m\.?|p\.?m\.?|noon|midnight)?'
_START_TIME_RE = re.compile(
    r'(?<![A-Za-z])start(?:\s*(?:time|ed|ing))?\s*[:\-–]?\s*' + _CLOCK, re.IGNORECASE)
_FINISH_TIME_RE = re.compile(
    r'(?<![A-Za-z])(?:finish|end)(?:\s*(?:time|ed|ing))?\s*[:\-–]?\s*' + _CLOCK,
    re.IGNORECASE)


@dataclass
class MeetingTimes:
    start: dt_time | None
    finish: dt_time | None


def _to_time(hour, minute, meridiem):
    """Build a ``datetime.time`` from a parsed clock match, or ``None`` if bogus."""
    h = int(hour)
    m = int(minute or 0)
    mer = (meridiem or '').replace('.', '').lower()
    if mer == 'noon':
        h, m = 12, 0
    elif mer == 'midnight':
        h, m = 0, 0
    elif mer == 'pm' and h < 12:
        h += 12
    elif mer == 'am' and h == 12:
        h = 0
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return dt_time(h, m)


def _match_time(regex, text):
    match = regex.search(text or '')
    if not match:
        return None
    return _to_time(match.group(1), match.group(2), match.group(3))


def parse_meeting_times(text: str) -> MeetingTimes:
    """Extract ``Start Time:`` / ``Finish Time:`` clock times from a note body.

    Returns ``MeetingTimes(start, finish)`` where each is a ``datetime.time`` or
    ``None`` when the corresponding labelled line is absent or left blank.
    """
    return MeetingTimes(
        start=_match_time(_START_TIME_RE, text),
        finish=_match_time(_FINISH_TIME_RE, text),
    )


# --- "Info of parties" parsing (Free 30 minute meetings) ----------------------
#
# Template given to fee earners as a Granola note section, e.g.:
#
#     ## Info of Parties
#     Party 1
#     - Name: John Smith
#     - Email: john@example.com
#     - Phone: 07123 456789
#     - Address: 1 High Street, London, Greater London, SW1A 1AA
#     Party 2
#     - Name: Jane Doe
#     ...
#
# Each party starts at a "Name:" label; subsequent label/value lines attach to it.

_UK_POSTCODE_RE = re.compile(
    r'\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b', re.IGNORECASE)

# Maps recognised labels (normalised) to attendee field names.
_PARTY_LABELS = {
    'name': 'name',
    'full name': 'name',
    'email': 'email', 'e-mail': 'email', 'email address': 'email',
    'phone': 'contact_number', 'telephone': 'contact_number',
    'tel': 'contact_number', 'mobile': 'contact_number',
    'contact': 'contact_number', 'contact number': 'contact_number',
    'number': 'contact_number', 'phone number': 'contact_number',
    'address': 'address_line1', 'address line 1': 'address_line1',
    'address 1': 'address_line1',
    'address line 2': 'address_line2', 'address 2': 'address_line2',
    'county': 'county', 'city': 'county', 'town': 'county',
    'postcode': 'postcode', 'post code': 'postcode', 'zip': 'postcode',
}

_LABEL_LINE_RE = re.compile(
    r'^\s*(?:[-*+]|\d+[.)]|\|)?\s*'        # optional markdown list / table marker
    r'\*{0,2}([A-Za-z][A-Za-z0-9 /-]{1,30})\*{0,2}\s*[:\-–]\s*'  # label:
    r'(.+?)\s*\|?\s*$')                    # value (trailing table pipe tolerated)


def _split_address(party):
    """Derive county/postcode from a one-line address when not given explicitly."""
    line1 = party.get('address_line1', '')
    if not line1 or party.get('postcode') or party.get('county'):
        return
    pc = _UK_POSTCODE_RE.search(line1)
    if pc:
        party['postcode'] = pc.group(1).strip()
        line1 = (line1[:pc.start()] + line1[pc.end():]).strip(' ,')
    parts = [p.strip() for p in line1.split(',') if p.strip()]
    if len(parts) >= 2:
        party['county'] = parts[-1]
        party['address_line1'] = ', '.join(parts[:-1])
    else:
        party['address_line1'] = line1


def parse_parties(markdown):
    """Parse an 'info of parties' block into a list of attendee dicts.

    Returns ``[{name, email, contact_number, address_line1, address_line2,
    county, postcode}, ...]`` — only parties with a name are included.
    """
    parties = []
    current = None
    for raw_line in (markdown or '').splitlines():
        match = _LABEL_LINE_RE.match(raw_line)
        if not match:
            continue
        label = re.sub(r'\s+', ' ', match.group(1).strip().lower())
        field = _PARTY_LABELS.get(label)
        if not field:
            continue
        value = match.group(2).strip()
        if not value:
            continue
        # A fresh "name" starts a new party (once the current one is named).
        if field == 'name' and (current is None or current.get('name')):
            current = {}
            parties.append(current)
        if current is None:
            current = {}
            parties.append(current)
        # Don't clobber a value already captured for this party/field.
        current.setdefault(field, value)

    cleaned = []
    for party in parties:
        if not party.get('name'):
            continue
        _split_address(party)
        cleaned.append(party)
    return cleaned
