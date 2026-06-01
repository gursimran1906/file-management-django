import logging
import time

from django.conf import settings

logger = logging.getLogger('backend.bundle_pdf')


def bundle_pdf_logging_enabled():
    return settings.DEBUG


class BundlePdfBuildStats:
    """Collect per-stage timings and metadata for bundle PDF generation."""

    def __init__(self, bundle_id):
        self.bundle_id = bundle_id
        self.builder = None
        self.stages = {}
        self.meta = {}
        self._started = time.perf_counter()
        self._stage_name = None
        self._stage_started = None

    def start(self, stage_name):
        self.finish_stage()
        self._stage_name = stage_name
        self._stage_started = time.perf_counter()

    def finish_stage(self):
        if self._stage_name is None or self._stage_started is None:
            return
        self.stages[self._stage_name] = time.perf_counter() - self._stage_started
        self._stage_name = None
        self._stage_started = None

    def set_builder(self, builder, **meta):
        self.builder = builder
        self.meta.update(meta)

    def add_meta(self, **meta):
        self.meta.update(meta)

    def log_summary(self, event='complete'):
        if not bundle_pdf_logging_enabled():
            return

        self.finish_stage()
        total_seconds = time.perf_counter() - self._started
        document_pages = self.meta.get('document_pages')
        output_pages = self.meta.get('output_pages')
        ms_per_page = None
        if document_pages:
            ms_per_page = round(total_seconds * 1000 / document_pages, 1)

        stage_parts = [
            f'{name}={elapsed:.3f}s'
            for name, elapsed in self.stages.items()
        ]
        stage_summary = ', '.join(stage_parts) if stage_parts else 'no stages'

        logger.info(
            'Bundle PDF %s bundle_id=%s builder=%s docs=%s document_pages=%s '
            'output_pages=%s output_mb=%s ms_per_page=%s total=%.3fs stages=[%s] %s',
            event,
            self.bundle_id,
            self.builder or 'unknown',
            self.meta.get('document_count'),
            document_pages,
            output_pages,
            self.meta.get('output_mb'),
            ms_per_page,
            total_seconds,
            stage_summary,
            self._extra_meta(),
        )

    def _extra_meta(self):
        extras = []
        if self.meta.get('qpdf_available') is not None:
            extras.append(f"qpdf={self.meta['qpdf_available']}")
        if self.meta.get('pikepdf_available') is not None:
            extras.append(f"pikepdf={self.meta['pikepdf_available']}")
        if self.meta.get('fallback_reason'):
            extras.append(f"fallback={self.meta['fallback_reason']}")
        if self.meta.get('cache_used') is not None:
            extras.append(f"cache={self.meta['cache_used']}")
        return '{' + ', '.join(extras) + '}' if extras else ''


def log_builder_selection(bundle_id, *, qpdf_ok, pikepdf_ok, cache_used, selected_builder, reason=None):
    if not bundle_pdf_logging_enabled():
        return
    logger.info(
        'Bundle PDF select bundle_id=%s builder=%s qpdf=%s pikepdf=%s cache=%s reason=%s',
        bundle_id,
        selected_builder,
        qpdf_ok,
        pikepdf_ok,
        cache_used,
        reason or 'n/a',
    )
