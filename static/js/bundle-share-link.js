(function (global) {
    function updateCreateButton(root) {
        if (!root) {
            return;
        }
        const btn = root.querySelector('.bundle-share-create-btn');
        if (!btn) {
            return;
        }
        if (btn.dataset.loading === 'true') {
            btn.disabled = true;
            return;
        }
        const sharepointOk = btn.dataset.sharepointEnabled !== 'false';
        btn.disabled = !sharepointOk;
    }

    function setLoading(root, loading) {
        const btn = root && root.querySelector('.bundle-share-create-btn');
        if (!btn) {
            return;
        }
        if (loading) {
            if (!btn.dataset.originalLabel) {
                btn.dataset.originalLabel = btn.textContent.trim();
            }
            btn.dataset.loading = 'true';
            btn.disabled = true;
            btn.setAttribute('aria-busy', 'true');
            btn.textContent = 'Creating link...';
            btn.classList.add('opacity-70', 'cursor-wait');
        } else {
            btn.dataset.loading = 'false';
            btn.removeAttribute('aria-busy');
            btn.classList.remove('opacity-70', 'cursor-wait');
            btn.textContent = btn.dataset.originalLabel || 'Create share link';
            updateCreateButton(root);
        }
    }

    function resetShareOptions(root) {
        const passwordToggle = root.querySelector('.bundle-share-use-password');
        if (passwordToggle) {
            passwordToggle.checked = true;
        }
        updateCreateButton(root);
    }

    function bindRoot(root) {
        if (!root || root.dataset.shareRiskBound === '1') {
            return;
        }
        root.dataset.shareRiskBound = '1';
        updateCreateButton(root);
    }

    function createPayload(root) {
        const passwordToggle = root.querySelector('.bundle-share-use-password');
        const payload = {};
        if (passwordToggle) {
            payload.use_password = passwordToggle.checked;
        }
        return payload;
    }

    function setSharepointEnabled(root, enabled) {
        const btn = root && root.querySelector('.bundle-share-create-btn');
        if (btn) {
            btn.dataset.sharepointEnabled = enabled ? 'true' : 'false';
        }
        updateCreateButton(root);
    }

    function copyText(value) {
        if (!value) {
            return;
        }
        navigator.clipboard.writeText(value).catch(function () {
            const input = document.createElement('textarea');
            input.value = value;
            document.body.appendChild(input);
            input.select();
            document.execCommand('copy');
            input.remove();
        });
    }

    function resolveLinkStatus(link) {
        if (link.status === 'revoked' || link.revoked_at) {
            return 'revoked';
        }
        if (link.expires_at) {
            const expiresAt = new Date(link.expires_at);
            if (!Number.isNaN(expiresAt.getTime()) && expiresAt.getTime() <= Date.now()) {
                return 'expired';
            }
        }
        if (link.status === 'expired') {
            return 'expired';
        }
        return link.status === 'active' || link.active ? 'active' : (link.status || 'active');
    }

    function formatShareLinkStatus(status) {
        if (status === 'active') {
            return 'Active';
        }
        if (status === 'expired') {
            return 'Expired';
        }
        if (status === 'revoked') {
            return 'Revoked';
        }
        return status;
    }

    function formatShareDate(value) {
        if (!value) {
            return '—';
        }
        return new Date(value).toLocaleString(undefined, {
            day: '2-digit',
            month: 'short',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
        });
    }

    function statusBadgeClass(status) {
        if (status === 'active') {
            return 'inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium bg-green-50 text-green-800';
        }
        if (status === 'expired') {
            return 'inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium bg-amber-50 text-amber-800';
        }
        return 'inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium bg-gray-100 text-gray-600';
    }

    function makeCopyButton(label, value, buttonClass) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = buttonClass || 'bundle-linear-btn text-xs';
        btn.textContent = label;
        btn.addEventListener('click', function () {
            copyText(value);
            const original = btn.textContent;
            btn.textContent = 'Copied';
            window.setTimeout(function () {
                btn.textContent = original;
            }, 1500);
        });
        return btn;
    }

    function renderExpiryNote(root, data) {
        const expiryNote = root.querySelector('.bundle-share-expiry-note');
        if (!expiryNote) {
            return;
        }
        const days = Number(data.link_expiry_days);
        if (!days || Number.isNaN(days)) {
            expiryNote.classList.add('hidden');
            expiryNote.textContent = '';
            return;
        }
        const dayLabel = days === 1 ? 'day' : 'days';
        expiryNote.textContent = `Each new link stays active for ${days} ${dayLabel} unless you revoke it sooner. After that date the link expires and shows as Expired below.`;
        expiryNote.classList.remove('hidden');
    }

    function renderShareLinks(root, data, options) {
        const listEl = root.querySelector('.bundle-share-links-list');
        const emptyEl = root.querySelector('.bundle-share-links-empty');
        const staleWarning = root.querySelector('.bundle-share-stale-warning');
        const scopeNote = root.querySelector('.bundle-share-scope-note');
        const buttonClass = options.buttonClass || 'bundle-linear-btn text-xs';

        if (!listEl) {
            return;
        }

        const links = Array.isArray(data.links) ? data.links : [];
        listEl.innerHTML = '';

        if (emptyEl) {
            emptyEl.classList.toggle('hidden', links.length > 0);
        }

        if (staleWarning) {
            staleWarning.classList.toggle('hidden', !data.stale);
        }

        if (scopeNote) {
            if (data.link_scope === 'organization') {
                scopeNote.textContent =
                    'Links are organisation-only: recipients must sign in with a firm Microsoft account.';
            } else {
                scopeNote.textContent =
                    'Links are for anyone with the URL (requires SharePoint external sharing to be enabled).';
            }
        }

        renderExpiryNote(root, data);

        if (!links.length) {
            return;
        }

        const table = document.createElement('table');
        table.className = 'bundle-share-links-table w-full text-xs text-left border-collapse';

        const thead = document.createElement('thead');
        thead.innerHTML = ''
            + '<tr class="border-b border-gray-200 text-gray-500">'
            + '<th class="py-2 pr-3 font-medium">Created</th>'
            + '<th class="py-2 pr-3 font-medium">Expires</th>'
            + '<th class="py-2 pr-3 font-medium">Status</th>'
            + '<th class="py-2 font-medium text-right">Actions</th>'
            + '</tr>';
        table.appendChild(thead);

        const tbody = document.createElement('tbody');
        links.forEach(function (link) {
            const status = resolveLinkStatus(link);
            const row = document.createElement('tr');
            row.className = 'border-b border-gray-100 last:border-0';
            if (status === 'expired') {
                row.classList.add('bg-amber-50/40');
            } else if (status === 'revoked') {
                row.classList.add('opacity-70');
            }
            row.dataset.linkId = link.id;

            const createdCell = document.createElement('td');
            createdCell.className = 'py-2.5 pr-3 text-gray-700 whitespace-nowrap';
            createdCell.textContent = formatShareDate(link.created_at);
            row.appendChild(createdCell);

            const expiresCell = document.createElement('td');
            expiresCell.className = 'py-2.5 pr-3 whitespace-nowrap';
            if (status === 'expired') {
                expiresCell.className += ' text-amber-800 font-medium';
                expiresCell.textContent = link.expires_at
                    ? `Expired (${formatShareDate(link.expires_at)})`
                    : 'Expired';
            } else {
                expiresCell.className += ' text-gray-700';
                expiresCell.textContent = formatShareDate(link.expires_at);
            }
            row.appendChild(expiresCell);

            const statusCell = document.createElement('td');
            statusCell.className = 'py-2.5 pr-3';
            const statusBadge = document.createElement('span');
            statusBadge.className = statusBadgeClass(status);
            statusBadge.textContent = formatShareLinkStatus(status);
            statusCell.appendChild(statusBadge);
            row.appendChild(statusCell);

            const actionsCell = document.createElement('td');
            actionsCell.className = 'py-2.5 text-right whitespace-nowrap';
            const actionsWrap = document.createElement('div');
            actionsWrap.className = 'inline-flex flex-wrap items-center justify-end gap-1.5';

            if (status === 'active' && link.url) {
                actionsWrap.appendChild(makeCopyButton('Copy link', link.url, buttonClass));
            }
            if (status === 'active' && link.password) {
                actionsWrap.appendChild(makeCopyButton('Copy pass', link.password, buttonClass));
            }
            if (status === 'active' && typeof options.onRevoke === 'function') {
                const revokeBtn = document.createElement('button');
                revokeBtn.type = 'button';
                revokeBtn.className = buttonClass;
                revokeBtn.textContent = 'Revoke';
                revokeBtn.addEventListener('click', function () {
                    options.onRevoke(link.id);
                });
                actionsWrap.appendChild(revokeBtn);
            }
            if (!actionsWrap.childNodes.length) {
                const inactiveLabel = document.createElement('span');
                inactiveLabel.className = 'text-gray-400 text-xs';
                inactiveLabel.textContent = status === 'expired' ? 'Expired' : (status === 'revoked' ? 'Revoked' : '—');
                actionsWrap.appendChild(inactiveLabel);
            }
            actionsCell.appendChild(actionsWrap);
            row.appendChild(actionsCell);

            tbody.appendChild(row);
        });

        table.appendChild(tbody);
        listEl.appendChild(table);
    }

    async function createWithProgress(options) {
        const root = options.root;
        const bundleId = options.bundleId;
        const csrfToken = options.csrfToken || '';
        const payload = options.createPayload || {};
        const statusUrl = options.statusUrl || `/bundle/${bundleId}/share-link/`;
        const createUrl = options.createUrl || `/bundle/${bundleId}/share-link/create/`;

        setLoading(root, true);
        if (global.BundleUpload) {
            global.BundleUpload.show(
                'Creating share link...',
                'Checking the bundle PDF is ready to share.',
                { showProgress: true, percent: 10 },
            );
        }

        try {
            const statusResponse = await fetch(statusUrl, {
                credentials: 'same-origin',
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
            });
            const statusData = await statusResponse.json().catch(function () {
                return {};
            });
            if (!statusResponse.ok) {
                throw new Error(statusData.error || 'Could not check bundle share status.');
            }

            if (global.BundleUpload) {
                global.BundleUpload.updateMessage(
                    'Creating share link...',
                    'Contacting Microsoft SharePoint.',
                    45,
                );
            }

            let progress = 45;
            const progressTimer = global.BundleUpload ? window.setInterval(function () {
                if (progress < 90) {
                    progress += 3;
                    global.BundleUpload.updateMessage(
                        'Creating share link...',
                        'Waiting for Microsoft SharePoint...',
                        progress,
                    );
                }
            }, 700) : null;

            let response;
            try {
                response = await fetch(createUrl, {
                    method: 'POST',
                    credentials: 'same-origin',
                    headers: {
                        'X-CSRFToken': csrfToken,
                        'X-Requested-With': 'XMLHttpRequest',
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(payload),
                });
            } finally {
                if (progressTimer) {
                    window.clearInterval(progressTimer);
                }
            }

            const data = await response.json().catch(function () {
                return {};
            });
            if (!response.ok) {
                throw new Error(data.error || 'Could not create share link.');
            }

            if (global.BundleUpload) {
                global.BundleUpload.updateMessage(
                    'Share link created',
                    'Updating the link list...',
                    100,
                );
            }

            return data;
        } finally {
            if (global.BundleUpload) {
                global.BundleUpload.hide();
            }
            setLoading(root, false);
        }
    }

    global.BundleShareLink = {
        bindRoot: bindRoot,
        resetShareOptions: resetShareOptions,
        updateCreateButton: updateCreateButton,
        createPayload: createPayload,
        setSharepointEnabled: setSharepointEnabled,
        setLoading: setLoading,
        createWithProgress: createWithProgress,
        renderShareLinks: renderShareLinks,
        copyText: copyText,
    };
}(window));
