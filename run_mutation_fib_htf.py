#!/usr/bin/env python
"""
run_mutation_fib_htf.py — in-sample mutation loop for fib_htf v4.

fib_htf (v4): swing detected on HTF (resampled), entry on LTF.
Faithful to ccxtv4 action server's tf_high parameter.

Discipline:
  - ALL mutations on the IS (70%) slice only.
  - Candidate: mean>0, prof>=50%, n>=30 per profitable cell -> SINGLE OOS check.
  - The grid is generic/hypothesis-driven, NOT biased by full-365d diagnostics.

Run from harness root:
    ~/Escritorio/ccxtv2/venv/bin/python run_mutation_fib_htf.py
"""
from __future__ import annotations

import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, ".")

import numpy as np
import pandas as pd

from data import loader
from portfolio import engine, exits
from signals.fib_retrace.fib_retrace import compute
from run_profit_map import _combined_return

SYMBOLS = ["BTC", "ETH"]
TIMEFRAMES = ["1h", "2h", "4h", "1d"]
DAYS = 365
IS_RATIO = 0.70
MAX_ITER = 20
PATIENCE = 6
CANDIDATE_MIN_N = 30


def run_one_cell(df, tf, params):
    """Run fib_htf on a single cell, return (n, combined_return, legA_ret, legB_ret)."""
    sig = compute(df, strategy="fib_htf", **params)
    entries = sig["entries"].fillna(False).astype(bool)
    shorts = sig["short_entries"].fillna(False).astype(bool)
    n = int(entries.sum() + shorts.sum())
    if not n:
        return 0, float("nan"), float("nan"), float("nan")
    direction = sig["dir"]
    brackets = exits.build_native_brackets(
        entry=df["close"], sl=sig["sl"],
        tp1=sig.get("tp1", pd.Series(np.nan, index=df.index)),
        tp2=sig.get("tp2", pd.Series(np.nan, index=df.index)),
        direction=direction,
        weight_tp1=float(sig.get("weight_tp1", 0.7)),
    )
    res = engine.run(df, entries=entries, short_entries=shorts,
                     brackets=brackets, mode="split", freq=tf)
    cr, cwr, ra, rb, wa, wb = _combined_return(res)
    return n, cr, ra, rb


def eval_variant(dfs, params):
    rows = []
    for sym, tf, df in dfs:
        n, cr, ra, rb = run_one_cell(df, tf, params)
        if n > 0:
            rows.append({"sym": sym, "tf": tf, "n": n, "ret": cr,
                         "legA": ra, "legB": rb})
    if not rows:
        return {"mean": float("-inf"), "prof": 0, "total_n": 0, "cells": 0,
                "n_below30": 0}
    s = pd.DataFrame(rows)
    return {"mean": s["ret"].mean(), "prof": int((s["ret"] > 0).sum()),
            "total_n": int(s["n"].sum()), "cells": len(s),
            "n_below30": int((s["n"] < CANDIDATE_MIN_N).sum()),
            "detail": rows}


def is_candidate(v):
    if v["mean"] <= 0 or v["cells"] == 0:
        return False
    if v["prof"] / v["cells"] < 0.5:
        return False
    if v["total_n"] < CANDIDATE_MIN_N:
        return False
    for r in v.get("detail", []):
        if r["ret"] > 0 and r["n"] < CANDIDATE_MIN_N:
            return False
    return True


def main():
    dfs_is, dfs_oos = [], []
    for sym in SYMBOLS:
        for tf in TIMEFRAMES:
            df = loader.load(symbol=sym, timeframe=tf, days=DAYS, cache=True)
            cut = int(len(df) * IS_RATIO)
            dfs_is.append((sym, tf, df.iloc[:cut]))
            dfs_oos.append((sym, tf, df.iloc[cut:]))

    baseline = eval_variant(dfs_is, {})
    print("=== BASELINE fib_htf v4 (defaults) IS ===")
    print(f"  mean={baseline['mean']:.2f}% prof={baseline['prof']}/{baseline['cells']} n={baseline['total_n']}")
    for r in baseline.get("detail", []):
        print(f"    {r['sym']}:{r['tf']} ret={r['ret']:+.2f}% n={r['n']} legA={r['legA']:+.2f}% legB={r['legB']:+.2f}%")

    mutations = [
        # entry levels
        ("entry_618",     {"entry_levels": [0.618]}),
        ("entry_786",     {"entry_levels": [0.618, 0.786]}),
        ("entry_382",     {"entry_levels": [0.382, 0.5]}),
        ("entry_5only",   {"entry_levels": [0.5]}),
        # swing window
        ("swing_1",       {"swing_window": 1}),
        ("swing_3",       {"swing_window": 3}),
        # exits
        ("exit_c05",      {"exit_cons": 0.5}),
        ("exit_c066",     {"exit_cons": 0.66}),
        ("exit_cl1618",   {"exit_classic": 1.618}),
        ("exit_cl20",     {"exit_classic": 2.0}),
        ("wt08",          {"weight_tp1": 0.8}),
        # confluence
        ("mc3",           {"min_confluence": 3}),
        ("mc1",           {"min_confluence": 1}),
        # impulse/volume
        ("atr20",         {"atr_mult": 2.0}),
        ("novol",         {"vol_mult": 0}),
        # invalidation
        ("inval_005",     {"invalidation": 0.05}),
        ("inval_02",      {"invalidation": 0.20}),
        # combos
        ("entry786+mc3",  {"entry_levels": [0.618, 0.786], "min_confluence": 3}),
        ("entry786+wt08",  {"entry_levels": [0.618, 0.786], "weight_tp1": 0.8}),
        ("swing3+exit066", {"swing_window": 3, "exit_cons": 0.66}),
    ]

    best_is = baseline
    best_name = "baseline"
    best_params = {}
    no_improve = 0
    candidate = None

    print(f"\n{'='*80}")
    print(f"MUTATION LOOP — fib_htf v4 (IS only, {int(IS_RATIO*100)}% of {DAYS}d)")
    print(f"Candidate threshold: mean>0, prof>=50%, n>=30 per cell")
    print(f"{'='*80}\n")

    for i, (name, params) in enumerate(mutations[:MAX_ITER], 1):
        res = eval_variant(dfs_is, params)
        improved = res["mean"] > best_is["mean"]
        marker = " <<<" if improved else ""
        print(f"[{i:2d}/{MAX_ITER}] {name:24s} mean={res['mean']:8.2f}% prof={res['prof']}/{res['cells']} n={res['total_n']:5d} n<30={res['n_below30']}{marker}")

        if improved:
            best_is, best_name, best_params = res, name, params
            no_improve = 0
        else:
            no_improve += 1

        if is_candidate(res):
            if candidate is None or res["mean"] > candidate["mean"]:
                candidate = {"name": name, "params": params, **res}
                print(f"        ^ CANDIDATO: mean={res['mean']:.2f}% prof={res['prof']}/{res['cells']} n={res['total_n']}")

        if no_improve >= PATIENCE:
            print(f"\n  Patience ({PATIENCE}) agotado tras {i} iteraciones. Mejor: {best_name}")
            break

    print(f"\n{'='*80}")
    print(f"RESULTADO IS — fib_htf v4")
    print(f"  Mejor variante: {best_name} | {best_params}")
    print(f"  IS: mean={best_is['mean']:.2f}% prof={best_is['prof']}/{best_is['cells']} n={best_is['total_n']}")
    for r in best_is.get("detail", []):
        print(f"    {r['sym']}:{r['tf']} ret={r['ret']:+.2f}% n={r['n']} legA={r['legA']:+.2f}% legB={r['legB']:+.2f}%")

    if candidate:
        print(f"\n  CANDIDATO FINAL: {candidate['name']} (mean={candidate['mean']:.2f}% n={candidate['total_n']})")
        print(f"\n--- OOS CHECK (single shot, one-shot rule) ---")
        oos = eval_variant(dfs_oos, candidate["params"])
        print(f"  OOS: mean={oos['mean']:.2f}% prof={oos['prof']}/{oos['cells']} n={oos['total_n']}")
        for r in oos.get("detail", []):
            print(f"    {r['sym']}:{r['tf']} ret={r['ret']:+.2f}% n={r['n']} legA={r['legA']:+.2f}% legB={r['legB']:+.2f}%")
        oos_pass = oos["mean"] > 0 and oos["prof"] / max(oos["cells"], 1) >= 0.5
        print(f"\n  OOS PASS: {oos_pass}")
        if oos_pass:
            print(f"  >>> CANDIDATO APROBADO PARA DEPLOY <<<")
        else:
            print(f"  >>> FALLO OOS — DESCARTADO <<<")
    else:
        print(f"\n  NO CANDIDATO IS-profitable con n>=30 tras {min(len(mutations), MAX_ITER)} mutaciones.")
        print(f"  FAMILIA: DESCARTADA (mejor: {best_name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
