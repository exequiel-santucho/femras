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
  PAN:      "pan",
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
  GRID:        "#4a6a8a",
  TEXT:        "#7a9ab8",
};

// ─── Pixel-size constants (target screen px for each visual element) ──────────
const PX = {
  nodeR:        5,    // vertex circle radius
  nodeStroke:   1.5,
  nodeLabelPx:  11,
  supportSz:    18,   // support triangle size
  edgeSuppSz:   14,
  loadArrow:    44,   // nodal load arrow length
  loadStroke:   2.5,
  edgeLoadArrow: 34,
  edgeLoadStroke: 1.5,
  polyStroke:   2,
  faceStroke:   4,
  hoverStroke:  3,
  edgeAccentStroke: 1,
  gridStroke:   1.0,
};

// ─── State ───────────────────────────────────────────────────────────────────
let edMode = "poly";
let activeTool = TOOL.VERTEX;
let activeSupportType = "fixed";

const _defaultPolyMaterial = () => ({
  E0: 22000.0, nu: 0.20, ft0: 2.10, fc0: 21.0, Gf0: 0.300, Gc0: 10.0,
  damage_max: 0.9995, enable_compression_damage: false, softening_law: "linear",
});
const _defaultPolyRas = () => ({
  enabled: false, mode: "imposed", xi_imposed: 0.0,
  age_days: 300.0, eps_inf_vol: 0.0042,
});
const _defaultBeamMaterial = () => ({
  E0: 38100.0, nu: 0.20, ft0: 4.0, fc0: 51.2, Gf0: 0.10, Gc0: 10.0,
  damage_max: 0.99999, enable_compression_damage: false, softening_law: "exponential",
});
const _defaultBeamRas = () => ({
  enabled: false, mode: "larive", age_days: 300.0, xi_imposed: 0.0,
  tau_lat: 188.83, tau_ch: 161.89, eps_inf_vol: 0.0042, linear_divisor: 3.0,
  expansion_scale: 1.0, activity_power: 1.0,
  beta_E: 0.25, beta_ft: 0.45, beta_fc: 0.15, beta_Gf: 0.55,
});

const poly = {
  name:          "modelo",
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
  material:      _defaultPolyMaterial(),
  ras:           _defaultPolyRas(),
};

const beam = {
  L: 430, H: 105, nx: 86, ny: 21,
  notchW: 3, notchH: 52.5, span: 400, thickness: 75,
  loadHistory: [],
  material: _defaultBeamMaterial(),
  ras:      _defaultBeamRas(),
};

// SVG interaction
let svgEl     = null;
let worldG    = null;
let hoverIdx  = -1;
let selIdx    = -1;
let selEdge   = -1;  // selected edge (start-vertex idx) for the inspector
let hoverEdge = -1;  // index into verts[] of the start vertex of hovered edge
let dragState = null;

// Pan state (middle mouse or PAN tool drag)
let panState = null; // { cx, cy, vbx, vby, vbw, vbh }

// Grid & snap
let snapGrid       = false;
let gridStepX      = 1000;   // mm (default 1 m); null = auto
let gridStepY      = null;   // null = same as gridStepX
let snapPreviewPos = null;   // {x, y} mm — snapped cursor, for crosshair

// Tools that operate on whole edges (drive edge hover + edge picking).
const EDGE_TOOLS = new Set([TOOL.EDGE, TOOL.ESUPPORT, TOOL.ELOAD]);

function _supportFlags(type) {
  if (type === "roller_x") return { fix_x: false, fix_y: true };   // free in X
  if (type === "roller_y") return { fix_x: true,  fix_y: false };  // free in Y
  return { fix_x: true, fix_y: true };                             // fixed
}

// ─── i18n helper ─────────────────────────────────────────────────────────────
// _ct() is defined in app.js; it returns I18N[lang].canvas[key]

// ─── World-to-pixel scale factor ─────────────────────────────────────────────
function _worldPerPx() {
  if (!svgEl) return 1;
  const vb = svgEl.viewBox.baseVal;
  const w = svgEl.clientWidth || 1;
  const h = svgEl.clientHeight || 1;
  if (!vb || vb.width === 0 || vb.height === 0) return 1;
  return Math.max(vb.width / w, vb.height / h);
}

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
      _showEntryBar(activeTool === TOOL.VERTEX && edMode === "poly");
      snapPreviewPos = null;
      // Auto-close when switching to an edge tool (EDGE/ESUPPORT/ELOAD/ESUPPORT)
      if (EDGE_TOOLS.has(activeTool) && !poly.closed && poly.verts.length >= 3) {
        poly.closed = true;
        _render();
        _updateStatus(_ct("st_closed"));
      }
    });
  });

  // Polygon parameter inputs
  const nameEl = document.getElementById("ed-casename");
  if (nameEl) nameEl.addEventListener("input", () => { poly.name = nameEl.value || "modelo"; });
  _bindInput("ed-meshsize",  v => { poly.meshSize  = (v || 2) * 1000; _render(); });
  _bindInput("ed-thickness", v => { poly.thickness = (v || 1) * 1000; });
  _bindInput("ed-tstart",    v => { poly.tStart = isNaN(v) ? 0 : v; });
  _bindInput("ed-tend",      v => { poly.tEnd   = isNaN(v) ? 1 : v; });
  _bindInput("ed-dt",        v => { poly.dt     = v || 0.05; });
  const ptEl = document.getElementById("ed-probtype");
  if (ptEl) ptEl.addEventListener("change", () => { poly.problemType = ptEl.value; });

  // Zoom extents button
  const fitBtn = document.getElementById("btn-fit-view");
  if (fitBtn) fitBtn.addEventListener("click", () => { _fitView(); _render(); });

  // Snap & grid
  const snapChk = document.getElementById("snap-chk");
  if (snapChk) snapChk.addEventListener("change", () => {
    snapGrid = snapChk.checked;
    _render();
  });
  const gsxEl = document.getElementById("ed-gridstep-x");
  if (gsxEl) gsxEl.addEventListener("change", () => {
    const v = parseFloat(gsxEl.value);
    gridStepX = (!isNaN(v) && v > 0) ? v * 1000 : null;
    _render();
  });
  const gsyEl = document.getElementById("ed-gridstep-y");
  if (gsyEl) gsyEl.addEventListener("change", () => {
    const v = parseFloat(gsyEl.value);
    gridStepY = (!isNaN(v) && v > 0) ? v * 1000 : null;
    _render();
  });

  // Vertex coordinate entry bar
  const addBtn = document.getElementById("entry-add-btn");
  if (addBtn) addBtn.addEventListener("click", () => _addVertexFromEntry());
  ["entry-x", "entry-y"].forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener("keydown", e => {
      if (e.key === "Enter") { e.preventDefault(); _addVertexFromEntry(); }
      if (e.key === "Escape") { el.blur(); }
    });
    // Tab from X → Y → add
    if (id === "entry-y") {
      el.addEventListener("keydown", e => {
        if (e.key === "Tab" && !e.shiftKey) { e.preventDefault(); _addVertexFromEntry(); }
      });
    }
  });

  // Material & RAS inputs (polygon defaults)
  _bindInput("mat-E0",  v => { poly.material.E0  = v || 22000; });
  _bindInput("mat-nu",  v => { poly.material.nu  = isNaN(v) ? 0.20 : v; });
  _bindInput("mat-ft0", v => { poly.material.ft0 = v || 2.10; });
  _bindInput("mat-fc0", v => { poly.material.fc0 = v || 21.0; });
  _bindInput("mat-Gf0", v => { poly.material.Gf0 = v || 0.300; });
  const slEl = document.getElementById("mat-softlaw");
  if (slEl) slEl.addEventListener("change", () => { poly.material.softening_law = slEl.value; });

  const rasChk = document.getElementById("ras-enabled");
  if (rasChk) rasChk.addEventListener("change", () => {
    poly.ras.enabled = rasChk.checked;
    const p = document.getElementById("ras-params");
    if (p) p.style.display = rasChk.checked ? "" : "none";
  });
  const rasModeEl = document.getElementById("ras-mode");
  if (rasModeEl) rasModeEl.addEventListener("change", () => {
    poly.ras.mode = rasModeEl.value;
    const ir = document.getElementById("ras-imposed-row");
    const lr = document.getElementById("ras-larive-row");
    if (ir) ir.style.display = rasModeEl.value === "imposed" ? "" : "none";
    if (lr) lr.style.display = rasModeEl.value === "larive"  ? "" : "none";
  });
  _bindInput("ras-xi",     v => { poly.ras.xi_imposed = isNaN(v) ? 0 : v; });
  _bindInput("ras-age",    v => { poly.ras.age_days   = v || 300; });
  _bindInput("ras-epsinf", v => { poly.ras.eps_inf_vol = isNaN(v) ? 0.0042 : v; });

  // Beam form
  ["L","H","nx","ny","notchW","notchH","span","thickness"].forEach(k => {
    const el = document.getElementById(`bm-${k}`);
    if (el) el.addEventListener("input", () => {
      beam[k] = parseFloat(el.value) || beam[k];
      renderBeamSchematic();
    });
  });

  // SVG events
  svgEl.addEventListener("click",       _onSvgClick);
  svgEl.addEventListener("dblclick",    _onSvgDblClick);
  svgEl.addEventListener("mousemove",   _onSvgMouseMove);
  svgEl.addEventListener("mousedown",   _onSvgMouseDown);
  svgEl.addEventListener("mouseup",     _onSvgMouseUp);
  svgEl.addEventListener("wheel",       _onSvgWheel, { passive: false });
  svgEl.addEventListener("contextmenu", e => e.preventDefault());

  // Keyboard shortcuts
  document.addEventListener("keydown", _onKeyDown);

  // Language change
  document.addEventListener("langchange", () => {
    _updateStatus(null);  // refresh with current content
    renderSchedulePanel();
  });

  // Start with empty canvas, poly mode
  edMode = "poly";
  _showMode("poly");
  _syncPolyForm();
  _fitView();
  _render();
  _updateStatus(_ct("st_no_verts"));
  renderSchedulePanel();
}

// ─── New / clear model ────────────────────────────────────────────────────────
function editorNewModel() {
  edMode = "poly";
  poly.verts         = [];
  poly.closed        = false;
  poly.supports      = [];
  poly.loads         = [];
  poly.hydraulicFace = null;
  poly.edgeSupports  = [];
  poly.edgeLoads     = [];
  poly.loadHistory   = [];
  poly.tStart        = 0.0;
  poly.tEnd          = 1.0;
  poly.dt            = 0.05;
  poly.material      = _defaultPolyMaterial();
  poly.ras           = _defaultPolyRas();
  _showMode("poly");
  _syncPolyForm();
  _syncMaterialForm();
  if (worldG) worldG.innerHTML = "";
  selIdx = -1; selEdge = -1; hoverIdx = -1; hoverEdge = -1;
  _updateInspector();
  renderSchedulePanel();
  _updateStatus(_ct("st_no_verts"));
  // Hide stale canvas results
  const rp = document.getElementById("sec-canvas-results");
  if (rp) rp.style.display = "none";
}

function _bindInput(id, fn) {
  const el = document.getElementById(id);
  if (el) el.addEventListener("change", () => fn(parseFloat(el.value)));
}

// ─── Templates ───────────────────────────────────────────────────────────────
function editorLoadTemplate(name) {
  if (name === "beam") {
    edMode = "beam";
    beam.material = _defaultBeamMaterial();
    beam.ras      = _defaultBeamRas();
    _showMode("beam");
    _syncBeamForm();
    _syncMaterialForm();
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
    poly.meshSize      = 2000;   // mm
    poly.thickness     = 1000;   // mm
    poly.problemType   = "plane_strain";
    poly.loadHistory   = [];
    poly.tStart        = 0.0;
    poly.tEnd          = 1.0;
    poly.dt            = 0.05;
    poly.material = _defaultPolyMaterial();
    poly.ras      = { enabled: true, mode: "imposed", xi_imposed: 0.70,
                      age_days: 300.0, eps_inf_vol: 0.00289 };
    _showMode("poly");
    _syncPolyForm();
    _fitView();
    _render();
    renderSchedulePanel();
    _updateStatus(_ct("st_template"));
    // Hide stale canvas results from previous run
    const rp = document.getElementById("sec-canvas-results");
    if (rp) rp.style.display = "none";
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
  if (msEl)  msEl.value  = (poly.meshSize  / 1000).toFixed(3);
  if (thEl)  thEl.value  = (poly.thickness / 1000).toFixed(3);
  if (ptEl)  ptEl.value  = poly.problemType;
  const ts = document.getElementById("ed-tstart");
  const te = document.getElementById("ed-tend");
  const dt = document.getElementById("ed-dt");
  if (ts) ts.value = poly.tStart;
  if (te) te.value = poly.tEnd;
  if (dt) dt.value = poly.dt;
  _syncMaterialForm();
}

function _syncMaterialForm() {
  const m = edMode === "beam" ? beam.material : poly.material;
  const r = edMode === "beam" ? beam.ras      : poly.ras;
  _setVal("mat-E0",  m.E0);
  _setVal("mat-nu",  m.nu);
  _setVal("mat-ft0", m.ft0);
  _setVal("mat-fc0", m.fc0);
  _setVal("mat-Gf0", m.Gf0);
  const sl = document.getElementById("mat-softlaw");
  if (sl) sl.value = m.softening_law;
  const chk = document.getElementById("ras-enabled");
  if (chk) { chk.checked = r.enabled; }
  const rp = document.getElementById("ras-params");
  if (rp) rp.style.display = r.enabled ? "" : "none";
  const rm = document.getElementById("ras-mode");
  if (rm) rm.value = r.mode;
  const ir = document.getElementById("ras-imposed-row");
  const lr = document.getElementById("ras-larive-row");
  if (ir) ir.style.display = r.mode === "imposed" ? "" : "none";
  if (lr) lr.style.display = r.mode === "larive"  ? "" : "none";
  _setVal("ras-xi",     r.xi_imposed);
  _setVal("ras-age",    r.age_days);
  _setVal("ras-epsinf", r.eps_inf_vol);
}

function _setVal(id, val) {
  const el = document.getElementById(id);
  if (el) el.value = val;
}

function _syncBeamForm() {
  ["L","H","nx","ny","notchW","notchH","span","thickness"].forEach(k => {
    const el = document.getElementById(`bm-${k}`);
    if (el) el.value = beam[k];
  });
}

// ─── ViewBox ─────────────────────────────────────────────────────────────────
function _fitView() {
  if (!svgEl) return;
  if (!poly.verts.length) {
    // Default viewBox for empty canvas (10m × 10m in mm)
    svgEl.setAttribute("viewBox", "-1000 -11000 12000 12000");
    return;
  }
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
  if (!poly.verts.length) {
    _drawGridEmpty();
    _drawSnapIndicator();
    return;
  }
  _drawGrid();
  _drawPolygon();
  _drawHydraulicFace();
  _drawEdgeHover();
  _drawEdgeSupports();
  _drawEdgeLoads();
  _drawSupports();
  _drawLoads();
  _drawVertices();
  _drawSnapIndicator();
}

function _drawSnapIndicator() {
  if (!snapPreviewPos) return;
  const wpp = _worldPerPx();
  const { x, y } = snapPreviewPos;
  const arm = 7 * wpp;
  const sw  = 1.2 * wpp;
  const g = _mkEl("g", { opacity: 0.9 });
  g.appendChild(_mkEl("line", { x1: x - arm, y1: y, x2: x + arm, y2: y,
    stroke: "#fbbf24", "stroke-width": sw }));
  g.appendChild(_mkEl("line", { x1: x, y1: y - arm, x2: x, y2: y + arm,
    stroke: "#fbbf24", "stroke-width": sw }));
  g.appendChild(_mkEl("circle", { cx: x, cy: y, r: 2.5 * wpp,
    fill: "none", stroke: "#fbbf24", "stroke-width": sw }));
  worldG.appendChild(g);
}

function _gridBounds() {
  // Cover the full SVG element area in worldG coords, accounting for
  // preserveAspectRatio="xMidYMid meet" letterboxing margins.
  const vb = svgEl && svgEl.viewBox.baseVal;
  if (!vb || !vb.width || !vb.height)
    return { xmin: -1000, xmax: 11000, ymin: -1000, ymax: 11000 };

  const cw = svgEl.clientWidth  || svgEl.getBoundingClientRect().width;
  const ch = svgEl.clientHeight || svgEl.getBoundingClientRect().height;

  if (!cw || !ch) {
    // Fallback: just the viewBox area
    return { xmin: vb.x, xmax: vb.x + vb.width,
             ymin: -(vb.y + vb.height), ymax: -vb.y };
  }

  // "meet" scales uniformly so the viewBox fits inside the element, centered.
  const scale  = Math.min(cw / vb.width, ch / vb.height);
  const offX   = (cw - vb.width  * scale) / 2; // letterbox px on left/right
  const offY   = (ch - vb.height * scale) / 2; // letterbox px on top/bottom
  const pxToVb = 1 / scale;                     // screen px → viewBox units

  // SVG coordinate corners of the full SVG element (including letterbox)
  const svgXmin = vb.x - offX * pxToVb;
  const svgXmax = vb.x + vb.width  + offX * pxToVb;
  const svgYmin = vb.y - offY * pxToVb;
  const svgYmax = vb.y + vb.height + offY * pxToVb;

  // worldG_y = -svg_y  (worldG has scale(1,-1))
  return { xmin: svgXmin, xmax: svgXmax,
           ymin: -svgYmax, ymax: -svgYmin };
}

function _drawGridLines(xmin, xmax, ymin, ymax, opacity) {
  const wpp = _worldPerPx();
  const stepX = _currentGridStepX(), stepY = _currentGridStepY();
  const sw  = PX.gridStroke * wpp;
  const g   = _mkEl("g", { opacity });
  for (let x = Math.ceil(xmin / stepX) * stepX; x <= xmax + stepX * 0.01; x += stepX)
    g.appendChild(_mkEl("line", {x1:x, y1:ymin, x2:x, y2:ymax, stroke:C.GRID, "stroke-width":sw}));
  for (let y = Math.ceil(ymin / stepY) * stepY; y <= ymax + stepY * 0.01; y += stepY)
    g.appendChild(_mkEl("line", {x1:xmin, y1:y, x2:xmax, y2:y, stroke:C.GRID, "stroke-width":sw}));
  return g;
}

function _drawGridDots(xmin, xmax, ymin, ymax, opacity) {
  const wpp   = _worldPerPx();
  const stepX = _currentGridStepX(), stepY = _currentGridStepY();
  const dotR  = 1.8 * wpp;
  const g     = _mkEl("g", { opacity });
  for (let x = Math.ceil(xmin / stepX) * stepX; x <= xmax + stepX * 0.01; x += stepX)
    for (let y = Math.ceil(ymin / stepY) * stepY; y <= ymax + stepY * 0.01; y += stepY)
      g.appendChild(_mkEl("circle", { cx: x, cy: y, r: dotR, fill: C.GRID }));
  return g;
}

function _drawGridLabel(stepX, stepY) {
  const wpp = _worldPerPx();
  const vb  = svgEl.viewBox.baseVal;
  if (!vb || !vb.width) return;
  const xm = stepX / 1000, ym = stepY / 1000;
  const fmt = v => v < 1 ? `${(v*100).toFixed(0)} cm` : `${v.toFixed(v < 10 ? 1 : 0)} m`;
  const same = (Math.abs(stepX - stepY) < 0.01 * stepX);
  const txt  = same ? `grid: ${fmt(xm)}` : `grid X:${fmt(xm)} Y:${fmt(ym)}`;
  // Place label at bottom-left of worldG visible area
  const label = _mkEl("text", {
    x: vb.x + 6 * wpp,
    y: -(vb.y + vb.height - 8 * wpp),
    "font-size": 9 * wpp,
    fill: "rgba(255,255,255,0.28)",
    "pointer-events": "none",
    transform: "scale(1,-1)",
  });
  label.textContent = txt;
  worldG.appendChild(label);
}

function _drawGridEmpty() {
  const b = _gridBounds();
  worldG.appendChild(_drawGridLines(b.xmin, b.xmax, b.ymin, b.ymax, snapGrid ? 0.55 : 0.35));
  if (snapGrid) worldG.appendChild(_drawGridDots(b.xmin, b.xmax, b.ymin, b.ymax, 0.75));
  _drawGridLabel(_currentGridStepX(), _currentGridStepY());
}

function _drawGrid() {
  const b = _gridBounds();
  worldG.appendChild(_drawGridLines(b.xmin, b.xmax, b.ymin, b.ymax, snapGrid ? 0.55 : 0.35));
  if (snapGrid) worldG.appendChild(_drawGridDots(b.xmin, b.xmax, b.ymin, b.ymax, 0.75));
  _drawGridLabel(_currentGridStepX(), _currentGridStepY());
}

function _drawPolygon() {
  const verts = poly.verts;
  if (verts.length < 2) return;
  const pts = verts.map(v => `${v.x},${v.y}`).join(" ");
  const sw = PX.polyStroke * _worldPerPx();
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
  const wpp = _worldPerPx();
  const sw = PX.faceStroke * wpp;
  worldG.appendChild(_mkEl("line", {
    x1: v1.x, y1: v1.y, x2: v2.x, y2: v2.y,
    stroke: C.EDGE_FACE, "stroke-width": sw,
    "stroke-linecap": "round", opacity: 0.85,
  }));
  const mx = (v1.x + v2.x) / 2, my = (v1.y + v2.y) / 2;
  const offset = 14 * wpp;
  const fs = 16 * wpp;
  const tx = _mkEl("text", {
    x: mx + offset, y: -(my - offset),
    "font-size": fs, fill: C.EDGE_FACE,
    "pointer-events": "none", transform: "scale(1,-1)",
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
    stroke: col, "stroke-width": PX.hoverStroke * _worldPerPx(),
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
  const wpp = _worldPerPx();
  const sz = PX.edgeSuppSz * wpp;
  poly.edgeSupports.forEach(es => {
    if (es.e0 < 0 || es.e0 >= n) return;
    const v1 = poly.verts[es.e0], v2 = poly.verts[(es.e0 + 1) % n];
    const { nx, ny, L } = _edgeInwardNormal(es.e0);
    const ox = -nx, oy = -ny;
    const count = Math.max(2, Math.min(12, Math.round(L / (sz * 6))));
    const sel = es.e0 === selEdge;
    const g = _mkEl("g", { opacity: sel ? 1 : 0.9 });
    g.appendChild(_mkEl("line", {
      x1: v1.x, y1: v1.y, x2: v2.x, y2: v2.y,
      stroke: C.SUPPORT_COL, "stroke-width": PX.edgeAccentStroke * wpp, opacity: 0.5,
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
  const ex = -oy, ey = ox;
  const b1 = { x: px + ox * sz * 1.55 + ex * sz, y: py + oy * sz * 1.55 + ey * sz };
  const b2 = { x: px + ox * sz * 1.55 - ex * sz, y: py + oy * sz * 1.55 - ey * sz };
  const filled = type === "fixed";
  g.appendChild(_mkEl("polygon", {
    points: `${px},${py} ${b1.x},${b1.y} ${b2.x},${b2.y}`,
    fill: filled ? C.SUPPORT_COL : "none",
    stroke: C.SUPPORT_COL, "stroke-width": sz * 0.2,
  }));
  if (!filled) {
    const cx = px + ox * sz * 2.0, cy = py + oy * sz * 2.0;
    g.appendChild(_mkEl("circle", { cx, cy, r: sz * 0.28, fill: C.SUPPORT_COL }));
  }
}

function _drawArrow(g, x1, y1, x2, y2, dx, dy, sw, headLen, headW, col) {
  // Line shaft (shortened so the head doesn't overlap)
  g.appendChild(_mkEl("line", {
    x1, y1, x2: x2 - dx * headLen * 0.8, y2: y2 - dy * headLen * 0.8,
    stroke: col, "stroke-width": sw, "stroke-linecap": "round",
  }));
  // Arrowhead triangle drawn explicitly (no SVG markers → works in scale(1,-1) groups)
  const bx = x2 - dx * headLen, by = y2 - dy * headLen;
  const px = -dy * headW / 2,   py = dx  * headW / 2;
  const pts = `${x2},${y2} ${bx+px},${by+py} ${bx-px},${by-py}`;
  g.appendChild(_mkEl("polygon", { points: pts, fill: col, stroke: "none" }));
}

function _drawEdgeLoads() {
  if (!poly.closed) return;
  const n = poly.verts.length;
  const wpp = _worldPerPx();
  const arrowLen = PX.edgeLoadArrow * wpp;
  const headLen  = arrowLen * 0.28;
  const headW    = arrowLen * 0.22;
  const sw = PX.edgeLoadStroke * wpp;
  const accentSw = PX.edgeAccentStroke * wpp;
  poly.edgeLoads.forEach(eld => {
    if (eld.e0 < 0 || eld.e0 >= n) return;
    const v1 = poly.verts[eld.e0], v2 = poly.verts[(eld.e0 + 1) % n];
    const { nx, ny, tx, ty, L } = _edgeInwardNormal(eld.e0);
    const sel = eld.e0 === selEdge;
    const g = _mkEl("g", { opacity: sel ? 1 : 0.85 });
    // Edge accent line
    g.appendChild(_mkEl("line", {
      x1: v1.x, y1: v1.y, x2: v2.x, y2: v2.y,
      stroke: C.LOAD_COL, "stroke-width": accentSw, opacity: 0.5,
    }));
    const sNorm = eld.pNormal || 0, sTan = eld.pTangential || 0;
    let dx = nx * sNorm + tx * sTan, dy = ny * sNorm + ty * sTan;
    const mag = Math.hypot(dx, dy);
    if (mag < 1e-12) { dx = nx; dy = ny; } else { dx /= mag; dy /= mag; }
    const count = Math.max(2, Math.min(10, Math.round(L / (arrowLen * 1.5))));
    for (let k = 0; k <= count; k++) {
      const f = k / count;
      const px = v1.x + (v2.x - v1.x) * f;
      const py = v1.y + (v2.y - v1.y) * f;
      _drawArrow(g, px - dx * arrowLen, py - dy * arrowLen, px, py,
                 dx, dy, sw, headLen, headW, C.LOAD_COL);
    }
    worldG.appendChild(g);
  });
}

function _drawVertices() {
  const wpp = _worldPerPx();
  const r   = PX.nodeR      * wpp;
  const sw  = PX.nodeStroke * wpp;
  const fs  = PX.nodeLabelPx * wpp;
  // V0 "close" hint: hover near first vertex while drawing (≥3 verts)
  const canClose = activeTool === TOOL.VERTEX && !poly.closed && poly.verts.length >= 3
                   && hoverIdx === 0;
  poly.verts.forEach((v, i) => {
    const closing = canClose && i === 0;
    const col = closing        ? "#34d399"   // green = click here to close
              : i === selIdx   ? C.VERT_SEL
              : i === hoverIdx ? C.VERT_HOVER
              :                  C.VERT_IDLE;
    worldG.appendChild(_mkEl("circle", {
      cx: v.x, cy: v.y, r,
      fill: col, stroke: "#0d1929", "stroke-width": sw,
      "data-vidx": i, style: "cursor:grab",
    }));
    // Extra ring when hovering V0 to signal "click to close"
    if (closing) {
      worldG.appendChild(_mkEl("circle", {
        cx: v.x, cy: v.y, r: r * 2.2,
        fill: "none", stroke: "#34d399", "stroke-width": sw * 0.8, opacity: 0.6,
        "pointer-events": "none",
      }));
    }
    const lbl = _mkEl("text", {
      x: v.x + r * 1.8, y: -(v.y - r * 1.5),
      "font-size": fs, fill: C.TEXT,
      "pointer-events": "none", transform: "scale(1,-1)",
    });
    lbl.textContent = `V${i}`;
    worldG.appendChild(lbl);
  });
}

function _drawSupports() {
  const wpp = _worldPerPx();
  const sz  = PX.supportSz * wpp;
  const sw  = sz * 0.22;
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
        stroke: C.SUPPORT_COL, "stroke-width": sw,
      }));
    } else if (s.type === "roller_x") {
      g.appendChild(_mkEl("polygon", {
        points: `${x},${y} ${x-sz},${y-sz*1.55} ${x+sz},${y-sz*1.55}`,
        fill: "none", stroke: C.SUPPORT_COL, "stroke-width": sw,
      }));
      for (let ddx = -sz*0.6; ddx <= sz*0.7; ddx += sz*0.6)
        g.appendChild(_mkEl("circle", { cx: x+ddx, cy: y-sz*2, r: sz*0.22, fill: C.SUPPORT_COL }));
    } else {
      g.appendChild(_mkEl("polygon", {
        points: `${x},${y} ${x-sz*1.55},${y-sz} ${x-sz*1.55},${y+sz}`,
        fill: "none", stroke: C.SUPPORT_COL, "stroke-width": sw,
      }));
      for (let ddy = -sz*0.6; ddy <= sz*0.7; ddy += sz*0.6)
        g.appendChild(_mkEl("circle", { cx: x-sz*2, cy: y+ddy, r: sz*0.22, fill: C.SUPPORT_COL }));
    }
    worldG.appendChild(g);
  });
}

function _drawLoads() {
  const wpp = _worldPerPx();
  const arrowLen = PX.loadArrow  * wpp;
  const headLen  = arrowLen * 0.28;
  const headW    = arrowLen * 0.22;
  const sw       = PX.loadStroke * wpp;
  poly.loads.forEach(l => {
    if (l.vIdx < 0 || l.vIdx >= poly.verts.length) return;
    const {x, y} = poly.verts[l.vIdx];
    const mag = Math.hypot(l.fx, l.fy) || 1;
    const dx = l.fx / mag, dy = l.fy / mag;
    const g = _mkEl("g", {});
    _drawArrow(g, x - dx * arrowLen, y - dy * arrowLen, x, y,
               dx, dy, sw, headLen, headW, C.LOAD_COL);
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
    const snapped = _snapPoint(m);
    // Click near first vertex with ≥3 verts → close polygon (CAD convention)
    if (poly.verts.length >= 3) {
      const v0 = poly.verts[0];
      if (Math.hypot(snapped.x - v0.x, snapped.y - v0.y) < 16 * _worldPerPx()) {
        poly.closed = true;
        selIdx = -1; selEdge = -1; hoverEdge = -1;
        _render();
        _updateStatus(_ct("st_closed"));
        return;
      }
    }
    poly.verts.push(snapped);
    selIdx = poly.verts.length - 1;
    selEdge = -1;
    hoverEdge = -1;
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
    if (!poly.closed) { _updateStatus("Cerrá el polígono primero (doble clic)."); return; }
    if (poly.verts.length < 2) return;
    const ei = _nearestEdgeIdx(m);
    if (ei < 0) { _updateStatus("Hacé clic cerca de una arista del polígono."); return; }
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
    if (!poly.closed) { _updateStatus("Cerrá el polígono primero (doble clic)."); return; }
    if (poly.verts.length < 2) return;
    const ei = _nearestEdgeIdx(m);
    if (ei < 0) { _updateStatus("Hacé clic cerca de una arista del polígono."); return; }
    if (!poly.edgeLoads.find(eld => eld.e0 === ei)) {
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
  if (activeTool !== TOOL.VERTEX || poly.closed) return;
  // Double-click adds two vertices (one per click) — remove both duplicates then close.
  if (poly.verts.length > 0) poly.verts.pop(); // remove 2nd-click duplicate
  if (poly.verts.length > 0) poly.verts.pop(); // remove 1st-click duplicate
  if (poly.verts.length < 3) return;
  poly.closed = true;
  _render();
  _updateStatus(_ct("st_closed"));
}

function _svgCoordFromEvent(e) {
  // Returns cursor position in SVG viewBox coordinates (y-down, not worldG)
  const rect = svgEl.getBoundingClientRect();
  const vb   = svgEl.viewBox.baseVal;
  if (!rect.width || !rect.height || !vb.width) return null;
  return {
    x: vb.x + ((e.clientX - rect.left) / rect.width)  * vb.width,
    y: vb.y + ((e.clientY - rect.top)  / rect.height) * vb.height,
  };
}

function _startPan(e) {
  const vb = svgEl.viewBox.baseVal;
  panState = { cx: e.clientX, cy: e.clientY,
               vbx: vb.x, vby: vb.y, vbw: vb.width, vbh: vb.height };
  svgEl.style.cursor = "grabbing";
  e.preventDefault();
}

function _onSvgMouseDown(e) {
  // Middle mouse → pan always
  if (e.button === 1) { _startPan(e); return; }
  if (e.button !== 0) return;

  // Left button: pan tool or vertex drag
  if (activeTool === TOOL.PAN) { _startPan(e); return; }

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
  // Pan handling (takes priority)
  if (panState) {
    const rect = svgEl.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const wppX = panState.vbw / rect.width;
    const wppY = panState.vbh / rect.height;
    const newX = panState.vbx - (e.clientX - panState.cx) * wppX;
    const newY = panState.vby - (e.clientY - panState.cy) * wppY;
    svgEl.setAttribute("viewBox", `${newX} ${newY} ${panState.vbw} ${panState.vbh}`);
    _render();
    return;
  }

  const m = _eventToModel(e);
  if (!m) return;

  const snapped = _snapPoint(m);
  const co = document.getElementById("ed-coords");
  if (co) co.textContent = snapGrid
    ? `x = ${(snapped.x/1000).toFixed(3)} m,  y = ${(snapped.y/1000).toFixed(3)} m  ✦`
    : _fmtCoord(m);

  if (dragState) {
    dragState.moved = true;
    poly.verts[dragState.vIdx] = snapped;
    _render();
    return;
  }

  if (activeTool === TOOL.PAN) return;

  // Update snap crosshair & entry fields when in vertex tool
  if (activeTool === TOOL.VERTEX && edMode === "poly" && !poly.closed) {
    _fillEntryFields(m);
    const prev = snapPreviewPos;
    snapPreviewPos = snapGrid ? snapped : null;
    if (snapGrid && (!prev || prev.x !== snapped.x || prev.y !== snapped.y)) {
      _render();
    } else if (!snapGrid && prev) {
      snapPreviewPos = null;
      _render();
    }
  } else {
    snapPreviewPos = null;
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
  if (panState) {
    panState = null;
    _updateCursor();
    return;
  }
  if (dragState) {
    if (dragState.moved) {
      selIdx = dragState.vIdx;
      _updateInspector();
    }
    dragState = null;
  }
}

function _onSvgWheel(e) {
  e.preventDefault();
  const sv = _svgCoordFromEvent(e);
  if (!sv) return;
  const vb = svgEl.viewBox.baseVal;
  // Normalize delta across different deltaMode values
  let delta = e.deltaY;
  if (e.deltaMode === 1) delta *= 33;   // lines → pixels approx
  if (e.deltaMode === 2) delta *= 600;  // pages → pixels approx
  // Clamp per-event zoom to avoid jumps on trackpad
  const rawFactor = Math.pow(1.0012, delta);
  const factor = Math.min(Math.max(rawFactor, 0.5), 2.0);
  const newW = vb.width  * factor;
  const newH = vb.height * factor;
  // Clamp zoom extents: min ~10 cm across, max ~50 km across
  if (newW < 100 || newH < 100 || newW > 50_000_000 || newH > 50_000_000) return;
  const rect = svgEl.getBoundingClientRect();
  const fx = (e.clientX - rect.left) / rect.width;
  const fy = (e.clientY - rect.top)  / rect.height;
  const newX = sv.x - fx * newW;
  const newY = sv.y - fy * newH;
  svgEl.setAttribute("viewBox", `${newX} ${newY} ${newW} ${newH}`);
  _render();
}

function _onKeyDown(e) {
  // Keyboard shortcuts for tools
  const keyMap = {
    "v": "vertex",          "V": "vertex",
    "f": "support-fixed",   "F": "support-fixed",
    "x": "support-roller_x","X": "support-roller_x",
    "y": "support-roller_y","Y": "support-roller_y",
    "l": "load",            "L": "load",
    "e": "edge",            "E": "edge",
    "g": "esupport",        "G": "esupport",
    "b": "eload",           "B": "eload",
    "d": "delete",          "D": "delete",
    "h": "pan",             "H": "pan",
  };

  if (!e.ctrlKey && !e.metaKey && !e.altKey && document.activeElement.tagName !== "INPUT") {
    if (e.key === "z" || e.key === "Z") { _fitView(); _render(); e.preventDefault(); return; }
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
      _showEntryBar(activeTool === TOOL.VERTEX && edMode === "poly");
      snapPreviewPos = null;
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
    <input type="number" step="0.001" value="${(v.x/1000).toFixed(3)}" onchange="updateVertCoordM(${selIdx},'x',this.value)">
    <span style="font-size:11px;color:var(--muted)">m</span>
  </div>`;
  html += `<div class="inspector-field">
    <label>${_ct("ins_y")}</label>
    <input type="number" step="0.001" value="${(v.y/1000).toFixed(3)}" onchange="updateVertCoordM(${selIdx},'y',this.value)">
    <span style="font-size:11px;color:var(--muted)">m</span>
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

function updateVertCoordM(idx, coord, valM) {
  updateVertCoord(idx, coord, (parseFloat(valM) || 0) * 1000);
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
    ${_ct("ins_len")}: ${(len / 1000).toFixed(3)} m</div>`;

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

  const rasOut = { ...poly.ras };
  if (!rasOut.enabled) {
    // Keep only the mode fields, zero out xi so it's a clean FEM run
    rasOut.xi_imposed = 0.0;
  }

  const cfg = {
    name: poly.name || "modelo",
    problem: {
      element_type: "t3",
      problem_type: poly.problemType,
      thickness: poly.thickness,
      strain_shear_factor: 0.5,
    },
    material: { ...poly.material },
    ras: rasOut,
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

  const rasOut = { ...beam.ras };
  if (!rasOut.enabled) rasOut.xi_imposed = 0.0;

  const cfg = {
    name: "canvas_beam",
    problem: {
      element_type: "q4",
      problem_type: "plane_stress",
      thickness: beam.thickness,
      strain_shear_factor: 1.0,
    },
    material: { ...beam.material },
    ras: rasOut,
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
  const thr = 16 * _worldPerPx();  // 16 px hit radius
  poly.verts.forEach((v, i) => {
    const d2 = (v.x - m.x)**2 + (v.y - m.y)**2;
    if (d2 < thr**2 && d2 < bestD2) { bestD2 = d2; best = i; }
  });
  return best;
}

function _nearestEdgeIdx(m) {
  if (!poly.closed || poly.verts.length < 2) return -1;
  let best = -1, bestD = Infinity;
  const thr = 30 * _worldPerPx();  // 30 px pick distance from edge
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
  return `x = ${(m.x/1000).toFixed(3)} m,  y = ${(m.y/1000).toFixed(3)} m`;
}

// ─── Grid step (in mm) ────────────────────────────────────────────────────────
function _niceStep(span) {
  // Pick 1-2-5 × power-of-10 targeting ~8 divisions
  const raw = Math.max(span, 1) / 8;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const r   = raw / mag;
  return (r < 1.5 ? 1 : r < 3.5 ? 2 : r < 7.5 ? 5 : 10) * mag;
}

function _autoGridStep() {
  // Use vertex extent when we have ≥2 vertices with meaningful spread
  if (poly.verts.length >= 2) {
    const xs = poly.verts.map(v => v.x), ys = poly.verts.map(v => v.y);
    const span = Math.max(
      Math.max(...xs) - Math.min(...xs),
      Math.max(...ys) - Math.min(...ys)
    );
    if (span >= 1000) return _niceStep(span);   // ≥ 1 m — use model extent
  }
  // Fallback: use viewBox extent (handles empty canvas and 1-vertex case)
  if (svgEl) {
    const vb = svgEl.viewBox.baseVal;
    if (vb && vb.width > 0) return _niceStep(Math.max(vb.width, vb.height));
  }
  return 1000; // 1 m ultimate fallback
}

function _currentGridStepX() { return (gridStepX  !== null && gridStepX  > 0) ? gridStepX  : _autoGridStep(); }
function _currentGridStepY() { return (gridStepY  !== null && gridStepY  > 0) ? gridStepY  : _currentGridStepX(); }

// ─── Snap ─────────────────────────────────────────────────────────────────────
function _snapPoint(pt) {
  if (!snapGrid) return { x: pt.x, y: pt.y };
  const sx = _currentGridStepX(), sy = _currentGridStepY();
  return { x: Math.round(pt.x / sx) * sx, y: Math.round(pt.y / sy) * sy };
}

// ─── Vertex entry bar ─────────────────────────────────────────────────────────
function _showEntryBar(show) {
  const bar = document.getElementById("ed-entry-bar");
  if (bar) bar.style.display = show ? "" : "none";
}

function _fillEntryFields(m) {
  const snapped = _snapPoint(m);
  const ex = document.getElementById("entry-x");
  const ey = document.getElementById("entry-y");
  if (ex && document.activeElement !== ex) ex.value = (snapped.x / 1000).toFixed(3);
  if (ey && document.activeElement !== ey) ey.value = (snapped.y / 1000).toFixed(3);
}

function _addVertexFromEntry() {
  const ex = document.getElementById("entry-x");
  const ey = document.getElementById("entry-y");
  if (!ex || !ey) return;
  const xm = parseFloat(ex.value), ym = parseFloat(ey.value);
  if (isNaN(xm) || isNaN(ym)) return;
  if (poly.closed) return;
  poly.verts.push({ x: xm * 1000, y: ym * 1000 });
  selIdx = poly.verts.length - 1;
  selEdge = -1;
  _render();
  _updateStatus(_ct("st_open"));
  _updateInspector();
  // Keep Y field selected for rapid multi-entry, clear X to signal ready
  ex.value = "";
  ex.focus();
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
    [TOOL.PAN]:      "grab",
  };
  svgEl.style.cursor = map[activeTool] || "default";
}
