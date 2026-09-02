"""
run_hvfvg_ifvg_walkforward.py — 7y rolling walk-forward for the IFVG 30m variant.

Evaluates the Inversion-FVG (IFVG) module (`signals/hvfvg/hvfvg_ifvg.py`) on the
30m execution frame, with macro 4h/2h bias gate, across the same 6 rolling
windows (2019-2026) used for the FVG baseline. Fixed params (no re-tune).

Exit management: All-In 1:2 and All-In 1:2.5 (native tp1/tp2 from the module).

Run (from harness root, ccxtv2 venv):
    ~/Escritorio/ccxtv2/venv/bin/python run_hvfvg_ifvg_walkforward.py
"""
from __future__ import annotations

import os
import numpy as np
import pandas as pd
import vectorbt as vbt
from signals.hvfvg.hvfvg_ifvg import compute

DATA_DIR = "data/cache/hist"
DATA_TF = "30m"
SYMBOLS = ["BTC", "ETH"]

IFVG_PARAMS = dict(
    htf_rules=("4h", "2h"),
    presence_window=12,
    require_htf=True,
    htf_mode="either",
    atr_sl_mult=0.8,
    tp_atr_mult=2.0,
    retest_max=48,
    swing_window=5,
)

FEES = 0.00045
SLIPPAGE = 0.0000
INIT_CASH = 10000.0

WINDOWS = [
    ("W1 2019Q3-2020Q4", "2019-09-08", "2020-12-31"),
    ("W2 2021Q1-2022Q1", "2021-01-01", "2022-03-31"),
    ("W3 2022Q2-2023Q3", "2022-04-01", "2023-06-30"),
    ("W4 2023Q4-2024Q5", "2023-07-01", "2024-08-31"),
    ("W5 2024Q6-2025Q7", "2024-09-01", "2025-10-31"),
    ("W6 2025Q8-2026Q9", "2025-11-01", "2026-09-02"),
]


def _run_allin(close, entries, shorts, sl, rr):
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
    return {
        "trades": int(s.get("Total Trades", 0) or 0),
        "wr": s.get("Win Rate [%]", np.nan),
        "pf": s.get("Profit Factor", np.nan),
        "ret": s.get("Total Return [%]", np.nan),
        "mdd": s.get("Max Drawdown [%]", np.nan),
    }


def main() -> int:
    os.makedirs("reports", exist_ok=True)
    rows = []
    for sym in SYMBOLS:
        path = os.path.join(DATA_DIR, f"{sym}_{DATA_TF}_hist.csv")
        full = pd.read_csv(path, index_col=0, parse_dates=True)
        print(f"Loaded {sym} {DATA_TF}: {len(full)} rows")
        for wname, start, end in WINDOWS:
            wdf = full[(full.index >= start) & (full.index <= end)]
            if len(wdf) < 200:
                continue
            sig = compute(wdf, **IFVG_PARAMS)
            entries = sig["entries"].fillna(False).astype(bool)
            shorts = sig["short_entries"].fillna(False).astype(bool)
            sl = sig["sl"]
            close = wdf["close"]
            n = int(entries.sum() + shorts.sum())
            a2 = _run_allin(close, entries, shorts, sl, 2.0)
            a25 = _run_allin(close, entries, shorts, sl, 2.5)
            rows.append({
                "window": wname, "symbol": sym, "candles": len(wdf),
                "n_signals": n,
                "allin_1to2_pf": a2["pf"], "allin_1to2_wr": a2["wr"],
                "allin_1to2_ret": a2["ret"], "allin_1to2_mdd": a2["mdd"],
                "allin_1to2_trades": a2["trades"],
                "allin_1to2p5_pf": a25["pf"], "allin_1to2p5_wr": a25["wr"],
                "allin_1to2p5_ret": a25["ret"], "allin_1to2p5_mdd": a25["mdd"],
                "allin_1to2p5_trades": a25["trades"],
            })
            print(f"  {wname} {sym}: n={n} 1:2 pf={a2['pf']:.2f} wr={a2['wr']:.1f} "
                  f"mdd={a2['mdd']:.1f} | 1:2.5 pf={a25['pf']:.2f} "
                  f"wr={a25['wr']:.1f} mdd={a25['mdd']:.1f}")

    r = pd.DataFrame(rows)
    r.to_csv("reports/hvfvg_ifvg_walkforward_7y.csv", index=False)
    print(f"\nSaved ({len(r)} rows)")

    print("\n== ACCUMULATED (IFVG 30m, all windows) ==")
    for sym in SYMBOLS:
        sub = r[r["symbol"] == sym]
        if sub.empty:
            continue
        for col, tcol, mcol in [("allin_1to2_pf", "allin_1to2_trades", "allin_1to2_mdd"),
                                ("allin_1to2p5_pf", "allin_1to2p5_trades", "allin_1to2p5_mdd")]:
            t = sub[tcol]
            if t.sum() == 0:
                continue
            pf = (sub[col] * t).sum() / t.sum()
            wcol = "allin_1to2_wr" if "1to2_" in col else "allin_1to2p5_wr"
            wr = (sub[wcol] * t).sum() / t.sum()
            worst = sub[mcol].min()
            print(f"  {sym} {col:16s} trades={int(t.sum()):4d} "
                  f"pf={pf:.3f} wr={wr:.1f}% worst_mdd={worst:.1f}%")

    print("\n== OVERALL ==")
    for col, tcol, wcol in [("allin_1to2_pf", "allin_1to2_trades", "allin_1to2_wr"),
                            ("allin_1to2p5_pf", "allin_1to2p5_trades", "allin_1to2p5_wr")]:
        t = r[tcol]
        tot = t.sum()
        if tot == 0:
            continue
        pf = (r[col] * t).sum() / tot
        wr = (r[wcol] * t).sum() / tot
        n_gt1 = int((r[col].dropna() > 1.0).sum())
        print(f"  {col:16s} trades={int(tot):4d} pf={pf:.3f} wr={wr:.1f}% "
              f"cells>1.0={n_gt1}/{len(r[col].dropna())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
