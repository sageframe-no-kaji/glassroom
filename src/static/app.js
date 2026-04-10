// ============================================================
//  Glassroom — app.js
//  Vanilla JS only. No framework. Defer-loaded.
// ============================================================

// ---- Nav scrape (called via onclick in base.html template) ----

function navScrape() {
  var btn = document.getElementById('btn-scrape-nav');
  var status = document.getElementById('scrape-status');
  btn.disabled = true;
  status.innerHTML = '<span class="nav-spinner"></span> Starting\u2026';

  fetch('/api/scrape', { method: 'POST' })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      if (data.error) {
        status.textContent = '\u26a0 ' + data.error;
        btn.disabled = false;
        return;
      }
      pollNavScrape();
    })
    .catch(function (err) {
      status.textContent = '\u26a0 ' + err;
      btn.disabled = false;
    });
}

function pollNavScrape() {
  var btn = document.getElementById('btn-scrape-nav');
  var status = document.getElementById('scrape-status');
  setTimeout(function () {
    fetch('/api/scrape/status')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var p = data.progress || {};
        if (p.status === 'done') {
          status.textContent = 'Done \u2014 ' + (p.inserted || 0) + ' new';
          btn.disabled = false;
          setTimeout(function () { status.textContent = ''; }, 5000);
        } else if (p.status === 'error') {
          status.textContent = '\u26a0 Scrape failed';
          btn.disabled = false;
        } else if (data.running) {
          status.innerHTML = '<span class="nav-spinner"></span> ' + (p.status || 'Scraping\u2026');
          pollNavScrape();
        } else {
          btn.disabled = false;
        }
      })
      .catch(function () { pollNavScrape(); });
  }, 2500);
}

// ---- Class detail — patch assignment field (notes / priority) ----

function patchAssignment(id, data) {
  fetch('/api/assignment/' + id, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

// ---- DOM-ready handlers ----

document.addEventListener('DOMContentLoaded', function () {

  // Show last-scraped timestamp in nav when server is idle
  (function fetchLastScraped() {
    var statusEl = document.getElementById('scrape-status');
    if (!statusEl) return;
    fetch('/api/scrape/status')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data.running) {
          var p = data.progress || {};
          if (p.completed_at) {
            var d = new Date(p.completed_at);
            var diffMin = Math.round((Date.now() - d.getTime()) / 60000);
            var label =
              diffMin < 1 ? 'just now' :
              diffMin < 60 ? diffMin + ' min ago' :
              Math.round(diffMin / 60) + ' hr ago';
            statusEl.textContent = 'Last scraped ' + label;
          }
        }
      })
      .catch(function () { /* ignore — cosmetic only */ });
  })();

  // Notes textarea — debounced autosave (600 ms)
  document.querySelectorAll('.notes-field').forEach(function (el) {
    var timer;
    el.addEventListener('input', function () {
      clearTimeout(timer);
      timer = setTimeout(function () {
        patchAssignment(el.dataset.id, { notes: el.value });
      }, 600);
    });
  });

  // Priority select — immediate save
  document.querySelectorAll('.priority-field').forEach(function (el) {
    el.addEventListener('change', function () {
      var val = el.value === '' ? null : parseInt(el.value, 10);
      patchAssignment(el.dataset.id, { class_priority: val });
    });
  });

});
