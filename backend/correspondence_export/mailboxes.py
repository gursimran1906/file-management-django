"""What an export starts from: mailboxes, client addresses, flag keywords, dates."""
import json
import re
from datetime import date, timedelta

from django.conf import settings
from django.core.validators import validate_email
from django.core.exceptions import ValidationError

DEFAULT_SHARED_MAILBOXES = [
    {'address': 'mail@anpsolicitors.com', 'label': 'Main office', 'matter_types': []},
    {'address': 'conveyancing@anpsolicitors.com', 'label': 'Conveyancing',
     'matter_types': ['conveyanc', 'property', 'lease', 'remortgage', 'purchase', 'sale']},
    {'address': 'disputeresolution@anpsolicitors.com', 'label': 'Dispute resolution',
     'matter_types': ['dispute', 'litigation', 'debt', 'employment', 'civil', 'claim']},
    {'address': 'privateclient@anpsolicitors.com', 'label': 'Private client',
     'matter_types': ['probate', 'will', 'lpa', 'power of attorney', 'trust', 'estate']},
    {'address': 'family@anpsolicitors.com', 'label': 'Family',
     'matter_types': ['family', 'divorce', 'children', 'matrimonial', 'financial remedy']},
    {'address': 'riskmanagement@anpsolicitors.com', 'label': 'Risk management', 'matter_types': []},
]

TITLE_WORDS = {'mr', 'mrs', 'ms', 'miss', 'dr', 'mx', 'sir', 'lady', 'lord', 'prof', 'rev', 'and', 'the'}


def shared_mailboxes():
    raw = getattr(settings, 'CORRESPONDENCE_EXPORT_SHARED_MAILBOXES', '') or ''
    if raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list) and parsed:
                return [{
                    'address': str(m.get('address', '')).lower(),
                    'label': m.get('label') or m.get('address', ''),
                    'matter_types': [str(k).lower() for k in (m.get('matter_types') or [])],
                } for m in parsed if m.get('address')]
        except (ValueError, AttributeError):
            pass
    return [dict(m) for m in DEFAULT_SHARED_MAILBOXES]


def staff_mailboxes():
    """Every active staff member with a mailbox, excluding the shared ones."""
    from users.models import CustomUser
    shared = {m['address'] for m in shared_mailboxes()}
    out = []
    for user in CustomUser.objects.filter(is_active=True).exclude(email='').order_by('first_name', 'last_name'):
        address = (user.email or '').strip().lower()
        if not address or address in shared:
            continue
        name = f'{user.first_name} {user.last_name}'.strip() or user.username
        out.append({'address': address, 'label': f'{name} ({user.username})', 'user_id': user.id})
    return out


def department_mailbox_for(matter):
    matter_type = ((matter.matter_type.type if matter.matter_type_id and matter.matter_type else '') or '').lower()
    for mailbox in shared_mailboxes():
        if any(keyword and keyword in matter_type for keyword in mailbox['matter_types']):
            return mailbox['address']
    return shared_mailboxes()[0]['address']


def default_mailboxes_for(matter):
    out = [department_mailbox_for(matter)]
    fee_earner = matter.fee_earner if matter.fee_earner_id else None
    if fee_earner and fee_earner.email:
        address = fee_earner.email.strip().lower()
        if address and address not in out:
            out.append(address)
    return out


def default_addresses_for(matter):
    return [e.strip().lower() for e in matter.all_client_emails if e and e.strip()]


def suggested_addresses_for(matter):
    """Addresses worth offering as one-click additions (not selected by default)."""
    out = []
    other = matter.other_side if matter.other_side_id else None
    if other:
        for label, value in (('Other side', other.email), ("Other side's solicitors", other.solicitors_email)):
            value = (value or '').strip().lower()
            if value and is_email(value):
                out.append({'label': f'{label}: {other.name or value}', 'address': value})
    return out


def name_keywords_for(matter):
    """Client names as flag keywords: each full name plus each word of three letters or more."""
    keywords = []
    for client in matter.all_clients:
        full = (client.name or '').strip()
        if not full:
            continue
        if full not in keywords:
            keywords.append(full)
        for word in re.split(r'[\s,&/]+', full):
            word = word.strip('.-')
            if len(word) >= 3 and word.lower() not in TITLE_WORDS and word not in keywords:
                keywords.append(word)
    return keywords


def default_date_from(matter):
    opened = getattr(matter, 'timestamp', None)
    if opened:
        return opened.date()
    return date.today() - timedelta(days=365 * 3)


def is_email(value):
    try:
        validate_email(value)
    except ValidationError:
        return False
    return True


def parse_address_list(raw):
    """Split a textarea / hidden input of addresses on commas, semicolons and whitespace."""
    out = []
    for token in re.split(r'[\s,;]+', raw or ''):
        token = token.strip().strip('<>').lower()
        if token and token not in out:
            out.append(token)
    return out
