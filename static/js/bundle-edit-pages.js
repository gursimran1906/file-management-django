(function (global) {
    const documentPageData = {};
    const loadedPagePreviews = {};
    let pdfjsLoadPromise = null;

    function escapeHtml(value) {
        return String(value || '').replace(/[&<>"']/g, char => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        }[char]));
    }

    function ensurePdfJs() {
        if (global.pdfjsLib) {
            return Promise.resolve(global.pdfjsLib);
        }
        if (!pdfjsLoadPromise) {
            pdfjsLoadPromise = new Promise((resolve, reject) => {
                const script = document.createElement('script');
                script.src = 'https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/build/pdf.min.js';
                script.onload = () => {
                    global.pdfjsLib.GlobalWorkerOptions.workerSrc =
                        'https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/build/pdf.worker.min.js';
                    resolve(global.pdfjsLib);
                };
                script.onerror = () => reject(new Error('Could not load PDF preview library'));
                document.head.appendChild(script);
            });
        }
        return pdfjsLoadPromise;
    }

    function getDocumentIds() {
        return Array.from(document.querySelectorAll('.document-item[data-document-id]'))
            .map(el => el.dataset.documentId);
    }

    function setPageToggleState(documentId, state, label) {
        const toggle = document.getElementById(`page-toggle-${documentId}`);
        if (!toggle) return;
        toggle.disabled = state === 'loading' || state === 'error';
        toggle.dataset.pagesState = state;
        toggle.classList.toggle('bundle-page-toggle-loading', state === 'loading');
        toggle.textContent = label;
    }

    function setPageSummary(documentId, text, isLoading) {
        const summary = document.getElementById(`document-page-summary-${documentId}`);
        if (!summary) return;
        summary.textContent = text;
        summary.classList.toggle('bundle-doc-pages-loading', !!isLoading);
    }

    function renderPagePanel(documentId, pageChoices, description) {
        const panel = document.getElementById(`page-panel-${documentId}`);
        if (!panel || panel.dataset.rendered === 'true') return;

        const rowsHtml = pageChoices.map(page => {
            const included = !!page.included;
            return `
                <div class="page-row group relative flex cursor-pointer flex-col overflow-hidden rounded-lg border-2 bg-white shadow-sm transition-all duration-150 hover:shadow-md ${included ? 'border-blue-300 ring-2 ring-blue-100' : 'page-row-excluded border-gray-200'}" data-page="${page.number}" role="button" tabindex="0" aria-pressed="${included ? 'true' : 'false'}">
                    <span class="page-drag-handle absolute right-2 top-2 z-10 cursor-grab rounded-md bg-white/95 px-1.5 py-0.5 text-[10px] text-gray-400 shadow-sm ring-1 ring-gray-200 opacity-0 transition-opacity group-hover:opacity-100" title="Drag to reorder">⋮⋮</span>
                    <div class="page-thumb relative aspect-[3/4] w-full overflow-hidden bg-gray-100" data-page-thumb="${page.number}">
                        <span class="page-thumb-loading absolute inset-0 flex items-center justify-center text-xs text-gray-400">
                            <span class="inline-flex items-center gap-1.5">
                                <span class="h-3 w-3 animate-spin rounded-full border-2 border-gray-300 border-t-blue-500"></span>
                                Loading
                            </span>
                        </span>
                    </div>
                    <div class="flex items-center justify-between gap-2 border-t border-gray-100 px-3 py-2.5">
                        <span class="text-sm font-medium text-gray-800">Page ${page.number}</span>
                        <span class="page-status text-[11px] font-medium ${included ? 'text-blue-600' : 'text-gray-400'}">${included ? 'Included' : 'Excluded'}</span>
                        <input type="checkbox" class="page-include sr-only" ${included ? 'checked' : ''} aria-label="Include page ${page.number}">
                    </div>
                </div>
            `;
        }).join('');

        panel.className = 'hidden mb-2 ml-8 overflow-hidden rounded-xl border border-gray-200 bg-gray-50/80';
        panel.setAttribute('role', 'region');
        panel.setAttribute('aria-label', `Page selection for ${description}`);
        panel.innerHTML = `
            <div class="flex flex-col gap-3 border-b border-gray-200 bg-white px-4 py-3 sm:flex-row sm:items-start sm:justify-between">
                <div class="min-w-0">
                    <h4 class="text-sm font-semibold text-gray-900">Page previews</h4>
                    <p class="mt-1 text-xs leading-relaxed text-gray-500">All pages are included by default. Use the previews to spot blank pages, then click to exclude any you do not want. Drag cards to reorder.</p>
                </div>
                <div id="page-count-summary-${documentId}" class="shrink-0 rounded-full bg-gray-100 px-3 py-1 text-xs font-medium text-gray-600">
                    ${pageChoices.length} pages
                </div>
            </div>
            <div class="p-4">
                <div id="page-list-${documentId}" class="page-list grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-5">
                    ${rowsHtml}
                </div>
            </div>
            <div class="flex flex-wrap items-center justify-between gap-3 border-t border-gray-200 bg-white px-4 py-3">
                <p class="text-xs text-gray-400">Excluded pages will not appear in the generated bundle.</p>
                <div class="flex flex-wrap gap-2">
                    <button type="button" onclick="BundleEditPages.resetPagePanel(${documentId})" class="btn-secondary text-xs">Reset all pages</button>
                    <button type="button" onclick="BundleEditPages.savePageOrder(${documentId})" class="btn-primary text-xs">Save pages</button>
                </div>
            </div>
        `;
        panel.dataset.rendered = 'true';
        bindPageListEvents(documentId);
        initPageListSortable(documentId);
        updatePageCountSummary(documentId);
    }

    function bindPageListEvents(documentId) {
        const list = document.getElementById(`page-list-${documentId}`);
        if (!list || list.dataset.bound === 'true') return;
        list.dataset.bound = 'true';

        list.addEventListener('click', function (event) {
            if (event.target.closest('.page-drag-handle')) return;
            const row = event.target.closest('.page-row');
            if (!row || !list.contains(row)) return;
            const checkbox = row.querySelector('.page-include');
            checkbox.checked = !checkbox.checked;
            syncPageRowState(row);
            updatePageCountSummary(documentId);
        });

        list.addEventListener('keydown', function (event) {
            if (event.key !== 'Enter' && event.key !== ' ') return;
            const row = event.target.closest('.page-row');
            if (!row || !list.contains(row)) return;
            event.preventDefault();
            const checkbox = row.querySelector('.page-include');
            checkbox.checked = !checkbox.checked;
            syncPageRowState(row);
            updatePageCountSummary(documentId);
        });

        list.querySelectorAll('.page-row').forEach(syncPageRowState);
    }

    function initPageListSortable(documentId) {
        const list = document.getElementById(`page-list-${documentId}`);
        if (!list || list.dataset.sortable === 'true' || !global.Sortable) return;
        list.dataset.sortable = 'true';
        new Sortable(list, {
            handle: '.page-drag-handle',
            animation: 150,
            ghostClass: 'sortable-ghost',
            chosenClass: 'sortable-chosen',
            dragClass: 'sortable-drag',
        });
    }

    function syncPageRowState(row) {
        if (!row) return;
        const included = row.querySelector('.page-include').checked;
        const status = row.querySelector('.page-status');
        row.classList.toggle('page-row-excluded', !included);
        row.classList.toggle('border-blue-300', included);
        row.classList.toggle('ring-2', included);
        row.classList.toggle('ring-blue-100', included);
        row.classList.toggle('border-gray-200', !included);
        row.setAttribute('aria-pressed', included ? 'true' : 'false');
        if (status) {
            status.textContent = included ? 'Included' : 'Excluded';
            status.classList.toggle('text-blue-600', included);
            status.classList.toggle('text-gray-400', !included);
        }
    }

    function updatePageCountSummary(documentId) {
        const summary = document.getElementById(`page-count-summary-${documentId}`);
        const rows = document.querySelectorAll(`#page-list-${documentId} .page-row`);
        if (!summary || rows.length === 0) return;
        const includedCount = Array.from(rows).filter(row => row.querySelector('.page-include').checked).length;
        summary.textContent = `${includedCount} of ${rows.length} pages included`;
    }

    async function fetchDocumentPageMetadata(documentId) {
        const response = await fetch(`/bundle/document/${documentId}/pages/`, {
            credentials: 'same-origin',
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Could not load page information');
        }
        return data;
    }

    async function loadDocumentPageMetadata(documentId) {
        const panel = document.getElementById(`page-panel-${documentId}`);
        const description = panel ? panel.dataset.documentDescription || 'Document' : 'Document';

        try {
            const data = await fetchDocumentPageMetadata(documentId);
            documentPageData[documentId] = data;
        setPageSummary(documentId, data.page_summary, false);
        setPageToggleState(documentId, 'ready', 'Pages');
            renderPagePanel(documentId, data.page_choices, description);
        } catch (error) {
            console.error(`Failed to load pages for document ${documentId}`, error);
            setPageSummary(documentId, 'Pages unavailable', false);
            setPageToggleState(documentId, 'error', 'Pages unavailable');
        }
    }

    async function loadDocumentPagesProgressively(onProgress) {
        const documentIds = getDocumentIds();
        if (documentIds.length === 0) {
            if (typeof onProgress === 'function') {
                onProgress(0, 0, true);
            }
            return;
        }

        const concurrency = 4;
        let completed = 0;

        async function loadOne(documentId) {
            await loadDocumentPageMetadata(documentId);
            completed += 1;
            if (typeof onProgress === 'function') {
                onProgress(completed, documentIds.length);
            }
        }

        const workers = Array.from(
            {length: Math.min(concurrency, documentIds.length)},
            async (_, workerIndex) => {
                for (let index = workerIndex; index < documentIds.length; index += concurrency) {
                    await loadOne(documentIds[index]);
                }
            },
        );

        await Promise.all(workers);

        if (typeof onProgress === 'function') {
            onProgress(documentIds.length, documentIds.length, true);
        }
    }

    async function loadPagePreviews(documentId) {
        await ensurePdfJs();
        loadedPagePreviews[documentId] = true;
        const thumbs = Array.from(document.querySelectorAll(`#page-list-${documentId} [data-page-thumb]`));
        if (thumbs.length === 0) return;

        const previewWidth = global.matchMedia('(min-width: 1280px)').matches ? 160
            : global.matchMedia('(min-width: 768px)').matches ? 140
            : global.matchMedia('(min-width: 640px)').matches ? 120
            : 100;

        try {
            const response = await fetch(`/bundle/document/${documentId}/file/`, {
                credentials: 'same-origin',
            });
            if (!response.ok) {
                throw new Error(`Could not load PDF (${response.status})`);
            }
            const pdfData = await response.arrayBuffer();
            const pdf = await global.pdfjsLib.getDocument({ data: pdfData }).promise;
            for (const thumb of thumbs) {
                const pageNumber = Number(thumb.dataset.pageThumb);
                const loading = thumb.querySelector('.page-thumb-loading');
                try {
                    const page = await pdf.getPage(pageNumber);
                    const baseViewport = page.getViewport({ scale: 1 });
                    const scale = previewWidth / baseViewport.width;
                    const viewport = page.getViewport({ scale });
                    const canvas = document.createElement('canvas');
                    canvas.width = viewport.width;
                    canvas.height = viewport.height;
                    await page.render({
                        canvasContext: canvas.getContext('2d'),
                        viewport: viewport,
                    }).promise;
                    thumb.querySelectorAll('canvas').forEach(node => node.remove());
                    thumb.appendChild(canvas);
                    if (loading) loading.classList.add('hidden');
                } catch (error) {
                    if (loading) loading.textContent = 'Preview unavailable';
                    console.error(`Failed to render page ${pageNumber}`, error);
                }
            }
        } catch (error) {
            thumbs.forEach(thumb => {
                const loading = thumb.querySelector('.page-thumb-loading');
                if (loading) loading.textContent = 'Could not load previews';
            });
            loadedPagePreviews[documentId] = false;
            console.error('Failed to load page previews', error);
        }
    }

    function togglePagePanel(documentId) {
        const panel = document.getElementById(`page-panel-${documentId}`);
        const toggle = document.getElementById(`page-toggle-${documentId}`);
        if (!panel || !toggle || toggle.disabled) return;

        const opening = panel.classList.contains('hidden');
        panel.classList.toggle('hidden');
        toggle.textContent = opening ? 'Hide' : 'Pages';
        toggle.setAttribute('aria-expanded', opening ? 'true' : 'false');
        if (opening && !loadedPagePreviews[documentId]) {
            loadPagePreviews(documentId);
        }
    }

    function resetPagePanel(documentId) {
        const pageList = document.getElementById(`page-list-${documentId}`);
        if (!pageList) return;
        Array.from(pageList.querySelectorAll('.page-row'))
            .sort((a, b) => Number(a.dataset.page) - Number(b.dataset.page))
            .forEach(row => {
                row.querySelector('.page-include').checked = true;
                syncPageRowState(row);
                pageList.appendChild(row);
            });
        updatePageCountSummary(documentId);
    }

    function savePageOrder(documentId) {
        const pageRows = Array.from(document.querySelectorAll(`#page-list-${documentId} .page-row`));
        const selectedPages = pageRows
            .filter(row => row.querySelector('.page-include').checked)
            .map(row => row.dataset.page);

        if (selectedPages.length === 0) {
            alert('Select at least one page, or delete the document instead.');
            return;
        }

        const params = new URLSearchParams();
        selectedPages.forEach(pageNumber => params.append('page_order[]', pageNumber));

        fetch(`/bundle/document/${documentId}/pages/`, {
            method: 'POST',
            headers: {
                'X-CSRFToken': global.getCsrfToken ? global.getCsrfToken() : '',
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            body: params,
        })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    setPageSummary(documentId, data.page_summary, false);
                    updatePageCountSummary(documentId);
                    const panel = document.getElementById(`page-panel-${documentId}`);
                    const toggle = document.getElementById(`page-toggle-${documentId}`);
                    panel.classList.add('hidden');
                    if (toggle) {
                        toggle.textContent = 'Pages';
                        toggle.setAttribute('aria-expanded', 'false');
                    }
                    if (documentPageData[documentId]) {
                        documentPageData[documentId].page_summary = data.page_summary;
                    }
                } else {
                    alert(data.error || 'Error updating pages');
                }
            })
            .catch(() => alert('Error updating pages'));
    }

    function updateDocumentsLoadBanner(current, total, done) {
        const banner = document.getElementById('bundle-documents-load-banner');
        if (!banner) return;
        if (done || total === 0) {
            banner.classList.add('hidden');
            banner.innerHTML = '';
            return;
        }
        const percent = total ? Math.round((current / total) * 100) : 0;
        banner.classList.remove('hidden');
        banner.innerHTML = `
            <span>Loading document details (${current} of ${total})...</span>
            <div class="bundle-inline-progress" aria-hidden="true">
                <div class="bundle-inline-progress-bar" style="width:${percent}%"></div>
            </div>
        `;
    }

    global.BundleEditPages = {
        init() {
            loadDocumentPagesProgressively(updateDocumentsLoadBanner);
        },
        togglePagePanel,
        resetPagePanel,
        savePageOrder,
        escapeHtml,
        onDocumentsReordered(documentIds) {
            documentIds.forEach(documentId => {
                const data = documentPageData[documentId];
                if (!data) return;
                setPageSummary(documentId, data.page_summary, false);
                const toggle = document.getElementById(`page-toggle-${documentId}`);
                const panel = document.getElementById(`page-panel-${documentId}`);
                if (toggle && toggle.dataset.pagesState !== 'loading') {
                    setPageToggleState(
                        documentId,
                        'ready',
                        panel && !panel.classList.contains('hidden') ? 'Hide' : 'Pages'
                    );
                }
            });
        },
        removeDocument(documentId) {
            delete documentPageData[documentId];
            delete loadedPagePreviews[documentId];
        },
        removeDocumentsInSection(sectionId) {
            document.querySelectorAll(
                `.section-card[data-section-id="${sectionId}"] .document-item[data-document-id]`
            ).forEach(el => {
                delete documentPageData[el.dataset.documentId];
                delete loadedPagePreviews[el.dataset.documentId];
            });
        },
        loadDocuments(documentIds) {
            const ids = (documentIds || []).filter(Boolean);
            if (ids.length === 0) return Promise.resolve();
            return Promise.all(ids.map(documentId => loadDocumentPageMetadata(documentId)));
        },
    };

    global.togglePagePanel = togglePagePanel;
})(window);
