"""Post-processing: element fields, curves, maps and result files.

Backend-agnostic (matplotlib used lazily so the core import stays light). Ported
from the save_* helpers of the legacy scripts but driven by the unified state.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

from .damage import GPState
from .elements.base import ElementData


def element_damage(state: GPState) -> np.ndarray:
    """Max total damage over the Gauss points of each element."""
    if state.damage_t.size == 0:
        return np.zeros(0)
    d = 1.0 - (1.0 - state.damage_t) * (1.0 - state.damage_c)
    return d.max(axis=1)


def element_damage_tension(state: GPState) -> np.ndarray:
    return state.damage_t.max(axis=1) if state.damage_t.size else np.zeros(0)


def element_stress(assembler, model, U, state) -> np.ndarray:
    """Average stress per element (n_elem, 3) at the converged state."""
    strain = assembler.strains(U)
    sigma, _d, _s = model.evaluate(strain, state)
    return sigma.mean(axis=1)


def element_stress_components(assembler, model, U, state):
    """(sigma_x, sigma_y, tau_xy) per element at the converged state."""
    s = element_stress(assembler, model, U, state)
    return s[:, 0], s[:, 1], s[:, 2]


# --------------------------------------------------------------------------
# Saving
# --------------------------------------------------------------------------

def save_tables(out_dir: Path, result, control_label="control", load_label="load"):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # incremental step table
    with open(out_dir / "tabla_incremental.csv", "w", newline="", encoding="utf-8") as f:
        if result.step_table:
            w = csv.DictWriter(f, fieldnames=list(result.step_table[0].keys()))
            w.writeheader()
            w.writerows(result.step_table)
    # control-load curve
    with open(out_dir / "curva.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([control_label, load_label, "dmax"])
        for c, l, d in zip(result.control, result.load, result.max_damage):
            w.writerow([c, l, d])


def save_summary(out_dir: Path, cfg, result, extra: dict | None = None):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {"name": cfg.name, "accepted": result.accepted, "rejected": result.rejected}
    if result.load.size:
        k = int(np.argmax(result.load))
        summary.update(load_max=float(result.load[k]),
                       control_at_load_max=float(result.control[k]),
                       control_final=float(result.control[-1]),
                       dmax_final=float(result.max_damage[-1]))
    if extra:
        summary.update(extra)
    with open(out_dir / "resumen.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    return summary


def save_figures(out_dir: Path, nodes, elements, result, assembler, model,
                 dpi=200, control_label="control |u|", load_label="P"):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    state, U = result.state, result.U_final

    # control-load curve
    fig, ax = plt.subplots()
    ax.plot(np.abs(result.control), result.load, "o-", lw=1.4, ms=3)
    ax.set_xlabel(control_label)
    ax.set_ylabel(load_label)
    ax.set_title("Curva carga-desplazamiento")
    ax.grid(True)
    fig.tight_layout()
    fig.savefig(out_dir / "curva.png", dpi=dpi)
    plt.close(fig)

    # max-damage evolution curve
    if result.max_damage.size:
        fig, ax = plt.subplots()
        ax.plot(np.abs(result.control), result.max_damage, "o-", lw=1.4, ms=3,
                color="#c0392b")
        ax.set_xlabel(control_label)
        ax.set_ylabel("daño máximo")
        ax.set_title("Evolución del daño máximo")
        ax.set_ylim(0, 1)
        ax.grid(True)
        fig.tight_layout()
        fig.savefig(out_dir / "curva_dano.png", dpi=dpi)
        plt.close(fig)

    # damage map (final)
    dmg = element_damage(state)
    _map(plt, out_dir / "mapa_dano.png", nodes, elements, dmg, "Daño (final)", dpi,
         vmin=0.0, vmax=1.0)

    # damage map (initial) — from first captured snapshot, if any
    if result.snapshots:
        dmg0 = np.asarray(result.snapshots[0]["damage"], float)
        if dmg0.size:
            _map(plt, out_dir / "mapa_dano_inicial.png", nodes, elements, dmg0,
                 "Daño (inicial)", dpi, vmin=0.0, vmax=1.0)

    # stress maps (final)
    stress = element_stress(assembler, model, U, state)
    _map(plt, out_dir / "mapa_sigma_x.png", nodes, elements, stress[:, 0],
         "sigma_x [MPa]", dpi)
    _map(plt, out_dir / "mapa_sigma_y.png", nodes, elements, stress[:, 1],
         "sigma_y [MPa]", dpi)

    # deformed shape (final), auto-scaled
    _deformed(plt, out_dir / "deformada.png", nodes, elements, U, dpi)


def _deformed(plt, path, nodes, elements, U, dpi):
    """Deformed mesh overlaid on the undeformed outline, auto scale factor."""
    u = U.reshape(-1, 2)
    span = float(max(np.ptp(nodes[:, 0]), np.ptp(nodes[:, 1]))) or 1.0
    umax = float(np.abs(u).max()) or 1e-12
    scale = 0.08 * span / umax  # deform ~8% of the model span
    defn = nodes + scale * u
    fig, ax = plt.subplots()
    for conn in elements:
        xy0 = nodes[conn, :]
        ax.fill(xy0[:, 0], xy0[:, 1], color="none", edgecolor="#b0b0b0", lw=0.2)
        xy = defn[conn, :]
        ax.fill(xy[:, 0], xy[:, 1], color="#2980b9", alpha=0.25,
                edgecolor="#1f5f8b", lw=0.2)
    ax.axis("equal")
    ax.set_title(f"Deformada (×{scale:.3g})")
    fig.tight_layout()
    fig.savefig(path, dpi=dpi)
    plt.close(fig)


def _map(plt, path, nodes, elements, values, label, dpi, vmin=None, vmax=None):
    fig, ax = plt.subplots()
    if vmin is None:
        vmin = float(values.min())
    if vmax is None:
        vmax = float(values.max())
    rng = vmax - vmin
    for e, conn in enumerate(elements):
        xy = nodes[conn, :]
        c = 0.5 if abs(rng) < 1e-15 else (values[e] - vmin) / rng
        ax.fill(xy[:, 0], xy[:, 1], color=plt.cm.viridis(c), edgecolor="k", lw=0.1)
    sm = plt.cm.ScalarMappable(cmap="viridis")
    sm.set_array(values)
    sm.set_clim(vmin, vmax)
    fig.colorbar(sm, ax=ax, label=label)
    ax.axis("equal")
    ax.set_title(label)
    fig.tight_layout()
    fig.savefig(path, dpi=dpi)
    plt.close(fig)


# --------------------------------------------------------------------------
# Field export for the interactive results viewer
# --------------------------------------------------------------------------

def fields_payload(nodes, elements, result, assembler=None, model=None) -> dict:
    """JSON-serialisable mesh + per-snapshot fields for the web results viewer.

    Each snapshot carries the nodal displacement ``U`` (flat, 2·n_nodes) and the
    per-element ``stress`` (σx, σy, τxy) and ``damage``. If the run captured no
    snapshots, a single final snapshot is synthesised from ``result``.
    """
    nodes = np.asarray(nodes, float)
    elements = np.asarray(elements, int)

    snaps = list(result.snapshots)
    if not snaps and assembler is not None and model is not None:
        snaps = [_field_snapshot_from_result(assembler, model, result)]
    snaps = _downsample(snaps, 16)

    out_snaps = []
    for s in snaps:
        stress = np.asarray(s["stress"], float)
        damage = np.asarray(s["damage"], float)
        out_snaps.append({
            "control": float(s["control"]),
            "load": float(s["load"]),
            "dmax": float(s.get("dmax", float(damage.max()) if damage.size else 0.0)),
            "U": [round(float(v), 6) for v in np.asarray(s["U"], float).ravel()],
            "sigma_x": [round(float(v), 4) for v in stress[:, 0]] if stress.size else [],
            "sigma_y": [round(float(v), 4) for v in stress[:, 1]] if stress.size else [],
            "damage": [round(float(v), 5) for v in damage] if damage.size else [],
        })

    return {
        "nodes": [[round(float(x), 4), round(float(y), 4)] for x, y in nodes],
        "elements": [[int(i) for i in conn] for conn in elements],
        "snapshots": out_snaps,
        "curve": {
            "control": [float(c) for c in result.control],
            "load": [float(l) for l in result.load],
            "dmax": [float(d) for d in result.max_damage],
        },
    }


def _downsample(items, max_count):
    """Keep at most ``max_count`` items, evenly spaced, always incl. first & last."""
    n = len(items)
    if n <= max_count:
        return items
    idx = np.unique(np.linspace(0, n - 1, max_count).round().astype(int))
    return [items[i] for i in idx]


def _field_snapshot_from_result(assembler, model, result) -> dict:
    stress = element_stress(assembler, model, result.U_final, result.state)
    damage = element_damage(result.state)
    return {"control": float(result.control[-1]) if result.control.size else 0.0,
            "load": float(result.load[-1]) if result.load.size else 0.0,
            "dmax": float(damage.max()) if damage.size else 0.0,
            "U": result.U_final, "stress": stress, "damage": damage}


def save_fields(out_dir: Path, nodes, elements, result, assembler=None, model=None):
    """Persist the interactive-viewer payload as JSON next to the figures."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = fields_payload(nodes, elements, result, assembler, model)
    with open(out_dir / "campos.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    return payload
