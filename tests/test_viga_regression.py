"""Regression test for the beam (displacement control).

Locks the refactored core against a deterministic coarse-mesh snapshot so future
changes cannot silently alter the mechanical response. The full-mesh case
matches the legacy script examples/legacy/viga_rilem.py (see docs).
"""

import numpy as np

from rasfem.config import load_config
from rasfem.run import run_config

EXAMPLE = "examples/viga_rilem.yaml"


def _coarse_cfg():
    cfg = load_config(EXAMPLE)
    cfg.geometry.nx = 40
    cfg.geometry.ny = 10
    cfg.loading.target = -0.06
    cfg.name = "reg"
    cfg.output.save_figures = False
    cfg.output.save_tables = False
    return cfg


def test_beam_snapshot(tmp_path):
    cfg = _coarse_cfg()
    info = run_config(cfg, out_dir=str(tmp_path))
    s = info["summary"]

    # ASR reaction extent at 300 days (Larive) -> frozen xi
    assert abs(s["xi"] - 0.56096) < 1e-3
    # deterministic snapshot of the mechanical response
    assert s["accepted"] == 41
    assert abs(s["load_max"] - 1600.58) < 5.0          # N
    assert abs(s["control_at_load_max"] - (-0.06)) < 1e-6
    assert 0.85 < s["dmax_final"] < 0.95


def test_beam_monotonic_damage():
    cfg = _coarse_cfg()
    info = run_config(cfg, out_dir="_pytest_tmp")
    dmax = info["result"].max_damage
    # damage is irreversible -> non-decreasing along the loading history
    assert np.all(np.diff(dmax) >= -1e-9)
