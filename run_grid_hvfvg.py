"""
run_grid_hvfvg.py — In-Sample (70%) grid search for the HVFVG strategy.

The default HVFVG params over-filter (too few signals) and take premature SL
hits from market noise. This script sweeps the search space on the temporal
In-Sample portion (first 70% of each series) and selects the combination that
maximizes Profit Factor while keeping Win Rate > 45% and n >= min_trades,
mirroring the split-mode metrics used by run_profit_map.

Run (from harness root, ccxtv2 venv):
    ~/Escritorio/ccxtv2/venv/bin/python run_grid_hvfvg.py
Output: reports/grid_hvfvg_IS.csv + selection summary.
"""
from __future__ import annotations

import os
from itertools import product

import numpy as np
import pandas as pd

from data import loader
from portfolio import engine, exits
from signals.hvfvg.hvfvg import compute

SYMBOLS = ["BTC", "ETH"]
TIMEFRAMES = ["1h", "2h", "4h"]
DAYS = 365
IS_FRAC = 0.70          # temporal In-Sample window
MIN_TRADES = 40         # minimum total trades per cell to count
MIN_WINRATE = 45.0      # win rate floor (%)
FEES = 0.00045
INIT_CASH = 10000.0

# Search space (real param names of hvfvg.compute)
GRID = {
    "vol_mult": [1.3, 1.5, 1.8],
    "entry_ratio": [0.0, 0.5],
    "atr_sl_mult": [0.5, 0.8, 1.2],
    "retest_max": [24, 48, 96],
    "use_absorption_filter": [True, False],
}


def _grid_rows() -> list[dict]:
    keys, values = zip(*GRID.items())
    return [dict(zip(keys, combo)) for combo in product(*values)]


def _cell_metrics(df, params) -> dict:
    """Signals on the temporal IS slice + split-engine stats."""
    n_is = int(len(df) * IS_FRAC)
    is_df = df.iloc[:n_is]
    sig = compute(is_df, **params)
    entries = sig["entries"].fillna(False).astype(bool)
    shorts = sig["short_entries"].fillna(False).astype(bool)
    n_sig = int(entries.sum() + shorts.sum())

    rec = {"n_long": int(entries.sum()), "n_short": int(shorts.sum()),
           "n_signals": n_sig,
           "return_pct": np.nan, "win_rate": np.nan,
           "profit_factor": np.nan, "total_trades": 0}

    if not n_sig:
        return rec

    brackets = exits.build_native_brackets(
        entry=is_df["close"], sl=sig["sl"],
        tp1=sig.get("tp1"), tp2=sig.get("tp2"),
        direction=sig["dir"])
    res = engine.run(is_df, entries=entries, short_entries=shorts,
                     brackets=brackets, mode="split", freq=params.get("_tf"),
                     fees=FEES, init_cash=INIT_CASH)

    sa = res["combined_stats"].get("leg_a_stats", {})
    sb = res["combined_stats"].get("leg_b_stats", {})
    na = sa.get("Total Trades", 0) or 0
    nb = sb.get("Total Trades", 0) or 0
    wa = sa.get("Win Rate [%]", np.nan)
    wb = sb.get("Win Rate [%]", np.nan)
    pfa = sa.get("Profit Factor", np.nan)
    pfb = sb.get("Profit Factor", np.nan)
    ra = sa.get("Total Return [%]", np.nan)
    rb = sb.get("Total Return [%]", np.nan)

    n_tot = na + nb
    # aggregate across legs by trade count weighting
    if n_tot:
        wr = (wa * na + wb * nb) / n_tot if (wa == wa and wb == wb) else np.nan
        pf = (pfa * na + pfb * nb) / n_tot if (pfa == pfa and pfb == pfb) else np.nan
        ret = (ra + rb) if (ra == ra and rb == rb) else np.nan
    else:
        wr = pf = ret = np.nan

    rec.update({"return_pct": ret, "win_rate": wr,
                "profit_factor": pf, "total_trades": n_tot})
    return rec


def main() -> int:
    os.makedirs("reports", exist_ok=True)
    frames = {}
    for sym in SYMBOLS:
        for tf in TIMEFRAMES:
            frames[f"{sym}:{tf}"] = loader.load(symbol=sym, timeframe=tf,
                                                days=DAYS, cache=True)

    rows = []
    configs = _grid_rows()
    print(f"== hvfvg IS grid: {len(configs)} configs x {len(frames)} cells ==")
    for params in configs:
        for cell, df in frames.items():
            symbol, tf = cell.split(":")
            p = dict(params, _tf=tf)
            rec = {"symbol": symbol, "timeframe": tf, **params}
            rec.update(_cell_metrics(df, p))
            rows.append(rec)
        print(f"  done {params}")

    df = pd.DataFrame(rows)
    out = os.path.join("reports", "grid_hvfvg_IS.csv")
    df.to_csv(out, index=False)
    print(f"\nSaved: {out} ({len(df)} rows)")

    # ---- selection: n>=MIN_TRADES per cell, then aggregate across cells ----
    qual = df[df["total_trades"] >= MIN_TRADES].copy()
    print(f"\nConfigs with >= {MIN_TRADES} trades in >=1 cell: "
          f"{qual['symbol'].notna().sum()} cell-records")

    param_cols = list(GRID.keys())
    if qual.empty:
        print("\nNO config reached the minimum trade threshold on IS.")
        print("Showing best-available summary (lower n, still informative):")
        qual = df[df["total_trades"] >= 20].copy()
        if qual.empty:
            print("Even n>=20 absent; showing raw top by profit factor.")
            qual = df.copy()

    g = (qual.groupby(param_cols)
             .agg(cells=("total_trades", "size"),
                  total_trades=("total_trades", "sum"),
                  avg_pf=("profit_factor", "mean"),
                  avg_wr=("win_rate", "mean"),
                  avg_ret=("return_pct", "mean"),
                  prof_cells=("return_pct", lambda s: (s > 0).sum()))
             .reset_index())
    # keep only rows that satisfy win-rate floor on average
    g = g[g["avg_wr"] > MIN_WINRATE]
    g = g.sort_values(["avg_pf", "total_trades"], ascending=[False, False])

    print("\n== TOP CONFIGS (avg PF desc, win rate > {}%) ==".format(MIN_WINRATE))
    if g.empty:
        print("None pass the win-rate floor after filtering.")
    print(g.head(15).to_string(index=False))

    if not g.empty:
        best = g.iloc[0]
        best_params = {k: best[k] for k in param_cols}
        print("\n== WINNER DEFAULTS ==")
        print(best_params)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
