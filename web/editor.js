/**
 * editor.js — femras interactive canvas preprocessor
 *
 * Two editing modes:
 *   poly – click-to-draw polygon → PolygonGeometry config (T3, plane strain)
 *   beam – form-based → BeamGeometry config (Q4, plane stress)
 *
 * Public API (called from index.html / app.js):
 *   initEditor()
 *   editorExportConfig()
 *   editorLoadTemplate(name)   "beam" | "dam"
 *   addScheduleStep()
 */

"use strict";

// ─── Tools ──────────────────────────────────────────────────────────────────
const TOOL = {
  VERTEX:   "vertex",
  SUPPORT:  "support",
  LOAD:     "load",
  EDGE:     "edge",
  ESUPPORT: "esupport",   // support on a whole edge
  ELOAD:    "eload",      // distributed time-variable load on a whole edge
  DELETE:   "delete",
};

// ─── Colours ─────────────────────────────────────────────────────────────────
const C = {
  POLY_FILL:   "rgba(30,80,55,0.5)",
  POLY_EDGE:   "#3b82f6",
  VERT_IDLE:   "#3b82f6",
  VERT_HOVER:  "#fbbf24",
  VERT_SEL:    "#f87171",
  EDGE_HOVER:  "rgba(251,191,36,0.4)",
  EDGE_FACE:   "#38bdf8",
  SUPPORT_COL: "#fbbf24",
  LOAD_COL:    "#f87171",
  GRID:        "rgba(255,255,255,0.05)",
  TEXT:        "#7a9ab8",
};

// ─── State ───────────────────────────────────────────────────────────────────
let edMode = "poly";
let activeTool = TOOL.VERTEX;
let activeSupportType = "fixed";

const poly = {
  verts:         [],      // [{x,y}] model coords (mm)
  closed:        false,
  supports:      [],      // [{vIdx, type}]
  loads:         [],      // [{vIdx, fx, fy}]
  hydraulicFace: null,    // {v1Idx, v2Idx} or null
  edgeSupports:  [],      // [{e0, type}]  e0 = start vertex idx of edge
  edgeLoads:     [],      // [{e0, pNormal, pTangential, fnType, expr, pointsText}]
  meshSize:      2000.0,
  thickness:     1000.0,
  problemType:   "plane_strain",
  loadHistory:   [],      // [target, target, …] ordered list of control targets
  tStart:        0.0,     // time_history pseudo-time range
  tEnd:          1.0,
  dt:            0.05,
};

const beam = {
  L: 430, H: 105, nx: 86, ny: 21,
  notchW: 3, notchH: 52.5, span: 400, thickness: 75,
  loadHistory: [],
};

// SVG interaction
let svgEl     = null;
let worldG    = null;
let hoverIdx  = -1;
let selIdx    = -1;
let selEdge   = -1;  // selected edge (start-vertex idx) for the inspector
let hoverEdge = -1;  // index into verts[] of the start vertex of hovered edge
let dragState = null;

// Tools that operate on whole edges (drive edge hover + edge picking).
const EDGE_TOOLS = new Set([TOOL.EDGE, TOOL.ESUPPORT, TOOL.ELOAD]);

function _supportFlags(type) {
  if (type === "roller_x") return { fix_x: false, fix_y: true };   // free in X
  if (type === "roller_y") return { fix_x: true,  fix_y: false };  // free in Y
  return { fix_x: true, fix_y: true };                             // fixed
}

// ─── i18n helper ─────────────────────────────────────────────────────────────
// _ct() is defined in app.js; it returns I18N[lang].canvas[key]

// ─── Init ────────────────────────────────────────────────────────────────────
function initEditor() {
  svgEl  = document.getElementById("ed-svg");
  worldG = document.getElementById("ed-world");

  // Tool buttons
  document.querySelectorAll(".ed-tool").forEach(btn => {
    btn.addEventListener("click", () => {
      activeTool = btn.dataset.tool;
      if (btn.dataset.stype) activeSupportType = btn.dataset.stype;
      document.querySelectorAll(".ed-tool").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      _updateCursor();
    });
  });

  // Polygon parameter inputs
  _bindInput("ed-meshsize",  v => { poly.meshSize  = v || 2000; });
  _bindInput("ed-thickness", v => { poly.thickness = v || 1000; });
  _bindInput("ed-tstart",    v => { poly.tStart = isNaN(v) ? 0 : v; });
  _bindInput("ed-tend",      v => { poly.tEnd   = isNaN(v) ? 1 : v; });
  _bindInput("ed-dt",        v => { poly.dt     = v || 0.05; });
  const ptEl = document.getElementById("ed-probtype");
  if (ptEl) ptEl.addEventListener("change", () => { poly.problemType = ptEl.value; });

  // Beam form
  ["L","H","nx","ny","notchW","notchH","span","thickness"].forEach(k => {
    const el = document.getElementById(`bm-${k}`);
    if (el) el.addEventListener("input", () => {
      beam[k] = parseFloat(el.value) || beam[k];
      renderBeamSchematic();
    });
  });

  // SVG events
  svgEl.addEventListener("click",     _onSvgClick);
  svgEl.addEventListener("dblclick",  _onSvgDblClick);
  svgEl.addEventListener("mousemove", _onSvgMouseMove);
  svgEl.addEventListener("mousedown", _onSvgMouseDown);
  svgEl.addEventListener("mouseup",   _onSvgMouseUp);

  // Keyboard shortcuts
  document.addEventListener("keydown", _onKeyDown);

  // Language change
  document.addEventListener("langchange", () => {
    _updateStatus(null);  // refresh with current content
    renderSchedulePanel();
  });

  editorLoadTemplate("dam");
}

function _bindInput(id, fn) {
  const el = document.getElementById(id);
  if (el) el.addEventListener("change", () => fn(parseFloat(el.value)));
}

// ─── Templates ───────────────────────────────────────────────────────────────
function editorLoadTemplate(name) {
  if (name === "beam") {
    edMode = "beam";
    _showMode("beam");
    _syncBeamForm();
    renderBeamSchematic();
    renderSchedulePanel();
    _updateStatus(_ct("st_no_verts"));
  } else {
    edMode = "poly";
    poly.verts = [
      {x:0,     y:0},
      {x:70000, y:0},
      {x:19200, y:66000},
      {x:14800, y:103000},
      {x:0,     y:103000},
    ];
    poly.closed        = true;
    poly.supports      = [{vIdx:0, type:"fixed"}, {vIdx:1, type:"fixed"}];
    poly.loads         = [];
    poly.hydraulicFace = {v1Idx:4, v2Idx:0};  // left face: V4→V0 (x=0, upstream)
    poly.edgeSupports  = [];
    poly.edgeLoads     = [];
    poly.meshSize      = 2000;
    poly.thickness     = 1000;
    poly.problemType   = "plane_strain";
    poly.loadHistory   = [];
    poly.tStart        = 0.0;
    poly.tEnd          = 1.0;
    poly.dt            = 0.05;
    _showMode("poly");
    _syncPolyForm();
    _fitView();
    _render();
    renderSchedulePanel();
    _updateStatus(_ct("st_template"));
  }
}

// ─── Mode visibility ─────────────────────────────────────────────────────────
function _showMode(mode) {
  const pf = document.getElementById("poly-form");
  const bf = document.getElementById("beam-form");
  if (pf) pf.style.display = mode === "poly" ? "" : "none";
  if (bf) bf.style.display = mode === "beam" ? "" : "none";
  // Edge tools (hydraulic face, edge support, edge load) only make sense in poly mode
  ["edge", "esupport", "eload"].forEach(t => {
    const b = document.querySelector(`[data-tool="${t}"]`);
    if (b) b.style.display = mode === "poly" ? "" : "none";
  });
  // Time-history range fields only relevant in poly mode
  const tr = document.getElementById("ed-time-range");
  if (tr) tr.style.display = mode === "poly" ? "" : "none";
}

function _syncPolyForm() {
  const msEl = document.getElementById("ed-meshsize");
  const thEl = document.getElementById("ed-thickness");
  const ptEl = document.getElementById("ed-probtype");
  if (msEl)  msEl.value  = poly.meshSize;
  if (thEl)  thEl.value  = poly.thickness;
  if (ptEl)  ptEl.value  = poly.problemType;
  const ts = document.getElementById("ed-tstart");
  const te = document.getElementById("ed-tend");
  const dt = document.getElementById("ed-dt");
  if (ts) ts.value = poly.tStart;
  if (te) te.value = poly.tEnd;
  if (dt) dt.value = poly.dt;
}

function _syncBeamForm() {
  ["L","H","nx","ny","notchW","notchH","span","thickness"].forEach(k => {
    const el = document.getElementById(`bm-${k}`);
    if (el) el.value = beam[k];
  });
}

// ─── ViewBox ─────────────────────────────────────────────────────────────────
function _fitView() {
  if (!poly.verts.length) return;
  const xs = poly.verts.map(v => v.x);
  const ys = poly.verts.map(v => v.y);
  const xmin = Math.min(...xs), xmax = Math.max(...xs);
  const ymin = Math.min(...ys), ymax = Math.max(...ys);
  const W = xmax - xmin || 100, H = ymax - ymin || 100;
  const pad = 0.12 * Math.max(W, H);
  svgEl.setAttribute("viewBox",
    `${xmin - pad} ${-(ymax + pad)} ${W + 2*pad} ${H + 2*pad}`);
}

// ─── Rendering ───────────────────────────────────────────────────────────────
function _render() {
  if (!worldG) return;
  worldG.innerHTML = "";
  if (!poly.verts.length) return;
  _drawGrid();
  _drawPolygon();
  _drawHydraulicFace();
  _drawEdgeHover();
  _drawEdgeSupports();
  _drawEdgeLoads();
  _drawSupports();
  _drawLoads();
  _drawVertices();
}

function _drawGrid() {
  const xs = poly.verts.map(v => v.x);
  const ys = poly.verts.map(v => v.y);
  const xmin = Math.min(...xs) - poly.meshSize * 2;
  const xmax = Math.max(...xs) + poly.meshSize * 2;
  const ymin = Math.min(...ys) - poly.meshSize * 2;
  const ymax = Math.max(...ys) + poly.meshSize * 2;
  const step = poly.meshSize * 5;
  const sw = poly.meshSize * 0.09;
  const g = _mkEl("g", { opacity: 0.5 });
  for (let x = Math.ceil(xmin / step) * step; x <= xmax; x += step)
    g.appendChild(_mkEl("line", {x1:x, y1:ymin, x2:x, y2:ymax, stroke:C.GRID, "stroke-width":sw}));
  for (let y = Math.ceil(ymin / step) * step; y <= ymax; y += step)
    g.appendChild(_mkEl("line", {x1:xmin, y1:y, x2:xmax, y2:y, stroke:C.GRID, "stroke-width":sw}));
  worldG.appendChild(g);
}

function _drawPolygon() {
  const verts = poly.verts;
  if (verts.length < 2) return;
  const pts = verts.map(v => `${v.x},${v.y}`).join(" ");
  const sw = poly.meshSize * 0.28;
  if (poly.closed) {
    worldG.appendChild(_mkEl("polygon", {
      points: pts, fill: C.POLY_FILL,
      stroke: C.POLY_EDGE, "stroke-width": sw, "stroke-linejoin": "round",
    }));
  } else {
    worldG.appendChild(_mkEl("polyline", {
      points: pts, fill: "none",
      stroke: C.POLY_EDGE, "stroke-width": sw, "stroke-linejoin": "round",
    }));
  }
}

function _drawHydraulicFace() {
  if (!poly.hydraulicFace || !poly.closed) return;
  const {v1Idx, v2Idx} = poly.hydraulicFace;
  if (v1Idx >= poly.verts.length || v2Idx >= poly.verts.length) return;
  const v1 = poly.verts[v1Idx], v2 = poly.verts[v2Idx];
  const sw = poly.meshSize * 1.2;
  // Bold coloured edge
  worldG.appendChild(_mkEl("line", {
    x1: v1.x, y1: v1.y, x2: v2.x, y2: v2.y,
    stroke: C.EDGE_FACE, "stroke-width": sw,
    "stroke-linecap": "round", opacity: 0.85,
  }));
  // Wave tick marks along the edge
  const mx = (v1.x + v2.x) / 2, my = (v1.y + v2.y) / 2;
  const tx = _mkEl("text", {
    x: mx + poly.meshSize * 2,
    y: -(my - poly.meshSize * 2),
    "font-size": poly.meshSize * 3,
    fill: C.EDGE_FACE,
    "pointer-events": "none",
    transform: "scale(1,-1)",
  });
  tx.textContent = "≈";
  worldG.appendChild(tx);
}

function _drawEdgeHover() {
  if (!EDGE_TOOLS.has(activeTool) || hoverEdge < 0 || !poly.closed) return;
  const n = poly.verts.length;
  const v1 = poly.verts[hoverEdge];
  const v2 = poly.verts[(hoverEdge + 1) % n];
  const col = activeTool === TOOL.ELOAD ? C.LOAD_COL
            : activeTool === TOOL.ESUPPORT ? C.SUPPORT_COL : C.VERT_HOVER;
  worldG.appendChild(_mkEl("line", {
    x1: v1.x, y1: v1.y, x2: v2.x, y2: v2.y,
    stroke: col, "stroke-width": poly.meshSize * 1.5,
    "stroke-linecap": "round", opacity: 0.55,
  }));
}

// Unit inward normal of edge e0 (toward the polygon centroid).
function _edgeInwardNormal(e0) {
  const n = poly.verts.length;
  const v1 = poly.verts[e0], v2 = poly.verts[(e0 + 1) % n];
  const tx = v2.x - v1.x, ty = v2.y - v1.y;
  const L = Math.hypot(tx, ty) || 1;
  let nx = -ty / L, ny = tx / L;
  const cx = poly.verts.reduce((s, v) => s + v.x, 0) / n;
  const cy = poly.verts.reduce((s, v) => s + v.y, 0) / n;
  const mx = (v1.x + v2.x) / 2, my = (v1.y + v2.y) / 2;
  if (nx * (cx - mx) + ny * (cy - my) < 0) { nx = -nx; ny = -ny; }
  return { nx, ny, tx: tx / L, ty: ty / L, L };
}

function _drawEdgeSupports() {
  if (!poly.closed) return;
  const n = poly.verts.length;
  const sz = poly.meshSize * 2.4;
  poly.edgeSupports.forEach(es => {
    if (es.e0 < 0 || es.e0 >= n) return;
    const v1 = poly.verts[es.e0], v2 = poly.verts[(es.e0 + 1) % n];
    const { nx, ny, L } = _edgeInwardNormal(es.e0);
    // outward direction for the symbols (opposite of inward normal)
    const ox = -nx, oy = -ny;
    const count = Math.max(2, Math.min(12, Math.round(L / (poly.meshSize * 5))));
    const sel = es.e0 === selEdge;
    const g = _mkEl("g", { opacity: sel ? 1 : 0.9 });
    // highlight the edge itself
    g.appendChild(_mkEl("line", {
      x1: v1.x, y1: v1.y, x2: v2.x, y2: v2.y,
      stroke: C.SUPPORT_COL, "stroke-width": poly.meshSize * 0.5, opacity: 0.5,
    }));
    for (let k = 0; k <= count; k++) {
      const f = k / count;
      const px = v1.x + (v2.x - v1.x) * f;
      const py = v1.y + (v2.y - v1.y) * f;
      _drawSupportSymbol(g, px, py, ox, oy, es.type, sz);
    }
    worldG.appendChild(g);
  });
}

// Draw a support glyph at (px,py) opening toward (ox,oy) (outward unit vector).
function _drawSupportSymbol(g, px, py, ox, oy, type, sz) {
  // perpendicular (along edge) unit
  const ex = -oy, ey = ox;
  const apex = { x: px, y: py };
  const b1 = { x: px + ox * sz * 1.55 + ex * sz, y: py + oy * sz * 1.55 + ey * sz };
  const b2 = { x: px + ox * sz * 1.55 - ex * sz, y: py + oy * sz * 1.55 - ey * sz };
  const filled = type === "fixed";
  g.appendChild(_mkEl("polygon", {
    points: `${apex.x},${apex.y} ${b1.x},${b1.y} ${b2.x},${b2.y}`,
    fill: filled ? C.SUPPORT_COL : "none",
    stroke: C.SUPPORT_COL, "stroke-width": sz * 0.18,
  }));
  if (!filled) {
    // roller circles just beyond the base
    const cx = px + ox * sz * 2.0, cy = py + oy * sz * 2.0;
    g.appendChild(_mkEl("circle", { cx, cy, r: sz * 0.25, fill: C.SUPPORT_COL }));
  }
}

function _drawEdgeLoads() {
  if (!poly.closed) return;
  const n = poly.verts.length;
  const arrowLen = poly.meshSize * 5;
  poly.edgeLoads.forEach(el => {
    if (el.e0 < 0 || el.e0 >= n) return;
    const v1 = poly.verts[el.e0], v2 = poly.verts[(el.e0 + 1) % n];
    const { nx, ny, tx, ty, L } = _edgeInwardNormal(el.e0);
    const sel = el.e0 === selEdge;
    const g = _mkEl("g", { opacity: sel ? 1 : 0.85 });
    g.appendChild(_mkEl("line", {
      x1: v1.x, y1: v1.y, x2: v2.x, y2: v2.y,
      stroke: C.LOAD_COL, "stroke-width": poly.meshSize * 0.5, opacity: 0.5,
    }));
    // arrow direction: combine normal (sign of pNormal, inward +) and tangential
    const sNorm = el.pNormal || 0, sTan = el.pTangential || 0;
    let dx = nx * sNorm + tx * sTan, dy = ny * sNorm + ty * sTan;
    const mag = Math.hypot(dx, dy);
    if (mag < 1e-12) { dx = nx; dy = ny; } else { dx /= mag; dy /= mag; }
    const count = Math.max(2, Math.min(10, Math.round(L / (poly.meshSize * 6))));
    for (let k = 0; k <= count; k++) {
      const f = k / count;
      const px = v1.x + (v2.x - v1.x) * f;
      const py = v1.y + (v2.y - v1.y) * f;
      // tail starts outside, head lands on the edge (pointing inward when pNormal>0)
      g.appendChild(_mkEl("line", {
        x1: px - dx * arrowLen, y1: py - dy * arrowLen, x2: px, y2: py,
        stroke: C.LOAD_COL, "stroke-width": poly.meshSize * 0.45,
        "marker-end": "url(#ed-arrow)",
      }));
    }
    worldG.appendChild(g);
  });
}

function _drawVertices() {
  const r = poly.meshSize * 1.1;
  poly.verts.forEach((v, i) => {
    const col = i === selIdx ? C.VERT_SEL : i === hoverIdx ? C.VERT_HOVER : C.VERT_IDLE;
    worldG.appendChild(_mkEl("circle", {
      cx: v.x, cy: v.y, r,
      fill: col, stroke: "#0d1929", "stroke-width": r * 0.3,
      "data-vidx": i, style: "cursor:grab",
    }));
    const lbl = _mkEl("text", {
      x: v.x + r * 1.6, y: -(v.y - r * 1.4),
      "font-size": poly.meshSize * 2.2,
      fill: C.TEXT, "pointer-events": "none",
      transform: "scale(1,-1)",
    });
    lbl.textContent = `V${i}`;
    worldG.appendChild(lbl);
  });
}

function _drawSupports() {
  const sz = poly.meshSize * 3.2;
  poly.supports.forEach(s => {
    if (s.vIdx < 0 || s.vIdx >= poly.verts.length) return;
    const {x, y} = poly.verts[s.vIdx];
    const g = _mkEl("g", {});
    if (s.type === "fixed") {
      g.appendChild(_mkEl("polygon", {
        points: `${x},${y} ${x-sz},${y-sz*1.55} ${x+sz},${y-sz*1.55}`,
        fill: C.SUPPORT_COL, "stroke-width": 0,
      }));
      g.appendChild(_mkEl("line", {
        x1: x-sz*1.2, y1: y-sz*1.75, x2: x+sz*1.2, y2: y-sz*1.75,
        stroke: C.SUPPORT_COL, "stroke-width": sz*0.28,
      }));
    } else if (s.type === "roller_x") {
      g.appendChild(_mkEl("polygon", {
        points: `${x},${y} ${x-sz},${y-sz*1.55} ${x+sz},${y-sz*1.55}`,
        fill: "none", stroke: C.SUPPORT_COL, "stroke-width": sz*0.28,
      }));
      for (let dx = -sz*0.6; dx <= sz*0.7; dx += sz*0.6)
        g.appendChild(_mkEl("circle", { cx: x+dx, cy: y-sz*2, r: sz*0.22, fill: C.SUPPORT_COL }));
    } else {
      g.appendChild(_mkEl("polygon", {
        points: `${x},${y} ${x-sz*1.55},${y-sz} ${x-sz*1.55},${y+sz}`,
        fill: "none", stroke: C.SUPPORT_COL, "stroke-width": sz*0.28,
      }));
      for (let dy = -sz*0.6; dy <= sz*0.7; dy += sz*0.6)
        g.appendChild(_mkEl("circle", { cx: x-sz*2, cy: y+dy, r: sz*0.22, fill: C.SUPPORT_COL }));
    }
    worldG.appendChild(g);
  });
}

function _drawLoads() {
  const arrowLen = poly.meshSize * 7;
  const hw = poly.meshSize * 1.4;
  poly.loads.forEach(l => {
    if (l.vIdx < 0 || l.vIdx >= poly.verts.length) return;
    const {x, y} = poly.verts[l.vIdx];
    const mag = Math.hypot(l.fx, l.fy) || 1;
    const dx = (l.fx / mag) * arrowLen;
    const dy = (l.fy / mag) * arrowLen;
    const g = _mkEl("g", {});
    g.appendChild(_mkEl("line", {
      x1: x-dx, y1: y-dy, x2: x, y2: y,
      stroke: C.LOAD_COL, "stroke-width": hw*0.5,
      "marker-end": "url(#ed-arrow)",
    }));
    worldG.appendChild(g);
  });
}

// ─── SVG event handlers ──────────────────────────────────────────────────────
function _onSvgClick(e) {
  if (dragState && dragState.moved) return;
  const m = _eventToModel(e);
  if (!m) return;

  if (activeTool === TOOL.VERTEX) {
    if (poly.closed) return;
    poly.verts.push({x: m.x, y: m.y});
    selIdx = poly.verts.length - 1;
    selEdge = -1;
    hoverEdge = -1;
    _fitView();
    _render();
    _updateStatus(_ct("st_open"));
    _updateInspector();

  } else if (activeTool === TOOL.SUPPORT) {
    const vi = _nearestVertIdx(m);
    if (vi < 0) return;
    poly.supports = poly.supports.filter(s => s.vIdx !== vi);
    poly.supports.push({vIdx: vi, type: activeSupportType});
    selIdx = vi; selEdge = -1;
    _render();
    _updateInspector();

  } else if (activeTool === TOOL.LOAD) {
    const vi = _nearestVertIdx(m);
    if (vi < 0) return;
    poly.loads = poly.loads.filter(l => l.vIdx !== vi);
    poly.loads.push(_defaultLoad(vi));
    selIdx = vi; selEdge = -1;
    _render();
    _updateInspector();

  } else if (activeTool === TOOL.EDGE) {
    if (!poly.closed || poly.verts.length < 2) return;
    const ei = _nearestEdgeIdx(m);
    if (ei < 0) return;
    const n = poly.verts.length;
    const v2i = (ei + 1) % n;
    if (poly.hydraulicFace && poly.hydraulicFace.v1Idx === ei && poly.hydraulicFace.v2Idx === v2i) {
      // Toggle off
      poly.hydraulicFace = null;
    } else {
      poly.hydraulicFace = {v1Idx: ei, v2Idx: v2i};
    }
    hoverEdge = -1;
    selEdge = -1;
    _render();
    _updateInspector();

  } else if (activeTool === TOOL.ESUPPORT) {
    if (!poly.closed || poly.verts.length < 2) return;
    const ei = _nearestEdgeIdx(m);
    if (ei < 0) return;
    const existing = poly.edgeSupports.find(es => es.e0 === ei);
    if (existing) {
      // toggle off if same type, else replace type
      if (existing.type === activeSupportType)
        poly.edgeSupports = poly.edgeSupports.filter(es => es.e0 !== ei);
      else
        existing.type = activeSupportType;
    } else {
      poly.edgeSupports.push({ e0: ei, type: activeSupportType });
    }
    selEdge = ei; selIdx = -1; hoverEdge = -1;
    _render();
    _updateInspector();

  } else if (activeTool === TOOL.ELOAD) {
    if (!poly.closed || poly.verts.length < 2) return;
    const ei = _nearestEdgeIdx(m);
    if (ei < 0) return;
    if (!poly.edgeLoads.find(el => el.e0 === ei)) {
      poly.edgeLoads.push({
        e0: ei, pNormal: 0.01, pTangential: 0.0,
        fnType: "expr", expr: "t", pointsText: "0, 0\n1, 1",
      });
    }
    selEdge = ei; selIdx = -1; hoverEdge = -1;
    _render();
    _updateInspector();

  } else if (activeTool === TOOL.DELETE) {
    const vi = _nearestVertIdx(m);
    if (vi >= 0) { _deleteVertex(vi); return; }
    // delete an edge support/load if clicking an edge with one
    if (poly.closed) {
      const ei = _nearestEdgeIdx(m);
      if (ei >= 0) {
        poly.edgeSupports = poly.edgeSupports.filter(es => es.e0 !== ei);
        poly.edgeLoads    = poly.edgeLoads.filter(el => el.e0 !== ei);
        if (selEdge === ei) selEdge = -1;
        _render();
        _updateInspector();
      }
    }
  }
}

function _onSvgDblClick(e) {
  if (activeTool !== TOOL.VERTEX || poly.closed || poly.verts.length < 3) return;
  poly.closed = true;
  _render();
  _updateStatus(_ct("st_closed"));
}

function _onSvgMouseDown(e) {
  if (activeTool !== TOOL.VERTEX) return;
  const m = _eventToModel(e);
  if (!m) return;
  const vi = _nearestVertIdx(m);
  if (vi >= 0) {
    dragState = {vIdx: vi, moved: false};
    e.preventDefault();
  }
}

function _onSvgMouseMove(e) {
  const m = _eventToModel(e);
  if (!m) return;

  const co = document.getElementById("ed-coords");
  if (co) co.textContent = _fmtCoord(m);

  if (dragState) {
    dragState.moved = true;
    poly.verts[dragState.vIdx] = {x: m.x, y: m.y};
    _fitView();
    _render();
    return;
  }

  if (EDGE_TOOLS.has(activeTool) && poly.closed) {
    const ei = _nearestEdgeIdx(m);
    if (ei !== hoverEdge) { hoverEdge = ei; _render(); }
    return;
  }

  const vi = _nearestVertIdx(m);
  if (vi !== hoverIdx) { hoverIdx = vi; _render(); }
}

function _onSvgMouseUp(e) {
  if (dragState) {
    if (dragState.moved) {
      selIdx = dragState.vIdx;
      _updateInspector();
    }
    dragState = null;
  }
}

function _onKeyDown(e) {
  // Keyboard shortcuts for tools
  const keyMap = {
    "v": "vertex", "V": "vertex",
    "f": "support-fixed", "F": "support-fixed",
    "x": "support-roller_x", "X": "support-roller_x",
    "y": "support-roller_y", "Y": "support-roller_y",
    "l": "load", "L": "load",
    "e": "edge", "E": "edge",
    "g": "esupport", "G": "esupport",
    "b": "eload", "B": "eload",
    "d": "delete", "D": "delete",
  };

  if (!e.ctrlKey && !e.metaKey && !e.altKey && document.activeElement.tagName !== "INPUT") {
    const mapped = keyMap[e.key];
    if (mapped) {
      const parts = mapped.split("-");
      activeTool = parts[0];
      if (parts[1]) activeSupportType = parts[1];
      document.querySelectorAll(".ed-tool").forEach(b => {
        const match = b.dataset.tool === activeTool &&
          (!b.dataset.stype || b.dataset.stype === activeSupportType);
        b.classList.toggle("active", match);
      });
      _updateCursor();
      e.preventDefault();
      return;
    }
  }

  if (e.key === "Delete" || e.key === "Backspace") {
    if (document.activeElement.tagName === "INPUT") return;
    if (selIdx >= 0 && selIdx < poly.verts.length) {
      _deleteVertex(selIdx);
    }
  }
  if (e.key === "Escape") {
    selIdx = -1;
    selEdge = -1;
    dragState = null;
    _render();
    _updateInspector();
  }
}

// ─── Property inspector ───────────────────────────────────────────────────────
function _updateInspector() {
  const el = document.getElementById("inspector-content");
  if (!el) return;

  if (selEdge >= 0 && selEdge < poly.verts.length) {
    _updateInspectorEdge(el);
    return;
  }

  if (selIdx < 0 || selIdx >= poly.verts.length) {
    el.innerHTML = `<p class="inspector-empty">${_ct("ins_none")}</p>`;
    return;
  }

  const v = poly.verts[selIdx];
  const support = poly.supports.find(s => s.vIdx === selIdx);
  const load    = poly.loads.find(l => l.vIdx === selIdx);

  const isFace = poly.hydraulicFace &&
    (poly.hydraulicFace.v1Idx === selIdx || poly.hydraulicFace.v2Idx === selIdx);

  let html = `<div style="font-size:12px;font-weight:600;color:var(--accent);margin-bottom:6px">
    ${_ct("ins_vertex")} V${selIdx}</div>`;
  html += `<div class="inspector-field">
    <label>${_ct("ins_x")}</label>
    <input type="number" value="${v.x.toFixed(1)}" onchange="updateVertCoord(${selIdx},'x',this.value)">
    <span style="font-size:11px;color:var(--muted)">mm</span>
  </div>`;
  html += `<div class="inspector-field">
    <label>${_ct("ins_y")}</label>
    <input type="number" value="${v.y.toFixed(1)}" onchange="updateVertCoord(${selIdx},'y',this.value)">
    <span style="font-size:11px;color:var(--muted)">mm</span>
  </div>`;

  if (support) {
    html += `<div style="margin-top:6px;font-size:11px;color:var(--support-col)">
      ${_ct("ins_type")}: ${support.type}</div>`;
  }

  // ── Nodal force load ──
  html += `<div style="margin-top:8px;font-size:11px;font-weight:600;color:var(--load-col)">
    ${_ct("ins_nload")}</div>`;
  if (load) {
    html += `<div class="field-row"><label>Fx</label>
      <input type="number" step="any" value="${load.fx}"
        onchange="updateNodalLoad(${selIdx},'fx',this.value)"></div>`;
    html += `<div class="field-row"><label>Fy</label>
      <input type="number" step="any" value="${load.fy}"
        onchange="updateNodalLoad(${selIdx},'fy',this.value)"></div>`;
    html += `<div class="field-row"><label>λ(t)</label>
      <select onchange="updateNodalLoad(${selIdx},'fnType',this.value)">
        <option value="expr"${load.fnType === "expr" ? " selected" : ""}>${_ct("ins_fn_expr")}</option>
        <option value="points"${load.fnType === "points" ? " selected" : ""}>${_ct("ins_fn_points")}</option>
      </select></div>`;
    if (load.fnType === "points") {
      html += `<textarea style="width:100%;height:70px;margin:2px 0;font-size:11px"
        placeholder="t, valor (uno por línea)"
        onchange="updateNodalLoad(${selIdx},'pointsText',this.value)">${load.pointsText || ""}</textarea>`;
    } else {
      html += `<input type="text" style="width:100%;margin:2px 0" value="${load.expr || ""}"
        placeholder="10*sin(2*pi*t)"
        onchange="updateNodalLoad(${selIdx},'expr',this.value)">`;
    }
    html += `<svg id="nload-preview" width="100%" height="50"
      style="background:var(--bg);border-radius:5px;margin-top:4px"></svg>`;
    html += `<button class="ghost sm" style="width:100%;margin:4px 0"
      onclick="removeNodalLoad(${selIdx})">${_ct("ins_remove")}</button>`;
  } else {
    html += `<button class="ghost sm" style="width:100%;margin:4px 0"
      onclick="addNodalLoad(${selIdx})">${_ct("ins_add_nload")}</button>`;
  }

  if (isFace) {
    html += `<div style="font-size:11px;color:var(--face-col)">${_ct("ins_face")}</div>`;
  }

  el.innerHTML = html;
  if (load) _renderMultPreview("nload-preview", load);
}

function _defaultLoad(vIdx) {
  return { vIdx, fx: 0, fy: -1, fnType: "expr", expr: "t", pointsText: "0, 0\n1, 1" };
}
function addNodalLoad(vIdx) {
  if (!poly.loads.find(l => l.vIdx === vIdx)) poly.loads.push(_defaultLoad(vIdx));
  _render(); _updateInspector();
}
function removeNodalLoad(vIdx) {
  poly.loads = poly.loads.filter(l => l.vIdx !== vIdx);
  _render(); _updateInspector();
}
function updateNodalLoad(vIdx, key, val) {
  const l = poly.loads.find(x => x.vIdx === vIdx);
  if (!l) return;
  if (key === "fx" || key === "fy") l[key] = parseFloat(val) || 0;
  else l[key] = val;
  _render();
  if (key === "fnType") _updateInspector();
  else if (l.fnType === "points" || key === "expr") _renderMultPreview("nload-preview", l);
}

function updateVertCoord(idx, coord, val) {
  if (idx < 0 || idx >= poly.verts.length) return;
  poly.verts[idx][coord] = parseFloat(val) || 0;
  _fitView();
  _render();
}

// ─── Edge inspector (edge supports + edge loads) ──────────────────────────────
function _updateInspectorEdge(el) {
  const n = poly.verts.length;
  const e0 = selEdge;
  const v1 = poly.verts[e0], v2 = poly.verts[(e0 + 1) % n];
  const len = Math.hypot(v2.x - v1.x, v2.y - v1.y);
  const es = poly.edgeSupports.find(s => s.e0 === e0);
  const elo = poly.edgeLoads.find(l => l.e0 === e0);

  let html = `<div style="font-size:12px;font-weight:600;color:var(--accent);margin-bottom:6px">
    ${_ct("ins_edge")} V${e0}–V${(e0 + 1) % n}</div>`;
  html += `<div style="font-size:11px;color:var(--muted);margin-bottom:6px">
    ${_ct("ins_len")}: ${(len / 1000).toFixed(2)} m</div>`;

  // ── Edge support ──
  html += `<div style="margin-top:4px;font-size:11px;font-weight:600;color:var(--support-col)">
    ${_ct("ins_esupport")}</div>`;
  if (es) {
    html += `<div class="field-row">
      <label>${_ct("ins_type")}</label>
      <select onchange="updateEdgeSupportType(${e0}, this.value)">
        <option value="fixed"${es.type === "fixed" ? " selected" : ""}>${_ct("tool_fixed")}</option>
        <option value="roller_x"${es.type === "roller_x" ? " selected" : ""}>${_ct("tool_rollerx")}</option>
        <option value="roller_y"${es.type === "roller_y" ? " selected" : ""}>${_ct("tool_rollery")}</option>
      </select></div>
      <button class="ghost sm" style="width:100%;margin:4px 0"
        onclick="removeEdgeSupport(${e0})">${_ct("ins_remove")}</button>`;
  } else {
    html += `<button class="ghost sm" style="width:100%;margin:4px 0"
      onclick="addEdgeSupport(${e0})">${_ct("ins_add_esupport")}</button>`;
  }

  // ── Edge load ──
  html += `<div style="margin-top:8px;font-size:11px;font-weight:600;color:var(--load-col)">
    ${_ct("ins_eload")}</div>`;
  if (elo) {
    html += `<div class="field-row"><label>${_ct("ins_pnormal")}</label>
      <input type="number" step="any" value="${elo.pNormal}"
        onchange="updateEdgeLoad(${e0},'pNormal',this.value)"></div>`;
    html += `<div class="field-row"><label>${_ct("ins_ptang")}</label>
      <input type="number" step="any" value="${elo.pTangential}"
        onchange="updateEdgeLoad(${e0},'pTangential',this.value)"></div>`;
    html += `<div class="field-row"><label>λ(t)</label>
      <select onchange="updateEdgeLoad(${e0},'fnType',this.value)">
        <option value="expr"${elo.fnType === "expr" ? " selected" : ""}>${_ct("ins_fn_expr")}</option>
        <option value="points"${elo.fnType === "points" ? " selected" : ""}>${_ct("ins_fn_points")}</option>
      </select></div>`;
    if (elo.fnType === "expr") {
      html += `<input type="text" style="width:100%;margin:2px 0" value="${elo.expr || ""}"
        placeholder="10*sin(2*pi*t)"
        onchange="updateEdgeLoad(${e0},'expr',this.value)">`;
    } else {
      html += `<textarea style="width:100%;height:70px;margin:2px 0;font-size:11px"
        placeholder="t, valor (uno por línea)"
        onchange="updateEdgeLoad(${e0},'pointsText',this.value)">${elo.pointsText || ""}</textarea>`;
    }
    html += `<svg id="eload-preview" width="100%" height="50"
      style="background:var(--bg);border-radius:5px;margin-top:4px"></svg>`;
    html += `<button class="ghost sm" style="width:100%;margin:4px 0"
      onclick="removeEdgeLoad(${e0})">${_ct("ins_remove")}</button>`;
  } else {
    html += `<button class="ghost sm" style="width:100%;margin:4px 0"
      onclick="addEdgeLoad(${e0})">${_ct("ins_add_eload")}</button>`;
  }

  el.innerHTML = html;
  if (elo) _renderMultPreview("eload-preview", elo);
}

function addEdgeSupport(e0) {
  if (!poly.edgeSupports.find(s => s.e0 === e0))
    poly.edgeSupports.push({ e0, type: "fixed" });
  _render(); _updateInspector();
}
function removeEdgeSupport(e0) {
  poly.edgeSupports = poly.edgeSupports.filter(s => s.e0 !== e0);
  _render(); _updateInspector();
}
function updateEdgeSupportType(e0, type) {
  const es = poly.edgeSupports.find(s => s.e0 === e0);
  if (es) es.type = type;
  _render(); _updateInspector();
}
function addEdgeLoad(e0) {
  if (!poly.edgeLoads.find(l => l.e0 === e0))
    poly.edgeLoads.push({ e0, pNormal: 0.01, pTangential: 0.0,
      fnType: "expr", expr: "t", pointsText: "0, 0\n1, 1" });
  _render(); _updateInspector();
}
function removeEdgeLoad(e0) {
  poly.edgeLoads = poly.edgeLoads.filter(l => l.e0 !== e0);
  _render(); _updateInspector();
}
function updateEdgeLoad(e0, key, val) {
  const elo = poly.edgeLoads.find(l => l.e0 === e0);
  if (!elo) return;
  if (key === "pNormal" || key === "pTangential") elo[key] = parseFloat(val) || 0;
  else elo[key] = val;
  _render();
  if (key === "fnType") _updateInspector();   // swap expr/points control
  else if (elo.fnType === "points" || key === "expr") _renderMultPreview("eload-preview", elo);
}

function _parsePoints(text) {
  return (text || "").split(/\n+/).map(line => {
    const m = line.trim().split(/[,\s]+/).map(Number);
    return (m.length >= 2 && m.every(x => !isNaN(x))) ? [m[0], m[1]] : null;
  }).filter(Boolean);
}

// Sample λ(t) over [tStart,tEnd] for a small preview curve.
function _renderMultPreview(svgId, elo) {
  const svg = document.getElementById(svgId);
  if (!svg) return;
  const W = svg.clientWidth || 220, H = 50, pad = 6;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const t0 = poly.tStart, t1 = poly.tEnd > poly.tStart ? poly.tEnd : poly.tStart + 1;
  const N = 60;
  let fn;
  if (elo.fnType === "points") {
    const pts = _parsePoints(elo.pointsText).sort((a, b) => a[0] - b[0]);
    fn = pts.length ? (t => {
      if (t <= pts[0][0]) return pts[0][1];
      if (t >= pts[pts.length - 1][0]) return pts[pts.length - 1][1];
      for (let i = 1; i < pts.length; i++)
        if (t <= pts[i][0]) {
          const [ta, va] = pts[i - 1], [tb, vb] = pts[i];
          return va + (vb - va) * (t - ta) / (tb - ta || 1);
        }
      return 0;
    }) : (() => 0);
  } else {
    fn = _safeExprFn(elo.expr);
  }
  const xs = [], ys = [];
  for (let i = 0; i <= N; i++) {
    const t = t0 + (t1 - t0) * i / N;
    let v = NaN; try { v = fn(t); } catch {}
    xs.push(t); ys.push(isFinite(v) ? v : 0);
  }
  const ymin = Math.min(0, ...ys), ymax = Math.max(0, ...ys), yr = ymax - ymin || 1;
  const toX = i => pad + (i / N) * (W - 2 * pad);
  const toY = v => H - pad - ((v - ymin) / yr) * (H - 2 * pad);
  const d = ys.map((v, i) => `${i ? "L" : "M"}${toX(i).toFixed(1)},${toY(v).toFixed(1)}`).join(" ");
  svg.innerHTML =
    `<line x1="${pad}" y1="${toY(0).toFixed(1)}" x2="${W - pad}" y2="${toY(0).toFixed(1)}"
       stroke="var(--border)" stroke-width="1"/>
     <path d="${d}" fill="none" stroke="var(--load-col)" stroke-width="1.5"/>`;
}

// Very small safe evaluator for the live preview (backend re-validates on run).
function _safeExprFn(expr) {
  const allowed = ["sin","cos","tan","asin","acos","atan","atan2","sinh","cosh",
    "tanh","exp","log","log10","sqrt","abs","min","max","pow","floor","ceil"];
  const env = { pi: Math.PI, e: Math.E, tau: 2 * Math.PI };
  allowed.forEach(k => { env[k] = Math[k] || (() => 0); });
  env.log10 = x => Math.log10(x);
  const names = (expr || "").match(/[a-zA-Z_]\w*/g) || [];
  for (const nm of names)
    if (nm !== "t" && !(nm in env)) return () => 0;   // unknown name → flat
  try {
    // eslint-disable-next-line no-new-func
    const f = new Function("t", "env", `with(env){return (${expr || 0});}`);
    return t => f(t, env);
  } catch { return () => 0; }
}

// ─── Load schedule panel ─────────────────────────────────────────────────────
function renderSchedulePanel() {
  const listEl = document.getElementById("schedule-list");
  if (!listEl) return;

  const history = edMode === "beam" ? beam.loadHistory : poly.loadHistory;
  const unit = edMode === "beam" ? "mm" : "mm H₂O";

  if (!history.length) {
    listEl.innerHTML = `<p class="inspector-empty" style="margin:4px 0">
      ${edMode === "beam"
        ? (lang === "es" ? "Un paso hasta el target predeterminado." : "Single step to default target.")
        : (lang === "es" ? "Un paso hasta el nivel predeterminado." : "Single step to default level.")
      }</p>`;
  } else {
    listEl.innerHTML = history.map((t, i) =>
      `<div class="schedule-item">
        <span class="seg-num">${i+1}</span>
        <input type="number" value="${t}" step="any"
               onchange="updateScheduleStep(${i}, this.value)">
        <span style="font-size:11px;color:var(--muted)">${unit}</span>
        <button class="btn-rm" onclick="removeScheduleStep(${i})">×</button>
      </div>`
    ).join("");
  }
  _renderSchedulePreview(history);
}

function addScheduleStep() {
  const history = edMode === "beam" ? beam.loadHistory : poly.loadHistory;
  const last = history.length ? history[history.length - 1] : (edMode === "beam" ? -0.20 : 120.0);
  history.push(last);
  renderSchedulePanel();
}

function removeScheduleStep(i) {
  const history = edMode === "beam" ? beam.loadHistory : poly.loadHistory;
  history.splice(i, 1);
  renderSchedulePanel();
}

function updateScheduleStep(i, val) {
  const history = edMode === "beam" ? beam.loadHistory : poly.loadHistory;
  history[i] = parseFloat(val) || 0;
  _renderSchedulePreview(history);
}

function _renderSchedulePreview(history) {
  const svg = document.getElementById("schedule-svg");
  if (!svg) return;
  const W = svg.clientWidth || 240, H = 60;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);

  if (!history.length) {
    svg.innerHTML = "";
    return;
  }

  const pts = [0, ...history];  // start at 0
  const yMin = Math.min(...pts), yMax = Math.max(...pts);
  const yRange = yMax - yMin || 1;
  const pad = 8;
  const n = pts.length;

  const toX = i => pad + (i / (n - 1)) * (W - 2*pad);
  const toY = v => H - pad - ((v - yMin) / yRange) * (H - 2*pad);

  const d = pts.map((v, i) => `${i === 0 ? "M" : "L"}${toX(i).toFixed(1)},${toY(v).toFixed(1)}`).join(" ");

  svg.innerHTML = `
    <line x1="${pad}" y1="0" x2="${pad}" y2="${H}" stroke="var(--border)" stroke-width="1"/>
    <line x1="0" y1="${toY(0).toFixed(1)}" x2="${W}" y2="${toY(0).toFixed(1)}" stroke="var(--border)" stroke-width="1"/>
    <path d="${d}" fill="none" stroke="var(--accent)" stroke-width="1.5"/>
    ${pts.map((v,i) => `<circle cx="${toX(i).toFixed(1)}" cy="${toY(v).toFixed(1)}" r="2.5" fill="var(--accent)"/>`).join("")}
  `;
}

// ─── Beam schematic ───────────────────────────────────────────────────────────
function renderBeamSchematic() {
  const svg = document.getElementById("bm-svg");
  if (!svg) return;
  const {L, H, notchW, notchH, span} = beam;
  const pad = 0.12 * Math.max(L, H);
  svg.setAttribute("viewBox", `${-pad} ${-pad} ${L + 2*pad} ${H + 2*pad}`);
  const sw = H * 0.023;
  let html = "";
  html += `<rect x="0" y="0" width="${L}" height="${H}"
    fill="#0f2820" stroke="#3b82f6" stroke-width="${sw}"/>`;
  const nx = (L - notchW) / 2;
  html += `<rect x="${nx}" y="${H - notchH}" width="${notchW}" height="${notchH}"
    fill="#0d1929" stroke="#3b82f6" stroke-width="${sw*0.6}"/>`;
  const sx = (L - span) / 2;
  const sz = H * 0.13;
  const tri = s => `0,0 ${-s},${s*1.55} ${s},${s*1.55}`;
  html += `<g transform="translate(${sx},${H})"><polygon points="${tri(sz)}" fill="#fbbf24"/></g>`;
  html += `<g transform="translate(${L-sx},${H})"><polygon points="${tri(sz)}" fill="none" stroke="#fbbf24" stroke-width="${sw}"/></g>`;
  const al = H * 0.4;
  html = `<defs><marker id="bm-arrow" markerWidth="6" markerHeight="6" refX="3" refY="3" orient="auto">
    <path d="M0,0 L6,3 L0,6 Z" fill="#f87171"/></marker></defs>` + html;
  html += `<line x1="${L/2}" y1="${-al}" x2="${L/2}" y2="0"
    stroke="#f87171" stroke-width="${sw*1.4}" marker-end="url(#bm-arrow)"/>`;
  html += `<text x="${L/2}" y="${H+sz*2.3}" text-anchor="middle"
    font-size="${H*0.16}" fill="#fbbf24">L=${L}mm</text>`;
  svg.innerHTML = html;
}

// ─── Config generation ────────────────────────────────────────────────────────
function editorExportConfig() {
  return edMode === "beam" ? _beamConfig() : _polyConfig();
}

function _polyConfig() {
  if (poly.verts.length < 3) {
    _updateStatus(lang === "es" ? "Necesitás al menos 3 vértices." : "Need at least 3 vertices.");
    return null;
  }
  const verts = poly.verts.map(v => [+v.x.toFixed(1), +v.y.toFixed(1)]);
  const ymax  = Math.max(...poly.verts.map(v => v.y));
  const n     = poly.verts.length;
  const edgeVerts = e0 => {
    const a = poly.verts[e0], b = poly.verts[(e0 + 1) % n];
    return [[+a.x.toFixed(1), +a.y.toFixed(1)], [+b.x.toFixed(1), +b.y.toFixed(1)]];
  };

  const mult = o => o.fnType === "points"
    ? { points: _parsePoints(o.pointsText) }
    : { expr: o.expr || "1" };

  // Loading mode priority: time_history (edge or nodal loads) > hydraulic > displacement.
  const hasTimeLoads = poly.edgeLoads.length > 0 || poly.loads.length > 0;
  const isHydraulic  = !hasTimeLoads && poly.hydraulicFace !== null;

  let loading;
  if (hasTimeLoads) {
    loading = {
      mode: "time_history",
      t_start: poly.tStart, t_end: poly.tEnd,
      dt_initial: poly.dt, dt_min: poly.dt * 0.05, dt_max: poly.dt * 2,
      max_accepted_steps: 600,
      self_weight: false, gamma_c: 2.40e-5,
      edge_loads: poly.edgeLoads.map(el => ({
        vertices: edgeVerts(el.e0),
        p_normal: el.pNormal, p_tangential: el.pTangential,
        multiplier: mult(el),
      })),
      point_loads: poly.loads
        .filter(l => poly.verts[l.vIdx])
        .map(l => ({
          x: +poly.verts[l.vIdx].x.toFixed(1),
          y: +poly.verts[l.vIdx].y.toFixed(1),
          fx: l.fx, fy: l.fy, multiplier: mult(l),
        })),
    };
  } else if (isHydraulic) {
    loading = {
      mode: "hydraulic",
      h_start: ymax * 0.80,
      h_target: ymax * 0.97,
      dh_initial: ymax * 0.004,
      dh_min: ymax * 0.0002,
      dh_max: ymax * 0.004,
      max_accepted_steps: 300,
    };
    const {v1Idx, v2Idx} = poly.hydraulicFace;
    const pf1 = poly.verts[v1Idx], pf2 = poly.verts[v2Idx];
    loading.face_vertices = [
      [+pf1.x.toFixed(1), +pf1.y.toFixed(1)],
      [+pf2.x.toFixed(1), +pf2.y.toFixed(1)],
    ];
    if (poly.loadHistory.length) loading.history = [...poly.loadHistory];
  } else {
    loading = {
      mode: "displacement",
      x_center: poly.verts.reduce((s,v) => s + v.x, 0) / poly.verts.length,
      y_top: ymax,
      patch: "three_nodes_centered",
      target: -0.20,
      step_initial: -0.001, step_min: -0.00001, step_max: -0.0015,
      grow_factor: 1.10, shrink_factor: 0.5, max_accepted_steps: 300,
    };
    if (poly.loadHistory.length) loading.history = [...poly.loadHistory];
  }

  // Vertex supports → real SupportCfg list (nearest-node); edge supports → edge_supports.
  const supports = poly.supports
    .filter(s => poly.verts[s.vIdx])
    .map(s => ({
      x: +poly.verts[s.vIdx].x.toFixed(1),
      y: +poly.verts[s.vIdx].y.toFixed(1),
      ..._supportFlags(s.type),
    }));
  const edge_supports = poly.edgeSupports
    .filter(es => es.e0 >= 0 && es.e0 < n)
    .map(es => ({ vertices: edgeVerts(es.e0), ..._supportFlags(es.type) }));

  const cfg = {
    name: "canvas_polygon",
    problem: {
      element_type: "t3",
      problem_type: poly.problemType,
      thickness: poly.thickness,
      strain_shear_factor: 0.5,
    },
    material: {
      E0: 22000.0, nu: 0.20,
      ft0: 2.10, fc0: 21.0, Gf0: 0.300, Gc0: 10.0,
      damage_max: 0.9995,
      enable_compression_damage: false,
      softening_law: "linear",
    },
    ras: { enabled: false, mode: "imposed", xi_imposed: 0.0 },
    geometry: {
      kind: "polygon",
      vertices: verts,
      mesh_size: poly.meshSize,
      height: ymax,
    },
    supports,
    edge_supports,
    loading,
    solver: {
      tangent_mode: "numerical_hybrid",
      max_iter: 60, tol_res_abs: 1.0e-4, tol_res_rel: 1.0e-5,
      use_line_search: true, backend: "auto",
    },
    output: { save_figures: true, save_tables: true },
  };
  return JSON.stringify(cfg, null, 2);
}

function _beamConfig() {
  const loading = {
    mode: "displacement",
    x_center: beam.L / 2, y_top: beam.H,
    patch: "three_nodes_centered",
    target: -0.20,
    step_initial: -0.001, step_min: -0.00001, step_max: -0.0015,
    grow_factor: 1.10, shrink_factor: 0.5, max_accepted_steps: 600,
  };
  if (beam.loadHistory.length) loading.history = [...beam.loadHistory];

  const cfg = {
    name: "canvas_beam",
    problem: {
      element_type: "q4",
      problem_type: "plane_stress",
      thickness: beam.thickness,
      strain_shear_factor: 1.0,
    },
    material: {
      E0: 38100.0, nu: 0.20,
      ft0: 4.0, fc0: 51.2, Gf0: 0.10, Gc0: 10.0,
      damage_max: 0.99999,
      enable_compression_damage: false,
      softening_law: "exponential",
    },
    ras: {
      enabled: false, mode: "larive", age_days: 300.0,
      tau_lat: 188.83, tau_ch: 161.89,
      eps_inf_vol: 0.0042, linear_divisor: 3.0,
      expansion_scale: 1.0, activity_power: 1.0,
      beta_E: 0.25, beta_ft: 0.45, beta_fc: 0.15, beta_Gf: 0.55,
    },
    geometry: {
      kind: "beam",
      L: beam.L, H: beam.H, nx: beam.nx, ny: beam.ny,
      notch_width: beam.notchW, notch_height: beam.notchH,
      support_span: beam.span,
    },
    loading,
    solver: {
      tangent_mode: "numerical_hybrid",
      max_iter: 60, tol_res_abs: 1.0e-4, tol_res_rel: 1.0e-5,
      use_line_search: true, backend: "auto",
    },
    output: { save_figures: true, save_tables: true },
  };
  return JSON.stringify(cfg, null, 2);
}

// ─── Helpers ─────────────────────────────────────────────────────────────────
function _eventToModel(e) {
  if (!worldG || !svgEl) return null;
  try {
    const pt = svgEl.createSVGPoint();
    pt.x = e.clientX; pt.y = e.clientY;
    const local = pt.matrixTransform(worldG.getScreenCTM().inverse());
    return {x: local.x, y: local.y};
  } catch { return null; }
}

function _nearestVertIdx(m) {
  let best = -1, bestD2 = Infinity;
  const thr = poly.meshSize * 5;
  poly.verts.forEach((v, i) => {
    const d2 = (v.x - m.x)**2 + (v.y - m.y)**2;
    if (d2 < thr**2 && d2 < bestD2) { bestD2 = d2; best = i; }
  });
  return best;
}

function _nearestEdgeIdx(m) {
  if (!poly.closed || poly.verts.length < 2) return -1;
  let best = -1, bestD = Infinity;
  const thr = poly.meshSize * 6;
  const n = poly.verts.length;
  for (let i = 0; i < n; i++) {
    const v1 = poly.verts[i], v2 = poly.verts[(i + 1) % n];
    const d = _distToSegment(m, v1, v2);
    if (d < thr && d < bestD) { bestD = d; best = i; }
  }
  return best;
}

function _distToSegment(p, a, b) {
  const dx = b.x - a.x, dy = b.y - a.y;
  const len2 = dx*dx + dy*dy;
  if (len2 < 1e-12) return Math.hypot(p.x - a.x, p.y - a.y);
  const t = Math.max(0, Math.min(1, ((p.x - a.x)*dx + (p.y - a.y)*dy) / len2));
  return Math.hypot(p.x - (a.x + t*dx), p.y - (a.y + t*dy));
}

function _deleteVertex(vi) {
  poly.verts.splice(vi, 1);
  poly.supports = poly.supports.filter(s => s.vIdx !== vi)
    .map(s => ({...s, vIdx: s.vIdx > vi ? s.vIdx - 1 : s.vIdx}));
  poly.loads = poly.loads.filter(l => l.vIdx !== vi)
    .map(l => ({...l, vIdx: l.vIdx > vi ? l.vIdx - 1 : l.vIdx}));
  if (poly.hydraulicFace) {
    const {v1Idx, v2Idx} = poly.hydraulicFace;
    if (v1Idx === vi || v2Idx === vi) {
      poly.hydraulicFace = null;
    } else {
      poly.hydraulicFace = {
        v1Idx: v1Idx > vi ? v1Idx - 1 : v1Idx,
        v2Idx: v2Idx > vi ? v2Idx - 1 : v2Idx,
      };
    }
  }
  // Edge supports / loads: drop those touching the deleted vertex, remap the rest.
  const remapEdge = arr => arr
    .filter(it => it.e0 !== vi && (it.e0 + 1) % (poly.verts.length + 1) !== vi)
    .map(it => ({ ...it, e0: it.e0 > vi ? it.e0 - 1 : it.e0 }));
  poly.edgeSupports = remapEdge(poly.edgeSupports);
  poly.edgeLoads    = remapEdge(poly.edgeLoads);
  if (poly.verts.length < 3) poly.closed = false;
  selIdx = -1;
  selEdge = -1;
  _fitView();
  _render();
  _updateInspector();
}

function _mkEl(tag, attrs) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, v));
  return el;
}

function _fmtCoord(m) {
  return `x=${(m.x/1000).toFixed(2)} m, y=${(m.y/1000).toFixed(2)} m`;
}

function _updateStatus(msg) {
  const el = document.getElementById("ed-status");
  if (el && msg !== null) el.textContent = msg;
}

function _updateCursor() {
  if (!svgEl) return;
  const map = {
    [TOOL.VERTEX]:   "crosshair",
    [TOOL.SUPPORT]:  "cell",
    [TOOL.LOAD]:     "cell",
    [TOOL.EDGE]:     "pointer",
    [TOOL.ESUPPORT]: "pointer",
    [TOOL.ELOAD]:    "pointer",
    [TOOL.DELETE]:   "no-drop",
  };
  svgEl.style.cursor = map[activeTool] || "default";
}
