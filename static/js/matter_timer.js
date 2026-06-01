(function () {
  function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(';').shift();
  }

  function csrfToken() {
    return getCookie('csrftoken');
  }

  function apiUrl(path) {
    return path;
  }

  document.addEventListener('DOMContentLoaded', function () {
    const strip = document.getElementById('matter-time-strip');
    if (!strip) return;

    const fileNumber = strip.dataset.fileNumber;
    const display = document.getElementById('matter-time-display');
    const btnStart = document.getElementById('matter-time-start');
    const btnStop = document.getElementById('matter-time-stop');
    const btnCancel = document.getElementById('matter-time-cancel');
    const modal = document.getElementById('matter-time-modal');
    const form = document.getElementById('matter-time-log-form');
    const descInput = document.getElementById('matter-time-description');
    const activitySelect = document.getElementById('matter-time-activity');
    const chargedInput = document.getElementById('matter-time-charged');
    const modeInput = document.getElementById('matter-time-mode');
    const minutesInput = document.getElementById('matter-time-minutes');

    let tickInterval = null;
    let sessionStartedAt = null;
    let sessionOnThisFile = false;

    function setRunning(running) {
      btnStart.disabled = running;
      btnStart.classList.toggle('btn-primary', !running);
      btnStart.classList.toggle('btn-disabled', running);
      btnStop.disabled = !running;
      btnStop.classList.toggle('btn-primary', running);
      btnStop.classList.toggle('btn-disabled', !running);
      btnCancel.classList.toggle('hidden', !running);
    }

    function formatElapsed(ms) {
      const totalSec = Math.floor(ms / 1000);
      const h = Math.floor(totalSec / 3600);
      const m = Math.floor((totalSec % 3600) / 60);
      const s = totalSec % 60;
      if (h > 0) {
        return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
      }
      return `${m}:${String(s).padStart(2, '0')}`;
    }

    function updateDisplay() {
      if (!sessionStartedAt || !sessionOnThisFile) {
        display.textContent = '';
        return;
      }
      const ms = Date.now() - new Date(sessionStartedAt).getTime();
      display.textContent = formatElapsed(ms);
    }

    function stopTick() {
      if (tickInterval) {
        clearInterval(tickInterval);
        tickInterval = null;
      }
    }

    function startTick() {
      stopTick();
      updateDisplay();
      tickInterval = setInterval(updateDisplay, 1000);
    }

    function openModal(mode, defaults) {
      modeInput.value = mode;
      if (defaults) {
        if (defaults.description) descInput.value = defaults.description;
        if (defaults.activity_type) activitySelect.value = defaults.activity_type;
        if (defaults.minutes) minutesInput.value = defaults.minutes;
      }
      modal.classList.remove('hidden');
      modal.classList.add('flex');
      descInput.focus();
    }

    function closeModal() {
      modal.classList.add('hidden');
      modal.classList.remove('flex');
    }

    async function fetchSession() {
      const res = await fetch(apiUrl(`/${fileNumber}/time-events/session/`), {
        headers: { Accept: 'application/json' },
      });
      if (!res.ok) return;
      const data = await res.json();
      const active = data.active_session;
      sessionOnThisFile = !!data.session_on_this_file;
      if (active && sessionOnThisFile) {
        sessionStartedAt = active.started_at;
        activitySelect.value = active.activity_type || 'other';
        setRunning(true);
        startTick();
      } else if (active && !sessionOnThisFile) {
        display.textContent = `Timer on ${active.file_number}`;
        setRunning(false);
        stopTick();
      } else {
        sessionStartedAt = null;
        setRunning(false);
        stopTick();
      }
    }

    async function postJson(url, body) {
      const res = await fetch(apiUrl(url), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken(),
        },
        body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.error || 'Request failed');
      }
      return data;
    }

    btnStart.addEventListener('click', async function () {
      try {
        await postJson(`/${fileNumber}/time-events/start/`, {
          activity_type: activitySelect.value,
        });
        sessionStartedAt = new Date().toISOString();
        sessionOnThisFile = true;
        setRunning(true);
        startTick();
        window.showAppToast?.('Timer started', 'success');
      } catch (e) {
        window.showAppToast?.(e.message, 'error');
      }
    });

    btnStop.addEventListener('click', function () {
      openModal('stop', {});
    });

    btnCancel.addEventListener('click', async function () {
      try {
        await postJson(`/${fileNumber}/time-events/cancel/`, {});
        sessionStartedAt = null;
        sessionOnThisFile = false;
        setRunning(false);
        stopTick();
        display.textContent = '';
      } catch (e) {
        window.showAppToast?.(e.message, 'error');
      }
    });

    document.getElementById('matter-time-modal-cancel')?.addEventListener('click', closeModal);

    document.querySelectorAll('.matter-time-quick').forEach(function (btn) {
      btn.addEventListener('click', function () {
        openModal('quick', {
          description: btn.dataset.label || '',
          minutes: btn.dataset.minutes || '6',
          activity_type: btn.dataset.activity || 'other',
        });
      });
    });

    form.addEventListener('submit', async function (e) {
      e.preventDefault();
      const description = descInput.value.trim();
      if (!description) return;

      const payload = {
        description,
        activity_type: activitySelect.value,
        is_charged: chargedInput.checked,
      };

      try {
        if (modeInput.value === 'stop') {
          await postJson(`/${fileNumber}/time-events/stop/`, payload);
          sessionStartedAt = null;
          sessionOnThisFile = false;
          setRunning(false);
          stopTick();
          display.textContent = '';
        } else {
          payload.minutes = parseInt(minutesInput.value, 10) || 6;
          await postJson(`/${fileNumber}/time-events/quick-log/`, payload);
        }
        closeModal();
        window.showAppToast?.('Time recorded on matter', 'success');
        await fetchSession();
      } catch (err) {
        window.showAppToast?.(err.message, 'error');
      }
    });

    fetchSession();

    const LEAVE_PROMPT_KEY = 'matterTimeLeavePrompted';
    window.addEventListener('beforeunload', function (e) {
      if (!sessionOnThisFile || !sessionStartedAt) return;
      const elapsed = Date.now() - new Date(sessionStartedAt).getTime();
      if (elapsed < 5 * 60 * 1000) return;
      if (sessionStorage.getItem(LEAVE_PROMPT_KEY) === fileNumber) return;
      sessionStorage.setItem(LEAVE_PROMPT_KEY, fileNumber);
      e.preventDefault();
      e.returnValue = '';
    });

    document.querySelectorAll('a[href]').forEach(function (link) {
      link.addEventListener('click', function (ev) {
        if (!sessionOnThisFile || !sessionStartedAt) return;
        const href = link.getAttribute('href');
        if (!href || href.startsWith('#') || href.indexOf(fileNumber) !== -1) return;
        const elapsed = Date.now() - new Date(sessionStartedAt).getTime();
        if (elapsed < 3 * 60 * 1000) return;
        if (!window.confirm('Timer is still running on this matter. Leave without logging time?')) {
          ev.preventDefault();
        }
      });
    });
  });
})();
