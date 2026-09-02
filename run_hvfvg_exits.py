"""
run_hvfvg_exits.py — evaluate alternative exit management for HVFVG on IS (70%).

Current split (leg A 80% @1:2 + leg B runner 20% @1:5 static) destroys edge: the
runner leg is negative across all cells. This evaluates two pivots, keeping the
winning signal defaults (vol_mult=1.8, entry_ratio=0.5, atr_sl_mult=0.8,
retest_max=96, use_absorption_filter=True):

  A) All-In Leg A : 100% position at a fixed TP (1:2 or 1:2.5), runner removed.
  B) SmartTrail   : 80/20 split; leg B replaces the fixed 1:5 target with an
                    ATR-based trailing stop (1.5 ATR) that only trails (no fixed
                    TP), capturing extended moves while limiting giveback.

In-Sample window = first 70% of each series. Metric = trade-count-weighted
Profit Factor across legs, per cell and averaged; goal: consistently > 1.15.

Run (from harness root, ccxtv2 venv):
    ~/Escritorio/ccxtv2/venv/bin/python run_hvfvg_exits.py
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
IS_FRAC = 0.70
FEES = 0.00045
SLIPPAGE = 0.0000
INIT_CASH = 10000.0

WINNING = dict(vol_mult=1.8, entry_ratio=0.5, atr_sl_mult=0.8,
               retest_max=96, use_absorption_filter=True)
ATR_TRAIL = 1.5


def _stats(pf):
    s = pf.stats()
    return {
        "trades": int(s.get("Total Trades", 0) or 0),
        "wr": s.get("Win Rate [%]", np.nan),
        "pf": s.get("Profit Factor", np.nan),
        "ret": s.get("Total Return [%]", np.nan),
    }


def _combine(la, lb):
    """Trade-count weighted aggregate over two legs."""
    na, nb = la["trades"], lb["trades"]
    n = na + nb
    if not n:
        return dict(trades=0, wr=np.nan, pf=np.nan, ret=np.nan)
    wr = (la["wr"] * na + lb["wr"] * nb) / n \
        if not (np.isnan(la["wr"]) or np.isnan(lb["wr"])) else np.nan
    pf = (la["pf"] * na + lb["pf"] * nb) / n \
        if not (np.isnan(la["pf"]) or np.isnan(lb["pf"])) else np.nan
    ra, rb = la["ret"], lb["ret"]
    ret = (ra + rb) if not (np.isnan(ra) or np.isnan(rb)) else np.nan
    return dict(trades=n, wr=wr, pf=pf, ret=ret)


def _run_baseline(close, entries, shorts, sl, direction):
    """Current 80/20 split: leg A 1:2, leg B runner 1:5 static, SL->BE."""
    risk = (close - sl).abs() * direction.abs()
    is_long = direction > 0
    tp1 = np.where(is_long, close + risk * 2.0, close - risk * 2.0)
    tp2 = np.where(is_long, close + risk * 5.0, close - risk * 5.0)
    rel_sl = ((close - sl) / close).abs()
    rel_tp1 = ((tp1 - close) / close).abs()
    rel_tp2 = ((tp2 - close) / close).abs()
    rel_be = np.zeros_like(close)
    la = vbt.Portfolio.from_signals(
        close=close, entries=entries, short_entries=shorts,
        sl_stop=pd.Series(rel_sl).fillna(np.inf), tp_stop=pd.Series(rel_tp1).fillna(np.inf),
        size=0.8, fees=FEES, slippage=SLIPPAGE, init_cash=INIT_CASH * 0.8, freq=None)
    lb = vbt.Portfolio.from_signals(
        close=close, entries=entries, short_entries=shorts,
        sl_stop=pd.Series(rel_be).fillna(np.inf), tp_stop=pd.Series(rel_tp2).fillna(np.inf),
        size=0.2, fees=FEES, slippage=SLIPPAGE, init_cash=INIT_CASH * 0.2, freq=None)
    return _combine(_stats(la), _stats(lb))


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
    st = _stats(pf)
    return dict(trades=st["trades"], wr=st["wr"], pf=st["pf"], ret=st["ret"])


def _run_smarttrail(close, entries, shorts, sl, atr, trail_mult=ATR_TRAIL):
    """80/20: leg A 1:2 fixed; leg B trailing stop at trail_mult*ATR, no fixed TP."""
    risk = (close - sl).abs()
    is_long = (close - sl) > 0
    tp1 = np.where(is_long, close + risk * 2.0, close - risk * 2.0)
    rel_sl = ((close - sl) / close).abs()
    rel_tp1 = ((tp1 - close) / close).abs()
    # leg B trailing at trail_mult ATR (relative). Wide relative to 1:2 TP so it
    # only captures the continuation.
    rel_trail = pd.Series((atr * trail_mult / close).abs()).fillna(np.inf)

    la = vbt.Portfolio.from_signals(
        close=close, entries=entries, short_entries=shorts,
        sl_stop=pd.Series(rel_sl).fillna(np.inf), tp_stop=pd.Series(rel_tp1).fillna(np.inf),
        size=0.8, fees=FEES, slippage=SLIPPAGE, init_cash=INIT_CASH * 0.8, freq=None)
    lb = vbt.Portfolio.from_signals(
        close=close, entries=entries, short_entries=shorts,
        sl_stop=rel_trail, sl_trail=True, tp_stop=None,
        size=0.2, fees=FEES, slippage=SLIPPAGE, init_cash=INIT_CASH * 0.2, freq=None)
    return _combine(_stats(la), _stats(lb))


def main() -> int:
    results = []
    for sym in SYMBOLS:
        for tf in TIMEFRAMES:
            df = loader.load(symbol=sym, timeframe=tf, days=DAYS, cache=True)
            n_is = int(len(df) * IS_FRAC)
            is_df = df.iloc[:n_is]
            sig = compute(is_df, **WINNING)
            entries = sig["entries"].fillna(False).astype(bool)
            shorts = sig["short_entries"].fillna(False).astype(bool)
            sl = sig["sl"]
            direction = sig["dir"].fillna(0)
            atr = sig["atr"]
            close = is_df["close"]
            n = int(entries.sum() + shorts.sum())

            base = _run_baseline(close, entries, shorts, sl, direction)
            a2 = _run_allin(close, entries, shorts, sl, 2.0)
            a25 = _run_allin(close, entries, shorts, sl, 2.5)
            st = _run_smarttrail(close, entries, shorts, sl, atr)

            results.append({
                "symbol": sym, "timeframe": tf, "n_signals": n,
                "base_pf": base["pf"], "base_ret": base["ret"],
                "allin_1to2_pf": a2["pf"], "allin_1to2_ret": a2["ret"],
                "allin_1to2p5_pf": a25["pf"], "allin_1to2p5_ret": a25["ret"],
                "trail_pf": st["pf"], "trail_ret": st["ret"],
            })
            print(f"{sym} {tf}: n={n} base={base['pf']:.3f} "
                  f"allin2={a2['pf']:.3f} allin2.5={a25['pf']:.3f} "
                  f"trail={st['pf']:.3f}")

    r = pd.DataFrame(results)
    print("\n== PF (IS) — per cell ==")
    print(r[["symbol", "timeframe", "base_pf", "allin_1to2_pf",
             "allin_1to2p5_pf", "trail_pf"]].to_string(index=False))

    print("\n== AVERAGE PF (IS) ==")
    cols = ["base_pf", "allin_1to2_pf", "allin_1to2p5_pf", "trail_pf"]
    for c in cols:
        sub = r[c].dropna()
        mean = sub.mean() if len(sub) else np.nan
        n_above = int((sub > 1.15).sum())
        print(f"  {c:16s} mean={mean:.3f}  cells>1.15={n_above}/{len(sub)}  "
              f"target={'MET' if mean > 1.15 else 'NOT MET'}")

    r.to_csv("reports/hvfvg_exits_IS.csv", index=False)
    print("\nSaved: reports/hvfvg_exits_IS.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
