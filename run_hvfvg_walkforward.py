"""
run_hvfvg_walkforward.py — rolling walk-forward validation (7y history, 6 windows).

Loads 5-7 years of Binance OHLCV data (2019/2026) from data/cache/hist and
evaluates the All-In 1:2 and All-In 1:2.5 exit variants on 6 contiguous
out-of-sample windows across different market regimes (bull, bear, range).

Signal defaults are FIXED (no re-tuning on any window) to avoid curve-fitting.
This directly tests whether the HVFVG bounce edge is robust across years.

Run (from harness root, ccxtv2 venv):
    ~/Escritorio/ccxtv2/venv/bin/python run_hvfvg_walkforward.py
"""
from __future__ import annotations

import os
import numpy as np
import pandas as pd
import vectorbt as vbt
from signals.hvfvg.hvfvg import compute

# Data paths (Binance 7y history, downloaded via download_history.py)
DATA_DIR = "data/cache/hist"
TIMEFRAMES = ["1h", "2h", "4h"]

# Fixed signal defaults (IS-tuned, no re-adjustment)
WINNING = dict(vol_mult=1.8, entry_ratio=0.5, atr_sl_mult=0.8,
               retest_max=96, use_absorption_filter=True)

FEES = 0.00045
SLIPPAGE = 0.0000
INIT_CASH = 10000.0

# Rolling OOS windows: 6 contiguous periods (~1.1-1.2y each)
WINDOWS = [
    ("W1 2019Q3-2020Q4", "2019-09-08", "2020-12-31"),  # pre-COVID + recovery early bull
    ("W2 2021Q1-2022Q1", "2021-01-01", "2022-03-31"),  # mid/late bull + crash
    ("W3 2022Q2-2023Q3", "2022-04-01", "2023-06-30"),  # bear market + bottom
    ("W4 2023Q4-2024Q5", "2023-07-01", "2024-08-31"),  # range + pre-halving
    ("W5 2024Q6-2025Q7", "2024-09-01", "2025-10-31"),  # ETF + late bull
    ("W6 2025Q8-2026Q9", "2025-11-01", "2026-09-02"),  # recent mixed
]

# Regime labels for each window
REGIMES = {
    "W1 2019Q3-2020Q4": "Bull (early COVID recovery)",
    "W2 2021Q1-2022Q1": "Bull (late) + Crash start",
    "W3 2022Q2-2023Q3": "Bear (FTX collapse, bottom)",
    "W4 2023Q4-2024Q5": "Range (pre-halving, ETF)",
    "W5 2024Q6-2025Q7": "Bull (ETF approved, late)",
    "W6 2025Q8-2026Q9": "Mixed (recent 2025-26)",
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
        sl_stop=pd.Series(rel_sl).fillna(np.inf),
        tp_stop=pd.Series(rel_tp).fillna(np.inf),
        size=1.0, fees=FEES, slippage=SLIPPAGE, init_cash=INIT_CASH, freq=None)
    s = pf.stats()
    max_dd = s.get("Max Drawdown [%]", np.nan)
    return {
        "trades": int(s.get("Total Trades", 0) or 0),
        "wr": s.get("Win Rate [%]", np.nan),
        "pf": s.get("Profit Factor", np.nan),
        "ret": s.get("Total Return [%]", np.nan),
        "max_dd": max_dd,
    }


def main() -> int:
    os.makedirs("reports", exist_ok=True)

    # Load historical data
    frames = {}
    for tf in TIMEFRAMES:
        for sym in ["BTC", "ETH"]:
            path = os.path.join(DATA_DIR, f"{sym}_{tf}_hist.csv")
            if not os.path.exists(path):
                print(f"MISSING: {path} — run download_history.py first")
                continue
            df = pd.read_csv(path, index_col=0, parse_dates=True)
            frames[f"{sym}:{tf}"] = df
            print(f"Loaded {sym} {tf}: {len(df)} rows "
                  f"({df.index[0].date()} → {df.index[-1].date()})")

    print(f"\nLoaded {len(frames)} cells.")

    rows = []
    for window_name, start, end in WINDOWS:
        regime = REGIMES[window_name]
        print(f"\n== {window_name}: {regime} ==")
        for cell, full_df in frames.items():
            sym, tf = cell.split(":")

            # Slice window
            mask = (full_df.index >= start) & (full_df.index <= end)
            wdf = full_df[mask]
            if len(wdf) < 100:
                print(f"  {cell}: SKIP (<100 candles)")
                continue

            sig = compute(wdf, **WINNING)
            entries = sig["entries"].fillna(False).astype(bool)
            shorts = sig["short_entries"].fillna(False).astype(bool)
            sl = sig["sl"]
            close = wdf["close"]
            n = int(entries.sum() + shorts.sum())

            a2 = _run_allin(close, entries, shorts, sl, 2.0)
            a25 = _run_allin(close, entries, shorts, sl, 2.5)

            rec = {
                "window": window_name, "regime": regime,
                "symbol": sym, "timeframe": tf,
                "candles": len(wdf),
                "n_signals": n,
                "allin_1to2_pf": a2["pf"], "allin_1to2_wr": a2["wr"],
                "allin_1to2_ret": a2["ret"], "allin_1to2_mdd": a2["max_dd"],
                "allin_1to2_trades": a2["trades"],
                "allin_1to2p5_pf": a25["pf"], "allin_1to2p5_wr": a25["wr"],
                "allin_1to2p5_ret": a25["ret"], "allin_1to2p5_mdd": a25["max_dd"],
                "allin_1to2p5_trades": a25["trades"],
            }
            rows.append(rec)
            print(f"  {cell}: n={n}  1:2 pf={a2['pf']:.2f} wr={a2['wr']:.1f}% "
                  f"mdd={a2['max_dd']:.1f}%  "
                  f"1:2.5 pf={a25['pf']:.2f} wr={a25['wr']:.1f}% "
                  f"mdd={a25['max_dd']:.1f}%")

    r = pd.DataFrame(rows)
    r.to_csv("reports/hvfvg_walkforward_7y.csv", index=False)
    print(f"\nSaved: reports/hvfvg_walkforward_7y.csv ({len(r)} rows)")

    # === Summary tables ===
    print("\n" + "="*80)
    print("FULL WALK-FORWARD SUMMARY (6 windows, 7 years)")
    print("="*80)

    for tf in TIMEFRAMES:
        sub = r[r["timeframe"] == tf]
        if sub.empty:
            continue
        print(f"\n--- {tf} ---")
        print(sub[["window", "regime", "symbol", "n_signals",
                    "allin_1to2_pf", "allin_1to2_wr", "allin_1to2_mdd",
                    "allin_1to2p5_pf", "allin_1to2p5_wr", "allin_1to2p5_mdd"]
                   ].to_string(index=False))

    # === Accumulated totals ===
    print("\n" + "="*80)
    print("ACCUMULATED (all windows combined) per cell")
    print("="*80)
    for cell in ["BTC:1h", "BTC:2h", "BTC:4h", "ETH:1h", "ETH:2h", "ETH:4h"]:
        sub = r[(r["symbol"] == cell.split(":")[0]) & (r["timeframe"] == cell.split(":")[1])]
        if sub.empty:
            continue
        total_2 = int(sub["allin_1to2_trades"].sum())
        total_25 = int(sub["allin_1to2p5_trades"].sum())
        # aggregate PF by trade-weighted average
        t2 = sub["allin_1to2_trades"]
        t25 = sub["allin_1to2p5_trades"]
        pf2 = (sub["allin_1to2_pf"] * t2).sum() / t2.sum() if t2.sum() else np.nan
        pf25 = (sub["allin_1to2p5_pf"] * t25).sum() / t25.sum() if t25.sum() else np.nan
        wr2 = (sub["allin_1to2_wr"] * t2).sum() / t2.sum() if t2.sum() else np.nan
        wr25 = (sub["allin_1to2p5_wr"] * t25).sum() / t25.sum() if t25.sum() else np.nan
        worst_dd2 = sub["allin_1to2_mdd"].min()
        worst_dd25 = sub["allin_1to2p5_mdd"].min()
        print(f"  {cell:8s}  1:2  total={total_2:4d} pf={pf2:.2f} wr={wr2:.1f}% "
              f"worst_dd={worst_dd2:.1f}%   "
              f"1:2.5 total={total_25:4d} pf={pf25:.2f} wr={wr25:.1f}% "
              f"worst_dd={worst_dd25:.1f}%")

    # === Overall averages ===
    print("\n--- OVERALL AVERAGES (across all windows, trade-weighted) ---")
    for variant, pf_col, wr_col, trades_col in [
        ("All-In 1:2", "allin_1to2_pf", "allin_1to2_wr", "allin_1to2_trades"),
        ("All-In 1:2.5", "allin_1to2p5_pf", "allin_1to2p5_wr", "allin_1to2p5_trades"),
    ]:
        total_trades = r[trades_col].sum()
        avg_pf = (r[pf_col] * r[trades_col]).sum() / total_trades if total_trades else np.nan
        avg_wr = (r[wr_col] * r[trades_col]).sum() / total_trades if total_trades else np.nan
        n_cells_gt1 = int((r[pf_col].dropna() > 1.0).sum())
        n_cells_total = len(r[pf_col].dropna())
        print(f"  {variant:16s} trades={total_trades:.0f}  PF={avg_pf:.3f}  "
              f"WR={avg_wr:.1f}%  cells>1.0={n_cells_gt1}/{n_cells_total}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
