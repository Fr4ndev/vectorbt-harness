"""
config.py — harness defaults and strategy registry.

Every strategy family registers its compute() entry point here so the runner
can dispatch by name. Defaults per family are held in PARAMS and can be
overridden per-run.
"""
from __future__ import annotations

import importlib

# strategy-id -> (module path, compute mapping)
# The runner resolves `signals.<family>.<module>` and calls compute() with the
# strategy/intercommunal params from PARAMS[family].
REGISTRY: dict[str, dict] = {
    "demon1": {
        "module": "signals.demon1.demon1",
        "tf": "1h",
        "exit": "split",
    },
    "demon2": {
        "module": "signals.demon2.demon2",
        "tf": "4h",
        "exit": "split",
        "strategies": [
            "continuation_bias", "po3", "power_flow", "weekly_bias", "abc",
            "mmxm", "ote_tbr", "liquidity_trap", "ifvg", "silver_bullet",
        ],
    },
    "demon2volumen": {
        "module": "signals.demon2volumen.demon2volumen",
        "tf": "4h",
        "exit": "split",
        "strategies": ["liquidity_sweep_bot"],
    },
    "ictquantum": {
        "module": "signals.ictquantum.ictquantum",
        "tf": "1h",
        "exit": "simple",
        "versions": ["v9", "v9.5", "v10", "v11"],
    },
    "ict4hsweep": {
        "module": "signals.ict4hsweep.ict4hsweep",
        "tf": "4h",
        "exit": "split",
        "tiers": ["1M", "1W", "1d", "4h", "1h"],
    },
    "ictsuite": {
        "module": "signals.ictsuite.ictsuite",
        "tf": "4h",
        "exit": "split",
        "strategies": ["scalp_sweep", "intraday_quantum", "macro_swing", "sfp"],
    },
    "fib_retrace": {
        "module": "signals.fib_retrace.fib_retrace",
        "tf": "1h",
        "exit": "split",
        "strategies": ["fib_retrace", "fib_htf"],
    },
    "fvg_mtf": {
        "module": "signals.fvg_mtf.fvg_mtf",
        "tf": "30m",
        "exit": "split",
        "strategies": ["ifvg", "fvg"],
    },
}

# Default exit scheme (from the user's spec)
EXIT_DEFAULTS = {
    "rr_tp1": 2.0,     # 80% at 1:2
    "rr_runner": 5.0,  # 20% runner to 1:5
    "weight_tp1": 0.8, # split
    "fees": 0.0006,
    "slippage": 0.0003,
    "init_cash": 10000.0,
    "size": 1.0,
}


def get_strategy_module(family: str, module_path: str | None = None):
    """Import and return a strategy module by family name."""
    path = module_path or REGISTRY[family]["module"]
    return importlib.import_module(path)


def list_strategies() -> list[str]:
    """Return a flat list of runnable strategy ids."""
    ids = []
    for fam, cfg in REGISTRY.items():
        inner = cfg.get("strategies") or cfg.get("versions") or cfg.get("tiers")
        ids += [f"{fam}:{i}" for i in inner] if inner else [fam]
    return ids