/**
 * editor.js — rasfem interactive canvas preprocessor
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
  VERTEX:  "vertex",
  SUPPORT: "support",
  LOAD:    "load",
  EDGE:    "edge",
  DELETE:  "delete",
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
  meshSize:      2000.0,
  thickness:     1000.0,
  problemType:   "plane_strain",
  loadHistory:   [],      // [target, target, …] ordered list of control targets
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
let hoverEdge = -1;  // index into verts[] of the start vertex of hovered edge
let dragState = null;

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
    poly.meshSize      = 2000;
    poly.thickness     = 1000;
    poly.problemType   = "plane_strain";
    poly.loadHistory   = [];
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
  // Edge tool only makes sense in poly mode
  const edgeBtn = document.querySelector('[data-tool="edge"]');
  if (edgeBtn) edgeBtn.style.display = mode === "poly" ? "" : "none";
}

function _syncPolyForm() {
  const msEl = document.getElementById("ed-meshsize");
  const thEl = document.getElementById("ed-thickness");
  const ptEl = document.getElementById("ed-probtype");
  if (msEl)  msEl.value  = poly.meshSize;
  if (thEl)  thEl.value  = poly.thickness;
  if (ptEl)  ptEl.value  = poly.problemType;
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
  if (activeTool !== TOOL.EDGE || hoverEdge < 0 || !poly.closed) return;
  const n = poly.verts.length;
  const v1 = poly.verts[hoverEdge];
  const v2 = poly.verts[(hoverEdge + 1) % n];
  worldG.appendChild(_mkEl("line", {
    x1: v1.x, y1: v1.y, x2: v2.x, y2: v2.y,
    stroke: C.VERT_HOVER, "stroke-width": poly.meshSize * 1.5,
    "stroke-linecap": "round", opacity: 0.6,
  }));
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
    selIdx = vi;
    _render();
    _updateInspector();

  } else if (activeTool === TOOL.LOAD) {
    const vi = _nearestVertIdx(m);
    if (vi < 0) return;
    poly.loads = poly.loads.filter(l => l.vIdx !== vi);
    poly.loads.push({vIdx: vi, fx: 0, fy: -1});
    selIdx = vi;
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
    _render();
    _updateInspector();

  } else if (activeTool === TOOL.DELETE) {
    const vi = _nearestVertIdx(m);
    if (vi < 0) return;
    _deleteVertex(vi);
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

  if (activeTool === TOOL.EDGE && poly.closed) {
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
    dragState = null;
    _render();
    _updateInspector();
  }
}

// ─── Property inspector ───────────────────────────────────────────────────────
function _updateInspector() {
  const el = document.getElementById("inspector-content");
  if (!el) return;

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
  if (load) {
    html += `<div style="font-size:11px;color:var(--load-col)">
      ${_ct("ins_type")}: load (fx=${load.fx}, fy=${load.fy})</div>`;
  }
  if (isFace) {
    html += `<div style="font-size:11px;color:var(--face-col)">${_ct("ins_face")}</div>`;
  }

  el.innerHTML = html;
}

function updateVertCoord(idx, coord, val) {
  if (idx < 0 || idx >= poly.verts.length) return;
  poly.verts[idx][coord] = parseFloat(val) || 0;
  _fitView();
  _render();
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

  const isHydraulic = poly.hydraulicFace !== null;

  const loading = {
    mode: isHydraulic ? "hydraulic" : "displacement",
  };

  if (isHydraulic) {
    Object.assign(loading, {
      h_start: ymax * 0.80,
      h_target: ymax * 0.97,
      dh_initial: ymax * 0.004,
      dh_min: ymax * 0.0002,
      dh_max: ymax * 0.004,
      max_accepted_steps: 300,
    });
    if (poly.hydraulicFace) {
      const {v1Idx, v2Idx} = poly.hydraulicFace;
      const pf1 = poly.verts[v1Idx], pf2 = poly.verts[v2Idx];
      loading.face_vertices = [
        [+pf1.x.toFixed(1), +pf1.y.toFixed(1)],
        [+pf2.x.toFixed(1), +pf2.y.toFixed(1)],
      ];
    }
    if (poly.loadHistory.length) loading.history = [...poly.loadHistory];
  } else {
    Object.assign(loading, {
      x_center: poly.verts.reduce((s,v) => s + v.x, 0) / poly.verts.length,
      y_top: ymax,
      patch: "three_nodes_centered",
      target: -0.20,
      step_initial: -0.001, step_min: -0.00001, step_max: -0.0015,
      grow_factor: 1.10, shrink_factor: 0.5, max_accepted_steps: 300,
    });
    if (poly.loadHistory.length) loading.history = [...poly.loadHistory];
  }

  const supportsInfo = poly.supports.map(s => ({
    vIdx: s.vIdx, type: s.type,
    coords: poly.verts[s.vIdx] ? [poly.verts[s.vIdx].x, poly.verts[s.vIdx].y] : null,
  }));

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
    loading,
    solver: {
      tangent_mode: "numerical_hybrid",
      max_iter: 60, tol_res_abs: 1.0e-4, tol_res_rel: 1.0e-5,
      use_line_search: true, backend: "auto",
    },
    output: { save_figures: true, save_tables: true },
    _canvas_supports: supportsInfo,
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
  if (poly.verts.length < 3) poly.closed = false;
  selIdx = -1;
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
    [TOOL.VERTEX]:  "crosshair",
    [TOOL.SUPPORT]: "cell",
    [TOOL.LOAD]:    "cell",
    [TOOL.EDGE]:    "pointer",
    [TOOL.DELETE]:  "no-drop",
  };
  svgEl.style.cursor = map[activeTool] || "default";
}
