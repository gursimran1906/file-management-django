(function () {
    const app = document.getElementById('completion-statement-app');
    if (!app) return;

    const editable = app.dataset.editable === 'true';
    const saveStatus = document.getElementById('cs-save-status');
    let headerSaveTimer = null;

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

    function updateTotals(data) {
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

        updateSummaries(data.summaries);
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
                    saveHeaderField(field).then(() => window.location.reload()).catch(() => {});
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
                    window.location.reload();
                }).catch(() => {});
            });
        }

        const reopenBtn = document.getElementById('cs-reopen-btn');
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
    bindActions();
    bindTabs();
    bindMortgageFields();
    bindApportionmentPanel();
    bindDistributionPanel();
    bindSchedulePanel();
    initAutoTextareas();
})();

function bindTabs() {
    const app = document.getElementById('completion-statement-app');
    if (!app) return;
    const tabs = app.querySelectorAll('[data-cs-tab]');
    const panels = app.querySelectorAll('[data-cs-panel]');
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const name = tab.dataset.csTab;
            tabs.forEach(t => {
                t.classList.toggle('is-active', t === tab);
                t.setAttribute('aria-selected', t === tab ? 'true' : 'false');
            });
            panels.forEach(panel => {
                panel.classList.toggle('hidden', panel.dataset.csPanel !== name);
            });
        });
    });
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
                window.location.reload();
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

function bindApportionmentPanel() {
    const app = document.getElementById('completion-statement-app');
    if (!app || app.dataset.editable !== 'true') return;
    const addBtn = document.getElementById('cs-apportionment-add');
    if (addBtn) {
        addBtn.addEventListener('click', () => {
            csPost(app, app.dataset.apportionmentAddUrl, {
                description: 'Rent apportionment',
                annual_amount: '0',
                item_type: 'rent',
                direction: 'add',
                paid_in_advance: true,
            }).then(() => window.location.reload());
        });
    }
    app.querySelectorAll('[data-ap-delete]').forEach(btn => {
        btn.addEventListener('click', () => {
            csPost(app, app.dataset.apportionmentDeleteUrl, { id: btn.dataset.apDelete })
                .then(() => window.location.reload());
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
                    .then(() => window.location.reload());
            });
        });
    });
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
            }).then(() => window.location.reload());
        });
    }
    app.querySelectorAll('[data-dist-delete]').forEach(btn => {
        btn.addEventListener('click', () => {
            csPost(app, app.dataset.distributionDeleteUrl, { id: btn.dataset.distDelete })
                .then(() => window.location.reload());
        });
    });
    app.querySelectorAll('[data-distribution-id]').forEach(row => {
        const save = () => {
            const payload = { id: row.dataset.distributionId };
            row.querySelectorAll('[data-dist-field]').forEach(f => {
                payload[f.dataset.distField] = f.value;
            });
            csPost(app, app.dataset.distributionUpdateUrl, payload)
                .then(() => window.location.reload());
        };
        row.querySelectorAll('[data-dist-field]').forEach(field => {
            field.addEventListener('blur', save);
            field.addEventListener('change', save);
        });
    });
}

function bindSchedulePanel() {
    const app = document.getElementById('completion-statement-app');
    if (!app || app.dataset.editable !== 'true') return;
    const addBtn = document.getElementById('cs-schedule-add');
    if (addBtn) {
        addBtn.addEventListener('click', () => {
            csPost(app, app.dataset.scheduleAddUrl, {
                payee_name: 'Payee',
                description: 'Manual payment',
                direction: 'less',
                ledger_account: 'C',
                projected_amount: '0',
            }).then(() => window.location.reload());
        });
    }
    app.querySelectorAll('[data-sched-create-slip]').forEach(btn => {
        btn.addEventListener('click', () => {
            const row = btn.closest('[data-schedule-id]');
            const ledger = row?.querySelector('[data-sched-field="ledger_account"]')?.value || 'C';
            const url = app.dataset.scheduleCreateSlipUrl.replace('/0/', `/${btn.dataset.schedCreateSlip}/`);
            if (!window.confirm(`Create slip from client/${ledger === 'O' ? 'office' : 'client'} account?`)) return;
            csPost(app, url, { ledger_account: ledger }).then(() => window.location.reload());
        });
    });
    app.querySelectorAll('[data-schedule-id]').forEach(row => {
        const ledgerField = row.querySelector('[data-sched-field="ledger_account"]');
        if (ledgerField) {
            ledgerField.addEventListener('change', () => {
                csPost(app, app.dataset.scheduleUpdateUrl, {
                    id: row.dataset.scheduleId,
                    ledger_account: ledgerField.value,
                }).then(() => window.location.reload());
            });
        }
    });
}
