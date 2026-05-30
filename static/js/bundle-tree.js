window.BundleTree = {
    escapeHtml(value) {
        return String(value || '').replace(/[&<>"']/g, char => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        }[char]));
    },

    getSectionHeading(sectionEl) {
        const input = sectionEl.querySelector('.section-heading-input, .builder-section-heading');
        return input ? input.value.trim() || 'Untitled section' : 'Untitled section';
    },

    getDocumentTitle(docEl) {
        const input = docEl.querySelector('.document-description-input');
        if (input) return input.value.trim() || 'Document';
        const titleEl = docEl.querySelector('.bundle-doc-title');
        return titleEl ? titleEl.textContent.trim() : 'Document';
    },

    getDocumentDate(docEl) {
        const dateInput = docEl.querySelector('.document-date-input');
        if (dateInput && dateInput.value) {
            if (window.BundleFilenameUtils && BundleFilenameUtils.formatUkDate) {
                return BundleFilenameUtils.formatUkDate(dateInput.value);
            }
            return dateInput.value;
        }

        const dateDisplay = docEl.querySelector('.bundle-doc-display-date');
        if (!dateDisplay) return '';

        const text = dateDisplay.textContent.trim();
        return text && text !== '—' ? text : '';
    },

    formatOutlineDocument(docEl) {
        const title = this.escapeHtml(this.getDocumentTitle(docEl));
        const date = this.getDocumentDate(docEl);
        if (!date) return title;
        return `${title}<span class="bundle-structure-doc-date">${this.escapeHtml(date)}</span>`;
    },

    refreshLabels(containerSelector) {
        const container = document.querySelector(containerSelector);
        if (!container) return;

        container.querySelectorAll('.section-card').forEach((sectionEl, sectionIndex) => {
            const sectionNum = sectionIndex + 1;
            const sectionLabel = sectionEl.querySelector('.section-index-label');
            if (sectionLabel) {
                const isLinearEdit = !!container.closest('.bundle-edit-page');
                sectionLabel.textContent = isLinearEdit ? `${sectionNum}` : `Sec ${sectionNum}`;
            }

            const docs = sectionEl.querySelectorAll('.document-item');
            docs.forEach((docEl, docIndex) => {
                const docLabel = docEl.querySelector('.doc-index-label');
                if (docLabel) docLabel.textContent = `${sectionNum}.${docIndex + 1}`;
            });
        });
    },

    refreshOutline(outlineId, containerSelector) {
        const outline = document.getElementById(outlineId);
        const container = document.querySelector(containerSelector);
        if (!outline || !container) return;

        const sections = container.querySelectorAll('.section-card');
        if (sections.length === 0) {
            outline.innerHTML = '<p class="text-xs text-gray-400">Add sections to see the bundle structure.</p>';
            return;
        }

        let html = '<ul class="bundle-structure-list">';
        sections.forEach((sectionEl, sectionIndex) => {
            const sectionNum = sectionIndex + 1;
            const heading = this.getSectionHeading(sectionEl);
            const docs = sectionEl.querySelectorAll('.document-item');

            html += `<li><span class="bundle-structure-section">${sectionNum}. ${this.escapeHtml(heading)}</span>`;
            html += '<ul>';
            if (docs.length === 0) {
                html += '<li class="bundle-structure-empty">No documents yet</li>';
            } else {
                docs.forEach((docEl, docIndex) => {
                    html += `<li class="bundle-structure-doc">${sectionNum}.${docIndex + 1} ${this.formatOutlineDocument(docEl)}</li>`;
                });
            }
            html += '</ul></li>';
        });
        html += '</ul>';
        outline.innerHTML = html;
    },

    refresh(containerSelector, outlineId) {
        this.refreshLabels(containerSelector);
        this.refreshOutline(outlineId, containerSelector);
    },

    bindHeadingInputs(containerSelector, outlineId) {
        document.querySelectorAll('.section-heading-input, .builder-section-heading, .document-description-input, .document-date-input').forEach(input => {
            if (input.dataset.bundleTreeBound) return;
            input.dataset.bundleTreeBound = '1';
            const eventName = input.classList.contains('document-date-input') ? 'change' : 'input';
            input.addEventListener(eventName, () => this.refreshOutline(outlineId, containerSelector));
        });
    },

    init(containerSelector, outlineId) {
        this.refresh(containerSelector, outlineId);
        this.bindHeadingInputs(containerSelector, outlineId);
    }
};
