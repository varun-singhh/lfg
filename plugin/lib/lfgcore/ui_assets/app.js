/* The full-screen pages (product home, intro) never flash the dashboard shell while the first data loads. */
(h => { if (!h || h === "#" || /^#(lfg|onboarding|unlock=)/.test(h)) document.body.classList.add("bare"); })(location.hash);
/* Appearance (Settings → Appearance), kept per browser: mode, a light and a dark theme, accent, density, text size,
   glow and motion. Applied before the first paint, and again when the system switches light/dark. */
const AP_DEFAULT = { mode: "system", light: "lfg", dark: "midnight", accent: "orange", density: "comfortable", text: "m", glow: "on", motion: "on" };
function apRead() {
  try {
    const saved = JSON.parse(localStorage.getItem("lfg.appearance") || "{}");
    if (!saved.v && saved.accent === "blue") delete saved.accent;  // blue was the default before v2, not a choice
    return Object.assign({}, AP_DEFAULT, saved);
  } catch (e) { return Object.assign({}, AP_DEFAULT); }
}
function apApply(a) {
  a = a || apRead();
  const dark = a.mode === "dark" || (a.mode === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  const r = document.documentElement.dataset;
  r.mode = dark ? "dark" : "light"; r.theme = dark ? a.dark : a.light;
  r.accent = a.accent; r.density = a.density; r.text = a.text; r.glow = a.glow; r.motion = a.motion;
}
function apSet(k, v) { const a = apRead(); a[k] = v; a.v = 2; try { localStorage.setItem("lfg.appearance", JSON.stringify(a)); } catch (e) { /* private window: this visit only */ } apApply(a); apFavicon(); return a; }
/* The logo, drawn in the accent colour (inline, so it follows the theme); the favicon is rebuilt to match. */
let LOGO_N = 2e6;  // logos drawn outside a page; a page numbers its own from 1
function logoSvg(size) {
  const g = "lg" + (tPage ? ++TID : ++LOGO_N);  // numbered with the page, so a redraw draws the same logo
  return `<svg class="lfg-logo" width="${size}" height="${size}" viewBox="0 0 32 32" aria-hidden="true"><defs><linearGradient id="${g}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" style="stop-color:var(--logo-a)"/><stop offset=".55" style="stop-color:var(--logo-b)"/><stop offset="1" style="stop-color:var(--logo-c)"/></linearGradient></defs><rect width="32" height="32" rx="7" fill="url(#${g})"/><path d="M8.5 9.5 15 16l-6.5 6.5" fill="none" stroke="#fff" stroke-opacity=".55" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"/><path d="M15.5 9.5 22 16l-6.5 6.5" fill="none" stroke="#fff" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"/><circle cx="26.2" cy="16" r="1.6" fill="#fff"/></svg>`;
}
function hexMix(a, b, t) {  // t of a, the rest b
  const p = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
  const [x, y] = [p(a), p(b)];
  return "#" + x.map((v, i) => Math.round(v * t + y[i] * (1 - t)).toString(16).padStart(2, "0")).join("");
}
function apFavicon() {
  const c = (getComputedStyle(document.documentElement).getPropertyValue("--blue") || "").trim();
  if (!/^#[0-9a-f]{6}$/i.test(c)) return;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${hexMix(c, "#ffffff", .72)}"/><stop offset=".55" stop-color="${c}"/><stop offset="1" stop-color="${hexMix(c, "#000000", .62)}"/></linearGradient></defs><rect width="32" height="32" rx="7" fill="url(#g)"/><path d="M8.5 9.5 15 16l-6.5 6.5" fill="none" stroke="#fff" stroke-opacity=".55" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"/><path d="M15.5 9.5 22 16l-6.5 6.5" fill="none" stroke="#fff" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"/><circle cx="26.2" cy="16" r="1.6" fill="#fff"/></svg>`;
  const link = document.querySelector('link[rel="icon"]');
  if (link) link.href = "data:image/svg+xml," + encodeURIComponent(svg);
}
apApply();
document.addEventListener("DOMContentLoaded", apFavicon); apFavicon();
try { matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { apApply(); apFavicon(); }); } catch (e) { /* old browsers */ }
/* LFG dashboard: a plain-language view of what LFG is doing in your repos. Read-only, except Settings, which saves
   only with the local edit key from `lfg ui`. Author: Varun Singh. No external resources. */
"use strict";

// ------------------------------------------------------------------ helpers
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const n = v => (v == null || v === "" ? "—" : Number(v).toLocaleString());
function compact(v) {
  if (v == null || isNaN(v)) return "—";
  const a = Math.abs(v);
  if (a >= 1e9) return (v / 1e9).toFixed(1).replace(/\.0$/, "") + "B";
  if (a >= 1e6) return (v / 1e6).toFixed(1).replace(/\.0$/, "") + "M";
  if (a >= 1e3) return (v / 1e3).toFixed(1).replace(/\.0$/, "") + "k";
  return String(v);
}
function ago(ts) {
  if (!ts) return "never";
  if (/^\d{4}-\d{2}-\d{2}$/.test(ts)) {  // day-granular (Omnigraph Date): compare calendar days, local time
    const t = new Date(), days = Math.round((new Date(t.getFullYear(), t.getMonth(), t.getDate()) - new Date(ts + "T00:00")) / 864e5);
    return days <= 0 ? "today" : days === 1 ? "yesterday" : days + " days ago";
  }
  const s = (Date.now() - new Date(ts).getTime()) / 1000;
  if (isNaN(s)) return esc(ts);
  if (s < 60) return "just now";
  if (s < 3600) return Math.floor(s / 60) + "m ago";
  if (s < 86400) return Math.floor(s / 3600) + "h ago";
  const d = Math.floor(s / 86400);
  return d === 1 ? "yesterday" : d + " days ago";
}
const pct = (a, b) => (b ? Math.round((100 * a) / b) : 0);
const plural = (k, w) => `${n(k)} ${w}${k === 1 ? "" : "s"}`;
const words = s => String(s || "").replace(/[-_]+/g, " ").replace(/\.md$/, "");
const state = { repo: localStorage.getItem("lfg.repo") || "", branch: "", repos: [], cache: {} };
const branchPref = () => "lfg.branch." + state.repo;

async function api(view, params = {}) {
  const q = new URLSearchParams({ repo: state.repo, ...(state.branch ? { branch: state.branch } : {}), ...(state.fresh ? { fresh: "1" } : {}), ...params });
  const r = await fetch(`/api/${view}?${q}`, { headers: { "X-LFG": "1" } });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

const repoName = (id = state.repo) => (state.repos || []).find(x => x.id === id)?.name || id;
/* Sessions, PR reviews and Environment list every repo on this computer: they show the picked repo unless "Show all
   repos" is on, remembered per page like the branch. The server does the filtering. */
const allRepos = page => !state.repo || localStorage.getItem("lfg.allrepos." + page) === "1";
const scopeArgs = page => (allRepos(page) ? { all: "1" } : {});
const scopeLine = page => !state.repo ? "" : allRepos(page)
  ? `Showing <b>all repos</b>. <a href="#" data-scope="${page}">Show only ${esc(repoName())}</a>`
  : `Showing <b>${esc(repoName())}</b> only. <a href="#" data-scope="${page}">Show all repos</a>`;
const shq = p => (/^[\w@%+=:,./-]+$/.test(p) ? p : `'${String(p).replace(/'/g, "'\\''")}'`);  // a path, safe to paste in a shell
const usd = v => "$" + (v >= 100 ? Math.round(v).toLocaleString() : v.toFixed(2));
// ------------------------------------------------------------------ plain words for tool status values
/* Every status value the tools write, as [what a person reads, tone]. Unknown values show as written. */
const SAY = {
  // checks before commit (ready.json)
  green: ["Checks pass", "ok"], red: ["Checks failing", "bad"],
  // review verdict
  approve: ["Approved", "ok"], changes: ["Changes requested", "warn"], block: ["Blocked", "bad"],
  // security verdict
  safe: ["No problems", "ok"], "safe with caveats": ["Minor notes", "warn"], "don't": ["Problems to fix", "bad"],
  // ship check
  pass: ["Passed", "ok"], fail: ["Failed", "bad"], pass_with_skips: ["Passed with skips", "ok"], needs_config: ["Needs build settings", "warn"],
  // graphs
  fresh: ["Up to date", "ok"], stale: ["Out of date", "warn"], syncing: ["Updating", "warn"], missing: ["Not built yet", "warn"], error: ["Error", "bad"],
  // issues and knowledge
  backlog: ["Backlog", ""], todo: ["To do", ""], in_progress: ["In progress", "on"], needs_review: ["In review", "warn"], hold: ["On hold", "warn"],
  done: ["Done", "ok"], canceled: ["Canceled", ""], duplicate: ["Duplicate", ""],
  accepted: ["Accepted", "ok"], proposed: ["Proposed", "warn"], rejected: ["Rejected", ""], superseded: ["Replaced", ""],
  holds: ["Holds", "ok"], violated: ["Broken", "bad"], unheld: ["Not checked by a test", "warn"],
  active: ["Active", "ok"], relaxed: ["Relaxed", ""], retired: ["Retired", ""],
  narrowing: ["Shrinking", "ok"], widened: ["Growing", "bad"], closed: ["Closed", "ok"],
  // review severity
  blocker: ["Must fix", "bad"], major: ["Should fix", "warn"], minor: ["Minor", ""], nit: ["Nitpick", ""],
  critical: ["Critical", "bad"], high: ["High", "bad"], medium: ["Medium", "warn"], moderate: ["Medium", "warn"], low: ["Low", ""],
  accept: ["You agreed", "ok"], reject: ["You disagreed", ""],
  // security test (pentest)
  refused: ["Didn't run", "warn"], completed: ["Finished", "ok"], findings: ["Found problems", "bad"],
};
const say = v => SAY[String(v ?? "").toLowerCase()] || [v == null || v === "" ? "" : String(v), ""];
function st(v, fallback) {
  const [text, t] = say(v);
  if (!text) return `<span class="muted">${esc(fallback || "—")}</span>`;
  return `<span class="st"><span class="dot ${t}"></span>${esc(text)}</span>`;
}
const dot = t => `<span class="dot ${t}"></span>`;
const fmtWhy = w => esc(w || "").replace(/`([^`]+)`/g, "<code>$1</code>");

/* Pipeline steps, in the words a person uses */
/* What each step of a run is: [command that does it, what it produces]. */
const STEP_WHY = {
  brief: ["/lfg:grill", "Writes up the idea: the problem, who it's for, and how you'll know it works."],
  design: ["/lfg:plan", "Designs the change from the code graphs. Small changes can skip it."],
  tasks: ["/lfg:plan", "Breaks the plan into tickets, each with its tests agreed up front."],
  build: ["/lfg:build", "Writes the code, test first, one ticket at a time."],
  qa: ["/lfg:check", "Proves each acceptance criterion with a test."],
  gate: ["/lfg:check", "Runs lint, types, tests and build, like CI."],
  secure: ["/lfg:secure", "Vets new packages, URLs and security-sensitive code."],
  review: ["/lfg:expert", "Reviews standards, spec and what the change could break."],
  ship: ["/lfg:ship", "Builds and smoke-tests it in Docker."],
  packet: ["/lfg:ship", "Writes the commit message and PR body for you."] };
const STEP = { brief: "Idea written up", design: "Plan", tasks: "Task list", build: "Built", qa: "Tested", gate: "Checks run",
  secure: "Security check", review: "Code review", ship: "Ship check", packet: "Ready to commit" };
const NEXT = { brief: "write up the idea", design: "make a plan", tasks: "split it into tasks", build: "build it", qa: "test it",
  gate: "run the checks", secure: "check security", review: "review the code", ship: "run the ship check", packet: "prepare the commit message",
  "fix-checks": "fix the failing checks (/lfg:fix)", "fix-block": "decide what to do about the blocked review",
  "fix-review": "address the review's requested changes", "fix-security": "fix the security problems (/lfg:fix)",
  "fix-ship": "fix what the ship check found" };
function runPlace(stages, done, r) {
  /* done = steps that really happened, or were done outside LFG (commits on the run's branch); skipped ones (`lfg run
     skip`) count neither way. next = what blocks first (a failing check, a review asking for changes), else the step
     after the furthest one done or skipped: steps run out of order never send you back to an earlier one */
  const out = (r && r.outside) || {}, skip = (r && r.skipped) || {};
  const did = k => done[k] || !!out[k];
  const keys = stages.map(s => s[0]), last = keys.reduce((a, x, i) => (did(x) || skip[x] ? i : a), -1);
  const count = keys.filter(did).length, total = keys.filter(k => !skip[k]).length;
  const block = r && (r.ready === "red" ? "fix-checks" : r.review === "block" ? "fix-block" : r.secure === "don't" ? "fix-security"
    : r.review === "changes" ? "fix-review" : r.shipcheck === "fail" ? "fix-ship" : null);  // most serious first
  const next = block || keys.slice(last + 1)[0];
  return { done: count, total, next, blocked: !!block, finished: !next, last };
}
const runName = r => r.title || (w => w.charAt(0).toUpperCase() + w.slice(1))(words(r.slug || "untitled run"));

// ------------------------------------------------------------------ components
function empty(title, body) {
  return `<div class="empty"><h3>${esc(title)}</h3><div>${body || ""}</div></div>`;
}
function unavailable(d, title) {
  return `<div class="callout warn"><b>${esc(title || "Not available yet")}</b><div class="small" style="margin-top:2px">${fmtWhy(d && d.why)}</div></div>`;
}
function head(title, text, back) {
  return `<div class="head">${back || ""}<h1>${esc(title)}</h1>${text ? `<p>${text}</p>` : ""}</div>`;
}
function section(title, body, sub) {
  return `<div class="section"><h2>${esc(title)}${sub ? `<span class="sub">${sub}</span>` : ""}</h2>${body}</div>`;
}
function stat(k, v, s) {
  return `<div class="box stat"><div class="k">${esc(k)}</div><div class="v">${v}</div>${s ? `<div class="s">${s}</div>` : ""}</div>`;
}

/* table(rows, cols, opts): cols = [{k, label, num, html: row => string, sort: row => value}] */
/* A page's tables are numbered from 1 each time the page draws, so a redraw finds the same table (and keeps how you
   sorted and filtered it); one drawn later (a drawer) gets a number no page uses. */
let TID = 0, TLATE = 1e6, tPage = false;
const TABLES = {};
function table(rows, cols, opts = {}) {
  const id = "t" + (tPage ? ++TID : ++TLATE);
  if (!rows || !rows.length) return empty(opts.emptyTitle || "Nothing here yet", opts.emptyBody || "");
  const was = TABLES[id], same = was && was.cols.map(c => c.k).join() === cols.map(c => c.k).join();
  TABLES[id] = { rows, cols, opts, sort: same ? was.sort : opts.sort || null, dir: same ? was.dir : opts.dir || -1, filter: same ? was.filter : "" };
  const tools = rows.length > 15 && opts.filter !== false ?
    `<div class="table-tools"><input type="search" placeholder="Search…" data-filter="${id}"><span class="count" id="${id}-count"></span></div>` : "";
  return `${tools}<div class="table-wrap"><table id="${id}" data-fill></table></div>`;
}
function drawTable(id) {
  const t = TABLES[id], el = document.getElementById(id);
  if (!t || !el) return;
  const f = t.filter.toLowerCase();
  const rows = f ? t.rows.filter(r => JSON.stringify(r).toLowerCase().includes(f)) : t.rows.slice();
  if (t.sort != null) {
    const c = t.cols.find(c => c.k === t.sort);
    const val = r => (c && c.sort ? c.sort(r) : r[t.sort]);
    rows.sort((a, b) => {
      const x = val(a), y = val(b);
      if (x == null) return 1; if (y == null) return -1;
      return (typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y))) * t.dir;
    });
  }
  const shown = rows.slice(0, t.opts.limit || 500);
  morph(el, `<thead><tr>${t.cols.map(c => `<th data-k="${esc(c.k)}" class="${c.num ? "num" : ""} ${t.sort === c.k ? (t.dir > 0 ? "sorted-asc" : "sorted-desc") : ""}">${esc(c.label)}</th>`).join("")}</tr></thead>
    <tbody>${shown.map(r => `<tr class="${t.opts.onRow ? "click" : ""}" data-i="${t.rows.indexOf(r)}">${t.cols.map(c => `<td class="${c.num ? "num" : ""}">${c.html ? c.html(r) : c.num ? n(r[c.k]) : esc(r[c.k])}</td>`).join("")}</tr>`).join("")}</tbody>`);
  const cnt = document.getElementById(id + "-count");
  if (cnt) cnt.textContent = rows.length === t.rows.length ? plural(rows.length, "item") : `${n(rows.length)} of ${n(t.rows.length)}`;
  $$("th", el).forEach(th => th.onclick = () => { const k = th.dataset.k; t.dir = t.sort === k ? -t.dir : -1; t.sort = k; drawTable(id); });
  if (t.opts.onRow) $$("tbody tr", el).forEach(tr => tr.onclick = e => { if (!e.target.closest("input, button, a, label, select, textarea")) t.opts.onRow(t.rows[+tr.dataset.i]); });
}
function mountTables(root = document) {
  $$("table[id^=t]", root).forEach(el => drawTable(el.id));
  $$("input[data-filter]", root).forEach(inp => inp.oninput = () => { TABLES[inp.dataset.filter].filter = inp.value; drawTable(inp.dataset.filter); });
}

/* tabs(id, [[key, label, count, htmlFn]]): renders lazily; tabs with a 0 count are left out unless all are empty */
const TABS = {};
function tabs(id, items) {
  const shown = items.filter(it => it[2] == null || it[2] > 0);
  const list = shown.length ? shown : items.slice(0, 1);
  TABS[id] = list;
  return `<div class="tabs" data-tabs="${id}">${list.map(([k, l, c]) => `<button class="tab" data-k="${esc(k)}">${esc(l)}${c ? `<span class="n">${compact(c)}</span>` : ""}</button>`).join("")}</div><div id="${id}-body" data-fill></div>`;
}
function mountTabs(root = document) {
  $$("[data-tabs]", root).forEach(bar => {
    const id = bar.dataset.tabs;
    const show = k => {
      $$(".tab", bar).forEach(b => { b.classList.toggle("on", b.dataset.k === k); if (b.dataset.k === k && bar.scrollWidth > bar.clientWidth) bar.scrollLeft = b.offsetLeft - 16; });
      const it = TABS[id].find(x => x[0] === k);
      const body = document.getElementById(id + "-body");
      morph(body, it[3]());
      mountTables(body); mountTabs(body); wire(body);
      sessionStorage.setItem("lfg.tab." + id, k);
    };
    $$(".tab", bar).forEach(b => b.onclick = () => show(b.dataset.k));
    const saved = sessionStorage.getItem("lfg.tab." + id);
    show(TABS[id].some(x => x[0] === saved) ? saved : TABS[id][0][0]);
  });
}

/* simple bar chart: data=[{label, values:[...]}], series=[[name,color]] */
/* Interactive bars: hover or focus a day for its numbers, click it to pin it (onPick), click a legend key to hide a
   series. data: [{label, values: [..], raw}], series: [[name, color, fmt]]. The y-axis gutter fits its labels. */
const ICHARTS = {};
function iChart(data, series, opts = {}) {
  const id = "ic" + (tPage ? ++TID : ++TLATE);  // numbered with the page's tables: a redraw finds the same chart
  const was = ICHARTS[id], same = was && was.series.map(x => x[0]).join() === series.map(x => x[0]).join();  // and keeps what you hid
  ICHARTS[id] = { data, series, opts, hidden: same ? was.hidden : new Set(opts.hidden || []), pick: opts.pick ?? null };
  return `<div class="ichart" id="${id}">${iChartBody(id)}</div>`;
}
function iChartBody(id) {
  const C = ICHARTS[id], { data, series, opts } = C, h = opts.h || 180;
  if (!data.length) return '<div class="muted small">Nothing recorded in this period.</div>';
  const fmt = series[0][2] || compact;
  const shown = series.map((_, j) => !C.hidden.has(j));
  const tot = d => d.values.reduce((a, v, j) => a + (shown[j] ? v || 0 : 0), 0);
  const max = Math.max(...data.map(tot), 1);
  const P = Math.max(34, 8 + 7 * fmt(max).length), W = 760, top = 14, base = h - 22;
  const step = (W - P - 8) / data.length, bw = Math.max(3, Math.min(28, step - Math.max(2, step * 0.18)));
  const x = i => P + 4 + i * step + (step - bw) / 2;
  const every = Math.ceil(data.length / 9);
  let bars = "";
  data.forEach((d, i) => {
    let y = base;
    const segs = d.values.map((v, j) => {
      if (!shown[j] || !v) return "";
      const bh = Math.max(1, (v / max) * (base - top));
      y -= bh;
      const ghost = series[j][3] && series[j][3].ghost;
      return ghost ? `<rect class="ghost" x="${x(i) + 0.75}" y="${y + 0.75}" width="${bw - 1.5}" height="${Math.max(0, bh - 1.5)}" rx="2" style="stroke:${series[j][1]}"></rect>`
        : `<rect x="${x(i)}" y="${y}" width="${bw}" height="${bh}" rx="2" style="fill:${series[j][1]}"></rect>`;
    }).join("");
    bars += `<g class="bar ${C.pick === i ? "on" : ""}" data-i="${i}" tabindex="0" role="button" aria-label="${esc(d.label)}: ${esc(series.map((sr, j) => shown[j] ? sr[0] + " " + (sr[2] || compact)(d.values[j] || 0) : "").filter(Boolean).join(", "))}"><rect class="hit" x="${P + 4 + i * step}" y="${top}" width="${step}" height="${base - top}"></rect>${segs}</g>`;
    if (i % every === 0 || data.length <= 10) bars += `<text x="${x(i) + bw / 2}" y="${h - 6}" text-anchor="middle">${esc(d.short || d.label.slice(5))}</text>`;
  });
  const grid = [0, 0.5, 1].map(t => `<line class="axis${t ? " faint" : ""}" x1="${P}" x2="${W}" y1="${base - t * (base - top)}" y2="${base - t * (base - top)}"/><text x="${P - 6}" y="${base - t * (base - top) + 4}" text-anchor="end">${esc(fmt(max * t))}</text>`).join("");
  const legend = series.length > 1 ? `<div class="legend">${series.map(([nm, c, , o], j) => `<button class="lkey ${shown[j] ? "" : "off"}" data-ic-key="${j}" title="Show or hide ${esc(nm)}"><i class="${o && o.ghost ? "ghost" : ""}" style="${o && o.ghost ? "border-color" : "background"}:${c}"></i>${esc(nm)}</button>`).join("")}</div>` : "";
  return `<div class="chart"><svg viewBox="0 0 ${W} ${h}" role="img" aria-label="${esc(opts.title || "")}">${grid}${bars}</svg><div class="ic-tip" hidden></div></div>${legend}`;
}
function wireIChart(id) {
  const el = document.getElementById(id), C = ICHARTS[id];
  if (!el || !C) return;
  const tip = $(".ic-tip", el), svg = $("svg", el);
  if (!svg) return;  // "Nothing recorded": no bars to wire
  const show = (g, ev) => {
    const i = +g.dataset.i, d = C.data[i];
    tip.textContent = "";
    const t = document.createElement("div"); t.className = "ic-t"; t.textContent = d.label; tip.appendChild(t);
    C.series.forEach(([nm, c, f], j) => {
      if (C.hidden.has(j)) return;
      const r = document.createElement("div"); r.className = "ic-r";
      const k = document.createElement("i"); k.style.background = c;
      const v = document.createElement("b"); v.textContent = (f || compact)(d.values[j] || 0);
      const l = document.createElement("span"); l.textContent = nm;
      r.append(k, v, l); tip.appendChild(r);
    });
    if (C.opts.total) {
      const tt = C.opts.total(d, C.hidden);
      if (tt) { const r = document.createElement("div"); r.className = "ic-h"; r.textContent = tt; tip.appendChild(r); }
    }
    if (C.opts.onPick) { const h = document.createElement("div"); h.className = "ic-h"; h.textContent = "Click for the breakdown"; tip.appendChild(h); }
    tip.hidden = false;
    const box = el.querySelector(".chart").getBoundingClientRect(), gr = g.getBoundingClientRect();
    const left = Math.min(Math.max(gr.left - box.left + gr.width / 2 - tip.offsetWidth / 2, 0), box.width - tip.offsetWidth);
    tip.style.left = left + "px";
    tip.style.top = Math.max(0, gr.top - box.top - tip.offsetHeight - 6) + "px";
  };
  $$("g.bar", svg).forEach(g => {
    g.onpointerenter = e => show(g, e);
    g.onfocus = e => show(g, e);
    g.onpointerleave = g.onblur = () => (tip.hidden = true);
    const pick = () => { if (!C.opts.onPick) return; C.pick = C.pick === +g.dataset.i ? null : +g.dataset.i; el.innerHTML = iChartBody(id); wireIChart(id); C.opts.onPick(C.pick); };
    g.onclick = pick;
    g.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } };
  });
  $$("[data-ic-key]", el).forEach(b => b.onclick = () => {
    const j = +b.dataset.icKey;
    if (C.hidden.has(j)) C.hidden.delete(j); else if (C.hidden.size < C.series.length - 1) C.hidden.add(j);
    el.innerHTML = iChartBody(id); wireIChart(id);
  });
}
function wireICharts(root) { $$(".ichart", root).forEach(el => wireIChart(el.id)); }
function barChart(data, series, h = 160) {
  if (!data.length) return '<div class="muted small">Nothing recorded in this period.</div>';
  const W = 760, P = 34, bw = Math.max(4, Math.min(24, (W - P - 10) / data.length - 4));
  const max = Math.max(...data.map(d => d.values.reduce((a, b) => a + (b || 0), 0)), 1);
  const x = i => P + 6 + i * ((W - P - 10) / data.length);
  let bars = "";
  data.forEach((d, i) => {
    let y = h - 20;
    d.values.forEach((v, j) => {
      const bh = ((v || 0) / max) * (h - 34);
      y -= bh;
      bars += `<rect x="${x(i)}" y="${y}" width="${bw}" height="${bh}" rx="2" style="fill:${series[j][1]}"><title>${esc(d.label)} · ${esc(series[j][0])}: ${n(v)}</title></rect>`;
    });
    if (data.length <= 16 || i % Math.ceil(data.length / 8) === 0) bars += `<text x="${x(i) + bw / 2}" y="${h - 6}" text-anchor="middle">${esc(d.label.slice(5))}</text>`;
  });
  const ticks = [0, 1].map(t => `<line class="axis" x1="${P}" x2="${W}" y1="${h - 20 - t * (h - 34)}" y2="${h - 20 - t * (h - 34)}"/><text x="${P - 4}" y="${h - 17 - t * (h - 34)}" text-anchor="end">${compact(Math.round(max * t))}</text>`).join("");
  return `<div class="chart"><svg viewBox="0 0 ${W} ${h}" role="img">${ticks}${bars}</svg></div><div class="legend">${series.map(([s, c]) => `<span><i style="background:${c}"></i>${esc(s)}</span>`).join("")}</div>`;
}

// ------------------------------------------------------------------ markdown (safe: escape first, allow-list links)
function inline(s, link) {
  const codes = [];
  s = esc(s).replace(/`([^`]+)`/g, (_, c) => { codes.push(c); return `\u0000${codes.length - 1}\u0000`; });
  s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, t, u) => {
    const raw = u.replace(/&amp;/g, "&");
    if (/^https?:\/\//i.test(raw)) return `<a href="${esc(raw)}" target="_blank" rel="noopener noreferrer">${t}</a>`;
    const xd = link && /^lfgdoc:([a-z]+)\/(.+\.md)$/i.exec(raw);  // link to another docs source
    if (xd) return `<a href="#docs/${esc(xd[1])}/${esc(encodeURIComponent(xd[2]))}">${t}</a>`;
    if (link && /\.md(#.*)?$/i.test(raw) && !/^[a-z]+:/i.test(raw)) return `<a href="#" data-doclink="${esc(raw)}">${t}</a>`;
    return t;
  });
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>").replace(/(^|[\s(])_([^_]+)_(?=[\s).,;:]|$)/g, "$1<em>$2</em>")
    .replace(/(^|[\s(])\*([^*]+)\*(?=[\s).,;:]|$)/g, "$1<em>$2</em>");
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${codes[+i]}</code>`);
}
/* A code block, with Copy. A block wrapped in "--- PASTE START (where) ---" / "--- PASTE END ---" (how Claude marks
   something to paste, which keeps it exact in a terminal) shows only what goes in, under a "Paste into" line naming
   where; Copy takes only what goes in. */
const PASTE_START = /^\s*-{2,}\s*PASTE START\s*(?:\((.*)\))?\s*-{2,}\s*$/i, PASTE_END = /^\s*-{2,}\s*PASTE END\s*-{2,}\s*$/i;
function pasteParts(lines) {  // {where, body} when the lines are one paste block, else null
  const s = lines.findIndex(x => x.trim()), e = lines.length - 1 - [...lines].reverse().findIndex(x => x.trim());
  const m = s >= 0 && PASTE_START.exec(lines[s]);
  return m && e > s && PASTE_END.test(lines[e]) ? { where: m[1] || "", body: lines.slice(s + 1, e) } : null;
}
const FENCE = /^\s{0,3}(```|~~~)/;
/* What a message's Copy takes: the text as written, but each paste block (fenced or not) as only what goes in */
function copyText(text) {
  const L = String(text || "").replace(/\r/g, "").split("\n"), out = [];
  for (let i = 0; i < L.length; i++) {
    const f = FENCE.exec(L[i]);
    if (f) {
      let j = i + 1; while (j < L.length && !L[j].trimStart().startsWith(f[1])) j++;
      const p = pasteParts(L.slice(i + 1, j));
      out.push(...(p ? p.body : L.slice(i, j + 1))); i = j; continue;
    }
    if (PASTE_START.test(L[i])) {
      let j = i + 1; while (j < L.length && !PASTE_END.test(L[j])) j++;
      if (j < L.length) { out.push(...L.slice(i + 1, j)); i = j; continue; }
    }
    out.push(L[i]);
  }
  return out.join("\n").replace(/\n{3,}/g, "\n\n").trim();
}
function codeBlock(lines) {
  const p = pasteParts(lines), where = p ? p.where : null, body = p ? p.body : lines;
  return `<div class="code-blk">${where !== null ? `<div class="code-h">${where ? `Paste into: ${esc(where)}` : "To paste"}</div>` : ""}<pre><code>${esc(body.join("\n"))}</code></pre><button type="button" class="code-copy" data-code-copy title="Copy this block">${icon("copy")}Copy</button></div>`;
}
document.addEventListener("click", async e => {  // one listener for every code block, however it was drawn
  const b = e.target.closest && e.target.closest("[data-code-copy]");
  const code = b && b.parentElement.querySelector("pre code");
  if (!code) return;
  const was = b.innerHTML;
  try { await navigator.clipboard.writeText(code.textContent); b.textContent = "Copied"; } catch (err) { b.textContent = "Select and copy"; }
  setTimeout(() => { b.innerHTML = was; }, 1400);
});
function md(text, link) {
  const L = String(text || "").replace(/\r/g, "").split("\n");
  let out = "", i = 0;
  const para = [];
  const flush = () => { if (para.length) { out += `<p>${inline(para.join(" "), link)}</p>`; para.length = 0; } };
  while (i < L.length) {
    const l = L[i];
    const f = FENCE.exec(l);
    if (f) {
      flush(); const buf = []; i++;
      while (i < L.length && !L[i].trimStart().startsWith(f[1])) buf.push(L[i++]);
      i++; out += codeBlock(buf); continue;
    }
    if (PASTE_START.test(l)) {  // a paste block written without a fence
      let j = i + 1; while (j < L.length && !PASTE_END.test(L[j])) j++;
      if (j < L.length) { flush(); out += codeBlock(L.slice(i, j + 1)); i = j + 1; continue; }
    }
    if (/^\s*\|.*\|\s*$/.test(l) && i + 1 < L.length && /^\s*\|?[\s:-]+\|[\s|:-]*$/.test(L[i + 1])) {
      flush();
      const cells = r => r.trim().replace(/^\||\|$/g, "").split(/(?<!\\)\|/).map(c => c.trim().replace(/\\\|/g, "|"));
      const hd = cells(l); i += 2; const body = [];
      while (i < L.length && /^\s*\|/.test(L[i])) body.push(cells(L[i++]));
      out += `<div class="md-table"><table><thead><tr>${hd.map(h => `<th>${inline(h, link)}</th>`).join("")}</tr></thead><tbody>${body.map(r => `<tr>${r.map(c => `<td>${inline(c, link)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
      continue;
    }
    let m;
    if ((m = l.match(/^(#{1,4})\s+(.*)$/))) { flush(); out += `<h${m[1].length}>${inline(m[2], link)}</h${m[1].length}>`; i++; continue; }
    if (/^\s*(---|\*\*\*)\s*$/.test(l)) { flush(); out += "<hr>"; i++; continue; }
    if (/^>\s?/.test(l)) {
      flush(); const buf = [];
      while (i < L.length && /^>\s?/.test(L[i])) buf.push(L[i++].replace(/^>\s?/, ""));
      out += `<blockquote>${md(buf.join("\n"), link)}</blockquote>`; continue;
    }
    if (/^\s*([-*+]|\d+\.)\s+/.test(l)) {
      flush(); const ordered = /^\s*\d+\./.test(l); const buf = [];
      while (i < L.length && /^\s*([-*+]|\d+\.)\s+/.test(L[i])) {
        let item = L[i++].replace(/^\s*([-*+]|\d+\.)\s+/, "");
        while (i < L.length && /^\s{2,}\S/.test(L[i]) && !/^\s*([-*+]|\d+\.)\s+/.test(L[i])) item += " " + L[i++].trim();
        buf.push(item);
      }
      const li = b => { const t = /^\[( |x|X)\]\s+(.*)$/.exec(b); return t ? `<li class="task${t[1] === " " ? "" : " done"}"><span class="cb" aria-hidden="true"></span><span>${inline(t[2], link)}</span></li>` : `<li>${inline(b, link)}</li>`; };
      out += `<${ordered ? "ol" : "ul"}>${buf.map(li).join("")}</${ordered ? "ol" : "ul"}>`; continue;
    }
    if (!l.trim()) { flush(); i++; continue; }
    para.push(l.trim()); i++;
  }
  flush();
  return out;
}

// ------------------------------------------------------------------ drawer (file viewer)
function openDrawer(title, html) {
  $("#drawer-title").textContent = title;
  $("#drawer-body").innerHTML = html;
  $("#drawer").hidden = false;
  mountTables($("#drawer-body"));
}
function closeDrawer() { $("#drawer").hidden = true; }
function renderFile(name, text) {
  if (/\.md$/i.test(name)) return `<div class="md">${md(frontMatter(text).body)}</div>`;
  if (/\.json$/i.test(name)) {
    let d;
    try { d = JSON.parse(text); } catch (e) { d = undefined; }
    if (d !== undefined) { const v = JSON_VIEWS[name.split("/").pop()]; return `<div class="readable">${v ? v(d) : readable(d)}</div>`; }
  }
  return `<pre class="raw">${esc(text)}</pre>`;
}

// ------------------------------------------------------------------ readable views (never raw JSON)
/* Agents sometimes write a field as structured data ({criterion, seam}, a list, counts) where a sentence was expected:
   flatten it to readable text instead of "[object Object]". */
const human = k => String(k).replace(/[_-]+/g, " ").replace(/^\w/, c => c.toUpperCase());
function plain(v) {
  if (v == null) return "";
  if (typeof v !== "object") return String(v);
  if (Array.isArray(v)) return v.map(plain).filter(Boolean).join("; ");
  return Object.entries(v).filter(([, x]) => x != null && x !== "" && !(Array.isArray(x) && !x.length))
    .map(([k, x]) => `${human(k)}: ${plain(x)}`).join(" · ");
}
const txt = v => inline(plain(v));
/* A task's verification: a sentence, or {criterion, seam} (what must hold, and where it's proved) */
function verifyHtml(v) {
  if (v && typeof v === "object" && !Array.isArray(v) && (v.criterion || v.seam)) {
    const rest = Object.fromEntries(Object.entries(v).filter(([k]) => k !== "criterion" && k !== "seam"));
    return `${v.criterion ? `<p>${txt(v.criterion)}</p>` : ""}${v.seam ? `<p class="muted small">Proved by: ${txt(v.seam)}</p>` : ""}${Object.keys(rest).length ? `<p class="muted small">${txt(rest)}</p>` : ""}`;
  }
  return `<p>${txt(v)}</p>`;
}
const label = k => { const s = words(k).replace(/([a-z])([A-Z])/g, "$1 $2").toLowerCase(); return s.charAt(0).toUpperCase() + s.slice(1); };
/* Any JSON as headings, lists and sentences */
function readable(v) {
  if (v == null || v === "") return '<span class="muted">—</span>';
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (typeof v !== "object") return txt(v);
  if (Array.isArray(v)) {
    if (!v.length) return '<span class="muted">None</span>';
    if (v.every(x => x == null || typeof x !== "object")) return `<ul>${v.map(x => `<li>${readable(x)}</li>`).join("")}</ul>`;
    return v.map(x => `<div class="card">${readable(x)}</div>`).join("");
  }
  return `<dl class="kv">${Object.entries(v).map(([k, x]) => `<dt>${esc(label(k))}</dt><dd>${readable(x)}</dd>`).join("")}</dl>`;
}
function moreDetails(d, skip) {
  const r = Object.fromEntries(Object.entries(d || {}).filter(([k, v]) => !skip.includes(k) && v != null && v !== "" && !(Array.isArray(v) && !v.length)));
  return Object.keys(r).length ? `<details class="more"><summary>More details</summary>${readable(r)}</details>` : "";
}
const AXIS = { standards: "Coding standards", spec: "Does what was asked", blast_radius: "Effect on other code", blast: "Effect on other code" };
/* One review or security finding: what's wrong, why, what to do, where */
function findingCard(f) {
  // scanner findings (lfg secure) have an id, item and evidence instead of a title
  const ev = [].concat(f.evidence || []).map(String);
  const head = f.title || f.finding || f.message || (f.type === "vuln" && f.item ? `${f.item} has a known vulnerability (${f.id})` : ev[0] && f.type === "code" ? ev[0] : f.item || f.id) || "Finding";
  const more = f.title ? f.detail || f.finding || f.message : f.detail;
  const where = f.file ? f.file + (f.line ? ":" + f.line : "") : f.where || f.package || f.target || "";
  const links = ev.filter(x => /^https?:\/\//.test(x));
  return `<div class="card"><div class="row">${st(f.severity)}${f.on_main ? '<span class="tag" title="In a file this branch doesn\'t change, so it was there before this work; not counted in the verdict">already on main</span>' : f.blocking === true ? '<span class="tag">must fix before shipping</span>' : ""}${f.axis ? `<span class="tag">${esc(AXIS[f.axis] || words(f.axis))}</span>` : ""}${f.feedback ? st(f.feedback) : ""}</div>
    <div class="title">${txt(head)}</div>
    ${more ? `<p>${txt(more)}</p>` : ""}
    ${f.fix ? `<p><b>What to do:</b> ${txt(f.fix)}</p>` : ""}
    ${f.reachable ? `<p class="muted small">Can an attacker reach it? ${txt(f.reachable)}</p>` : ""}
    ${f.principle && f.principle !== "None" ? `<p class="muted small">Based on: ${txt(f.principle)}</p>` : ""}
    ${links.length ? `<p class="small">${links.map(u => `<a href="${esc(u)}" target="_blank" rel="noopener noreferrer">Read the advisory ↗</a>`).join(" · ")}</p>` : ""}
    ${where ? `<div class="muted small mono">${esc(where)}</div>` : ""}</div>`;
}
const SEV_RANK = { blocker: 0, critical: 0, high: 1, major: 1, medium: 2, moderate: 2, minor: 3, low: 3, nit: 4 };
const sevRank = f => (f.on_main ? 10 : f.blocking === true ? -1 : 0) + (SEV_RANK[String(f.severity).toLowerCase()] ?? 5);
const findingList = (fs, none) => (fs || []).length ? [...fs].sort((a, b) => sevRank(a) - sevRank(b)).map(findingCard).join("") : `<p class="muted">${esc(none || "Nothing found.")}</p>`;
/* A task: its description, opening to the steps and how it's checked */
function taskItem(t) {
  if (!t || typeof t !== "object") return "";
  const steps = Array.isArray(t.steps) ? t.steps : [], deps = Array.isArray(t.depends_on) ? t.depends_on : [];
  const body = `${steps.length ? `<div class="k">Steps</div><ol>${steps.map(s => `<li>${txt(s)}</li>`).join("")}</ol>` : ""}
    ${t.verification ? `<div class="k">How we know it works</div>${verifyHtml(t.verification)}` : ""}
    ${t.notes ? `<div class="k">Notes</div><p>${txt(t.notes)}</p>` : ""}
    ${deps.length ? `<p class="muted small">Waits for: ${esc(deps.join(", "))}</p>` : ""}`;
  return `<details class="item"><summary>${dot(t.passes ? "ok" : "")}<span class="grow">${txt(t.description || t.id || "Task")}</span><span class="muted small nowrap">${t.passes ? "done" : "to do"}</span></summary><div class="item-body">${body}</div></details>`;
}
/* A check that ran (tests, lint, ship check): failed ones open to show the error */
const CHECK_NAMES = { lint: "Lint", types: "Type check", test: "Tests", build: "Build", secrets: "Secret scan",
  suppressions: "No new lint or test suppressions" };
function checkItem(name, result, out, cmd, log) {
  const [word, tone] = { pass: ["passed", "ok"], fail: ["failed", "bad"], skip: ["not run", ""], na: ["doesn't apply", ""], manual: ["for you to do", "warn"] }[result];
  // the saved output is only the last lines; the run folder keeps the whole log
  const full = log ? `<div class="muted small">Last lines only. <a href="#" data-run-file="${esc(JSON.stringify(log))}" data-title="${esc(`Full log: ${CHECK_NAMES[name] || name}`)}">See the full log</a></div>` : "";
  const body = !["pass", "skip", "na"].includes(result) && out ? `${cmd ? `<div class="muted small mono">${esc(cmd)}</div>` : ""}${full}<pre class="out">${esc(out)}</pre>` : "";
  return `<details class="item${body ? "" : " plain"}"><summary>${dot(tone)}<span class="grow">${esc(CHECK_NAMES[name] || (/\s/.test(name || "") ? name : (w => w.charAt(0).toUpperCase() + w.slice(1))(words(name || ""))))}</span><span class="muted small nowrap">${word}</span></summary>${body ? `<div class="item-body">${body}</div>` : ""}</details>`;
}
const readyChecks = (cs, run) => (cs || []).map(c => checkItem(c.name, c.exit === 0 ? "pass" : c.exit == null ? "skip" : "fail", c.tail, c.cmd,
  run && c.cmd && c.exit ? [run, `gate-logs/${c.name}.log`] : null)).join("");
const shipChecks = cs => (cs || []).map(c => checkItem(c.check || c.name, c.manual ? "manual" : c.status === "n/a" ? "na" : c.ok ? "pass" : c.ok == null ? "skip" : "fail", c.detail)).join("");
/* 07-shipcheck.json: part A (container) checks + the shipping checklist, as one list (same as dash.shipcheck_items) */
const shipItems = d => [].concat(((d.part_a || {}).checks || []).map(c => ({ check: c.check, ok: c.severity === "warn" && c.ok === false ? null : c.ok, detail: c.skip ? `Skipped (${words(c.skip)}). ${c.detail || ""}` : c.detail })),
  (d.checklist || (d.part_b || {}).checks || []).map(i => ({ check: i.requirement || i.check, detail: i.detail, manual: i.status === "manual", status: i.status,
    ok: "ok" in i ? i.ok : i.status === "pass" ? true : i.status === "fail" ? false : null })));
const verdictOf = v => (v && typeof v === "object" ? v.overall : v);
const JSON_VIEWS = {
  "06-review.json": d => `<p>${st(d.verdict)}</p>${typeof d.summary === "string" ? `<p>${txt(d.summary)}</p>` : d.summary ? readable(d.summary) : ""}
    <h3>Findings</h3>${findingList(d.findings, "The review found nothing to change.")}${moreDetails(d, ["verdict", "summary", "findings", "run", "base", "lane", "remember"])}`,
  "05-secure.json": d => `<p>${st(verdictOf(d.verdict))}</p>${d.scope ? `<p class="muted">Checked: ${txt(d.scope)}</p>` : ""}
    <h3>Findings</h3>${findingList(d.findings, "No security problems found.")}${moreDetails(d, ["verdict", "scope", "findings", "ts", "run"])}`,
  "05-pentest.json": d => `<p>${st(d.status)}</p>${d.summary || d.conclusion ? `<p>${txt(d.summary || d.conclusion)}</p>` : ""}
    ${(d.preflight_failures || []).length ? `<h3>Why it didn't run</h3><ul>${d.preflight_failures.map(x => `<li>${txt(x)}</li>`).join("")}</ul>` : ""}
    ${d.next_steps ? `<h3>What to do next</h3><p>${txt(d.next_steps)}</p>` : ""}
    ${(d.findings || []).length ? `<h3>Findings</h3>${findingList(d.findings)}` : ""}${moreDetails(d, ["status", "summary", "conclusion", "preflight_failures", "next_steps", "findings", "ts", "ran"])}`,
  "tasks.json": d => { const l = Array.isArray(d) ? d : d.tasks || []; return l.length ? l.map(taskItem).join("") : '<p class="muted">No tasks.</p>'; },
  "ready.json": d => `<p>${st(d.green ? "green" : "red")}</p>${readyChecks(d.checks)}`,
  "07-shipcheck.json": d => `<p>${st(d.status || (d.pass ? "pass" : "fail"))}</p>${(d.part_a || {}).note ? `<p class="muted">${txt(d.part_a.note)}</p>` : ""}${shipChecks(shipItems(d))}${moreDetails(d, ["pass", "part_a", "part_b", "checklist", "ts", "run", "run_id"])}`,
};
/* Skill and rule files start with a YAML header; show its description, not the YAML */
function frontMatter(text) {
  const m = /^---\n([\s\S]*?)\n---\n?/.exec(String(text || ""));
  if (!m) return { meta: {}, body: String(text || "") };
  const meta = {};
  let key = null;  // "key: value", or "key: >" / "key: |" followed by indented lines
  m[1].split("\n").forEach(l => {
    const k = /^([\w-]+):\s*(.*)$/.exec(l);
    if (k) { key = k[1]; meta[key] = /^[>|][-+]?$/.test(k[2]) ? "" : k[2].replace(/^["']|["']$/g, ""); }
    else if (key && /^\s+\S/.test(l)) meta[key] = (meta[key] ? meta[key] + " " : "") + l.trim();
  });
  return { meta, body: text.slice(m[0].length) };
}
// Knowledge entries open their full text: one listener for the page, so lazily drawn tabs need no wiring.
const openKnow = e => {
  const li = e.target.closest && e.target.closest("[data-kn]");
  if (!li || (e.type === "keydown" && e.key !== "Enter")) return;
  const make = (state.know || [])[+li.dataset.kn];
  if (make) openDrawer(...make());
};
document.addEventListener("click", openKnow);
document.addEventListener("click", async e => {  // [data-copy="<id>"]: copy that element's text
  const b = e.target.closest("[data-copy]");
  const el = b && document.getElementById(b.dataset.copy);
  if (!el) return;  // most buttons carry the text itself and copy it in their own handler: leave the clipboard alone
  try { await navigator.clipboard.writeText(el ? el.textContent : ""); b.textContent = "Copied"; } catch (err) { b.textContent = "Select and copy"; }
  setTimeout(() => (b.textContent = "Copy"), 1600);
});
document.addEventListener("keydown", openKnow);


function wireOnboarding(root) {
  const saveBtn = $("#onboard-save", root);
  const skipBtn = $("#onboard-skip", root);
  const msgEl = $("#onboard-msg", root);
  if (!saveBtn) return;
  const count = () => { const n = $$("[data-feature]", root).filter(c => c.checked).length; $("#wl-count", root).textContent = `${n} selected`; };
  $$("[data-feature]", root).forEach(c => c.onchange = count); count();
  saveBtn.onclick = async () => {
    saveBtn.disabled = true; saveBtn.textContent = "Saving…";
    const selected = $$("[data-feature]", root).filter(c => c.checked).map(c => c.dataset.feature);
    const r = await save("onboarding_save", { features: selected });
    if (r.ok) {
      state.pages = r.pages || NAV.map(p => p[0]);
      renderNav("studio");
      state.pendingTour = "page-sessions";
      location.hash = "#studio";
    } else {
      saveBtn.disabled = false; saveBtn.textContent = "Start with these";
      if (msgEl) saidMsg(msgEl, r);
    }
  };
  skipBtn.onclick = async () => {
    skipBtn.disabled = true;
    const r = await save("onboarding_save", { skip: true });
    if (r.ok) {
      state.pages = NAV.map(p => p[0]);
      renderNav("studio");
      state.pendingTour = "page-sessions";
      location.hash = "#studio";
    } else {
      skipBtn.disabled = false;
      if (msgEl) saidMsg(msgEl, r);
    }
  };
}

function wire(root) {
  $$("[data-scope]", root).forEach(a => a.onclick = e => {
    e.preventDefault();
    localStorage.setItem("lfg.allrepos." + a.dataset.scope, allRepos(a.dataset.scope) ? "" : "1");
    route();
  });
  $$("[data-run-file]", root).forEach(a => a.onclick = async e => {
    e.preventDefault();
    const [run, f] = JSON.parse(a.dataset.runFile);
    const d = await api("file", { run, f });
    openDrawer(a.dataset.title || a.textContent, renderFile(f, d.text));
  });
  $$("[data-rule-module]", root).forEach(a => a.onclick = e => {
    e.preventDefault();
    const m = (state.rules.modules || []).find(x => x.name === a.dataset.ruleModule);
    if (m) openDrawer(words(m.name), renderFile(m.name + ".md", m.text));
  });
  wireSettings(root);
  wireMap(root);
  wireStacks(root);
  $$("[data-run-checks]", root).forEach(b => b.onclick = async () => {
    b.disabled = true; b.textContent = "Starting…";
    const r = await save("run_checks", { repo: state.repo, run: b.dataset.runChecks });
    if (!r.ok) { b.disabled = false; b.textContent = "Run checks again"; alert(String(r.why || "Couldn't start the checks.").replace(/`/g, "")); return; }
    state.cache = {}; route();
  });
  $$("[data-run-needed]", root).forEach(b => b.onclick = async () => {
    b.disabled = true;
    const r = await save("run_needed", { repo: state.repo, run: b.dataset.run, needed: b.dataset.runNeeded === "1" });
    if (!r.ok) { b.disabled = false; return alert(String(r.why || "Not saved.")); }
    state.cache = {}; route();
  });
  // timers redraw in place (softRoute), never from the top: a full route() would scroll you up and close what you opened
  if ($("[data-checks-running]", root)) pageTimer("checks", 10000, () => { if (document.body.contains(root) && $("[data-checks-running]", root)) { state.cache = {}; softRoute(); } });
  if ($("[data-spend-pending]", root)) pageTimer("spend", 4000, () => { if (document.body.contains(root) && $("[data-spend-pending]", root)) softRoute(); });
}

// ------------------------------------------------------------------ rules: hover any mention to see what it means
const RULE_RX = /\b(?:[Rr]ule (\d{1,2})\b|lfg rule ([a-z][a-z-]+))/g;
function ruleTip(num, mod) {
  const R = state.rules;
  if (!R) return "";
  if (num) {
    const r = R.rules.find(x => x.id === num);
    return r ? `Rule ${r.id}: ${r.title}\n${r.summary}` : "";
  }
  const m = R.modules.find(x => x.name === mod);
  return m ? `${words(m.name)}\n${m.summary}` : "";
}
function decorateRules(root) {
  if (!state.rules || !root || root.nodeType !== 1 || root.closest(".rule-ref, textarea, script, style, option")) return;
  const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: t => (t.parentElement.closest(".rule-ref, textarea, script, style, option, select") ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
  });
  const hits = [];
  for (let t = walk.nextNode(); t; t = walk.nextNode()) { RULE_RX.lastIndex = 0; if (RULE_RX.test(t.data)) hits.push(t); }
  for (const t of hits) {
    const frag = document.createDocumentFragment();
    let last = 0;
    RULE_RX.lastIndex = 0;
    for (const m of t.data.matchAll(RULE_RX)) {
      const tip = ruleTip(m[1], m[2]);
      if (!tip) continue;
      frag.append(t.data.slice(last, m.index));
      const span = document.createElement("span");
      span.className = "rule-ref"; span.dataset.tip = tip; span.textContent = m[0];
      frag.append(span);
      last = m.index + m[0].length;
    }
    if (!last) continue;
    frag.append(t.data.slice(last));
    t.replaceWith(frag);
  }
}
/* A status dot in running text needs a space after it; in a flex or grid row the row's gap already spaces it. */
function spaceDots(node) {
  if (!node || node.nodeType !== 1) return;
  [...(node.matches(".dot") ? [node] : []), ...node.querySelectorAll(".dot")].forEach(d => {
    const parent = d.parentElement;
    d.classList.toggle("in-text", !!parent && !/flex|grid/.test(getComputedStyle(parent).display));
  });
}
function mountRuleTips() {
  new MutationObserver(ms => ms.forEach(m => m.addedNodes.forEach(n => { decorateRules(n); spaceDots(n); }))).observe(document.body, { childList: true, subtree: true });
  decorateRules(document.body);
  spaceDots(document.body);
  const tip = document.createElement("div");
  tip.id = "tip"; tip.hidden = true; document.body.append(tip);
  document.addEventListener("mouseover", e => {
    const el = e.target.closest && e.target.closest("[data-tip]");
    if (!el) { tip.hidden = true; return; }
    tip.textContent = el.dataset.tip; tip.hidden = false;
    const r = el.getBoundingClientRect(), w = Math.min(360, window.innerWidth - 16);
    tip.style.maxWidth = w + "px";
    tip.style.left = Math.max(8, Math.min(r.left, window.innerWidth - w - 8)) + "px";
    const below = r.bottom + 6, h = tip.offsetHeight;
    tip.style.top = (below + h > window.innerHeight ? r.top - h - 6 : below) + "px";
  });
  window.addEventListener("scroll", () => (tip.hidden = true), true);
}

// ------------------------------------------------------------------ settings (the only writes)
// the page the dashboard serves carries its edit key; an old one in this browser is only a fallback
const editKey = () => (document.querySelector('meta[name="lfg-key"]') || {}).content || localStorage.getItem("lfg.editKey") || "";
async function isUnlocked() {
  if (!editKey()) return false;
  try {
    const r = await fetch("/api/unlocked", { headers: { "X-LFG": "1", "X-LFG-Key": editKey() } });
    return r.ok && (await r.json()).ok;
  } catch (e) { return false; }
}
// The edit key is kept per address (host and port): a tab on another port, or on localhost instead of 127.0.0.1, or a
// dashboard started with --no-open, has none. --unlock opens this port's dashboard with it.
// --unlock opens your default browser; another browser needs its name, so the note names the one you're in.
const thisBrowser = () => { const u = navigator.userAgent; return /Edg\//.test(u) ? "Microsoft Edge" : /Arc\//.test(u) ? "Arc" : /Brave/.test(u) ? "Brave Browser" : /Chrome\//.test(u) ? "Google Chrome" : /Firefox\//.test(u) ? "Firefox" : /Safari\//.test(u) ? "Safari" : ""; };
const unlockCmd = () => `lfg ui --unlock --port ${location.port || "80"}${thisBrowser() ? ` --browser "${thisBrowser()}"` : ""}`;
const lockedNote = what => `<div class="callout">Read-only in this tab. To ${what}, run <code>lfg ui --unlock --port ${esc(location.port || "80")}${thisBrowser() ? ` --browser "${esc(thisBrowser())}"` : ""}</code> in your terminal; it opens this dashboard again, unlocked, in this browser.</div>`;
async function save(what, body) {
  try {
    const r = await fetch(`/api/save/${what}`, { method: "POST", body: JSON.stringify(body),
      headers: { "X-LFG": "1", "X-LFG-Key": editKey(), "Content-Type": "application/json" } });
    return await r.json();
  } catch (e) { return { ok: false, why: e.message }; }
}
function saidMsg(el, d, okText) {
  el.className = "save-msg " + (d.ok ? "ok" : "bad");
  el.innerHTML = d.ok ? esc(okText || "Saved.") + [].concat(d.notes || [], d.note || []).map(x => " " + fmtWhy(x)).join("") : fmtWhy(d.why || "Not saved.");
}
function fieldInput(f, locked) {
  const id = `cfg-${f.key}`, dis = locked ? "disabled" : "", v = f.value;
  if (f.type === "bool") return `<span class="tgl-wrap"><input type="checkbox" id="${id}" data-cfg="${esc(f.key)}" ${v ? "checked" : ""} ${dis} role="switch"><span class="tgl"></span></span>`;
  if (f.type === "choice") return `<select id="${id}" data-cfg="${esc(f.key)}" ${dis}>${f.options.map(o => `<option ${o === v ? "selected" : ""}>${esc(o)}</option>`).join("")}</select>`;
  if (f.type === "int") return `<input type="number" id="${id}" data-cfg="${esc(f.key)}" min="${f.min}" max="${f.max}" value="${esc(v)}" ${dis}>`;
  const val = Array.isArray(v) ? v.join(", ") : v ?? "";
  return `<input type="text" id="${id}" data-cfg="${esc(f.key)}" value="${esc(val)}" ${dis}>`;
}
/* General settings, grouped by what they're for; the model choices get their own card */
const SET_GROUPS = [
  ["How LFG works", "What Claude may do, how big a change can be for each lane, and the line LFG adds to replies.", k => /^(guard|lanes|replies|graphs)\./.test(k)],
  ["Agent models", "Which Claude model each of LFG's agents uses.", k => k.startsWith("models.")],
  ["Dashboard and disk space", "", k => /^(ui|storage)\./.test(k)],
  ["Updates", "What the Update button brings in.", k => k.startsWith("updates.")],
];
const settingRow = (f, unlocked) => `<label class="set-row" for="cfg-${esc(f.key)}"><div><div class="set-label">${esc(f.label.replace(/^Model:\s*/, "").replace(/-/g, " ").replace(/^./, c => c.toUpperCase()))}</div>${f.help ? `<div class="set-help">${esc(f.help)}</div>` : ""}</div><div class="set-input">${fieldInput(f, !unlocked)}</div></label>`;
function settingsGroups(cfg, unlocked) {
  const fields = cfg.fields.filter(f => !f.owner), used = new Set();
  const row = f => settingRow(f, unlocked);
  const card = (title, note, list) => list.length ? `<div class="set-section"><h4>${esc(title)}</h4>${note ? `<p class="muted">${esc(note)}</p>` : ""}${list.map(row).join("")}</div>` : "";
  let out = SET_GROUPS.map(([t, n, test]) => { const list = fields.filter(f => test(f.key)); list.forEach(f => used.add(f.key)); return card(t, n, list); }).join("");
  out += card("Other", "", fields.filter(f => !used.has(f.key)));
  return out;
}
const AP_THEMES = {
  light: [["lfg", "LFG", "Soft white, cool ink", ["#f6f8fc", "#ffffff", "#0e1729", "#2563eb", "#f1f4fa"]],
    ["paper", "Paper", "Warm neutral, easy on the eyes", ["#fbfaf7", "#ffffff", "#2b2a26", "#2563eb", "#f6f4ef"]],
    ["mist", "Mist", "Cool grey, crisp contrast", ["#f4f5f7", "#ffffff", "#111318", "#2563eb", "#eceef2"]]],
  dark: [["midnight", "Midnight", "Deep navy with an accent glow", ["#070b14", "#0d1424", "#e6ebf5", "#3b82f6", "#0a101e"]],
    ["graphite", "Graphite", "Neutral grey, no tint", ["#111214", "#18191c", "#ececee", "#3b82f6", "#141518"]],
    ["carbon", "Carbon", "True black for OLED screens", ["#000000", "#0a0a0b", "#f2f2f3", "#3b82f6", "#050506"]]],
};
const AP_ACCENTS = [["orange", "#ea580c"], ["blue", "#2563eb"], ["violet", "#7c3aed"], ["green", "#059669"], ["rose", "#e11d48"]];
function settingsAppearance() {
  const a = apRead();
  const seg = (k, opts) => `<div class="seg">${opts.map(([v, t]) => `<button class="pill${a[k] === v ? " on" : ""}" data-ap="${k}" data-v="${v}">${t}</button>`).join("")}</div>`;
  const card = (kind, [id, name, about, [pg, sf, tx, , sd]]) => `<button class="ap-theme${a[kind] === id ? " on" : ""}" data-ap="${kind}" data-v="${id}" style="--p:${pg}">
    <span class="ap-prev" style="background:${pg}"><i class="s" style="background:${sd}"></i><span class="c" style="background:${sf};box-shadow:0 0 0 1px ${tx}1a"><b style="background:${tx}"></b><b style="background:${tx}55"></b><b class="a" style="background:var(--blue)"></b></span></span>
    <span class="ap-name">${esc(name)}<span class="muted">${esc(about)}</span></span></button>`;
  const row = (label, help, ctl) => `<div class="set-row"><div><div class="set-label">${label}</div>${help ? `<div class="set-help">${help}</div>` : ""}</div><div class="set-input">${ctl}</div></div>`;
  return `<div class="set-section"><h4>Mode</h4>${row("Light or dark", "System follows your computer's setting.", seg("mode", [["system", "System"], ["light", "Light"], ["dark", "Dark"]]))}</div>
    <div class="set-section"><h4>Light theme</h4><div class="ap-grid">${AP_THEMES.light.map(t => card("light", t)).join("")}</div><p class="muted small">Used in light mode.</p></div>
    <div class="set-section"><h4>Dark theme</h4><div class="ap-grid">${AP_THEMES.dark.map(t => card("dark", t)).join("")}</div><p class="muted small">Used in dark mode.</p></div>
    <div class="set-section"><h4>Look and feel</h4>
      ${row("Accent colour", "Buttons, links, selection and focus.", `<div class="ap-acc">${AP_ACCENTS.map(([v, c]) => `<button class="${a.accent === v ? "on" : ""}" data-ap="accent" data-v="${v}" style="background:${c}" title="${v}" aria-label="${v}"></button>`).join("")}</div>`)}
      ${row("Density", "Compact fits more rows on screen.", seg("density", [["comfortable", "Comfortable"], ["compact", "Compact"]]))}
      ${row("Text size", "", seg("text", [["s", "Small"], ["m", "Default"], ["l", "Large"]]))}
      ${row("Background glow", "The faint coloured light behind the page.", seg("glow", [["on", "On"], ["off", "Off"]]))}
      ${row("Motion", "Animations and transitions.", seg("motion", [["on", "On"], ["off", "Reduced"]]))}
    </div>
    <div class="set-actions"><button class="btn" data-ap-reset>Reset to default</button><span class="muted small">Saved in this browser.</span></div>`;
}
document.addEventListener("click", e => {
  const b = e.target.closest("[data-ap]");
  if (b) { apSet(b.dataset.ap, b.dataset.v); $$(`[data-ap="${b.dataset.ap}"]`).forEach(x => x.classList.toggle("on", x === b)); return; }
  if (e.target.closest("[data-ap-reset]")) { try { localStorage.removeItem("lfg.appearance"); } catch (err) { /* ignore */ } apApply(); apFavicon(); route({ soft: true }); }
});
function settingsGeneral() {
  const { cfg, unlocked } = state.settings;
  return `<div>${notifyRow()}</div><div class="set-section"><h4>Features</h4><p class="muted">Pick what you use; the sidebar shows only those pages. Changes apply right away.</p>
      <div id="features-section"><div class="loading">Loading features…</div></div>
      <label class="row mt"><input type="checkbox" id="show-all-pages" ${state.settings?.showAll ? "checked" : ""} ${!unlocked ? "disabled" : ""}> Show every page in the sidebar anyway</label>
      <p class="muted small" style="margin-top:8px"><a href="#onboarding">Run the welcome again</a></p>
    </div>
    ${settingsGroups(cfg, unlocked)}
    <div class="set-actions"><button class="btn primary" id="cfg-save" ${unlocked ? "" : "disabled"}>Save</button><span class="save-msg" id="cfg-msg"></span></div>`;
}
function settingsSkills() {
  const { sk } = state.settings;
  return `<div class="skill-edit"><nav>${sk.skills.map(x => `<a href="#" data-skill="${esc(x.name)}" title="${esc(x.description)}">/lfg:${esc(x.name)}${x.edited ? '<span class="tag">edited</span>' : ""}</a>`).join("")}</nav>
    <div class="grow"><div id="skill-editor">${empty("Pick a skill to read or change it", "Your changes survive updates and apply to new Claude Code sessions.")}</div></div></div>`;
}
function settingsClaude() {
  const { cm, unlocked } = state.settings;
  return `<div class="row"><p class="muted grow">Your own instructions for every Claude Code session (<code>~/.claude/CLAUDE.md</code>). They always win over LFG, and LFG never writes to this file.${cm.has_lfg_section ? " It still has a block an older LFG added: Settings → Claude Code can remove it." : ""}</p>${unlocked ? '<button class="btn" id="cm-edit">Change</button>' : ""}</div>
    <div id="cm-read" class="box pad md">${md(cm.text)}</div>
    <div id="cm-write" hidden><p class="muted small">Written in Markdown.</p><textarea class="editor" id="cm-text" spellcheck="false">${esc(cm.text)}</textarea>
    <div class="set-actions"><button class="btn primary" id="cm-save">Save</button><button class="btn" id="cm-cancel">Cancel</button><span class="save-msg" id="cm-msg"></span></div></div>`;
}
function settingsRules() {
  const R = state.rules || { rules: [], modules: [] }, un = state.settings.unlocked;
  const rows = R.rules.map(r => `<li><span class="muted nowrap">${esc(r.id)}.</span><div class="grow"><div class="title">${esc(r.title)}</div><div class="meta">${esc(r.summary)}</div></div></li>`).join("");
  const tag = m => m.yours ? '<span class="tag">yours</span>' : m.edited ? '<span class="tag">edited</span>' : "";
  return `<div class="set-section" style="margin-top:0"><h4>Guidance agents read</h4>
    <p class="muted">Agents load these with <code>lfg rule &lt;name&gt;</code>. ${un ? "Change any of them in Markdown, or add your own: every new Claude Code session is told to follow rules you add." : "Unlock editing to change them or add your own."}</p>
    <div class="skill-edit"><nav>${R.modules.map(m => `<a href="#" data-rule="${esc(m.name)}" title="${esc(m.summary)}">${esc(words(m.name))}${tag(m)}</a>`).join("")}${un ? '<a href="#" data-rule-new class="add">+ Add a rule</a>' : ""}</nav>
    <div class="grow"><div id="rule-editor">${empty("Pick a rule to read or change it", "Your changes survive updates. A copy is kept every time you save.")}</div></div></div></div>
    <div class="set-section"><h4>Safety rules</h4><p class="muted">What every LFG session must follow. LFG enforces these in code. To lift a block so Claude does it only when you ask, use <a href="#prefs">Preferences → Safety rules</a>.</p>
    <div class="box"><ul class="list">${rows}</ul></div></div>`;
}
async function reloadRules(pick) {
  state.rules = await api("rules");
  const body = $("#settings-body");
  if (body) { body.innerHTML = settingsRules(); wire(body); }
  if (pick) { $$("[data-rule]").forEach(x => x.classList.toggle("on", x.dataset.rule === pick)); showRule(pick); }
}
function wireRules(root) {
  $$("[data-rule]", root).forEach(a => a.onclick = e => {
    e.preventDefault();
    $$("[data-rule], [data-rule-new]", root).forEach(x => x.classList.toggle("on", x === a));
    showRule(a.dataset.rule);
  });
  const nw = $("[data-rule-new]", root);
  if (nw) nw.onclick = e => {
    e.preventDefault();
    $$("[data-rule], [data-rule-new]", root).forEach(x => x.classList.toggle("on", x === nw));
    newRule();
  };
}
function newRule() {
  const box = $("#rule-editor");
  box.innerHTML = `<p><b>Add a rule</b></p><p class="muted small">Give it a short name (lowercase, dashes) and write it in Markdown. Agents read it with <code>lfg rule &lt;name&gt;</code>. New sessions are told to follow it, and sessions already open are told with your next message to them.</p>
    <label class="set-label" for="rule-name">Name</label><input type="text" id="rule-name" placeholder="api-style" maxlength="41" style="width:100%;margin:4px 0 12px">
    <textarea class="editor" id="rule-text" spellcheck="false"># api-style: one line saying what this rule is about

- What to always do
- What never to do, and why
</textarea>
    <div class="set-actions"><button class="btn primary" id="rule-save">Add</button><span class="save-msg" id="rule-msg"></span></div>`;
  $("#rule-save").onclick = async () => {
    const name = $("#rule-name").value.trim().toLowerCase();
    if ((state.rules?.modules || []).some(m => m.name === name) && !confirm(`A rule called "${name}" already exists. Replace its text with this?`)) return;
    const r = await save("rule", { name, text: $("#rule-text").value });
    saidMsg($("#rule-msg"), r);
    if (r.ok) reloadRules(r.saved);
  };
}
function showRule(name) {
  const box = $("#rule-editor"), un = state.settings.unlocked;
  const m = (state.rules?.modules || []).find(x => x.name === name);
  if (!m) { box.innerHTML = empty("Rule not found", ""); return; }
  const undo = m.yours ? '<button class="btn danger" id="rule-reset">Delete this rule</button>' : m.edited ? '<button class="btn" id="rule-reset">Undo my changes</button>' : "";
  box.innerHTML = `<div class="row" style="margin-bottom:8px"><b>${esc(words(name))}</b>${m.yours ? '<span class="tag">added by you</span>' : m.edited ? '<span class="tag">edited by you</span>' : ""}<span class="grow"></span>${un ? '<button class="btn" id="rule-edit">Change</button>' : ""}</div>
    <div id="rule-read"><p class="muted small">Agents read this with <code>lfg rule ${esc(name)}</code>.</p><div class="md">${md(m.text)}</div></div>
    <div id="rule-write" hidden><p class="muted small">Written in Markdown.</p>
    <textarea class="editor" id="rule-text" spellcheck="false">${esc(m.text)}</textarea>
    <div class="set-actions"><button class="btn primary" id="rule-save">Save</button><button class="btn" id="rule-cancel">Cancel</button>${undo}<span class="save-msg" id="rule-msg"></span></div></div>`;
  const mode = edit => { $("#rule-read").hidden = edit; $("#rule-write").hidden = !edit; if ($("#rule-edit")) $("#rule-edit").hidden = edit; };
  if ($("#rule-edit")) $("#rule-edit").onclick = () => mode(true);
  $("#rule-cancel").onclick = () => showRule(name);
  $("#rule-save").onclick = async () => {
    const r = await save("rule", { name, text: $("#rule-text").value });
    saidMsg($("#rule-msg"), r);
    if (r.ok) reloadRules(name);
  };
  const rs = $("#rule-reset");
  if (rs) rs.onclick = async () => {
    if (!confirm(m.yours ? `Delete the rule "${name}"? A copy is kept in LFG's backups.` : `Put "${name}" back to how LFG ships it? A copy of your version is kept.`)) return;
    const r = await save("rule_reset", { name });
    if (!r.ok) return saidMsg($("#rule-msg"), r);
    reloadRules(r.deleted ? null : name);
    if (r.deleted) $("#rule-editor").innerHTML = empty("Rule deleted", "A copy is kept in LFG's backups.");
  };
}
// ------------------------------------------------------------------ settings → Claude Code (LFG's footprint, all undoable)
/* Dictate's own options, right on its pack row */
function dictateControls(o, dis) {
  if (o.preview) dis = "disabled";
  return `<div class="dictate-opts${o.preview ? " preview" : ""}">${o.preview ? '<div class="preview-note">These controls work once Dictate is on.</div>' : ""}
    <label>Shortcut <select data-dict="dictate.shortcut" ${dis}>${o.shortcuts.map(([k, l]) => `<option value="${esc(k)}" ${k === o.shortcut ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></label>
    <label>Put text in by <select data-dict="dictate.insert" ${dis}><option value="paste" ${o.insert === "paste" ? "selected" : ""}>Pasting</option><option value="type" ${o.insert === "type" ? "selected" : ""}>Typing</option></select></label>
    <label class="row"><input type="checkbox" data-dict="dictate.cleanup" ${o.cleanup ? "checked" : ""} ${dis}><span>Clean up with Claude <span class="meta">· removes filler words; sends the text (never audio) to Claude</span></span></label>
    <a href="#" class="small" data-tour-start="${o.preview ? "dictate-intro" : "dictate"}">Take the tour</a>
  </div>`;
}
function settingsClaudeCode() {
  return '<div id="cc-box" data-fill><div class="loading">Looking at your Claude Code setup…</div></div>';
}
let ccTimer = null;
const where = r => r.root.replace(/^\/Users\/[^/]+/, "~");
async function loadClaudeCode() {
  const box = $("#cc-box");
  if (!box) return;
  const d = await api("claude"), un = state.settings.unlocked, dis = un ? "" : "disabled";
  const R = d.repos, hr = d.headroom, sc = d.scan;
  const repoRows = R.repos.filter(r => r.exists).map(r => `<li>${dot(r.enabled ? "ok" : "")}<div class="grow"><div class="title">${esc(r.name)}</div><div class="meta">${esc(where(r))}${r.hardened ? " · hardened" : ""}${r.headroom ? " · Headroom" : ""}</div></div>
    ${R.everywhere ? '<span class="muted small">on everywhere</span>' : `<button class="btn small" data-cc="${r.enabled ? "repo_off" : "repo_on"}" data-root="${esc(r.root)}" ${dis}>${r.enabled ? "Turn off" : "Turn on"}</button>`}</li>`).join("");
  const job = name => {
    const j = d.jobs[name];
    return j ? `<div class="meta">${j.status === "running" ? "Installing…" : j.status === "done" ? "Installed." : "Install failed."}</div>${j.log.length ? `<pre class="joblog">${esc(j.log.slice(-12).join("\n"))}</pre>` : ""}` : "";
  };
  const packRows = d.packs.map(p => `<li data-pack="${esc(p.name)}">${dot(p.on ? (p.missing.length ? "warn" : "ok") : "")}<div class="grow"><div class="title">${esc(p.title.replace(" (experimental)", ""))}${p.experimental ? ' <span class="tag">Experimental</span>' : ""}</div><div class="meta">${esc(p.about)}${p.detail ? `<br>${fmtWhy(p.detail)}` : ""}${p.settings ? dictateControls(p.settings, dis) : ""}${p.on && p.missing.length ? ` · missing: ${esc(p.missing.map(m => m.split(":")[1]).join(", "))}` : ""}</div>${job(p.name)}</div>
    ${p.name === "core" ? '<span class="muted small">always on</span>' : p.on && !p.missing.length ? `<button class="btn small" data-cc="pack_remove" data-name="${esc(p.name)}" ${dis}>Turn off</button>` : `<button class="btn small" data-cc="pack_add" data-name="${esc(p.name)}" ${dis || ((d.jobs[p.name] || {}).status === "running" ? "disabled" : "")}>${p.on ? "Install missing" : "Add"}</button>`}</li>`).join("");
  const hrOpts = [["off", "Off"], ["repos", "Only repos where LFG is on"], ["everywhere", "Every Claude Code session"]];
  const hrBlocked = hr.cloud_provider ? `Not available: Claude Code uses ${esc(hr.cloud_provider)} here.` : !hr.installed ? "Add the Headroom pack first." : "";
  const changes = d.changes.length ? `<div class="box"><ul class="list">${d.changes.slice().reverse().map(c => `<li><span class="muted nowrap">#${c.id}</span><div class="grow"><div class="title">${fmtWhy(c.text)}</div><div class="meta">${esc(c.why)} · ${ago(c.ts)}</div></div><button class="btn small" data-cc="change_undo" data-id="${c.id}" ${dis}>Undo</button></li>`).join("")}</ul></div>`
    : `<div class="box calm">${dot("ok")}LFG has changed nothing outside ~/.lfg.</div>`;
  const legacy = d.legacy.length ? `<div class="set-section"><h4>Left over from an older LFG</h4><p class="muted">Older versions changed Claude Code for every session. Each fix below removes exactly what LFG added.</p>
    <div class="box"><ul class="list">${d.legacy.map(l => `<li>${dot("warn")}<div class="grow"><div class="title">${esc(l.title)}</div><div class="meta">${esc(l.fix)}</div></div>${l.default ? `<button class="btn small" data-cc="legacy_fix" data-id="${esc(l.id)}" ${dis}>Fix</button>` : ""}</li>`).join("")}</ul></div></div>` : "";
  morph(box, `<p class="muted">What LFG does to Claude Code, and where. Everything here is recorded and can be undone; nothing outside the repos you pick is touched.</p>
    <span class="save-msg" id="cc-msg"></span>${legacy}
    <div class="set-section" id="cc-where"><h4>Where LFG is on</h4><p class="muted">In other repos Claude Code works exactly as if LFG weren't installed: no skills, hooks or MCP servers.</p>
      <label class="row"><input type="checkbox" data-cc="everywhere" ${R.everywhere ? "checked" : ""} ${dis}> Turn LFG on in every repo <span class="muted small">(not recommended)</span></label>
      <div class="box mt">${repoRows ? `<ul class="list">${repoRows}</ul>` : empty("No repos yet", "Run <code>lfg enable</code> in a repo, or open one in Claude Code after enabling it.")}</div></div>
    <div class="set-section"><h4>Integrations</h4><p class="muted">Feature packs (Headroom, SonarQube, Dictate, pentest with Ollama and Strix, and the rest) and their settings are on the <a href="#integrations">Integrations</a> page.</p></div>
    <div class="set-section"><h4>Safety</h4>
      <div class="box pad"><div class="row">${dot("ok")}<div class="grow"><b>Guard</b><div class="meta">On in every LFG repo: blocks commits, pushes, secret reads and the rest of the 18 rules (Settings → Rules). Recently blocked: ${d.blocked.length ? d.blocked.slice(0, 3).map(b => `rule ${esc(b.rule)} (${esc(b.tool)})`).join(", ") : "nothing"}.</div></div></div>
      <label class="row mt" id="cc-hardened"><input type="checkbox" data-cc="hardened" ${d.hardened ? "checked" : ""} ${dis}><span><b>Hardened mode</b><span class="meta"> · also add Claude Code deny rules (git commit/push, secret files…) to each LFG repo's <code>.claude/settings.local.json</code>, never to your user settings</span></span></label></div></div>
    <div class="set-section"><h4>MCP servers LFG brings</h4><p class="muted">Only in LFG repos. One that isn't set up stays quiet and offers no tools.</p>
      <div class="box"><ul class="list">${d.mcp.map(m => `<li>${dot(m.ready ? "ok" : "")}<div class="grow"><div class="title">${esc(m.name)}</div><div class="meta">${m.ready ? "ready" : fmtWhy(m.why)}</div></div></li>`).join("")}</ul></div></div>
    <div class="set-section"><h4>Your Claude Code setup <span class="muted small">(read-only; LFG leaves these alone)</span></h4>
      <div class="box"><ul class="list">
        <li><div class="grow"><div class="title">Claude Code ${esc(sc.claude.version || "not found")}</div><div class="meta">${sc.managed_settings ? "Managed by your organisation's policy: " + esc(sc.managed_settings) : "No organisation policy"}${sc.base_url_host ? " · API endpoint " + esc(sc.base_url_host) : ""}</div></div></li>
        <li><div class="grow"><div class="title">Your hooks</div><div class="meta">${sc.user_hooks.length ? esc(sc.user_hooks.join(", ")) : "none"}</div></div></li>
        <li><div class="grow"><div class="title">Your MCP servers (every session)</div><div class="meta">${sc.user_mcp_servers.length ? esc(sc.user_mcp_servers.join(", ")) : "none"}</div></div></li>
        <li><div class="grow"><div class="title">Skills that share a name with LFG's</div><div class="meta">${sc.skill_collisions.length ? sc.skill_collisions.map(x => `<code>/${esc(x)}</code> is yours, LFG's is <code>/lfg:${esc(x)}</code>`).join(" · ") : "none"}</div></div></li>
      </ul></div></div>
    <div class="set-section"><h4>Changes LFG made outside ~/.lfg</h4>${changes}
      <p class="muted small mt">To remove LFG completely, run <code>lfg uninstall</code> in your terminal. It lists everything it will undo before it does anything.</p></div>`);
  $$("[data-dict]", box).forEach(el => el.onchange = async () => {
    el.disabled = true;
    state.ccMsg = await save("config", { values: { [el.dataset.dict]: el.type === "checkbox" ? el.checked : el.value } });
    loadClaudeCode();
  });
  $$("[data-cc]", box).forEach(el => {
    const act = el.dataset.cc, ev = el.type === "checkbox" ? "onchange" : "onclick";
    el[ev] = async () => {
      const body = act === "everywhere" || act === "hardened" ? { on: el.checked } : act === "headroom" ? { scope: $("#cc-hr").value }
        : { root: el.dataset.root, name: el.dataset.name, id: el.dataset.id };
      if (act === "repo_off" && !confirm(`Turn LFG off in ${el.dataset.root}? Its graphs and runs are kept.`)) return;
      if (act === "everywhere" && el.checked && !confirm("Turn LFG on in every repo, including ones you never set up? Each repo can't opt out while this is on.")) { el.checked = false; return; }
      el.disabled = true;
      state.ccMsg = await save(act, body);
      loadClaudeCode();
    };
  });
  if (state.ccMsg) { saidMsg($("#cc-msg", box), state.ccMsg, state.ccMsg.ok ? "Done." : ""); state.ccMsg = null; }
  $$("[data-tour-start]", box).forEach(l => l.onclick = e => { e.preventDefault(); startTour(l.dataset.tourStart); });
  if (state.pendingTour && $('[data-pack="dictate"]', box)) { const t = state.pendingTour; state.pendingTour = null; setTimeout(() => startTour(t), 250); }
  clearTimeout(ccTimer);
  if (Object.values(d.jobs).some(j => j.status === "running")) ccTimer = setTimeout(() => { if (document.body.contains(box)) loadClaudeCode(); }, 2000);
}

// ------------------------------------------------------------------ integrations: every tool LFG works with, on one page
async function integrationsPage() {
  const [cfg, unlocked] = await Promise.all([api("settings"), isUnlocked()]);
  state.settings = Object.assign(state.settings || {}, { cfg, unlocked });
  return `${head("Integrations", "The tools LFG works with. Turn one on and its settings appear on its card; everything installs locally and can be turned off again.")}
    ${unlocked ? "" : lockedNote("change anything")}
    <span class="save-msg" id="int-msg"></span><div id="int-box" data-fill><div class="loading">Checking each integration…</div></div>
    ${section("Claude Code plugins", `<p class="muted">Plugins add skills, agents and tools to every Claude Code session, from the marketplaces Claude Code knows. Install one here and turn it on or off without removing it; each change is listed under Settings → Claude Code, where it can be undone.</p><div id="plg-box" data-fill><div class="loading">Asking Claude Code for its plugins…</div></div>`)}`;
}
/* Integrations → Claude Code plugins: what's installed (on/off, remove), suggestions, and a search of the marketplaces.
   Drawn on its own, not with the integrations above (those redraw every 2 seconds while one installs). */
async function loadPlugins(fresh) {
  const box = $("#plg-box");
  if (!box) return;
  const q = state.plgQ || "", dis = (state.settings || {}).unlocked ? "" : "disabled";
  const d = await api("plugins", { q, fresh: fresh ? "1" : "" });
  if (!$("#plg-box")) return;
  if (d.available === false) { box.innerHTML = unavailable(d, "Couldn't list Claude Code's plugins"); return; }
  const busy = state.plgBusy || {};
  const btn = (act, id, label, cls = "btn small") => `<button class="${cls}" data-plg="${esc(act)}" data-id="${esc(id)}" ${dis || (busy[id] ? "disabled" : "")}>${busy[id] === act ? (act === "install" ? "Installing…" : "Working…") : label}</button>`;
  const inst = x => `<li class="plg"><div class="grow"><div class="title">${esc(x.name)} <span class="muted small">${esc(x.marketplace)}${x.version ? " · " + esc(x.version) : ""}</span>${x.suggested ? ' <span class="tag">suggested</span>' : ""}</div>
      ${x.about ? `<div class="meta">${esc(x.about)}</div>` : ""}${x.yours ? "" : x.scope === "synced" ? `<div class="meta">From your claude.ai account or organisation: change it there.</div>` : `<div class="meta">Installed for ${x.project ? esc(x.project.split("/").pop()) + " only" : "one repo"}: change it in that repo's Claude Code.</div>`}</div>
      ${x.yours ? `<button class="tgl${x.enabled ? " on" : ""}" role="switch" aria-checked="${x.enabled}" aria-label="${x.enabled ? "Turn off" : "Turn on"} ${esc(x.name)}" data-plg-on="${esc(x.id)}" ${dis || (busy[x.id] ? "disabled" : "")}></button>${btn("uninstall", x.id, "Remove", "btn small ghost")}` : `<span class="muted small nowrap">${x.enabled ? "On" : "Off"}</span>`}</li>`;
  const sugg = x => `<li class="plg"><div class="grow"><div class="title">${esc(x.name)} <span class="tag">suggested</span></div><div class="meta">${esc(x.why)}</div></div>${x.available ? btn("install", x.id, "Install", "btn small primary") : '<span class="muted small">Not in your marketplaces</span>'}</li>`;
  const hit = x => `<li class="plg"><div class="grow"><div class="title">${esc(x.name)} <span class="muted small">${esc(x.marketplace)}${x.installs ? ` · ${n(x.installs)} installs` : ""}</span></div><div class="meta">${esc(x.about)}</div></div>${btn("install", x.id, "Install")}</li>`;
  morph(box, `${d.installed.length ? `<div class="k">Installed</div><div class="box"><ul class="list">${d.installed.map(inst).join("")}</ul></div>` : '<p class="muted">No plugins installed besides LFG.</p>'}
    ${d.suggested.length ? `<div class="k mt">Suggested</div><div class="box"><ul class="list">${d.suggested.map(sugg).join("")}</ul></div>` : ""}
    <div class="k mt">Find a plugin</div><div class="row"><input type="search" id="plg-q" class="grow" placeholder="Search ${n(d.available_total)} plugins, e.g. review, terraform, playwright" value="${esc(q)}" autocomplete="off"><button class="btn small" id="plg-refresh" title="Ask Claude Code again">Refresh</button></div>
    ${d.searched ? (d.found.length ? `<div class="box mt"><ul class="list">${d.found.map(hit).join("")}</ul></div>${d.found_total > d.found.length ? `<p class="muted small">${d.found_total - d.found.length} more: add a word to narrow it down.</p>` : ""}` : `<p class="muted small mt">No plugin matches "${esc(d.searched)}".</p>`) : ""}
    <p class="muted small mt">Installing adds someone else's code to every session. Only you can do it, here or with <code>lfg plugins</code> in your terminal; Claude can't.</p><span class="save-msg" id="plg-msg"></span>`);
  const msg = $("#plg-msg", box), qi = $("#plg-q", box);
  let t = null;
  qi.oninput = () => { clearTimeout(t); t = setTimeout(() => { state.plgQ = qi.value; loadPlugins().then(() => { const el = $("#plg-q"); if (el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length); } }); }, 300); };
  $("#plg-refresh", box).onclick = () => loadPlugins(true);
  const act = async (what, id, body, okText) => {
    state.plgBusy = { ...(state.plgBusy || {}), [id]: what }; loadPlugins();
    const r = await save("plugin_" + what, body);
    delete state.plgBusy[id];
    await loadPlugins();
    const m = $("#plg-msg"); if (m) saidMsg(m, r, okText);
  };
  $$("[data-plg]", box).forEach(b => b.onclick = () => {
    const id = b.dataset.id, what = b.dataset.plg;
    if (what === "install" && !confirm(`Install ${id}? It adds its skills, agents and tools to every Claude Code session. New sessions pick it up.`)) return;
    if (what === "uninstall" && !confirm(`Remove ${id}? Turning it off keeps it installed; removing deletes it.`)) return;
    act(what, id, { id }, what === "install" ? `Installed ${id}. New sessions have it.` : `Removed ${id}.`);
  });
  $$("[data-plg-on]", box).forEach(b => b.onclick = () => { const id = b.dataset.plgOn, on = !b.classList.contains("on"); act("enable", id, { id, on }, `${id} is ${on ? "on" : "off"}. New sessions pick it up.`); });
}
let intTimer = null;
const INT_ICON = { core: "code", knowledge: "knowledge", headroom: "compress", sonarqube: "checks", dictate: "mic", pentest: "target", security: "lock", shipcheck: "box", linear: "issues", github: "branch" };
async function loadIntegrations() {
  const box = $("#int-box");
  if (!box) return;
  const d = await api("integrations"), un = state.settings.unlocked, dis = un ? "" : "disabled";
  const claude = await api("claude").catch(() => ({}));
  state.intOpen = state.intOpen || new Set();
  if (state.pendingTour) state.intOpen.add("dictate");
  const job = name => { const j = d.jobs[name]; return j ? `<div class="int-job"><span class="meta">${j.status === "running" ? "Installing…" : j.status === "done" ? "Installed" : "Install failed"}</span>${j.log.length ? `<pre class="joblog">${esc(j.log.slice(-8).join("\n"))}</pre>` : ""}</div>` : ""; };
  const sw = i => i.fixed || i.name === "core" ? '<span class="muted small nowrap">Always on</span>'
    : `<button class="tgl${i.on ? " on" : ""}" role="switch" aria-checked="${i.on}" aria-label="${i.on ? "Turn off" : "Turn on"} ${esc(i.title)}" data-int-switch="${esc(i.name)}" ${dis || ((d.jobs[i.name] || {}).status === "running" ? "disabled" : "")}></button>`;
  const field = f => `<label class="int-field"><span class="grow"><span class="set-label">${esc(f.label.replace(/^(Headroom|Ship check|SonarQube|Dictate|Pentest|Linear)\s*:?\s*/i, "").replace(/^./, c => c.toUpperCase()))}</span>${f.help ? `<span class="set-help">${esc(f.help)}</span>` : ""}</span>${f.type === "bool" ? `<span class="tgl-wrap"><input type="checkbox" data-cfg="${esc(f.key)}" aria-label="${esc(f.label)}" ${f.value ? "checked" : ""} ${dis}><span class="tgl" aria-hidden="true"></span></span>` : fieldInput(f, !un)}</label>`;
  const extra = i => {
    if (i.name === "headroom" && claude.headroom) {
      const hr = claude.headroom, opts = [["off", "Off"], ["repos", "LFG repos"], ["everywhere", "Every session"]];
      return `<label class="int-field"><span class="grow"><span class="set-label">Route Claude Code through it</span><span class="set-help">${hr.cloud_provider ? `Not available: Claude Code uses ${esc(hr.cloud_provider)} here.` : "New sessions pick it up."}</span></span><select id="int-hr" data-int-act="headroom" ${dis}>${opts.map(([v, l]) => `<option value="${v}" ${v === hr.scope ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></label>`;
    }
    if (i.name === "knowledge") return `<div class="int-acts"><button class="btn small" data-int-act="omnigraph_restart" ${dis}>Restart the servers</button></div>`;
    if (i.name === "sonarqube") return `<div class="int-acts">${/needs a restart/.test(i.status) ? `<button class="btn small primary" data-int-act="sonar_apply" ${dis}>Restart to apply</button>` : ""}<a class="btn small" href="http://127.0.0.1:9000" target="_blank" rel="noopener noreferrer">Open SonarQube ↗</a><span class="muted small">sign in as admin · <code>lfg sonar login</code></span></div>`;
    if (i.name === "dictate" && i.settings) return dictateControls(i.settings, dis);
    if (i.name === "pentest" && i.on) return '<div class="int-sub"><div class="set-label">Local AI models (Ollama)</div><div id="ollama-box" data-fill><div class="loading">Asking the local Ollama…</div></div></div>';
    return "";
  };
  const fieldsOf = i => i.name === "dictate" ? [] : i.name === "pentest" ? i.fields.filter(f => f.key !== "pentest.model") : i.fields;
  const hasPanel = i => !!((i.on || i.name === "dictate") && (fieldsOf(i).length || extra(i) || i.missing.length || d.jobs[i.name]));
  const status = i => i.on ? (i.status ? `<span class="int-st ${i.tone === "warn" || i.tone === "bad" ? i.tone : ""}">${fmtWhy(i.status)}</span>` : "")
    : `<span class="int-st">${esc((i.about || "").split(/(?<=\.)\s/)[0].replace(/\.$/, ""))}</span>`;
  const row = i => {
    const open = state.intOpen.has(i.name) && hasPanel(i);
    return `<div class="int-item${open ? " open" : ""}" data-pack="${esc(i.name)}"><div class="int-row"><button class="int-main" ${hasPanel(i) ? `data-int-open="${esc(i.name)}" aria-expanded="${open}"` : "tabindex=\"-1\""} title="${esc(i.about || "")}">${icon(INT_ICON[i.name] || "settings")}<span class="grow"><span class="int-nm">${esc(i.title.replace(/ \((experimental|local)\)/, ""))}${i.experimental ? ' <span class="tag">Experimental</span>' : ""}</span>${status(i)}</span>${hasPanel(i) ? icon(open ? "chevron-up" : "chevron-down", "ico chev") : ""}</button>${sw(i)}</div>
      ${open ? `<div class="int-panel">${i.missing.length && i.on ? `<div class="int-acts"><span class="int-st warn">Missing: ${esc(i.missing.map(m => m.split(":").pop()).join(", "))}</span><button class="btn small" data-cc="pack_add" data-name="${esc(i.name)}" ${dis}>Install missing</button></div>` : ""}${fieldsOf(i).map(field).join("")}${extra(i)}${job(i.name)}</div>` : ""}</div>`;
  };
  morph(box, `<div class="int-list">${d.integrations.map(row).join("")}</div>
    <details class="int-tools"><summary class="muted small">Command-line tools LFG uses</summary><div id="int-tools" class="mt" data-fill><div class="loading">Checking…</div></div></details>`);
  const msg = $("#int-msg");
  const said = r => { if (msg) saidMsg(msg, r, r.ok ? "Saved" : ""); };
  $$("[data-int-open]", box).forEach(b => b.onclick = () => { const k = b.dataset.intOpen; state.intOpen.has(k) ? state.intOpen.delete(k) : state.intOpen.add(k); loadIntegrations(); });
  $$("[data-int-switch]", box).forEach(b => b.onclick = async () => {
    const name = b.dataset.intSwitch, on = b.classList.contains("on");
    if (on && !confirm(`Turn off ${name}? Its tools stay installed; you can turn it on again any time.`)) return;
    b.disabled = true; b.classList.toggle("on", !on);
    if (!on) state.intOpen.add(name);
    said(await save(on ? "pack_remove" : "pack_add", { name })); loadIntegrations();
  });
  $$("[data-cfg]", box).forEach(el => el.onchange = (async () => {  // a property: this box redraws in place every 2 seconds
    const v = el.type === "checkbox" ? el.checked : el.type === "number" ? Number(el.value) : el.value;
    const r = await save("config", { values: { [el.dataset.cfg]: v } }); said(r); if (r.ok) loadIntegrations();
  }));
  $$("[data-dict]", box).forEach(el => el.onchange = async () => { el.disabled = true; said(await save("config", { values: { [el.dataset.dict]: el.type === "checkbox" ? el.checked : el.value } })); loadIntegrations(); });
  $$("[data-cc]", box).forEach(b => b.onclick = async () => { b.disabled = true; said(await save(b.dataset.cc, { name: b.dataset.name })); loadIntegrations(); });
  $$("[data-int-act]", box).forEach(b => b[b.tagName === "SELECT" ? "onchange" : "onclick"] = async () => {
    const act = b.dataset.intAct;
    if (act === "sonar_apply" && !confirm("Restart SonarQube with the new setting? It takes a minute or two; your login and results are kept.")) return;
    b.disabled = true; if (b.tagName === "BUTTON") b.textContent = "Working…";
    said(await save(act, act === "headroom" ? { scope: b.value } : {})); loadIntegrations();
  });
  $$("[data-tour-start]", box).forEach(l => l.onclick = e => { e.preventDefault(); startTour(l.dataset.tourStart); });
  if (state.pendingTour && $('[data-pack="dictate"]', box)) { const t = state.pendingTour; state.pendingTour = null; setTimeout(() => startTour(t), 250); }
  if ($("#ollama-box", box)) loadOllama();
  api("tools").then(t => { const el = $("#int-tools"); if (!el) return; const miss = t.tools.filter(x => !x.installed);
    morph(el, miss.length ? `<div class="box"><ul class="list">${miss.map(x => `<li>${dot(x.required ? "bad" : "")}<div class="grow"><div class="title">${esc(x.tool)} is not installed</div><div class="meta">${esc(x.purpose)}</div></div></li>`).join("")}</ul></div>` : `<p class="muted small">All ${n(t.tools.length)} tools are installed.</p>`); });
  clearTimeout(intTimer);
  if (Object.values(d.jobs).some(j => j.status === "running")) intTimer = setTimeout(() => { if (document.body.contains(box)) loadIntegrations(); }, 2000);
}

function settingsTools() {
  return '<div id="tools-box" data-fill><div class="loading">Checking…</div></div>';
}
// "MCP: ✔ Connected" (raw `claude mcp list` text) -> "Connected"
const plainDetail = s => (s || "").replace(/MCP:\s*/g, "").replace(/[✔✓✘✗⏸]\uFE0F?\s*/g, "");
async function loadTools() {
  const box = $("#tools-box");
  if (!box) return;
  const d = await api("tools");
  const missing = d.tools.filter(t => !t.installed);
  box.innerHTML = `<p class="muted">Everything LFG connects to, checked ${ago(d.checked_at)}.</p>
    <div class="box"><ul class="list">${d.integrations.map(i => `<li>${dot(i.ok ? "ok" : i.optional ? "" : "bad")}<div class="grow"><div class="title">${esc(i.name)}</div><div class="meta">${esc(plainDetail(i.detail))}</div></div></li>`).join("")}</ul></div>
    ${mcpSection(d.mcp_servers || [])}
    <div class="set-section"><h4>Command-line tools</h4>${missing.length
      ? `<div class="box"><ul class="list">${missing.map(t => `<li>${dot(t.required ? "bad" : "")}<div class="grow"><div class="title">${esc(t.tool)} is not installed</div><div class="meta">${esc(t.purpose)}${t.required ? (t.pack === "core" ? " · needed: run lfg setup" : ` · needed by the ${esc(t.pack)} pack: lfg add ${esc(t.pack)}`) : ` · ${esc(t.pack)} pack, not added`}</div></div></li>`).join("")}</ul></div>`
      : `<div class="box calm">${dot("ok")}All ${n(d.tools.length)} tools are installed.</div>`}</div>`;
}
/* Every MCP server Claude Code has (claude mcp list): connected first, then the ones waiting for a sign-in. LFG only
   reads this list; signing in and removing happen in Claude Code or on claude.ai. */
const MCP_FROM = { "claude.ai": ["claude.ai connector", "Added on claude.ai; manage it under Settings → Connectors there"],
  you: ["yours, every project", "In ~/.claude.json: every Claude Code session has it"],
  project: ["this project", "From this project's .mcp.json or local settings"] };
function mcpSection(list) {
  if (!list.length) return "";
  const row = m => { const [tag, why] = MCP_FROM[m.source] || [m.source, "Provided by a Claude Code plugin"]; return `<li>${dot(m.status === "ok" ? "ok" : m.status === "auth" ? "" : "bad")}<div class="grow"><div class="title">${esc(m.name)} <span class="tag" title="${esc(why)}">${esc(tag)}</span>${m.lfg ? ` <span class="tag ok" title="${esc(m.lfg)}">LFG uses it</span>` : ""}</div><div class="meta mono small">${esc(m.target)}</div></div><span class="muted small nowrap">${esc(m.state)}</span></li>`; };
  const group = (title, xs, open, help) => xs.length ? `<details class="item" ${open ? "open" : ""}><summary><b>${esc(title)}</b> <span class="muted small">${n(xs.length)}</span></summary>${help ? `<p class="muted small">${help}</p>` : ""}<ul class="list">${xs.map(row).join("")}</ul></details>` : "";
  const by = s => list.filter(m => m.status === s).sort((a, b) => (b.lfg ? 1 : 0) - (a.lfg ? 1 : 0) || a.name.localeCompare(b.name));
  return `<div class="set-section"><h4>MCP servers</h4><p class="muted small">Every MCP server Claude Code can use, as <code>claude mcp list</code> reports them. Sign in to one with <code>/mcp</code> in Claude Code; claude.ai connectors are added and removed at <a href="https://claude.ai/settings/connectors" target="_blank" rel="noopener noreferrer">claude.ai → Settings → Connectors ↗</a>.</p>
    <div class="box">${group("Connected", by("ok"), true)}${group("Failed to connect", by("bad"), true, "Run <code>/mcp</code> in Claude Code to see why.")}${group("Need you to sign in", by("auth"), false, "Not usable until you sign in: run <code>/mcp</code> in Claude Code and pick it.")}</div></div>`;
}
function settingsOllama() {
  return '<div id="ollama-box" data-fill><div class="loading">Asking the local Ollama…</div></div>';
}
const gb = v => (v ? `${v} GB` : "—");
function pullBar(name, p) {
  const pc = p.total ? Math.round((100 * p.completed) / p.total) : 0;
  const s = p.error ? `<span class="save-msg bad">${esc(p.error)}</span>` : p.done ? '<span class="save-msg ok">done</span>' : `${esc(p.status)}${p.total ? ` · ${pc}%` : ""}`;
  return `<div class="pull"><div class="row"><b>${esc(name)}</b><span class="muted small">${s}</span></div>${p.done || p.error ? "" : `<div class="bar"><span style="width:${pc}%"></span></div>`}</div>`;
}
let ollamaTimer = null;
async function loadOllama() {
  const box = $("#ollama-box");
  if (!box) return;
  const d = await api("ollama"), un = state.settings.unlocked, dis = un ? "" : "disabled";
  const canPull = un && d.running ? "" : "disabled";
  const pulls = Object.entries(d.pulls || {});
  const use = name => (name === d.current ? `<span class="st">${dot("ok")}In use</span>` : `<button class="btn" data-ollama-use="${esc(name)}" ${dis}>Use</button>`);
  morph(box, `<p class="muted">Security tests (<code>/lfg:pentest</code>) run on a model on this computer, never in the cloud. ${d.running ? "" : fmtWhy(d.why)}</p>
    <div class="row">${dot(d.running ? "ok" : "bad")}<span>${d.running ? "Ollama is running" : "Ollama is not running"}</span><span class="muted small">· model in use: ${d.current ? esc(d.current) : "none yet"}${d.ram_gb ? ` · this computer has ${d.ram_gb} GB memory` : ""}</span></div>
    ${pulls.length ? `<div class="set-section"><h4>Downloading</h4>${pulls.map(([k, p]) => pullBar(k, p)).join("")}</div>` : ""}
    <div class="set-section"><h4>On this computer</h4><div class="box">${table(d.installed, [
      { k: "name", label: "Model", html: r => esc(r.name) }, { k: "size_gb", label: "Size", num: true, html: r => gb(r.size_gb) },
      { k: "use", label: "", html: r => (r.cloud ? '<span class="muted small">cloud model: not allowed</span>' : r.tools ? use(r.name) : '<span class="muted small">can\'t run pentests</span>') },
    ], { filter: false, emptyTitle: "No models yet", emptyBody: d.running ? "Download one below." : "" })}</div></div>
    <div class="set-section"><h4>Download a model</h4><div class="box">${table(d.catalog, [
      { k: "name", label: "Model", html: r => `${esc(r.name)}<div class="sub">${esc(r.note || "")}</div>` },
      { k: "size_gb", label: "Download", num: true, html: r => gb(r.size_gb) },
      { k: "fit", label: "Fits this computer", html: r => ({ fits: `${dot("ok")} Yes`, tight: `${dot("warn")} Just`, "too big": `${dot("bad")} No` }[r.fit] || "—") },
      { k: "act", label: "", html: r => (r.installed ? use(r.name) : `<button class="btn" data-ollama-pull="${esc(r.name)}" ${canPull}>Download</button>`) },
    ], { filter: false })}</div>
      <div class="row mt"><input type="text" id="ollama-name" placeholder="Other model, e.g. qwen3:14b" ${dis}><button class="btn" id="ollama-pull" ${canPull}>Download</button><span class="save-msg" id="ollama-msg"></span></div></div>`);
  mountTables(box);
  const pull = async name => {
    const r = await save("ollama_pull", { name });
    saidMsg($("#ollama-msg"), r, r.ok ? `Downloading ${name}…` : "");
    if (r.ok) loadOllama();
  };
  $$("[data-ollama-pull]", box).forEach(b => b.onclick = () => pull(b.dataset.ollamaPull));
  $("#ollama-pull", box).onclick = () => pull($("#ollama-name").value.trim());
  $$("[data-ollama-use]", box).forEach(b => b.onclick = async () => {
    const r = await save("config", { values: { "pentest.model": b.dataset.ollamaUse } });
    if (!r.ok) return saidMsg($("#ollama-msg"), r);
    state.settings.cfg = await api("settings");
    loadOllama();
  });
  clearTimeout(ollamaTimer);
  if (pulls.some(([, p]) => !p.done)) ollamaTimer = setTimeout(() => { if (document.body.contains(box)) loadOllama(); }, 1500);
}
function settingsStorage() {
  return '<div id="storage-box"><div class="loading">Measuring…</div></div>';
}
async function loadStorage() {
  const box = $("#storage-box");
  if (!box) return;
  const d = await api("storage"), un = state.settings.unlocked;
  const cands = d.candidates.length ? `<div class="box">${table(d.candidates, [
      { k: "pick", label: "", html: r => `<input type="checkbox" data-clean="${esc(r.id)}" ${un ? "" : "disabled"}>` },
      { k: "label", label: "What", html: r => `${esc(r.label)}<div class="sub">${esc(r.reason)}</div>` },
      { k: "mb", label: "Size", num: true, html: r => `${r.mb} MB` }], { filter: false })}</div>
    <div class="set-actions"><button class="btn danger" id="clean-go" disabled>Delete selected</button><span class="save-msg" id="clean-msg"></span></div>`
    : `<div class="box calm">${dot("ok")}Nothing to clean up. Everything kept is still in use.</div>`;
  box.innerHTML = `<p><b>${d.total_mb} MB</b> <span class="muted">used of your ${d.limit_mb} MB limit</span></p>
    <div class="bar ${d.over ? "over" : ""}"><span style="width:${Math.min(100, pct(d.total_mb, d.limit_mb))}%"></span></div>
    <p class="muted small">The code maps inside your projects (${d.in_repos_mb || 0} MB) don't count toward this. Git ignores them.</p>
    <div class="set-section"><h4>Safe to delete</h4>${cands}</div>
    <div class="set-section"><h4>By project</h4><div class="box">${table(d.repos, [
      { k: "repo", label: "Project", html: r => esc(repoName(r.repo)) },
      { k: "total", label: "Size", num: true, sort: r => (r.graphs_mb || 0) + (r.runs_mb || 0), html: r => `${Math.round(((r.graphs_mb || 0) + (r.runs_mb || 0)) * 10) / 10} MB` }], { filter: false })}</div></div>`;
  mountTables(box);
  const go = $("#clean-go", box);
  if (!go) return;
  const picked = () => $$("[data-clean]", box).filter(c => c.checked).map(c => c.dataset.clean);
  $$("[data-clean]", box).forEach(c => c.onchange = () => (go.disabled = !picked().length));
  go.onclick = async () => {
    const ids = picked();
    if (!confirm(`Permanently delete ${ids.length} item(s)?`)) return;
    go.disabled = true;
    const r = await save("storage_cleanup", { ids });
    if (!r.ok) { go.disabled = false; return saidMsg($("#clean-msg"), r); }
    await loadStorage();
    const msg = $("#clean-msg") || $("#storage-box p");
    if (msg) saidMsg(msg, r, "Done.");
    loadBranches();
  };
}
function wireSettings(root) {
  const nt = $("#notify-test", root);
  if (nt) nt.onclick = async () => {
    if ("Notification" in window && Notification.permission === "default") await Notification.requestPermission();
    const sent = desktopNotice("LFG test notification", "If you can see this, notifications work.", () => {});
    saidMsg($("#notify-msg", root), sent ? { ok: true } : { ok: false, why: "the browser hasn't allowed them" }, "Sent. If nothing appeared, check macOS's notification settings for your browser.");
  };
  if ($("#cc-box", root)) loadClaudeCode();
  if ($("#skills-box", root)) loadSkills();
  if ($("#mylib-box", root)) loadMyLibrary();
  if ($("#ollama-box", root)) loadOllama();
  if ($("#storage-box", root)) loadStorage();
  if ($("#tools-box", root)) loadTools();
  if ($("#int-box", root)) loadIntegrations();
  if ($("#plg-box", root)) loadPlugins();
  if ($("#features-section", root)) loadFeatures();
  wireRules(root);
  const cs = $("#cfg-save", root);
  if (cs) cs.onclick = async () => {
    const values = {};
    for (const f of state.settings.cfg.fields) {
      const el = document.getElementById(`cfg-${f.key}`);
      let v = f.type === "bool" ? el.checked : f.type === "int" ? Number(el.value) : el.value;
      if (f.type === "list") v = el.value.split(",").map(x => x.trim()).filter(Boolean);
      if (JSON.stringify(v) !== JSON.stringify(f.value ?? (f.type === "list" ? [] : ""))) values[f.key] = v;
    }
    if (!Object.keys(values).length) return saidMsg($("#cfg-msg"), { ok: true }, "Nothing changed.");
    const d = await save("config", { values });
    saidMsg($("#cfg-msg"), d, d.ok ? `Saved ${plural(d.changed.length, "change")}.` : "");
    if (d.ok) state.settings.cfg = await api("settings");
  };

  $$("[data-skill]", root).forEach(a => a.onclick = e => {
    e.preventDefault();
    $$("[data-skill]", root).forEach(x => x.classList.toggle("on", x === a));
    showSkill(a.dataset.skill);
  });
  const cmMode = edit => { $("#cm-read").hidden = edit; $("#cm-write").hidden = !edit; $("#cm-edit").hidden = edit; };
  const ce = $("#cm-edit", root);
  if (ce) ce.onclick = () => cmMode(true);
  const cc = $("#cm-cancel", root);
  if (cc) cc.onclick = () => { $("#cm-text").value = state.settings.cm.text; cmMode(false); };
  const ms = $("#cm-save", root);
  if (ms) ms.onclick = async () => {
    const d = await save("claudemd", { text: $("#cm-text").value });
    saidMsg($("#cm-msg"), d);
    if (d.ok) { state.settings.cm = await api("claudemd"); $("#cm-read").innerHTML = md(state.settings.cm.text); }
  };
}
async function showSkill(name) {
  const box = $("#skill-editor"), un = state.settings.unlocked;
  const d = await api("skill", { name });
  if (d.available === false) { box.innerHTML = unavailable(d); return; }
  const fm = frontMatter(d.text);
  box.innerHTML = `<div class="row" style="margin-bottom:8px"><b>/lfg:${esc(name)}</b>${d.edited ? '<span class="tag">edited by you</span>' : ""}<span class="grow"></span>${un ? '<button class="btn" id="skill-edit">Change</button>' : ""}</div>
    <div id="skill-read">${fm.meta.description ? `<p class="muted">${txt(fm.meta.description)}</p>` : ""}<div class="md">${md(fm.body)}</div></div>
    <div id="skill-write" hidden><p class="muted small">Written in Markdown. Keep the header between the <code>---</code> lines; Claude Code reads it.</p>
    <textarea class="editor" id="skill-text" spellcheck="false">${esc(d.text)}</textarea>
    <div class="set-actions"><button class="btn primary" id="skill-save">Save</button><button class="btn" id="skill-cancel">Cancel</button>${d.edited ? '<button class="btn" id="skill-reset">Undo my changes</button>' : ""}<span class="save-msg" id="skill-msg"></span></div></div>`;
  const mode = edit => { $("#skill-read").hidden = edit; $("#skill-write").hidden = !edit; if ($("#skill-edit")) $("#skill-edit").hidden = edit; };
  if ($("#skill-edit")) $("#skill-edit").onclick = () => mode(true);
  $("#skill-cancel").onclick = () => showSkill(name);
  const refreshList = async () => { state.settings.sk = await api("skills"); const a = $(`[data-skill="${name}"]`); if (a) a.innerHTML = `/lfg:${esc(name)}${state.settings.sk.skills.find(x => x.name === name)?.edited ? '<span class="tag">edited</span>' : ""}`; };
  $("#skill-save").onclick = async () => {
    const r = await save("skill", { name, text: $("#skill-text").value });
    saidMsg($("#skill-msg"), r);
    if (r.ok) { await refreshList(); showSkill(name); }
  };
  const rs = $("#skill-reset");
  if (rs) rs.onclick = async () => {
    if (!confirm(`Put /lfg:${name} back to how LFG ships it? A copy of your version is kept.`)) return;
    const r = await save("skill_reset", { name });
    if (!r.ok) return saidMsg($("#skill-msg"), r);
    await refreshList();
    showSkill(name);
  };
}

// ------------------------------------------------------------------ guided tours (first time, skippable)
const shortcutLabel = () => { const o = $('[data-dict="dictate.shortcut"]'); return o ? o.options[o.selectedIndex].text : "your shortcut"; };
/* One walkthrough of every Dictate control. While Dictate is off the controls are shown greyed and the last step is
   Add; once it's on, the same steps end with Turn off. */
function dictateTour(on) {
  const pre = on ? "" : " Works once Dictate is on.";
  return [
    { sel: '[data-pack="dictate"]', title: on ? "Meet LFG Dictate" : "New: LFG Dictate", body: () => `Speech-to-text that works in any app on your Mac: Slack, your editor, the browser, Claude. Speech is turned into text on this computer, so audio never leaves it and nothing you say is saved.${on ? " This row shows its shortcut, whether it's running and how many times you used it today." : " It's off until you add it."}` },
    { title: "How to talk to it", body: () => `<b>Hold ${esc(shortcutLabel())}</b>, speak, and let go: the words appear where your cursor is.<br><br><b>Double-tap</b> it for hands-free dictation; press it again or <b>Esc</b> to finish.<br><br>While it listens, a small pill at the bottom of your screen shows bars that move with your voice:<div class="tour-pill" aria-hidden="true">${"<i></i>".repeat(9)}</div>` },
    { sel: '[data-dict="dictate.shortcut"]', title: "Shortcut", body: () => `Which keys start Dictate: Option+Space, Right Option, Fn (globe), Control+Space or Command+Shift+Space. Right Option and Fn work on their own. Pick another one if an app already uses yours (the ChatGPT app and Raycast like Option+Space).${pre}` },
    { sel: '[data-dict="dictate.insert"]', title: "Put text in by", body: () => `Your words always go two places: where your cursor is, and your clipboard, so you can paste them again anywhere with ⌘V. <b>Pasting</b> is instant. <b>Typing</b> is for the odd app that blocks pasting; it's slower for long text.${pre}` },
    { sel: '[data-dict="dictate.cleanup"]', title: "Clean up with Claude", body: () => `On by default. Removes filler words ("um", "like"), applies spoken corrections ("Tuesday, no, Wednesday") and fixes punctuation: the text, never the audio, goes to Claude with your Claude Code sign-in. Untick it to keep everything on your Mac.${pre}` },
    on ? { sel: '[data-pack="dictate"] [data-int-switch]', title: "Turn it off", body: () => "Stops Dictate and deletes everything it installed: the model, its app and its login item. You can add it again any time." }
       : { sel: '[data-pack="dictate"] [data-int-switch]', title: "Turn it on", body: () => '<b>Add</b> downloads the speech model (about 90 MB, into ~/.lfg/dictate) and starts Dictate. macOS then asks for <b>Microphone</b> and <b>Accessibility</b> permission for "LFG Dictate". After that, the controls above come alive.' },
    { title: "From the terminal", body: () => `The same controls, if you prefer typing:<pre class="out">lfg add dictate                    # turn it on\nlfg dictate status\nlfg dictate shortcut right_option\nlfg dictate insert type            # or paste\nlfg dictate cleanup off            # or on\nlfg remove dictate                 # turn it off</pre>Replay this tour any time with <b>Take the tour</b> on the Dictate row.` },
  ];
}
const TOURS = { get dictate() { return dictateTour(true); }, get "dictate-intro"() { return dictateTour(false); } };
let TOUR = null;
function startTour(name) {
  endTour();
  const box = document.createElement("div");
  box.className = "tour";
  box.innerHTML = '<div class="tour-shade"></div><div class="tour-hole" hidden></div><div class="tour-card" role="dialog" aria-modal="true" aria-labelledby="tour-title"></div>';
  document.body.append(box);
  TOUR = { name, i: 0, box, onKey: e => { if (e.key === "Escape") finishTour("skipped"); else if (e.key === "ArrowRight") tourGo(1); else if (e.key === "ArrowLeft") tourGo(-1); } };
  document.addEventListener("keydown", TOUR.onKey);
  window.addEventListener("resize", tourDraw);
  tourShow();
}
function tourGo(d) { if (!TOUR) return; const n = TOUR.i + d; if (n >= TOURS[TOUR.name].length) return finishTour("finished"); TOUR.i = Math.max(0, n); tourShow(); }
/* what a step lights up: its element, if it's on the page and showing */
const tourTarget = st => { const el = st.sel && $(st.sel); return el && el.getClientRects().length ? el : null; };
/* A step on another page opens that page first and waits up to 3s for what it lights up; without it, the card is
   centred. A later move (Next, Back) wins over a wait still running. */
async function tourShow() {
  if (!TOUR) return;
  const st = TOURS[TOUR.name][TOUR.i], mine = TOUR.seq = (TOUR.seq || 0) + 1;
  if (st.page && (location.hash.slice(1).split("/")[0] || "home") !== st.page) location.hash = "#" + st.page;
  for (let k = 0; st.page && st.sel && k < 30 && !tourTarget(st); k++) {
    await new Promise(r => setTimeout(r, 100));
    if (!TOUR || TOUR.seq !== mine) return;
  }
  tourDraw();
}
function tourDraw() {
  if (!TOUR) return;
  const steps = TOURS[TOUR.name], st = steps[TOUR.i], last = TOUR.i === steps.length - 1;
  const hole = $(".tour-hole", TOUR.box), card = $(".tour-card", TOUR.box), shade = $(".tour-shade", TOUR.box);
  const target = tourTarget(st);
  card.innerHTML = `<div class="tour-step">${TOUR.i + 1} of ${steps.length}</div><h3 id="tour-title">${esc(st.title)}</h3><div class="tour-body">${st.body()}</div>
    <div class="tour-actions"><button class="link" data-t="skip">Skip tour</button><span class="grow"></span>${TOUR.i ? '<button class="btn small" data-t="back">Back</button>' : ""}<button class="btn small primary" data-t="next">${last ? "Done" : "Next"}</button></div>`;
  $('[data-t="skip"]', card).onclick = () => finishTour("skipped");
  $('[data-t="next"]', card).onclick = () => tourGo(1);
  const back = $('[data-t="back"]', card); if (back) back.onclick = () => tourGo(-1);
  shade.classList.toggle("solid", !target);
  if (!target) {  // a step about how to use it, not a button: centred card
    hole.hidden = true;
    card.style.left = `${Math.max(16, (innerWidth - card.offsetWidth) / 2)}px`; card.style.top = `${Math.max(16, (innerHeight - card.offsetHeight) / 2)}px`;
  } else {
    const el = target.closest("label") && !target.closest("li > .grow > .title") && target.type === "checkbox" ? target.closest("label") : target;
    el.scrollIntoView({ block: "center" });
    const r = el.getBoundingClientRect(), pad = 6;
    Object.assign(hole.style, { left: `${r.left - pad}px`, top: `${r.top - pad}px`, width: `${r.width + 2 * pad}px`, height: `${r.height + 2 * pad}px` });
    hole.hidden = false;
    const below = r.bottom + pad + 12, h = card.offsetHeight, w = card.offsetWidth;
    card.style.top = `${below + h < innerHeight - 8 ? below : Math.max(8, r.top - pad - 12 - h)}px`;
    card.style.left = `${Math.min(innerWidth - w - 16, Math.max(16, r.left))}px`;
  }
  $('[data-t="next"]', card).focus();
}
function finishTour(how) {
  if (!TOUR) return;
  const name = TOUR.name;
  try { localStorage.setItem("lfg.tour." + name, how); } catch (e) { /* private window: the server copy still counts */ }
  save("tour_done", { name, how });
  endTour();
  const p = $("#tour-prompt"); if (p) p.remove();
}
function endTour() {
  if (!TOUR) return;
  document.removeEventListener("keydown", TOUR.onKey);
  window.removeEventListener("resize", tourDraw);
  TOUR.box.remove();
  TOUR = null;
}
/* What's new: a walkthrough of what changed, shown once after an update (and from Help → What's new any time). The
   first step lists everything; each item after it opens its page and lights up what it's about. Finishing or skipping
   it counts the release as seen. Written in plugin/releases.json. */
const newsText = t => esc(t).replace(/`([^`]+)`/g, "<code>$1</code>");
function newsTour(rels) {
  const items = rels.flatMap(r => r.items);
  const list = rels.map(r => `${rels.length > 1 ? `<div class="k">${esc(r.version)}: ${esc(r.title)}</div>` : ""}<ul class="news-list">${r.items.map(i => `<li>${esc(i.title)}</li>`).join("")}</ul>`).join("");
  TOURS["whats-new"] = [{ title: rels.length === 1 ? `What's new in LFG ${rels[0].version}` : `What's new since you last looked`,
    body: () => `${rels.length === 1 ? `<p>${esc(rels[0].title)}.</p>` : ""}${list}<p class="muted small">Next walks you through each one. Skip any time; Help → What's new has it again.</p>` }]
    .concat(items.map(i => ({ page: i.page, sel: i.sel, title: i.title, body: () => newsText(i.text) })));
  startTour("whats-new");
}
async function newsReplay(version) {
  const d = await api("releases");
  const r = (d.releases || []).find(x => x.version === version);
  if (r) newsTour([r]);
}
document.addEventListener("click", e => { const b = e.target.closest("[data-news-replay]"); if (b) { e.preventDefault(); newsReplay(b.dataset.newsReplay); } });
/* The first time the dashboard opens after Dictate is set up: offer the tour, or skip it for good */
async function offerTours() {
  let t;
  try { t = await api("tours"); } catch (e) { return; }
  if (!t.setup_guide_done) { setupGuide(true); return; }  // first run: the setup guide comes before anything else
  if (((t.news || {}).unseen || []).length) { newsTour(t.news.unseen); return; }  // after an update: what's new, once
  const seen = k => { try { return localStorage.getItem("lfg.tour." + k); } catch (e) { return null; } };
  const remember = (k, how) => { try { localStorage.setItem("lfg.tour." + k, how); } catch (e) { /* ignore */ } save("tour_done", { name: k, how }); };
  const d = t.dictate || {};
  const promo = $("#promo");
  promo.innerHTML = "";
  // New in this version: Welcome (choose your pages) and Insights. Shown before the Dictate banner, once.
  if (!t.news_welcome_closed && !seen("news-welcome") && (location.hash.slice(1).split("/")[0] || "home") !== "onboarding") {
    promo.innerHTML = `<div class="promo" role="region" aria-label="New in LFG">
      <div class="grow"><div class="promo-title"><span class="tag">New</span> Choose your pages, and Insights</div>
        <div class="promo-text"><b>Welcome</b> lets you pick the features you use so the sidebar shows only their pages. <b>Insights</b> runs quick checks on this project: a review coach for your changes, explain a file, and test ideas.</div></div>
      <div class="promo-actions"><button class="btn small primary" data-news="welcome">Choose pages</button><button class="btn small" data-news="insights">Open Insights</button>
        <button class="icon-btn" data-news="close" aria-label="Close" title="Don't show again">&times;</button></div></div>`;
    const close = () => { remember("news-welcome", "closed"); promo.innerHTML = ""; };
    $('[data-news="welcome"]', promo).onclick = () => { close(); location.hash = "#onboarding"; };
    $('[data-news="insights"]', promo).onclick = () => { close(); location.hash = "#insights"; };
    $('[data-news="close"]', promo).onclick = close;
    return;
  }
  // A hidden feature the user has started to need: offer its pages once (yes, or "not now" for a month)
  let feats = null;
  try { feats = await api("features"); } catch (e) { feats = null; }
  const sug = feats && feats.suggestion;
  if (sug) {
    promo.innerHTML = `<div class="promo" role="region" aria-label="Show more of LFG">
      <div class="grow"><div class="promo-title">${esc(sug.name)}</div><div class="promo-text">${esc(sug.why)}</div></div>
      <div class="promo-actions"><button class="btn small primary" data-sug="yes">Show it</button><button class="btn small" data-sug="later">Not now</button></div></div>`;
    $$("[data-sug]", promo).forEach(b => b.onclick = async () => {
      const r = await save("feature_suggestion", { feature: sug.feature, answer: b.dataset.sug });
      promo.innerHTML = "";
      if (r.ok && b.dataset.sug === "yes") { applyPages(r); location.hash = "#" + sug.pages[0]; }
    });
    return;
  }
  // Dictate off: a banner on every page until it is turned on or closed (new installs and updates alike)
  if (!d.on && !d.banner_closed && !seen("dictate-banner")) {
    promo.innerHTML = `<div class="promo" role="region" aria-label="New: LFG Dictate">
      <div class="tour-pill" aria-hidden="true">${"<i></i>".repeat(9)}</div>
      <div class="grow"><div class="promo-title"><span class="tag">New</span> LFG Dictate</div>
        <div class="promo-text">Hold <b>Option+Space</b> anywhere on your Mac, speak, and let go: the words appear where your cursor is. Your voice is transcribed on this Mac and never saved; Claude tidies up the text.</div></div>
      <div class="promo-actions"><button class="btn small primary" data-promo="on">Turn it on</button><button class="btn small" data-promo="tour">Take the tour</button>
        <button class="icon-btn" data-promo="close" aria-label="Close" title="Don't show again">&times;</button></div></div>`;
    const go = () => { if ((location.hash.slice(1) || "home").split("/")[0] === "integrations") route(); else location.hash = "#integrations"; };
    $('[data-promo="close"]', promo).onclick = () => { remember("dictate-banner", "closed"); promo.innerHTML = ""; };
    $('[data-promo="tour"]', promo).onclick = () => { state.pendingTour = "dictate-intro"; go(); };
    $('[data-promo="on"]', promo).onclick = async e => {
      const r = await save("pack_add", { name: "dictate" });
      if (!r.ok) { e.target.closest(".promo").querySelector(".promo-text").innerHTML = `${fmtWhy(r.why || "Couldn't start it.")} You can also run <code>lfg add dictate</code> in your terminal.`; return; }
      promo.innerHTML = "";
      go();  // Integrations shows the download's progress
    };
    return;
  }
  // Dictate on: offer the controls tour once
  // (the walkthrough taken before turning it on already showed every control, so it counts)
  if (!d.on || d.done || seen("dictate") || seen("dictate-intro") === "finished" || $("#tour-prompt")) return;
  const card = document.createElement("div");
  card.id = "tour-prompt"; card.className = "tour-prompt"; card.setAttribute("role", "dialog"); card.setAttribute("aria-label", "LFG Dictate is ready");
  card.innerHTML = `<div class="tour-pill small" aria-hidden="true">${"<i></i>".repeat(7)}</div><div class="grow"><b>LFG Dictate is ready</b><div class="meta">Take a 1-minute tour of its controls?</div></div>
    <button class="link" data-p="skip">Skip</button><button class="btn small primary" data-p="go">Start tour</button>`;
  document.body.append(card);
  $('[data-p="skip"]', card).onclick = () => { remember("dictate", "skipped"); card.remove(); };
  $('[data-p="go"]', card).onclick = () => {
    card.remove();
    state.pendingTour = "dictate";
    if ((location.hash.slice(1) || "home").split("/")[0] === "integrations") route(); else location.hash = "#integrations";
  };
}

// ------------------------------------------------------------------ pages
const NAV = [["prefs", "Preferences"], ["talk", "How Claude talks"], ["corrections", "Corrections"], ["home", "Home"], ["studio", "Studio"], ["sessions", "Sessions"], ["todos", "Todos"], ["environment", "Environment"], ["runs", "Runs"], ["issues", "Issues"], ["checks", "Checks"], ["prs", "PR reviews"], ["code", "Code"], ["insights", "Insights"], ["docs", "Docs"],
  ["knowledge", "Knowledge"], ["usage", "Usage"], ["skills", "Skills"], ["integrations", "Integrations"], ["settings", "Settings"], ["help", "Help"]];
const TITLES = Object.fromEntries(NAV);
TITLES.onboarding = "Welcome"; TITLES.lfg = "Home";
const PAGES = {};
state.pages = NAV.map(p => p[0]);  // visible nav pages, set from onboarding

async function cachedRuns() {
  const key = "runs:" + state.repo;
  if (!state.cache[key]) state.cache[key] = await api("runs");
  return state.cache[key];
}

/* What a run is doing, in one line: "Step 5 of 10 · next: run the checks" */
function runLine(r, stages) {
  const p = runPlace(stages, r.stages, r);
  return p.finished ? "All steps done" : `${p.done} of ${p.total} steps · next: ${NEXT[p.next]}`;
}
/* Things on a run that need a person, as [tone, text, short label for the Runs table] */
function runAttention(r) {
  const out = [];
  if (r.review === "block") out.push(["bad", "The code review found something that must be fixed", "Review: must fix"]);
  else if (r.review === "changes") out.push(["warn", "The code review asked for changes", "Review: changes asked"]);
  if (r.review && r.review_on_red) out.push(["warn", "The code review was written while checks were failing: if code changes to fix them, review again before shipping", "Reviewed on failing checks"]);
  if (r.secure === "don't") out.push(["bad", "The security check found problems to fix", "Security problems"]);
  if (r.ready === "red") out.push(["bad", "Tests or checks are failing", "Checks failing"]);
  else if (r.ready === "cant_run") out.push(["warn", `Some checks can't run on this computer: ${(r.cant_run || []).join(", ") || "a tool"} isn't installed. Nothing failed; install it to prove them here, or rely on CI`, "Some checks can't run here"]);
  else if (r.ready === "stale") out.push(["warn", "The last checks ran before the latest work, so their result is out of date: run /lfg:check", "Checks out of date"]);
  if (r.shipcheck === "fail") out.push(["bad", "The ship check failed", "Ship check failed"]);
  else if (r.shipcheck === "needs_config") out.push(["warn", "The ship check couldn't build the image: it needs build args in .lfg/shipcheck.json", "Ship check needs build args"]);
  if (r.pentest === "refused") out.push(["warn", "The security test didn't run: open the Security test document to see why", "Security test didn't run"]);
  return out.sort((a, b) => (a[0] === "bad" ? 0 : 1) - (b[0] === "bad" ? 0 : 1));
}

const FEATURE_ICON = { coding: "code", reviews: "review", security: "checks", knowledge: "knowledge", planning: "issues" };

/* Insights: understand code you didn't write, without opening an editor. Three tabs, each answering one question:
   Your changes (is this safe to approve?), Hotspots (where does this codebase break?), Files (what is this and why
   is it like this?). Everything comes from git on this computer; nothing here edits code. */
const INS = { file: "" };
PAGES.insights = async arg => {
  const [tab, ...rest] = (arg || "").split("/");
  if (tab === "files" && rest.length) { INS.file = rest.join("/"); sessionStorage.setItem("lfg.tab.insights", "files"); }
  else if (["changes", "hotspots", "files"].includes(tab)) sessionStorage.setItem("lfg.tab.insights", tab);
  return `${head("Insights", "Understand what changed, where the code is fragile, and why it looks the way it does. From your git history, on this computer.")}
    ${tabs("insights", [
      ["changes", "Your changes", null, () => `<div id="ins-changes"><div class="loading">Reading your changes…</div></div>`],
      ["hotspots", "Hotspots", null, () => `<div id="ins-hot"><div class="loading">Reading the history…</div></div>`],
      ["files", "Files", null, () => `<div class="fx-search"><span class="fx-search-ico">${icon("docs")}</span><input id="ins-file" list="ins-files" placeholder="Type a file path, e.g. src/billing.py" value="${esc(INS.file)}" autocomplete="off" aria-label="File"><button class="btn primary" id="ins-open">Explain</button></div><div id="ins-file-out"></div>`],
    ])}
    <datalist id="ins-files"></datalist>`;
};
const insLink = p => `<a href="#insights/files/${esc(p)}" class="ins-path">${esc(p)}</a>`;
const LEVEL = { HIGH_RISK: ["bad", "Fix before merging"], NEEDS_WORK: ["warn", "Needs a look"], READY_TO_REVIEW: ["ok", "No red flags"] };
function insChanges(d) {
  if (d.error) return unavailable({ why: d.error }, "Couldn't read your changes");
  if (d.message) return empty("No changes yet", "When this branch has changes, committed or not, they show up here with what to check before merging.");
  const [tone, label] = LEVEL[d.risk_level] || ["", d.risk_level];
  const files = d.files_reviewed || [];
  const added = files.reduce((a, f) => a + (f.additions || 0), 0);
  const issues = (d.issues || []).map(i => ({ severity: i.severity, file: i.file, line: i.line, title: i.message, fix: i.suggestion }));
  const shown = issues.filter(i => i.severity !== "low"), low = issues.filter(i => i.severity === "low");
  const q = d.questions || [], hot = d.touches_hotspots || [], pat = d.patterns || [];
  return `<div class="ins-summary"><span class="st"><span class="dot ${tone}"></span>${esc(label)}</span><span class="muted">${plural(files.length, "file")} · +${n(added)} lines · compared with <code>${esc(d.base_branch || "")}</code></span><span class="grow"></span><button class="btn small" id="ins-recheck">Check again</button></div>
    ${q.length ? `<h3 class="ins-h">Before you approve, ask</h3><ol class="ins-questions box">${q.map(x => `<li>${esc(x.q)}</li>`).join("")}</ol>` : ""}
    ${shown.length ? `<h3 class="ins-h">Worth a look</h3>${shown.map(findingCard).join("")}` : ""}
    ${hot.length ? `<h3 class="ins-h">Touches fragile code</h3><ul class="ins-hot box">${hot.slice(0, 5).map(h => `<li>${dot(h.level === "high" ? "bad" : "warn")}<div class="grow">${insLink(h.path)}<div class="muted small">${esc(h.reasons.join(" · "))}</div></div></li>`).join("")}${hot.length > 5 ? `<li class="muted">and ${hot.length - 5} more, in <a href="#insights/hotspots">Hotspots</a></li>` : ""}</ul>` : ""}
    ${pat.length ? `<h3 class="ins-h">Keeps coming up</h3><ul class="ins-list box">${pat.map(p => `<li>${esc(p.kind)}<span class="muted"> · in ${p.times} of your last ${p.of} checks</span></li>`).join("")}</ul>` : ""}
    ${!q.length && !shown.length && !hot.length ? `<p class="muted">Nothing stood out. These are pattern checks, not a review: <code>/lfg:review-coach</code> in Claude Code gives you one.</p>` : ""}
    <details class="ins-more"><summary>${plural(files.length, "changed file")}${low.length ? ` · ${plural(low.length, "note")} in tests` : ""}</summary>
      <ul class="ins-list">${files.map(f => `<li>${insLink(f.path)}<span class="muted"> · ${f.new ? "new, " : ""}+${n(f.additions || 0)}${f.deletions ? ` −${n(f.deletions)}` : ""}</span></li>`).join("")}</ul>
      ${low.length ? low.map(findingCard).join("") : ""}
      <div class="ins-pick mt"><input id="ins-base" placeholder="Compare with another branch (default: found automatically)"><button class="btn small" id="ins-base-go">Compare</button></div>
    </details>`;
}
function insHotspots(d) {
  if (d.error) return unavailable({ why: d.error }, "Couldn't read the history");
  const f = d.files || [];
  if (!f.length) return empty("No hotspots yet", `Nothing changed often enough in the last ${d.days} days to stand out.`);
  return `<p class="muted">The files that keep needing fixes are where the next bug most likely is. From ${plural(d.commits, "commit")} in the last ${d.days} days.</p>
    ${(d.rising || []).length ? `<p class="ins-warn">${dot("bad")}Fixes are rising in ${d.rising.map(a => `<code>${esc(a)}</code>`).join(", ")}: more in the last ${d.half} days than the ${d.half} before.</p>` : ""}
    <ul class="ins-hot box">${f.map(h => `<li>${dot(h.level === "high" ? "bad" : "warn")}<div class="grow">${insLink(h.path)}<div class="muted small">${esc(h.reasons.join(" · "))}</div>
      ${h.recent_fixes.length ? `<details class="ins-fixes"><summary>Recent fixes</summary><ul>${h.recent_fixes.map(c => `<li><code>${esc(c.sha.slice(0, 7))}</code> ${esc(c.date)} ${esc(c.subject)}</li>`).join("")}</ul></details>` : ""}</div></li>`).join("")}</ul>
    ${(d.areas || []).length > 1 ? `<h3 class="ins-h">By folder</h3><div class="box">${table(d.areas, [{ k: "area", label: "Folder", html: r => `<code>${esc(r.area)}</code>` }, { k: "files", label: "Files changed", num: true }, { k: "changes", label: "Changes", num: true }, { k: "fixes", label: "Fixes", num: true }, { k: "trend", label: "Trend", html: r => r.trend === "rising" ? `<b>rising</b> <span class="muted">${r.fixes_recent} vs ${r.fixes_earlier}</span>` : r.trend === "falling" ? `falling <span class="muted">${r.fixes_recent} vs ${r.fixes_earlier}</span>` : '<span class="muted">steady</span>' }], { sort: "fixes", filter: false })}</div>` : ""}
    <p class="muted small mt">Dependency risks (known vulnerabilities, end-of-life packages) are in <a href="#checks">Checks</a>, from <code>/lfg:secure</code>.</p>`;
}
function insWhy(d) {
  if (d.error) return `<p class="muted">${esc(d.error)}</p>`;
  if (!d.commits.length) return `<p class="muted">No history yet: this hasn't been committed.</p>`;
  return `<ol class="ins-timeline">${d.commits.map(c => `<li><div><b>${esc(c.subject)}</b></div>
    <div class="muted small">${c.url ? `<a href="${esc(c.url)}" target="_blank" rel="noopener noreferrer"><code>${esc(c.sha.slice(0, 7))}</code></a>` : `<code>${esc(c.sha.slice(0, 7))}</code>`} · ${esc(c.author)} · ${esc(c.date)}${c.fix ? ' <span class="tag bad">fix</span>' : ""}${c.refs.map(r => ` · ${r.url ? `<a href="${esc(r.url)}" target="_blank" rel="noopener noreferrer">${esc(r.label)}</a>` : esc(r.label)}`).join("")}</div>
    ${c.body ? `<details><summary class="small">Details</summary><div class="ins-body">${esc(c.body)}</div></details>` : ""}</li>`).join("")}</ol>`;
}
/* Files: understand one file without opening it. Empty: what this is for, and files worth starting with. */
function insFilePicker(hot) {
  const files = (hot && hot.files) || [];
  const fragile = files.slice(0, 5), recent = files.slice().sort((a, b) => (b.last || "").localeCompare(a.last || "")).slice(0, 5);
  const chip = f => `<button class="fx-chip" data-pick="${esc(f.path)}"><span class="fx-chip-dir">${esc(f.path.includes("/") ? f.path.slice(0, f.path.lastIndexOf("/") + 1) : "")}</span><b>${esc(f.path.split("/").pop())}</b></button>`;
  return `<div class="fx-intro box pad"><div class="fx-intro-h"><h3>Understand any file without opening it</h3><p class="muted">Pick a file and LFG reads it and its git history for you.</p></div>
    <div class="fx-what">${[["docs", "What it does", "Its purpose, in its own words, and everything it defines."], ["runs", "Why it's like this", "The commits, PRs and tickets that shaped each part."], ["checks", "What to test", "Test ideas, past bugs to guard, and a test file to start from."]].map(([ic, t, d]) => `<div><span class="fx-what-ico">${icon(ic)}</span><b>${t}</b><span class="muted">${d}</span></div>`).join("")}</div></div>
    ${fragile.length ? `<h3 class="ins-h">Start with a fragile file</h3><div class="fx-chips">${fragile.map(chip).join("")}</div>` : ""}
    ${recent.length ? `<h3 class="ins-h">Changed recently</h3><div class="fx-chips">${recent.map(chip).join("")}</div>` : ""}`;
}
function insFile(ex, ts) {
  if (ex.error) return unavailable({ why: ex.error }, "Couldn't open it");
  const w = ex.why_its_here || {};
  const defs = (ex.how_it_works || []).slice().sort((a, b) => a.line - b.line);
  const ideas = (ts && ts.suggested_tests) || [];
  const tests = ex.related_tests || [], fixes = w.recent_fixes || [];
  const dir = ex.file.includes("/") ? ex.file.slice(0, ex.file.lastIndexOf("/") + 1) : "", name = ex.file.split("/").pop();
  const P = { 1: "Start here", 2: "Edge case", 3: "Nice to have" };
  ideas.forEach(t => { if (t.category === "regression") t.kind = "Past bug"; });
  const kindTag = k => `<span class="tag ${k === "class" ? "blue" : ""}">${k === "class" ? "class" : "fn"}</span>`;
  const overview = `${ex.summary ? `<p class="fx-sum">${inline(ex.summary)}</p>` : '<p class="muted">The file doesn\'t describe itself. Ask Claude: <code>/lfg:explain</code> how it works.</p>'}
    ${fixes.length ? `<div class="callout warn fx-warn"><b>Fixed ${plural(fixes.length, "time")} in the last six months:</b> ${fixes.slice(0, 2).map(f => `“${esc(f.message.replace(/[.\s]+$/, ""))}”`).join(", ")}${fixes.length > 2 ? "…" : ""}. Change it carefully.</div>` : ""}
    ${defs.length ? `<h3 class="ins-h">What's in it <span class="tag">${defs.length}</span></h3>
      <div class="fx-defs box">${defs.map((x, k) => `<div class="fx-def"><div class="fx-def-row">${kindTag(x.type)}<code class="fx-def-n">${esc(x.name)}</code><span class="fx-def-d">${x.docstring ? inline(x.docstring) : '<span class="faint">no description</span>'}</span><span class="fx-def-l">line ${x.line}</span><button class="btn small" data-why="${x.line}" data-end="${defs[k + 1] ? defs[k + 1].line - 1 : ""}">History</button></div><div class="ins-why"></div></div>`).join("")}</div>` : ""}
    ${(ex.potential_issues || []).length ? `<h3 class="ins-h">Worth a look</h3><div class="box">${ex.potential_issues.map(i => `<div class="fx-issue"><span class="tag warn">line ${esc(i.line)}</span>${esc(i.message)}</div>`).join("")}</div>` : ""}`;
  const history = `<div id="ins-why-file"><div class="loading">Reading the history…</div></div>`;
  const testsTab = `${tests.length ? `<p class="muted">Already tested in ${tests.map(t => insLink(t)).join(", ")}.</p>` : '<p class="muted">No test file covers it yet: start with the file below.</p>'}
    ${ts && ts.skeleton ? `<div class="ins-skel"><div class="row"><b>A test file to start from</b><span class="muted small">every test is skipped until it's written, so it runs as-is</span><span class="grow"></span><button class="btn small" data-copy="ins-skel-code">Copy</button></div><pre class="out" id="ins-skel-code">${esc(ts.skeleton)}</pre></div>` : ""}
    ${ideas.length ? `<h3 class="ins-h">Test ideas <span class="tag">${ideas.length}</span></h3><div class="box">${table(ideas, [{ k: "priority", label: "", html: r => `<span class="tag ${r.kind ? "bad" : r.priority === 1 ? "blue" : ""}">${esc(r.kind || P[r.priority] || "")}</span>`, sort: r => r.priority }, { k: "test_name", label: "Test", html: r => `<code>${esc(r.test_name)}</code>` }, { k: "reason", label: "Why" }], { sort: "priority", dir: 1, filter: false })}</div>` : ""}`;
  return `<div class="fx-file">
    <div class="fx-head box pad"><div class="fx-path"><span>${esc(dir)}</span><b>${esc(name)}</b></div>
      <div class="fx-tags">${ex.language ? `<span class="tag">${esc(ex.language)}</span>` : ""}${w.total_commits ? `<span class="tag">${plural(w.total_commits, "commit")}</span>` : '<span class="tag">not committed yet</span>'}${tests.length ? `<span class="tag ok">tested</span>` : '<span class="tag warn">no tests</span>'}${fixes.length ? `<span class="tag bad">${fixes.length} recent ${fixes.length === 1 ? "fix" : "fixes"}</span>` : ""}</div>
      ${w.created_by ? `<div class="muted small">Added by ${esc(w.created_by)} on ${esc(w.created_date)} · last changed by ${esc(w.last_modified_by)} on ${esc(w.last_modified_date)}</div>` : ""}
      <button class="link small fx-back" data-fx-back>← Pick another file</button></div>
    ${tabs("insfile", [["overview", "Overview", null, () => overview], ["history", "History", null, () => history], ["tests", "Tests", ideas.length || null, () => testsTab]])}
  </div>`;
}
function wireInsights(root) {
  const dl = $("#ins-files", root);
  if (dl && !dl.dataset.loaded) { dl.dataset.loaded = "1"; api("insight_files").then(d => { dl.innerHTML = (d.files || []).map(f => `<option value="${esc(f)}">`).join(""); }).catch(() => {}); }
  const ch = $("#ins-changes", root);
  if (ch && !ch.dataset.done) {
    ch.dataset.done = "1";
    const load = async base => {
      ch.innerHTML = '<div class="loading">Reading your changes…</div>';
      try { ch.innerHTML = insChanges(await api("insight_review", base ? { base } : {})); } catch (e) { ch.innerHTML = unavailable({ why: e.message }); }
      const again = $("#ins-recheck", ch); if (again) again.onclick = () => load(base);
      const go = $("#ins-base-go", ch); if (go) go.onclick = () => load($("#ins-base", ch).value.trim());
    };
    load("");
  }
  const hot = $("#ins-hot", root);
  if (hot && !hot.dataset.done) {
    hot.dataset.done = "1";
    api("insight_hotspots").then(d => { hot.innerHTML = insHotspots(d); mountTables(hot); }).catch(e => { hot.innerHTML = unavailable({ why: e.message }); });
  }
  const out = $("#ins-file-out", root), inp = $("#ins-file", root);
  if (out && inp && !out.dataset.wired) {
    out.dataset.wired = "1";
    const wireFile = file => {
      const histBox = () => $("#ins-why-file", out);
      const loadHist = async () => { const b = histBox(); if (b && !b.dataset.done) { b.dataset.done = "1"; b.innerHTML = insWhy(await api("insight_why", { file })); } };
      $$("[data-tabs=insfile] .tab", out).forEach(t => t.addEventListener("click", () => setTimeout(() => { if (t.dataset.k === "history") loadHist(); wireDefs(); }, 0)));
      if (sessionStorage.getItem("lfg.tab.insfile") === "history") loadHist();
      const wireDefs = () => $$("[data-why]", out).forEach(b => b.onclick = async () => {
        const box = b.closest(".fx-def").querySelector(".ins-why");
        if (box.innerHTML) { box.innerHTML = ""; b.textContent = "History"; return; }
        b.textContent = "Reading…";
        box.innerHTML = insWhy(await api("insight_why", { file, start: b.dataset.why, end: b.dataset.end }));
        b.textContent = "Hide";
      });
      wireDefs();
      const back = $("[data-fx-back]", out); if (back) back.onclick = () => { INS.file = ""; inp.value = ""; showPicker(); };
    };
    const open = async file => {
      file = (file || inp.value).trim();
      if (!file) return;
      INS.file = file; inp.value = file;
      out.innerHTML = '<div class="loading">Reading the file and its history…</div>';
      const [ex, ts] = await Promise.all([api("insight_explain", { file }), api("insight_tests", { file }).catch(() => null)]);
      out.innerHTML = insFile(ex, ts); mountTabs(out); mountTables(out); wireFile(file);
    };
    const showPicker = async () => {
      out.innerHTML = insFilePicker(null);
      let hot = null; try { hot = await api("insight_hotspots"); } catch (e) { hot = null; }
      if (!INS.file) out.innerHTML = insFilePicker(hot);
      $$("[data-pick]", out).forEach(b => b.onclick = () => open(b.dataset.pick));
    };
    $("#ins-open", root).onclick = () => open();
    inp.onkeydown = e => { if (e.key === "Enter") open(); };
    if (INS.file) open(INS.file); else showPicker();
  }
  $$(".tab", root).forEach(t => { if (!t.dataset.insWired) { t.dataset.insWired = "1"; t.addEventListener("click", () => setTimeout(() => wireInsights(root), 0)); } });
}

/* ------------------------------------------------------------------ product home, intro journey, page tours
   The home (#lfg, what `lfg ui` opens) and the first-run intro are full-screen pages without the sidebar. Their
   pictures are small HTML snapshots of the real screens (aria-hidden), not screenshots, so they follow the theme. */
const BARE = ["lfg", "onboarding"];
/* Snapshots of the real screens, for the landing page and the intro. `A(d)` marks a part that animates in on the
   landing page, d steps after its row scrolls into view (elsewhere they just show). */
const A = (d, cls = "") => ` class="lp-a${cls ? " " + cls : ""}" style="--d:${d}"`;
const MOCK = {
  run: () => `<div class="mk mk-run"><div class="mk-row"><span class="tag blue">Standard lane</span><span class="mk-dim">run 0142 · feature/rate-limit</span></div>
    <div class="mk-title">Add rate limiting to the public API</div>
    <div class="mk-steps">${[["Brief", "done"], ["Plan", "done"], ["Build", "done"], ["Check", "now"], ["Review", ""], ["Ship", ""]].map(([st, c], i) => `<span${A(1 + i * .6, `mk-step ${c}`)}>${c === "done" ? "✓ " : ""}${st}</span>`).join("")}</div>
    <div class="mk-bar"><span style="--w:62%"></span></div>
    <div${A(5, "mk-dim")}>Tests 48 passed · lint clean · security check running…</div></div>`,
  diff: () => `<div class="mk mk-diff"><div class="mk-file"><span class="mk-st">M</span>api/limits.py<span class="grow"></span><span class="mk-add">+14</span><span class="mk-del">−3</span></div>
    <div class="mk-lines">
      <div${A(0, "mk-l")}><i>18</i><i></i><code>def allow(client, now):</code></div>
      <div${A(.5, "mk-l del")}><i>19</i><i>−</i><code>    window = now // 60</code></div>
      <div${A(1, "mk-l add")}><i>19</i><i>+</i><code>    hits = [t for t in log[client] if now - t &lt; 60]</code></div>
      <div${A(1.5, "mk-l add sel")}><i>20</i><i>+</i><code>    if len(hits) &gt;= LIMIT:</code></div>
      <div${A(2, "mk-l add")}><i>21</i><i>+</i><code>        return False</code></div>
    </div>
    <div class="mk-thread"><div${A(3.5, "mk-me")}>Why a sliding window and not a fixed one?</div>
      <div${A(5, "mk-ai wipe")}><span class="mk-ai-h"><span class="ai-badge">AI</span> from the diff and callers</span>A fixed minute lets a client send 2× the limit across the boundary (59s + 61s). The sliding window counts the last 60 seconds, so bursts stay capped. <code>login()</code> and <code>search()</code> call this.</div>
      <div${A(9, "mk-acts")}><span class="tag">Ask a follow-up</span><span class="tag ok">Resolve</span></div></div></div>`,
  comment: () => `<div class="mk mk-cmt"><div class="mk-row"><span class="tag bad">High</span><span class="mk-dim">reviewer · api/auth.py:42</span></div>
    <div class="mk-title">Token expiry isn't checked before refresh</div>
    <div class="mk-ai"><span class="mk-ai-h"><span class="ai-badge">AI</span> take</span>Valid: <code>refresh()</code> trusts the cached token. Fix is one line: compare <code>exp</code> first.</div>
    <div class="mk-acts"><span class="tag blue">Will fix</span><span class="tag">Discuss</span><span class="tag">Not now</span></div></div>`,
  questions: () => `<div class="mk mk-q"><div class="mk-row"><span class="st"><span class="dot warn"></span>Needs a look</span><span class="mk-dim">6 files · +212 lines vs main</span></div>
    <div class="mk-h">Before you approve, ask</div>
    <ol class="mk-ol"><li${A(1)}>It changes <code>billing.py</code>, which needed 4 fixes recently. How would you know if it broke?</li>
      <li${A(3)}>Your team decided <b>“money is integer cents”</b>. Does this still follow it?</li>
      <li${A(5)}>Nothing tests <code>refunds.py</code>. Which check shows it still works?</li></ol></div>`,
  hotspots: () => `<div class="mk mk-hot">${[["bad", "billing/charge.py", "needed 5 fixes · fixes rising · no tests", 92], ["warn", "api/limits.py", "changed 14 times · 3 people", 64], ["warn", "auth/session.py", "needed 2 fixes · 900 lines", 41]].map(([t, p, r, w], i) => `<div${A(i * 1.2, "mk-hot-r")}>${dot(t)}<div class="grow"><code>${p}</code><div class="mk-dim">${r}</div><span class="mk-heat ${t}"><i style="--w:${w}%;--d:${1 + i * 1.2}"></i></span></div></div>`).join("")}</div>`,
  why: () => `<div class="mk mk-why"><div class="mk-row"><code>def allow()</code><span class="mk-dim">· why is this here?</span></div>
    <ol class="mk-tl">${[["Count the last 60s instead of the minute", "PR #318", "Sarah · 3 days ago", ""], ["fix: clients doubled their burst at :00", "ENG-412", "Rahul · 2 weeks ago", "fix"], ["Add per-client rate limits", "PR #201", "Mike · 4 months ago", ""]].map(([t, r, w, f], i) => `<li${A(1 + i * 1.6)}><b>${t}</b><div class="mk-dim">${w} · <span class="tag blue">${r}</span>${f ? ' <span class="tag bad">fix</span>' : ""}</div></li>`).join("")}</ol></div>`,
  guard: () => `<div class="mk mk-term"><div class="mk-dots"><i></i><i></i><i></i></div>
    <div${A(0)}><span class="mk-p">claude ›</span> git push origin main</div>
    <div${A(1.5, "mk-red")}>✕ LFG guard: pushing is yours to do. Changes are ready to commit.</div>
    <div${A(3)}><span class="mk-p">claude ›</span> cat .env</div>
    <div${A(4.5, "mk-red")}>✕ LFG guard: secrets stay unread.</div>
    <div${A(6)}><span class="mk-p">claude ›</span> git commit -m "Add sliding-window rate limit"</div>
    <div${A(7.5, "mk-yel")}>? Asks you first. Approve in Claude Code.</div></div>`,
  dictate: () => `<div class="mk mk-dict"><div class="mk-dict-text">“${"Add a test for the refund path, and make it fail on negative amounts".split(" ").map((w, i, all) => `<span${A(1 + i * .35)}>${w}${i < all.length - 1 ? " " : ""}</span>`).join("")}”<span class="mk-caret"></span></div>
    <div class="mk-pill">${"<i></i>".repeat(9)}</div><div class="mk-dim mk-center">Hold <kbd>⌥</kbd> <kbd>Space</kbd>, speak, let go</div></div>`,
};
/* Go editorless: each editor as an app tile with its logo (ui_assets/editors): [name, file, tile background, logo size] */
const EDITORS = [["VS Code", "vscode", "#ffffff", 68], ["Cursor", "cursor", "", 100], ["JetBrains", "jetbrains", "linear-gradient(135deg, #ff8f1f, #ff318c 45%, #7b5cff)", 56],
  ["Zed", "zed", "#0c0e14", 54], ["Sublime Text", "sublime", "", 100], ["Xcode", "xcode", "#ffffff", 80], ["Antigravity", "antigravity", "#ffffff", 82]];
/* the hero's window: a Studio session, one sentence in, the pipeline running */
const HERO_STEPS = [["Grill", "brief and acceptance criteria"], ["Plan", "4 tasks · standard lane"], ["Build", "test-first, in its own worktree"],
  ["Check", "lint · types · tests · security"], ["Review", "standards · spec · blast radius"], ["Ship", "commit message and PR notes ready"]];
const FLOW = [["Ask", "/lfg:lfg add rate limiting", "One sentence in Claude Code."], ["Grill", "brief + acceptance criteria", "It asks until the goal is sharp."],
  ["Plan", "design · tasks · lane", "Small, testable slices."], ["Build", "agents in worktrees", "Test-first, one task each."],
  ["Check", "lint · tests · security · review", "Proof from exit codes."], ["Ship", "ready to commit", "You push. Always."]];
const SHOWCASE = [  // [kicker, icon, punch line (em = the highlight), what it is, snapshot, link]
  ["Reviews", "review", "Argue with the diff. <em>Win.</em>", "Open any pull request and ask about one line. Answers come from the code and everything that calls it, not from memory. Push back, decide what to fix, move on.", () => MOCK.diff(), "#review"],
  ["Insights", "insights", "Know what to ask <em>before you approve.</em>", "Every change arrives with the questions a senior engineer would ask: the fragile files it touches, the tests it skipped, the team decisions it might break.", () => MOCK.questions(), "#insights"],
  ["Hotspots", "target", "See the next bug <em>before it's filed.</em>", "Files that keep needing fixes, ranked from your own history, with the reason in plain words. Pay down debt where it actually hurts.", () => MOCK.hotspots(), "#insights/hotspots"],
  ["History", "branch", "Every line has a story. <em>Read it in seconds.</em>", "Any function's history, newest first: the commits that shaped it and the PRs and tickets behind them. Context without blame, without an editor.", () => MOCK.why(), "#insights/files"],
  ["Runs", "runs", "Watch the work, <em>not the keystrokes.</em>", "One sentence becomes a run you can follow: brief, plan, build, checks, review. You step in only where it needs a decision.", () => MOCK.run(), "#runs"],
  ["Guard", "checks", "It can't push, deploy or <em>read your secrets.</em>", "Guard rails enforced in code on every command, not asked for nicely in a prompt. Commits wait for your yes.", () => MOCK.guard(), "#settings"],
  ["Dictate", "mic", "Say it. <em>It's typed.</em>", "Hold a shortcut anywhere on your Mac and talk. Transcribed on the Mac and pasted where your cursor is; your audio never leaves it.", () => MOCK.dictate(), "#integrations"],
];
/* The open-source tools LFG stands on. Thank you. */
const THANKS = [
  ["Claude Code", "the agent LFG runs inside", "https://claude.com/claude-code"],
  ["code-review-graph", "the code map agents read instead of whole files", "https://pypi.org/project/code-review-graph/"],
  ["graphify", "the code wiki, call flows and architecture map", "https://pypi.org/project/graphifyy/"],
  ["Omnigraph", "dev-graph and second-brain: what LFG remembers", ""],
  ["Headroom", "context compression that saves tokens", ""],
  ["Cactus · Whistle", "on-device speech-to-text for Dictate", "https://cactuscompute.com/blog/whistle"],
  ["mattpocock/skills", "the grill, plan and TDD skills LFG adapts", "https://github.com/mattpocock/skills"],
  ["Cloudflare security-audit-skill", "the security review method", "https://github.com/cloudflare/security-audit-skill"],
  ["Semgrep", "code scanning", ""], ["Gitleaks", "secret scanning", ""], ["Trivy", "container and dependency scanning", ""],
  ["OSV-Scanner", "known vulnerabilities in dependencies", ""], ["Hadolint", "Dockerfile checks", ""], ["zizmor · actionlint", "GitHub Actions checks", ""],
  ["Strix", "offline pentests", ""], ["Ollama", "the local model for pentests", ""], ["SonarQube", "code quality, run locally", ""],
  ["uv", "fast, isolated Python tool installs", ""], ["PyObjC", "the macOS bits of Dictate", ""],
];
const lfgMark = () => `<span class="lp-mark">${logoSvg(22)}LFG</span>`;

PAGES.lfg = async () => {
  let n = 0;
  try { n = ((await api("guide")).skills || []).length; } catch (e) { n = 0; }
  return `<div class="lp">
  <header class="lp-nav"><a href="#lfg" class="lp-home" data-scroll="top" aria-label="Back to the top">${lfgMark()}</a><nav><a href="#lfg" data-scroll="lp-film">Film</a><a href="#lfg" data-scroll="lp-features">Features</a><a href="#lfg" data-scroll="lp-reviews">Reviews</a><a href="#lfg" data-scroll="lp-thanks">Open source</a><a href="#onboarding">Intro</a></nav>
    <a class="btn primary" href="#studio">Open dashboard →</a></header>
  <section class="lp-hero">
    <span class="wl-pill"><span class="tag">New</span> Insights and talk-to-the-diff reviews</span>
    <h1>Stop writing code.<br><em>Start directing it.</em></h1>
    <p>The bottleneck moved. It isn't typing any more; it's deciding what to build, steering the agents that build it, and trusting what ships. LFG is the cockpit for that, inside Claude Code.</p>
    <div class="lp-cta"><a class="btn primary big" href="#studio">Open dashboard</a><a class="btn big lp-ghost" href="#onboarding">Take the intro</a></div>
    <div class="lp-win" aria-hidden="true"><div class="lp-win-bar"><i></i><i></i><i></i><span>Studio · your-project</span></div>
      <div class="lp-win-b"><div class="lp-win-me">/lfg:lfg add rate limiting to the public API</div>
        <ol class="lp-win-steps">${HERO_STEPS.map(([t, d], i) => `<li class="todo" data-step="${t}" style="--i:${i}"><span class="lp-win-dot"></span><b>${t}</b><span>${d}</span><em></em></li>`).join("")}</ol>
        <div class="lp-win-ask"><span>Claude wants to edit <code>api/limits.py</code></span><span class="lp-win-btns"><span class="lp-win-btn on">Allow once</span><span class="lp-win-btn">Deny</span></span><span class="lp-win-ok">✓ Allowed</span></div>
        <div class="lp-win-done"><span class="lp-win-check">✓</span><b>Ready to commit.</b><span>6 files · 48 tests pass · review approved · nothing pushed</span></div></div></div>
  </section>
  <section class="lp-editors" id="lp-editors">
    <h2 class="lp-ed-h">Go editorless</h2>
    <div class="lp-ed">${EDITORS.map(([name, file, bg, size], i) => `<div class="lp-ed-i" style="--i:${i}"><span class="lp-ed-tile${bg ? "" : " bare"}" style="${bg ? `background:${bg};` : ""}--s:${size}%"><img src="/assets/editors/${file}.svg" alt="" draggable="false"><i class="lp-ed-x" aria-hidden="true"></i></span><span class="lp-ed-n">${esc(name)}</span></div>`).join("")}</div>
    <p class="lp-ed-p">Great editors. You just won't be editing.<br><b>Describe the change, review the result, ship.</b></p></section>
  <section class="lp-punch lp-reveal">
    <div><b>Coding was the skill.<br><em>Orchestration</em> is the new one.</b><p>You decide what gets built and in what order. Specialist agents do the typing, in their own worktrees.</p></div>
    <div><b>Read intent,<br>not diffs.</b><p>Every change arrives with why it was made, what it touches and what to ask before you approve it.</p></div>
    <div><b>Ship with proof,<br>not hope.</b><p>Lint, types, tests, security and a review on every change, judged from exit codes, never an agent's claim.</p></div>
  </section>
  <section class="lp-sec lp-film lp-reveal" id="lp-film"><div class="lp-k">The launch film</div><h2>See it in <em>a minute and a half.</em></h2>
    <div class="lp-film-v"><video src="${LAUNCH_VIDEO}" controls playsinline preload="metadata" aria-label="The LFG launch film"></video></div></section>
  <section class="lp-sec lp-feats" id="lp-features"><div class="lp-k">What you get</div><h2>Everything you'd open an editor for. <em>Without one.</em></h2>
    ${SHOWCASE.map(([k, ico, punch, d, v, href], i) => `<div class="lp-row lp-reveal${i % 2 ? " flip" : ""}"${k === "Reviews" ? ' id="lp-reviews"' : ""}><div class="lp-copy"><span class="lp-kick">${icon(ico)}${k}</span><h3>${punch}</h3><p>${d}</p><a href="${href}" class="lp-link">Open ${k} →</a></div><div class="lp-vis" aria-hidden="true">${v()}</div></div>`).join("")}
  </section>
  <section class="lp-facts lp-reveal"><div><b>${n || "25+"}</b><span>skills, one per job</span></div><div><b>8</b><span>specialist agents</span></div><div><b>18</b><span>guard rules, in code</span></div><div><b>0</b><span>lines of your code sent by Insights</span></div></section>
  <section class="lp-sec lp-thanks lp-reveal" id="lp-thanks"><div class="lp-k">Built on open source</div><h2>Thank you</h2>
    <p class="muted">LFG is a thin layer on top of other people's excellent work. These projects do the heavy lifting.</p>
    <div class="lp-tk">${THANKS.map(([n, what, url]) => `<${url ? `a href="${url}" target="_blank" rel="noopener noreferrer"` : "div"} class="lp-tk-i"><b>${esc(n)}</b><span>${esc(what)}</span></${url ? "a" : "div"}>`).join("")}</div></section>
  <section class="lp-end lp-reveal"><h2>Ready when you are.</h2><p class="muted">Open Claude Code in a repo, run <code>lfg enable</code>, and say what you want.</p>
    <div class="lp-cta"><a class="btn primary big" href="#studio">Open dashboard</a><a class="btn big" href="https://github.com/varun-singhh/lfg" target="_blank" rel="noopener noreferrer" data-gh-star>★ Star on GitHub</a></div></section>
  <footer class="lp-foot"><div class="lp-lfg">Let's F<span>**</span>king go.</div>
    <div class="lp-foot-row">${lfgMark()}<span class="muted small">Runs on your computer · never pushes or deploys · open source</span><span class="grow"></span><a href="#studio">Dashboard</a><a href="#help">Help</a></div></footer>
  </div>`;
};

/* The landing page: sections animate in as they scroll into view (once; none with reduced motion) */
function wireLanding(root) {
  const parts = $$("#lp-editors, .lp-reveal", root), win = $(".lp-win", root);
  if (!("IntersectionObserver" in window) || matchMedia("(prefers-reduced-motion: reduce)").matches) {
    parts.forEach(x => x.classList.add("in"));
    if (win) { $$(".lp-win-steps li", win).forEach(li => { li.className = "done"; }); $(".lp-win-ask", win).classList.add("on", "ok"); $(".lp-win-done", win).classList.add("on"); }
    launchVideo();
    return;
  }
  if (win) heroRun(win);
  launchVideo();
  const io = new IntersectionObserver(es => es.forEach(x => { if (x.isIntersecting) { x.target.classList.add("in"); io.unobserve(x.target); } }), { threshold: 0.2 });
  parts.forEach(x => io.observe(x));
}

/* The launch film, offered once on the home page. It counts as seen the moment it shows (tours.json, and this
   browser as a fallback), so quitting `lfg ui` or closing the tab mid-film doesn't bring it back: the next start goes
   straight to the home page, and the film stays on it under "The launch film". It waits until the first-run setup
   guide is done so the two never stack. */
const LAUNCH_VIDEO = "https://github.com/user-attachments/assets/bcc10777-99ec-4f32-9b55-19702dbade8f";
async function launchVideo() {
  if ($(".lv")) return;
  let t;
  try { t = await api("tours"); } catch (e) { return; }
  let local = null;
  try { local = localStorage.getItem("lfg.launchVideo"); } catch (e) { /* private window */ }
  if (!t || t.launch_video_seen || local || !t.setup_guide_done || (location.hash.slice(1).split("/")[0] || "lfg") !== "lfg") return;
  try { localStorage.setItem("lfg.launchVideo", "seen"); } catch (e) { /* private window */ }
  save("tour_done", { name: "launch-video", how: "finished" });  // seen once it shows, whatever happens next
  const box = document.createElement("div");
  box.className = "lv";
  box.innerHTML = `<div class="lv-shade"></div><video class="lv-v" src="${LAUNCH_VIDEO}" playsinline preload="auto" aria-label="The LFG launch film"></video>`;
  document.body.appendChild(box);
  const v = $(".lv-v", box);
  let gone = false;
  const close = () => {
    if (gone) return;
    gone = true;
    try { v.pause(); } catch (e) { /* ignore */ }
    box.remove();
    document.removeEventListener("keydown", onKey, true);
    document.removeEventListener("pointerdown", unmute, true);
  };
  // Browsers only autoplay with sound after the page has had a click or key press. If this one refuses, play muted
  // and turn the sound on at the first click or key press, which then also counts as permission to play.
  const unmute = () => { v.muted = false; v.play().catch(() => {}); document.removeEventListener("pointerdown", unmute, true); };
  const onKey = e => { if (e.key === "Escape") close(); else unmute(); };
  document.addEventListener("keydown", onKey, true);
  box.addEventListener("click", e => { if (e.target === v) { if (v.muted) return; v.paused ? v.play() : v.pause(); } else close(); });
  v.addEventListener("ended", close);
  window.addEventListener("hashchange", close, { once: true });
  v.play().catch(() => { v.muted = true; v.play().catch(() => {}); document.addEventListener("pointerdown", unmute, true); });
}

/* The hero's window plays a whole run: each stage works, then is done; the permission prompt shows up during Build
   and is allowed; then "Ready to commit", a pause, and again. Stops once the page is left. */
function heroRun(win) {
  const steps = $$(".lp-win-steps li", win), ask = $(".lp-win-ask", win), done = $(".lp-win-done", win);
  const set = (li, st) => { li.className = st; $("em", li).textContent = st === "run" ? "working…" : ""; };
  let t = 0;
  const at = (ms, fn) => setTimeout(() => { if (document.body.contains(win)) fn(); }, t += ms);
  const play = () => {
    t = 0;
    steps.forEach(li => set(li, "todo")); ask.classList.remove("on", "ok"); done.classList.remove("on");
    steps.forEach((li, i) => {
      at(i ? 250 : 1400, () => set(li, "run"));
      if (li.dataset.step === "Build") { at(1000, () => ask.classList.add("on")); at(1100, () => ask.classList.add("ok")); }
      at(li.dataset.step === "Build" ? 900 : 1150, () => set(li, "done"));
    });
    at(300, () => done.classList.add("on"));
    at(4500, play);
  };
  play();
}

/* The setup guide: run `lfg init` in a repo, turn LFG on for it in Settings, hardened mode, and where to find this
   again. The first time, it opens by itself and has to be finished: no close button, Escape and clicks outside do
   nothing. The ⓘ button in the top bar opens it any time. Steps on Settings light up the real controls, which stay
   usable (the dimmed parts around them are not). */
const SG_STEPS = [
  { title: "Set up LFG in three steps", next: "Start", body: () => `<p>Two minutes, once. LFG only works in repos you turn it on for, so let's do that for your first one.</p>
      <ol class="sg-list"><li><div><b>Run <code>lfg init</code></b> in your repo</div><span>builds the code map LFG's agents read</span></li>
        <li><div><b>Turn LFG on</b> for it in Settings</div><span>skills, guard and hooks, in that repo only</span></li>
        <li><div><b>Choose hardened mode</b></div><span>a second lock, enforced by Claude Code itself</span></li></ol>` },
  { title: "1 · Run lfg init in your repo", body: () => `<p>In a terminal, go to the project you want LFG to work on and run:</p>
      <div class="sg-cmd"><pre id="sg-cmd">cd path/to/your-repo
lfg init</pre><button class="btn small" data-copy="sg-cmd">Copy</button></div>
      <p class="muted small">It builds the code map (a minute or two the first time). The repo then shows up in the project picker and in Settings.</p>
      <div class="sg-found" id="sg-found"></div>`,
    live: card => {
      const box = $("#sg-found", card);
      const tick = async () => {
        const r = await api("repos").catch(() => null), n = (r && r.repos) || [];
        if (box.isConnected) box.innerHTML = n.length ? `${dot("ok")}<span>LFG sees ${n.length === 1 ? "" : `${n.length} repos: `}<b>${n.slice(0, 3).map(x => esc(x.name || x.id)).join(", ")}</b>${n.length > 3 ? "…" : ""}</span>`
          : `${dot("warn")}<span>No repo yet. Run <code>lfg init</code> in one and it shows up here.</span>`;
      };
      tick(); return setInterval(tick, 3000);
    } },
  { title: "2 · Turn LFG on for that repo", page: "settings", tab: "claudecode", target: "#cc-where",
    body: () => `<p>Find your repo in this list and press <b>Turn on</b>. Claude Code then gets LFG's skills, guard and hooks in that repo; every other repo stays exactly as it was.</p><p class="muted small">Same as running <code>lfg enable</code> inside the repo.</p>` },
  { title: "3 · Hardened mode", page: "settings", tab: "claudecode", target: "#cc-hardened",
    body: () => `<p>Recommended. On top of LFG's guard, it writes Claude Code's own deny rules (commit and push, secret files) into each LFG repo's <code>.claude/settings.local.json</code>, so Claude Code itself refuses them too.</p><p class="muted small">Never touches your user settings. Same as <code>lfg enable --hardened</code>.</p>` },
  { title: "Find this again any time", target: "#guide-btn", next: "Finish",
    body: () => `<p>This guide lives behind the <b>ⓘ</b> button in the top bar. Every command LFG understands is under <a href="#help">Help</a>, and these switches stay in <b>Settings → Claude Code</b>.</p>` },
];
function setupGuide(first) {
  if ($("#sg")) return;
  const back = location.hash || "#studio";
  const root = document.createElement("div");
  root.id = "sg"; root.className = "sg";
  root.innerHTML = `${'<div class="sg-m"></div>'.repeat(4)}<div class="sg-ring" hidden></div><div class="sg-card" role="dialog" aria-modal="true" aria-labelledby="sg-t" tabindex="-1"></div>`;
  document.body.append(root); document.body.classList.add("sg-open");
  const card = $(".sg-card", root), masks = $$(".sg-m", root), ring = $(".sg-ring", root);
  let target = null, live = null;  // target: the selector being lit up (pages re-render, so it's found again each time)
  const place = () => {
    const vw = innerWidth, vh = innerHeight, el = target && $(target);
    if (!el) {
      masks[0].style.cssText = "left:0;top:0;width:100%;height:100%"; masks.slice(1).forEach(m => { m.style.cssText = "display:none"; });
      ring.hidden = true; card.classList.add("center"); card.style.cssText = ""; return;
    }
    const r = el.getBoundingClientRect(), p = 8;
    const x = Math.max(0, r.left - p), y = Math.max(0, r.top - p), x2 = Math.min(vw, r.right + p), y2 = Math.min(vh, r.bottom + p);
    masks[0].style.cssText = `left:0;top:0;width:100%;height:${y}px`;
    masks[1].style.cssText = `left:0;top:${y2}px;width:100%;height:${Math.max(0, vh - y2)}px`;
    masks[2].style.cssText = `left:0;top:${y}px;width:${x}px;height:${y2 - y}px`;
    masks[3].style.cssText = `left:${x2}px;top:${y}px;width:${Math.max(0, vw - x2)}px;height:${y2 - y}px`;
    ring.hidden = false; ring.style.cssText = `left:${x}px;top:${y}px;width:${x2 - x}px;height:${y2 - y}px`;
    card.classList.remove("center");
    const cw = card.offsetWidth, ch = card.offsetHeight;
    const top = y2 + 14 + ch <= vh ? y2 + 14 : y - 14 - ch >= 0 ? y - 14 - ch : Math.max(12, vh - ch - 12);
    card.style.cssText = `left:${Math.min(Math.max(12, x2 - cw), vw - cw - 12)}px;top:${top}px`;
  };
  const waitFor = async (sel, tab) => {
    for (let k = 0; k < 300; k++) {  // Settings → Claude Code reads Claude Code's setup first: give it time
      if (tab) { const b = $(`[data-tabs="settings"] .tab[data-k="${tab}"]`); if (b && !b.classList.contains("on")) b.click(); }
      const el = $(sel); if (el) return el;
      await new Promise(r => setTimeout(r, 100));
    }
    return null;
  };
  const keys = e => {  // Esc skips it, like Skip; Tab stays inside the card
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); finish(); }
    if (e.key === "Tab") { const f = $$("button, a[href]", card); if (f.length && !card.contains(document.activeElement)) { e.preventDefault(); f[0].focus(); } }
  };
  const timer = setInterval(place, 250);
  addEventListener("resize", place); document.addEventListener("keydown", keys, true);
  let seq = 0;
  const show = async i => {
    const s = SG_STEPS[i], mine = ++seq;
    clearInterval(live); live = null; target = null;
    if (s.page && (location.hash.slice(1).split("/")[0] || "") !== s.page) location.hash = "#" + s.page;
    card.innerHTML = `<div class="sg-dots" aria-hidden="true">${SG_STEPS.map((_, k) => `<i class="${k === i ? "on" : k < i ? "done" : ""}"></i>`).join("")}</div>
      <h2 id="sg-t">${s.title}</h2><div class="sg-b">${s.body()}</div>
      <div class="sg-a"><button class="link" data-sg="skip" title="Close the guide. The ⓘ button in the top bar opens it again.">Skip</button>${i ? '<button class="btn" data-sg="back">Back</button>' : ""}<span class="grow"></span><span class="muted small">${i + 1} of ${SG_STEPS.length}</span><button class="btn primary" data-sg="next">${s.next || "Next"}</button></div>`;
    place(); card.focus();
    if (s.live) live = s.live(card);
    const bk = $('[data-sg="back"]', card); if (bk) bk.onclick = () => show(i - 1);
    $('[data-sg="skip"]', card).onclick = () => finish();
    $('[data-sg="next"]', card).onclick = () => i < SG_STEPS.length - 1 ? show(i + 1) : finish();
    $$("a[href^='#']", card).forEach(a => a.onclick = e => e.preventDefault());  // links are pointers here, not exits
    if (!s.target) return;
    const wait = document.createElement("p"); wait.className = "muted small sg-wait"; wait.textContent = s.page ? "Loading Settings…" : "";
    if (s.page && !$(s.target)) $(".sg-b", card).append(wait);
    const el = await waitFor(s.target, s.tab);
    if (mine !== seq) return;  // moved on meanwhile
    wait.remove();
    if (el) { target = s.target; el.scrollIntoView({ block: "center" }); place(); }
  };
  const finish = () => {
    clearInterval(timer); clearInterval(live); removeEventListener("resize", place); document.removeEventListener("keydown", keys, true);
    root.remove(); document.body.classList.remove("sg-open");
    if (first) save("tour_done", { name: "setup-guide" });
    if (location.hash !== back) location.hash = back;
  };
  show(0);
}
document.addEventListener("click", e => { if (e.target.closest("#guide-btn")) setupGuide(false); });

/* Star buttons: with the GitHub CLI signed in, one click stars it from your account; otherwise they open GitHub */
document.addEventListener("click", async e => {
  const b = e.target.closest("[data-gh-star]");
  if (!b || b.dataset.busy) return;
  const g = state.gh;  // fetched at startup, so this click can decide now
  if (!g || !g.ready) return;  // not signed in: the link opens github.com as usual
  e.preventDefault();
  if (g.starred) { b.textContent = "★ Starred, thank you"; return; }
  b.dataset.busy = "1"; b.textContent = "Starring…";
  const r = await save("github_star", {});
  b.textContent = r.ok && r.starred ? "★ Starred, thank you" : "★ Star on GitHub";
  if (r.ok && r.starred) state.gh = Object.assign({}, g, { starred: true });
  delete b.dataset.busy;
  if (!(r.ok && r.starred)) window.open(r.url || b.href, "_blank", "noopener");
}, true);
/* In-page links on the home page scroll to their section; the hash stays #lfg, so the router never sees them */
document.addEventListener("click", e => {
  const a = e.target.closest("[data-scroll]");
  if (!a) return;
  e.preventDefault();
  const el = a.dataset.scroll === "top" ? null : document.getElementById(a.dataset.scroll);
  if (a.dataset.scroll !== "top" && !el) return;
  const top = el ? Math.max(0, el.getBoundingClientRect().top + scrollY - 68) : 0, from = scrollY;
  const calm = document.documentElement.dataset.motion === "off" || matchMedia("(prefers-reduced-motion: reduce)").matches;
  window.scrollTo({ top, behavior: calm ? "auto" : "smooth" });
  setTimeout(() => { if (scrollY === from && Math.abs(top - from) > 4) window.scrollTo(0, top); }, 350);  // smooth scrolling unsupported
});
/* The first-run intro: one feature per step, each with its snapshot, then pick what to use. */
const JOURNEY = [
  { k: "Welcome", t: "Welcome to LFG", d: "You're about to stop writing code and start directing it. Here's the 60-second version of how.", v: () => `<div class="jv-stack">${MOCK.run()}</div>` },
  { k: "The flow", t: "One sentence in, a checked change out", d: "Say what you want in Claude Code. LFG grills it into a brief, plans small slices, builds them test-first and checks everything before you see it.", v: () => `<ol class="lp-flow mini">${FLOW.map(([t, c], i) => `<li><span class="lp-n">${String(i + 1).padStart(2, "0")}</span><b>${t}</b><code>${esc(c)}</code></li>`).join("")}</ol>` },
  { k: "Reviews", t: "Talk to the diff", d: "Ask about a single line or a single review comment and get an answer from the code. Decide what to fix without opening a file.", v: () => MOCK.diff() },
  { k: "Insights", t: "Know what to ask before you approve", d: "The fragile files a change touches, the tests it skipped and the team decisions it might break, as questions.", v: () => MOCK.questions() },
  { k: "History", t: "Why is this code here?", d: "Every function's story: the commits that shaped it, with the PRs and tickets behind them.", v: () => MOCK.why() },
  { k: "Guard", t: "Agents can't do the scary things", d: "No pushes, no deploys, no reading secrets. Commits ask you first. Enforced on every command.", v: () => MOCK.guard() },
];
const OBS = { step: 0 };
async function journeyPicker() {
  const d = await api("onboarding");
  const unlocked = await isUnlocked();
  const tile = f => {
    const on = d.complete ? f.enabled : f.id === "coding";
    return `<label class="wl-tile"><input type="checkbox" data-feature="${esc(f.id)}" ${on ? "checked" : ""} ${unlocked ? "" : "disabled"}><span class="wl-check" aria-hidden="true"></span>
      <span class="wl-ico">${icon(FEATURE_ICON[f.id] || "home")}</span><b>${esc(f.name)}</b><span class="wl-desc">${esc(f.description)}</span>
      ${(f.page_titles || []).length ? `<span class="wl-pages">${f.page_titles.map(t => `<span class="tag blue">${esc(t)}</span>`).join("")}</span>` : ""}<span class="wl-skills">${(f.skills || []).slice(0, 4).map(k => `<code>${esc(k)}</code>`).join(" ")}</span></label>`;
  };
  return `${unlocked ? "" : `<div class="callout wl-note">Read-only. To change anything, run <code>lfg ui</code> in your own terminal.</div>`}
    <div class="wl-pick-h"><div><h2>What will you use?</h2><p class="muted">The sidebar shows only these pages. Change it any time in Settings.</p></div><span class="tag blue" id="wl-count"></span></div>
    <div class="wl-grid">${(d.features || []).map(tile).join("")}</div>
    <div class="wl-actions"><button class="btn primary big" id="onboard-save" ${unlocked ? "" : "disabled"}>Start with these</button><button class="btn big" id="onboard-skip" ${unlocked ? "" : "disabled"}>Show me everything</button><span class="save-msg" id="onboard-msg"></span><span class="grow"></span><a class="btn big" href="https://github.com/varun-singhh/lfg" target="_blank" rel="noopener noreferrer" data-gh-star>★ Star LFG on GitHub</a></div>`;
}
PAGES.onboarding = async arg => {
  OBS.step = arg === "pick" ? JOURNEY.length : 0;
  return `<div class="ob">
    <header class="lp-nav">${lfgMark()}<span class="grow"></span><a class="ob-skip" href="#onboarding/pick" data-ob-skip>Skip intro</a></header>
    <div id="ob-body"></div></div>`;
};
async function drawJourney(root) {
  const body = $("#ob-body", root);
  if (!body) return;
  const i = OBS.step, last = JOURNEY.length;
  const dots = `<div class="ob-dots">${JOURNEY.concat([{ k: "Pick" }]).map((s, j) => `<button class="ob-dot${j === i ? " on" : j < i ? " done" : ""}" data-ob-go="${j}" aria-label="${esc(s.k)}"><span></span>${esc(s.k)}</button>`).join("")}</div>`;
  if (i >= last) {
    body.innerHTML = `${dots}<section class="wl-pick ob-pick">${await journeyPicker()}</section>`;
    wireOnboarding(root);
  } else {
    const s = JOURNEY[i];
    body.innerHTML = `${dots}<section class="ob-card"><div class="ob-copy"><span class="tag blue">${esc(s.k)}</span><h1>${esc(s.t)}</h1><p>${esc(s.d)}</p>
      <div class="ob-nav">${i ? '<button class="btn big" data-ob="back">Back</button>' : ""}<button class="btn primary big" data-ob="next">${i === last - 1 ? "Pick what you'll use →" : "Next →"}</button></div>
      <div class="muted small">${i + 1} of ${last}</div></div><div class="ob-vis" aria-hidden="true">${s.v()}</div></section>`;
  }
  $$("[data-ob-go]", body).forEach(b => b.onclick = () => { OBS.step = +b.dataset.obGo; drawJourney(root); });
  const nx = $('[data-ob="next"]', body); if (nx) nx.onclick = () => { OBS.step++; drawJourney(root); };
  const bk = $('[data-ob="back"]', body); if (bk) bk.onclick = () => { OBS.step--; drawJourney(root); };
  const sk = $("[data-ob-skip]", root); if (sk) sk.onclick = e => { e.preventDefault(); OBS.step = last; drawJourney(root); };
}

/* A tour for every dashboard page: the Tour button in the top bar starts the one for the page you're on. */
const PAGE_TOURS = {
  studio: [
    { sel: "#nav", title: "Your dashboard", body: () => "Everything LFG does, by what you're doing: <b>Your work</b> (runs, todos, reviews, checks), <b>This project</b> (code, insights, docs) and <b>LFG</b> itself (usage, skills, settings)." },
    { sel: "#repo", title: "Pick a project", body: () => "Every page shows the project picked here, and the branch below it narrows runs and checks to one branch." },
    { sel: "#ss-comp", title: "Studio", body: () => "Run Claude Code here: describe the task, <code>/</code> for skills, <code>@</code> for files, drop in screenshots. Sessions from your terminal and the desktop app show up too. In the terminal, <code>/rename</code> gives a session a readable name here." },
    { sel: "#bell", title: "Notifications", body: () => "When a check finishes, a run needs a decision or a review is ready, it shows up here." },
    { sel: "#tour-btn", title: "A tour on every page", body: () => "Press <b>Tour</b> on any page to see what it's for." },
  ],
  sessions: [{ title: "Sessions", body: () => "Every Claude Code session on this computer, from the terminal, the desktop app or here. Star the ones to keep, and group them by project or PR." }, { title: "Give a session a name", body: () => "In Claude Code, type <code>/rename</code> and a name. This page then shows that name instead of the first thing you asked, so you can find the session later." }],
  todos: [{ sel: "[data-td-add]", title: "Add a todo", body: () => "Type and press Enter. It's tagged with the project you're in." }, { sel: ".td-st", title: "Status", body: () => "Click the coloured tag to move it along: to do, in progress, done." }, { sel: ".td-a", title: "Linear and notes", body: () => "Turn any todo into a Linear ticket, or add notes." }],
  runs: [{ title: "Runs", body: () => "Every request you give LFG becomes a run: brief, plan, build, checks, review and ship, with each stage's files." }, { sel: ".runs-bar", title: "Find a run", body: () => "Search by what it was for, its branch or its issue." }],
  review: [{ title: "Reviews", body: () => "Review pull requests and AI chats here. Open one to see the diff, the comments and a chat beside it." }, { sel: ".rv-top", title: "Start a review", body: () => "Pick a pull request or a chat. LFG reads the diff and its callers before it says anything." }, { title: "Talk to the diff", body: () => "In a review, click a line number to ask about that line, or <b>Discuss</b> on a comment to argue with it. Mark each comment <b>Will fix</b> or <b>Not now</b>." }],
  checks: [{ sel: ".view .cols", title: "Latest checks", body: () => "The newest code review, security check and ship check for this project, and what they found." }, { sel: ".view .tabs", title: "Findings", body: () => "Every finding with what's wrong, why it matters and what to do, sorted by severity." }],
  code: [{ title: "Code", body: () => "The code map LFG's agents read instead of whole files, and the architecture's health." }],
  insights: [{ sel: '[data-tabs="insights"]', title: "Three questions", body: () => "<b>Your changes</b>: is this safe to approve? <b>Hotspots</b>: where does this code break? <b>Files</b>: what is this and why is it like this?" }, { sel: "#ins-changes", title: "Before you approve", body: () => "The questions a senior engineer would ask, the fragile files you touched and the problems that keep coming back." }],
  docs: [{ sel: ".doc-nav", title: "Docs", body: () => "LFG's wiki for this project and the docs you asked for: project-wide at the top, then one folder per branch." }],
  knowledge: [{ title: "Knowledge", body: () => "Decisions, rules and lessons LFG remembers about this project, and your own notes. Save one with <code>/lfg:note</code>." }],
  usage: [{ title: "Usage", body: () => "What Claude Code cost, by day, model and project, and what Headroom saved." }],
  skills: [{ title: "Skills", body: () => "Every skill Claude Code can load on this computer, yours and every plugin's, with name clashes and how much context they cost." }],
  integrations: [{ sel: ".int-list", title: "Integrations", body: () => "Turn tools on and off: knowledge graphs, Headroom, SonarQube, Dictate, pentests, Linear. Each one installs locally and can be removed." }],
  settings: [{ sel: ".view .tabs", title: "Settings", body: () => "<b>Claude Code</b>: where LFG is on. <b>General</b>: features, updates, models. Every change is backed up and can be undone." }],
  help: [{ title: "Help", body: () => "How LFG works, every command grouped by what it is for, and short answers." }],
};
Object.keys(PAGE_TOURS).forEach(k => Object.defineProperty(TOURS, "page-" + k, { get: () => PAGE_TOURS[k], enumerable: true }));
function wireTourButton(key) {
  const b = $("#tour-btn");
  if (!b) return;
  b.hidden = !PAGE_TOURS[key];
  b.onclick = () => startTour("page-" + key);
}

/* Runs: each with tags (its PR and that PR's state, its issue, a fix run) and whether it still needs anything (done,
   or not needed: its PR merged or closed, its branch merged, or you said so). Search finds runs by meaning: a vector
   search over each run's brief, tasks and notes, on this computer. */
const LIFE = { active: ["Active", "on"], done: ["Done", "ok"], "not-needed": ["Not needed", ""] };
const runTags = r => `${(r.tags || []).map(t => t.href ? `<a class="tg ${t.tone || ""}" href="${esc(t.href)}" target="_blank" rel="noopener noreferrer" title="${esc(t.state ? `${t.text} is ${t.state.toLowerCase()} on GitHub` : t.text)}" data-stop>${esc(t.text)}${t.state === "MERGED" ? " · merged" : t.state === "CLOSED" ? " · closed" : ""}</a>` : `<span class="tg ${t.tone || ""}"${t.title ? ` title="${esc(t.title)}"` : ""}>${esc(t.text)}</span>`).join("")}${r.life && r.life !== "active" ? `<span class="tg${r.life === "done" ? " ok" : " faded"}" title="${esc(r.life_why || "")}">${esc(LIFE[r.life][0])}${r.life_why && r.life === "not-needed" ? ` · ${esc(r.life_why)}` : ""}</span>` : ""}`;
PAGES.home = async () => {
  const d = await api("overview");
  if (d.available === false) return unavailable(d, "No project yet");
  const all = await cachedRuns();
  const stages = all.stages, run = d.run, g = d.graphs || {}, t = d.tokens_7d || {}, hr = d.headroom || {};
  // what needs the user
  const attn = [];
  if (run) runAttention(run).forEach(([tn, text]) => attn.push([tn, text, `#runs/${encodeURIComponent(run.run)}`]));
  if (d.security && d.security.blocking && !(run && run.secure === "don't")) attn.push(["bad", `The latest security check found ${plural(d.security.blocking, "problem")}`, "#checks"]);
  if (g.status === "error") attn.push(["bad", "The code map failed to update", "#code"]);
  (d.integrations || []).filter(x => !x.ok && !x.optional).forEach(x => attn.push(["warn", x.problem || `${x.name} needs attention`, "#settings"]));
  if (d.work && d.work.blocked) attn.push(["warn", `${plural(d.work.blocked, "issue")} blocked by other work`, "#issues"]);
  const worst = attn.some(a => a[0] === "bad") ? "bad" : attn.length ? "warn" : "ok";
  const attnBox = attn.length
    ? `<div class="callout ${worst}"><ul class="attn">${attn.map(([tn, text, href]) => `<li>${dot(tn)}<a class="grow" href="${href}">${fmtWhy(text)}</a><span class="go" aria-hidden="true">→</span></li>`).join("")}</ul></div>`
    : `<div class="callout ok">${dot("ok")}Nothing needs you right now.</div>`;
  // the current run
  let now;
  if (run) {
    const p = runPlace(stages, run.stages, run);
    now = `<a class="now" href="#runs/${encodeURIComponent(run.run)}">
      <h2>${esc(runName(run))}</h2>
      ${run.about ? `<p class="about">${txt(run.about)}</p>` : ""}
      <div class="meta">${run.owner ? `Filed under ${esc(run.owner_name)}${run.branch ? ` (branch ${esc(run.branch)})` : ""} · started ${ago(run.created)} · ${n(run.tasks_here_done)} of ${plural(run.tasks_here, "task")} for this repo done` : `${run.branch ? `On branch ${esc(run.branch)} · ` : ""}started ${ago(run.created)}${run.tasks.total ? ` · ${run.tasks.done} of ${plural(run.tasks.total, "task")} done` : ""}`}</div>
      <div class="progress${p.blocked ? " stuck" : p.finished ? " done" : ""}"><span style="width:${pct(p.done, p.total)}%"></span></div>
      <div class="next${p.blocked ? " stuck" : ""}">${p.finished ? "All steps done. The commit message is ready for you." : `${p.done} of ${p.total} steps · next: ${esc(NEXT[p.next])}`}</div></a>`;
  } else {
    now = `<div class="box">${empty("Nothing in progress", "Start in Claude Code with <code>/lfg:lfg</code> and a short description of what you want, or <code>/lfg:wizard</code> for a guided run.")}</div>`;
  }
  const recent = all.runs.filter(r => !run || r.run !== run.run).slice(0, 5);
  const recentBox = recent.length ? `<div class="box"><ul class="list">${recent.map(r => `<li class="click" data-href="#runs/${encodeURIComponent(r.run)}"><div class="grow"><div class="title">${esc(runName(r))}</div>${r.about ? `<div class="about clamp">${txt(r.about)}</div>` : ""}<div class="meta">${esc(runLine(r, stages))}</div></div><span class="muted small nowrap">${ago(r.created)}</span></li>`).join("")}</ul></div>` : "";
  const used = (t.input || 0) + (t.output || 0) + (t.cache_read || 0) + (t.cache_write || 0);
  const cached = pct(t.cache_read || 0, used - (t.output || 0));
  const saved = hr.available && hr.lifetime && hr.lifetime.tokens_saved;
  return `${head(repoName() || "Home", `${run ? "What LFG is doing in this project" : "Nothing in progress in this project"}${state.branch ? `, on ${esc(state.branch === "-" ? "unrecorded branches" : state.branch)}` : ""}.`)}
    ${section(run ? "Working on" : "Current work", now)}
    ${section("Needs your attention", attnBox)}
    ${recent.length ? section("Earlier runs", recentBox, `<a href="#runs">See all ${n(all.runs.length)}</a>`) : ""}
    ${section("This week", `<div class="cols">${(d.spend || {}).available ? stat("AI cost", usd(d.spend["7d"]), `${compact(used)} tokens, all projects${saved ? ` · ${compact(saved)} saved by compression` : ""}`) : stat("AI tokens", compact(used), `all projects, last 7 days · ${cached}% from cache${saved ? ` · ${compact(saved)} saved by compression` : ""}`)}${stat("Code map", say(g.status)[0] || "Unknown", `${g.status === "missing" ? "not built yet" : g.synced_at ? `updated ${ago(g.synced_at)}` : ""} ${mapBtn(g.status)}`)}${d.work && !d.work.why ? stat("Issues ready to start", n(d.work.ready), d.work.blocked ? `${n(d.work.blocked)} blocked` : "none blocked") : d.work ? stat("Issues", "Not available", fmtWhy(d.work.why)) : ""}</div>`)}`;
};

PAGES.runs = async arg => {
  if (arg) return runDetail(arg);
  const d = await cachedRuns();
  if (d.available === false) return unavailable(d);
  const v = state.runsView = Object.assign({ filter: "active", q: "", hits: null, engine: null }, state.runsView || {});
  const count = k => d.runs.filter(r => k === "all" || (r.life || "active") === k).length;
  const chip = (k, label) => `<button class="pill${v.filter === k ? " on" : ""}" data-runs-filter="${k}">${label} <span class="muted">${count(k)}</span></button>`;
  return `${head("Runs", "Each run is one piece of work LFG took from idea to a commit you can review. Click one to see where it is.")}
    <div class="runs-bar"><input type="search" id="runs-q" placeholder="Search runs by what they're about, e.g. &quot;partition id on windows&quot;" value="${esc(v.q)}" autocomplete="off">
      <span class="seg">${chip("active", "Active")}${chip("done", "Done")}${chip("not-needed", "Not needed")}${chip("all", "All")}</span></div>
    <div id="runs-note" class="muted small"></div>
    <div class="box" id="runs-box"></div>`;
};
function runsTable() {
  const d = state.cache["runs:" + state.repo], v = state.runsView, box = $("#runs-box");
  if (!d || !box) return;
  let rows = d.runs.filter(r => v.filter === "all" || (r.life || "active") === v.filter);
  if (v.hits) {  // search: only matches, best first
    const rank = Object.fromEntries(v.hits.map((h, i) => [h.run, [i, h.score]]));
    rows = d.runs.filter(r => rank[r.run] && (v.filter === "all" || (r.life || "active") === v.filter)).sort((x, y) => rank[x.run][0] - rank[y.run][0]);
    rows.forEach(r => { r.match = rank[r.run][1]; });
  }
  box.innerHTML = table(rows, [
    { k: "slug", label: "Work", html: r => `${esc(runName(r))}${r.current ? ' <span class="tag">current</span>' : ""}${v.hits && r.match != null ? ` <span class="tg on" title="How close it is to your search">${Math.round(r.match * 100)}% match</span>` : ""}${r.about ? `<div class="about clamp">${txt(r.about)}</div>` : ""}<div class="sub">${r.owner ? `filed under ${esc(r.owner_name)} · ${plural(r.tasks_here, "task")} for this repo, ${n(r.tasks_here_done)} done` : r.branch ? `<span class="brtag">${esc(r.branch)}</span>` : ""}</div><div class="run-tags">${runTags(r)}</div>`, sort: r => runName(r) },
    { k: "progress", label: "Where it is", html: r => esc(runLine(r, d.stages)), sort: r => r.progress },
    { k: "attn", label: "Status", html: r => { if (r.fix && r.fix.working) return `<span class="st">${dot("on")}AI working</span>`; if (r.life === "not-needed") return `<span class="st">${dot("")}${esc(r.life_why || "Not needed")}</span>`; const a = runAttention(r); return a.length ? `<span class="st" title="${esc(a[0][1])}">${dot(a[0][0])}${esc(a[0][2])}${a.length > 1 ? ` +${a.length - 1}` : ""}</span>` : `<span class="st">${dot("ok")}${r.life === "done" ? "Done" : "On track"}</span>`; }, sort: r => runAttention(r).length },
    { k: "created", label: "Started", html: r => `<span class="nowrap">${ago(r.created)}</span>` },
  ], { filter: false, onRow: r => (location.hash = "#runs/" + encodeURIComponent(r.run)), emptyTitle: v.hits ? "No run matches that" : v.filter === "active" ? "Nothing active" : "No runs here", emptyBody: v.hits ? "Try other words, or the All filter." : v.filter === "active" ? "Every run is done or not needed. See Done or All." : "Start one in Claude Code with <code>/lfg:lfg</code> and what you want built." });
  mountTables(box);
}
let runsTimer = null;
function wireRuns(root) {
  if (!$("#runs-box", root)) return;
  const v = state.runsView, note = $("#runs-note", root);
  const engineNote = r => {
    if (!r || !r.engine) { note.innerHTML = ""; return; }
    note.innerHTML = r.engine === "embeddings" ? `Searching by meaning with <code>${esc(r.model)}</code> on your Ollama.`
      : `Word-based vector search (TF-IDF). For search by meaning, install the local embedding model <code>${esc(r.model)}</code> (about 270 MB, from the Ollama library, runs only on your Ollama): <button class="btn small" id="runs-model">Install</button>`;
    const b = $("#runs-model", note);
    if (b) b.onclick = async () => { b.disabled = true; b.textContent = "Installing…"; const s = await save("ollama_pull", { name: r.model }); note.innerHTML = s.ok ? "Downloading the model in the background; search uses it once it's ready." : fmtWhy(s.why || "Couldn't start the download."); };
  };
  const run = async () => {
    const q = $("#runs-q", root).value.trim(); v.q = q;
    if (!q) { v.hits = null; engineNote(null); return runsTable(); }
    note.innerHTML = '<span class="spin"></span> Searching…';
    const r = await api("runs_search", { q });
    if (v.q !== q) return;  // a newer search is on its way
    v.hits = r.results || []; engineNote(r); runsTable();
  };
  $("#runs-q", root).oninput = () => { clearTimeout(runsTimer); runsTimer = setTimeout(run, 350); };
  $$("[data-runs-filter]", root).forEach(b => b.onclick = () => { v.filter = b.dataset.runsFilter; $$("[data-runs-filter]", root).forEach(x => x.classList.toggle("on", x === b)); runsTable(); });
  if (v.q) run(); else runsTable();
}

const FILE_NAMES = { "01-brief.md": "The idea, written up", "02-design.md": "The plan", "tasks.json": "Task list", "04-qa.md": "Test report",
  "ready.json": "Check results", "05-secure.json": "Security check", "05-pentest.json": "Security test", "06-review.json": "Code review",
  "07-shipcheck.json": "Ship check", "COMMIT_MSG.md": "Commit message", "PR_BODY.md": "Pull request text", "progress.md": "Progress notes" };
const fileName = f => FILE_NAMES[f] || (/^03-build-(.+)\.md$/.test(f) ? `Build notes · ${f.slice(9, -3)}` : null);
/* documents in pipeline order: brief, plan, tasks, build notes, tests, checks, security, review, ship, packet, notes */
const FILE_ORDER = ["01-brief.md", "02-design.md", "tasks.json", "03-build-", "04-qa.md", "ready.json", "05-secure.json", "05-pentest.json",
  "06-review.json", "07-shipcheck.json", "COMMIT_MSG.md", "PR_BODY.md", "progress.md"];
const fileRank = f => { const i = FILE_ORDER.findIndex(x => f === x || (x.endsWith("-") && f.startsWith(x))); return i < 0 ? 99 : i; };

// ------------------------------------------------------------------ stacked PRs and their epic
/* One component in two sizes: a strip (run page, PR page: this PR, its neighbors and a line about the epic) and the
   full view (Issues: the epic in build order and every stack in the repo). It loads after the page shows, since the
   first GitHub read can take several seconds. */
const STACK_STATE = { draft: ["Draft", ""], open: ["Open", "on"], approved: ["Approved", "ok"], changes: ["Changes asked", "warn"],
  merged_parent: ["Merged into the PR below", "ok"], merged_main: ["Merged into main", "ok"], closed: ["Closed", ""], no_pr: ["No PR yet", ""] };
const CHECK_WORD = { pass: ["passing", "ok"], fail: ["failing", "bad"], pending: ["running", "warn"] };
/* What each strip last showed, for a minute: a page that refreshes itself (a running review) draws it at once
   instead of flashing the placeholder every time. */
const stackSeen = new Map();
const stackBox = (params, mode) => {
  const key = JSON.stringify([params, mode]), hit = stackSeen.get(key);
  if (hit && Date.now() - hit.at < 60000) return `<div class="stack-box">${hit.html}</div>`;
  return `<div class="stack-box" data-stack="${esc(key)}"><div class="skeleton stack-skel"></div></div>`;
};
function wireStacks(root) {
  $$("[data-stack]", root).forEach(async el => {
    const [params, mode] = JSON.parse(el.dataset.stack);
    delete el.dataset.stack;
    let d;
    try { d = await api("stack", params); } catch (e) { d = { available: false, why: String(e.message || e) }; }
    const html = stackHtml(d, mode);
    stackSeen.set(JSON.stringify([params, mode]), { at: Date.now(), html });
    if (document.body.contains(el)) el.innerHTML = html;
  });
}
function stackTicket(d, key) {
  const t = ((d.epic || {}).items || []).find(i => i.key === key) || (d.epic && d.epic.key === key ? d.epic : null);
  const name = `${esc(key)}${t && t.title ? ` <span class="stack-tt">${esc(t.title)}</span>` : ""}`;
  return d.linear_workspace ? `<a class="stack-tk" href="https://linear.app/${encodeURIComponent(d.linear_workspace)}/issue/${encodeURIComponent(key)}" target="_blank" rel="noopener noreferrer">${name} ↗</a>` : `<span class="stack-tk">${name}</span>`;
}
const stackRun = r => r ? `<a class="small" href="#runs/${encodeURIComponent(r.run)}">LFG run: ${r.done} of ${r.total} steps</a>` : "";
const stackPr = (d, p) => p.number ? `<a class="mono" href="#prs/${esc(d.gh_repo)}/${p.number}">#${p.number}</a>${p.url ? ` <a class="small" href="${esc(p.url)}" target="_blank" rel="noopener noreferrer" title="Open on GitHub">↗</a>` : ""}` : `<span class="mono">${esc(p.branch)}</span>`;
function stackRow(d, p, i) {
  const [word, tone] = STACK_STATE[p.state] || [words(p.state), ""];
  const check = (who, v) => v ? tagHtml(`${who} ${CHECK_WORD[v][0]}`, CHECK_WORD[v][1]) : "";
  const below = p.parent === d.default ? d.default : p.inferred ? "the branch below" : "the PR below";
  return `<li class="stack-row${p.here ? " here" : ""}"><span class="stack-n">${i + 1}</span><div class="grow">
    <div class="stack-t">${stackPr(d, p)} ${esc(p.title || (p.number ? "" : "branch with no PR yet"))}${p.here ? ' <span class="tg on">You are here</span>' : ""}</div>
    <div class="stack-m">${p.ticket ? stackTicket(d, p.ticket) : ""}${tagHtml(word, tone)}${check("CI", p.ci)}${check("CodeRabbit", p.coderabbit)}${p.behind ? tagHtml(`${plural(p.behind, "commit")} behind ${below}`, "warn") : ""}${p.inferred && p.number ? tagHtml(`its PR points at ${d.default}`, "warn") : ""}${stackRun(p.run)}</div></div></li>`;
}
function stackList(d, s) {
  const head = s.kind === "preview" ? `Preview stack on <code>${esc(s.base)}</code>` : `Stack on <code>${esc(s.base)}</code>`;
  const note = s.kind === "preview" ? `<p class="muted small">Not stacked on GitHub yet: LFG worked out from git which branch each one is built on.</p>` : "";
  return `<div class="stack-h"><b>${head}</b><span class="muted small">${plural(s.prs.length, "PR")}, bottom first</span></div>${note}<ol class="stack-list">${s.prs.map((p, i) => stackRow(d, p, i)).join("")}</ol>`;
}
function epicLine(d) {
  const e = d.epic, done = e.items.filter(i => i.done).length, nx = e.items.find(i => i.next);
  return `<div class="stack-epic">Part of ${stackTicket(d, e.key)}: ${done} of ${plural(e.items.length, "ticket")} landed${nx ? ` · next: ${stackTicket(d, nx.key)}` : ""} · <a href="#issues">See the whole epic</a></div>`;
}
function epicFull(d) {
  const e = d.epic, done = e.items.filter(i => i.done).length;
  const row = (i, k) => {
    const pr = i.pr, ps = pr && (STACK_STATE[pr.state] || [words(pr.state), ""]);
    const where = !pr ? '<span class="muted small">no PR yet</span>' : `${stackPr(d, pr)}${tagHtml(ps[0], ps[1])}${i.position ? tagHtml(`${i.position[0]} of ${i.position[1]} in its stack`, "") : pr.state === "merged_main" ? tagHtml("merged on its own", "") : tagHtml("not stacked", "")}`;
    return `<li class="stack-row${i.here ? " here" : ""}${i.done ? " done" : ""}"><span class="stack-n">${k + 1}</span><div class="grow">
      <div class="stack-t">${stackTicket(d, i.key)}${i.here ? ' <span class="tg on">You are here</span>' : ""}${i.next ? ' <span class="tg warn">Next</span>' : ""}</div>
      <div class="stack-m">${tagHtml(i.done ? "Done" : words(i.status || "unknown"), i.done ? "ok" : "")}${where}${i.run ? stackRun(i.run) : '<span class="muted small">no LFG run</span>'}</div></div></li>`;
  };
  return `<div class="stack-card"><div class="stack-h"><b>${e.kind === "parent" ? "Parent ticket" : "Epic"} ${stackTicket(d, e.key)}</b><span class="muted small">${done} of ${plural(e.items.length, "ticket")} landed</span></div>
    <p class="muted small">${e.ordered_by_blocks ? "In build order: each ticket comes after the ones that block it." : "dev-graph has no blocking links for these tickets, so the order is where each PR sits in its stack, then ticket number."} Status is dev-graph's copy of Linear; a PR merged into ${esc(d.default)} counts as done.</p>
    <ol class="stack-list">${e.items.map(row).join("")}</ol></div>`;
}
function stackHtml(d, mode) {
  if (d.available === false) return mode === "full" ? `<p class="muted small">${fmtWhy(d.why)}</p>` : "";
  if (mode !== "full") {
    if (!d.stack && !d.epic) return "";
    return `<div class="stack-card">${d.stack ? stackList(d, d.stack) : ""}${d.epic ? epicLine(d) : ""}</div>`;
  }
  const t = d.here.ticket;
  const epic = d.epic ? epicFull(d) : `<p class="muted small">${t ? `${esc(t)} isn't in an epic or under a parent ticket that dev-graph knows about${d.epic_why ? ` (${fmtWhy(d.epic_why)})` : ""}.` : "Nothing in front of you: start a run or check out a ticket's branch to see its epic here."}</p>`;
  const stacks = d.stacks.length ? d.stacks.map(s => `<div class="stack-card">${stackList(d, s)}</div>`).join("") : `<p class="muted small">No stacked PRs in ${esc(d.gh_repo)}.</p>`;
  return `${epic}<div class="k mt">Stacks in ${esc(d.gh_repo)}</div>${stacks}`;
}

const runLifeBar = (d, run) => d.owner_name ? "" : `<div class="run-life"><div class="run-tags">${runTags(d)}</div><span class="grow"></span>${d.archived
  ? `<button class="btn small" data-run-needed="1" data-run="${esc(run)}">Needed again</button>`
  : `<button class="btn small" data-run-needed="0" data-run="${esc(run)}" title="Hide it from Active; nothing is deleted">Mark not needed</button>`}</div>`;
async function runDetail(run) {
  const [d, all] = await Promise.all([api("run", { run }), cachedRuns()]);
  if (d.available === false) return unavailable(d);
  const p = runPlace(all.stages, d.stages, d), attn = runAttention(d);
  const stuck = { "fix-checks": "gate", "fix-review": "review", "fix-block": "review", "fix-security": "secure", "fix-ship": "ship" }[p.next];
  const keys = all.stages.map(([k]) => k), out = d.outside || {}, skipped = d.skipped || {};
  const steps = `<div class="steps">${keys.map((k, i) => {
    const [cmd, what] = STEP_WHY[k] || ["", ""];
    const doing = (d.doing || []).includes(k);
    const cls = k === stuck ? "stuck" : doing ? "doing" : d.stages[k] ? "done" : out[k] ? "done outside" : skipped[k] != null ? "skipped"
      : k === p.next ? "next" : i < p.last ? "unrecorded" : "todo";
    const state = k === stuck ? "Has a problem: needs fixing" : doing ? "In progress: started, not finished" : d.stages[k] ? "Done" : out[k] ? `Done outside LFG (${plural(out[k], "commit")} on the run's branch)`
      : skipped[k] != null ? `Skipped: ${skipped[k]}` : k === p.next ? "Next: not started" : i < p.last ? "Not recorded: a later step ran without it" : "Not started";
    return `<span class="${cls}" tabindex="0">${esc(STEP[k] || k)}<span class="tip" role="tooltip"><span class="tip-state">${esc(state)}</span><br><code>${esc(cmd)}</code> ${esc(what)}</span></span>`;
  }).join("")}</div><p class="muted small">○ not started · <span class="step-doing">◐ in progress</span> · <span class="step-ok">✓ done</span> · <span class="step-bad">✕ has a problem</span>. Hover a step for what it is. <code>/lfg:lfg</code> runs every step in order; <code>lfg run skip &lt;step&gt; "why"</code> marks one you left out on purpose.</p>`;
  const files = d.files.filter(f => fileName(f.name)).map(f => ({ ...f, run, label: fileName(f.name) }))
    .sort((a, b) => fileRank(a.name) - fileRank(b.name) || a.name.localeCompare(b.name));
  const tasks = d.tasks_list.length ? `<div class="box items">${d.tasks_list.map(taskItem).join("")}</div>` : "";
  const recheck = d.owner_name || !d.current ? "" : d.checking
    ? `<p class="muted small" data-checks-running>Running the checks now (started ${ago(d.checking === true ? "" : d.checking)}). This page updates when they finish; a big project can take several minutes.</p>`
    : `<p><button class="btn small" data-run-checks="${esc(run)}">Run checks again</button> <span class="muted small">lint, types, tests and build, in the background</span></p>`;
  const checks = d.checks.length ? `${recheck}<div class="box items">${readyChecks(d.checks, run)}</div>` : recheck;
  crumbs("runs", runName(d));
  return `${head(runName(d), `${d.ticket ? `<span class="tag mono">${esc(d.ticket)}</span> ` : ""}${d.owner_name ? `Filed under ${esc(d.owner_name)} · ` : ""}${d.branch ? `On branch ${esc(d.branch)} · ` : ""}started ${ago(d.created)}`, '<a class="back" href="#runs">← All runs</a>')}${runLifeBar(d, run)}
    ${d.about ? `<p class="about lead">${txt(d.about)}</p>` : ""}
    ${stackBox({ run }, "strip")}
    <div class="panel"><div class="row"><b>${p.finished ? "All steps done" : `${p.done} of ${p.total} steps done`}</b><span class="muted${p.blocked ? " stuck-text" : ""}">${p.finished ? "· the commit message is ready for you to review" : `· next: ${esc(NEXT[p.next])}`}</span></div>
      <div class="progress${p.blocked ? " stuck" : p.finished ? " done" : ""}"><span style="width:${pct(p.done, p.total)}%"></span></div>${steps}</div>
    ${attn.length ? section("Needs your attention", `<div class="callout ${attn.some(a => a[0] === "bad") ? "bad" : "warn"}"><ul class="attn">${attn.map(([tn, text]) => `<li>${dot(tn)}<span class="grow">${esc(text)}</span></li>`).join("")}</ul></div>`) : ""}
    ${tasks ? section("Tasks", tasks, `${d.tasks.done} of ${d.tasks.total} done · click one for its steps`) : ""}
    ${checks ? section("Checks", d.ready === "stale" && d.checks.length ? `<p class="muted small">These ran ${ago(d.checked_at)}, before the latest work on this run, so they may no longer hold. Run <code>/lfg:check</code> for a fresh result.</p>${checks}` : checks, d.ready === "stale" ? "out of date" : "click a failed one to see why") : d.owner_name ? section("Checks", `<p class="muted small">This run's checks run in ${esc(d.owner_name)}, on its code, so they aren't shown here.</p>`) : ""}
    ${(d.worktrees || []).length ? section("Worktrees", `<div class="box"><ul class="list">${d.worktrees.map(w => `<li><span class="grow mono small">${esc(w.path)}</span><span class="muted small mono">${esc(w.branch)}</span>${w.here ? "" : ' <span class="tag">removed</span>'}</li>`).join("")}</ul></div>`, 'where this run\'s code is being written. <a href="#environment">Environment</a> lists every worktree') : ""}
    ${files.length ? section("Documents", `<div class="box"><ul class="list">${files.map(f => `<li><a href="#" class="grow" data-run-file='${esc(JSON.stringify([f.run, f.name]))}'>${esc(f.label)}</a><span class="muted small nowrap" title="${esc(f.mtime)}">${ago(f.mtime.replace(" ", "T"))}</span></li>`).join("")}</ul></div>`) : ""}`;
}

PAGES.issues = async () => {
  const d = await api("issues");
  if (d.available === false) return `${head("Issues", "Your Linear issues, copied into dev-graph by <code>/lfg:inbox</code>.")}${unavailable(d, "Issues aren't available")}`;
  const ws = d.linear_workspace;
  const key = r => [r.legacyRef, r.slug].find(v => /^[A-Z][A-Z0-9]+-\d+$/.test(v || ""));
  const title = r => {
    const k = key(r), link = k && ws ? ` <a class="small" href="https://linear.app/${encodeURIComponent(ws)}/issue/${encodeURIComponent(k)}" target="_blank" rel="noopener noreferrer">${esc(k)} ↗</a>` : k ? ` <span class="muted small">${esc(k)}</span>` : "";
    const name = !r.title || !/\s/.test(r.title) ? words(String(r.title || r.slug).replace(/^iss-/, "")) : r.title;  // a bare ID reads as words
    return `${esc(name)}${link}`;
  };
  const bySlug = Object.fromEntries(d.issues.map(i => [i.slug, i]));
  const fill = rows => rows.map(r => ({ ...bySlug[r.slug], ...r }));
  const cols = [{ k: "title", label: "Issue", html: title }, { k: "status", label: "Status", html: r => `${st(r.status)}${r.graph_status ? `<div class="sub">finished in its run</div>` : ""}` },
    { k: "branches", label: "Branch", html: r => (r.branches || []).length ? r.branches.map(b => `<code>${esc(b)}</code>`).join(" ") : '<span class="muted">—</span>', sort: r => (r.branches || []).join(" ") },
    { k: "updatedAt", label: "Updated", html: r => `<span class="nowrap">${ago(r.updatedAt)}</span>` }];
  const open = r => openDrawer(r.title || words(r.slug), `<div class="readable"><p>${st(r.status)} <span class="tag">${esc(words(r.issueType || "issue"))}</span>${(r.branches || []).map(b => ` <code>${esc(b)}</code>`).join("")}</p>
    ${r.graph_status ? `<p class="muted small">Its task passed in the run; dev-graph still says ${esc(words(r.graph_status))}.</p>` : ""}
    ${r.text_from ? `<p class="muted small">This text comes from the run's plan (<a href="#runs/${encodeURIComponent(r.text_from)}">${esc(runName({ slug: String(r.text_from).slice(14) }))}</a>); the issue itself was saved without it.</p>` : ""}
    ${r.description ? `<div class="md">${md(r.description)}</div>` : '<p class="muted">No description was written for this issue.</p>'}
    ${r.acceptanceCriteria ? `<h3>Done when</h3><div class="md">${md(r.acceptanceCriteria)}</div>` : ""}</div>`);
  const sub = r => { const t = String(r.description || ""); return (r.title && t.startsWith(r.title) ? t.slice(r.title.length) : t).replace(/^\s*Steps:\s*/, "").trim(); };
  cols[0].html = r => `${title(r)}${sub(r) ? `<div class="sub clamp">${esc(sub(r))}</div>` : ""}`;
  const plain = rows => table(fill(rows), cols, { onRow: open });
  const where = `${esc(repoName())}${state.branch ? ` on <code>${esc(state.branch === "-" ? "no branch recorded" : state.branch)}</code>` : ""}`;
  return `${head("Issues", `Issues for ${where}: ${n(d.ready.length)} ready to start, ${n(d.blocked.length)} waiting on other work.`)}
    ${d.error ? `<div class="callout bad">Couldn't read the issues: ${esc(d.error)}</div>` : ""}
    ${section("Your epic and stacks", stackBox({}, "full"), "where the work in front of you sits; read only, from GitHub, git and dev-graph")}
    ${d.hidden ? `<p class="muted small">${plural(d.hidden, "issue")} not shown: ${d.hidden === 1 ? "it belongs" : "they belong"} to another repo or branch, or no run or branch name ties ${d.hidden === 1 ? "it" : "them"} to one.</p>` : ""}
    ${tabs("issues", [
      ["ready", "Ready to start", d.ready.length, () => `<div class="box">${plain(d.ready)}</div>`],
      ["blocked", "Waiting on other work", d.blocked.length, () => `<div class="box">${plain(d.blocked)}</div>`],
      ["stale", "Stale", d.stale.length, () => `<p class="muted small">Still open and not touched for ${n(d.stale_days)} days or more.</p><div class="box">${table(d.stale, cols, { onRow: open, emptyTitle: "Nothing stale", emptyBody: `Every open issue changed in the last ${n(d.stale_days)} days.` })}</div>`],
      ["all", "All", d.issues.length, () => `<div class="box">${table(d.issues, cols, { onRow: open, emptyTitle: "No issues yet", emptyBody: "Run <code>/lfg:inbox</code> in Claude Code to bring in your Linear issues." })}</div>`],
    ])}`;
};


/* Local SonarQube: what SonarCloud would flag, found before you push */
function sonarTab(q) {
  const m = q.measures || {};
  const SEV = { BLOCKER: "bad", CRITICAL: "bad", HIGH: "bad", MAJOR: "warn", MEDIUM: "warn" };
  const KIND = { BUG: "Bug", VULNERABILITY: "Vulnerability", CODE_SMELL: "Code smell", SECURITY_HOTSPOT: "Hotspot" };
  const gate = q.gate === "OK" ? tagHtml("Gate passed", "ok") : q.gate === "ERROR" ? tagHtml("Gate failed", "bad") : q.gate ? tagHtml(q.gate, "warn") : tagHtml("Not scanned yet", "");
  const scan = q.server !== "up" ? "" : q.scanning ? `<span class="rv-note" data-sq-scanning><span class="spin"></span>Scanning · started ${ago(q.scanning)}</span>` : `<button class="btn small" data-sq-scan>${icon("refresh")} Scan now</button>`;
  const what = q.ts ? `scanned <span class="brtag">${esc(q.branch || "?")}</span>${q.head ? ` at <span class="brtag">${esc(q.head)}</span>` : ""}${q.base_name ? ` vs <span class="brtag">${esc(q.base_name)}</span>` : ""} · ${ago(q.ts)}` : "";
  const tile = (k, v) => `<div class="sq-tile"><div class="k">${k}</div><div class="v">${esc(v ?? "–")}</div></div>`;
  const issue = r => `<div class="sq-row">${tagHtml((words(String(r.severity || "").toLowerCase()) || "–").replace(/^./, c => c.toUpperCase()), SEV[r.severity] || "")}${tagHtml(KIND[r.kind] || words(String(r.kind || "").toLowerCase()), "")}<span class="grow"><span class="sq-msg">${esc(r.message || "")}</span><span class="rv-row-m"><span class="brtag" title="${esc(r.path || "")}">${esc((r.path || "").split("/").pop())}${r.line ? ":" + r.line : ""}</span><span class="mono">${esc(r.rule || "")}</span></span></span></div>`;
  const mine = (q.issues || []).filter(i => i.mine), rest = (q.issues || []).filter(i => !i.mine);
  const byKind = Object.entries(q.rest_by_kind || {}).map(([k, v]) => tagHtml(`${KIND[k] || words(k.toLowerCase())} ${v}`, "")).join("");
  return `${q.server !== "up" ? `<div class="callout warn">SonarQube isn't running (${esc(q.server)}). Turn it on in <a href="#integrations">Integrations</a>.</div>` : ""}
    <div class="rv-card sq-head"><div class="sq-line">${gate}<span class="rv-row-m">${what}</span><span class="grow"></span>${scan}</div>
      ${q.ts ? `<div class="sq-tiles">${tile("Bugs", m.bugs)}${tile("Vulnerabilities", m.vulnerabilities)}${tile("Code smells", m.code_smells)}${tile("Hotspots", m.security_hotspots)}${tile("Duplication", m.duplicated_lines_density != null ? m.duplicated_lines_density + "%" : null)}</div>` : ""}
      ${(q.conditions || []).filter(c => c.status === "ERROR").map(c => `<div class="sq-line">${tagHtml("Failed", "bad")}<span>${esc(words(c.metricKey))} is ${esc(c.actualValue)} (limit ${esc(c.comparator)} ${esc(c.errorThreshold)})</span></div>`).join("")}
      <div class="sq-line" id="sq-cloud"><span class="muted small">Checking SonarCloud…</span></div></div>
    ${q.ts ? `<div class="rv-card-h sq-sub">On your branch<span class="muted small">${plural(mine.length, "issue")} on lines it changed</span></div>
      <div class="rv-card sq-list">${mine.length ? mine.map(issue).join("") : '<p class="muted small">Nothing on the lines this branch changed.</p>'}</div>` : ""}
    ${rest.length ? `<details class="rv-card"><summary class="rv-card-h">Rest of the repo · ${plural(rest.length, "issue")}<span class="sq-kinds">${byKind}</span></summary><div class="sq-list">${rest.map(issue).join("")}</div></details>` : ""}
    ${q.url ? `<p class="muted small">Full report in <a href="${esc(q.url)}" target="_blank" rel="noopener noreferrer">SonarQube ↗</a> · sign in as admin, <code>lfg sonar login</code> shows the password</p>` : ""}`;
}
async function wireSonar(root) {
  $$("[data-sq-scan]", root).forEach(b => b.onclick = async () => {
    b.disabled = true; b.textContent = "Starting…";
    const r = await save("sonar_scan", { repo: state.repo });
    if (!r.ok) { alert(String(r.why || "Couldn't start the scan.").replace(/`/g, "")); b.disabled = false; b.textContent = "Scan now"; return; }
    route({ soft: true });
  });
  if ($("[data-sq-scanning]", root)) pageTimer("sonar", 10000, () => { if (location.hash.startsWith("#checks") && $("[data-sq-scanning]")) route({ soft: true }); });
  const box = $("#sq-cloud", root);
  if (box) {
    const c = await api("sonar_cloud");
    const failed = c && /fail|cancel/i.test(`${c.conclusion} ${c.title}`), crashed = c && /analysis failed/i.test(c.title || c.summary || "");
    box.innerHTML = !c || !c.found ? '<span class="muted small">No SonarCloud check on this commit (not pushed yet, or the repo doesn\'t use SonarCloud)</span>'
      : `${tagHtml(`SonarCloud: ${crashed ? "analysis failed" : c.conclusion || c.status || "?"}`, c.conclusion === "success" ? "ok" : failed ? "bad" : "warn")}<span class="rv-row-m">on <span class="brtag">${esc(String(c.sha).slice(0, 7))}</span>${crashed ? " · their side, not your code" : c.title ? ` · ${esc(c.title)}` : ""}${c.url ? ` · <a href="${esc(c.url)}" target="_blank" rel="noopener noreferrer">open ↗</a>` : ""}</span>`;
  }
}

PAGES.checks = async () => {
  const [r, s] = await Promise.all([api("reviews"), api("security")]);
  for (const d of [r, s]) if (d.available === false) return unavailable(d);
  const last = s.secure[0], ship = s.shipcheck[0], rev = r.verdicts[0];
  const open = r.findings.filter(f => !f.feedback);
  const sum = `<div class="cols">${stat("Latest code review", rev ? say(rev.verdict)[0] : "None yet", rev ? plural(rev.findings, "finding") : "run <code>/lfg:review-coach</code>")}${stat("Latest security check", last ? say(last.verdict)[0] : "None yet", last ? (last.blocking ? `${plural(last.blocking, "problem")} to fix` : "nothing blocking") : "run <code>/lfg:secure</code>")}${stat("Latest ship check", ship ? (ship.pass ? "Passed" : "Failed") : "None yet", ship ? `${ship.ok} of ${ship.total} checks passed${(ship.manual || []).length ? ` · ${ship.manual.length} for you to do` : ""}` : "run <code>/lfg:ship</code>")}</div>`;
  const sevSort = { blocker: 0, critical: 0, high: 1, major: 1, medium: 2, minor: 3, low: 3, nit: 4 };
  return `${head("Checks", "What the code reviews and security checks found, and the actions LFG stopped to keep your work safe.")}
    ${sum}
    <div class="section">${tabs("checks", [
      ["review", "Review findings", r.findings.length, () => `<div class="box">${table(r.findings, [
        { k: "severity", label: "How serious", html: x => st(x.severity), sort: x => -(sevSort[String(x.severity).toLowerCase()] ?? 5) },
        { k: "message", label: "Finding", html: x => `${txt(x.title || x.finding || x.message || x.id)}${x.fix ? `<div class="sub clamp">What to do: ${txt(x.fix)}</div>` : ""}${x.file ? `<div class="sub mono">${esc(x.file)}${x.line ? ":" + esc(x.line) : ""}</div>` : ""}<div class="sub">from <a href="#runs/${encodeURIComponent(x.run)}">${esc(runName({ slug: String(x.run || "").slice(14) }))}</a></div>` },
        { k: "feedback", label: "Your call", html: x => st(x.feedback, "not decided") }], { onRow: x => openDrawer("Review finding", `<div class="readable">${findingCard(x)}</div>`), emptyTitle: "No findings", emptyBody: "Run <code>/lfg:review-coach</code> on a change." })}</div>${open.length ? `<p class="muted small">Record your call with <code>lfg feedback add &lt;id&gt; accept|reject</code>.</p>` : ""}`],
      ["security", "Security checks", s.secure.length, () => `<div class="box">${table(s.secure, [
        { k: "verdict", label: "Result", html: x => st(x.verdict) },
        { k: "blocking", label: "Problems to fix", num: true },
        { k: "inventory", label: "New things checked", html: x => esc(Object.entries(x.inventory).filter(([, v]) => v).map(([k, v]) => `${v} ${words(k)}`).join(", ") || "none") },
        { k: "ts", label: "When", html: x => `<span class="nowrap">${ago(x.ts)}</span>` }],
        { onRow: x => openDrawer("Security check", `<div class="readable"><p>${st(x.verdict)}</p>${x.scope ? `<p class="muted">Checked: ${txt(x.scope)}</p>` : ""}${findingList(x.findings, "No security problems found.")}</div>`) })}</div>`],
      ["pentest", "Security tests", s.pentest.length, () => `<div class="box">${table(s.pentest, [{ k: "status", label: "Result", html: x => st(x.status) }, { k: "summary", label: "What happened", html: x => `<div class="clamp">${txt(x.summary)}</div>` }, { k: "model", label: "Local model" }],
        { onRow: x => openDrawer("Security test", `<div class="readable">${JSON_VIEWS["05-pentest.json"](x)}</div>`) })}</div>`],
      ["ship", "Ship checks", s.shipcheck.length, () => `<div class="box">${table(s.shipcheck, [{ k: "pass", label: "Result", html: x => st(x.pass ? "pass" : "fail") }, { k: "ok", label: "Passed", html: x => `${x.ok} of ${x.total}` }, { k: "failed", label: "What failed", html: x => esc((x.failed || []).join(", ") || "—") }, { k: "ts", label: "When", html: x => `<span class="nowrap">${ago(x.ts)}</span>` }],
        { onRow: x => openDrawer("Ship check", `<div class="readable"><p>${st(x.pass ? "pass" : "fail")}</p>${x.note ? `<p class="muted">${txt(x.note)}</p>` : ""}<div class="items">${shipChecks(x.checks)}</div></div>`) })}</div>`],
      ...(s.sonar ? [["sonar", "SonarQube", s.sonar.mine || null, () => sonarTab(s.sonar)]] : []),
      ["stopped", "Stopped actions", r.blocked.length, () => `<p class="muted">Actions an agent tried that break a rule, so LFG stopped them. Nothing here needs you; it shows the guard working.</p><div class="box">${table(r.blocked, [{ k: "why", label: "What was stopped", html: x => esc(x.why || x.tool) }, { k: "rule", label: "Rule", html: x => `rule ${esc(x.rule)}` }, { k: "ts", label: "When", html: x => `<span class="nowrap">${ago(x.ts)}</span>` }])}</div>`],
    ])}</div>`;
};

PAGES.code = async () => {
  const [c, a] = await Promise.all([api("code"), api("architecture")]);
  const g = await api("graphs");
  const [gText, gTone] = say(g.status);
  const mapRow = `<div class="box pad row">${dot(gTone)}<div class="grow"><b>${esc(repoName())} code map: ${esc((gText || "unknown").toLowerCase())}</b><div class="meta">${g.status === "syncing" ? "Building in the background. This page updates when it's done." : g.synced_at ? `Updated ${ago(g.synced_at)}${g.seconds ? ` in ${Math.round(g.seconds)}s` : ""}.` : "Not built yet."}${g.error ? ` Last error: ${esc(String(g.error).slice(0, 200))}` : ""}</div></div>
    ${mapBtn(g.status)}${g.status !== "missing" && g.status !== "syncing" ? '<button class="btn small" data-map-build="rebuild">Rebuild from scratch</button><button class="btn small" data-map-build="docs" title="Wikis, call flows and playbooks">Refresh docs</button>' : ""}</div>`;
  if (c.available === false && a.available === false) return `${head("Code", "LFG keeps a map of this project so agents read only the parts that matter.")}${mapRow}
    ${g.status === "syncing" ? "" : empty("No code map yet", "Build it now. It runs in the background on this computer and usually takes a minute or two.")}`;
  let summary = "";
  if (c.available !== false) {
    const cov = pct(c.coverage.tested, c.coverage.tested + c.coverage.untested);
    summary = `${n(c.nodes.File)} code files, ${n((c.nodes.Function || 0) + (c.nodes.Class || 0))} functions and classes; code-review-graph links ${cov}% of them to a test.`;
  }
  const risky = c.available !== false ? (c.hotspots || []).slice(0, 10) : [];
  const notes = a.available !== false ? a.rationale : [];
  return `${head("Code", `LFG keeps a map of this project so agents read only the parts that matter. ${summary}`)}
    ${mapRow}
    ${risky.length ? section("Where changes are riskiest", `<div class="box">${table(risky, [
      { k: "symbol", label: "Code", html: r => `${esc(r.symbol)}<div class="sub">${esc(r.file)}</div>` },
      { k: "callers", label: "Used by", num: true, html: r => plural(r.callers, "place") },
      { k: "coverage", label: "Tested", html: r => (r.coverage === "tested" ? `${dot("ok")} Yes` : `${dot("warn")} No`) }], { filter: false })}</div>`, "used in many places, so a change here reaches far") : ""}
    ${notes.length ? section("Why the code is the way it is", `<div class="box">${table(notes, [{ k: "note", label: "Explanation" }, { k: "file", label: "Where", html: r => `<span class="small muted mono nowrap">${esc(r.file + (r.line ? ":" + r.line : ""))}</span>` }])}</div>`, `docstrings and WHY / NOTE / HACK comments${a.rationale_total > notes.length ? `, first ${notes.length} of ${n(a.rationale_total)}` : ""}`) : ""}`;
};

/* Docs: a tree. Project docs (LFG's wiki, glossary, decisions, guides you asked for) at the root, then one folder
   per branch for docs about that branch's work. */
PAGES.docs = async arg => {
  const d = await api("docs");
  if (d.available === false) return unavailable(d);
  const parts = (arg || "").split("/");
  let src = parts[0], path = decodeURIComponent(parts.slice(1).join("/"));
  const all = t => t.items.concat(...t.folders.map(f => f.items));
  if (!src) { const pick = (d.intro || [])[0] || (d.views || [])[0] || all(d.root)[0]; if (pick) { src = pick.src; path = pick.path; } }
  const on = it => it.src === src && it.path === path;
  const link = (it, ico) => `<a href="#docs/${esc(it.src)}/${encodeURIComponent(it.path)}" class="${on(it) ? "on" : ""}" title="${esc(it.title)}">${ico ? icon(ico) : ""}${esc(it.title)}</a>`;
  const folder = (name, items, tag, open) => `<details class="doc-folder"${open || items.some(on) ? " open" : ""}><summary>${icon("folder")}<span class="grow">${esc(name)}</span>${tag || ""}<span class="count">${items.length}</span></summary>${items.map(x => link(x)).join("")}</details>`;
  const STATE = { current: "current", default: "default", merged: "merged", deleted: "deleted" };
  const mine = all(d.root).length + d.branches.reduce((n, b) => n + all(b).length, 0);
  const grp = (t, extra) => `<div class="grp"><span>${t}</span>${extra || ""}</div>`;
  const nav = `${grp("Getting started")}${(d.intro || []).map(x => link(x, "docs")).join("")}
    ${(d.views || []).length || (d.code || []).length ? grp("Code wiki", '<span class="tag" title="Generated by graphify from the code">graphify</span>') : ""}
    ${(d.views || []).map(x => link(x, x.path === "callflow" ? "runs" : "code")).join("")}
    ${(d.code || []).map(x => link(x, "docs")).join("")}
    ${grp("Your docs")}${mine ? d.root.items.map(x => link(x)).join("") + d.root.folders.map(f => folder(f.name, f.items)).join("") : '<p class="meta small pad">None yet. Write one with <b>New doc</b>.</p>'}
    ${d.branches.length ? grp("Branches") + d.branches.map(b => folder(b.name, all(b), b.state ? `<span class="tag${b.state === "current" ? " blue" : ""}">${STATE[b.state]}</span>` : "", b.name === state.branch || b.state === "current")).join("") : ""}`;
  let body;
  if (src === "new" || src === "edit") body = await docEditor(src === "edit" ? path : "");
  else if (src === "view") {
    const v = await api("view", { kind: path });
    body = v.src ? `<iframe class="viewer tall" src="${esc(v.src)}" title="${esc(path)}" referrerpolicy="no-referrer"></iframe>` : empty("Not built yet", fmtWhy(v.message || ""));
  } else if (src && path) {
    const doc = await api("doc", { src, path });
    body = doc.text === "not found" ? empty("Document not found", "") : `${src === "repo" ? `<div class="doc-bar"><span class="tag">${path.startsWith("branches/") ? "Branch doc" : "Project doc"}</span><span class="grow"></span><a class="btn small" href="#docs/edit/${encodeURIComponent(path)}">Edit</a></div>` : src === "gwiki" ? '<div class="doc-bar"><span class="tag">graphify</span><span class="muted small">Written from the code graph; it updates when the code map does.</span></div>' : ""}<div class="md">${md(doc.text, true)}</div>`;
  } else body = empty("No docs yet", "Write one with New doc.");
  return `${head("Docs", "Start here, explore the code wiki graphify builds from your code, and keep your own docs in Markdown.")}
    <div class="docs"><div class="box doc-nav"><div class="doc-tools"><input type="search" id="doc-filter" placeholder="Search docs…"><a class="btn primary small" href="#docs/new">New doc</a></div>${nav}</div>
    <div class="box" id="doc-body" data-src="${esc(src || "")}" data-path="${esc(path || "")}">${body}</div></div>`;
};
async function docEditor(path) {
  let title = "", text = "";
  if (path) {
    const doc = await api("doc", { src: "repo", path });
    text = doc.text === "not found" ? "" : doc.text;
    const m = /^# (.+)\n+/.exec(text); if (m) { title = m[1]; text = text.slice(m[0].length); }
  }
  const br = state.branch && state.branch !== "-" ? state.branch : "";
  return `<div class="doc-edit"><input type="text" id="de-title" placeholder="Title" value="${esc(title)}" maxlength="140">
    ${path ? `<p class="muted small">Editing <code>${esc(path)}</code></p>` : `<div class="row"><span class="muted small">Save it to</span><div class="seg" id="de-where"><button class="pill on" data-w="project">Project</button>${br ? `<button class="pill" data-w="branch" title="Docs about the work on this branch">Branch ${esc(br)}</button>` : ""}</div></div>`}
    <div class="seg de-mode"><button class="pill on" data-m="write">Write</button><button class="pill" data-m="preview">Preview</button></div>
    <textarea class="editor" id="de-text" placeholder="Write or paste Markdown: # headings, - lists, - [ ] checklists, \`code\`, tables…">${esc(text)}</textarea>
    <div class="md de-preview" id="de-preview" hidden></div>
    <div class="set-actions"><button class="btn primary" id="de-save" data-path="${esc(path)}">Save</button><a class="btn" href="#docs${path ? `/repo/${encodeURIComponent(path)}` : ""}">Cancel</a><span class="save-msg" id="de-msg"></span></div></div>`;
}
function wireKnowledgeAdd(root) {
  const b = $("#kn-save", root);
  if (!b) return;
  let kind = "note";
  $$("#kn-kind .pill", root).forEach(p => p.onclick = () => { kind = p.dataset.k; $$("#kn-kind .pill", root).forEach(x => x.classList.toggle("on", x === p)); });
  b.onclick = async () => {
    b.disabled = true;
    const r = await save("knowledge_add", { repo: state.repo, title: $("#kn-title", root).value, text: $("#kn-text", root).value, kind });
    b.disabled = false;
    if (r.ok) { sessionStorage.setItem("lfg.tab.know", "mine"); route(); } else saidMsg($("#kn-msg", root), r);
  };
}
function wireDocEditor(root) {
  const save$ = $("#de-save", root);
  if (!save$) return;
  let where = "project";
  $$("#de-where .pill", root).forEach(b => b.onclick = () => { where = b.dataset.w; $$("#de-where .pill", root).forEach(x => x.classList.toggle("on", x === b)); });
  $$(".de-mode .pill", root).forEach(b => b.onclick = () => {
    $$(".de-mode .pill", root).forEach(x => x.classList.toggle("on", x === b));
    const pv = b.dataset.m === "preview";
    $("#de-text", root).hidden = pv; $("#de-preview", root).hidden = !pv;
    if (pv) $("#de-preview", root).innerHTML = md(`# ${$("#de-title", root).value || "Untitled"}\n\n${$("#de-text", root).value}`);
  });
  save$.onclick = async () => {
    save$.disabled = true;
    const r = await save("doc_save", { repo: state.repo, title: $("#de-title", root).value, text: $("#de-text", root).value, where, branch: state.branch, path: save$.dataset.path });
    save$.disabled = false;
    if (r.ok) location.hash = `#docs/repo/${encodeURIComponent(r.path)}`; else saidMsg($("#de-msg", root), r);
  };
}

/* Knowledge: what LFG has saved, each item with a repo, a feature and a topic, fuzzy search and Ask. */
const KINDS = {
  decision: ["Decisions", "Choices made while building something, and why: \"the queue auto-starts and can be cancelled\". Kept so nobody re-argues them. Usually about one repo and one feature."],
  learning: ["Lessons", "Things found out the hard way: gotchas, root causes, how to run or deploy something. The kind of thing you'd tell a teammate before they start."],
  rule: ["Rules", "Always/never rules and things that must stay true, which agents check their work against."],
  note: ["Your notes", "Personal notes and preferences in second-brain, not tied to a repo. How you like to work, ideas, questions."],
};
const TOPIC = { setup: "Setup and environment", gotcha: "Gotcha", incident_review: "Incident review", retro: "Retro", hindsight: "Hindsight" };
/* Fuzzy match: every word of the query must appear, as a substring or as letters in order, in the item's text. */
function fuzzy(q, text) {
  if (!q) return 1;
  const t = text.toLowerCase();
  let score = 0;
  for (const w of q.toLowerCase().split(/\s+/).filter(Boolean)) {
    if (t.includes(w)) { score += 2; continue; }
    let i = 0;
    for (const c of t) if (c === w[i]) i++;
    if (i === w.length) score += 1; else return 0;
  }
  return score;
}
PAGES.knowledge = async () => {
  const [k, b, unlocked] = await Promise.all([api("knowledge"), api("brain"), isUnlocked()]);
  const K = k.available === false ? { decisions: [], principles: [], invariants: [], unheld: [], gaps: [], learnings: [] } : k;
  const B = b.available === false ? { notes: [], preferences: [] } : b;
  const unheld = new Set((K.unheld || []).map(r => r.slug));
  const part = (label, v) => v ? `<h3>${label}</h3><div class="md">${md(String(v))}</div>` : "";
  const sheet = (title, tags, body) => [title, `<div class="readable"><p>${tags}</p>${body}</div>`];
  const note = r => sheet(r.name || words(r.slug), `${r.kind ? `<span class="tag">${esc(words(r.kind))}</span>` : ""} ${r.when ? `<span class="muted small">${ago(r.when)}</span>` : ""}`,
    `${r.content ? `<div class="md">${md(String(r.content))}</div>` : '<p class="muted">No text was saved with this note.</p>'}${r.tags && String(r.tags) !== "[]" ? `<p class="muted small">Tags: ${esc(String(r.tags).replace(/[[\]']/g, ""))}</p>` : ""}`);
  const dec = r => sheet(r.title, `${st(r.status)} <span class="muted small">${ago(r.createdAt)}</span>`, `${part("Why it came up", r.context)}${part("What was decided", r.decision)}${part("What follows from it", r.consequences)}`);
  const lrn = r => sheet(r.title, `${r.learningKind ? `<span class="tag">${esc(words(r.learningKind))}</span>` : ""} <span class="muted small">${ago(r.createdAt)}</span>`, r.body ? `<div class="md">${md(String(r.body))}</div>` : '<p class="muted">No text was saved with this lesson.</p>');
  const rule = r => sheet(r.text, `<span class="tag">${esc(r.kind)}</span> ${st(r.s)}`, `${part("Why", r.why)}${part("Do this instead", r.alt)}${part("Checked by", r.guard)}${part("Where it comes from", r.spec)}`);
  const items = [
    ...K.decisions.map(r => ({ ...r, kind: "decision", text: [r.decision, r.context].filter(Boolean).join(" "), when: r.createdAt, detail: () => dec(r) })),
    ...K.learnings.map(r => ({ ...r, kind: "learning", text: r.body || "", when: r.createdAt, detail: () => lrn(r) })),
    ...K.principles.map(p => ({ slug: p.slug, kind: "rule", title: (p.polarity === "forbids" ? "Never: " : "Always: ") + p.statement, text: p.rationale || "", status: p.status,
      detail: () => rule({ text: p.statement, why: p.rationale, s: p.status, kind: p.polarity === "forbids" ? "Never" : "Always", alt: p.correctAlternative, spec: p.specRef }) })),
    ...K.invariants.map(i => ({ slug: i.slug, kind: "rule", title: "Must stay true: " + i.statement, text: "", status: unheld.has(i.slug) ? "unheld" : i.status,
      detail: () => rule({ text: i.statement, s: unheld.has(i.slug) ? "unheld" : i.status, kind: "Must stay true", guard: i.guardRef, spec: i.specRef }) })),
    ...[...B.notes].map(n => ({ slug: n.slug, kind: "note", title: n.name || words(n.slug), text: String(n.content || ""), when: n.createdAt, topic: n.kind, detail: () => note({ ...n, when: n.createdAt }) })),
  ];
  state.knowledge = items;
  const F = state.kf || (state.kf = { q: "", kind: "", repo: "", feature: "", topic: "" });
  const opts = key => [...new Set(items.map(i => i[key]).filter(Boolean))].sort();
  const shown = items.map(i => [i, fuzzy(F.q, [i.title, i.text, i.repo, i.feature, (i.tickets || []).join(" "), TOPIC[i.topic] || i.topic].join(" "))])
    .filter(([i, s]) => s && (!F.kind || i.kind === F.kind) && (!F.repo || i.repo === F.repo) && (!F.feature || i.feature === F.feature) && (!F.topic || i.topic === F.topic))
    .sort((a, b) => b[1] - a[1] || String(b[0].when || "").localeCompare(String(a[0].when || ""))).map(([i]) => i);
  const sel = (key, label, values, names = {}) => `<label class="small muted">${label} <select data-kf="${key}"><option value="">All</option>${values.map(v => `<option value="${esc(v)}" ${F[key] === v ? "selected" : ""}>${esc(names[v] || v)}</option>`).join("")}</select></label>`;
  const guessed = (i, f) => (i.guessed || []).includes(f) ? ' title="Filled in by LFG from the ticket it came from; set your own with Tag"' : "";
  const KN = state.know = shown.slice(0, 300).map(i => i.detail);
  const line = (i, n) => `<li class="sess"><div class="grow click" data-kn="${n}" tabindex="0"><div class="title">${esc(i.title || "")}</div>
      ${i.text ? `<div class="meta clamp">${esc(i.text.slice(0, 400))}</div>` : ""}
      <div class="meta"><span class="tag">${esc(KINDS[i.kind][0].replace(/s$/, ""))}</span>${i.repo ? ` <span class="tag"${guessed(i, "repo")}>${esc(i.repo)}</span>` : ""}${i.feature ? ` <span class="tag"${guessed(i, "feature")}>${esc(i.feature.slice(0, 48))}</span>` : ""}${i.topic && TOPIC[i.topic] ? ` <span class="tag"${guessed(i, "topic")}>${esc(TOPIC[i.topic])}</span>` : ""}${(i.tickets || []).length ? ` · ${esc(i.tickets.join(", "))}` : ""}${i.when ? ` · ${ago(i.when)}` : ""}${i.status && i.status !== "accepted" && i.status !== "active" ? ` · ${st(i.status)}` : ""}</div></div>
      ${["decision", "learning"].includes(i.kind) ? `<button class="btn small" data-ktag="${esc(i.slug)}" ${unlocked ? "" : "disabled"}>Tag</button>` : ""}</li>`;
  const missing = [k, b].filter(x => x.available === false).map(x => `<div class="callout warn">${fmtWhy(x.why)}</div>`).join("");
  return `${head("Knowledge", "What Claude has saved while working with you. Agents read it before they start, so they don't repeat old mistakes or re-argue settled choices.")}
    ${missing}
    <div class="cols">${Object.entries(KINDS).map(([kk, [t, about]]) => `<a href="#" class="box pad stat-link ${F.kind === kk ? "on" : ""}" data-kkind="${kk}"><div class="k" style="margin-top:0">${t} · ${items.filter(i => i.kind === kk).length}</div><p class="muted small">${about}</p></a>`).join("")}</div>
    <div class="panel mt"><div class="row"><input type="text" id="k-ask" class="grow" placeholder="Ask: how do I run atomus-local-mcp locally? what did we decide about the run queue?"><button class="btn primary" id="k-askgo" ${unlocked ? "" : "disabled title=\"Open the dashboard with lfg ui to ask\""}>Ask</button></div><div id="k-answer"></div></div>
    <div class="table-tools mt"><input type="search" id="k-find" placeholder="Search everything (typos are fine)…" value="${esc(F.q)}">${sel("repo", "Repo", opts("repo"))}${sel("feature", "Feature", opts("feature"))}${sel("topic", "Topic", Object.keys(TOPIC).filter(t => items.some(i => i.topic === t)), TOPIC)}<span class="count">${plural(shown.length, "item")}</span></div>
    ${shown.length ? `<ul class="items box">${shown.slice(0, 300).map(line).join("")}</ul>` : empty("Nothing matches", "Try fewer words, or clear a filter.")}
    <p class="muted small">Repo and feature come from the ticket each item was saved under; a hover on a tag says when LFG filled it in. Tag sets your own, which always wins. To save something, tell Claude "remember that…" or use <code>/lfg:note</code>; things every session must know, like how to reach prod, belong in your CLAUDE.md instead.</p>`;
};
function wireKnowledge(root) {
  const F = state.kf;
  const find = $("#k-find", root);
  let t;
  if (find) find.oninput = () => { clearTimeout(t); t = setTimeout(() => { F.q = find.value; route().then(() => { const f = $("#k-find"); if (f) { f.focus(); f.setSelectionRange(f.value.length, f.value.length); } }); }, 200); };
  $$("[data-kf]", root).forEach(s => s.onchange = () => { F[s.dataset.kf] = s.value; route(); });
  $$("[data-kkind]", root).forEach(a => a.onclick = e => { e.preventDefault(); F.kind = F.kind === a.dataset.kkind ? "" : a.dataset.kkind; route(); });
  const go = $("#k-askgo", root), q = $("#k-ask", root);
  const ask = async () => {
    if (!q.value.trim()) return q.focus();
    go.disabled = true; go.textContent = "Asking…";
    const r = await save("knowledge_ask", { question: q.value });
    go.disabled = false; go.textContent = "Ask";
    const box = $("#k-answer");
    if (!r.ok) { box.innerHTML = `<p class="bad-tx small">${esc(r.why || "")}</p>`; return; }
    const by = Object.fromEntries((state.knowledge || []).map(i => [i.slug, i]));
    box.innerHTML = `<p class="mt">${esc(r.answer)}</p>${(r.slugs || []).length ? `<div class="k">From</div><ul class="list">${r.slugs.map(sl => `<li>${esc((by[sl] || {}).title || sl)} <span class="muted small">${esc(KINDS[(by[sl] || {}).kind]?.[0] || "")}</span></li>`).join("")}</ul>` : ""}`;
  };
  if (go) go.onclick = ask;
  if (q) q.onkeydown = e => { if (e.key === "Enter") ask(); };
  $$("[data-ktag]", root).forEach(b => b.onclick = () => {
    const i = (state.knowledge || []).find(x => x.slug === b.dataset.ktag) || {};
    const opts = key => [...new Set((state.knowledge || []).map(x => x[key]).filter(Boolean))].sort();
    openDrawer("Tag: " + (i.title || i.slug), `<div class="readable"><p class="muted">Stored in LFG only; the saved item itself doesn't change. Leave a box empty to go back to what LFG filled in.</p>
      <label class="k">Repo</label><input type="text" id="kt-repo" class="wide" list="kt-repos" value="${esc(i.repo || "")}"><datalist id="kt-repos">${opts("repo").map(v => `<option value="${esc(v)}">`).join("")}</datalist>
      <label class="k">Feature</label><input type="text" id="kt-feature" class="wide" list="kt-features" value="${esc(i.feature || "")}"><datalist id="kt-features">${opts("feature").map(v => `<option value="${esc(v)}">`).join("")}</datalist>
      ${i.kind === "learning" ? `<label class="k">Topic</label><select id="kt-topic"><option value="">(LFG's guess)</option>${Object.entries(TOPIC).map(([v, l]) => `<option value="${v}" ${i.topic === v && !(i.guessed || []).includes("topic") ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>` : ""}
      <div class="set-actions"><button class="btn primary" id="kt-save">Save</button><span class="save-msg" id="kt-msg"></span></div></div>`);
    $("#kt-save").onclick = async () => {
      const body = { slug: i.slug, repo: $("#kt-repo").value, feature: $("#kt-feature").value };
      if ($("#kt-topic")) body.topic = $("#kt-topic").value;
      const r = await save("knowledge_tag", body);
      saidMsg($("#kt-msg"), r, "Saved.");
      if (r.ok) setTimeout(() => { closeDrawer(); route(); }, 400);
    };
  });
}
/* Preferences: your rules for Claude. Defaults here; one session's changes from Sessions → Rules. */
function prefControls(P, values, defaults, scope, unlocked) {
  const groups = {};
  for (const p of P.catalog) if (!p.shown_if || values[p.shown_if[0]] === p.shown_if[1]) (groups[p.group] = groups[p.group] || []).push(p);
  const changed = p => scope && values[p.id] !== defaults[p.id];
  const ctl = p => {
    const v = values[p.id], dis = unlocked ? "" : "disabled";
    const told = t => t ? `<details class="told"><summary>What Claude is told</summary><p class="small mono">${esc(t)}</p></details>` : "";
    if (p.kind === "number") return `<label class="row"><input type="number" class="num" min="${p.min || 0}" max="${p.max || ""}" value="${esc(v)}" data-pref='${esc(JSON.stringify([p.id, scope || ""]))}' ${dis}> <span>${esc(p.unit || "")}</span></label>${p.about ? `<p class="small">${esc(p.about)}</p>` : ""}`;
    if (p.kind === "switch") return `<label class="row"><input type="checkbox" data-pref='${esc(JSON.stringify([p.id, scope || ""]))}' ${v ? "checked" : ""} ${dis}> <span>${v ? "On" : "Off"}</span></label>${p.about ? `<p class="small">${esc(p.about)}</p>` : ""}${told(v ? p.text : p.off_text)}`;
    return `<div class="opts">${p.options.map(o => `<label class="opt ${o.value === v ? "on" : ""}"><input type="radio" name="pref-${esc(p.id)}${scope ? "-" + esc(scope) : ""}" data-pref='${esc(JSON.stringify([p.id, scope || ""]))}' value="${esc(o.value)}" ${o.value === v ? "checked" : ""} ${dis}><span><b>${esc(o.label)}</b>${o.about ? `<span class="small muted">${esc(o.about)}</span>` : ""}</span></label>`).join("")}</div>${told((p.options.find(o => o.value === v) || {}).text)}`;
  };
  return Object.entries(groups).map(([g, ps]) => section(g, `<div class="pref-grid">${ps.map(p => `<div class="box pad pref ${changed(p) ? "changed" : ""}"><div class="row"><b class="grow">${esc(p.title)}</b>${p.enforce ? '<span class="tag" title="LFG checks every command against it, so Claude can\'t break it even by mistake">blocked if broken</span>' : '<span class="tag" title="Claude is told to follow it; nothing checks it">Claude is asked</span>'}${changed(p) ? ' <span class="tag warn">this session</span>' : ""}${p.custom && !scope && unlocked ? ` <a href="#" class="small" data-pref-rm="${esc(p.id)}">Remove</a>` : ""}</div>${ctl(p)}</div>`).join("")}</div>`)).join("");
}
function prefToast(msg, bad) {
  let t = $("#pref-toast");
  if (!t) { t = document.createElement("div"); t.id = "pref-toast"; document.body.appendChild(t); }
  t.className = bad ? "bad" : "";
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(t._h);
  t._h = setTimeout(() => (t.hidden = true), 5000);
}
function wirePrefs(root, after) {
  $$("[data-pref]", root).forEach(el => el.onchange = async () => {
    const [id, session] = JSON.parse(el.dataset.pref);
    const value = el.type === "checkbox" ? el.checked : el.type === "number" ? Number(el.value) : el.value;
    const r = await save("pref_set", { id, value, session: session || null });
    if (!r.ok) { prefToast("Not saved: " + (r.why || "error"), true); after(); return; }
    prefToast(session ? "Saved for this session. It takes effect with your next message there." : "Saved. New sessions start with it; open sessions pick it up with your next message.");
    await after();
    const card = $(`[data-pref^='["${id}"']`)?.closest(".pref");
    if (card) { card.classList.add("just-saved"); setTimeout(() => card.classList.remove("just-saved"), 1600); }
  });
  $$("[data-pref-rm]", root).forEach(a => a.onclick = async e => { e.preventDefault(); const r = await save("pref_remove", { id: a.dataset.prefRm }); if (r.ok) after(); });
}
PAGES.prefs = async () => {
  const [P, unlocked] = await Promise.all([api("prefs"), isUnlocked()]);
  const I = P.installed || {};
  const on = I.hooks && I.import;
  const banner = on ? "" : `<div class="callout warn">${dot("warn")}<span><b>Your rules aren't switched on yet.</b> This adds four small hooks to <code>~/.claude/settings.json</code> (one gives each session its rules, one checks commands before they run, one queues your corrections while they're on) and one line to your CLAUDE.md that reads the rules file. Both are backed up and listed under Settings → Claude Code, where they can be undone.</span> <button class="btn small primary" id="prefs-install" ${unlocked ? "" : "disabled"}>Switch on</button></div>`;
  return `${head("Preferences", "Your rules for Claude. These are the defaults every new session starts with; Sessions → Rules changes them for one session. Enforced rules are checked before every command, so Claude keeps them even by mistake; the rest are instructions.")}
    ${banner}
    ${on ? `<div class="callout ok">${dot("ok")}<span><b>Changes apply to sessions already open, no restart needed.</b> Enforced rules are checked on the very next command; open sessions are told about any change with your next message to them.</span></div>` : ""}
    ${unlocked ? "" : lockedNote("change your rules here")}
    ${prefControls({ ...P, catalog: P.catalog.filter(p => p.group !== TALK && p.group !== CORR) }, P.defaults, P.defaults, null, unlocked)}
    ${section(CORR, `<p class="muted">Rules you approved from your corrections have their own page: <a href="#corrections">Corrections</a>.</p>`)}
    ${section(TALK, `<p class="muted">Its rules have their own page: <a href="#talk">How Claude talks</a>.</p>`)}
    <div class="box pad mt"><div class="k" style="margin-top:0">When a change takes effect</div>
      <ul class="small"><li><b>Enforced rules</b> apply at once, in every session, open or new: the next command is checked against them.</li>
      <li><b>Instructions</b> reach new sessions when they start, and sessions already open with your next message in them. Nothing to restart.</li>
      <li>Claude can make a session stricter, never looser. Loosening is yours: here, or <code>! lfg prefs set &lt;id&gt; &lt;value&gt; --by-user</code> in Claude Code.</li></ul>
      <p class="muted small">Your defaults are written to <code>${esc(P.file)}</code>, which your CLAUDE.md reads.</p></div>`;
};
const TALK = "How Claude talks to you";
const CORR = "From your corrections";
/* Corrections: what you corrected Claude on, queued; you approve, merge or discard each. Nothing is a rule until you approve it. */
const CORR_KIND = { said: "you said", rejected: "rejected a tool call", interrupted: "after interrupting", flagged: "Claude noticed" };
PAGES.corrections = async () => {
  const [D, unlocked] = await Promise.all([api("corrections"), isUnlocked()]);
  const dis = unlocked ? "" : "disabled", I = D.installed || {};
  const toggle = `<div class="callout ${D.enabled ? "ok" : ""}">${dot(D.enabled ? "ok" : "")}<span class="grow"><b>Corrections are ${D.enabled ? "on" : "off"}.</b> ${D.enabled ? "When you correct Claude in any session, it lands here for you to review. Claude also queues the ones that are more a feeling than a plain no." : "Turn on to queue what you correct Claude on. Rules you already approved keep working either way."}</span> <label class="row"><input type="checkbox" id="corr-on" ${D.enabled ? "checked" : ""} ${dis}> <span>${D.enabled ? "On" : "Off"}</span></label></div>`;
  const hooks = I.hooks ? "" : `<div class="callout warn">${dot("warn")}<span><b>The hook that captures corrections isn't installed yet.</b> It is one more of your Preferences hooks in <code>~/.claude/settings.json</code>, backed up and undoable under Settings → Claude Code.</span> <button class="btn small primary" id="corr-install" ${dis}>Install</button></div>`;
  const scopeOpts = x => `<label class="row"><input type="radio" name="scope-${esc(x.id)}" value="global" checked ${dis}> Every repo</label>${x.repo ? `<label class="row"><input type="radio" name="scope-${esc(x.id)}" value="project" ${dis}> Only ${esc(x.repo_name)}</label>` : ""}`;
  const card = x => `<div class="box pad corr" data-corr="${esc(x.id)}">
      <div class="row"><b class="grow">“${esc(x.said)}”</b><span class="tag">${esc(CORR_KIND[x.kind] || x.kind)}</span>${x.repo_name ? ` <span class="tag">${esc(x.repo_name)}</span>` : ""} <span class="small muted">${ago(x.at)}</span></div>
      ${x.did ? `<p class="small muted"><b>Claude had:</b> ${esc(x.did)}</p>` : ""}
      ${x.note ? `<p class="small"><b>Claude's read of the lesson:</b> ${esc(x.note)}</p>` : ""}
      <p class="small muted">Caught because it ${esc(x.why || "was flagged")}.</p>
      ${(x.similar || []).map(r => `<div class="callout small"><span class="grow">Looks like your rule <b>${esc(r.title)}</b>: ${esc(r.text)}</span> <button class="btn small" data-corr-merge="${esc(r.id)}" ${dis}>Merge into it</button></div>`).join("")}
      <details ${x.similar && x.similar.length ? "" : "open"}><summary>Make it a rule</summary>
        <input type="text" class="wide mt" data-f="title" placeholder="A short name, e.g. Don't ask what's already decided" ${dis}>
        <textarea class="editor small mt" data-f="text" placeholder="What Claude should do from now on, in words it can follow" ${dis}>${esc(x.note || "")}</textarea>
        <textarea class="editor small mt" data-f="why" placeholder="Why it matters (optional, told to Claude with the rule)" ${dis}></textarea>
        <textarea class="editor small mt" data-f="example" placeholder="A real time it went wrong (optional), e.g. what you just said" ${dis}></textarea>
        <div class="row mt">${scopeOpts(x)}</div>
      </details>
      <div class="set-actions"><button class="btn small primary" data-corr-approve ${dis}>Approve as a rule</button><button class="btn small" data-corr-brain ${dis} title="Background about you, not how Claude should work: kept as a note Claude looks up when it matters, not told to every session">Save to second-brain</button><button class="btn small" data-corr-discard ${dis}>Discard</button><span class="save-msg"></span></div></div>`;
  const rule = r => `<div class="box pad pref" data-corr-rule="${esc(r.id)}"><div class="row"><b class="grow">${esc(r.title)}</b>${r.repo ? `<span class="tag">only ${esc(r.repo.split("/").pop())}</span>` : '<span class="tag">every repo</span>'} <span class="tag" title="How many of your corrections this rule holds">${plural((r.sources || []).length || 1, "correction")}</span>
        <label class="row"><input type="checkbox" data-pref='${esc(JSON.stringify([r.id, ""]))}' ${r.on ? "checked" : ""} ${dis}> <span>${r.on ? "On" : "Off"}</span></label></div>
      <div class="k">Rule</div><textarea class="editor small" data-f="text" ${dis}>${esc(r.text || "")}</textarea>
      <div class="k">Why</div><textarea class="editor small" data-f="why" ${dis}>${esc(r.why || "")}</textarea>
      <div class="k">Example</div><textarea class="editor small" data-f="example" ${dis}>${esc(r.example || "")}</textarea>
      <div class="set-actions"><button class="btn small primary" data-corr-rule-save ${dis}>Save wording</button>${unlocked ? `<a href="#" class="small" data-pref-rm="${esc(r.id)}">Remove</a>` : ""}<span class="save-msg"></span></div></div>`;
  const done = D.done.filter(x => x.status !== "pending");
  return `${head("Corrections", "What you corrected Claude on. Nothing becomes a rule until you approve it here; approved rules go to the file your CLAUDE.md reads (or, for one repo, only to that repo's sessions), each with its own switch.")}
    ${unlocked ? "" : lockedNote("review corrections here")}
    ${toggle}${hooks}
    ${section("To review", D.pending.length ? `<div class="pref-grid">${D.pending.map(card).join("")}</div>` : `<p class="muted">Nothing to review.${D.enabled ? "" : " Corrections are off."}</p>`, D.pending.length ? plural(D.pending.length, "item") : "")}
    ${section("Your rules from corrections", D.rules.length ? `<div class="pref-grid">${D.rules.map(rule).join("")}</div>` : `<p class="muted">None yet.</p>`)}
    ${done.length ? section("Decided", `<ul class="small">${done.map(x => `<li><b>${esc(x.status)}</b> ${ago(x.done_at || x.at)}: “${esc(x.said.slice(0, 140))}”${x.rule ? ` → <code>${esc(x.rule)}</code>` : ""}</li>`).join("")}</ul>`) : ""}`;
};
function wireCorrections(root) {
  wirePrefs(root, softRoute);
  const on = $("#corr-on", root);
  if (on) on.onchange = async () => { const r = await save("corr_toggle", { on: on.checked }); if (!r.ok) prefToast("Not saved: " + (r.why || "error"), true); softRoute(); };
  const inst = $("#corr-install", root);
  if (inst) inst.onclick = async () => { inst.disabled = true; const r = await save("prefs_install", {}); if (!r.ok) { inst.disabled = false; return alertMsg(inst, r); } softRoute(); };
  const val = (c, f) => ($(`[data-f="${f}"]`, c) || {}).value || "";
  $$("[data-corr]", root).forEach(c => {
    const id = c.dataset.corr, msg = $(".save-msg", c);
    const done = (r, text) => { saidMsg(msg, r, text); if (r.ok) setTimeout(softRoute, 600); };
    $("[data-corr-approve]", c).onclick = async () => {
      const text = val(c, "text").trim();
      if (!text) { $("details", c).open = true; return saidMsg(msg, { ok: false, why: "write the rule first: what Claude should do from now on" }); }
      const scope = ($(`input[name="scope-${id}"]:checked`, c) || {}).value || "global";
      done(await save("corr_approve", { id, text, title: val(c, "title"), why: val(c, "why"), example: val(c, "example"), scope }), "Approved. New sessions get it; open ones with your next message.");
    };
    $("[data-corr-discard]", c).onclick = async () => done(await save("corr_discard", { ids: [id] }), "Discarded.");
    $("[data-corr-brain]", c).onclick = async () => done(await save("corr_brain", { id, title: val(c, "title"), text: val(c, "text") }), "Saved to your second-brain.");
    $$("[data-corr-merge]", c).forEach(b => b.onclick = async () => done(await save("corr_merge", { id, rule: b.dataset.corrMerge, why: val(c, "why"), example: val(c, "example") }), "Merged."));
  });
  $$("[data-corr-rule]", root).forEach(c => {
    const b = $("[data-corr-rule-save]", c);
    if (b) b.onclick = async () => { const r = await save("corr_rule_edit", { id: c.dataset.corrRule, text: val(c, "text"), why: val(c, "why"), example: val(c, "example") }); saidMsg($(".save-msg", c), r, "Saved."); };
  });
}
/* How Claude talks to you: each rule on its own, on or off, in the exact words Claude gets, which you can change. */
PAGES.talk = async () => {
  const [P, unlocked] = await Promise.all([api("prefs"), isUnlocked()]);
  const rules = P.catalog.filter(p => p.group === TALK), dis = unlocked ? "" : "disabled";
  const card = p => {
    const v = P.defaults[p.id];
    return `<div class="box pad pref talk-rule" data-talk="${esc(p.id)}"><div class="row"><b class="grow">${esc(p.title)}</b>${p.custom ? '<span class="tag">yours</span>' : p.lfg_text ? '<span class="tag warn">your wording</span>' : ""}<label class="row"><input type="checkbox" data-pref='${esc(JSON.stringify([p.id, ""]))}' ${v ? "checked" : ""} ${dis}> <span>${v ? "On" : "Off"}</span></label></div>
      ${p.about ? `<p class="small muted">${esc(p.about)}</p>` : ""}
      <div class="k">What Claude is told when it's on</div>
      <textarea class="editor small" data-talk-text ${dis}>${esc(p.text || "")}</textarea>
      <div class="set-actions"><button class="btn small primary" data-talk-save ${dis}>Save wording</button>${p.lfg_text ? `<button class="btn small" data-talk-reset ${dis} title="${esc(p.lfg_text)}">Put back LFG's wording</button>` : ""}${p.custom ? `<a href="#" class="small" data-pref-rm="${esc(p.id)}">Remove</a>` : ""}<span class="save-msg"></span></div></div>`;
  };
  return `${head("How Claude talks", "How Claude writes to you: answers, explanations, things to paste, PR comments. Each rule is on or off for every new session, in the exact words Claude gets, and you can change those words. Sessions → Rules turns one off for a single session.")}
    ${unlocked ? "" : lockedNote("change these here")}
    <div class="pref-grid talk-grid">${rules.filter(p => p.kind === "switch").map(card).join("")}</div>
    ${prefControls({ ...P, catalog: rules.filter(p => p.kind !== "switch") }, P.defaults, P.defaults, null, unlocked)}
    ${section("Add a rule of your own", unlocked ? `<div class="box pad"><input type="text" id="talk-title" class="wide" placeholder="A short name, e.g. Say which environment first"><textarea class="editor small mt" id="talk-text" placeholder="What Claude is told, e.g. When a reply is about a deploy, name the environment in its first sentence."></textarea><div class="set-actions"><button class="btn small primary" id="talk-add">Add rule</button><span class="save-msg" id="talk-msg"></span></div></div>` : lockedNote("add rules here"))}
    <p class="muted small">These rules go into <code>${esc(P.file)}</code> with your other preferences, which your CLAUDE.md reads.</p>`;
};
function wireTalk(root) {
  wirePrefs(root, softRoute);
  $$("[data-talk]", root).forEach(c => {
    const id = c.dataset.talk, msg = $(".save-msg", c), put = async text => {
      const r = await save("pref_text", { id, text });
      saidMsg(msg, r, text ? "Saved. New sessions get it; open ones with your next message." : "LFG's wording is back.");
      if (r.ok) setTimeout(softRoute, 700);
    };
    const s = $("[data-talk-save]", c), r = $("[data-talk-reset]", c);
    if (s) s.onclick = () => put($("[data-talk-text]", c).value);
    if (r) r.onclick = () => put("");
  });
  const add = $("#talk-add", root);
  if (add) add.onclick = async () => {
    const title = $("#talk-title").value.trim(), text = $("#talk-text").value.trim();
    if (!title || !text) return saidMsg($("#talk-msg"), { ok: false, why: "give it a name and what Claude is told" });
    const id = "talk-" + title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40);
    const r = await save("pref_add", { id, group: TALK, title, text });
    saidMsg($("#talk-msg"), r, "Added.");
    if (r.ok) setTimeout(softRoute, 600);
  };
}
function wirePrefsPage(root) {
  const b = $("#prefs-install", root);
  if (b) b.onclick = async () => { b.disabled = true; const r = await save("prefs_install", {}); if (!r.ok) { b.disabled = false; return alertMsg(b, r); } softRoute(); };
  wirePrefs(root, softRoute);
}
async function sessionRules(sid) {
  const s = (state.sessions.sessions || []).find(x => x.id === sid) || {};
  const draw = async () => {
    const [P, unlocked] = await Promise.all([api("prefs", { session: sid }), isUnlocked()]);
    const n = Object.keys(P.overrides || {}).length;
    openDrawer(`Rules: ${s.name || sid}`, `<div class="readable"><p class="muted">Starts from your defaults (Preferences). What you change here is for this session only and reaches it with your next message.${n ? ` <b>${plural(n, "rule")} differ${n === 1 ? "s" : ""} from your defaults.</b> <button class="btn small" id="sr-reset">Back to defaults</button>` : ""}</p>
      ${(P.installed || {}).hooks ? "" : `<div class="callout warn">Your rules aren't switched on yet, so a session can't get its own. Switch them on under Preferences.</div>`}
      ${prefControls(P, P.values, P.defaults, sid, unlocked)}</div>`);
    wirePrefs($("#drawer-body"), draw);
    const r = $("#sr-reset");
    if (r) r.onclick = async () => { await save("pref_clear", { session: sid }); draw(); };
  };
  draw();
}
/* Groups and labels, shared by the Sessions page and Studio's list. A group holds sessions (a studio chat is one) and
   other groups; labels cut across them. Both live in LFG only: nothing on disk moves. */
const LABEL_COLORS = ["gray", "green", "yellow", "red", "blue", "purple", "pink", "orange"];
const LABEL_FILTER_KEY = "lfg.labels.filter";
const labelFilter = () => { try { return JSON.parse(localStorage.getItem(LABEL_FILTER_KEY) || "[]").filter(x => typeof x === "string"); } catch (e) { return []; } };
/* the filter without labels that are gone (deleted or renamed), so a stale one can't hide everything */
const liveLabelFilter = list => { const have = (list || []).map(l => l.name.toLowerCase()), all = labelFilter(), keep = all.filter(k => have.includes(k)); if (keep.length !== all.length) setLabelFilter(keep); return keep; };
const setLabelFilter = f => localStorage.setItem(LABEL_FILTER_KEY, JSON.stringify(f));
const labelHit = (s, filter) => !filter.length || filter.every(f => (s.labels || []).some(l => l.name.toLowerCase() === f));
const labelChip = l => `<span class="chip lbl c-${esc(l.color || "gray")}" title="Label">${esc(l.name)}</span>`;
const labelChips = s => (s.labels || []).length ? `<span class="lbl-row">${s.labels.map(labelChip).join("")}</span>` : "";
/* The groups as a tree: [{name, count, rows, children}]. A group's count includes everything under it. With a label
   filter on (or opts.hideEmpty), a group with no matching row anywhere under it is left out. */
function groupTree(rows, info, filter, opts) {
  const hideEmpty = (filter && filter.length) || (opts && opts.hideEmpty);
  const nodes = new Map();
  const node = name => { if (!nodes.has(name)) nodes.set(name, { name, count: 0, rows: [], children: [] }); return nodes.get(name); };
  Object.keys(info || {}).forEach(node);
  for (const r of rows) if (r.folder) node(r.folder).rows.push(r);
  const roots = [];
  for (const n of nodes.values()) {
    const parent = ((info || {})[n.name] || {}).parent;
    if (parent && parent !== n.name && nodes.has(parent)) nodes.get(parent).children.push(n); else roots.push(n);
  }
  const total = (n, seen) => {
    if (seen.has(n.name)) return 0;
    seen.add(n.name);
    n.children.sort((a, b) => a.name.localeCompare(b.name));
    n.count = n.rows.length + n.children.reduce((t, c) => t + total(c, seen), 0);
    if (hideEmpty) n.children = n.children.filter(c => c.count);
    return n.count;
  };
  const seen = new Set();
  roots.sort((a, b) => a.name.localeCompare(b.name));
  roots.forEach(n => total(n, seen));
  return hideEmpty ? roots.filter(n => n.count) : roots;
}
/* the group's name with the groups above it: "Epic › M1" */
function groupPath(name, info) {
  const out = [];
  for (let g = name; g && !out.includes(g); g = ((info || {})[g] || {}).parent) out.unshift(g);
  return out.join(" › ");
}
/* nested <details>, one per group; `h` supplies what differs between the two lists */
function treeHtml(nodes, h) {
  return nodes.map(n => `<details class="item grp-node" data-grp-node="${esc(n.name)}" ${h.open(n) ? "open" : ""}><summary><span class="grow"><b>${esc(n.name)}</b> ${h.tags(n.name)}</span><span class="muted small nowrap">${n.count ? plural(n.count, "session") : "nothing in it yet"}</span>${h.unlocked ? ` <button class="btn small" data-grp-manage="${esc(n.name)}" title="Rename it, move it, follow a ticket, or delete it">Manage</button>` : ""}</summary>${n.rows.length ? h.listOf(n.rows) : ""}${n.children.length ? `<div class="grp-kids">${treeHtml(n.children, h)}</div>` : ""}</details>`).join("");
}
const groupTags = (name, info) => { const g = (info || {})[name] || {}; return [...(g.prs || []).map(pr => `<a class="tag mono" href="#prs/${esc(pr.replace("#", "/"))}" title="This group follows ${esc(pr)}: every session that mentions it joins">${esc(pr)}</a>`), ...(g.tickets || []).map(t => `<span class="tag mono" title="This group follows ${esc(t)}: every session whose branch, title or first message names it joins">${esc(t)}</span>`)].join(" "); };
const labelFilterBar = (list, filter) => !(list || []).length && !filter.length ? "" : `<div class="lbl-filter"><span class="muted small">Labels</span> ${list.map(l => `<button class="chip lbl c-${esc(l.color)}${filter.includes(l.name.toLowerCase()) ? " on" : ""}" data-lbl-filter="${esc(l.name.toLowerCase())}" aria-pressed="${filter.includes(l.name.toLowerCase())}" title="Show only what has this label. Pick several to narrow it down.">${esc(l.name)} <span class="n">${l.count}</span></button>`).join("")} <button class="btn small" data-lbl-manage>Manage labels</button>${filter.length ? ` <a href="#" data-lbl-clear>Clear</a>` : ""}</div>`;
/* the groups that can't be a group's new parent: itself and everything under it */
function groupBelow(name, info) {
  const out = new Set([name]);
  let grew = true;
  while (grew) { grew = false; for (const [g, i] of Object.entries(info || {})) if (!out.has(g) && out.has(i.parent)) { out.add(g); grew = true; } }
  return out;
}
const colorDots = (attr, value) => `<span class="clr-dots">${LABEL_COLORS.map(c => `<button class="clr c-${c}${c === value ? " on" : ""}" ${attr}="${c}" title="${c}" aria-label="${c}"></button>`).join("")}</span>`;
/* ctx = { info: {group: {parent, prs, tickets}}, labels: [{name, color, count}], refresh() } */
function sessionGroupDrawer(s, ctx) {
  const info = ctx.info || {}, names = Object.keys(info).sort((a, b) => groupPath(a, info).localeCompare(groupPath(b, info)));
  openDrawer("Put this in a group", `<div class="readable">
    <p>Groups are your own way of sorting sessions and studio chats, for example an epic, then its milestones. They live in LFG only: no file or folder on disk moves, and <code>/resume</code> is unchanged. Each one is in at most one group. Anything you don't sort stays visible as Unsorted.</p>
    ${s.folder ? `<p>Now in <b>${esc(s.folder)}</b>${s.via_pr ? " (it mentions a PR this group follows)" : s.via_ticket ? " (it names a ticket this group follows)" : ""}. <button class="btn small" id="grp-out">Take it out</button></p>` : ""}
    ${names.filter(g => g !== s.folder).length ? `<div class="k">Your groups</div><div class="row wrap">${names.filter(g => g !== s.folder).map(g => `<button class="btn small" data-grp="${esc(g)}">${esc(groupPath(g, info))}</button>`).join("")}</div>` : ""}
    <div class="k">New group</div>
    <div class="row"><input type="text" id="grp-new" class="grow" placeholder="e.g. ATO-4162 rollout" maxlength="80"><button class="btn primary" id="grp-make">Create and add</button></div>
    ${names.length ? `<div class="row"><span class="muted small">Inside</span> <select id="grp-parent"><option value="">(top level)</option>${names.map(g => `<option value="${esc(g)}">${esc(groupPath(g, info))}</option>`).join("")}</select></div>` : ""}
    <span class="save-msg" id="sess-msg"></span></div>`);
  const put = async folder => {
    const from = s.via_pr || s.via_ticket ? s.folder : "";
    const r = await save("session_folder", { id: s.id, folder, from });
    saidMsg($("#sess-msg"), r, folder ? `Added to ${folder}.` : "Taken out.");
    if (r.ok) setTimeout(() => { closeDrawer(); ctx.refresh(); }, 400);
  };
  $$("[data-grp]").forEach(b => b.onclick = () => put(b.dataset.grp));
  const out = $("#grp-out");
  if (out) out.onclick = () => put("");
  const make = async () => {
    const v = $("#grp-new").value.replace(/\s+/g, " ").trim();
    if (v.length < 2) { $("#sess-msg").textContent = "Give the group a name of at least 2 characters."; return; }
    if (!info[v]) {
      const r = await save("group_make", { name: v, parent: ($("#grp-parent") || {}).value || "" });
      if (!r.ok) return saidMsg($("#sess-msg"), r);
    }
    put(v);
  };
  $("#grp-make").onclick = make;
  $("#grp-new").onkeydown = e => { if (e.key === "Enter") make(); };
}
function groupManagerDrawer(name, ctx) {
  const info = ctx.info || {}, g = info[name] || {}, below = groupBelow(name, info);
  const others = Object.keys(info).filter(x => !below.has(x)).sort((a, b) => groupPath(a, info).localeCompare(groupPath(b, info)));
  openDrawer(`Group: ${name}`, `<div class="readable">
    <div class="k">Name</div><div class="row"><input type="text" id="gm-name" class="grow" value="${esc(name)}" maxlength="80"><button class="btn" id="gm-rename">Rename</button></div>
    <div class="k">Inside</div><div class="row"><select id="gm-parent"><option value="">(top level)</option>${others.map(x => `<option value="${esc(x)}" ${x === g.parent ? "selected" : ""}>${esc(groupPath(x, info))}</option>`).join("")}</select><button class="btn" id="gm-move">Move</button></div>
    <div class="k">Follows tickets</div>
    <p class="muted small">Every session whose branch, title or first message names the ticket joins this group, unless you filed it elsewhere or took it out.</p>
    <div class="row wrap">${(g.tickets || []).map(t => `<span class="tag mono">${esc(t)} <a href="#" data-gm-unfollow="${esc(t)}" aria-label="Stop following ${esc(t)}">✕</a></span>`).join("") || '<span class="muted small">None yet.</span>'}</div>
    <div class="row"><input type="text" id="gm-ticket" class="grow" placeholder="ATO-4162" maxlength="20"><button class="btn" id="gm-follow">Follow</button></div>
    <div class="k">Delete</div>
    <p class="muted small">Nothing is hidden or deleted. Its sessions and groups move up to ${g.parent ? `<b>${esc(g.parent)}</b>` : "the top level, and its sessions go back to Unsorted"}.</p>
    <button class="btn" id="gm-delete">Delete this group</button>
    <div><span class="save-msg" id="gm-msg"></span></div></div>`);
  const run = async (what, body, ok) => {
    const r = await save(what, body);
    saidMsg($("#gm-msg"), r, ok);
    if (r.ok) setTimeout(() => { closeDrawer(); ctx.refresh(); }, 400);
  };
  $("#gm-rename").onclick = () => run("group_rename", { old: name, new: $("#gm-name").value }, "Renamed.");
  $("#gm-move").onclick = () => run("group_move", { name, parent: $("#gm-parent").value }, "Moved.");
  const follow = () => run("group_ticket", { group: name, ticket: $("#gm-ticket").value.trim().toUpperCase(), on: true }, "Following it.");
  $("#gm-follow").onclick = follow;
  $("#gm-ticket").onkeydown = e => { if (e.key === "Enter") follow(); };
  $$("[data-gm-unfollow]").forEach(a => a.onclick = e => { e.preventDefault(); run("group_ticket", { group: name, ticket: a.dataset.gmUnfollow, on: false }, "Stopped."); });
  $("#gm-delete").onclick = () => run("group_delete", { name }, "Deleted.");
}
function newGroupDrawer(ctx) {
  const info = ctx.info || {}, names = Object.keys(info).sort((a, b) => groupPath(a, info).localeCompare(groupPath(b, info)));
  openDrawer("New group", `<div class="readable"><p>An empty group stays until you delete it. Put it inside another group to build an epic, then its milestones.</p>
    <div class="row"><input type="text" id="ng-name" class="grow" placeholder="e.g. ATO-4162 rollout" maxlength="80"></div>
    ${names.length ? `<div class="row"><span class="muted small">Inside</span> <select id="ng-parent"><option value="">(top level)</option>${names.map(g => `<option value="${esc(g)}">${esc(groupPath(g, info))}</option>`).join("")}</select></div>` : ""}
    <div class="set-actions"><button class="btn primary" id="ng-make">Create</button><span class="save-msg" id="ng-msg"></span></div></div>`);
  const make = async () => {
    const r = await save("group_make", { name: $("#ng-name").value.trim(), parent: ($("#ng-parent") || {}).value || "" });
    saidMsg($("#ng-msg"), r, "Created.");
    if (r.ok) setTimeout(() => { closeDrawer(); ctx.refresh(); }, 300);
  };
  $("#ng-make").onclick = make;
  $("#ng-name").onkeydown = e => { if (e.key === "Enter") make(); };
  $("#ng-name").focus();
}
function sessionLabelsDrawer(s, ctx) {
  const mine = (s.labels || []).map(l => l.name), colorOf = {};
  (ctx.labels || []).forEach(l => (colorOf[l.name.toLowerCase()] = l.color));
  const rest = (ctx.labels || []).filter(l => !mine.some(m => m.toLowerCase() === l.name.toLowerCase()));
  openDrawer(`Labels: ${s.name || s.title || s.id}`, `<div class="readable">
    <p>Labels cut across groups: a session can have any number, for example <i>orchestrator</i> or <i>needs review</i>. They live in LFG only.</p>
    <div class="k">On this one</div>
    <div class="row wrap">${mine.map(n => `<span class="chip lbl c-${esc(colorOf[n.toLowerCase()] || "gray")}">${esc(n)} <a href="#" data-lbl-off="${esc(n)}" aria-label="Remove ${esc(n)}">✕</a></span>`).join("") || '<span class="muted small">None yet.</span>'}</div>
    ${rest.length ? `<div class="k">Add one you already use</div><div class="row wrap">${rest.map(l => `<button class="chip lbl c-${esc(l.color)}" data-lbl-on="${esc(l.name)}">${esc(l.name)}</button>`).join("")}</div>` : ""}
    <div class="k">New label</div>
    <div class="row"><input type="text" id="lbl-new" class="grow" placeholder="e.g. needs review" maxlength="30"><button class="btn primary" id="lbl-add">Add</button></div>
    <p class="muted small">Change a label's colour, rename it or delete it from Manage labels.</p>
    <span class="save-msg" id="lbl-msg"></span></div>`);
  const put = async names => {
    const r = await save("session_labels", { id: s.id, labels: names });
    saidMsg($("#lbl-msg"), r, "Saved.");
    if (r.ok) setTimeout(() => { closeDrawer(); ctx.refresh(); }, 300);
  };
  $$("[data-lbl-off]").forEach(a => a.onclick = e => { e.preventDefault(); put(mine.filter(n => n !== a.dataset.lblOff)); });
  $$("[data-lbl-on]").forEach(b => b.onclick = () => put([...mine, b.dataset.lblOn]));
  const add = () => { const v = $("#lbl-new").value.trim(); if (v) put([...mine, v]); };
  $("#lbl-add").onclick = add;
  $("#lbl-new").onkeydown = e => { if (e.key === "Enter") add(); };
  $("#lbl-new").focus();
}
function labelManagerDrawer(ctx) {
  const list = ctx.labels || [];
  openDrawer("Manage labels", `<div class="readable">
    <p class="muted">Rename a label to the name of another one to merge them. Deleting a label takes it off everything that has it.</p>
    ${list.map(l => `<div class="lbl-edit" data-lbl-edit="${esc(l.name)}"><span class="chip lbl c-${esc(l.color)}">${esc(l.name)} <span class="n">${l.count}</span></span>
      <input type="text" class="grow" value="${esc(l.name)}" maxlength="30" data-lbl-rename aria-label="Rename ${esc(l.name)}">${colorDots("data-lbl-color", l.color)}
      <button class="btn small" data-lbl-save>Rename</button><button class="btn small" data-lbl-del>Delete</button></div>`).join("") || '<p class="muted">No labels yet. Add one from a session or studio chat.</p>'}
    <span class="save-msg" id="lm-msg"></span></div>`);
  const run = async (what, body, ok) => { const r = await save(what, body); saidMsg($("#lm-msg"), r, ok); if (r.ok) setTimeout(() => { closeDrawer(); ctx.refresh(); }, 300); };
  $$("[data-lbl-edit]").forEach(row => {
    const name = row.dataset.lblEdit;
    $$("[data-lbl-color]", row).forEach(b => b.onclick = () => run("label_edit", { name, color: b.dataset.lblColor }, "Colour changed."));
    $("[data-lbl-save]", row).onclick = () => run("label_edit", { name, new_name: $("[data-lbl-rename]", row).value }, "Renamed.");
    $("[data-lbl-del]", row).onclick = () => run("label_delete", { name }, "Deleted.");
  });
}
/* wires the label filter bar and the Manage buttons inside `root`; `ctx` as for the drawers, `rows` the items shown */
function wireGroupsAndLabels(root, ctx, rows) {
  $$("[data-lbl-filter]", root).forEach(b => b.onclick = () => { const f = labelFilter(), k = b.dataset.lblFilter; setLabelFilter(f.includes(k) ? f.filter(x => x !== k) : [...f, k]); ctx.refresh(); });
  $$("[data-lbl-clear]", root).forEach(a => a.onclick = e => { e.preventDefault(); setLabelFilter([]); ctx.refresh(); });
  $$("[data-lbl-manage]", root).forEach(b => b.onclick = () => labelManagerDrawer(ctx));
  $$("[data-grp-manage]", root).forEach(b => b.onclick = e => { e.preventDefault(); e.stopPropagation(); groupManagerDrawer(b.dataset.grpManage, ctx); });
  $$("[data-sess-labels]", root).forEach(b => b.onclick = () => sessionLabelsDrawer(rows.find(x => x.id === b.dataset.sessLabels) || { id: b.dataset.sessLabels }, ctx));
}
/* "Starred only" on the Sessions page: remembered like the page's other filters. */
const SESS_STARRED_KEY = "lfg.sessions.starred";
const sessStarredOn = () => localStorage.getItem(SESS_STARRED_KEY) === "1";
const sessStarredCount = all => (all || []).filter(s => s.starred).length;
/* the sessions to show: those matching the search, and only the starred ones when that filter is on */
const sessShown = (all, hit, only) => (all || []).filter(s => hit(s) && (!only || s.starred));
/* what the page says when nothing is shown: [title, body] */
function sessEmptyText(all, q, only, projectsDir) {
  if (only && !sessStarredCount(all)) return ["No starred sessions yet: star one to keep it here", ""];
  return ["No sessions match", q ? "Try a ticket number, a branch or a repo name." : "No Claude Code sessions found in " + projectsDir];
}
/* Sessions: every Claude Code session on this machine, grouped repo → ticket/branch (or your folder). */
PAGES.sessions = async () => {
  const loose = localStorage.getItem("lfg.sessions.loose") === "1";
  const [d, unlocked, sr] = await Promise.all([api("sessions", { ...(state.showHidden ? { hidden: "1" } : {}), ...scopeArgs("sessions"), ...(loose ? { loose: "1" } : {}) }), isUnlocked(), api("skillruns", { runs_only: "1" }).catch(() => ({ runs: [] }))]);
  state.sessions = d;
  const runsOf = {};
  (sr.runs || []).forEach(j => (runsOf[j.session] || (runsOf[j.session] = [])).push(j));
  if ((sr.runs || []).some(j => ["running", "starting"].includes(j.status))) pageTimer("sess-runs", 4000, () => { if (location.hash.startsWith("#sessions")) softRoute(); });
  const q = (state.sessionFind || "").toLowerCase();
  const filt = liveLabelFilter(d.label_list);
  const hit = s => labelHit(s, filt) && (!q || [s.name, s.repo, s.worktree, s.branch, s.ticket, s.folder, s.first, s.cwd].join(" ").toLowerCase().includes(q));
  const starredOnly = sessStarredOn(), nStarred = sessStarredCount(d.sessions);
  const rows = sessShown(d.sessions, hit, starredOnly);
  const byRepo = new Map();
  for (const s of rows) {
    if (s.folder) continue; // sessions in a group are shown in the group tree
    // outside any repo: one heading, then the folder it was started in (~/code, ~/Downloads, ...)
    const repo = s.loose ? "Outside a repo" : s.repo || "Other";
    if (!byRepo.has(repo)) byRepo.set(repo, new Map());
    const g = byRepo.get(repo);
    const sub = s.loose ? homePath(s.cwd) || "(folder unknown)" : s.group;
    if (!g.has(sub)) g.set(sub, []);
    g.get(sub).push(s);
  }
  const line = s => `<li class="sess" data-sid="${esc(s.id)}"><button class="star${s.starred ? " on" : ""}" data-sess-star='${esc(JSON.stringify([s.id, !s.starred]))}' ${unlocked ? "" : "disabled"} title="${s.starred ? "Starred: kept at the top of its group. Click to unstar" : "Star a session you still care about: it stays at the top of its group and is never folded away"}" aria-label="${s.starred ? "Unstar" : "Star"}">${s.starred ? "★" : "☆"}</button><div class="grow"><div class="title">${esc(s.name)}${s.named ? "" : ' <span class="tag" title="You haven\'t named it (/rename in Claude Code, or Rename here); this name is made up from its ticket, branch and first message">not named</span>'} ${labelChips(s)}</div>
      <div class="meta">${ago(s.modified)} · ${plural(s.prompts, "message")}${s.worktree ? ` · worktree <span class="mono">${esc(s.worktree)}</span>` : ""}${s.branch && s.group !== s.branch ? ` · <span class="mono">${esc(s.branch)}</span>` : ""}${s.app ? " · desktop app" : ""}${s.cost != null ? ` · ${usd(s.cost)}` : ""}${s.folder_exists ? "" : ` · <span class="bad-tx">its folder is gone</span>`}</div>
      ${Date.now() - Date.parse(s.modified) < 6 * 36e5 ? `<div class="sess-work" data-sess-work="${esc(s.id)}" data-fill></div>` : ""}
      <details class="more" data-sess-recent="${esc(s.id)}"><summary class="small">Recent messages and what it used</summary><div class="sess-recent small muted"><span class="loading-inline">Loading…</span></div></details>${skillRuns(runsOf[s.id], unlocked)}</div>
      <div class="sess-actions"><button class="btn small primary" data-copy="${esc(s.resume)}" title="${esc(s.resume)}">Copy resume command</button>
      <button class="btn small" data-sess-changes='${esc(JSON.stringify([s.id, s.name]))}' title="Every file this session edited, as diffs, from its own transcript. Pick lines to ask about them or have it change them">What it changed</button>
      <button class="btn small" data-sess-skill='${esc(JSON.stringify([s.id, s.name]))}' ${unlocked ? "" : "disabled"} title="Run a skill or an instruction on this session, once or in a loop; Claude knows everything said in it">Run a skill…</button>
      <button class="btn small" data-sess-rules="${esc(s.id)}">Rules</button>
      <button class="btn small" data-sess-remind="${esc(s.id)}" ${unlocked ? "" : "disabled"} title="Its next message carries your &quot;How Claude talks to you&quot; rules again, once">Remind it of my style</button>
      <button class="btn small" data-sess-name="${esc(s.id)}" ${unlocked ? "" : "disabled"}>Rename</button>
      ${s.folder ? `<span class="tag" title="${s.via_pr ? "Joined because it mentions a PR this group follows" : s.via_ticket ? "Joined because it names a ticket this group follows" : "Your group"}">${esc(s.folder)}${s.via_pr ? " · via PR" : s.via_ticket ? " · via ticket" : ""} <a href="#" data-sess-ungroup='${esc(JSON.stringify([s.id, s.via_pr || s.via_ticket ? s.folder : ""]))}' title="Take it out of this group" aria-label="Take it out of ${esc(s.folder)}">✕</a></span>` : ""}
      <button class="btn small" data-sess-folder="${esc(s.id)}" ${unlocked ? "" : "disabled"} title="Group sessions your own way, e.g. an epic, then its milestones. Only LFG stores this; nothing on disk moves.">${s.folder ? "Change group" : "Add to a group…"}</button>
      <button class="btn small" data-sess-labels="${esc(s.id)}" ${unlocked ? "" : "disabled"} title="Labels cut across groups, e.g. orchestrator or needs review">Labels…</button>
      <button class="btn small" data-sess-hide='${esc(JSON.stringify([s.id, !s.hidden]))}' ${unlocked ? "" : "disabled"}>${s.hidden ? "Show again" : "Hide"}</button>
      <button class="btn small" data-sess-trash="${esc(s.id)}" ${unlocked ? "" : "disabled"} title="Move this session's file to the Trash">Delete</button></div></li>`;
  /* starred first; sessions not starred and untouched for a week fold away, so the ones you still care about stand out */
  const quiet = s => !s.starred && Date.now() - Date.parse(s.modified) > 7 * 864e5;
  const listOf = ss => {
    const sorted = [...ss].sort((a, b) => (b.starred - a.starred) || (a.modified < b.modified ? 1 : -1));
    const live = q ? sorted : sorted.filter(s => !quiet(s)), old = q ? [] : sorted.filter(quiet);
    return `${live.length ? `<ul class="items sess-list">${live.map(line).join("")}</ul>` : ""}${old.length ? `<details class="more sess-old"><summary>${plural(old.length, "older session")}, not starred and untouched for a week</summary><ul class="items sess-list">${old.map(line).join("")}</ul></details>` : ""}`;
  };
  const tree = groupTree(rows, d.group_info, filt, { hideEmpty: !!q || starredOnly });
  const treeSec = tree.length ? [section("Your groups", treeHtml(tree, { unlocked, listOf, tags: name => groupTags(name, d.group_info), open: n => !!q || filt.length > 0 || n.count > 0 }), plural(rows.filter(s => s.folder).length, "session"))] : [];
  const groups = [...treeSec, ...[...byRepo].map(([repo, g]) => section(repo, [...g].map(([name, ss]) => `<details class="item" ${q || byRepo.size === 1 || !ss.length || ss.some(s => s.starred || Date.now() - Date.parse(s.modified) < 3 * 864e5) ? "open" : ""}><summary><span class="grow"><b>${esc(name)}</b></span><span class="muted small nowrap">${ss.length ? `${plural(ss.length, "session")} · ${ago(ss[0].modified)}` : "nothing in it yet"}</span>${repo !== "Outside a repo" && unlocked ? ` <button class="btn small" data-sess-done='${esc(JSON.stringify([repo, name]))}' title="Hide these sessions and clean up their worktrees">Done with this</button>` : ""}</summary>${listOf(ss)}</details>`).join(""), plural([...g.values()].flat().length, "session")))];
  const lock = unlocked ? "" : `<div class="callout warn">Rename, groups and delete are locked. Run <code>${esc(unlockCmd())}</code> in your terminal to change them here. Copy works either way.</div>`;
  const tab = (on, label, act, title) => `<a href="#" class="tab ${on ? "on" : ""}" data-sess-scope="${act}" title="${esc(title)}">${label}</a>`;
  const tabs = `<div class="tabs page-tabs">${state.repo ? tab(!loose && !allRepos("sessions"), esc(repoName()), "repo", "Sessions in this repo and its worktrees") : ""}${tab(!loose && allRepos("sessions"), "All repos", "all", "Every session, in a repo or not")}${tab(loose, `Outside a repo${d.loose_count ? ` <span class="n">${n(d.loose_count)}</span>` : ""}`, "loose", "Sessions started in a folder that isn't a git repo: your home folder, ~/code, a scratch folder")}</div>`;
  return `${head("Sessions", `Every Claude Code session on this machine, whichever folder you started it in. Copy a resume command and paste it in any terminal: it opens the right folder and picks the session back up.`)}
    ${tabs}
    ${lock}
    <div class="table-tools"><input type="search" id="sess-find" placeholder="Search names, tickets, branches, repos…" value="${esc(state.sessionFind || "")}"><button class="btn small sess-starred${starredOnly ? " on" : ""}" data-sess-starred aria-pressed="${starredOnly}" title="Show only the sessions you starred">★ Starred only <span class="n">${nStarred}</span></button>${unlocked ? `<button class="btn small" data-grp-new title="Make a group to put sessions and studio chats in, inside another group if you like">New group…</button>` : ""}<span class="count">${plural(rows.length, "session")}${q || starredOnly || filt.length ? ` of ${d.sessions.length}` : ""}</span>${d.hidden_count ? `<label class="small"><input type="checkbox" id="sess-hidden" ${state.showHidden ? "checked" : ""}> Show ${plural(d.hidden_count, "hidden session")}</label>` : ""}</div>
    ${labelFilterBar(d.label_list, filt)}
    ${rows.length || groups.length ? groups.join("") : empty(...sessEmptyText(d.sessions, q, starredOnly, esc(d.projects_dir)))}`;
};
/* Skills run on a session from here: what's running, what each run said last, and what it used. */
const RUN_ST = { starting: ["Starting", "on"], running: ["Running", "on"], done: ["Done", "ok"], failed: ["Failed", "bad"] };
function skillRuns(runs, unlocked) {
  if (!(runs || []).length) return "";
  return `<div class="skill-runs">${runs.slice(0, 3).map(j => {
    const [st, tone] = RUN_ST[j.status] || [j.status, ""], last = (j.passes || []).slice(-1)[0];
    const what = j.skill || "Instruction";
    return `<div class="skill-run ${tone}"><div class="row">${dot(tone)}<b class="mono">${esc(what)}</b><span class="muted small">${esc(st)}${j.times > 1 ? ` · pass ${(j.passes || []).length + (j.status === "running" ? 1 : 0)} of ${j.times}` : ""}${j.until_clean && last && last.clean ? " · nothing left to change" : ""} · ${ago(j.ended || j.started)}${j.fork ? " · in a copy" : ""}</span><span class="grow"></span>${j.status === "running" && !j.stop ? `<button class="btn small" data-run-stop="${esc(j.id)}" ${unlocked ? "" : "disabled"} title="Stop after the pass that's running now">Stop after this pass</button>` : ""}<button class="btn small" data-copy="${esc(j.resume)}" title="${esc(j.resume)}">Copy resume command</button></div>
      ${j.say && j.skill ? `<div class="small muted">${esc(j.say.slice(0, 200))}</div>` : !j.skill ? `<div class="small">${esc(j.say.slice(0, 200))}</div>` : ""}
      ${j.status === "running" && (j.steps || []).length ? `<ul class="mono small pr-steps">${j.steps.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
      ${j.status === "failed" && j.why ? `<div class="small bad-tx">${esc(j.why)}</div>` : ""}
      ${last && last.said ? `<details class="more"><summary class="small">What Claude said last</summary><div class="md small">${md(last.said)}</div></details>` : ""}
      ${j.used ? `<details class="more"><summary class="small">What it used</summary>${usedTags(j.used)}</details>` : ""}</div>`;
  }).join("")}</div>`;
}
/* What a session changed: its own edits as diffs, read from its transcript (not git). Click a line number, then
   shift-click another, to pick lines; Ask or Make this change sends them to the session through a skill run. */
async function sessionChanges(sid, name, unlocked) {
  openDrawer(`What ${name} changed`, '<div class="skeleton"></div>');
  const d = await api("sessionchanges", { id: sid });
  const body = $("#drawer-body");
  if (d.available === false) { body.innerHTML = `<p class="muted">${fmtWhy(d.why)}</p>`; return; }
  const where = f => `${f.worktree ? `<span class="tag mono" title="Edited in this worktree">${esc(f.worktree)}</span> ` : ""}${esc(f.outside ? homePath(f.path) : f.path)}`;
  const row = (fi, hi, li, x) => `<tr class="${x.t === "+" ? "add" : x.t === "-" ? "del" : ""}" data-l="${fi}.${hi}.${li}"><td class="ln pick">${esc(x.old ?? "")}</td><td class="ln pick">${esc(x.new ?? "")}</td><td class="sg">${x.t === " " ? "" : esc(x.t)}</td><td class="tx">${esc(x.text)}</td></tr>`;
  const file = (f, fi) => `<details class="sc-file" ${d.files.length <= 6 ? "open" : ""}><summary><span class="grow mono small">${where(f)}${f.outside ? ' <span class="tag" title="Outside this session\'s project: a scratch file or another repo">outside</span>' : ""}</span><span class="diffstat"><b class="add">+${f.additions}</b><b class="del">−${f.deletions}</b></span><span class="muted small nowrap">${plural(f.edits, "edit")}${f.status === "added" ? " · new file" : ""}</span></summary>
    ${f.too_big ? '<p class="muted small">Too big to draw here.</p>' : f.hunks.map((h, hi) => `<div class="pr-snip"><div class="pr-snip-h mono">${esc(h.header)} <span class="muted">· edited ${ago(h.at)}</span></div><div class="pr-snip-b"><table>${h.lines.map((x, li) => row(fi, hi, li, x)).join("")}</table></div></div>`).join("")}</details>`;
  const shell = (d.shell || []).length ? `<details class="more"><summary class="small">${plural(d.shell.length, "shell command")} that may also have changed files (not shown above)</summary><ul class="mono small">${d.shell.map(x => `<li>${esc(x.command)}</li>`).join("")}</ul></details>` : "";
  body.innerHTML = `<div class="readable sc">
    <p class="muted small">${d.files.length ? `${plural(d.files.length, "file")} · <span class="diffstat"><b class="add">+${d.additions}</b><b class="del">−${d.deletions}</b></span> · what this session itself did, from its transcript; denied and rewound edits are left out.` : "This session hasn't edited any files."} Click a line number, then shift-click another, to pick lines.</p>
    ${shell}${d.files.map(file).join("")}
    <div class="sc-ask" hidden><div class="small"><b id="sc-what"></b></div>
      <div class="pr-compose"><textarea id="sc-say" data-grow rows="2" placeholder="Ask about these lines, or say what to change"></textarea></div>
      <label class="row small"><input type="checkbox" id="sc-in"> In the session itself (close it in your terminal first). Otherwise in a copy you can resume.</label>
      <div class="set-actions"><button class="btn" id="sc-ask" ${unlocked ? "" : "disabled"}>Ask</button><button class="btn primary" id="sc-change" ${unlocked ? "" : "disabled"}>Make this change</button><span class="save-msg" id="sc-msg"></span></div></div></div>`;
  $$("textarea[data-grow]", body).forEach(grow);
  let pick = null;  // {fi, from: [hi, li], to: [hi, li]}
  const lineOf = k => { const [fi, hi, li] = k.split(".").map(Number); return { fi, hi, li, x: d.files[fi].hunks[hi].lines[li] }; };
  const picked = () => {
    if (!pick) return [];
    const f = d.files[pick.fi], all = f.hunks.flatMap((h, hi) => h.lines.map((x, li) => ({ hi, li, x })));
    const at = ([hi, li]) => all.findIndex(y => y.hi === hi && y.li === li);
    const [a, b] = [at(pick.from), at(pick.to)].sort((m, n) => m - n);
    return all.slice(a, b + 1);
  };
  const paint = () => {
    const keys = new Set(picked().map(y => `${pick.fi}.${y.hi}.${y.li}`));
    $$("tr[data-l]", body).forEach(tr => tr.classList.toggle("sel", keys.has(tr.dataset.l)));
    const box = $(".sc-ask", body);
    box.hidden = !keys.size;
    if (keys.size) {
      const nums = picked().map(y => y.x.new ?? y.x.old).filter(v => v != null);
      $("#sc-what").textContent = `${d.files[pick.fi].path}, ${nums.length > 1 ? `lines ${Math.min(...nums)}-${Math.max(...nums)}` : `line ${nums[0]}`}`;
    }
  };
  $$("td.pick", body).forEach(td => td.onclick = e => {
    const { fi, hi, li } = lineOf(td.parentNode.dataset.l);
    pick = e.shiftKey && pick && pick.fi === fi ? { ...pick, to: [hi, li] } : { fi, from: [hi, li], to: [hi, li] };
    paint();
  });
  const send = kind => async () => {
    const said = $("#sc-say").value.trim();
    if (!said) { $("#sc-msg").textContent = kind === "ask" ? "Say what you want to know." : "Say what to change."; return; }
    const r = await save("session_lines", { session: sid, path: d.files[pick.fi].path, lines: picked().map(y => y.x), said, kind, fork: !$("#sc-in").checked });
    if (!r.ok) return saidMsg($("#sc-msg"), r, "");
    closeDrawer(); prefToast(kind === "ask" ? "Asked. The answer shows under the session when it's done." : "It's making the change. You'll see it under the session."); softRoute();
  };
  $("#sc-ask").onclick = send("ask");
  $("#sc-change").onclick = send("change");
}
/* What a session has running besides the conversation: subagents and background commands. */
const WORK_ST = { running: ["Running", "on"], quiet: ["No news for 15 min", "warn"], done: ["Done", "ok"], failed: ["Failed", "bad"], stopped: ["Stopped", ""] };
function sessionWork(d) {
  if (!d || d.available === false || !(d.items || []).length) return "";
  return `<div class="k small">Background work</div><ul class="sess-bg">${d.items.slice().reverse().map(a => {
    const [w, tone] = WORK_ST[a.status] || [a.status, ""];
    return `<li>${dot(tone)}<span class="grow"><b>${esc(a.label)}</b> <span class="muted small">${a.kind === "agent" ? `${esc(a.type || "subagent")}${a.steps ? ` · ${plural(a.steps, "step")}` : ""}` : "background command"} · ${esc(w)}${a.ended ? ` ${ago(a.ended)}` : ` · started ${ago(a.started)}`}</span>${a.status === "running" && a.now ? `<div class="mono small muted">now: ${esc(a.now)}</div>` : ""}${a.summary ? `<div class="small muted">${esc(a.summary)}</div>` : ""}</span></li>`;
  }).join("")}</ul>`;
}

/* Pick a skill (or say what to do) and run it on a session, once or in a loop. */
async function sessionSkill(sid, name) {
  openDrawer(`Run a skill on ${name}`, '<div class="loading">Loading your skills…</div>');
  const d = await api("skillruns", { id: sid });
  const groups = {};
  (d.skills || []).forEach(x => (groups[x.source] || (groups[x.source] = [])).push(x));
  const label = { personal: "Your skills", plugin: "Plugins", project: "This project", "Claude Code": "Claude Code" };
  $("#drawer-body").innerHTML = `<div class="readable run-form">
    <p class="muted">Claude picks up the session with everything said in it, then runs what you pick. You get a desktop notice when it's done.</p>
    <label class="k" for="run-skill">Skill</label>
    <select id="run-skill"><option value="">None: just do what I say below</option>${Object.entries(groups).map(([g, xs]) => `<optgroup label="${esc(label[g] || g)}">${xs.map(x => `<option value="${esc(x.invoke)}" title="${esc(x.about)}">${esc(x.invoke)}</option>`).join("")}</optgroup>`).join("")}</select>
    <div class="small muted" id="run-about"></div>
    <label class="k" for="run-say">Anything to tell it</label>
    <div class="pr-compose"><textarea id="run-say" data-grow rows="3" placeholder="e.g. focus on the export endpoint; don't touch the migrations"></textarea></div>
    <div class="run-grid">
      <label><span class="k">How many times</span><select id="run-times">${[1, 2, 3, 5, 10].map(n => `<option>${n}</option>`).join("")}</select></label>
      <label><span class="k">Model</span><select id="run-model">${(d.models || []).map(m => `<option value="${esc(m.id)}" ${m.id === (d.model || "") ? "selected" : ""}>${esc(m.label)}</option>`).join("")}</select></label>
    </div>
    <label class="row small" id="run-clean-row" hidden><input type="checkbox" id="run-clean" checked> Stop early once a pass finds nothing left to change</label>
    <span class="k">What it may do</span>
    <div class="opts">${(d.modes || []).map((m, i) => `<label class="opt ${i === 0 ? "on" : ""}"><input type="radio" name="run-mode" value="${esc(m.id)}" ${i === 0 ? "checked" : ""}><span><b>${esc({ auto: "Auto", acceptEdits: "Edit files", dontAsk: "Only what you've allowed" }[m.id] || m.id)}</b><span class="small muted">${esc(m.label)}</span></span></label>`).join("")}</div>
    <span class="k">Where it runs</span>
    <div class="opts"><label class="opt on"><input type="radio" name="run-where" value="fork" checked><span><b>In a copy of the session</b><span class="small muted">Your session stays as it is. Resume the copy afterwards to keep going from what it did.</span></span></label>
      <label class="opt"><input type="radio" name="run-where" value="in"><span><b>In the session itself</b><span class="small muted">What it does becomes part of the session. Close it in your terminal first, or the two will talk over each other.</span></span></label></div>
    <div class="set-actions"><button class="btn primary" id="run-go">Run</button><span class="save-msg" id="run-msg"></span></div></div>`;
  const body = $("#drawer-body");
  $$("textarea[data-grow]", body).forEach(grow);
  $$(".opts input", body).forEach(r => r.onchange = () => $$(`input[name="${r.name}"]`, body).forEach(x => x.closest(".opt").classList.toggle("on", x.checked)));
  $("#run-skill").onchange = () => { const o = $("#run-skill").selectedOptions[0]; $("#run-about").textContent = o && o.value ? o.title : ""; };
  $("#run-times").onchange = () => { $("#run-clean-row").hidden = $("#run-times").value === "1"; };
  $("#run-go").onclick = async () => {
    const b = $("#run-go"), skill = $("#run-skill").value, say = $("#run-say").value.trim();
    if (!skill && !say) { $("#run-msg").textContent = "Pick a skill or say what to do."; return; }
    b.disabled = true; b.textContent = "Starting…";
    const r = await save("skill_run", { session: sid, skill, say, times: Number($("#run-times").value), until_clean: $("#run-clean").checked,
      model: $("#run-model").value, mode: $('input[name="run-mode"]:checked', body).value, fork: $('input[name="run-where"]:checked', body).value === "fork" });
    if (!r.ok) { b.disabled = false; b.textContent = "Run"; return saidMsg($("#run-msg"), r, ""); }
    closeDrawer(); prefToast(`${skill || "Your instruction"} is running on the session.`); softRoute();
  };
}
/* A path with the home folder as ~ */
const homePath = p => (p || "").replace(/^\/(Users|home)\/[^/]+/, "~");
function wireSessions(root) {
  $$("[data-sess-scope]", root).forEach(a => a.onclick = e => {
    e.preventDefault();
    const v = a.dataset.sessScope;
    localStorage.setItem("lfg.sessions.loose", v === "loose" ? "1" : "");
    if (v !== "loose") localStorage.setItem("lfg.allrepos.sessions", v === "all" ? "1" : "");
    route();
  });
  $$("[data-sess-starred]", root).forEach(b => b.onclick = () => { localStorage.setItem(SESS_STARRED_KEY, sessStarredOn() ? "" : "1"); route(); });
  $$("[data-sess-skill]", root).forEach(b => b.onclick = () => { const [sid, name] = JSON.parse(b.dataset.sessSkill); sessionSkill(sid, name); });
  $$("[data-sess-changes]", root).forEach(b => b.onclick = async () => { const [sid, name] = JSON.parse(b.dataset.sessChanges); sessionChanges(sid, name, await isUnlocked()); });
  const work = $$("[data-sess-work]", root);
  work.forEach(async el => { const d = await api("sessionwork", { id: el.dataset.sessWork }).catch(() => null); if (document.body.contains(el)) morph(el, sessionWork(d)); });
  if (work.length) pageTimer("sess-work", 15000, () => { if (document.body.contains(root) && $$("[data-sess-work] .dot.on", root).length) softRoute(); });
  $$("[data-run-stop]", root).forEach(b => b.onclick = async () => { b.disabled = true; const r = await save("skill_stop", { id: b.dataset.runStop }); if (!r.ok) return alertMsg(b, r); b.textContent = "Stopping after this pass"; });
  const find = $("#sess-find", root);
  if (find) {
    let t;
    find.oninput = () => { clearTimeout(t); t = setTimeout(() => { state.sessionFind = find.value; route().then(() => { const f = $("#sess-find"); if (f) { f.focus(); f.setSelectionRange(f.value.length, f.value.length); } }); }, 250); };
  }
  $$("[data-copy]", root).forEach(b => b.onclick = async () => {
    try { await navigator.clipboard.writeText(b.dataset.copy); b.textContent = "Copied"; } catch (e) { window.prompt("Copy this:", b.dataset.copy); }
    setTimeout(() => (b.textContent = "Copy resume command"), 1500);
  });
  const groupsCtx = () => ({ info: state.sessions.group_info || {}, labels: state.sessions.label_list || [], refresh: () => route() });
  const setGroup = async (sid, folder, msgEl, from) => {
    const cur = (state.sessions.sessions || []).find(x => x.id === sid) || {};
    const r = await save("session_folder", { id: sid, folder, from: from || (cur.via_pr || cur.via_ticket ? cur.folder : "") });
    if (msgEl) saidMsg(msgEl, r, folder ? `Added to ${folder}.` : "Taken out.");
    if (r.ok) setTimeout(() => { closeDrawer(); route(); }, 400);
    return r;
  };
  const ask = (sid, kind) => {
    const s = (state.sessions.sessions || []).find(x => x.id === sid) || {};
    if (kind === "name") {
      openDrawer("Rename session", `<div class="readable"><p>Shown in LFG only; Claude Code's own title is left alone. Leave it empty to go back to the automatic name: <i>${esc(s.auto_name || "")}</i>.</p>
        <input type="text" id="sess-val" class="wide" value="${esc(s.name !== s.auto_name ? s.name : "")}" placeholder="${esc(s.auto_name || "")}">
        <div class="set-actions"><button class="btn primary" id="sess-save">Save</button><span class="save-msg" id="sess-msg"></span></div></div>`);
      const go = async () => { const r = await save("session_name", { id: sid, name: $("#sess-val").value }); saidMsg($("#sess-msg"), r, "Saved."); if (r.ok) setTimeout(() => { closeDrawer(); route(); }, 400); };
      $("#sess-save").onclick = go;
      $("#sess-val").onkeydown = e => { if (e.key === "Enter") go(); };
      $("#sess-val").focus();
      return;
    }
    sessionGroupDrawer(s, groupsCtx());
  };
  $$("[data-sess-ungroup]", root).forEach(a => a.onclick = e => { e.preventDefault(); const [sid, from] = JSON.parse(a.dataset.sessUngroup); setGroup(sid, "", null, from); });
  $$("[data-grp-new]", root).forEach(b => b.onclick = () => newGroupDrawer(groupsCtx()));
  wireGroupsAndLabels(root, groupsCtx(), state.sessions.sessions || []);
  /* Starring changes the star and moves the session to the top of its list in place: no reload, no flicker. */
  $$("[data-sess-star]", root).forEach(b => b.onclick = async () => {
    const [id, on] = JSON.parse(b.dataset.sessStar);
    b.disabled = true;
    const r = await save("session_star", { id, on });
    b.disabled = false;
    if (!r.ok) return alertMsg(b, r);
    const s = (state.sessions.sessions || []).find(x => x.id === id);
    if (s) s.starred = on;
    b.classList.toggle("on", on);
    b.textContent = on ? "★" : "☆";
    b.setAttribute("aria-label", on ? "Unstar" : "Star");
    b.title = on ? "Starred: kept at the top of its group. Click to unstar" : "Star a session you still care about: it stays at the top of its group and is never folded away";
    b.dataset.sessStar = JSON.stringify([id, !on]);
    const li = b.closest("li.sess"), list = li && li.parentNode;
    if (on && list) list.prepend(li);
    const cnt = $(".sess-starred .n", root); if (cnt) cnt.textContent = sessStarredCount(state.sessions.sessions);
  });
  const hid = $("#sess-hidden", root);
  if (hid) hid.onchange = () => { state.showHidden = hid.checked; route(); };
  $$("[data-sess-hide]", root).forEach(b => b.onclick = async () => {
    const [id, on] = JSON.parse(b.dataset.sessHide);
    b.disabled = true;
    const r = await save("session_hide", { ids: [id], on });
    if (!r.ok) { b.disabled = false; return alertMsg(b, r); }
    route();
  });
  $$("[data-sess-trash]", root).forEach(b => b.onclick = () => {
    const s = (state.sessions.sessions || []).find(x => x.id === b.dataset.sessTrash) || {};
    openDrawer("Delete this session?", `<div class="readable"><p><b>${esc(s.name)}</b></p><p>Its file goes to the macOS Trash, so you can still get it back from there. It disappears from <code>/resume</code>. If you only want it out of this list, use Hide instead.</p>
      <div class="set-actions"><button class="btn primary" id="sess-trash-go">Move to Trash</button><span class="save-msg" id="sess-trash-msg"></span></div></div>`);
    $("#sess-trash-go").onclick = async () => {
      const r = await save("session_trash", { id: s.id });
      saidMsg($("#sess-trash-msg"), r, "Moved to the Trash.");
      if (r.ok) setTimeout(() => { closeDrawer(); route(); }, 700);
    };
  });
  $$("[data-sess-done]", root).forEach(b => b.onclick = async e => {
    e.preventDefault(); e.stopPropagation();
    const [repo, group] = JSON.parse(b.dataset.sessDone);
    openDrawer(`Done with ${group}`, '<div class="skeleton"></div>');
    const d = await api("sessiondone", { repo, group });
    const wts = d.worktrees || [];
    const wtRow = w => `<li><label class="row"><input type="checkbox" data-wt="${esc(w.path)}" ${w.safe ? "checked" : "disabled"}><span class="grow"><span class="mono small">${esc(w.path)}</span><div class="meta">${w.safe ? `nothing would be lost${w.branch ? `; the branch <span class="mono">${esc(w.branch)}</span> is kept` : ""}` : `<span class="bad-tx">kept: ${esc(w.why)}</span>`}</div>${(w.dirty || []).length ? `<pre class="small">${esc(w.dirty.join("\n"))}</pre>` : ""}${(w.unpushed || []).length ? `<pre class="small">${esc(w.unpushed.join("\n"))}</pre>` : ""}</span></label></li>`;
    openDrawer(`Done with ${group}`, `<div class="readable">
      <label class="row"><input type="checkbox" id="done-hide" checked><span>Hide its ${plural(d.sessions.length, "session")} from this page. Their files stay, so <code>/resume</code> still works, and "Show hidden" brings them back.</span></label>
      ${wts.length ? `<div class="k">Worktrees these sessions used</div><p class="muted small">Only ones with nothing uncommitted or unpushed can be deleted. Files git ignores there (node_modules, copied .env files) go with them.</p><ul class="items box">${wts.map(wtRow).join("")}</ul>` : `<p class="muted">None of these sessions ran in a worktree.</p>`}
      <div class="set-actions"><button class="btn primary" id="done-go">Clean up</button><span class="save-msg" id="done-msg"></span></div></div>`);
    $("#done-go").onclick = async () => {
      const go = $("#done-go"), msg = $("#done-msg"), out = [];
      go.disabled = true;
      if ($("#done-hide").checked && d.sessions.length) {
        const r = await save("session_hide", { ids: d.sessions, on: true });
        out.push(r.ok ? `hid ${plural(d.sessions.length, "session")}` : `couldn't hide: ${r.why}`);
      }
      for (const box of $$("[data-wt]:checked")) {
        const r = await save("worktree_remove", { path: box.dataset.wt });
        out.push(r.ok ? `deleted ${box.dataset.wt.split("/").pop()}` : r.why);
      }
      msg.textContent = out.join(" · ") || "Nothing selected.";
      setTimeout(() => { closeDrawer(); route(); }, 1600);
    };
  });
  $$("[data-sess-name]", root).forEach(b => b.onclick = () => ask(b.dataset.sessName, "name"));
  $$("[data-sess-rules]", root).forEach(b => b.onclick = () => sessionRules(b.dataset.sessRules));
  $$("[data-sess-recent]", root).forEach(d => d.ontoggle = async () => {
    if (!d.open || d.dataset.loaded) return;
    d.dataset.loaded = "1";
    const r = await api("sessionrecent", { id: d.dataset.sessRecent });
    const box = $(".sess-recent", d);
    box.innerHTML = r.available === false ? esc(r.why) : usedTags(r.used) + ((r.turns || []).length
      ? r.turns.map(t => `<div class="sess-turn ${t.who}"><b>${t.who === "you" ? "You" : "Claude"}</b> <span class="muted">${ago(t.at)}</span><div class="pre-wrap">${esc(t.text)}${t.text.length >= 400 ? "…" : ""}</div></div>`).join("")
      : "No messages yet.");
  });
  $$("[data-sess-remind]", root).forEach(b => b.onclick = async () => {
    b.disabled = true;
    const r = await save("pref_remind", { session: b.dataset.sessRemind });
    if (!r.ok) { b.disabled = false; return alertMsg(b, r); }
    b.textContent = "Reminder set";
    b.title = "Your style rules go out with the next message you send in that session";
  });
  $$("[data-sess-folder]", root).forEach(b => b.onclick = () => ask(b.dataset.sessFolder, "folder"));
}
/* Environment: every repo and worktree on this machine, and what LFG runs in the background. */
const MB = b => b == null ? "?" : b >= 1e9 ? (b / 1e9).toFixed(1) + " GB" : Math.round(b / 1e6) + " MB";
PAGES.environment = async () => {
  const [d, unlocked] = await Promise.all([api("environment", scopeArgs("environment")), isUnlocked()]);
  if (d.pending) {
    setTimeout(() => { if ((location.hash.slice(1) || "").startsWith("environment")) softRoute(); }, 2500);
    return `${head("Environment", "Every repo and worktree on this computer, and what LFG runs in the background.")}<div class="loading">Looking at every repo and worktree… (about 10 seconds)</div>`;
  }
  if (d.available === false) return unavailable(d);
  state.env = d;
  const S = d.services || {};
  const svc = section("Running in the background", `<ul class="items box">${(S.rows || []).map(r => `<li class="sess"><div class="grow">${dot(r.ok ? "ok" : "bad")}<b>${esc(r.name)}</b> <span class="muted small">${esc(r.detail)}</span></div>${r.ok ? "" : `<button class="btn small" data-copy="${esc(r.fix)}">Copy fix</button>`}</li>`).join("")}${(S.disk || []).map(x => `<li class="sess"><div class="grow muted small">${esc(x.what)}</div><span class="small">${MB(x.bytes)}</span></li>`).join("")}</ul>`);
  const all = d.repos.flatMap(r => r.worktrees.filter(w => !w.main).map(w => Object.assign({ repo: r.name, root: r.root }, w)));
  const old = all.filter(w => w.safe_to_delete && Date.now() - Date.parse(w.last_session || w.touched || 0) > 14 * 864e5);
  const status = w => w.missing ? `<span class="muted">folder already gone</span>` : [w.dirty ? `<span class="bad-tx">${plural(w.dirty, "uncommitted file")}</span>` : "", w.unpushed ? `<span class="bad-tx">${plural(w.unpushed, "commit")} not pushed</span>` : "", !w.dirty && !w.unpushed ? "nothing unsaved" : ""].filter(Boolean).join(" · ");
  const wtLine = w => `<li class="sess"><div class="grow"><div class="title">${esc(w.branch || (w.detached ? "detached at " + w.head : w.head))}${w.ticket && !(w.branch || "").toUpperCase().includes(w.ticket) ? ` <span class="tag">${esc(w.ticket)}</span>` : ""}${w.main ? ' <span class="tag">main checkout</span>' : ""}</div>
      <div class="meta mono">${esc(w.path)}</div>
      <div class="meta">${status(w)}${w.last_session ? ` · last session ${ago(w.last_session)}` : w.touched ? ` · touched ${ago(w.touched)}` : ""}${w.sessions ? ` · ${plural(w.sessions, "session")}` : ""}${w.last_subject ? ` · <span title="${esc(w.last_commit || "")}">${esc(w.last_subject.slice(0, 70))}</span>` : ""}</div></div>
      ${w.missing ? "" : `<button class="btn small" data-copy="cd ${esc(w.path)}">Copy cd</button>`}
      ${w.main || w.missing ? "" : `<button class="btn small" data-wt-del="${esc(w.path)}" ${unlocked && w.safe_to_delete ? "" : "disabled"} title="${w.safe_to_delete ? "Delete this worktree; the branch is kept" : "Has unsaved work, so it can't be deleted from here"}">Delete</button>`}</li>`;
  const repos = d.repos.filter(r => r.worktrees.length > 1 || r.worktrees.some(w => w.dirty || w.unpushed)).map(r => {
    const wt = r.worktrees.filter(w => !w.main), gone = wt.filter(w => w.missing).length;
    const sub = `${plural(wt.length, "worktree")}${gone ? ` · ${gone} already gone` : ""}${r.enabled ? " · LFG on" : ""}`;
    return `<details class="item" ${wt.some(w => w.dirty || w.unpushed) || wt.length <= 5 ? "open" : ""}><summary><span class="grow"><b>${esc(r.name)}</b> <span class="muted small">${sub}</span></span>${gone && unlocked ? `<button class="btn small" data-wt-prune="${esc(r.root)}" title="Forget worktrees whose folders were deleted by hand. No files are touched.">Forget ${gone} gone</button>` : ""}</summary><ul class="items sess-list">${r.worktrees.map(wtLine).join("")}</ul></details>`;
  }).join("");
  const quiet = d.repos.filter(r => r.worktrees.length <= 1 && !r.worktrees.some(w => w.dirty || w.unpushed)).map(r => r.name);
  const lock = unlocked ? "" : `<div class="callout warn">Delete is locked. Run <code>lfg ui</code> in your terminal to open this page unlocked. Copy works either way.</div>`;
  return `${head("Environment", `Repos and worktrees on this computer (${plural(all.length, "worktree")} in ${plural(d.repos.length, "repo")}), and what LFG runs in the background. Checked ${ago(d.checked_at)}. ${scopeLine("environment")}`)}
    ${lock}${svc}
    ${old.length && unlocked ? `<div class="callout">${plural(old.length, "worktree")} have nothing unsaved and no session or change in the last 14 days. <button class="btn small primary" id="wt-old">Review and delete…</button></div>` : ""}
    ${section("Repos and worktrees", repos || empty("No worktrees", "None of your repos has a second worktree."), "worktrees with unsaved work first open")}
    ${quiet.length ? `<p class="muted small">No worktrees and nothing unsaved: ${esc(quiet.join(", "))}.</p>` : ""}`;
};
function wireEnvironment(root) {
  $$("[data-copy]", root).forEach(b => b.onclick = async () => {
    const was = b.textContent;
    try { await navigator.clipboard.writeText(b.dataset.copy); b.textContent = "Copied"; } catch (e) { window.prompt("Copy this:", b.dataset.copy); }
    setTimeout(() => (b.textContent = was), 1500);
  });
  const del = async paths => {
    const out = [];
    for (const p of paths) { const r = await save("worktree_remove", { path: p }); out.push(r.ok ? null : `${p.split("/").pop()}: ${r.why}`); }
    return out.filter(Boolean);
  };
  $$("[data-wt-del]", root).forEach(b => b.onclick = () => {
    const p = b.dataset.wtDel;
    openDrawer("Delete this worktree?", `<div class="readable"><p class="mono small">${esc(p)}</p><p>The folder goes, including files git ignores there (node_modules, a copied .env). The branch stays, so you can check it out again any time. LFG checks again just before deleting and refuses if anything is unsaved.</p>
      <div class="set-actions"><button class="btn primary" id="wt-go">Delete worktree</button><span class="save-msg" id="wt-msg"></span></div></div>`);
    $("#wt-go").onclick = async () => { $("#wt-go").disabled = true; const bad = await del([p]); $("#wt-msg").textContent = bad.length ? bad[0] : "Deleted."; if (!bad.length) setTimeout(() => { closeDrawer(); route(); }, 600); };
  });
  $$("[data-wt-prune]", root).forEach(b => b.onclick = async e => {
    e.preventDefault(); e.stopPropagation(); b.disabled = true;
    const r = await save("worktree_prune", { root: b.dataset.wtPrune });
    if (!r.ok) { b.disabled = false; return alertMsg(b, r); }
    route();
  });
  const oldBtn = $("#wt-old", root);
  if (oldBtn) oldBtn.onclick = () => {
    const all = state.env.repos.flatMap(r => r.worktrees.filter(w => !w.main && w.safe_to_delete && Date.now() - Date.parse(w.last_session || w.touched || 0) > 14 * 864e5).map(w => Object.assign({ repo: r.name }, w)));
    openDrawer(`Delete ${plural(all.length, "old worktree")}?`, `<div class="readable"><p>Each has nothing uncommitted and nothing unpushed, and hasn't been used in 14 days. Branches are kept. Untick any you want to keep.</p>
      <ul class="items box">${all.map(w => `<li><label class="row"><input type="checkbox" data-old="${esc(w.path)}" checked><span class="grow"><b>${esc(w.repo)}</b> · ${esc(w.branch || w.head)}<div class="meta mono small">${esc(w.path)} · ${ago(w.last_session || w.touched)}</div></span></label></li>`).join("")}</ul>
      <div class="set-actions"><button class="btn primary" id="old-go">Delete ticked</button><span class="save-msg" id="old-msg"></span></div></div>`);
    $("#old-go").onclick = async () => {
      const go = $("#old-go"), msg = $("#old-msg"), paths = $$("[data-old]:checked").map(x => x.dataset.old);
      go.disabled = true; msg.textContent = `Deleting ${paths.length}…`;
      const bad = await del(paths);
      msg.textContent = bad.length ? `Deleted ${paths.length - bad.length}; kept ${bad.length}: ${bad.join("; ")}` : `Deleted ${paths.length}.`;
      setTimeout(() => { closeDrawer(); route(); }, bad.length ? 5000 : 900);
    };
  };
}
/* Usage: range and measure in one row above everything they scope; each chart says what it counts. */
const UR = { days: 30, by: "day", measure: "usd" };
function weekOf(day) { const d = new Date(day + "T00:00"); d.setDate(d.getDate() - ((d.getDay() + 6) % 7)); return d.toISOString().slice(0, 10); }
function bucket(rows, by, sum) {
  if (by === "day") return rows.map(r => ({ ...r, key: r.day, label: r.day, short: r.day.slice(5) }));
  const m = new Map();
  for (const r of rows) { const k = weekOf(r.day); if (!m.has(k)) m.set(k, []); m.get(k).push(r); }
  return [...m].map(([k, rs]) => ({ ...sum(rs), key: k, days: rs, label: "Week of " + k, short: k.slice(5) }));
}
function addRows(rs, keys) {
  const o = {};
  for (const k of keys) o[k] = rs.reduce((a, r) => a + (r[k] || 0), 0);
  const models = {};
  for (const r of rs) for (const [m, v] of Object.entries(r.models || {})) { const t = models[m] || (models[m] = {}); for (const [k2, x] of Object.entries(v)) t[k2] = (t[k2] || 0) + x; }
  return { ...o, models };
}
// small tags and status pills (SonarQube, Checks)
const tagHtml = (t, tone) => `<span class="tg ${tone || ""}">${esc(t)}</span>`;
const pill = (t, tone) => `<span class="st"><span class="dot ${tone}"></span>${esc(t)}</span>`;
const FIX_SAY = { working: ["AI fixing", "on"], fixed: ["Fixed", "ok"], skipped: ["AI skipped it", ""], failed: ["Fix failed", "bad"] };
/* The Diff tab: the pull request's diff, GitHub style. Drag down the line numbers (or click one, then shift-click
   another) to select lines, even across removed and added ones, and ask the AI about them; it answers in a thread
   under them and you go back and forth. All local: nothing goes to GitHub. */
const DF_ICON = { added: ["+", "add"], deleted: ["−", "del"], renamed: ["→", "ren"], modified: ["•", "mod"] };
const rowKey = l => l.new != null ? `R${l.new}` : `L${l.old}`;
const keyLabel = (a, b) => a === b ? `line ${a}` : `lines ${a} to ${b}`;
let dfPoll = null;

const n_ = v => Number(v || 0).toLocaleString();

/* The file list as folders, single-child folders joined into one path the way GitHub shows them */
function diffTree(files, byFile) {
  const root = { dirs: {}, files: [] };
  files.forEach((f, i) => { let node = root; const parts = f.path.split("/"); parts.slice(0, -1).forEach(p => { node = node.dirs[p] = node.dirs[p] || { dirs: {}, files: [] }; }); node.files.push([parts[parts.length - 1], f, i]); });
  const shut = new Set(state.dfOpen.shut || []);
  const walk = (node, depth, prefix) => Object.keys(node.dirs).sort().map(name => {
    let label = name, cur = node.dirs[name], path = prefix + name;
    while (!cur.files.length && Object.keys(cur.dirs).length === 1) { const k = Object.keys(cur.dirs)[0]; label += "/" + k; path += "/" + k; cur = cur.dirs[k]; }
    return `<div class="df-dir${shut.has(path) ? " shut" : ""}" data-dir="${esc(path)}"><a href="#" class="df-row" style="--d:${depth}" data-df-dir><span class="df-chev">${icon("chev")}</span>${icon("folder")}<span class="df-name">${esc(label)}</span></a><div class="df-kids">${walk(cur, depth + 1, path + "/")}${leaves(cur, depth + 1)}</div></div>`;
  }).join("");
  const leaves = (node, depth) => node.files.sort((a, b) => a[0].localeCompare(b[0])).map(([name, f, i]) => {
    const [g, cls] = DF_ICON[f.status] || DF_ICON.modified, th = byFile[f.path] || [];
    return `<a href="#" class="df-row df-leaf" style="--d:${depth}" data-df-goto="${i}" data-name="${esc(f.path.toLowerCase())}" title="${esc(f.path)}"><span class="df-st ${cls}">${g}</span><span class="df-name">${esc(name)}</span>${th.length ? `<span class="df-cnt" title="${plural(th.length, "thread")}">${icon("review")}${th.length}</span>` : ""}</a>`;
  }).join("");
  return walk(root, 0, "") + leaves(root, 0);
}

/* Light syntax colouring for the Diff tab, like GitHub's: comments in a lighter grey, strings in blue. Comment
   syntax comes from the file's extension; strings are read so a "//" inside "http://..." isn't taken for a comment.
   `st` carries an open block comment from one line to the next. */
const HL_LANG = (() => {
  const c = { line: ["//"], block: [["/*", "*/"]], q: "\"'`" }, hash = { line: ["#"], block: [], q: "\"'" }, sql = { line: ["--"], block: [["/*", "*/"]], q: "'\"" };
  const xml = { line: [], block: [["<!--", "-->"]], q: "\"" }, prose = { line: [], block: [["<!--", "-->"]], q: "" };
  const ps = { line: ["#"], block: [["<#", "#>"]], q: "\"'" }, lua = { line: ["--"], block: [], q: "\"'" };
  const m = {};
  "js jsx ts tsx mjs cjs go java kt kts c h cc cpp hpp cs swift rs scala dart php css scss less proto groovy gradle".split(" ").forEach(e => m[e] = c);
  "py sh bash zsh rb yml yaml toml r pl conf ini env tf hcl dockerfile makefile mk cmake nix".split(" ").forEach(e => m[e] = hash);
  "sql".split(" ").forEach(e => m[e] = sql); "lua".split(" ").forEach(e => m[e] = lua);
  "html htm xml wxs wxi svg vue xaml csproj props targets".split(" ").forEach(e => m[e] = xml);
  "md mdx markdown txt".split(" ").forEach(e => m[e] = prose);  // prose: an apostrophe isn't a string
  "ps1 psm1 psd1".split(" ").forEach(e => m[e] = ps);
  return m;
})();
const hlLang = path => { const base = path.split("/").pop().toLowerCase(), ext = base.includes(".") ? base.split(".").pop() : base; return HL_LANG[ext] || null; };
function hlLine(text, lang, st) {
  if (!lang) return esc(text);
  let out = "", i = 0, buf = "";
  const flush = () => { if (buf) { out += esc(buf); buf = ""; } };
  const span = (cls, s) => { flush(); out += `<span class="${cls}">${esc(s)}</span>`; };
  while (i < text.length) {
    if (st.block) {  // inside a comment that started on an earlier line
      const end = text.indexOf(st.block, i);
      if (end < 0) { span("tk-c", text.slice(i)); return out; }
      span("tk-c", text.slice(i, end + st.block.length)); i = end + st.block.length; st.block = null; continue;
    }
    const ch = text[i];
    if (lang.q.includes(ch)) {
      let j = i + 1;
      while (j < text.length && text[j] !== ch) j += text[j] === "\\" ? 2 : 1;
      span("tk-s", text.slice(i, j + 1)); i = j + 1; continue;
    }
    const lc = lang.line.find(t => text.startsWith(t, i) && (t !== "#" || !/[\w$]/.test(text[i - 1] || "")));
    const bc = lang.block.find(([a]) => text.startsWith(a, i));
    if (bc) { st.block = bc[1]; span("tk-c", bc[0]); i += bc[0].length; continue; }
    if (lc) { span("tk-c", text.slice(i)); return out; }
    buf += ch; i++;
  }
  flush();
  return out;
}

function diffFile(f, i, threads, open) {
  const [g, cls] = DF_ICON[f.status] || DF_ICON.modified;
  const keys = new Set(f.hunks.flatMap(h => h.lines.map(rowKey)));
  const at = {}, loose = [];
  threads.forEach(t => t.outdated || !keys.has(t.end) ? loose.push(t) : (at[t.end] = at[t.end] || []).push(t));
  const lang = hlLang(f.path);
  let st = { block: null };  // block comments carry over within a hunk
  const row = l => {
    const k = rowKey(l);
    return `<tr class="df-l ${l.t === "+" ? "add" : l.t === "-" ? "del" : ""}" data-k="${k}"><td class="df-n" data-df-pick>${l.old ?? ""}</td><td class="df-n" data-df-pick>${l.new ?? ""}<button class="df-plus" data-df-pick tabindex="-1" aria-label="Ask the AI about this line">+</button></td><td class="df-s">${l.t === " " ? "" : l.t}</td><td class="df-c">${hlLine(l.text, lang, st) || " "}</td></tr>${(at[k] || []).map(t => `<tr class="df-trow"><td colspan="4">${diffThread(t)}</td></tr>`).join("")}`;
  };
  const body = f.binary ? `<p class="muted small df-pad">Binary file: no lines to show.</p>` : f.too_big ? `<p class="muted small df-pad">This file's diff is too big to show here (${n_(f.additions)} added, ${n_(f.deletions)} removed).</p>`
    : `<table class="df-t" data-path="${esc(f.path)}"><colgroup><col class="c-n"><col class="c-n"><col class="c-s"><col></colgroup><tbody>${f.hunks.map(h => { st = { block: null }; return `<tr class="df-h"><td colspan="2"></td><td colspan="2">${esc(h.header)}</td></tr>${h.lines.map(row).join("")}`; }).join("")}</tbody></table>`;
  return `<details class="df-file" id="df-f${i}" data-path="${esc(f.path)}"${open ? " open" : ""}><summary><span class="df-chev">${icon("chev")}</span><span class="df-st ${cls}">${g}</span><span class="df-path">${esc(f.status === "renamed" && f.old_path ? `${f.old_path} → ${f.path}` : f.path)}</span>${threads.length ? `<span class="df-cnt">${icon("review")}${threads.length}</span>` : ""}<span class="grow"></span><span class="small"><span class="add">+${f.additions}</span> <span class="del">−${f.deletions}</span></span></summary>
    ${loose.length ? `<div class="df-loose">${loose.map(diffThread).join("")}</div>` : ""}${body}</details>`;
}

/* An AI thread on some diff lines: a review conversation, one row per message (avatar, who and when, then the text) */
const avMe = () => `<span class="th-av me" aria-hidden="true">You</span>`;
const avAi = () => `<span class="th-av ai" aria-hidden="true">${logoSvg(28)}</span>`;
function diffThread(t) {
  const where = keyLabel(t.start, t.end);
  if (t.resolved) return `<div class="th resolved" data-th="${esc(t.id)}"><span class="tag ok">Resolved</span><span class="muted small">${esc(where)} · ${plural(t.messages.length, "message")}</span><span class="grow"></span><button class="btn small" data-th-act="reopen">Show</button></div>`;
  const answers = t.messages.filter(m => m.role === "ai" && !m.error), spent = answers.reduce((a, m) => a + (m.cost || 0), 0);
  const cost = c => c ? `<span class="th-cost" title="What this answer cost">${c < 0.01 ? "&lt;$0.01" : usd(c)}</span>` : "";
  const msgs = t.messages.map(m => m.role === "me"
    ? `<div class="th-m">${avMe()}<div class="th-c"><div class="th-who"><b>You</b>${m.ts ? `<span>${ago(m.ts)}</span>` : ""}</div><div class="th-text">${esc(m.text)}</div></div></div>`
    : `<div class="th-m${m.error ? " bad" : ""}">${avAi()}<div class="th-c"><div class="th-who"><b>LFG</b><span class="tag blue">AI</span>${m.error ? '<span class="tag bad">didn\'t answer</span>' : ""}${m.ts ? `<span>${ago(m.ts)}</span>` : ""}${VIA_SAY[m.via] ? `<span>${VIA_SAY[m.via]}</span>` : ""}${cost(m.cost)}</div><div class="md th-text">${md(m.text)}</div></div></div>`).join("");
  return `<div class="th" data-th="${esc(t.id)}"><div class="th-h"><span class="th-lines">${icon("review")}${esc(where.charAt(0).toUpperCase() + where.slice(1))}</span>${t.outdated ? tagHtml("outdated", "warn") : ""}${answers.length ? `<span class="muted small">${plural(answers.length, "answer")}${spent ? ` · ${usd(spent)}` : ""}</span>` : ""}<span class="grow"></span><button class="btn small" data-th-act="resolve"${t.job ? " disabled" : ""}>Resolve</button><button class="icon-btn" data-th-act="delete" title="Delete this thread" aria-label="Delete this thread">&times;</button></div>
    <div class="th-list">${msgs}${t.job ? `<div class="th-m" data-df-working>${avAi()}<div class="th-c"><div class="th-who"><b>LFG</b><span class="tag blue">AI</span></div><div class="th-text muted"><span class="spin"></span> Reading the diff and its callers…</div></div></div>` : ""}</div>
    <div class="th-reply df-reply"><textarea rows="1" placeholder="${t.job ? "Wait for the answer…" : "Reply or ask a follow-up"}"${t.job ? " disabled" : ""}></textarea><button class="btn primary small" data-th-reply${t.job ? " disabled" : ""}>Reply</button></div></div>`;
}


/* Did Claude use LFG in this repo's replies? From each reply's **LFG:** line, recorded by the Stop hook. */
function lfgReplies(r) {
  const c = (r || {}).counts || {}, total = Object.values(c).reduce((a, x) => a + x, 0);
  if (!total) return "";
  const why = x => x.kind === "missing" ? '<span class="muted">The reply didn\'t say whether it used LFG</span>' : txt(x.detail || "no reason given");
  return section(`${repoName()}: did Claude use LFG?`, `<div class="cols">${stat("Used an LFG skill", n(c.skill || 0), `of ${n(total)} ${total === 1 ? "reply" : "replies"}`)}${stat("Used LFG's tools", n(c.tools || 0), "graphs, dev-graph, lfg commands")}${stat("Didn't use LFG", n(c["not-used"] || 0), "each with its reason, below")}${stat("Didn't say", n(c.missing || 0), c.missing ? "replies without the LFG line" : "every reply said")}</div>
    ${(r.recent || []).length ? `<div class="box mt">${table(r.recent, [{ k: "ts", label: "When", html: x => `<span class="nowrap">${ago(x.ts)}</span>` }, { k: "detail", label: "Why not", html: why }], { filter: false })}</div>` : ""}`, "last 30 days");
}

PAGES.integrations = integrationsPage;

/* Todos: one list across every project, each todo to do, in progress, cancelled or done. A todo becomes a Linear
   ticket only from its Create Linear ticket button, after you confirm the exact text; it is then tagged with the
   issue's id, linked to Linear. */
const TD_SAY = { todo: "To do", in_progress: "In progress", cancelled: "Cancelled", done: "Done" };
let tdPoll = null;
PAGES.todos = async () => {
  const d = await api("todos");
  if (d.available === false) return unavailable(d);
  state.todos = d;
  const of = st => d.todos.filter(t => t.status === st);
  const lin = t => t.linear && t.linear.key ? `<a class="tg on td-lin" href="${esc(t.linear.url)}" target="_blank" rel="noopener noreferrer" title="Open ${esc(t.linear.key)} in Linear${t.linear.project ? ` · ${esc(t.linear.project)}` : ""}${t.linear.assignee ? ` · ${esc(t.linear.assignee === "me" ? "you" : t.linear.assignee)}` : ""}">${esc(t.linear.key)} ↗</a>`
    : t.linear_job ? `<span class="tg td-lin" data-td-creating><span class="spin"></span>Creating Linear ticket…</span>`
    : t.linear_error ? `<span class="td-err small" title="${esc(t.linear_error)}">Linear ticket not created: ${fmtWhy(t.linear_error)}</span>` : "";
  const row = t => `<div class="td st-${t.status}" data-td="${esc(t.id)}">
      <select class="td-st" data-td-status aria-label="Status">${d.statuses.map(k => `<option value="${k}"${k === t.status ? " selected" : ""}>${TD_SAY[k]}</option>`).join("")}</select>
      <div class="grow td-main"><div class="td-text" contenteditable="plaintext-only" spellcheck="true" data-td-text>${esc(t.text)}</div>
        <div class="td-m">${lin(t)}${t.repo ? `<span class="tag">${icon("folder")}${esc(repoName(t.repo))}</span>` : ""}<span class="td-when">${ago(t.status_at || t.created)}</span>${t.notes ? `<span class="muted small" title="${esc(t.notes)}">· notes</span>` : ""}</div></div>
      <span class="td-a">${t.linear && t.linear.key || t.linear_job ? "" : `<button class="btn small" data-td-linear>${t.linear_error ? "Try again" : "Create Linear ticket"}</button>`}<button class="icon-btn" data-td-more title="Notes and more" aria-label="Notes and more">⋯</button></span></div>`;
  const group = (st, open) => { const xs = of(st); if (!xs.length) return ""; const body = `<div class="box td-list">${xs.map(row).join("")}</div>`;
    return open ? section(TD_SAY[st], body, `<span class="tag">${xs.length}</span>`) : `<details class="td-fold"><summary>${TD_SAY[st]} <span class="tag">${xs.length}</span></summary>${body}</details>`; };
  const active = d.counts.todo + d.counts.in_progress;
  return `${head("Todos", "Things to do, across all your projects. Make any of them a Linear ticket when it needs one.")}
    <form class="td-add" data-td-add><span class="td-add-ico">${icon("plus")}</span><input type="text" id="td-new" placeholder="Add a todo and press Enter" maxlength="300" autocomplete="off"><button class="btn primary">Add</button></form>
    ${group("in_progress", true)}${group("todo", true)}${active ? "" : `<div class="box">${empty("Nothing to do", "Add one above. It's tagged with the project you're in.")}</div>`}
    ${group("done", false)}${group("cancelled", false)}`;
};

function wireTodos(root) {
  const d = state.todos;
  clearTimeout(tdPoll);
  if (!d || !d.todos) return;
  const byId = Object.fromEntries(d.todos.map(t => [t.id, t]));
  const act = async (what, body) => { const r = await save(what, body); if (!r.ok) alert(String(r.why || "That didn't work.").replace(/`/g, "")); return r; };
  const reload = () => route({ soft: true });
  const form = $("[data-td-add]", root);
  if (form) form.onsubmit = async e => { e.preventDefault(); const i = $("#td-new", root); if (!i.value.trim()) return; const r = await act("todo_add", { text: i.value, repo: state.repo }); if (r.ok) { i.value = ""; await reload(); const n = $("#td-new"); if (n) n.focus(); } };
  $$(".td", root).forEach(el => {
    const t = byId[el.dataset.td];
    const st = $("[data-td-status]", el); if (st) st.onchange = async () => { await act("todo_update", { id: t.id, status: st.value }); reload(); };
    const tx = $("[data-td-text]", el);
    if (tx) {
      tx.onkeydown = e => { if (e.key === "Enter") { e.preventDefault(); tx.blur(); } if (e.key === "Escape") { tx.textContent = t.text; tx.blur(); } };
      tx.onblur = async () => { const v = tx.textContent.replace(/\s+/g, " ").trim(); if (v === t.text) return; if (!v) { tx.textContent = t.text; return; } const r = await act("todo_update", { id: t.id, text: v }); if (r.ok) t.text = v; else tx.textContent = t.text; };
    }
    const ln = $("[data-td-linear]", el); if (ln) ln.onclick = () => todoToLinear(t, d.linear);
    const more = $("[data-td-more]", el); if (more) more.onclick = () => todoMore(t);
  });
  if ($("[data-td-creating]", root)) tdPoll = setTimeout(() => { if ((location.hash.slice(1) || "").split("/")[0] === "todos" && !document.activeElement.closest(".td-main, .td-add, #drawer")) reload(); }, 4000);
}

function todoMore(t) {
  openDrawer("Todo", `<div class="readable td-sheet"><label>Todo<input type="text" id="td-t" maxlength="300" value="${esc(t.text)}"></label>
    <label>Status<select id="td-s">${Object.entries(TD_SAY).map(([k, v]) => `<option value="${k}"${k === t.status ? " selected" : ""}>${v}</option>`).join("")}</select></label>
    <label>Notes<textarea id="td-n" rows="6" placeholder="Anything worth keeping with it">${esc(t.notes || "")}</textarea></label>
    <p class="muted small">${t.repo ? `From ${esc(repoName(t.repo))} · ` : ""}added ${ago(t.created)}${t.linear && t.linear.key ? ` · Linear <a href="${esc(t.linear.url)}" target="_blank" rel="noopener noreferrer">${esc(t.linear.key)} ↗</a>` : ""}</p>
    <p class="row"><button class="btn primary" id="td-save">Save</button><span class="grow"></span><button class="btn small bad" id="td-del">Delete</button></p></div>`);
  $("#td-save").onclick = async () => { const r = await save("todo_update", { id: t.id, text: $("#td-t").value, notes: $("#td-n").value, status: $("#td-s").value }); if (!r.ok) return alert(String(r.why || "Not saved.")); closeDrawer(); route({ soft: true }); };
  $("#td-del").onclick = async () => { if (!confirm(`Delete this todo?\n\n${t.text}${t.linear && t.linear.key ? `\n\n(${t.linear.key} stays in Linear.)` : ""}`)) return; const r = await save("todo_delete", { id: t.id }); if (!r.ok) return alert(String(r.why || "Not deleted.")); closeDrawer(); route({ soft: true }); };
}

/* Create Linear ticket: you check the exact title and description and pick the team, project and assignee from
   Linear's own lists (fetched read-only, kept a day); only then is one issue created, and the todo is tagged with
   its id and linked to it. */
let tlPoll = null;
async function todoToLinear(t, lin) {
  const desc = [t.notes || "", t.repo ? `Repo: ${repoName(t.repo)}` : ""].filter(Boolean).join("\n\n");
  openDrawer("Create Linear ticket", `<div class="readable td-sheet">
    <p class="row small" id="tl-draft"><span class="spin"></span><span class="grow">Writing the ticket with your <code>/linear-ticket</code> skill… Nothing is sent to Linear.</span></p>
    <label>Title<input type="text" id="tl-t" maxlength="300" value="${esc(t.text)}" disabled></label>
    <label>Description<textarea id="tl-d" rows="12" placeholder="Optional" disabled>${esc(desc)}</textarea></label>
    <div id="tl-opts"><p class="muted small"><span class="spin"></span> Getting your Linear teams, projects and people…</p></div>
    ${t.linear_error ? `<p class="td-err small">Last try: ${fmtWhy(t.linear_error)}</p>` : ""}
    <p class="muted small">Creates this one issue in Linear, exactly as written and picked here. Nothing else in Linear changes.</p>
    <p class="row"><button class="btn primary" id="tl-go" disabled>Create Linear ticket</button><span class="muted small" id="tl-msg"></span></p></div>`);
  const box = $("#tl-opts"), go = $("#tl-go");
  const pick = { team: lin.team || "", project: "", assignee: "" };
  // the preview: your /linear-ticket skill writes the title and description, you change anything, then Create
  const ready = { draft: false, opts: false }, canGo = () => { go.disabled = !(ready.draft && ready.opts); };
  const draft = async () => {
    const note = $("#tl-draft"), ti = $("#tl-t"), de = $("#tl-d");
    ready.draft = false; canGo(); ti.disabled = de.disabled = true;
    note.innerHTML = '<span class="spin"></span><span class="grow">Writing the ticket with your <code>/linear-ticket</code> skill… Nothing is sent to Linear.</span>';
    const r = await save("todo_draft", { id: t.id }).catch(e => ({ ok: false, why: e.message }));
    if (!document.body.contains(note)) return;
    if (r.ok) { ti.value = r.title; de.value = r.description; grow(de); }
    note.innerHTML = r.ok
      ? `<span class="grow muted">Written by <code>/${esc(r.skill)}</code>. Check it and change anything before you create it.</span><button class="btn small" data-tl-redraft>Write it again</button>`
      : `<span class="grow td-err">Couldn't write it with the skill: ${fmtWhy(r.why || "no answer")}. Write it here instead.</span><button class="btn small" data-tl-redraft>Try again</button>`;
    $("[data-tl-redraft]", note).onclick = draft;
    ti.disabled = de.disabled = false; ready.draft = true; canGo();
  };
  draft();
  const paint = o => {
    if (!document.body.contains(box)) return;
    if (!o.teams.length) {
      box.innerHTML = o.loading ? `<p class="muted small"><span class="spin"></span> Getting your Linear teams, projects and people…</p>`
        : `<p class="td-err small">${fmtWhy(o.error || o.why || "Couldn't read Linear.")}</p><p><a href="#" class="small" data-tl-refresh>Try again</a></p>`;
    } else {
      if (!o.teams.some(x => x.key === pick.team)) pick.team = (o.teams.find(x => x.key === o.default_team) || o.teams.find(x => !x.retired) || o.teams[0]).key;
      const projects = o.projects.filter(p => !p.teams.length || p.teams.includes(pick.team));
      if (!projects.some(p => p.name === pick.project)) pick.project = "";
      const opt = (v, label, cur) => `<option value="${esc(v)}"${v === cur ? " selected" : ""}>${esc(label)}</option>`;
      box.innerHTML = `<label>Team<select id="tl-team">${o.teams.map(x => opt(x.key, `${x.name} (${x.key})${x.retired ? " · retired" : ""}`, pick.team)).join("")}</select></label>
        <label>Project<select id="tl-project">${opt("", "No project", pick.project)}${projects.map(p => opt(p.name, p.name, pick.project)).join("")}</select></label>
        <label>Assignee<select id="tl-who">${opt("", "Unassigned", pick.assignee)}${opt("me", "Me", pick.assignee)}${o.users.map(u => opt(u.name, u.display && u.display !== u.name ? `${u.name} (${u.display})` : u.name, pick.assignee)).join("")}</select></label>
        <p class="muted small">${o.loading ? '<span class="spin"></span> Updating from Linear… · ' : o.at ? `From Linear ${ago(new Date(o.at * 1000).toISOString())} · ` : ""}<a href="#" data-tl-refresh>Refresh</a></p>`;
      $("#tl-team").onchange = e => { pick.team = e.target.value; paint(o); };
      $("#tl-project").onchange = e => { pick.project = e.target.value; };
      $("#tl-who").onchange = e => { pick.assignee = e.target.value; };
    }
    ready.opts = !!o.teams.length; canGo();
    const r = $("[data-tl-refresh]", box); if (r) r.onclick = e => { e.preventDefault(); load(true); };
    clearTimeout(tlPoll);
    if (o.loading) tlPoll = setTimeout(() => load(false), 3000);
  };
  const load = async fresh => paint(await api("linear_options", fresh ? { fresh: "1" } : {}).then(o => Object.assign({ teams: [], projects: [], users: [] }, o)));
  load(false);
  go.onclick = async () => {
    const who = pick.assignee === "me" ? "you" : pick.assignee || "nobody";
    if (!confirm(`Create this ticket in Linear?\n\n${$("#tl-t").value}\n\nTeam ${pick.team}${pick.project ? ` · project ${pick.project}` : ""} · assigned to ${who}`)) return;
    go.disabled = true; go.textContent = "Starting…";
    const r = await save("todo_linear", { id: t.id, title: $("#tl-t").value, description: $("#tl-d").value, team: pick.team, project: pick.project, assignee: pick.assignee });
    if (!r.ok) { go.disabled = false; go.textContent = "Create Linear ticket"; $("#tl-msg").innerHTML = fmtWhy(r.why || "Not started."); return; }
    clearTimeout(tlPoll); closeDrawer(); route({ soft: true });
  };
}

PAGES.usage = async () => {
  const [d, H] = await Promise.all([api("usage", { days: UR.days > 30 ? 90 : 30 }), api("headroom", { days: UR.days > 30 ? 90 : 30 })]);
  if (d.pending) {
    pageTimer("usage", 2500, () => { if ((location.hash.slice(1) || "").startsWith("usage")) softRoute(); });
    return `${head("Usage", "What Claude Code used and what it would cost at API prices, across every session on this computer.")}<div class="loading">Adding up every session's usage… the first time after an update this reads every transcript again, which can take a minute.</div><div class="skeleton" style="height:260px"></div>`;
  }
  const hrDay = Object.fromEntries((((H || {}).when || {}).days || []).map(x => [x.day, x]));
  const since = new Date(Date.now() - (UR.days - 1) * 864e5).toISOString().slice(0, 10);
  const days = (d.days || []).filter(x => x.day >= since).map(x => ({ ...x, hr_saved: (hrDay[x.day] || {}).saved || 0, hr_usd: (hrDay[x.day] || {}).usd || 0 }));
  const hrPending = H && H.pending;
  const rangeUsd = days.reduce((a, x) => a + (x.usd || 0), 0), hrUsd = days.reduce((a, x) => a + (x.hr_usd || 0), 0);
  const revUsd = days.reduce((a, x) => a + (x.review_usd || 0), 0), revs = (d.reviews || []).filter(r => r.last >= since);
  const hrTokens = days.reduce((a, x) => a + (x.hr_saved || 0), 0);
  const t = days.reduce((a, x) => { for (const k of ["input", "output", "cache_read", "cache_write"]) a[k] += x[k] || 0; return a; }, { input: 0, output: 0, cache_read: 0, cache_write: 0 });
  const hit = pct(t.cache_read, t.cache_read + t.input + t.cache_write);
  /* models with no price, and how many tokens of theirs fall in the range shown (their dollars count as $0) */
  const unpriced = (d.unpriced || []).map(m => ({ m, tokens: days.reduce((a, x) => { const v = (x.models || {})[m] || {}; return a + (v.input || 0) + (v.output || 0) + (v.cache_read || 0) + (v.cache_write_5m || 0) + (v.cache_write_1h || 0); }, 0) })).filter(x => x.tokens);
  const hr = d.headroom || {}, life = hr.lifetime || {}, sp = d.spend || {};
  const seg = (key, opts) => `<div class="seg inline">${opts.map(([v, l]) => `<label class="${UR[key] === v ? "on" : ""}"><input type="radio" name="ur-${key}" data-ur="${key}" value="${v}" ${UR[key] === v ? "checked" : ""}>${l}</label>`).join("")}</div>`;
  const rows = bucket(days, UR.by, rs => addRows(rs, ["input", "output", "cache_read", "cache_write", "usd", "hr_saved", "hr_usd"]));
  const usdFmt = v => usd(v || 0);
  const filters_row = `<div class="row filters">${seg("days", [[7, "7 days"], [14, "14 days"], [30, "30 days"], [90, "90 days"]])}${seg("by", [["day", "By day"], ["week", "By week"]])}${seg("measure", [["usd", "Dollars"], ["tokens", "Tokens"]])}</div>`;
  const ghost = { ghost: true };
  if (hrPending) pageTimer("usage", 2500, () => { if ((location.hash.slice(1) || "").startsWith("usage")) softRoute(); });
  const chart = UR.measure === "usd"
    ? iChart(rows.map(r => ({ label: r.label, short: r.short, values: [r.usd, r.hr_usd], raw: r })), [["Actual cost", "var(--series-1)", usdFmt], ["Saved by Headroom", "var(--series-1)", usdFmt, ghost]],
        { title: "Cost per " + UR.by, onPick: i => usageDetail(rows, i), total: (x, hid) => hid.has(1) ? "" : `Without Headroom: ${usd((x.values[0] || 0) + (x.values[1] || 0))}` })
    : iChart(rows.map(r => ({ label: r.label, short: r.short, values: [(r.input || 0) + (r.cache_write || 0), r.cache_read || 0, r.output || 0, r.hr_saved || 0], raw: r })), [["Sent new", "var(--series-1)"], ["Reused from cache", "var(--series-2)"], ["Written by Claude", "var(--series-3)"], ["Removed by Headroom", "var(--series-1)", compact, ghost]],
        { title: "Tokens per " + UR.by, hidden: [1], onPick: i => usageDetail(rows, i), total: (x, hid) => hid.has(3) ? "" : `Without Headroom: ${compact(x.values.reduce((a, v, j) => a + (hid.has(j) ? 0 : v || 0), 0))} tokens` });
  state.usageRows = rows;
  return `${head("Usage", "What Claude Code used and what it would cost at API prices, across every session on this computer.")}
    ${filters_row}
    <div class="cols">${stat(`Cost, last ${UR.days} days`, usd(rangeUsd), "the work priced at Anthropic's API rates, from every session's log; on a subscription you pay your plan, not this")}${stat("Cost today", usd(sp.today || 0), "since midnight")}${stat(`PR reviews, last ${UR.days} days`, usd(revUsd), revs.length ? `${pct(revUsd, rangeUsd)}% of the cost, ${plural(revs.length, "review session")}` : "no review sessions")}${stat(`Saved by Headroom, last ${UR.days} days`, hrTokens ? usd(hrUsd) : "—", hrTokens ? `${compact(hrTokens)} tokens removed, by Headroom's count` : hrPending ? "checking…" : "nothing recorded")}</div>
    ${unpriced.length ? `<div class="callout warn">Not priced: ${unpriced.map(x => `<span class="mono">${esc(x.m)}</span> (${compact(x.tokens)} tokens)`).join(", ")}. Claude Code logged this work without a model LFG has a price for, so it's left out of the dollar figures above, which are low by that much. The token figures include it.</div>` : ""}
    <div class="cols">${stat(`Tokens sent, last ${UR.days} days`, compact(t.input + t.cache_read + t.cache_write), `${hit}% reused from cache, which costs about a tenth as much`)}${stat(`Tokens written, last ${UR.days} days`, compact(t.output), "Claude's replies")}</div>
    ${section(UR.measure === "usd" ? `Cost per ${UR.by}` : `Tokens per ${UR.by}`, `<div class="box pad" id="usage-main">${chart}<div id="usage-detail"></div></div>`, UR.measure === "usd"
      ? `the solid bar is what that ${UR.by}'s work cost at Anthropic's API prices; the dashed part on top is what Headroom saved, so the whole bar is what it would have cost without Headroom${hrPending ? " (Headroom's numbers are still loading)" : ""}. Hover for numbers, click for the breakdown by model.`
      : `solid: what was sent (new text, and text reused from cache, hidden until you click its key) and what Claude wrote back. Dashed on top: what Headroom removed before sending, so the whole bar is what would have been sent without it${hrPending ? " (Headroom's numbers are still loading)" : ""}.`)}
    ${(d.models || []).length ? section("By model", `<div class="box">${table(d.models, [{ k: "model", label: "Model" }, { k: "input", label: "Sent", num: true, html: r => compact((r.input || 0) + (r.cache_read || 0) + (r.cache_write || 0)) }, { k: "output", label: "Written", num: true, html: r => compact(r.output) }, { k: "usd", label: "Cost", num: true, html: r => r.usd != null ? usd(r.usd) : "" }], { filter: false })}</div>`, "last " + (d.days || []).length + " days") : ""}
    ${revs.length ? section("PR reviews", `<div class="box">${table(revs, [{ k: "pr", label: "PR", html: r => esc(r.pr) }, { k: "last", label: "Last used", html: r => `<span class="nowrap">${esc(r.last)}</span>` }, { k: "tokens", label: "Tokens", num: true, html: r => compact(r.tokens) }, { k: "usd", label: "Cost", num: true, html: r => usd(r.usd) }], { filter: false, sort: "last" })}</div>`, "sessions that started with /review-pr, /lfg:review or the dashboard's Review button, with their subagents") : ""}
    <div id="hr-detail" data-fill><div class="loading">Reading Headroom's logs…</div></div>
    ${lfgReplies(d.replies)}
    ${(d.runs || []).length ? section(`${repoName()}, by run`, `<div class="box">${table(d.runs, [{ k: "run", label: "Run", html: r => r.run && r.run !== "(no run)" ? `<a href="#runs/${encodeURIComponent(r.run)}">${esc(runName({ slug: r.run.slice(14) }))}</a>` : '<span class="muted">Outside a run</span>' }, { k: "input", label: "Sent", num: true, html: r => compact((r.input || 0) + (r.cache_read || 0)) }, { k: "output", label: "Written", num: true, html: r => compact(r.output) }], { filter: false })}</div>`, "this project only, all time") : ""}`;
};
function usageDetail(rows, i) {
  const box = $("#usage-detail");
  if (!box) return;
  if (i == null) { box.innerHTML = ""; return; }
  const r = rows[i], ms = Object.entries(r.models || {}).map(([m, v]) => ({ model: m, ...v })).sort((a, b) => (b.usd || 0) - (a.usd || 0));
  box.innerHTML = `<div class="k">${esc(r.label)}: ${usd(r.usd || 0)}, ${compact((r.input || 0) + (r.cache_read || 0) + (r.cache_write || 0))} tokens sent, ${compact(r.output || 0)} written</div>
    <div class="box">${table(ms, [{ k: "model", label: "Model" }, { k: "usd", label: "Cost", num: true, html: x => usd(x.usd || 0) }, { k: "input", label: "Sent new", num: true, html: x => compact((x.input || 0) + (x.cache_write_5m || 0) + (x.cache_write_1h || 0)) }, { k: "cache_read", label: "Reused", num: true, html: x => compact(x.cache_read || 0) }, { k: "output", label: "Written", num: true, html: x => compact(x.output || 0) }], { filter: false, sort: "usd" })}</div>`;
  mountTables(box);
}
function wireUsage(root) {
  $$("[data-ur]", root).forEach(el => el.onchange = () => {
    const k = el.dataset.ur; UR[k] = k === "days" ? +el.value : el.value;
    $$(".seg label", el.closest(".seg")).forEach(l => l.classList.toggle("on", l.contains(el)));
    const m = $("#usage-main");
    if (m) { m.classList.add("is-loading"); m.setAttribute("aria-busy", "true"); }
    softRoute();
  });
  wireICharts(root);
}

async function loadHeadroom() {
  const box = $("#hr-detail");
  if (!box) return;
  const d = await api("headroom", { days: UR.days > 30 ? 90 : 30 });
  if (d.pending) { setTimeout(loadHeadroom, 2000); return; }
  if (d.available === false) { box.innerHTML = ""; return; }
  const W = d.when || {}, X = d.where || {};
  const since = new Date(Date.now() - (UR.days - 1) * 864e5).toISOString().slice(0, 10);
  const days = (W.days || []).filter(x => x.day >= since);
  const rows = bucket(days, UR.by, rs => addRows(rs, ["saved", "calls", "usd", "before"]));
  const status = d.routed ? `<span class="row" style="gap:8px">${dot(d.live ? "ok" : "bad")}<span>${d.live ? "On: every Claude Code session goes through it." : "Every terminal session goes through it, but it isn't running right now, so they can't reach Claude. Run <code>lfg headroom restart</code> in a terminal."}</span></span>` : d.live ? `<span class="row" style="gap:8px">${dot("warn")}<span>Running, but Claude Code doesn't go through it.</span></span>` : `<span class="row" style="gap:8px">${dot("")}<span>Off.</span></span>`;
  const hours = (W.today_by_hour || []).filter(h => h.calls).sort((a, b) => b.calls - a.calls).slice(0, 3);
  morph(box, section("Saved by Headroom", `<p class="muted">Headroom is a small program on this computer that every request from Claude Code passes through on its way to Anthropic. It removes repeated and unneeded text first, so less is sent and billed.</p>
    <p>${status}</p>
    ${rows.length ? `<p class="muted small">In this range: ${compact(rows.reduce((a, x) => a + (x.saved || 0), 0))} tokens removed from ${n(rows.reduce((a, x) => a + (x.calls || 0), 0))} requests, about ${usd(rows.reduce((a, x) => a + (x.usd || 0), 0))} by Headroom's count. It's the dashed part of the chart above.${hours.length ? ` Busiest today: ${hours.map(h => `${h.hour}:00 (${n(h.calls)} requests)`).join(", ")}.` : ""}</p>` : ""}
    ${(X.sessions || []).length ? `<div class="k">Where it saved the most, since ${ago(X.since)}</div>
      <p class="muted small">Headroom's request log only keeps the last few hours. Requests are matched to a session by their token counts: ${n(X.matched)} of ${n(X.requests)} matched one session exactly.</p>
      <div class="box">${table(X.repos, [{ k: "repo", label: "Repo" }, { k: "sessions", label: "Sessions", num: true }, { k: "calls", label: "Requests", num: true }, { k: "saved", label: "Tokens removed", num: true, html: r => compact(r.saved) }], { filter: false })}</div>
      <div class="box mt">${table(X.sessions, [{ k: "name", label: "Session", html: r => `${esc(r.name)}<div class="sub">${esc(r.repo)}${r.group ? " · " + esc(r.group) : ""} · last ${ago(r.last)}</div>` }, { k: "calls", label: "Requests", num: true }, { k: "saved", label: "Tokens removed", num: true, html: r => compact(r.saved) }, { k: "percent", label: "Smaller by", num: true, html: r => r.percent + "%" }], { filter: false, sort: "saved" })}</div>` : ""}`));
  mountTables(box);
  wireICharts(box);
}
PAGES.settings = async () => {
  const [cfg, sk, cm, unlocked] = await Promise.all([api("settings"), api("skills"), api("claudemd"), isUnlocked()]);
  state.settings = { cfg, sk, cm, unlocked };
  return `${head("Settings", unlocked ? "Changes are checked, refused if they look like a password or key, and backed up." : "")}
    ${unlocked ? "" : lockedNote("make changes")}
    <div class="section">${tabs("settings", [["claudecode", "Claude Code", null, settingsClaudeCode], ["general", "General", null, settingsGeneral], ["tools", "Connections", null, settingsTools], ["storage", "Disk space", null, settingsStorage], ["rules", "Rules", null, settingsRules], ["claudemd", "Your instructions", null, settingsClaude], ["appearance", "Appearance", null, settingsAppearance]])}</div>`;
};

// ------------------------------------------------------------------ skills: every skill Claude Code loads, from every source
const SRC_LABEL = { personal: "Yours", "personal command": "Your command", project: "This project", plugin: "Plugin" };
PAGES.skills = async () => {
  const [sk, cm, unlocked] = await Promise.all([api("skills"), api("claudemd"), isUnlocked()]);
  state.settings = Object.assign(state.settings || {}, { sk, cm, unlocked, cfg: (state.settings || {}).cfg });
  return `${head("Skills", "Everything Claude Code can load as a skill on this computer: yours, this project's and every plugin's, LFG's included.")}
    ${unlocked ? "" : lockedNote("change skills")}
    <div class="section">${tabs("skillspage", [["all", "All skills", null, () => '<div id="skills-box"><div class="loading">Reading skills…</div></div>'], ["mine", "Your skills & references", null, () => '<div id="mylib-box"><div class="loading">Reading ~/.claude…</div></div>'], ["lfgedit", "Edit LFG skills", null, settingsSkills]])}</div>`;
};
async function loadFeatures() {
  const box = $("#features-section");
  if (!box) return;
  const d = await api("onboarding");
  state.onboardData = d;
  state.pages = d.pages || NAV.map(p => p[0]);
  const unlocked = state.settings?.unlocked;
  const showAllCb = $("#show-all-pages");
  // Wire show-all-pages toggle
  if (showAllCb) {
    showAllCb.checked = d.show_all || false;
    showAllCb.onchange = async () => {
      showAllCb.disabled = true;
      const r = await save("pages_show_all", { on: showAllCb.checked });
      if (r.ok) applyPages(r);
      showAllCb.disabled = false;
    };
  }
  // Render all 5 feature toggles, none disabled
  box.innerHTML = (d.features || []).map(f =>
    `<label class="row"><input type="checkbox" data-feat="${esc(f.id)}" ${f.enabled ? "checked" : ""} ${!unlocked ? "disabled" : ""}> <div><b>${esc(f.name)}</b><div class="muted small">${esc(f.description)}</div></div></label>`
  ).join("") + '<span class="save-msg ml" id="feat-msg"></span>';
  // Wire feature toggles: save immediately on change
  $$("[data-feat]", box).forEach(cb => {
    cb.onchange = async () => {
      cb.disabled = true;
      const r = await save("feature_toggle", { feature: cb.dataset.feat, enabled: cb.checked });
      saidMsg($("#feat-msg"), r, r.ok ? "Saved." : "");
      if (r.ok) applyPages(r);
      cb.disabled = false;
    };
  });
}

async function loadSkills() {
  const box = $("#skills-box");
  if (!box) return;
  const [d, G] = await Promise.all([api("allskills"), api("skillgroups")]), un = state.settings.unlocked, S = d.summary;
  const groupOf = Object.fromEntries(Object.entries(G).flatMap(([g, ids]) => ids.map(i => [i, g])));
  d.skills.forEach(r => (r.group = groupOf[r.id] || ""));
  state.skillGroups = Object.keys(G).sort();
  const filt = sessionStorage.getItem("lfg.skills.filter") || "all";
  const rows = d.skills.filter(r => filt === "all" || (filt.startsWith("group:") ? r.group === filt.slice(6) : filt === "collisions" ? r.collides_with.length : filt === "auto" ? r.auto : r.source === filt));
  box.innerHTML = `<div class="cols">${stat("Skills", n(S.total))}${stat("Claude may use on its own", n(S.auto), `about ${compact(S.approx_tokens)} tokens of descriptions in every session`)}${stat("Name clashes", n(S.collisions), "the short name goes to your own skill first")}</div>
    <div class="row mt"><label class="muted small" for="sk-filter">Show</label><select id="sk-filter">${[["all", "All"], ["auto", "Used on its own"], ["collisions", "Name clashes"], ...S.sources.map(x => [x, SRC_LABEL[x] || x]), ...state.skillGroups.map(g => ["group:" + g, "Group: " + g])].map(([v, l]) => `<option value="${esc(v)}" ${v === filt ? "selected" : ""}>${esc(l)}</option>`).join("")}</select><span class="save-msg" id="sk-msg"></span></div>
    <div class="box mt">${table(rows, [
      { k: "invoke", label: "Type", html: r => `<code class="nowrap">${esc(r.invoke)}</code>${r.shadowed ? ' <span class="tag" title="A skill of yours has the same short name">use full name</span>' : ""}` },
      { k: "source", label: "From", html: r => `${esc(SRC_LABEL[r.source] || r.source)}${r.plugin ? `<div class="sub">${esc(r.plugin)}${r.enabled === false ? " · off" : ""}</div>` : ""}` },
      { k: "auto", label: "Claude uses it on its own", sort: r => (r.auto ? 1 : 0), html: r => r.editable ? `<label class="row"><input type="checkbox" data-sk-auto="${esc(r.id)}" ${r.auto ? "checked" : ""} ${un ? "" : "disabled"}> ${r.auto ? "yes" : "only when typed"}</label>` : (r.auto ? "yes" : "only when typed") },
      { k: "description", label: "What it does", html: r => `<span title="${esc(r.description)}">${esc(r.description.slice(0, 140))}${r.description.length > 140 ? "…" : ""}</span>${r.collides_with.length ? `<div class="sub">same name as ${r.collides_with.map(x => `<code>${esc(x)}</code>`).join(", ")}</div>` : ""}` },
      { k: "group", label: "Group", html: r => `${r.group ? `<span class="tag">${esc(r.group)}</span> ` : ""}<button class="btn small" data-sk-group="${esc(r.id)}" ${un ? "" : "disabled"}>${r.group ? "Change" : "Group…"}</button>` },
      { k: "chars", label: "Size", num: true },
    ], { onRow: r => showSkillText(r.id), emptyTitle: "No skills here" })}</div>`;
  mountTables(box);
  $("#sk-filter", box).onchange = e => { sessionStorage.setItem("lfg.skills.filter", e.target.value); loadSkills(); };
  $$("[data-sk-group]", box).forEach(b => b.onclick = e => {
    e.stopPropagation();
    const id = b.dataset.skGroup, cur = (d.skills.find(x => x.id === id) || {}).group || "";
    const set = async g => { const r = await save("skill_group", { id, group: g }); saidMsg($("#skg-msg"), r, "Saved."); if (r.ok) setTimeout(() => { closeDrawer(); loadSkills(); }, 400); };
    openDrawer(`Group ${(d.skills.find(x => x.id === id) || {}).invoke || id}`, `<div class="readable"><p>Groups sort skills your own way, for example your <code>/review-pr</code> with <code>/lfg:review</code>. They live in LFG only and change nothing about the skills.</p>
      ${cur ? `<p>Now in <b>${esc(cur)}</b>. <button class="btn small" id="skg-out">Take it out</button></p>` : ""}
      ${state.skillGroups.filter(g => g !== cur).length ? `<div class="k">Your groups</div><div class="row wrap">${state.skillGroups.filter(g => g !== cur).map(g => `<button class="btn small" data-skg="${esc(g)}">${esc(g)}</button>`).join("")}</div>` : ""}
      <div class="k">New group</div><div class="row"><input type="text" id="skg-new" class="grow" placeholder="e.g. PR reviews" maxlength="60"><button class="btn primary" id="skg-make">Create and add</button></div><span class="save-msg" id="skg-msg"></span></div>`);
    $$("[data-skg]").forEach(x => x.onclick = () => set(x.dataset.skg));
    if ($("#skg-out")) $("#skg-out").onclick = () => set("");
    const make = () => { const v = $("#skg-new").value.trim(); if (v.length < 2) { $("#skg-msg").textContent = "Give the group a name of at least 2 characters."; return; } set(v); };
    $("#skg-make").onclick = make;
    $("#skg-new").onkeydown = e => { if (e.key === "Enter") make(); };
  });
  $$("[data-sk-auto]", box).forEach(c => {
    c.onclick = e => e.stopPropagation();
    c.onchange = async () => {
      const r = await save("skill_auto", { id: c.dataset.skAuto, auto: c.checked });
      saidMsg($("#sk-msg"), r, r.ok ? "Saved." : "");
      if (!r.ok) c.checked = !c.checked;
    };
  });
}
async function loadMyLibrary(pick) {
  const box = $("#mylib-box");
  if (!box) return;
  const d = await api("mylibrary"), un = state.settings.unlocked;
  const fileLink = (f, label) => `<a href="#" data-myfile="${esc(f.path)}" title="${esc(f.path)}">${esc(label)}${(f.used_by || []).length ? `<span class="tag" title="Mentioned by ${esc(f.used_by.join(", "))}">${f.used_by.length}</span>` : ""}</a>`;
  const skills = d.skills.map(s => `<div class="nav-grp">/${esc(s.name)}</div>${s.files.map(f => fileLink(f, f.rel)).join("")}`).join("");
  const shared = d.shared.map(g => `<div class="nav-grp">${esc(g.name)}</div>${g.files.map(f => fileLink(f, f.rel)).join("")}`).join("");
  box.innerHTML = `<p class="muted">Your own skills in <code>~/.claude/skills</code>, and the shared files they read: <code>~/.claude/skills/shared</code> and <code>~/.claude/references</code>. The number on a shared file is how many of your skills mention it. ${un ? "Saving keeps a copy of the old version in <code>~/.lfg/backups/personal/</code>." : "Unlock editing (run <code>lfg ui</code>) to change them."}</p>
    <div class="skill-edit"><nav>${shared ? `<div class="nav-grp"><b>Shared</b></div>${shared}` : ""}<div class="nav-grp"><b>Your skills</b></div>${skills}</nav>
    <div class="grow"><div id="myfile-editor">${empty("Pick a file to read or change it", "New Claude Code sessions use what you save.")}</div></div></div>`;
  $$("[data-myfile]", box).forEach(a => a.onclick = e => { e.preventDefault(); $$("[data-myfile]", box).forEach(x => x.classList.toggle("on", x === a)); showMyFile(a.dataset.myfile, d); });
  if (pick) { const a = $(`[data-myfile="${CSS.escape(pick)}"]`, box); if (a) a.click(); }
}
async function showMyFile(path, lib) {
  const ed = $("#myfile-editor"), un = state.settings.unlocked;
  const d = await api("myfile", { path });
  if (d.available === false) { ed.innerHTML = unavailable(d); return; }
  const f = [...lib.skills, ...lib.shared].flatMap(g => g.files).find(x => x.path === path) || {};
  const isMd = /\.md$/i.test(path);
  ed.innerHTML = `<div class="row"><span class="mono small grow">${esc(path.replace(/^\/Users\/[^/]+/, "~"))}</span>${un ? '<button class="btn small" id="myf-edit">Edit</button>' : ""}</div>
    ${(f.used_by || []).length ? `<p class="muted small">Mentioned by ${f.used_by.map(n => `<code>/${esc(n)}</code>`).join(", ")}: changing it changes how they work.</p>` : ""}
    <div id="myf-read" class="box pad ${isMd ? "md" : ""}">${isMd ? md(frontMatter(d.text).body) : `<pre>${esc(d.text)}</pre>`}</div>
    <div id="myf-write" hidden><textarea class="editor" id="myf-text" spellcheck="false">${esc(d.text)}</textarea>
      <div class="set-actions"><button class="btn primary" id="myf-save">Save</button><button class="btn" id="myf-cancel">Cancel</button><span class="save-msg" id="myf-msg"></span></div></div>`;
  if (!un) return;
  $("#myf-edit").onclick = () => { $("#myf-read").hidden = true; $("#myf-write").hidden = false; $("#myf-edit").hidden = true; };
  $("#myf-cancel").onclick = () => showMyFile(path, lib);
  $("#myf-save").onclick = async () => {
    const r = await save("my_file", { path, text: $("#myf-text").value });
    saidMsg($("#myf-msg"), r, r.ok ? (r.note || "Saved.") : "");
    if (r.ok) setTimeout(() => loadMyLibrary(path), 900);
  };
}
async function showSkillText(id) {
  const d = await api("skilltext", { id });
  if (d.available === false) return;
  const fm = frontMatter(d.text);
  openDrawer(d.invoke, `${fm.meta.description ? `<p class="muted">${txt(fm.meta.description)}</p>` : ""}${d.lfg_name ? '<p class="small">Change it under <b>Edit LFG skills</b>.</p>' : ""}<div class="md">${md(fm.body)}</div>`);
};

/* Help: how LFG works in three steps, every command grouped by what it's for (read from the plugin, so it's
   always current), and a few answers. */
const HELP_GROUPS = [["Build something", ["lfg", "plan", "build", "spike", "wizard"]], ["Fix a problem", ["fix", "why", "health"]],
  ["Understand the code", ["explain", "explain5", "impact", "map", "research"]], ["Review and ship", ["review-coach", "check", "secure", "pentest", "suggest-tests", "grill", "ship"]],
  ["Remember and hand off", ["note", "learn", "handoff", "inbox"]], ["Not sure", ["which"]]];
PAGES.help = async () => {
  const [d, R] = await Promise.all([api("guide"), api("releases")]);
  const news = (R.releases || []).map((r, n) => `<details class="hp-q"${n ? "" : " open"}><summary><b>${esc(r.version)}</b> · ${esc(r.title)}${r.version === R.version ? ' <span class="tag">installed</span>' : ""}</summary>
      <ul>${r.items.map(i => `<li><b>${esc(i.title)}.</b> ${newsText(i.text)}</li>`).join("")}</ul>
      <p><button class="btn small" data-news-replay="${esc(r.version)}">Walk me through it</button></p></details>`).join("");
  const first = t => { const x = String(t || "").replace(/\s+/g, " ").trim(), m = /^(.{20,220}?[.!?])(\s|$)/.exec(x); return m ? m[1] : x.length <= 200 ? x : x.slice(0, x.lastIndexOf(" ", 190)) + "…"; };
  const all = (d.skills || []).map(x => ({ cmd: x.name, key: x.name.replace(/^\/lfg:/, ""), what: first(x.description) }));
  const placed = new Set(), groups = HELP_GROUPS.map(([g, ks]) => [g, ks.map(k => all.find(x => x.key === k)).filter(Boolean)]);
  groups.forEach(([, xs]) => xs.forEach(x => placed.add(x.key)));
  const rest = all.filter(x => !placed.has(x.key)); if (rest.length) groups.push(["More", rest]);
  const step = (n, ico, title, body) => `<div class="box hp-step"><span class="hp-n">${n}</span>${icon(ico)}<b>${title}</b><p>${body}</p></div>`;
  const qa = (q, a) => `<details class="hp-q"><summary>${q}</summary><p>${a}</p></details>`;
  return `${head("Help", "LFG takes a change from idea to pull request inside Claude Code. You describe it, review what comes back, and ship.")}
    ${news ? section("What's new", `<div class="box pad" id="hp-news">${news}</div>`) : ""}
    ${section("Get started", `<div class="hp-steps">
      ${step(1, "studio", "Describe the change", `Open <a href="#studio">Studio</a> and write what you want, or type <code>/lfg:lfg</code> and a sentence in Claude Code.`)}
      ${step(2, "review", "Review the result", `LFG plans, builds, tests and reviews it, and stops to ask you at each checkpoint. Follow along in <a href="#runs">Runs</a>.`)}
      ${step(3, "runs", "Ship it", `<code>/lfg:ship</code> gets the pull request ready. LFG never commits, pushes or merges; you do.`)}</div>`)}
    ${section("What you can ask for", `<input type="search" id="hp-find" class="hp-find" placeholder="Search commands" autocomplete="off">
      ${groups.filter(([, xs]) => xs.length).map(([g, xs]) => `<div class="hp-grp"><h3>${esc(g)}</h3><div class="box"><ul class="list">${xs.map(x => `<li class="click hp-sk" tabindex="0" data-copy-cmd="${esc(x.cmd)}" data-find="${esc((x.cmd + " " + x.what).toLowerCase())}" title="Click to copy"><code>${esc(x.cmd)}</code><span class="grow">${esc(x.what)}</span></li>`).join("")}</ul></div></div>`).join("")}`, "click one to copy it")}
    ${section("Questions", `<div class="box pad">
      ${qa("Which command should I use?", "Type <code>/lfg:which</code> and describe your situation; it picks one for you. For a guided first run, use <code>/lfg:wizard</code>.")}
      ${qa("Where does my work go?", "Everything stays on this computer: LFG keeps its notes in <code>~/.lfg</code> and changes files only in your project. It never commits, pushes, merges or deploys.")}
      ${qa("How much does it cost?", `<a href="#usage">Usage</a> shows what Claude Code spent, by day, model and project, and what Headroom saved.`)}
      ${qa("Can I hide pages I don't use?", `Yes: <a href="#onboarding">choose which pages you see</a>.`)}
      ${qa("How do I get updates?", `The bottom of the sidebar shows your LFG version and tells you when a new one is out; <a href="#settings">Settings</a> can check now.`)}</div>`)}`;
};
function wireHelp(root) {
  const f = $("#hp-find", root);
  if (f) f.oninput = () => { const q = f.value.trim().toLowerCase(); $$(".hp-sk", root).forEach(li => { li.hidden = !!q && !q.split(/\s+/).every(w => li.dataset.find.includes(w)); }); $$(".hp-grp", root).forEach(g => { g.hidden = !$$(".hp-sk", g).some(li => !li.hidden); }); };
  $$("[data-copy-cmd]", root).forEach(li => li.onclick = async () => { await navigator.clipboard.writeText(li.dataset.copyCmd + " "); const c = $("code", li), t = c.textContent; c.textContent = "Copied"; setTimeout(() => { c.textContent = t; }, 1000); });
}

// ------------------------------------------------------------------ shell
// ------------------------------------------------------------------ PR reviews (lfg review)
/* Reviews of other people's PRs: the queue GitHub asks you to review, each saved review, and the buttons to run a
   review, decide each finding and post. Every button needs the edit key; posting is only ever a person's click. */
const prRef = r => `${r.repo}#${r.number}`;
const prHash = r => `#prs/${r.repo}/${r.number}`;
const PRIOR = { fixed: ["Fixed", "ok"], replied: ["Answered, still open", "warn"], withdrawn: ["Withdrawn", ""],
  "resolved-unchanged": ["Resolved but not fixed", "bad"], ignored: ["Not addressed", "bad"], open: ["Still open", "warn"] };
/* Earlier findings on a re-review, grouped by where each stands: the review's own call, moved on by what you have
   checked since ("Is it fixed?" says fixed or partly). Order is how much attention each needs; a state this code
   doesn't know gets a group of its own at the end. */
const PRIOR_GROUPS = [["open", "Still open", "warn", "Still open"], ["ignored", "Not addressed", "bad", "Not addressed"],
  ["resolved-unchanged", "Resolved but not fixed", "bad", "Resolved but not fixed"], ["replied", "Answered, still open", "warn", "Answered, still open"],
  ["partly", "Partly fixed", "warn", "Partly fixed"], ["fixed", "Fixed", "ok", "Fixed"], ["withdrawn", "Withdrawn", "", "Not applicable"]];
function priorGroupOf(x, f) {
  if (x.state === "fixed" || x.state === "withdrawn" || !f) return x.state;
  if ((f.fixed || {}).commit || (f.check || {}).state === "fixed") return "fixed";
  return (f.check || {}).state === "partly" ? "partly" : x.state;
}
/* [{key, label, tone, heading, items: [prior row]}] for the groups that have rows */
function priorGroups(prior, byId) {
  const by = {};
  (prior || []).forEach(x => (by[priorGroupOf(x, byId[x.id])] = by[priorGroupOf(x, byId[x.id])] || []).push(x));
  const known = PRIOR_GROUPS.map(g => g[0]);
  const rows = PRIOR_GROUPS.map(([key, label, tone, heading]) => ({ key, label, tone, heading, items: by[key] || [] }));
  Object.keys(by).filter(k => !known.includes(k)).forEach(k => rows.push({ key: k, label: k, tone: "", heading: k, items: by[k] }));
  return rows.filter(g => g.items.length);
}
const SINCE = { new: "in the new commits", missed: "missed last time" };
const ORIGIN = { exposed: "existing bug this PR now reaches", "pre-existing": "was already there" };
const ABOUT = { ticket: ["About the ticket", "The Linear ticket is wrong, out of date, contradicts itself or leaves something out, or the PR doesn't do part of what it asks"], description: ["About the PR description", "The PR's description says something the code doesn't do, leaves out something it does, or contradicts the ticket"] };
/* What the PR was meant to do, as this review read it: its ticket and description, and how much of the ask it does. */
const DELIVERS = { all: ["Does all of it", "c-green"], most: ["Does most of it", "c-yellow"], part: ["Does part of it", "c-red"], unclear: ["Can't tell", "c-gray"] };
function intentLine(p) {
  const it = p.intent;
  if (!it) return "";
  const [dl, cls] = DELIVERS[it.delivers] || DELIVERS.unclear;
  const tk = it.ticket ? `<b>${esc(it.ticket)}</b>${it.ticket_title ? ` (${esc(it.ticket_title)})` : ""}${it.read_ticket ? "" : ' <span class="tag warn" title="The review couldn\'t read this ticket from Linear">not read</span>'}` : '<span class="tag warn">no ticket found</span>';
  return `<div class="row wrap mt" style="gap:8px"><span class="k" style="margin:0">Against the ticket</span>${tk}<span class="chip ${cls}">${dl}</span>${it.read_description ? "" : '<span class="tag warn" title="The PR has no description, or it says nothing about what the PR does">no description</span>'}</div>${it.note ? `<p class="muted small" style="margin-top:4px">${txt(it.note)}</p>` : ""}`;
}
/* " together with owner/repo#n" (and the ticket) for a review that covers several PRs in one session */
const togetherWith = j => (j.with || []).length ? ` together with ${j.with.map(esc).join(", ")}${j.ticket ? ` for ${esc(ticketName(j.ticket))}` : ""}` : "";
function jobLine(j) {
  if (!j) return "";
  if (j.status === "running") return `<span class="st">${dot("on")}Reviewing${togetherWith(j)}… started ${ago(j.started)}</span>`;
  if (j.status === "failed") return `<span class="st" title="${esc(j.log || "")}">${dot("bad")}${esc(j.why || "The last review failed")}</span> <button class="btn small" data-pr-import='${esc(JSON.stringify([`${j.repo}#${j.number}`, "log"]))}' title="Look in that run's log for a review and save it">Save from log</button>`;
  return "";
}
function tallyLine(r) {
  const t = r.tally || {};
  if (r.posted) return `<span class="st">${dot("ok")}Posted: ${esc({ APPROVE: "approved", REQUEST_CHANGES: "changes requested", COMMENT: "comments" }[r.posted.event] || r.posted.event)}</span>`;
  if (t.pending) return `<span class="st">${dot("warn")}${plural(t.pending, "finding")} to decide</span>`;
  return `<span class="st">${dot("on")}Ready to post</span>`;
}
/* The notes a review was started with: shown on it, and one click puts them in the box for the next review. */
const NOTES_ON = ' <span class="notes-on" title="The review will also look into your notes">· with your notes</span>';
const usedNotes = (text, pr, label) => `<div class="pr-used-notes"><div class="row"><b class="small">${esc(label)}</b><span class="grow"></span><button class="btn small" data-pr-notes-again="${esc(pr)}" data-text="${esc(text)}" title="Put these notes in the box for the next review, to change or reuse them">Edit for the next review</button></div><p class="pre-wrap small">${txt(text)}</p></div>`;
async function prStart(pr, btn) {
  const fresh = btn.dataset.fresh === "1";
  btn.style.minWidth = btn.offsetWidth + "px";  // a shorter label must not pull the buttons beside it left
  btn.disabled = true; btn.textContent = "Starting…";
  const notes = ((state.reviewNotes || {})[pr] || "").trim();
  const d = await save("review_run", { pr, fresh, fresh_eyes: fresh && !!state.freshEyes, sources: methodSel(state.prMethodData), notes });
  if (!d.ok) { btn.disabled = false; btn.textContent = "Try again"; btn.title = d.why || ""; return; }
  if (d.started) { delete (state.reviewNotes || {})[pr]; delete (state.reviewNotesOpen || {})[pr]; }  // notes are for this one review
  btn.textContent = d.started ? "Started" : "Already running";
  setTimeout(softRoute, 1200);
}
/* Where a PR stands on GitHub, as a tag: Approved / Changes requested / Needs review / Merged / Closed. */
const GH_DECISION = { APPROVED: ["Approved", "ok"], CHANGES_REQUESTED: ["Changes requested", "bad"], REVIEW_REQUIRED: ["Needs review", "warn"] };
function ghTag(g) {
  if (!g || g.available === false) return "";
  if (g.state === "MERGED") return '<span class="tag ok">Merged</span>';
  if (g.state === "CLOSED") return '<span class="tag">Closed</span>';
  // GitHub's own state: reviews done here stay here until posted, and GitHub never counts your own PR's
  const [t, tn] = GH_DECISION[g.decision] || [(g.reviewers || []).length ? "Not approved yet" : "No reviews on GitHub", ""];
  const mine = (g.reviewers || []).find(r => r.who === g.me);
  const fails = (g.checks || {}).FAILURE || 0;
  return `<span class="tag ${tn}">${esc(t)}</span>${mine ? ` <span class="tag">you: ${esc(({ APPROVED: "approved", CHANGES_REQUESTED: "asked for changes", COMMENTED: "commented", DISMISSED: "dismissed" })[mine.state] || mine.state.toLowerCase())}</span>` : ""}${fails ? ` <span class="tag bad">${plural(fails, "check")} failing</span>` : ""}${g.draft ? ' <span class="tag">draft</span>' : ""}`;
}
/* "12 files +340 −58" and GitHub's five-box bar: green for added lines, red for removed, gray when it's small. */
function diffStat(g) {
  if (!g || g.available === false || !g.files) return "";
  const a = g.additions || 0, r = g.deletions || 0, t = a + r;
  const green = t ? Math.round(5 * a / Math.max(t, 5)) : 0, red = t ? Math.min(5 - green, Math.round(5 * r / Math.max(t, 5))) : 0;
  const boxes = [...Array(5)].map((_, i) => `<i class="${i < green ? "add" : i < green + red ? "del" : ""}"></i>`).join("");
  return `<span class="diffstat" title="${esc(`${a} added and ${r} removed lines in ${g.files} files`)}">${plural(g.files, "file")} <b class="add">+${a}</b> <b class="del">−${r}</b><span class="bar">${boxes}</span></span>`;
}
/* A PR page opens with what is known; GitHub and the session search are asked behind it, and the page fills in
   (a soft refresh, which keeps what you typed and where you scrolled) once they answer. */
const prFilling = new Set();
function prFillIn(pr, arg, pending) {
  if (!(pending || []).length || prFilling.has(pr)) return;
  prFilling.add(pr);
  api("prreview", { pr }).catch(() => null).then(() => {
    prFilling.delete(pr);
    if (location.hash === `#prs/${arg}`) softRoute();
  });
}
function ghPanel(g, ours) {
  if (g && g.pending) return '<div class="pr-status small muted"><span class="loading-inline">Asking GitHub where this PR stands…</span></div>';
  if (!g || g.available === false) return g && g.why ? `<p class="muted small">Couldn't ask GitHub: ${esc(g.why)}</p>` : "";
  const word = { APPROVED: "approved", CHANGES_REQUESTED: "asked for changes", COMMENTED: "commented", DISMISSED: "dismissed" };
  const checks = Object.entries(g.checks || {}).map(([k, v]) => `${v} ${k.toLowerCase()}`).join(", ");
  return `<div class="pr-status small"><div class="tags">${ghTag(g)}${diffStat(g)}</div><div class="muted">${(g.reviewers || []).map(r => `${esc(r.who)} ${esc(word[r.state] || r.state.toLowerCase())} ${ago(r.at)}`).join(" · ") || (ours ? `nobody has reviewed on GitHub; your ${plural(ours, "LFG review")} ${ours > 1 ? "stay" : "stays"} here until you post one` : "nobody has reviewed on GitHub yet")}${(g.waiting_on || []).length ? ` · waiting on ${esc(g.waiting_on.join(", "))}` : ""}${checks ? ` · checks: ${esc(checks)}` : ""}</div></div>`;
}
PAGES.prs = async arg => {
  if (arg && arg.startsWith("ticket/")) return prTicket(decodeURIComponent(arg.slice(7)));
  if (arg === "scores") return prScores();
  if (arg) return prDetail(arg);
  const [d, unlocked] = await Promise.all([api("prreviews", scopeArgs("prs")), isUnlocked()]);
  const lock = unlocked ? "" : `<div class="callout warn">Buttons are locked. Run <code>${esc(unlockCmd())}</code> in your terminal to review and post from here.</div>`;
  state.prPick = state.prPick || new Set();
  /* merged and closed PRs are done: hidden unless you ask, remembered across visits */
  const showDone = localStorage.getItem("lfg.prs.done") === "1";
  const isDone = x => x.open === false || ["MERGED", "CLOSED"].includes((x.gh || {}).state);
  const done = (d.reviews || []).filter(isDone).length;
  const shownReviews = showDone ? d.reviews : (d.reviews || []).filter(x => !isDone(x));
  const doneToggle = done ? `<label class="row small done-toggle"><input type="checkbox" data-prs-done ${showDone ? "checked" : ""}> Show merged and closed PRs (${done})</label>` : "";
  state.prReviewed = new Set([...(d.queue || []), ...(d.mine || []), ...(d.reviews || []), ...(d.ticket_more || [])].filter(x => x.passes).map(prRef));
  state.prTicket = Object.fromEntries([...(d.queue || []), ...(d.mine || []), ...(d.reviews || [])].filter(x => x.ticket).map(x => [prRef(x), x.ticket]));
  state.ticketTitles = d.ticket_titles || {};
  const qcols = [
    { k: "pick", label: "", html: x => `<input type="checkbox" data-pr-pick="${esc(prRef(x))}" ${state.prPick.has(prRef(x)) ? "checked" : ""} ${unlocked ? "" : "disabled"} title="Pick several PRs, for example a backend and its frontend, and review them together" aria-label="Pick ${esc(prRef(x))}">` },
    { k: "title", label: "Pull request", html: x => `${esc(x.title)}<div class="sub mono">${esc(prRef(x))} · by ${esc(x.author)}</div><div class="sub">${ghTag(x.gh)}${linkTags(x.linked)}${diffStat(x.gh)}</div>${x.job ? `<div class="sub">${jobLine(x.job)}</div>` : ""}` },
    { k: "review", label: "Your review", html: x => x.passes ? `<div class="row" style="gap:6px">${verdictPill(x)}${x.score != null ? `<span class="score-mini ${scoreTone(x.score)}" style="margin:0">${esc(x.score)}</span>` : ""}${trend(x.scores, true)}</div><div class="sub">${plural(x.passes, "review")}${x.reviewed ? ` · last ${ago(x.reviewed)}` : ""}</div><div class="sub">${tallyLine(x)}</div>` : '<span class="muted small">Not reviewed yet</span>', sort: x => (x.passes ? x.score ?? 0 : -1) },
    { k: "updated", label: "Updated", html: x => `<span class="nowrap">${ago(x.updated)}</span>` },
    { k: "act", label: "", html: x => (x.job && x.job.status === "running") ? "" : `<button class="btn small${x.passes ? "" : " primary"}" data-pr-start="${esc(prRef(x))}" ${unlocked ? "" : "disabled"}>${x.passes ? "Re-review" : "Review"}</button> <button class="btn small" data-pr-sessions="${esc(prRef(x))}" ${unlocked ? "" : "disabled"} title="Bring in a review you did in a Claude Code session">Import</button>${x.passes ? ` <a class="small" href="${esc(prHash(x))}">Open</a>` : ""}` },
  ];
  const qopts = { onRow: x => (location.hash = prHash(x)) };
  const rcols = [
    qcols[0],
    { k: "title", label: "Review", html: x => `${esc(x.title || prRef(x))}${x.other_repo ? ' <span class="tag" title="In another repo than the one picked top left; reviewed with or linked to one here">other repo</span>' : ""}<div class="sub mono">${esc(prRef(x))} · by ${esc(x.author || "")}${x.ticket ? ` · ${esc(ticketName(x.ticket))}` : ""}</div><div class="sub">${x.gh ? ghTag(x.gh) : ""}${linkTags(x.linked)}</div>` },
    { k: "state", label: "Where it is", html: x => `${tallyLine(x)}${x.job ? `<div class="sub">${jobLine(x.job)}</div>` : ""}`, sort: x => (x.posted ? 2 : (x.tally || {}).pending ? 0 : 1) },
    { k: "score", label: "Can it merge", html: x => `<div class="merge-cell">${verdictPill(x)}${x.score != null ? `<span class="score-mini ${scoreTone(x.score)}">${esc(x.score)}</span>` : ""}${trend(x.scores, true)}</div>`, sort: x => x.score ?? -1 },
    { k: "passes", label: "Reviews", num: true },
    { k: "updated", label: "Updated", html: x => `<span class="nowrap">${ago(x.updated)}</span>` },
  ];
  return `${head("PR reviews", `Pull requests waiting on your review, your own open ones, and the reviews you've run. Run one, decide what to keep, then post it to GitHub. Reviews run on your own Claude Code login. ${scopeLine("prs")}`)}
    ${prTabs("list")}
    ${d.no_remote && !allRepos("prs") ? `<p class="muted small">${esc(repoName())} has no GitHub remote, so this shows PRs from every repo.</p>` : ""}
    ${lock}
    <div class="row pr-actions"><span class="grow"></span>${methodPick(d, unlocked)}${modelPick(d, unlocked)}</div>
    <div class="callout" id="pr-pickbar" hidden></div>
    ${ticketSection(d, unlocked)}
    ${section("Waiting on you", d.queue_why ? unavailable({ why: d.queue_why }, "Couldn't ask GitHub") : `<div class="box">${table(d.queue, qcols, { ...qopts, emptyTitle: "Nothing waiting", emptyBody: "No open PRs ask for your review." })}</div>`, "open PRs where GitHub lists you as a reviewer")}
    ${section("Your open PRs", d.mine_why ? unavailable({ why: d.mine_why }, "Couldn't ask GitHub") : `<div class="box">${table(d.mine, qcols, { ...qopts, emptyTitle: "No open PRs", emptyBody: "You have no open pull requests here." })}</div>`, "review your own work before others do; on your own PR you can only comment. Open one to link it to a session or a session group")}
    ${section("Your reviews", `${doneToggle}<div class="box">${table(shownReviews, rcols, { onRow: x => (location.hash = prHash(x)), sort: "updated", emptyTitle: done && !showDone ? "No open PRs reviewed" : "No reviews yet", emptyBody: done && !showDone ? "Every PR you reviewed here is merged or closed. Tick the box above to see them." : "Press Review above, or run <code>/lfg:review &lt;PR&gt;</code> in Claude Code." })}</div>`)}
    ${passedSection(d, unlocked)}`;
};
/* A model's name as people say it: claude-opus-5-5 is Opus 5.5. */
function modelName(id) {
  const m = /^claude-([a-z]+)-(\d+)(?:-(\d{1,2}))?(?:-\d{8})?(\[1m\])?$/.exec(id || "");
  return m ? `${m[1][0].toUpperCase()}${m[1].slice(1)} ${m[2]}${m[3] ? "." + m[3] : ""}${m[4] ? " (1M)" : ""}` : id || "";
}
/* What a session or review used, one row of tags per kind: the model, skills, subagents, MCP servers and claude.ai
   connectors, the plugins those came from, lfg commands and Claude Code's own tools. */
/* A small (i) that explains a term on hover or keyboard focus, for words a newcomer won't know. */
const info = text => `<span class="info" tabindex="0" role="note" aria-label="${esc(text)}" data-tip="${esc(text)}">i</span>`;
const USED_INFO = {
  Method: "The checklist this review followed: what to look for, how serious each finding is, and how comments are worded. LFG's built-in method or one of your own skills.",
  Model: "The Claude model the review ran on.",
  Skills: "Claude Code skills the session used, and how often.",
  Agents: "Subagents the session started for parts of the work.",
  MCP: "MCP servers and claude.ai connectors it called, such as Linear or dev-graph.",
  Plugins: "The Claude Code plugins those skills and servers came from.",
  LFG: "lfg commands it ran, for example to read earlier reviews or other reviewers' comments.",
  Tools: "Claude Code's own tools and how often it called each: Read opens files, Bash runs commands, Grep searches.",
};
const RUNNER_INFO = "Runs every review started from the dashboard, whatever the method: reads the PR and the earlier reviews, follows up earlier findings, then saves the findings, summary and score. The method decides what to look for and how comments read.";
function usedTags(u, method) {
  if (!u) return "";
  const times = (x, w) => (x.count ? ` · ${plural(x.count, w)}` : "");
  const chip = (cls, label, title, count) => `<span class="chip ${cls}" title="${esc(title)}">${esc(label)}${count > 1 ? `<span class="n">${n(count)}</span>` : ""}</span>`;
  const where = x => (x.kind === "connector" ? "claude.ai connector" : x.kind === "plugin" ? `MCP server from the ${x.plugin} plugin` : "MCP server");
  const rows = [
    ["Model", (u.models || []).map(m => chip("c-purple", modelName(m), m))],
    ["Method", method ? [`<span class="chip c-blue">${esc(method)}</span>`, ...(method !== "LFG's built-in method" ? (u.method_files || []).map(f => chip("c-gray mono", f, "A file from your skill that this review read")) : [])] : []],
    ["Skills", (u.skills || []).map(x => x.runner ? `<span class="chip c-blue">${esc(x.name)}<span class="n">runs every review</span></span>${info(RUNNER_INFO)}` : chip("c-blue", x.name, `Skill${times(x, "time")}`, x.count))],
    ["Agents", (u.agents || []).map(x => chip("c-pink", x.name, `Subagent${times(x, "run")}`, x.count))],
    ["MCP", (u.mcp || []).map(x => chip(x.kind === "connector" ? "c-orange connector" : "c-orange", x.name, `${where(x)}${times(x, "call")}`, x.count))],
    ["Plugins", (u.plugins || []).map(x => chip("c-green", x, "Plugin"))],
    ["LFG", (u.lfg || []).map(x => chip("c-gray mono", "lfg " + x.name, `Command${times(x, "run")}`, x.count))],
    ["Tools", (u.tools || []).map(x => chip("c-gray", x.name, `Claude Code tool${times(x, "call")}`, x.count))],
  ].filter(r => r[1].length);
  return rows.length ? `<div class="used">${rows.map(([k, cs]) => `<div class="used-k">${k}${USED_INFO[k] ? info(USED_INFO[k]) : ""}</div><div class="used-v">${cs.join("")}</div>`).join("")}</div>` : "";
}
/* Which model reviews run on, next to the buttons that start them. One setting for every review, chat and fix. */
/* Which methods the next review here follows, and your default: one picker. Tick one or several (several are read
   together, LFG's own first so yours win where they disagree); the ticks hold for reviews started from this page while
   it is open. Save as my default keeps them for every review. Combos are ticked sets saved under a name: one click
   picks one, the star makes one your default. Keys: "builtin", ~/.claude/skills/<name>, plugin:<plugin>/<skill>, or
   a file. */
const methodSel = d => state.reviewSel || (d && d.method_saved) || ["builtin"];
const methodName = (d, k) => (((d && d.methods) || []).find(m => m.key === k) || {}).label || k.split("/").pop();
const methodLabel = (d, keys) => [...keys].sort((a, b) => (a !== "builtin") - (b !== "builtin")).map(k => methodName(d, k)).join(" + ");
const sameSet = (a, b) => a.length === b.length && a.every(x => b.includes(x));
function methodPick(d, unlocked) {
  if (!d.methods) return "";
  state.prMethodData = d;
  const sel = methodSel(d), saved = d.method_saved || ["builtin"], all = state.reviewMethodsAll, same = sameSet(sel, saved);
  const extra = (state.reviewExtra || []).filter(k => !d.methods.some(m => m.key === k)).map(k => ({ key: k, label: k.split("/").pop(), about: k, fits: true, file: true }));
  const list = [...d.methods, ...extra], shown = list.filter(m => all || m.fits || sel.includes(m.key)), hidden = list.length - shown.length;
  const row = m => `<label class="mp-o" title="${esc(m.about || "")}"><input type="checkbox" data-mp-key="${esc(m.key)}" ${sel.includes(m.key) ? "checked" : ""} ${unlocked ? "" : "disabled"}><span class="grow"><b>${esc(m.label)}</b>${m.plugin ? ` <span class="tag" title="From the ${esc(m.plugin)} plugin you installed">${esc(m.plugin)}</span>` : ""}${m.saved ? ' <span class="muted small">default</span>' : ""}${m.file ? `<div class="muted small mono">${esc(m.key)}</div>` : ""}</span></label>`;
  const combos = d.combos || [], dis = unlocked ? "" : "disabled";
  const combo = c => { const on = sameSet(sel, c.methods), dflt = sameSet(c.methods, saved);
    return `<span class="mp-combo${on ? " on" : ""}"><button class="btn small${on ? " primary" : ""}" data-mp-combo="${esc(c.name)}" title="${esc(methodLabel(d, c.methods))}">${esc(c.name)}</button>${unlocked ? `<button class="mp-cx${dflt ? " on" : ""}" data-mp-star="${esc(c.name)}" title="${dflt ? "Your default" : "Make it my default"}" aria-label="${dflt ? "Your default" : "Make it my default"}" ${dflt ? "disabled" : ""}>★</button><button class="mp-cx" data-mp-ren="${esc(c.name)}" title="Rename, or save the ticked methods into it" aria-label="Rename ${esc(c.name)}">✎</button><button class="mp-cx" data-mp-del="${esc(c.name)}" title="Delete this combo" aria-label="Delete ${esc(c.name)}">×</button>` : ""}</span>`; };
  const combosBox = combos.length || unlocked ? `<div class="mp-combos"><div class="k" style="margin:0">Combos</div>${combos.map(combo).join("")}${combos.length ? "" : '<span class="muted small">None yet: tick some methods, then Save as combo.</span>'}</div>` : "";
  return `<details class="method-pick" data-method-pick><summary class="btn small">Method: <b data-mp-label>${esc(methodLabel(d, sel))}</b> <span class="tag warn" data-mp-tag ${same ? "hidden" : ""}>this page only</span></summary>
    <div class="mp-pop"><div class="muted small">What the next review follows: what to look for, how serious each finding is, how comments read. Tick several to use them together; LFG's own is read first, so yours win where they disagree.</div>
      ${combosBox}
      <div class="mp-list">${shown.map(row).join("")}${hidden ? `<a href="#" class="small" data-mp-all>Show every skill (${hidden} more)</a>` : ""}</div>
      ${unlocked ? `<div class="row mt"><input type="text" class="grow mono small" data-mp-file placeholder="Or add a file or folder, e.g. ~/notes/review.md"><button class="btn small" data-mp-add>Add</button></div>
      <div class="row mt"><span class="muted small grow" data-mp-msg>${same ? "This is your default." : "Only for reviews started from this page."}</span><button class="btn small" data-mp-combo-new ${dis}>Save as combo</button><button class="btn small primary" data-mp-save ${same ? "disabled" : ""}>Save as my default</button></div>` : ""}</div></details>`;
}
function wireMethodPick(root) {
  const box = $("[data-method-pick]", root);
  if (!box) return;
  const d = state.prMethodData;
  const paint = () => {
    const sel = methodSel(d), same = sameSet(sel, d.method_saved || ["builtin"]);
    $("[data-mp-label]", box).textContent = methodLabel(d, sel);
    $("[data-mp-tag]", box).hidden = same;
    const sv = $("[data-mp-save]", box); if (sv) sv.disabled = same;
    const msg = $("[data-mp-msg]", box); if (msg) msg.textContent = same ? "This is your default." : "Only for reviews started from this page.";
  };
  $$("[data-mp-key]", box).forEach(c => c.onchange = () => {
    const keys = $$("[data-mp-key]:checked", box).map(x => x.dataset.mpKey);
    if (!keys.length) { c.checked = true; return; }  // a review needs at least one method
    state.reviewSel = keys; paint();
  });
  const allA = $("[data-mp-all]", box);
  if (allA) allA.onclick = e => { e.preventDefault(); state.reviewMethodsAll = true; state.mpOpen = true; softRoute(); };
  const add = $("[data-mp-add]", box), inp = $("[data-mp-file]", box);
  if (add) add.onclick = () => {
    const v = inp.value.trim(); if (!v) return;
    state.reviewExtra = [...new Set([...(state.reviewExtra || []), v])];
    state.reviewSel = [...new Set([...methodSel(d), v])]; state.mpOpen = true; softRoute();
  };
  if (inp) inp.onkeydown = e => { if (e.key === "Enter") add.onclick(); };
  const sv = $("[data-mp-save]", box);
  if (sv) sv.onclick = async () => {
    const r = await save("review_sources", { sources: methodSel(d) });
    if (!r.ok) return saidMsg($("[data-mp-msg]", box), r, "");
    state.reviewSel = null; state.reviewExtra = []; state.mpOpen = true;
    prefToast(`Every review now follows ${methodLabel({ methods: r.methods }, r.saved)}.`);
    softRoute();
  };
  const combos = d.combos || [], byName = n => combos.find(c => c.name === n);
  const after = (r, text) => { if (!r.ok) return saidMsg($("[data-mp-msg]", box), r, ""); state.mpOpen = true; if (text) prefToast(text); softRoute(); };
  $$("[data-mp-combo]", box).forEach(b => b.onclick = e => { e.preventDefault(); const c = byName(b.dataset.mpCombo); if (!c) return; state.reviewSel = [...c.methods]; state.reviewExtra = c.methods.filter(k => !d.methods.some(m => m.key === k)); state.mpOpen = true; softRoute(); });
  const nb = $("[data-mp-combo-new]", box);
  if (nb) nb.onclick = async () => {
    const name = (prompt(`Name this combo (${methodLabel(d, methodSel(d))}):`) || "").trim();
    if (!name) return;
    if (byName(name) && !confirm(`Replace the combo "${name}" with what's ticked now?`)) return;
    after(await save("review_combo_save", { name, sources: methodSel(d) }), `Saved "${name}".`);
  };
  $$("[data-mp-ren]", box).forEach(b => b.onclick = async e => {
    e.preventDefault();
    const old = b.dataset.mpRen, c = byName(old);
    const name = (prompt(`New name for "${old}". It also takes what's ticked now (${methodLabel(d, methodSel(d))}); clear the box to cancel.`, old) || "").trim();
    if (!name || !c) return;
    after(await save("review_combo_save", { name, old, sources: methodSel(d) }), `Saved "${name}".`);
  });
  $$("[data-mp-del]", box).forEach(b => b.onclick = async e => {
    e.preventDefault();
    if (!confirm(`Delete the combo "${b.dataset.mpDel}"? Your default and the ticks stay as they are.`)) return;
    after(await save("review_combo_delete", { name: b.dataset.mpDel }), "Deleted.");
  });
  $$("[data-mp-star]", box).forEach(b => b.onclick = async e => {
    e.preventDefault();
    const c = byName(b.dataset.mpStar); if (!c) return;
    const r = await save("review_sources", { sources: c.methods });
    if (r.ok) { state.reviewSel = null; state.reviewExtra = []; }
    after(r, `Every review now follows "${c.name}" (${methodLabel(d, c.methods)}).`);
  });
  if (state.mpOpen) { box.open = true; state.mpOpen = false; }
  if (state.mpOutside) document.removeEventListener("click", state.mpOutside, true);
  state.mpOutside = e => { const b = $("[data-method-pick]"); if (b && b.open && !b.contains(e.target)) b.open = false; };
  document.addEventListener("click", state.mpOutside, true);
}
function modelPick(d, unlocked) {
  if (!d.models) return "";
  return `<label class="model-pick" >Model${info("The model every review, re-review, chat and fix runs on, from now on.")}<select data-review-model ${unlocked ? "" : "disabled"}>${d.models.map(m => `<option value="${esc(m.id)}" ${m.id === (d.model || "") ? "selected" : ""}>${esc(m.label)}</option>`).join("")}</select></label>`;
}
const prTabs = on => `<div class="tabs page-tabs"><a class="tab ${on === "list" ? "on" : ""}" href="#prs">Pull requests</a><a class="tab ${on === "scores" ? "on" : ""}" href="#prs/scores">Scores</a></div>`;
/* How PRs score, per person and per repo. The first review scores the code as it was handed in; later reviews
   usually score higher after fixes, so the latest score and how many reviews it took to approve are shown apart. */
async function prScores() {
  const d = await api("prscores", scopeArgs("prs"));
  crumbs("prs", "Scores");
  const o = d.overall || {}, k = d.kinds || {};
  const mini = v => (v == null ? '<span class="muted">–</span>' : `<span class="score-mini ${scoreTone(v)}" style="margin:0">${esc(Math.round(v))}</span>`);
  const gain = v => (v == null ? "" : `<span class="trend ${v > 0 ? "up" : v < 0 ? "down" : "same"}">${v > 0 ? "↑" : v < 0 ? "↓" : "→"}${v ? Math.abs(v) : ""}</span>`);
  const tile = (label, body, sub) => `<div class="stat-tile"><div class="k">${label}</div><div class="v">${body}</div>${sub ? `<div class="muted small">${sub}</div>` : ""}</div>`;
  const ring = v => (v == null ? '<span class="muted">–</span>' : `<div class="score-ring ${scoreTone(v)}" style="--pct:${v}"><span>${esc(Math.round(v))}</span><small>avg</small></div>`);
  const tiles = `<div class="stat-tiles">
    ${tile("First review", ring(o.first), "the code as it was handed in")}
    ${tile("Latest review", ring(o.latest), "after fixes")}
    ${tile("Reviews to approval", `<span class="big-n">${o.to_approval ?? "–"}</span>`, "on PRs you approved")}
    ${tile("Full reviews", `<span class="big-n">${k.full ? Math.round(k.full.avg) : "–"}</span>`, k.full ? `${plural(k.full.reviews, "review")}, average score` : "")}
    ${tile("Re-reviews", `<span class="big-n">${k["re-review"] ? Math.round(k["re-review"].avg) : "–"}</span>`, k["re-review"] ? `${plural(k["re-review"].reviews, "review")}, average score` : "")}</div>`;
  const gcols = who => [
    { k: "name", label: who, html: x => `<span class="${who === "Repo" ? "mono" : ""}">${esc(x.name)}</span>` },
    { k: "prs", label: "PRs", num: true },
    { k: "first", label: "First review", html: x => mini(x.first), sort: x => x.first ?? -1 },
    { k: "latest", label: "Latest", html: x => `<div class="merge-cell">${mini(x.latest)}${gain(x.gain)}</div>`, sort: x => x.latest ?? -1 },
    { k: "to_approval", label: "Reviews to approval", html: x => (x.to_approval == null ? '<span class="muted small">none approved</span>' : `${esc(x.to_approval)}<span class="muted small"> · ${x.first_time} of ${x.approved} on the first</span>`), sort: x => x.to_approval ?? 99 },
  ];
  const pcols = [
    { k: "title", label: "Pull request", html: x => `${esc(x.title)}<div class="sub mono">${esc(x.repo)}#${esc(x.number)} · ${esc(x.author)}</div>` },
    { k: "first", label: "First", html: x => mini(x.first), sort: x => x.first },
    { k: "latest", label: "Latest", html: x => `<div class="merge-cell">${verdictPill(x)}${mini(x.latest)}${trend(x.scores, true)}</div>`, sort: x => x.latest },
    { k: "reviews", label: "Reviews", num: true },
    { k: "approved_after", label: "Approved", html: x => (x.approved_after ? `after ${plural(x.approved_after, "review")}` : '<span class="muted small">not by you</span>'), sort: x => x.approved_after ?? 99 },
    { k: "updated", label: "Updated", html: x => `<span class="nowrap">${ago(x.updated)}</span>` },
  ];
  if (d.available === false) return `${head("PR reviews", "")}${prTabs("scores")}${unavailable(d)}`;
  return `${head("PR reviews", `How pull requests score. The first review scores the code as it was handed in; later reviews usually go up after fixes, so they're shown apart. ${scopeLine("prs")}`)}
    ${prTabs("scores")}
    ${(d.prs || []).length ? `${tiles}
    ${section("Where each person starts and ends", startEnd(d.authors), "average score on the first review, and on the latest one")}
    ${section("First reviews over time", overTime(d.prs, d.authors), "each dot is a PR's first review; hover for which")}
    ${section("By person", `<div class="box">${table(d.authors, gcols("Person"), { sort: "prs", filter: false })}</div>`, "average first-review score, then where they ended up")}
    ${section("By repo", `<div class="box">${table(d.repos, gcols("Repo"), { sort: "prs", filter: false })}</div>`)}
    ${section("Every PR", `<div class="box">${table(d.prs, pcols, { sort: "updated", onRow: x => (location.hash = `#prs/${x.repo}/${x.number}`) })}</div>`)}` : empty("No scores yet", allRepos("prs") ? "Reviews give each PR a score out of 100. Run one from Pull requests." : `No reviews in ${esc(repoName())} yet. Use “Show all repos” above to see every repo.`)}`;
}
/* Each person's average first-review score and latest score, as a dot each joined by a line: how far fixes took
   them. Orange is the first review, blue the latest; both are labeled in the legend and the tooltip. */
function startEnd(rows) {
  rows = (rows || []).filter(r => r.first != null);
  if (!rows.length) return "";
  const W = 760, L = 150, R = 24, rowH = 34, H = rows.length * rowH + 30;
  const lo = Math.max(0, Math.floor((Math.min(...rows.flatMap(r => [r.first, r.latest])) - 5) / 10) * 10), hi = 100;
  const x = v => L + ((v - lo) / (hi - lo)) * (W - L - R);
  const grid = [];
  for (let v = lo; v <= hi; v += 10) grid.push(`<line class="axis" x1="${x(v)}" x2="${x(v)}" y1="4" y2="${H - 22}"/><text x="${x(v)}" y="${H - 6}" text-anchor="middle">${v}</text>`);
  const marks = rows.map((r, i) => {
    const y = 18 + i * rowH, tip = `${r.name} · ${plural(r.prs, "PR")}|First review: ${Math.round(r.first)}|Latest: ${Math.round(r.latest)}${r.to_approval != null ? `|Reviews to approval: ${r.to_approval}` : ""}`;
    return `<g class="se-row" data-tip="${esc(tip)}"><rect x="0" y="${y - rowH / 2}" width="${W}" height="${rowH}" fill="transparent"/>
      <text class="se-name" x="${L - 12}" y="${y + 4}" text-anchor="end">${esc(r.name.length > 20 ? r.name.slice(0, 19) + "…" : r.name)}</text>
      <line x1="${x(r.first)}" x2="${x(r.latest)}" y1="${y}" y2="${y}" class="se-link"/>
      <circle cx="${x(r.latest)}" cy="${y}" r="5" class="se-latest"/><circle cx="${x(r.first)}" cy="${y}" r="8" class="se-first"/></g>`;
  }).join("");
  return `<div class="box pad chart-box"><div class="legend"><span><i class="se-key first"></i>First review</span><span><i class="se-key latest"></i>Latest review</span></div><svg class="score-chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Average first and latest review score per person">${grid.join("")}${marks}</svg><div class="chart-tip" hidden></div></div>`;
}
/* Every PR's first-review score by date, one dot each, with a person filter. The dashed line is the average of
   what's shown. */
function overTime(prs, authors) {
  const pick = state.scoreWho || "";
  const xs = (prs || []).filter(p => p.first_at && (!pick || p.author === pick)).sort((a, b) => a.first_at.localeCompare(b.first_at));
  const filter = `<div class="row filters"><label class="model-pick">Person<select data-score-who><option value="">Everyone</option>${(authors || []).map(a => `<option ${a.name === pick ? "selected" : ""}>${esc(a.name)}</option>`).join("")}</select></label></div>`;
  if (xs.length < 2) return `${filter}<div class="box pad muted small">Not enough reviews to draw yet: it needs at least two.</div>`;
  const W = 760, L = 36, R = 16, H = 220, B = 24;
  const t = s => new Date(s).getTime(), t0 = t(xs[0].first_at), t1 = Math.max(t(xs[xs.length - 1].first_at), t0 + 864e5);
  const lo = Math.max(0, Math.floor((Math.min(...xs.map(p => p.first)) - 5) / 10) * 10);
  const x = s => L + ((t(s) - t0) / (t1 - t0)) * (W - L - R), y = v => 8 + (1 - (v - lo) / (100 - lo)) * (H - B - 8);
  const grid = [];
  for (let v = lo; v <= 100; v += 10) grid.push(`<line class="axis" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${v}</text>`);
  const day = s => new Date(s).toLocaleDateString([], { month: "short", day: "numeric" });
  const ticks = [xs[0], xs[Math.floor(xs.length / 2)], xs[xs.length - 1]].map(p => `<text x="${x(p.first_at)}" y="${H - 6}" text-anchor="middle">${esc(day(p.first_at))}</text>`).join("");
  const avg = xs.reduce((a, p) => a + p.first, 0) / xs.length;
  const dots = xs.map(p => `<circle class="ot-dot" cx="${x(p.first_at)}" cy="${y(p.first)}" r="5" data-tip="${esc(`${p.title}|${p.repo}#${p.number} · ${p.author}|First review: ${p.first} · latest: ${p.latest}|${day(p.first_at)}`)}" data-href="#prs/${esc(p.repo)}/${esc(p.number)}"/>`).join("");
  return `${filter}<div class="box pad chart-box"><svg class="score-chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="First-review score of each PR over time">${grid.join("")}${ticks}<line class="ot-avg" x1="${L}" x2="${W - R}" y1="${y(avg)}" y2="${y(avg)}"/><text class="ot-avg-l" x="${L + 6}" y="${y(avg) + 14}">average ${Math.round(avg)}</text>${dots}</svg><div class="chart-tip" hidden></div></div>`;
}
/* Hover any [data-tip] mark in a chart: a tooltip beside it, one line per "|". */
function wireScoreCharts(root) {
  $$(".chart-box", root).forEach(box => {
    const tip = $(".chart-tip", box);
    const show = (el, ev) => {
      const [t, ...rest] = el.dataset.tip.split("|");
      tip.innerHTML = `<div class="ic-t">${esc(t)}</div>${rest.map(r => `<div>${esc(r)}</div>`).join("")}`;
      const b = box.getBoundingClientRect();
      tip.hidden = false;
      tip.style.left = Math.min(ev.clientX - b.left + 14, b.width - tip.offsetWidth - 8) + "px";
      tip.style.top = ev.clientY - b.top + 14 + "px";
    };
    $$("[data-tip]", box).forEach(el => { el.onmousemove = ev => show(el, ev); el.onmouseleave = () => (tip.hidden = true); });
  });
  $$("[data-score-who]", root).forEach(s => s.onchange = () => { state.scoreWho = s.value; softRoute(); });
}
/* Linked PRs as tags. They can be in another repo than the one picked top left, so each says its repo, and opening
   one works whichever repo is picked. */
const linkTags = prs => (prs || []).map(x => ` <a class="tag mono" href="#prs/${esc(x.replace("#", "/"))}" title="Linked: reviewed together, or linked by you">with ${esc(x)}</a>`).join("");
/* Which files a review reads to decide what to look for, how to score and how to word comments. */
/* Review sources next to each other from one skill's folder (its SKILL.md and the files it points at) are one entry:
   the skill, with its parts under it, moved and removed together. */
/* Findings you told reviews not to flag again, in this repo or in every repo. Every review reads these first. */
const PASS_SCOPE = { repo: ["Every PR in this repo", "A review of any PR in that repo leaves it alone.", "for every PR in this repo"], all: ["Every repo", "A review of any PR in any repo leaves it alone.", "for every repo"] };
const passedTag = x => x.scope === "all" ? `<span class="tag warn" title="${PASS_SCOPE.all[1]}">Every repo</span>` : `<span class="tag" title="${PASS_SCOPE.repo[1]}">Every PR in ${esc(x.repo)}</span>`;
function passedSection(d, unlocked) {
  const rows = d.passed || [];
  const line = x => { const [r, n] = String(x.pr).split("#"); return `<li class="fx-i"><div class="grow">${passedTag(x)} <b>${esc(x.title)}</b> <span class="tag">${esc(x.severity || "")}</span>${x.issue ? `<div class="muted small">${esc(x.issue)}</div>` : ""}
      <div class="muted small">From <a href="#prs/${esc(r)}/${esc(n)}">${esc(x.pr)}</a> · ${ago(x.at)}${x.note ? ` · ${esc(x.note)}` : ""}</div></div>
      <button class="btn small" data-pass-rm="${esc(x.id)}" ${unlocked ? "" : "disabled"} title="Let reviews flag this again">Remove</button></li>`; };
  return section("Passed on for good", `<p class="muted small">Findings you told reviews not to flag again. Every review reads these before it files anything, and raises one again only if it is clearly worse than when you passed on it. Remove one to let reviews flag it again.</p>
    ${rows.length ? `<ul class="list items box">${rows.map(line).join("")}</ul>` : `<p class="muted small">Nothing yet. When you Drop or Pass on a finding, you choose how far "don't flag this again" reaches.</p>`}`, rows.length ? plural(rows.length, "finding") : "");
}
const ownCard = card => /^Pass$/.test((($('[data-pr-mark*="drop"]', card) || {}).textContent || "").trim());  // your own PR says Pass, not Drop
/* After dropping a finding: how far "don't flag this again" reaches. This PR only is what dropping always did. */
function offerPass(pr, id, title, own) {
  const repo = String(pr).split("#")[0];
  const row = (scope, label, why, primary) => `<div class="row" style="gap:10px;align-items:flex-start;margin-top:8px"><button class="btn${primary ? " primary" : ""}" data-pass-scope="${scope}" style="flex:none;min-width:190px">${label}</button><span class="muted small">${why}</span></div>`;
  openDrawer("Don't flag this again?", `<div class="readable"><p><b>${txt(title)}</b></p>
    <p class="muted small">You ${own ? "passed on" : "dropped"} this finding. How far should that reach? Whatever you pick, a finding that gets worse is still raised.</p>
    ${row("pr", "Only on this PR", "Later reviews of this PR leave it alone. This is what dropping always did.")}
    ${row("repo", `Every PR in ${esc(repo)}`, PASS_SCOPE.repo[1], true)}
    ${row("all", "Every repo", PASS_SCOPE.all[1])}
    <textarea class="editor small mt" data-pass-note rows="2" placeholder="Why? Optional, shown next to it in the list"></textarea>
    <span class="save-msg" data-pass-msg></span></div>`);
  $$("#drawer-body [data-pass-scope]").forEach(b => b.onclick = async () => {
    $$("#drawer-body [data-pass-scope]").forEach(x => (x.disabled = true));
    const d = await save("review_pass", { pr, id, scope: b.dataset.passScope, note: $("#drawer-body [data-pass-note]").value });
    if (!d.ok) { $$("#drawer-body [data-pass-scope]").forEach(x => (x.disabled = false)); return saidMsg($("#drawer-body [data-pass-msg]"), d); }
    closeDrawer();
    if (b.dataset.passScope !== "pr") prefToast(`Reviews won't flag this again in ${b.dataset.passScope === "all" ? "any repo" : repo}. You can undo it under Passed on for good.`);
    softRoute();
  });
}
/* A Linear ticket as Lee's rules want it named: its id and, when LFG has it, its title. */
const ticketName = t => `${t}${(state.ticketTitles || {})[t] ? ` (${state.ticketTitles[t]})` : ""}`;
/* Open PRs grouped by the Linear ticket their branch, title or description names, to review a ticket's PRs at once. */
function ticketSection(d, unlocked) {
  const seen = new Set(), by = new Map();
  for (const x of [...(d.mine || []), ...(d.queue || []), ...(d.reviews || []).filter(r => r.open), ...(d.ticket_more || [])]) {
    if (!x.ticket || seen.has(prRef(x))) continue;
    seen.add(prRef(x));
    (by.get(x.ticket) || by.set(x.ticket, []).get(x.ticket)).push(x);
  }
  const groups = [...by].sort((a, b) => b[1].length - a[1].length || b[0].localeCompare(a[0])).map(([t, prs]) => `<details class="item" ${prs.length > 1 ? "open" : ""}><summary><span class="grow"><b class="mono">${esc(t)}</b> ${esc((state.ticketTitles || {})[t] || "")} <span class="muted small">${plural(prs.length, "open PR")}</span></span>${prs.some(x => x.passes) ? `<a class="small" href="#prs/ticket/${encodeURIComponent(t)}" title="Every review of this ticket's PRs on one page">Open reviews</a>` : ""}</summary>
    <ul class="list">${prs.map(x => `<li><input type="checkbox" data-pr-pick="${esc(prRef(x))}" ${state.prPick.has(prRef(x)) ? "checked" : ""} ${unlocked ? "" : "disabled"} aria-label="Pick ${esc(prRef(x))}"><div class="grow">${esc(x.title || "")}<div class="meta mono">${esc(prRef(x))} · by ${esc(x.author || "")}${x.passes ? ` · ${plural(x.passes, "review")}` : ""}</div>${x.job ? `<div class="meta">${jobLine(x.job)}</div>` : ""}</div><a class="small" href="${esc(prHash(x))}">Open</a></li>`).join("")}</ul>
    <div class="row mt"><button class="btn small primary" data-ticket-run='${esc(JSON.stringify([t, prs.map(prRef)]))}' ${unlocked ? "" : "disabled"} title="One Claude session reviews them as one change, reading the ticket, and checks they agree with each other">${anyReviewed(prs.map(prRef)) ? (prs.length > 1 ? `Re-review all ${prs.length} together` : "Re-review") : prs.length > 1 ? `Review all ${prs.length} together` : "Review it"}</button>${anyReviewed(prs.map(prRef)) ? `<button class="btn small" data-ticket-run='${esc(JSON.stringify([t, prs.map(prRef)]))}' data-fresh="1" ${unlocked ? "" : "disabled"} title="${FULL_TITLE}">${prs.length > 1 ? `Review all ${prs.length} from scratch` : "Review from scratch"}</button>` : ""}<button class="btn small" data-ticket-find="${esc(t)}" ${unlocked ? "" : "disabled"} title="Ask GitHub for other open PRs that name ${esc(t)}, in any repo">Find more PRs on ${esc(t)}</button><span class="muted small">or tick some and use the bar above</span></div>${anyReviewed(prs.map(prRef)) ? AGAIN_HELP : ""}</details>`).join("");
  return section("By Linear ticket", `${groups ? `<div class="box">${groups}</div>` : ""}
    <div class="row mt"><input type="text" id="tk-id" class="mono" placeholder="ATO-4223" ${unlocked ? "" : "disabled"}><button class="btn small" id="tk-go" ${unlocked ? "" : "disabled"}>Find the ticket's PRs</button></div>`,
    "open PRs whose branch, title or description names a Linear ticket, from every repo");
}
/* A ticket's open PRs from GitHub, ticked, to review together. */
async function ticketFind(t) {
  t = String(t || "").trim().toUpperCase();
  if (!t) return;
  openDrawer(`Open PRs on ${t}`, '<div class="skeleton"></div>');
  const d = await api("ticketprs", { ticket: t });
  if (d.available === false) return openDrawer(`Open PRs on ${t}`, `<p class="muted">${esc(d.why)}</p>`);
  const prs = d.prs || [];
  if (d.title) state.ticketTitles = { ...(state.ticketTitles || {}), [t]: d.title };
  openDrawer(`Open PRs on ${ticketName(t)}`, `<div class="readable">${prs.length ? `<p>GitHub found ${plural(prs.length, "open PR")} that name ${esc(t)}. Untick any you don't want, then review the rest in one session that reads the ticket.</p>
    <ul class="items box">${prs.map(x => `<li><input type="checkbox" data-tk-pick="${esc(prRef(x))}" checked><div class="grow">${esc(x.title)}<div class="meta mono">${esc(prRef(x))} · by ${esc(x.author)}</div></div></li>`).join("")}</ul>
    <div class="row mt"><button class="btn primary" id="tk-run">Review the ticked ones</button><span class="save-msg" id="tk-msg"></span></div>` : `<p class="muted">GitHub has no open PR whose title or description names ${esc(t)}. A PR that names it only in its branch shows under By Linear ticket once it's in your lists.</p>`}</div>`);
  const b = $("#tk-run");
  if (b) b.onclick = async () => {
    const refs = $$("[data-tk-pick]").filter(c => c.checked).map(c => c.dataset.tkPick);
    if (!refs.length) return;
    b.disabled = true; b.textContent = "Starting…";
    const r = await save("review_run", { pr: refs[0], with: refs.slice(1), ticket: t });
    saidMsg($("#tk-msg"), r, "Started. It shows on each PR when it's done.");
    if (r.ok) setTimeout(() => { closeDrawer(); softRoute(); }, 900); else { b.disabled = false; b.textContent = "Try again"; }
  };
}
/* Pick several PRs on the list (checkboxes) and review them together in one session. */
/* Reviewing several PRs together: a PR reviewed before gets a re-review, unless you ask for a full one. The full option
   shows only when one of them has been reviewed. */
const FULL_TITLE = "Read all the code again, as if new. Earlier findings still open are still checked";
/* The two ways to review again, said the same way everywhere, under the buttons. */
const AGAIN_HELP = '<div class="again-help"><span><b>Re-review</b> checks your earlier comments and reads only the commits since the last review. Use it after the author pushed fixes.</span><span><b>From scratch</b> reads all the code again, as if new, and still checks earlier findings that are open. Use it when the PR changed a lot.</span></div>';
const anyReviewed = refs => refs.some(r => (state.prReviewed || new Set()).has(r));
function pickBar() {
  const bar = $("#pr-pickbar");
  if (!bar) return;
  const picked = [...state.prPick];
  bar.hidden = picked.length < 1;
  bar.innerHTML = `<span><b>${plural(picked.length, "PR")} picked:</b> <span class="mono small">${esc(picked.join(", "))}</span></span>
    <button class="btn small primary" id="pr-together" ${picked.length < 2 ? "disabled" : ""} title="One Claude session reviews them as one change: each gets its own review, and it checks they agree with each other">${anyReviewed(picked) ? "Re-review together" : "Review together"}</button>
    ${anyReviewed(picked) ? `<button class="btn small" id="pr-together-full" ${picked.length < 2 ? "disabled" : ""} title="${FULL_TITLE}">Review together from scratch</button>` : ""} <button class="btn small" id="pr-picklink" ${picked.length < 2 ? "disabled" : ""} title="Link their reviews without running anything">Link them</button>
    <button class="btn small" id="pr-pickclear">Clear</button>${anyReviewed(picked) && picked.length > 1 ? AGAIN_HELP : ""}`;
  $("#pr-pickclear").onclick = () => { state.prPick.clear(); $$("[data-pr-pick]").forEach(c => (c.checked = false)); pickBar(); };
  const together = async e => {
    const b = e.target, [first, ...rest] = picked, fresh = b.id === "pr-together-full";
    b.disabled = true; b.textContent = "Starting…";
    const ts = [...new Set(picked.map(x => (state.prTicket || {})[x]))];
    const r = await save("review_run", { pr: first, with: rest, fresh, ticket: ts.length === 1 && ts[0] ? ts[0] : undefined });
    if (!r.ok) { b.disabled = false; b.textContent = "Try again"; return alertMsg(b, r); }
    state.prPick.clear(); setTimeout(softRoute, 1000);
  };
  $("#pr-together").onclick = together;
  if ($("#pr-together-full")) $("#pr-together-full").onclick = together;
  $("#pr-picklink").onclick = async e => {
    const [first, ...rest] = picked;
    for (const x of rest) { const r = await save("review_link", { pr: first, other: x }); if (!r.ok) return alertMsg(e.target, r); }
    for (let i = 1; i < rest.length; i++) for (const y of rest.slice(i)) await save("review_link", { pr: rest[i - 1], other: y });
    state.prPick.clear(); softRoute();
  };
}
/* Another PR's review from the same session, on this PR's page: its summary and findings, decided here like this PR's. */
function togetherSection(t, unlocked, me) {
  const q = t.pass, link = `<a class="mono" href="#prs/${esc(t.pr.replace("#", "/"))}">${esc(t.pr)}</a>`;
  if (!q) return section(`Findings on ${t.pr}`, `<p class="muted small">No review was saved for ${link} from this session.</p>`);
  const order = { blocker: 0, major: 1, minor: 2, nitpick: 3, note: 4 };
  const fs = [...q.findings].sort((a, b) => (order[a.severity] ?? 5) - (order[b.severity] ?? 5));
  const stale = !t.live && !q.posted ? `<p class="muted small">${link} has a newer review; post that one from its page.</p>` : "";
  const own = !!(t.author && me && t.author === me);
  return section(`Findings on ${t.pr}`, `${t.title ? `<p class="muted small">${esc(t.title)}</p>` : ""}${q.summary ? `<p>${txt(q.summary)}</p>` : ""}
    ${fs.length ? fs.map(f => prFinding(f, t.pr, unlocked, t.live, own)).join("") : empty("Nothing found", "Nothing to comment on in this PR.")}
    ${stale || postBar(t.pr, q, t.live, own, unlocked)}`, prTally(q, own));
}
/* "3 findings · 1 kept · 2 to decide · score 91" for one PR's review */
/* Passed on, or "Is it fixed?" found it fixed: decided, and no longer costs points. */
const settled = f => f.status === "drop" || (f.check || {}).state === "fixed";
const undecided = p => p.findings.filter(f => f.status === "pending" && !settled(f)).length;
function prTally(p, own) {
  const fixed = p.findings.filter(f => f.status !== "drop" && (f.check || {}).state === "fixed").length;
  const kept = p.findings.filter(f => f.status === "keep" && !settled(f)).length, pending = undecided(p);
  const dropped = p.findings.filter(f => f.status === "drop").length;
  return `${plural(p.findings.length, "finding")} · ${kept} ${own ? "to fix" : "kept"}${fixed ? ` · ${fixed} fixed` : ""}${dropped ? ` · ${dropped} ${own ? "passed" : "dropped"}` : ""} · ${pending} to decide${p.score != null ? ` · score ${esc(p.score)}` : ""}`;
}
/* On your own PR: Claude fixes the findings marked Fix, in one commit unless that would be too big, and pushes. */
function fixBar(pr, p, live, unlocked, fj, carry) {
  const steps = j => (j.steps || []).length ? `<ul class="mono small pr-steps">${j.steps.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : "";
  if (fj && fj.status === "running") return `<div class="callout">${dot("on")}<b>Fixing ${plural((fj.ids || []).length, "finding")}</b>, started ${ago(fj.started)}${fj.cwd ? ` in <span class="mono">${esc(fj.cwd)}</span>` : ""}. This updates by itself.${steps(fj)}</div>`;
  const done = p.fix ? `<div class="callout ${(p.fix.commits || []).length ? "ok" : "warn"}">${dot((p.fix.commits || []).length ? "ok" : "warn")}${(p.fix.commits || []).length ? `Fixed and pushed ${ago(p.fix.ended)} in ${(p.fix.commits || []).map(c => `<span class="mono">${esc(c.slice(0, 8))}</span>`).join(", ")}.` : "The last fix didn't commit anything."}${p.fix.note ? ` <span class="pre-wrap">${txt(p.fix.note)}</span>` : ""}${(p.fix.skipped || []).length ? `<ul>${p.fix.skipped.map(x => `<li><b class="mono">${esc(x.id)}</b> skipped: ${txt(x.why || "")}</li>`).join("")}</ul>` : ""}</div>` : "";
  const failed = fj && fj.status === "failed" ? `<div class="callout bad">${dot("bad")}The fix didn't go through: ${esc(fj.why || "")}${steps(fj)}</div>` : "";
  if (!live) return done || `<p class="muted small">An older review. Only the newest one can be fixed.</p>`;
  const pending = undecided(p);
  const todo = [...p.findings, ...(carry || [])].filter(f => f.status === "keep" && !(f.fixed || {}).commit && !settled(f)).length;
  return `<div class="pr-fixbar">${done}${failed}<div class="panel"><div class="k" style="margin-top:0">Fix your PR: <span class="mono">${esc(pr)}</span></div>
      <div class="row"><button class="btn primary" data-pr-fix="${esc(pr)}" ${unlocked && !pending && todo ? "" : "disabled"}>Fix ${plural(todo, "finding")}</button>
      <span class="muted small">${pending ? `Choose Fix or Pass on ${plural(pending, "more finding")} first.` : todo ? "Claude fixes them in a checkout of the PR's branch, runs the tests, and pushes one commit (more only if one would be too big to review)." : "Nothing marked Fix."}</span></div></div></div>`;
}
/* Post one PR's review to GitHub. Every PR on a reviewed-together page gets its own, whichever repo is picked. */
function postBar(pr, p, live, own, unlocked, fj, carry) {
  if (own && !p.posted) return fixBar(pr, p, live, unlocked, fj, carry);
  if (p.posted) return `<div class="callout ok">${dot("ok")}Posted ${ago(p.posted.ts)}. <a href="${esc(p.posted.url)}" target="_blank" rel="noopener noreferrer">Open on GitHub ↗</a></div>`;
  if (!live) return `<p class="muted small">An older review. Only the newest one can be posted or discarded.</p>`;
  const pending = undecided(p), kept = p.findings.filter(f => f.status === "keep" && !settled(f)).length;
  return `<div class="panel"><div class="k" style="margin-top:0">Post to GitHub: <span class="mono">${esc(pr)}</span></div>
      <textarea class="editor small" data-pr-postbody="${esc(pr)}" placeholder="Optional: a note above the comments"></textarea>
      <div class="row mt">${(own ? [["comment", "Comment only"]] : [["request-changes", "Request changes"], ["approve", "Approve"], ["comment", "Comment only"]]).map(([e, l]) => `<button class="btn${e === "request-changes" || own ? " primary" : ""}" data-pr-preview='${esc(JSON.stringify([pr, e]))}' ${unlocked && !pending ? "" : "disabled"}>${l}…</button>`).join("")}
      <span class="muted small">${pending ? `Decide ${plural(pending, "more finding")} first.` : `${plural(kept, "kept finding")} will be posted. You'll see exactly what goes out before it does.`}${own ? " This is your own PR, so GitHub only takes a comment." : ""}</span></div></div>`;
}
function prFinding(f, pr, unlocked, live, own) {
  const where = f.file ? `${f.file}${f.line ? ":" + f.line : ""}` : "the PR as a whole";
  const tags = (ABOUT[f.about] ? `<span class="tag c-blue" title="${esc(ABOUT[f.about][1])}">${ABOUT[f.about][0]}</span>` : "")
    + [f.since !== "first" && SINCE[f.since], ORIGIN[f.origin]].filter(Boolean).map(t => `<span class="tag">${esc(t)}</span>`).join("")
    + (f.echoes || []).map(e => `<a class="tag warn" ${e.url ? `href="${esc(e.url)}" target="_blank" rel="noopener noreferrer"` : ""} title="${esc((e.near ? "Commented within a few lines of this: " : "") + (e.said || ""))}">Also raised by ${e.bot ? "" : "@"}${esc(e.who)}${e.url ? " ↗" : ""}</a>`).join("")
    + (f.repeats || []).map(r => `<span class="tag warn" title="This Fresh eyes review didn't see earlier reviews; review ${r.pass} raised this as ${esc(r.id)}${r.status === "drop" ? " and you dropped it" : r.status === "keep" ? " and you kept it" : ""}${r.posted ? ", and it was posted" : ""}">Also in review ${r.pass} (${esc(r.id)}${r.status === "drop" ? ", dropped" : ""})</span>`).join("")
    + (f.status === "drop" && f.dropped_by === "claude" ? `<span class="tag" title="You said it wasn't needed and Claude agreed after checking the code">Claude agreed: not needed</span>` : "")
    + (f.passed_on ? `<span class="tag" title="You told reviews not to flag this again: ${esc(PASS_SCOPE[f.passed_on.scope][1])} Remove it on the PR reviews page, under Passed on for good.">Passed on ${esc(PASS_SCOPE[f.passed_on.scope][2])}</span>` : "")
    + ((f.fixed || {}).commit ? `<span class="tag ok">Fixed in ${esc(f.fixed.commit.slice(0, 8))}</span>` : "")
    + (f.raised_by ? `<a class="tag" ${f.raised_by.url ? `href="${esc(f.raised_by.url)}" target="_blank" rel="noopener noreferrer"` : ""}>From ${f.raised_by.bot ? "" : "@"}${esc(f.raised_by.who)}${f.raised_by.url ? " ↗" : ""}</a>${WORTH[f.worth] ? `<span class="tag ${WORTH[f.worth][1]}">${WORTH[f.worth][0]}</span>` : ""}` : "");
  const posted = f.comment_url ? `<a class="small" href="${esc(f.comment_url)}" target="_blank" rel="noopener noreferrer">Posted ↗</a>` : "";
  const can = unlocked && !f.comment_id && !(f.fixed || {}).commit;  // a decision is yours in any review; only posting is the newest's
  const btn = (status, text) => `<button class="btn small${f.status === status ? " primary" : ""}" data-pr-mark='${esc(JSON.stringify([pr, f.id, status]))}' ${can ? "" : "disabled"}>${text}</button>`;
  const chat = f.chat || [];
  const ref = esc(JSON.stringify([pr, f.id]));
  const known = (state.snips || {})[JSON.stringify([pr, f.id])];  // fetched before: drawn at once, so a redraw doesn't show "Loading" again
  const code = f.file && f.line ? `<div class="pr-snip" data-pr-snip='${ref}'>${known ? snipHtml(known) : `<div class="pr-snip-h mono">${esc(where)}</div><div class="muted small pad">${known === false ? "Couldn't get this code from GitHub." : '<span class="loading-inline">Loading the code…</span>'}</div>`}</div>` : `<div class="muted small mono">${esc(where)}</div>`;
  const cost = POINTS[f.severity] || 0;
  const pts = cost ? `<span class="pts ${settled(f) ? "off" : ""}" title="${settled(f) ? `Would cost ${cost} points; ${f.status === "drop" ? "dropped" : "fixed"}, so it doesn't count` : `Costs ${cost} points of the score (${f.severity}). Nitpicks count once per kind`}">−${cost}</span>` : "";
  return `<div class="card pr-finding ${esc(f.status)}" id="f-${esc(f.id)}"><div class="row">${st(f.severity === "nitpick" ? "nit" : f.severity)}${pts}${tags}<span class="grow"></span><span class="muted small mono">${esc(f.id)}</span></div>
    <div class="title">${txt(f.title || f.issue)}</div>
    ${f.issue && f.title ? `<p>${txt(f.issue)}</p>` : ""}${f.fix ? `<p><b>Fix:</b> ${txt(f.fix)}</p>` : ""}
    ${code}
    ${f.detail ? `<details class="more"><summary>What the review checked</summary><div class="md">${md(f.detail)}</div></details>` : ""}
    ${own ? "" : `<div class="k">Comment the author will read</div>
    <div class="pr-body md" data-pr-body="${esc(f.id)}">${md(f.body)}</div>
    <div class="pr-edit" data-pr-editbox="${esc(f.id)}" hidden>
      <div class="pr-compose slim"><textarea data-grow rows="1" data-pr-ask="${esc(f.id)}" placeholder="Ask Claude to change it: shorter, softer, add an example…"></textarea><button class="btn small" data-pr-askgo='${ref}'>Ask Claude</button></div>
      <textarea class="editor small">${esc(f.body)}</textarea>
      <div class="set-actions"><button class="btn small primary" data-pr-editsave='${ref}'>Save comment</button><button class="btn small" data-pr-editcancel="${esc(f.id)}">Cancel</button><span class="save-msg"></span></div></div>`}
    ${f.check ? checkLine(f.check) : ""}
    ${f.raised_by && own && f.status === "drop" ? replyBox(f, pr, unlocked) : ""}
    ${chat.length ? `<button class="pr-discussed" data-pr-discuss='${ref}' title="Open this conversation in the chat"><span class="pr-discussed-n">${plural(chat.length, "message")}</span><span class="pr-discussed-last">${esc(chat[chat.length - 1].a.replace(/```[\s\S]*?```/g, "").replace(/[*_`#>]/g, "").trim().slice(0, 140))}</span><span class="pr-discussed-go">Open ↗</span></button>` : ""}
    <div class="row mt">${posted || `${own ? `${btn("keep", "Fix")}${btn("drop", "Pass")}` : `${btn("keep", "Keep")}${btn("drop", "Drop")}<button class="btn small" data-pr-edit="${esc(f.id)}" ${can ? "" : "disabled"}>Edit comment</button>`}`}<button class="btn small" data-pr-discuss='${ref}' title="Talk this finding through with Claude: push back, ask why, or say it isn't needed">Discuss</button>${f.status === "drop" && !f.passed_on && !f.comment_id ? `<button class="btn small" data-pr-passoffer='${ref}' ${unlocked ? "" : "disabled"} title="Tell reviews not to flag this again: on every PR in this repo, or in every repo">Don't flag again…</button>` : ""}${f.status !== "drop" && !(f.fixed || {}).commit ? `<button class="btn small" data-pr-check='${ref}' ${unlocked ? "" : "disabled"} title="Look at the commits since this review and say whether this one finding is fixed, without a whole re-review">${f.check ? "Check again" : "Is it fixed?"}</button>` : ""}<span class="grow"></span>${copyBtns(findingForPerson(f, pr), findingForAgent(f, pr))}</div></div>`;
}
/* The last "Is it fixed?" answer for a finding. */
const CHECKED = { fixed: ["Fixed", "ok"], partly: ["Partly fixed", "warn"], not: ["Not fixed yet", "bad"] };
const checkLine = c => `<div class="pr-check ${CHECKED[c.state][1]}">${dot(CHECKED[c.state][1])}<b>${CHECKED[c.state][0]}</b><span class="grow">${txt(c.why)}</span><span class="muted small nowrap" title="Checked at commit ${esc((c.head || "").slice(0, 8))}">${ago(c.at)}</span></div>`;
const WORTH = { fix: ["Worth fixing", "warn"], maybe: ["Maybe worth it", ""], skip: ["Not worth fixing", "ok"] };
/* One turn of a conversation with Claude, and what it changed in the review. */
const chatTurn = (x, pr) => {
  const m = /^You asked: ([\s\S]*?)\nMy answer: ([\s\S]*)$/.exec(x.q || "");
  const tag = m ? `<a href="#" class="chip c-blue msg-tag" ${x.qid ? `data-goto-q="${esc(x.qid)}"` : ""} title="${esc(m[1])}">Answer to: ${esc(m[1].length > 60 ? m[1].slice(0, 59) + "…" : m[1])}</a>` : "";
  return chatTurnOf({ ...x, q: m ? m[2] : x.q }, pr, tag);
};
const CHAT_ATT = /\s*\[(?:image|file): ([^\]\s]+)\]/g;
const chatFiles = q => [...String(q || "").matchAll(CHAT_ATT)].map(m => m[1].split("/").pop());
const chatFileChips = q => [...String(q || "").matchAll(/\[(image|file): ([^\]\s]+)\]/g)].map(([, k, path]) =>
  `<button type="button" class="ss-chip chat-file" data-chat-file="${esc(path)}" title="Open ${esc(path.split("/").pop())}">${icon(k === "image" ? "image" : "docs")}<span>${esc(path.split("/").pop())}</span></button>`).join("");
const chatTurnOf = (x, pr, tag) => `<div class="msg you${x.queued ? " queued" : ""}">${tag || ""}<div class="bubble">${txt(String(x.q || "").replace(CHAT_ATT, "").trim())}${chatFiles(x.q).length ? `<div class="ss-att msg-files">${chatFileChips(x.q)}</div>` : ""}</div>${x.queued ? '<div class="msg-at">queued: sends when Claude answers the one before</div>' : x.at ? `<div class="msg-at">${msgStamp(x.at)}</div>` : ""}</div>${x.queued ? "" : x.a == null ? typing(x.session) : `<div class="msg claude"><div class="who">${x.session ? `Session: ${esc(x.session)}` : "Claude"}</div><div class="bubble md">${md(x.a)}</div>${changedChips(x.changed, pr)}</div>`}`;
const typing = who => '<div class="msg claude"><div class="who">' + (who ? "Session: " + esc(who) : "Claude") + '</div><div class="bubble typing" aria-label="Claude is thinking"><i></i><i></i><i></i></div></div>';
/* What a reply changed in the review, as chips that jump to the finding. */
function changedChips(changed, pr) {
  if (!(changed || []).length) return "";
  const word = { mergeable: "Mergeable", almost: "Almost mergeable", not: "Not mergeable" };
  return `<div class="msg-changes"><span class="small muted" title="What Claude's reply changed in the review. Findings open on the page when clicked">Claude changed:</span>${changed.map(c => {
    const m = /^(?:\S+#\d+ )?(\d+\.\d+): (.*)$/.exec(c);
    if (m && pr) {
      const what = m[2] === "dropped" ? "dropped: not needed" : m[2] === "kept" ? "kept" : `${m[2]} reworded`;
      return `<a href="#" class="chip chip-link" data-chat-goto='${esc(JSON.stringify([pr, m[1]]))}' title="Click to show finding ${esc(m[1])} on the page">${esc(m[1])} ${esc(what)}<span class="chip-go" aria-hidden="true">↗</span></a>`;
    }
    const v = /^verdict (\w+)$/.exec(c), sc = /^score (\d+)$/.exec(c);
    const label = v ? `Now ${word[v[1]] || v[1]}` : sc ? `Score now ${sc[1]}` : c === "verdict" ? "Verdict" : c === "summary" ? "Summary updated" : c;
    const tone = v ? { mergeable: "c-green", almost: "c-orange", not: "c-red" }[v[1]] || "" : "";
    return `<span class="chip chip-fact ${tone}" title="What this reply changed in the review">${esc(label)}</span>`;
  }).join("")}</div>`;
}
/* Passing on someone else's comment on your PR: the reply Claude drafted, to edit and post in their thread. */
function replyBox(f, pr, unlocked) {
  const who = `${f.raised_by.bot ? "" : "@"}${f.raised_by.who}`;
  if (f.replied) return `<div class="pr-reply"><div class="k">Your reply to ${esc(who)}</div><div class="pr-body md">${md(f.reply)}</div>${f.replied.url ? `<a class="small" href="${esc(f.replied.url)}" target="_blank" rel="noopener noreferrer">Posted ${ago(f.replied.at)} ↗</a>` : ""}</div>`;
  return `<div class="pr-reply"><div class="k">Reply to ${esc(who)} (optional)</div><textarea class="editor small" data-pr-replytext>${esc(f.reply || "")}</textarea>
    <div class="set-actions"><button class="btn small" data-pr-reply='${esc(JSON.stringify([pr, f.id]))}' ${unlocked ? "" : "disabled"}>Post reply on GitHub</button><span class="save-msg"></span></div></div>`;
}
/* Questions the review couldn't settle from the code: your answer goes to its conversation, which can change it. */
/* A question for the PR's author: post it on GitHub (inline on its line, else a PR comment), then their replies. A
   reply can be used as your answer: it goes to the review's chat like one you typed. */
function askAuthor(pr, p, q, unlocked) {
  const a = q.asked;
  if (!a) {
    if (q.answer) return "";
    const where = q.file && q.line ? `on ${q.file}:${q.line} if that line is in the diff, else as a comment on the PR` : "as a comment on the PR";
    return `<details class="pr-ask-gh" data-keep="open"><summary class="btn small" title="Post this question on GitHub for the PR's author, ${esc(where)}">Ask the author on GitHub…</summary>
      <div class="pr-compose"><textarea data-grow rows="2" data-pr-ghasktext ${unlocked ? "" : "disabled"}>${esc(q.ask)}</textarea><button class="btn small primary" data-pr-ghask='${esc(JSON.stringify([pr, p.n, q.id]))}' ${unlocked ? "" : "disabled"}>Post on GitHub</button></div>
      <div class="muted small">Posted ${esc(where)}, as it reads above: edit it first if it needs to read better for them. Their reply shows here.</div></details>`;
  }
  const reps = q.replies || [];
  const head = `<div class="muted small">${dot(reps.length ? "on" : "")}<a href="${esc(a.url || "#")}" target="_blank" rel="noopener noreferrer">Asked on GitHub ↗</a> ${a.kind === "inline" ? "on its line" : "as a PR comment"} · ${ago(a.at)}${reps.length ? "" : " · no reply yet"}</div>`;
  const list = reps.map(r => `<div class="pr-gh-reply"><b>${esc(r.by)}</b> <span class="muted small">${ago(r.at)}</span><div class="md">${md(r.body)}</div></div>`).join("");
  const use = reps.length && !q.answer && unlocked ? `<button class="btn small primary" data-pr-usereply='${esc(JSON.stringify([pr, p.n, q.id]))}' title="Send their reply to the review's chat as the answer: Claude changes the review if it settles something">Use their reply as the answer</button>` : "";
  return `<div class="pr-asked">${head}${list}${use}</div>`;
}
function questionsBox(pr, p, unlocked) {
  const qs = p.questions || [];
  if (!qs.length) return "";
  const open = qs.filter(q => !q.answer).length;
  const pend = state.chatPending || {};
  return `<div class="panel pr-questions"><div class="k" style="margin-top:0">${open ? `${plural(open, "question")} for you` : "Questions, answered"}</div><p class="muted small">Your answer goes to the review's chat. Claude replies here and changes the review if your answer settles something.</p>${qs.map(q => {
    const key = `q:${pr}:${p.n}:${q.id}`, waiting = pend[key];
    const said = q.answer || waiting;
    return `<div class="pr-question" id="q-${esc(q.id)}" data-ask="${esc(q.ask)}"><div class="pr-ask">${q.costs ? `<span class="pts q-pts ${q.answer ? "off" : ""}" title="${q.answer ? `Cost ${q.costs} points until you answered it` : `This question costs ${q.costs} points until it's answered: it could become a finding that holds the merge back`}">−${q.costs}</span>` : ""}<button class="btn tiny pr-q-copy" data-copy="${esc(q.ask + (q.why ? "\n\nWhy it matters: " + q.why : ""))}" title="Copy the question, and why it matters">Copy</button>${txt(q.ask)}${q.why ? `<div class="muted small">${txt(q.why)}</div>` : ""}${q.file ? `<div class="muted small mono">${esc(q.file)}${q.line ? ":" + esc(q.line) : ""}</div>` : ""}</div>${askAuthor(pr, p, q, unlocked)}${said
      ? `<div class="pr-chat-thread">${chatTurn({ q: said, a: waiting ? null : q.reply || (q.answer ? "" : null), changed: q.changed }, pr).replace('<div class="bubble md"></div>', '<div class="bubble md muted">Sent to the review\'s chat. Answers from before this update show their reply there.</div>')}</div>${q.answer ? rememberRow(pr, p.n, q, unlocked) : ""}`
      : `<div class="pr-compose"><textarea data-grow rows="2" data-pr-answer placeholder="Your answer" ${unlocked ? "" : "disabled"}></textarea><button class="btn small primary" data-pr-answergo='${esc(JSON.stringify([pr, p.n, q.id]))}' ${unlocked ? "" : "disabled"}>Answer</button>${((state.prSessions || {})[pr] || []).length ? `<button class="btn small" data-pr-qsession='${esc(JSON.stringify([pr, q.id]))}' ${unlocked ? "" : "disabled"} title="Ask a session about this PR, such as the one where you built it. Its answer comes back in the chat">Ask a session…</button>` : ""}</div>`}</div>`;
  }).join("")}</div>`;
}
/* The review's own conversation, beside it: ask, push back, or ask for changes, and the review changes to match. */
/* Can it merge? The review's own call when it made one, else worked out from the findings still open. */
const VERDICT = { mergeable: ["Mergeable", "ok"], almost: ["Almost mergeable", "warn"], not: ["Not mergeable", "bad"] };
function mergeVerdict(p) {
  if (VERDICT[p.verdict_now]) return { v: p.verdict_now, why: `${p.verdict_now === "mergeable" ? "Everything this review raised is now fixed or passed" : "What made it worse is fixed or passed; this is what is still open"}. When it ran it said ${VERDICT[p.verdict] ? VERDICT[p.verdict][0].toLowerCase() : "otherwise"}${p.verdict_why ? `: ${p.verdict_why}` : "."}`, guessed: false };
  if (VERDICT[p.verdict]) return { v: p.verdict, why: p.verdict_why || "", guessed: false };
  const open = (p.findings || []).filter(f => f.status !== "drop" && !(f.fixed || {}).commit);
  const big = open.filter(f => ["blocker", "major"].includes(f.severity)), small = open.filter(f => f.severity === "minor");
  if (big.length) return { v: "not", why: `${plural(big.length, big.some(f => f.severity === "blocker") ? "blocker or major finding" : "major finding")} still open`, guessed: true };
  if (small.length) return { v: "almost", why: `${plural(small.length, "minor finding")} still open`, guessed: true };
  return { v: "mergeable", why: "Nothing open that should hold it up", guessed: true };
}
/* What each severity costs: the review method's Score rule (plugin/review/method.md). */
const POINTS = { blocker: 25, major: 12, minor: 4, nitpick: 1, note: 0 };
const RUBRIC = `<details class="rubric"><summary class="small">How the score works</summary><div class="small">
  <p>Every review starts at 100 and loses points for each finding:</p>
  <div class="rubric-grid"><span>${st("blocker")}</span><b>−25</b><span>Breaks something people use, loses data, or opens a hole</span>
  <span>${st("major")}</span><b>−12</b><span>A real bug on a less common path, or wrong but recoverable</span>
  <span>${st("minor")}</span><b>−4</b><span>No bug today, but a real cost: duplication, a broken convention</span>
  <span>${st("nit")}</span><b>−1</b><span>Cosmetic or taste; counted once per kind</span>
  <span>${st("note")}</span><b>0</b><span>Context for the author, never counted</span></div>
  <p>An open question that holds the merge back costs what the finding it could become would. The score is always 100 minus what is still open: passing on a finding, a fix, or an answer gives its points back, and nothing comes off without a finding or question behind it. Green is 85 and up, yellow 70 to 84, red below 70.</p></div></details>`;
const scoreTone = sc => (sc >= 85 ? "ok" : sc >= 70 ? "warn" : "bad");
/* The verdict and the score, big, at the top of a review. */
function verdictHero(p, together, gh) {
  const { v, why, guessed } = mergeVerdict(p), [label, tone] = VERDICT[v], clash = approvedAnyway(gh, v);
  const sc = p.score != null && !together ? Number(p.score) : null;
  const ring = sc == null ? "" : `<div class="score-ring ${scoreTone(sc)}" style="--pct:${Math.max(0, Math.min(100, sc))}" title="100 minus what is still open"><span>${esc(sc)}</span><small>score</small></div>`;
  const upTo = (p.history || []).filter(x => x.n <= p.n);
  /* the score is 100 minus what is still open: its findings, earlier ones it still counted, and questions that cost points */
  const o = p.open_points || {}, part = (n, label, title) => n ? ` <span class="muted">−</span> <b>${n}</b> <span class="muted"${title ? ` title="${title}"` : ""}>${label}</span>` : "";
  const parts = part(o.findings, "open findings") + part(o.earlier, "earlier findings", "Earlier reviews' findings this review still counted as open") + part(o.questions, "open questions");
  const breakdown = sc == null ? "" : `<div class="score-why small" title="The score is 100 minus these">100${parts || ` <span class="muted">− nothing open</span>`} <span class="muted">=</span> <b>${sc}</b></div>${(p.credits || []).length ? `<div class="score-why small">${esc(p.score_at_review)} when reviewed, <b>${sc}</b> now: ${p.credits.map(c => `+${c.points} for ${esc(c.id)} ${{ fixed: "fixed", passed: "passed on", answered: "answered" }[c.why] || esc(c.why)}`).join(", ")}</div>` : ""}`;
  return `<div class="verdict-hero ${tone}">${ring}<div class="grow"><div class="verdict-badge ${tone}">${dot(tone)}${esc(label)}</div>${why ? `<div class="verdict-why">${txt(why)}</div>` : ""}${guessed ? '<div class="muted small">Worked out from the open findings; new reviews give their own call.</div>' : ""}${breakdown}${RUBRIC}</div>${together ? "" : trend(upTo)}</div>${clash ? `<div class="callout ${clash.others ? "bad" : "warn"} approved-anyway">${dot(clash.others ? "bad" : "warn")}<span>${esc(clash.text)}</span></div>` : ""}`;
}
/* Which way the score is heading: against the review before, and a small line of every score so far. */
function trend(list, compact) {
  const xs = (list || []).filter(x => x.score != null);
  if (xs.length < 2) return "";
  const a = xs[xs.length - 2], b = xs[xs.length - 1], d = b.score - a.score;
  const [cls, arrow, word] = d > 0 ? ["up", "↑", `Up ${d}`] : d < 0 ? ["down", "↓", `Down ${-d}`] : ["same", "→", "Same"];
  const title = `${word} from review ${a.n} (${a.score}). Every score: ${xs.map(x => `#${x.n} ${x.score}${x.kind === "full" ? " full" : x.kind === "re-review" ? " re" : ""}`).join(", ")}`;
  const badge = `<span class="trend ${cls}" title="${esc(title)}">${arrow}${compact ? (d ? Math.abs(d) : "") : ` ${esc(word)}`}</span>`;
  if (compact) return badge;
  const w = 120, h = 32, lo = Math.min(...xs.map(x => x.score)) - 5, hi = Math.max(...xs.map(x => x.score)) + 5;
  const pt = (x, i) => [Math.round((i / (xs.length - 1)) * (w - 8)) + 4, Math.round(h - 4 - ((x.score - lo) / Math.max(1, hi - lo)) * (h - 8))];
  const pts = xs.map(pt);
  const spark = `<svg class="spark" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" role="img" aria-label="${esc(title)}"><polyline points="${pts.map(p => p.join(",")).join(" ")}" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>${pts.map((p, i) => `<circle cx="${p[0]}" cy="${p[1]}" r="${i === pts.length - 1 ? 3.5 : 2.5}"><title>Review ${xs[i].n}: ${xs[i].score}</title></circle>`).join("")}</svg>`;
  return `<div class="trend-box ${cls}">${badge}<span class="muted small">from review ${a.n}</span>${spark}</div>`;
}
/* Approved on GitHub while the review says it isn't ready: say who, loudest when it wasn't you. */
function approvedAnyway(gh, v) {
  if (!gh || v === "mergeable") return null;
  const who = (gh.reviewers || []).filter(r => r.state === "APPROVED").map(r => r.who);
  if (!who.length) return null;
  const names = who.map(w => (w === gh.me ? "you" : "@" + w));
  return { names, others: who.some(w => w !== gh.me), text: `Approved by ${names.length > 1 ? names.slice(0, -1).join(", ") + " and " + names.slice(-1) : names[0]}, but this review says it ${v === "not" ? "isn't ready to merge" : "isn't quite ready"}.` };
}
/* A compact verdict for lists. */
function verdictPill(r) {
  const v = VERDICT[r.verdict] ? r.verdict : null, clash = v && approvedAnyway(r.gh, v);
  return v ? `<span class="tag ${VERDICT[v][1]} verdict-pill">${esc(VERDICT[v][0])}</span>${clash ? `<span class="tag ${clash.others ? "bad" : "warn"}" title="${esc(clash.text)}">approved anyway</span>` : ""}` : "";
}
/* Keep an answer: a decision for this repo (dev-graph) or a note for you (second-brain). */
function rememberRow(pr, n, q, unlocked) {
  if (q.saved) return `<div class="pr-remember small muted">${dot("ok")}Saved to ${q.saved.to === "dev-graph" ? "this repo's dev-graph, as a decision" : "your second-brain, as a note"} ${ago(q.saved.at)}</div>`;
  const b = (to, label, title) => `<button class="btn small" data-pr-remember='${esc(JSON.stringify([pr, n, q.id, to]))}' title="${title}" ${unlocked ? "" : "disabled"}>${label}</button>`;
  return `<div class="pr-remember"><div class="row"><span class="muted small">Worth keeping?</span>${b("dev-graph", "Remember for this repo", "Saved as a decision in this repo's dev-graph: every session and review in this repo can find it")}${b("second-brain", "Remember for me", "Saved as a note in your second-brain: yours, in every repo")}</div>
    <div class="small muted remember-help"><span><b>For this repo:</b> a decision in this repo's dev-graph. Every session and review here can find it; it's on the Knowledge page.</span><span><b>For me:</b> a note in your second-brain. Only yours, in every repo.</span></div></div>`;
}
/* Save what a finding's discussion settled: asked every time where it goes. Later reviews read it as settled. */
function findingSaveRow(pr, f, unlocked) {
  if (!(f.chat || []).length) return "";
  const done = f.saved || [], has = to => done.some(x => x.to === to);
  const said = done.map(x => `${dot("ok")}Saved to ${x.to === "dev-graph" ? "this repo's dev-graph, as a decision" : "your second-brain, as a note"} ${ago(x.at)}`).join(" · ");
  const decided = f.status !== "pending";
  const b = (to, label, title) => has(to) ? "" : `<button class="btn small" data-pr-savefinding='${esc(JSON.stringify([pr, f.id, to]))}' title="${title}" ${unlocked && decided ? "" : "disabled"}>${label}</button>`;
  const buttons = b("dev-graph", "Save for this repo", "Saved as a decision in this repo's dev-graph: later reviews and sessions in this repo read it as settled") + b("second-brain", "Save for me", "Saved as a note in your second-brain: yours, in every repo, and later reviews read it as settled");
  return `<div class="pr-remember chat-save"><div class="row"><span class="muted small">Settled for next time?</span>${buttons}<span class="save-msg"></span></div>
    ${decided ? "" : `<div class="small muted">Choose Keep or Drop on the finding first: the decision is what gets saved.</div>`}
    ${said ? `<div class="small muted">${said}</div>` : ""}</div>`;
}
/* The chat, beside the review: about the whole review, or about one finding (Discuss). Side panel, wide, or hidden
   behind a button; your choice is remembered. Ask, push back, or say a finding isn't needed: the review changes to
   match what the conversation settles. */
const chatMode = () => localStorage.getItem("lfg.chat") || "side";
const rvBusy = d => !!d && ["working", "needs-you", "starting"].includes(d.state);
function talkPane(pr, p, unlocked, byId) {
  state.lastTalk = { pr, p, unlocked, byId };  // what a Discuss redraws from at once, before the page catches up
  const about = (state.chatAbout || {})[pr], f = about && byId[about];
  const mode = chatMode(), count = (p.chat || []).length;
  const rd = ((state.rv || {})[pr] || {}).d;  // the chat as last seen, so a redraw of the page draws it the same
  const hint = f ? `Ask about ${f.id}, push back, or say it isn't needed. If Claude agrees after checking the code, it drops the finding; if not, it says why it still matters.`
    : `Ask why something is rated the way it is, push back, or ask for a change: "drop 1.3, it's handled in the caller", "make 1.1 softer". The review changes to match.`;
  const ico = d => `<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="${d}"/></svg>`;
  const old = (f ? f.chat || [] : p.chat || []).filter(x => !x.studio);  // said before this chat became Studio's: kept, read only
  const askAgain = f && f.status === "drop" && !f.passed_on && !f.comment_id && (f.chat || []).length
    ? `<div class="pr-remember chat-save"><div class="row"><span class="muted small">Dropped. Should reviews stop raising it?</span><button class="btn small" data-pr-passoffer='${esc(JSON.stringify([pr, f.id]))}' ${unlocked ? "" : "disabled"} title="Tell reviews not to flag this again: on this PR, on every PR in this repo, or in every repo">Don't flag again…</button></div></div>` : "";
  return `<button class="chat-fab" data-chat-mode="side" ${mode === "hidden" ? "" : "hidden"}>${ico("M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z")}Chat${count ? `<span class="n">${count}</span>` : ""}</button>
  <aside class="pr-talk ${mode}" ${mode === "hidden" ? "hidden" : ""} data-chat="${esc(JSON.stringify([pr, p.n, f ? f.id : ""]))}">
    <div class="pr-talk-h"><b>Chat</b><select class="chat-to" data-chat-to="${esc(pr)}" data-fill title="The session your messages go to. It opens on the session that did this review, which can change the review. Any other session only answers; a terminal session is copied first, so the terminal's stays as it was."></select><span class="rv-ctx" data-fill></span><span class="grow"></span><a class="icon-btn rv-open" href="#studio${rd ? "/" + esc(rd.id) : ""}" title="Open this session in Studio" ${rd ? "" : "hidden"}>${ico("M14 3h7v7M21 3l-9 9M10 5H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-5")}</a>
      <button class="icon-btn" data-chat-mode="${mode === "wide" ? "side" : "wide"}" title="${mode === "wide" ? "Back to the side" : "Make it bigger"}">${ico(mode === "wide" ? "M4 14h6v6M20 10h-6V4M14 10l7-7M3 21l7-7" : "M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7")}</button>
      <button class="icon-btn" data-chat-mode="hidden" title="Hide the chat">${ico("M18 6 6 18M6 6l12 12")}</button></div>
    <div class="chat-about"><button class="chip ${f ? "" : "on"}" data-chat-about='${esc(JSON.stringify([pr, ""]))}'>Whole review${count ? ` · ${count}` : ""}</button>${f ? `<span class="chip on" title="${esc(f.title || f.issue || "")}">${esc(f.id)} · ${esc((f.title || f.issue || "").slice(0, 40))}${(f.title || f.issue || "").length > 40 ? "…" : ""}<a href="#" data-chat-about='${esc(JSON.stringify([pr, ""]))}' aria-label="Back to the whole review">×</a></span>` : ""}</div>
    ${old.length ? `<details class="chat-hist chat-old"><summary>${plural(old.length, "earlier message")} from before the chat moved into Studio</summary>${old.map(x => chatTurn(x, pr)).join("")}</details>` : ""}
    <div class="pr-thread ss-conv rv-conv" data-hint="${esc(hint)}" data-fill><div class="loading-inline">Opening the chat…</div></div>
    ${f ? findingSaveRow(pr, f, unlocked) : ""}${askAgain}
    <div class="pr-compose big" id="rv-comp"><div class="ss-att" id="rv-att" data-fill data-keep="hidden" hidden></div><textarea data-grow rows="3" data-pr-chat placeholder="${f ? `Say something about ${esc(f.id)}…` : "Ask, push back, or ask for a change. Start with / for a command or skill."}" ${unlocked ? "" : "disabled"}></textarea>
      <div class="pr-compose-bar"><button type="button" class="icon-btn ss-clip" data-rv-attach title="Attach files or images. You can also drop them here or paste them." ${unlocked ? "" : "disabled"}>${icon("clip")}</button><input type="file" data-rv-file multiple hidden><span class="muted small grow">Enter to send · Shift+Enter for a new line · drop, paste or attach any file</span><button class="btn small primary" data-pr-chatgo ${unlocked ? "" : "disabled"}>${rvBusy(rd) ? "Queue" : "Send"}</button></div></div></aside>`;
}
/* Copy one finding or earlier comment: short for a person, everything an agent needs to act on it. */
const copyBtns = (person, agent) => `<button class="btn small" data-copy="${esc(person)}" title="What's wrong, where, and the comment: to paste to a person">Copy</button><button class="btn small" data-copy="${esc(agent)}" title="Everything needed to act on it: file and line, issue, fix, the evidence, the comment and its status">Copy for an agent</button>`;
const whereOf = f => f.file ? `${f.file}${f.line ? ":" + f.line : ""}` : "the PR as a whole";
const DECIDED = { keep: "kept", drop: "dropped", pending: "not decided yet" };
function findingForPerson(f, pr) {
  return [`${f.title || f.issue} (${f.severity}) in ${pr}`, `Where: ${whereOf(f)}`, f.body, f.comment_url || ""].filter(Boolean).join("\n\n");
}
function findingForAgent(f, pr) {
  return [`# Review finding ${f.id} on ${pr}: ${f.title || f.issue}`,
    `Severity: ${f.severity}. Status: ${DECIDED[f.status] || f.status}${f.comment_url ? ", posted" : ""}${(f.fixed || {}).commit ? `, fixed in ${f.fixed.commit}` : ""}.`,
    `Where: ${whereOf(f)}`, f.issue ? `Issue: ${f.issue}` : "", f.fix ? `Suggested fix: ${f.fix}` : "",
    f.detail ? `What the review checked: ${f.detail}` : "", ...findingState(f),
    f.body ? `Comment for the author:\n${f.body}` : "", f.comment_url ? `On GitHub: ${f.comment_url}` : "",
    (f.chat || []).length ? `Discussion so far:\n\n${copyChat(f.chat)}` : "",
    "Verify it against the code before changing anything; if it's wrong, say why instead."].filter(Boolean).join("\n\n");
}
function earlierForPerson(x, f, pr, said) {
  return [`${f.title || x.id} on ${pr}: ${said}`, x.note || "", f.comment_url || ""].filter(Boolean).join("\n\n");
}
function earlierForAgent(x, f, pr, said) {
  return [`# Earlier review comment ${x.id} on ${pr}: ${f.title || ""}`, `Now: ${said}.`, x.note ? `Why: ${x.note}` : "",
    `Where: ${whereOf(f)}`, f.issue ? `Original issue: ${f.issue}` : "", f.fix ? `Suggested fix: ${f.fix}` : "",
    f.body ? `What was posted:\n${f.body}` : "", f.comment_url ? `On GitHub: ${f.comment_url}` : ""].filter(Boolean).join("\n\n");
}
/* The code a finding points at, like GitHub shows it: file name on top, old and new line numbers, added and removed lines. */
function snipHtml(sn) {
  const rows = sn.rows.map(r => `<tr class="${r.kind === "+" ? "add" : r.kind === "-" ? "del" : ""}${r.at ? " at" : ""}"><td class="ln">${r.kind === "+" ? "" : esc(r.old ?? "")}</td><td class="ln">${r.kind === "-" ? "" : esc(r.new ?? "")}</td><td class="sg">${r.kind === " " ? "" : esc(r.kind)}</td><td class="tx">${esc(r.text)}</td></tr>`).join("");
  const short = x => esc(String(x || "").slice(0, 7));
  const note = sn.changed_since ? `This line changed after the review; shown as it was at the reviewed commit <span class="mono">${short(sn.head)}</span>.`
    : sn.reviewed_head && sn.head !== sn.reviewed_head ? `At the PR's latest commit <span class="mono">${short(sn.head)}</span>${sn.reviewed_line !== sn.line ? `; the review saw it at line ${esc(sn.reviewed_line)} of <span class="mono">${short(sn.reviewed_head)}</span>` : ""}.` : "";
  return `<div class="pr-snip-h mono">${esc(sn.file)}</div>${note ? `<div class="pr-snip-note">${note}</div>` : ""}<div class="pr-snip-b"><table>${rows}</table></div>`;
}
/* Every reviewed PR on one Linear ticket, on one page: each with its newest review, score and post box. */
async function prTicket(t) {
  const [d, unlocked] = await Promise.all([api("prreviews", { all: "1" }), isUnlocked()]);
  crumbs("prs", t);
  const back = '<a class="back" href="#prs">← All reviews</a>';
  const seen = new Set();
  const refs = [...(d.reviews || []), ...(d.mine || []), ...(d.queue || []), ...(d.ticket_more || [])]
    .filter(x => x.ticket === t && x.passes && !seen.has(prRef(x)) && seen.add(prRef(x))).map(prRef);
  const title = (d.ticket_titles || {})[t] || "";
  if (!refs.length) return `${head(t, esc(title || "No reviews yet."), back)}${empty("No reviews yet", "None of this ticket's PRs has been reviewed. Review them from the PR reviews page.")}`;
  const all = await Promise.all(refs.map(pr => api("prreview", { pr }).then(x => [pr, x])));
  const parts = all.map(([pr, x]) => {
    const rec = x.record, p = rec && rec.passes[rec.passes.length - 1];
    if (!p) return "";
    const live = !p.posted, me = x.gh && x.gh.me, own = !!(rec.author && me && rec.author === me);
    const order = { blocker: 0, major: 1, minor: 2, nitpick: 3, note: 4 };
    const fs = [...p.findings].sort((a, b) => (order[a.severity] ?? 5) - (order[b.severity] ?? 5));
    const link = `<a class="mono" href="#prs/${esc(pr.replace("#", "/"))}">${esc(pr)}</a>`;
    return section(`Findings on ${pr}`, `<div class="pr-split"><div class="pr-pass-body"><p class="muted small">${esc(rec.title || "")} · by ${esc(rec.author || "")} · ${link}${rec.passes.length > 1 ? `, review ${p.n} of ${rec.passes.length}` : ""} · ${ago(p.ts)}</p>${ghPanel(x.gh)}${p.summary ? `<p>${txt(p.summary)}</p>` : ""}
      ${questionsBox(pr, p, unlocked)}
      ${fs.length ? fs.map(f => prFinding(f, pr, unlocked, live, own)).join("") : empty("Nothing found", "Nothing to comment on in this PR.")}
      ${postBar(pr, p, live, own, unlocked, x.fix_job)}</div>${talkPane(pr, p, unlocked)}</div>`, prTally(p, own));
  }).join("");
  return `${head(`${t}${title ? ": " + title : ""}`, `The newest review of each of this ticket's ${plural(refs.length, "reviewed PR")}. Each PR is posted on its own.`, back)}${parts}`;
}
/* A PR page is about its own repo: when LFG knows a checkout of it, pick that repo top left too. */
function followRepo(full) {
  const short = full.split("/")[1], hit = (state.repos || []).filter(x => x.name === short);
  if (hit.length !== 1 || hit[0].id === state.repo) return;
  state.repo = hit[0].id; localStorage.setItem("lfg.repo", state.repo);
  const sel = $("#repo"); if (sel) sel.value = state.repo;
  loadBranches();
}
/* Questions asked on GitHub: read the author's replies behind the page (GitHub is asked at most every 2 minutes), and
   redraw when one came in. */
const prReplying = new Set();
function prRepliesSoon(pr, arg, rec) {
  const asked = ((rec || {}).passes || []).flatMap(p => (p.questions || []).filter(q => q.asked && !q.answer).map(q => [p.n, q]));
  if (!asked.length || prReplying.has(pr)) return;
  prReplying.add(pr);
  api("prreplies", { pr }).then(d => {
    const now = (d && d.questions) || {};
    if (asked.some(([n, q]) => JSON.stringify(now[`${n}:${q.id}`] || []) !== JSON.stringify(q.replies || [])) && location.hash === `#prs/${arg}`) softRoute();
  }).catch(() => {}).finally(() => setTimeout(() => prReplying.delete(pr), 120e3));
}
async function prDetail(arg) {
  const m = /^([\w.-]+\/[\w.-]+)\/(\d+)$/.exec(arg);
  if (!m) return unavailable({ why: "Not a PR address." });
  const pr = `${m[1]}#${m[2]}`;
  followRepo(m[1]);
  const [d, unlocked] = await Promise.all([api("prreview", { pr, wait: "0" }), isUnlocked()]);
  if (d.available === false) return unavailable(d);
  prFillIn(pr, arg, d.pending);
  const rec = d.record, j = d.job;
  (state.prRecord || (state.prRecord = {}))[pr] = rec;
  prRepliesSoon(pr, arg, rec);
  crumbs("prs", pr);
  prTabOpen(pr, (rec && rec.title) || (d.gh && d.gh.title) || "");
  const running = j && j.status === "running";
  const fixing = d.fix_job && d.fix_job.status === "running";
  if (running || fixing) pageTimer("pr", 4000, () => { if (location.hash === `#prs/${arg}`) softRoute(); });
  const back = '<a class="back" href="#prs">← All reviews</a>';
  const kindOf = j && (j.fresh ? "review from scratch" : j.re_review ? "re-review" : "review");
  const jobBox = j && j.status === "running" ? `<div class="callout">${dot("on")}<b>${esc(kindOf[0].toUpperCase() + kindOf.slice(1))} running</b>${(j.with || []).length ? `, together with ${j.with.map(x => `<a class="mono" href="#prs/${esc(x.replace("#", "/"))}">${esc(x)}</a>`).join(", ")} in one session${j.ticket ? ` for ${esc(ticketName(j.ticket))}` : ""}` : ""}, started ${ago(j.started)}${j.method ? `, following <b>${esc(j.method)}</b>` : ""}${j.model ? ` on ${esc(modelName(j.model))}` : ""}. It shows up below as a new tab when it's done; this updates by itself.${unlocked ? ` <button class="btn small" data-pr-cancel="${esc(pr)}" title="Stop this review and its Claude session; nothing is saved">Cancel</button>` : ""}${(j.steps || []).length ? `<ul class="mono small pr-steps">${j.steps.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}${j.notes ? usedNotes(j.notes, pr, "Your notes for this review") : ""}</div>`
    : j && j.status === "cancelled" && Date.now() - Date.parse(j.ended) < 3600000 ? `<div class="callout">You cancelled the ${esc(kindOf)} started ${ago(j.started)}. Nothing from it was saved.</div>`
    : j && j.status === "failed" ? `<div class="callout bad">${jobLine(j)}${(j.steps || []).length ? `<ul class="mono small pr-steps">${j.steps.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}</div>` : "";
  const can = unlocked && !running;
  const notes = (state.reviewNotes || {})[pr] || "", notesOpen = !!notes || (state.reviewNotesOpen || {})[pr];
  const withNotes = notes.trim() ? NOTES_ON : "";
  const actions = `<div class="row wrap pr-actions">${rec ? `<button class="btn primary" data-pr-start="${esc(pr)}" ${can ? "" : "disabled"} title="Check what happened to your posted comments, review only the new commits, then look once more for anything missed" data-label="Re-review">Re-review${withNotes}</button><button class="btn" data-pr-start="${esc(pr)}" data-fresh="1" ${can ? "" : "disabled"} title="Review the whole PR again from scratch, ignoring earlier reviews" data-label="Review from scratch">Review from scratch${withNotes}</button><label class="fresh-eyes" title="Only with Review from scratch: a re-review needs the earlier reviews"><input type="checkbox" data-fresh-eyes ${state.freshEyes ? "checked" : ""} ${can ? "" : "disabled"}>Fresh eyes${info("Review from scratch without seeing earlier reviews, your Fix/Pass choices, or anything CodeRabbit, Sonar or people said. A true second opinion. Findings it repeats get a tag, and posting tells you who raised them already.")}</label>` : `<button class="btn primary" data-pr-start="${esc(pr)}" ${can ? "" : "disabled"} data-label="Review">Review${withNotes}</button>`}<button class="btn" data-pr-sessions="${esc(pr)}" ${can ? "" : "disabled"} title="Bring in a review you did in a Claude Code session">Import</button><button class="btn" data-pr-group="${esc(pr)}" ${unlocked ? "" : "disabled"} title="Put this PR in one of your session groups: every session that mentions it, review runs included, joins that group on the Sessions page">${(d.groups || []).length ? `In ${esc(d.groups.join(", "))}` : "Add to a group…"}</button><button class="btn" data-pr-notes ${can ? "" : "disabled"} aria-expanded="${notesOpen ? "true" : "false"}" title="Tell the next review what to look into on top of its method: an angle, some context, a worry">${notes ? "Notes added" : "Add notes…"}</button><span class="grow"></span>${methodPick(d, unlocked)}${modelPick(d, unlocked)}</div>
    <div class="pr-notes" ${notesOpen ? "" : "hidden"}><textarea data-grow rows="2" data-pr-notes-text="${esc(pr)}" placeholder="What should the next review look into? E.g. &quot;focus on the retry logic and whether a failed fetch can leave a run half-done&quot;. Only for the next review you start." ${can ? "" : "disabled"}>${esc(notes)}</textarea></div>${rec ? AGAIN_HELP : ""}`;
  state.prGroups = { pr, groups: d.groups || [], all: d.all_groups || [] };
  state.prDetail = { pr, linked: (d.linked || []).map(x => x.pr) };
  (state.prSessions || (state.prSessions = {}))[pr] = (d.sessions || []).filter(x => !x.dashboard && x.cwd);
  const sessRows = (d.sessions || []).map(x => `<li class="sess"><div class="grow"><div class="title">${esc(x.title)}${x.linked ? ' <span class="tag">linked by you</span>' : ""}</div><div class="meta">${ago(x.modified)} · ${esc(x.cwd || "")}${x.has_json && !x.dashboard ? " · review ready to import" : ""}</div></div><button class="btn small" data-copy="${esc(x.resume)}" title="${esc(x.resume)}">Copy resume command</button>${x.linked ? `<button class="btn small" data-pr-unlinksess='${esc(JSON.stringify([pr, x.id]))}' ${unlocked ? "" : "disabled"}>Unlink</button>` : x.dashboard || !x.path ? "" : `<button class="btn small" data-pr-importpath='${esc(JSON.stringify([pr, x.path]))}' ${unlocked ? "" : "disabled"}>Import as a review</button>`}</li>`).join("");
  const sess = section("Sessions about this PR", `${sessRows ? `<ul class="items box">${sessRows}</ul>` : (d.pending || []).includes("sessions") ? '<p class="muted small"><span class="loading-inline">Looking through your recent sessions…</span></p>' : '<p class="muted small">None found yet: no session in the last 30 days mentions this PR.</p>'}<div class="row mt"><button class="btn small" data-pr-linksess="${esc(pr)}" ${unlocked ? "" : "disabled"} title="For example the session where you built this PR">Link a session…</button></div>`, "sessions that mention it, and ones you linked; resume one to ask it about the PR");
  const linkedBox = section("Linked PRs", `${(d.linked || []).length ? `<ul class="items box">${d.linked.map(x => `<li><div class="grow"><a class="mono" href="#prs/${esc(x.pr.replace("#", "/"))}">${esc(x.pr)}</a> ${x.title ? esc(x.title) : ""} ${x.reviewed ? "" : '<span class="tag">not reviewed yet</span>'}</div><button class="btn small" data-pr-unlink='${esc(JSON.stringify([pr, x.pr]))}' ${unlocked ? "" : "disabled"}>Unlink</button></li>`).join("")}</ul>` : '<p class="muted small">None. Link the other half of this change, for example the frontend for a backend PR, from any repo.</p>'}
    <div class="row mt"><button class="btn small" data-pr-linkpr="${esc(pr)}" ${unlocked ? "" : "disabled"}>Link a PR…</button>${(d.linked || []).length ? `<button class="btn small primary" data-pr-together='${esc(JSON.stringify([pr, d.linked.map(x => x.pr)]))}' ${can ? "" : "disabled"} title="One Claude session reviews this PR and its linked ones as one change, and checks they agree with each other">${rec || d.linked.some(x => x.reviewed) ? "Re-review" : "Review"} together with linked PRs</button>${rec || d.linked.some(x => x.reviewed) ? `<button class="btn small" data-pr-together='${esc(JSON.stringify([pr, d.linked.map(x => x.pr)]))}' data-fresh="1" ${can ? "" : "disabled"} title="${FULL_TITLE}">Review together from scratch</button>` : ""}` : ""}</div>${(d.linked || []).length && (rec || d.linked.some(x => x.reviewed)) ? AGAIN_HELP : ""}`, "reviewed together, or linked by you; they can be in any repo");
  const stack = stackBox({ gh: m[1], pr: m[2] }, "strip");
  if (!rec) return `${prTabStrip()}${head(pr, `Not reviewed yet. <a href="https://github.com/${esc(m[1])}/pull/${esc(m[2])}" target="_blank" rel="noopener noreferrer">Open on GitHub ↗</a>`, back)}${ghPanel(d.gh)}${stack}${jobBox}${actions}${linkedBox}${sess}`;
  const passes = rec.passes, last = passes[passes.length - 1];
  const key = "lfg.prpass." + pr;
  let pick = Number(sessionStorage.getItem(key)) || last.n;
  if (state.prSeen && state.prSeen[pr] && state.prSeen[pr] < last.n) pick = last.n;  // a new review just landed
  (state.prSeen || (state.prSeen = {}))[pr] = last.n;
  const p = passes.find(x => x.n === pick) || last;
  const live = p === last && !p.posted;
  const byId = Object.fromEntries(passes.flatMap(x => x.findings).map(f => [f.id, f]));
  // a full review saved before LFG recorded the kind: no earlier findings followed up, and every finding is new
  const full = x => x.kind === "full" || (x.kind === "re-review" && !(x.prior || []).length && x.findings.length > 0 && x.findings.every(f => f.since === "first"));
  const label = x => `Review ${x.n}${(x.run || {}).fresh_eyes ? " · fresh eyes" : full(x) ? " · from scratch" : x.kind === "re-review" ? " · re-review" : ""}`;
  const passTabs = `<div class="tabs pr-passes" data-scroll-on>${passes.slice().reverse().map(x => `<button class="tab ${x.n === p.n ? "on" : ""}" data-pr-pass='${esc(JSON.stringify([pr, x.n]))}'>${esc(label(x))}<span class="n">${x.posted ? "posted" : ago(x.ts)}</span></button>`).join("")}</div>`;
  const own = !!(rec.author && d.gh && d.gh.me && rec.author === d.gh.me);  // GitHub takes only a comment on your own PR
  const passOf = Object.fromEntries(passes.flatMap(x => x.findings.map(f => [f.id, x.n])));
  const priorItem = (x, g) => {
    const f = byId[x.id], from = passOf[x.id], head = `<div class="row prior-head">${f && f.status === "drop" ? `<span class="tag" title="The review still sees it in the code; you decided not to act on it">${own ? "you passed on it" : "you dropped it"}</span>` : ""}<span class="grow"></span>${from && from !== p.n ? `<a href="#" class="small" data-pr-goto='${esc(JSON.stringify([pr, from, x.id]))}'>From review ${from} ↗</a>` : ""}${f ? copyBtns(earlierForPerson(x, f, pr, g.label), earlierForAgent(x, f, pr, g.label)) : ""}</div>${x.note ? `<p class="small">${txt(x.note)}</p>` : ""}`;
    return `<div class="prior-item">${head}${f ? prFinding(f, pr, unlocked, true, own) : ""}</div>`;
  };
  const priorBy = priorGroups(p.prior, byId);
  const prior = priorBy.length ? section("Earlier comments", priorBy.map(g => `<div class="prior-group" data-prior-group="${esc(g.key)}"><h3 class="prior-group-h">${dot(g.tone)}${esc(g.heading)}<span class="n">${g.items.length}</span></h3>${g.items.map(x => priorItem(x, g)).join("")}</div>`).join(""), "where each earlier finding stands now; decide, discuss or fix them here") : "";
  const order = { blocker: 0, major: 1, minor: 2, nitpick: 3, note: 4 };
  const fs = [...p.findings].sort((a, b) => (order[a.severity] ?? 5) - (order[b.severity] ?? 5));
  const together = p.together || [];
  const discard = live && unlocked ? `<button class="btn small" data-pr-discard='${esc(JSON.stringify([pr, p.n]))}' title="Throw this review away; nothing was posted">Discard this review</button>` : "";
  return `${prTabStrip()}${head(rec.title || pr, `<span class="mono">${esc(pr)}</span> by ${esc(rec.author || "")}${rec.ticket ? ` · ${esc(rec.ticket)}` : ""} · <a href="${esc(rec.url)}" target="_blank" rel="noopener noreferrer">Open on GitHub ↗</a>`, back)}
    ${ghPanel(d.gh, passes.length)}
    ${stack}
    ${jobBox}
    ${actions}
    ${passTabs}
    <div class="pr-split"><div class="pr-pass-body">
      <div class="panel">${verdictHero({ ...p, history: passes.map(x => ({ n: x.n, score: x.score, kind: x.kind })) }, together.length, d.gh)}<div class="row"><span class="muted">${ago(p.ts)} · reviewed at commit <span class="mono">${esc(p.head_sha.slice(0, 8))}</span>${d.gh && d.gh.head_sha && d.gh.head_sha !== p.head_sha ? ` · <span class="tag warn" title="Commits were pushed after this review. Is it fixed? checks a finding against the newest code; a re-review reads them all">PR is now at <span class="mono">${esc(d.gh.head_sha.slice(0, 8))}</span></span>` : ""}${p.imported_from ? " · imported from a session" : ""}${(p.run || {}).notes ? ` · <span class="tag" title="${esc(p.run.notes)}">with your notes</span>` : ""}</span><span class="grow"></span><button class="btn small" data-copy="${esc(prCopyText(rec, p))}" title="The summary, approach notes and every finding, as Markdown to paste to an agent">Copy summary and findings</button>${discard}</div>
        ${p.summary ? `<p>${txt(p.summary)}</p>` : ""}${intentLine(p)}
        ${(p.run || {}).notes ? usedNotes(p.run.notes, pr, `Your notes for review ${p.n}`) : ""}
        ${(p.approach_notes || []).length ? `<div class="k">Approach notes (not posted)</div><ul>${p.approach_notes.map(x => `<li>${txt(x)}</li>`).join("")}</ul>` : ""}
        ${p.run ? `<div class="row wrap mt">${p.run.resume ? `<button class="btn small" data-copy="${esc(p.run.resume)}" title="${esc(p.run.resume)}">Copy command to resume it in a terminal</button>` : ""}${(p.run.with || []).length ? `<span class="muted small">Reviewed together with ${p.run.with.map(x => `<a class="mono" href="#prs/${esc(x.replace("#", "/"))}">${esc(x)}</a>`).join(", ")}</span>` : ""}</div>
        ${p.run.used ? `<div class="k mt">What it used</div>${p.run.fresh_eyes ? `<div class="used"><div class="used-k">Mode${info("Fresh eyes: this review didn't see earlier reviews, your Fix/Pass choices, or anyone else's comments. Findings an earlier review raised are tagged.")}</div><div class="used-v"><span class="chip c-green">Fresh eyes</span></div></div>` : ""}${usedTags(p.run.used, p.run.method)}` : ""}
        <details class="more" data-pr-activity='${esc(JSON.stringify([pr, p.n]))}'><summary class="small">What Claude did</summary><div class="small muted"><span class="loading-inline">Loading…</span></div></details>` : ""}</div>
      ${questionsBox(pr, p, unlocked)}
      ${prior}
      ${together.length ? `<div class="callout">This review covered ${plural(together.length + 1, "PR")} in one session: <span class="mono">${esc(pr)}</span>${together.map(t => `, <a class="mono" href="#prs/${esc(t.pr.replace("#", "/"))}">${esc(t.pr)}</a>`).join("")}. Each PR has its own findings, score and post box below.</div>` : ""}
      ${section(together.length ? `Findings on ${pr}` : "Findings", (fs.length ? fs.map(f => prFinding(f, pr, unlocked, live, own)).join("") : empty("Nothing found", "This review found nothing to comment on.")) + (together.length ? postBar(pr, p, live, own, unlocked, d.fix_job) : ""), prTally(p, own))}
      ${together.length ? "" : postBar(pr, p, live, own, unlocked, d.fix_job, (p.prior || []).filter(x => !["fixed", "withdrawn"].includes(x.state)).map(x => byId[x.id]).filter(Boolean))}
      ${together.map(t => togetherSection(t, unlocked, d.gh && d.gh.me)).join("")}
    </div>${talkPane(pr, p, unlocked, byId)}</div>
    ${sess}`;
}
/* One review pass as Markdown for an agent: what the PR is, the summary, approach notes, and every finding with
   where it is, what's wrong, the fix and the comment, plus what you decided about it. */
/* Copied text: a chat message's attachments by file name, and one discussion as You / Claude turns. */
const copyMsg = q => String(q || "").replace(/\[(?:image|file): ([^\]\s]+)\]/g, (m, path) => `[attached: ${path.split("/").pop()}]`).trim();
const copyChat = chat => (chat || []).map(t => [`**You:** ${copyMsg(t.q)}`, t.a ? `**Claude:** ${String(t.a).trim()}` : "_(no answer yet)_"].join("\n\n")).join("\n\n");
/* Where a finding stands beyond kept/dropped: who raised it, your reply, the re-check, the fix. */
function findingState(x) {
  return [x.raised_by ? `Raised by: ${x.raised_by.who}${x.raised_by.url ? " (" + x.raised_by.url + ")" : ""}` : "",
    (x.echoes || []).length ? `Also raised by: ${x.echoes.map(e => `${e.who}${e.url ? " (" + e.url + ")" : ""}`).join(", ")}` : "",
    x.status === "drop" && x.dropped_by === "claude" ? "Dropped: you said it wasn't needed and Claude agreed after checking the code." : "",
    x.reply ? `Your reply:\n${x.reply}` : "",
    x.check && x.check.state ? `Re-check: ${x.check.state}${x.check.why ? ". " + x.check.why : ""}` : "",
    (x.fixed || {}).commit ? `Fixed in ${x.fixed.commit}` : ""].filter(Boolean);
}
function prCopyText(rec, p) {
  const decided = { keep: "kept", drop: "dropped", pending: "not decided yet" };
  const byId = Object.fromEntries((rec.passes || []).flatMap(x => x.findings).map(x => [x.id, x]));
  const f = p.findings.map((x, i) => [`### ${i + 1}. ${x.title || x.issue || x.id} (${x.id}, ${x.severity}, ${decided[x.status] || x.status}${x.comment_url ? ", posted" : ""})`,
    x.file ? `Where: ${x.file}${x.line ? ":" + x.line : ""}` : ABOUT[x.about] ? `Where: ${ABOUT[x.about][0].replace("About", "in")}` : "Where: the PR as a whole",
    x.issue && x.title ? `Issue: ${x.issue}` : "", x.fix ? `Fix: ${x.fix}` : "", x.detail ? `What the review checked: ${x.detail}` : "",
    ...findingState(x), x.body ? `Comment:\n${x.body}` : "", x.comment_url ? `On GitHub: ${x.comment_url}` : "",
    (x.chat || []).length ? `#### Discussion of ${x.id}\n\n${copyChat(x.chat)}` : ""].filter(Boolean).join("\n"));
  const qs = (p.questions || []).map(q => [`- **${q.ask}**`, q.why ? `  Why it matters: ${q.why}` : "",
    `  Answer: ${q.answer ? String(q.answer).trim() : "not answered yet"}`].filter(Boolean).join("\n"));
  const prior = (p.prior || []).map(x => `- ${x.id}${byId[x.id] ? ` (${byId[x.id].title || byId[x.id].issue || ""})` : ""}: ${(PRIOR[x.state] || [x.state])[0]}${x.note ? ". " + x.note : ""}`);
  return [`# Review of ${rec.repo}#${rec.number}: ${rec.title || ""}`, `${rec.url || ""}\nReview ${p.n}, at commit ${p.head_sha}${p.score != null ? `, score ${p.score}` : ""}`,
    p.summary ? `## Summary\n${p.summary}` : "",
    p.intent ? `## Against the ticket\n${p.intent.ticket ? `${p.intent.ticket}${p.intent.ticket_title ? ` (${p.intent.ticket_title})` : ""}` : "No ticket found"}: ${(DELIVERS[p.intent.delivers] || DELIVERS.unclear)[0].toLowerCase()}${p.intent.note ? `. ${p.intent.note}` : ""}` : "",
    (p.approach_notes || []).length ? `## Approach notes\n${p.approach_notes.map(x => "- " + x).join("\n")}` : "",
    (p.run || {}).notes ? `## Your notes for this review\n${p.run.notes}` : "",
    qs.length ? `## Questions (${qs.length})\n${qs.join("\n")}` : "",
    prior.length ? `## Earlier review comments (${prior.length})\n${prior.join("\n")}` : "",
    `## Findings (${p.findings.length})`, f.join("\n\n") || "None.",
    (p.chat || []).length ? `## Discussion of the whole review\n\n${copyChat(p.chat)}` : ""].filter(Boolean).join("\n\n");
}
async function prImport(pr, path, btn) {
  btn.disabled = true; btn.textContent = path === "log" ? "Saving…" : "Importing…";
  const d = await save("review_import", { pr, path });
  if (!d.ok) { btn.disabled = false; btn.textContent = "Try again"; alertMsg(btn, d); return; }
  btn.textContent = `Saved ${plural(d.findings, "finding")}`;
  setTimeout(() => { closeDrawer(); const h = `#prs/${pr.replace("#", "/")}`; if (location.hash === h) softRoute(); else location.hash = h; }, 900);
}
async function prSessions(pr) {
  openDrawer(`Import a review of ${pr}`, '<div class="skeleton"></div>');
  const d = await save("review_sessions", { pr });
  const ss = (d.ok && d.sessions) || [];
  const rows = ss.map(s => `<li><div class="grow"><div class="title">${esc(s.title)}</div><div class="meta">${ago(s.modified)} · ${esc(s.cwd || "")}${s.has_json ? " · review ready to import" : " · Claude turns the review into findings (one short call)"}</div></div><button class="btn small" data-pr-importpath='${esc(JSON.stringify([pr, s.path]))}'>Import</button></li>`).join("");
  openDrawer(`Import a review of ${pr}`, `<div class="readable"><p>Your Claude Code sessions from the last 30 days that mention this PR, newest first. Importing adds it as a new review you can keep, drop and post like any other.</p>
    ${!d.ok ? unavailable(d) : ss.length ? `<ul class="items box">${rows}</ul>` : empty("No sessions found", "None of your sessions in the last 30 days mention this PR.")}</div>`);
  $$("[data-pr-importpath]").forEach(b => b.onclick = () => { const [p, path] = JSON.parse(b.dataset.prImportpath); prImport(p, path, b); });
}
/* Link another PR to this one: pick from your open PRs and review requests in every repo, or type one. */
async function prLinkPr(pr) {
  openDrawer(`Link a PR to ${pr}`, '<div class="skeleton"></div>');
  const d = await api("prreviews", { all: "1" });
  const have = new Set([pr, ...(state.prDetail.linked || [])]);
  const opts = [...(d.mine || []), ...(d.queue || []), ...(d.reviews || [])].filter((x, i, a) => !have.has(prRef(x)) && a.findIndex(y => prRef(y) === prRef(x)) === i);
  openDrawer(`Link a PR to ${pr}`, `<div class="readable"><p>Linked PRs show on each other's page, whichever repo is picked top left, and can be reviewed together in one session that also checks they agree with each other.</p>
    <div class="row"><input type="text" id="lk-pr" class="grow mono" placeholder="owner/repo#123 or a PR URL"><button class="btn primary" id="lk-go">Link</button></div><span class="save-msg" id="lk-msg"></span>
    ${opts.length ? `<div class="k">Your open PRs, review requests and reviews, in every repo</div><ul class="items box">${opts.map(x => `<li><div class="grow">${esc(x.title || "")}<div class="meta mono">${esc(prRef(x))}</div></div><button class="btn small" data-lk="${esc(prRef(x))}">Link</button></li>`).join("")}</ul>` : ""}</div>`);
  const go = async other => {
    const r = await save("review_link", { pr, other });
    saidMsg($("#lk-msg"), r, `Linked ${other}.`);
    if (r.ok) setTimeout(() => { closeDrawer(); softRoute(); }, 600);
  };
  $("#lk-go").onclick = () => go($("#lk-pr").value.trim());
  $("#lk-pr").onkeydown = e => { if (e.key === "Enter") go($("#lk-pr").value.trim()); };
  $$("[data-lk]").forEach(b => b.onclick = () => go(b.dataset.lk));
}
/* Link one of your sessions to this PR by hand, e.g. the one where you built it. */
async function prLinkSession(pr) {
  openDrawer(`Link a session to ${pr}`, '<div class="skeleton"></div>');
  const d = await api("sessions", scopeArgs("sessions"));
  const ss = (d.sessions || []).slice(0, 60);
  openDrawer(`Link a session to ${pr}`, `<div class="readable"><p>It shows under "Sessions about this PR" with its resume command. To link a whole group of sessions, use <b>Add to a group…</b> above instead. ${allRepos("sessions") ? "" : `Showing sessions in ${esc(repoName())}.`}</p>
    <input type="search" id="lk-find" class="wide" placeholder="Search names, branches…">
    <ul class="items box" id="lk-list">${ss.map(s => `<li data-q="${esc((s.name + " " + (s.branch || "") + " " + (s.repo || "")).toLowerCase())}"><div class="grow"><div class="title">${esc(s.name)}</div><div class="meta">${ago(s.modified)}${s.branch ? ` · <span class="mono">${esc(s.branch)}</span>` : ""}</div></div><button class="btn small" data-lks="${esc(s.id)}">Link</button></li>`).join("") || "<li>No sessions.</li>"}</ul><span class="save-msg" id="lk-msg"></span></div>`);
  $("#lk-find").oninput = e => { const q = e.target.value.toLowerCase(); $$("#lk-list li[data-q]").forEach(li => (li.style.display = li.dataset.q.includes(q) ? "" : "none")); };
  $$("[data-lks]").forEach(b => b.onclick = async () => {
    const r = await save("review_link_session", { pr, id: b.dataset.lks });
    saidMsg($("#lk-msg"), r, "Linked.");
    if (r.ok) setTimeout(() => { closeDrawer(); softRoute(); }, 600);
  });
}
function prGroup() {
  const G = state.prGroups, others = G.all.filter(g => !G.groups.includes(g));
  openDrawer(`Group ${G.pr} with its sessions`, `<div class="readable">
    <p>A group follows this PR: every session that mentions it joins the group on the Sessions page, including the review runs started here, alongside any sessions you put there yourself. Take one out with its ✕ and it stays out.</p>
    ${G.groups.length ? `<div class="k">Following it</div><div class="row wrap">${G.groups.map(g => `<span class="tag">${esc(g)} <a href="#" data-grp-off="${esc(g)}" title="Stop following this PR">✕</a></span>`).join("")}</div>` : ""}
    ${others.length ? `<div class="k">Your groups</div><div class="row wrap">${others.map(g => `<button class="btn small" data-grp-on="${esc(g)}">${esc(g)}</button>`).join("")}</div>` : ""}
    <div class="k">New group</div>
    <div class="row"><input type="text" id="grp-new" class="grow" placeholder="e.g. ATO-4282 Terraform" maxlength="80"><button class="btn primary" id="grp-make">Create and add</button></div>
    <span class="save-msg" id="grp-msg"></span></div>`);
  const go = async (group, on) => {
    const r = await save("group_pr", { group, pr: G.pr, on });
    saidMsg($("#grp-msg"), r, on ? `Added to ${group}. Its sessions show there on the Sessions page.` : `No longer in ${group}.`);
    if (r.ok) setTimeout(() => { closeDrawer(); softRoute(); }, 900);
  };
  $$("[data-grp-on]").forEach(b => b.onclick = () => go(b.dataset.grpOn, true));
  $$("[data-grp-off]").forEach(a => a.onclick = ev => { ev.preventDefault(); go(a.dataset.grpOff, false); });
  const make = () => { const v = $("#grp-new").value.trim(); if (v.length < 2) { $("#grp-msg").textContent = "Give the group a name of at least 2 characters."; return; } go(v, true); };
  $("#grp-make").onclick = make;
  $("#grp-new").onkeydown = ev => { if (ev.key === "Enter") make(); };
}
/* The chat panel: send (Enter), switch what it's about, resize or hide it. A message shows at once with Claude
   "typing" under it, and survives the page refreshing while Claude answers. */
function wireChat(root) {
  $$("textarea[data-grow]", root).forEach(grow);
  $$("[data-chat-mode]", root).forEach(b => b.onclick = () => chatSetMode(b.dataset.chatMode));
  $$(".msg-tag", root).forEach(a => a.onclick = e => {  // your answer in the chat: show the question it answers
    e.preventDefault();
    const el = a.dataset.gotoQ ? $(`#q-${CSS.escape(a.dataset.gotoQ)}`) : $$(".pr-question").find(q => q.dataset.ask === a.title);
    if (!el) return;
    el.scrollIntoView({ block: "center", behavior: "smooth" });
    el.classList.add("flash"); setTimeout(() => el.classList.remove("flash"), 1600);
  });
  $$("[data-chat-goto]", root).forEach(a => a.onclick = e => {
    e.preventDefault();
    const [, id] = JSON.parse(a.dataset.chatGoto), el = $(`#f-${CSS.escape(id)}`);
    if (!el) return;
    el.scrollIntoView({ block: "center", behavior: "smooth" });
    el.classList.add("flash"); setTimeout(() => el.classList.remove("flash"), 1600);
  });
  wireChatPane(root);
}
/* Point the chat at a finding (or back at the whole review) and show it now, from what the page last drew; the
   page refreshes behind it. */
function chatRedraw(pr) {
  const t = state.lastTalk, old = $(".pr-talk");
  if (!t || t.pr !== pr || !old) return softRoute();
  const box = document.createElement("div");
  box.innerHTML = talkPane(t.pr, t.p, t.unlocked, t.byId);
  const fab = $(".chat-fab");
  if (fab) fab.replaceWith(box.firstElementChild);
  old.replaceWith(box.querySelector(".pr-talk"));
  wireChat(document);
  $("[data-pr-chat]")?.focus();
  softRoute();
}
/* Who the chat can talk to: the review's own session, sessions about this PR, then your Studio sessions and your
   terminal and desktop ones. Fetched once a minute; the page shows the select straight away from what it has. */
async function rvSessions(pr) {
  const c = state.rvList;
  if (c && Date.now() - c.at < 60000) return c.list;
  const d = await api("studio").catch(() => ({ sessions: [] }));
  state.rvList = { at: Date.now(), list: (d.sessions || []).filter(x => x.id) };
  return state.rvList.list;
}
function rvOptions(pr, to, own, list) {
  const about = (state.prSessions || {})[pr] || [], seen = new Set([own]);
  const opt = (id, label) => { seen.add(id); return `<option value="${esc(id)}" ${to === id ? "selected" : ""}>${esc(label.slice(0, 48))}</option>`; };
  const aboutRows = about.filter(x => !seen.has(x.id)).map(x => opt(x.id, x.title));
  const mine = list.filter(x => !seen.has(x.id) && x.source === "lfg").slice(0, 15).map(x => opt(x.id, x.title));
  const other = list.filter(x => !seen.has(x.id) && x.source !== "lfg").slice(0, 15).map(x => opt(x.id, `${x.title} (${x.source === "terminal" ? "terminal" : "other"}, copied)`));
  const group = (name, rows) => rows.length ? `<optgroup label="${name}">${rows.join("")}</optgroup>` : "";
  return `<option value="" ${!to || to === own ? "selected" : ""}>${own ? "The review's session" : "A new chat"}</option>${group("About this PR", aboutRows)}${group("Your Studio sessions", mine)}${group("Terminal and other sessions", other)}`;
}
/* The chat on a review's page is Studio's chat, bound to the review: the session's own conversation (replies, tool
   steps, permission prompts, queued messages, context) with Whole review / one finding on top, and what each reply
   changed as chips. Messages go to the server wrapped with the review; the reply streams back. */
function wireChatPane(root) {
  $$("[data-chat-to]", root).forEach(sel => sel.onchange = () => { (state.chatTo || (state.chatTo = {}))[sel.dataset.chatTo] = sel.value; chatRedraw(sel.dataset.chatTo); });
  $$("[data-chat-about]", root).forEach(b => b.onclick = e => {
    e.preventDefault();
    const [pr, id] = JSON.parse(b.dataset.chatAbout);
    (state.chatAbout || (state.chatAbout = {}))[pr] = id;
    chatRedraw(pr);
  });
  clearTimeout(state.rvTimer);
  const pane = $(".pr-talk", root);
  if (!pane) return;
  const [pr, n, fid] = JSON.parse(pane.dataset.chat), conv = $(".rv-conv", pane), input = $("[data-pr-chat]", pane), b = $("[data-pr-chatgo]", pane);
  const rv = (state.rv || (state.rv = {}))[pr] || (state.rv[pr] = {}), to = () => (state.chatTo || {})[pr] || "";
  const hint = conv.dataset.hint, sel = $("[data-chat-to]", pane), ctxBox = $(".rv-ctx", pane), open = $(".rv-open", pane), first = !conv._drawn;
  const A = ssAttach({ comp: $("#rv-comp", pane), ta: input, box: $("#rv-att", pane), file: $("[data-rv-file]", pane), btn: $("[data-rv-attach]", pane), say: m => prefToast(m, true) });
  const fill = () => morph(sel, rvOptions(pr, to(), rv.own, state.rvList ? state.rvList.list : []));
  fill();
  rvSessions(pr).then(() => { if (document.body.contains(sel)) fill(); });
  const atBottom = () => conv.scrollTop + conv.clientHeight >= conv.scrollHeight - 120;
  const wired = () => {
    const d = rv.d;
    const wire = ssConvWirer({ conv, S: { id: d.id }, d, go: ssGo, refresh: () => poll(), follow: () => {}, rewound: () => {}, goto: id => {
      const el = $(`#f-${CSS.escape(id)}`); if (!el) return;
      el.scrollIntoView({ block: "center", behavior: "smooth" }); el.classList.add("flash"); setTimeout(() => el.classList.remove("flash"), 1600);
    } });
    wire();
  };
  // The conversation is this element's own (data-fill), kept across the page's redraws: what it last drew and whether
  // it drew at all live on the element itself, never in attributes a redraw of the page would take away.
  const draw = () => {
    const d = rv.d, stick = !conv._drawn || atBottom();  // the first draw starts at the end; after that only if you were there
    conv._drawn = true;
    const html = d ? `${d.earlier ? `<p class="muted small chat-more">${plural(d.earlier, "earlier message")} not shown. <a href="#studio/${esc(d.id)}">Open the whole session in Studio</a></p>` : ""}${(d.items || []).length || ssLive(d.state) || (d.queued || []).length ? "" : `<div class="chat-empty">${esc(hint)}</div>`}${ssConv(d, true)}`
      : `${rv.history ? `<details class="chat-hist" open><summary>Earlier in <b>${esc(rv.history.title)}</b></summary>${rv.history.html}</details>` : ""}<div class="chat-empty">${esc(hint)}</div>`;
    if (html !== conv._html) { morph(conv, html); conv._html = html; }  // only what changed; nothing at all when nothing did
    if (d) wired();
    if (stick) conv.scrollTop = conv.scrollHeight;
    b.textContent = rvBusy(d) ? "Queue" : "Send";
    if (open) { open.hidden = !d; if (d) open.href = `#studio/${d.id}`; }
    if (ctxBox) morph(ctxBox, d && ssLive(d.state) ? ssCtxHtml((state.ssCtx || {})[d.id]) : "");
  };
  const loadCtx = async () => {  // how full the session's context is, once Claude is idle
    const d = rv.d;
    if (!d || !ssLive(d.state) || d.state === "working") return;
    const c = await api("studio_context", { id: d.id }).catch(() => null);
    if (c && c.percent != null) { (state.ssCtx = state.ssCtx || {})[d.id] = c; if (ctxBox && document.body.contains(ctxBox)) morph(ctxBox, ssCtxHtml(c)); }
  };
  const BUSY = ["working", "starting", "needs-you"];
  async function poll() {
    clearTimeout(state.rvTimer);
    if (!document.body.contains(conv) || !rv.sid) return;
    const nd = await api("studio_session", { id: rv.sid, limit: 40 }).catch(() => null);
    if (!nd || nd.available === false || !document.body.contains(conv)) return;
    const was = rv.d, sig = d => JSON.stringify([d.items.length, d.state, (d.pending || []).length, (d.queued || []).length, d.error, (d.items[d.items.length - 1] || {}).result != null, d.items.map(x => x.changed ? 1 : 0).join("")]);
    const changed = !was || was.id !== nd.id || sig(was) !== sig(nd);
    rv.d = nd;
    if (changed) draw();
    if (was && BUSY.includes(was.state) && nd.state === "idle") { loadCtx(); return softRoute(); }  // the review may have changed: the page catches up
    if (ssLive(nd.state)) state.rvTimer = setTimeout(poll, nd.state === "idle" ? 4000 : 1200);
  }
  // where the chat is pointed: the session whose conversation shows (a terminal session shows its copy once there is one)
  (async () => {
    const t = await api("review_chat", { pr, pass: n, session: to() }).catch(e => ({ available: false, why: e.message }));
    if (!document.body.contains(conv)) return;
    if (t.available === false) { morph(conv, `<p class="muted small">${fmtWhy(t.why)}</p>`); conv._html = null; return; }
    rv.own = t.own; fill();
    if (rv.sid !== t.session) { rv.sid = t.session; rv.d = null; rv.history = null; }
    if (rv.d) draw();  // what the last visit saw, until the fresh copy arrives
    if (!t.session && t.to) {  // a terminal session not copied yet: its recent talk, read only
      const h = await api("chatsession", { id: t.to, limit: 20 }).catch(e => ({ available: false, why: e.message }));
      if (h.available !== false) {
        const sess = (state.rvList ? state.rvList.list : []).find(x => x.id === t.to);
        rv.history = { title: ((sess && sess.title) || "the session").slice(0, 60), html: `${h.more ? `<p class="muted small">${plural(h.more, "earlier exchange")} not shown.</p>` : ""}${h.turns.map(x => `<div class="msg you"><div class="bubble">${txt(x.q.slice(0, 4000))}</div></div>${x.a ? `<div class="msg claude"><div class="bubble md">${md(x.a.slice(0, 12000))}</div></div>` : ""}`).join("") || '<p class="muted small">Nothing said in it yet.</p>'}` };
      }
    }
    if (t.session) await poll(); else draw();
    if (first) conv.scrollTop = conv.scrollHeight;  // opening the chat starts at its end; a redraw of the page leaves it where you are
    loadCtx();
  })();
  const go = async () => {
    const said = input.value.trim(), files = A.attached();
    if (!said && !files.length) return input.focus();
    if (A.busy()) return prefToast("Wait for the files to finish adding", true);
    input.value = ""; grow(input); A.clear();
    b.disabled = true;
    const r = await save("review_chat_say", { repo: state.repo, pr, pass: n, finding: fid, session: to(), text: said, attachments: files });
    b.disabled = false;
    if (!r.ok) { input.value = said; grow(input); return prefToast(r.error || r.why || "Couldn't send that", true); }
    rv.sid = r.session; rv.history = null;
    conv.querySelector(".chat-empty")?.remove();
    poll(); setTimeout(poll, 500);
  };
  b.onclick = go;
  input.onkeydown = e => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); go(); } };
  if (pane.classList.contains("wide")) document.onkeydown = e => { if (e.key === "Escape" && $(".pr-talk.wide")) { localStorage.setItem("lfg.chat", "side"); softRoute(); } };
}
/* An attachment from a review chat, opened in the page: an image or PDF as itself, a CSV as a table, text as text. */
async function openChatFile(path) {
  const name = path.split("/").pop();
  openDrawer(name, '<div class="loading-inline">Opening…</div>');
  const d = await api("chatfile", { path }).catch(e => ({ available: false, why: e.message }));
  const body = d.available === false ? `<p class="muted">${fmtWhy(d.why)}</p>`
    : d.kind === "image" ? `<img class="chat-file-img" src="${d.src}" alt="${esc(d.name)}">`
    : d.kind === "pdf" ? `<iframe class="chat-file-pdf" src="${d.src}" title="${esc(d.name)}"></iframe>`
    : d.kind === "table" ? `<div class="chat-file-tbl"><table>${d.rows.map((r, i) => `<tr>${r.map(c => i ? `<td>${esc(c)}</td>` : `<th>${esc(c)}</th>`).join("")}</tr>`).join("")}</table></div>${d.more ? `<p class="muted small">${plural(d.more, "more row")} not shown.</p>` : ""}`
    : d.kind === "text" ? `${/\.(md|markdown)$/i.test(d.name) ? `<div class="md readable">${md(d.text)}</div>` : `<pre class="chat-file-txt">${esc(d.text)}</pre>`}${d.cut ? '<p class="muted small">Only the start of the file is shown.</p>' : ""}`
    : `<p class="muted">${esc(d.name)} isn't text or an image (${n(d.size)} bytes), so it can't be shown here. Claude reads it as it is.</p>`;
  if ($("#drawer-title").textContent === name) $("#drawer-body").innerHTML = body;
}
/* A file dropped anywhere but the chat would open in place of the dashboard: ignore it. */
["dragover", "drop"].forEach(t => document.addEventListener(t, e => { if ([...(e.dataTransfer || {}).types || []].includes("Files") && !e.defaultPrevented) { e.preventDefault(); e.dataTransfer.dropEffect = "none"; } }));
/* Side, wide or hidden, at once: only classes change, nothing is fetched again. */
function chatSetMode(mode) {
  localStorage.setItem("lfg.chat", mode);
  const pane = $(".pr-talk"), fab = $(".chat-fab");
  if (!pane) return;
  pane.classList.remove("side", "wide", "hidden");
  pane.classList.add(mode);
  pane.hidden = mode === "hidden";
  if (fab) fab.hidden = mode !== "hidden";
  const wide = $('.pr-talk-h [data-chat-mode="wide"], .pr-talk-h [data-chat-mode="side"]', pane);
  if (wide) {
    wide.dataset.chatMode = mode === "wide" ? "side" : "wide";
    wide.title = mode === "wide" ? "Back to the side" : "Make it bigger";
    $("path", wide).setAttribute("d", mode === "wide" ? "M4 14h6v6M20 10h-6V4M14 10l7-7M3 21l7-7" : "M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7");
  }
  if (mode !== "hidden") { const t = $(".pr-thread", pane); if (t) t.scrollTop = t.scrollHeight; $("[data-pr-chat]", pane)?.focus(); }
  if (mode === "wide") document.onkeydown = e => { if (e.key === "Escape" && $(".pr-talk.wide")) chatSetMode("side"); };
}
/* A text box that grows with what you type, up to a limit, then scrolls. */
function grow(t) {
  const fit = () => { t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight + 2, Math.round(innerHeight * .4)) + "px"; };
  if (once(t, "grow")) t.addEventListener("input", fit);
  fit();
}
function wirePrs(root) {
  $$(".pr-steps", root).forEach(el => (el.scrollTop = el.scrollHeight));  // newest step in view
  $$("[data-prs-done]", root).forEach(c => c.onchange = () => { localStorage.setItem("lfg.prs.done", c.checked ? "1" : "0"); softRoute(); });
  $$("[data-pr-group]", root).forEach(b => b.onclick = prGroup);
  $$("[data-review-model]", root).forEach(s => s.onchange = async () => {
    const r = await save("review_model", { model: s.value });
    if (!r.ok) return alertMsg(s, r);
    prefToast(`Reviews now run on ${s.selectedOptions[0].textContent}.`);
  });
  wireMethodPick(root);
  $$("[data-pr-notes]", root).forEach(b => b.onclick = () => {
    const box = b.closest(".pr-actions").nextElementSibling, t = $("textarea", box), pr = t.dataset.prNotesText;
    box.hidden = !box.hidden;
    b.setAttribute("aria-expanded", String(!box.hidden));
    (state.reviewNotesOpen || (state.reviewNotesOpen = {}))[pr] = !box.hidden;
    if (!box.hidden) t.focus();
  });
  $$("[data-pr-notes-text]", root).forEach(t => t.oninput = () => {
    (state.reviewNotes || (state.reviewNotes = {}))[t.dataset.prNotesText] = t.value;
    const b = $("[data-pr-notes]", root);
    if (b) b.textContent = t.value.trim() ? "Notes added" : "Add notes…";
    $$("[data-pr-start][data-label]", root).forEach(x => { if (!x.disabled) x.innerHTML = esc(x.dataset.label) + (t.value.trim() ? NOTES_ON : ""); });
  });
  $$("[data-pr-notes-again]", root).forEach(b => b.onclick = () => {
    const pr = b.dataset.prNotesAgain;
    (state.reviewNotes || (state.reviewNotes = {}))[pr] = b.dataset.text;
    (state.reviewNotesOpen || (state.reviewNotesOpen = {}))[pr] = true;
    const t = $(`[data-pr-notes-text="${CSS.escape(pr)}"]`, root);
    if (!t) return softRoute();
    t.value = b.dataset.text; t.closest(".pr-notes").hidden = false; t.dispatchEvent(new Event("input")); grow(t);
    t.scrollIntoView({ block: "center", behavior: "smooth" }); t.focus();
  });
  /* on the page, not each box: sorting a table redraws its rows */
  root.onchange = e => { const c = e.target.closest && e.target.closest("[data-pr-pick]"); if (!c) return; c.checked ? state.prPick.add(c.dataset.prPick) : state.prPick.delete(c.dataset.prPick); $$(`[data-pr-pick="${CSS.escape(c.dataset.prPick)}"]`).forEach(x => (x.checked = c.checked)); pickBar(); };
  $$("[data-ticket-run]", root).forEach(b => b.onclick = async () => {
    const [t, refs] = JSON.parse(b.dataset.ticketRun);
    b.disabled = true; b.textContent = "Starting…";
    const r = await save("review_run", { pr: refs[0], with: refs.slice(1), ticket: t, fresh: b.dataset.fresh === "1", fresh_eyes: b.dataset.fresh === "1" && !!state.freshEyes, sources: methodSel(state.prMethodData) });
    if (!r.ok) { b.disabled = false; b.textContent = "Try again"; return alertMsg(b, r); }
    setTimeout(softRoute, 1000);
  });
  $$("[data-ticket-find]", root).forEach(b => b.onclick = () => ticketFind(b.dataset.ticketFind));
  const tk = $("#tk-id", root);
  if (tk) { $("#tk-go", root).onclick = () => ticketFind(tk.value); tk.onkeydown = e => { if (e.key === "Enter") ticketFind(tk.value); }; }
  pickBar();
  $$("[data-pr-together]", root).forEach(b => b.onclick = async () => {
    const [pr, others] = JSON.parse(b.dataset.prTogether);
    b.disabled = true; b.textContent = "Starting…";
    const r = await save("review_run", { pr, with: others, fresh: b.dataset.fresh === "1", fresh_eyes: b.dataset.fresh === "1" && !!state.freshEyes, sources: methodSel(state.prMethodData) });
    if (!r.ok) { b.disabled = false; b.textContent = "Try again"; return alertMsg(b, r); }
    setTimeout(softRoute, 1000);
  });
  $$("[data-pr-unlink]", root).forEach(b => b.onclick = async () => { const [pr, other] = JSON.parse(b.dataset.prUnlink); const r = await save("review_link", { pr, other, on: false }); if (!r.ok) return alertMsg(b, r); softRoute(); });
  $$("[data-pr-unlinksess]", root).forEach(b => b.onclick = async () => { const [pr, id] = JSON.parse(b.dataset.prUnlinksess); const r = await save("review_link_session", { pr, id, on: false }); if (!r.ok) return alertMsg(b, r); softRoute(); });
  $$("[data-pr-linkpr]", root).forEach(b => b.onclick = () => prLinkPr(b.dataset.prLinkpr));
  $$("[data-pr-linksess]", root).forEach(b => b.onclick = () => prLinkSession(b.dataset.prLinksess));
  wireChat(root);
  $$("[data-pr-answergo]", root).forEach(b => {
    const [pr, n, id] = JSON.parse(b.dataset.prAnswergo), input = $("[data-pr-answer]", b.closest(".pr-question"));
    const go = async () => {
      const text = input.value.trim();
      if (!text) return input.focus();
      b.disabled = true; b.textContent = "Sending…";
      // your answer goes to the review's own session in the chat; Claude's reply streams in there
      const d = await save("review_answer", { repo: state.repo, pr, pass: n, id, answer: text });
      if (!d.ok) { b.disabled = false; b.textContent = "Answer"; return prefToast(d.error || d.why || "Couldn't send the answer", true); }
      (state.chatAbout || (state.chatAbout = {}))[pr] = ""; (state.chatTo || (state.chatTo = {}))[pr] = "";
      if (chatMode() === "hidden") localStorage.setItem("lfg.chat", "side");
      chatRedraw(pr);
    };
    b.onclick = go;
    input.onkeydown = e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); go(); } };
  });
  $$("[data-pr-ghask]", root).forEach(b => b.onclick = async () => {
    const [pr, n, id] = JSON.parse(b.dataset.prGhask), input = $("[data-pr-ghasktext]", b.closest(".pr-ask-gh"));
    const text = input.value.trim();
    if (!text) return input.focus();
    b.disabled = true; b.textContent = "Posting…";
    const d = await save("review_ask", { pr, pass: n, id, text });
    if (!d.ok) { b.disabled = false; b.textContent = "Post on GitHub"; return prefToast(d.error || d.why || "Couldn't post the question", true); }
    prefToast("Asked on GitHub");
    softRoute();
  });
  $$("[data-pr-usereply]", root).forEach(b => b.onclick = async () => {
    const [pr, n, id] = JSON.parse(b.dataset.prUsereply), rec = (state.prRecord || {})[pr];
    const q = rec && (rec.passes.find(x => x.n === n) || {}).questions.find(x => x.id === id);
    if (!q || !(q.replies || []).length) return;
    const text = `The author replied on GitHub:\n\n${q.replies.map(r => `${r.by}: ${r.body}`).join("\n\n")}`;
    b.disabled = true; b.textContent = "Sending…";
    const d = await save("review_answer", { repo: state.repo, pr, pass: n, id, answer: text });
    if (!d.ok) { b.disabled = false; b.textContent = "Use their reply as the answer"; return prefToast(d.error || d.why || "Couldn't send it", true); }
    (state.chatAbout || (state.chatAbout = {}))[pr] = ""; (state.chatTo || (state.chatTo = {}))[pr] = "";
    if (chatMode() === "hidden") localStorage.setItem("lfg.chat", "side");
    chatRedraw(pr);
    softRoute();
  });
  $$("[data-pr-remember]", root).forEach(b => b.onclick = async () => {
    const [pr, n, id, to] = JSON.parse(b.dataset.prRemember);
    b.disabled = true; b.textContent = "Saving…";
    const d = await save("review_remember", { pr, pass: n, id, to });
    if (!d.ok) { b.disabled = false; b.textContent = "Try again"; return alertMsg(b, d); }
    softRoute();
  });
  $$("[data-pr-savefinding]", root).forEach(b => b.onclick = async () => {
    const [pr, id, to] = JSON.parse(b.dataset.prSavefinding);
    b.disabled = true; const label = b.textContent; b.textContent = "Saving…";
    const d = await save("review_remember_finding", { pr, id, to });
    if (!d.ok) { b.disabled = false; b.textContent = label; return saidMsg($(".save-msg", b.closest(".chat-save")), d); }
    softRoute();
  });
  $$("[data-pr-reply]", root).forEach(b => b.onclick = async () => {
    const [pr, id] = JSON.parse(b.dataset.prReply), box = b.closest(".pr-reply");
    b.disabled = true; b.textContent = "Posting…";
    const d = await save("review_reply", { pr, id, body: $("[data-pr-replytext]", box).value });
    if (!d.ok) { b.disabled = false; b.textContent = "Post reply on GitHub"; return saidMsg($(".save-msg", box), d); }
    softRoute();
  });
  $$("[data-pr-activity]", root).forEach(det => det.ontoggle = async () => {
    if (!det.open || det.dataset.loaded) return;
    det.dataset.loaded = "1";
    const [pr, n] = JSON.parse(det.dataset.prActivity), box = det.querySelector("div"), key = det.dataset.prActivity;
    const cache = state.activity || (state.activity = {});
    const d = cache[key] || await api("prreviewlog", { pr, n });
    cache[key] = d;  // a saved review's log never changes
    const steps = d.steps || [];
    box.className = "pr-activity small";
    box.innerHTML = steps.length ? `<ol>${steps.map(x => x.kind === "said" ? `<li class="said">${txt(x.text)}</li>` : `<li><span class="tag">${esc(x.tool)}</span> <span class="mono">${esc(x.text)}</span></li>`).join("")}</ol>` : '<p class="muted">Its log is gone, so there is nothing to show.</p>';
  });
  $$("[data-copy]", root).forEach(b => b.onclick = async () => {
    const was = b.textContent;
    try { await navigator.clipboard.writeText(b.dataset.copy); b.textContent = "Copied"; } catch (e) { window.prompt("Copy this:", b.dataset.copy); }
    setTimeout(() => (b.textContent = was), 1500);
  });
  $$("[data-pr-start]", root).forEach(b => b.onclick = e => { e.stopPropagation(); prStart(b.dataset.prStart, b); });
  /* Fresh eyes goes with Review from scratch only: a re-review is built on the earlier reviews it would hide */
  const reOnly = () => $$("[data-pr-start]:not([data-fresh])", root);
  const freshEyes = on => reOnly().forEach(b => {
    if (on) { b.dataset.wasDisabled = b.disabled ? "1" : ""; b.disabled = true; b.title = "Fresh eyes is on: a re-review needs the earlier reviews it hides. Use Review from scratch, or untick Fresh eyes."; }
    else if (b.dataset.wasDisabled !== undefined) { b.disabled = b.dataset.wasDisabled === "1"; delete b.dataset.wasDisabled; }
  });
  $$("[data-fresh-eyes]", root).forEach(c => { if (c.checked) freshEyes(true); c.onchange = () => { state.freshEyes = c.checked; freshEyes(c.checked); }; });
  $$("[data-pr-cancel]", root).forEach(b => b.onclick = async () => {
    b.style.minWidth = b.offsetWidth + "px";
    b.disabled = true; b.textContent = "Cancelling…";
    const d = await save("review_cancel", { pr: b.dataset.prCancel });
    if (!d.ok) { b.disabled = false; b.textContent = "Try again"; b.title = d.why || ""; return; }
    softRoute();
  });
  $$("[data-pr-sessions]", root).forEach(b => b.onclick = e => { e.stopPropagation(); prSessions(b.dataset.prSessions); });
  $$("[data-pr-import]", root).forEach(b => b.onclick = e => { e.stopPropagation(); const [pr, path] = JSON.parse(b.dataset.prImport); prImport(pr, path, b); });
  $$("[data-pr-mark]", root).forEach(b => b.onclick = async () => {
    const [pr, id, status] = JSON.parse(b.dataset.prMark);
    if (b.classList.contains("primary")) return;  // already this status: nothing to save
    b.disabled = true;
    const card = b.closest(".pr-finding"), title = ($(".title", card) || {}).textContent || id, own = ownCard(card);
    const d = await save("review_mark", { pr, ids: [id], status });
    if (!d.ok) { b.disabled = false; b.title = d.why || ""; alertMsg(b, d); return; }
    if (status === "drop") offerPass(pr, id, title, own);  // how far "don't flag this again" reaches
    softRoute();
  });
  $$("[data-pr-passoffer]", root).forEach(b => b.onclick = () => {
    const [pr, id] = JSON.parse(b.dataset.prPassoffer), card = b.closest(".pr-finding") || $(`#f-${CSS.escape(id)}`);
    offerPass(pr, id, ($(".title", card) || {}).textContent || id, ownCard(card));
  });
  $$("[data-pass-rm]", root).forEach(b => b.onclick = async () => {
    b.disabled = true;
    const d = await save("review_unpass", { id: b.dataset.passRm });
    if (!d.ok) { b.disabled = false; return alertMsg(b, d); }
    softRoute();
  });
  // finding ids repeat across PRs on one page (1.1 on each), so look inside the finding's own card
  $$("[data-pr-snip]", root).forEach(async el => {
    const [pr, id] = JSON.parse(el.dataset.prSnip), cache = state.snips || (state.snips = {});
    if (cache[el.dataset.prSnip] !== undefined) return;  // drawn with the page: the code, or that GitHub didn't give it
    const d = await api("prsnippet", { pr, id }).catch(() => ({}));
    cache[el.dataset.prSnip] = d.snippet || false;  // false: not asked again until you refresh, so redraws don't flip it back to Loading
    setTimeout(() => { if (state.pin && Date.now() < state.pin.until) state.pin.keep(); }, 0);
    if (d.snippet) morph(el, snipHtml(d.snippet));
    else $(".pad", el).textContent = "Couldn't get this code from GitHub.";
  });
  $$("[data-pr-goto]", root).forEach(a => a.onclick = e => {
    e.preventDefault();
    const [pr, n, id] = JSON.parse(a.dataset.prGoto);
    sessionStorage.setItem("lfg.prpass." + pr, n);
    state.goto = "#f-" + CSS.escape(id);
    softRoute();
  });
  $$("[data-pr-qsession]", root).forEach(b => b.onclick = () => {
    const [pr, qid] = JSON.parse(b.dataset.prQsession), box = b.closest(".pr-question"), q = box.dataset.ask;
    const list = (state.prSessions || {})[pr] || [];
    openDrawer("Ask a session", `<div class="readable"><p>Pick the session to ask, such as the one where you built this PR. Your question goes into the chat and the answer streams back there. A session that isn't one of your Studio sessions is copied first, so the original doesn't change.</p><div class="box pad small">${txt(q)}</div>
      <ul class="items box mt">${list.map(x => `<li><div class="grow"><div class="title">${esc(x.title)}</div><div class="meta">${ago(x.modified)} · ${esc(x.cwd)}${x.linked ? " · linked by you" : ""}</div></div><button class="btn small primary" data-ask-sess="${esc(x.id)}">Ask</button></li>`).join("")}</ul><span class="save-msg" id="ask-sess-msg"></span></div>`);
    $$("[data-ask-sess]").forEach(go => go.onclick = async () => {
      $$("[data-ask-sess]").forEach(x => { x.disabled = true; });
      go.textContent = "Asking…";
      const n = (state.lastTalk || {}).p ? state.lastTalk.p.n : 0;
      const d = await save("review_chat_say", { repo: state.repo, pr, pass: n, session: go.dataset.askSess, text: q });
      if (!d.ok) { $$("[data-ask-sess]").forEach(x => { x.disabled = false; }); go.textContent = "Ask"; return saidMsg($("#ask-sess-msg"), d); }
      closeDrawer();
      (state.chatAbout || (state.chatAbout = {}))[pr] = ""; (state.chatTo || (state.chatTo = {}))[pr] = go.dataset.askSess;
      if (chatMode() === "hidden") localStorage.setItem("lfg.chat", "side");
      chatRedraw(pr);
    });
  });
  $$("[data-pr-discuss]", root).forEach(b => b.onclick = () => {
    const [pr, id] = JSON.parse(b.dataset.prDiscuss);
    (state.chatAbout || (state.chatAbout = {}))[pr] = id;
    if (chatMode() === "hidden") localStorage.setItem("lfg.chat", "side");  // a Discuss opens the chat
    chatRedraw(pr);
  });
  $$("[data-pr-check]", root).forEach(b => b.onclick = async () => {
    const [pr, id] = JSON.parse(b.dataset.prCheck), card = b.closest(".pr-finding");
    b.disabled = true; b.innerHTML = '<span class="loading-inline">Checking the new commits…</span>';
    $(".pr-check", card)?.remove();
    const d = await save("review_check", { pr, id });
    if (!d.ok) { b.disabled = false; b.textContent = "Is it fixed?"; return alertMsg(b, d); }
    b.closest(".row").insertAdjacentHTML("beforebegin", checkLine(d));
    b.disabled = false; b.textContent = "Check again";
    softRoute();  // a finding found fixed gives its points back: show the new score now
  });
  $$("[data-pr-fix]", root).forEach(b => b.onclick = async () => {
    b.disabled = true; b.textContent = "Starting…";
    const d = await save("review_fix", { pr: b.dataset.prFix });
    if (!d.ok) { b.disabled = false; b.textContent = "Try again"; return alertMsg(b, d); }
    softRoute();
  });
  $$("[data-pr-edit]", root).forEach(b => b.onclick = () => {
    const card = b.closest(".pr-finding");
    $(`[data-pr-editbox="${b.dataset.prEdit}"]`, card).hidden = false;
    $(`[data-pr-body="${b.dataset.prEdit}"]`, card).hidden = true;
  });
  $$("[data-pr-editcancel]", root).forEach(b => b.onclick = () => {
    const card = b.closest(".pr-finding");
    $(`[data-pr-editbox="${b.dataset.prEditcancel}"]`, card).hidden = true;
    $(`[data-pr-body="${b.dataset.prEditcancel}"]`, card).hidden = false;
  });
  $$("[data-pr-importpath]", root).forEach(b => b.onclick = () => { const [p, path] = JSON.parse(b.dataset.prImportpath); prImport(p, path, b); });
  $$("[data-pr-pass]", root).forEach(b => b.onclick = () => {
    const [pr, n] = JSON.parse(b.dataset.prPass);
    sessionStorage.setItem("lfg.prpass." + pr, n);
    $$("[data-pr-pass]", root).forEach(x => x.classList.toggle("on", x === b));  // the tab moves now, the review follows
    const body = $(".pr-split", root);
    if (body) body.innerHTML = `<div class="pr-pass-body" aria-busy="true" aria-label="Loading"><div class="skeleton" style="height:120px"></div><div class="skeleton" style="height:18px;width:70%;margin-top:16px"></div><div class="skeleton" style="height:18px;width:55%;margin-top:10px"></div><div class="sk-box">${'<div class="sk-row"><div class="skeleton" style="width:45%"></div></div>'.repeat(3)}</div></div>`;
    softRoute();
  });
  $$("[data-pr-discard]", root).forEach(b => b.onclick = () => {
    const [pr, n] = JSON.parse(b.dataset.prDiscard);
    openDrawer(`Discard review ${n}?`, `<div class="readable"><p>Its findings and your keep/drop choices go. Nothing was posted, so GitHub isn't touched. Earlier reviews stay.</p><div class="set-actions"><button class="btn primary" id="pr-disc-go">Discard</button><span class="save-msg" id="pr-disc-msg"></span></div></div>`);
    $("#pr-disc-go").onclick = async () => {
      const r = await save("review_discard", { pr, pass: n });
      saidMsg($("#pr-disc-msg"), r, "Discarded.");
      if (r.ok) { sessionStorage.removeItem("lfg.prpass." + pr); setTimeout(() => { closeDrawer(); softRoute(); }, 500); }
    };
  });
  $$("[data-pr-askgo]", root).forEach(b => {
    const [pr, id] = JSON.parse(b.dataset.prAskgo), box = b.closest(".pr-edit"), input = $("[data-pr-ask]", box);
    const go = async () => {
      if (!input.value.trim()) return input.focus();
      b.disabled = true; b.textContent = "Asking…";
      const d = await save("review_rewrite", { pr, id, instruction: input.value });
      b.disabled = false; b.textContent = "Ask Claude";
      if (!d.ok) return alertMsg(b, d);
      $("textarea.editor", box).value = d.body;
      input.value = "";
      input.placeholder = "Changed below. Ask again, edit it yourself, or Save comment.";
    };
    b.onclick = go;
    input.onkeydown = e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); go(); } };
  });
  $$("[data-pr-editsave]", root).forEach(b => b.onclick = async () => {
    const [pr, id] = JSON.parse(b.dataset.prEditsave), box = b.closest(".pr-edit");
    const text = $("textarea.editor", box).value;  // the comment, not the "Ask Claude to change it" box above it
    const d = await save("review_mark", { pr, ids: [id], body: text });
    if (!d.ok) return saidMsg($(".save-msg", box), d);
    const shown = $(`[data-pr-body="${id}"]`, b.closest(".pr-finding"));
    shown.innerHTML = md(text);
    shown.hidden = false;
    box.hidden = true;
    saidMsg($(".save-msg", box), d, "");
  });
  $$("[data-pr-preview]", root).forEach(b => b.onclick = async () => {
    const [pr, event] = JSON.parse(b.dataset.prPreview), body = ($(`[data-pr-postbody="${pr}"]`, root) || {}).value || "";
    const d = await save("review_post", { pr, event, body, dry_run: true });
    if (!d.ok) return alertMsg(b, d);
    const verb = { APPROVE: "Approve", REQUEST_CHANGES: "Request changes", COMMENT: "Comment" }[d.event];
    openDrawer(`${verb}: what will be posted`, `<div class="readable">
      <p>${plural(d.comments.length, "comment")} on lines of code${d.in_body.length ? `, and ${plural(d.in_body.length, "finding")} in the review text because GitHub can't attach ${d.in_body.length === 1 ? "it" : "them"} to a changed line` : ""}.</p>
      ${(d.already || []).length ? `<div class="callout warn"><b>Raised before:</b><ul>${d.already.map(a => `<li><span class="mono">${esc(a.id)}</span>: ${esc(a.who.join(", "))}</li>`).join("")}</ul>Check you're not posting the same comment twice.</div>` : ""}
      ${d.body ? `<div class="k">Review text</div><div class="box pad md">${md(d.body)}</div>` : ""}
      ${d.comments.map(c => `<div class="card"><div class="muted small mono">${esc(c.path)}:${esc(c.line)}</div><div class="md">${md(c.body)}</div></div>`).join("")}
      <div class="set-actions"><button class="btn primary" id="pr-post-go">${verb} on GitHub</button><span class="save-msg" id="pr-post-msg"></span></div></div>`);
    $("#pr-post-go").onclick = async () => {
      const go = $("#pr-post-go");
      go.disabled = true; go.textContent = "Posting…";
      const r = await save("review_post", { pr, event: event, body });
      saidMsg($("#pr-post-msg"), r, "Posted.");
      if (r.ok) { go.textContent = "Posted"; setTimeout(() => { closeDrawer(); softRoute(); }, 900); } else { go.disabled = false; go.textContent = "Try again"; }
    };
  });
}
function alertMsg(el, d) {
  let m = el.parentNode.querySelector(".save-msg");
  if (!m) { m = document.createElement("span"); m.className = "save-msg"; el.parentNode.appendChild(m); }
  saidMsg(m, d);
}

const NAV_GROUPS = [["Your work", ["home", "sessions", "todos", "environment", "runs", "issues", "checks", "prs"]], ["This project", ["code", "insights", "docs", "knowledge"]], ["LFG", ["prefs", "talk", "corrections", "usage", "skills", "integrations", "settings", "help"]]];
/* 24px line icons, drawn for these pages (stroke = currentColor) */
const ICON = {
  home: "M3 10.5 12 3l9 7.5M5 9v11h5v-6h4v6h5V9",
  sessions: "M4 5h16v11H8l-4 4zM8 9h8M8 12h5",
  environment: "M4 5h16v5H4zM4 14h16v5H4zM7 7.5h.01M7 16.5h.01",
  prefs: "M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0M14 4v4M8 10v4M16 16v4",
  talk: "M4 5h16v10H9l-5 4zM8 9h8M8 12h5",
  corrections: "M4 5h16v10H9l-5 4zM9 9.5l2 2 4-4",
  runs: "M5 4l14 8-14 8z",
  todos: "M4 6.5l1.5 1.5L8 5.5M4 12.5l1.5 1.5L8 11.5M4 18.5l1.5 1.5L8 17.5M11 7h9M11 13h9M11 19h9",
  studio: "M4 5h16v14H4zM7.5 10l2.5 2-2.5 2M12 15h4",
  issues: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2z",
  checks: "M12 3l8 3v6c0 5-3.4 8.3-8 9-4.6-.7-8-4-8-9V6zM9 12l2 2 4-4",
  prs: "M6 3a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM6 7v10M6 17a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM18 17a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM18 17V9a3 3 0 0 0-3-3h-4M13 3.5 10.5 6 13 8.5",
  code: "M8 7l-5 5 5 5M16 7l5 5-5 5M13.5 5l-3 14",
  insights: "M3 17l6-6 4 4 8-8M15 7h6v6",
  back: "M15 6l-6 6 6 6",
  diff: "M6 4v10M12 4v4M9 8h6M17 10v10M14 16h6M6 18h.01",
  image: "M4 5h16v14H4zM4 16l5-5 4 4 3-3 4 4M15 9.5h.01",
  docs: "M14 3H6v18h12V7zM14 3v4h4M9 12h6M9 16h6",
  plus: "M12 5v14M5 12h14",
  insights: "M9 18h6M10 21h4M12 3a6 6 0 0 0-3.6 10.8c.6.5 1 1.2 1.1 2h5c.1-.8.5-1.5 1.1-2A6 6 0 0 0 12 3z",
  stack: "M12 3l9 4.5-9 4.5-9-4.5zM3 12l9 4.5 9-4.5M3 16.5l9 4.5 9-4.5",
  chev: "M6 9l6 6 6-6",
  folder: "M3 6.5A1.5 1.5 0 0 1 4.5 5H9l2 2h8.5A1.5 1.5 0 0 1 21 8.5v9a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5z",
  knowledge: "M4 5.5C6.5 4 9.5 4 12 6c2.5-2 5.5-2 8-.5V19c-2.5-1.5-5.5-1.5-8 .5-2.5-2-5.5-2-8-.5zM12 6v13.5",
  usage: "M4 20V10M10 20V4M16 20v-6M2 20h20",
  skills: "M13 2 4 14h7l-1 8 9-12h-7z",
  integrations: "M9 3v5M15 3v5M6 8h12v4a6 6 0 0 1-12 0zM12 18v3",
  refresh: "M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7",
  compress: "M4 9h16M4 15h16M10 4l2 3 2-3M10 20l2-3 2 3",
  mic: "M12 3a3 3 0 0 1 3 3v6a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3zM5 11a7 7 0 0 0 14 0M12 18v3",
  target: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM12 12h.01",
  lock: "M6 11h12v10H6zM8 11V7a4 4 0 0 1 8 0v4",
  box: "M3 7l9-4 9 4-9 4zM3 7v10l9 4 9-4V7M12 11v10",
  branch: "M6 3v12M6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM18 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM18 9a9 9 0 0 1-9 9",
  "chevron-down": "M6 9l6 6 6-6",
  "chevron-up": "M6 15l6-6 6 6",
  settings: "M4 7h9M17 7h3M4 17h3M11 17h9M15 9a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM9 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4z",
  help: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM9.5 9.5a2.5 2.5 0 1 1 3.4 2.3c-.6.3-.9.8-.9 1.4v.3M12 17h.01",
  panel: "M4 4h16v16H4zM9.5 4v16",
  clip: "M20.5 11.5l-8.3 8.3a5 5 0 0 1-7.1-7.1l8.6-8.6a3.3 3.3 0 0 1 4.7 4.7l-8.5 8.5a1.7 1.7 0 0 1-2.4-2.4l7.8-7.8",
  rewind: "M3 12a9 9 0 1 0 2.6-6.4M3 4v5h5",
  copy: "M9 9h11v11H9zM5 15H4V4h11v1",
  more: "M5 12h.01M12 12h.01M19 12h.01",
  download: "M12 4v11M7 10l5 5 5-5M5 20h14",
  terminal: "M4 5h16v14H4zM7.5 10l2.5 2-2.5 2M12 15h4",
  pin: "M9 4h6l-1 6 3 3H7l3-3zM12 13v7",
  agent: "M12 3v3M7 6h10a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2zM9.5 11.5v1M14.5 11.5v1M9.5 15.5h5",
};
const icon = (k, cls = "ico") => `<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true"><path d="${ICON[k] || ""}"/></svg>`;
/* Tabs: PR reviews and Studio sessions you open join a row of tabs above the page and a list under the page in the
   sidebar, until you close them. Drag one, above the page or in the sidebar, to reorder: both follow one order. Pin
   one to keep it at the front: pinned tabs stay ahead of the rest, have no close button, and never drop off when too
   many are open. Dragging a tab among the pinned ones pins it. Kept in this browser. Each repo has its own: the tabs
   shown are the selected repo's (a session's tab keeps the repo it was opened in; a PR's is its GitHub repo, matched
   by name to your checkouts, and shows everywhere when you have no checkout of it). */
const TABS_MAX = 40;  // across every repo; pinned tabs never count
const nsDot = st => st === "needs-you" ? '<span class="ns-dot warn" title="Needs you"></span>' : ssLive(st) ? `<span class="ns-dot${st === "idle" ? "" : " on"}" title="${st === "idle" ? "Waiting for you" : "Working"}"></span>` : "";
const ssStateOf = id => ((state.navSess || []).find(x => x.id === id) || {}).state;
const TABSETS = {
  prs: { store: "lfg.prtabs", key: "pr", root: "prs", href: k => "#prs/" + k.replace("#", "/"), tip: t => t.pr + " · " + t.title,
    label: t => `${esc(t.pr.split("#")[1] ? "#" + t.pr.split("#")[1] : t.pr)} <span class="prtab-t">${esc(t.title)}</span>` },
  studio: { store: "lfg.sstabs", key: "id", root: "studio", href: k => "#studio/" + k, tip: t => t.title,
    label: t => `${nsDot(ssStateOf(t.id))}<span class="prtab-t ss-tab-t">${esc(t.title || "Session")}</span>` },
};
const tabKey = (kind, t) => t[TABSETS[kind].key];
const tabHref = (kind, k) => TABSETS[kind].href(k);
const tabOn = (kind, k) => { const h = tabHref(kind, k); return location.hash === h || location.hash.startsWith(h + "/"); };
/* Whether a tab belongs to the repo selected top left. */
function tabHere(kind, t) {
  if (kind === "studio") return t.repo ? t.repo === state.repo : (state.navSess || []).some(x => x.id === t.id);
  const name = String(t.pr || "").split("#")[0].split("/")[1] || "";
  return !(state.repos || []).some(r => r.name === name) || repoName() === name;
}
/* The selected repo's tabs, in order. tabsAll: every repo's, which is what's stored. */
const tabsOf = kind => tabsAll(kind).filter(t => tabHere(kind, t));
function tabsAll(kind) {
  try { const v = JSON.parse(localStorage.getItem(TABSETS[kind].store) || "[]"); return Array.isArray(v) ? v.filter(t => t && tabKey(kind, t)) : []; } catch (e) { return []; }
}
function tabsSave(kind, tabs) {
  const pinned = tabs.filter(t => t.pinned), rest = tabs.filter(t => !t.pinned);  // pinned first, each group in its order
  localStorage.setItem(TABSETS[kind].store, JSON.stringify([...pinned, ...rest.slice(-Math.max(1, TABS_MAX - pinned.length))]));
}
function tabsRedraw(kind) {
  renderNav((location.hash.slice(1) || "home").split("/")[0]);
  $$(`[data-tabstrip="${kind}"]`).forEach(el => { el.outerHTML = tabStrip(kind); });
}
function tabOpen(kind, k, title) {
  const tabs = tabsAll(kind), hit = tabs.find(t => tabKey(kind, t) === k);
  if (hit) {
    const repo = kind === "studio" && !hit.repo && state.repo;  // a tab from before tabs had a repo: it gets this one
    if ((title && hit.title !== title) || repo) { if (title) hit.title = title; if (repo) hit.repo = repo; tabsSave(kind, tabs); tabsRedraw(kind); }
    return;
  }
  tabsSave(kind, [...tabs, { [TABSETS[kind].key]: k, title: title || k, ...(kind === "studio" && state.repo ? { repo: state.repo } : {}) }]);
  tabsRedraw(kind);
}
function tabClose(kind, k) {
  const tabs = tabsAll(kind), t = tabs.find(x => tabKey(kind, x) === k);
  if (!t || t.pinned) return;
  const here = tabs.filter(x => tabHere(kind, x)), i = here.indexOf(t);
  here.splice(i, 1);
  tabsSave(kind, tabs.filter(x => x !== t));
  if (tabOn(kind, k)) location.hash = here.length ? tabHref(kind, tabKey(kind, here[Math.min(i, here.length - 1)])).slice(1) : TABSETS[kind].root;
  else tabsRedraw(kind);
}
function tabPin(kind, k) {
  const tabs = tabsAll(kind), t = tabs.find(x => tabKey(kind, x) === k);
  if (!t) return;
  t.pinned = !t.pinned;
  if (t.pinned) { tabs.splice(tabs.indexOf(t), 1); tabs.splice(tabs.filter(x => x.pinned).length, 0, t); }  // last of the pinned
  tabsSave(kind, tabs);
  tabsRedraw(kind);
}
function tabMove(kind, from, to, after) {
  const tabs = tabsAll(kind), i = tabs.findIndex(t => tabKey(kind, t) === from);
  if (i < 0 || from === to) return;
  const [t] = tabs.splice(i, 1);
  const j = tabs.findIndex(x => tabKey(kind, x) === to);
  if (j >= 0) t.pinned = !!tabs[j].pinned;  // among the pinned ones it's pinned; among the rest it isn't
  tabs.splice(j < 0 ? tabs.length : j + (after ? 1 : 0), 0, t);
  tabsSave(kind, tabs);
  tabsRedraw(kind);
}
const tabData = (kind, k) => esc(JSON.stringify([kind, k]));
const tabBtns = (kind, t) => {
  const k = tabKey(kind, t);
  return `<span class="tab-pin${t.pinned ? " on" : ""}" data-tab-pin="${tabData(kind, k)}" role="button" title="${t.pinned ? "Unpin" : "Pin: keep it at the front"}" aria-label="${t.pinned ? "Unpin" : "Pin"} ${esc(t.title || k)}">${icon("pin")}</span>${t.pinned ? "" : `<span class="prtab-x" data-tab-x="${tabData(kind, k)}" role="button" aria-label="Close ${esc(t.title || k)}">×</span>`}`;
};
function tabStrip(kind) {
  const tabs = tabsOf(kind);
  return `<div class="pr-doc-tabs" role="tablist" data-tabstrip="${kind}"${tabs.length ? "" : " hidden"}>${tabs.map(t => { const k = tabKey(kind, t); return `<a class="prtab${tabOn(kind, k) ? " on" : ""}${t.pinned ? " pinned" : ""}" href="${tabHref(kind, k)}" draggable="true" data-tab="${tabData(kind, k)}" title="${esc(TABSETS[kind].tip(t))}">${TABSETS[kind].label(t)}${tabBtns(kind, t)}</a>`; }).join("")}</div>`;
}
const tabNavRow = (kind, t, cls) => { const k = tabKey(kind, t); return `<a class="${cls}${tabOn(kind, k) ? " on" : ""}${t.pinned ? " pinned" : ""}" href="${tabHref(kind, k)}" draggable="true" data-tab="${tabData(kind, k)}" title="${esc(TABSETS[kind].tip(t))}"><span class="tab-l">${TABSETS[kind].label(t)}</span>${tabBtns(kind, t)}</a>`; };
document.addEventListener("click", e => {
  const b = e.target.closest("[data-tab-x], [data-tab-pin]");
  if (!b) return;
  e.preventDefault(); e.stopPropagation();
  const [kind, k] = JSON.parse(b.dataset.tabX || b.dataset.tabPin);
  if (b.dataset.tabX) tabClose(kind, k); else tabPin(kind, k);
}, true);
let tabDrag = null;
const tabAt = e => { const el = e.target.closest && e.target.closest("[data-tab]"); return el && tabDrag && JSON.parse(el.dataset.tab)[0] === tabDrag[0] ? el : null; };
const tabAfter = (e, el) => {
  const r = el.getBoundingClientRect();
  return el.closest("#nav") ? e.clientY > r.top + r.height / 2 : e.clientX > r.left + r.width / 2;
};
document.addEventListener("dragstart", e => {
  const el = e.target.closest && e.target.closest("[data-tab]");
  if (!el) return;
  tabDrag = JSON.parse(el.dataset.tab);
  e.dataTransfer.effectAllowed = "move";
  e.dataTransfer.setData("text/plain", tabDrag[1]);
  el.classList.add("dragging");
});
document.addEventListener("dragover", e => {
  const el = tabAt(e);
  if (!el) return;
  e.preventDefault();
  $$(".drop-before, .drop-after").forEach(x => x.classList.remove("drop-before", "drop-after"));
  if (JSON.parse(el.dataset.tab)[1] !== tabDrag[1]) el.classList.add(tabAfter(e, el) ? "drop-after" : "drop-before");
});
document.addEventListener("drop", e => {
  const el = tabAt(e);
  if (!el) return;
  e.preventDefault();
  tabMove(tabDrag[0], tabDrag[1], JSON.parse(el.dataset.tab)[1], tabAfter(e, el));
});
document.addEventListener("dragend", () => {
  tabDrag = null;
  $$(".dragging, .drop-before, .drop-after").forEach(x => x.classList.remove("dragging", "drop-before", "drop-after"));
});
const prTabOpen = (pr, title) => tabOpen("prs", pr, title);
const prTabStrip = () => tabStrip("prs");
function renderNav(active) {
  const subs = k => k !== "prs" ? "" : tabsOf("prs").map(t => tabNavRow("prs", t, "nav-sub")).join("");
  // the pages the welcome turned on (always the one you're on)
  const visible = new Set(state.pages || NAV.map(p => p[0]));
  visible.add(active);
  morph($("#nav"), navSessions(active) + NAV_GROUPS.map(([g, ks]) => {
    const shown = ks.filter(k => visible.has(k));
    return shown.length ? `<div class="nav-grp">${esc(g)}</div>${shown.map(k => `<a class="${k === active && !(k === "prs" && tabsOf("prs").some(t => tabOn("prs", t.pr))) ? "on" : ""}" href="#${k}" title="${esc(TITLES[k])}"${k === active ? ' aria-current="page"' : ""}>${icon(k)}<span>${esc(TITLES[k])}</span></a>${subs(k)}`).join("")}` : "";
  }).filter(Boolean).join(""));
}
/* The Studio accordion at the top of the sidebar: new session, your open session tabs (pinned first, drag to reorder),
   then sessions live here that aren't open as tabs (and whether they need you) and your recent ones, and the full list.
   Open or closed is remembered. */
function navSessions(active) {
  const open = localStorage.getItem("lfg.nav.sessions") !== "0";
  const list = (state.navSess || []).filter(x => x.source !== "background");
  const cur = active === "studio" ? (location.hash.split("/")[1] || "") : "";  // "" = new, "all" = the list
  const tabs = tabsOf("studio"), tabbed = new Set(tabs.map(t => t.id)), rest = list.filter(x => !tabbed.has(x.id));
  const live = rest.filter(x => ssLive(x.state)).slice(0, 5), recent = rest.filter(x => !ssLive(x.state)).slice(0, Math.max(0, 5 - live.length - tabs.length));
  const nLive = list.filter(x => ssLive(x.state));
  const when = t => { const m = (Date.now() - new Date(t || 0)) / 6e4; return m < 60 ? `${Math.max(1, Math.round(m))}m` : m < 1440 ? `${Math.round(m / 60)}h` : `${Math.round(m / 1440)}d`; };
  const row = x => `<a class="ns-item${x.id === cur ? " on" : ""}" href="#studio/${esc(x.id)}" title="${esc(x.title)}">${nsDot(x.state)}<span class="ns-t">${esc(x.title)}</span><span class="ns-w">${ssLive(x.state) ? "" : when(x.updated)}</span></a>`;
  const others = live.map(row).join("") + recent.map(row).join("");
  return `<div class="ns${open ? " open" : ""}"><div class="ns-head"><a class="${active === "studio" && !cur ? "on" : ""}" href="#studio" title="Studio: Claude Code sessions, here">${icon("studio")}<span>Studio</span>${nLive.length ? `<span class="ns-n${nLive.some(x => x.state === "needs-you") ? " warn" : ""}">${nLive.length}</span>` : ""}</a>
    <button class="ns-btn" data-ns-new title="New session" aria-label="New session">+</button><button class="ns-btn ns-tog" data-ns-toggle aria-expanded="${open}" aria-label="Show Studio sessions">${icon("chev")}</button></div>
    <div class="ns-body">${tabs.map(t => tabNavRow("studio", t, "ns-item ns-tab")).join("")}${tabs.length && others ? '<div class="ns-sep"></div>' : ""}${others}${list.length || tabs.length ? `<a class="ns-all${cur === "all" ? " on" : ""}" href="#studio/all">All sessions</a>` : '<span class="ns-empty">No sessions yet</span>'}</div></div>`;
}
async function loadNavSessions() {
  if (!state.repo) return;
  try { const d = await api("studio"); state.navSess = d.sessions || []; } catch (e) { return; }
  if (state.linearWs === undefined) { try { state.linearWs = ((await api("todos")).linear || {}).workspace || ""; } catch (e) { state.linearWs = ""; } }
  renderNav((location.hash.slice(1) || "home").split("/")[0]);
  $$('[data-tabstrip="studio"]').forEach(el => { el.outerHTML = tabStrip("studio"); });
}
/* the sidebar folds to an icon rail (the button left of the breadcrumb, or Cmd/Ctrl+\\); remembered */
function setRail(on) {
  document.body.classList.toggle("rail", on); localStorage.setItem("lfg.side", on ? "rail" : "");
  const b = $("#side-tog"); if (b) { b.setAttribute("aria-label", on ? "Expand sidebar" : "Collapse sidebar"); b.title = `${on ? "Expand" : "Collapse"} sidebar (${/Mac/.test(navigator.platform) ? "⌘" : "Ctrl+"}\\)`; b.setAttribute("aria-expanded", String(!on)); }
}
setRail(localStorage.getItem("lfg.side") === "rail");
document.addEventListener("click", e => { if (e.target.closest("#side-tog")) setRail(!document.body.classList.contains("rail")); });
document.addEventListener("keydown", e => { if (e.key === "\\" && (e.metaKey || e.ctrlKey) && !e.altKey) { e.preventDefault(); setRail(!document.body.classList.contains("rail")); } });
document.addEventListener("click", e => { if (e.target.closest("[data-stop]")) e.stopPropagation(); }, true);  // a link in a clickable row opens only itself
document.addEventListener("click", e => {
  const t = e.target.closest("[data-ns-toggle], [data-ns-new]");
  if (!t) return;
  e.preventDefault();
  if (t.hasAttribute("data-ns-new")) { state.ssFresh = true; if (location.hash === "#studio") route(); else location.hash = "#studio"; return; }
  const box = t.closest(".ns"), open = !box.classList.contains("open");
  box.classList.toggle("open", open); t.setAttribute("aria-expanded", open); localStorage.setItem("lfg.nav.sessions", open ? "1" : "0");
});
function applyPages(d) {
  state.pages = d.pages || NAV.map(p => p[0]);
  const current = (location.hash.slice(1) || "home").split("/")[0];
  renderNav(current);
}
/* A repo's short name for the browser tab: its first word, cut to 3 letters when that word is long (external-api is
   "ext", aegis-compliance-portal "aegis", lfg "lfg"). Two repos that would share one get the first letter of each
   word after it as well (external-api "ext-a", external-web "ext-w"). */
function repoShort(name, all) {
  const words = n => String(n || "").toLowerCase().split(/[-_.\s]+/).filter(Boolean);
  const base = n => { const w = words(n)[0] || ""; return w.length > 6 ? w.slice(0, 3) : w; };
  const short = base(name);
  if (!short) return "";
  const clash = (all || []).some(o => o && o !== name && base(o) === short);
  return clash && words(name).length > 1 ? short + "-" + words(name).slice(1).map(w => w[0]).join("") : short;
}
const PAGE_SHORT = { prs: "PRs", talk: "Talk" };
/* The browser tab: repo · page · what's open, shortened so several tabs stay readable ("ext · PRs · #1800"). */
function tabTitle(page, item) {
  const repo = repoShort(repoName(), (state.repos || []).map(r => r.name));
  const what = !item ? "" : page === "prs" && /^[^#\s]+#\d+$/.test(item) ? "#" + item.split("#")[1]
    : item.length > 32 ? item.slice(0, 31).trimEnd() + "…" : item;
  return [repo, PAGE_SHORT[page] || TITLES[page] || page, what].filter(Boolean).join(" · ") || "LFG";
}
/* Breadcrumb in the top bar: project / page / item. Pages that open an item call crumbs() again with it. It also names
   the browser tab. */
function crumbs(page, item, itemHref) {
  state.crumb = { page, item, itemHref };
  const parts = [`<span class="crumb-proj">${esc(repoName() || "LFG")}</span>`, `<a href="#${page}">${icon(page)}${esc(TITLES[page] || page)}</a>`];
  if (item) parts.push(itemHref ? `<a href="${itemHref}">${esc(item)}</a>` : `<span>${esc(item)}</span>`);
  $("#crumbs").innerHTML = parts.join('<span class="sep">/</span>');
  document.title = tabTitle(page, item);
}
/* code map: build/update from the dashboard (the same background job the hooks start) */
const mapBtn = (st, cls = "btn small") => st === "syncing" ? "" : st === "missing" ? `<button class="${cls} primary" data-map-build="update">Build now</button>`
  : st === "fresh" ? `<button class="${cls}" data-map-build="update" title="Re-check the code for changes">Refresh</button>` : `<button class="${cls}" data-map-build="update">Update now</button>`;
let mapTimer = null, mapWatching = false;
async function buildMap(what, btn) {
  if (btn) { btn.disabled = true; btn.textContent = "Starting…"; }
  const r = await save("graphs_build", { repo: state.repo, what });
  if (!r.ok) { if (btn) { btn.disabled = false; btn.textContent = "Try again"; btn.title = r.why || ""; } alert(r.why || "Couldn't start it."); return; }
  if (what === "docs") { if (btn) btn.textContent = "Started: docs update in the background"; return; }
  mapWatching = true;
  setTimeout(mapStatus, 1500);
}
function wireMap(root) {
  $$("[data-map-build]", root).forEach(b => b.onclick = e => {
    e.preventDefault();
    if (b.dataset.mapBuild === "rebuild" && !confirm("Rebuild the code map from scratch? It runs in the background and can take a few minutes on a big project.")) return;
    buildMap(b.dataset.mapBuild, b);
  });
}
async function mapStatus() {
  const el = $("#map-status");
  clearTimeout(mapTimer);
  if (!state.repo) { el.innerHTML = ""; return; }
  try {
    const g = await api("graphs");
    const [text, t] = say(g.status);
    morph(el, `<span class="map-line">${dot(t)}<span class="label">${esc(repoName())} code map: ${esc((text || "unknown").toLowerCase())}</span></span>${mapBtn(g.status, "btn tiny")}`);
    el.title = `The code map of ${repoName()} (the project picked above): an index of its functions and what calls what, which LFG's agents read instead of whole files. ${text || "Unknown"}. Each project has its own.`;
    wireMap(el);
    if (g.status === "syncing") { mapWatching = true; mapTimer = setTimeout(mapStatus, 4000); }
    else if (mapWatching) {
      mapWatching = false;
      if ((location.hash.slice(1) || "").split("/")[0] === "code") { state.cache = {}; softRoute(); }
    }
  } catch (e) { el.innerHTML = ""; }
}
let renderSeq = 0, lastHtml = "", lastHash = "";
const pageCache = {};  // each page as last drawn, shown at once when you come back to it
/* morph(el, html): make el's content match html by changing only what differs, instead of throwing it away and
   building it again (innerHTML). Everything that didn't change is the same element as before, so a redraw keeps
   what you did to it: scroll position, an open section, focus and the caret, selected text, typed text, an open
   menu. What the page itself owns is left alone:
   - data-fill on an element (in the HTML): script draws its content (a table, a tab's body, the review chat), so a
     redraw keeps what is in it; the script that fills it updates it (with morph too).
   - data-local on an element script added (a Rewind box): stays until script removes it.
   - data-keep="attr ..." on an element: those attributes are script's (hidden, aria-expanded, class, href).
   - always the person's: a <details>'s open, a text box's typed value, a style script set (a grown text box),
     and the flags script puts on what it loaded (data-loaded and the like, whose content it then also keeps). */
const SCRIPT_FLAGS = ["data-loaded", "data-done", "data-wired", "data-ins-wired"];
function morph(el, html) {
  const t = document.createElement("template");
  t.innerHTML = html;
  morphKids(el, t.content);
}
function morphOuter(el, html) {  // el itself becomes the (single) element html describes
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  const nb = t.content.firstElementChild;
  if (!nb) return el.remove();
  if (sameNode(el, nb)) morphNode(el, nb); else el.replaceWith(nb);
}
const isLocal = n => n.nodeType === 1 && n.hasAttribute("data-local");
const nodeKey = n => n.nodeType === 1 ? n.id || n.getAttribute("data-key") || n.getAttribute("data-i") || "" : "";
const firstClass = n => (n.getAttribute("class") || "").split(" ")[0];
function sameNode(a, b) {
  if (a.nodeType !== b.nodeType) return false;
  if (a.nodeType !== 1) return true;
  return a.tagName === b.tagName && nodeKey(a) === nodeKey(b) && firstClass(a) === firstClass(b);
}
function keepAttr(a, name, inNew) {
  if (SCRIPT_FLAGS.includes(name)) return true;
  if (name === "open" && a.tagName === "DETAILS") return true;
  if (name === "style" && !inNew) return true;
  if (name === "hidden" && a.matches(KEEP_SHOWN)) return true;
  const own = a.getAttribute("data-keep");
  return !!own && own.split(" ").includes(name);
}
function morphNode(a, b) {
  if (a.nodeType !== 1) { if (a.nodeValue !== b.nodeValue) a.nodeValue = b.nodeValue; return; }
  for (const { name, value } of [...b.attributes]) if (a.getAttribute(name) !== value && !keepAttr(a, name, true)) a.setAttribute(name, value);
  for (const { name } of [...a.attributes]) if (!b.hasAttribute(name) && !keepAttr(a, name, false)) a.removeAttribute(name);
  if ((b.hasAttribute("data-fill") && a.childNodes.length) || SCRIPT_FLAGS.some(f => a.hasAttribute(f))) return;  // script's content
  morphKids(a, b);
}
function morphKids(a, b) {
  let cur = a.firstChild;
  for (let nb = b.firstChild; nb;) {
    const next = nb.nextSibling;
    while (cur && isLocal(cur)) cur = cur.nextSibling;
    if (cur && sameNode(cur, nb)) { morphNode(cur, nb); cur = cur.nextSibling; } else {
      let hit = null;
      if (nodeKey(nb)) for (let x = cur; x; x = x.nextSibling) if (sameNode(x, nb)) { hit = x; break; }
      if (hit) { a.insertBefore(hit, cur); morphNode(hit, nb); } else a.insertBefore(nb, cur);
    }
    nb = next;
  }
  while (cur) { const n = cur.nextSibling; if (!isLocal(cur)) cur.remove(); cur = n; }
}
/* A page that watches something (a running review, checks, a scan) redraws itself on a timer, and each redraw asks
   for the next one. pageTimer keeps one pending per name, so redraws from elsewhere don't stack up extra timers. */
const PAGE_TIMERS = {};
function pageTimer(name, ms, fn) {
  if (PAGE_TIMERS[name]) return;
  PAGE_TIMERS[name] = setTimeout(() => { delete PAGE_TIMERS[name]; fn(); }, ms);
}
/* Wiring that adds listeners runs again after each redraw that keeps the element: once(el, "what") is true only
   the first time for that element, so a listener is never added twice (one Enter sending a message twice). */
const once = (el, k) => { const w = el._wired || (el._wired = new Set()); return !w.has(k) && !!w.add(k); };
/* A refresh redraws the page from scratch. What you did to it (opened, shown, typed, focused, scrolled) is noted
   first, by a key that survives the redraw, and put back after, so a page that updates itself never undoes you. */
const KEEP_SHOWN = ".pr-discuss, .pr-edit, [data-pr-body], [data-pr-discuss], [data-pr-editbox]";
function uiKey(el, view) {
  const part = e => {
    if (e.id) return "#" + e.id;
    const a = [...e.attributes].find(x => x.name.startsWith("data-") && !["data-fill", "data-keep", "data-local", ...SCRIPT_FLAGS].includes(x.name));
    if (a) return `[${a.name}=${a.value}]`;
    if (e.tagName === "DETAILS") { const sm = e.querySelector(":scope > summary"); return "details:" + (sm ? sm.textContent.trim().slice(0, 60) : ""); }
    return "";
  };
  const path = [];
  for (let e = el; e && e !== view; e = e.parentElement) { const k = part(e); if (k) path.unshift(k); if (e.id) break; }
  return (el.className && typeof el.className === "string" ? el.className.split(" ")[0] : el.tagName) + "|" + path.join(">");
}
function keyed(view, sel) {
  const seen = {}, out = [];
  $$(sel, view).forEach(el => { const k = uiKey(el, view); seen[k] = (seen[k] || 0) + 1; out.push([k + "#" + seen[k], el]); });
  return out;
}
function uiSnapshot(view) {
  const a = document.activeElement, keys = new Map(keyed(view, "input, textarea, select").map(([k, el]) => [el, k]));
  return {
    open: new Map(keyed(view, "details").map(([k, d]) => [k, d.open])),
    shown: new Map(keyed(view, KEEP_SHOWN).map(([k, el]) => [k, el.hidden])),
    typed: new Map(keyed(view, "input, textarea").filter(([, el]) => el.type !== "checkbox" && el.type !== "radio" && el.value !== el.defaultValue).map(([k, el]) => [k, el.value])),
    // a list scrolled to its end stays at the end as lines arrive (-1); one you scrolled up stays where you left it
    scroll: new Map(keyed(view, ".pr-thread, .pr-activity ol, .pr-steps, .scroll").filter(([, el]) => el.scrollTop).map(([k, el]) => [k, el.scrollHeight - el.scrollTop - el.clientHeight < 8 ? -1 : el.scrollTop])),
    focus: a && keys.has(a) ? { key: keys.get(a), start: a.selectionStart, end: a.selectionEnd } : null,
  };
}
function uiRestore(view, snap) {
  keyed(view, "details").forEach(([k, d]) => { if (snap.open.has(k) && d.open !== snap.open.get(k)) d.open = snap.open.get(k); });
  keyed(view, KEEP_SHOWN).forEach(([k, el]) => { if (snap.shown.has(k)) el.hidden = snap.shown.get(k); });
  keyed(view, "input, textarea").forEach(([k, el]) => {
    if (snap.typed.has(k)) el.value = snap.typed.get(k);
    // only a box the redraw replaced: focusing one that kept its focus would move your text selection into it
    if (snap.focus && snap.focus.key === k && document.activeElement !== el) { el.focus({ preventScroll: true }); try { el.setSelectionRange(snap.focus.start, snap.focus.end); } catch (e) { /* not a text field */ } }
  });
  keyed(view, ".pr-thread, .pr-activity ol, .pr-steps, .scroll").forEach(([k, el]) => { if (snap.scroll.has(k)) el.scrollTo({ top: snap.scroll.get(k) === -1 ? el.scrollHeight : snap.scroll.get(k), behavior: "instant" }); });  // never animate from the top after a redraw
}
/* Re-draw the current page in place: no loading placeholder, same scroll position, open sections stay open. For
   buttons that change one thing on the page (Keep, Save comment, Review); route() is for going to a page. */
function softRoute() { return route({ soft: true }); }
async function route(opts) {
  const soft = !!(opts && opts.soft);
  let [page, ...rest] = (location.hash.slice(1) || "home").split("/");
  page = { overview: "home", reviews: "checks", security: "checks", architecture: "code", health: "code", brain: "knowledge", tools: "settings" }[page] || page;
  const key = PAGES[page] ? page : "home";
  document.body.classList.toggle("bare", BARE.includes(key));
  wireTourButton(key);
  const arg = rest.join("/");
  renderNav(key);
  if (!soft) crumbs(key);  // a refresh keeps the page's own crumbs (e.g. the PR) instead of flashing back to the page
  const seq = ++renderSeq, view = $("#view"), y = window.scrollY;
  view.classList.toggle("wide", ((key === "review" || key === "prs") && !!arg && arg !== "scores") || key === "studio");  // review screens are two panes, Studio fills the window
  view.classList.toggle("studio", key === "studio");
  view.classList.toggle("welcome", key === "onboarding");
  const snap = soft ? uiSnapshot(view) : null;
  const seen = !soft && pageCache[location.hash];
  if (seen) { view.innerHTML = seen; view.classList.add("stale"); wireView(key, view); }  // last time's page, at once and usable; updated below
  else if (!soft) view.innerHTML = skeletonPage(key, !!arg && arg !== "scores");
  const bar = soft ? null : setTimeout(() => document.body.classList.add("routing"), 120);  // a slow page shows the bar
  let html;
  TID = 0; tPage = true;
  try { html = await PAGES[key](decodeURIComponent(arg)); } catch (e) { html = unavailable({ why: "Couldn't load this page: " + e.message }); } finally { tPage = false; }
  if (bar) { clearTimeout(bar); if (seq === renderSeq) document.body.classList.remove("routing"); }
  if (seq !== renderSeq) return;
  if (soft && html === lastHtml && location.hash === lastHash) return applyGoto(view);  // nothing changed: leave the page alone
  lastHtml = html; lastHash = location.hash;
  pageCache[location.hash] = html;
  view.classList.remove("stale");
  if (soft || seen) morph(view, html); else view.innerHTML = html;  // a page already showing changes only where it changed
  tPage = true;
  try { wireView(key, view); } finally { tPage = false; }
  const rf = $("#refreshed");
  if (rf) rf.textContent = "Updated " + new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  if (soft) {
    uiRestore(view, snap);
    window.scrollTo(0, y);
  } else if (!arg) window.scrollTo(0, 0);
  applyGoto(view);
}
/* Everything a page's HTML needs to work: tables, tabs, buttons. Also run on last time's copy shown while loading. */
function wireView(key, view) {
  mountTables(view); mountTabs(view); wire(view);
  $$("[data-scroll-on]", view).forEach(el => {
    el.classList.toggle("more", el.scrollWidth > el.clientWidth);
    const on = $(".tab.on", el);  // scroll only if the chosen tab is out of view
    if (on) { const r = on.getBoundingClientRect(), b = el.getBoundingClientRect(); if (r.left < b.left || r.right > b.right - 40) el.scrollLeft += r.left - b.left - 8; }
  });
  $$("[data-href]", view).forEach(li => li.onclick = () => (location.hash = li.dataset.href));
  if (key === "docs") wireDocs();
  if (key === "prs") { wirePrs(view); wireScoreCharts(view); }
  if (key === "sessions") wireSessions(view);
  if (key === "knowledge") wireKnowledge(view);
  if (key === "prefs") wirePrefsPage(view);
  if (key === "talk") wireTalk(view);
  if (key === "corrections") wireCorrections(view);
  if (key === "environment") wireEnvironment(view);
  if (key === "checks") { $$('[data-tabs="checks"] .tab', view).forEach(t => { if (once(t, "sonar")) t.addEventListener("click", () => setTimeout(() => wireSonar(view), 0)); }); wireSonar(view); }
  if (key === "onboarding") drawJourney(view);
  if (state.gh && state.gh.starred) $$("[data-gh-star]", view).forEach(b => (b.textContent = "★ Starred, thank you"));
  if (state.pendingTour && state.pendingTour.startsWith("page-")) { const t = state.pendingTour; state.pendingTour = null; setTimeout(() => startTour(t), 400); }
  if (key === "insights") wireInsights(view);
  if (key === "todos") wireTodos(view);
  if (key === "lfg") wireLanding(view);
  if (key === "help") wireHelp(view);
  if (key === "studio") wireStudio(view);
  if (key === "runs" && !/^#runs\/./.test(location.hash)) wireRuns(view);
  if (key === "usage") { wireUsage(view); loadHeadroom(); }
  if (key === "insights") wireInsights(view);
}
/* What shows while a page loads the first time: its shape, shimmering, and what it's waiting on when that's slow. */
const SLOW = { prs: "Asking GitHub for your pull requests…", usage: "Adding up every session's usage…", environment: "Checking your setup…", sessions: "Reading your sessions…" };
function skeletonPage(key, detail) {
  const line = (w, h = 14, mt = 10) => `<div class="skeleton" style="width:${w};height:${h}px;margin-top:${mt}px"></div>`;
  const rows = n => `<div class="sk-box">${Array.from({ length: n }, (_, i) => `<div class="sk-row"><div class="skeleton" style="width:${[46, 38, 52, 30, 42][i % 5]}%"></div><div class="skeleton" style="width:12%"></div><div class="skeleton" style="width:9%"></div></div>`).join("")}</div>`;
  const body = key === "usage" ? `<div class="skeleton" style="height:260px;margin-top:20px"></div>${rows(4)}`
    : key === "prs" && detail ? `${line("60%", 30, 4)}${line("35%")}<div class="sk-split"><div><div class="skeleton" style="height:96px;margin-top:20px"></div>${rows(3)}</div><div class="skeleton" style="height:420px;margin-top:20px"></div></div>`
    : `${rows(5)}${rows(3)}`;
  return `<div class="sk-page" aria-busy="true" aria-label="Loading">${detail && key === "prs" ? "" : `${line("30%", 28, 4)}${line("55%")}`}${SLOW[key] && !detail ? `<div class="loading">${SLOW[key]}</div>` : ""}${body}</div>`;
}
function wireDocs() {
  const body = $("#doc-body");
  wireDocEditor(body);
  $$("[data-doclink]", body).forEach(a => a.onclick = e => {
    e.preventDefault();
    const base = body.dataset.path.split("/").slice(0, -1);
    const target = a.dataset.doclink.split("#")[0];
    const parts = [...base];
    for (const p of target.split("/")) { if (p === "..") parts.pop(); else if (p && p !== ".") parts.push(p); }
    location.hash = `#docs/${body.dataset.src}/${encodeURIComponent(parts.join("/"))}`;
  });
  const f = $("#doc-filter");
  if (f) f.oninput = () => {
    const q = f.value.toLowerCase();
    $$(".doc-nav a").forEach(a => (a.style.display = !q || a.textContent.toLowerCase().includes(q) ? "" : "none"));
    $$(".doc-folder").forEach(dt => {
      const hit = $$("a", dt).some(a => a.style.display !== "none") || dt.querySelector("summary").textContent.toLowerCase().includes(q);
      dt.style.display = !q || hit ? "" : "none";
      if (q && hit) { dt.dataset.wasOpen ??= dt.open ? "1" : ""; dt.open = true; } else if (!q && "wasOpen" in dt.dataset) { dt.open = !!dt.dataset.wasOpen; delete dt.dataset.wasOpen; }
    });
  };
  const on = $(".doc-nav a.on");
  if (on) on.scrollIntoView({ block: "nearest" });
}
/* Back and forward arrows in the top bar. Browsers with the Navigation API say when there is nowhere to go;
   others leave both on, and an arrow with nowhere to go does nothing. */
function histButtons() {
  const n = window.navigation;
  if (!n || !("canGoBack" in n)) return;
  $("#back").disabled = !n.canGoBack;
  $("#forward").disabled = !n.canGoForward;
}
/* Sessions: Claude Code, run from here. Every session for the project, wherever it was started (here, a terminal,
   the desktop app, LFG's own background runs), read from Claude Code's own transcripts; any of them can be continued
   here. A live session shows what Claude does as readable cards, and asks for your OK with buttons. */
const SS_SRC = { lfg: ["LFG", "on"], terminal: ["Terminal", ""], desktop: ["Desktop app", ""], background: ["Background", "faded"] };
const SS_STATE = { "needs-you": ["Needs you", "warn"], working: ["Working", "ok"], starting: ["Starting", "ok"], idle: ["Waiting for you", "on"], ended: ["Ended", ""], saved: ["", ""] };
const SS_MODES = [["default", "Ask first", "Asks before edits and commands"], ["acceptEdits", "Accept edits", "Edits files, asks before commands"], ["plan", "Plan only", "Reads and plans, changes nothing"]];
const ssLive = st => ["working", "needs-you", "starting", "idle"].includes(st);
const money = v => v == null ? "" : v < 0.01 ? "<$0.01" : usd(v);
let ssPoll = null;

PAGES.studio = async arg => {
  if (arg === "all") {  // every session for the project, and the worktrees they work in
    const [list, where, unlocked] = await Promise.all([api("studio"), api("studio_where"), isUnlocked()]);
    (list.sessions || []).forEach(x => { x.via_pr = x.via === "pr"; x.via_ticket = x.via === "ticket"; });
    state.sess = { list, d: null, id: null, where };
    state.navSess = list.sessions || [];
    crumbs("studio", "All sessions", "#studio/all");
    return `<div class="ss-page">${ssWorktrees(where)}${ssAll(list, unlocked)}</div>`;
  }
  if (!arg) {  // a new session: the same screen as any session, empty, with the composer at the bottom
    const [sug, where] = await Promise.all([api("studio_suggest"), api("studio_where")]);
    state.sess = { d: null, id: null, sug, where };
    crumbs("studio", "New session", "#studio");
    return `${tabStrip("studio")}<div class="ss-one">${ssNew(sug)}</div>`;
  }
  const ch = arg.match(/^([0-9a-f-]{36})\/changes$/);
  if (ch) return `${tabStrip("studio")}${await ssChanges(ch[1])}`;
  const d = await api("studio_session", { id: arg });
  state.sess = { d, id: arg };
  crumbs("studio", d && d.available !== false ? d.title : null, `#studio/${arg}`);
  if (d.available !== false) tabOpen("studio", arg, d.title);
  return d.available === false ? unavailable(d) : `${tabStrip("studio")}<div class="ss-one${(d.activity || []).length ? " has-act" : ""}">${ssDetail(d)}</div>`;
};

/* tags: one look tells you what a session is about and where it stands */
function ssTagList(x, full) {  // full: the session's own header, where tags can be links (a row is already one)
  const out = [], link = (cls, href, text, title) => full && href ? `<a class="tg ${cls}" href="${esc(href)}" target="_blank" rel="noopener noreferrer"${title ? ` title="${esc(title)}"` : ""}>${text}</a>` : `<span class="tg ${cls}"${title ? ` title="${esc(title)}"` : ""}>${text}</span>`;
  const [st, tone] = SS_STATE[x.state] || ["", ""]; if (st) out.push(`<span class="tg ${tone}">${st}</span>`);
  if (x.pr) out.push(link(x.pr.state === "MERGED" ? "merged" : x.pr.state === "CLOSED" ? "bad" : "on", x.pr.url, `PR #${x.pr.number}${x.pr.state === "MERGED" ? " · merged" : x.pr.state === "CLOSED" ? " · closed" : ""}`, "Pull request for this branch"));
  (x.issues || []).forEach(k => out.push(link("", state.linearWs ? `https://linear.app/${state.linearWs}/issue/${k}` : "", esc(k), "Linear issue")));
  if (x.branch && x.branch !== "HEAD") out.push(`<span class="brtag" title="Branch">${esc(x.branch)}</span>`);
  (x.skills || []).slice(0, full ? 6 : 2).forEach(k => out.push(`<span class="tg sk">/${esc(k.replace(/^\//, ""))}</span>`));
  const files = Array.isArray(x.files) ? x.files.length : x.files;
  if (files) out.push(full && x.id ? `<a class="ss-chg" href="#studio/${esc(x.id)}/changes" title="Open every change this session made, as diffs. Select lines there to ask about them or ask for a change.">${icon("diff")}<span>${plural(files, "file")} changed</span>${x.additions || x.deletions ? `<span class="add">+${n_(x.additions)}</span><span class="del">−${n_(x.deletions)}</span>` : ""}<span class="ss-chg-go">View changes${icon("chev")}</span></a>`
    : `<span class="tg" title="${Array.isArray(x.files) ? esc(x.files.join("\n")) : "Files Claude changed"}">${plural(files, "file")} changed</span>`);
  if (x.worktree_name) out.push(`<span class="tg wt" title="Works in this worktree">${icon("folder")}${esc(x.worktree_name)}</span>`);
  const [src, stone] = SS_SRC[x.source] || ["", ""]; if (src) out.push(`<span class="tg ${stone}">${src}</span>`);
  return out.join("");
}

function ssNew(sug) {
  const list = (sug && sug.suggestions || []).slice(0, 4);
  return `<header class="ss-head"><div class="grow"><h1 class="ss-title">New session</h1>
      <div class="ss-tags"><span class="tg">${esc(repoName())}</span><span class="brtag" id="ss-branch" title="The branch Claude will work on"></span><span class="tg wt" id="ss-wt-tag" hidden></span></div></div></header>
    <div class="ss-conv ss-empty">${list.length ? `<div class="ss-quick"><span class="muted small">Suggestions</span>${list.map((x, i) => `<button class="chip ss-sug ${x.tone || ""}" data-sug="${i}" title="${esc(x.title)}"><span class="ss-sug-k">${esc(x.skill)}</span>${esc(x.title.length > 56 ? x.title.slice(0, 54) + "…" : x.title)}</button>`).join("")}</div>` : ""}</div>
    ${ssComposer({ isNew: true })}`;
}

function ssAll(list, unlocked) {
  const f = state.ssFilter || "mine", all = list.sessions || [], lf = liveLabelFilter(list.label_list);
  const view = localStorage.getItem("lfg.ss.view") === "group" ? "group" : "time";
  const pick = all.filter(s => (f === "all" || (f === "background" ? s.source === "background" : s.source !== "background")) && labelHit(s, lf));
  const day = t => { const d = (Date.now() - new Date(t || 0)) / 864e5; return d < 1 ? "Today" : d < 7 ? "This week" : d < 31 ? "This month" : "Earlier"; };
  const groups = {}; pick.forEach(s => (groups[ssLive(s.state) ? "Live here" : day(s.updated)] = groups[ssLive(s.state) ? "Live here" : day(s.updated)] || []).push(s));
  const row = s => `<a class="ss-row" href="#studio/${esc(s.id)}" data-title="${esc((s.title + " " + (s.branch || "") + " " + (s.skills || []).join(" ") + " " + (s.issues || []).join(" ")).toLowerCase())}">
      <span class="grow"><span class="ss-row-t">${esc(s.title)}${labelChips(s)}</span><span class="ss-tags">${ssTagList(s)}${s.folder ? `<span class="tg" title="${s.via === "pr" ? "Joined because it mentions a PR this group follows" : s.via === "ticket" ? "Joined because it names a ticket this group follows" : "Your group"}">${esc(groupPath(s.folder, list.group_info))}</span>` : ""}</span></span>
      ${unlocked ? `<span class="ss-row-act"><button type="button" class="btn small" data-ss-group="${esc(s.id)}">Add to a group…</button><button type="button" class="btn small" data-sess-labels="${esc(s.id)}">Labels…</button></span>` : ""}
      <span class="ss-row-m"><span>${ago(s.updated)}</span>${s.cost ? `<span class="ss-row-c">${money(s.cost)}</span>` : ""}</span></a>`;
  const chip = (k, l, n) => `<button class="pill${f === k ? " on" : ""}" data-ss-filter="${k}">${l} <span class="muted">${n}</span></button>`;
  const vchip = (k, l) => `<button class="pill${view === k ? " on" : ""}" data-ss-view="${k}">${l}</button>`;
  const listOf = rs => `<div class="box ss-list">${rs.map(row).join("")}</div>`;
  const byTime = () => ["Live here", "Today", "This week", "This month", "Earlier"].filter(g => groups[g]).map(g => `<div class="ss-grp">${g}</div>${listOf(groups[g])}`).join("");
  const byGroup = () => {
    const tree = groupTree(pick, list.group_info, lf, { hideEmpty: true }), loose = pick.filter(s => !s.folder);
    return `${tree.length ? `<div class="ss-grp">Groups</div><div class="ss-tree">${treeHtml(tree, { unlocked, listOf, tags: name => groupTags(name, list.group_info), open: () => true })}</div>` : ""}${loose.length ? `<div class="ss-grp">Unsorted</div>${listOf(loose)}` : ""}`;
  };
  return `<section class="ss-allbox"><div class="ss-all-h"><h1>All sessions</h1><a class="btn primary small" href="#studio" data-ss-newbtn>New session</a><input type="search" id="ss-find" placeholder="Search by title, branch, skill or issue" autocomplete="off">
      <span class="seg">${chip("mine", "Yours", all.filter(s => s.source !== "background").length)}${chip("background", "Background", all.filter(s => s.source === "background").length)}${chip("all", "All", all.length)}</span>
      <span class="seg" title="Sort the list by when it was last used, or by your groups">${vchip("time", "By time")}${vchip("group", "By group")}</span>${unlocked ? `<button class="btn small" data-grp-new title="Make a group, inside another group if you like">New group…</button>` : ""}</div>
    ${labelFilterBar(list.label_list, lf)}
    <div class="ss-scrollarea">${(view === "group" ? byGroup() : byTime()) || empty("No sessions yet", "Start one from New session. Sessions from your terminal and the desktop app show up here too.")}</div></section>`;
}

function ssComposer(o) {
  const mode = o.mode || localStorage.getItem("lfg.ss.mode") || "default";
  const seg = (name, opts, cur) => `<span class="seg" role="radiogroup" data-seg="${name}">${opts.map(([k, l, tip]) => `<button type="button" role="radio" aria-checked="${k === cur}" class="pill${k === cur ? " on" : ""}" data-v="${k}" title="${esc(tip)}">${l}</button>`).join("")}</span>`;
  const fork = o.fork ? `<div class="ss-forking">${icon("branch")}<span class="grow">New session from ${o.fork.at ? `before <b>“${esc(o.fork.label)}”</b>` : "this whole conversation"}. This one stays as it is.</span><button class="btn small" data-fork-x>Cancel</button></div>` : "";
  return `<div class="ss-comp" id="ss-comp">
    <div class="ss-ac" id="ss-ac" data-fill data-keep="hidden" hidden></div>${fork}
    <div class="ss-att" id="ss-att" data-fill data-keep="hidden" hidden></div>
    <textarea id="ss-text" rows="1" placeholder="${o.fork ? "What should the new session do?" : o.isNew ? "Describe the task. / for skills, @ for files and folders" : o.saved ? "Write to continue this session here" : "Reply to Claude. / for skills, @ for files"}"></textarea>
    <div class="ss-comp-b"><button type="button" class="icon-btn ss-clip" id="ss-attach" title="Attach files or images. You can also drop them here or paste a screenshot.">${icon("clip")}</button><input type="file" id="ss-file" multiple hidden>
      ${o.isNew ? ssWherePicker() : ""}${o.isNew || o.live ? seg("mode", SS_MODES, mode) : ""}
      <span class="grow"></span><button class="btn primary small" id="ss-send">${o.fork ? "Start fork" : o.isNew ? "Start" : o.saved ? "Continue here" : "Send"}</button></div></div>`;
}

/* Where a new session works: this checkout, a worktree, an existing branch in a worktree of its own, or a new
   worktree forked from a branch. The dashboard's branch picker chooses the default. */
function ssWherePicker() {
  const w = state.sess.where || {}, cur = w.branch || "", picked = state.branch && state.branch !== "-" ? state.branch : "";
  const wts = (w.worktrees || []).filter(x => x.kind === "lfg" || x.kind === "yours");
  const opts = [["here", `Here · ${cur}`]];
  wts.forEach(x => opts.push([`wt:${x.path}`, `Worktree · ${x.branch || x.name}`]));
  if (picked && picked !== cur && !wts.some(x => x.branch === picked)) opts.push([`br:${picked}`, `New worktree · ${picked}`]);
  opts.push(["new", "New worktree, new branch…"]);
  const pw = wts.find(x => x.branch === picked), def = picked && picked !== cur ? (pw ? `wt:${pw.path}` : `br:${picked}`) : "here";
  const branches = (w.branches || []).slice().sort((a, b) => (b === cur) - (a === cur) || (b === w.default) - (a === w.default) || a.localeCompare(b));
  return `<select id="ss-where" class="ss-sel" aria-label="Where Claude works" title="Where Claude works: this checkout, a worktree, or a new one">${opts.map(([v, l]) => `<option value="${esc(v)}"${v === def ? " selected" : ""}>${esc(l)}</option>`).join("")}</select>
    <span class="ss-newwt" hidden><input type="text" id="ss-wt-name" placeholder="lfg/short-name" autocomplete="off" aria-label="New branch name"><select id="ss-wt-base" class="ss-sel" aria-label="Fork it from" title="Fork it from">${branches.map(b => `<option value="${esc(b)}"${b === (picked || cur) ? " selected" : ""}>from ${esc(b)}</option>`).join("")}</select></span>`;
}
/* the branch the new session will work on, as the picker and the sidebar's branch say */
function ssTarget(root) {
  const w = state.sess.where || {}, v = ($("#ss-where", root) || {}).value || "here";
  if (v === "here") return [w.branch || "", ""];
  if (v.startsWith("wt:")) { const x = (w.worktrees || []).find(t => t.path === v.slice(3)); return [x ? x.branch : "", x ? `worktree ${x.name}` : "worktree"]; }
  if (v.startsWith("br:")) return [v.slice(3), "new worktree"];
  const n = ($("#ss-wt-name", root) || {}).value || "";
  return [n.trim() || "new branch", `new worktree, from ${($("#ss-wt-base", root) || {}).value || ""}`];
}
function ssWhereValue(root) {
  const v = ($("#ss-where", root) || {}).value || "here";
  if (v === "here") return { kind: "here" };
  if (v.startsWith("wt:")) return { kind: "worktree", path: v.slice(3) };
  if (v.startsWith("br:")) return { kind: "branch", branch: v.slice(3) };
  return { kind: "new", branch: $("#ss-wt-name", root).value.trim(), base: $("#ss-wt-base", root).value };
}

/* Worktrees: where each stands against the branch it was forked from, and merging it back (committed work only) */
function ssWorktrees(w) {
  const rows = (w && w.worktrees || []).filter(x => x.kind === "lfg" || x.kind === "yours");
  if (!rows.length) return "";
  const byBase = {}; rows.forEach(x => { if (x.base) (byBase[x.base] = byBase[x.base] || []).push(x); });
  const row = x => {
    const can = !x.dirty && x.ahead > 0, why = x.dirty ? `${plural(x.dirty, "uncommitted change")}: commit them in the worktree first` : !x.ahead ? `Nothing to merge into ${x.base}` : `Merge ${plural(x.ahead, "commit")} into ${x.base}`;
    return `<div class="wt-row" data-wt="${esc(x.name)}"><span class="wt-ic">${icon("folder")}</span><span class="grow"><span class="wt-t"><b>${esc(x.name)}</b>${x.kind === "lfg" ? '<span class="tg on">LFG</span>' : '<span class="tg">yours</span>'}</span>
      <span class="ss-tags"><span class="brtag">${esc(x.branch || "detached")}</span>${x.base ? `<span class="muted small">→ ${esc(x.base)}</span>` : ""}${x.ahead ? `<span class="tg ok">${x.ahead} ahead</span>` : ""}${x.behind ? `<span class="tg">${x.behind} behind</span>` : ""}${x.dirty ? `<span class="tg warn">${x.dirty} uncommitted</span>` : ""}${x.sessions ? `<span class="tg">${plural(x.sessions, "session")}</span>` : ""}</span></span>
      <span class="wt-a"><button class="btn small" data-wt-session="${esc(x.path)}">New session here</button>${x.base ? `<button class="btn small" data-wt-merge${can ? "" : " disabled"} title="${esc(why)}">Merge into ${esc(x.base)}</button>` : ""}${x.kind === "lfg" && x.base ? `<button class="btn small" data-wt-merge data-remove${can || (!x.dirty && !x.ahead) ? "" : " disabled"} title="${esc(can ? `Merge into ${x.base}, then remove the worktree and its branch` : !x.dirty ? "Nothing to merge: remove the worktree and its branch" : why)}">${can ? "Merge and remove" : "Remove"}</button>` : ""}</span></div>`;
  };
  const bulk = Object.entries(byBase).filter(([, xs]) => xs.filter(x => x.kind === "lfg").length > 1).map(([b, xs]) => `<div class="wt-bulk"><span class="grow">${plural(xs.filter(x => x.kind === "lfg").length, "LFG worktree")} forked from <b>${esc(b)}</b>. Merge them all back and remove them, here or in a terminal: <code>lfg worktree merge --all --into ${esc(b)} --remove</code></span><button class="btn small" data-wt-all="${esc(b)}">Merge all into ${esc(b)}</button></div>`).join("");
  return `<section class="wt-box"><div class="ss-all-h"><h1>Worktrees</h1><span class="muted small">Branches checked out in their own folders. Only committed work is merged; LFG never commits for you.</span></div>
    <div class="wt-scroll"><div class="box wt-list">${rows.map(row).join("")}</div>${bulk}</div></section>`;
}

/* tools as one readable line each; the input and output open on click */
const TOOL_ICON = { Bash: "code", Read: "docs", Edit: "docs", MultiEdit: "docs", Write: "docs", Grep: "code", Glob: "code", Skill: "skills", Agent: "runs", Task: "runs", WebFetch: "issues", WebSearch: "issues", TodoWrite: "todos", AskUserQuestion: "review" };
const base = p => String(p || "").split("/").pop();
const mcpName = n => { const [, srv, tool] = String(n).split("__"); return [String(srv || "").replace(/^plugin_[^_]+_/, ""), String(tool || "").replace(/_tool$/, "").replace(/_/g, " ")]; };
function toolLine(t) {
  const i = t.input || {}, n = t.name || "?";
  if (n === "Bash") return [`Ran`, `<code>${esc(String(i.command || "").split("\n")[0].slice(0, 140))}</code>`, i.description];
  if (n === "Read") return ["Read", `<code>${esc(base(i.file_path))}</code>`, i.offset ? `from line ${i.offset}` : ""];
  if (n === "Edit" || n === "MultiEdit") return ["Edited", `<code>${esc(base(i.file_path))}</code>`, ""];
  if (n === "Write") return ["Wrote", `<code>${esc(base(i.file_path))}</code>`, `${String(i.content || "").split("\n").length} lines`];
  if (n === "Grep") return ["Searched for", `<code>${esc(i.pattern || "")}</code>`, i.path ? `in ${base(i.path)}` : ""];
  if (n === "Glob") return ["Listed", `<code>${esc(i.pattern || "")}</code>`, ""];
  if (n === "Skill") return ["Used skill", `<b>${esc(i.skill || i.name || "")}</b>`, ""];
  if (n === "Agent" || n === "Task") return ["Sent a subagent", esc(i.description || i.subagent_type || ""), ""];
  if (n === "WebFetch") return ["Fetched", `<code>${esc(i.url || "")}</code>`, ""];
  if (n === "WebSearch") return ["Searched the web for", esc(i.query || ""), ""];
  if (n === "TodoWrite") return ["Updated its to-do list", "", `${(i.todos || []).length} items`];
  if (n === "AskUserQuestion") { const qs = i.questions || []; return ["Asked you", esc(((qs[0] || {}).header || (qs[0] || {}).question || "").slice(0, 120)), qs.length > 1 ? `${qs.length} questions` : ""]; }
  if (n === "ExitPlanMode") return ["Presented a plan", "", t.error ? "you asked for changes" : t.result != null ? "approved" : ""];
  if (/^mcp__/.test(n)) { const [srv, tool] = mcpName(n); return ["Asked", `<b>${esc(srv)}</b>: ${esc(tool)}`, ""]; }
  return [esc(n), "", ""];
}
function toolBody(t) {
  const i = t.input || {};
  let inp = "";
  if ((t.name === "Edit" || t.name === "MultiEdit") && (i.old_string != null || i.edits)) {
    const edits = i.edits || [{ old_string: i.old_string, new_string: i.new_string }];
    inp = `<div class="muted small">${esc(i.file_path || "")}</div>` + edits.slice(0, 4).map(e => `<div class="ss-diff">${String(e.old_string || "").split("\n").slice(0, 12).map(l => `<div class="d-del">- ${esc(l)}</div>`).join("")}${String(e.new_string || "").split("\n").slice(0, 12).map(l => `<div class="d-add">+ ${esc(l)}</div>`).join("")}</div>`).join("");
  } else if (t.name === "Bash") inp = `<pre class="ss-pre">$ ${esc(i.command || "")}</pre>`;
  else if (t.name === "AskUserQuestion") {  // each question with what you picked (Claude Code's result: "Q"="A")
    const got = {}; String(t.result || "").replace(/"([^"]+)"="([^"]*)"/g, (_m, q, a) => { got[q] = a; return ""; });
    return `<div class="ss-qa">${(i.questions || []).map(q => `<div><span class="muted small">${esc(q.header || "")}</span><b>${esc(q.question || "")}</b><span>${got[q.question] != null ? `→ ${esc(got[q.question])}` : t.error ? '<span class="muted">skipped</span>' : '<span class="muted">waiting for you</span>'}</span></div>`).join("")}</div>`;
  } else if (t.name === "ExitPlanMode") return `<div class="md">${md(String(i.plan || ""))}</div>${t.error && t.result ? `<pre class="ss-pre bad">${esc(String(t.result).slice(0, 2000))}</pre>` : ""}`;
  else if (Object.keys(i).length) inp = `<pre class="ss-pre">${esc(JSON.stringify(i, null, 2).slice(0, 4000))}</pre>`;
  const out = t.result != null && t.result !== "" ? `<pre class="ss-pre${t.error ? " bad" : ""}">${esc(String(t.result).slice(0, 6000))}${String(t.result).length > 6000 ? "\n…" : ""}</pre>` : "";
  return inp + out;
}
function ssItems(items, live, pr, chat) {
  let html = "", group = [];
  const flush = last => {
    if (!group.length) return;
    const names = {}; group.forEach(t => { const k = /^mcp__/.test(t.name) ? mcpName(t.name)[0] : t.name; names[k] = (names[k] || 0) + 1; });
    const running = live && last && group.some(t => t.result == null);
    const one = t => { const [verb, what, note] = toolLine(t); return `<details class="ss-tool${t.error ? " bad" : ""}"><summary>${icon(TOOL_ICON[t.name] || (/^mcp__/.test(t.name) ? "integrations" : "code"))}<span class="grow"><span class="ss-verb">${verb}</span> ${what}${note ? ` <span class="muted small">${esc(note)}</span>` : ""}</span>${t.result == null ? (running ? '<span class="spin"></span>' : "") : t.error ? '<span class="tg bad">error</span>' : ""}</summary><div class="ss-tool-b">${toolBody(t)}</div></details>`; };
    html += group.length <= 3 ? `<div class="ss-tools">${group.map(one).join("")}</div>`
      : `<details class="ss-steps"${running ? " open" : ""}><summary><span class="grow">${plural(group.length, "step")} · ${Object.entries(names).map(([k, v]) => `${esc(k)}${v > 1 ? ` ×${v}` : ""}`).join(", ")}</span>${running ? '<span class="spin"></span>' : ""}</summary><div class="ss-tools">${group.map(one).join("")}</div></details>`;
    group = [];
  };
  items.forEach((it, i) => {
    if (it.k === "tool") { group.push(it); return; }
    flush(false);
    if (it.k === "me") html += `<div class="ss-me" data-i="${i}">${(it.images || []).length ? `<div class="ss-imgs">${it.images.map(m => `<button class="ss-img" data-img="${esc(m.u)}:${m.i}" data-fill data-keep="class" title="Show larger"></button>`).join("")}</div>` : ""}${ssMeText(it) ? `<div class="ss-bub">${ssMeText(it)}</div>` : ""}${ssMsgActions(it, i, chat)}</div>`;
    else if (it.k === "skill") html += `<div class="ss-me" data-i="${i}"><div class="ss-bub skill">${icon("skills")}/${esc(it.name.replace(/^\//, ""))}${it.args ? ` <span>${esc(it.args)}</span>` : ""}</div>${ssMsgActions(it, i, chat)}</div>`;
    else if (it.k === "ai") html += `<div class="ss-ai" data-i="${i}"><span class="ss-ai-av">${icon("studio")}</span><div class="md">${md(it.text)}</div>${changedChips(it.changed, pr)}<div class="ss-msg-a"><button class="ss-ma" data-ss-copy="${i}" title="Copy this answer">${icon("copy")}Copy</button>${msgStamp(it.ts)}</div></div>`;
    else if (it.k === "note") html += `<div class="ss-note">${esc(it.text)}</div>`;
  });
  flush(true);
  return html;
}
/* what you sent: uploaded files show as chips, the [Image #n] markers as the images themselves */
/* Lines you pointed at from a session's changes: <lfg-lines file lines>…</lfg-lines> becomes a small diff card, and the
   <lfg-note> (the instruction meant for Claude) is hidden. Messages sent before the tags existed read the same way. */
const SS_OLD_REF = /^About `([^`]+)`, (?:lines? )?([\d-]+|removed lines) \(as this session changed them; the file may have moved on since\):\n\n```diff\n([\s\S]*?)\n```\n\n([\s\S]*?)\n\n(?:This is a question: answer it, don't edit any files\.|Make this change to those lines \(read the file first, it may differ from the snippet\)\.)\s*$/;
function ssRefCard(file, lines, body) {
  const lang = hlLang(file), st = { block: null };
  const rows = body.split("\n").map(l => { const t = l[0] === "+" || l[0] === "-" ? l[0] : " "; return `<div class="ss-ref-l ${t === "+" ? "add" : t === "-" ? "del" : ""}"><span class="ss-ref-s">${t === " " ? "" : t}</span><code>${hlLine(t === " " && l[0] !== " " ? l : l.slice(1), lang, st) || " "}</code></div>`; }).join("");
  return `<div class="ss-ref"><div class="ss-ref-h">${icon("diff")}<b title="${esc(file)}">${esc(file.split("/").pop())}</b><span>${/^\d/.test(lines) ? `${lines.includes("-") ? "lines" : "line"} ${esc(lines)}` : esc(lines)}</span></div><div class="ss-ref-b">${rows}</div></div>`;
}
function ssMeText(it) {
  let raw = it.text || "";
  const old = raw.match(SS_OLD_REF);
  if (old) raw = `<lfg-lines file="${old[1]}" lines="${old[2]}">\n${old[3]}\n</lfg-lines>\n\n${old[4]}`;
  const cards = [];
  raw = raw.replace(/<lfg-lines file="([^"]*)" lines="([^"]*)">\n?([\s\S]*?)\n?<\/lfg-lines>\s*/g, (_m, f, l, b) => { cards.push(ssRefCard(f, l, b)); return `\u0000${cards.length - 1}\u0000`; })
    .replace(/\s*<lfg-note>[\s\S]*?<\/lfg-note>\s*/g, "").replace(/\s*<lfg-review\b[^>]*>[\s\S]*?<\/lfg-review>\s*/g, "");
  let t = esc(raw).replace(/\u0000(\d+)\u0000/g, (_m, k) => cards[+k]);
  if ((it.images || []).length) t = t.replace(/\[Image #\d+\]\s?/g, "");
  t = t.replace(/@(\/\S*?\/\.lfg\/uploads\/\d{8}\/[0-9a-f]{8}-(\S+))/g, (_m, path, name) => `<span class="ss-file" title="${path}">${icon("docs")}${name}</span>`);
  return t.trim();
}
/* each of your messages: Rewind to before it, Fork from before it (a new session), Copy (as in Claude Code) */
/* When a message was sent, on the message: the time today, the date and time before that (with the year when it isn't
   this one). Hover for the full date. */
function msgStamp(ts) {
  const d = ts ? new Date(ts) : null;
  if (!d || isNaN(d)) return "";
  const now = new Date(), time = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  const day = d.toDateString() === now.toDateString() ? "" : d.toLocaleDateString([], { month: "short", day: "numeric", ...(d.getFullYear() === now.getFullYear() ? {} : { year: "numeric" }) }) + ", ";
  return `<time class="msg-ts" datetime="${esc(d.toISOString())}" title="${esc(d.toLocaleString([], { dateStyle: "full", timeStyle: "medium" }))}">${esc(day + time)}</time>`;
}
function ssMsgActions(it, i, chat) {
  const rw = it.u && !chat ? `<button class="ss-ma" data-rw="${esc(it.u)}" title="Undo the conversation from here, the code Claude changed since, or both">${icon("rewind")}Rewind</button>` : "";
  const fk = it.u && it.p && !chat ? `<button class="ss-ma" data-fork="${i}" title="A new session with the conversation up to here; this one stays as it is">${icon("branch")}Fork</button>` : "";
  return `<div class="ss-msg-a">${msgStamp(it.ts)}${rw}${fk}<button class="ss-ma" data-ss-copy="${i}" title="Copy">${icon("copy")}Copy</button></div>`;
}
const ssItemText = it => it.k === "skill" ? `/${it.name.replace(/^\//, "")}${it.args ? " " + it.args : ""}` : it.k === "tool" ? `${it.name} ${JSON.stringify(it.input || {})}` : it.k === "ai" ? copyText(it.text) : (it.text || "").replace(/\[Image #\d+\]\s?/g, "").replace(/\s*<lfg-review\b[^>]*>[\s\S]*?<\/lfg-review>\s*/g, "");
function ssMarkdown(d) {  // Export: the conversation as Markdown, like /export
  const out = [`# ${d.title}`, "", [d.branch && `Branch: ${d.branch}`, d.updated && `Updated: ${new Date(d.updated).toLocaleString()}`, `Session: ${d.id}`].filter(Boolean).join(" · "), ""];
  (d.items || []).forEach(it => {
    if (it.k === "me" || it.k === "skill") out.push(`## You`, "", ssItemText(it), "");
    else if (it.k === "ai") out.push(`## Claude`, "", it.text, "");
    else if (it.k === "tool") { const [verb, what] = toolLine(it); out.push(`- ${verb} ${what.replace(/<[^>]+>/g, "")}${it.error ? " (error)" : ""}`); }
    else if (it.k === "note") out.push("", `*${it.text}*`, "");
  });
  return out.join("\n").replace(/\n{3,}/g, "\n\n");
}
function ssDownload(name, text) {
  const a = document.createElement("a"), url = URL.createObjectURL(new Blob([text], { type: "text/markdown" }));
  a.href = url; a.download = name; document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 2000);
}
async function ssImages(root, id) {  // images in messages come from the transcript, one request each, kept for the page
  state.ssImg = state.ssImg || {};
  for (const b of $$(".ss-img[data-img]", root)) {
    if (b.firstChild) continue;
    const key = b.dataset.img, [u, i] = key.split(":");
    if (!state.ssImg[key]) { const r = await api("studio_image", { id: id || state.sess.id, u, i }).catch(() => null); if (!r || !r.src) continue; state.ssImg[key] = r.src; }
    const img = new Image(); img.alt = "Image you sent"; img.src = state.ssImg[key]; b.append(img);
  }
}
/* How full the context window is, like /context: a pill in the header, and under it a grid of 100 cells, one per
   percent of the window, coloured by what fills it. Once a session passes about 100k tokens it says so plainly,
   because every new message resends all of it. */
const SS_CTX_LONG = 100000;
/* the 100 cells: [part index], "reserved" or "free"; every part that has tokens gets at least one cell */
function ssCtxCells(c) {
  const max = c.max || 0, n = v => max ? Math.round((v || 0) / max * 100) : 0;
  const parts = (c.parts || []).map(p => Math.max(1, n(p.tokens)));
  const res = c.reserved ? Math.max(1, n(c.reserved)) : 0;
  let over = parts.reduce((a, b) => a + b, 0) + res - 100;
  for (let i = parts.length - 1; over > 0 && i >= 0; i--) { const cut = Math.min(over, parts[i] - 1); parts[i] -= cut; over -= cut; }
  const cells = [];
  parts.forEach((k, i) => { for (let j = 0; j < k; j++) cells.push(i); });
  const free = Math.max(0, 100 - cells.length - res);
  for (let j = 0; j < free; j++) cells.push("free");
  for (let j = 0; cells.length < 100; j++) cells.push("reserved");
  return cells.slice(0, 100);
}
const ssTok = v => v >= 1000 ? `${Math.round(v / 100) / 10}k`.replace(".0k", "k") : String(v || 0);
function ssCtxHtml(c) {
  if (!c || c.percent == null) return "";
  const long = (c.used || 0) >= SS_CTX_LONG, parts = c.parts || [];
  const cells = ssCtxCells(c).map(k => `<i class="ctx-c ${typeof k === "number" ? "c" + (k % 8) : k}"></i>`).join("");
  const row = (cls, name, tok) => `<li><i class="ctx-c ${cls}"></i><span class="grow">${esc(name)}</span><span class="mono">${(tok || 0).toLocaleString()}</span><span class="muted small ctx-pc">${c.max ? Math.max(0.1, Math.round(tok / c.max * 1000) / 10) : 0}%</span></li>`;
  const legend = parts.map((p, i) => row("c" + (i % 8), p.name, p.tokens)).join("") + (c.free ? row("free", "Free space", c.free) : "") + (c.reserved ? row("reserved", "Kept back for compacting", c.reserved) : "");
  const warn = long ? `<div class="ctx-warn">${dot("warn")}<span><b>This session is long (${ssTok(c.used)} tokens).</b> Every new message sends all of it again, so replies get slower and cost more. Compact it, or start a new session for something different.</span><button class="btn small" data-ctx-compact>Compact now</button></div>` : "";
  return `<details class="ss-ctx-box"><summary class="ss-ctx${long ? " long" : c.percent >= 70 ? " warn" : ""}" title="What fills this session's context window. Click for the breakdown."><i style="--p:${Math.min(100, c.percent)}%"></i>${c.percent}% context${long ? ` · long: ${ssTok(c.used)} tokens` : ""}</summary>
    <div class="ctx-pop"><div class="ctx-h"><b>${(c.used || 0).toLocaleString()}</b> of ${(c.max || 0).toLocaleString()} tokens used${c.auto_compact_at ? `<span class="muted small"> · compacts by itself near ${c.auto_compact_at.toLocaleString()}</span>` : ""}</div>${warn}
      <div class="ctx-grid" role="img" aria-label="${c.percent}% of the context window is used">${cells}</div><ul class="ctx-legend">${legend}</ul>
      <div class="muted small">Each square is 1% of the window.</div></div></details>`;
}
/* Claude's questions (AskUserQuestion): pick an option per question (or several, for multi-select), or write your
   own answer; it goes back as Claude Code's own picker sends it. Picks survive the page redrawing. */
function ssQuestion(p) {
  const qs = (p.input && p.input.questions) || [], picked = ((state.ssAns = state.ssAns || {})[p.id] = state.ssAns[p.id] || {});
  const one = (q, qi) => {
    const multi = !!q.multiSelect, cur = picked[qi] || { labels: [], other: "" }, name = `q-${p.id}-${qi}`;
    const opt = (o, oi) => `<label class="ss-q-o${cur.labels.includes(o.label) ? " on" : ""}"><input type="${multi ? "checkbox" : "radio"}" name="${esc(name)}" data-q="${qi}" data-opt="${esc(o.label)}"${cur.labels.includes(o.label) ? " checked" : ""}>
      <span class="ss-q-k">${multi ? "" : oi + 1}</span><span class="grow"><b>${esc(o.label)}</b>${o.description ? `<span>${esc(o.description)}</span>` : ""}</span></label>`;
    return `<fieldset class="ss-q" data-qi="${qi}"><legend>${q.header ? `<span class="tg">${esc(q.header)}</span>` : ""}<span class="ss-q-t">${esc(q.question)}</span>${multi ? '<span class="muted small">Pick any</span>' : ""}</legend>
      <div class="ss-q-os">${(q.options || []).map(opt).join("")}
        <label class="ss-q-o ss-q-other${cur.other ? " on" : ""}"><input type="${multi ? "checkbox" : "radio"}" name="${esc(name)}" data-q="${qi}" data-opt="__other"${cur.other ? " checked" : ""}><span class="ss-q-k">${multi ? "" : "✎"}</span><span class="grow"><b>Something else</b><input type="text" class="ss-q-in" data-q-other="${qi}" placeholder="Type your own answer" value="${esc(cur.other)}"></span></label></div></fieldset>`;
  };
  // several questions: one tab each, Next moves on, so the card stays one question tall
  const many = qs.length > 1, tab = Math.min(((state.ssQTab = state.ssQTab || {})[p.id]) || 0, qs.length - 1);
  const tabs = many ? `<div class="ss-q-tabs" role="tablist">${qs.map((q, qi) => `<button type="button" role="tab" class="ss-q-tab${qi === tab ? " on" : ""}" data-q-tab="${qi}" aria-selected="${qi === tab}"><span class="ss-q-done" aria-hidden="true"></span>${esc(q.header || `Question ${qi + 1}`)}</button>`).join("")}</div>` : "";
  return `<div class="ss-ask ss-ask-q${many ? " many" : ""}" data-req="${esc(p.id)}" data-kind="question"><div class="ss-ask-h">${icon("review")}<span class="grow">Claude has ${many ? `${qs.length} questions` : "a question"} for you</span></div>
    ${tabs}${qs.map((q, qi) => one(q, qi).replace("<fieldset ", `<fieldset${many && qi !== tab ? " hidden" : ""} `)).join("")}
    <div class="ss-ask-a">${many ? '<button class="btn small" data-q-back>Back</button><button class="btn primary small" data-q-next>Next</button>' : ""}<button class="btn primary small" data-q-send disabled${many && tab < qs.length - 1 ? " hidden" : ""}>${many ? "Send answers" : "Send answer"}</button><button class="btn small" data-decide="skip" title="Claude carries on with its best guess and says what it assumed">Skip</button><span class="muted small" data-q-left></span></div></div>`;
}
/* Claude's plan (ExitPlanMode): read it, then approve it or say what to change */
function ssPlan(p) {
  return `<div class="ss-ask ss-ask-plan" data-req="${esc(p.id)}" data-kind="plan"><div class="ss-ask-h">${icon("runs")}<span class="grow"><b>Claude's plan</b>, ready for you</span></div>
    <div class="md ss-plan">${md(String((p.input || {}).plan || ""))}</div>
    <textarea class="ss-plan-fb" rows="2" placeholder="What should change? (only needed for Keep planning)"></textarea>
    <div class="ss-ask-a"><button class="btn primary small" data-decide="approve">Approve plan</button><button class="btn small" data-plan-revise>Keep planning</button></div></div>`;
}
function ssPending(d) {
  return (d.pending || []).map(p => {
    if (p.kind === "question") return ssQuestion(p);
    if (p.kind === "plan") return ssPlan(p);
    const t = { name: p.tool, input: p.input }, [verb, what] = toolLine(t), label = /^mcp__/.test(p.tool) ? mcpName(p.tool).join(": ") : p.tool;
    return `<div class="ss-ask" data-req="${esc(p.id)}"><div class="ss-ask-h">${icon("checks")}<span class="grow">Claude wants to <b>${verb.toLowerCase()}</b> ${what}</span></div>
      ${p.description ? `<div class="muted small">${esc(p.description)}</div>` : ""}<div class="ss-tool-b">${toolBody(t)}</div>
      <div class="ss-ask-a"><button class="btn primary small" data-decide="once">Allow once</button>${p.can_remember ? `<button class="btn small" data-decide="always" title="Saved in your Claude Code settings, like choosing it in a terminal">Always allow ${esc(label)}</button>` : ""}<button class="btn small" data-decide="session">Allow for this session</button><button class="btn small bad" data-decide="deny">Deny</button></div></div>`;
  }).join("");
}
function ssFollowups(d) {
  if (d.state !== "idle" || d.pending && d.pending.length) return "";
  const out = [];
  if ((d.files || []).length) { out.push(["/lfg:check", "Check these changes", "/lfg:check the changes from this session"]); out.push(["/lfg:review-coach", "Review the changes", "/lfg:review-coach review the changes from this session"]); }
  if (d.pr && d.pr.state === "OPEN" && (d.files || []).length) out.push(["/lfg:ship", `Get PR #${d.pr.number} ready`, `/lfg:ship PR #${d.pr.number}`]);
  out.push(["", "Summarize what changed", "Summarize what you changed in this session and anything left to do, in a few bullets."]);
  return `<div class="ss-follow"><span class="muted small">Next</span>${out.map(([k, l, p]) => `<button class="chip" data-follow="${esc(p)}">${k ? `<span class="ss-sug-k">${esc(k)}</span>` : ""}${esc(l)}</button>`).join("")}</div>`;
}
function ssConv(d, chat) {  // chat: on a review's page, where there is no Rewind or Fork and no suggested next steps
  const live = ssLive(d.state);
  return `${ssItems(d.items || [], live, (d.review || {}).pr, chat)}${(d.queued || []).map(q => `<div class="ss-me"><div class="ss-bub queued">${esc(q)}<span class="muted small"> · goes in when Claude is ready</span></div></div>`).join("")}
    ${ssPending(d)}${d.state === "working" || d.state === "starting" ? `<div class="ss-working"><span class="ss-pulse"></span> Claude is working… <button class="btn small" data-ss-interrupt>Stop</button></div>` : ""}
    ${d.error ? `<div class="callout bad small">${fmtWhy(d.error)}</div>` : ""}${ssOutside(d)}${chat ? "" : ssFollowups(d)}${!(d.items || []).length && !live && !chat ? empty("Nothing to show", "This session has no messages yet.") : ""}`;
}
/* Somebody carried on with this session in another window (a terminal, the desktop app) while it runs here. The
   process here read the conversation when it started and never again, so without a reload it would answer from its
   older copy and split the session in two. The server reloads it before the next message; this says so. */
function ssOutside(d) {
  const o = d.outside;
  if (!o) return "";
  return `<div class="callout warn small ss-outside">You carried on with this session in ${esc(o.where)} ${ago(o.ts)}${o.compacted ? " and compacted it there" : ""}. The studio hasn't seen that yet: it is still working from its copy from before. Your next message here reloads it first, so it picks up where ${esc(o.where)} left off. Use one window at a time, or the two copies drift apart again. <button class="btn small" data-ss-reload>Reload now</button></div>`;
}
function ssHead(d) {
  const model = String(d.model || "").replace(/^claude-/, "").replace(/-(\d)-(\d)$/, " $1.$2").replace(/^./, c => c.toUpperCase());
  return `<div class="grow"><h1 class="ss-title" title="Click to rename" data-ss-rename>${esc(d.title)}</h1>
      <div class="ss-tags">${ssTagList(d, true)}${model ? `<span class="tg">${esc(model)}</span>` : ""}${d.via === "headroom" ? '<span class="tg on">via Headroom</span>' : ""}</div></div>
    <div class="ss-head-a">${ssLive(d.state) ? ssCtxHtml((state.ssCtx || {})[d.id]) : ""}${d.cost ? `<span class="ss-cost" title="What this session has cost so far">${money(d.cost)}</span>` : ""}${ssLive(d.state) ? `<button class="btn small" data-ss-end title="End the Claude Code process; you can continue the session later">End</button>` : ""}
      <button class="icon-btn ss-more" data-ss-more data-keep="aria-expanded" aria-haspopup="menu" aria-expanded="false" title="More">${icon("more")}</button>
      <div class="ss-menu" role="menu" data-keep="hidden" hidden>
        <button role="menuitem" data-menu="fork">${icon("branch")}Fork session</button>
        <button role="menuitem" data-menu="compact">${icon("compress")}Compact conversation</button>
        <hr><button role="menuitem" data-menu="export">${icon("download")}Export as Markdown</button>
        <button role="menuitem" data-menu="resume">${icon("terminal")}Copy terminal command</button>
        <button role="menuitem" data-menu="rename">${icon("docs")}Rename</button></div></div>`;
}
function ssDetail(d) {
  const live = ssLive(d.state), fork = state.ssFork && state.ssFork.sid === d.id ? state.ssFork : null;
  return `<header class="ss-head" id="ss-head">${ssHead(d)}</header>
    <div class="ss-conv${d.state === "working" || d.state === "starting" || (d.pending || []).length ? " ss-busy" : ""}" id="ss-conv">${ssConv(d)}</div>
    ${ssComposer({ live, saved: !live, mode: d.mode, fork })}
    <aside class="ss-act" id="ss-act" aria-label="Running in the background" aria-live="polite">${ssAct(d)}</aside>`;
}

/* Beside the conversation: the subagents and background commands this session has going, so you can see Claude
   isn't idle (or that something is still running after it went quiet). Running first, then what just finished. */
const SS_ACT = { running: ["Running", "run"], quiet: ["No news for 15 min", "quiet"], done: ["Done", "ok"], failed: ["Failed", "bad"], stopped: ["Stopped", "off"] };
function ssAct(d) {
  const xs = (d.activity || []).slice().sort((a, b) => (a.status === "running" ? 0 : a.status === "quiet" ? 1 : 2) - (b.status === "running" ? 0 : b.status === "quiet" ? 1 : 2));
  if (!xs.length) return "";
  // an accordion: the panel folds to its header line, and each item folds to one line (its details on open).
  // What's open is kept across the page's refreshes, and the panel's fold in this browser.
  const open = state.ssActOpen = state.ssActOpen || new Set();
  let shut = false; try { shut = localStorage.getItem("lfg.ssAct.shut") === "1"; } catch (e) { /* private window */ }
  const n = xs.filter(a => a.status === "running").length, done = xs.length - n;
  const row = a => {
    const [word, cls] = SS_ACT[a.status] || [a.status, "off"];
    const kind = a.kind === "agent" ? `${a.type ? esc(a.type) : "Subagent"}${a.background ? " · background" : ""}` : a.kind === "command" ? "Background command" : `Background ${esc(a.tool || "task")}`;
    const when = a.status === "running" || a.status === "quiet" ? `started ${ago(a.started)}` : ago(a.ended);
    return `<details class="ss-act-i ${cls}" data-act="${esc(a.id)}"${open.has(a.id) ? " open" : ""}><summary><span class="ss-act-dot" aria-hidden="true"></span><b title="${esc(a.label)}">${esc(a.label)}</b><span class="ss-act-st">${word === "Running" ? (a.steps ? plural(a.steps, "step") : "") : word}</span><span class="ss-act-chev">${icon("chev")}</span></summary>
      <div class="ss-act-d"><div class="ss-act-k">${icon(a.kind === "agent" ? "agent" : "terminal")}<span>${kind}</span></div>
      ${a.now && (a.status === "running" || a.status === "quiet") ? `<span class="ss-act-now" title="${esc(a.now)}">${esc(a.now)}</span>` : ""}
      ${a.summary && a.status !== "running" ? `<span class="ss-act-now" title="${esc(a.summary)}">${esc(a.summary)}</span>` : ""}
      <span class="ss-act-m">${a.steps ? `${plural(a.steps, "step")} · ` : ""}${when}</span></div></details>`;
  };
  return `<button type="button" class="ss-act-h" data-act-fold aria-expanded="${!shut}"><span class="ss-act-chev">${icon("chev")}</span><b>${n ? `${n} running` : "Background work"}</b><span class="muted small">${[n ? "" : "nothing running", done ? `${done} finished` : ""].filter(Boolean).join(" · ")}</span></button>
    <div class="ss-act-list"${shut ? " hidden" : ""}>${xs.map(row).join("")}</div>`;
}
/* the accordion's clicks: delegated, so they keep working after each refresh redraws the panel */
function wireAct(box) {
  if (!box || !once(box, "act")) return;  // not a data- flag: that would make redraws leave the list alone
  box.addEventListener("click", e => {
    const h = e.target.closest("[data-act-fold]");
    if (!h) return;
    const list = $(".ss-act-list", box), shut = !list.hidden;
    list.hidden = shut; h.setAttribute("aria-expanded", String(!shut));
    try { localStorage.setItem("lfg.ssAct.shut", shut ? "1" : "0"); } catch (err) { /* private window */ }
  });
  box.addEventListener("toggle", e => {
    const it = e.target.closest && e.target.closest("[data-act]");
    if (!it) return;
    const open = state.ssActOpen = state.ssActOpen || new Set();
    it.open ? open.add(it.dataset.act) : open.delete(it.dataset.act);
  }, true);
}

/* a file for a message: big images are scaled down first (to 2000px and under ~3.5 MB, as Claude Code does) */
async function ssPrepFile(f) {
  let blob = f, type = f.type || "";
  if (/^image\/(png|jpeg|webp)$/.test(type)) {
    const img = await createImageBitmap(f).catch(() => null);
    if (img && (Math.max(img.width, img.height) > 2000 || f.size > 3.5e6)) {
      const k = Math.min(1, 2000 / Math.max(img.width, img.height)), c = document.createElement("canvas");
      c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
      c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
      blob = await new Promise(ok => c.toBlob(ok, "image/jpeg", 0.88)); type = "image/jpeg";
    }
  }
  if (blob.size > 20 * 1024 * 1024) throw new Error("files can be up to 20 MB");
  const url = await new Promise((ok, no) => { const r = new FileReader(); r.onload = () => ok(String(r.result)); r.onerror = () => no(new Error("couldn't read it")); r.readAsDataURL(blob); });
  return { type, data: url.slice(url.indexOf(",") + 1), thumb: /^image\/(png|jpeg|gif|webp)$/.test(type) ? url : "" };
}

/* the composer: / for skills, @ for files and folders, ↑↓ to pick, Enter or Tab to take, Escape to close */
const SK_GROUP = { plugin: "LFG and plugins", project: "This project", personal: "Your skills", builtin: "Claude Code" };
async function ssSkills() {
  if (!state.ssSkillList) {
    const d = await api("allskills");
    state.ssSkillList = (d.skills || []).filter(x => x.invoke).map(x => ({ v: x.invoke, d: x.description || "", g: SK_GROUP[x.source] || "Other", lfg: /^\/lfg:/.test(x.invoke) }))
      .sort((a, b) => (b.lfg - a.lfg) || a.g.localeCompare(b.g) || a.v.localeCompare(b.v));
  }
  return state.ssSkillList;
}
function ssAutocomplete(ta, box) {
  let items = [], at = 0, tok = null, timer = null, total = 0;
  const close = () => { box.hidden = true; items = []; tok = null; };
  const paint = () => {
    if (!tok) return close();
    box.hidden = false;
    const head = tok.kind === "/" ? `<b>Skills</b><span>${items.length}${items.length === 1 ? " skill" : " skills"} · type to filter</span>` : `<b>Files and folders</b><span>${total > items.length ? `${items.length} of ${total} · keep typing to narrow` : `${items.length} found`}</span>`;
    let group = "";
    box.innerHTML = `<div class="ss-ac-h">${head}<span class="grow"></span><span class="ss-keys"><kbd>↑</kbd><kbd>↓</kbd> choose <kbd>↵</kbd> add <kbd>esc</kbd> close</span></div><div class="ss-ac-l">${items.length ? items.map((x, i) => {
      const g = x.g && x.g !== group ? (group = x.g, `<div class="ss-ac-g">${esc(x.g)}</div>`) : "";
      const isDir = tok.kind === "@" && x.v.endsWith("/"), name = tok.kind === "@" ? x.v.replace(/\/$/, "").split("/").pop() + (isDir ? "/" : "") : x.v, dir = tok.kind === "@" ? x.v.replace(/\/$/, "").split("/").slice(0, -1).join("/") : "";
      return `${g}<button type="button" class="ss-ac-i${i === at ? " on" : ""}" data-i="${i}">${tok.kind === "@" ? `<span class="ss-ac-ic">${icon(isDir ? "folder" : "docs")}</span>` : ""}<span class="ss-ac-t"><b>${esc(name)}</b>${tok.kind === "@" ? (dir ? `<span>${esc(dir)}</span>` : "") : x.d ? `<span>${esc(x.d.slice(0, 110))}</span>` : ""}</span></button>`;
    }).join("") : `<div class="ss-ac-none">${tok.kind === "/" ? "No skill matches that." : "No file or folder matches that."}</div>`}</div>`;
    $$(".ss-ac-i", box).forEach(b => b.onmousedown = e => { e.preventDefault(); take(+b.dataset.i); });
    const on = $(".ss-ac-i.on", box); if (on) on.scrollIntoView({ block: "nearest" });
  };
  const take = i => {
    const x = items[i]; if (!x || !tok) return;
    const before = ta.value.slice(0, tok.start), after = ta.value.slice(ta.selectionStart);
    const ins = (tok.kind === "@" ? "@" + x.v : x.v) + (tok.kind === "@" && x.v.endsWith("/") ? "" : " ");
    ta.value = before + ins + after; ta.selectionStart = ta.selectionEnd = before.length + ins.length; ta.focus();
    if (tok.kind === "@" && x.v.endsWith("/")) { update(); return; }  // a folder: keep going inside it, or press space
    close(); ta.dispatchEvent(new Event("input"));
  };
  const update = async () => {
    const upto = ta.value.slice(0, ta.selectionStart), m = /(^|\s)([/@])([^\s]*)$/.exec(upto);
    if (!m) return close();
    const mine = tok = { kind: m[2], start: upto.length - m[3].length - 1, q: m[3].toLowerCase() };
    if (mine.kind === "/") {
      if (mine.q.includes("/")) return close();  // a path like /tmp/x, not a skill
      const found = (await ssSkills()).filter(x => (x.v + " " + x.d).toLowerCase().includes(mine.q));
      if (tok !== mine) return;  // the text moved on while the list loaded
      items = found; total = found.length; at = 0; return paint();
    }
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const r = await api("studio_files", { q: mine.q });
      if (tok !== mine) return;
      items = (r.files || []).map(f => ({ v: f })); total = r.total || items.length; at = 0; paint();
    }, 120);
  };
  ta.addEventListener("input", update);
  ta.addEventListener("click", update);
  ta.addEventListener("keydown", e => {
    if (box.hidden || !items.length) { if (!box.hidden && e.key === "Escape") { e.preventDefault(); close(); } return; }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); at = (at + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length; $$(".ss-ac-i", box).forEach((b, i) => b.classList.toggle("on", i === at)); $(".ss-ac-i.on", box).scrollIntoView({ block: "nearest" }); }
    else if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); e.stopImmediatePropagation(); take(at); }
    else if (e.key === "Escape") { e.preventDefault(); close(); }
  }, true);
  box.addEventListener("mousedown", e => e.preventDefault());  // scrolling or clicking the list keeps the cursor in the text
  ta.addEventListener("blur", () => setTimeout(close, 150));
}

/* Studio screens fill the window exactly: the page never scrolls, their own parts do */
function ssFit(root) {
  const box = $(".ss-one, .ss-page", root), view = $("#view");
  if (!box) return;
  window.scrollTo(0, 0);
  // Text size zooms #view: the box's position is measured on screen, but --ss-h is set in the zoomed CSS pixels
  const zoom = parseFloat(getComputedStyle(view).zoom) || 1, pad = (parseFloat(getComputedStyle(view).paddingBottom) || 0) * zoom;
  box.style.setProperty("--ss-h", Math.max(360, Math.floor((window.innerHeight - box.getBoundingClientRect().top - pad - 2) / zoom)) + "px");
}
window.addEventListener("resize", () => { if ((location.hash.slice(1) || "").split("/")[0] === "studio") ssFit(document); });

/* What one session changed: every file it edited or created, as diffs, from its own transcript. The same diff view as
   Reviews (file tree, folding, filter), read-only. Shell commands that may also have changed files are listed. */
async function ssChanges(id) {
  const [c, d] = await Promise.all([api("studio_changes", { id }), api("studio_session", { id }).catch(() => ({}))]);
  state.sess = { d: null, id: null, changes: true };
  crumbs("studio", d && d.title ? d.title : "Session", `#studio/${id}`);
  const back = `<a class="btn small" href="#studio/${esc(id)}">${icon("back")}Back to the session</a>`;
  if (!c || c.available === false) return `<div class="ssc">${back}${unavailable(c || {})}</div>`;
  // files outside the project (scratch notes, another repo) go under their own folder in the tree; files in one of
  // the project's worktrees go under that worktree's name
  const files = c.files.map(f => f.outside ? Object.assign({}, f, { path: "Outside this project/" + f.path.split("/").pop(), full: f.path })
    : f.worktree ? Object.assign({}, f, { path: `${f.worktree} (worktree)/${f.path}`, full: f.path }) : f);
  state.sscFiles = Object.fromEntries(files.map(f => [f.path, f.full || f.path]));  // shown path -> the real one
  state.dfOpen = { n: "ss-" + id, paths: [], shut: [], filter: "" };
  const total = files.reduce((a, f) => a + f.hunks.reduce((b, h) => b + h.lines.length, 0), 0);
  const body = files.map((f, i) => diffFile(f, i, [], total <= 3000 || i < 4)).join("");
  const shell = c.shell.length ? `<details class="box ssc-sh"><summary><b>${plural(c.shell.length, "shell command")}</b> that can also change files <span class="muted small">(sed, scripts, installs, formatters: these aren't recorded as edits, so check git for what they did)</span></summary>
    <ul>${c.shell.slice().reverse().map(x => `<li><code>${esc(x.command)}</code><span class="muted small">${ago(x.ts)}</span></li>`).join("")}</ul></details>` : "";
  return `<div class="ssc"><div class="ssc-h">${back}<div class="grow"><h1>What this session changed</h1>
      <p class="muted">${esc(d && d.title || "")}${d && d.title ? " · " : ""}${plural(files.length, "file")} · <span class="add">+${n_(c.additions)}</span> <span class="del">−${n_(c.deletions)}</span> · from the session's own record, so it shows exactly what Claude edited here, even after commits</p></div></div>
    ${shell}
    ${files.length ? `<p class="muted small df-note">Drag down the line numbers, or click one and shift-click another, to ask about those lines or ask for a change. It goes into this same session, with the file and lines pointed out.</p>` : ""}
    ${files.length ? `<div class="df"><aside class="df-side"><div class="df-filter"><input type="search" id="df-filter" placeholder="Filter files…" aria-label="Filter files"></div>
      <div class="df-sum">${plural(files.length, "file")} · <span class="add">+${n_(c.additions)}</span> <span class="del">−${n_(c.deletions)}</span></div>
      <div class="df-tree" id="df-tree">${diffTree(files, {})}</div></aside><div class="df-main">${body}</div></div>` : empty("No file edits in this session", "Claude didn't edit or create files here. Shell commands, if any, are listed above.")}</div>`;
}
function wireSessChanges(root) {
  const id = (location.hash.match(/^#studio\/([0-9a-f-]{36})\/changes/) || [])[1];
  // select lines (drag down the numbers, or click then shift-click), then ask about them or ask for an edit: it goes
  // into this same session as the next message, with the file, the lines and what they say, so Claude knows exactly
  // what you mean
  let sel = null, dragging = false;
  const rowsOf = table => $$(".df-l", table);
  const range = () => { const rows = rowsOf(sel.table), i = rows.indexOf(sel.a), j = rows.indexOf(sel.b); return rows.slice(Math.min(i, j), Math.max(i, j) + 1); };
  const clear = () => $$(".df-l.sel", root).forEach(r => r.classList.remove("sel"));
  const mark = () => { clear(); if (sel) range().forEach(r => r.classList.add("sel")); };
  const compose = () => {
    $$(".df-compose", root).forEach(r => r.remove());
    if (!sel || !id) return;
    const rows = range(), path = state.sscFiles[sel.table.dataset.path] || sel.table.dataset.path;
    const nums = rows.map(r => +(r.dataset.k.startsWith("R") ? r.dataset.k.slice(1) : NaN)).filter(n => !isNaN(n));
    const where = nums.length ? (nums[0] === nums[nums.length - 1] ? `line ${nums[0]}` : `lines ${nums[0]}-${nums[nums.length - 1]}`) : "removed lines";
    const tr = document.createElement("tr");
    tr.className = "df-compose";
    tr.innerHTML = `<td colspan="4"><div class="th th-ask"><div class="th-h"><span class="th-lines">${icon("review")}${esc(path.split("/").pop())}, ${esc(where)} · goes to this session</span></div>
      <textarea rows="3" placeholder="Ask about these lines, or say what to change: rename this, handle the empty case, why a sliding window?"></textarea>
      <div class="df-reply"><span class="muted small">⌘ Enter asks · Claude gets the file, the lines and this text</span><span class="grow"></span><button class="btn small" data-ssc-cancel>Cancel</button><button class="btn small" data-ssc-send="ask">Ask</button><button class="btn small primary" data-ssc-send="edit">Make this change</button></div></div></td>`;
    rows[rows.length - 1].after(tr);
    const ta = $("textarea", tr); ta.focus();
    const cancel = () => { sel = null; clear(); tr.remove(); };
    ta.onkeydown = e => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) $('[data-ssc-send="ask"]', tr).click(); if (e.key === "Escape") cancel(); };
    $("[data-ssc-cancel]", tr).onclick = cancel;
    $$("[data-ssc-send]", tr).forEach(b => b.onclick = async () => {
      if (!ta.value.trim()) return ta.focus();
      const snippet = rows.slice(0, 80).map(r => { const t = r.classList.contains("add") ? "+" : r.classList.contains("del") ? "-" : " "; return t + ($(".df-c", r) || r.lastElementChild).textContent; }).join("\n");
      const edit = b.dataset.sscSend === "edit";
      // Claude gets the file, the lines and an instruction; the chat shows only the lines (as a diff) and your words
      const span = where.replace(/^lines? /, "");
      const text = `<lfg-lines file="${path.replace(/"/g, "")}" lines="${span}">\n${snippet}${rows.length > 80 ? "\n… (" + (rows.length - 80) + " more lines selected)" : ""}\n</lfg-lines>\n\n${ta.value.trim()}\n\n<lfg-note>${edit ? `Make this change to ${where} of ${path} (read the file first: the lines above are as this session changed them, and it may differ now).` : `This is a question about ${where} of ${path}, as this session changed them (the file may differ now): answer it, don't edit any files.`}</lfg-note>`;
      $$("[data-ssc-send]", tr).forEach(x => (x.disabled = true)); b.textContent = "Sending…";
      const st = await api("studio_session", { id }).catch(() => null);
      if (!st || !ssLive(st.state)) { const r = await save("sess_resume", { repo: state.repo, id }); if (!r.ok) { b.disabled = false; b.textContent = edit ? "Make this change" : "Ask"; return alert(String(r.why || "Couldn't start the session.")); } }
      const r = await save("sess_say", { repo: state.repo, id, text });
      if (!r.ok) { $$("[data-ssc-send]", tr).forEach(x => (x.disabled = false)); b.textContent = edit ? "Make this change" : "Ask"; return alert(String(r.why || "Couldn't send it.")); }
      location.hash = `#studio/${id}`;  // watch the answer in the conversation
    });
  };
  $$("[data-df-pick]", root).forEach(el => el.onmousedown = (e => {  // a property, not a listener: a redraw that keeps the line rewires it, once
    if (e.button !== 0) return;
    e.preventDefault();
    const tr = el.closest(".df-l"), table = el.closest(".df-t");
    if (e.shiftKey && sel && sel.table === table) sel.b = tr; else sel = { table, a: tr, b: tr };
    dragging = true; mark();
  }));
  $$(".df-t", root).forEach(table => table.onmouseover = (e => {
    if (!dragging || !sel || sel.table !== table) return;
    const tr = e.target.closest(".df-l");
    if (tr && tr !== sel.b) { sel.b = tr; mark(); }
  }));
  const up = () => { if (!dragging) return; dragging = false; compose(); };
  document.removeEventListener("mouseup", state.dfUp || (() => {}));
  state.dfUp = up; document.addEventListener("mouseup", up);

  $$("[data-df-dir]", root).forEach(a => a.onclick = e => { e.preventDefault(); a.parentNode.classList.toggle("shut"); });
  $$("[data-df-goto]", root).forEach(a => a.onclick = e => { e.preventDefault(); $$(".df-leaf.on", root).forEach(x => x.classList.remove("on")); a.classList.add("on"); const f = $(`#df-f${a.dataset.dfGoto}`, root); f.open = true; f.scrollIntoView({ block: "start", behavior: "smooth" }); });
  const filt = $("#df-filter", root);
  if (filt) filt.oninput = () => {
    const q = filt.value.trim().toLowerCase();
    $$(".df-leaf", root).forEach(a => { a.hidden = !!q && !a.dataset.name.includes(q); });
    $$(".df-dir", root).slice().reverse().forEach(dir => { dir.hidden = !!q && !$$(".df-leaf", dir).some(a => !a.hidden); if (q) dir.classList.remove("shut"); });
  };
}

/* Files for a message: the paperclip, files dropped on the box, a pasted screenshot. Each is uploaded as it is added
   (up to 10); `att` is what is attached, `attached()` what a send carries. Used by Studio and by the chat on a review.
   One per composer: a redraw that keeps the composer gets the same one back, with what you attached still there. */
function ssAttach(o) {
  if (!o.comp._att) o.comp._att = ssAttachNew(o);
  return o.comp._att;
}
function ssAttachNew({ comp, ta, box, file, btn, say }) {
  const att = [], tell = say || (m => alert(m));
  const paint = () => {
    box.hidden = !att.length;
    box.innerHTML = att.map((a, i) => `<span class="ss-chip${a.path ? "" : " up"}" title="${esc(a.name)}${a.path ? "" : " (adding…)"}">${a.thumb ? `<img src="${a.thumb}" alt="">` : icon("docs")}<span>${esc(a.name)}</span><button type="button" data-att-x="${i}" aria-label="Remove ${esc(a.name)}">&times;</button></span>`).join("");
    $$("[data-att-x]", box).forEach(b => b.onclick = () => { att.splice(+b.dataset.attX, 1); paint(); });
  };
  const add = async files => {
    for (const f of Array.from(files || [])) {
      if (att.length >= 10) { tell("Attach up to 10 files at a time."); break; }
      const a = { name: f.name || "pasted-image.png" }; att.push(a); paint();
      try {
        const x = await ssPrepFile(f); a.thumb = x.thumb; paint();
        const r = await save("sess_upload", { repo: state.repo, name: a.name, type: x.type, data: x.data });
        if (!r.ok) throw new Error(r.why || "couldn't attach it");
        Object.assign(a, { path: r.path, type: r.type, image: r.image });
      } catch (e) { att.splice(att.indexOf(a), 1); tell(`${a.name}: ${String(e.message || e).replace(/`/g, "")}`); }
      paint();
    }
  };
  btn.onclick = () => file.click();
  file.onchange = () => { add(file.files); file.value = ""; };
  let depth = 0;
  const hasFiles = e => Array.from((e.dataTransfer || {}).types || []).includes("Files");
  comp.addEventListener("dragenter", e => { if (!hasFiles(e)) return; e.preventDefault(); depth++; comp.classList.add("drop"); });
  comp.addEventListener("dragover", e => { if (hasFiles(e)) e.preventDefault(); });
  comp.addEventListener("dragleave", () => { if (--depth <= 0) { depth = 0; comp.classList.remove("drop"); } });
  comp.addEventListener("drop", e => { if (!hasFiles(e)) return; e.preventDefault(); depth = 0; comp.classList.remove("drop"); add(e.dataTransfer.files); });
  ta.addEventListener("paste", e => { const fs = Array.from((e.clipboardData || {}).files || []); if (fs.length) { e.preventDefault(); add(fs); } });
  return { att, paint, add, attached: () => att.filter(a => a.path).map(a => ({ path: a.path, type: a.type || "" })), busy: () => att.some(a => !a.path), clear: () => { att.length = 0; paint(); } };
}
async function ssGo(what, body, btn, busy) { const was = btn && btn.textContent; if (btn) { btn.disabled = true; if (busy) btn.textContent = busy; } const r = await save(what, Object.assign({ repo: state.repo }, body)); if (!r.ok) { if (btn) { btn.disabled = false; btn.textContent = was; } alert(String(r.why || "That didn't work.").replace(/`/g, "")); } return r;  }
/* The wiring of a session's conversation (permission prompts, Claude's questions, plans, Stop, follow-ups, copy, fork,
   rewind, images), shared by Studio and the chat on a review's page. `o`: conv (its element), S ({id}), d (the session,
   kept current by the caller), go (a button's save), refresh, follow(text) (a suggested next message), rewound(),
   chat (the review page, where a chip jumps to its finding). Returns what to call after each redraw of conv. */
function ssConvWirer(o) {
  const { conv, S, d, go } = o, refresh = () => o.refresh();
  const wire = () => {
    $$("[data-chat-goto]", conv).forEach(a => a.onclick = e => { e.preventDefault(); const [pr, id] = JSON.parse(a.dataset.chatGoto); if (o.goto) o.goto(id); else location.hash = "#prs/" + pr.replace("#", "/"); });
    $$(".ss-ask", conv).forEach(card => $$("[data-decide]", card).forEach(b => b.onclick = async () => { const r = await go("sess_decide", { id: S.id, request: card.dataset.req, decision: b.dataset.decide }, b); if (r.ok) refresh(); }));
    $$(".ss-ask-q", conv).forEach(card => {  // questions: pick, type, send
      const rid = card.dataset.req, picked = (state.ssAns = state.ssAns || {})[rid] = state.ssAns[rid] || {};
      const qs = $$(".ss-q", card), send = $("[data-q-send]", card), left = $("[data-q-left]", card);
      const answerOf = qi => { const c = picked[qi] || { labels: [], other: "" }; return [...c.labels, ...(c.other.trim() ? [c.other.trim()] : [])]; };
      const next = $("[data-q-next]", card), back = $("[data-q-back]", card), tabs = $$("[data-q-tab]", card);
      const tabNow = () => Math.min((state.ssQTab = state.ssQTab || {})[rid] || 0, qs.length - 1);
      const show = k => {  // one question at a time when there are several
        state.ssQTab[rid] = k;
        qs.forEach((f, i) => { f.hidden = i !== k; });
        tabs.forEach((t, i) => { t.classList.toggle("on", i === k); t.setAttribute("aria-selected", String(i === k)); });
        sync();
        const first = $("input[data-opt]:checked", qs[k]) || $("input[data-opt]", qs[k]); if (first && tabs.length) first.focus({ preventScroll: true });
      };
      const sync = () => {
        qs.forEach(f => { const qi = f.dataset.qi; $$(".ss-q-o", f).forEach(l => { const i = $("input[data-opt]", l); l.classList.toggle("on", i.checked); }); picked[qi] = picked[qi] || { labels: [], other: "" }; });
        const missing = qs.filter(f => !answerOf(f.dataset.qi).length).length, k = tabNow(), last = k >= qs.length - 1;
        tabs.forEach((t, i) => t.classList.toggle("done", !!answerOf(qs[i].dataset.qi).length));
        if (next) { next.hidden = last; next.disabled = !answerOf(qs[k].dataset.qi).length; back.hidden = k === 0; send.hidden = !last; }
        send.disabled = !!missing; left.textContent = missing && qs.length > 1 && last ? `${missing} left to answer` : "";
      };
      if (next) { next.onclick = () => show(Math.min(tabNow() + 1, qs.length - 1)); back.onclick = () => show(Math.max(tabNow() - 1, 0)); }
      tabs.forEach((t, i) => t.onclick = () => show(i));
      qs.forEach(f => {
        const qi = f.dataset.qi, multi = !!$('input[type="checkbox"]', f);
        $$("input[data-opt]", f).forEach(i => i.onchange = () => {
          const c = picked[qi] = picked[qi] || { labels: [], other: "" };
          if (i.dataset.opt === "__other") { if (!i.checked) c.other = ""; else $(".ss-q-in", f).focus(); if (!multi) c.labels = []; }
          else if (multi) c.labels = i.checked ? [...new Set([...c.labels, i.dataset.opt])] : c.labels.filter(x => x !== i.dataset.opt);
          else { c.labels = [i.dataset.opt]; c.other = ""; const o = $(".ss-q-in", f); if (o) o.value = ""; }
          sync();
        });
        const other = $(".ss-q-in", f);
        other.oninput = () => {
          const c = picked[qi] = picked[qi] || { labels: [], other: "" };
          c.other = other.value;
          const box = $('input[data-opt="__other"]', f); box.checked = !!other.value.trim();
          if (!multi && other.value.trim()) { c.labels = []; $$("input[data-opt]", f).forEach(x => { if (x !== box) x.checked = false; }); }
          sync();
        };
        other.onclick = () => { const box = $('input[data-opt="__other"]', f); if (!box.checked && !multi) { box.checked = true; c0(qi); sync(); } };
        other.onkeydown = e => { if (e.key !== "Enter") return; if (next && !next.hidden && !next.disabled) next.click(); else if (!send.disabled) send.click(); };
      });
      const c0 = qi => { const c = picked[qi] = picked[qi] || { labels: [], other: "" }; if (!multi0(qi)) c.labels = []; };
      const multi0 = qi => !!$(`.ss-q[data-qi="${qi}"] input[type="checkbox"]`, card);
      card.onkeydown = e => {  // 1-9 picks an option in the first unanswered single-choice question, as in the terminal
        if (e.target.matches("input[type=text], textarea") || !/^[1-9]$/.test(e.key)) return;
        const f = tabs.length ? qs[tabNow()] : qs.find(x => !multi0(x.dataset.qi) && !answerOf(x.dataset.qi).length) || qs[0];
        if (multi0(f.dataset.qi)) { const i = $$("input[data-opt]", f)[+e.key - 1]; if (i && i.dataset.opt !== "__other") { i.checked = !i.checked; i.onchange(); } return; }
        const i = $$("input[data-opt]", f)[+e.key - 1]; if (i && i.dataset.opt !== "__other") { i.checked = true; i.onchange(); }
      };
      sync();
      send.onclick = async () => {
        const answers = {};
        const list = (d.pending || []).find(x => x.id === rid);
        ((list && list.input && list.input.questions) || []).forEach((q, qi) => { answers[q.question] = answerOf(qi).join(", "); });
        const r = await go("sess_decide", { id: S.id, request: rid, decision: "answer", answers }, send, "Sending…");
        if (r.ok) { delete state.ssAns[rid]; delete (state.ssQTab || {})[rid]; refresh(); }
      };
    });
    $$(".ss-ask-plan", conv).forEach(card => {
      const fb = $(".ss-plan-fb", card), rv = $("[data-plan-revise]", card);
      rv.onclick = async () => {
        if (!fb.value.trim()) { fb.focus(); fb.placeholder = "Say what to change, then Keep planning"; return; }
        const r = await go("sess_decide", { id: S.id, request: card.dataset.req, decision: "revise", message: fb.value }, rv, "Sending…");
        if (r.ok) refresh();
      };
    });
    const stop = $("[data-ss-interrupt]", conv); if (stop) stop.onclick = () => go("sess_interrupt", { id: S.id }, stop, "Stopping…");
    $$("[data-follow]", conv).forEach(b => b.onclick = () => o.follow(b.dataset.follow));
    $$("[data-ss-copy]", conv).forEach(b => b.onclick = async () => { await navigator.clipboard.writeText(ssItemText(d.items[+b.dataset.ssCopy])); const t = b.innerHTML; b.textContent = "Copied"; setTimeout(() => { b.innerHTML = t; }, 1200); });
    $$("[data-fork]", conv).forEach(b => b.onclick = () => {
      const it = d.items[+b.dataset.fork];
      state.ssFork = { sid: S.id, at: it.p || "", label: ssItemText(it).slice(0, 60) };
      state.ssPrefill = ssItemText(it); route({ soft: true });
    });
    $$("[data-rw]", conv).forEach(b => b.onclick = () => ssRewind(b));
    $$(".ss-img", conv).forEach(b => b.onclick = () => b.classList.toggle("big"));
    ssImages(conv, S.id);
  };
  // Rewind: like Claude Code's, to before one of your messages: the conversation, the code, or both
  const ssRewind = async b => {
    $$(".ss-rw", conv).forEach(x => x.remove());
    const msg = b.closest(".ss-me"), u = b.dataset.rw;
    const box = document.createElement("div"); box.className = "ss-rw"; box.dataset.local = "";  // yours until you close it: a redraw keeps it
    box.innerHTML = `<div class="ss-rw-h"><b>Rewind to before this message</b><span class="muted small" data-rw-prev>Checking which files would change…</span></div><div class="ss-rw-files" hidden></div>
      <div class="ss-rw-a"><button class="btn small primary" data-rw-go="both">Code and conversation</button><button class="btn small" data-rw-go="chat">Conversation only</button><button class="btn small" data-rw-go="code">Code only</button><button class="btn small" data-rw-x>Cancel</button></div>`;
    msg.append(box); box.scrollIntoView({ block: "nearest" });
    $("[data-rw-x]", box).onclick = () => box.remove();
    const codeBtns = $$('[data-rw-go="both"], [data-rw-go="code"]', box);
    const p = await save("sess_rewind_preview", { repo: state.repo, id: S.id, message: u }), prev = $("[data-rw-prev]", box);
    if (!p.ok || !p.can) { prev.textContent = p.ok ? `The code can't be rewound: ${p.why || "no saved copy of the files from then"}.` : String(p.why || "Couldn't check the files.").replace(/`/g, ""); codeBtns.forEach(x => x.disabled = true); $('[data-rw-go="chat"]', box).classList.add("primary"); }
    else if (!p.files.length) { prev.textContent = "No file changes since then; only the conversation goes back."; codeBtns.forEach(x => x.disabled = true); $('[data-rw-go="chat"]', box).classList.add("primary"); }
    else { prev.textContent = `Puts back ${plural(p.files.length, "file")} (+${p.insertions} −${p.deletions}).`; const fl = $(".ss-rw-files", box); fl.hidden = false; fl.textContent = p.files.join("\n"); }
    $$("[data-rw-go]", box).forEach(x => x.onclick = async () => {
      const what = x.dataset.rwGo;
      if (what !== "chat" && !confirm(`Put ${plural(p.files.length, "file")} back to how they were before this message? Changes made since, by Claude or by you, are lost.`)) return;
      const r = await go("sess_rewind", { id: S.id, message: u, what }, x, "Rewinding…");
      if (!r.ok) return;
      if (r.prefill) state.ssPrefill = r.prefill;
      o.rewound();
    });
  };
  return wire;
}
function wireStudio(root) {
  clearTimeout(ssPoll);
  if ($(".ssc", root)) return wireSessChanges(root);
  ssFit(root);
  const S = state.sess || {}, d = S.d;
  const go = ssGo;
  // the list: filter and search
  $$("[data-ss-filter]", root).forEach(b => b.onclick = () => { state.ssFilter = b.dataset.ssFilter; route({ soft: true }); });
  $$("[data-ss-view]", root).forEach(b => b.onclick = () => { localStorage.setItem("lfg.ss.view", b.dataset.ssView); route({ soft: true }); });
  if (S.list && !S.id) {  // groups and labels on the list: the same drawers as the Sessions page
    const ctx = { info: S.list.group_info || {}, labels: S.list.label_list || [], refresh: () => route({ soft: true }) };
    wireGroupsAndLabels(root, ctx, S.list.sessions || []);
    $$("[data-ss-group]", root).forEach(b => b.onclick = e => { e.preventDefault(); e.stopPropagation(); sessionGroupDrawer((S.list.sessions || []).find(x => x.id === b.dataset.ssGroup) || { id: b.dataset.ssGroup }, ctx); });
    $$("[data-sess-labels]", root).forEach(b => { const go = b.onclick; b.onclick = e => { e.preventDefault(); e.stopPropagation(); go(e); }; });
    $$("[data-grp-new]", root).forEach(b => b.onclick = () => newGroupDrawer(ctx));
  }
  const find = $("#ss-find", root);
  if (find) { find.oninput = () => { const q = find.value.trim().toLowerCase(); $$(".ss-row", root).forEach(a => { a.hidden = !!q && !q.split(/\s+/).every(w => a.dataset.title.includes(w)); }); }; if (find.value) find.oninput(); }  // a redraw keeps your search applied
  // the composer
  const ta = $("#ss-text", root), send = $("#ss-send", root), ac = $("#ss-ac", root);
  const fresh = ta && once(ta, "studio");  // a redraw that keeps the text box wires it again: listeners and focus only once
  $$("[data-seg]", root).forEach(seg => $$("button", seg).forEach(b => b.onclick = () => {
    $$("button", seg).forEach(x => { x.classList.toggle("on", x === b); x.setAttribute("aria-checked", x === b); });
    localStorage.setItem("lfg.ss." + seg.dataset.seg, b.dataset.v);
    if (seg.dataset.seg === "mode" && S.id && d && ssLive(d.state)) go("sess_mode", { id: S.id, mode: b.dataset.v });
  }));
  const segVal = k => { const b = $(`[data-seg="${k}"] button.on`, root); return b ? b.dataset.v : undefined; };
  if (fresh) {
    ssAutocomplete(ta, ac);
    ta.addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing && $("#ss-ac").hidden) { e.preventDefault(); $("#ss-send").click(); } });
    ta.addEventListener("input", () => { ta.style.height = "auto"; ta.style.height = Math.min(ta.scrollHeight, 280) + "px"; });
  }
  if (ta) {
    if (state.ssPrefill) { ta.value = state.ssPrefill; state.ssPrefill = ""; ta.dispatchEvent(new Event("input")); state.ssFresh = true; }
    if ((fresh && (!S.id || ssLive(d && d.state))) || state.ssFresh) { ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); }
    state.ssFresh = false;
  }
  // attachments: the paperclip, drag and drop onto the composer, or a pasted screenshot
  const comp = $("#ss-comp", root), A = comp && ta ? ssAttach({ comp, ta, box: $("#ss-att", root), file: $("#ss-file", root), btn: $("#ss-attach", root) }) : null;
  const att = A ? A.att : [], paintAtt = () => A && A.paint(), attached = () => A ? A.attached() : [];
  $$("[data-sug]", root).forEach(b => b.onclick = () => { const x = S.sug.suggestions[+b.dataset.sug]; ta.value = x.prompt; ta.dispatchEvent(new Event("input")); ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); });
  const clearComposer = () => { ta.value = ""; ta.style.height = "auto"; att.length = 0; paintAtt(); };
  if (send) send.onclick = async () => {
    const text = ta.value.trim(), files = attached();
    if (att.some(a => !a.path)) return;  // still uploading
    if (!text && !files.length) return ta.focus();
    const fork = S.id && state.ssFork && state.ssFork.sid === S.id ? state.ssFork : null;
    if (fork) {
      const r = await go("sess_fork", { id: S.id, at: fork.at || "", text, attachments: files }, send, "Forking…");
      if (r.ok) { state.ssFork = null; clearComposer(); loadNavSessions(); location.hash = "#studio/" + r.id; }
      return;
    }
    if (!S.id) {
      const where = ssWhereValue(root);
      if (where.kind === "new" && !where.branch) { const n = $("#ss-wt-name", root); n.focus(); n.placeholder = "Name the new branch"; n.classList.add("need"); return; }
      const r = await go("sess_start", { text, mode: segVal("mode"), where, attachments: files }, send, where.kind === "here" || where.kind === "worktree" ? "Starting…" : "Making the worktree…");
      if (r.ok) { clearComposer(); loadNavSessions(); location.hash = "#studio/" + r.id; }
      return;
    }
    if (!ssLive(d.state)) { const r = await go("sess_resume", { id: S.id }, send, "Starting…"); if (!r.ok) return; }
    const r = await go("sess_say", { id: S.id, text, attachments: files }, send, "Sending…");
    if (r.ok) { clearComposer(); send.disabled = false; send.textContent = "Send"; refresh(); }
  };
  const fx = $("[data-fork-x]", root); if (fx) fx.onclick = () => { state.ssFork = null; route({ soft: true }); };
  const wsel = $("#ss-where", root);
  const tag = () => { const [b, wt] = ssTarget(root), t = $("#ss-branch", root), w = $("#ss-wt-tag", root); if (t) t.textContent = b; if (w) { w.hidden = !wt; w.innerHTML = wt ? `${icon("folder")}${esc(wt)}` : ""; } };
  if (wsel) {
    const show = () => { $(".ss-newwt", root).hidden = wsel.value !== "new"; tag(); };
    wsel.onchange = () => { show(); if (wsel.value === "new") $("#ss-wt-name", root).focus(); };
    $("#ss-wt-name", root).oninput = tag; $("#ss-wt-base", root).onchange = tag;
    show();
  }
  if (!S.id && $("#ss-branch", root)) {  // the checked-out branch can change under us: keep it current
    const tick = async () => {
      if (location.hash !== "#studio") return;
      const w = await api("studio_where").catch(() => null);
      if (w && w.branch !== (state.sess.where || {}).branch) { state.sess.where = w; const o = $('#ss-where option[value="here"]'); if (o) o.textContent = `Here · ${w.branch}`; tag(); }
      ssPoll = setTimeout(tick, 5000);
    };
    ssPoll = setTimeout(tick, 5000);
  }
  // worktrees: new session there, merge back, merge all
  $$("[data-wt-session]", root).forEach(b => b.onclick = () => { state.ssStartIn = b.dataset.wtSession; location.hash = "#studio"; });
  if (state.ssStartIn && wsel) { const o = $(`#ss-where option[value="wt:${CSS.escape(state.ssStartIn)}"]`, root); if (o) { wsel.value = o.value; wsel.onchange(); } state.ssStartIn = null; }
  const merge = async (body, btn, label) => {
    let r = await go(body.into ? "wt_merge_all" : "wt_merge", body, btn, "Merging…");
    if (r.ok && r.needs_merge_commit) {
      if (!confirm(r.why + "\n\nThis creates a merge commit on the base branch.")) { route({ soft: true }); return; }
      r = await go(body.into ? "wt_merge_all" : "wt_merge", Object.assign({ merge_commit: true }, body), btn, "Merging…");
    }
    if (r.ok) { const done = r.done || [r]; alert(done.length ? done.map(x => `${x.name}: ${x.commits ? `${x.commits} commit${x.commits === 1 ? "" : "s"} into ${x.into} (${x.how})` : "nothing to merge"}${x.removed ? ", removed" : ""}`).join("\n") : "Nothing to merge."); }
    route({ soft: true });
  };
  $$("[data-wt-merge]", root).forEach(b => b.onclick = () => {
    const row = b.closest("[data-wt]"), name = row.dataset.wt, rm = b.hasAttribute("data-remove");
    if (!confirm(rm ? `${b.textContent} ${name}?\n\nOnly committed work is merged. The worktree folder and its branch (once merged) are removed.` : `Merge ${name} into its base branch?\n\nOnly committed work is merged.`)) return;
    merge({ name, remove: rm }, b);
  });
  $$("[data-wt-all]", root).forEach(b => b.onclick = () => { if (confirm(`Merge every LFG worktree forked from ${b.dataset.wtAll} into it, then remove them?\n\nIt stops at the first one that can't merge (uncommitted changes or conflicts).`)) merge({ into: b.dataset.wtAll }, b); });
  if (!d || d.available === false) return;
  // one session: answers, follow-ups, stop, end, rename, live updates
  const conv = $("#ss-conv", root), head = $("#ss-head", root);
  const wireConv = ssConvWirer({ conv, S, d, go, refresh: () => refresh(), follow: t => { ta.value = t; send.click(); }, rewound: () => { loadNavSessions(); route({ soft: true }); } });
  const wireHead = () => {
    const end = $("[data-ss-end]", head); if (end) end.onclick = async () => { if (confirm("End this session? Claude Code stops; you can continue the session later.")) { await go("sess_end", { id: S.id }, end); loadNavSessions(); route({ soft: true }); } };
    const rename = async () => { const t = prompt("Name this session", d.title); if (t && t.trim()) { await go("sess_rename", { id: S.id, title: t }); loadNavSessions(); route({ soft: true }); } };
    const ttl = $("[data-ss-rename]", head); if (ttl) ttl.onclick = rename;
    const more = $("[data-ss-more]", head), menu = $(".ss-menu", head);
    const close = () => { menu.hidden = true; more.setAttribute("aria-expanded", "false"); document.removeEventListener("click", outside, true); };
    const outside = e => { if (!e.target.closest(".ss-menu, [data-ss-more]")) close(); };
    more.onclick = () => { const open = menu.hidden; menu.hidden = !open; more.setAttribute("aria-expanded", open); if (open) document.addEventListener("click", outside, true); else close(); };
    $$("[data-menu]", menu).forEach(b => b.onclick = async () => {
      close();
      const k = b.dataset.menu;
      if (k === "rename") return rename();
      if (k === "export") return ssDownload(`${(d.title || "session").replace(/[^\w.-]+/g, "-").slice(0, 60)}.md`, ssMarkdown(d));
      if (k === "resume") { await navigator.clipboard.writeText(`claude --resume ${S.id}`); return alert(`Copied: claude --resume ${S.id}\n\nRun it in this project's folder to carry on in a terminal.`); }
      if (k === "fork") { state.ssFork = { sid: S.id, at: "", label: "" }; route({ soft: true }); return; }
      if (k === "compact") return compact();
    });
  };
  const compact = async () => {
    if (!confirm("Compact this conversation? Claude Code summarizes it to free up context, as /compact does in a terminal.")) return;
    if (!ssLive(d.state)) { const r = await go("sess_resume", { id: S.id }); if (!r.ok) return; }
    const r = await go("sess_compact", { id: S.id }); if (r.ok) refresh();
  };
  head.onclick = e => { if (e.target.closest("[data-ctx-compact]")) { e.preventDefault(); compact(); } };  // the button in the long-session warning (one handler, however often this runs)
  const wireOut = () => {
    const b = $("[data-ss-reload]", conv);
    if (b) b.onclick = async () => { const r = await go("sess_reload", { id: S.id }, b, "Reloading…"); if (r.ok) { await refresh(); loadCtx(); } };
  };
  const loadCtx = async () => {  // how full the context is, once Claude is idle
    if (!ssLive(d.state) || d.state === "working") return;
    const c = await api("studio_context", { id: S.id }).catch(() => null);
    if (!c || c.percent == null) return;
    (state.ssCtx = state.ssCtx || {})[S.id] = c;
    const a = $(".ss-head-a", head), old = $(".ss-ctx-box", a);
    if (old) morphOuter(old, ssCtxHtml(c)); else a.insertAdjacentHTML("afterbegin", ssCtxHtml(c));  // an open breakdown stays open
  };
  wireConv(); wireHead(); wireOut(); loadCtx();
  const atBottom = () => conv.scrollTop + conv.clientHeight >= conv.scrollHeight - 120;
  if (once(conv, "at-end")) conv.scrollTop = conv.scrollHeight;  // a session opens at its end; a redraw leaves you where you are
  let sig = "";
  const sigOf = n => JSON.stringify([n.items.length, n.state, (n.pending || []).length, (n.queued || []).length, n.error, n.cost, (n.items[n.items.length - 1] || {}).result != null, (n.outside || {}).ts]);
  const busyBg = n => (n.activity || []).some(a => a.status === "running");
  wireAct($("#ss-act", root));
  const drawAct = n => { const box = $("#ss-act", root); if (box) morph(box, ssAct(n)); const one = $(".ss-one", root); if (one) one.classList.toggle("has-act", !!(n.activity || []).length); };
  sig = sigOf(d);
  async function refresh() {
    clearTimeout(ssPoll);
    if (!/^#studio\//.test(location.hash) || state.sess.id !== S.id) return;
    const n = await api("studio_session", { id: S.id });
    if (!n || n.available === false) return;
    drawAct(n);  // steps and times change without the conversation changing
    const nsig = sigOf(n);
    if (nsig !== sig) {
      const stick = atBottom(), was = d.state;
      sig = nsig; state.sess.d = n; Object.assign(d, n);
      morph(conv, ssConv(n)); morph(head, ssHead(n)); wireConv(); wireHead(); wireOut();  // only what changed: open steps, selection, the menu stay
      conv.classList.toggle("ss-busy", n.state === "working" || n.state === "starting" || !!(n.pending || []).length);
      if (n.state === "idle" && was !== "idle") loadCtx();
      if (send) { const want = ssLive(n.state) ? "Send" : "Continue here"; if (!send.disabled && send.textContent !== want) send.textContent = want; }
      if (stick) conv.scrollTop = conv.scrollHeight;
    }
    if (ssLive(n.state)) ssPoll = setTimeout(refresh, n.state === "idle" ? 4000 : 1200);
    else if (busyBg(n)) ssPoll = setTimeout(refresh, 5000);  // a terminal session's agents: keep watching
  }
  if (ssLive(d.state)) ssPoll = setTimeout(refresh, 1200);
  else if (busyBg(d)) ssPoll = setTimeout(refresh, 5000);
}

/* Notifications: every long job (an AI review or answer, a fix run, a Linear ticket, a scan, the checks) is announced
   when it finishes, by `lfg ui` itself, even with its page closed. They show as toasts, in the bell's list and, when
   this tab is in the background and you allowed it, as system notifications. A click opens the page. */
const NOTES = { last: "", seen: localStorage.getItem("lfg.notes.seen") || "", events: [] };
const NOTE_ICON = { review: "review", diff: "review", fix: "runs", linear: "todos", checks: "checks", sonar: "checks" };
async function openNote(ev) {
  closeBell();
  if (ev.repo && ev.repo !== state.repo && state.repos.some(r => r.id === ev.repo)) {
    state.repo = ev.repo; localStorage.setItem("lfg.repo", ev.repo);
    const sel = $("#repo"); if (sel) sel.value = ev.repo;
    await loadBranches();
  }
  if (ev.href && location.hash !== ev.href) location.hash = ev.href; else route();
}
function noteHtml(ev, cls) {
  const proj = ev.repo && ev.repo !== state.repo ? `<span class="brtag">${esc(repoName(ev.repo))}</span>` : "";
  return `<a href="${esc(ev.href || "#")}" class="${cls}${ev.ok ? "" : " bad"}${ev.id > NOTES.seen ? " new" : ""}" data-note="${esc(ev.id)}"><span class="note-ico">${icon(NOTE_ICON[ev.kind] || "home")}</span><span class="grow"><b>${esc(ev.title)}</b>${ev.body ? `<span class="note-b">${esc(ev.body)}</span>` : ""}<span class="note-m">${proj}${ago(ev.ts)}</span></span></a>`;
}
function paintBell() {
  const unread = NOTES.events.filter(e => e.id > NOTES.seen).length, n = $("#bell-n");
  n.hidden = !unread; n.textContent = unread > 9 ? "9+" : unread;
  const pop = $("#bell-pop");
  if (pop.hidden) return;
  const perm = NOTES.desktop === "terminal-notifier" ? `<span class="muted small">When this tab isn't in front, you also get a macOS notification; click it to come back here.</span>`
    : NOTES.desktop === "osascript" ? `<span class="muted small">When this tab isn't in front, you also get a macOS notification. Install terminal-notifier (<code>brew install terminal-notifier</code>) to make it open the page on click.</span>`
    : !("Notification" in window) ? "" : Notification.permission === "granted" ? `<span class="muted small">System notifications are on when this tab is in the background.</span>`
    : Notification.permission === "denied" ? `<span class="muted small">System notifications are blocked for this page in your browser's settings.</span>`
    : `<button class="btn small" id="note-perm">Notify me when this tab is in the background</button>`;
  morph(pop, `<div class="bell-h"><b>Notifications</b><span class="grow"></span>${unread ? `<a href="#" class="small" id="note-read">Mark all read</a>` : ""}</div>
    <div class="bell-list">${NOTES.events.slice(0, 30).map(e => noteHtml(e, "note")).join("") || '<p class="muted small bell-empty">Nothing yet. When the AI finishes a review, an answer or a fix run, or a scan or check is done, it shows up here.</p>'}</div>
    <div class="bell-f">${perm}</div>`);
  $$("[data-note]", pop).forEach(a => a.onclick = e => { e.preventDefault(); openNote(NOTES.events.find(x => x.id === a.dataset.note)); });
  const rd = $("#note-read", pop); if (rd) rd.onclick = e => { e.preventDefault(); markSeen(); };
  const pm = $("#note-perm", pop); if (pm) pm.onclick = async () => { await Notification.requestPermission(); paintBell(); };
}
function markSeen() { NOTES.seen = NOTES.events[0] ? NOTES.events[0].id : NOTES.seen; localStorage.setItem("lfg.notes.seen", NOTES.seen); paintBell(); }
function closeBell() { const pop = $("#bell-pop"); if (!pop.hidden) { pop.hidden = true; $("#bell").setAttribute("aria-expanded", "false"); markSeen(); } }
function toast(ev) {
  const box = $("#toasts"), el = document.createElement("div");
  // a toast is one quiet line in the accent colour: what happened, click to go there; the details stay in the bell
  el.innerHTML = `<a href="${esc(ev.href || "#")}" class="toast${ev.ok ? "" : " bad"}" title="${esc([ev.title, ev.body].filter(Boolean).join("\n"))}"><span class="toast-dot" aria-hidden="true"></span><span class="toast-t">${esc(ev.title)}</span></a><button class="toast-x" aria-label="Dismiss">&times;</button>`;
  const t = el.firstChild, x = el.lastChild;
  const wrap = document.createElement("div"); wrap.className = "toast-wrap"; wrap.append(t, x); box.prepend(wrap);
  t.onclick = e => { e.preventDefault(); wrap.remove(); openNote(ev); };
  x.onclick = () => wrap.remove();
  setTimeout(() => wrap.remove(), 6000);
  while (box.children.length > 3) box.lastChild.remove();
}
function systemNote(ev) {  // the browser's own notification, only when `lfg ui` can't post macOS ones itself
  if (NOTES.desktop || !document.hidden || !("Notification" in window) || Notification.permission !== "granted") return;
  const n = new Notification(`LFG · ${ev.title}`, { body: [ev.body, ev.repo && repoName(ev.repo)].filter(Boolean).join("\n"), tag: ev.id });
  n.onclick = () => { window.focus(); n.close(); openNote(ev); };
}
const inFront = () => document.visibilityState === "visible" && document.hasFocus();
async function pollNotes(first) {
  let d;
  try { d = await api("notifications", Object.assign({ visible: inFront() ? "1" : "0" }, NOTES.last ? { since: NOTES.last } : {})); } catch (e) { return; }
  if (!d || !d.events) return;
  NOTES.desktop = d.desktop || "";
  const sb = $("#top-sess-n"), ss = d.sessions || {};
  const sk = JSON.stringify(ss); if (sk !== NOTES.sessKey || Date.now() - (NOTES.sessAt || 0) > 30000) { NOTES.sessKey = sk; NOTES.sessAt = Date.now(); loadNavSessions(); }
  if (sb) { sb.hidden = !ss.live; sb.textContent = ss.needs_you ? `${ss.needs_you} need you` : `${ss.live} live`; sb.classList.toggle("warn", !!ss.needs_you); }
  if (!first) d.events.slice().reverse().forEach(ev => { toast(ev); systemNote(ev); });
  NOTES.events = d.events.concat(NOTES.events).slice(0, 50);
  NOTES.last = d.latest || NOTES.last;
  paintBell();
}
function mountBell() {
  const b = $("#bell"), pop = $("#bell-pop");
  b.onclick = e => { e.stopPropagation(); if (pop.hidden) { pop.hidden = false; b.setAttribute("aria-expanded", "true"); paintBell(); } else closeBell(); };
  document.addEventListener("click", e => { if (!pop.hidden && !e.target.closest(".bell")) closeBell(); });
  document.addEventListener("keydown", e => { if (e.key === "Escape") closeBell(); });
  pollNotes(true);
  setInterval(() => pollNotes(false), 5000);
  // tell `lfg ui` at once when this tab goes to the back (or comes forward), so macOS notifications start right away
  ["visibilitychange", "blur", "focus"].forEach(ev => (ev === "visibilitychange" ? document : window).addEventListener(ev, () => pollNotes(false)));
}

/* Bottom of the sidebar: the LFG version, a tag when a newer one is out, and a button to check now */
async function init() {
  const brand = $(".brand"); if (brand) brand.innerHTML = logoSvg(20);
  api("github").then(g => { state.gh = g; if (g && g.starred) $$("[data-gh-star]").forEach(b => (b.textContent = "★ Starred, thank you")); }).catch(() => {});
  if (location.hash.startsWith("#unlock=")) {  // from `lfg ui`: keep the edit key, drop it from the URL
    localStorage.setItem("lfg.editKey", decodeURIComponent(location.hash.slice(8)));
    history.replaceState(null, "", location.pathname);
  }
  $("#drawer-close").onclick = closeDrawer;
  const linked = new URLSearchParams(location.search).get("repo");  // opened from a macOS notification
  if (linked) { state.repo = linked; localStorage.setItem("lfg.repo", linked); history.replaceState(null, "", location.pathname + location.hash); }
  mountBell();
  setTimeout(loadNavSessions, 300);
  $("#drawer").onclick = e => { if (e.target.id === "drawer") closeDrawer(); };
  document.addEventListener("keydown", e => { if (e.key === "Escape") closeDrawer(); });
  try { state.rules = await api("rules"); } catch (e) { state.rules = null; }
  mountRuleTips();
  // Fetch features BEFORE first route, set pages
  let d = null;
  try { d = await api("features"); } catch (e) { d = null; }
  if (d) {
    state.pages = d.pages || NAV.map(p => p[0]);
    if (d.show_all) state.pages = NAV.map(p => p[0]);
  }
  // Redirect to onboarding only when: !complete AND hash empty AND no welcomeShown
  let welcomeShown = null;
  try { welcomeShown = sessionStorage.getItem("lfg.welcomeShown"); } catch (e) { /* ignore */ }
  const hashEmpty = !location.hash || location.hash === "#";
  if (d && !d.complete && hashEmpty && !welcomeShown) {
    try { sessionStorage.setItem("lfg.welcomeShown", "1"); } catch (e) { /* ignore */ }
    location.hash = "#onboarding";
  }
  const r = await api("repos");
  state.repos = r.repos || [];
  if (!state.repos.some(x => x.id === state.repo)) state.repo = state.repos[0] ? state.repos[0].id : "";
  $("#repo").innerHTML = state.repos.map(x => `<option value="${esc(x.id)}" title="${esc(x.root || x.id)}" ${x.id === state.repo ? "selected" : ""}>${esc(x.name || x.id)}</option>`).join("") || "<option>no projects yet</option>";
  $("#repo").onchange = async () => {
    state.repo = $("#repo").value; localStorage.setItem("lfg.repo", state.repo); state.navSess = [];
    if (state.crumb) crumbs(state.crumb.page, state.crumb.item, state.crumb.itemHref);  // the new repo's name, top and tab
    await loadBranches();
    loadNavSessions();
    // a page about one thing in the old repo (a PR, a run, a doc) goes to that section's list in the new one
    const [page, ...rest] = location.hash.slice(1).split("/");
    if (rest.length && rest.join("")) location.hash = "#" + page; else refresh();
  };
  $("#refresh").onclick = refresh;
  checkUpdate();
  $("#branch").onchange = () => { state.branch = $("#branch").value; localStorage.setItem(branchPref(), state.branch); refresh(); };
  $("#back").onclick = () => history.back();
  $("#forward").onclick = () => history.forward();
  window.onhashchange = () => { histButtons(); route(); };
  histButtons();
  await loadBranches();
  mapStatus();
  route();
  offerTours();
  watchNotices();
}
/* A review finished: a desktop notification that opens it (once you allow them), and a note in the page either way. */
async function watchNotices() {
  let since = 0;
  const tick = async () => {
    const d = await api("notices", { since }).catch(() => null);
    if (!d) return;
    if ((d.items || []).length) noticeBatch(d.items);
    since = d.last || since;
  };
  await tick();
  setInterval(tick, 15000);
}
/* Where a notice takes you: the PR on its newest review, scrolled to the findings or the Fix box, which flashes. */
const NOTICE_PLACE = { findings: ".pr-pass-body", fix: ".pr-fixbar" };
function noticeGo(x) {
  if ((x.place || "").startsWith("session:")) {  // a skill run finished: open the session it ran on
    state.goto = `[data-sid="${CSS.escape(x.place.slice(8))}"]`;
    if (location.hash === "#sessions") route(); else location.hash = "#sessions";
    return;
  }
  sessionStorage.removeItem("lfg.prpass." + x.pr);
  state.goto = NOTICE_PLACE[x.place] || NOTICE_PLACE.findings;
  const href = `#prs/${x.pr.replace("#", "/")}`;
  if (location.hash === href) route(); else location.hash = href;
}
function applyGoto(view) {
  if (!state.goto) return;
  const el = $(state.goto, view);
  state.goto = null;
  if (!el) return;
  // code snippets above it load after this and push it down: keep it in place until they're in, or you scroll
  const until = Date.now() + 4000, keep = () => el.isConnected && el.scrollIntoView({ block: "start" });
  keep();
  state.pin = { keep, until };
  const stop = () => { state.pin = null; window.removeEventListener("wheel", stop); window.removeEventListener("keydown", stop); };
  window.addEventListener("wheel", stop, { once: true }); window.addEventListener("keydown", stop, { once: true });
  el.classList.add("flash");
  setTimeout(() => el.classList.remove("flash"), 1800);
}
function desktopNotice(title, body, onclick) {
  if (!("Notification" in window) || Notification.permission !== "granted") return false;
  const n = new Notification(title, { body });
  n.onclick = () => { window.focus(); onclick(); n.close(); };
  return true;
}
/* Notices stack in one box at the bottom right: the newest three show, the rest fold under "N more", and Clear all
   empties it. A batch that arrives at once (a tab coming back) makes one desktop notification, not one each. */
const NOTICES = [];
let noticesOpen = false;
function noticeShow(x, quiet) {
  if (!quiet) desktopNotice(x.title, x.body, () => noticeGo(x));
  NOTICES.unshift(x);
  noticesDraw();
}
function noticeBatch(items) {
  if (items.length > 2) {
    const bad = items.filter(x => !x.ok).length;
    desktopNotice(`${items.length} updates`, `${items.length - bad} done${bad ? `, ${bad} failed` : ""}. Open the dashboard to see them.`, () => window.focus());
    items.forEach(x => noticeShow(x, true));
  } else items.forEach(x => noticeShow(x));
}
function noticesDraw() {
  let box = $("#notices");
  if (!box) box = document.body.appendChild(Object.assign(document.createElement("div"), { id: "notices" }));
  if (!NOTICES.length) { box.innerHTML = ""; noticesOpen = false; return; }
  const shown = noticesOpen ? NOTICES : NOTICES.slice(0, 3), more = NOTICES.length - shown.length;
  const card = (x, i) => `<div class="notice ${x.ok ? "ok" : "bad"}" data-notice="${i}" title="Open it">${dot(x.ok ? "ok" : "bad")}<div class="grow"><b>${esc(x.title)}</b><div class="small muted">${esc(x.body)}</div><div class="small faint">${ago(x.at)}</div></div><button class="btn tiny" data-notice-x="${i}" aria-label="Close">×</button></div>`;
  const ask = "Notification" in window && Notification.permission === "default";
  morph(box, `${NOTICES.length > 1 ? `<div class="notices-h"><b>${plural(NOTICES.length, "update")}</b><span class="grow"></span>${ask ? '<button class="btn tiny" data-notify-on>Desktop alerts</button>' : ""}<button class="btn tiny" data-notices-clear>Clear all</button></div>` : ""}
    <div class="notices-list ${noticesOpen ? "open" : ""}">${shown.map((x, i) => card(x, i)).join("")}</div>
    ${more ? `<button class="notices-more" data-notices-more>Show ${plural(more, "more update")}</button>` : noticesOpen && NOTICES.length > 3 ? '<button class="notices-more" data-notices-more>Show fewer</button>' : ""}
    ${NOTICES.length === 1 && ask ? '<button class="btn tiny notices-ask" data-notify-on>Also tell me on the desktop</button>' : ""}`);
  $$("[data-notice]", box).forEach(el => el.onclick = e => {
    const i = +el.dataset.notice;
    if (e.target.closest("[data-notice-x]")) { NOTICES.splice(i, 1); return noticesDraw(); }
    const [x] = NOTICES.splice(i, 1);
    noticesDraw(); noticeGo(x);
  });
  const clear = $("[data-notices-clear]", box);
  if (clear) clear.onclick = () => { NOTICES.length = 0; noticesDraw(); };
  const more_ = $("[data-notices-more]", box);
  if (more_) more_.onclick = () => { noticesOpen = !noticesOpen; noticesDraw(); };
  $$("[data-notify-on]", box).forEach(b => b.onclick = async () => { await Notification.requestPermission(); noticesDraw(); });
}
/* Settings → General: check desktop notifications end to end, and say what's in the way when they don't show. */
function notifyRow() {
  const p = "Notification" in window ? Notification.permission : "unsupported";
  const say = { granted: "Allowed in this browser.", denied: "Blocked in this browser: allow it in the site settings (the icon left of the address).", default: "Not asked yet.", unsupported: "This browser can't show them." }[p];
  return `<div class="set-row"><div><div class="set-label">Desktop notifications</div><div class="set-help">When a review or a fix finishes. ${esc(say)} If the test shows nothing, macOS is holding them: System Settings → Notifications → your browser → Allow notifications, and check Focus is off.</div></div>
    <div class="row"><button class="btn small" id="notify-test">${p === "default" ? "Allow and send a test" : "Send a test"}</button><span class="save-msg" id="notify-msg"></span></div></div>`;
}
async function loadBranches() {
  /* runs and checks are tagged with the branch they ran on; the code map is one per project */
  const sel = $("#branch");
  let B = null;
  try { B = state.repo ? await api("branches", { branch: "" }) : null; } catch (e) { B = null; }
  B = B || { branches: [], unrecorded: 0 };
  const known = new Set(B.branches.map(b => b.name).concat(B.unrecorded ? ["-"] : []));
  state.branch = localStorage.getItem(branchPref()) || "";
  if (!known.has(state.branch)) state.branch = "";
  const opt = (v, label) => `<option value="${esc(v)}" ${v === state.branch ? "selected" : ""}>${esc(label)}</option>`;
  sel.innerHTML = opt("", "All branches") + B.branches.map(b => opt(b.name, b.name + (b.state === "current" ? " (checked out)" : b.state === "deleted" ? " (deleted)" : ""))).join("") + (B.unrecorded ? opt("-", "Older runs (branch unknown)") : "");
  sel.disabled = !state.repo;
  // a filter needs two things to choose between: hide it (icon too) until runs exist on two branches
  const choices = B.branches.filter(b => b.runs).length + (B.unrecorded ? 1 : 0);
  sel.closest("label").hidden = choices < 2;
  if (choices < 2 && state.branch) { state.branch = ""; localStorage.removeItem(branchPref()); }
  sel.title = "Show runs and checks from one branch. The code map always follows the checked-out branch.";
}
/* "Update ready": newer LFG in your fork or the original project. Checked on load, every minute and when the tab
   comes back; the server caches for a minute, so a new merge shows within about two. */
const UPDATE_FROM = { upstream: "the original LFG", origin: "your fork" };
let updateRecheck = 0;
/* What every tab shows while an update runs: the steps so far, the one running and how long it has been going. */
const UPDATE_STEP_HINT = { "Running LFG's tests": "about a minute; if they fail, nothing changes" };
function runningMsg(j) {
  const steps = j.steps || [], now = steps.slice(-1)[0] || "Starting";
  const done = steps.slice(0, -1).map(s => `<li>${dot("ok")}${esc(s)}</li>`).join("");
  const hint = UPDATE_STEP_HINT[now] ? ` <span class="muted">(${esc(UPDATE_STEP_HINT[now])})</span>` : "";
  const open = !!$("#update-banner details.inline[open]");  // the banner redraws every few seconds: stay open if you opened it
  return `${dot("on")}<span><b>Updating LFG:</b> ${esc(now)}…${hint} <span class="muted small">started ${ago(j.started)}. You can leave this page; every tab shows this.</span></span>${done ? `<details class="more inline"${open ? " open" : ""}><summary>${plural(steps.length - 1, "step")} finished</summary><ul class="small">${done}</ul></details>` : ""}`;
}
/* Tabs tell each other when an update starts or ends, so none keeps offering an Update button meanwhile. */
const updateTabs = "BroadcastChannel" in window ? new BroadcastChannel("lfg-update") : null;
if (updateTabs) updateTabs.onmessage = () => watchUpdate();
/* A tab left open across an Update still runs the old script (only the tab you pressed Update in reloads). When the
   server's files differ from the ones this tab loaded, reload it: at once, or, while you're typing, from a banner. */
const PAGE_BUILD = (document.querySelector('meta[name="lfg-build"]') || {}).content || "";
function staleTab(d, j) {
  if (!PAGE_BUILD || !d.build || d.build === PAGE_BUILD || (j && j.status === "running")) return false;
  const el = document.activeElement, typing = el && /^(TEXTAREA|INPUT)$/.test(el.tagName) && el.value;
  if (!typing) { location.reload(); return true; }
  const box = $("#update-banner");
  box.hidden = false;
  box.className = "callout";
  morph(box, `${dot("on")}LFG was updated. <button class="btn small primary" data-reload-now>Reload</button> to use the new version.`);
  const b = $("[data-reload-now]", box);
  if (b) b.onclick = () => location.reload();
  return true;
}
async function checkUpdate(fresh) {
  const box = $("#update-banner");
  if (!box) return;
  let d;
  try { d = await api("update", fresh === true ? { fresh: "1" } : {}); } catch (e) { return; }
  /* an answer older than the cache means the server only just started a new check: ask again once it's done */
  if (d.checked_at && Date.now() - Date.parse(d.checked_at) > 70e3 && Date.now() - updateRecheck > 30e3) {
    updateRecheck = Date.now();
    setTimeout(checkUpdate, 5000);
  }
  const j = d.job;
  if (staleTab(d, j)) return;
  if (j && j.status === "running") {
    box.hidden = false;
    box.className = "callout";
    morph(box, runningMsg(j));
    watchUpdate();
    return;
  }
  const F = d.fix;
  if (F && F.status === "running") {
    box.hidden = false;
    box.className = "callout";
    morph(box, fixingMsg(F));
    watchUpdate();
    return;
  }
  const R = d.remotes || {}, H = d.held;
  const named = r => `${UPDATE_FROM[r]}${(R[r] || {}).name ? ` (${R[r].name})` : ""}`;
  if (H && H.state !== "ready") {
    /* a merge that conflicted, or code whose tests failed: it waits on its own branch until it's fixed and committed */
    box.hidden = false;
    box.className = "callout bad";
    const ver = $("#lfg-version");
    if (ver) ver.textContent = "Update stopped";
    const what = H.state === "tests" ? "LFG's tests fail on the new code"
      : `the changes from ${esc(named("upstream"))} ${H.state === "conflict" ? `conflict with yours in ${plural(H.files.length, "file")}` : "are merged but not committed yet"}`;
    /* Fix with Claude stopped for a decision only you can make: the question, and a prompt for a session of your own */
    const ask = F && F.status === "needs_you" && F.branch === H.branch ? F : null;
    const tried = ask ? `<div class="picks"><span class="tag warn">Needs your decision</span> <span class="pre-wrap">${esc(ask.question || "")}</span>
        <div class="mt"><button class="btn small primary" data-copy="${esc(ask.session || "")}">Copy prompt for a Claude session</button>
        <span class="muted small">Paste it into a new Claude Code session and decide there; it adds your decision to FORK.md so the next update follows it. Then press Update.</span></div></div>`
      : F && F.status === "failed" && F.branch === H.branch ? `<span class="muted small pre-wrap">The last try ${ago(F.ended)} stopped: ${esc(F.why || "")}</span>` : "";
    const unlocked = await isUnlocked();
    box.innerHTML = `<span>${dot("bad")}<b>LFG update stopped:</b> ${what}. Nothing changed on main and nothing was installed; it's on <code>${esc(H.branch)}</code> in <code>${esc(H.worktree)}</code>.</span>
      ${H.files.length ? `<details class="more inline"><summary>${H.state === "conflict" ? "Conflicting files" : "Changed files"}</summary><ul>${H.files.map(f => `<li class="mono small">${esc(f)}</li>`).join("")}</ul></details>` : ""}
      ${H.output ? `<details class="more inline"><summary>Test output</summary><pre class="raw mono small">${esc(H.output)}</pre></details>` : ""}
      ${tried}
      <button class="btn small primary" id="update-fix" ${unlocked ? "" : "disabled title=\"Open the dashboard with lfg ui to fix from here\""}>${tried ? "Try again" : "Fix with Claude"}</button>
      <button class="btn small" data-copy="${esc(H.prompt)}" title="${esc(H.prompt)}">Copy fix for Claude</button>
      <span class="muted small">Fix with Claude runs Claude Code on that branch by itself, LFG commits its fix, then runs the update again; it never touches main. Try again picks up a fix the last try left: if the tests pass on it, it is only committed. Or paste the fix into Claude Code yourself and press Update once it's committed.</span>`;
    $$("[data-copy]", box).forEach(b => b.onclick = async () => {
      try { await navigator.clipboard.writeText(b.dataset.copy); b.textContent = "Copied"; } catch (e) { window.prompt("Copy this:", b.dataset.copy); }
    });
    const fx = $("#update-fix");
    if (fx) fx.onclick = async () => {
      fx.disabled = true; fx.textContent = "Starting…";
      const r = await save("update_fix", {});
      if (!r.ok) { fx.disabled = false; fx.textContent = "Try again"; return alertMsg(fx, r); }
      if (updateTabs) updateTabs.postMessage("started");
      startedHere = true;
      watchUpdate();
    };
    return;
  }
  const seen = localStorage.getItem("lfg.update.seen") === (j && j.ended);
  if (j && j.status === "done" && !seen && !(d.available && d.ready) && Date.now() - Date.parse(j.ended) < 15 * 60e3) {
    box.hidden = false;
    box.className = "callout ok";
    box.innerHTML = `<span>${dot("ok")}<b>LFG updated ${ago(j.ended)}</b>: tests passed and it's installed${(j.changes || []).length ? `, ${plural(j.changes.length, "change")}: ${esc(j.changes.map(c => c.replace(/^\S+ /, "")).slice(0, 3).join("; "))}${j.changes.length > 3 ? "…" : ""}` : ""}. This page runs the new version. <b>Start a new Claude Code session</b> for new or changed skills; sessions already open keep the old ones.</span> <button class="btn small" id="update-ok">OK</button>`;
    $("#update-ok").onclick = () => { localStorage.setItem("lfg.update.seen", j.ended); box.hidden = true; };
    return;
  }
  if (j && j.status === "failed" && !seen && !(d.available && d.ready && Date.parse(j.ended) < Date.now() - 60e3)) {
    box.hidden = false;
    box.className = "callout bad";
    box.innerHTML = `<span>${dot("bad")}The update didn't go through: <span class="pre-wrap">${esc(j.why || "")}</span></span> <button class="btn small" id="update-ok">OK</button>`;
    $("#update-ok").onclick = () => { localStorage.setItem("lfg.update.seen", j.ended); box.hidden = true; };
    return;
  }
  const ver = $("#lfg-version");
  if (ver && d.available) ver.textContent = d.ready ? "Update ready" : "LFG up to date";
  if (d.pending) { if (ver) ver.textContent = "Checking for updates…"; setTimeout(checkUpdate, 3000); return; }
  const aside = (d.upstream || []).filter(c => c.verdict !== "keep");
  if (ver && d.available && !d.ready && aside.length) {
    ver.innerHTML = `LFG up to date · <a href="" id="show-aside">${plural(aside.length, "change")} set aside</a>`;
    $("#show-aside").onclick = e => { e.preventDefault(); showAside = !showAside; checkUpdate(); };
  }
  if (!d.available || (!d.ready && !(showAside && aside.length))) { box.hidden = true; return; }
  if (!d.ready) {
    const unlocked = await isUnlocked();
    box.hidden = false;
    box.className = "callout";
    box.innerHTML = `${dot("off")}<span><b>Set aside from ${esc(named("upstream"))}:</b> nothing is installed until you press Keep on one; Update then brings in only the kept ones.</span>${upstreamPicks(d, named("upstream"), unlocked)}`;
    wirePicks(box);
    return;
  }
  const src = d.sources || [], parts = src.map(r => src.length === 1 ? plural(R[r].new, "change") : `${plural(R[r].new, "change")} from ${named(r)}`);
  if (d.not_installed) parts.push(`${plural(d.not_installed, "change")} in your checkout not installed yet`);
  if (H) parts.push(`the merge on ${H.branch}, fixed and committed`);
  const from = src.length === 2 ? "from both the original LFG and your fork" : src.length ? `from ${named(src[0])}` : "";
  const li = c => `<li class="mono small">${esc(c)}</li>`, group = (title, cs) => cs.length ? `<li><b>${esc(title)}</b><ul>${cs.map(li).join("")}</ul></li>` : "";
  const list = src.filter(r => r !== "upstream").map(r => group(`From ${named(r)}`, R[r].commits || [])).concat(group("In your checkout, not installed yet", d.not_installed_commits || []));
  /* Update merges into main in the LFG checkout, so it waits while that checkout is on another branch or has
     uncommitted changes. Say which, and give the one safe command when there is one. */
  const onBranch = d.current_branch && d.current_branch !== "main" ? d.current_branch : "";
  const toMain = `git -C ${shq(d.source)} checkout main`;
  const blocked = d.dirty ? `<b>Can't update yet:</b> your LFG checkout <code>${esc(d.source)}</code> has uncommitted changes${onBranch ? ` on <code>${esc(onBranch)}</code>` : ""}. Commit or stash them there${onBranch ? " and switch it back to main" : ""}, then press Refresh.`
    : onBranch ? `<b>Can't update yet:</b> your LFG checkout <code>${esc(d.source)}</code> is on <code>${esc(onBranch)}</code>, not main. Switch it back, then press Refresh. <button class="btn small primary" data-copy="${esc(toMain)}" title="${esc(toMain)}">Copy command</button>` : "";
  const unlocked = await isUnlocked();
  box.hidden = false;
  box.className = "callout warn";
  box.innerHTML = `${dot("warn")}<b>LFG update ready${from ? ` ${esc(from)}` : ""}:</b> ${esc(parts.join(", "))}. ${list.some(Boolean) ? `<details class="more inline"><summary>What's in it</summary><ul>${list.join("")}</ul></details>` : ""}
    ${upstreamPicks(d, named("upstream"), unlocked)}${heldNotes(H)}
    ${blocked ? `<span>${blocked}</span>` : `<button class="btn small primary" id="update-go" ${unlocked ? "" : "disabled title=\"Open the dashboard with lfg ui to update from here\""}>Update</button><span class="muted small"> Tests run first; if they fail nothing changes.</span>`}`;
  $$("[data-copy]", box).forEach(b => b.onclick = async () => {
    try { await navigator.clipboard.writeText(b.dataset.copy); b.textContent = "Copied"; } catch (e) { window.prompt("Copy this:", b.dataset.copy); }
  });
  wirePicks(box);
  const go = $("#update-go");
  if (go) go.onclick = async () => {
    go.disabled = true; go.textContent = "Starting…";
    const r = await save("update_apply", {});
    if (!r.ok) { go.disabled = false; go.textContent = "Try again"; return alertMsg(go, r); }
    box.className = "callout";
    box.innerHTML = runningMsg({ steps: [], started: new Date().toISOString() });  /* at once, not at the next poll */
    if (updateTabs) updateTabs.postMessage("started");
    startedHere = true;
    watchUpdate();
  };
}
/* Upstream's commits one by one. Keep is the default; Later stays listed for another day; Skip stays listed, greyed,
   and is never brought in unless you press Keep on it. */
let showAside = false;
function upstreamPicks(d, from, unlocked) {
  const U = d.upstream || [];
  if (!U.length) return "";
  const label = { keep: "Keep", later: "Later", skip: "Skip" };
  const row = c => {
    const clash = c.conflicts == null ? "" : c.conflicts.length
      ? `<span class="tag warn" title="${esc(c.conflicts.join("\n"))}">Conflicts with your fork in ${plural(c.conflicts.length, "file")}</span>`
      : `<span class="tag ok">No conflicts with your fork</span>`;
    const btns = Object.keys(label).map(v => `<label class="${c.verdict === v ? "on" : ""}" ${unlocked ? "" : `title="Read-only in this tab: run lfg ui --unlock --port ${esc(location.port || "80")}"`}><input type="radio" name="pick-${c.short}" data-sha="${c.sha}" value="${v}" ${c.verdict === v ? "checked" : ""} ${unlocked ? "" : "disabled"}>${label[v]}</label>`).join("");
    return `<li class="pick${c.verdict === "skip" ? " skipped" : ""}"><span><span class="mono small">${esc(c.short)}</span> ${esc(c.subject)} ${clash}</span><span class="seg inline">${btns}</span></li>`;
  };
  const n = v => U.filter(c => c.verdict === v).length;
  const sum = [n("keep") && `${n("keep")} kept`, n("later") && `${n("later")} for later`, n("skip") && `${n("skip")} skipped`].filter(Boolean).join(", ");
  return `<div class="picks"><div class="small"><b>From ${esc(from)}</b> <span class="muted">(${sum}). Update brings in only what's kept. Later stays here until you decide; Skip leaves it out for good unless you press Keep.</span></div><ul>${U.map(row).join("")}</ul></div>`;
}
/* What a prepared update branch keeps and leaves out of upstream's changes, from its commit message. */
function heldNotes(H) {
  if (!H || !((H.kept || []).length || (H.not_kept || []).length)) return "";
  const ul = (t, xs, cls) => xs.length ? `<div class="small"><span class="tag ${cls}">${t}</span><ul>${xs.map(x => `<li>${esc(x)}</li>`).join("")}</ul></div>` : "";
  return `<div class="picks">${ul("Keeping", H.kept || [], "ok")}${ul("Not keeping", H.not_kept || [], "bad")}<div class="muted small">Prepared on <code>${esc(H.branch)}</code>. Update installs exactly this.</div></div>`;
}
function wirePicks(box) {
  $$(".picks input[data-sha]", box).forEach(i => i.onchange = async () => {
    const group = $$(`input[name="${i.name}"]`, box), seg = i.closest(".seg");
    group.forEach(x => { x.disabled = true; x.parentNode.classList.toggle("on", x === i); });
    const note = document.createElement("span");
    note.className = "muted small saving"; note.textContent = "Saving…";
    seg.after(note);
    const r = await save("update_pick", { sha: i.dataset.sha, verdict: i.value });
    if (!r.ok) { note.remove(); group.forEach(x => (x.disabled = false)); return alertMsg(i.parentNode, r); }
    checkUpdate();  /* the server re-checked without asking GitHub, so this answers at once */
  });
}
const fixingMsg = F => `${dot("on")}Claude is fixing the stopped update${F.branch ? ` on <code>${esc(F.branch)}</code>` : ""}, started ${ago(F.started)}. Once it has a fix, LFG commits it and runs the update again by itself.`;
let watching = false;  /* one watcher at a time: the banner re-checks every minute and would start another */
let startedHere = false;  /* only the tab that pressed Update restarts the dashboard; the others show "updated" */
async function watchUpdate() {
  if (watching) return;
  watching = true;
  try { await watchLoop(); } finally { watching = false; }
}
async function watchLoop() {
  const box = $("#update-banner");
  for (;;) {
    await new Promise(r => setTimeout(r, 2500));
    let d;
    try { d = await api("update", { t: Date.now() }); } catch (e) { continue; }
    const j = d.job || {}, F = d.fix || {};
    box.hidden = false;
    if (j.status === "running") { box.className = "callout"; box.innerHTML = runningMsg(j); continue; }
    if (F.status === "running") { box.className = "callout"; box.innerHTML = fixingMsg(F); continue; }
    if (j.status === "done" && startedHere) {
      box.innerHTML = `${dot("on")}Installed. Reloading the dashboard on the new version…`;
      await save("ui_restart", {});
      for (let i = 0; i < 40; i++) {
        await new Promise(r => setTimeout(r, 750));
        try { const r = await fetch("/api/unlocked", { headers: { "X-LFG": "1" } }); if (r.status) { location.reload(); return; } } catch (e) { /* restarting */ }
      }
      return;
    }
    return checkUpdate(true);
  }
}
setInterval(checkUpdate, 60 * 1000);
document.addEventListener("visibilitychange", () => { if (!document.hidden) checkUpdate(); });
window.addEventListener("focus", () => checkUpdate());
function refresh() { Object.keys(state.snips || {}).forEach(k => { if (!state.snips[k]) delete state.snips[k]; }); state.cache = {}; state.fresh = true; mapStatus(); checkUpdate(true); route().finally(() => { state.fresh = false; }); }
/* Pages whose data changes without you (GitHub, running jobs) reload every 10 minutes, unless you're typing or a
   drawer is open, so nothing you're in the middle of is thrown away. */
const AUTO_REFRESH = ["home", "sessions", "environment", "prs", "checks", "runs", "issues"];
setInterval(() => {
  const page = (location.hash.slice(1) || "home").split("/")[0];
  const busy = document.hidden || document.querySelector("#drawer:not([hidden])") ||
    ["TEXTAREA", "INPUT", "SELECT"].includes((document.activeElement || {}).tagName);
  if (AUTO_REFRESH.includes(page) && !busy) { state.cache = {}; state.fresh = true; softRoute().finally(() => { state.fresh = false; }); }  // in place
}, 10 * 60 * 1000);
init();
