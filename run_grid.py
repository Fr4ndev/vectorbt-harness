"""
run_grid.py — grid search over the restrictive gates of the low-signal
strategies (sfp_institutional, po3_fractal) to find the frequency / PnL
balance point on local BTC + ETH data only.

Methodology matches run_profit_map.py: split-mode engine (80% TP1 1:2, 20%
runner 1:5, SL->BE, fees 0.0006, slippage 0.0003, cash 10k) so grid verdicts
are comparable with the profit-map verdicts.

Run (from harness root, ccxtv2 venv):
    ~/Escritorio/ccxtv2/venv/bin/python run_grid.py
Output: reports/grid_search_results.csv + compact per-strategy summary.
"""
from __future__ import annotations

import os
from itertools import product

import pandas as pd

from data import loader
from portfolio import engine
from portfolio.exits import build_brackets
from run_profit_map import _combined_return

SYMBOLS = ["BTC", "ETH"]
TIMEFRAMES = ["1h", "4h"]
DAYS = 365

# ---------------------------------------------------------------------------
# Search spaces (real parameter names of each strategy)
# ---------------------------------------------------------------------------
SFP_GRID = {
    "depth_min": [0.0005, 0.0010, 0.0015],      # relax 0.15% -> 0.05%
    "depth_max": [0.0050, 0.0075],              # widen the depth ceiling
    "reclaim_bars": [1, 2, 3, 4],               # extend the reclaim window
    "killzones": [True, False],                 # is the session the bottleneck?
}

PO3_GRID = {
    "acc_range": [0.0015, 0.0030, 0.0060],      # wider accumulation tolerance
    "judas_window": [4, 6, 10, 14],             # longer sweep window (bars)
    "ms_lookback": [3, 5, 10],                  # MSS sensitivity (swing lookback)
    "killzones": [True, False],
}


def _grid_rows(strategy: str) -> list[dict]:
    space = SFP_GRID if strategy == "sfp_institutional" else PO3_GRID
    keys, values = zip(*space.items())
    return [dict(zip(keys, combo)) for combo in product(*values)]


def main() -> int:
    os.makedirs("reports", exist_ok=True)
    # load each (symbol, tf) once and reuse across the grid
    frames = {}
    for sym in SYMBOLS:
        for tf in TIMEFRAMES:
            frames[f"{sym}:{tf}"] = loader.load(symbol=sym, timeframe=tf,
                                                days=DAYS, cache=True)

    rows = []
    from signals.demon2.demon2 import compute as demon2_compute
    from signals.ictsuite.ictsuite import compute as ictsuite_compute
    for strategy in ["sfp_institutional", "po3_fractal"]:
        compute = ictsuite_compute if strategy == "sfp_institutional" else demon2_compute
        family = "ictsuite" if strategy == "sfp_institutional" else "demon2"
        n_cfg = len(_grid_rows(strategy))
        print(f"== {family}:{strategy} — {n_cfg} configs x {len(frames)} cells ==")
        for params in _grid_rows(strategy):
            for cell, df in frames.items():
                symbol, tf = cell.split(":")
                sig = compute(df, strategy=strategy, **params)
                entries = sig["entries"].fillna(False).astype(bool)
                shorts = sig["short_entries"].fillna(False).astype(bool)
                n_sig = int(entries.sum() + shorts.sum())
                rec = {
                    "strategy": strategy, "family": family,
                    "symbol": symbol, "timeframe": tf,
                    "n_signals": n_sig,
                    "n_long": int(entries.sum()), "n_short": int(shorts.sum()),
                    **params,
                }
                if n_sig:
                    brackets = build_brackets(entry=df["close"],
                                              sl=sig["sl"],
                                              direction=sig["dir"])
                    res = engine.run(df, entries=entries,
                                     short_entries=shorts, brackets=brackets,
                                     mode="split", freq=tf)
                    cr, cwr, *_ = _combined_return(res)
                    rec["return_pct"] = cr
                    rec["win_rate"] = cwr
                else:
                    rec["return_pct"] = float("nan")
                    rec["win_rate"] = float("nan")
                rows.append(rec)
            print(f"  done {params}")

    df = pd.DataFrame(rows)
    out = os.path.join("reports", "grid_search_results.csv")
    df.to_csv(out, index=False)
    print(f"\nSaved: {out} ({len(df)} rows)")

    print("\n== TOP CONFIGS (mean return across cells, >=10 signals) ==")
    for strategy in ["sfp_institutional", "po3_fractal"]:
        sub = df[(df["strategy"] == strategy) & df["return_pct"].notna()]
        sub = sub[sub["n_signals"] >= 10]
        if sub.empty:
            print(f"\n{strategy}: no config reached >=10 signals")
            continue
        param_cols = [c for c in df.columns
                      if c not in ("strategy", "family", "symbol", "timeframe",
                                   "n_signals", "n_long", "n_short",
                                   "return_pct", "win_rate")]
        g = (sub.groupby(param_cols)
                 .agg(mean_return=("return_pct", "mean"),
                      mean_winrate=("win_rate", "mean"),
                      total_signals=("n_signals", "sum"),
                      prof_cells=("return_pct", lambda s: (s > 0).sum()))
                 .reset_index()
                 .sort_values("mean_return", ascending=False))
        print(f"\n{strategy}:")
        print(g.head(10).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())