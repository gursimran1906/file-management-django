/*
 * The risk assessment form.
 *
 * The rating is scored server-side (backend/risk_scoring.py) so there is only
 * ever one set of weights. This script keeps the page in step with it as the
 * answers are given: it posts the answers to the score-preview endpoint, swaps
 * in the re-rendered panel, holds the rating dropdowns on the scored rating
 * until someone deliberately moves one, and reveals the questions that only
 * apply given an earlier answer.
 *
 * Nothing here decides a rating. If this script does not run, the form still
 * works: the server scores the answers again on save and refuses an override
 * without a reason.
 */
(function () {
    'use strict';

    const form = document.getElementById('risk-assessment-form');
    if (!form) {
        return;
    }

    const scoreUrl = form.dataset.scoreUrl;
    const panel = document.getElementById('risk-score-panel');
    const summary = document.getElementById('risk-computed-summary');
    const overrideBox = document.getElementById('risk-override-box');
    const eddFields = document.getElementById('risk-edd-fields');
    const eddNotNeeded = document.getElementById('risk-edd-not-needed');

    // The three recorded ratings, against the computed value each follows.
    const RATINGS = [
        { name: 'client_risk_level', computed: ['client', 'level'], summary: 'client' },
        { name: 'matter_risk_level', computed: ['matter', 'level'], summary: 'matter' },
        { name: 'customer_due_diligence_level', computed: ['due_diligence_level'], summary: 'dd' },
    ];

    // Set from the last scoring: the regulations can require enhanced due
    // diligence whatever the dropdown has been set to.
    let eddRequired = form.dataset.eddRequired === 'true';

    // A rating stops following the score once someone changes it themselves.
    const touched = new Set();
    RATINGS.forEach(function (rating) {
        const select = form.elements[rating.name];
        if (!select) {
            return;
        }
        // An assessment saved with an override arrives already differing from
        // its score, so treat it as touched rather than snapping it back.
        if (overrideBox && !overrideBox.classList.contains('hidden')) {
            touched.add(rating.name);
        }
        select.addEventListener('change', function () {
            touched.add(rating.name);
        });
    });

    function valueAt(breakdown, path) {
        return path.reduce(function (value, key) {
            return value == null ? value : value[key];
        }, breakdown);
    }

    /* Tint a question whose answer is the one that carries risk, so a long
       part-filled form shows where the risk is without reading it all. */
    function markRiskyAnswers() {
        form.querySelectorAll('.risk-question').forEach(function (row) {
            const risky = row.dataset.risky;
            const field = row.querySelector('select, input');
            const isRisky = Boolean(risky) && field && field.value === risky;
            row.classList.toggle('risk-question-risky', isRisky);
        });
    }

    /* The "issues identified" box for a section is only required once
       something in that section is flagged, so its hint says so. */
    function markNeededDetails() {
        form.querySelectorAll('[data-flag-hint]').forEach(function (hint) {
            const section = hint.closest('.div-container');
            const flagged = Boolean(section
                && section.querySelector('.risk-question-risky'));
            hint.classList.toggle('text-amber-800', flagged);
            hint.classList.toggle('font-medium', flagged);
            hint.classList.toggle('text-gray-500', !flagged);
        });
    }

    /* Questions that only make sense given an earlier answer. */
    function applyConditionalSections() {
        form.querySelectorAll('[data-show-when]').forEach(function (block) {
            const field = form.elements[block.dataset.showWhen];
            const wanted = (block.dataset.showValues || '').split(',');
            const show = Boolean(field) && wanted.indexOf(field.value) !== -1;
            block.classList.toggle('hidden', !show);
        });
    }

    function applyBreakdown(breakdown) {
        RATINGS.forEach(function (rating) {
            const select = form.elements[rating.name];
            const computed = valueAt(breakdown, rating.computed);
            if (!select || !computed) {
                return;
            }
            if (!touched.has(rating.name)) {
                select.value = computed;
            }
            if (summary) {
                const cell = summary.querySelector('[data-computed="' + rating.summary + '"]');
                if (cell) {
                    cell.textContent = computed;
                }
            }
        });

        // The override box only matters once a recorded rating differs from
        // the score. The reason it holds is required server-side.
        if (overrideBox) {
            const differs = RATINGS.some(function (rating) {
                const select = form.elements[rating.name];
                const computed = valueAt(breakdown, rating.computed);
                return select && computed && select.value !== computed;
            });
            const hasError = overrideBox.querySelector('.text-red-700');
            overrideBox.classList.toggle('hidden', !differs && !hasError);
        }

        eddRequired = Boolean(breakdown.edd_reasons && breakdown.edd_reasons.length);
        applyEddVisibility();
    }

    /* Section 6 is for what was done about enhanced due diligence, so it
       appears once enhanced due diligence applies. */
    function applyEddVisibility() {
        const select = form.elements.customer_due_diligence_level;
        const enhanced = eddRequired
            || (Boolean(select) && select.value === 'Enhanced');
        if (eddFields) {
            eddFields.classList.toggle('hidden', !enhanced);
        }
        if (eddNotNeeded) {
            eddNotNeeded.classList.toggle('hidden', enhanced);
        }
    }

    let pending = null;

    function refreshScore() {
        if (!scoreUrl) {
            return;
        }
        fetch(scoreUrl, {
            method: 'POST',
            body: new FormData(form),
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
        })
            .then(function (response) {
                return response.ok ? response.json() : null;
            })
            .then(function (data) {
                if (!data || !data.ok) {
                    return;
                }
                if (panel && data.html) {
                    panel.innerHTML = data.html;
                }
                applyBreakdown(data.breakdown);
            })
            .catch(function () {
                /* Leave the last rating on screen; the server scores again on
                   save, so a failed preview cannot produce a wrong record. */
            });
    }

    function scheduleRefresh() {
        markRiskyAnswers();
        markNeededDetails();
        applyConditionalSections();
        window.clearTimeout(pending);
        pending = window.setTimeout(refreshScore, 250);
    }

    form.addEventListener('change', scheduleRefresh);
    form.addEventListener('input', function (event) {
        // Only the transaction value changes the score as it is typed.
        if (event.target && event.target.name === 'matter_transaction_value') {
            scheduleRefresh();
        }
    });

    markRiskyAnswers();
    markNeededDetails();
    applyConditionalSections();
    applyEddVisibility();
})();
