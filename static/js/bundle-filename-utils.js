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
        + '.bundle-upload-progress-bar{height:100%;width:0;border-radius:9999px;background:#2563eb;transition:width .25s ease}'
        + '.bundle-upload-progress-label{font-size:.6875rem;color:#6b7280;text-align:right}'
        + '@keyframes bundle-upload-spin{to{transform:rotate(360deg)}}';

    global.BundleUpload = {
        _overlay: null,

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

        show(message, subtext, options) {
            const overlay = this._ensureOverlay();
            const opts = options || {};
            overlay.querySelector('.bundle-upload-message').textContent = message || 'Working...';
            overlay.querySelector('.bundle-upload-subtext').textContent = subtext || 'Please wait, do not close this page.';
            this.setProgress(opts.percent, opts.showProgress);
            overlay.classList.remove('hidden');
        },

        setProgress(percent, showProgress) {
            const overlay = this._ensureOverlay();
            const wrap = overlay.querySelector('#bundle-upload-progress-wrap');
            const bar = overlay.querySelector('#bundle-upload-progress-bar');
            const label = overlay.querySelector('#bundle-upload-progress-label');
            const spinner = overlay.querySelector('.bundle-upload-spinner');
            const shouldShow = showProgress || (typeof percent === 'number' && percent > 0 && percent < 100);
            wrap.classList.toggle('hidden', !shouldShow);
            spinner.classList.toggle('hidden', shouldShow && percent >= 5);
            if (typeof percent === 'number') {
                const safePercent = Math.max(0, Math.min(100, Math.round(percent)));
                bar.style.width = `${safePercent}%`;
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
                this._overlay.classList.add('hidden');
                this.setProgress(0, false);
            }
        },
    };

    function sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    async function pollPdfStatus(statusUrl, onProgress) {
        for (let attempt = 0; attempt < 600; attempt += 1) {
            const response = await fetch(statusUrl, {
                credentials: 'same-origin',
                headers: {'X-Requested-With': 'XMLHttpRequest'},
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(data.error || data.message || 'PDF generation failed');
            }
            if (typeof onProgress === 'function') {
                onProgress(data);
            }
            if (data.ready === true || data.status === 'ready') {
                return data;
            }
            await sleep(500);
        }
        throw new Error('PDF generation timed out. Please try again.');
    }

    async function downloadPdfBlob(url, filename, options) {
        const opts = options || {};
        const headers = {
            'X-Requested-With': 'XMLHttpRequest',
            'X-Bundle-Serve-Only': '1',
        };
        let lastError = null;
        for (let attempt = 0; attempt < 10; attempt += 1) {
            const response = await fetch(url, {
                credentials: 'same-origin',
                headers,
            });
            const contentType = response.headers.get('Content-Type') || '';
            if (response.status === 409 && attempt < 9) {
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
            {showProgress: true, percent: 0},
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
                await pollPdfStatus(statusUrl, data => {
                    BundleUpload.updateMessage(
                        opts.progressTitle || 'Generating PDF...',
                        data.message || 'Please wait.',
                        data.percent || 0,
                    );
                });
            } else {
                BundleUpload.updateMessage(
                    opts.readyTitle || 'PDF ready',
                    'Starting download...',
                    100,
                );
            }

            BundleUpload.updateMessage('Downloading PDF...', 'Your file will open shortly.', 100);
            await downloadPdfBlob(downloadUrl, filename, opts);
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
    };
})(window);
