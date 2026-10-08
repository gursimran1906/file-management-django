(function (global) {
    function copyText(value) {
        if (global.BundleShareLink && global.BundleShareLink.copyText) {
            global.BundleShareLink.copyText(value);
            return;
        }
        if (value && navigator.clipboard) {
            navigator.clipboard.writeText(value).catch(function () {});
        }
    }

    function formatDate(value) {
        if (!value) {
            return '—';
        }
        const parsed = new Date(value);
        if (Number.isNaN(parsed.getTime())) {
            return '—';
        }
        return parsed.toLocaleString(undefined, {
            day: '2-digit',
            month: 'short',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
        });
    }

    function formatBytes(bytes) {
        if (bytes === null || bytes === undefined || Number.isNaN(Number(bytes))) {
            return '';
        }
        const value = Number(bytes);
        if (value < 1024) {
            return value + ' B';
        }
        const kb = value / 1024;
        if (kb < 1024) {
            return kb.toFixed(0) + ' KB';
        }
        const mb = kb / 1024;
        return mb.toFixed(mb < 10 ? 1 : 0) + ' MB';
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

    function statusLabel(status) {
        if (status === 'active') return 'Active';
        if (status === 'expired') return 'Expired';
        if (status === 'revoked') return 'Revoked';
        return status;
    }

    function statusBadgeClass(status) {
        const base = 'inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium ';
        if (status === 'active') return base + 'bg-green-50 text-green-800';
        if (status === 'expired') return base + 'bg-amber-50 text-amber-800';
        return base + 'bg-gray-100 text-gray-600';
    }

    function makeButton(label, onClick, extraClass) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'bundle-linear-btn text-xs' + (extraClass ? ' ' + extraClass : '');
        btn.textContent = label;
        btn.addEventListener('click', onClick);
        return btn;
    }

    function makeCopyButton(label, value) {
        const btn = makeButton(label, function () {
            copyText(value);
            const original = btn.textContent;
            btn.textContent = 'Copied';
            window.setTimeout(function () { btn.textContent = original; }, 1500);
        });
        return btn;
    }

    function renderLinkRow(link, options) {
        const status = resolveLinkStatus(link);
        const row = document.createElement('div');
        row.className = 'flex flex-wrap items-center gap-2 py-1.5 border-b border-gray-100 last:border-0';
        if (status === 'revoked') {
            row.classList.add('text-gray-400');
        }

        const badge = document.createElement('span');
        badge.className = statusBadgeClass(status);
        badge.textContent = statusLabel(status);
        row.appendChild(badge);

        const meta = document.createElement('span');
        meta.className = 'text-[11px] text-gray-500';
        if (status === 'expired') {
            meta.textContent = 'Expired ' + formatDate(link.expires_at);
        } else if (status === 'active' && link.expires_at) {
            meta.textContent = 'Expires ' + formatDate(link.expires_at);
        } else if (status === 'revoked') {
            meta.textContent = 'Revoked ' + formatDate(link.revoked_at);
        } else {
            meta.textContent = 'Created ' + formatDate(link.created_at);
        }
        row.appendChild(meta);

        const actions = document.createElement('div');
        actions.className = 'ml-auto inline-flex flex-wrap items-center gap-1.5';
        if (status === 'active' && link.url) {
            actions.appendChild(makeCopyButton('Copy link', link.url));
        }
        if (status === 'active' && link.password) {
            actions.appendChild(makeCopyButton('Copy pass', link.password));
        }
        if (status === 'active' && typeof options.onRevoke === 'function') {
            actions.appendChild(makeButton('Revoke', function () {
                options.onRevoke(link.id);
            }));
        }
        row.appendChild(actions);
        return row;
    }

    function renderVersionCard(version, options) {
        const card = document.createElement('div');
        card.id = 'bundle-version-' + version.version;
        card.className = 'bundle-version-card rounded-lg border px-3 py-3 space-y-2 scroll-mt-24 '
            + (version.is_current ? 'border-green-200 bg-green-50/40' : 'border-gray-200');

        const header = document.createElement('div');
        header.className = 'flex flex-wrap items-center gap-2';

        const title = document.createElement('span');
        title.className = 'font-semibold text-sm text-gray-900';
        title.textContent = 'v' + version.version;
        header.appendChild(title);

        if (version.is_current) {
            const current = document.createElement('span');
            current.className = 'inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium bg-green-100 text-green-800';
            current.textContent = 'Current';
            header.appendChild(current);
        }
        if (version.pinned) {
            const pin = document.createElement('span');
            pin.className = 'inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium bg-indigo-50 text-indigo-700';
            pin.textContent = 'Pinned';
            header.appendChild(pin);
        }
        if (version.label) {
            const label = document.createElement('span');
            label.className = 'inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium bg-gray-100 text-gray-700';
            label.textContent = version.label;
            header.appendChild(label);
        }

        const actions = document.createElement('div');
        actions.className = 'ml-auto inline-flex flex-wrap items-center gap-1.5';

        const download = document.createElement('a');
        download.className = 'bundle-linear-btn text-xs';
        download.textContent = 'Download';
        download.href = '/bundle/' + options.bundleId + '/version/' + version.id + '/download/';
        actions.appendChild(download);

        if (!version.is_current && typeof options.onPromote === 'function') {
            actions.appendChild(makeButton('Make current', function () {
                options.onPromote(version.id, version.version);
            }));
        }
        if (typeof options.onPin === 'function') {
            actions.appendChild(makeButton(version.pinned ? 'Unpin' : 'Pin', function () {
                options.onPin(version.id, !version.pinned);
            }));
        }
        if (options.sharepointEnabled && typeof options.onShare === 'function') {
            actions.appendChild(makeButton('Share', function () {
                options.onShare(version.id, version.version);
            }, 'btn-primary'));
        }
        header.appendChild(actions);
        card.appendChild(header);

        const meta = document.createElement('p');
        meta.className = 'text-[11px] text-gray-500';
        const bits = [];
        bits.push('Generated ' + formatDate(version.pdf_generated_at || version.created_at));
        if (version.page_count) {
            bits.push(version.page_count + (version.page_count === 1 ? ' page' : ' pages'));
        }
        const size = formatBytes(version.size_bytes);
        if (size) bits.push(size);
        if (version.created_by) bits.push('by ' + version.created_by);
        meta.textContent = bits.join(' · ');
        card.appendChild(meta);

        const links = Array.isArray(version.links) ? version.links : [];
        if (links.length) {
            const linksWrap = document.createElement('div');
            linksWrap.className = 'mt-1 rounded-md border border-gray-100 bg-white px-2';
            links.forEach(function (link) {
                linksWrap.appendChild(renderLinkRow(link, options));
            });
            card.appendChild(linksWrap);
        }

        return card;
    }

    function render(container, data, options) {
        if (!container) {
            return;
        }
        container.innerHTML = '';
        const versions = Array.isArray(data.versions) ? data.versions : [];
        if (!versions.length) {
            const empty = document.createElement('p');
            empty.className = 'text-xs text-gray-500';
            empty.textContent = 'No versions yet. Use Download PDF to generate the first version.';
            container.appendChild(empty);
            return;
        }
        versions.forEach(function (version) {
            container.appendChild(renderVersionCard(version, options));
        });
    }

    global.BundleVersions = {
        render: render,
        formatDate: formatDate,
        formatBytes: formatBytes,
    };
}(window));
