"""Convert Granola's Markdown note bodies into the Quill JSON the
``MatterAttendanceNotes.content`` field expects.

``QuillField`` stores a JSON document ``{"delta": <str>, "html": <str>}`` (see
``django_quill``). The editor renders from ``html``; ``delta`` only needs to be
present and parseable, so we store a plain-text delta alongside the rendered
HTML. This mirrors the existing ``backend.views._to_quill_json`` convention.
"""
import json

import bleach
import markdown as markdown_lib
from django.utils.html import strip_tags

# Tags Granola summaries realistically produce, plus what Quill can render.
_ALLOWED_TAGS = [
    'p', 'br', 'strong', 'em', 'b', 'i', 'u', 's', 'blockquote',
    'ul', 'ol', 'li', 'a', 'code', 'pre',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'hr',
]
_ALLOWED_ATTRS = {'a': ['href', 'title', 'target', 'rel']}


def markdown_to_html(text: str) -> str:
    """Render Markdown to sanitised HTML safe for storage and display."""
    text = (text or '').replace('\r\n', '\n').replace('\r', '\n').strip()
    if not text:
        return ''
    html = markdown_lib.markdown(
        text,
        extensions=['extra', 'sane_lists', 'nl2br'],
    )
    cleaned = bleach.clean(
        html, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRS, strip=True,
    )
    return cleaned.strip()


def markdown_to_quill_json(text: str) -> str:
    """Convert Markdown into a Quill ``{"delta", "html"}`` JSON string."""
    html = markdown_to_html(text)
    if not html:
        return json.dumps({'delta': '', 'html': ''})

    plain = strip_tags(html).strip()
    delta = json.dumps({'ops': [{'insert': f'{plain}\n'}]})
    return json.dumps({'delta': delta, 'html': html})
