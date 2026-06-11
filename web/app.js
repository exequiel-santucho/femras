// rasfem local web app (MVP).
// Loads an example config, lets the user edit it as JSON, previews the mesh and
// runs the analysis, plotting the control-response curve. This is the foundation
// the graphical canvas pre-processor builds on (it will write the same config).

const I18N = {
  es: { config:"Ficha de datos", ex_beam:"Ejemplo viga", ex_dam:"Ejemplo presa",
        preview:"Previsualizar malla", run:"Calcular", mesh:"Malla / Geometría",
        results:"Resultados", summary:"Resumen", running:"Calculando…",
        meshing:"Generando malla…", done:"Listo", err:"Error" },
  en: { config:"Data sheet", ex_beam:"Beam example", ex_dam:"Dam example",
        preview:"Preview mesh", run:"Run", mesh:"Mesh / Geometry",
        results:"Results", summary:"Summary", running:"Running…",
        meshing:"Meshing…", done:"Done", err:"Error" },
};
let lang = "es";

function applyI18n() {
  document.querySelectorAll("[data-i18n]").forEach(el => {
    const k = el.getAttribute("data-i18n");
    if (I18N[lang][k]) el.textContent = I18N[lang][k];
  });
  document.getElementById("lang").textContent = lang === "es" ? "EN" : "ES";
  document.documentElement.lang = lang;
}

const $ = id => document.getElementById(id);
const status = m => { $("status").textContent = m; };

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
    method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({ cfg })
  });
  if (!r.ok) { status(I18N[lang].err + ": " + (await r.text())); return; }
  const { nodes, elements } = await r.json();
  drawMesh(nodes, elements);
  status(`${I18N[lang].done}: ${nodes.length} ${lang==="es"?"nodos":"nodes"}, ${elements.length} ${lang==="es"?"elementos":"elements"}`);
}

function drawMesh(nodes, elements) {
  const xs = nodes.map(n => n[0]), ys = nodes.map(n => n[1]);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const w = maxX - minX || 1, h = maxY - minY || 1;
  const pad = 0.05 * Math.max(w, h);
  const svg = $("mesh");
  svg.setAttribute("viewBox", `${minX-pad} ${minY-pad} ${w+2*pad} ${h+2*pad}`);
  // flip Y so it reads as engineering coordinates (y up)
  const polys = elements.map(el => {
    const pts = el.map(i => `${nodes[i][0]},${maxY+minY-nodes[i][1]}`).join(" ");
    return `<polygon points="${pts}" fill="#173a2a" stroke="#4aa3ff" stroke-width="${0.004*Math.max(w,h)}"/>`;
  }).join("");
  svg.innerHTML = polys;
}

async function run() {
  const cfg = readCfg(); if (!cfg) return;
  status(I18N[lang].running);
  $("run").disabled = true;
  try {
    const r = await fetch("/api/run", {
      method:"POST", headers:{"Content-Type":"application/json"},
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
  const isDam = cfg.loading && cfg.loading.mode === "hydraulic";
  const x = curve.control.map(Math.abs);
  Plotly.newPlot("curve", [
    { x, y: curve.load, mode:"lines+markers", name: isDam ? "ux crest" : "P",
      line:{color:"#4aa3ff"} },
    { x, y: curve.dmax, mode:"lines", name:"dmax", yaxis:"y2",
      line:{color:"#ff9a4a", dash:"dot"} },
  ], {
    margin:{t:10,r:50,b:40,l:55}, paper_bgcolor:"#16212e", plot_bgcolor:"#0c141d",
    font:{color:"#e7eef6"},
    xaxis:{ title: isDam ? "H" : "|δ|", gridcolor:"#25364a" },
    yaxis:{ title: isDam ? "ux crest" : "P", gridcolor:"#25364a" },
    yaxis2:{ title:"dmax", overlaying:"y", side:"right", range:[0,1] },
    legend:{orientation:"h"},
  }, {displaylogo:false, responsive:true});
}

function showSummary(s) {
  const fmt = v => (typeof v === "number" ? v.toExponential(4) : v);
  const rows = Object.entries(s).map(([k,v]) => `<div>${k}</div><div>${fmt(v)}</div>`);
  $("summary").innerHTML = rows.join("");
}

document.addEventListener("click", e => {
  const t = e.target;
  if (t.id === "lang") { lang = lang === "es" ? "en" : "es"; applyI18n(); }
  if (t.id === "preview") preview();
  if (t.id === "run") run();
  if (t.dataset && t.dataset.load) loadExample(t.dataset.load);
});

applyI18n();
loadExample("beam");
