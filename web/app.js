/* ErgoVision enterprise console
   hash-routed single page app: dashboard, posture lab (3D), tool runners,
   risk register, actions, workstations, methodology.                          */
import { Twin } from './twin.js';

const API = '';
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const num = v => (v === null || v === undefined || v === '' || isNaN(v)) ? 0 : Number(v);
const fmtDeg = v => (v === null || v === undefined || isNaN(v)) ? '—' : Number(v).toFixed(1) + '°';
const fmtDate = s => s ? new Date(s).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : '—';
const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

const BANDS = [
  ['negligible', 'No action needed.', '#4ade80'],
  ['low', 'Acceptable; improve if the change is cheap.', '#9be15d'],
  ['medium', 'Action needed. Plan a change and re-assess.', '#ffc53d'],
  ['high', 'Action needed soon. Prioritise this workstation.', '#ff6b6b'],
  ['very high', 'Action needed now. Redesign or stop the task.', '#c03cff'],
];
const bandObj = level => ({ level, label: BANDS[level][0], action: BANDS[level][1], colour: BANDS[level][2] });
const bandColour = level => BANDS[Math.max(0, Math.min(4, level | 0))][2];
const bandPill = (level, text) => `<span class="pill b${Math.max(0, Math.min(4, level | 0))}">${esc(text || BANDS[level | 0][0])}</span>`;
const valPill = v => `<span class="pill v-${esc(v)}">${{ verified: 'verified · tested', transcribed: 'transcribed · verify', model: 'engineering model' }[v] || esc(v)}</span>`;
const CONTROL_LABEL = { eliminate: 'Eliminate', substitute: 'Substitute', engineering: 'Engineering control', administrative: 'Administrative control', ppe: 'PPE' };
const SEV_COLOUR = { critical: '#ff6b6b', high: '#ff6b6b', medium: '#ffc53d', low: '#4ade80', info: '#8a90a3' };

const state = {
  catalogue: null, tools: {}, workstations: [], prefill: {}, charts: [], twin: null,
  lab: { angles: null, flags: null, modifiers: {}, result: null, demo: true, demoIndex: 1, timer: null },
};

/* ── infrastructure ─────────────────────────────────────────────────────── */
async function api(path, opts = {}) {
  const init = { method: opts.method || (opts.body ? 'POST' : 'GET'), headers: {} };
  if (opts.body instanceof FormData) init.body = opts.body;
  else if (opts.body !== undefined) { init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(opts.body); }
  const r = await fetch(API + path, init);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(data.error || ('HTTP ' + r.status)), { code: data.code, status: r.status });
  return data;
}
let toastTimer = null;
function toast(text) { const el = $('#toast'); el.textContent = text; el.classList.add('on'); clearTimeout(toastTimer); toastTimer = setTimeout(() => el.classList.remove('on'), 3000); }
function modal(html) { const m = $('#modal'); $('#modal-card').innerHTML = html; m.hidden = false; return m; }
function closeModal() { $('#modal').hidden = true; }
$('#modal').addEventListener('click', ev => { if (ev.target.id === 'modal') closeModal(); });

function ring(value, max, level, label, size = 120) {
  const r = 50, c = 2 * Math.PI * r, ratio = Math.max(0, Math.min(1, max ? value / max : 0));
  return `<div class="ring" style="--c:${bandColour(level)};width:${size}px;height:${size}px"><svg viewBox="0 0 120 120">
    <circle class="track" cx="60" cy="60" r="${r}"/><circle class="arc" cx="60" cy="60" r="${r}" stroke-dasharray="${c.toFixed(1)}" stroke-dashoffset="${(c * (1 - ratio)).toFixed(1)}"/></svg>
    <div class="val"><b>${esc(value)}</b><small>${esc(label)}</small></div></div>`;
}
function chart(canvas, cfg) { if (!window.Chart || !canvas) return null; const ch = new Chart(canvas.getContext('2d'), cfg); state.charts.push(ch); return ch; }
const CHART_DEFAULTS = { plugins: { legend: { labels: { color: '#8a90a3', font: { family: 'Inter', size: 11 }, boxWidth: 10 } } },
  scales: { x: { grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#8a90a3', font: { family: 'Inter', size: 10 } }, border: { display: false } },
            y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#555c70', font: { family: 'Inter', size: 10 } }, border: { display: false }, beginAtZero: true } } };

async function loadCatalogue() {
  if (state.catalogue) return state.catalogue;
  state.catalogue = await api('/api/tools');
  for (const t of state.catalogue.tools) state.tools[t.id] = t;
  return state.catalogue;
}
async function loadWorkstations() { state.workstations = await api('/api/workstations'); return state.workstations; }

async function health() {
  const led = $('#led'), text = $('#status-text');
  try {
    const d = await api('/health');
    if (d.pose && d.pose.ready) { led.className = 'led ok'; text.textContent = 'engine ' + d.engine + ' · ' + d.tools + ' tools · vision ready'; }
    else { led.className = 'led warn'; text.textContent = 'API up · pose model missing'; }
  } catch (e) { led.className = 'led err'; text.textContent = 'API offline — run python app.py'; }
}
async function refreshActionBadge() {
  try { const acts = await api('/api/actions'); const n = acts.filter(a => a.status !== 'done').length; $('#nav-actions').textContent = n ? n : ''; } catch (e) { /* offline */ }
}

/* ── background canvas ──────────────────────────────────────────────────── */
(function bg() {
  const cv = $('#bg'), ctx = cv.getContext('2d');
  let w, h, t0 = performance.now();
  const dots = Array.from({ length: 90 }, () => ({ x: Math.random(), y: Math.random(), r: 0.6 + Math.random() * 1.6, s: 0.2 + Math.random() * 0.6 }));
  function size() { w = cv.width = window.innerWidth; h = cv.height = window.innerHeight; }
  window.addEventListener('resize', size); size();
  (function frame(now) {
    const t = (now - t0) / 1000;
    ctx.clearRect(0, 0, w, h);
    const g = ctx.createRadialGradient(w * 0.7, h * 0.15, 0, w * 0.7, h * 0.15, Math.max(w, h) * 0.8);
    g.addColorStop(0, 'rgba(79,140,255,0.10)'); g.addColorStop(0.5, 'rgba(62,230,210,0.03)'); g.addColorStop(1, 'rgba(7,9,16,0)');
    ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);
    // perspective floor grid
    ctx.strokeStyle = 'rgba(79,140,255,0.07)'; ctx.lineWidth = 1;
    const horizon = h * 0.62, cx = w * 0.55;
    for (let i = -14; i <= 14; i++) { ctx.beginPath(); ctx.moveTo(cx + i * 40, horizon); ctx.lineTo(cx + i * 260, h); ctx.stroke(); }
    for (let k = 0; k < 12; k++) { const p = ((k / 12) + (t * 0.03) % (1 / 12)) % 1, y = horizon + (h - horizon) * p * p; ctx.globalAlpha = 0.25 + p * 0.6; ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke(); }
    ctx.globalAlpha = 1;
    for (const d of dots) {
      const y = ((d.y + t * 0.01 * d.s) % 1) * h, x = (d.x + Math.sin(t * 0.2 + d.y * 6) * 0.01) * w;
      ctx.fillStyle = 'rgba(111,156,255,' + (0.15 + d.s * 0.3) + ')'; ctx.beginPath(); ctx.arc(x, h - y, d.r, 0, Math.PI * 2); ctx.fill();
    }
    requestAnimationFrame(frame);
  })(t0);
})();

/* ── router ─────────────────────────────────────────────────────────────── */
const ROUTES = [
  [/^#?\/?$/, 'dashboard', () => viewDashboard()],
  [/^#\/lab$/, 'lab', () => viewLab()],
  [/^#\/tools$/, 'tools', () => viewTools()],
  [/^#\/new(\?.*)?$/, 'new', m => viewGuided(m)],
  [/^#\/tools\/([a-z_]+)$/, 'tool', m => viewTool(m[1])],
  [/^#\/register$/, 'register', () => viewRegister()],
  [/^#\/assessment\/(\d+)$/, 'register', m => viewAssessment(+m[1])],
  [/^#\/workstations$/, 'workstations', () => viewWorkstations()],
  [/^#\/actions$/, 'actions', () => viewActions()],
  [/^#\/method$/, 'method', () => viewMethod()],
];
function setCrumbs(parts) { $('#crumbs').innerHTML = parts.map((p, i) => i === parts.length - 1 ? '<b>' + esc(p) + '</b>' : esc(p)).join('<span>›</span>'); }
async function render() {
  for (const ch of state.charts) { try { ch.destroy(); } catch (e) { /* ignore */ } }
  state.charts = [];
  if (state.twin) { state.twin.dispose(); state.twin = null; }
  clearTimeout(state.lab.timer);
  $('#sidebar').classList.remove('open');
  const hash = location.hash || '#/';
  const view = $('#view');
  for (const [re, key, fn] of ROUTES) {
    const m = hash.match(re);
    if (!m) continue;
    const hasOwnEntry = key === 'tool' && !!$('#nav a[data-route="tool-' + m[1] + '"]');
    const isOn = a => a.dataset.route === key
      || (key === 'tool' && a.dataset.route === 'tool-' + m[1])
      || (key === 'tool' && a.dataset.route === 'tools' && !hasOwnEntry);
    $$('#nav a').forEach(a => a.classList.toggle('on', isOn(a)));
    view.innerHTML = '<div class="empty"><span class="spinner"></span></div>';
    try { await fn(m); } catch (e) { view.innerHTML = '<div class="card"><div class="note err"><b>Could not load this page.</b><br>' + esc(e.message) + '<br><span class="muted">Is the API running? <code>python app.py</code></span></div></div>'; console.error(e); }
    view.classList.remove('view-in'); void view.offsetWidth; view.classList.add('view-in');
    window.scrollTo({ top: 0 });
    return;
  }
  location.hash = '#/';
}
window.addEventListener('hashchange', render);
$('#burger').addEventListener('click', () => $('#sidebar').classList.toggle('open'));
$('#new-assessment').addEventListener('click', () => { location.hash = '#/new'; });

/* ── search ─────────────────────────────────────────────────────────────── */
$('#search').addEventListener('keydown', async ev => {
  if (ev.key !== 'Enter') return;
  const q = ev.target.value.trim().toLowerCase(); if (!q) return;
  await loadCatalogue(); await loadWorkstations();
  const tool = state.catalogue.tools.find(t => (t.name + ' ' + t.short + ' ' + t.id).toLowerCase().includes(q));
  if (tool) { location.hash = tool.route === 'lab' ? '#/lab' : '#/tools/' + tool.id; ev.target.value = ''; return; }
  const ws = state.workstations.find(w => (w.name + ' ' + w.department).toLowerCase().includes(q));
  if (ws) { location.hash = '#/register?ws=' + ws.id; state.registerFilter = { workstation_id: ws.id }; location.hash = '#/register'; ev.target.value = ''; return; }
  toast('Nothing matched "' + q + '"');
});

/* ══════════════════════════════════════════════════════════════════════════
   DASHBOARD
   ══════════════════════════════════════════════════════════════════════════ */
async function viewDashboard() {
  setCrumbs(['Dashboard']);
  const [d] = await Promise.all([api('/api/dashboard'), loadCatalogue()]);
  const view = $('#view');
  if (!d.counts.assessments) {
    view.innerHTML = `
      <div class="page-head"><div><div class="eyebrow">Overview</div><h1 class="page">Workplace <em>risk</em> at a glance</h1>
        <p>Nothing has been assessed yet. Load the demo plant to see how the register, heat-map and action tracker behave, or start with your own first assessment.</p></div></div>
      <div class="grid g2">
        <div class="card"><div class="card-t">Load the demo plant</div><p class="muted" style="margin:8px 0 14px;line-height:1.6">Nine workstations across packaging, warehouse, assembly, quality and offices, assessed with every tool. Every number is produced by really running the engines — nothing is hand-typed.</p><button class="btn primary" id="seed">Load demo data</button></div>
        <div class="card"><div class="card-t">Start from scratch</div><p class="muted" style="margin:8px 0 14px;line-height:1.6">Create a workstation, then run a photo through the posture lab or pick a tool from the catalogue and save the result to the register.</p><div style="display:flex;gap:8px;flex-wrap:wrap"><a class="btn" href="#/workstations">Add a workstation</a><a class="btn" href="#/lab">Posture lab</a><a class="btn" href="#/tools">Tool catalogue</a></div></div>
      </div>`;
    $('#seed').addEventListener('click', async ev => { ev.target.disabled = true; ev.target.innerHTML = '<span class="spinner"></span> loading…'; await api('/api/demo/seed', { body: {} }); toast('Demo plant loaded'); refreshActionBadge(); render(); });
    return;
  }
  const c = d.counts;
  const wsById = Object.fromEntries(d.workstations.map(w => [w.id, w]));
  const toolCols = [...new Set(d.heatmap.map(h => h.tool))].sort();
  const cell = {};
  for (const h of d.heatmap) cell[h.workstation_id + ':' + h.tool] = h;
  const rows = d.workstations.filter(w => w.assessments > 0);
  const worstNow = d.priority[0];   // scores are never averaged: the worst band governs
  view.innerHTML = `
    <div class="page-head"><div><div class="eyebrow">Overview</div><h1 class="page">Workplace <em>risk</em> at a glance</h1>
      <p>Every assessment keeps its native score and maps onto one five-step action band, so lifting, posture, repetition and office results rank together in one register.</p></div>
      <div style="display:flex;gap:8px;flex-wrap:wrap">${c.demo_records ? '<button class="btn ghost" id="clear-demo">Clear demo data</button>' : ''}<a class="btn primary" href="#/new">＋ New assessment</a></div></div>
    <div class="grid g4" style="margin-bottom:18px">
      <div class="card kpi" style="--c:#4f8cff"><div class="cap">Workstations assessed</div><div class="big">${rows.length}<span class="muted" style="font-size:14px"> / ${c.workstations}</span></div><div class="sub">${c.assessments} assessments on record</div></div>
      <div class="card kpi" style="--c:#ff6b6b"><div class="cap">High or very high</div><div class="big" style="color:${c.high_or_worse ? '#ff6b6b' : 'inherit'}">${c.high_or_worse}</div><div class="sub">assessments needing action soon</div></div>
      <div class="card kpi" style="--c:#ffc53d"><div class="cap">Open actions</div><div class="big">${c.actions_open}</div><div class="sub">${c.actions_overdue ? '<span style="color:#ff6b6b;font-weight:700">' + c.actions_overdue + ' overdue</span>' : 'none overdue'}</div></div>
      <div class="card kpi" style="--c:${bandColour(worstNow ? worstNow.worst_band : 0)}"><div class="cap">Highest risk now</div><div class="big" style="font-size:22px;color:${bandColour(worstNow ? worstNow.worst_band : 0)}">${worstNow ? BANDS[worstNow.worst_band][0] : 'none'}</div><div class="sub">${worstNow ? esc(worstNow.name) : 'nothing assessed yet'}</div></div>
    </div>
    <div class="grid g-main" style="margin-bottom:18px">
      <div class="card"><div class="card-h"><span class="card-t">Risk heat-map · latest result per workstation and tool</span><span class="band">click a cell to open the report</span></div>
        <div class="heat"><table><thead><tr><th>Workstation</th>${toolCols.map(t => '<th class="col">' + esc((state.tools[t] || {}).short || t) + '</th>').join('')}<th class="col">Worst</th></tr></thead><tbody>
        ${rows.map(w => '<tr><td class="ws">' + esc(w.name) + '<small>' + esc(w.department) + '</small></td>' + toolCols.map(t => { const h = cell[w.id + ':' + t]; return h ? `<td class="cell b${h.band_level}" data-id="${h.id}" title="${esc((state.tools[t] || {}).name || t)} · ${esc(h.score_label)} ${esc(h.score)}">${esc(h.score)}</td>` : '<td class="cell">·</td>'; }).join('') + '<td class="cell b' + w.worst_band + '">' + BANDS[w.worst_band][0] + '</td></tr>').join('')}
        </tbody></table></div></div>
      <div style="display:grid;gap:18px">
        <div class="card"><div class="card-h"><span class="card-t">Action band distribution</span></div><div style="height:180px"><canvas id="ch-band"></canvas></div></div>
        <div class="card"><div class="card-h"><span class="card-t">Priority workstations</span><a class="band" href="#/register">open register →</a></div>
          ${d.priority.map(w => `<div class="chip" style="margin-bottom:6px;cursor:pointer" data-ws="${w.id}"><span class="name">${esc(w.name)}<span class="sub"> · ${esc(w.department)}</span></span>${bandPill(w.worst_band)}</div>`).join('') || '<div class="muted">No prioritised stations yet.</div>'}</div>
      </div>
    </div>
    <div class="grid g2" style="margin-bottom:18px">
      <div class="card"><div class="card-h"><span class="card-t">Assessments by tool · mean band</span></div><div style="height:220px"><canvas id="ch-tool"></canvas></div></div>
      <div class="card"><div class="card-h"><span class="card-t">Assessment activity</span><span class="band">per day · worst band</span></div><div style="height:220px"><canvas id="ch-trend"></canvas></div></div>
    </div>
    <div class="card"><div class="card-h"><span class="card-t">Recent assessments</span><a class="band" href="#/register">all →</a></div>
      <table class="tbl"><thead><tr><th>When</th><th>Workstation</th><th>Tool</th><th>Result</th><th>Band</th></tr></thead><tbody>
      ${d.recent.map(a => `<tr class="link" data-id="${a.id}"><td class="muted">${fmtDate(a.created_at)}</td><td>${esc(a.workstation || '—')}</td><td>${esc(a.tool_name)}</td><td class="mono">${esc(a.summary)}</td><td>${bandPill(a.band_level)}</td></tr>`).join('')}
      </tbody></table></div>`;
  $$('.heat td.cell[data-id], tr.link[data-id]').forEach(el => el.addEventListener('click', () => { location.hash = '#/assessment/' + el.dataset.id; }));
  $$('[data-ws]').forEach(el => el.addEventListener('click', () => { state.registerFilter = { workstation_id: +el.dataset.ws }; location.hash = '#/register'; }));
  const cd = $('#clear-demo'); if (cd) cd.addEventListener('click', async () => { if (!confirm('Remove the demo workstations and their assessments?')) return; await api('/api/demo/clear', { body: {} }); toast('Demo data cleared'); refreshActionBadge(); render(); });
  chart($('#ch-band'), { type: 'doughnut', data: { labels: BANDS.map(b => b[0]), datasets: [{ data: d.by_band, backgroundColor: BANDS.map(b => b[2]), borderWidth: 0, hoverOffset: 6 }] },
    options: { cutout: '68%', plugins: { legend: { position: 'right', labels: { color: '#8a90a3', font: { family: 'Inter', size: 11 }, boxWidth: 10 } } }, maintainAspectRatio: false } });
  chart($('#ch-tool'), { type: 'bar', data: { labels: d.by_tool.map(t => (state.tools[t.tool] || {}).short || t.tool), datasets: [{ label: 'assessments', data: d.by_tool.map(t => t.n), backgroundColor: d.by_tool.map(t => bandColour(Math.round(t.mean_band))), borderRadius: 6, maxBarThickness: 36 }] },
    options: { ...CHART_DEFAULTS, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { callbacks: { label: it => { const t = d.by_tool[it.dataIndex]; return t.n + ' assessments · mean band ' + t.mean_band.toFixed(1) + ' · worst ' + BANDS[t.worst][0]; } } } } } });
  chart($('#ch-trend'), { type: 'line', data: { labels: d.trend.map(t => t.day.slice(5)), datasets: [
    { label: 'assessments', data: d.trend.map(t => t.n), borderColor: '#4f8cff', backgroundColor: 'rgba(79,140,255,0.15)', fill: true, tension: 0.35, pointRadius: 2, yAxisID: 'y' },
    { label: 'worst band', data: d.trend.map(t => t.worst), borderColor: '#ff6b6b', tension: 0.35, pointRadius: 2, yAxisID: 'y2' }] },
    options: { ...CHART_DEFAULTS, maintainAspectRatio: false, scales: { ...CHART_DEFAULTS.scales, y2: { position: 'right', min: 0, max: 4, ticks: { color: '#555c70', stepSize: 1 }, grid: { display: false }, border: { display: false } } } } });
}

/* ══════════════════════════════════════════════════════════════════════════
   TOOL CATALOGUE + RUNNER
   ══════════════════════════════════════════════════════════════════════════ */
async function viewTools() {
  setCrumbs(['Assess', 'Assessment tools']);
  const cat = await loadCatalogue();
  const groups = {};
  for (const t of cat.tools) (groups[t.category] = groups[t.category] || []).push(t);
  $('#view').innerHTML = `
    <div class="page-head"><div><div class="eyebrow">Assess</div><h1 class="page">Eleven methods, <em>one register</em></h1>
      <p>Pick the tool that matches the exposure. Posture tools read the angles from a photo or clip; the others take the observations a camera cannot make — load, frequency, duration, grip, layout. Every result carries its worksheet arithmetic and a ranked fix list.</p></div>
      <div style="display:flex;gap:6px;flex-wrap:wrap">${valPill('verified')}${valPill('transcribed')}${valPill('model')}</div></div>
    ${Object.entries(cat.categories).filter(([k]) => groups[k]).map(([k, label]) => `
      <div class="eyebrow" style="margin:6px 0 12px">${esc(label)}</div>
      <div class="grid g3" style="margin-bottom:24px">${groups[k].map(t => `
        <a class="card tool-card" href="${t.route === 'lab' ? '#/lab' : '#/tools/' + t.id}">
          <div class="foot"><span class="short">${esc(t.short)}</span>${valPill(t.validation)}</div>
          <h3>${esc(t.name)}</h3><p>${esc(t.description)}</p>
          <div class="foot"><span class="band">${esc(t.standard)}</span><span class="btn small">${t.route === 'lab' ? 'Open lab →' : 'Run →'}</span></div>
        </a>`).join('')}</div>`).join('')}`;
}

function fieldHTML(f, value) {
  const v = value === undefined || value === null ? (f.default ?? '') : value;
  const help = f.help ? '<span class="help">' + esc(f.help) + '</span>' : '';
  if (f.type === 'bool') return `<div class="field"><label>${esc(f.label)}${help}</label><span class="switch${v ? ' on' : ''}" data-key="${f.key}" role="checkbox" aria-checked="${!!v}"></span></div>`;
  if (f.type === 'select') return `<div class="field"><label>${esc(f.label)}${help}</label><select data-key="${f.key}">${f.options.map(([ov, ol]) => `<option value="${esc(ov)}"${String(ov) === String(v) ? ' selected' : ''}>${esc(ol)}</option>`).join('')}</select></div>`;
  return `<div class="field"><label>${esc(f.label)}${help}</label><span class="unit"><input type="number" data-key="${f.key}" value="${esc(v)}" ${f.min !== undefined ? 'min="' + f.min + '"' : ''} ${f.max !== undefined ? 'max="' + f.max + '"' : ''} step="${f.step || 1}"><em>${esc(f.unit || '')}</em></span></div>`;
}
function readForm(root, schema) {
  const out = {};
  for (const g of schema.groups) for (const f of g.fields) {
    const el = root.querySelector('[data-key="' + f.key + '"]'); if (!el) continue;
    if (f.type === 'bool') out[f.key] = el.classList.contains('on');
    else if (f.type === 'select') { const raw = el.value; const opt = f.options.find(o => String(o[0]) === raw); out[f.key] = opt ? opt[0] : raw; }
    else out[f.key] = el.value === '' ? null : parseFloat(el.value);
  }
  return out;
}
function insightsHTML(list, ref) {
  if (!list || !list.length) return '<div class="finding"><div class="f-title">No findings</div><div class="f-body">Everything scored in its acceptable band.</div></div>';
  return list.map((f, i) => `<div class="finding" id="finding-${i}" style="--c:${SEV_COLOUR[f.severity] || SEV_COLOUR.info}">
    <div class="f-head"><span class="f-title">${esc(f.title)}</span><span style="display:flex;gap:6px;align-items:center"><span class="ctrl">${esc(CONTROL_LABEL[f.control] || '')}</span><span class="pill" style="color:${SEV_COLOUR[f.severity]};border-color:${SEV_COLOUR[f.severity]}">${esc(f.severity)}</span></span></div>
    ${f.finding ? '<div class="f-body">' + esc(f.finding) + '</div>' : ''}<div class="f-why">${esc(f.why)}</div>
    <ul>${(f.actions || []).map(a => '<li>' + esc(a) + '</li>').join('')}</ul>${f.reference || ref ? '<div class="ref">' + esc(f.reference || ref) + '</div>' : ''}</div>`).join('');
}
function breakdownHTML(rows) {
  return `<table class="tbl"><thead><tr><th>Row</th><th>Observation</th><th class="num">Points / value</th></tr></thead><tbody>
    ${rows.map(r => `<tr><td>${esc(r.label)}</td><td class="band">${esc(r.value)}${r.note ? ' <span class="muted">· ' + esc(r.note) + '</span>' : ''}</td><td class="num">${esc(r.points)}</td></tr>`).join('')}</tbody></table>`;
}
function resultHTML(res, schema) {
  const max = { niosh: 3, strain_index: 13, rosa: 10, owas: 4, art: 30, rapp: 30, kim: 60, biomech: 6400, fit: 30 }[res.tool] || 10;
  return `<div class="card"><div class="score-hero">${ring(res.score === null ? 'n/a' : res.score, max, res.band.level, res.score_label || 'score')}
      <div><div class="eyebrow">${esc(schema.short)} result</div><h3>${esc(res.summary)}</h3><div style="margin-top:8px">${bandPill(res.band.level, res.band.label + ' risk')}</div><div class="lead">${esc(res.band.action)}</div></div></div></div>
    <div class="card" style="margin-top:18px"><div class="card-h"><span class="card-t">Where the score came from</span><span class="band">${esc(schema.output)}</span></div>${breakdownHTML(res.breakdown)}</div>
    <div class="card" style="margin-top:18px"><div class="card-h"><span class="card-t">What to change, in priority order</span><span class="band">${res.insights.length} finding${res.insights.length === 1 ? '' : 's'} · hierarchy of controls</span></div>${insightsHTML(res.insights, schema.standard)}</div>`;
}

async function viewTool(id) {
  await loadCatalogue();
  const schema = state.tools[id];
  if (!schema || schema.route === 'lab') { location.hash = schema ? '#/lab' : '#/tools'; return; }
  setCrumbs(['Assess', schema.name]);
  const prefill = state.prefill[id] || {}; delete state.prefill[id];
  const view = $('#view');
  view.innerHTML = `
    <div class="page-head"><div><div class="eyebrow">${esc(state.catalogue.categories[schema.category] || '')} · ${esc(schema.short)}</div><h1 class="page">${esc(schema.name)}</h1>
      <p>${esc(schema.description)} <span class="muted">${esc(schema.standard)}.</span></p></div>
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">${valPill(schema.validation)}<button class="btn" id="reset">Reset</button><button class="btn primary" id="save">Save to register</button></div></div>
    ${Object.keys(prefill).length ? '<div class="note info" style="margin-bottom:14px">Inputs pre-filled from the posture lab. Adjust anything the camera could not see, then save.</div>' : ''}
    <div class="grid g-tool">
      <div class="card" id="form">${schema.groups.map(g => `<div class="form-group"><div class="fg-title">${esc(g.title)}</div>${g.fields.map(f => fieldHTML(f, prefill[f.key])).join('')}</div>`).join('')}
        ${id === 'niosh' ? `<div class="form-group"><div class="fg-title">Multi-task job (composite lifting index)</div><div class="muted" style="line-height:1.6;margin-bottom:8px">Add each lift of the job with its own geometry and frequency; the CLI combines them the way the NIOSH manual does.</div><div id="cli-list" class="muted">No tasks added yet.</div><div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap"><button class="btn small" id="cli-add">Add current lift as a task</button><button class="btn small primary" id="cli-run" disabled>Compute CLI</button></div><div id="cli-out" style="margin-top:10px"></div></div>` : ''}
      </div>
      <div id="result"><div class="empty"><span class="spinner"></span></div></div>
    </div>`;
  let latest = null, cliTasks = [];
  const run = debounce(async () => {
    const inputs = readForm($('#form'), schema);
    try { latest = await api('/api/tools/' + id, { body: { inputs } }); latest._inputs = inputs; $('#result').innerHTML = resultHTML(latest, schema); }
    catch (e) { $('#result').innerHTML = '<div class="note err">' + esc(e.message) + '</div>'; }
  }, 220);
  $('#form').addEventListener('input', run);
  $('#form').addEventListener('change', run);
  $('#form').addEventListener('click', ev => { const sw = ev.target.closest('.switch'); if (sw) { sw.classList.toggle('on'); sw.setAttribute('aria-checked', sw.classList.contains('on')); run(); } });
  $('#reset').addEventListener('click', () => { $('#form').querySelectorAll('[data-key]').forEach(el => { const f = schema.groups.flatMap(g => g.fields).find(x => x.key === el.dataset.key); if (!f) return; if (f.type === 'bool') el.classList.remove('on'); else el.value = f.default ?? ''; }); run(); });
  $('#save').addEventListener('click', () => { if (latest) saveDialog({ tool: id, tool_name: schema.name, inputs: latest._inputs, result: latest }); });
  if (id === 'niosh') {
    const list = $('#cli-list');
    $('#cli-add').addEventListener('click', () => { const t = readForm($('#form'), schema); t.name = 'Task ' + (cliTasks.length + 1) + ' · ' + t.load_kg + ' kg @ ' + t.lifts_per_min + '/min'; cliTasks.push(t); list.innerHTML = cliTasks.map((x, i) => '<div class="chip" style="margin-bottom:6px"><span class="name">' + esc(x.name) + '</span><button class="btn small ghost" data-rm="' + i + '">✕</button></div>').join(''); $('#cli-run').disabled = false; list.querySelectorAll('[data-rm]').forEach(b => b.addEventListener('click', () => { cliTasks.splice(+b.dataset.rm, 1); $('#cli-add').click(); cliTasks.pop(); })); });
    $('#cli-run').addEventListener('click', async () => { const r = await api('/api/tools/niosh/composite', { body: { tasks: cliTasks, duration: readForm($('#form'), schema).duration } }); $('#cli-out').innerHTML = `<div class="chip"><span class="name">CLI ${esc(r.score ?? 'n/a')}</span>${bandPill(r.band.level)}</div><table class="tbl" style="margin-top:8px"><thead><tr><th>Task</th><th class="num">FILI</th><th class="num">STLI</th></tr></thead><tbody>${r.tasks.map(t => '<tr><td>' + esc(t.name) + '</td><td class="num">' + t.fili + '</td><td class="num">' + t.stli + '</td></tr>').join('')}</tbody></table>`; });
  }
  run();
}

/* save-to-register dialog, shared by tools and the lab */
async function saveDialog(records) {
  const list = Array.isArray(records) ? records : [records];
  await loadWorkstations();
  const first = list[0];
  const topActions = (first.result.insights || []).slice(0, 4).flatMap(f => (f.actions || []).slice(0, 1).map(a => ({ text: a, control: f.control || 'engineering' })));
  const m = modal(`
    <div class="eyebrow">Save to the risk register</div><h3 style="margin:6px 0 4px;font-size:18px">${list.map(r => esc(r.tool_name)).join(' + ')}</h3>
    <div class="muted" style="margin-bottom:14px">${list.map(r => esc(r.result.summary)).join(' · ')}</div>
    <div class="field"><label>Workstation</label><select id="sv-ws"><option value="">— choose —</option>${state.workstations.map(w => `<option value="${w.id}">${esc(w.name)} · ${esc(w.department)}</option>`).join('')}<option value="__new">＋ New workstation…</option></select></div>
    <div id="sv-new" hidden><div class="field"><label>Name</label><input class="inp" id="sv-name" placeholder="e.g. Case packing line 2"></div><div class="field"><label>Department</label><input class="inp" id="sv-dept" placeholder="Packaging"></div></div>
    <div class="field"><label>Assessor</label><input class="inp" id="sv-who" placeholder="Your name"></div>
    <div class="field"><label>Note</label><input class="inp" id="sv-note" placeholder="Shift, product, anything worth remembering"></div>
    <div class="form-group" style="margin-top:12px"><div class="fg-title">Raise actions</div>${topActions.map((a, i) => `<div class="field"><label style="font-size:12px">${esc(a.text)}<span class="help">${esc(CONTROL_LABEL[a.control])}</span></label><span class="switch on" data-act="${i}"></span></div>`).join('') || '<div class="muted">No actions suggested.</div>'}
      <div class="field" style="margin-top:6px"><label>Owner</label><input class="inp" id="sv-owner" placeholder="Who"></div><div class="field"><label>Due</label><input class="inp" type="date" id="sv-due"></div></div>
    <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:14px"><button class="btn" id="sv-cancel">Cancel</button><button class="btn primary" id="sv-ok">Save</button></div>`);
  $('#sv-ws').addEventListener('change', ev => { $('#sv-new').hidden = ev.target.value !== '__new'; });
  m.querySelectorAll('.switch[data-act]').forEach(sw => sw.addEventListener('click', () => sw.classList.toggle('on')));
  $('#sv-cancel').addEventListener('click', closeModal);
  $('#sv-ok').addEventListener('click', async () => {
    let wsId = $('#sv-ws').value;
    if (wsId === '__new') { const w = await api('/api/workstations', { body: { name: $('#sv-name').value || 'New workstation', department: $('#sv-dept').value } }); wsId = w.id; }
    if (!wsId) { toast('Choose a workstation first'); return; }
    const chosen = [...m.querySelectorAll('.switch[data-act].on')].map(sw => topActions[+sw.dataset.act]).map(a => ({ ...a, owner: $('#sv-owner').value, due: $('#sv-due').value }));
    let lastId = null;
    for (const [i, r] of list.entries()) {
      const saved = await api('/api/assessments', { body: { ...r, workstation_id: +wsId, assessor: $('#sv-who').value, note: $('#sv-note').value, actions: i === 0 ? chosen : [] } });
      lastId = saved.id;
    }
    closeModal(); toast('Saved to the register'); refreshActionBadge();
    location.hash = '#/assessment/' + lastId;
  });
}

/* ══════════════════════════════════════════════════════════════════════════
   POSTURE LAB (3D twin + vision API)
   ══════════════════════════════════════════════════════════════════════════ */
const MOD_SPEC = [
  { key: 'load_kg', type: 'number', label: 'Hand load (kg)', min: 0, max: 60, step: 0.5 },
  { key: 'coupling', type: 'select', label: 'Grip / coupling', options: [['good', 'Good'], ['fair', 'Fair'], ['poor', 'Poor'], ['unacceptable', 'Unacceptable']] },
  { key: 'assessed_side', type: 'select', label: 'Assess which arm', options: [['auto', 'Worst side'], ['left', 'Left'], ['right', 'Right']] },
  { key: 'static_posture', type: 'bool', label: 'Held over 1 minute' },
  { key: 'repeated_actions', type: 'bool', label: 'Repeated > 4× / minute' },
  { key: 'load_static_or_repeated', type: 'bool', label: 'Load static or repeated' },
  { key: 'shock_or_rapid_buildup', type: 'bool', label: 'Shock / rapid force' },
  { key: 'arm_supported', type: 'bool', label: 'Arm supported / leaning' },
  { key: 'shoulder_raised', type: 'bool', label: 'Shoulder raised' },
  { key: 'arm_across_midline', type: 'bool', label: 'Arm across midline' },
  { key: 'wrist_twist_end_range', type: 'bool', label: 'Wrist twisted near end range' },
  { key: 'sitting', type: 'bool', label: 'Seated task' },
  { key: 'legs_supported', type: 'bool', label: 'Legs supported and balanced' },
];
function pose(body, left, right) {
  const arm = o => ({ upper_arm_flexion: 0, upper_arm_abduction: 0, upper_arm_elevation: 0, elbow_flexion: 0, wrist_flexion: 0, wrist_deviation: 0, confidence: 1, ...o });
  return { trunk_flexion: 0, trunk_side_bend: 0, trunk_twist: 0, neck_flexion: 0, neck_flexion_gravity: 0, neck_side_bend: 0, neck_twist: 0,
    left_knee_flexion: 0, right_knee_flexion: 0, left_hip_flexion: 0, right_hip_flexion: 0, shoulder_ear_ratio: 0.45,
    confidence: { trunk: 1, neck: 1, left_arm: 1, right_arm: 1, legs: 1 }, ...body, left: arm(left), right: arm(right || left) };
}
const DEMOS = [
  { name: 'Neutral bench work', angles: pose({ neck_flexion: 6 }, { upper_arm_flexion: 12, elbow_flexion: 90 }), modifiers: { legs_supported: true } },
  { name: 'Stooped lift', angles: pose({ trunk_flexion: 55, neck_flexion: 25, neck_flexion_gravity: 80, left_hip_flexion: 62, right_hip_flexion: 62, left_knee_flexion: 35, right_knee_flexion: 35 }, { upper_arm_flexion: 40, upper_arm_elevation: 40, elbow_flexion: 80 }), modifiers: { load_kg: 12, coupling: 'poor', repeated_actions: true } },
  { name: 'Overhead reach', angles: pose({ trunk_flexion: -8, neck_flexion: -18, left_hip_flexion: -8, right_hip_flexion: -8 }, { upper_arm_flexion: 128, upper_arm_elevation: 128, elbow_flexion: 32, wrist_flexion: -18 }, { upper_arm_flexion: 20, upper_arm_elevation: 20, elbow_flexion: 70 }), modifiers: { static_posture: true } },
  { name: 'Seated screen work', angles: pose({ trunk_flexion: 9, neck_flexion: 32, neck_flexion_gravity: 41, left_hip_flexion: 98, right_hip_flexion: 98, left_knee_flexion: 88, right_knee_flexion: 88 }, { upper_arm_flexion: 22, upper_arm_elevation: 22, elbow_flexion: 96, wrist_flexion: -22 }), modifiers: { sitting: true, static_posture: true } },
  { name: 'Twisted pallet drop', angles: pose({ trunk_flexion: 30, trunk_twist: 28, trunk_side_bend: 12, neck_flexion: 14, neck_twist: 22, left_hip_flexion: 34, right_hip_flexion: 22, left_knee_flexion: 12, right_knee_flexion: 40 }, { upper_arm_flexion: 58, upper_arm_abduction: 30, upper_arm_elevation: 64, elbow_flexion: 40, wrist_deviation: 14 }, { upper_arm_flexion: 35, upper_arm_elevation: 35, elbow_flexion: 65 }), flags: { trunk_twisted: true, trunk_side_bent: true, neck_twisted: true, left_arm_abducted: true, left_wrist_deviated: true, legs_uneven: true, knee_asymmetry_deg: 28 }, modifiers: { load_kg: 8, coupling: 'fair' } },
];
const MAXIMA = { upper_arm: 6, lower_arm: 3, wrist: 4, wrist_twist: 2, neck: 6, trunk: 6, legs: 4 };
const REBA_MAX = { neck: 3, trunk: 5, legs: 4, upper_arm: 6, lower_arm: 2, wrist: 3 };
const ratio = (s, max) => max <= 1 ? 0 : max === 2 ? (s >= 2 ? 0.5 : 0) : Math.max(0, Math.min(1, (s - 1) / (max - 1)));
const compHeat = (rula, reba, k) => { const r = rula && rula.components[k], b = reba && reba.components[k]; return Math.max(r ? ratio(r.score, MAXIMA[k]) : 0, b ? ratio(b.score, REBA_MAX[k] || MAXIMA[k]) : 0); };
const cssHeat = t => t > 0.65 ? '#ff6b6b' : t > 0.3 ? '#ffc53d' : '#4ade80';
const levelColour = lvl => lvl >= 3 ? '#ff6b6b' : lvl >= 2 ? '#ffc53d' : '#4ade80';
const COMPONENT_ROWS = [['upper_arm', 'Upper arm'], ['lower_arm', 'Lower arm'], ['wrist', 'Wrist'], ['wrist_twist', 'Wrist twist'], ['neck', 'Neck'], ['trunk', 'Trunk'], ['legs', 'Legs']];
const ANGLE_ROWS = [
  ['Trunk flexion', a => a.trunk_flexion, 'vertical (+ forward)'], ['Trunk side bend', a => a.trunk_side_bend, 'frontal plane'], ['Trunk twist', a => a.trunk_twist, 'shoulders vs hips'],
  ['Neck flexion', a => a.neck_flexion, 'trunk axis (+ forward)'], ['Neck twist', a => a.neck_twist, 'head vs shoulders'],
  ['Upper arm flexion', (a, s) => a[s].upper_arm_flexion, 'trunk axis, sagittal'], ['Upper arm abduction', (a, s) => a[s].upper_arm_abduction, 'out of sagittal plane'],
  ['Elbow flexion', (a, s) => a[s].elbow_flexion, '0 = straight arm'], ['Wrist flexion', (a, s) => a[s].wrist_flexion, 'forearm (+ palmar)'], ['Wrist deviation', (a, s) => a[s].wrist_deviation, 'radial / ulnar'],
  ['Hip flexion', (a, s) => a[s + '_hip_flexion'], 'thigh vs trunk'], ['Knee flexion (L / R)', a => null, ''],
];

/* ── the six body areas the manager reads, in head-to-toe order ─────────── */
const AREAS = [
  { key: 'neck', label: 'Neck and head', comp: 'neck', ideal: 'under 10° forward',
    angle: a => a.neck_flexion, unit: '°' },
  { key: 'trunk', label: 'Back', comp: 'trunk', ideal: 'upright, under 20° forward',
    angle: a => a.trunk_flexion, unit: '°' },
  { key: 'shoulder', label: 'Shoulder and upper arm', comp: 'upper_arm', ideal: 'under 20° from the body',
    angle: (a, s) => a[s].upper_arm_flexion, unit: '°' },
  { key: 'elbow', label: 'Elbow and forearm', comp: 'lower_arm', ideal: 'bent 60–100°',
    angle: (a, s) => a[s].elbow_flexion, unit: '°' },
  { key: 'wrist', label: 'Wrist and hand', comp: 'wrist', ideal: 'straight, within 15°',
    angle: (a, s) => a[s].wrist_flexion, unit: '°' },
  { key: 'legs', label: 'Legs and feet', comp: 'legs', ideal: 'straight, weight on both feet',
    angle: a => Math.max(num(a.left_knee_flexion), num(a.right_knee_flexion)), unit: '°' },
];
const heatLevel = t => t > 0.65 ? 3 : t > 0.3 ? 2 : t > 0 ? 1 : 0;

/* Which other assessments this photo suggests. The camera fixes the posture
   half; the load and timing half comes from the task details the user set. */
function recommendTools(result, modifiers) {
  const m = modifiers || {}, flags = (result && result.flags) || {}, out = [];
  const add = (id, why) => { if (!out.some(o => o.id === id)) out.push({ id, why }); };
  const load = num(m.load_kg);
  if (load >= 3) {
    add('niosh', 'a load of ' + load + ' kg is being lifted — check it against the recommended weight limit');
    add('biomech', 'see what ' + load + ' kg does to the spine in this posture');
    if (m.repeated_actions || m.static_posture) add('kim', 'the lift is repeated through the shift');
  }
  if (m.repeated_actions) {
    add('strain_index', 'repeated hand work needs a repetition assessment, which a photo cannot give');
    add('art', 'HSE ART covers frequency, force and breaks across the shift');
  }
  if (flags.probably_sitting || m.sitting) add('rosa', 'this is seated screen work — score the chair, screen and input devices');
  if (!out.length) add('fit', 'check the bench height and reach against the worker’s size');
  return out;
}
function verdictLine(rula, reba) {
  const level = Math.max(rula.action_level, reba.risk_level);
  const worst = rula.action_level >= reba.risk_level
    ? 'RULA ' + rula.grand_score + ' of 7' : 'REBA ' + reba.reba_score + ' of 15';
  const text = ['Posture is fine as it is.', 'Acceptable. Improve it if the change is cheap.',
    'Change this workstation. Plan it.', 'Change this workstation soon.', 'Stop and redesign this task now.'][level];
  return { level, text, worst };
}

async function viewLab() {
  setCrumbs(['Assess', 'Posture lab']);
  const L = state.lab;
  $('#view').innerHTML = `
    <div class="lab-bar">
      <div><div class="eyebrow">Posture lab</div><div class="lab-title" id="lab-title">Loading…</div></div>
      <div class="lab-actions">
        <button class="btn primary" id="up-img">⇪ Upload photo</button>
        <button class="btn" id="up-vid">▶ Video clip</button>
        <button class="btn" id="lab-save">Save to register</button>
      </div>
    </div>

    <div class="stage-wrap tall" id="stage"><div class="stage-labels" id="stage-labels"></div>
      <div class="stage-top">
        <div class="demo-strip glass" id="demo-strip"></div>
        <div class="chip glass" id="chip" hidden><span class="name" id="chip-name"></span><span class="sub" id="chip-sub"></span></div>
      </div>
      <div class="frame-card glass" id="frame-card" hidden><img id="frame-img" alt="Analysed frame"><div class="cap" id="frame-cap">Source frame</div></div>
      <div class="stage-hint glass"><kbd>drag</kbd> turn · <kbd>scroll</kbd> zoom · <kbd>click</kbd> a body part to jump to its fix</div>
    </div>
    <div id="lab-status" style="margin-top:12px"></div>

    <div class="verdict" id="verdict"></div>
    <div class="grid g3" style="margin-top:14px">
      <div class="score big" id="rula-card"><div class="cap">RULA · upper limb</div><div class="big"><span id="rula-n">–</span><small> / 7</small></div><div class="act" id="rula-act"></div></div>
      <div class="score big" id="reba-card"><div class="cap">REBA · whole body</div><div class="big"><span id="reba-n">–</span><small> / 15</small></div><div class="act" id="reba-act"></div></div>
      <div class="score big" id="owas-card"><div class="cap">OWAS · action category</div><div class="big"><span id="owas-n">–</span><small> / 4</small></div><div class="act" id="owas-act"></div></div>
    </div>
    <div id="warnings" style="margin-top:10px"></div>
    <div class="card" id="timeline-card" hidden style="margin-top:14px"><div class="card-h"><span class="card-t">Score across the clip</span><span class="band" id="timeline-note"></span></div><svg class="spark" id="spark" viewBox="0 0 600 64" preserveAspectRatio="none"></svg></div>

    <details class="card fold" style="margin-top:14px"><summary><span class="card-t">Task details the camera cannot see</span><span class="band" id="mods-note"></span></summary>
      <div class="mods" id="mods"></div></details>

    <div class="card" style="margin-top:18px"><div class="card-h"><span class="card-t">What to change, head to toe</span><span class="band">worst area first · click a body part in the 3D view to jump here</span></div>
      <div id="areas"></div></div>

    <div class="card" id="next-card" hidden style="margin-top:18px"><div class="card-h"><span class="card-t">What to assess next</span><span class="band">chosen from this posture and the task details</span></div>
      <div id="next-list"></div></div>

    <details class="card fold" style="margin-top:18px"><summary><span class="card-t">Measured angles and the worksheet arithmetic</span><span class="band" id="angle-side"></span></summary>
      <div class="grid g2" style="margin-top:12px">
        <table class="tbl"><thead><tr><th>Joint</th><th class="num">Angle</th><th>Measured from</th></tr></thead><tbody id="angle-rows"></tbody></table>
        <div><table class="tbl"><thead><tr><th>Worksheet row</th><th class="num">Angle</th><th>Band</th><th class="num">RULA</th><th class="num">REBA</th></tr></thead><tbody id="component-rows"></tbody></table>
          <div class="mono muted" id="table-math" style="margin-top:10px;line-height:1.9;font-size:11.5px"></div>
          <div class="muted" id="view-kv" style="margin-top:8px;font-family:var(--mono);font-size:11px"></div></div>
      </div></details>`;

  state.twin = new Twin($('#stage'), $('#stage-labels'));
  state.twin.onPick = seg => {
    const key = { trunk: 'trunk', neck: 'neck', legs: 'legs', upper_arm_left: 'shoulder', upper_arm_right: 'shoulder',
                  lower_arm_left: 'elbow', lower_arm_right: 'elbow', hand_left: 'wrist', hand_right: 'wrist' }[seg];
    const el = $('#area-' + key);
    if (!el) return;
    $$('.area').forEach(a => a.classList.remove('flash'));
    el.classList.add('flash');
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  };
  $('#demo-strip').innerHTML = DEMOS.map((d, i) => '<button data-i="' + i + '">' + esc(d.name) + '</button>').join('');
  $$('#demo-strip button').forEach(b => b.addEventListener('click', () => { clearTimeout(L.timer); showDemo(+b.dataset.i); }));
  $('#up-img').addEventListener('click', () => pickFile('image/*'));
  $('#up-vid').addEventListener('click', () => pickFile('video/*'));
  $('#lab-save').addEventListener('click', () => { if (L.result) saveDialog(postureRecords(L.result)); });
  const stage = $('#stage');
  stage.addEventListener('dragover', ev => ev.preventDefault());
  stage.addEventListener('drop', ev => { ev.preventDefault(); const f = ev.dataTransfer.files[0]; if (f) analyse(f); });
  buildMods();
  if (L.result && !L.demo) labRender(L.result); else showDemo(L.demoIndex);
}

function pickFile(accept) { const inp = $('#file'); inp.accept = accept; inp.value = ''; inp.onchange = () => { const f = inp.files[0]; if (f) analyse(f); }; inp.click(); }
function buildMods() {
  const host = $('#mods'); host.innerHTML = '';
  for (const spec of MOD_SPEC) {
    const wrap = document.createElement('label'); wrap.className = 'mod';
    const cur = state.lab.modifiers[spec.key];
    if (spec.type === 'bool') { wrap.innerHTML = '<span>' + esc(spec.label) + '</span><span class="switch' + (cur ? ' on' : '') + '"></span>'; const sw = wrap.querySelector('.switch'); wrap.addEventListener('click', ev => { ev.preventDefault(); sw.classList.toggle('on'); state.lab.modifiers[spec.key] = sw.classList.contains('on'); rescore(); }); }
    else if (spec.type === 'number') { wrap.innerHTML = '<span>' + esc(spec.label) + '</span><input type="number" min="' + spec.min + '" max="' + spec.max + '" step="' + spec.step + '" value="' + (cur ?? 0) + '">'; wrap.querySelector('input').addEventListener('change', ev => { state.lab.modifiers[spec.key] = parseFloat(ev.target.value) || 0; rescore(); }); }
    else { wrap.innerHTML = '<span>' + esc(spec.label) + '</span><select>' + spec.options.map(([v, l]) => '<option value="' + v + '"' + ((cur ?? spec.options[0][0]) === v ? ' selected' : '') + '>' + esc(l) + '</option>').join('') + '</select>'; wrap.querySelector('select').addEventListener('change', ev => { state.lab.modifiers[spec.key] = ev.target.value; rescore(); }); }
    host.appendChild(wrap);
  }
}
async function showDemo(i) {
  const L = state.lab, demo = DEMOS[i];
  L.demo = true; L.demoIndex = i; L.angles = demo.angles; L.flags = demo.flags || {}; L.modifiers = { ...(demo.modifiers || {}) };
  buildMods();
  $$('#demo-strip button').forEach((b, j) => b.classList.toggle('on', j === i));
  $('#chip').hidden = true; $('#frame-card').hidden = true;
  await rescore(true);
  L.timer = setTimeout(() => { if (L.demo && state.twin) showDemo((i + 1) % DEMOS.length); }, 12000);
}
function labStatus(html, kind) { $('#lab-status').innerHTML = html ? '<div class="note ' + (kind || 'info') + '">' + html + '</div>' : ''; }
async function analyse(file) {
  const L = state.lab, isVideo = /^video\//.test(file.type);
  clearTimeout(L.timer); L.demo = false;
  $$('#demo-strip button').forEach(b => b.classList.remove('on'));
  $('#chip').hidden = false; $('#chip-name').textContent = file.name; $('#chip-sub').textContent = (isVideo ? 'sampling frames' : 'detecting pose');
  labStatus('<span class="spinner"></span>&nbsp; ' + (isVideo ? 'Scoring every sampled frame…' : 'Detecting the pose and scoring…'));
  const body = new FormData(); body.append(isVideo ? 'video' : 'image', file); body.append('options', JSON.stringify(L.modifiers));
  try {
    const data = await api(isVideo ? '/analyze-video' : '/analyze', { body });
    labStatus(''); L.angles = data.angles; L.flags = data.flags;
    $('#chip-sub').textContent = isVideo ? data.frames_sampled + ' frames · worst at ' + data.worst_frame_time_s + ' s' : data.image.width + '×' + data.image.height + ' · ' + data.view.view + ' view';
    labRender(data);
  } catch (e) {
    labStatus('<strong>' + esc(e.message) + '</strong>' + (e.code === 'pose_backend' ? '<div style="margin-top:6px">Run <code>python download_model.py</code> once, then retry.</div>' : ''), 'err');
    $('#chip-sub').textContent = 'failed';
  }
}
async function rescore(fromDemo) {
  const L = state.lab; if (!L.angles) return;
  try {
    const data = await api('/score', { body: { angles: L.angles, flags: L.flags, modifiers: L.modifiers } });
    if (!fromDemo && L.result) for (const k of ['annotated_image', 'view', 'warnings', 'timeline', 'peak', 'image', 'worst_frame_time_s', 'frames_sampled', 'hands']) data[k] = L.result[k];
    labRender(data);
  } catch (e) {
    if (state.twin) { state.twin.setPose(L.angles, 'left'); state.twin.setHeat({}); }
    labStatus('API offline — showing the pose without scores. Start it with <code>python app.py</code>.', 'warn');
  }
}
function labRender(data) {
  const L = state.lab; L.result = data;
  const rula = data.rula, reba = data.reba, owas = data.owas, side = rula.governing_side;

  /* 3D twin */
  if (state.twin) {
    state.twin.setPose(data.angles, side);
    const heat = { trunk: compHeat(rula, reba, 'trunk'), neck: compHeat(rula, reba, 'neck'), legs: compHeat(rula, reba, 'legs') };
    for (const s of ['left', 'right']) {
      const r = rula.detail_by_side[s], b = reba.detail_by_side[s];
      heat['upper_arm_' + s] = compHeat(r, b, 'upper_arm'); heat['lower_arm_' + s] = compHeat(r, b, 'lower_arm'); heat['hand_' + s] = compHeat(r, b, 'wrist');
    }
    state.twin.setHeat(heat, { trunk: heat.trunk, neck: heat.neck, shoulder: compHeat(rula, reba, 'upper_arm'),
      elbow: compHeat(rula, reba, 'lower_arm'), wrist: compHeat(rula, reba, 'wrist'), knee: heat.legs });
    state.twin.setRisk(reba.risk_level);
  }

  /* title + verdict */
  const title = L.demo ? DEMOS[L.demoIndex].name : ($('#chip-name') || {}).textContent || 'Uploaded posture';
  $('#lab-title').innerHTML = esc(title) + (L.demo ? ' <span class="tag" id="demo-tag">demo pose</span>' : '');
  const v = verdictLine(rula, reba);
  $('#verdict').innerHTML = '<span class="dot" style="background:' + bandColour(v.level) + '"></span>'
    + '<b>' + esc(v.text) + '</b><span class="muted"> Worst score: ' + esc(v.worst) + ' · ' + esc(side) + ' arm governs.</span>';
  $('#verdict').style.setProperty('--c', bandColour(v.level));

  /* three scores */
  const rc = $('#rula-card'), bc = $('#reba-card'), oc = $('#owas-card');
  rc.style.setProperty('--c', levelColour(rula.action_level)); bc.style.setProperty('--c', levelColour(reba.risk_level)); oc.style.setProperty('--c', bandColour(owas.band.level));
  $('#rula-n').textContent = rula.grand_score; $('#reba-n').textContent = reba.reba_score; $('#owas-n').textContent = owas.score;
  $('#rula-act').textContent = rula.action; $('#reba-act').textContent = reba.action; $('#owas-act').textContent = owas.band.action;
  $('#warnings').innerHTML = (data.warnings || []).map(w => '<div class="note warn" style="margin-top:6px">' + esc(w) + '</div>').join('');

  /* source frame + clip timeline */
  const fc = $('#frame-card');
  if (data.annotated_image) { $('#frame-img').src = data.annotated_image; $('#frame-cap').textContent = data.worst_frame_time_s !== undefined ? 'worst frame · ' + data.worst_frame_time_s + ' s' : 'analysed frame'; fc.hidden = false; } else fc.hidden = true;
  const tc = $('#timeline-card');
  if (data.timeline && data.timeline.length > 1) {
    tc.hidden = false; const T = data.timeline, W = 600, H = 64;
    const pts = (key, max) => T.map((f, i) => (i / (T.length - 1) * W).toFixed(1) + ',' + (H - 4 - (f[key] / max) * (H - 8)).toFixed(1)).join(' ');
    $('#spark').innerHTML = '<polyline points="' + pts('reba', 15) + '" fill="none" stroke="#ff6b6b" stroke-width="2"/><polyline points="' + pts('rula', 7) + '" fill="none" stroke="#4f8cff" stroke-width="2"/>';
    $('#timeline-note').textContent = T.length + ' frames · peak REBA ' + data.peak.reba + ' / RULA ' + data.peak.rula + ' · the worst frame is scored above';
  } else tc.hidden = true;

  /* what to change, head to toe: one card per body area, worst first */
  const byArea = {};
  for (const f of data.insights || []) (byArea[f.segment] = byArea[f.segment] || []).push(f);
  const cards = AREAS.map(area => {
    const t = compHeat(rula, reba, area.comp), lvl = heatLevel(t);
    const deg = area.angle(data.angles, side);
    const fixes = byArea[area.key] || [];
    return { area, lvl, deg, fixes };
  }).sort((a, b) => b.lvl - a.lvl || (b.deg || 0) - (a.deg || 0));
  const extras = ['load', 'organisation'].flatMap(k => byArea[k] || []);
  $('#areas').innerHTML = cards.map(({ area, lvl, deg, fixes }) => `
    <div class="area" id="area-${area.key}" style="--c:${bandColour(lvl)}">
      <div class="area-head">
        <div><div class="area-name">${esc(area.label)}</div>
          <div class="area-angle">${fmtDeg(deg)} <span class="muted">· target ${esc(area.ideal)}</span></div></div>
        ${bandPill(lvl, lvl === 0 ? 'fine' : BANDS[lvl][0])}
      </div>
      ${fixes.length
        ? '<ul class="area-fixes">' + fixes.flatMap(f => f.actions.slice(0, 2)).slice(0, 3).map(a => '<li>' + esc(a) + '</li>').join('') + '</ul>'
          + '<div class="area-why">' + esc(fixes[0].why) + '</div>'
        : '<div class="area-ok">In the acceptable band — nothing to change here.</div>'}
    </div>`).join('')
    + (extras.length ? `<div class="area" style="--c:${bandColour(2)}"><div class="area-head"><div><div class="area-name">The task itself</div>
        <div class="area-angle muted">load, repetition and grip — from the task details, not the photo</div></div></div>
      <ul class="area-fixes">${extras.flatMap(f => f.actions.slice(0, 2)).slice(0, 4).map(a => '<li>' + esc(a) + '</li>').join('')}</ul></div>` : '');

  /* what to assess next */
  const next = recommendTools(data, L.modifiers);
  $('#next-card').hidden = !next.length;
  $('#next-list').innerHTML = next.map(n => {
    const t = state.tools[n.id] || { name: n.id, short: n.id };
    return `<a class="next-row" href="#/new?tool=${n.id}"><span class="next-name">${esc(t.name)}</span><span class="next-why">${esc(n.why)}</span><span class="btn small">open →</span></a>`;
  }).join('');

  /* detail fold */
  $('#angle-side').textContent = 'arm values: ' + side + ' side';
  $('#mods-note').textContent = [L.modifiers.load_kg ? L.modifiers.load_kg + ' kg load' : 'no load set',
    L.modifiers.static_posture ? 'held over a minute' : null, L.modifiers.repeated_actions ? 'repeated' : null,
    L.modifiers.sitting ? 'seated' : null].filter(Boolean).join(' · ');
  $('#angle-rows').innerHTML = ANGLE_ROWS.map(([label, get, ref]) => label.startsWith('Knee')
    ? '<tr><td>' + label + '</td><td class="num">' + fmtDeg(data.angles.left_knee_flexion) + ' / ' + fmtDeg(data.angles.right_knee_flexion) + '</td><td class="band">0 = straight leg</td></tr>'
    : '<tr><td>' + label + '</td><td class="num">' + fmtDeg(get(data.angles, side)) + '</td><td class="band">' + ref + '</td></tr>').join('');
  $('#component-rows').innerHTML = COMPONENT_ROWS.map(([k, label]) => {
    const r = rula.components[k], b = reba.components[k], c = r || b; if (!c) return '';
    const adj = (c.adjustments || []).map(a => ' <span class="band">(' + (a.delta > 0 ? '+' : '') + a.delta + ' ' + esc(a.label) + ')</span>').join('');
    return '<tr><td>' + label + '</td><td class="num">' + (c.angle === null ? '—' : Number(c.angle).toFixed(0) + '°') + '</td><td class="band">' + esc(c.band) + adj + '</td><td class="num">' + (r ? r.score : '—') + '</td><td class="num">' + (b ? b.score : '—') + '</td></tr>';
  }).join('');
  $('#table-math').innerHTML = 'RULA · Table A ' + rula.group_a.table_a + ' + muscle ' + rula.group_a.muscle_use + ' + force ' + rula.group_a.force + ' = <b>A ' + rula.group_a.score + '</b> · Table B ' + rula.group_b.table_b + ' + muscle ' + rula.group_b.muscle_use + ' + force ' + rula.group_b.force + ' = <b>B ' + rula.group_b.score + '</b> → Table C = <b>' + rula.grand_score + '</b><br>REBA · Table A ' + reba.group_a.table_a + ' + force ' + reba.group_a.force + ' = <b>A ' + reba.group_a.score + '</b> · Table B ' + reba.group_b.table_b + ' + coupling ' + reba.group_b.coupling + ' = <b>B ' + reba.group_b.score + '</b> → Table C ' + reba.table_c + ' + activity ' + reba.activity + ' = <b>' + reba.reba_score + '</b><br>OWAS · back ' + owas.code[0] + ' arms ' + owas.code[1] + ' legs ' + owas.code[2] + ' load ' + owas.code[3] + ' → category <b>' + owas.score + '</b>';
  $('#view-kv').textContent = data.view
    ? 'view ' + data.view.view + ' · facing ' + data.view.facing + ' · near side ' + data.view.near_side + (data.hands ? ' · hands ' + data.hands.horizontal_m + ' m from the hips' : '')
    : (L.demo ? 'source: synthetic demo posture' : '');
}

function postureRecords(data) {
  const rula = data.rula, reba = data.reba;
  const ins = (data.insights || []).map(f => ({ factor: f.segment, severity: f.severity, title: f.title, why: f.why, actions: f.actions, control: 'engineering', finding: f.finding, reference: f.reference }));
  const comps = res => Object.values(res.components).map(c => ({ label: c.name.replace(/_/g, ' '), value: c.band, points: c.score }));
  const rulaLevel = rula.action_level === 1 ? (rula.grand_score <= 1 ? 0 : 1) : rula.action_level;
  const inputs = { angles: state.lab.angles, flags: state.lab.flags, modifiers: state.lab.modifiers };
  return [
    { tool: 'rula', tool_name: 'RULA', inputs, result: { tool: 'rula', score: rula.grand_score, score_label: 'RULA grand score', band: bandObj(rulaLevel), breakdown: comps(rula), insights: ins, summary: 'RULA ' + rula.grand_score + ' · action level ' + rula.action_level } },
    { tool: 'reba', tool_name: 'REBA', inputs, result: { tool: 'reba', score: reba.reba_score, score_label: 'REBA score', band: bandObj(reba.risk_level), breakdown: comps(reba), insights: ins, summary: 'REBA ' + reba.reba_score + ' · ' + reba.risk + ' risk' } },
  ];
}

/* ══════════════════════════════════════════════════════════════════════════
   REGISTER · REPORT · WORKSTATIONS · ACTIONS
   ══════════════════════════════════════════════════════════════════════════ */
async function viewRegister() {
  setCrumbs(['Overview', 'Risk register']);
  const [list] = await Promise.all([api('/api/assessments'), loadCatalogue(), loadWorkstations()]);
  const f = state.registerFilter || {}; state.registerFilter = null;
  const view = $('#view');
  view.innerHTML = `
    <div class="page-head"><div><div class="eyebrow">Overview</div><h1 class="page">Risk <em>register</em></h1><p>Every saved assessment, ranked by action band. Filter by tool, band or workstation; open a row for the full report and its actions.</p></div>
      <div style="display:flex;gap:8px"><button class="btn" id="csv">Export CSV</button><a class="btn primary" href="#/new">＋ New assessment</a></div></div>
    <div class="card"><div class="filters">
      <select id="f-tool"><option value="">All tools</option>${state.catalogue.tools.map(t => '<option value="' + t.id + '">' + esc(t.name) + '</option>').join('')}</select>
      <select id="f-band"><option value="">All bands</option>${BANDS.map((b, i) => '<option value="' + i + '">' + b[0] + '</option>').join('')}</select>
      <select id="f-ws"><option value="">All workstations</option>${state.workstations.map(w => '<option value="' + w.id + '"' + (f.workstation_id === w.id ? ' selected' : '') + '>' + esc(w.name) + '</option>').join('')}</select>
      <input id="f-q" placeholder="search…"><span class="muted" id="f-count"></span></div>
      <table class="tbl"><thead><tr><th>When</th><th>Workstation</th><th>Tool</th><th>Result</th><th class="num">Score</th><th>Band</th><th>Assessor</th></tr></thead><tbody id="rows"></tbody></table></div>`;
  const draw = () => {
    const tool = $('#f-tool').value, band = $('#f-band').value, ws = $('#f-ws').value, q = $('#f-q').value.toLowerCase();
    const rows = list.filter(a => (!tool || a.tool === tool) && (band === '' || String(a.band_level) === band) && (!ws || String(a.workstation_id) === ws) && (!q || (a.workstation + ' ' + a.tool_name + ' ' + a.summary + ' ' + a.assessor + ' ' + a.note).toLowerCase().includes(q)))
      .sort((a, b) => b.band_level - a.band_level || (b.created_at > a.created_at ? 1 : -1));
    $('#f-count').textContent = rows.length + ' of ' + list.length;
    $('#rows').innerHTML = rows.map(a => `<tr class="link" data-id="${a.id}"><td class="muted">${fmtDate(a.created_at)}</td><td>${esc(a.workstation || '—')}<br><span class="muted">${esc(a.department || '')}</span></td><td>${esc(a.tool_name)}</td><td class="band">${esc(a.summary)}</td><td class="num">${esc(a.score ?? '—')}</td><td>${bandPill(a.band_level)}</td><td class="muted">${esc(a.assessor || '')}</td></tr>`).join('') || '<tr><td colspan="7" class="empty">No assessments match.</td></tr>';
    $$('#rows tr.link').forEach(tr => tr.addEventListener('click', () => { location.hash = '#/assessment/' + tr.dataset.id; }));
    return rows;
  };
  ['#f-tool', '#f-band', '#f-ws', '#f-q'].forEach(s => $(s).addEventListener('input', draw));
  $('#csv').addEventListener('click', () => {
    const rows = draw(); const head = ['id', 'date', 'plant', 'department', 'workstation', 'tool', 'score', 'score_label', 'band', 'summary', 'assessor', 'note'];
    const csv = [head.join(',')].concat(rows.map(a => [a.id, a.created_at, a.plant, a.department, a.workstation, a.tool_name, a.score, a.score_label, a.band_label, a.summary, a.assessor, a.note].map(v => '"' + String(v ?? '').replace(/"/g, '""') + '"').join(','))).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' }); const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'ergovision-register.csv'; a.click();
  });
  draw();
}

async function viewAssessment(id) {
  const [a] = await Promise.all([api('/api/assessments/' + id), loadCatalogue()]);
  setCrumbs(['Risk register', a.tool_name + ' · ' + (a.workstation || 'no workstation')]);
  const r = a.result, schema = state.tools[a.tool] || { short: a.tool, output: '', standard: '' };
  $('#view').innerHTML = `
    <div class="page-head"><div><div class="eyebrow">Assessment #${a.id} · ${fmtDate(a.created_at)}</div><h1 class="page">${esc(a.workstation || 'Unassigned')} <em>· ${esc(a.tool_name)}</em></h1>
      <p>${esc(a.plant || '')}${a.department ? ' · ' + esc(a.department) : ''}${a.assessor ? ' · assessed by ' + esc(a.assessor) : ''}${a.note ? '<br>' + esc(a.note) : ''}</p></div>
      <div class="no-print" style="display:flex;gap:8px;flex-wrap:wrap">${state.tools[a.tool] && state.tools[a.tool].route === 'tool' ? '<button class="btn" id="rerun">Re-run in tool</button>' : ''}<button class="btn" id="print">Print / PDF</button><button class="btn danger" id="del">Delete</button></div></div>
    <div class="grid g-tool">
      <div>
        <div class="card"><div class="score-hero">${ring(r.score ?? 'n/a', { niosh: 3, strain_index: 13, rosa: 10, owas: 4, art: 30, rapp: 30, kim: 60, biomech: 6400, fit: 30, rula: 7, reba: 15 }[a.tool] || 10, r.band.level, r.score_label || 'score')}
          <div><h3>${esc(r.summary)}</h3><div style="margin-top:8px">${bandPill(r.band.level, r.band.label + ' risk')}</div><div class="lead">${esc(r.band.action)}</div><div class="muted" style="margin-top:8px">${esc(schema.standard)}</div></div></div></div>
        <div class="card" style="margin-top:18px"><div class="card-h"><span class="card-t">Where the score came from</span><span class="band">${esc(schema.output)}</span></div>${breakdownHTML(r.breakdown || [])}</div>
        <div class="card no-print" style="margin-top:18px"><div class="card-h"><span class="card-t">Actions</span><button class="btn small" id="add-act">＋ Add action</button></div><div id="acts">${actionRows(a.actions)}</div></div>
      </div>
      <div class="card"><div class="card-h"><span class="card-t">Findings and fixes</span><span class="band">${(r.insights || []).length} findings</span></div>${insightsHTML(r.insights || [], schema.standard)}</div>
    </div>`;
  $('#print').addEventListener('click', () => window.print());
  $('#del').addEventListener('click', async () => { if (!confirm('Delete this assessment and its actions?')) return; await api('/api/assessments/' + id, { method: 'DELETE' }); toast('Deleted'); refreshActionBadge(); location.hash = '#/register'; });
  const rr = $('#rerun'); if (rr) rr.addEventListener('click', () => { state.prefill[a.tool] = a.inputs; location.hash = '#/tools/' + a.tool; });
  const refreshActs = async () => { const fresh = await api('/api/assessments/' + id); $('#acts').innerHTML = actionRows(fresh.actions); wireActionRows(refreshActs); };
  wireActionRows(refreshActs);
  $('#add-act').addEventListener('click', () => {
    const m = modal(`<div class="eyebrow">New action</div><div class="field"><label>What</label><input class="inp" id="na-text"></div><div class="field"><label>Control</label><select id="na-ctrl" class="inp">${Object.entries(CONTROL_LABEL).map(([k, v]) => '<option value="' + k + '">' + v + '</option>').join('')}</select></div><div class="field"><label>Owner</label><input class="inp" id="na-owner"></div><div class="field"><label>Due</label><input class="inp" type="date" id="na-due"></div><div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px"><button class="btn" id="na-cancel">Cancel</button><button class="btn primary" id="na-ok">Add</button></div>`);
    $('#na-cancel').addEventListener('click', closeModal);
    $('#na-ok').addEventListener('click', async () => { if (!$('#na-text').value) return; await api('/api/actions', { body: { assessment_id: id, workstation_id: a.workstation_id, text: $('#na-text').value, control: $('#na-ctrl').value, owner: $('#na-owner').value, due: $('#na-due').value } }); closeModal(); refreshActionBadge(); render(); });
  });
}
function actionRows(actions) {
  if (!actions || !actions.length) return '<div class="muted">No actions raised.</div>';
  const today = new Date().toISOString().slice(0, 10);
  return actions.map(x => `<div class="action-row${x.status === 'done' ? ' done' : ''}" data-id="${x.id}"><span class="ctrl">${esc((CONTROL_LABEL[x.control] || x.control || '').split(' ')[0])}</span><span>${esc(x.text)}${x.workstation ? '<br><span class="muted">' + esc(x.workstation) + (x.tool ? ' · ' + esc(x.tool) : '') + '</span>' : ''}</span><span class="muted">${esc(x.owner || '—')}</span><span class="due${x.due && x.due < today && x.status !== 'done' ? ' over' : ''}">${x.due ? fmtDate(x.due) : '—'}</span><select data-status><option value="open"${x.status === 'open' ? ' selected' : ''}>Open</option><option value="in_progress"${x.status === 'in_progress' ? ' selected' : ''}>In progress</option><option value="done"${x.status === 'done' ? ' selected' : ''}>Done</option></select></div>`).join('');
}
function wireActionRows(after) {
  $$('.action-row select[data-status]').forEach(sel => sel.addEventListener('change', async () => { const row = sel.closest('.action-row'); await api('/api/actions/' + row.dataset.id, { method: 'PATCH', body: { status: sel.value } }); row.classList.toggle('done', sel.value === 'done'); toast('Action updated'); refreshActionBadge(); if (after) after(); }));
}

/* ── Action tracker: what a manager has to do, and by when ──────────────── */
const STATUS_LABEL = { open: 'To do', in_progress: 'Doing', done: 'Done' };
function dueText(due, status) {
  if (!due) return { text: 'no date', cls: '' };
  const days = Math.round((new Date(due + 'T00:00:00') - new Date(new Date().toDateString())) / 86400000);
  if (status === 'done') return { text: fmtDate(due), cls: '' };
  if (days < 0) return { text: Math.abs(days) + ' day' + (Math.abs(days) === 1 ? '' : 's') + ' late', cls: 'over' };
  if (days === 0) return { text: 'due today', cls: 'over' };
  if (days <= 7) return { text: 'in ' + days + ' day' + (days === 1 ? '' : 's'), cls: 'soon' };
  return { text: fmtDate(due), cls: '' };
}
function actionCard(a) {
  const d = dueText(a.due, a.status);
  const posture = a.tool === 'rula' || a.tool === 'reba';
  return `<div class="act-card${a.status === 'done' ? ' done' : ''}" data-id="${a.id}" style="--c:${bandColour(a.band_level || 0)}">
    <div class="act-main">
      <div class="act-text">${esc(a.text)}</div>
      <div class="act-meta">${esc(a.workstation || 'no workstation')} · ${esc(CONTROL_LABEL[a.control] || a.control || '')}
        ${a.band_level !== null && a.band_level !== undefined ? ' · ' + bandPill(a.band_level) : ''}</div>
    </div>
    <div class="act-owner">${esc(a.owner || '—')}<span class="due ${d.cls}">${esc(d.text)}</span></div>
    <div class="act-controls">
      ${posture ? '<button class="btn small ghost" data-pose="' + a.assessment_id + '">Show the posture</button>' : ''}
      <div class="seg" role="group">${['open', 'in_progress', 'done'].map(s =>
        `<button data-status="${s}"${a.status === s ? ' class="on"' : ''}>${STATUS_LABEL[s]}</button>`).join('')}</div>
    </div>
  </div>`;
}
async function viewActions() {
  setCrumbs(['Overview', 'Actions']);
  const acts = await api('/api/actions');
  const today = new Date().toISOString().slice(0, 10);
  const overdue = acts.filter(a => a.status !== 'done' && a.due && a.due < today);
  const open = acts.filter(a => a.status !== 'done' && !overdue.includes(a));
  const done = acts.filter(a => a.status === 'done');
  const byStation = {};
  for (const a of [...overdue, ...open]) (byStation[a.workstation || 'Unassigned'] = byStation[a.workstation || 'Unassigned'] || []).push(a);
  const stations = Object.entries(byStation).sort((a, b) => Math.max(...b[1].map(x => x.band_level || 0)) - Math.max(...a[1].map(x => x.band_level || 0)));

  $('#view').innerHTML = `
    <div class="page-head"><div><div class="eyebrow">Overview</div><h1 class="page">What needs <em>doing</em></h1>
      <p>Every fix raised by an assessment, grouped by workstation with the worst risk first. Tap a status to update it.</p></div></div>
    <div class="grid g3" style="margin-bottom:20px">
      <div class="card kpi" style="--c:#ff6b6b"><div class="cap">Late</div><div class="big" style="color:${overdue.length ? '#ff6b6b' : 'inherit'}">${overdue.length}</div><div class="sub">past the agreed date</div></div>
      <div class="card kpi" style="--c:#ffc53d"><div class="cap">In hand</div><div class="big">${open.length}</div><div class="sub">to do or in progress</div></div>
      <div class="card kpi" style="--c:#4ade80"><div class="cap">Done</div><div class="big">${done.length}</div><div class="sub">completed fixes</div></div>
    </div>
    ${stations.length ? stations.map(([name, list]) => `
      <div class="card" style="margin-bottom:16px"><div class="card-h"><span class="card-t">${esc(name)}</span>
        <span class="band">${list.length} action${list.length === 1 ? '' : 's'} · worst risk ${BANDS[Math.max(...list.map(x => x.band_level || 0))][0]}</span></div>
        ${list.map(actionCard).join('')}</div>`).join('')
      : '<div class="card"><div class="empty"><b>Nothing outstanding</b>Every action raised so far is done.</div></div>'}
    ${done.length ? `<details class="card fold"><summary><span class="card-t">Done · ${done.length}</span></summary><div style="margin-top:10px">${done.map(actionCard).join('')}</div></details>` : ''}`;
  wireActionCards();
}
function wireActionCards() {
  $$('.act-card .seg button').forEach(b => b.addEventListener('click', async () => {
    const card = b.closest('.act-card'), status = b.dataset.status;
    await api('/api/actions/' + card.dataset.id, { method: 'PATCH', body: { status } });
    card.querySelectorAll('.seg button').forEach(x => x.classList.toggle('on', x === b));
    card.classList.toggle('done', status === 'done');
    toast('Marked "' + STATUS_LABEL[status] + '"'); refreshActionBadge();
  }));
  $$('.act-card [data-pose]').forEach(b => b.addEventListener('click', () => showPosture(+b.dataset.pose, b.closest('.act-card').querySelector('.act-text').textContent)));
}

/* A saved posture, replayed in 3D — the quickest way to show a manager what
   the words mean. Mounted in a modal so only one twin is ever live. */
async function showPosture(assessmentId, caption) {
  modal(`<div class="eyebrow">The posture this fix came from</div>
    <div style="font-weight:700;margin:6px 0 12px">${esc(caption || '')}</div>
    <div class="stage-wrap" id="modal-stage" style="height:320px"><div class="stage-labels" id="modal-labels"></div></div>
    <div class="muted" id="modal-note" style="margin-top:10px">Loading the saved angles…</div>
    <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px"><button class="btn" id="modal-close">Close</button></div>`);
  let twin = null;
  const close = () => { if (twin) twin.dispose(); closeModal(); };
  $('#modal-close').addEventListener('click', close);
  try {
    const a = await api('/api/assessments/' + assessmentId);
    const angles = a.inputs && a.inputs.angles;
    if (!angles) { $('#modal-note').textContent = 'This assessment has no stored angles.'; return; }
    twin = new Twin($('#modal-stage'), $('#modal-labels'));
    twin.setPose(angles, 'left');
    twin.setRisk(a.band_level || 0);
    const heat = {};
    for (const b of (a.result.breakdown || [])) {
      const k = String(b.label).replace(/ /g, '_');
      const t = Math.max(0, Math.min(1, (b.points - 1) / 5));
      if (k === 'trunk' || k === 'neck' || k === 'legs') heat[k] = t;
      if (k === 'upper_arm') { heat.upper_arm_left = t; heat.upper_arm_right = t; }
      if (k === 'lower_arm') { heat.lower_arm_left = t; heat.lower_arm_right = t; }
      if (k === 'wrist') { heat.hand_left = t; heat.hand_right = t; }
    }
    twin.setHeat(heat);
    $('#modal-note').innerHTML = esc(a.tool_name) + ' · ' + esc(a.result.summary) + ' — ' + bandPill(a.band_level)
      + '<br><span class="muted">Red segments are the ones driving the score. Drag to turn the model.</span>';
  } catch (e) { $('#modal-note').textContent = 'Could not load that assessment: ' + e.message; }
}

async function viewWorkstations() {
  setCrumbs(['Manage', 'Workstations']);
  const ws = await loadWorkstations();
  $('#view').innerHTML = `
    <div class="page-head"><div><div class="eyebrow">Manage</div><h1 class="page">Work<em>stations</em></h1><p>The places assessments are saved against. Each row shows its worst current band and when it was last looked at.</p></div><button class="btn primary" id="add">＋ Add workstation</button></div>
    <div class="card"><table class="tbl"><thead><tr><th>Workstation</th><th>Plant</th><th>Task type</th><th class="num">Workers</th><th class="num">Assessments</th><th>Worst band</th><th>Last assessed</th><th></th></tr></thead><tbody>
      ${ws.map(w => `<tr><td><b>${esc(w.name)}</b><br><span class="muted">${esc(w.department)}</span></td><td class="muted">${esc(w.plant)}</td><td class="muted">${esc(w.task_type)}</td><td class="num">${w.workers}</td><td class="num">${w.assessments}</td><td>${w.worst_band === null || w.worst_band === undefined ? '<span class="muted">—</span>' : bandPill(w.worst_band)}</td><td class="muted">${fmtDate(w.last_assessed)}</td><td style="white-space:nowrap"><button class="btn small" data-open="${w.id}">register</button> <button class="btn small ghost" data-edit="${w.id}">edit</button> <button class="btn small ghost danger" data-del="${w.id}">✕</button></td></tr>`).join('') || '<tr><td colspan="8" class="empty">No workstations yet.</td></tr>'}
    </tbody></table></div>`;
  const form = (w = {}) => modal(`<div class="eyebrow">${w.id ? 'Edit' : 'New'} workstation</div>
    <div class="field"><label>Name</label><input class="inp" id="w-name" value="${esc(w.name || '')}"></div><div class="field"><label>Plant</label><input class="inp" id="w-plant" value="${esc(w.plant || '')}"></div>
    <div class="field"><label>Department</label><input class="inp" id="w-dept" value="${esc(w.department || '')}"></div><div class="field"><label>Task type</label><input class="inp" id="w-type" value="${esc(w.task_type || '')}" placeholder="lifting, repetitive, office…"></div>
    <div class="field"><label>Workers on station</label><input class="inp" type="number" id="w-workers" value="${w.workers || 1}"></div><div class="field"><label>Notes</label><textarea class="inp" id="w-notes">${esc(w.notes || '')}</textarea></div>
    <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px"><button class="btn" id="w-cancel">Cancel</button><button class="btn primary" id="w-ok">Save</button></div>`);
  const submit = async (id) => { const body = { name: $('#w-name').value, plant: $('#w-plant').value, department: $('#w-dept').value, task_type: $('#w-type').value, workers: +$('#w-workers').value || 1, notes: $('#w-notes').value }; if (!body.name) { toast('Name is required'); return; } if (id) await api('/api/workstations/' + id, { method: 'PATCH', body }); else await api('/api/workstations', { body }); closeModal(); toast('Saved'); render(); };
  $('#add').addEventListener('click', () => { form(); $('#w-cancel').addEventListener('click', closeModal); $('#w-ok').addEventListener('click', () => submit()); });
  $$('[data-edit]').forEach(b => b.addEventListener('click', () => { const w = ws.find(x => x.id === +b.dataset.edit); form(w); $('#w-cancel').addEventListener('click', closeModal); $('#w-ok').addEventListener('click', () => submit(w.id)); }));
  $$('[data-del]').forEach(b => b.addEventListener('click', async () => { if (!confirm('Delete this workstation and all its assessments?')) return; await api('/api/workstations/' + b.dataset.del, { method: 'DELETE' }); toast('Deleted'); refreshActionBadge(); render(); }));
  $$('[data-open]').forEach(b => b.addEventListener('click', () => { state.registerFilter = { workstation_id: +b.dataset.open }; location.hash = '#/register'; }));
}

/* ══════════════════════════════════════════════════════════════════════════
   METHOD: flowchart + triage + tool table
   ══════════════════════════════════════════════════════════════════════════ */
const STAGES = [
  ['0', 'Site model', 'Plant → department → workstation → task. The keys the register is organised by.'],
  ['1', 'Task triage', 'What kind of exposure is it? Routes the task to the right methods (right).'],
  ['2', 'Capture', 'Vision (photo / clip / webcam → joint angles) + observed inputs + anthropometrics.'],
  ['3', 'Assessment engines', 'Published tables and equations, each unit-tested. Native score per tool.'],
  ['4', 'Normalise', 'Every result also maps to one 0-4 action band so tools rank together.'],
  ['5', 'Insights & controls', 'Driving factor → fix, ordered by the hierarchy of controls; what-if rescoring.'],
  ['6', 'Register & dashboard', 'Heat-map, priority queue, action tracker, trend, exportable report.'],
];
const TRIAGE = {
  lifting: ['Lifting / lowering', ['niosh', 'kim', 'biomech', 'reba']],
  carrying: ['Carrying / holding', ['kim', 'biomech']],
  pushpull: ['Pushing / pulling', ['rapp']],
  repetitive: ['Repetitive upper limb', ['strain_index', 'art', 'rula']],
  posture: ['Awkward / static posture', ['rula', 'reba', 'owas']],
  office: ['Office / screen work', ['rosa', 'rula', 'fit']],
  design: ['New workstation design', ['fit', 'niosh', 'biomech']],
};
async function viewMethod() {
  setCrumbs(['Manage', 'Method & flowchart']);
  const cat = await loadCatalogue();
  const toolIds = ['rula', 'reba', 'owas', 'niosh', 'kim', 'rapp', 'strain_index', 'art', 'rosa', 'biomech', 'fit'];
  const bw = 470, bh = 66, gap = 26, x0 = 30, y0 = 30, tx = 560, tw = 180, th = 34;
  let svg = `<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#4f8cff"/></marker></defs>`;
  STAGES.forEach(([n, title, sub], i) => {
    const y = y0 + i * (bh + gap);
    svg += `<rect class="box${i === 1 ? ' hl' : ''}" x="${x0}" y="${y}" width="${bw}" height="${bh}"/><text class="k" x="${x0 + 16}" y="${y + 24}">STAGE ${n}</text><text x="${x0 + 90}" y="${y + 24}">${esc(title)}</text><text class="sub" x="${x0 + 16}" y="${y + 47}">${esc(sub)}</text>`;
    if (i < STAGES.length - 1) svg += `<path class="edge" d="M${x0 + bw / 2},${y + bh} L${x0 + bw / 2},${y + bh + gap - 2}"/>`;
  });
  const triY = y0 + (bh + gap) + bh / 2;
  toolIds.forEach((id, i) => {
    const t = state.tools[id]; const y = y0 + i * (th + 10);
    svg += `<rect class="tool" x="${tx}" y="${y}" width="${tw}" height="${th}" data-tool="${id}"/><text class="tool-t" x="${tx + 12}" y="${y + 21}">${esc(t.short)} · ${esc(t.name.split(' - ')[0].split(' (')[0]).slice(0, 22)}</text>`;
    svg += `<path class="edge" style="opacity:.45" d="M${x0 + bw},${triY} C${x0 + bw + 40},${triY} ${tx - 40},${y + th / 2} ${tx - 2},${y + th / 2}"/>`;
  });
  const H = Math.max(y0 + STAGES.length * (bh + gap), y0 + toolIds.length * (th + 10)) + 10;
  $('#view').innerHTML = `
    <div class="page-head"><div><div class="eyebrow">Method</div><h1 class="page">How a task becomes a <em>ranked fix list</em></h1><p>The same seven stages for every exposure. Stage 1 decides which engines run; stage 4 is what lets a lifting index, a REBA score and a ROSA score sit in the same register.</p></div></div>
    <div class="grid g-main">
      <div class="card"><svg class="flow" viewBox="0 0 770 ${H}">${svg}</svg></div>
      <div style="display:grid;gap:18px">
        <div class="card"><div class="card-h"><span class="card-t">Triage: what does the worker mainly do?</span></div><div class="triage" id="triage">${Object.entries(TRIAGE).map(([k, [label]]) => '<button data-k="' + k + '">' + esc(label) + '</button>').join('')}</div><div id="triage-out" style="margin-top:14px"></div></div>
        <div class="card"><div class="card-h"><span class="card-t">Tool status</span></div><table class="tbl"><thead><tr><th>Tool</th><th>Source</th><th>Status</th></tr></thead><tbody>${cat.tools.map(t => '<tr><td><b>' + esc(t.short) + '</b> <span class="muted">' + esc(t.name) + '</span></td><td class="band">' + esc(t.standard) + '</td><td>' + valPill(t.validation) + '</td></tr>').join('')}</tbody></table>
          <div class="muted" style="margin-top:12px;line-height:1.6"><b style="color:#3ee6d2">verified</b> = tables and equations checked by unit tests against the published source · <b style="color:#ffc53d">transcribed</b> = taken from the published sheet, confirm before regulatory use · <b style="color:#4f8cff">model</b> = engineering estimate or design rule, not a scored worksheet.</div></div>
      </div></div>`;
  $$('.flow .tool').forEach(r => r.addEventListener('click', () => { const t = state.tools[r.dataset.tool]; location.hash = t.route === 'lab' ? '#/lab' : '#/tools/' + t.id; }));
  $$('#triage button').forEach(b => b.addEventListener('click', () => {
    $$('#triage button').forEach(x => x.classList.toggle('on', x === b));
    const [label, ids] = TRIAGE[b.dataset.k];
    $('#triage-out').innerHTML = '<div class="eyebrow" style="margin-bottom:8px">' + esc(label) + ' · run these</div>' + ids.map((id, i) => { const t = state.tools[id]; return `<a class="chip" style="margin-bottom:6px" href="${t.route === 'lab' ? '#/lab' : '#/tools/' + id}"><span class="name">${i + 1}. ${esc(t.name)}<span class="sub"> · ${esc(t.output)}</span></span><span class="btn small">open →</span></a>`; }).join('');
  }));
}

/* ══════════════════════════════════════════════════════════════════════════
   GUIDED ASSESSMENT — one page: where, what the work is, the forms that
   apply, one save. The individual tool pages stay for single-tool use.
   ══════════════════════════════════════════════════════════════════════════ */
async function viewGuided(match) {
  setCrumbs(['Assess', 'New assessment']);
  await Promise.all([loadCatalogue(), loadWorkstations()]);
  const query = new URLSearchParams((location.hash.split('?')[1] || ''));
  const preTool = query.get('tool');
  const chosen = new Set(preTool ? [preTool] : []);
  const results = {};

  $('#view').innerHTML = `
    <div class="page-head"><div><div class="eyebrow">Assess</div><h1 class="page">New <em>assessment</em></h1>
      <p>Say where the work happens and what the worker actually does. The methods that apply appear below, on one page — the posture half is measured from a photo, the rest is what only a person on the floor can tell you.</p></div></div>

    <div class="card step"><div class="step-n">1</div><div class="step-body">
      <div class="card-t">Where is the work?</div>
      <div class="step-row">
        <select id="g-ws" class="inp"><option value="">— choose a workstation —</option>
          ${state.workstations.map(w => `<option value="${w.id}">${esc(w.name)} · ${esc(w.department)}</option>`).join('')}
          <option value="__new">＋ New workstation…</option></select>
        <input class="inp" id="g-who" placeholder="Assessed by">
      </div>
      <div id="g-new" hidden class="step-row" style="margin-top:8px">
        <input class="inp" id="g-name" placeholder="Workstation name"><input class="inp" id="g-dept" placeholder="Department">
      </div></div></div>

    <div class="card step"><div class="step-n">2</div><div class="step-body">
      <div class="card-t">What does the worker do? <span class="band">pick everything that happens on this job</span></div>
      <div class="triage" id="g-triage" style="margin-top:10px">
        ${Object.entries(TRIAGE).map(([k, [label]]) => `<button data-k="${k}">${esc(label)}</button>`).join('')}</div>
      <div class="muted" id="g-why" style="margin-top:10px">Each choice adds the methods that cover it. Nothing is averaged — every method keeps its own score and the worst one governs.</div>
    </div></div>

    <div class="card step"><div class="step-n">3</div><div class="step-body">
      <div class="card-t">Fill in what the camera cannot see</div>
      <div id="g-tools" style="margin-top:10px"><div class="muted">Choose what the worker does above and the forms appear here.</div></div>
    </div></div>

    <div class="save-bar glass" id="g-save-bar" hidden>
      <div><b id="g-save-count">0 assessments ready</b><div class="muted" id="g-save-note"></div></div>
      <div class="step-row" style="flex:none">
        <input class="inp" id="g-owner" placeholder="Action owner" style="width:140px">
        <input class="inp" type="date" id="g-due" style="width:150px">
        <button class="btn primary" id="g-save">Save to the register</button>
      </div>
    </div>`;

  $('#g-ws').addEventListener('change', ev => { $('#g-new').hidden = ev.target.value !== '__new'; });
  $$('#g-triage button').forEach(b => b.addEventListener('click', () => {
    b.classList.toggle('on');
    const ids = new Set();
    $$('#g-triage button.on').forEach(x => TRIAGE[x.dataset.k][1].forEach(id => ids.add(id)));
    chosen.clear(); ids.forEach(id => chosen.add(id));
    renderTools();
  }));
  if (preTool) {
    for (const [k, [, ids]] of Object.entries(TRIAGE)) if (ids.includes(preTool)) { const b = $('#g-triage button[data-k="' + k + '"]'); if (b) b.classList.add('on'); break; }
    $$('#g-triage button.on').forEach(x => TRIAGE[x.dataset.k][1].forEach(id => chosen.add(id)));
  }

  function renderTools() {
    const host = $('#g-tools');
    const ids = [...chosen];
    if (!ids.length) { host.innerHTML = '<div class="muted">Choose what the worker does above and the forms appear here.</div>'; updateBar(); return; }
    host.innerHTML = ids.map(id => {
      const t = state.tools[id];
      if (!t) return '';
      if (t.route === 'lab') {
        const have = state.lab.result;
        return `<div class="tool-step"><div class="tool-step-h"><div><b>${esc(t.name)}</b><div class="muted">${esc(t.description)}</div></div>
          ${have ? '<span class="pill b' + Math.max(state.lab.result.rula.action_level, state.lab.result.reba.risk_level) + '">measured</span>' : '<a class="btn small" href="#/lab">Measure in the posture lab →</a>'}</div>
          ${have ? '<div class="muted" style="margin-top:8px">Using the posture measured in the lab: RULA ' + have.rula.grand_score + ', REBA ' + have.reba.reba_score + '. It will be saved with the rest.</div>' : ''}</div>`;
      }
      const pre = (state.prefill[id] || {});
      return `<details class="tool-step" data-tool="${id}" open><summary class="tool-step-h"><div><b>${esc(t.name)}</b>
          <div class="muted">${esc(t.output)}</div></div><span class="pill b0" data-chip="${id}">—</span></summary>
        <div class="form" data-form="${id}">${t.groups.map(g => `<div class="form-group"><div class="fg-title">${esc(g.title)}</div>${g.fields.map(f => fieldHTML(f, pre[f.key])).join('')}</div>`).join('')}</div>
        <div class="tool-step-result" data-result="${id}"></div></details>`;
    }).join('');
    host.querySelectorAll('[data-form]').forEach(form => {
      const id = form.dataset.form;
      const run = debounce(async () => {
        const inputs = readForm(form, state.tools[id]);
        try {
          const res = await api('/api/tools/' + id, { body: { inputs } });
          results[id] = { tool: id, tool_name: state.tools[id].name, inputs, result: res };
          const chip = host.querySelector('[data-chip="' + id + '"]');
          chip.className = 'pill b' + res.band.level; chip.textContent = res.score + ' · ' + res.band.label;
          host.querySelector('[data-result="' + id + '"]').innerHTML =
            `<div class="mini-result"><div><b>${esc(res.summary)}</b><div class="muted">${esc(res.band.action)}</div></div></div>`
            + (res.insights[0] && res.insights[0].severity !== 'info' ? `<div class="mini-fix"><span class="ctrl">${esc(CONTROL_LABEL[res.insights[0].control] || '')}</span>${esc(res.insights[0].actions[0])}</div>` : '');
          updateBar();
        } catch (e) { host.querySelector('[data-result="' + id + '"]').innerHTML = '<div class="note err">' + esc(e.message) + '</div>'; }
      }, 200);
      form.addEventListener('input', run); form.addEventListener('change', run);
      form.addEventListener('click', ev => { const sw = ev.target.closest('.switch'); if (sw) { sw.classList.toggle('on'); run(); } });
      run();
    });
    updateBar();
  }
  function updateBar() {
    const n = Object.keys(results).length + (chosen.has('rula') && state.lab.result ? 2 : 0);
    $('#g-save-bar').hidden = n === 0;
    $('#g-save-count').textContent = n + ' assessment' + (n === 1 ? '' : 's') + ' ready';
    const worst = Object.values(results).reduce((m, r) => Math.max(m, r.result.band.level), 0);
    $('#g-save-note').textContent = n ? 'Worst result so far: ' + BANDS[worst][0] + ' — ' + BANDS[worst][1] : '';
  }
  $('#g-save').addEventListener('click', async () => {
    let wsId = $('#g-ws').value;
    if (wsId === '__new') {
      const w = await api('/api/workstations', { body: { name: $('#g-name').value || 'New workstation', department: $('#g-dept').value } });
      wsId = w.id;
    }
    if (!wsId) { toast('Choose a workstation first'); $('#g-ws').focus(); return; }
    const records = Object.values(results);
    if (chosen.has('rula') && state.lab.result) records.push(...postureRecords(state.lab.result));
    if (!records.length) { toast('Nothing to save yet'); return; }
    const owner = $('#g-owner').value, due = $('#g-due').value, who = $('#g-who').value;
    let last = null;
    for (const r of records) {
      const top = (r.result.insights || []).find(f => f.severity !== 'info');
      const actions = top && r.result.band.level >= 2 ? [{ text: top.actions[0], control: top.control || 'engineering', owner, due }] : [];
      last = await api('/api/assessments', { body: { ...r, workstation_id: +wsId, assessor: who, actions } });
    }
    toast(records.length + ' assessments saved'); refreshActionBadge();
    location.hash = '#/assessment/' + last.id;
  });
  renderTools();
}

/* ── boot ───────────────────────────────────────────────────────────────── */
health(); setInterval(health, 20000); refreshActionBadge();
render();
window.ergovision = { state, api, render };
