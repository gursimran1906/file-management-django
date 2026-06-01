(function (global) {
    function toIsoDate(year, month, day) {
        const y = Number(year);
        const m = Number(month);
        const d = Number(day);
        const dt = new Date(y, m - 1, d);
        if (dt.getFullYear() !== y || dt.getMonth() !== m - 1 || dt.getDate() !== d) {
            return '';
        }
        return `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
    }

    function cleanDescription(value) {
        return String(value || '').replace(/_/g, ' ').replace(/\s+/g, ' ').trim();
    }

    /** ISO YYYY-MM-DD → UK dd/mm/YYYY for display */
    function formatUkDate(value) {
        const isoMatch = String(value || '').match(/^(\d{4})-(\d{2})-(\d{2})$/);
        if (isoMatch) {
            return `${isoMatch[3]}/${isoMatch[2]}/${isoMatch[1]}`;
        }
        return String(value || '').trim();
    }

    function parseDocumentFilename(filename) {
        const basename = String(filename || '').replace(/\.[^/.]+$/, '');
        const patterns = [
            { re: /^(\d{4})-(\d{2})-(\d{2})[\s_-]+(.+)$/i, parts: m => [m[1], m[2], m[3], m[4]] },
            { re: /^(\d{4})(\d{2})(\d{2})[\s_-]+(.+)$/i, parts: m => [m[1], m[2], m[3], m[4]] },
            { re: /^(\d{2})[-.](\d{2})[-.](\d{4})[\s_-]+(.+)$/i, parts: m => [m[3], m[2], m[1], m[4]] },
        ];

        for (const pattern of patterns) {
            const match = basename.match(pattern.re);
            if (!match) continue;
            const [year, month, day, description] = pattern.parts(match);
            const date = toIsoDate(year, month, day);
            if (!date) continue;
            return {
                description: cleanDescription(description),
                date: date,
                dateFromFilename: true,
            };
        }

        return {
            description: cleanDescription(basename),
            date: '',
            dateFromFilename: false,
        };
    }

    global.BundleFilenameUtils = {
        parse: parseDocumentFilename,
        formatUkDate: formatUkDate,
        descriptionFromName: function (filename) {
            return parseDocumentFilename(filename).description;
        },
    };

    const OVERLAY_STYLES = ''
        + '#bundle-upload-overlay{position:fixed;inset:0;z-index:9999;display:flex;align-items:center;justify-content:center;background:rgba(17,24,39,.45);padding:1rem}'
        + '#bundle-upload-overlay.hidden{display:none}'
        + '.bundle-upload-panel{display:flex;flex-direction:column;align-items:stretch;gap:.75rem;min-width:18rem;max-width:28rem;width:100%;padding:1.5rem 1.75rem;border-radius:.75rem;background:#fff;box-shadow:0 20px 25px -5px rgba(0,0,0,.1),0 8px 10px -6px rgba(0,0,0,.1)}'
        + '.bundle-upload-panel-head{display:flex;flex-direction:column;align-items:center;gap:.75rem;text-align:center}'
        + '.bundle-upload-spinner{width:2rem;height:2rem;border:3px solid #e5e7eb;border-top-color:#2563eb;border-radius:9999px;animation:bundle-upload-spin .8s linear infinite;flex-shrink:0}'
        + '.bundle-upload-message{font-size:.875rem;font-weight:500;color:#111827}'
        + '.bundle-upload-subtext{font-size:.75rem;color:#6b7280;line-height:1.4}'
        + '.bundle-upload-progress-wrap{display:flex;flex-direction:column;gap:.35rem;width:100%}'
        + '.bundle-upload-progress-track{height:.45rem;border-radius:9999px;background:#e5e7eb;overflow:hidden}'
        + '.bundle-upload-progress-bar{height:100%;width:0;border-radius:9999px;background:#2563eb;transition:width .45s ease-out}'
        + '.bundle-upload-progress-bar.is-instant{transition:none}'
        + '.bundle-upload-progress-bar.is-transfer{width:40%!important;transition:none;animation:bundle-upload-transfer 1.35s ease-in-out infinite}'
        + '.bundle-upload-progress-label{font-size:.6875rem;color:#6b7280;text-align:right}'
        + '@keyframes bundle-upload-spin{to{transform:rotate(360deg)}}'
        + '@keyframes bundle-upload-transfer{0%{transform:translateX(-120%)}100%{transform:translateX(320%)}}';

    global.BundleUpload = {
        _overlay: null,
        _maxPercent: 0,
        _indeterminate: false,
        _transferMode: false,
        _transferTimer: null,
        _transferMessages: [],
        _transferMsgIndex: 0,

        _ensureStyles() {
            if (document.getElementById('bundle-upload-styles')) return;
            const style = document.createElement('style');
            style.id = 'bundle-upload-styles';
            style.textContent = OVERLAY_STYLES;
            document.head.appendChild(style);
        },

        _ensureOverlay() {
            this._ensureStyles();
            if (this._overlay) return this._overlay;

            this._overlay = document.createElement('div');
            this._overlay.id = 'bundle-upload-overlay';
            this._overlay.className = 'hidden';
            this._overlay.setAttribute('role', 'alertdialog');
            this._overlay.setAttribute('aria-live', 'assertive');
            this._overlay.setAttribute('aria-busy', 'true');
            this._overlay.innerHTML = ''
                + '<div class="bundle-upload-panel">'
                + '<div class="bundle-upload-panel-head">'
                + '<div class="bundle-upload-spinner" aria-hidden="true"></div>'
                + '<div>'
                + '<p class="bundle-upload-message">Working...</p>'
                + '<p class="bundle-upload-subtext">Please wait, do not close this page.</p>'
                + '</div>'
                + '</div>'
                + '<div class="bundle-upload-progress-wrap hidden" id="bundle-upload-progress-wrap">'
                + '<div class="bundle-upload-progress-track" aria-hidden="true">'
                + '<div class="bundle-upload-progress-bar" id="bundle-upload-progress-bar"></div>'
                + '</div>'
                + '<p class="bundle-upload-progress-label" id="bundle-upload-progress-label">0%</p>'
                + '</div>'
                + '</div>';
            document.body.appendChild(this._overlay);
            return this._overlay;
        },

        _setBarWidth(percent, animate) {
            const bar = this._ensureOverlay().querySelector('#bundle-upload-progress-bar');
            if (!bar) {
                return;
            }
            const safePercent = Math.max(0, Math.min(100, Math.round(percent)));
            if (animate) {
                bar.classList.remove('is-instant');
            } else {
                bar.classList.add('is-instant');
            }
            bar.style.width = `${safePercent}%`;
            if (!animate) {
                void bar.offsetWidth;
                bar.classList.remove('is-instant');
            }
        },

        _clearTransferTimer() {
            if (this._transferTimer) {
                clearInterval(this._transferTimer);
                this._transferTimer = null;
            }
        },

        _setTransferSubtext() {
            if (!this._overlay || !this._transferMessages.length) {
                return;
            }
            this._overlay.querySelector('.bundle-upload-subtext').textContent =
                this._transferMessages[this._transferMsgIndex];
        },

        beginTransfer(message, subtextMessages) {
            this._clearTransferTimer();
            this._transferMode = true;
            this._indeterminate = false;
            this._transferMessages = subtextMessages && subtextMessages.length
                ? subtextMessages
                : ['Please wait, your download will start shortly.'];
            this._transferMsgIndex = 0;

            const overlay = this._ensureOverlay();
            const wrap = overlay.querySelector('#bundle-upload-progress-wrap');
            const label = overlay.querySelector('#bundle-upload-progress-label');
            const bar = overlay.querySelector('#bundle-upload-progress-bar');
            const spinner = overlay.querySelector('.bundle-upload-spinner');

            overlay.querySelector('.bundle-upload-message').textContent = message || 'Downloading PDF...';
            wrap.classList.remove('hidden');
            label.textContent = 'Downloading';
            bar.classList.add('is-transfer', 'is-instant');
            bar.style.width = '';
            bar.style.transform = '';
            spinner.classList.remove('hidden');
            this._setTransferSubtext();

            this._transferTimer = setInterval(() => {
                this._transferMsgIndex = (this._transferMsgIndex + 1) % this._transferMessages.length;
                this._setTransferSubtext();
            }, 2800);
        },

        updateTransferProgress(ratio) {
            if (!this._transferMode || !this._overlay) {
                return;
            }
            const bar = this._overlay.querySelector('#bundle-upload-progress-bar');
            const label = this._overlay.querySelector('#bundle-upload-progress-label');
            if (!bar || !label) {
                return;
            }
            bar.classList.remove('is-transfer');
            bar.style.transform = '';
            const pct = Math.round(Math.max(0, Math.min(1, ratio)) * 100);
            this._setBarWidth(pct, true);
            label.textContent = `${pct}% downloaded`;
        },

        finishTransfer(message, subtext) {
            this._clearTransferTimer();
            this._transferMode = false;
            if (!this._overlay) {
                return;
            }
            const wrap = this._overlay.querySelector('#bundle-upload-progress-wrap');
            const bar = this._overlay.querySelector('#bundle-upload-progress-bar');
            const spinner = this._overlay.querySelector('.bundle-upload-spinner');
            if (bar) {
                bar.classList.remove('is-transfer');
                bar.style.transform = '';
            }
            if (wrap) {
                wrap.classList.add('hidden');
            }
            if (spinner) {
                spinner.classList.add('hidden');
            }
            if (message) {
                this._overlay.querySelector('.bundle-upload-message').textContent = message;
            }
            if (subtext !== undefined) {
                this._overlay.querySelector('.bundle-upload-subtext').textContent = subtext;
            }
        },

        show(message, subtext, options) {
            this._clearTransferTimer();
            this._transferMode = false;
            const overlay = this._ensureOverlay();
            const bar = overlay.querySelector('#bundle-upload-progress-bar');
            if (bar) {
                bar.classList.remove('is-transfer');
                bar.style.transform = '';
            }
            const opts = options || {};
            this._maxPercent = typeof opts.percent === 'number' ? opts.percent : 0;
            this._indeterminate = !!opts.indeterminate;
            overlay.querySelector('.bundle-upload-message').textContent = message || 'Working...';
            overlay.querySelector('.bundle-upload-subtext').textContent = subtext || 'Please wait, do not close this page.';
            this._setBarWidth(this._maxPercent, false);
            this.setProgress(this._maxPercent, !!opts.showProgress || this._indeterminate);
            overlay.classList.remove('hidden');
        },

        setProgress(percent, showProgress) {
            const overlay = this._ensureOverlay();
            const wrap = overlay.querySelector('#bundle-upload-progress-wrap');
            const label = overlay.querySelector('#bundle-upload-progress-label');
            const spinner = overlay.querySelector('.bundle-upload-spinner');
            if (typeof percent === 'number') {
                this._maxPercent = Math.max(this._maxPercent || 0, percent);
                if (this._indeterminate && this._maxPercent >= 3) {
                    this._indeterminate = false;
                }
            }
            const displayPercent = this._maxPercent || 0;
            const showBar = !this._indeterminate && (
                showProgress || (displayPercent > 0 && displayPercent <= 100)
            );
            wrap.classList.toggle('hidden', !showBar);
            spinner.classList.toggle('hidden', showBar && displayPercent >= 5);
            if (showBar) {
                const safePercent = Math.max(0, Math.min(100, Math.round(displayPercent)));
                this._setBarWidth(safePercent, true);
                label.textContent = `${safePercent}%`;
            }
        },

        updateMessage(message, subtext, percent) {
            if (!this._overlay || this._overlay.classList.contains('hidden')) return;
            if (message) {
                this._overlay.querySelector('.bundle-upload-message').textContent = message;
            }
            if (subtext !== undefined) {
                this._overlay.querySelector('.bundle-upload-subtext').textContent = subtext;
            }
            if (typeof percent === 'number') {
                this.setProgress(percent, true);
            }
        },

        hide() {
            if (this._overlay) {
                this._clearTransferTimer();
                this._transferMode = false;
                const bar = this._overlay.querySelector('#bundle-upload-progress-bar');
                if (bar) {
                    bar.classList.remove('is-transfer');
                    bar.style.transform = '';
                }
                this._overlay.classList.add('hidden');
                this._maxPercent = 0;
                this._indeterminate = false;
            }
        },
    };

    function sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    async function pollPdfStatus(statusUrl, onProgress) {
        let maxPercent = 0;
        for (let attempt = 0; attempt < 600; attempt += 1) {
            const response = await fetch(statusUrl, {
                credentials: 'same-origin',
                headers: {'X-Requested-With': 'XMLHttpRequest'},
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(data.error || data.message || 'PDF generation failed');
            }
            if (typeof data.percent === 'number') {
                maxPercent = Math.max(maxPercent, data.percent);
            }
            if (typeof onProgress === 'function') {
                onProgress({
                    ...data,
                    ...(typeof data.percent === 'number' ? {percent: maxPercent} : {}),
                });
            }
            if (data.ready === true || data.status === 'ready') {
                return data;
            }
            await sleep(500);
        }
        throw new Error('PDF generation timed out. Please try again.');
    }

    async function readResponseBlob(response, onProgress) {
        if (!response.body) {
            return response.blob();
        }
        const total = Number(response.headers.get('Content-Length')) || 0;
        if (!total || typeof onProgress !== 'function') {
            return response.blob();
        }

        const reader = response.body.getReader();
        const chunks = [];
        let loaded = 0;
        while (true) {
            const {done, value} = await reader.read();
            if (done) {
                break;
            }
            chunks.push(value);
            loaded += value.length;
            onProgress(loaded / total);
        }
        return new Blob(chunks, {type: response.headers.get('Content-Type') || 'application/pdf'});
    }

    async function downloadPdfBlob(url, filename, options) {
        const opts = options || {};
        const headers = {
            'X-Requested-With': 'XMLHttpRequest',
            'X-Bundle-Serve-Only': '1',
        };
        const transferMessages = opts.transferMessages || [
            'Fetching the PDF from storage...',
            'Large bundles may take a little longer...',
            'Your download will start automatically...',
        ];
        let lastError = null;

        if (opts.useTransfer && global.BundleUpload) {
            global.BundleUpload.beginTransfer(
                opts.transferTitle || 'Downloading PDF...',
                transferMessages,
            );
        }

        for (let attempt = 0; attempt < 10; attempt += 1) {
            if (opts.useTransfer && global.BundleUpload && attempt > 0) {
                global.BundleUpload.beginTransfer(
                    'Almost ready...',
                    ['Finalising the PDF file...', 'Retrying download...'],
                );
            }

            const response = await fetch(url, {
                credentials: 'same-origin',
                headers,
            });
            const contentType = response.headers.get('Content-Type') || '';
            if (response.status === 409 && attempt < 9) {
                if (global.BundleUpload) {
                    global.BundleUpload.beginTransfer(
                        'Almost ready...',
                        ['The PDF is still being prepared...', 'Please wait a moment...'],
                    );
                }
                await sleep(800);
                continue;
            }
            if (!response.ok) {
                if (contentType.includes('application/json')) {
                    const data = await response.json();
                    lastError = new Error(data.error || 'Download failed');
                    throw lastError;
                }
                lastError = new Error('Download failed');
                throw lastError;
            }
            if (!contentType.includes('application/pdf')) {
                lastError = new Error('Download failed');
                throw lastError;
            }

            const blob = await readResponseBlob(response, ratio => {
                if (opts.useTransfer && global.BundleUpload) {
                    global.BundleUpload.updateTransferProgress(ratio);
                }
            });

            const objectUrl = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = objectUrl;
            link.download = filename || 'bundle.pdf';
            document.body.appendChild(link);
            link.click();
            link.remove();
            URL.revokeObjectURL(objectUrl);

            if (opts.useTransfer && global.BundleUpload) {
                global.BundleUpload.finishTransfer(
                    'Download started',
                    'Check your downloads folder if the file did not open.',
                );
                await sleep(450);
            }

            if (typeof opts.onComplete === 'function') {
                opts.onComplete(response);
            }
            return;
        }
        throw lastError || new Error('Download failed');
    }

    async function downloadPdf(url, filename, options) {
        const opts = options || {};
        if (!opts.skipOverlay) {
            BundleUpload.show(
                opts.message || 'Preparing download...',
                opts.subtext || 'Please wait.',
                {showProgress: !!opts.showProgress, percent: opts.percent || 0},
            );
        }
        try {
            const response = await fetch(url, {
                credentials: 'same-origin',
                headers: {'X-Requested-With': 'XMLHttpRequest'},
            });
            const contentType = response.headers.get('Content-Type') || '';
            if (!response.ok) {
                if (contentType.includes('application/json')) {
                    const data = await response.json();
                    throw new Error(data.error || 'Download failed');
                }
                if (contentType.includes('text/html')) {
                    window.location.href = url;
                    return;
                }
                throw new Error('Download failed');
            }
            if (!contentType.includes('application/pdf')) {
                if (contentType.includes('text/html')) {
                    window.location.href = url;
                    return;
                }
                throw new Error('Download failed');
            }
            const blob = await response.blob();
            const objectUrl = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = objectUrl;
            link.download = filename || 'bundle.pdf';
            document.body.appendChild(link);
            link.click();
            link.remove();
            URL.revokeObjectURL(objectUrl);
            if (typeof opts.onComplete === 'function') {
                opts.onComplete(response);
            }
        } catch (error) {
            alert(error.message || opts.errorMessage || 'Could not download PDF. Please try again.');
            throw error;
        } finally {
            if (!opts.skipOverlay) {
                BundleUpload.hide();
            }
        }
    }

    async function prepareAndDownload(options) {
        const opts = options || {};
        const prepareUrl = opts.prepareUrl;
        const statusUrl = opts.statusUrl;
        const downloadUrl = opts.downloadUrl;
        const filename = opts.filename || 'bundle.pdf';
        const csrfToken = opts.csrfToken || '';

        BundleUpload.show(
            opts.message || 'Preparing PDF...',
            opts.subtext || 'Checking whether the bundle needs to be regenerated.',
            {indeterminate: true},
        );

        try {
            const prepareResponse = await fetch(prepareUrl, {
                method: 'POST',
                credentials: 'same-origin',
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                    'X-CSRFToken': csrfToken,
                },
            });
            const prepareData = await prepareResponse.json().catch(() => ({}));
            if (!prepareResponse.ok) {
                throw new Error(prepareData.error || prepareData.message || 'Could not start PDF generation');
            }

            if (!prepareData.ready) {
                const initialPercent = typeof prepareData.percent === 'number' ? prepareData.percent : 3;
                BundleUpload.updateMessage(
                    opts.progressTitle || 'Generating PDF...',
                    prepareData.message || 'Please wait.',
                    initialPercent,
                );
                await pollPdfStatus(statusUrl, data => {
                    BundleUpload.updateMessage(
                        opts.progressTitle || 'Generating PDF...',
                        data.message || 'Please wait.',
                        typeof data.percent === 'number' ? data.percent : undefined,
                    );
                });
            }

            await downloadPdfBlob(downloadUrl, filename, {
                ...opts,
                skipOverlay: true,
                useTransfer: true,
                transferTitle: 'Downloading PDF...',
                transferMessages: [
                    'Fetching the PDF from storage...',
                    'Large bundles may take a little longer...',
                    'Your download will start automatically...',
                ],
            });
            if (typeof opts.onComplete === 'function') {
                opts.onComplete();
            }
        } catch (error) {
            alert(error.message || opts.errorMessage || 'Could not download PDF. Please try again.');
            throw error;
        } finally {
            BundleUpload.hide();
        }
    }

    async function deleteBundle(bundleId, bundleName, options) {
        const opts = options || {};
        const confirmMessage = opts.confirmMessage
            || `Are you sure you want to delete the bundle "${bundleName}"? This action cannot be undone.`;
        if (!window.confirm(confirmMessage)) {
            return false;
        }

        const csrfInput = document.querySelector('[name=csrfmiddlewaretoken]');
        const csrfToken = opts.csrfToken || (csrfInput ? csrfInput.value : '');

        try {
            const response = await fetch(`/bundle/${bundleId}/delete/`, {
                method: 'POST',
                credentials: 'same-origin',
                headers: {
                    'X-CSRFToken': csrfToken,
                    'X-Requested-With': 'XMLHttpRequest',
                    'Content-Type': 'application/json',
                },
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok || data.success === false) {
                throw new Error(data.error || 'Could not delete bundle');
            }
            if (typeof opts.onSuccess === 'function') {
                opts.onSuccess(data);
            } else {
                window.location.reload();
            }
            return true;
        } catch (error) {
            window.alert(error.message || opts.errorMessage || 'Error deleting bundle');
            return false;
        }
    }

    function bindBundleEditNavigation() {
        document.querySelectorAll('a[href*="/bundle/"]').forEach(link => {
            const href = link.getAttribute('href') || '';
            if (!/\/bundle\/\d+\/?$/.test(href)) {
                return;
            }
            link.addEventListener('click', () => {
                BundleUpload.show(
                    'Opening bundle editor...',
                    'Loading sections and documents.',
                );
            });
        });
        window.addEventListener('pageshow', () => BundleUpload.hide());
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bindBundleEditNavigation);
    } else {
        bindBundleEditNavigation();
    }

    global.BundleDownload = {
        downloadPdf,
        prepareAndDownload,
        pollPdfStatus,
        deleteBundle,
    };
})(window);
