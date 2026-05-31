(function () {
    const app = document.getElementById('estate-account-app');
    if (!app) return;

    const editable = app.dataset.editable === 'true';
    const saveStatus = document.getElementById('estate-save-status');
    let headerSaveTimer = null;
    let distributionSaveTimers = new Map();

    function getCsrfToken() {
        const input = app.querySelector('[name=csrfmiddlewaretoken]');
        return input ? input.value : '';
    }

    function setSaveStatus(text) {
        if (saveStatus) saveStatus.textContent = text || '';
    }

    function postJson(url, payload) {
        setSaveStatus('Saving…');
        return fetch(url, {
            method: 'POST',
            headers: {
                'X-CSRFToken': getCsrfToken(),
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(payload || {}),
        })
            .then(response => response.json().then(data => ({ ok: response.ok, data })))
            .then(({ ok, data }) => {
                if (!ok || data.error) {
                    throw new Error(data.error || 'Save failed');
                }
                if (data.totals) {
                    updateTotals(data.totals);
                }
                updateAllSummaries();
                setSaveStatus('Saved');
                window.setTimeout(() => setSaveStatus(''), 1500);
                return data;
            })
            .catch(error => {
                setSaveStatus('');
                alert(error.message || 'Save failed');
                throw error;
            });
    }

    function updateTotals(totals) {
        const map = {
            'total-gross': totals.gross_estate_display,
            'total-debts': totals.total_debts_paid_display,
            'total-net': totals.net_estate_display,
            'total-iht': totals.inheritance_tax_display,
            'total-balance': totals.balance_for_distribution_display,
            'total-distribution': totals.distribution_total_display,
            'total-distribution-payments': totals.distribution_payments_total_display,
        };
        Object.entries(map).forEach(([id, value]) => {
            const el = document.getElementById(id);
            if (el) el.textContent = value;
        });
    }

    function formatMoney(amount) {
        const value = Number(amount) || 0;
        return new Intl.NumberFormat('en-GB', {
            style: 'currency',
            currency: 'GBP',
        }).format(value);
    }

    function formatDisplayDate(isoValue) {
        if (!isoValue) return '';
        const [year, month, day] = isoValue.split('-');
        if (!day) return isoValue;
        return `${day}/${month}/${year}`;
    }

    function setSummaryText(id, text) {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    }

    function linesSummaryText(listId) {
        const tbody = document.getElementById(listId);
        if (!tbody) return 'No lines';
        const rows = tbody.querySelectorAll('.estate-line-row:not(.estate-line-row--excluded)');
        const excludedCount = tbody.querySelectorAll('.estate-line-row--excluded').length;
        let total = 0;
        rows.forEach(row => {
            const amountField = row.querySelector('[data-line-field="amount"]');
            if (amountField) total += parseFloat(amountField.value) || 0;
        });
        if (!rows.length) return 'No lines';
        const lineWord = rows.length === 1 ? 'line' : 'lines';
        let text = `${rows.length} ${lineWord} · ${formatMoney(total)}`;
        if (excludedCount) {
            const excludedWord = excludedCount === 1 ? 'line' : 'lines';
            text += ` · ${excludedCount} excluded ${excludedWord}`;
        }
        return text;
    }

    function updateCoverSummary() {
        const parts = [];
        const deceased = app.querySelector('[data-header-field="deceased_name"]')?.value.trim();
        const dod = app.querySelector('[data-header-field="date_of_death"]')?.value;
        const accountDate = app.querySelector('[data-header-field="account_date"]')?.value;
        const iht = app.querySelector('[data-header-field="inheritance_tax"]')?.value;
        if (deceased) parts.push(deceased);
        if (dod) parts.push(`DOD ${formatDisplayDate(dod)}`);
        if (accountDate) parts.push(`Account ${formatDisplayDate(accountDate)}`);
        if (iht !== undefined && iht !== '') parts.push(`IHT ${formatMoney(iht)}`);
        setSummaryText('estate-summary-cover', parts.join(' · ') || 'Cover details not set');
    }

    function updateDistributionSummary() {
        const parts = [];
        const paymentsBody = document.getElementById('estate-distribution-payments-list');
        const paymentCount = paymentsBody
            ? paymentsBody.querySelectorAll('.estate-line-row:not(.estate-line-row--excluded)').length
            : 0;
        if (paymentCount) {
            const paymentWord = paymentCount === 1 ? 'payment' : 'payments';
            const paymentsTotal = document.getElementById('total-distribution-payments')?.textContent
                || formatMoney(0);
            parts.push(`${paymentCount} finance ${paymentWord} · ${paymentsTotal}`);
        }
        const beneficiaryCount = app.querySelectorAll('.estate-distribution-row').length;
        if (beneficiaryCount) {
            const beneficiaryWord = beneficiaryCount === 1 ? 'beneficiary' : 'beneficiaries';
            parts.push(`${beneficiaryCount} ${beneficiaryWord}`);
        }
        const distributionTotal = document.getElementById('total-distribution')?.textContent
            || formatMoney(0);
        parts.push(`Total ${distributionTotal}`);
        setSummaryText('estate-summary-distribution', parts.join(' · '));
    }

    function updateAcknowledgementSummary() {
        const parts = [];
        const signerCount = app.querySelectorAll('.estate-client-signer').length;
        if (signerCount) {
            const clientWord = signerCount === 1 ? 'client' : 'clients';
            parts.push(`${signerCount} signing ${clientWord}`);
        }
        const text = app.querySelector('[data-header-field="acknowledgement_text"]')
            ?.value.trim().replace(/\s+/g, ' ');
        if (text) {
            parts.push(text.length > 72 ? `${text.slice(0, 69).trim()}…` : text);
        }
        setSummaryText('estate-summary-acknowledgement', parts.join(' · ') || 'Acknowledgement not set');
    }

    function updateAllSummaries() {
        updateCoverSummary();
        setSummaryText('estate-summary-assets', linesSummaryText('estate-assets-list'));
        setSummaryText('estate-summary-debts', linesSummaryText('estate-debts-list'));
        updateDistributionSummary();
        updateAcknowledgementSummary();
    }

    const SECTION_LIST_IDS = {
        asset: 'estate-assets-list',
        debt: 'estate-debts-list',
        distribution: 'estate-distribution-payments-list',
    };

    function moveLineRowToSection(row, section) {
        const targetId = SECTION_LIST_IDS[section];
        if (!targetId) return;
        const targetBody = document.getElementById(targetId);
        const sourceBody = row.closest('tbody');
        if (!targetBody || sourceBody === targetBody) return;

        const targetEmpty = targetBody.querySelector('.estate-empty-msg');
        if (targetEmpty) targetEmpty.remove();

        targetBody.appendChild(row);

        if (sourceBody && !sourceBody.querySelector('.estate-line-row')) {
            sourceBody.insertAdjacentHTML('beforeend', emptyLineMessage(sourceBody.id));
        }

        const sectionField = row.querySelector('[data-line-field="section"]');
        if (sectionField) {
            sectionField.dataset.originalValue = section;
        }
        updateAllSummaries();
    }

    function autoResizeTextarea(textarea) {
        textarea.style.height = 'auto';
        textarea.style.height = `${textarea.scrollHeight}px`;
    }

    function initAutoTextareas(root) {
        (root || app).querySelectorAll('.estate-auto-textarea').forEach(textarea => {
            autoResizeTextarea(textarea);
            if (textarea.dataset.autoResizeBound) return;
            textarea.dataset.autoResizeBound = '1';
            textarea.addEventListener('input', () => autoResizeTextarea(textarea));
        });
    }

    function collectHeaderPayload() {
        const payload = {};
        app.querySelectorAll('[data-header-field]').forEach(field => {
            const key = field.dataset.headerField;
            if (field.type === 'checkbox') {
                payload[key] = field.checked;
            } else {
                payload[key] = field.value;
            }
        });
        return payload;
    }

    function queueHeaderSave() {
        if (!editable) return;
        clearTimeout(headerSaveTimer);
        headerSaveTimer = window.setTimeout(() => {
            postJson(app.dataset.updateUrl, collectHeaderPayload()).catch(() => {});
        }, 400);
    }

    function saveHeaderField(field) {
        if (!editable) return Promise.resolve();
        const key = field.dataset.headerField;
        const payload = {};
        if (field.type === 'checkbox') {
            payload[key] = field.checked;
        } else {
            const original = field.dataset.originalValue;
            if (original !== undefined && field.value === original) {
                return Promise.resolve();
            }
            payload[key] = field.value;
        }
        return postJson(app.dataset.updateUrl, payload).then(() => {
            if (field.dataset.originalValue !== undefined) {
                field.dataset.originalValue = field.value;
            }
        });
    }

    function linePayload(row) {
        const payload = {
            line_kind: row.dataset.lineKind,
        };
        if (row.dataset.lineId) payload.id = row.dataset.lineId;
        if (row.dataset.sourceType) {
            payload.source_type = row.dataset.sourceType;
            payload.source_id = row.dataset.sourceId;
        }
        row.querySelectorAll('[data-line-field]').forEach(field => {
            const key = field.dataset.lineField;
            if (field.type === 'checkbox') {
                payload[key] = field.checked;
            } else {
                payload[key] = field.value;
            }
        });
        return payload;
    }

    function saveLineRow(row) {
        if (!editable) return Promise.resolve();
        const sectionField = row.querySelector('[data-line-field="section"]');
        const sectionChanged = sectionField
            && sectionField.dataset.originalValue !== undefined
            && sectionField.value !== sectionField.dataset.originalValue;
        return postJson(app.dataset.lineUpdateUrl, linePayload(row)).then(() => {
            if (sectionChanged && sectionField) {
                moveLineRowToSection(row, sectionField.value);
            }
            row.querySelectorAll('[data-line-field]').forEach(field => {
                if (field.dataset.originalValue !== undefined) {
                    field.dataset.originalValue = field.value;
                }
            });
            const excludeField = row.querySelector('[data-line-field="is_excluded"]');
            if (excludeField) {
                setLineExcludedState(row, excludeField.checked);
            }
        });
    }

    function setLineExcludedState(row, excluded) {
        row.classList.toggle('estate-line-row--excluded', excluded);
    }

    function deleteLineRow(row) {
        if (!editable) return;
        const payload = {
            line_kind: row.dataset.lineKind,
        };
        if (row.dataset.lineId) payload.id = row.dataset.lineId;
        if (row.dataset.sourceType) {
            payload.source_type = row.dataset.sourceType;
            payload.source_id = row.dataset.sourceId;
        }
        const list = row.closest('tbody');
        postJson(app.dataset.lineDeleteUrl, payload).then(() => {
            row.remove();
            if (list && !list.querySelector('.estate-line-row')) {
                list.insertAdjacentHTML('beforeend', emptyLineMessage(list.id));
            }
            updateAllSummaries();
        }).catch(() => {});
    }

    function emptyLineMessage(listId) {
        const labels = {
            'estate-assets-list': 'asset',
            'estate-debts-list': 'debt',
            'estate-distribution-payments-list': 'distribution payment from Finances',
        };
        const label = labels[listId] || 'line';
        return `<tr class="estate-empty-msg"><td colspan="5">No ${label} lines yet.</td></tr>`;
    }

    function buildManualLineHtml(line) {
        return `
        <tr class="estate-line-row" data-line-kind="manual" data-line-id="${line.id}">
            <td class="estate-line-source">
                <span class="estate-line-badge estate-line-badge--manual">Pending</span>
            </td>
            <td class="estate-line-date-cell">
                <input type="date" class="estate-line-date bundle-linear-field w-full" data-line-field="date"
                       value="${line.date_iso || ''}" data-original-value="${line.date_iso || ''}">
            </td>
            <td class="estate-line-desc-cell">
                <input type="text" class="estate-line-desc bundle-linear-field w-full" data-line-field="description"
                       value="${escapeHtml(line.description || '')}" data-original-value="${escapeHtml(line.description || '')}"
                       placeholder="Description">
            </td>
            <td class="estate-line-amount-cell">
                <input type="number" step="0.01" class="estate-line-amount bundle-linear-field w-full" data-line-field="amount"
                       value="${line.amount || '0.00'}" data-original-value="${line.amount || '0.00'}"
                       placeholder="0.00">
            </td>
            <td class="estate-line-actions-cell">
                <div class="estate-line-actions">
                    <label class="estate-line-action-label">
                        <input type="checkbox" data-line-field="is_pending" ${line.is_pending ? 'checked' : ''}> Pending
                    </label>
                    <button type="button" class="estate-line-delete-btn" data-delete-line>Delete</button>
                </div>
            </td>
        </tr>`;
    }

    function escapeHtml(value) {
        return String(value || '').replace(/[&<>"']/g, char => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        }[char]));
    }

    function addLine(section) {
        postJson(app.dataset.lineAddUrl, {
            section,
            description: 'New entry',
            amount: '0.00',
            is_pending: true,
        }).then(data => {
            const list = document.getElementById(section === 'asset' ? 'estate-assets-list' : 'estate-debts-list');
            const empty = list.querySelector('.estate-empty-msg');
            if (empty) empty.remove();
            list.insertAdjacentHTML('beforeend', buildManualLineHtml(data.line));
            bindLineRows(list);
        }).catch(() => {});
    }

    function distributionPayload(row) {
        const payload = { id: row.dataset.distributionId };
        row.querySelectorAll('[data-distribution-field]').forEach(field => {
            payload[field.dataset.distributionField] = field.value;
        });
        return payload;
    }

    function saveDistributionRow(row) {
        if (!editable) return Promise.resolve();
        return postJson(app.dataset.distributionUpdateUrl, distributionPayload(row)).then(data => {
            if (data.distribution) {
                const net = row.querySelector('.distribution-net');
                if (net) net.textContent = data.distribution.net_amount_display;
            }
        });
    }

    function buildDistributionHtml(row) {
        return `
        <div class="estate-distribution-row bundle-linear-panel py-2 px-3 grid grid-cols-1 md:grid-cols-6 gap-2"
             data-distribution-id="${row.id}">
            <input type="text" class="bundle-linear-field text-xs md:col-span-2" data-distribution-field="beneficiary_name"
                   value="${escapeHtml(row.beneficiary_name)}">
            <input type="text" class="bundle-linear-field text-xs" data-distribution-field="share_fraction"
                   value="${escapeHtml(row.share_fraction || '')}" placeholder="1/8">
            <input type="number" step="0.01" class="bundle-linear-field text-xs" data-distribution-field="gross_amount"
                   value="${row.gross_amount}">
            <input type="text" class="bundle-linear-field text-xs" data-distribution-field="adjustment_description"
                   value="${escapeHtml(row.adjustment_description || '')}">
            <div class="flex items-center gap-2">
                <input type="number" step="0.01" class="bundle-linear-field text-xs w-full" data-distribution-field="adjustment_amount"
                       value="${row.adjustment_amount || '0'}">
                <button type="button" class="text-xs text-red-600 shrink-0" data-delete-distribution>Delete</button>
            </div>
            <div class="text-xs text-gray-600 md:col-span-6">Net: <strong class="distribution-net">${row.net_amount_display}</strong></div>
        </div>`;
    }

    function bindLineRows(container) {
        (container || app).querySelectorAll('.estate-line-row').forEach(row => {
            if (row.dataset.bound) return;
            row.dataset.bound = '1';
            row.querySelectorAll('[data-line-field]').forEach(field => {
                field.addEventListener('blur', () => saveLineRow(row));
                if (field.type === 'checkbox') {
                    field.addEventListener('change', () => {
                        if (field.dataset.lineField === 'is_excluded') {
                            setLineExcludedState(row, field.checked);
                        }
                        saveLineRow(row);
                    });
                } else if (field.tagName === 'SELECT') {
                    field.addEventListener('change', () => saveLineRow(row));
                }
            });
            const deleteBtn = row.querySelector('[data-delete-line]');
            if (deleteBtn) deleteBtn.addEventListener('click', () => deleteLineRow(row));
        });
    }

    function bindDistributionRows(container) {
        (container || app).querySelectorAll('.estate-distribution-row').forEach(row => {
            if (row.dataset.bound) return;
            row.dataset.bound = '1';
            row.querySelectorAll('[data-distribution-field]').forEach(field => {
                const handler = () => {
                    clearTimeout(distributionSaveTimers.get(row));
                    distributionSaveTimers.set(row, window.setTimeout(() => {
                        saveDistributionRow(row).catch(() => {});
                    }, 400));
                };
                field.addEventListener('blur', handler);
                field.addEventListener('input', handler);
            });
            const deleteBtn = row.querySelector('[data-delete-distribution]');
            if (deleteBtn) {
                deleteBtn.addEventListener('click', () => {
                    postJson(app.dataset.distributionDeleteUrl, {
                        id: row.dataset.distributionId,
                    }).then(() => {
                        row.remove();
                        updateAllSummaries();
                    }).catch(() => {});
                });
            }
        });
    }

    function bindHeaderFields() {
        app.querySelectorAll('[data-header-field]').forEach(field => {
            if (field.tagName === 'TEXTAREA' || field.dataset.headerField === 'prepared_by_address'
                || field.dataset.headerField === 'will_clause_text'
                || field.dataset.headerField === 'distribution_notes'
                || field.dataset.headerField === 'acknowledgement_text') {
                field.addEventListener('input', () => {
                    queueHeaderSave();
                    updateAllSummaries();
                });
                field.addEventListener('blur', queueHeaderSave);
            } else if (field.dataset.headerField === 'deceased_name'
                || field.dataset.headerField === 'date_of_death'
                || field.dataset.headerField === 'account_date'
                || field.dataset.headerField === 'inheritance_tax') {
                field.addEventListener('input', updateCoverSummary);
                field.addEventListener('blur', () => saveHeaderField(field).catch(() => {}));
            } else if (field.type === 'checkbox') {
                field.addEventListener('change', () => {
                    if (field.id === 'use-manual-totals') {
                        document.getElementById('manual-totals-fields')
                            ?.classList.toggle('hidden', !field.checked);
                    }
                    saveHeaderField(field).catch(() => {});
                });
            } else {
                field.addEventListener('blur', () => saveHeaderField(field).catch(() => {}));
            }
        });
    }

    function bindActions() {
        app.querySelectorAll('[data-add-line]').forEach(button => {
            button.addEventListener('click', () => addLine(button.dataset.addLine));
        });

        const addDistribution = document.getElementById('estate-add-distribution');
        if (addDistribution) {
            addDistribution.addEventListener('click', () => {
                postJson(app.dataset.distributionAddUrl, {
                    beneficiary_name: 'Beneficiary',
                    gross_amount: '0.00',
                }).then(data => {
                    document.getElementById('estate-distributions-list')
                        .insertAdjacentHTML('beforeend', buildDistributionHtml(data.distribution));
                    bindDistributionRows(document.getElementById('estate-distributions-list'));
                }).catch(() => {});
            });
        }

        const finaliseBtn = document.getElementById('estate-finalise-btn');
        if (finaliseBtn) {
            finaliseBtn.addEventListener('click', () => {
                if (!window.confirm('Finalise this estate account? Editing will be locked.')) return;
                postJson(app.dataset.statusUrl, { action: 'finalise' }).then(() => {
                    window.location.reload();
                }).catch(() => {});
            });
        }

        const reopenBtn = document.getElementById('estate-reopen-btn');
        if (reopenBtn) {
            reopenBtn.addEventListener('click', () => {
                postJson(app.dataset.statusUrl, { action: 'reopen' }).then(() => {
                    window.location.reload();
                }).catch(() => {});
            });
        }
    }

    bindHeaderFields();
    bindLineRows();
    bindDistributionRows();
    bindActions();
    initAutoTextareas();
    updateAllSummaries();
})();
