/* femras — interactive results viewer.
 *
 * Renders, over the canvas, the deformed shape and per-element heatmaps
 * (sigma_x, sigma_y, damage) at any captured time instant, with an adjustable
 * deformation scale factor, plus the load–displacement and max-damage curves.
 *
 * Public API (called from index.html):
 *   initResultsViewer(payload)   store data + build UI
 *   openResultsViewer()          show overlay
 *   closeResultsViewer()         hide overlay
 *
 * Payload shape (from /api/run → fields):
 *   { nodes:[[x,y]…], elements:[[i,j,k]…],
 *     snapshots:[{control,load,dmax,U:[…2N],sigma_x:[…E],sigma_y,damage}…],
 *     curve:{control,load,dmax} }
 */

const SVGNS = "http://www.w3.org/2000/svg";

let _rv = {
  data: null,
  field: "deformed",      // deformed | sigma_x | sigma_y | damage
  snap: 0,
  scale: 1,
  ranges: {},             // per-field {min,max} across all snapshots
  bbox: null,             // undeformed model bounds {minX,maxX,minY,maxY,span}
};

// ── Viridis colormap (9 anchors, linear interpolation) ───────────────────────
const _VIRIDIS = [
  [68, 1, 84], [72, 40, 120], [62, 74, 137], [49, 104, 142],
  [38, 130, 142], [31, 158, 137], [53, 183, 121], [110, 206, 88],
  [181, 222, 43], [253, 231, 37],
];
function _viridis(t) {
  t = Math.min(1, Math.max(0, t));
  const x = t * (_VIRIDIS.length - 1);
  const i = Math.floor(x), f = x - i;
  const a = _VIRIDIS[i], b = _VIRIDIS[Math.min(i + 1, _VIRIDIS.length - 1)];
  const r = Math.round(a[0] + (b[0] - a[0]) * f);
  const g = Math.round(a[1] + (b[1] - a[1]) * f);
  const bl = Math.round(a[2] + (b[2] - a[2]) * f);
  return `rgb(${r},${g},${bl})`;
}

function _mk(tag, attrs) {
  const el = document.createElementNS(SVGNS, tag);
  for (const k in attrs) el.setAttribute(k, attrs[k]);
  return el;
}

// ── Field accessors ──────────────────────────────────────────────────────────
function _fieldLabel(field) {
  return { deformed: "|u| [mm]", sigma_x: "σx [MPa]", sigma_y: "σy [MPa]",
           damage: "Daño" }[field] || field;
}

// Per-element value array for a snapshot + field.
function _elemValues(snap, field) {
  const d = _rv.data;
  if (field === "deformed") {
    // element-average displacement magnitude from nodal U
    const U = snap.U;
    return d.elements.map(([i, j, k]) => {
      const m = a => Math.hypot(U[2 * a], U[2 * a + 1]);
      return (m(i) + m(j) + m(k)) / 3;
    });
  }
  return snap[field] || [];
}

// Global range of a field across all snapshots (stable colors over time).
function _computeRanges() {
  const d = _rv.data;
  const fields = ["deformed", "sigma_x", "sigma_y", "damage"];
  _rv.ranges = {};
  for (const f of fields) {
    let mn = Infinity, mx = -Infinity;
    for (const s of d.snapshots) {
      const vals = _elemValues(s, f);
      for (const v of vals) { if (v < mn) mn = v; if (v > mx) mx = v; }
    }
    if (!isFinite(mn)) { mn = 0; mx = 1; }
    if (f === "damage") { mn = 0; mx = 1; }   // damage always 0..1
    _rv.ranges[f] = { min: mn, max: mx };
  }
}

function _computeBbox() {
  const ns = _rv.data.nodes;
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const [x, y] of ns) {
    if (x < minX) minX = x; if (x > maxX) maxX = x;
    if (y < minY) minY = y; if (y > maxY) maxY = y;
  }
  const span = Math.max(maxX - minX, maxY - minY) || 1;
  _rv.bbox = { minX, maxX, minY, maxY, span };
}

// Suggest a scale so max displacement ≈ 8% of the model span.
function _autoScale() {
  const r = _rv.ranges.deformed;
  const umax = r ? r.max : 0;
  if (umax < 1e-12) return 1;
  return +(0.08 * _rv.bbox.span / umax).toPrecision(2);
}

// ── Rendering ────────────────────────────────────────────────────────────────
function _render() {
  const d = _rv.data;
  if (!d) return;
  const snap = d.snapshots[_rv.snap];
  const world = document.getElementById("res-world");
  world.innerHTML = "";

  const scale = _rv.field === "deformed" ? _rv.scale : _rv.scale; // scale all fields
  const U = snap.U;
  const defX = i => d.nodes[i][0] + scale * U[2 * i];
  const defY = i => d.nodes[i][1] + scale * U[2 * i + 1];

  const vals = _elemValues(snap, _rv.field);
  const rng = _rv.ranges[_rv.field];
  const span = (rng.max - rng.min) || 1;

  // Faint undeformed outline for reference
  const refG = _mk("g", { opacity: "0.18" });
  const sw = _rv.bbox.span * 0.0015;
  for (const [i, j, k] of d.elements) {
    const pts = `${d.nodes[i][0]},${d.nodes[i][1]} ${d.nodes[j][0]},${d.nodes[j][1]} ${d.nodes[k][0]},${d.nodes[k][1]}`;
    refG.appendChild(_mk("polygon", { points: pts, fill: "none",
      stroke: "#7a9ab8", "stroke-width": sw }));
  }
  world.appendChild(refG);

  // Filled deformed elements colored by the selected field
  const g = _mk("g", {});
  d.elements.forEach(([i, j, k], e) => {
    const pts = `${defX(i)},${defY(i)} ${defX(j)},${defY(j)} ${defX(k)},${defY(k)}`;
    const t = (vals[e] - rng.min) / span;
    g.appendChild(_mk("polygon", { points: pts, fill: _viridis(t),
      stroke: _viridis(t), "stroke-width": sw * 0.5 }));
  });
  world.appendChild(g);

  // Fit viewBox to deformed bounds (+ padding)
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (let i = 0; i < d.nodes.length; i++) {
    const x = defX(i), y = defY(i);
    if (x < minX) minX = x; if (x > maxX) maxX = x;
    if (y < minY) minY = y; if (y > maxY) maxY = y;
  }
  const pad = Math.max(maxX - minX, maxY - minY) * 0.06 || 1;
  const svg = document.getElementById("res-svg");
  // res-world has scale(1,-1): svg_y = -world_y → viewBox y = -(maxY)
  svg.setAttribute("viewBox",
    `${minX - pad} ${-(maxY + pad)} ${maxX - minX + 2 * pad} ${maxY - minY + 2 * pad}`);

  _renderColorbar(rng);
  _renderInfo(snap);
  _updateScaleVisibility();
}

function _renderColorbar(rng) {
  const box = document.getElementById("rv-colorbar");
  const stops = [];
  for (let i = 0; i <= 10; i++) stops.push(`${_viridis(i / 10)} ${i * 10}%`);
  const grad = `linear-gradient(to top, ${stops.join(",")})`;
  box.innerHTML =
    `<div class="cb-lbl">${_fieldLabel(_rv.field)}</div>
     <div class="cb-max">${_fmt(rng.max)}</div>
     <div class="cb-bar" style="background:${grad}"></div>
     <div class="cb-min">${_fmt(rng.min)}</div>`;
}

function _fmt(v) {
  if (Math.abs(v) >= 1000 || (Math.abs(v) < 0.01 && v !== 0))
    return v.toExponential(2);
  return (+v).toFixed(Math.abs(v) < 1 ? 3 : 2);
}

function _renderInfo(snap) {
  const info = document.getElementById("rv-info");
  const es = lang === "es";
  info.innerHTML =
    `<span>${es ? "Control" : "Control"}: <b>${_fmt(snap.control)}</b></span>` +
    `<span>${es ? "Carga" : "Load"}: <b>${_fmt(snap.load)}</b></span>` +
    `<span>${es ? "Daño máx" : "Max dmg"}: <b>${_fmt(snap.dmax)}</b></span>` +
    (_rv.field === "deformed"
      ? `<span>${es ? "Escala" : "Scale"}: <b>×${_fmt(_rv.scale)}</b></span>` : "");
}

function _updateScaleVisibility() {
  // scale control is meaningful for all fields (mesh is deformed), keep visible
  const lbl = document.getElementById("rv-time-lbl");
  if (lbl) lbl.textContent =
    `${_rv.snap + 1}/${_rv.data.snapshots.length}`;
}

// ── Curves (Plotly) ──────────────────────────────────────────────────────────
function _plotCurves() {
  const d = _rv.data;
  const ctrl = d.curve.control.map(Math.abs);
  const common = {
    margin: { t: 8, r: 12, b: 38, l: 50 },
    paper_bgcolor: "#0d1929", plot_bgcolor: "#0b1622",
    font: { color: "#dce8f5", size: 10 },
    showlegend: false,
  };
  const cur = d.snapshots[_rv.snap].control;
  Plotly.newPlot("rv-curve-load", [
    { x: ctrl, y: d.curve.load, mode: "lines+markers",
      line: { color: "#60a5fa" }, marker: { size: 3 } },
    { x: [Math.abs(cur)], y: [_interp(ctrl, d.curve.load, Math.abs(cur))],
      mode: "markers", marker: { color: "#f87171", size: 9 } },
  ], Object.assign({}, common, {
    xaxis: { title: lang === "es" ? "|control|" : "|control|", gridcolor: "#233b5c" },
    yaxis: { title: lang === "es" ? "carga" : "load", gridcolor: "#233b5c" },
  }), { displaylogo: false, responsive: true });

  Plotly.newPlot("rv-curve-dmg", [
    { x: ctrl, y: d.curve.dmax, mode: "lines+markers",
      line: { color: "#c0392b" }, marker: { size: 3 } },
    { x: [Math.abs(cur)], y: [_interp(ctrl, d.curve.dmax, Math.abs(cur))],
      mode: "markers", marker: { color: "#fbbf24", size: 9 } },
  ], Object.assign({}, common, {
    xaxis: { title: "|control|", gridcolor: "#233b5c" },
    yaxis: { title: lang === "es" ? "daño máx" : "max dmg", range: [0, 1],
             gridcolor: "#233b5c" },
  }), { displaylogo: false, responsive: true });
}

function _interp(xs, ys, x) {
  if (!xs.length) return 0;
  for (let i = 1; i < xs.length; i++) {
    if (x <= xs[i]) {
      const t = (x - xs[i - 1]) / ((xs[i] - xs[i - 1]) || 1);
      return ys[i - 1] + (ys[i] - ys[i - 1]) * t;
    }
  }
  return ys[ys.length - 1];
}

// ── Public API ───────────────────────────────────────────────────────────────
function initResultsViewer(payload) {
  if (!payload || !payload.fields) return;
  _rv.data = payload.fields;
  _rv.field = "deformed";
  _rv.snap = _rv.data.snapshots.length - 1;  // start at final state
  _computeRanges();
  _computeBbox();
  _rv.scale = _autoScale();
  const scIn = document.getElementById("rv-scale");
  if (scIn) scIn.value = _rv.scale;

  const slider = document.getElementById("rv-time");
  slider.max = _rv.data.snapshots.length - 1;
  slider.value = _rv.snap;

  document.querySelectorAll(".rv-field").forEach(b =>
    b.classList.toggle("active", b.dataset.field === _rv.field));

  _render();
  _plotCurves();
}

function openResultsViewer() {
  const v = document.getElementById("results-viewer");
  if (!v || !_rv.data) return;
  v.style.display = "flex";
  _render();
  // Plotly needs a resize once visible
  setTimeout(() => {
    try { Plotly.Plots.resize("rv-curve-load"); Plotly.Plots.resize("rv-curve-dmg"); }
    catch (e) {}
  }, 50);
}

function closeResultsViewer() {
  const v = document.getElementById("results-viewer");
  if (v) v.style.display = "none";
}

// ── Wire up controls ─────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".rv-field").forEach(btn => {
    btn.addEventListener("click", () => {
      _rv.field = btn.dataset.field;
      document.querySelectorAll(".rv-field").forEach(b =>
        b.classList.toggle("active", b === btn));
      _render();
    });
  });

  const slider = document.getElementById("rv-time");
  if (slider) slider.addEventListener("input", () => {
    _rv.snap = parseInt(slider.value, 10) || 0;
    _render();
    _plotCurves();
  });

  const scIn = document.getElementById("rv-scale");
  if (scIn) scIn.addEventListener("input", () => {
    const v = parseFloat(scIn.value);
    _rv.scale = (!isNaN(v) && v >= 0) ? v : 1;
    _render();
  });

  const auto = document.getElementById("rv-scale-auto");
  if (auto) auto.addEventListener("click", () => {
    _rv.scale = _autoScale();
    if (scIn) scIn.value = _rv.scale;
    _render();
  });

  const tg = document.getElementById("rv-toggle-curves");
  if (tg) tg.addEventListener("click", () => {
    const c = document.getElementById("rv-curves");
    const show = c.style.display === "none";
    c.style.display = show ? "flex" : "none";
    if (show) setTimeout(() => {
      try { Plotly.Plots.resize("rv-curve-load"); Plotly.Plots.resize("rv-curve-dmg"); }
      catch (e) {}
    }, 50);
  });

  const close = document.getElementById("rv-close");
  if (close) close.addEventListener("click", closeResultsViewer);
});

window.initResultsViewer = initResultsViewer;
window.openResultsViewer = openResultsViewer;
window.closeResultsViewer = closeResultsViewer;
