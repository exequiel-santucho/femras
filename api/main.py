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

The run is synchronous for this MVP; long analyses block the request. A job
queue with progress streaming (SSE/WebSocket) is the next step, plus the
graphical canvas pre-processor that posts to /api/mesh_preview and /api/run.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
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


@app.get("/api/example/{name}")
def example(name: str):
    files = {"beam": "viga_rilem.yaml", "dam": "presa_ras.yaml"}
    if name not in files:
        raise HTTPException(404, "unknown example")
    cfg = load_config(EXAMPLES / files[name])
    return JSONResponse(cfg.model_dump())


@app.post("/api/run")
def run(cfg_dict: dict):
    try:
        cfg = Config.model_validate(cfg_dict)
    except Exception as e:  # validation error
        raise HTTPException(422, f"invalid config: {e}")
    cfg.output.save_figures = False  # the web plots the curve itself
    with tempfile.TemporaryDirectory() as tmp:
        info = run_config(cfg, out_dir=tmp)
    r = info["result"]
    return {
        "summary": info["summary"],
        "curve": {
            "control": [float(x) for x in r.control],
            "load": [float(x) for x in r.load],
            "dmax": [float(x) for x in r.max_damage],
        },
    }


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
