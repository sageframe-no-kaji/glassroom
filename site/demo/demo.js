/* demo.js — Glassroom static demo dashboard
 * Pure vanilla JS. No frameworks. No build step.
 * Reads data.json, renders dashboard identical to the Flask app.
 */

'use strict';

// ── Constants ────────────────────────────────────────────────────────────
const DONE_STATUSES = new Set(['Turned in', 'Graded', 'Done']);

// ── State ────────────────────────────────────────────────────────────────
let allData = [];
let currentView = 'dashboard'; // 'dashboard' | 'todo'

// ── Entry point ──────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  fetch('data.json')
    .then(r => r.json())
    .then(data => {
      allData = data;
      renderStatsRow(data);
      renderView();
    })
    .catch(err => {
      document.getElementById('main-content').innerHTML =
        `<div class="empty-state">Failed to load demo data: ${err}</div>`;
    });

  document.getElementById('nav-dashboard').addEventListener('click', () => switchView('dashboard'));
  document.getElementById('nav-todo').addEventListener('click', () => switchView('todo'));
  document.getElementById('btn-export').addEventListener('click', exportCSV);
});

// ── View switching ────────────────────────────────────────────────────────
function switchView(view) {
  currentView = view;
  document.getElementById('nav-dashboard').classList.toggle('active', view === 'dashboard');
  document.getElementById('nav-todo').classList.toggle('active', view === 'todo');
  document.getElementById('page-title').textContent = view === 'todo' ? 'To Do' : 'Dashboard';
  renderView();
}

function renderView() {
  if (currentView === 'todo') {
    renderTodo();
  } else {
    renderDashboard();
  }
}

// ── Stats row ─────────────────────────────────────────────────────────────
function renderStatsRow(data) {
  const byClass = groupByClass(data);
  const container = document.getElementById('stats-row');
  container.innerHTML = '';
  for (const [className, items] of byClass) {
    const total = items.length;
    const missing = items.filter(a => a.status === 'Missing').length;
    const todo = items.filter(a => a.turn_in_required && !DONE_STATUSES.has(a.status) && a.status !== 'Unknown').length;
    const done = items.filter(a => DONE_STATUSES.has(a.status)).length;
    const pctDue = Math.round(100 * items.filter(a => a.due_date).length / total);
    const pctAttach = Math.round(100 * items.filter(a => a.attachment_links).length / total);
    const shortName = className.split(' - ')[0]; // "English Language Arts 7"

    const card = document.createElement('div');
    card.className = 'stat-card';
    card.innerHTML = `
      <div class="stat-card-name" title="${esc(className)}">${esc(shortName)}</div>
      <div class="stat-card-numbers">
        <div class="stat-item">
          <span class="stat-val">${total}</span>
          <span class="stat-lbl">total</span>
        </div>
        <div class="stat-item ${missing > 0 ? 'stat-missing' : ''}">
          <span class="stat-val">${missing}</span>
          <span class="stat-lbl">missing</span>
        </div>
        <div class="stat-item ${todo > 0 ? 'stat-todo' : ''}">
          <span class="stat-val">${todo}</span>
          <span class="stat-lbl">to do</span>
        </div>
        <div class="stat-item stat-done">
          <span class="stat-val">${done}</span>
          <span class="stat-lbl">done</span>
        </div>
        <div class="stat-item">
          <span class="stat-val">${pctDue}%</span>
          <span class="stat-lbl">due dates</span>
        </div>
        <div class="stat-item">
          <span class="stat-val">${pctAttach}%</span>
          <span class="stat-lbl">attached</span>
        </div>
      </div>`;
    container.appendChild(card);
  }
}

// ── Dashboard view ────────────────────────────────────────────────────────
function renderDashboard() {
  const byClass = groupByClass(allData);
  const container = document.getElementById('main-content');
  container.innerHTML = '';

  if (byClass.size === 0) {
    container.innerHTML = '<div class="empty-state">No assignments.</div>';
    return;
  }

  for (const [className, items] of byClass) {
    const total = items.length;
    const missing = items.filter(a => a.status === 'Missing').length;
    const todo = items.filter(a => a.turn_in_required && !DONE_STATUSES.has(a.status) && a.status !== 'Unknown').length;
    const done = items.filter(a => DONE_STATUSES.has(a.status)).length;

    const details = document.createElement('details');
    details.className = 'class-group';
    details.open = true;

    const miniStats = [
      `<span class="mini-stat">${total} total</span>`,
      missing > 0 ? `<span class="mini-stat warn">${missing} missing</span>` : '',
      todo > 0 ? `<span class="mini-stat amber">${todo} to do</span>` : '',
      `<span class="mini-stat">${done} done</span>`,
    ].filter(Boolean).join('');

    details.innerHTML = `
      <summary class="class-summary">
        <span class="chevron">▶</span>
        <h2>${esc(className)}</h2>
        <div class="class-mini-stats">${miniStats}</div>
      </summary>
      <div class="card-body">${renderAssignmentTable(items, true)}</div>`;
    container.appendChild(details);
  }
}

// ── To Do view ────────────────────────────────────────────────────────────
function renderTodo() {
  const todoItems = allData
    .filter(a => a.turn_in_required && !DONE_STATUSES.has(a.status) && a.status !== 'Unknown')
    .sort((a, b) => {
      // Sort by due date (nulls last), then class name
      if (a.due_date && b.due_date) return a.due_date.localeCompare(b.due_date);
      if (a.due_date) return -1;
      if (b.due_date) return 1;
      return a.class_name.localeCompare(b.class_name);
    });

  const container = document.getElementById('main-content');
  container.innerHTML = '';

  if (todoItems.length === 0) {
    container.innerHTML = '<div class="empty-state">No items to do.</div>';
    return;
  }

  // Group by class for To Do view
  const byClass = groupByClass(todoItems);
  for (const [className, items] of byClass) {
    const group = document.createElement('details');
    group.className = 'class-group';
    group.open = true;
    group.innerHTML = `
      <summary class="class-summary">
        <span class="chevron">▶</span>
        <h2>${esc(className)}</h2>
        <div class="class-mini-stats">
          <span class="mini-stat amber">${items.length} item${items.length !== 1 ? 's' : ''}</span>
        </div>
      </summary>
      <div class="card-body">${renderAssignmentTable(items, false)}</div>`;
    container.appendChild(group);
  }
}

// ── Assignment table renderer ─────────────────────────────────────────────
function renderAssignmentTable(items, groupByWeek) {
  if (items.length === 0) return '<div class="empty-state">No assignments.</div>';

  const rows = [];
  rows.push(`
    <table>
      <thead>
        <tr>
          <th>Title</th>
          <th>Due</th>
          <th>Status</th>
          <th>Points</th>
          <th>Grade</th>
          <th>Attach?</th>
        </tr>
      </thead>
      <tbody>`);

  let lastWeek = null;
  for (const a of items) {
    if (groupByWeek && a.week_label !== lastWeek) {
      lastWeek = a.week_label;
      const label = a.week_label || 'No topic';
      rows.push(`<tr class="week-separator"><td colspan="6">${esc(label)}</td></tr>`);
    }

    const titleCell = `<a href="#" title="Links to Google Classroom in the live app" onclick="return false">${esc(a.title || '(untitled)')}</a>`;
    const due = a.due_date || '—';
    const badge = statusBadge(a.status);
    const pts = a.points_possible != null ? a.points_possible : '—';
    const grade = a.grade || '—';
    const attach = a.attachment_links
      ? `<span class="attach-chip" title="${esc(a.attachment_titles || '')}">📎</span>`
      : '—';

    rows.push(`
      <tr>
        <td class="title-cell">${titleCell}</td>
        <td class="nowrap">${esc(due)}</td>
        <td>${badge}</td>
        <td class="muted">${esc(String(pts))}</td>
        <td class="muted">${esc(grade)}</td>
        <td>${attach}</td>
      </tr>`);
  }

  rows.push('</tbody></table>');
  return rows.join('');
}

// ── Status badge ──────────────────────────────────────────────────────────
function statusBadge(status) {
  const map = {
    'Assigned':  'badge-assigned',
    'Missing':   'badge-missing',
    'Graded':    'badge-graded',
    'Turned in': 'badge-turned-in',
    'Done':      'badge-done',
  };
  const cls = map[status] || 'badge-unknown';
  return `<span class="badge ${cls}">${esc(status || 'Unknown')}</span>`;
}

// ── Export CSV ────────────────────────────────────────────────────────────
function exportCSV() {
  const FIELDS = [
    'id','class_name','week_label','title','description','teacher',
    'posted_date','due_date','points_possible','category','assignment_type',
    'status','turn_in_required','grade','attachment_titles',
    'assignment_url','scraped_at',
  ];

  const rows = [FIELDS.join(',')];
  for (const a of allData) {
    const row = FIELDS.map(f => {
      const v = a[f] == null ? '' : String(a[f]);
      // Quote fields that contain comma, newline, or double-quote
      if (v.includes(',') || v.includes('"') || v.includes('\n')) {
        return '"' + v.replace(/"/g, '""') + '"';
      }
      return v;
    });
    rows.push(row.join(','));
  }

  const blob = new Blob([rows.join('\r\n')], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'glassroom-demo.csv';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ── Helpers ───────────────────────────────────────────────────────────────
function groupByClass(data) {
  const map = new Map();
  for (const a of data) {
    if (!map.has(a.class_name)) map.set(a.class_name, []);
    map.get(a.class_name).push(a);
  }
  return map;
}

function esc(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
