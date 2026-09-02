"""
run_hvfvg_oos.py — Out-of-Sample (30%) validation for HVFVG All-In exits.

The signal defaults (winning IS grid) and All-In exit schedules are held FIXED
(no re-tuning on OOS) to detect curve-fitting. The temporal OOS = last 30% of
each series, which the In-Sample optimization never saw.

Validates the two winning variants:
  All-In 1:2   (100% @ fixed TP 1:2)
  All-In 1:2.5 (100% @ fixed TP 1:2.5)

Reports pure PF per symbol x timeframe, with explicit read-out for the low-TF
(1h) cells vs 2h/4h, to decide whether 1h should be dropped for this strategy.

Run (from harness root, ccxtv2 venv):
    ~/Escritorio/ccxtv2/venv/bin/python run_hvfvg_oos.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import vectorbt as vbt

from data import loader
from signals.hvfvg.hvfvg import compute

SYMBOLS = ["BTC", "ETH"]
TIMEFRAMES = ["1h", "2h", "4h"]
DAYS = 365
IS_FRAC = 0.70          # first 70% = IS; last 30% = OOS
FEES = 0.00045
SLIPPAGE = 0.0000
INIT_CASH = 10000.0

WINNING = dict(vol_mult=1.8, entry_ratio=0.5, atr_sl_mult=0.8,
               retest_max=96, use_absorption_filter=True)


def _stats(pf):
    s = pf.stats()
    return {
        "trades": int(s.get("Total Trades", 0) or 0),
        "wr": s.get("Win Rate [%]", np.nan),
        "pf": s.get("Profit Factor", np.nan),
        "ret": s.get("Total Return [%]", np.nan),
    }


def _run_allin(close, entries, shorts, sl, rr):
    """100% at fixed TP rr:1 with original SL. No runner."""
    risk = (close - sl).abs()
    is_long = (close - sl) > 0
    tp = np.where(is_long, close + risk * rr, close - risk * rr)
    rel_sl = ((close - sl) / close).abs()
    rel_tp = ((tp - close) / close).abs()
    pf = vbt.Portfolio.from_signals(
        close=close, entries=entries, short_entries=shorts,
        sl_stop=pd.Series(rel_sl).fillna(np.inf), tp_stop=pd.Series(rel_tp).fillna(np.inf),
        size=1.0, fees=FEES, slippage=SLIPPAGE, init_cash=INIT_CASH, freq=None)
    return _stats(pf)


def main() -> int:
    rows = []
    for sym in SYMBOLS:
        for tf in TIMEFRAMES:
            df = loader.load(symbol=sym, timeframe=tf, days=DAYS, cache=True)
            n_split = int(len(df) * IS_FRAC)
            oos_df = df.iloc[n_split:]          # last 30% = OOS
            sig = compute(oos_df, **WINNING)
            entries = sig["entries"].fillna(False).astype(bool)
            shorts = sig["short_entries"].fillna(False).astype(bool)
            sl = sig["sl"]
            close = oos_df["close"]
            n = int(entries.sum() + shorts.sum())

            a2 = _run_allin(close, entries, shorts, sl, 2.0)
            a25 = _run_allin(close, entries, shorts, sl, 2.5)

            rows.append({
                "symbol": sym, "timeframe": tf, "n_signals": n,
                "allin_1to2_pf": a2["pf"], "allin_1to2_wr": a2["wr"],
                "allin_1to2_ret": a2["ret"], "allin_1to2_trades": a2["trades"],
                "allin_1to2p5_pf": a25["pf"], "allin_1to2p5_wr": a25["wr"],
                "allin_1to2p5_ret": a25["ret"], "allin_1to2p5_trades": a25["trades"],
            })
            print(f"{sym} {tf}: n={n} allin2.pf={a2['pf']:.3f} "
                  f"allin2.5.pf={a25['pf']:.3f} (trades {a2['trades']}/{a25['trades']})")

    r = pd.DataFrame(rows)
    print("\n== OOS (30%) — pure PF per cell ==")
    print(r[["symbol", "timeframe", "n_signals",
             "allin_1to2_pf", "allin_1to2p5_pf"]].to_string(index=False))

    print("\n== OOS breakdown by TF group ==")
    for grp, tfs in [("1h", ["1h"]), ("2h+4h", ["2h", "4h"])]:
        sub = r[r["timeframe"].isin(tfs)]
        for col in ["allin_1to2_pf", "allin_1to2p5_pf"]:
            vals = sub[col].dropna()
            mean = vals.mean() if len(vals) else np.nan
            n_gt1 = int((vals > 1.0).sum())
            print(f"  {grp:5s} {col:16s} mean={mean:.3f}  cells>1.0={n_gt1}/{len(vals)}")

    print("\n== OOS average PF ==")
    for col in ["allin_1to2_pf", "allin_1to2p5_pf"]:
        vals = r[col].dropna()
        mean = vals.mean() if len(vals) else np.nan
        n_gt1 = int((vals > 1.0).sum())
        print(f"  {col:16s} mean={mean:.3f}  cells>1.0={n_gt1}/{len(vals)}")

    r.to_csv("reports/hvfvg_oos.csv", index=False)
    print("\nSaved: reports/hvfvg_oos.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
