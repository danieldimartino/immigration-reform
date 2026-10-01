{% raw %}
// Shared chart and table helpers for both pages. Included inside a <script>.
"use strict";

const el = (tag, attrs = {}, text) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (text != null) e.textContent = text;
  return e;
};
const svgEl = (tag, attrs = {}) => {
  const e = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  return e;
};
const fmt = n => Math.round(n).toLocaleString("en-US");
const compact = n => n >= 1e6 ? (n / 1e6).toFixed(n % 1e6 ? 1 : 0) + "M"
                    : n >= 1e3 ? (n / 1e3).toFixed(n % 1e3 && n < 1e4 ? 1 : 0) + "k" : String(n);
const pct = (a, b) => b ? (a - b) / b * 100 : null;
const pctText = p => p == null ? "—" : (p > 0 ? "+" : p < 0 ? "−" : "") + Math.abs(p).toFixed(1) + "%";
const signed = n => (n > 0 ? "+" : n < 0 ? "−" : "") + fmt(Math.abs(n));
const SLOT = i => `var(--s${i + 1})`;

function niceTicks(max, n) {
  if (max <= 0) return [0, 1];
  const raw = max / n, p = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map(s => s * p).find(s => s >= raw);
  const t = [];
  for (let v = 0; v <= Math.ceil(max / step) * step + 1e-9; v += step) t.push(v);
  return t;
}

// Drop text elements that would overlap the previous one kept.
function thinLabels(texts, gap) {
  let right = -Infinity;
  for (const t of texts) {
    const bb = t.getBBox();
    if (bb.x < right + gap) t.remove(); else right = bb.x + bb.width;
  }
}

// Event labels go on the first of two lines where they fit, else the second;
// one that fits on neither is left to the tooltip.
function placeEventLabels(texts, W, y0) {
  const lineRight = [-Infinity, -Infinity];
  for (const t of texts) {
    const bb = t.getBBox();
    const line = [0, 1].find(l => bb.x > lineRight[l] + 6 && bb.x + bb.width <= W);
    if (line == null) { t.remove(); continue; }
    t.setAttribute("y", y0 + line * 13);
    lineRight[line] = bb.x + bb.width;
  }
}

// A label-per-year x axis: pick a step so labels stay legible.
function yearStep(n, W) {
  const fit = Math.max(4, Math.floor(W / 60));
  return [1, 2, 5, 10, 20, 25, 50].find(s => n / s <= fit) || 50;
}

function tipRows(tip, title, evLabel, rows, total) {
  tip.replaceChildren(el("div", { class: "t" }, title));
  if (evLabel) tip.append(el("div", { class: "ev" }, evLabel));
  for (const r of rows) {
    const row = el("div", { class: "r" });
    const k = el("span", { class: "key" }); k.style.background = r.color;
    row.append(k, el("b", {}, r.value == null ? "—" : fmt(r.value)), el("span", {}, r.name));
    tip.append(row);
  }
  if (total) {
    const t = el("div", { class: "r" + (rows.length ? " tot" : "") });
    t.append(el("b", {}, fmt(total.value)), el("span", {}, total.name));
    tip.append(t);
  }
}

function placeTip(tip, svg, W, cx, top) {
  const scale = svg.getBoundingClientRect().width / W;
  const box = svg.parentElement.clientWidth, tw = tip.offsetWidth, x = cx * scale;
  tip.style.left = Math.min(Math.max(x + 12 + tw > box ? x - tw - 12 : x + 12, 0), box - tw) + "px";
  tip.style.top = (top * scale) + "px";
}

function attachHover(svg, tip, n, xOf, show) {
  let active = null;
  const hide = () => { active = null; tip.classList.remove("on"); svg.querySelectorAll(".hover-col,.crosshair,.marker").forEach(e => e.setAttribute("visibility", "hidden")); };
  const pick = i => { active = i; show(i); tip.classList.add("on"); };
  svg.onpointermove = e => {
    const r = svg.getBoundingClientRect();
    const i = xOf((e.clientX - r.left) / r.width);
    if (i != null && i >= 0 && i < n) pick(i); else hide();
  };
  svg.onpointerleave = hide;
  svg.onblur = hide;
  svg.onkeydown = e => {
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      e.preventDefault();
      const d = e.key === "ArrowRight" ? 1 : -1;
      pick(active == null ? (d > 0 ? 0 : n - 1) : Math.min(n - 1, Math.max(0, active + d)));
    } else if (e.key === "Escape") hide();
  };
}

// Stacked bars. o = {svg, tip, periods:[{key,label,long}], series:[{name,color}],
// values:[[per series]], events:[{index,label}], xLabel(i,p,W) -> text|null,
// partial:Set(index), height, maxBar, totalName}
function stackedBars(o) {
  const svg = o.svg, tip = o.tip, P = o.periods, S = o.series, V = o.values;
  const W = Math.max(280, svg.parentElement.clientWidth), small = W < 560;
  const H = o.height || (small ? 260 : 340);
  const events = (o.events || []).filter(e => e.index >= 0 && e.index < P.length);
  const m = { t: events.length && !small ? 36 : 8, r: 6, b: 24, l: 44 };
  const pw = W - m.l - m.r, ph = H - m.t - m.b;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("height", H);
  svg.replaceChildren();

  const n = P.length, totals = V.map(v => v.reduce((a, b) => a + b, 0));
  const max = Math.max(0, ...totals);
  const ticks = niceTicks(max, small ? 3 : 4), top = ticks[ticks.length - 1];
  const y = v => m.t + ph - v / top * ph;
  const band = pw / Math.max(n, 1), gap = band > 14 ? 2 : band > 5 ? 1 : 0;
  const bw = Math.max(1, Math.min(band - gap, o.maxBar || 40));
  const x = i => m.l + i * band + (band - bw) / 2;

  const grid = svgEl("g", { class: "grid" }), axis = svgEl("g", { class: "axis" });
  for (const t of ticks) {
    if (t > 0) grid.append(svgEl("line", { x1: m.l, x2: W - m.r, y1: y(t), y2: y(t) }));
    const tx = svgEl("text", { x: m.l - 6, y: y(t) + 4, "text-anchor": "end" });
    tx.textContent = compact(t); axis.append(tx);
  }
  svg.append(grid);

  const evG = svgEl("g", { class: "event" });
  for (const ev of events) {
    const cx = m.l + ev.index * band + band / 2;
    evG.append(svgEl("line", { x1: cx, x2: cx, y1: m.t - (small ? 0 : 4), y2: m.t + ph }));
    if (!small) { const t = svgEl("text", { x: cx + 3, y: m.t - 22 }); t.textContent = ev.label; evG.append(t); }
  }
  svg.append(evG);
  placeEventLabels(evG.querySelectorAll("text"), W, m.t - 22);

  const hover = svgEl("rect", { class: "hover-col", y: m.t, height: ph, width: band, visibility: "hidden" });
  svg.append(hover);
  const bars = svgEl("g");
  P.forEach((p, i) => {
    let acc = 0;
    V[i].forEach((v, s) => {
      if (!v) return;
      const y0 = y(acc), y1 = y(acc + v); acc += v;
      const h = y0 - y1;
      const r = svgEl("rect", { x: x(i), y: y1, width: bw, height: Math.max(h - (h > 3 ? gap : 0), 0.5) });
      r.style.fill = S[s].color;
      if (o.partial && o.partial.has(i)) r.setAttribute("opacity", "0.55");
      bars.append(r);
    });
  });
  svg.append(bars);
  svg.append(svgEl("line", { class: "baseline", x1: m.l, x2: W - m.r, y1: m.t + ph, y2: m.t + ph }));

  P.forEach((p, i) => {
    const label = o.xLabel(i, p, W);
    if (label == null) return;
    const t = svgEl("text", { x: m.l + i * band + band / 2, y: H - 6, "text-anchor": "middle" });
    t.textContent = label; axis.append(t);
  });
  svg.append(axis);
  thinLabels([...axis.querySelectorAll("text[text-anchor=middle]")], 4);

  attachHover(svg, tip, n, f => Math.floor((f * W - m.l) / band), i => {
    const p = P[i];
    hover.setAttribute("x", m.l + i * band); hover.setAttribute("visibility", "visible");
    const ev = events.find(e => e.index === i);
    const rows = S.length > 1 ? S.map((s, k) => ({ name: s.name, color: s.color, value: V[i][k] }))
      .filter(r => r.value).reverse() : [];
    tipRows(tip, p.long + (o.partial && o.partial.has(i) ? " (to date)" : ""), ev && ev.label, rows,
            { name: o.totalName || "total", value: totals[i] });
    placeTip(tip, svg, W, m.l + i * band + band / 2, m.t);
  });
  return { max };
}

// Multi-series lines with a crosshair. o = {svg, tip, periods, series:[{name,color}],
// values:[[per series]] (null = gap), events, xLabel, height}
function lineChart(o) {
  const svg = o.svg, tip = o.tip, P = o.periods, S = o.series, V = o.values;
  const W = Math.max(280, svg.parentElement.clientWidth), small = W < 560;
  const H = o.height || (small ? 260 : 340);
  const events = (o.events || []).filter(e => e.index >= 0 && e.index < P.length);
  const m = { t: events.length && !small ? 36 : 10, r: 10, b: 24, l: 44 };
  const pw = W - m.l - m.r, ph = H - m.t - m.b;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("height", H);
  svg.replaceChildren();

  const n = P.length;
  const max = Math.max(0, ...V.flat().filter(v => v != null));
  const ticks = niceTicks(max, small ? 3 : 4), top = ticks[ticks.length - 1];
  const y = v => m.t + ph - v / top * ph;
  const x = i => m.l + (n > 1 ? i / (n - 1) * pw : pw / 2);

  const grid = svgEl("g", { class: "grid" }), axis = svgEl("g", { class: "axis" });
  for (const t of ticks) {
    if (t > 0) grid.append(svgEl("line", { x1: m.l, x2: W - m.r, y1: y(t), y2: y(t) }));
    const tx = svgEl("text", { x: m.l - 6, y: y(t) + 4, "text-anchor": "end" });
    tx.textContent = compact(t); axis.append(tx);
  }
  svg.append(grid);
  const evG = svgEl("g", { class: "event" });
  for (const ev of events) {
    const cx = x(ev.index);
    evG.append(svgEl("line", { x1: cx, x2: cx, y1: m.t - (small ? 0 : 4), y2: m.t + ph }));
    if (!small) { const t = svgEl("text", { x: cx + 3, y: m.t - 22 }); t.textContent = ev.label; evG.append(t); }
  }
  svg.append(evG);
  placeEventLabels(evG.querySelectorAll("text"), W, m.t - 22);
  svg.append(svgEl("line", { class: "baseline", x1: m.l, x2: W - m.r, y1: m.t + ph, y2: m.t + ph }));

  S.forEach((s, k) => {
    let d = "", pen = false;
    for (let i = 0; i < n; i++) {
      const v = V[i][k];
      if (v == null) { pen = false; continue; }
      d += (pen ? "L" : "M") + x(i).toFixed(1) + "," + y(v).toFixed(1); pen = true;
    }
    const path = svgEl("path", { class: "series-line", d }); path.style.stroke = s.color; svg.append(path);
  });

  const cross = svgEl("line", { class: "crosshair", y1: m.t, y2: m.t + ph, visibility: "hidden" });
  svg.append(cross);
  const marks = S.map(s => { const c = svgEl("circle", { class: "marker", r: 4, visibility: "hidden" }); c.style.fill = s.color; svg.append(c); return c; });

  P.forEach((p, i) => {
    const label = o.xLabel(i, p, W);
    if (label == null) return;
    const t = svgEl("text", { x: x(i), y: H - 6, "text-anchor": "middle" });
    t.textContent = label; axis.append(t);
  });
  svg.append(axis);
  thinLabels([...axis.querySelectorAll("text[text-anchor=middle]")], 4);

  attachHover(svg, tip, n, f => Math.round((f * W - m.l) / pw * (n - 1)), i => {
    cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("visibility", "visible");
    marks.forEach((c, k) => {
      const v = V[i][k];
      c.setAttribute("visibility", v == null ? "hidden" : "visible");
      if (v != null) { c.setAttribute("cx", x(i)); c.setAttribute("cy", y(v)); }
    });
    const ev = events.find(e => e.index === i);
    tipRows(tip, P[i].long, ev && ev.label, S.map((s, k) => ({ name: s.name, color: s.color, value: V[i][k] })));
    placeTip(tip, svg, W, x(i), m.t);
  });
}

// Legend as buttons. opts: {line, toggled(s), disabled(s), onPick(s), title(s)}
function renderLegend(ul, series, live, opts = {}) {
  ul.replaceChildren();
  series.forEach((s, i) => {
    if (live && !live[i]) return;
    const b = el("button", { type: "button" });
    const sw = el("span", { class: "sw" + (opts.line ? " line" : "") }); sw.style.background = s.color;
    b.append(sw, document.createTextNode(s.name));
    if (opts.toggled) b.setAttribute("aria-pressed", String(opts.toggled(s)));
    if (opts.disabled && opts.disabled(s)) b.disabled = true;
    else if (opts.onPick) { b.title = opts.title ? opts.title(s) : ""; b.addEventListener("click", () => opts.onPick(s)); }
    else b.disabled = true;
    const li = el("li"); li.append(b); ul.append(li);
  });
}

function sortableTable(table, columns, rows, sortState, onSort, footer) {
  table.replaceChildren();
  const tr = el("tr");
  columns.forEach((c, i) => {
    const th = el("th", { scope: "col" });
    if (c.sort) {
      const b = el("button", { type: "button" }, c.label);
      b.addEventListener("click", () => onSort(i));
      th.append(b);
      if (sortState.col === i) th.setAttribute("aria-sort", sortState.asc ? "ascending" : "descending");
    } else th.textContent = c.label;
    if (c.cls) th.className = c.cls;
    tr.append(th);
  });
  const thead = el("thead"); thead.append(tr);
  const tb = el("tbody");
  const col = columns[sortState.col];
  rows.sort((p, q) => {
    const a = col.sort(p), b = col.sort(q);
    const d = typeof a === "string" ? a.localeCompare(b) : (a ?? -Infinity) - (b ?? -Infinity);
    return sortState.asc ? d : -d;
  });
  rows.forEach(r => {
    const row = el("tr");
    columns.forEach(c => { const td = el("td"); if (c.cls) td.className = c.cls; c.cell(r, td); row.append(td); });
    tb.append(row);
  });
  table.append(thead, tb);
  if (footer) {
    const tf = el("tfoot"), fr = el("tr");
    columns.forEach(c => { const td = el("td"); if (c.cls) td.className = c.cls; (c.foot || (() => {}))(td); fr.append(td); });
    tf.append(fr); table.append(tf);
  }
}

function sparkline(vals) {
  const w = 120, h = 26, s = svgEl("svg", { class: "spark", width: w, height: h, viewBox: `0 0 ${w} ${h}`, "aria-hidden": "true" });
  if (!vals.length) return s;
  const mx = Math.max(...vals, 1);
  const d = vals.map((v, i) => `${i ? "L" : "M"}${(i / Math.max(vals.length - 1, 1) * (w - 2) + 1).toFixed(1)},${(h - 2 - v / mx * (h - 4)).toFixed(1)}`).join("");
  s.append(svgEl("path", { d }));
  return s;
}

function fillSelect(sel, options, allLabel) {
  sel.replaceChildren();
  if (allLabel) sel.append(el("option", { value: "" }, allLabel));
  for (const [v, t] of options) sel.append(el("option", { value: v }, t));
}

// Packed table helpers: rows are [period, code..., value], dims name each code.
function rankDim(table, dims, dim) {
  const i = dims.indexOf(dim) + 1, tot = new Map();
  for (const r of table.rows) tot.set(r[i], (tot.get(r[i]) || 0) + r[r.length - 1]);
  return table.dims[dim].map((v, code) => ({ v, code, n: tot.get(code) || 0 })).sort((a, b) => b.n - a.n).map(x => x.v);
}
// A predicate from {dim: value} filters, or null if the table lacks a filtered dim.
function packedMatcher(table, dims, filters) {
  const checks = [];
  for (const [d, v] of Object.entries(filters)) {
    if (!v) continue;
    const i = dims.indexOf(d);
    if (i < 0) return null;
    checks.push([i + 1, table.dims[d].indexOf(v)]);
  }
  return r => checks.every(([i, c]) => r[i] === c);
}

function onResize(node, fn) {
  let raf;
  new ResizeObserver(() => { cancelAnimationFrame(raf); raf = requestAnimationFrame(fn); }).observe(node);
}
{% endraw %}
