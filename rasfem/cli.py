"""Command-line interface: ``rasfem run config.yaml``.

Subcommands:
    run <config>      run an analysis from a ficha de datos (YAML/JSON)
    examples [dir]    write the bundled example configs to a folder
    validate <config> load + validate a config and print the resolved values
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

EXAMPLES = {
    "viga_rilem.yaml": "beam",
    "presa_ras.yaml": "dam",
}


def _cmd_run(args):
    from .config import load_config
    from .run import run_config

    cfg = load_config(args.config)

    def progress(step, control, load, dmax):
        if step % 10 == 0 or step == 1:
            print(f"  step {step:4d}  control={control:+.5e}  load={load:12.3f}  dmax={dmax:.4f}")

    print(f"[rasfem] running '{cfg.name}' ({cfg.loading.mode} control, "
          f"{cfg.problem.element_type})")
    info = run_config(cfg, out_dir=args.out, progress=progress)
    s = info["summary"]
    print(f"[rasfem] done. accepted={s['accepted']} rejected={s['rejected']}")
    if "load_max" in s:
        print(f"[rasfem] load_max={s['load_max']:.3f}  "
              f"control@max={s['control_at_load_max']:.5e}  dmax={s['dmax_final']:.5f}")
    print(f"[rasfem] results in: {info['out_dir']}")


def _cmd_examples(args):
    src = Path(__file__).resolve().parent.parent / "examples"
    dst = Path(args.dir)
    dst.mkdir(parents=True, exist_ok=True)
    for name in EXAMPLES:
        f = src / name
        if f.exists():
            (dst / name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"wrote {dst / name}")


def _cmd_validate(args):
    from .config import load_config
    cfg = load_config(args.config)
    print(cfg.model_dump_json(indent=2))


def main(argv=None):
    p = argparse.ArgumentParser(prog="rasfem", description="2D FEM for concrete with ASR/RAS")
    sub = p.add_subparsers(dest="command", required=True)

    pr = sub.add_parser("run", help="run an analysis from a config file")
    pr.add_argument("config")
    pr.add_argument("--out", default=None, help="output directory (overrides config)")
    pr.set_defaults(func=_cmd_run)

    pe = sub.add_parser("examples", help="write bundled example configs")
    pe.add_argument("dir", nargs="?", default="examples_rasfem")
    pe.set_defaults(func=_cmd_examples)

    pv = sub.add_parser("validate", help="validate and print a config")
    pv.add_argument("config")
    pv.set_defaults(func=_cmd_validate)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
