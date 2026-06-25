"""Time-multiplier functions ``lambda(t)`` for load histories.

A time multiplier scales a reference edge load along a pseudo-time axis ``t``.
It can be defined two ways (see :class:`~rasfem.config.TimeFunctionCfg`):

* a piecewise-linear table of ``[t, value]`` points, or
* an expression string such as ``"10*sin(2*pi*t)"``.

Expressions are evaluated in a sandbox: only a whitelist of math names is
exposed and Python builtins are removed, so an untrusted ficha de datos cannot
reach the filesystem or import modules.  Both forms return a plain ``float``.
"""

from __future__ import annotations

import math
from typing import Callable, List, Optional, Sequence

import numpy as np

# Whitelisted names available inside a time-function expression.
_ALLOWED = {
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan, "atan2": math.atan2,
    "sinh": math.sinh, "cosh": math.cosh, "tanh": math.tanh,
    "exp": math.exp, "log": math.log, "log10": math.log10, "sqrt": math.sqrt,
    "abs": abs, "min": min, "max": max, "pow": pow,
    "floor": math.floor, "ceil": math.ceil, "fmod": math.fmod,
    "pi": math.pi, "e": math.e, "tau": math.tau,
}


def _compile_expr(expr: str) -> Callable[[float], float]:
    code = compile(expr, "<timefunc>", "eval")
    for name in code.co_names:
        if name not in _ALLOWED and name != "t":
            raise ValueError(
                f"name '{name}' is not allowed in a time function expression; "
                f"allowed names: {', '.join(sorted(_ALLOWED))}, t"
            )
    env = {"__builtins__": {}, **_ALLOWED}

    def lam(t: float) -> float:
        return float(eval(code, env, {"t": float(t)}))

    return lam


def _table_interpolator(points: Sequence[Sequence[float]]) -> Callable[[float], float]:
    pts = sorted(([float(t), float(v)] for t, v in points), key=lambda p: p[0])
    ts = np.array([p[0] for p in pts], float)
    vs = np.array([p[1] for p in pts], float)

    def lam(t: float) -> float:
        # np.interp clamps to the endpoints outside [ts[0], ts[-1]].
        return float(np.interp(float(t), ts, vs))

    return lam


def make_time_multiplier(points: Optional[List[List[float]]] = None,
                         expr: Optional[str] = None) -> Callable[[float], float]:
    """Build a callable ``lambda(t) -> float``.

    ``expr`` takes precedence over ``points``.  If neither is given, the
    multiplier is the constant 1.0 (i.e. the reference load is applied as-is).
    """
    if expr:
        return _compile_expr(expr)
    if points:
        return _table_interpolator(points)
    return lambda t: 1.0
