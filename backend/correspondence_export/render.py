"""Outlook memo-style rendering of an email to PDF, with enclosures appended.

WeasyPrint runs in a child process with one font map for its whole life. On
some builds (Homebrew Pango/HarfBuzz on macOS) tearing a font map down after
certain emails aborts the process; in a child that costs one email, which is
flagged, instead of the whole export.
"""
import base64
import html as html_mod
import io
import logging
import multiprocessing
import os
import re
from contextlib import ExitStack

import pikepdf

logging.getLogger('weasyprint').setLevel(logging.CRITICAL)
logging.getLogger('fontTools').setLevel(logging.CRITICAL)

# Carlito is metric-compatible with Calibri (Outlook's default) and ships in the
# container; Calibri itself is used where installed.
FONT_STACK = 'Carlito, Calibri, "Liberation Sans", Arial, Helvetica, sans-serif'


class RenderError(Exception):
    pass


def _blocked_fetcher(url, *args, **kwargs):
    """Only data: URIs may load. Remote images and tracking pixels never do."""
    if url.startswith('data:'):
        from weasyprint import default_url_fetcher
        return default_url_fetcher(url, *args, **kwargs)
    raise ValueError('external resources are blocked')


_FONT_CONFIG = None


def _shared_font_config():
    """One font map per process. Creating and tearing one down per document is the
    path that aborts on some Pango/HarfBuzz builds."""
    global _FONT_CONFIG
    if _FONT_CONFIG is None:
        from weasyprint.text.fonts import FontConfiguration
        _FONT_CONFIG = FontConfiguration()
    return _FONT_CONFIG


def _render_in_process(html_doc, font_config=None):
    from weasyprint import HTML
    return HTML(string=html_doc, url_fetcher=_blocked_fetcher, base_url=None).write_pdf(
        font_config=font_config or _shared_font_config())


def _render_loop(conn):
    """Child process body: render documents sent over the pipe until told to stop."""
    font_config = _shared_font_config()
    while True:
        try:
            html_doc = conn.recv()
        except EOFError:
            return
        if html_doc is None:
            return
        if html_doc == '__crash__':  # test hook: die abruptly like a native crash
            os._exit(134)
        try:
            conn.send((True, _render_in_process(html_doc, font_config)))
        except Exception as exc:
            conn.send((False, type(exc).__name__))


class RenderWorker:
    def __init__(self, timeout=180):
        self.ctx = multiprocessing.get_context('spawn')
        self.timeout = timeout
        self.proc = None
        self.conn = None
        self.crashes = 0

    def start(self):
        self.conn, child = self.ctx.Pipe()
        self.proc = self.ctx.Process(target=_render_loop, args=(child,), daemon=True)
        self.proc.start()
        child.close()

    def _restart(self):
        self.crashes += 1
        try:
            if self.proc is not None:
                self.proc.kill()
                self.proc.join(5)
            if self.conn is not None:
                self.conn.close()
        except Exception:
            pass
        self.start()

    def render(self, html_doc):
        if self.proc is None:
            self.start()
        elif not self.proc.is_alive():
            self._restart()
        try:
            self.conn.send(html_doc)
            if not self.conn.poll(self.timeout):
                self._restart()
                raise RenderError('render timeout')
            ok, payload = self.conn.recv()
        except RenderError:
            raise
        except (EOFError, BrokenPipeError, ConnectionResetError, OSError):
            self._restart()
            raise RenderError('renderer crashed')
        if not ok:
            raise RenderError(payload)
        return payload

    def close(self):
        try:
            if self.conn is not None:
                self.conn.send(None)
            if self.proc is not None:
                self.proc.join(10)
                if self.proc.is_alive():
                    self.proc.kill()
        except Exception:
            pass


class Renderer:
    """Renders through a RenderWorker when one is active, else in-process."""

    def __init__(self, worker=None):
        self.worker = worker

    def pdf(self, html_doc):
        if self.worker is not None:
            return self.worker.render(html_doc)
        return _render_in_process(html_doc)


# ----------------------------------------------------------------------------- HTML

def css_string(value):
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('\n', ' ') + '"'


def page_css(owner, printed):
    foot = f'font-family: {FONT_STACK}; font-size: 9pt; color: #000;'
    return f"""
    @page {{ size: A4; margin: 18mm 18mm 20mm 18mm;
      @bottom-left {{ content: {css_string(owner)}; {foot} }}
      @bottom-center {{ content: counter(page); {foot} }}
      @bottom-right {{ content: {css_string(printed)}; {foot} }} }}
    html, body {{ margin: 0; padding: 0; }}
    body {{ font-family: {FONT_STACK}; font-size: 11pt; color: #000; }}
    .memo-owner {{ font-size: 14pt; font-weight: bold; padding-bottom: 3pt; border-bottom: 1.5pt solid #000; margin-bottom: 9pt; }}
    table.memo-hdr {{ border-collapse: collapse; margin: 0 0 14pt 0; }}
    table.memo-hdr td {{ vertical-align: top; padding: 0 0 2pt 0; font-size: 11pt; line-height: 1.25; }}
    table.memo-hdr td.k {{ font-weight: bold; width: 82pt; padding-right: 6pt; white-space: nowrap; }}
    .memo-body {{ overflow-wrap: anywhere; word-wrap: break-word; }}
    .memo-body img {{ max-width: 100%; height: auto; }}
    .memo-body table {{ max-width: 100%; }}
    .memo-body pre {{ white-space: pre-wrap; font-family: {FONT_STACK}; font-size: 11pt; margin: 0; }}
    .enc-divider {{ margin-top: 40%; text-align: center; font-size: 12pt; }}
    .enc-divider .big {{ font-size: 16pt; font-weight: bold; margin-bottom: 8pt; }}
    .enc-image img {{ max-width: 100%; max-height: 240mm; }}
    """


def _strip_page_props(css):
    # Outlook/Word HTML names its body page ("div.WordSection1 {page:WordSection1}");
    # a named page forces a page break before that element, pushing the body to page 2.
    return re.sub(r'(?<![\w-])page\s*:\s*[^;}"\']*;?', '', css, flags=re.I)


def clean_email_html(html_src):
    """Return (styles, inner body html) safe to embed inside the memo page."""
    styles = ' '.join(re.findall(r'<style[^>]*>(.*?)</style>', html_src, flags=re.S | re.I))
    styles = re.sub(r'@page[^{]*\{[^}]*\}', '', styles, flags=re.S | re.I)
    styles = re.sub(r'@import[^;]*;', '', styles, flags=re.I)
    styles = re.sub(r'@font-face\s*\{[^}]*\}', '', styles, flags=re.S | re.I)
    styles = _strip_page_props(styles)
    match = re.search(r'<body[^>]*>(.*)</body>', html_src, flags=re.S | re.I)
    inner = match.group(1) if match else html_src
    inner = re.sub(r'(style\s*=\s*)(["\'])(.*?)\2',
                   lambda m: m.group(1) + m.group(2) + _strip_page_props(m.group(3)) + m.group(2),
                   inner, flags=re.S | re.I)
    inner = re.sub(r'<!--\[if[^\]]*\]>.*?<!\[endif\]-->', '', inner, flags=re.S | re.I)
    inner = re.sub(r'<!--.*?-->', '', inner, flags=re.S)
    inner = re.sub(r'<(script|style|iframe|object|embed|title|head)[^>]*>.*?</\1\s*>', '', inner, flags=re.S | re.I)
    inner = re.sub(r'<(script|link|meta|base|iframe|object|embed)\b[^>]*/?>', '', inner, flags=re.I)
    inner = re.sub(r'</?o:p\b[^>]*>', '', inner, flags=re.I)
    inner = re.sub(r'<v:[^>]*>.*?</v:[^>]*>', '', inner, flags=re.S | re.I)
    inner = re.sub(r'<(/?)(html|body)\b[^>]*>', '', inner, flags=re.I)
    return styles, inner


def strip_tags(html_src):
    text = re.sub(r'<(script|style)[^>]*>.*?</\1\s*>', ' ', html_src, flags=re.S | re.I)
    text = re.sub(r'<br\s*/?>|</p>|</div>|</tr>|</li>', '\n', text, flags=re.I)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html_mod.unescape(text)
    return re.sub(r'[ \t\xa0]+', ' ', text)


def memo_html(owner, printed, rows, body_html, extra_css=''):
    row_html = ''.join(
        f'<tr><td class="k">{html_mod.escape(key)}</td><td>{value}</td></tr>'
        for key, value in rows if value)
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f'<style>{page_css(owner, printed)}</style>'
        f'<style>{extra_css}</style></head><body>'
        f'<div class="memo-owner">{html_mod.escape(owner)}</div>'
        f'<table class="memo-hdr">{row_html}</table>'
        f'<div class="memo-body">{body_html}</div></body></html>'
    )


def divider_html(owner, printed, title, subtitle):
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f'<style>{page_css(owner, printed)}</style></head><body>'
        f'<div class="enc-divider"><div class="big">{html_mod.escape(title)}</div>'
        f'<div>{html_mod.escape(subtitle)}</div></div></body></html>'
    )


def image_html(owner, printed, enclosure):
    uri = f'data:{enclosure.content_type};base64,{base64.b64encode(enclosure.data).decode()}'
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f'<style>{page_css(owner, printed)}</style></head><body>'
        f'<div class="enc-image"><div style="font-weight:bold;margin-bottom:6pt">'
        f'{html_mod.escape(enclosure.name)}</div><img src="{uri}"></div></body></html>'
    )


def merge_pdfs(blobs):
    out = pikepdf.new()
    with ExitStack() as stack:
        for blob in blobs:
            src = stack.enter_context(pikepdf.open(io.BytesIO(blob)))
            out.pages.extend(src.pages)
        buf = io.BytesIO()
        out.save(buf)
    return buf.getvalue()


IMAGE_TYPES = ('image/jpeg', 'image/png', 'image/gif')
IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.gif')


def append_enclosures(renderer, email_pdf, enclosures, owner, printed):
    """Append PDF and image enclosures after the email, each behind a divider page.

    Returns (pdf_bytes, flags). Enclosures that cannot be appended keep a note and
    stay available as files.
    """
    flags = []
    blobs = [email_pdf]
    total = len(enclosures)
    for index, enc in enumerate(enclosures, 1):
        label = f'Enclosure {index} of {total}'
        is_pdf = enc.data[:5] == b'%PDF-' or enc.name.lower().endswith('.pdf')
        is_image = enc.content_type.lower() in IMAGE_TYPES or enc.name.lower().endswith(IMAGE_EXTENSIONS)
        try:
            if is_pdf:
                with pikepdf.open(io.BytesIO(enc.data)) as src:
                    if src.is_encrypted:
                        raise ValueError('encrypted')
                    pages = len(src.pages)
                blobs.append(renderer.pdf(divider_html(
                    owner, printed, label, f"{enc.name} ({pages} page{'s' if pages != 1 else ''})")))
                blobs.append(enc.data)
                enc.appended = True
            elif is_image:
                blobs.append(renderer.pdf(divider_html(owner, printed, label, enc.name)))
                blobs.append(renderer.pdf(image_html(owner, printed, enc)))
                enc.appended = True
            else:
                enc.note = 'saved as file only'
        except Exception as exc:
            enc.appended = False
            enc.note = f'not appended ({type(exc).__name__})'
            flags.append(f'Enclosure not appended: {enc.name}')
            blobs = [b for b in blobs if b is not enc.data]
    if len(blobs) == 1:
        return email_pdf, flags
    try:
        return merge_pdfs(blobs), flags
    except Exception:
        for enc in enclosures:
            enc.appended = False
        flags.append('Enclosures not appended (merge failed) - saved as files only')
        return email_pdf, flags
