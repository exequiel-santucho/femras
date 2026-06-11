/**
 * editor.js — rasfem interactive canvas preprocessor (Phase 7)
 *
 * Two editing modes
 *   poly  – click-to-draw polygon → PolygonGeometry config (T3, plane strain)
 *   beam  – form-based → BeamGeometry config (Q4, plane stress)
 *
 * Public API (called from index.html):
 *   initEditor()               – called once on DOMContentLoaded
 *   editorExportConfig()       – returns config JSON string from canvas state
 *   editorLoadTemplate(name)   – "beam" | "dam"
 */

"use strict";

// ─── Constants ──────────────────────────────────────────────────────────────

const TOOL = {
  VERTEX:   "vertex",
  SUPPORT:  "support",
  LOAD:     "load",
  DELETE:   "delete",
};

const SUPPORT_TYPES = ["fixed", "roller_x", "roller_y"];

// Colours
const C = {
  POLY_FILL:    "rgba(26,75,50,0.55)",
  POLY_EDGE:    "#4aa3ff",
  VERT_IDLE:    "#4aa3ff",
  VERT_HOVER:   "#ffdd55",
  VERT_SEL:     "#ff7755",
  SUPPORT_COL:  "#f0c040",
  LOAD_COL:     "#ff7755",
  GRID:         "rgba(255,255,255,0.05)",
  TEXT:         "#8aa0b4",
};

// ─── State ──────────────────────────────────────────────────────────────────

let edMode = "poly";          // "poly" | "beam"
let activeTool = TOOL.VERTEX;
let activeSupportType = "fixed";

// Polygon mode state
const poly = {
  verts:      [],    // [{x, y}] model coords (mm)
  closed:     false,
  supports:   [],    // [{vIdx, type}]  type ∈ SUPPORT_TYPES
  loads:      [],    // [{vIdx, fx, fy}]  normalised direction
  hydraulic:  false,
  meshSize:   2000.0,
  thickness:  1000.0,
  problemType:"plane_strain",
};

// Beam mode state (form mirrors these)
const beam = {
  L: 430, H: 105, nx: 86, ny: 21,
  notchW: 3, notchH: 52.5, span: 400, thickness: 75,
};

// SVG interaction
let svgEl   = null;
let worldG  = null;   // <g id="ed-world"> with transform="scale(1,-1)"
let hoverIdx  = -1;
let selIdx    = -1;
let dragState = null; // {vIdx, origX, origY}

// ─── Init ───────────────────────────────────────────────────────────────────

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

  // Mesh size + thickness inputs sync
  const msEl = document.getElementById("ed-meshsize");
  if (msEl) msEl.addEventListener("change", () => {
    poly.meshSize = parseFloat(msEl.value) || 2000;
  });
  const thEl = document.getElementById("ed-thickness");
  if (thEl) thEl.addEventListener("change", () => {
    poly.thickness = parseFloat(thEl.value) || 1000;
  });

  // Hydraulic toggle
  const hydEl = document.getElementById("ed-hydraulic");
  if (hydEl) hydEl.addEventListener("change", () => {
    poly.hydraulic = hydEl.checked;
  });

  // Beam form inputs
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
  document.addEventListener("keydown", _onKeyDown);

  // Default: dam template
  editorLoadTemplate("dam");
}

// ─── Templates ──────────────────────────────────────────────────────────────

function editorLoadTemplate(name) {
  if (name === "beam") {
    edMode = "beam";
    _showMode("beam");
    _syncBeamForm();
    renderBeamSchematic();
  } else {
    edMode = "poly";
    poly.verts = [
      {x:0,      y:0},
      {x:70000,  y:0},
      {x:19200,  y:66000},
      {x:14800,  y:103000},
      {x:0,      y:103000},
    ];
    poly.closed    = true;
    poly.supports  = [{vIdx:0, type:"fixed"}, {vIdx:1, type:"fixed"}];
    poly.loads     = [];
    poly.hydraulic = true;
    poly.meshSize  = 2000;
    poly.thickness = 1000;
    poly.problemType = "plane_strain";
    _showMode("poly");
    _fitView();
    _render();
    _syncPolyForm();
  }
  _updateStatus("Plantilla cargada. Editá los vértices y generá la malla.");
}

// ─── Mode visibility ────────────────────────────────────────────────────────

function _showMode(mode) {
  const polyPanel = document.getElementById("ed-poly-panel");
  const beamPanel = document.getElementById("ed-beam-panel");
  if (polyPanel) polyPanel.style.display = mode === "poly" ? "" : "none";
  if (beamPanel) beamPanel.style.display = mode === "beam" ? "" : "none";
}

function _syncPolyForm() {
  const msEl = document.getElementById("ed-meshsize");
  const thEl = document.getElementById("ed-thickness");
  const hydEl = document.getElementById("ed-hydraulic");
  if (msEl)  msEl.value  = poly.meshSize;
  if (thEl)  thEl.value  = poly.thickness;
  if (hydEl) hydEl.checked = poly.hydraulic;
}

function _syncBeamForm() {
  ["L","H","nx","ny","notchW","notchH","span","thickness"].forEach(k => {
    const el = document.getElementById(`bm-${k}`);
    if (el) el.value = beam[k];
  });
}

// ─── ViewBox ────────────────────────────────────────────────────────────────

function _fitView() {
  if (!poly.verts.length) return;
  const xs = poly.verts.map(v => v.x);
  const ys = poly.verts.map(v => v.y);
  const xmin = Math.min(...xs), xmax = Math.max(...xs);
  const ymin = Math.min(...ys), ymax = Math.max(...ys);
  const W = xmax - xmin || 100, H = ymax - ymin || 100;
  const pad = 0.12 * Math.max(W, H);
  // With scale(1,-1) in worldG, SVG y-coords are negated model y-coords.
  // ViewBox must cover negative y: origin at (xmin-pad, -(ymax+pad)).
  svgEl.setAttribute("viewBox",
    `${xmin - pad} ${-(ymax + pad)} ${W + 2*pad} ${H + 2*pad}`);
}

// ─── SVG rendering ──────────────────────────────────────────────────────────

function _render() {
  if (!worldG) return;
  worldG.innerHTML = "";
  if (!poly.verts.length) return;

  _drawGrid();
  _drawPolygon();
  _drawSupports();
  _drawLoads();
  _drawVertices();
}

function _drawGrid() {
  if (!poly.verts.length) return;
  const xs = poly.verts.map(v => v.x);
  const ys = poly.verts.map(v => v.y);
  const xmin = Math.min(...xs) - poly.meshSize * 2;
  const xmax = Math.max(...xs) + poly.meshSize * 2;
  const ymin = Math.min(...ys) - poly.meshSize * 2;
  const ymax = Math.max(...ys) + poly.meshSize * 2;
  const step = poly.meshSize * 5;
  const sw = poly.meshSize * 0.1;
  const g = _mkEl("g", {opacity: 0.4});
  for (let x = Math.ceil(xmin / step) * step; x <= xmax; x += step)
    g.appendChild(_mkEl("line", {x1:x, y1:ymin, x2:x, y2:ymax,
      stroke: C.GRID, "stroke-width": sw}));
  for (let y = Math.ceil(ymin / step) * step; y <= ymax; y += step)
    g.appendChild(_mkEl("line", {x1:xmin, y1:y, x2:xmax, y2:y,
      stroke: C.GRID, "stroke-width": sw}));
  worldG.appendChild(g);
}

function _drawPolygon() {
  const verts = poly.verts;
  if (verts.length < 2) return;
  const pts = verts.map(v => `${v.x},${v.y}`).join(" ");
  if (poly.closed) {
    worldG.appendChild(_mkEl("polygon", {
      points: pts, fill: C.POLY_FILL,
      stroke: C.POLY_EDGE, "stroke-width": poly.meshSize * 0.3,
      "stroke-linejoin": "round",
    }));
  } else {
    worldG.appendChild(_mkEl("polyline", {
      points: pts, fill: "none",
      stroke: C.POLY_EDGE, "stroke-width": poly.meshSize * 0.3,
      "stroke-linejoin": "round",
    }));
  }
}

function _drawVertices() {
  const r = poly.meshSize * 1.2;
  poly.verts.forEach((v, i) => {
    const col = i === selIdx ? C.VERT_SEL : i === hoverIdx ? C.VERT_HOVER : C.VERT_IDLE;
    const c = _mkEl("circle", {
      cx: v.x, cy: v.y, r,
      fill: col, stroke: "#0f1720", "stroke-width": r * 0.3,
      "data-vidx": i, style: "cursor:grab",
    });
    worldG.appendChild(c);
    // Label (needs un-flipped text)
    const lbl = _mkEl("text", {
      x: v.x + r * 1.5, y: -(v.y - r * 1.5),   // negative y for scale(1,-1)
      "font-size": poly.meshSize * 2.5,
      fill: C.TEXT, "pointer-events": "none",
      transform: "scale(1,-1)",
    });
    lbl.textContent = `V${i}`;
    worldG.appendChild(lbl);
  });
}

function _drawSupports() {
  const sz = poly.meshSize * 3.5;
  poly.supports.forEach(s => {
    if (s.vIdx < 0 || s.vIdx >= poly.verts.length) return;
    const {x, y} = poly.verts[s.vIdx];
    const g = _mkEl("g", {});
    if (s.type === "fixed") {
      // Filled triangle pointing up (pins both DOFs)
      g.appendChild(_mkEl("polygon", {
        points: `${x},${y} ${x-sz},${y-sz*1.6} ${x+sz},${y-sz*1.6}`,
        fill: C.SUPPORT_COL, stroke: C.SUPPORT_COL, "stroke-width": sz * 0.1,
      }));
      g.appendChild(_mkEl("line", {
        x1: x - sz*1.2, y1: y - sz*1.8, x2: x + sz*1.2, y2: y - sz*1.8,
        stroke: C.SUPPORT_COL, "stroke-width": sz * 0.3,
      }));
    } else if (s.type === "roller_x") {
      // Open triangle + horizontal rollers
      g.appendChild(_mkEl("polygon", {
        points: `${x},${y} ${x-sz},${y-sz*1.6} ${x+sz},${y-sz*1.6}`,
        fill: "none", stroke: C.SUPPORT_COL, "stroke-width": sz * 0.3,
      }));
      for (let dx = -sz*0.6; dx <= sz*0.7; dx += sz * 0.6)
        g.appendChild(_mkEl("circle", {
          cx: x + dx, cy: y - sz*2, r: sz * 0.25,
          fill: C.SUPPORT_COL,
        }));
    } else {
      // roller_y — triangle + vertical rollers
      g.appendChild(_mkEl("polygon", {
        points: `${x},${y} ${x-sz*1.6},${y-sz} ${x-sz*1.6},${y+sz}`,
        fill: "none", stroke: C.SUPPORT_COL, "stroke-width": sz * 0.3,
      }));
      for (let dy = -sz*0.6; dy <= sz*0.7; dy += sz * 0.6)
        g.appendChild(_mkEl("circle", {
          cx: x - sz*2, cy: y + dy, r: sz * 0.25,
          fill: C.SUPPORT_COL,
        }));
    }
    worldG.appendChild(g);
  });
}

function _drawLoads() {
  const arrowLen = poly.meshSize * 8;
  const hw = poly.meshSize * 1.5;
  poly.loads.forEach(l => {
    if (l.vIdx < 0 || l.vIdx >= poly.verts.length) return;
    const {x, y} = poly.verts[l.vIdx];
    const mag = Math.hypot(l.fx, l.fy) || 1;
    const dx = (l.fx / mag) * arrowLen;
    const dy = (l.fy / mag) * arrowLen;
    const g = _mkEl("g", {});
    // Arrow shaft
    g.appendChild(_mkEl("line", {
      x1: x - dx, y1: y - dy, x2: x, y2: y,
      stroke: C.LOAD_COL, "stroke-width": hw * 0.5,
      "marker-end": "url(#ed-arrow)",
    }));
    worldG.appendChild(g);
  });
}

// ─── SVG event handlers ────────────────────────────────────────────────────

function _onSvgClick(e) {
  if (dragState) return;  // was a drag, not a click
  const m = _eventToModel(e);
  if (!m) return;

  if (activeTool === TOOL.VERTEX) {
    if (poly.closed) return;
    poly.verts.push({x: m.x, y: m.y});
    selIdx = poly.verts.length - 1;
    _fitView();
    _render();
    _updateStatus(`Vértice V${selIdx} agregado (${_fmtCoord(m)}). Doble clic para cerrar.`);

  } else if (activeTool === TOOL.SUPPORT) {
    const vi = _nearestVertIdx(m);
    if (vi < 0) return;
    // Remove existing support on this vertex, then add new
    poly.supports = poly.supports.filter(s => s.vIdx !== vi);
    poly.supports.push({vIdx: vi, type: activeSupportType});
    _render();
    _updateStatus(`Apoyo ${activeSupportType} en V${vi}.`);

  } else if (activeTool === TOOL.LOAD) {
    const vi = _nearestVertIdx(m);
    if (vi < 0) return;
    poly.loads = poly.loads.filter(l => l.vIdx !== vi);
    poly.loads.push({vIdx: vi, fx: 0, fy: -1});
    _render();
    _updateStatus(`Carga puntual en V${vi} (dirección -Y). Editá fx/fy en el JSON.`);

  } else if (activeTool === TOOL.DELETE) {
    const vi = _nearestVertIdx(m);
    if (vi < 0) return;
    poly.verts.splice(vi, 1);
    poly.supports = poly.supports.filter(s => s.vIdx !== vi)
      .map(s => ({...s, vIdx: s.vIdx > vi ? s.vIdx - 1 : s.vIdx}));
    poly.loads = poly.loads.filter(l => l.vIdx !== vi)
      .map(l => ({...l, vIdx: l.vIdx > vi ? l.vIdx - 1 : l.vIdx}));
    if (poly.verts.length < 3) poly.closed = false;
    selIdx = -1;
    _fitView();
    _render();
    _updateStatus(`Vértice V${vi} eliminado.`);
  }
}

function _onSvgDblClick(e) {
  if (activeTool !== TOOL.VERTEX || poly.closed || poly.verts.length < 3) return;
  poly.closed = true;
  _render();
  _updateStatus("Polígono cerrado. Ahora podés agregar apoyos y cargas.");
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

  // Update coordinate readout
  const co = document.getElementById("ed-coords");
  if (co) co.textContent = _fmtCoord(m);

  if (dragState) {
    dragState.moved = true;
    poly.verts[dragState.vIdx] = {x: m.x, y: m.y};
    _fitView();
    _render();
    return;
  }

  // Hover highlight
  const vi = _nearestVertIdx(m);
  if (vi !== hoverIdx) {
    hoverIdx = vi;
    _render();
  }
}

function _onSvgMouseUp(e) {
  if (dragState) {
    if (dragState.moved) {
      selIdx = dragState.vIdx;
      _updateStatus(`V${selIdx} movido a ${_fmtCoord(poly.verts[selIdx])}.`);
    }
    dragState = null;
  }
}

function _onKeyDown(e) {
  if (e.key === "Delete" || e.key === "Backspace") {
    if (selIdx >= 0 && selIdx < poly.verts.length) {
      const vi = selIdx;
      poly.verts.splice(vi, 1);
      poly.supports = poly.supports.filter(s => s.vIdx !== vi)
        .map(s => ({...s, vIdx: s.vIdx > vi ? s.vIdx - 1 : s.vIdx}));
      poly.loads = poly.loads.filter(l => l.vIdx !== vi)
        .map(l => ({...l, vIdx: l.vIdx > vi ? l.vIdx - 1 : l.vIdx}));
      if (poly.verts.length < 3) poly.closed = false;
      selIdx = -1;
      _fitView();
      _render();
    }
  }
  if (e.key === "Escape") {
    selIdx = -1;
    dragState = null;
    _render();
  }
}

// ─── Beam schematic ─────────────────────────────────────────────────────────

function renderBeamSchematic() {
  const svg = document.getElementById("bm-svg");
  if (!svg) return;
  const {L, H, notchW, notchH, span} = beam;
  const pad = 0.12 * Math.max(L, H);
  const vbW = L + 2*pad, vbH = H + 2*pad;
  svg.setAttribute("viewBox", `${-pad} ${-pad} ${vbW} ${vbH}`);
  const sw = H * 0.025;
  const cols = {fill:"#173a2a", edge:"#4aa3ff", notch:"#0c141d",
                sup:"#f0c040", load:"#ff7755"};

  let html = "";
  // Beam outline
  html += `<rect x="0" y="0" width="${L}" height="${H}"
    fill="${cols.fill}" stroke="${cols.edge}" stroke-width="${sw}"/>`;
  // Notch (at center bottom)
  const nx = (L - notchW) / 2, nh = notchH;
  html += `<rect x="${nx}" y="${H - nh}" width="${notchW}" height="${nh}"
    fill="${cols.notch}" stroke="${cols.edge}" stroke-width="${sw*0.6}"/>`;
  // Supports (at bottom, inset by (L-span)/2)
  const sx = (L - span) / 2;
  const tri = sz => `0,0 ${-sz},${sz*1.6} ${sz},${sz*1.6}`;
  const sz = H * 0.14;
  html += `<g transform="translate(${sx},${H})"><polygon points="${tri(sz)}"
    fill="${cols.sup}"/></g>`;
  html += `<g transform="translate(${L-sx},${H})"><polygon points="${tri(sz)}"
    fill="none" stroke="${cols.sup}" stroke-width="${sw}"/></g>`;
  // Load arrow at top center
  const al = H * 0.4;
  html += `<line x1="${L/2}" y1="${-al}" x2="${L/2}" y2="${0}"
    stroke="${cols.load}" stroke-width="${sw*1.5}"
    marker-end="url(#bm-arrow)"/>`;
  // Arrow marker def
  html = `<defs><marker id="bm-arrow" markerWidth="6" markerHeight="6"
    refX="3" refY="3" orient="auto">
    <path d="M0,0 L6,3 L0,6 Z" fill="${cols.load}"/>
    </marker></defs>` + html;
  // Dimensions
  const fs = H * 0.18;
  html += `<text x="${L/2}" y="${-al-fs*0.3}" text-anchor="middle"
    font-size="${fs}" fill="${cols.load}">P</text>`;
  html += `<text x="${L/2}" y="${H+sz*2.2}" text-anchor="middle"
    font-size="${fs}" fill="${cols.sup}">L=${L}mm</text>`;

  svg.innerHTML = html;
}

// ─── Config generation ───────────────────────────────────────────────────────

function editorExportConfig() {
  if (edMode === "beam") return _beamConfig();
  return _polyConfig();
}

function _polyConfig() {
  if (poly.verts.length < 3) {
    _updateStatus("Necesitás al menos 3 vértices para generar la ficha.");
    return null;
  }
  const verts = poly.verts.map(v => [+v.x.toFixed(1), +v.y.toFixed(1)]);
  const ymax = Math.max(...poly.verts.map(v => v.y));

  // Build boundary conditions from supports
  // Supports are encoded as BCs on geometry vertices;
  // presa_ras.py applies them to base nodes automatically, so we attach
  // them via a custom "canvas_supports" field that run.py can interpret.
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
    loading: {
      mode: poly.hydraulic ? "hydraulic" : "displacement",
      h_target: ymax * 0.97,
      max_accepted_steps: 300,
    },
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
    loading: {
      mode: "displacement",
      x_center: beam.L / 2, y_top: beam.H,
      patch: "three_nodes_centered",
      target: -0.20,
      step_initial: -0.001, step_min: -0.00001, step_max: -0.0015,
      grow_factor: 1.10, shrink_factor: 0.5, max_accepted_steps: 600,
    },
    solver: {
      tangent_mode: "numerical_hybrid",
      max_iter: 60, tol_res_abs: 1.0e-4, tol_res_rel: 1.0e-5,
      use_line_search: true, backend: "auto",
    },
    output: { save_figures: true, save_tables: true },
  };
  return JSON.stringify(cfg, null, 2);
}

// ─── Helpers ────────────────────────────────────────────────────────────────

function _eventToModel(e) {
  if (!worldG || !svgEl) return null;
  try {
    const pt = svgEl.createSVGPoint();
    pt.x = e.clientX;
    pt.y = e.clientY;
    // worldG CTM includes scale(1,-1), so local Y is the negated SVG parent Y.
    // That means local coords = model coords directly (y-up convention in group).
    const local = pt.matrixTransform(worldG.getScreenCTM().inverse());
    return {x: local.x, y: local.y};
  } catch { return null; }
}

function _nearestVertIdx(m) {
  let best = -1, bestD2 = Infinity;
  const thr = poly.meshSize * 4;
  poly.verts.forEach((v, i) => {
    const d2 = (v.x - m.x)**2 + (v.y - m.y)**2;
    if (d2 < thr**2 && d2 < bestD2) { bestD2 = d2; best = i; }
  });
  return best;
}

function _mkEl(tag, attrs) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, v));
  return el;
}

function _fmtCoord(m) {
  const x = (m.x / 1000).toFixed(2), y = (m.y / 1000).toFixed(2);
  return `x=${x} m, y=${y} m`;
}

function _updateStatus(msg) {
  const el = document.getElementById("ed-status");
  if (el) el.textContent = msg;
}

function _updateCursor() {
  if (!svgEl) return;
  const cursors = {
    [TOOL.VERTEX]:  "crosshair",
    [TOOL.SUPPORT]: "cell",
    [TOOL.LOAD]:    "cell",
    [TOOL.DELETE]:  "no-drop",
  };
  svgEl.style.cursor = cursors[activeTool] || "default";
}
