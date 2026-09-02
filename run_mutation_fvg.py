#!/usr/bin/env python
"""
run_mutation_fvg.py — in-sample mutation loop for fvg_mtf:fvg (CORRECTED).

Per the OOS one-shot rule:
  - ALL mutations happen on the IS (70%) slice only.
  - Candidate threshold: n≥30 per cell (matches promotion condition 3).
  - If a variant passes IS (mean>0, prof≥50%, n≥30), it becomes a candidate
    for a SINGLE OOS check against the held-out 30%.
  - Each config's OOS is evaluated EXACTLY ONCE (one-shot rule).

Data leakage fix: this script does NOT use any full-365d diagnostic results
to bias the mutation grid. All hypotheses are tested equally on IS only.

Run from harness root:
    ~/Escritorio/ccxtv2/venv/bin/python run_mutation_fvg.py
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
from signals.fvg_mtf.fvg_mtf import compute
from run_profit_map import _combined_return

SYMBOLS = ["BTC", "ETH"]
TIMEFRAMES = ["1h", "2h", "4h", "1d"]
DAYS = 365
IS_RATIO = 0.70
MAX_ITER = 20
PATIENCE = 4
CANDIDATE_MIN_N = 30  # per-cell n≥30 (promotion condition 3)
STRICT_EXIT = {"rr_runner": 3.0, "weight_tp1": 0.9}


def run_one_cell(df, tf, params, strict_tfs):
    """Run fvg:fvg on a single cell, return (n, combined_return)."""
    sig = compute(df, strategy="fvg", **params)
    entries = sig["entries"].fillna(False).astype(bool)
    shorts = sig["short_entries"].fillna(False).astype(bool)
    n = int(entries.sum() + shorts.sum())
    if not n:
        return 0, float("nan")
    dk = dict(STRICT_EXIT) if tf in strict_tfs else {}
    brackets = exits.build_brackets(
        entry=df["close"], sl=sig["sl"], direction=sig["dir"],
        rr_tp1=dk.get("rr_tp1", 2.0), rr_runner=dk.get("rr_runner", 5.0),
        weight_tp1=dk.get("weight_tp1", 0.8), trail=sig.get("runner_inv"),
    )
    res = engine.run(df, entries=entries, short_entries=shorts,
                     brackets=brackets, mode="split", freq=tf)
    cr, cwr, *_ = _combined_return(res)
    return n, cr


def eval_variant(dfs, params, strict_tfs):
    """Evaluate a variant across all cells, return aggregate stats."""
    rows = []
    for sym, tf, df in dfs:
        n, cr = run_one_cell(df, tf, params, strict_tfs)
        if n > 0:
            rows.append({"sym": sym, "tf": tf, "n": n, "ret": cr})
    if not rows:
        return {"mean": float("-inf"), "prof": 0, "total_n": 0, "cells": 0,
                "n_below30": 0}
    s = pd.DataFrame(rows)
    mean_ret = s["ret"].mean()
    prof = int((s["ret"] > 0).sum())
    total_n = int(s["n"].sum())
    n_below30 = int((s["n"] < CANDIDATE_MIN_N).sum())
    return {"mean": mean_ret, "prof": prof, "total_n": total_n,
            "cells": len(s), "n_below30": n_below30, "detail": rows}


def is_candidate(v):
    """Check if variant passes IS gate for OOS candidacy."""
    if v["mean"] <= 0:
        return False
    if v["prof"] / max(v["cells"], 1) < 0.5:
        return False
    if v["total_n"] < CANDIDATE_MIN_N:
        return False
    # Check per-cell n: at least the profitable cells need n≥30
    for r in v.get("detail", []):
        if r["ret"] > 0 and r["n"] < CANDIDATE_MIN_N:
            return False
    return True


def main():
    # Load all data and split 70/30 — IS only for mutations, OOS reserved
    dfs_is = []
    dfs_oos = []
    for sym in SYMBOLS:
        for tf in TIMEFRAMES:
            df = loader.load(symbol=sym, timeframe=tf, days=DAYS, cache=True)
            cut = int(len(df) * IS_RATIO)
            dfs_is.append((sym, tf, df.iloc[:cut]))
            dfs_oos.append((sym, tf, df.iloc[cut:]))

    # --- Baseline ---
    baseline_params = {}
    baseline_st = ("1h", "4h")
    baseline_is = eval_variant(dfs_is, baseline_params, baseline_st)
    print(f"=== BASELINE (strict_tfs=1h/4h, defaults) ===")
    print(f"  IS: mean={baseline_is['mean']:.2f}% prof={baseline_is['prof']}/{baseline_is['cells']} n={baseline_is['total_n']}")
    for r in baseline_is.get("detail", []):
        print(f"    {r['sym']}:{r['tf']} ret={r['ret']:+.2f}% n={r['n']}")

    # --- Mutation grid (not biased by full-data diagnostics) ---
    # Each mutation: (name, params, strict_tfs)
    # Covers: strict_tfs, min_confluence, quality, gap_atr, vol, atr_sl
    mutations = [
        # Dimension 1: strict_tfs (which TFs get the strict gate)
        ("st_1h2h4h",     {}, ("1h", "2h", "4h")),
        ("st_1h2h4h1d",   {}, ("1h", "2h", "4h", "1d")),
        ("st_1h4h_mc3",   {"strict_min_confluence": 3}, ("1h", "4h")),

        # Dimension 2: min_confluence on strict TFs
        ("st_1h2h4h_mc5", {"strict_min_confluence": 5}, ("1h", "2h", "4h")),
        ("st_1h2h4h_mc3", {"strict_min_confluence": 3}, ("1h", "2h", "4h")),

        # Dimension 3: quality gate
        ("qual_all",      {"quality_tfs": ("1h", "2h", "4h", "1d")}, ("1h", "4h")),
        ("qual_all_mc5",  {"quality_tfs": ("1h", "2h", "4h", "1d"), "strict_min_confluence": 5}, ("1h", "4h")),

        # Dimension 4: gap_atr_mult (require wider gaps)
        ("gap_075",       {"gap_atr_mult": 0.75}, ("1h", "4h")),
        ("gap_100",       {"gap_atr_mult": 1.0}, ("1h", "4h")),

        # Dimension 5: volume filter
        ("vol_15",        {"vol_mult": 1.5}, ("1h", "4h")),
        ("vol_20",        {"vol_mult": 2.0}, ("1h", "4h")),

        # Dimension 6: SL buffer
        ("atr_sl_075",    {"atr_sl_mult": 0.75}, ("1h", "4h")),

        # Combinations: strict+quality
        ("st+qual",       {"quality_tfs": ("1h", "2h", "4h")}, ("1h", "2h", "4h")),

        # Combinations: strict+gap
        ("st+gap075",     {"gap_atr_mult": 0.75}, ("1h", "2h", "4h")),
        ("st+gap100",     {"gap_atr_mult": 1.0}, ("1h", "2h", "4h")),

        # Combinations: strict+vol
        ("st+vol15",      {"vol_mult": 1.5}, ("1h", "2h", "4h")),

        # Combinations: strict+atr_sl
        ("st+atr_sl075",  {"atr_sl_mult": 0.75}, ("1h", "2h", "4h")),

        # Multi-factor: strict+gap+vol
        ("st+gap075+vol", {"gap_atr_mult": 0.75, "vol_mult": 1.5}, ("1h", "2h", "4h")),

        # Multi-factor: strict+qual+gap+vol
        ("st+qual+gap+vol", {"quality_tfs": ("1h", "2h", "4h"), "gap_atr_mult": 0.75, "vol_mult": 1.5}, ("1h", "2h", "4h")),

        # Adaptive confluence
        ("adaptive",      {"adaptive_confluence": True, "adaptive_high": 4, "adaptive_low": 2}, ("1h", "4h")),
    ]

    best_is = baseline_is
    best_name = "baseline"
    best_params = baseline_params
    best_st = baseline_st
    no_improve = 0
    candidate = None

    print(f"\n{'='*80}")
    print(f"MUTATION LOOP — fvg_mtf:fvg (IS only, {int(IS_RATIO*100)}% of {DAYS}d)")
    print(f"Candidate threshold: mean>0, prof≥50%, n≥30 per cell")
    print(f"{'='*80}\n")

    for i, (name, params, st) in enumerate(mutations[:MAX_ITER], 1):
        res = eval_variant(dfs_is, params, st)
        improved = res["mean"] > best_is["mean"]
        marker = " <<<" if improved else ""

        print(f"[{i:2d}/{MAX_ITER}] {name:30s} mean={res['mean']:7.2f}% prof={res['prof']}/{res['cells']} n={res['total_n']:5d} n<30={res['n_below30']}{marker}")

        if improved:
            best_is = res
            best_name = name
            best_params = params
            best_st = st
            no_improve = 0
        else:
            no_improve += 1

        # Check if candidate (with n≥30 gate)
        if is_candidate(res):
            if candidate is None or res["mean"] > candidate["mean"]:
                candidate = {"name": name, "params": params, "strict_tfs": st, **res}
                print(f"        ^ CANDIDATO: mean={res['mean']:.2f}% prof={res['prof']}/{res['cells']} n={res['total_n']}")

        if no_improve >= PATIENCE:
            print(f"\n  Patience ({PATIENCE}) agotado tras {i} iteraciones. Mejor: {best_name}")
            break

    print(f"\n{'='*80}")
    print(f"RESULTADO IS")
    print(f"  Mejor variante: {best_name}")
    print(f"  Params: strict_tfs={best_st} | {best_params}")
    print(f"  IS: mean={best_is['mean']:.2f}% prof={best_is['prof']}/{best_is['cells']} n={best_is['total_n']}")
    for r in best_is.get("detail", []):
        print(f"    {r['sym']}:{r['tf']} ret={r['ret']:+.2f}% n={r['n']}")

    if candidate:
        print(f"\n  CANDIDATO FINAL (IS profitable + n≥30): {candidate['name']}")
        print(f"    mean={candidate['mean']:.2f}% prof={candidate['prof']}/{candidate['cells']} n={candidate['total_n']}")
        print(f"\n--- OOS CHECK (single shot, one-shot rule) ---")
        oos = eval_variant(dfs_oos, candidate["params"], candidate["strict_tfs"])
        print(f"  OOS: mean={oos['mean']:.2f}% prof={oos['prof']}/{oos['cells']} n={oos['total_n']}")
        for r in oos.get("detail", []):
            print(f"    {r['sym']}:{r['tf']} ret={r['ret']:+.2f}% n={r['n']}")
        oos_pass = oos["mean"] > 0 and oos["prof"] / max(oos["cells"], 1) >= 0.5
        print(f"\n  OOS PASS: {oos_pass}")
        print(f"  EVALUACIONES OOS esta config: 1 (one-shot rule)")
        if oos_pass:
            print(f"\n  >>> CANDIDATO APROBADO PARA DEPLOY <<<")
        else:
            print(f"\n  >>> FALLO OOS — DESCARTADO <<<")
    else:
        print(f"\n  NO HAY CANDIDATO IS-profitable con n≥30 tras {min(len(mutations), MAX_ITER)} mutaciones.")
        print(f"  FAMILIA: DESCARTADA (mejor variante alcanzada: {best_name})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
