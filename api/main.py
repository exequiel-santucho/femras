"""Local web API (FastAPI) exposing the femras core.

Run with:
    pip install -e ".[web]"
    uvicorn api.main:app --reload
    # open http://127.0.0.1:8000

Endpoints
---------
GET  /                       serve the single-page app
GET  /api/example/{name}     return a bundled example config (beam|dam) as JSON
POST /api/run                run an analysis from a config dict -> summary + curve
POST /api/mesh_preview       mesh a geometry -> nodes/elements (canvas preview)
POST /api/to_yaml            convert a config dict to YAML text for download

The run is synchronous for this MVP; long analyses block the request. A job
queue with progress streaming (SSE/WebSocket) is the next step.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel

from femras.config import Config, load_config
from femras.run import run_config

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
EXAMPLES = ROOT / "examples"

app = FastAPI(title="femras", version="0.1.0")


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


@app.get("/style.css")
def stylecss():
    return FileResponse(WEB / "style.css", media_type="text/css")


@app.get("/app.js")
def appjs():
    return FileResponse(WEB / "app.js", media_type="application/javascript")


@app.get("/editor.js")
def editorjs():
    return FileResponse(WEB / "editor.js", media_type="application/javascript")


@app.get("/results.js")
def resultsjs():
    return FileResponse(WEB / "results.js", media_type="application/javascript")


@app.get("/api/example/{name}")
def example(name: str):
    files = {"beam": "viga_rilem.yaml", "dam": "presa_ras.yaml"}
    if name not in files:
        raise HTTPException(404, "unknown example")
    cfg = load_config(EXAMPLES / files[name])
    return JSONResponse(cfg.model_dump())


RESULTS_DIR = ROOT / "resultados_femras"


def _safe_name(name: str) -> str:
    """Filesystem-safe case name."""
    keep = "-_."
    s = "".join(c if (c.isalnum() or c in keep) else "_" for c in (name or "caso"))
    return s.strip("_. ") or "caso"


@app.post("/api/run")
def run(cfg_dict: dict):
    try:
        cfg = Config.model_validate(cfg_dict)
    except Exception as e:  # validation error
        raise HTTPException(422, f"invalid config: {e}")

    # Persist each run to resultados_femras/<name>_<timestamp>/ so nothing is lost.
    # run_config joins out_dir / cfg.name, so set cfg.name to the stamped folder
    # and out_dir to RESULTS_DIR → final dir = resultados_femras/<name>_<timestamp>.
    from datetime import datetime
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    case = _safe_name(cfg.name)
    cfg.name = f"{case}_{stamp}"
    cfg.output.save_figures = True  # also write PNGs for reports
    cfg.output.save_tables = True
    info = run_config(cfg, out_dir=RESULTS_DIR)

    r = info["result"]
    out_dir = Path(info["out_dir"])
    figures = sorted(p.name for p in out_dir.glob("*.png"))
    return {
        "summary": info["summary"],
        "curve": {
            "control": [float(x) for x in r.control],
            "load": [float(x) for x in r.load],
            "dmax": [float(x) for x in r.max_damage],
        },
        "fields": info.get("fields"),
        "out_dir": str(out_dir),
        "result_dir": out_dir.name,
        "figures": figures,
    }


@app.get("/api/results/{run_dir}/{filename}")
def result_file(run_dir: str, filename: str):
    """Serve a saved result file (PNG/CSV/JSON) from a run folder."""
    safe_run = _safe_name(run_dir)
    safe_file = Path(filename).name  # strip any path components
    path = RESULTS_DIR / safe_run / safe_file
    if not path.exists() or not path.is_file():
        raise HTTPException(404, "file not found")
    return FileResponse(path)


class GeometryPayload(BaseModel):
    cfg: dict


@app.post("/api/mesh_preview")
def mesh_preview(payload: GeometryPayload):
    """Return nodes/elements for the geometry so the canvas can draw the mesh."""
    cfg = Config.model_validate(payload.cfg)
    geo = cfg.geometry
    if geo.kind == "beam":
        from femras.mesh.structured import notched_beam_mesh
        nodes, elements, _ = notched_beam_mesh(geo.L, geo.H, geo.nx, geo.ny,
                                               geo.notch_width, geo.notch_height)
    else:
        from femras.mesh.polygon import conforming_t3_mesh
        nodes, elements = conforming_t3_mesh(np.asarray(geo.vertices, float), geo.mesh_size)
    return {"nodes": nodes.tolist(), "elements": elements.tolist(),
            "element_type": cfg.problem.element_type}


@app.post("/api/to_yaml")
def to_yaml(cfg_dict: dict):
    """Validate a config dict and return it as YAML text (for client-side download)."""
    try:
        cfg = Config.model_validate(cfg_dict)
    except Exception as e:
        raise HTTPException(422, f"invalid config: {e}")
    text = yaml.safe_dump(cfg.model_dump(), allow_unicode=True, sort_keys=False,
                          default_flow_style=False)
    return PlainTextResponse(text, media_type="text/yaml")
