"""Tell read receipts, delivery receipts and bounces apart from real emails."""
import email
import email.policy

# PR_MESSAGE_CLASS, exposed by Graph as an extended property. Requesting it with
# $expand lets the search results say what a message is before it is downloaded.
MESSAGE_CLASS_PROPERTY_ID = 'String 0x001A'
EXPAND_MESSAGE_CLASS = f"singleValueExtendedProperties($filter=id eq '{MESSAGE_CLASS_PROPERTY_ID}')"

READ_RECEIPT = 'read receipt'
NOT_READ = 'not-read notification'
DELIVERY_RECEIPT = 'delivery receipt'
NON_DELIVERY = 'non-delivery report'
OTHER_REPORT = 'report'

# Left out of an export unless the user asks for receipts. Bounces are kept
# (and flagged) because a failed delivery can matter to the file.
EXCLUDED_REPORT_TYPES = frozenset({READ_RECEIPT, NOT_READ, DELIVERY_RECEIPT, OTHER_REPORT})


def message_class(message):
    """PR_MESSAGE_CLASS from an expanded Graph message, or '' when absent."""
    for prop in message.get('singleValueExtendedProperties') or []:
        prop_id = str(prop.get('id', '')).lower().replace(' ', '')
        if prop_id in ('string0x001a', 'string0x1a'):
            return str(prop.get('value') or '')
    return ''


def classify_by_class(msg_class):
    """Report type for an Exchange message class, or None for an ordinary email."""
    cls = (msg_class or '').upper()
    if not cls.startswith('REPORT.'):
        return None
    if '.IPNNRN' in cls:
        return NOT_READ
    if '.IPNRN' in cls:
        return READ_RECEIPT
    if cls.endswith(('.NDR', '.DELAYED')) or '.NDR.' in cls:
        return NON_DELIVERY
    if cls.endswith(('.DR', '.RELAYED', '.EXPANDED')):
        return DELIVERY_RECEIPT
    return OTHER_REPORT


def classify_by_mime(raw):
    """Same classification from the MIME structure, for when the class is unknown."""
    try:
        msg = email.message_from_bytes(raw, policy=email.policy.default)
    except Exception:
        return None
    if msg.get_content_type() != 'multipart/report':
        return None
    report_type = str(msg.get_param('report-type') or '').lower()
    if report_type == 'disposition-notification':
        return READ_RECEIPT
    if report_type == 'delivery-status':
        for part in msg.walk():
            if part.get_content_type() == 'message/delivery-status':
                try:
                    status = part.as_bytes().decode('utf-8', 'replace').lower()
                except Exception:
                    status = ''
                if 'action: failed' in status or 'action: delayed' in status:
                    return NON_DELIVERY
        return DELIVERY_RECEIPT
    return OTHER_REPORT


def is_automatic_reply(msg_class):
    cls = (msg_class or '').upper()
    return 'OOFTEMPLATE' in cls or 'REPLYTEMPLATE' in cls
