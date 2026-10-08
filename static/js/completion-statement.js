(function () {
    const app = document.getElementById('completion-statement-app');
    if (!app) return;

    const editable = app.dataset.editable === 'true';
    let headerSaveTimer = null;

    function getCsrfToken() {
        const input = app.querySelector('[name=csrfmiddlewaretoken]');
        return input ? input.value : '';
    }

    function setSaveStatus(text) {
        // Re-query: the header chrome (and this element) can be swapped by softReload.
        const el = document.getElementById('cs-save-status');
        if (el) el.textContent = text || '';
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
                    updateTotals(data);
                }
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

    function updateTotalsHeader(data) {
        const totals = data.totals || {};
        const map = {
            'cs-add-total': totals.money_in_total_display || totals.add_total_display,
            'cs-less-total': totals.money_out_total_display || totals.less_total_display,
            'cs-balance-total': totals.balance_display,
        };
        Object.entries(map).forEach(([id, value]) => {
            const el = document.getElementById(id);
            if (el && value !== undefined) el.textContent = value;
        });

        const outcome = document.getElementById('cs-outcome-label');
        const banner = document.getElementById('cs-balance-banner');
        if (outcome && totals.outcome_label) {
            outcome.textContent = totals.outcome_label;
            outcome.classList.toggle('text-green-800', totals.is_balanced);
            outcome.classList.toggle('text-amber-900', !totals.is_balanced);
        }
        if (banner) {
            banner.classList.toggle('border-green-200', totals.is_balanced);
            banner.classList.toggle('bg-green-50', totals.is_balanced);
            banner.classList.toggle('border-amber-200', !totals.is_balanced);
            banner.classList.toggle('bg-amber-50', !totals.is_balanced);
        }

        updateSummaries(data.summaries);
    }

    function updateTotals(data) {
        updateTotalsHeader(data);
        if (data.lines) {
            data.lines.forEach((line, index) => {
                const rows = app.querySelectorAll('#cs-lines-list .estate-line-row:not([data-pinned="true"])');
                const row = rows[index];
                if (row) {
                    const balanceCell = row.querySelector('.cs-running-balance');
                    if (balanceCell) balanceCell.textContent = line.running_balance_display || '';
                }
            });
            const pinnedRow = app.querySelector('#cs-lines-list [data-pinned="true"]');
            if (pinnedRow && data.completion_monies_line) {
                const balanceCell = pinnedRow.querySelector('.cs-running-balance');
                if (balanceCell) {
                    balanceCell.textContent = data.completion_monies_line.running_balance_display || '';
                }
                const addCell = pinnedRow.querySelector('td:nth-child(4) .cs-line-readonly');
                const lessCell = pinnedRow.querySelector('td:nth-child(5) .cs-line-readonly');
                const cmLine = data.completion_monies_line;
                if (addCell) {
                    addCell.textContent = cmLine.direction === 'add' ? cmLine.amount_display : '';
                }
                if (lessCell) {
                    lessCell.textContent = cmLine.direction === 'less' ? cmLine.amount_display : '';
                }
            }
        }
    }

    function updateSummaries(summaries) {
        if (!summaries) return;
        if (summaries.header) {
            const el = document.getElementById('cs-summary-header');
            if (el) el.textContent = summaries.header;
        }
        if (summaries.lines) {
            const el = document.getElementById('cs-summary-lines');
            if (el) el.textContent = summaries.lines;
        }
    }

    function updatePreparedSummary() {
        const name = app.querySelector('[data-header-field="prepared_by_name"]')?.value.trim();
        const el = document.getElementById('cs-summary-prepared');
        if (el) el.textContent = name || 'Not set';
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
            payload[field.dataset.headerField] = field.value;
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
        const original = field.dataset.originalValue;
        if (original !== undefined && field.value === original) {
            return Promise.resolve();
        }
        const payload = { [key]: field.value };
        return postJson(app.dataset.updateUrl, payload).then(() => {
            if (field.dataset.originalValue !== undefined) {
                field.dataset.originalValue = field.value;
            }
        });
    }

    function linePayload(row) {
        const payload = { line_kind: row.dataset.lineKind };
        if (row.dataset.lineId) payload.id = row.dataset.lineId;
        if (row.dataset.sourceType) {
            payload.source_type = row.dataset.sourceType;
            payload.source_id = row.dataset.sourceId;
        }

        const addField = row.querySelector('[data-line-field="add_amount"]');
        const lessField = row.querySelector('[data-line-field="less_amount"]');
        if (addField || lessField) {
            const addVal = parseFloat(addField?.value) || 0;
            const lessVal = parseFloat(lessField?.value) || 0;
            if (addVal > 0) {
                payload.direction = 'add';
                payload.amount = addVal.toFixed(2);
            } else if (lessVal > 0) {
                payload.direction = 'less';
                payload.amount = lessVal.toFixed(2);
            } else {
                payload.direction = 'less';
                payload.amount = '0.00';
            }
        }

        row.querySelectorAll('[data-line-field]').forEach(field => {
            const key = field.dataset.lineField;
            if (key === 'add_amount' || key === 'less_amount') return;
            if (field.type === 'checkbox') {
                payload[key] = field.checked;
            } else {
                payload[key] = field.value;
            }
        });
        return payload;
    }

    function saveLineRow(row) {
        if (!editable || row.dataset.pinned === 'true') return Promise.resolve();
        return postJson(app.dataset.lineUpdateUrl, linePayload(row)).then(() => {
            row.querySelectorAll('[data-line-field]').forEach(field => {
                if (field.dataset.originalValue !== undefined) {
                    field.dataset.originalValue = field.value;
                }
            });
            const excludeField = row.querySelector('[data-line-field="is_excluded"]');
            if (excludeField) {
                row.classList.toggle('estate-line-row--excluded', excludeField.checked);
            }
        });
    }

    function deleteLineRow(row) {
        if (!editable) return;
        const payload = { line_kind: row.dataset.lineKind };
        if (row.dataset.lineId) payload.id = row.dataset.lineId;
        if (row.dataset.sourceType) {
            payload.source_type = row.dataset.sourceType;
            payload.source_id = row.dataset.sourceId;
        }
        const list = row.closest('tbody');
        postJson(app.dataset.lineDeleteUrl, payload).then(() => {
            row.remove();
            if (list && !list.querySelector('.estate-line-row:not([data-pinned="true"])')) {
                const empty = list.querySelector('.estate-empty-msg');
                if (!empty) {
                    list.insertAdjacentHTML('beforeend',
                        '<tr class="estate-empty-msg"><td colspan="7">No lines yet.</td></tr>');
                }
            }
        }).catch(() => {});
    }

    function escapeHtml(value) {
        return String(value || '').replace(/[&<>"']/g, char => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        }[char]));
    }

    function buildManualLineHtml(line) {
        const addVal = line.direction === 'add' ? line.amount : '';
        const lessVal = line.direction === 'less' ? line.amount : '';
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
                <input type="number" step="0.01" class="estate-line-add-amount estate-line-amount bundle-linear-field w-full"
                       data-line-field="add_amount" value="${addVal}" placeholder="0.00">
            </td>
            <td class="estate-line-amount-cell">
                <input type="number" step="0.01" class="estate-line-less-amount estate-line-amount bundle-linear-field w-full"
                       data-line-field="less_amount" value="${lessVal}" placeholder="0.00">
            </td>
            <td class="estate-line-balance-cell">
                <span class="cs-running-balance">${line.running_balance_display || ''}</span>
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

    function addLine(direction) {
        postJson(app.dataset.lineAddUrl, {
            direction,
            description: 'New entry',
            amount: '0.00',
            is_pending: true,
        }).then(data => {
            const list = document.getElementById('cs-lines-list');
            const empty = list.querySelector('.estate-empty-msg');
            if (empty) empty.remove();
            list.insertAdjacentHTML('beforeend', buildManualLineHtml(data.line));
            bindLineRows(list);
        }).catch(() => {});
    }

    function bindAddLessFields(row) {
        const addField = row.querySelector('[data-line-field="add_amount"]');
        const lessField = row.querySelector('[data-line-field="less_amount"]');
        if (!addField || !lessField) return;

        addField.addEventListener('input', () => {
            if (parseFloat(addField.value) > 0) lessField.value = '';
        });
        lessField.addEventListener('input', () => {
            if (parseFloat(lessField.value) > 0) addField.value = '';
        });
    }

    function bindLineRows(container) {
        (container || app).querySelectorAll('.estate-line-row').forEach(row => {
            if (row.dataset.bound) return;
            row.dataset.bound = '1';
            if (row.dataset.pinned === 'true') return;

            bindAddLessFields(row);
            row.querySelectorAll('[data-line-field]').forEach(field => {
                field.addEventListener('blur', () => saveLineRow(row));
                if (field.type === 'checkbox') {
                    field.addEventListener('change', () => saveLineRow(row));
                } else if (field.tagName === 'SELECT') {
                    field.addEventListener('change', () => saveLineRow(row));
                }
            });
            const deleteBtn = row.querySelector('[data-delete-line]');
            if (deleteBtn) deleteBtn.addEventListener('click', () => deleteLineRow(row));
        });
    }

    function bindHeaderFields() {
        app.querySelectorAll('[data-header-field]').forEach(field => {
            if (field.tagName === 'TEXTAREA') {
                field.addEventListener('input', () => {
                    queueHeaderSave();
                    if (field.dataset.headerField === 'prepared_by_name') {
                        updatePreparedSummary();
                    }
                });
                field.addEventListener('blur', queueHeaderSave);
            } else if (field.tagName === 'SELECT') {
                field.addEventListener('change', () => {
                    saveHeaderField(field).then(() => softReload()).catch(() => {});
                });
            } else {
                field.addEventListener('blur', () => {
                    saveHeaderField(field).then(() => {
                        if (field.dataset.headerField === 'prepared_by_name') {
                            updatePreparedSummary();
                        }
                    }).catch(() => {});
                });
            }
        });
    }

    function bindActions() {
        app.querySelectorAll('[data-add-line]').forEach(button => {
            button.addEventListener('click', () => addLine(button.dataset.addLine));
        });

        const finaliseBtn = document.getElementById('cs-finalise-btn');
        if (finaliseBtn) {
            finaliseBtn.addEventListener('click', () => {
                if (!window.confirm('Finalise this completion statement? Balance must be £0.00.')) return;
                postJson(app.dataset.statusUrl, { action: 'finalise' }).then(() => {
                    softReload();
                }).catch(() => {});
            });
        }

        const reopenBtn = document.getElementById('cs-reopen-btn');
        if (reopenBtn) {
            reopenBtn.addEventListener('click', () => {
                postJson(app.dataset.statusUrl, { action: 'reopen' }).then(() => {
                    softReload();
                }).catch(() => {});
            });
        }
    }

    // Bind (or re-bind) every panel. Called on load and again after softReload
    // swaps in freshly server-rendered content.
    function bindAll() {
        bindHeaderFields();
        bindLineRows();
        bindActions();
        bindTabs();
        bindMortgageFields();
        bindApportionmentPanel();
        bindDistributionPanel();
        bindSchedulePanel();
        initAutoTextareas();
    }

    // Expose the re-bind entry point so softReload can re-wire fresh content.
    app.csBindAll = bindAll;

    bindAll();
})();

function bindTabs() {
    const app = document.getElementById('completion-statement-app');
    if (!app) return;
    const tabs = app.querySelectorAll('[data-cs-tab]');
    const panels = app.querySelectorAll('[data-cs-panel]');

    function activate(name) {
        tabs.forEach(t => {
            const on = t.dataset.csTab === name;
            t.classList.toggle('is-active', on);
            t.setAttribute('aria-selected', on ? 'true' : 'false');
        });
        panels.forEach(panel => {
            panel.classList.toggle('hidden', panel.dataset.csPanel !== name);
        });
    }

    function rememberTab(name) {
        try { sessionStorage.setItem('cs-active-tab', name); } catch (e) { /* ignore */ }
    }

    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const name = tab.dataset.csTab;
            rememberTab(name);
            activate(name);
        });
    });

    // Restore the last active tab after a (soft) reload so actions don't bounce
    // the user back to the main statement.
    let restore = null;
    try { restore = sessionStorage.getItem('cs-active-tab'); } catch (e) { /* ignore */ }
    if (restore && Array.from(tabs).some(t => t.dataset.csTab === restore)) {
        activate(restore);
    }
}

function bindMortgageFields() {
    const app = document.getElementById('completion-statement-app');
    if (!app || app.dataset.editable !== 'true' || !app.dataset.mortgageUrl) return;
    const panel = document.getElementById('cs-mortgage-panel');
    if (!panel) return;

    function collectMortgage() {
        const payload = {};
        panel.querySelectorAll('[data-mortgage-field]').forEach(field => {
            payload[field.dataset.mortgageField] = field.value;
        });
        return payload;
    }

    let timer = null;
    function saveMortgage() {
        clearTimeout(timer);
        timer = setTimeout(() => {
            fetch(app.dataset.mortgageUrl, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': app.querySelector('[name=csrfmiddlewaretoken]').value,
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(collectMortgage()),
            }).then(r => r.json()).then(data => {
                if (data.error) throw new Error(data.error);
                if (data.mortgage_redemption) {
                    const m = data.mortgage_redemption;
                    const days = document.getElementById('cs-mortgage-days');
                    const interest = document.getElementById('cs-mortgage-interest');
                    const total = document.getElementById('cs-mortgage-total');
                    if (days) days.textContent = m.calculated_days;
                    if (interest) interest.textContent = m.calculated_interest_display;
                    if (total) total.textContent = m.total_amount_display;
                }
                softReload();
            }).catch(err => alert(err.message));
        }, 500);
    }

    panel.querySelectorAll('[data-mortgage-field]').forEach(field => {
        field.addEventListener('blur', saveMortgage);
        field.addEventListener('change', saveMortgage);
    });
}

function csPost(app, url, payload) {
    return fetch(url, {
        method: 'POST',
        headers: {
            'X-CSRFToken': app.querySelector('[name=csrfmiddlewaretoken]').value,
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload || {}),
    }).then(r => r.json()).then(data => {
        if (data.error) throw new Error(data.error);
        return data;
    });
}

// Re-render the whole page in place: fetch the freshly server-rendered page,
// swap the app section and header chrome, and re-bind. Keeps the app element
// itself (so the page's event closures stay valid) and restores the active tab.
function softReload() {
    const app = document.getElementById('completion-statement-app');
    if (!app) { window.location.reload(); return Promise.resolve(); }
    const active = app.querySelector('[data-cs-tab].is-active')?.dataset.csTab;
    if (active) {
        try { sessionStorage.setItem('cs-active-tab', active); } catch (e) { /* ignore */ }
    }
    return fetch(window.location.href, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
        .then(r => r.text())
        .then(html => {
            const doc = new DOMParser().parseFromString(html, 'text/html');
            const fresh = doc.getElementById('completion-statement-app');
            if (!fresh) { window.location.reload(); return; }
            app.innerHTML = fresh.innerHTML;
            if (fresh.dataset.editable) app.dataset.editable = fresh.dataset.editable;
            // Refresh the header chrome that reflects status / type / finalise state.
            ['cs-header-badges', 'cs-header-actions'].forEach(id => {
                const cur = document.getElementById(id);
                const next = doc.getElementById(id);
                if (cur && next) cur.innerHTML = next.innerHTML;
            });
            if (app.csBindAll) app.csBindAll();
        })
        .catch(() => window.location.reload());
}

function bindApportionmentRows(app) {
    if (app.dataset.editable !== 'true') return;
    app.querySelectorAll('[data-ap-delete]').forEach(btn => {
        btn.addEventListener('click', () => {
            csPost(app, app.dataset.apportionmentDeleteUrl, { id: btn.dataset.apDelete })
                .then(() => softReload()).catch(err => alert(err.message));
        });
    });
    app.querySelectorAll('[data-apportionment-id]').forEach(row => {
        row.querySelectorAll('[data-ap-field]').forEach(field => {
            field.addEventListener('blur', () => {
                const payload = { id: row.dataset.apportionmentId };
                row.querySelectorAll('[data-ap-field]').forEach(f => {
                    payload[f.dataset.apField] = f.value;
                });
                csPost(app, app.dataset.apportionmentUpdateUrl, payload)
                    .then(() => softReload()).catch(err => alert(err.message));
            });
        });
    });
}

function bindApportionmentPanel() {
    const app = document.getElementById('completion-statement-app');
    if (!app) return;
    bindApportionmentRows(app);
    if (app.dataset.editable !== 'true') return;
    const addBtn = document.getElementById('cs-apportionment-add');
    if (addBtn) {
        addBtn.addEventListener('click', () => {
            csPost(app, app.dataset.apportionmentAddUrl, {
                description: 'Rent apportionment',
                annual_amount: '0',
                item_type: 'rent',
                direction: 'add',
                paid_in_advance: true,
            }).then(() => softReload()).catch(err => alert(err.message));
        });
    }
}

function bindDistributionPanel() {
    const app = document.getElementById('completion-statement-app');
    if (!app || app.dataset.editable !== 'true') return;
    const addBtn = document.getElementById('cs-distribution-add');
    if (addBtn) {
        addBtn.addEventListener('click', () => {
            csPost(app, app.dataset.distributionAddUrl, {
                payee_name: 'Payee',
                share_mode: 'remainder',
                share_value: '',
            }).then(() => softReload()).catch(err => alert(err.message));
        });
    }
    app.querySelectorAll('[data-dist-delete]').forEach(btn => {
        btn.addEventListener('click', () => {
            csPost(app, app.dataset.distributionDeleteUrl, { id: btn.dataset.distDelete })
                .then(() => softReload()).catch(err => alert(err.message));
        });
    });
    app.querySelectorAll('[data-distribution-id]').forEach(row => {
        const save = () => {
            const payload = { id: row.dataset.distributionId };
            row.querySelectorAll('[data-dist-field]').forEach(f => {
                payload[f.dataset.distField] = f.value;
            });
            csPost(app, app.dataset.distributionUpdateUrl, payload)
                .then(() => softReload()).catch(err => alert(err.message));
        };
        row.querySelectorAll('[data-dist-field]').forEach(field => {
            field.addEventListener('blur', save);
            field.addEventListener('change', save);
        });
    });
}

function refreshBankIndicator(app, id) {
    const bankRow = app.querySelector(`[data-bank-row="${id}"]`);
    const toggle = app.querySelector(`[data-sched-bank-toggle="${id}"]`);
    if (!bankRow || !toggle) return;
    const sort = bankRow.querySelector('[data-sched-field="bank_sort_code"]')?.value.trim();
    const acct = bankRow.querySelector('[data-sched-field="bank_account_number"]')?.value.trim();
    toggle.innerHTML = (sort && acct) ? '<span class="text-green-700">✓ Bank</span>' : 'Add bank';
}

// Bind the per-row handlers. Called on load and after every in-place re-render.
function bindScheduleRows(app) {
    app.querySelectorAll('[data-sched-bank-toggle]').forEach(btn => {
        btn.addEventListener('click', () => {
            const bankRow = app.querySelector(`[data-bank-row="${btn.dataset.schedBankToggle}"]`);
            if (bankRow) bankRow.classList.toggle('hidden');
        });
    });
    if (app.dataset.editable !== 'true') return;
    app.querySelectorAll('[data-sched-create-slip]').forEach(btn => {
        btn.addEventListener('click', () => {
            const row = btn.closest('[data-schedule-id]');
            const ledger = row?.querySelector('[data-sched-field="ledger_account"]')?.value || 'C';
            const url = app.dataset.scheduleCreateSlipUrl.replace('/0/', `/${btn.dataset.schedCreateSlip}/`);
            if (!window.confirm(`Create slip from client/${ledger === 'O' ? 'office' : 'client'} account?`)) return;
            csPost(app, url, { ledger_account: ledger }).then(() => softReload()).catch(err => alert(err.message));
        });
    });
    app.querySelectorAll('[data-sched-field]').forEach(field => {
        const scheduleId = field.closest('[data-schedule-id]')?.dataset.scheduleId
            || field.closest('[data-bank-row]')?.dataset.bankRow;
        if (!scheduleId) return;
        field.addEventListener('change', () => {
            const payload = { id: scheduleId };
            payload[field.dataset.schedField] = field.value;
            csPost(app, app.dataset.scheduleUpdateUrl, payload).then(() => {
                // Keep the bank panel open; just refresh its summary indicator.
                if (field.dataset.schedField.startsWith('bank_')) {
                    refreshBankIndicator(app, scheduleId);
                }
            }).catch(err => alert(err.message));
        });
    });
}

function bindSchedulePanel() {
    const app = document.getElementById('completion-statement-app');
    if (!app) return;
    bindScheduleRows(app);
    if (app.dataset.editable !== 'true') return;
    const addBtn = document.getElementById('cs-schedule-add');
    if (addBtn) {
        addBtn.addEventListener('click', () => {
            csPost(app, app.dataset.scheduleAddUrl, {
                payee_name: 'New payee',
                description: '',
                direction: 'less',
                ledger_account: 'C',
                projected_amount: '0',
            }).then(() => softReload()).catch(err => alert(err.message));
        });
    }
}
