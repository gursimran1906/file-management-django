"""Parse an original message (RFC 822 bytes) into body, inline images and enclosures."""
import base64
import email
import email.policy
import mimetypes
import re
import unicodedata
from dataclasses import dataclass


@dataclass
class Enclosure:
    name: str
    data: bytes
    content_type: str
    appended: bool = False   # True once its pages were added to the email PDF
    note: str = ''           # e.g. "saved as file only", "not appended (encrypted)"


@dataclass
class ParsedMessage:
    html: str | None
    text: str | None
    enclosures: list


def safe_get_content(part):
    try:
        content = part.get_content()
        if isinstance(content, bytes):
            raise TypeError
        return content
    except Exception:
        data = part.get_payload(decode=True) or b''
        charset = part.get_content_charset() or 'utf-8'
        try:
            return data.decode(charset, errors='replace')
        except LookupError:
            return data.decode('utf-8', errors='replace')


def safe_filename(name, fallback='attachment', maxlen=100):
    name = unicodedata.normalize('NFKC', name or '').replace('\\', '/').split('/')[-1]
    name = re.sub(r'[\x00-\x1f<>:"|?*]', '', name).strip().strip('.')
    if not name:
        return fallback
    if len(name) > maxlen:
        stem, dot, ext = name.rpartition('.')
        if dot and len(ext) <= 8:
            name = stem[: maxlen - len(ext) - 1] + '.' + ext
        else:
            name = name[:maxlen]
    return name


def subject_slug(subject, maxlen=60):
    text = unicodedata.normalize('NFKD', subject or '').encode('ascii', 'ignore').decode()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'\s+', '_', text.strip())
    return text[:maxlen].rstrip('_-') or 'no_subject'


def parse_message(raw):
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    body = msg.get_body(preferencelist=('html', 'plain'))
    plain = msg.get_body(preferencelist=('plain',))
    html_body = text_body = None
    if body is not None:
        content = safe_get_content(body)
        if body.get_content_subtype() == 'html':
            html_body = content
        else:
            text_body = content
    if plain is not None and plain is not body:
        text_body = safe_get_content(plain)

    body_ids = {id(body), id(plain)}
    enclosures = []
    cid_map = {}
    for part in msg.walk():
        if part.is_multipart() or id(part) in body_ids:
            continue
        content_type = part.get_content_type()
        cid = (part.get('Content-ID') or '').strip().strip('<>')
        disposition = part.get_content_disposition()
        filename = part.get_filename()
        if content_type == 'message/rfc822':
            payload = part.get_payload()
            inner = payload[0] if isinstance(payload, list) and payload else None
            data = inner.as_bytes() if inner is not None else part.as_bytes()
            inner_subject = (inner.get('Subject') if inner is not None else '') or 'attached_email'
            enclosures.append(Enclosure(
                safe_filename(filename or f'{subject_slug(inner_subject)}.eml'), data, content_type))
            continue
        try:
            data = part.get_payload(decode=True)
        except Exception:
            data = None
        if not data:
            continue
        if cid and html_body and f'cid:{cid}' in html_body:
            cid_map[cid] = f'data:{content_type};base64,{base64.b64encode(data).decode()}'
            continue
        is_attachment = disposition == 'attachment' or bool(filename)
        if not is_attachment and disposition == 'inline' and part.get_content_maintype() == 'image':
            is_attachment = True
        if is_attachment:
            ext = mimetypes.guess_extension(content_type) or ''
            enclosures.append(Enclosure(
                safe_filename(filename, f'attachment_{len(enclosures) + 1}{ext}'), data, content_type))

    if html_body and cid_map:
        def _sub(match):
            key = match.group(2).strip('<>')
            if key in cid_map:
                return f'{match.group(1)}"{cid_map[key]}"'
            return match.group(0)
        html_body = re.sub(
            r'((?:src|background)\s*=\s*)["\']?cid:([^"\'>\s]+)["\']?', _sub, html_body, flags=re.I)

    seen = {}
    for enc in enclosures:
        base = enc.name
        count = seen.get(base.lower(), 0)
        seen[base.lower()] = count + 1
        if count:
            stem, dot, ext = base.rpartition('.')
            enc.name = f'{stem} ({count + 1}).{ext}' if dot else f'{base} ({count + 1})'
    return ParsedMessage(html_body, text_body, enclosures)
