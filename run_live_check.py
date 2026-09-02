#!/usr/bin/env python
"""
run_live_check.py — scan NOW for a fresh fvg 4h signal in BTC/ETH.

Validated config (IS +72.55 / OOS +24.68, n=16):
    strategy=fvg | strict_tfs=("4h",) | strict_min_confluence=5 | gap_atr_mult=0.75
    exits = STRICT_EXIT (rr_tp1=2.0, rr_runner=3.0, weight_tp1=0.9)  [OOS-eval faithful]

Run from harness root:
    ~/Escritorio/ccxtv2/venv/bin/python run_live_check.py
"""
from __future__ import annotations

import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, ".")

import numpy as np
import pandas as pd

from data import loader
from portfolio import exits
from signals.fvg_mtf.fvg_mtf import compute

SYMBOLS = ["BTC", "ETH"]
TF = "4h"
WARMUP_DAYS = 45
PARAMS = {
    "strategy": "fvg",
    "strict_tfs": ("4h",),
    "strict_min_confluence": 5,
    "gap_atr_mult": 0.75,
}
EXITS = {"rr_tp1": 2.0, "rr_runner": 3.0, "weight_tp1": 0.9}


def fmt_level(x):
    return f"{x:,.2f}" if pd.notna(x) else "—"


def main():
    now = pd.Timestamp.utcnow().tz_localize(None).floor("min")
    print(f"NOW (UTC): {now}\n")

    for sym in SYMBOLS:
        df = loader.load(symbol=sym, timeframe=TF, days=WARMUP_DAYS, cache=False)
        if df.empty:
            print(f"{sym} {TF}: NO DATA")
            continue

        sig = compute(df, **PARAMS)
        entries = sig["entries"].fillna(False).astype(bool)
        shorts = sig["short_entries"].fillna(False).astype(bool)
        sl = sig["sl"]
        conf = sig["confluences"]
        trail = sig["runner_inv"]

        brk = exits.build_brackets(
            entry=df["close"], sl=sl, direction=sig["dir"],
            rr_tp1=EXITS["rr_tp1"], rr_runner=EXITS["rr_runner"],
            weight_tp1=EXITS["weight_tp1"], trail=trail,
        )

        tail = slice(-30, None)
        show = pd.DataFrame({
            "open": df["open"],
            "close": df["close"],
            "LONG": entries,
            "SHORT": shorts,
            "conf": conf,
            "entry": brk["entry"],
            "sl": brk["sl"],
            "tp1": brk["tp1"],
            "tp2": brk["tp2"],
            "run_inv": trail,
        }).iloc[tail]
        last = show.index[-1]

        print(f"===== {sym}/USDT {TF} — últimas {len(show)} velas =====")
        with pd.option_context("display.max_rows", None, "display.width", 300):
            print(show)
        print()

        # recent signals (last 14 days) for context
        recent = (entries | shorts) & (df.index >= now - pd.Timedelta(days=14))
        if recent.any():
            idx_r = df.index[recent]
            print(f"  Señales en últimos 14d: {[str(i) for i in idx_r]}")
        else:
            print("  No hay señales en los últimos 14 días")
        last_close = df["close"].loc[last]
        last_conf = int(conf.loc[last])
        last_gapw = float(sig["gap_quality"].loc[last])
        print(f"  Última vela {last}: conf={last_conf}/5 gap_quality={last_gapw:.2f} (min=0.30 no aplica en 4h)")
        print()

        # fresh signal = the most recent bar holding an execution
        last = show.index[-1]
        for lbl, m in (("LONG", entries), ("SHORT", shorts)):
            if m.iloc[-1]:
                i = last
                d = 1 if lbl == "SHORT" else -1
                d = -d if lbl == "SHORT" else 1
                direction = "SHORT" if lbl == "SHORT" else "LONG"
                e = float(df["open"].loc[i])
                s = float(sl.loc[i])
                r = abs(e - s)
                tp1 = float(df["open"].loc[i]) + d * r * EXITS["rr_tp1"]
                tp2 = float(df["open"].loc[i]) + d * r * EXITS["rr_runner"]
                print(f"  >>> SEÑAL FRESCA: {sym} {direction} en vela {i}")
                print(f"      entry(open bar)={fmt_level(e)} sl={fmt_level(s)} "
                      f"tp1={fmt_level(tp1)} tp2={fmt_level(tp2)} confluences={int(conf.loc[i])}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())