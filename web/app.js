// rasfem web app — text mode + canvas integration.

const I18N = {
  es: {
    // Text mode
    config:    "Ficha de datos",
    ex_beam:   "Ejemplo viga",
    ex_dam:    "Ejemplo presa",
    preview:   "Previsualizar malla",
    run:       "Calcular",
    mesh:      "Malla / Geometría",
    results:   "Resultados",
    summary:   "Resumen",
    running:   "Calculando…",
    meshing:   "Generando malla…",
    done:      "Listo",
    err:       "Error",
    // Header
    mode_text:   "Texto",
    mode_canvas: "Canvas",
    // Canvas tools
    canvas: {
      tool_vertex:   "Vértice",
      tool_fixed:    "Fijo",
      tool_rollerx:  "Rod.X",
      tool_rollery:  "Rod.Y",
      tool_load:     "Carga",
      tool_edge:     "Cara H.",
      tool_esupport: "Apoyo ar.",
      tool_eload:    "Carga ar.",
      tool_delete:   "Borrar",
      lbl_timerange: "Tiempo (carga variable)",
      lbl_tstart:    "t inicial",
      lbl_tend:      "t final",
      lbl_dt:        "Δt",
      // Templates / export
      sec_templates: "Plantillas",
      tpl_dam:       "Presa",
      tpl_beam:      "Viga",
      sec_geometry:  "Geometría",
      lbl_meshsize:  "Tamaño malla (mm)",
      lbl_thickness: "Espesor (mm)",
      lbl_probtype:  "Tipo de problema",
      opt_strain:    "Def. plana",
      opt_stress:    "Tens. plana",
      sec_schedule:  "Historial de carga",
      sch_add:       "+ Agregar paso",
      sec_beam:      "Geometría viga",
      lbl_L:   "L (mm)",
      lbl_H:   "H (mm)",
      lbl_nx:  "nx",
      lbl_ny:  "ny",
      lbl_nw:  "Entalla ancho (mm)",
      lbl_nh:  "Entalla alto (mm)",
      lbl_sp:  "Vano apoyos (mm)",
      lbl_th:  "Espesor (mm)",
      sec_inspector: "Propiedades",
      ins_none: "Sin selección.",
      ins_vertex: "Vértice",
      ins_edge:   "Arista",
      ins_x: "X",
      ins_y: "Y",
      ins_len: "Long.",
      ins_type: "Tipo",
      ins_face: "(cara hidráulica)",
      ins_esupport:     "Apoyo en arista",
      ins_eload:        "Carga en arista",
      ins_nload:        "Carga nodal (fuerza)",
      ins_add_esupport: "+ Apoyo en esta arista",
      ins_add_eload:    "+ Carga en esta arista",
      ins_add_nload:    "+ Carga en este nodo",
      ins_remove:       "Quitar",
      ins_pnormal:      "p normal",
      ins_ptang:        "p tang.",
      ins_fn_expr:      "Función f(t)",
      ins_fn_points:    "Puntos (t, valor)",
      btn_preview: "Ver malla",
      btn_export:  "Exportar a Texto",
      // Status
      st_template: "Plantilla cargada. Editá los vértices y generá la malla.",
      st_closed:   "Polígono cerrado. Agregá apoyos y cargas.",
      st_open:     "Doble clic para cerrar el polígono.",
      st_no_verts: "Hacé clic en el canvas para agregar vértices.",
      instr: "Clic: vértice · Doble clic: cerrar · Arrastrar: mover · Del: borrar",
    },
  },
  en: {
    config:    "Data sheet",
    ex_beam:   "Beam example",
    ex_dam:    "Dam example",
    preview:   "Preview mesh",
    run:       "Run",
    mesh:      "Mesh / Geometry",
    results:   "Results",
    summary:   "Summary",
    running:   "Running…",
    meshing:   "Meshing…",
    done:      "Done",
    err:       "Error",
    mode_text:   "Text",
    mode_canvas: "Canvas",
    canvas: {
      tool_vertex:   "Vertex",
      tool_fixed:    "Fixed",
      tool_rollerx:  "Roll.X",
      tool_rollery:  "Roll.Y",
      tool_load:     "Load",
      tool_edge:     "H.Face",
      tool_esupport: "Edge sup.",
      tool_eload:    "Edge load",
      tool_delete:   "Delete",
      lbl_timerange: "Time (variable load)",
      lbl_tstart:    "t start",
      lbl_tend:      "t end",
      lbl_dt:        "Δt",
      sec_templates: "Templates",
      tpl_dam:       "Dam",
      tpl_beam:      "Beam",
      sec_geometry:  "Geometry",
      lbl_meshsize:  "Mesh size (mm)",
      lbl_thickness: "Thickness (mm)",
      lbl_probtype:  "Problem type",
      opt_strain:    "Plane strain",
      opt_stress:    "Plane stress",
      sec_schedule:  "Load schedule",
      sch_add:       "+ Add step",
      sec_beam:      "Beam geometry",
      lbl_L:   "L (mm)",
      lbl_H:   "H (mm)",
      lbl_nx:  "nx",
      lbl_ny:  "ny",
      lbl_nw:  "Notch width (mm)",
      lbl_nh:  "Notch height (mm)",
      lbl_sp:  "Support span (mm)",
      lbl_th:  "Thickness (mm)",
      sec_inspector: "Properties",
      ins_none:   "Nothing selected.",
      ins_vertex: "Vertex",
      ins_edge:   "Edge",
      ins_x:   "X",
      ins_y:   "Y",
      ins_len: "Len.",
      ins_type: "Type",
      ins_face: "(hydraulic face)",
      ins_esupport:     "Edge support",
      ins_eload:        "Edge load",
      ins_nload:        "Nodal load (force)",
      ins_add_esupport: "+ Support on this edge",
      ins_add_eload:    "+ Load on this edge",
      ins_add_nload:    "+ Load on this node",
      ins_remove:       "Remove",
      ins_pnormal:      "p normal",
      ins_ptang:        "p tang.",
      ins_fn_expr:      "Function f(t)",
      ins_fn_points:    "Points (t, value)",
      btn_preview: "Preview mesh",
      btn_export:  "Export to Text",
      st_template: "Template loaded. Edit vertices and generate the mesh.",
      st_closed:   "Polygon closed. Add supports and loads.",
      st_open:     "Double-click to close the polygon.",
      st_no_verts: "Click on canvas to add vertices.",
      instr: "Click: vertex · Dbl-click: close · Drag: move · Del: delete",
    },
  },
};

let lang = "es";

function _ct(key) {
  return (I18N[lang].canvas && I18N[lang].canvas[key]) || key;
}

function applyI18n() {
  document.querySelectorAll("[data-i18n]").forEach(el => {
    const k = el.getAttribute("data-i18n");
    const parts = k.split(".");
    let val = I18N[lang];
    for (const p of parts) val = val && val[p];
    if (val && typeof val === "string") el.textContent = val;
  });
  document.getElementById("lang").textContent = lang === "es" ? "EN" : "ES";
  document.documentElement.lang = lang;
  document.dispatchEvent(new CustomEvent("langchange", { detail: { lang } }));
}

const $ = id => document.getElementById(id);
const status = m => { if ($("status")) $("status").textContent = m; };

async function loadExample(name) {
  const r = await fetch(`/api/example/${name}`);
  const cfg = await r.json();
  $("cfg").value = JSON.stringify(cfg, null, 2);
  status("");
}

function readCfg() {
  try { return JSON.parse($("cfg").value); }
  catch (e) { status(I18N[lang].err + ": JSON — " + e.message); return null; }
}

async function preview() {
  const cfg = readCfg(); if (!cfg) return;
  status(I18N[lang].meshing);
  const r = await fetch("/api/mesh_preview", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ cfg })
  });
  if (!r.ok) { status(I18N[lang].err + ": " + (await r.text())); return; }
  const { nodes, elements } = await r.json();
  drawMesh(nodes, elements);
  const nn = nodes.length, ne = elements.length;
  const ns = lang === "es" ? "nodos" : "nodes";
  const es = lang === "es" ? "elementos" : "elements";
  status(`${I18N[lang].done}: ${nn} ${ns}, ${ne} ${es}`);
}

function drawMesh(nodes, elements) {
  const xs = nodes.map(n => n[0]), ys = nodes.map(n => n[1]);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const w = maxX - minX || 1, h = maxY - minY || 1;
  const pad = 0.05 * Math.max(w, h);
  const svg = $("mesh-svg");
  svg.setAttribute("viewBox", `${minX - pad} ${minY - pad} ${w + 2*pad} ${h + 2*pad}`);
  const sw = 0.004 * Math.max(w, h);
  const polys = elements.map(el => {
    const pts = el.map(i => `${nodes[i][0]},${maxY + minY - nodes[i][1]}`).join(" ");
    return `<polygon points="${pts}" fill="#0f2820" stroke="#3b82f6" stroke-width="${sw}"/>`;
  }).join("");
  svg.innerHTML = polys;
}

async function run() {
  const cfg = readCfg(); if (!cfg) return;
  status(I18N[lang].running);
  $("run").disabled = true;
  try {
    const r = await fetch("/api/run", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cfg)
    });
    if (!r.ok) { status(I18N[lang].err + ": " + (await r.text())); return; }
    const data = await r.json();
    plotCurve(data.curve, cfg);
    showSummary(data.summary);
    status(I18N[lang].done);
  } finally { $("run").disabled = false; }
}

function plotCurve(curve, cfg) {
  const mode = cfg.loading && cfg.loading.mode;
  const isDam  = mode === "hydraulic";
  const isTime = mode === "time_history";
  const xLabel = isTime ? "t" : isDam ? "H" : "|δ|";
  const yLabel = isTime ? "max|u|" : isDam ? "ux crest" : "P";
  const x = curve.control.map(Math.abs);
  Plotly.newPlot("curve", [
    { x, y: curve.load, mode: "lines+markers", name: yLabel,
      line: { color: "#60a5fa" } },
    { x, y: curve.dmax, mode: "lines", name: "dmax", yaxis: "y2",
      line: { color: "#f87171", dash: "dot" } },
  ], {
    margin: { t: 10, r: 50, b: 40, l: 55 },
    paper_bgcolor: "#132135", plot_bgcolor: "#0d1929",
    font: { color: "#dce8f5", size: 11 },
    xaxis: { title: xLabel, gridcolor: "#233b5c" },
    yaxis: { title: yLabel, gridcolor: "#233b5c" },
    yaxis2: { title: "dmax", overlaying: "y", side: "right", range: [0, 1] },
    legend: { orientation: "h", y: -0.2 },
  }, { displaylogo: false, responsive: true });
}

function showSummary(s) {
  const fmt = v => (typeof v === "number" ? v.toExponential(4) : String(v));
  const rows = Object.entries(s).map(([k, v]) =>
    `<div>${k}</div><div>${fmt(v)}</div>`);
  $("summary").innerHTML = rows.join("");
}

// ── Event delegation ──────────────────────────────────────────────────────────
document.addEventListener("click", e => {
  const t = e.target;
  if (t.id === "lang") {
    lang = lang === "es" ? "en" : "es";
    applyI18n();
  }
  if (t.id === "preview") preview();
  if (t.id === "run") run();
  if (t.dataset && t.dataset.load) loadExample(t.dataset.load);
});

// ── View switching ─────────────────────────────────────────────────────────────
function switchView(view) {
  const tl = $("text-layout");
  const cl = $("canvas-layout");
  if (view === "text") {
    tl.classList.remove("hidden");
    cl.classList.remove("active");
  } else {
    tl.classList.add("hidden");
    cl.classList.add("active");
  }
  document.querySelectorAll(".mode-tab").forEach(b =>
    b.classList.toggle("active", b.dataset.view === view));
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".mode-tab").forEach(btn =>
    btn.addEventListener("click", () => switchView(btn.dataset.view)));
  applyI18n();
  loadExample("beam");
  initEditor();
});
