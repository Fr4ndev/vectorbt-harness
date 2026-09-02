#!/usr/bin/env python
"""
run_profit_map.py — multi-strategy profitability map (BTC + ETH, 1 year).

Runs the requested strategy families across symbols x timeframes and emits a
per-strategy profitability verdict. Strategies flagged as unprofitable
(non-positive combined return) are marked for discard.

Run (from harness root, ccxtv2 venv):
    ~/Escritorio/ccxtv2/venv/bin/python run_profit_map.py
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, ".")

import numpy as np
import pandas as pd

from engine import runner

SYMBOLS = ["BTC", "ETH"]
TIMEFRAMES = ["1h", "2h", "4h", "1d"]
DAYS = 365

# (family, strategy, params, exit_kwargs) — the backtest scope requested by the user
RUNS = [
    ("demon2", "mmxm", {"enable_breaker": True}, {}),
    ("demon2", "po3_fractal", {}, {}),
    ("fvg_mtf", "ifvg", {}, {}),
    ("fvg_mtf", "fvg", {}, {}),
    ("ictsuite", "scalp_sweep", {}, {}),
    ("ictsuite", "intraday_quantum", {}, {}),
    ("ictsuite", "macro_swing", {}, {}),
    ("ictsuite", "sfp_institutional", {}, {}),
]

CELLS = [f"{sym}:{tf}" for sym in SYMBOLS for tf in TIMEFRAMES]

# tighter runner / more aggressive partial only on the weak fvg_mtf entry TFs
STRICT_FVG_TFS = ("1h", "4h")
STRICT_FVG_EXIT = {"rr_runner": 3.0, "weight_tp1": 0.9}


def _combined_return(result: dict) -> tuple:
    """Weighted total return and win rate from the split-mode portfolios."""
    stats = result.get("combined_stats", {}) or {}
    sa = stats.get("leg_a_stats", {}) or {}
    sb = stats.get("leg_b_stats", {}) or {}
    ra = sa.get("Total Return [%]", np.nan)
    rb = sb.get("Total Return [%]", np.nan)
    wa = sa.get("Win Rate [%]", np.nan)
    wb = sb.get("Win Rate [%]", np.nan)
    w = 0.8
    combined = (w * ra + (1 - w) * rb) if (ra == ra and rb == rb) else np.nan
    winrate = (w * wa + (1 - w) * wb) if (wa == wa and wb == wb) else np.nan
    return combined, winrate, ra, rb, wa, wb


def main():
    rows = []
    for family, strategy, params, exit_kwargs in RUNS:
        for cell in CELLS:
            symbol, tf = cell.split(":")
            kwargs = dict(exit_kwargs)
            if family == "fvg_mtf" and tf in STRICT_FVG_TFS:
                kwargs.update(STRICT_FVG_EXIT)
            try:
                res = runner.run_one(family=family, strategy=strategy,
                                     symbol=symbol, tf=tf, days=DAYS,
                                     params=params, **kwargs)
                rec = {
                    "family": family, "strategy": strategy or "default",
                    "symbol": symbol, "timeframe": tf,
                    "n_signals": res.get("n_signals", 0),
                    "n_long": res.get("n_long", 0),
                    "n_short": res.get("n_short", 0),
                }
                if "error" in res:
                    rec.update({"error": res.get("error")})
                else:
                    cr, cwr, ra, rb, wa, wb = _combined_return(res["result"])
                    rec.update({
                        "total_return_pct": cr, "winrate_pct": cwr,
                        "leg_a_return_pct": ra, "leg_b_return_pct": rb,
                        "leg_a_winrate_pct": wa, "leg_b_winrate_pct": wb,
                    })
                rows.append(rec)
                print(f"  {family}:{strategy or '-'} {cell}: "
                      f"n={rec.get('n_signals')} ret={rec.get('total_return_pct')}")
            except Exception as e:
                rows.append({"family": family, "strategy": strategy or "default",
                             "symbol": symbol, "timeframe": tf, "error": str(e)})
                print(f"  {family}:{strategy or '-'} {cell}: ERROR {e}")

    df = pd.DataFrame(rows)
    os.makedirs("reports", exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join("reports", f"profit_map_{stamp}.csv")
    df.to_csv(path, index=False)

    print("\n== STRATEGY VERDICT ==")
    verdicts = []
    for family, strategy, _, _ in RUNS:
        sub = df[(df["family"] == family) & (df["strategy"] == (strategy or "default"))]
        sub = sub.dropna(subset=["total_return_pct"])
        if sub.empty:
            verdicts.append([family, strategy or "default", "NO_DATA", 0, 0, 0, 0])
            continue
        mean_ret = sub["total_return_pct"].mean()
        n_cells = len(sub)
        n_prof = int((sub["total_return_pct"] > 0).sum())
        n_sig = int(sub["n_signals"].sum())
        prof_ratio = n_prof / n_cells if n_cells else 0.0
        ok = mean_ret > 0 and prof_ratio >= 0.5 and n_sig > 10
        verdicts.append([family, strategy or "default",
                         "PROFITABLE" if ok else "UNPROFITABLE",
                         round(mean_ret, 2), n_prof, n_cells, n_sig])
    v = pd.DataFrame(verdicts, columns=["family", "strategy", "verdict",
                                        "mean_return_pct", "prof_cells",
                                        "total_cells", "total_signals"])
    cols = ["family", "strategy", "verdict", "mean_return_pct", "prof_cells",
            "total_cells", "total_signals"]
    print(v[cols].to_string(index=False))
    v.to_csv(os.path.join("reports", f"verdict_{stamp}.csv"), index=False)

    print(f"\nSaved: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())