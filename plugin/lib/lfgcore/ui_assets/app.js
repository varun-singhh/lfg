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
  if (s < 3600) return Math.floor(s / 60) + " min ago";
  if (s < 86400) return Math.floor(s / 3600) + " h ago";
  const d = Math.floor(s / 86400);
  return d === 1 ? "yesterday" : d + " days ago";
}
const pct = (a, b) => (b ? Math.round((100 * a) / b) : 0);
const plural = (k, w) => `${n(k)} ${w}${k === 1 ? "" : "s"}`;
const words = s => String(s || "").replace(/[-_]+/g, " ").replace(/\.md$/, "");
const state = { repo: localStorage.getItem("lfg.repo") || "", branch: "", repos: [], cache: {} };
const branchPref = () => "lfg.branch." + state.repo;

async function api(view, params = {}) {
  const q = new URLSearchParams({ repo: state.repo, ...(state.branch ? { branch: state.branch } : {}), ...params });
  const r = await fetch(`/api/${view}?${q}`, { headers: { "X-LFG": "1" } });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

const repoName = (id = state.repo) => (state.repos || []).find(x => x.id === id)?.name || id;
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
  pass: ["Passed", "ok"], fail: ["Failed", "bad"],
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
const STEP = { brief: "Idea written up", design: "Plan", tasks: "Task list", build: "Built", qa: "Tested", gate: "Checks run",
  secure: "Security check", review: "Code review", ship: "Ship check", packet: "Ready to commit" };
const NEXT = { brief: "write up the idea", design: "make a plan", tasks: "split it into tasks", build: "build it", qa: "test it",
  gate: "run the checks", secure: "check security", review: "review the code", ship: "run the ship check", packet: "prepare the commit message",
  "fix-checks": "fix the failing checks (/lfg:fix)", "fix-block": "decide what to do about the blocked review",
  "fix-review": "address the review's requested changes", "fix-security": "fix the security problems (/lfg:fix)",
  "fix-ship": "fix what the ship check found" };
function runPlace(stages, done, r) {
  /* done = steps that really happened; next = what blocks first (a failing check, a review asking for changes),
     else the step after the furthest one done (review-only runs skip the early steps, so those don't count as next) */
  const keys = stages.map(s => s[0]), last = keys.reduce((a, x, i) => (done[x] ? i : a), -1);
  const count = keys.filter(k => done[k]).length;
  const block = r && (r.ready === "red" ? "fix-checks" : r.review === "block" ? "fix-block" : r.secure === "don't" ? "fix-security"
    : r.review === "changes" ? "fix-review" : r.shipcheck === "fail" ? "fix-ship" : null);  // most serious first
  const next = block || keys.slice(last + 1)[0];
  return { done: count, total: keys.length, next, blocked: !!block, finished: !next };
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
let TID = 0;
const TABLES = {};
function table(rows, cols, opts = {}) {
  const id = "t" + ++TID;
  if (!rows || !rows.length) return empty(opts.emptyTitle || "Nothing here yet", opts.emptyBody || "");
  TABLES[id] = { rows, cols, opts, sort: opts.sort || null, dir: opts.dir || -1, filter: "" };
  const tools = rows.length > 15 && opts.filter !== false ?
    `<div class="table-tools"><input type="search" placeholder="Search…" data-filter="${id}"><span class="count" id="${id}-count"></span></div>` : "";
  return `${tools}<div class="table-wrap"><table id="${id}"></table></div>`;
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
  el.innerHTML = `<thead><tr>${t.cols.map(c => `<th data-k="${esc(c.k)}" class="${c.num ? "num" : ""} ${t.sort === c.k ? (t.dir > 0 ? "sorted-asc" : "sorted-desc") : ""}">${esc(c.label)}</th>`).join("")}</tr></thead>
    <tbody>${shown.map(r => `<tr class="${t.opts.onRow ? "click" : ""}" data-i="${t.rows.indexOf(r)}">${t.cols.map(c => `<td class="${c.num ? "num" : ""}">${c.html ? c.html(r) : c.num ? n(r[c.k]) : esc(r[c.k])}</td>`).join("")}</tr>`).join("")}</tbody>`;
  const cnt = document.getElementById(id + "-count");
  if (cnt) cnt.textContent = rows.length === t.rows.length ? plural(rows.length, "item") : `${n(rows.length)} of ${n(t.rows.length)}`;
  $$("th", el).forEach(th => th.onclick = () => { const k = th.dataset.k; t.dir = t.sort === k ? -t.dir : -1; t.sort = k; drawTable(id); });
  if (t.opts.onRow) $$("tbody tr", el).forEach(tr => tr.onclick = () => t.opts.onRow(t.rows[+tr.dataset.i]));
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
  return `<div class="tabs" data-tabs="${id}">${list.map(([k, l, c]) => `<button class="tab" data-k="${esc(k)}">${esc(l)}${c ? `<span class="n">${compact(c)}</span>` : ""}</button>`).join("")}</div><div id="${id}-body"></div>`;
}
function mountTabs(root = document) {
  $$("[data-tabs]", root).forEach(bar => {
    const id = bar.dataset.tabs;
    const show = k => {
      $$(".tab", bar).forEach(b => { b.classList.toggle("on", b.dataset.k === k); if (b.dataset.k === k && bar.scrollWidth > bar.clientWidth) bar.scrollLeft = b.offsetLeft - 16; });
      const it = TABS[id].find(x => x[0] === k);
      const body = document.getElementById(id + "-body");
      body.innerHTML = it[3]();
      mountTables(body); mountTabs(body); wire(body);
      sessionStorage.setItem("lfg.tab." + id, k);
    };
    $$(".tab", bar).forEach(b => b.onclick = () => show(b.dataset.k));
    const saved = sessionStorage.getItem("lfg.tab." + id);
    show(TABS[id].some(x => x[0] === saved) ? saved : TABS[id][0][0]);
  });
}

/* Interactive bars: hover or focus a day for its numbers, click it to pin it (onPick), click a legend key to hide a
   series. data: [{label, values: [..], raw}], series: [[name, color, fmt]]. The y-axis gutter fits its labels. */
const ICHARTS = {};
let ICID = 0;
function iChart(data, series, opts = {}) {
  const id = "ic" + ++ICID;
  ICHARTS[id] = { data, series, opts, hidden: new Set(opts.hidden || []), pick: opts.pick ?? null };
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
/* simple bar chart: data=[{label, values:[...]}], series=[[name,color]] */
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
function md(text, link) {
  const L = String(text || "").replace(/\r/g, "").split("\n");
  let out = "", i = 0;
  const para = [];
  const flush = () => { if (para.length) { out += `<p>${inline(para.join(" "), link)}</p>`; para.length = 0; } };
  while (i < L.length) {
    const l = L[i];
    if (/^```/.test(l)) {
      flush(); const buf = []; i++;
      while (i < L.length && !/^```/.test(L[i])) buf.push(L[i++]);
      i++; out += `<pre><code>${esc(buf.join("\n"))}</code></pre>`; continue;
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
      out += `<${ordered ? "ol" : "ul"}>${buf.map(b => `<li>${inline(b, link)}</li>`).join("")}</${ordered ? "ol" : "ul"}>`; continue;
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
const txt = v => inline(typeof v === "string" ? v : v == null ? "" : String(v));
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
  return `<div class="card"><div class="row">${st(f.severity)}${f.blocking === true ? '<span class="tag">must fix before shipping</span>' : ""}${f.axis ? `<span class="tag">${esc(AXIS[f.axis] || words(f.axis))}</span>` : ""}${f.feedback ? st(f.feedback) : ""}</div>
    <div class="title">${txt(head)}</div>
    ${more ? `<p>${txt(more)}</p>` : ""}
    ${f.fix ? `<p><b>What to do:</b> ${txt(f.fix)}</p>` : ""}
    ${f.reachable ? `<p class="muted small">Can an attacker reach it? ${txt(f.reachable)}</p>` : ""}
    ${f.principle && f.principle !== "None" ? `<p class="muted small">Based on: ${txt(f.principle)}</p>` : ""}
    ${links.length ? `<p class="small">${links.map(u => `<a href="${esc(u)}" target="_blank" rel="noopener noreferrer">Read the advisory ↗</a>`).join(" · ")}</p>` : ""}
    ${where ? `<div class="muted small mono">${esc(where)}</div>` : ""}</div>`;
}
const SEV_RANK = { blocker: 0, critical: 0, high: 1, major: 1, medium: 2, moderate: 2, minor: 3, low: 3, nit: 4 };
const sevRank = f => (f.blocking === true ? -1 : 0) + (SEV_RANK[String(f.severity).toLowerCase()] ?? 5);
const findingList = (fs, none) => (fs || []).length ? [...fs].sort((a, b) => sevRank(a) - sevRank(b)).map(findingCard).join("") : `<p class="muted">${esc(none || "Nothing found.")}</p>`;
/* A task: its description, opening to the steps and how it's checked */
function taskItem(t) {
  if (!t || typeof t !== "object") return "";
  const steps = Array.isArray(t.steps) ? t.steps : [], deps = Array.isArray(t.depends_on) ? t.depends_on : [];
  const body = `${steps.length ? `<div class="k">Steps</div><ol>${steps.map(s => `<li>${txt(s)}</li>`).join("")}</ol>` : ""}
    ${t.verification ? `<div class="k">How we know it works</div><p>${txt(t.verification)}</p>` : ""}
    ${t.notes ? `<div class="k">Notes</div><p>${txt(t.notes)}</p>` : ""}
    ${deps.length ? `<p class="muted small">Waits for: ${esc(deps.join(", "))}</p>` : ""}`;
  return `<details class="item"><summary>${dot(t.passes ? "ok" : "")}<span class="grow">${txt(t.description || t.id || "Task")}</span><span class="muted small nowrap">${t.passes ? "done" : "to do"}</span></summary><div class="item-body">${body}</div></details>`;
}
/* A check that ran (tests, lint, ship check): failed ones open to show the error */
const CHECK_NAMES = { lint: "Lint", types: "Type check", test: "Tests", build: "Build", secrets: "Secret scan",
  suppressions: "No new lint or test suppressions" };
function checkItem(name, result, out, cmd) {
  const [word, tone] = { pass: ["passed", "ok"], fail: ["failed", "bad"], skip: ["not run", ""], na: ["doesn't apply", ""], manual: ["for you to do", "warn"] }[result];
  const body = !["pass", "skip", "na"].includes(result) && out ? `${cmd ? `<div class="muted small mono">${esc(cmd)}</div>` : ""}<pre class="out">${esc(out)}</pre>` : "";
  return `<details class="item${body ? "" : " plain"}"><summary>${dot(tone)}<span class="grow">${esc(CHECK_NAMES[name] || (/\s/.test(name || "") ? name : (w => w.charAt(0).toUpperCase() + w.slice(1))(words(name || ""))))}</span><span class="muted small nowrap">${word}</span></summary>${body ? `<div class="item-body">${body}</div>` : ""}</details>`;
}
const readyChecks = cs => (cs || []).map(c => checkItem(c.name, c.exit === 0 ? "pass" : c.exit == null ? "skip" : "fail", c.tail, c.cmd)).join("");
const shipChecks = cs => (cs || []).map(c => checkItem(c.check || c.name, c.manual ? "manual" : c.status === "n/a" ? "na" : c.ok ? "pass" : c.ok == null ? "skip" : "fail", c.detail)).join("");
/* 07-shipcheck.json: part A (container) checks + the shipping checklist, as one list (same as dash.shipcheck_items) */
const shipItems = d => [].concat(((d.part_a || {}).checks || []).map(c => ({ check: c.check, ok: c.severity === "warn" && c.ok === false ? null : c.ok, detail: c.detail })),
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
  "07-shipcheck.json": d => `<p>${st(d.pass ? "pass" : "fail")}</p>${(d.part_a || {}).note ? `<p class="muted">${txt(d.part_a.note)}</p>` : ""}${shipChecks(shipItems(d))}${moreDetails(d, ["pass", "part_a", "part_b", "checklist", "ts", "run", "run_id"])}`,
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
document.addEventListener("keydown", openKnow);

function wire(root) {
  $$("[data-run-file]", root).forEach(a => a.onclick = async e => {
    e.preventDefault();
    const [run, f] = JSON.parse(a.dataset.runFile);
    const d = await api("file", { run, f });
    openDrawer(a.textContent, renderFile(f, d.text));
  });
  $$("[data-view]", root).forEach(b => b.onclick = async () => {
    const box = document.getElementById(b.dataset.target);
    box.innerHTML = '<div class="loading">Opening… large repos can take a minute the first time.</div>';
    const d = await api("view", { kind: b.dataset.view });
    box.innerHTML = d.src ? `<iframe class="viewer mt" src="${esc(d.src)}" title="${esc(b.textContent)}" referrerpolicy="no-referrer"></iframe>` : empty("Not made yet", fmtWhy(d.message));
  });
  $$("[data-rule-module]", root).forEach(a => a.onclick = e => {
    e.preventDefault();
    const m = (state.rules.modules || []).find(x => x.name === a.dataset.ruleModule);
    if (m) openDrawer(words(m.name), renderFile(m.name + ".md", m.text));
  });
  wireSettings(root);
  wireMap(root);
  $$("[data-run-checks]", root).forEach(b => b.onclick = async () => {
    b.disabled = true; b.textContent = "Starting…";
    const r = await save("run_checks", { repo: state.repo, run: b.dataset.runChecks });
    if (!r.ok) { b.disabled = false; b.textContent = "Run checks again"; alert(String(r.why || "Couldn't start the checks.").replace(/`/g, "")); return; }
    state.cache = {}; route();
  });
  if ($("[data-checks-running]", root)) setTimeout(() => { if (document.body.contains(root) && $("[data-checks-running]", root)) { state.cache = {}; route(); } }, 10000);
  if ($("[data-spend-pending]", root)) setTimeout(() => { if (document.body.contains(root) && $("[data-spend-pending]", root)) route(); }, 4000);
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
function mountRuleTips() {
  new MutationObserver(ms => ms.forEach(m => m.addedNodes.forEach(decorateRules))).observe(document.body, { childList: true, subtree: true });
  decorateRules(document.body);
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
const editKey = () => localStorage.getItem("lfg.editKey") || "";
async function isUnlocked() {
  if (!editKey()) return false;
  try {
    const r = await fetch("/api/unlocked", { headers: { "X-LFG": "1", "X-LFG-Key": editKey() } });
    return r.ok && (await r.json()).ok;
  } catch (e) { return false; }
}
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
  if (f.type === "bool") return `<input type="checkbox" id="${id}" data-cfg="${esc(f.key)}" ${v ? "checked" : ""} ${dis}>`;
  if (f.type === "choice") return `<select id="${id}" data-cfg="${esc(f.key)}" ${dis}>${f.options.map(o => `<option ${o === v ? "selected" : ""}>${esc(o)}</option>`).join("")}</select>`;
  if (f.type === "int") return `<input type="number" id="${id}" data-cfg="${esc(f.key)}" min="${f.min}" max="${f.max}" value="${esc(v)}" ${dis}>`;
  const val = Array.isArray(v) ? v.join(", ") : v ?? "";
  return `<input type="text" id="${id}" data-cfg="${esc(f.key)}" value="${esc(val)}" ${dis}>`;
}
function settingsGeneral() {
  const { cfg, unlocked } = state.settings;
  return `<div>${cfg.fields.filter(f => !f.owner).map(f => `<label class="set-row" for="cfg-${esc(f.key)}"><div><div class="set-label">${esc(f.label)}</div><div class="set-help">${esc(f.help || "")}</div></div><div class="set-input">${fieldInput(f, !unlocked)}</div></label>`).join("")}</div>
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
    <div class="set-section"><h4>Safety rules</h4><p class="muted">What every LFG session must follow. LFG enforces these in code, so they can't be changed or switched off here.</p>
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
  box.innerHTML = `<p><b>Add a rule</b></p><p class="muted small">Give it a short name (lowercase, dashes) and write it in Markdown. Agents read it with <code>lfg rule &lt;name&gt;</code>, and new sessions are told to follow it.</p>
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
  return '<div id="cc-box"><div class="loading">Looking at your Claude Code setup…</div></div>';
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
  box.innerHTML = `<p class="muted">What LFG does to Claude Code, and where. Everything here is recorded and can be undone; nothing outside the repos you pick is touched.</p>
    <span class="save-msg" id="cc-msg"></span>${legacy}
    <div class="set-section"><h4>Where LFG is on</h4><p class="muted">In other repos Claude Code works exactly as if LFG weren't installed: no skills, hooks or MCP servers.</p>
      <label class="row"><input type="checkbox" data-cc="everywhere" ${R.everywhere ? "checked" : ""} ${dis}> Turn LFG on in every repo <span class="muted small">(not recommended)</span></label>
      <div class="box mt">${repoRows ? `<ul class="list">${repoRows}</ul>` : empty("No repos yet", "Run <code>lfg enable</code> in a repo, or open one in Claude Code after enabling it.")}</div></div>
    <div class="set-section"><h4>Integrations</h4><p class="muted">Feature packs (Headroom, SonarQube, Dictate, pentest with Ollama and Strix, and the rest) and their settings are on the <a href="#integrations">Integrations</a> page.</p></div>
    <div class="set-section"><h4>Safety</h4>
      <div class="box pad"><div class="row">${dot("ok")}<div class="grow"><b>Guard</b><div class="meta">On in every LFG repo: blocks pushes, secret reads, deploys and the rest of the 18 rules (Settings → Rules), and asks you before any commit. Recently blocked: ${d.blocked.length ? d.blocked.slice(0, 3).map(b => `rule ${esc(b.rule)} (${esc(b.tool)})`).join(", ") : "nothing"}.</div></div></div>
      <label class="row mt"><input type="checkbox" data-cc="commits" ${d.allow_commits ? "checked" : ""} ${dis}><span><b>Let Claude commit when I ask</b><span class="meta"> · each commit becomes an approval prompt in Claude Code; pushing, merging, rebasing, PRs, secrets and deploys stay blocked</span></span></label>
      <label class="row mt"><input type="checkbox" data-cc="hardened" ${d.hardened ? "checked" : ""} ${dis}><span><b>Hardened mode</b><span class="meta"> · also add Claude Code deny rules (git commit/push, secret files…) to each LFG repo's <code>.claude/settings.local.json</code>, never to your user settings</span></span></label></div></div>
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
      <p class="muted small mt">To remove LFG completely, run <code>lfg uninstall</code> in your terminal. It lists everything it will undo before it does anything.</p></div>`;
  $$("[data-dict]", box).forEach(el => el.onchange = async () => {
    el.disabled = true;
    state.ccMsg = await save("config", { values: { [el.dataset.dict]: el.type === "checkbox" ? el.checked : el.value } });
    loadClaudeCode();
  });
  $$("[data-cc]", box).forEach(el => {
    const act = el.dataset.cc, ev = el.type === "checkbox" ? "onchange" : "onclick";
    el[ev] = async () => {
      if (act === "commits") { state.ccMsg = await save("config", { values: { "guard.allow_commits": el.checked } }); loadClaudeCode(); return; }
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
    ${unlocked ? "" : `<div class="callout">Read-only. To change anything, run <code>lfg ui</code> in your own terminal; it opens this page unlocked.</div>`}
    <span class="save-msg" id="int-msg"></span><div id="int-box"><div class="loading">Checking each integration…</div></div>`;
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
    if (i.name === "pentest" && i.on) return '<div class="int-sub"><div class="set-label">Local AI models (Ollama)</div><div id="ollama-box"><div class="loading">Asking the local Ollama…</div></div></div>';
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
  box.innerHTML = `<div class="int-list">${d.integrations.map(row).join("")}</div>
    <details class="int-tools"><summary class="muted small">Command-line tools LFG uses</summary><div id="int-tools" class="mt"><div class="loading">Checking…</div></div></details>`;
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
  $$("[data-cfg]", box).forEach(el => el.addEventListener("change", async () => {
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
    el.innerHTML = miss.length ? `<div class="box"><ul class="list">${miss.map(x => `<li>${dot(x.required ? "bad" : "")}<div class="grow"><div class="title">${esc(x.tool)} is not installed</div><div class="meta">${esc(x.purpose)}</div></div></li>`).join("")}</ul></div>` : `<p class="muted small">All ${n(t.tools.length)} tools are installed.</p>`; });
  clearTimeout(intTimer);
  if (Object.values(d.jobs).some(j => j.status === "running")) intTimer = setTimeout(() => { if (document.body.contains(box)) loadIntegrations(); }, 2000);
}

function settingsTools() {
  return '<div id="tools-box"><div class="loading">Checking…</div></div>';
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
    <div class="set-section"><h4>Command-line tools</h4>${missing.length
      ? `<div class="box"><ul class="list">${missing.map(t => `<li>${dot(t.required ? "bad" : "")}<div class="grow"><div class="title">${esc(t.tool)} is not installed</div><div class="meta">${esc(t.purpose)}${t.required ? (t.pack === "core" ? " · needed: run lfg setup" : ` · needed by the ${esc(t.pack)} pack: lfg add ${esc(t.pack)}`) : ` · ${esc(t.pack)} pack, not added`}</div></div></li>`).join("")}</ul></div>`
      : `<div class="box calm">${dot("ok")}All ${n(d.tools.length)} tools are installed.</div>`}</div>`;
}
function settingsOllama() {
  return '<div id="ollama-box"><div class="loading">Asking the local Ollama…</div></div>';
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
  box.innerHTML = `<p class="muted">Security tests (<code>/lfg:pentest</code>) run on a model on this computer, never in the cloud. ${d.running ? "" : fmtWhy(d.why)}</p>
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
      <div class="row mt"><input type="text" id="ollama-name" placeholder="Other model, e.g. qwen3:14b" ${dis}><button class="btn" id="ollama-pull" ${canPull}>Download</button><span class="save-msg" id="ollama-msg"></span></div></div>`;
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
  if ($("#cc-box", root)) loadClaudeCode();
  if ($("#skills-box", root)) loadSkills();
  if ($("#ollama-box", root)) loadOllama();
  if ($("#storage-box", root)) loadStorage();
  if ($("#tools-box", root)) loadTools();
  if ($("#int-box", root)) loadIntegrations();
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
  tourDraw();
}
function tourGo(d) { if (!TOUR) return; const n = TOUR.i + d; if (n >= TOURS[TOUR.name].length) return finishTour("finished"); TOUR.i = Math.max(0, n); tourDraw(); }
function tourDraw() {
  if (!TOUR) return;
  const steps = TOURS[TOUR.name], st = steps[TOUR.i], last = TOUR.i === steps.length - 1;
  const hole = $(".tour-hole", TOUR.box), card = $(".tour-card", TOUR.box), shade = $(".tour-shade", TOUR.box);
  const target = st.sel && $(st.sel);
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
/* The first time the dashboard opens after Dictate is set up: offer the tour, or skip it for good */
async function offerTours() {
  let t;
  try { t = await api("tours"); } catch (e) { return; }
  const seen = k => { try { return localStorage.getItem("lfg.tour." + k); } catch (e) { return null; } };
  const remember = (k, how) => { try { localStorage.setItem("lfg.tour." + k, how); } catch (e) { /* ignore */ } save("tour_done", { name: k, how }); };
  const d = t.dictate || {};
  const promo = $("#promo");
  promo.innerHTML = "";
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
const NAV = [["home", "Home"], ["runs", "Runs"], ["issues", "Issues"], ["review", "Reviews"], ["checks", "Checks"], ["code", "Code"], ["docs", "Docs"],
  ["knowledge", "Knowledge"], ["usage", "Usage"], ["skills", "Skills"], ["integrations", "Integrations"], ["settings", "Settings"], ["help", "Help"]];
const TITLES = Object.fromEntries(NAV);
const PAGES = {};

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
/* Things on a run that need a person, as [tone, text] */
function runAttention(r) {
  const out = [];
  if (r.review === "block") out.push(["bad", "The code review found something that must be fixed"]);
  else if (r.review === "changes") out.push(["warn", "The code review asked for changes"]);
  if (r.secure === "don't") out.push(["bad", "The security check found problems to fix"]);
  if (r.ready === "red") out.push(["bad", "Tests or checks are failing"]);
  else if (r.ready === "stale") out.push(["warn", "The last checks ran before the latest work, so their result is out of date: run /lfg:check"]);
  if (r.shipcheck === "fail") out.push(["bad", "The ship check failed"]);
  if (r.pentest === "refused") out.push(["warn", "The security test didn't run: open the Security test document to see why"]);
  return out.sort((a, b) => (a[0] === "bad" ? 0 : 1) - (b[0] === "bad" ? 0 : 1));
}

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
  return `${head("Runs", "Each run is one piece of work LFG took from idea to a commit you can review. Click one to see where it is.")}
    <div class="box">${table(d.runs, [
      { k: "slug", label: "Work", html: r => `${esc(runName(r))}${r.current ? ' <span class="tag">current</span>' : ""}${r.about ? `<div class="about clamp">${txt(r.about)}</div>` : ""}<div class="sub">${r.owner ? `filed under ${esc(r.owner_name)} · ${plural(r.tasks_here, "task")} for this repo, ${n(r.tasks_here_done)} done` : r.branch ? `branch ${esc(r.branch)}` : ""}</div>`, sort: r => runName(r) },
      { k: "progress", label: "Where it is", html: r => esc(runLine(r, d.stages)), sort: r => r.progress },
      { k: "attn", label: "Status", html: r => { const a = runAttention(r); return a.length ? `<span class="st">${dot(a[0][0])}${esc(a[0][1])}</span>` : `<span class="st">${dot("ok")}On track</span>`; }, sort: r => runAttention(r).length },
      { k: "created", label: "Started", html: r => `<span class="nowrap">${ago(r.created)}</span>` },
    ], { onRow: r => (location.hash = "#runs/" + encodeURIComponent(r.run)), emptyTitle: "No runs yet", emptyBody: "Start one in Claude Code with <code>/lfg:lfg</code> and what you want built." })}</div>`;
};

const FILE_NAMES = { "01-brief.md": "The idea, written up", "02-design.md": "The plan", "tasks.json": "Task list", "04-qa.md": "Test report",
  "ready.json": "Check results", "05-secure.json": "Security check", "05-pentest.json": "Security test", "06-review.json": "Code review",
  "07-shipcheck.json": "Ship check", "COMMIT_MSG.md": "Commit message", "PR_BODY.md": "Pull request text", "progress.md": "Progress notes" };
const fileName = f => FILE_NAMES[f] || (/^03-build-(.+)\.md$/.test(f) ? `Build notes · ${f.slice(9, -3)}` : null);
/* documents in pipeline order: brief, plan, tasks, build notes, tests, checks, security, review, ship, packet, notes */
const FILE_ORDER = ["01-brief.md", "02-design.md", "tasks.json", "03-build-", "04-qa.md", "ready.json", "05-secure.json", "05-pentest.json",
  "06-review.json", "07-shipcheck.json", "COMMIT_MSG.md", "PR_BODY.md", "progress.md"];
const fileRank = f => { const i = FILE_ORDER.findIndex(x => f === x || (x.endsWith("-") && f.startsWith(x))); return i < 0 ? 99 : i; };

async function runDetail(run) {
  const [d, all] = await Promise.all([api("run", { run }), cachedRuns()]);
  if (d.available === false) return unavailable(d);
  const p = runPlace(all.stages, d.stages, d), attn = runAttention(d);
  const stuck = { "fix-checks": "gate", "fix-review": "review", "fix-block": "review", "fix-security": "secure", "fix-ship": "ship" }[p.next];
  const steps = `<div class="steps">${all.stages.map(([k]) => `<span class="${k === stuck ? "stuck" : d.stages[k] ? "done" : k === p.next ? "next" : ""}">${esc(STEP[k] || k)}</span>`).join("")}</div>`;
  const files = d.files.filter(f => fileName(f.name)).map(f => ({ ...f, run, label: fileName(f.name) }))
    .sort((a, b) => fileRank(a.name) - fileRank(b.name) || a.name.localeCompare(b.name));
  const tasks = d.tasks_list.length ? `<div class="box items">${d.tasks_list.map(taskItem).join("")}</div>` : "";
  const recheck = d.owner_name || !d.current ? "" : d.checking
    ? `<p class="muted small" data-checks-running>Running the checks now (started ${ago(d.checking === true ? "" : d.checking)}). This page updates when they finish; a big project can take several minutes.</p>`
    : `<p><button class="btn small" data-run-checks="${esc(run)}">Run checks again</button> <span class="muted small">lint, types, tests and build, in the background</span></p>`;
  const checks = d.checks.length ? `${recheck}<div class="box items">${readyChecks(d.checks)}</div>` : recheck;
  crumbs("runs", runName(d));
  return `${head(runName(d), `${d.owner_name ? `Filed under ${esc(d.owner_name)} · ` : ""}${d.branch ? `On branch ${esc(d.branch)} · ` : ""}started ${ago(d.created)}`, '<a class="back" href="#runs">← All runs</a>')}
    ${d.about ? `<p class="about lead">${txt(d.about)}</p>` : ""}
    <div class="panel"><div class="row"><b>${p.finished ? "All steps done" : `${p.done} of ${p.total} steps done`}</b><span class="muted${p.blocked ? " stuck-text" : ""}">${p.finished ? "· the commit message is ready for you to review" : `· next: ${esc(NEXT[p.next])}`}</span></div>
      <div class="progress${p.blocked ? " stuck" : p.finished ? " done" : ""}"><span style="width:${pct(p.done, p.total)}%"></span></div>${steps}</div>
    ${attn.length ? section("Needs your attention", `<div class="callout ${attn.some(a => a[0] === "bad") ? "bad" : "warn"}"><ul class="attn">${attn.map(([tn, text]) => `<li>${dot(tn)}<span class="grow">${esc(text)}</span></li>`).join("")}</ul></div>`) : ""}
    ${tasks ? section("Tasks", tasks, `${d.tasks.done} of ${d.tasks.total} done · click one for its steps`) : ""}
    ${checks ? section("Checks", d.ready === "stale" && d.checks.length ? `<p class="muted small">These ran ${ago(d.checked_at)}, before the latest work on this run, so they may no longer hold. Run <code>/lfg:check</code> for a fresh result.</p>${checks}` : checks, d.ready === "stale" ? "out of date" : "click a failed one to see why") : d.owner_name ? section("Checks", `<p class="muted small">This run's checks run in ${esc(d.owner_name)}, on its code, so they aren't shown here.</p>`) : ""}
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
  if ($("[data-sq-scanning]", root)) setTimeout(() => { if (location.hash.startsWith("#checks") && $("[data-sq-scanning]")) route({ soft: true }); }, 10000);
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
  const last = s.secure[0], ship = s.shipcheck[0], rev = r.verdicts[0];
  const open = r.findings.filter(f => !f.feedback);
  const sum = `<div class="cols">${stat("Latest code review", rev ? say(rev.verdict)[0] : "None yet", rev ? plural(rev.findings, "finding") : "run <code>/lfg:expert</code>")}${stat("Latest security check", last ? say(last.verdict)[0] : "None yet", last ? (last.blocking ? `${plural(last.blocking, "problem")} to fix` : "nothing blocking") : "run <code>/lfg:secure</code>")}${stat("Latest ship check", ship ? (ship.pass ? "Passed" : "Failed") : "None yet", ship ? `${ship.ok} of ${ship.total} checks passed${(ship.manual || []).length ? ` · ${ship.manual.length} for you to do` : ""}` : "run <code>/lfg:ship</code>")}</div>`;
  const sevSort = { blocker: 0, critical: 0, high: 1, major: 1, medium: 2, minor: 3, low: 3, nit: 4 };
  return `${head("Checks", "What the code reviews and security checks found, and the actions LFG stopped to keep your work safe.")}
    ${sum}
    <div class="section">${tabs("checks", [
      ["review", "Review findings", r.findings.length, () => `<div class="box">${table(r.findings, [
        { k: "severity", label: "How serious", html: x => st(x.severity), sort: x => -(sevSort[String(x.severity).toLowerCase()] ?? 5) },
        { k: "message", label: "Finding", html: x => `${txt(x.title || x.finding || x.message || x.id)}${x.fix ? `<div class="sub clamp">What to do: ${txt(x.fix)}</div>` : ""}${x.file ? `<div class="sub mono">${esc(x.file)}${x.line ? ":" + esc(x.line) : ""}</div>` : ""}<div class="sub">from <a href="#runs/${encodeURIComponent(x.run)}">${esc(runName({ slug: String(x.run || "").slice(14) }))}</a></div>` },
        { k: "feedback", label: "Your call", html: x => st(x.feedback, "not decided") }], { onRow: x => openDrawer("Review finding", `<div class="readable">${findingCard(x)}</div>`), emptyTitle: "No findings", emptyBody: "Run <code>/lfg:expert</code> on a change." })}</div>${open.length ? `<p class="muted small">Record your call with <code>lfg feedback add &lt;id&gt; accept|reject</code>.</p>` : ""}`],
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
  const mapRow = `<div class="box pad row">${dot(gTone)}<div class="grow"><b>Code map: ${esc((gText || "unknown").toLowerCase())}</b><div class="meta">${g.status === "syncing" ? "Building in the background. This page updates when it's done." : g.synced_at ? `Updated ${ago(g.synced_at)}${g.seconds ? ` in ${Math.round(g.seconds)}s` : ""}.` : "Not built yet."}${g.error ? ` Last error: ${esc(String(g.error).slice(0, 200))}` : ""}</div></div>
    ${mapBtn(g.status)}${g.status !== "missing" && g.status !== "syncing" ? '<button class="btn small" data-map-build="rebuild">Rebuild from scratch</button><button class="btn small" data-map-build="docs" title="Wikis, call flows and playbooks">Refresh docs</button>' : ""}</div>`;
  if (c.available === false && a.available === false) return `${head("Code", "LFG keeps a map of this project so agents read only the parts that matter.")}${mapRow}
    ${g.status === "syncing" ? "" : empty("No code map yet", "Build it now. It runs in the background on this computer and usually takes a minute or two.")}`;
  let summary = "";
  if (c.available !== false) {
    const cov = pct(c.coverage.tested, c.coverage.tested + c.coverage.untested);
    summary = `${n(c.nodes.File)} code files, ${n((c.nodes.Function || 0) + (c.nodes.Class || 0))} functions and classes; code-review-graph links ${cov}% of them to a test.`;
  }
  const risky = c.available !== false ? (c.hotspots || []).slice(0, 10) : [];
  const areas = a.available !== false ? a.community_list.slice(0, 12) : [];
  const notes = a.available !== false ? a.rationale : [];
  return `${head("Code", `LFG keeps a map of this project so agents read only the parts that matter. ${summary}`)}
    ${mapRow}
    ${risky.length ? section("Where changes are riskiest", `<div class="box">${table(risky, [
      { k: "symbol", label: "Code", html: r => `${esc(r.symbol)}<div class="sub">${esc(r.file)}</div>` },
      { k: "callers", label: "Used by", num: true, html: r => plural(r.callers, "place") },
      { k: "coverage", label: "Tested", html: r => (r.coverage === "tested" ? `${dot("ok")} Yes` : `${dot("warn")} No`) }], { filter: false })}</div>`, "used in many places, so a change here reaches far") : ""}
    ${areas.length ? section("Main parts of the code", `<div class="box"><ul class="list">${areas.map(x => `<li><div class="grow"><div class="title">${esc(x.name)}</div><div class="meta">${esc((x.files || []).slice(0, 3).join(" · "))}</div></div></li>`).join("")}</ul></div>`) : ""}
    ${notes.length ? section("Why the code is the way it is", `<div class="box">${table(notes, [{ k: "note", label: "Explanation" }, { k: "file", label: "Where", html: r => `<span class="small muted mono nowrap">${esc(r.file + (r.line ? ":" + r.line : ""))}</span>` }])}</div>`, `docstrings and WHY / NOTE / HACK comments${a.rationale_total > notes.length ? `, first ${notes.length} of ${n(a.rationale_total)}` : ""}`) : ""}
    ${section("Explore", `<div class="row"><button class="btn" data-view="architecture" data-target="explore">Map of the code</button><button class="btn" data-view="callflow" data-target="explore">How calls flow</button><button class="btn" data-view="code" data-target="explore">Detailed code graph</button><button class="btn" data-view="health" data-target="explore">Health report</button></div><div id="explore"></div>`)}`;
};

/* Docs: a tree. Project docs (LFG's wiki, glossary, decisions, guides you asked for) at the root, then one folder
   per branch for docs about that branch's work. */
PAGES.docs = async arg => {
  const d = await api("docs");
  if (d.available === false) return unavailable(d);
  const parts = (arg || "").split("/");
  let src = parts[0], path = decodeURIComponent(parts.slice(1).join("/"));
  const all = t => t.items.concat(...t.folders.map(f => f.items));
  const every = all(d.root).concat(...d.branches.map(all));
  if (!src && every.length) {
    const cur = d.branches.find(b => b.name === state.branch);
    const pick = (d.root.folders[0] || {}).items?.[0] || (cur && all(cur)[0]) || every[0];
    src = pick.src; path = pick.path;
  }
  const on = it => it.src === src && it.path === path;
  const link = it => `<a href="#docs/${esc(it.src)}/${encodeURIComponent(it.path)}" class="${on(it) ? "on" : ""}" title="${esc(it.title)}">${esc(it.title)}</a>`;
  const folder = (name, items, tag, open) => `<details class="doc-folder"${open || items.some(on) ? " open" : ""}><summary>${icon("folder")}<span class="grow">${esc(name)}</span>${tag || ""}<span class="count">${items.length}</span></summary>${items.map(link).join("")}</details>`;
  const fold = (f, openAuto) => folder(f.name, f.items, f.generated ? '<span class="tag" title="Written by LFG from the code map">auto</span>' : "", openAuto && f.generated);
  const tree = (t, openAuto) => t.folders.filter(f => f.generated).map(f => fold(f, openAuto)).join("") + t.items.map(link).join("") + t.folders.filter(f => !f.generated).map(f => fold(f)).join("");
  const STATE = { current: "current", default: "default", merged: "merged", deleted: "deleted" };
  const rootHtml = tree(d.root, true);
  const branchHtml = d.branches.map(b => folder(b.name, all(b), b.state ? `<span class="tag${b.state === "current" ? " blue" : ""}">${STATE[b.state]}</span>` : "", b.name === state.branch || b.state === "current")).join("");
  const nav = `<div class="grp"><span>Project</span></div>${rootHtml || '<p class="meta small pad">Nothing yet.</p>'}
    <div class="grp"><span>Branches</span></div>${branchHtml || '<p class="meta small pad">No branch docs yet.</p>'}`;
  const how = `<p>Ask Claude in a repo where LFG is on, for example <i>"write a doc explaining how billing retries work"</i>. Docs about the whole project go to the top; docs about what you're building on a branch (<i>"write up this branch's design"</i>) go in that branch's folder.</p>
    <p class="meta small">Project: <code>${esc(d.paths.project)}</code><br>Branches: <code>${esc(d.paths.branches)}/&lt;branch&gt;</code></p>`;
  let body = `<div class="readable">${empty("No docs yet", "LFG's wiki (onboarding tour, landmines, test gaps) appears after the code map is built.")}${how}</div>`;
  if (src && path) {
    const doc = await api("doc", { src, path });
    body = doc.text === "not found" ? empty("Document not found", "") : `<div class="md">${md(doc.text, true)}</div>`;
  }
  return `${head("Docs", "LFG's wiki for this project and the docs you asked LFG to write: project-wide at the top, then one folder per branch.")}
    <div class="docs"><div class="box doc-nav"><div class="table-tools"><input type="search" id="doc-filter" placeholder="Search docs…"></div>${nav}
    <details class="doc-help"><summary>How to add a doc</summary>${how}</details></div>
    <div class="box" id="doc-body" data-src="${esc(src || "")}" data-path="${esc(path || "")}">${body}</div></div>`;
};

PAGES.knowledge = async () => {
  const [k, b] = await Promise.all([api("knowledge"), api("brain")]);
  if (k.available === false && b.available === false) return `${head("Knowledge", "What LFG remembers between sessions: decisions and lessons about this project, and your own preferences.")}${unavailable(k, "Knowledge isn't available")}${b.why && b.why !== k.why ? unavailable(b, "Your second-brain isn't available") : ""}`;
  const K = k.available === false ? { decisions: [], principles: [], invariants: [], unheld: [], gaps: [], learnings: [] } : k;
  const B = b.available === false ? { notes: [], preferences: [] } : b;
  const unheld = new Set((K.unheld || []).map(r => r.slug));
  const KN = state.know = [];
  const part = (label, v) => v ? `<h3>${label}</h3><div class="md">${md(String(v))}</div>` : "";
  const listOf = (rows, fn, detail) => rows.length ? `<div class="box"><ul class="list">${rows.map(r => {
    KN.push(() => detail(r));
    return fn(r).replace(/^<li>/, `<li class="click" data-kn="${KN.length - 1}" tabindex="0">`);
  }).join("")}</ul></div>` : empty("Nothing saved yet", "Tell Claude Code what to remember, or use <code>/lfg:note</code>.");
  const sheet = (title, tags, body) => [title, `<div class="readable"><p>${tags}</p>${body}</div>`];
  const rules = K.principles.map(p => ({ text: p.statement, why: p.rationale, s: p.status, kind: p.polarity === "forbids" ? "Never" : "Always", alt: p.correctAlternative, spec: p.specRef }))
    .concat(K.invariants.map(i => ({ text: i.statement, s: unheld.has(i.slug) ? "unheld" : i.status, kind: "Must stay true", guard: i.guardRef, spec: i.specRef })));
  const note = r => sheet(r.name || words(r.slug), `${r.kind ? `<span class="tag">${esc(words(r.kind))}</span>` : ""} ${r.when ? `<span class="muted small">${ago(r.when)}</span>` : ""}`,
    `${r.content ? `<div class="md">${md(String(r.content))}</div>` : '<p class="muted">No text was saved with this note.</p>'}${r.tags && String(r.tags) !== "[]" ? `<p class="muted small">Tags: ${esc(String(r.tags).replace(/[[\]']/g, ""))}</p>` : ""}`);
  const dec = r => sheet(r.title, `${st(r.status)} <span class="muted small">${ago(r.createdAt)}</span>`, `${part("Why it came up", r.context)}${part("What was decided", r.decision)}${part("What follows from it", r.consequences)}`);
  const lrn = r => sheet(r.title, `${r.learningKind ? `<span class="tag">${esc(words(r.learningKind))}</span>` : ""} <span class="muted small">${ago(r.createdAt)}</span>`, r.body ? `<div class="md">${md(String(r.body))}</div>` : '<p class="muted">No text was saved with this lesson.</p>');
  const rule = r => sheet(r.text, `<span class="tag">${esc(r.kind)}</span> ${st(r.s)}`, `${part("Why", r.why)}${part("Do this instead", r.alt)}${part("Checked by", r.guard)}${part("Where it comes from", r.spec)}`);
  const gap = r => sheet(r.title, `${st(r.state)}${r.updatedAt ? ` <span class="muted small">${ago(r.updatedAt)}</span>` : ""}`, `${part("What happens today", r.currentBehavior)}${part("What it should do", r.targetBehavior)}`);
  const missing = [k, b].filter(x => x.available === false).map(x => `<div class="callout warn">${fmtWhy(x.why)}</div>`).join("");
  return `${head("Knowledge", "What LFG remembers between sessions: decisions and lessons about this project, and your own preferences. Agents read these before they work.")}
    ${missing}
    ${tabs("know", [
      ["dec", "Decisions", K.decisions.length, () => listOf(K.decisions, r => `<li><div class="grow"><div class="title">${esc(r.title)}</div><div class="meta clamp">${esc(r.decision)}</div></div><span class="muted small nowrap">${ago(r.createdAt)}</span></li>`, dec)],
      ["lrn", "Lessons learned", K.learnings.length, () => listOf(K.learnings, r => `<li><div class="grow"><div class="title">${esc(r.title)}</div><div class="meta clamp">${esc(r.body || "")}</div></div><span class="muted small nowrap">${ago(r.createdAt)}</span></li>`, lrn)],
      ["rules", "Code rules", rules.length, () => listOf(rules, r => `<li><span class="tag">${esc(r.kind)}</span><div class="grow"><div class="title">${esc(r.text)}</div>${r.why ? `<div class="meta clamp">${esc(r.why)}</div>` : ""}</div>${st(r.s)}</li>`, rule)],
      ["gaps", "Known gaps", K.gaps.length, () => listOf(K.gaps, r => `<li><div class="grow"><div class="title">${esc(r.title)}</div><div class="meta clamp">${r.currentBehavior ? `Today: ${esc(r.currentBehavior)}` : ""}${r.targetBehavior ? ` · Goal: ${esc(r.targetBehavior)}` : ""}</div></div>${st(r.state)}</li>`, gap)],
      ["pref", "Your preferences", B.preferences.length, () => listOf(B.preferences, r => `<li><div class="grow"><div class="title">${esc(r.name || words(r.slug))}</div>${r.content ? `<div class="meta clamp">${esc(String(r.content))}</div>` : ""}</div></li>`, note)],
      ["notes", "Your notes", B.notes.length, () => listOf(B.notes, r => `<li><div class="grow"><div class="title">${esc(r.name || words(r.slug))}</div>${r.content ? `<div class="meta clamp">${esc(String(r.content))}</div>` : ""}</div><span class="muted small nowrap">${esc(words(r.kind))}</span></li>`, note)],
    ])}
    <p class="muted small mt">To add something, tell Claude Code what to remember, or use <code>/lfg:note</code>.</p>`;
};

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
// ------------------------------------------------------------------ reviews (other people's pull requests)
const RV_SAY = { new: ["Not started", ""], working: ["AI is working", "warn"], ready: ["Ready for you", "ok"], posted: ["Posted", "ok"], closed: ["Closed", ""] };
const tagHtml = (t, tone) => `<span class="tg ${tone || ""}">${esc(t)}</span>`;
const initials = name => (String(name || "?").replace(/[-_.\d]+/g, " ").trim().split(/\s+|(?=[A-Z])/).filter(Boolean).slice(0, 2).map(x => x[0]).join("") || "?").toUpperCase();
const RV_TAG = { new: ["Not started", ""], working: ["AI working", "on"], ready: ["Ready for you", "ok"], posted: ["Posted", "ok"], closed: ["Closed", ""] };
const rvTag = rv => { const [t, tone] = RV_TAG[(rv || {}).status] || [(rv || {}).status || "", ""]; return `${tagHtml(t, tone)}${rv && rv.new_commits ? tagHtml("New commits", "warn") : ""}`; };
/* one pull request row: who, which branch into which, size, and where it stands */
function prRow(p, href, who, side) {
  const size = p.changedFiles ? `${plural(p.changedFiles, "file")} <span class="add">+${n(p.additions || 0)}</span> <span class="del">−${n(p.deletions || 0)}</span>` : "";
  return `<a class="rv-row" href="${href}"><span class="av" title="${esc(p.author || "")}">${esc(initials(p.author))}</span><span class="grow"><span class="rv-row-t">${esc(p.title || "#" + p.number)} <span class="muted">#${p.number}</span></span>
    <span class="rv-row-m">${who ? `${who} · ` : ""}<span class="brtag" title="${esc(p.headRefName || "")}">${esc(p.headRefName || "?")}</span><span class="arrow">→</span><span class="brtag">${esc(p.baseRefName || "?")}</span>${size ? ` · ${size}` : ""}${p.updatedAt ? ` · ${ago(p.updatedAt)}` : ""}</span></span>${side}</a>`;
}
const pill = (t, tone) => `<span class="st"><span class="dot ${tone}"></span>${esc(t)}</span>`;
const rvChip = rv => { const [t, tone] = RV_SAY[(rv || {}).status] || [rv && rv.status || "", ""]; return `<span class="rv-chips">${pill(t, tone)}${rv && rv.new_commits ? pill("New commits", "warn") : ""}</span>`; };
const EVENT_SAY = { COMMENT: "Comment", REQUEST_CHANGES: "Request changes", APPROVE: "Approve" };

PAGES.review = async arg => {
  const n = parseInt(arg, 10);
  const unlocked = await isUnlocked();
  if (/^yours\//.test(arg)) return triagePage(parseInt(arg.slice(6), 10), unlocked);
  if (!n) {
    const fresh = state.prFresh ? { fresh: "1" } : {};
    const [d, y] = await Promise.all([api("prs", fresh), api("mine", fresh)]);
    state.prFresh = false;
    const top = `<div class="rv-top"><span class="muted small">${d.fetched_at ? `checked ${ago(d.fetched_at)}` : ""}</span><button class="btn small" data-rv-refresh>Refresh</button></div>`;
    if (d.available === false) return `${head("Reviews")}${top}${unavailable(d, "Couldn't read your review requests")}`;
    const rows = d.prs.map(p => prRow(p, `#review/${p.number}`, `${esc(p.author || "?")}${p.requested === false ? " · no longer asks you" : ""}`,
      `<span class="rv-side">${rvTag(p.review)}${p.review && p.review.worktree_name ? `<span class="brtag">${icon("folder")}${esc(p.review.worktree_name)}</span>` : ""}</span>`)).join("");
    const DEC = { APPROVED: ["Approved", "ok"], CHANGES_REQUESTED: ["Changes requested", "warn"], REVIEW_REQUIRED: ["Review required", ""] };
    const yours = y.available === false ? unavailable(y, "Couldn't read your pull requests") : y.prs.length ? `<div class="box rv-list">${y.prs.map(p => prRow(p, `#review/yours/${p.number}`,
      p.reviewDecision ? tagHtml(...(DEC[p.reviewDecision] || [words(p.reviewDecision), ""])) : "",
      `<span class="rv-side">${p.review && p.review.status === "working" ? tagHtml("AI reading", "on") : p.review && p.review.status !== "new" ? `${p.worth_open ? tagHtml(`${p.worth_open} worth fixing`, "bad") : tagHtml("Nothing to fix", "ok")}${p.low_open ? tagHtml(`${p.low_open} low`, "") : ""}${p.decided ? tagHtml(`${p.decided} ready to send`, "on") : ""}` : tagHtml("Not read yet", "")}</span>`)).join("")}</div>` : empty("No open pull requests", "You have no open pull request in this repo.");
    return `${head("Reviews", `Pull requests in ${esc(repoName())}. Each one is read in its own worktree, so your checkout stays as it is, and nothing goes to GitHub until you post.`)}${top}
      ${tabs("rvl", [["waiting", "Waiting on you", d.prs.length, () => d.prs.length ? `<div class="box rv-list">${rows}</div>` : empty("Nothing waiting on you", "No open pull request in this repo asks for your review.")],
        ["yours", "Your pull requests", y.available === false ? null : y.prs.length, () => yours]])}`;
  }
  const d = await api("pr", { n });
  if (d.available === false) return unavailable(d);
  state.pr = d;
  const p = d.pr || {}, rv = d.review || {}, dr = d.draft || {}, working = rv.status === "working";
  crumbs("review", `#${n}`);
  const header = rvHeader(d, n, p, rv, `@${esc(p.author || "?")} · ${esc(p.baseRefName || "")} ← ${esc(p.headRefName || "")}`,
    rv.new_commits ? `<button class="btn small" data-rv-update${working || !unlocked ? " disabled" : ""}>Pull new commits</button>` : "", "data-rv-refresh");
  if (rv.status === "new") return `${header}${rvStart("Start review", "data-rv-start", unlocked, "An AI reviewer reads it in its own worktree with LFG's code review skill, the code graphs and the brains. You talk it through and post when you're happy.")}`;
  const dis = working || rv.status === "posted" || !unlocked ? " disabled" : "";
  const ratings = dr.ratings || [], comments = dr.comments || [], questions = dr.questions || [];
  const ai = ratings.map(r => r.ai).filter(Boolean);
  const score = r => `<div class="rv-score" title="${esc(r.why || "")}"><span class="grow">${esc(r.area)}</span>${r.ai ? `<span class="muted small">AI ${r.ai}</span>` : ""}<span class="pills" data-area="${esc(r.area)}">${[1, 2, 3, 4, 5].map(v => `<button class="pill${r.mine === v ? " on" : ""}" data-v="${v}"${dis}>${v}</button>`).join("")}</span></div>`;
  const comment = c => `<div class="rv-c" data-c="${esc(c.id)}" data-path="${esc(c.path || "")}" data-line="${c.line || ""}" data-sev="${esc(c.severity || "")}" data-src="${esc(c.source || "")}"><input type="checkbox" aria-label="Include this comment"${c.include !== false ? " checked" : ""}${dis}><div class="grow"><div class="rv-c-m"><span title="${esc(c.path || "")}">${esc((c.path || "general").split("/").pop())}${c.line ? ":" + c.line : ""}</span>${c.severity ? ` · ${esc(c.severity)}` : ""} · ${c.inline ? "on the line" : "in the summary"}</div><textarea class="inline-edit" rows="1"${dis}>${esc(c.body || "")}</textarea></div><button class="icon-btn" data-rv-drop title="Remove" aria-label="Remove"${dis}>&times;</button></div>`;
  const question = q => `<div class="rv-q" data-q="${esc(q.id)}"><div>${txt(q.ask)}${q.why ? `<div class="meta">${txt(q.why)}</div>` : ""}</div><textarea class="inline-edit" rows="1" placeholder="Your answer"${dis}>${esc(q.answer || "")}</textarea><a href="#" class="small" data-rv-discuss="${esc(q.id)}">Discuss</a></div>`;
  const more = (items, keep, fn, what) => items.slice(0, keep).map(fn).join("") + (items.length > keep ? `<div class="rv-more" hidden>${items.slice(keep).map(fn).join("")}</div><a href="#" class="rv-more-link small" data-more>+${items.length - keep} more ${what}</a>` : "");
  const kept = comments.filter(c => c.include !== false).length;
  const main = `<div class="rv-main">
    ${working ? `<p class="rv-note" data-rv-working><span class="spin"></span>The AI is ${rv.job === "review" ? "reviewing the pull request" : "answering"} · started ${ago(d.working_since)}</p>` : ""}
    ${!working && ((d.chat || []).slice(-1)[0] || {}).error ? `<p class="rv-note bad">The last AI run failed (details on the right).<button class="btn small" data-rv-start${unlocked ? "" : " disabled"}>Try again</button></p>` : ""}
    ${rv.posted ? `<p class="rv-note ok">Posted ${ago(rv.posted.at)} as ${esc((EVENT_SAY[rv.posted.event] || rv.posted.event).toLowerCase())}${rv.posted.url ? ` · <a href="${esc(rv.posted.url)}" target="_blank" rel="noopener noreferrer">see it on GitHub</a>` : ""}</p>` : ""}
    <div class="rv-card"><div class="rv-card-h">Summary for the author${dr.ai_verdict ? `<span class="muted small">AI's call: ${esc(dr.ai_verdict)}</span>` : ""}</div><textarea id="rv-summary" class="inline-edit" rows="2" placeholder="What you'll tell the author"${dis}>${esc(dr.summary || "")}</textarea></div>
    ${ratings.length ? `<div class="rv-card"><div class="rv-card-h">Your scores${ai.length ? `<span class="muted small">AI suggests ${Math.min(...ai)}–${Math.max(...ai)}</span>` : ""}</div>${more(ratings, 2, score, "areas")}</div>` : ""}
    <div class="rv-card"><div class="rv-card-h">Comments<span class="muted small">${kept} to post</span></div>${comments.length ? more(comments, 3, comment, "comments") : '<p class="muted small">No comments yet.</p>'}</div>
    ${questions.length ? `<details class="rv-card"><summary class="rv-card-h">${questions.length} ${questions.length === 1 ? "question" : "questions"} to settle</summary>${questions.map(question).join("")}</details>` : ""}
    ${(dr.context || []).length ? `<details class="rv-card"><summary class="rv-card-h">What the brains added<span class="muted small">${dr.context.length}</span></summary><ul class="small">${dr.context.map(x => `<li>${txt(x)}</li>`).join("")}</ul></details>` : ""}
    ${rv.posted ? `<div class="rv-bar"><span class="grow"></span><button class="btn small" data-rv-close${!unlocked || working ? " disabled" : ""}>Done: remove the worktree</button></div>`
      : `<div class="rv-bar"><input type="hidden" id="rv-event" value="${esc(dr.event || "COMMENT")}"><span class="seg">${Object.entries(EVENT_SAY).map(([k, v]) => `<button class="pill wide${(dr.event || "COMMENT") === k ? " on" : ""}" data-ev="${k}"${dis}>${v}</button>`).join("")}</span><label class="small muted"><input type="checkbox" id="rv-rates"${dr.include_ratings !== false ? " checked" : ""}${dis}> scores</label><span class="grow"></span><span class="muted small" id="rv-saved"></span><button class="btn primary" data-rv-preview${dis}>Post review</button></div>`}
  </div>`;
  return `${header}<div class="rv">${main}${rvChat(d, working, dis)}</div>`;
};

function rvHeader(d, n, p, rv, meta, extra, refresh) {
  const wt = rv.worktree_name || (d.worktree_to_be || "").split("/").pop();
  return `<div class="rvh"><div class="grow"><h1>${esc(p.title || "Pull request")} <span class="muted">#${n}</span></h1>
    <div class="rvh-m">${meta} · <span class="wtchip" title="${esc((d.meta || {}).worktree || d.worktree_to_be || "")}">${icon("folder")}${esc(wt)}</span>${p.url ? ` · <a href="${esc(p.url)}" target="_blank" rel="noopener noreferrer">GitHub ↗</a>` : ""}</div></div>
    <div class="rvh-a">${extra}${rv.status === "new" ? "" : `<button class="icon-btn" ${refresh} title="Refresh" aria-label="Refresh">${icon("refresh")}</button>`}</div></div>`;
}
function rvStart(label, attr, unlocked, text) {
  return `<div class="rv-empty"><p>${text}</p><button class="btn primary" ${attr}${unlocked ? "" : ' disabled title="Run lfg ui in your terminal to unlock"'}>${label}</button></div>`;
}
function rvChat(d, working, dis) {
  const msgs = (d.chat || []).map(m => `<div class="msg ${m.role === "me" ? "me" : "ai"}${m.error ? " bad" : ""}">${m.role === "me" ? esc(m.text) : `<div class="md">${md(m.text)}</div>`}${m.changed && m.changed.length ? `<div class="meta">Updated ${esc(m.changed.join(", "))}</div>` : ""}</div>`).join("");
  return `<aside class="rv-chat"><div class="rv-chat-head">Talk it through</div><div class="rv-msgs" id="rv-msgs">${msgs || '<p class="muted small">The AI\'s read lands here. Push back, answer its questions, or ask for changes.</p>'}${working ? '<div class="msg ai muted"><span class="spin"></span>Thinking…</div>' : ""}</div>
    <div class="rv-send"><textarea id="rv-text" rows="2" placeholder="${d.mode === "triage" ? "Why only 30% on the null check?" : "Ask or push back"}"${dis}></textarea><button class="btn small" data-rv-ask${dis}>Send</button></div></aside>`;
}

/* Review bots (CodeRabbit, Devin and the like) open with a label line ("Stability | Major | Quick win") and wrap
   parts in HTML: the label becomes tags, the AI-agent prompt goes, <summary> becomes a bold line. */
function botComment(body) {
  let b = String(body || "").replace(/<details>\s*<summary>[^<]*Prompt for AI[^<]*<\/summary>[\s\S]*?<\/details>/gi, "")
    .replace(/<summary>\s*([\s\S]*?)\s*<\/summary>/gi, "\n**$1**\n").replace(/<\/?details>/gi, "").replace(/<\/?(br|p|div|span|b|i|em|strong)\b[^>]*>/gi, "");
  const lines = b.split("\n"), i0 = lines.findIndex(l => l.trim());
  let tags = [];
  if (i0 >= 0 && lines[i0].includes("|") && lines[i0].length < 160) {
    tags = lines[i0].split("|").map(x => x.replace(/[*_`]/g, "").replace(/\p{Extended_Pictographic}\uFE0F?/gu, "").trim()).filter(Boolean);
    lines.splice(i0, 1);
  }
  return { tags, body: lines.join("\n").replace(/\n{3,}/g, "\n\n").trim() };
}
const TAG_TONE = { critical: "bad", major: "warn" };

/* Your own PR: every comment thread, the AI's read on it, and the reply you'll send */
async function triagePage(n, unlocked) {
  const d = await api("triage", { n });
  if (d.available === false) return unavailable(d);
  state.pr = d;
  const p = d.pr || {}, rv = d.review || {}, working = rv.status === "working";
  crumbs("review", `Yours #${n}`, `#review/yours/${n}`);
  const all = Object.values((d.triage || {}).threads || {});
  const open = all.filter(t => !t.resolved && !t.posted).sort((a, b) => (b.worth ?? -1) - (a.worth ?? -1));
  const closed = all.filter(t => t.resolved || t.posted);
  const header = rvHeader(d, n, p, rv, `your pull request · ${esc(p.baseRefName || "")} ← ${esc(p.headRefName || "")}`, "",
    `data-tr-start${working || !unlocked ? " disabled" : ""}`);
  if (rv.status === "new") return `${header}${rvStart("Read the comments", "data-tr-start", unlocked, "An AI reads every comment on this pull request against your code, the code graphs and the brains, says how likely each is worth fixing, and drafts your reply either way. Nothing is sent until you send it.")}`;
  const dis = working || !unlocked ? " disabled" : "";
  const title = t => {  // a comment's first line, as a person would summarise it: no markup, no emoji
    const unlink = l => { let p; do { p = l; l = l.replace(/!?\[([^[\]]*)\]\([^)]*\)/g, "$1"); } while (l !== p); return l; };
    const lines = (t.body || "").replace(/<[^>]*>?/g, " ").split("\n").map(l => unlink(l).replace(/[#*`>|\[\]]/g, "").replace(/(^|\s)_+|_+(?=\s|$|[.,;:])/g, "$1").replace(/\p{Extended_Pictographic}\uFE0F?/gu, "").replace(/\s+/g, " ").trim()).filter(Boolean);
    const first = lines[0] || "";
    const x = first.length >= 12 ? first : lines.slice(0, 2).join(" ");
    return x.length > 110 ? x.slice(0, 108) + "…" : x;
  };
  const score = t => t.worth == null ? `<span class="score">${working ? "…" : "–"}</span>` : `<span class="score ${t.worth >= 70 ? "hi" : t.worth >= 40 ? "mid" : "lo"}" title="How likely it's worth fixing">${t.worth}%</span>`;
  const row = t => {
    const reasons = [t.reply_wont].concat(t.wont_reasons || []).filter(Boolean);
    const reply = t.reply != null && t.reply !== "" ? t.reply : t.decision === "fix" ? t.reply_fix || "" : t.decision === "wont" ? t.reply_wont || "" : "";
    const bc = botComment(t.body);
    return `<div class="rv-t" data-t="${esc(t.id)}"><div class="rv-t-row">${score(t)}<details class="grow rv-t-d"><summary><span class="rv-t-title">${esc(title({ body: bc.body }))}</span><span class="rv-t-m">${bc.tags.map(x => tagHtml(x, TAG_TONE[x.toLowerCase()] || "")).join("")}${esc(t.author || "?")}${t.bot ? " (bot)" : ""}${t.path ? ` · <span title="${esc(t.path)}">${esc(t.path.split("/").pop())}${t.line ? ":" + t.line : ""}</span>` : ""}${t.outdated ? " · outdated" : ""}${t.from_summary ? ` ${tagHtml("in the review summary", "")}` : ""}</span></summary>
        <div class="rv-t-x">${t.why ? `<p><b>AI:</b> ${txt(t.why)}</p>` : ""}${t.fix ? `<p class="muted">Fix: ${txt(t.fix)}</p>` : ""}<div class="md">${md(bc.body)}</div>${t.url ? `<a href="${esc(t.url)}" target="_blank" rel="noopener noreferrer" class="small">Open on GitHub ↗</a>` : ""}</div></details>
      <span class="seg">${[["fix", "Fix"], ["wont", "Won't fix"]].map(([k, l]) => `<button class="pill wide${t.decision === k ? " on" : ""}" data-dec="${k}"${dis}>${l}</button>`).join("")}</span></div>
      ${t.decision === "fix" || t.decision === "wont" ? `<div class="rv-reply"><span class="muted">↳</span><textarea class="inline-edit" rows="1"${dis}>${esc(reply)}</textarea></div>` : ""}
      ${t.decision === "wont" && reasons.length > 1 ? `<div class="reasons">${reasons.map((r, i) => `<button class="chip${reply === r ? " on" : ""}" data-reason="${i}" title="${esc(r)}"${dis}>${esc(r.length > 48 ? r.slice(0, 46) + "…" : r)}</button>`).join("")}</div>` : ""}</div>`;
  };
  state.trReasons = Object.fromEntries(all.map(t => [t.id, [t.reply_wont].concat(t.wont_reasons || []).filter(Boolean)]));
  const top = open.filter(t => t.worth == null || t.worth >= 30 || t.decision), low = open.filter(t => !top.includes(t));
  const ready = open.filter(t => t.decision === "fix" || t.decision === "wont").length;
  const main = `<div class="rv-main">
    ${working ? `<p class="rv-note" data-rv-working><span class="spin"></span>The AI is ${rv.job === "triage" ? "reading the comments" : "answering"} · started ${ago(d.working_since)}</p>` : ""}
    ${!working && ((d.chat || []).slice(-1)[0] || {}).error ? `<p class="rv-note bad">The last AI run failed (details on the right).<button class="btn small" data-tr-start${unlocked ? "" : " disabled"}>Try again</button></p>` : ""}
    <div class="rv-card rv-list-card">${top.map(row).join("") || (low.length ? "" : '<p class="muted small">No unresolved comments.</p>')}${low.length ? `<div class="rv-divider">${low.length} under 30% · probably not worth fixing</div>${low.map(row).join("")}` : ""}</div>
    ${closed.length ? `<details class="rv-card"><summary class="rv-card-h">${closed.length} resolved or answered</summary>${closed.map(t => `<div class="meta">${esc(t.author || "?")}${t.path ? ` · ${esc(t.path.split("/").pop())}` : ""} · ${t.posted ? `replied (${t.posted.decision === "fix" ? "fixing" : "won't fix"})` : "resolved"}</div>`).join("")}</details>` : ""}
    <div class="rv-bar"><span class="muted small">${open.length} unresolved · ${ready} ${ready === 1 ? "reply" : "replies"} ready</span><span class="grow"></span><span class="muted small" id="rv-saved"></span><button class="btn primary" data-tr-preview${ready && !working && unlocked ? "" : " disabled"}>Send replies</button></div></div>`;
  return `${header}<div class="rv">${main}${rvChat(Object.assign({ mode: "triage" }, d), working, dis)}</div>`;
}

function rvDraft(root) {
  const g = s => $(s, root);
  return {
    summary: g("#rv-summary") ? g("#rv-summary").value : undefined,
    event: g("#rv-event") ? g("#rv-event").value : undefined,
    include_ratings: g("#rv-rates") ? g("#rv-rates").checked : undefined,
    ratings: $$(".pills", root).map(p => ({ area: p.dataset.area, mine: +(($(".pill.on", p) || {}).dataset || {}).v || null })),
    questions: $$(".rv-q", root).map(q => ({ id: q.dataset.q, answer: $("textarea", q).value })),
    comments: $$(".rv-c", root).map(c => ({ id: c.dataset.c, path: c.dataset.path, line: c.dataset.line ? +c.dataset.line : null, severity: c.dataset.sev, source: c.dataset.src, body: $("textarea", c).value, include: $("input[type=checkbox]", c).checked })),
  };
}
let rvTimer = null, rvPoll = null;
function wireReview(root) {
  const d = state.pr, n = d && d.number;
  clearTimeout(rvPoll);
  $$("[data-rv-refresh]", root).forEach(b => b.onclick = () => { state.prFresh = true; if (n) api("prs", { fresh: "1" }).then(() => route({ soft: true })); else route(); });
  if (!n || !/^#review\/(yours\/)?\d+/.test(location.hash)) return;
  const act = async (what, extra, btn, label) => {
    if (btn) { btn.disabled = true; btn.textContent = label || "Working…"; }
    const r = await save(what, Object.assign({ repo: state.repo, n }, extra || {}));
    if (!r.ok) { alert(String(r.why || "That didn't work.").replace(/`/g, "")); if (btn) btn.disabled = false; }
    route({ soft: true });
    return r;
  };
  const msgs = $("#rv-msgs", root);
  if (msgs) msgs.scrollTop = msgs.scrollHeight;
  $$("[data-rv-start]", root).forEach(b => b.onclick = () => act("pr_start", {}, b, "Setting up the worktree…"));
  $$("[data-rv-update]", root).forEach(b => b.onclick = () => act("pr_update", {}, b, "Pulling…"));
  $$("[data-rv-close]", root).forEach(b => b.onclick = () => confirm("Remove this review's worktree? The chat and draft are kept.") && act("pr_close", {}, b));
  const send = $("[data-rv-ask]", root), box = $("#rv-text", root);
  if (send) send.onclick = () => box.value.trim() && act("pr_ask", { text: box.value }, send, "Sending…");
  if (box) box.onkeydown = e => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) send.click(); };
  $$("[data-rv-discuss]", root).forEach(b => b.onclick = e => { e.preventDefault(); const q = (d.draft.questions || []).find(x => x.id === b.dataset.rvDiscuss); box.value = `About ${q.id} (“${q.ask}”): `; box.focus(); });
  const CAP = 66;  // comments show three lines until you click into them
  const grow = t => { t.style.height = "auto"; const full = t.scrollHeight + 2, cap = t.closest(".rv-c, .rv-reply") && document.activeElement !== t;
    t.style.height = (cap ? Math.min(full, CAP) : full) + "px"; t.classList.toggle("clipped", cap && full > CAP); };
  $$(".inline-edit", root).forEach(t => { grow(t); ["input", "focus", "blur"].forEach(ev => t.addEventListener(ev, () => grow(t))); });
  $$("[data-more]", root).forEach(a => a.onclick = e => { e.preventDefault(); const m = a.previousElementSibling; m.hidden = false; $$(".inline-edit", m).forEach(grow); a.remove(); });
  const saved = $("#rv-saved", root);
  const persist = () => { clearTimeout(rvTimer); if (saved) saved.textContent = "…"; rvTimer = setTimeout(async () => { const r = await save("pr_draft", { repo: state.repo, n, draft: rvDraft(root) }); if (saved) saved.textContent = r.ok ? "saved" : (r.why || "not saved"); }, 700); };
  $$(".rv-main textarea, .rv-main select, .rv-main input", root).filter(el => !el.closest(".rv-t")).forEach(el => el.addEventListener(el.tagName === "TEXTAREA" ? "input" : "change", persist));
  $$("[data-ev]", root).forEach(b => b.onclick = () => { $$("[data-ev]", root).forEach(x => x.classList.toggle("on", x === b)); $("#rv-event", root).value = b.dataset.ev; persist(); });
  $$(".pills .pill", root).forEach(b => b.onclick = () => { const on = b.classList.contains("on"); $$(".pill", b.parentNode).forEach(x => x.classList.remove("on")); if (!on) b.classList.add("on"); persist(); });
  $$("[data-rv-drop]", root).forEach(b => b.onclick = () => { b.closest(".rv-c").remove(); persist(); });
  $$("[data-rv-preview]", root).forEach(b => b.onclick = async () => {
    clearTimeout(rvTimer);
    await save("pr_draft", { repo: state.repo, n, draft: rvDraft(root) });
    const o = await api("pr_outgoing", { n });
    if (o.available === false) return alert(o.why);
    openDrawer(`Post to #${n}?`, `<div class="readable"><p><b>${esc(EVENT_SAY[o.event] || o.event)}</b> · ${plural(o.comments.length, "comment")} on lines${o.in_body ? ` · ${o.in_body} in the summary` : ""}</p>
      <div class="md box pad">${md(o.body || "_No summary._")}</div>
      ${o.comments.map(c => `<div class="box pad mt"><code>${esc(c.path)}:${c.line}</code><div class="md">${md(c.body)}</div></div>`).join("")}
      <p class="mt"><button class="btn primary" id="rv-post-go">Post to GitHub</button> <span class="muted small">as you, on commit ${esc(o.commit_id.slice(0, 7))}</span></p></div>`);
    $("#rv-post-go").onclick = async e => { if (!confirm("Post this review to GitHub now?")) return; const r = await act("pr_post", {}, e.target, "Posting…"); if (r.ok) closeDrawer(); };
  });
  wireTriage(root, n, act);
  if ($("[data-rv-working]", root)) rvPoll = setTimeout(() => { if (/^#review\/(yours\/)?\d+/.test(location.hash) && !document.activeElement.closest(".rv-send")) route({ soft: true }); }, 4000);
}

function wireTriage(root, n, act) {
  $$("[data-tr-start]", root).forEach(b => b.onclick = () => act("pr_triage", {}, b, "Reading…"));
  const saved = $("#rv-saved", root);
  const decisions = () => Object.fromEntries($$(".rv-t", root).map(c => [c.dataset.t, { decision: ($(".seg .pill.on", c) || { dataset: {} }).dataset.dec || null, reply: $("textarea", c) ? $("textarea", c).value : undefined }]));
  const persist = (rerender) => { clearTimeout(rvTimer); if (saved) saved.textContent = "…"; rvTimer = setTimeout(async () => { const r = await save("pr_decide", { repo: state.repo, n, decisions: decisions() }); if (saved) saved.textContent = r.ok ? "saved" : (r.why || "not saved"); if (rerender) route({ soft: true }); }, rerender ? 0 : 700); };
  $$(".rv-t .seg .pill", root).forEach(b => b.onclick = () => { const c = b.closest(".rv-t"), on = b.classList.contains("on"); $$(".seg .pill", c).forEach(x => x.classList.remove("on")); if (!on) b.classList.add("on"); const ta = $("textarea", c); if (ta) ta.value = ""; persist(true); });
  $$(".rv-t [data-reason]", root).forEach(b => b.onclick = () => { const c = b.closest(".rv-t"); $("textarea", c).value = state.trReasons[c.dataset.t][+b.dataset.reason]; $$("[data-reason]", c).forEach(x => x.classList.toggle("on", x === b)); persist(); });
  $$(".rv-t textarea", root).forEach(t => t.addEventListener("input", () => persist()));
  $$("[data-tr-preview]", root).forEach(b => b.onclick = async () => {
    clearTimeout(rvTimer);
    await save("pr_decide", { repo: state.repo, n, decisions: decisions() });
    const o = await api("triage_out", { n });
    openDrawer(`Post ${o.replies.length} ${o.replies.length === 1 ? "reply" : "replies"} to #${n}?`, `<div class="readable">${o.replies.map(r => `<div class="box pad mt"><div class="meta">to @${esc(r.author || "?")}${r.path ? ` · <code>${esc(r.path)}${r.line ? ":" + r.line : ""}</code>` : ""} · ${r.decision === "fix" ? "fixing" : "won't fix"}</div><div class="md">${md(r.body)}</div></div>`).join("")}
      <p class="mt"><button class="btn primary" id="tr-post-go">Post to GitHub</button> <span class="muted small">as you, each under its comment</span></p></div>`);
    $("#tr-post-go").onclick = async e => { if (!confirm("Post these replies to GitHub now?")) return; const r = await act("pr_replies", {}, e.target, "Posting…"); if (r.ok) closeDrawer(); };
  });
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

PAGES.usage = async () => {
  const [d, H] = await Promise.all([api("usage", { days: UR.days > 30 ? 90 : 30 }), api("headroom", { days: UR.days > 30 ? 90 : 30 })]);
  const hrDay = Object.fromEntries((((H || {}).when || {}).days || []).map(x => [x.day, x]));
  const since = new Date(Date.now() - (UR.days - 1) * 864e5).toISOString().slice(0, 10);
  const days = (d.days || []).filter(x => x.day >= since).map(x => ({ ...x, hr_saved: (hrDay[x.day] || {}).saved || 0, hr_usd: (hrDay[x.day] || {}).usd || 0 }));
  const hrPending = H && H.pending;
  const rangeUsd = days.reduce((a, x) => a + (x.usd || 0), 0), hrUsd = days.reduce((a, x) => a + (x.hr_usd || 0), 0);
  const hrTokens = days.reduce((a, x) => a + (x.hr_saved || 0), 0);
  const t = days.reduce((a, x) => { for (const k of ["input", "output", "cache_read", "cache_write"]) a[k] += x[k] || 0; return a; }, { input: 0, output: 0, cache_read: 0, cache_write: 0 });
  const hit = pct(t.cache_read, t.cache_read + t.input + t.cache_write);
  const hr = d.headroom || {}, life = hr.lifetime || {}, sp = d.spend || {};
  const seg = (key, opts) => `<div class="seg inline">${opts.map(([v, l]) => `<label class="${UR[key] === v ? "on" : ""}"><input type="radio" name="ur-${key}" data-ur="${key}" value="${v}" ${UR[key] === v ? "checked" : ""}>${l}</label>`).join("")}</div>`;
  const rows = bucket(days, UR.by, rs => addRows(rs, ["input", "output", "cache_read", "cache_write", "usd", "hr_saved", "hr_usd"]));
  const usdFmt = v => usd(v || 0);
  const filters_row = `<div class="row filters">${seg("days", [[7, "7 days"], [14, "14 days"], [30, "30 days"], [90, "90 days"]])}${seg("by", [["day", "By day"], ["week", "By week"]])}${seg("measure", [["usd", "Dollars"], ["tokens", "Tokens"]])}</div>`;
  const ghost = { ghost: true };
  if (hrPending) setTimeout(() => { if ((location.hash.slice(1) || "").startsWith("usage")) softRoute(); }, 2500);
  const chart = UR.measure === "usd"
    ? iChart(rows.map(r => ({ label: r.label, short: r.short, values: [r.usd, r.hr_usd], raw: r })), [["Actual cost", "var(--series-1)", usdFmt], ["Saved by Headroom", "var(--series-1)", usdFmt, ghost]],
        { title: "Cost per " + UR.by, onPick: i => usageDetail(rows, i), total: (x, hid) => hid.has(1) ? "" : `Without Headroom: ${usd((x.values[0] || 0) + (x.values[1] || 0))}` })
    : iChart(rows.map(r => ({ label: r.label, short: r.short, values: [(r.input || 0) + (r.cache_write || 0), r.cache_read || 0, r.output || 0, r.hr_saved || 0], raw: r })), [["Sent new", "var(--series-1)"], ["Reused from cache", "var(--series-2)"], ["Written by Claude", "var(--series-3)"], ["Removed by Headroom", "var(--series-1)", compact, ghost]],
        { title: "Tokens per " + UR.by, hidden: [1], onPick: i => usageDetail(rows, i), total: (x, hid) => hid.has(3) ? "" : `Without Headroom: ${compact(x.values.reduce((a, v, j) => a + (hid.has(j) ? 0 : v || 0), 0))} tokens` });
  state.usageRows = rows;
  return `${head("Usage", "What Claude Code used and what it would cost at API prices, across every session on this computer.")}
    ${filters_row}
    <div class="cols">${stat(`Cost, last ${UR.days} days`, usd(rangeUsd), "the work priced at Anthropic's API rates, from every session's log; on a subscription you pay your plan, not this")}${stat("Cost today", usd(sp.today || 0), "since midnight")}${stat(`Saved by Headroom, last ${UR.days} days`, hrTokens ? usd(hrUsd) : "—", hrTokens ? `${compact(hrTokens)} tokens removed, by Headroom's count` : hrPending ? "checking…" : "nothing recorded")}</div>
    <div class="cols">${stat(`Tokens sent, last ${UR.days} days`, compact(t.input + t.cache_read + t.cache_write), `${hit}% reused from cache, which costs about a tenth as much`)}${stat(`Tokens written, last ${UR.days} days`, compact(t.output), "Claude's replies")}</div>
    ${section(UR.measure === "usd" ? `Cost per ${UR.by}` : `Tokens per ${UR.by}`, `<div class="box pad" id="usage-main">${chart}<div id="usage-detail"></div></div>`, UR.measure === "usd"
      ? `the solid bar is what that ${UR.by}'s work cost at Anthropic's API prices; the dashed part on top is what Headroom saved, so the whole bar is what it would have cost without Headroom${hrPending ? " (Headroom's numbers are still loading)" : ""}. Hover for numbers, click for the breakdown by model.`
      : `solid: what was sent (new text, and text reused from cache, hidden until you click its key) and what Claude wrote back. Dashed on top: what Headroom removed before sending, so the whole bar is what would have been sent without it${hrPending ? " (Headroom's numbers are still loading)" : ""}.`)}
    ${(d.models || []).length ? section("By model", `<div class="box">${table(d.models, [{ k: "model", label: "Model" }, { k: "input", label: "Sent", num: true, html: r => compact((r.input || 0) + (r.cache_read || 0) + (r.cache_write || 0)) }, { k: "output", label: "Written", num: true, html: r => compact(r.output) }, { k: "usd", label: "Cost", num: true, html: r => r.usd != null ? usd(r.usd) : "" }], { filter: false })}</div>`, "last " + (d.days || []).length + " days") : ""}
    <div id="hr-detail"><div class="loading">Reading Headroom's logs…</div></div>
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
  const W = d.when || {};
  const since = new Date(Date.now() - (UR.days - 1) * 864e5).toISOString().slice(0, 10);
  const days = (W.days || []).filter(x => x.day >= since);
  const rows = bucket(days, UR.by, rs => addRows(rs, ["saved", "calls", "usd", "before"]));
  const status = d.routed ? `<span class="row" style="gap:8px">${dot(d.live ? "ok" : "bad")}<span>${d.live ? "On: every Claude Code session goes through it." : "Every session goes through it, but it isn't running right now, so sessions can't reach Claude."}</span></span>` : d.live ? `<span class="row" style="gap:8px">${dot("warn")}<span>Running, but Claude Code doesn't go through it.</span></span>` : `<span class="row" style="gap:8px">${dot("")}<span>Off.</span></span>`;
  const hours = (W.today_by_hour || []).filter(h => h.calls).sort((a, b) => b.calls - a.calls).slice(0, 3);
  box.innerHTML = section("Saved by Headroom", `<p class="muted">Headroom is a small program on this computer that every request from Claude Code passes through on its way to Anthropic. It removes repeated and unneeded text first, so less is sent and billed.</p>
    <p>${status}</p>
    ${rows.length ? `<p class="muted small">In this range: ${compact(rows.reduce((a, x) => a + (x.saved || 0), 0))} tokens removed from ${n(rows.reduce((a, x) => a + (x.calls || 0), 0))} requests, about ${usd(rows.reduce((a, x) => a + (x.usd || 0), 0))} by Headroom's count. It's the dashed part of the chart above.${hours.length ? ` Busiest today: ${hours.map(h => `${h.hour}:00 (${n(h.calls)} requests)`).join(", ")}.` : ""}</p>` : ""}`);
  mountTables(box);
  wireICharts(box);
}

PAGES.settings = async () => {
  const [cfg, sk, cm, unlocked] = await Promise.all([api("settings"), api("skills"), api("claudemd"), isUnlocked()]);
  state.settings = { cfg, sk, cm, unlocked };
  return `${head("Settings", unlocked ? "Changes are checked, refused if they look like a password or key, and backed up." : "")}
    ${unlocked ? "" : `<div class="callout">Read-only. To make changes, run <code>lfg ui</code> in your own terminal; it opens this page unlocked.</div>`}
    <div class="section">${tabs("settings", [["claudecode", "Claude Code", null, settingsClaudeCode], ["general", "General", null, settingsGeneral], ["storage", "Disk space", null, settingsStorage], ["rules", "Rules", null, settingsRules], ["claudemd", "Your instructions", null, settingsClaude]])}</div>`;
};

// ------------------------------------------------------------------ skills: every skill Claude Code loads, from every source
const SRC_LABEL = { personal: "Yours", "personal command": "Your command", project: "This project", plugin: "Plugin" };
PAGES.skills = async () => {
  const [sk, cm, unlocked] = await Promise.all([api("skills"), api("claudemd"), isUnlocked()]);
  state.settings = Object.assign(state.settings || {}, { sk, cm, unlocked, cfg: (state.settings || {}).cfg });
  return `${head("Skills", "Everything Claude Code can load as a skill on this computer: yours, this project's and every plugin's, LFG's included.")}
    ${unlocked ? "" : `<div class="callout">Read-only. To change skills, run <code>lfg ui</code> in your own terminal; it opens this page unlocked.</div>`}
    <div class="section">${tabs("skillspage", [["all", "All skills", null, () => '<div id="skills-box"><div class="loading">Reading skills…</div></div>'], ["lfgedit", "Edit LFG skills", null, settingsSkills]])}</div>`;
};
async function loadSkills() {
  const box = $("#skills-box");
  if (!box) return;
  const d = await api("allskills"), un = state.settings.unlocked, S = d.summary;
  const filt = sessionStorage.getItem("lfg.skills.filter") || "all";
  const rows = d.skills.filter(r => filt === "all" || (filt === "collisions" ? r.collides_with.length : filt === "auto" ? r.auto : r.source === filt));
  box.innerHTML = `<div class="cols">${stat("Skills", n(S.total))}${stat("Claude may use on its own", n(S.auto), `about ${compact(S.approx_tokens)} tokens of descriptions in every session`)}${stat("Name clashes", n(S.collisions), "the short name goes to your own skill first")}</div>
    <div class="row mt"><label class="muted small" for="sk-filter">Show</label><select id="sk-filter">${[["all", "All"], ["auto", "Used on its own"], ["collisions", "Name clashes"], ...S.sources.map(x => [x, SRC_LABEL[x] || x])].map(([v, l]) => `<option value="${esc(v)}" ${v === filt ? "selected" : ""}>${esc(l)}</option>`).join("")}</select><span class="save-msg" id="sk-msg"></span></div>
    <div class="box mt">${table(rows, [
      { k: "invoke", label: "Type", html: r => `<code class="nowrap">${esc(r.invoke)}</code>${r.shadowed ? ' <span class="tag" title="A skill of yours has the same short name">use full name</span>' : ""}` },
      { k: "source", label: "From", html: r => `${esc(SRC_LABEL[r.source] || r.source)}${r.plugin ? `<div class="sub">${esc(r.plugin)}${r.enabled === false ? " · off" : ""}</div>` : ""}` },
      { k: "auto", label: "Claude uses it on its own", sort: r => (r.auto ? 1 : 0), html: r => r.editable ? `<label class="row"><input type="checkbox" data-sk-auto="${esc(r.id)}" ${r.auto ? "checked" : ""} ${un ? "" : "disabled"}> ${r.auto ? "yes" : "only when typed"}</label>` : (r.auto ? "yes" : "only when typed") },
      { k: "description", label: "What it does", html: r => `<span title="${esc(r.description)}">${esc(r.description.slice(0, 140))}${r.description.length > 140 ? "…" : ""}</span>${r.collides_with.length ? `<div class="sub">same name as ${r.collides_with.map(x => `<code>${esc(x)}</code>`).join(", ")}</div>` : ""}` },
      { k: "chars", label: "Size", num: true },
    ], { onRow: r => showSkillText(r.id), emptyTitle: "No skills here" })}</div>`;
  mountTables(box);
  $("#sk-filter", box).onchange = e => { sessionStorage.setItem("lfg.skills.filter", e.target.value); loadSkills(); };
  $$("[data-sk-auto]", box).forEach(c => {
    c.onclick = e => e.stopPropagation();
    c.onchange = async () => {
      const r = await save("skill_auto", { id: c.dataset.skAuto, auto: c.checked });
      saidMsg($("#sk-msg"), r, r.ok ? "Saved." : "");
      if (!r.ok) c.checked = !c.checked;
    };
  });
}
async function showSkillText(id) {
  const d = await api("skilltext", { id });
  if (d.available === false) return;
  const fm = frontMatter(d.text);
  openDrawer(d.invoke, `${fm.meta.description ? `<p class="muted">${txt(fm.meta.description)}</p>` : ""}${d.lfg_name ? '<p class="small">Change it under <b>Edit LFG skills</b>.</p>' : ""}<div class="md">${md(fm.body)}</div>`);
};

PAGES.help = async () => {
  const d = await api("guide");
  return `${head("Help", `New here? Type <code>/lfg:wizard</code> in Claude Code for a guided run, or <code>/lfg:which</code> if you're not sure what to do next. LFG ${esc(d.version)}.`)}
    ${tabs("help", [
      ["guide", "Guide", null, () => d.has_guide ? `<iframe class="viewer" src="/guide/guide.html" title="LFG guide" referrerpolicy="no-referrer"></iframe>` : empty("The guide isn't installed", "Re-run <code>bootstrap.sh</code>.")],
      ["skills", "What you can ask for", d.skills.length, () => `<div class="box">${table(d.skills, [{ k: "name", label: "Command", html: r => `<code>/${esc(r.name)}</code>` }, { k: "description", label: "What it does" }])}</div>`],
    ])}`;
};

// ------------------------------------------------------------------ shell
const NAV_GROUPS = [["Your work", ["home", "runs", "issues", "review", "checks"]], ["This project", ["code", "docs", "knowledge"]], ["LFG", ["usage", "skills", "integrations", "settings", "help"]]];
/* 24px line icons, drawn for these pages (stroke = currentColor) */
const ICON = {
  home: "M3 10.5 12 3l9 7.5M5 9v11h5v-6h4v6h5V9",
  runs: "M5 4l14 8-14 8z",
  issues: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2z",
  checks: "M12 3l8 3v6c0 5-3.4 8.3-8 9-4.6-.7-8-4-8-9V6zM9 12l2 2 4-4",
  review: "M4 5h16v11H9l-5 4zM8 9h8M8 12h5",
  code: "M8 7l-5 5 5 5M16 7l5 5-5 5M13.5 5l-3 14",
  docs: "M14 3H6v18h12V7zM14 3v4h4M9 12h6M9 16h6",
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
};
const icon = (k, cls = "ico") => `<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true"><path d="${ICON[k] || ""}"/></svg>`;
function renderNav(active) {
  $("#nav").innerHTML = NAV_GROUPS.map(([g, ks]) => `<div class="nav-grp">${esc(g)}</div>${ks.map(k => `<a class="${k === active ? "on" : ""}" href="#${k}"${k === active ? ' aria-current="page"' : ""}>${icon(k)}<span>${esc(TITLES[k])}</span></a>`).join("")}`).join("");
}
/* Breadcrumb in the top bar: project / page / item. Pages that open an item call crumbs() again with it. */
function crumbs(page, item, itemHref) {
  const parts = [`<span class="crumb-proj">${esc(repoName() || "LFG")}</span>`, `<a href="#${page}">${icon(page)}${esc(TITLES[page] || page)}</a>`];
  if (item) parts.push(itemHref ? `<a href="${itemHref}">${esc(item)}</a>` : `<span>${esc(item)}</span>`);
  $("#crumbs").innerHTML = parts.join('<span class="sep">/</span>');
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
    el.innerHTML = `<span class="map-line">${dot(t)}<span class="label">Code map: ${esc((text || "unknown").toLowerCase())}</span></span>${mapBtn(g.status, "btn tiny")}`;
    el.title = `Code map: ${(text || "unknown").toLowerCase()}. Agents read this map instead of whole files.`;
    wireMap(el);
    if (g.status === "syncing") { mapWatching = true; mapTimer = setTimeout(mapStatus, 4000); }
    else if (mapWatching) {
      mapWatching = false;
      if (["home", "code"].includes((location.hash.slice(1) || "home").split("/")[0])) { state.cache = {}; route(); }
    }
  } catch (e) { el.innerHTML = ""; }
}
let renderSeq = 0;
/* Re-draw the current page in place: no loading placeholder, same scroll position, open sections stay open. For
   controls that change one thing on the page (the Usage range); route() is for going to a page. */
function softRoute() { return route({ soft: true }); }
async function route(opts) {
  const soft = !!(opts && opts.soft);
  let [page, ...rest] = (location.hash.slice(1) || "home").split("/");
  page = { overview: "home", reviews: "checks", security: "checks", architecture: "code", health: "code", brain: "knowledge", tools: "settings" }[page] || page;
  const key = PAGES[page] ? page : "home";
  const arg = rest.join("/");
  renderNav(key);
  crumbs(key);
  document.title = `${TITLES[key]} · LFG`;
  const seq = ++renderSeq, view = $("#view"), y = window.scrollY;
  view.classList.toggle("wide", key === "review" && !!arg);  // the review screens are two panes: use the width
  const open = soft ? $$("details[open]", view).map((d, i) => d.id || "i" + i) : [];
  if (!soft) view.innerHTML = '<div class="skeleton" style="height:60px;width:40%"></div><div class="skeleton mt"></div><div class="skeleton mt" style="height:220px"></div>';
  let html;
  try { html = await PAGES[key](decodeURIComponent(arg)); } catch (e) { html = unavailable({ why: "Couldn't load this page: " + e.message }); }
  if (seq !== renderSeq) return;
  view.innerHTML = html;
  mountTables(view); mountTabs(view); wire(view);
  $$("[data-href]", view).forEach(li => li.onclick = () => (location.hash = li.dataset.href));
  if (key === "docs") wireDocs();
  if (key === "review") wireReview(view);
  if (key === "checks") { $$('[data-tabs="checks"] .tab', view).forEach(t => t.addEventListener("click", () => setTimeout(() => wireSonar(view), 0))); wireSonar(view); }
  if (key === "usage") { wireUsage(view); loadHeadroom(); }
  if (soft) {
    $$("details", view).forEach((d, i) => { if (open.includes(d.id || "i" + i)) d.open = true; });
    window.scrollTo(0, y);
  } else if (!arg) window.scrollTo(0, 0);
}
function wireDocs() {
  const body = $("#doc-body");
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
async function init() {
  if (location.hash.startsWith("#unlock=")) {  // from `lfg ui`: keep the edit key, drop it from the URL
    localStorage.setItem("lfg.editKey", decodeURIComponent(location.hash.slice(8)));
    history.replaceState(null, "", location.pathname);
  }
  $("#drawer-close").onclick = closeDrawer;
  $("#drawer").onclick = e => { if (e.target.id === "drawer") closeDrawer(); };
  document.addEventListener("keydown", e => { if (e.key === "Escape") closeDrawer(); });
  try { state.rules = await api("rules"); } catch (e) { state.rules = null; }
  mountRuleTips();
  const r = await api("repos");
  state.repos = r.repos || [];
  if (!state.repos.some(x => x.id === state.repo)) state.repo = state.repos[0] ? state.repos[0].id : "";
  $("#repo").innerHTML = state.repos.map(x => `<option value="${esc(x.id)}" title="${esc(x.root || x.id)}" ${x.id === state.repo ? "selected" : ""}>${esc(x.name || x.id)}</option>`).join("") || "<option>no projects yet</option>";
  $("#repo").onchange = async () => { state.repo = $("#repo").value; localStorage.setItem("lfg.repo", state.repo); await loadBranches(); refresh(); };
  $("#branch").onchange = () => { state.branch = $("#branch").value; localStorage.setItem(branchPref(), state.branch); refresh(); };
  window.onhashchange = route;
  await loadBranches();
  mapStatus();
  route();
  offerTours();
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
  sel.hidden = !B.branches.length && !B.unrecorded;
  sel.title = "Show runs and checks from one branch. The code map always follows the checked-out branch.";
}
function refresh() { state.cache = {}; mapStatus(); route(); }
init();
