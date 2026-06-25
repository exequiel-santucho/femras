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
    ax.set_title("Curva")
    ax.grid(True)
    fig.tight_layout()
    fig.savefig(out_dir / "curva.png", dpi=dpi)
    plt.close(fig)

    # damage map
    dmg = element_damage(state)
    _map(plt, out_dir / "mapa_dano.png", nodes, elements, dmg, "Daño / Damage", dpi)

    # stress sigma_x map
    stress = element_stress(assembler, model, U, state)
    _map(plt, out_dir / "mapa_sigma_x.png", nodes, elements, stress[:, 0],
         "sigma_x [MPa]", dpi)


def _map(plt, path, nodes, elements, values, label, dpi):
    fig, ax = plt.subplots()
    vmin, vmax = float(values.min()), float(values.max())
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
