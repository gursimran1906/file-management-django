(function () {
  function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(';').shift();
  }

  function csrfToken() {
    return getCookie('csrftoken');
  }

  function formatBytes(n) {
    if (!n) return '';
    if (n < 1024) return n + ' B';
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
    return (n / (1024 * 1024)).toFixed(1) + ' MB';
  }

  function normalizeDraftSummaries(data) {
    if (Array.isArray(data)) return data;
    if (typeof data === 'string' && data.trim()) {
      try {
        var parsed = JSON.parse(data);
        if (Array.isArray(parsed)) return parsed;
        if (typeof parsed === 'string') {
          parsed = JSON.parse(parsed);
          if (Array.isArray(parsed)) return parsed;
        }
      } catch (e) { /* ignore */ }
    }
    return [];
  }

  document.addEventListener('DOMContentLoaded', function () {
    const panel = document.getElementById('email-form-panel');
    const editorEl = document.getElementById('corr-body-editor');
    if (!panel || !editorEl || typeof Quill === 'undefined') return;

    const fileNumber = panel.dataset.fileNumber;
    const bodyInput = document.getElementById('corr-body-input');
    const statusEl = document.getElementById('corr-draft-status');
    const draftIdInput = document.getElementById('corr-draft-id');
    const draftSelect = document.getElementById('corr-draft-select');
    const newDraftBtn = document.getElementById('corr-new-draft');
    const fromInput = document.getElementById('from_mailbox');
    const toInput = document.getElementById('corr-to');
    const ccInput = document.getElementById('corr-cc');
    const bccInput = document.getElementById('corr-bcc');
    const subjectInput = document.getElementById('corr-subject');
    const readReceiptInput = document.getElementById('corr-read-receipt');
    const deliveryReceiptInput = document.getElementById('corr-delivery-receipt');
    const attachmentInput = document.getElementById('corr-attachment-input');
    const attachmentList = document.getElementById('corr-attachment-list');
    const discardBtn = document.getElementById('corr-discard-draft');
    const saveDraftBtn = document.getElementById('corr-save-draft');
    const toggleEmailBtn = document.getElementById('toggle-email-form');

    let quill = null;
    let autosaveTimer = null;
    let saveInFlight = false;
    let dirty = false;
    let switchingDraft = false;
    let activeDraftId = (draftIdInput && draftIdInput.value)
      ? parseInt(draftIdInput.value, 10) : null;
    let draftSummaries = [];
    let attachments = [];

    const quillOptions = {
      theme: 'snow',
      modules: {
        toolbar: [
          [{ header: [1, 2, 3, false] }],
          ['bold', 'italic', 'underline', 'strike'],
          [{ list: 'ordered' }, { list: 'bullet' }],
          [{ align: [] }],
          ['link'],
          ['clean'],
        ],
      },
    };

    function setActiveDraftId(id) {
      activeDraftId = id || null;
      if (draftIdInput) {
        draftIdInput.value = activeDraftId ? String(activeDraftId) : '';
      }
    }

    function updateToggleButtonLabel() {
      if (!toggleEmailBtn) return;
      const n = draftSummaries.length;
      const base = 'Send email';
      toggleEmailBtn.innerHTML =
        n > 0
          ? base + ' <span class="opacity-80">(' + n + ' draft' + (n !== 1 ? 's' : '') + ')</span>'
          : base;
    }

    function renderDraftSelect() {
      if (!draftSelect) return;
      const prev = draftSelect.value;
      draftSelect.innerHTML = '';
      if (!draftSummaries.length) {
        const opt = document.createElement('option');
        opt.value = '';
        opt.textContent = '— No saved drafts —';
        draftSelect.appendChild(opt);
        return;
      }
      draftSummaries.forEach(function (d) {
        const opt = document.createElement('option');
        opt.value = String(d.id);
        let text = d.label || 'Draft';
        if (d.attachment_count) text += ' (' + d.attachment_count + ' file' + (d.attachment_count !== 1 ? 's' : '') + ')';
        opt.textContent = text;
        draftSelect.appendChild(opt);
      });
      if (activeDraftId) {
        draftSelect.value = String(activeDraftId);
      } else if (prev) {
        draftSelect.value = prev;
      }
    }

    function syncHiddenInput() {
      if (!quill || !bodyInput) return;
      var editor = editorEl.querySelector('.ql-editor');
      const html = (editor && editor.innerHTML) || '';
      bodyInput.value = JSON.stringify({
        delta: quill.getContents(),
        html: html,
      });
    }

    function setStatus(text, isError) {
      if (!statusEl) return;
      statusEl.textContent = text || '';
      statusEl.classList.toggle('text-red-600', !!isError);
      statusEl.classList.toggle('text-gray-500', !isError);
    }

    function renderAttachments() {
      if (!attachmentList) return;
      attachmentList.innerHTML = '';
      attachments.forEach(function (att) {
        const li = document.createElement('li');
        li.className = 'flex items-center justify-between gap-2 rounded border border-gray-200 bg-gray-50 px-2 py-1';
        const span = document.createElement('span');
        span.className = 'truncate text-gray-800';
        span.textContent = att.name + (att.size ? ' (' + formatBytes(att.size) + ')' : '');
        li.appendChild(span);
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'text-red-600 hover:text-red-800 shrink-0';
        btn.textContent = 'Remove';
        btn.addEventListener('click', function () {
          removeAttachment(att.id);
        });
        li.appendChild(btn);
        attachmentList.appendChild(li);
      });
    }

    function clearForm() {
      if (fromInput) fromInput.value = panel.dataset.defaultMailbox || '';
      if (toInput) toInput.value = '';
      if (ccInput) ccInput.value = '';
      if (bccInput) bccInput.value = '';
      if (subjectInput) subjectInput.value = '';
      if (readReceiptInput) readReceiptInput.checked = false;
      if (deliveryReceiptInput) deliveryReceiptInput.checked = false;
      if (quill) quill.setContents([]);
      attachments = [];
      renderAttachments();
      syncHiddenInput();
    }

    function applyDraft(draft) {
      if (!draft) {
        clearForm();
        setActiveDraftId(null);
        return;
      }
      setActiveDraftId(draft.id);
      if (fromInput) fromInput.value = draft.from_mailbox || panel.dataset.defaultMailbox || '';
      if (toInput) toInput.value = draft.to || '';
      if (ccInput) ccInput.value = draft.cc || '';
      if (bccInput) bccInput.value = draft.bcc || '';
      if (subjectInput) subjectInput.value = draft.subject || '';
      if (readReceiptInput) readReceiptInput.checked = !!draft.request_read_receipt;
      if (deliveryReceiptInput) deliveryReceiptInput.checked = !!draft.request_delivery_receipt;
      if (quill) {
        if (draft.body_html) {
          quill.clipboard.dangerouslyPasteHTML(draft.body_html);
        } else {
          quill.setContents([]);
        }
        syncHiddenInput();
      }
      attachments = (draft.attachments && draft.attachments.slice()) || [];
      renderAttachments();
      if (draft.updated_at) {
        setStatus('Draft · last saved ' + draft.updated_at);
      }
      if (draftSelect && draft.id) {
        draftSelect.value = String(draft.id);
      }
    }

    function applyDraftListResponse(data) {
      if (data.drafts) {
        var allDrafts = normalizeDraftSummaries(data.drafts);
        draftSummaries = allDrafts.filter(function (d) {
          return !d.is_empty;
        });
        if (!draftSummaries.length && allDrafts.length) {
          draftSummaries = allDrafts;
        }
      }
      if (data.active_draft_id) {
        setActiveDraftId(data.active_draft_id);
      }
      renderDraftSelect();
      updateToggleButtonLabel();
    }

    function collectPayload() {
      syncHiddenInput();
      return {
        draft_id: activeDraftId,
        from_mailbox: (fromInput && fromInput.value) || '',
        to: (toInput && toInput.value) || '',
        cc: (ccInput && ccInput.value) || '',
        bcc: (bccInput && bccInput.value) || '',
        subject: (subjectInput && subjectInput.value) || '',
        body: (bodyInput && bodyInput.value) || '',
        request_read_receipt: !!(readReceiptInput && readReceiptInput.checked),
        request_delivery_receipt: !!(deliveryReceiptInput && deliveryReceiptInput.checked),
      };
    }

    async function saveDraft(showToast) {
      if (saveInFlight || switchingDraft) return;
      saveInFlight = true;
      try {
        const res = await fetch(`/${fileNumber}/correspondence/draft/save/`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken(),
          },
          body: JSON.stringify(collectPayload()),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Save failed');
        dirty = false;
        applyDraftListResponse(data);
        if (data.cleared) {
          applyDraft(data.draft || null);
          setStatus('Draft cleared');
        } else if (data.draft) {
          applyDraft(data.draft);
          if (data.saved_at) setStatus('Draft saved at ' + data.saved_at);
        }
        if (showToast && window.showAppToast) {
          window.showAppToast('Draft saved', 'success');
        }
      } catch (err) {
        setStatus(err.message, true);
      } finally {
        saveInFlight = false;
      }
    }

    async function loadDraftById(draftId) {
      const res = await fetch(
        `/${fileNumber}/correspondence/draft/?draft_id=${draftId}`,
        { headers: { 'X-CSRFToken': csrfToken() } },
      );
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Load failed');
      applyDraftListResponse(data);
      applyDraft(data.draft);
      dirty = false;
    }

    async function switchDraft(newId) {
      if (String(newId) === String(activeDraftId)) return;
      switchingDraft = true;
      try {
        if (dirty && activeDraftId) {
          await saveDraft(false);
        }
        if (!newId) {
          clearForm();
          setActiveDraftId(null);
          return;
        }
        await loadDraftById(newId);
      } catch (err) {
        setStatus(err.message, true);
      } finally {
        switchingDraft = false;
      }
    }

    async function createNewDraft() {
      switchingDraft = true;
      try {
        if (dirty && activeDraftId) {
          await saveDraft(false);
        }
        const res = await fetch(`/${fileNumber}/correspondence/draft/new/`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken(),
          },
          body: JSON.stringify({ from_mailbox: (fromInput && fromInput.value) || '' }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Could not create draft');
        applyDraftListResponse(data);
        clearForm();
        if (data.draft) {
          applyDraft(data.draft);
          if (fromInput && data.draft.from_mailbox) {
            fromInput.value = data.draft.from_mailbox;
          }
        }
        dirty = false;
        setStatus('New draft — start typing to autosave');
        if (window.showAppToast) window.showAppToast('New email draft', 'info');
      } catch (err) {
        setStatus(err.message, true);
      } finally {
        switchingDraft = false;
      }
    }

    async function uploadFile(file) {
      const formData = new FormData();
      formData.append('file', file);
      if (activeDraftId) formData.append('draft_id', String(activeDraftId));
      const res = await fetch(`/${fileNumber}/correspondence/draft/attachment/upload/`, {
        method: 'POST',
        headers: { 'X-CSRFToken': csrfToken() },
        body: formData,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Upload failed');
      if (data.active_draft_id) setActiveDraftId(data.active_draft_id);
      if (data.draft) {
        applyDraft(data.draft);
        applyDraftListResponse({ drafts: draftSummaries, active_draft_id: data.active_draft_id });
      }
      dirty = true;
      setStatus('Attachment added');
    }

    async function removeAttachment(id) {
      const res = await fetch(
        `/${fileNumber}/correspondence/draft/attachment/${id}/delete/`,
        { method: 'POST', headers: { 'X-CSRFToken': csrfToken() } },
      );
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Remove failed');
      if (data.draft) applyDraft(data.draft);
      scheduleAutosave();
    }

    function scheduleAutosave() {
      if (switchingDraft) return;
      dirty = true;
      if (autosaveTimer) clearTimeout(autosaveTimer);
      autosaveTimer = setTimeout(function () {
        if (dirty) saveDraft(false);
      }, 15000);
    }

    const draftsScript = document.getElementById('corr-drafts-data');
    const draftScript = document.getElementById('corr-draft-data');
    let draftApplied = false;

    if (draftsScript && draftsScript.textContent) {
      try {
        draftSummaries = normalizeDraftSummaries(JSON.parse(draftsScript.textContent));
      } catch (e) {
        draftSummaries = [];
      }
    }
    renderDraftSelect();
    updateToggleButtonLabel();

    function initQuill() {
      if (quill) return;
      quill = new Quill('#corr-body-editor', quillOptions);
      quill.on('text-change', function () {
        syncHiddenInput();
        scheduleAutosave();
      });

      if (!draftApplied && draftScript && draftScript.textContent) {
        try {
          const parsed = JSON.parse(draftScript.textContent);
          if (parsed && parsed.id) {
            applyDraft(parsed);
            draftApplied = true;
          }
        } catch (e) { /* ignore */ }
      }
    }

    function onFieldInput() {
      scheduleAutosave();
    }

    [fromInput, toInput, ccInput, bccInput, subjectInput].forEach(function (el) {
      if (el) el.addEventListener('input', onFieldInput);
    });
    [readReceiptInput, deliveryReceiptInput].forEach(function (el) {
      if (el) el.addEventListener('change', onFieldInput);
    });

    if (draftSelect) {
      draftSelect.addEventListener('change', function () {
        const val = draftSelect.value;
        switchDraft(val ? parseInt(val, 10) : null);
      });
    }

    if (newDraftBtn) {
      newDraftBtn.addEventListener('click', createNewDraft);
    }

    if (attachmentInput) {
      attachmentInput.addEventListener('change', async function () {
        const files = attachmentInput.files;
        if (!files || !files.length) return;
        for (let i = 0; i < files.length; i++) {
          try {
            await uploadFile(files[i]);
          } catch (err) {
            setStatus(err.message, true);
            if (window.showAppToast) window.showAppToast(err.message, 'error');
          }
        }
        attachmentInput.value = '';
      });
    }

    if (saveDraftBtn) {
      saveDraftBtn.addEventListener('click', function () {
        saveDraft(true);
      });
    }

    if (discardBtn) {
      discardBtn.addEventListener('click', async function () {
        if (!activeDraftId) {
          clearForm();
          setStatus('Nothing to discard');
          return;
        }
        if (!window.confirm('Discard this draft and its attachments?')) return;
        try {
          const res = await fetch(
            `/${fileNumber}/correspondence/draft/${activeDraftId}/delete/`,
            { method: 'POST', headers: { 'X-CSRFToken': csrfToken() } },
          );
          const data = await res.json();
          if (!res.ok) throw new Error(data.error || 'Discard failed');
          applyDraftListResponse(data);
          applyDraft(data.draft || null);
          if (!data.draft) {
            clearForm();
            setStatus('Draft discarded');
          } else {
            setStatus('Switched to another draft');
          }
          dirty = false;
          if (window.showAppToast) window.showAppToast('Draft discarded', 'info');
        } catch (err) {
          setStatus(err.message, true);
        }
      });
    }

    const form = document.getElementById('corr-email-form');
    if (form) {
      form.addEventListener('submit', function () {
        syncHiddenInput();
        if (draftIdInput && activeDraftId) {
          draftIdInput.value = String(activeDraftId);
        }
      });
    }

    window.initCorrespondenceCompose = function () {
      initQuill();
      if (statusEl && !statusEl.textContent.trim()) {
        setStatus('Autosave every 15 seconds · use New email for another draft');
      }
    };

    const observer = new MutationObserver(function () {
      if (!panel.classList.contains('hidden')) {
        window.initCorrespondenceCompose();
      }
    });
    observer.observe(panel, { attributes: true, attributeFilter: ['class'] });

    if (!panel.classList.contains('hidden')) {
      window.initCorrespondenceCompose();
    }
  });
})();
