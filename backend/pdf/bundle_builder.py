import logging
import os
import shutil
import subprocess
import tempfile

logger = logging.getLogger(__name__)

PAGE_NUMBER_FONT_SIZE = 20
PAGE_NUMBER_RIGHT_MARGIN = 18
PAGE_NUMBER_BOTTOM_MARGIN = 16
PAGE_NUMBER_PADDING = 4
PAGE_NUMBER_FONT = 'Times-Bold'


def _page_number_text_width(text):
    from reportlab.pdfbase.pdfmetrics import stringWidth

    return stringWidth(str(text), PAGE_NUMBER_FONT, PAGE_NUMBER_FONT_SIZE)


def qpdf_available():
    return shutil.which('qpdf') is not None


def pikepdf_available():
    try:
        import pikepdf  # noqa: F401
        return True
    except ImportError:
        return False


def fast_builder_available():
    return qpdf_available() and pikepdf_available()


def _page_range_spec(page_indices):
    """Convert 0-based page indices to a qpdf page spec (1-based)."""
    if not page_indices:
        return None
    one_based = [index + 1 for index in page_indices]
    if len(one_based) == 1:
        return str(one_based[0])
    if one_based == list(range(one_based[0], one_based[-1] + 1)):
        return f'{one_based[0]}-{one_based[-1]}'
    return ','.join(str(page) for page in one_based)


def _run_qpdf(args):
    result = subprocess.run(
        ['qpdf', *args],
        capture_output=True,
        text=True,
    )
    # qpdf exit code 3 means "operation succeeded with warnings": the output file
    # is still produced and valid (e.g. a source PDF with a minor structural quirk
    # like "object has offset 0"). Treating it as a failure needlessly drops the
    # build to the slow, fully-in-memory PyPDF2 fallback path, which is what OOMs
    # the worker on large bundles. Only codes other than 0/3 are real failures.
    if result.returncode not in (0, 3):
        raise RuntimeError(
            f'qpdf failed ({result.returncode}): {result.stderr or result.stdout}'
        )
    if result.returncode == 3:
        logger.warning(
            'qpdf completed with warnings: %s',
            (result.stderr or result.stdout or '').strip(),
        )


def _concat_with_qpdf(output_path, page_inputs):
    """
    page_inputs: list of (pdf_path, page_spec) e.g. ('index.pdf', '1-z')
    """
    args = ['--empty', '--pages']
    for pdf_path, page_spec in page_inputs:
        args.extend([pdf_path, page_spec])
    args.extend(['--', output_path])
    _run_qpdf(args)


def _build_page_number_overlay(page_width, page_height, page_number):
    """Build a single-page PDF overlay with a white backing box and page number."""
    from io import BytesIO

    from reportlab.pdfgen import canvas

    text = str(page_number)
    text_width = _page_number_text_width(text)
    x_right = page_width - PAGE_NUMBER_RIGHT_MARGIN
    y_bottom = PAGE_NUMBER_BOTTOM_MARGIN
    padding = PAGE_NUMBER_PADDING

    buffer = BytesIO()
    overlay_canvas = canvas.Canvas(buffer, pagesize=(page_width, page_height))
    overlay_canvas.setFillColorRGB(1, 1, 1)
    overlay_canvas.setStrokeColorRGB(1, 1, 1)
    overlay_canvas.rect(
        x_right - text_width - padding,
        y_bottom - padding,
        text_width + (padding * 2),
        PAGE_NUMBER_FONT_SIZE + (padding * 2),
        fill=1,
        stroke=0,
    )
    overlay_canvas.setFillColorRGB(0, 0, 0)
    overlay_canvas.setFont(PAGE_NUMBER_FONT, PAGE_NUMBER_FONT_SIZE)
    overlay_canvas.drawRightString(x_right, y_bottom, text)
    overlay_canvas.save()
    buffer.seek(0)
    return buffer


def _page_rotation(page):
    """Return a page's effective /Rotate (0/90/180/270), following inheritance.

    /Rotate can live on the page or be inherited from a /Pages ancestor. Walk up
    the parent chain (bounded) so scanned pages that carry rotation are handled.
    """
    obj = page.obj
    for _ in range(32):
        if obj is None:
            break
        try:
            rotate = obj.get('/Rotate')
        except Exception:
            break
        if rotate is not None:
            try:
                return int(rotate) % 360
            except (TypeError, ValueError):
                return 0
        try:
            obj = obj.get('/Parent')
        except Exception:
            break
    return 0


def _stamp_page_numbers(input_path, output_path):
    import pikepdf
    from pikepdf import Page, Rectangle

    pdf = pikepdf.Pdf.open(input_path)
    for page_number, page in enumerate(pdf.pages, start=1):
        # Use the visible area (cropbox), honouring a non-zero origin, and place
        # the overlay with an explicit rect so scanned pages whose box does not
        # start at (0, 0) still get the number in the bottom-right corner.
        box = page.cropbox
        x0 = float(box[0])
        y0 = float(box[1])
        x1 = float(box[2])
        y1 = float(box[3])
        box_width = x1 - x0
        box_height = y1 - y0

        # Scanned pages are often stored upright with a /Rotate flag. add_overlay
        # is rotation-aware, so the overlay must be sized to the *visual*
        # (post-rotation) dimensions or the number lands rotated and off-corner.
        rotation = _page_rotation(page)
        if rotation in (90, 270):
            visible_width, visible_height = box_height, box_width
        else:
            visible_width, visible_height = box_width, box_height

        overlay_pdf = pikepdf.open(
            _build_page_number_overlay(
                visible_width, visible_height, page_number
            ),
        )
        Page(page).add_overlay(
            Page(overlay_pdf.pages[0]),
            rect=Rectangle(x0, y0, x1, y1),
        )
        overlay_pdf.close()

    pdf.save(output_path)
    pdf.close()


def _add_index_links(pdf_path, index_links):
    if not index_links:
        return

    import pikepdf
    from pikepdf import Array, Dictionary, Name

    pdf = pikepdf.Pdf.open(pdf_path, allow_overwriting_input=True)
    for link in index_links:
        source_index = link['source_page_index']
        target_index = link['target_page_index']
        if source_index >= len(pdf.pages) or target_index >= len(pdf.pages):
            continue

        page = pdf.pages[source_index]
        rect = link['rect']
        x1, y1, x2, y2 = rect
        target_page = pdf.pages[target_index]
        annot = pdf.make_indirect(
            Dictionary(
                Type=Name('/Annot'),
                Subtype=Name('/Link'),
                Rect=[x1, y1, x2, y2],
                Border=[0, 0, 0],
                Dest=[target_page.obj, Name('/Fit')],
            )
        )
        if '/Annots' in page:
            page.Annots.append(annot)
        else:
            page.Annots = Array([annot])

    pdf.save()
    pdf.close()


def _add_bookmarks(pdf_path, documents_info):
    import pikepdf

    pdf = pikepdf.Pdf.open(pdf_path, allow_overwriting_input=True)
    with pdf.open_outline() as outline:
        outline.root.clear()
        outline.root.append(pikepdf.OutlineItem('Index', 0))

        current_section = None
        section_parent = None
        serial_number = 1

        for doc_info in documents_info:
            page_start = doc_info.get('page_start')
            if not page_start:
                continue

            target_page = page_start - 1
            if target_page < 0 or target_page >= len(pdf.pages):
                continue

            if doc_info['section'] != current_section:
                current_section = doc_info['section']
                section_parent = pikepdf.OutlineItem(
                    f'{current_section} (p. {page_start})',
                    target_page,
                )
                outline.root.append(section_parent)

            label = doc_info['description']
            if doc_info.get('date'):
                label = f'{label} ({doc_info["date"]})'

            item = pikepdf.OutlineItem(
                f'{serial_number}. {label} (p. {page_start})',
                target_page,
            )
            if section_parent is not None:
                section_parent.children.append(item)
            else:
                outline.root.append(item)
            serial_number += 1

    pdf.save()
    pdf.close()


def build_bundle_pdf_fast(
    index_pdf_bytes,
    documents_info,
    cache,
    progress_callback=None,
    stats=None,
):
    """
    Build the final bundle PDF on disk using qpdf + pikepdf.
    Returns the path to the output file (caller must delete).
    """
    if not fast_builder_available():
        raise RuntimeError('Fast bundle builder requires qpdf and pikepdf')

    work_dir = tempfile.mkdtemp(prefix='bundle_build_')
    try:
        if stats is not None:
            stats.start('fast_write_index')
        index_path = os.path.join(work_dir, 'index.pdf')
        with open(index_path, 'wb') as index_file:
            index_file.write(index_pdf_bytes)
        if stats is not None:
            stats.finish_stage()

        page_inputs = [(index_path, '1-z')]
        doc_total = len(documents_info)

        if stats is not None:
            stats.start('fast_prepare_inputs')
        for doc_index, doc_info in enumerate(documents_info):
            if progress_callback and doc_total:
                percent = 30 + int(40 * (doc_index + 1) / doc_total)
                label = (doc_info['description'] or 'document')[:48]
                progress_callback(
                    percent,
                    f'Preparing document {doc_index + 1} of {doc_total}: {label}...',
                )

            source_path = cache.local_path(doc_info['document'])
            page_spec = _page_range_spec(doc_info['page_indices'])
            if page_spec:
                page_inputs.append((source_path, page_spec))
        if stats is not None:
            stats.finish_stage()

        unnumbered_path = os.path.join(work_dir, 'unnumbered.pdf')
        if progress_callback:
            progress_callback(72, 'Concatenating PDFs...')
        if stats is not None:
            stats.start('fast_qpdf_concat')
        _concat_with_qpdf(unnumbered_path, page_inputs)
        if stats is not None:
            stats.finish_stage()

        numbered_path = os.path.join(work_dir, 'numbered.pdf')
        if progress_callback:
            progress_callback(80, 'Adding page numbers...')
        if stats is not None:
            stats.start('fast_pikepdf_page_numbers')
        _stamp_page_numbers(unnumbered_path, numbered_path)
        if stats is not None:
            stats.finish_stage()

        if progress_callback:
            progress_callback(85, 'Adding bookmarks and links...')
        if stats is not None:
            stats.start('fast_pikepdf_bookmarks')
        _add_bookmarks(numbered_path, documents_info)
        if stats is not None:
            stats.finish_stage()

        output_path = os.path.join(work_dir, 'final.pdf')
        shutil.copy2(numbered_path, output_path)
        return output_path, work_dir
    except Exception:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise


def build_bundle_pdf_fast_with_links(
    index_pdf_bytes,
    index_links,
    documents_info,
    cache,
    progress_callback=None,
    stats=None,
):
    """Like build_bundle_pdf_fast but also adds index hyperlinks."""
    output_path, work_dir = build_bundle_pdf_fast(
        index_pdf_bytes,
        documents_info,
        cache,
        progress_callback=progress_callback,
        stats=stats,
    )
    try:
        linked_path = os.path.join(work_dir, 'linked.pdf')
        shutil.copy2(output_path, linked_path)
        if stats is not None:
            stats.start('fast_pikepdf_index_links')
        _add_index_links(linked_path, index_links)
        if stats is not None:
            stats.finish_stage()
        return linked_path, work_dir
    except Exception:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise
