/* Staff timeline panel: swaps the panel in place (no full reload), keeps the
 * page URL in sync so a reload/bookmark restores the view, and drives the
 * per-entry detail sheet. Works with plain links when JS is unavailable. */
(function () {
  'use strict';

  var TL_KEYS = ['tl_view', 'tl_date', 'tl_types', 'tl_user'];

  function initRoot(root) {
    if (root.__tlInit) return;
    root.__tlInit = true;

    var panelUrl = root.getAttribute('data-tl-panel-url');
    var hostUrl = root.getAttribute('data-tl-host') || window.location.pathname;
    var loading = false;

    function pickable() {
      return !!root.querySelector('[data-tl-user-select]');
    }

    function sheet() {
      return root.querySelector('[data-tl-sheet]');
    }

    function panel() {
      return root.querySelector('[data-tl-panel]');
    }

    function currentParams() {
      var p = panel();
      var query = p ? p.getAttribute('data-tl-query') || '' : '';
      return new URLSearchParams(query);
    }

    function stripTl(params) {
      TL_KEYS.forEach(function (key) { params.delete(key); });
      return params;
    }

    function syncUrl(query) {
      try {
        var next = new URL(window.location.href);
        stripTl(next.searchParams);
        var incoming = new URLSearchParams(query);
        incoming.forEach(function (value, key) { next.searchParams.append(key, value); });
        window.history.replaceState({}, '', next.toString());
      } catch (e) { /* ignore */ }
    }

    function load(query) {
      var p = panel();
      if (!p || !panelUrl) {
        window.location.href = hostUrl + '?' + query;
        return;
      }
      var params = new URLSearchParams(query);
      var user = root.getAttribute('data-tl-user');
      if (user && !params.has('tl_user')) params.set('tl_user', user);
      params.set('tl_host', hostUrl);
      loading = true;
      p.style.opacity = '0.4';
      p.style.pointerEvents = 'none';
      closeSheet();
      fetch(panelUrl + '?' + params.toString(), {
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
        credentials: 'same-origin'
      })
        .then(function (r) {
          if (!r.ok) throw new Error('HTTP ' + r.status);
          return r.text();
        })
        .then(function (html) {
          var wrapper = document.createElement('div');
          wrapper.innerHTML = html;
          var fresh = wrapper.querySelector('[data-tl-panel]');
          if (!fresh) throw new Error('bad panel');
          p.replaceWith(fresh);
          params.delete('tl_host');
          if (!pickable()) params.delete('tl_user');
          syncUrl(params.toString());
        })
        .catch(function () {
          window.location.href = hostUrl + '?' + params.toString();
        })
        .finally(function () {
          loading = false;
          var live = panel();
          if (live) {
            live.style.opacity = '';
            live.style.pointerEvents = '';
          }
        });
    }

    function withParam(key, value) {
      var params = currentParams();
      params.set(key, value);
      return params.toString();
    }

    function openSheet(templateId) {
      var el = sheet();
      if (!el) return;
      var tpl = root.querySelector('template[id="' + templateId + '"]');
      var body = el.querySelector('[data-tl-sheet-body]');
      if (!tpl || !body) return;
      body.innerHTML = '';
      body.appendChild(tpl.content.cloneNode(true));
      el.hidden = false;
      var closeBtn = el.querySelector('[data-tl-sheet-close]');
      if (closeBtn) closeBtn.focus();
    }

    function closeSheet() {
      var el = sheet();
      if (el && !el.hidden) el.hidden = true;
    }

    root.addEventListener('click', function (event) {
      var nav = event.target.closest('[data-tl-nav]');
      if (nav && root.contains(nav)) {
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
        event.preventDefault();
        if (loading) return;
        var href = nav.getAttribute('href') || '';
        var idx = href.indexOf('?');
        load(idx === -1 ? '' : href.slice(idx + 1));
        return;
      }
      var detail = event.target.closest('[data-tl-detail]');
      if (detail && root.contains(detail)) {
        event.preventDefault();
        openSheet(detail.getAttribute('data-tl-detail'));
        return;
      }
      if (event.target.closest('[data-tl-sheet-close]')) {
        event.preventDefault();
        closeSheet();
      }
    });

    root.addEventListener('change', function (event) {
      var target = event.target;
      if (target.matches('[data-tl-date]')) {
        if (target.value) load(withParam('tl_date', target.value));
      } else if (target.matches('[data-tl-user-select]')) {
        root.setAttribute('data-tl-user', target.value);
        load(withParam('tl_user', target.value));
      }
    });

    document.addEventListener('keydown', function (event) {
      if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return;
      var tag = (event.target.tagName || '').toLowerCase();
      if (tag === 'input' || tag === 'textarea' || tag === 'select' || event.target.isContentEditable) return;
      if (event.key === 'Escape') { closeSheet(); return; }
      var p = panel();
      if (!p) return;
      var link = null;
      if (event.key === 'ArrowLeft') link = p.querySelector('[data-tl-prev]');
      else if (event.key === 'ArrowRight') link = p.querySelector('[data-tl-next]');
      else if (event.key === 't' || event.key === 'T') link = p.querySelector('[data-tl-today]');
      if (link) {
        event.preventDefault();
        link.click();
      }
    });

    document.addEventListener('click', function (event) {
      var el = sheet();
      if (!el || el.hidden) return;
      if (el.contains(event.target) || event.target.closest('[data-tl-detail]')) return;
      closeSheet();
    });

    window.addEventListener('popstate', function () {
      var params = new URLSearchParams(window.location.search);
      var query = new URLSearchParams();
      TL_KEYS.forEach(function (key) {
        params.getAll(key).forEach(function (value) { query.append(key, value); });
      });
      if ([...query.keys()].length) load(query.toString());
    });
  }

  function init() {
    document.querySelectorAll('[data-tl-root]').forEach(initRoot);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
