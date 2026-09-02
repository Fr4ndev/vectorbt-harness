"""
demon1.py — Demon v1 signals (liquidity sweep 1H + scalp OTE micro).

Two sub-strategies (from demon/strategies.py):

  A. Liquidity Sweep 1H  — volume spike + displacement + HTF bias alignment
  B. Scalp OTE micro      — |z| > 1.0 trend + price inside OTE fib zone

HTF 4h bias via Valeyre z-score (>0.5 bull, <-0.5 bear); sweep must align.

Output dict (compute()):
    entries (bool), short_entries (bool), sl (abs stop), dir (+1/-1/0),
    plus intermediate masks for inspection.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from indicators import core as ic


def compute(
    df: pd.DataFrame,
    htf_z: pd.Series | None = None,
    z_period: int = 50,
    vol_multiplier: float = 1.5,
    displacement_atr: float = 1.2,
    sl_pct: float = 0.01,
    rr: float = 3.0,
    lookback: int = 20,
    recent_window: int = 10,
    ote_lookback: int = 25,
    ote_fib_lo: float = 0.79,
    ote_fib_hi: float = 0.62,
    z_strong: float = 1.0,
    sweep: bool = True,
    ote: bool = True,
) -> dict:
    """Compute demon1 signals on an OHLCV df (open/high/low/close/volume).

    Args:
        df: primary (micro/entry) timeframe OHLCV.
        htf_z: optional precomputed 4h z-score aligned to df index (bias).
    """
    close = df["close"] if "close" in df else df["c"]
    high = df["high"]
    low = df["low"]
    open_ = df["open"] if "open" in df else close.shift(1)
    volume = df["volume"] if "volume" in df else df["v"]

    n = len(df)
    close_s = close
    open_s = open_
    high_s = high
    low_s = low
    vol_s = volume

    sweep_entries = pd.Series(False, index=df.index)
    sweep_shorts = pd.Series(False, index=df.index)
    ote_entries = pd.Series(False, index=df.index)
    ote_shorts = pd.Series(False, index=df.index)

    sl = pd.Series(np.nan, index=df.index)
    dir_sig = pd.Series(0, index=df.index)

    if htf_z is not None:
        htf_bias = ic.zscore_bias(htf_z, up=0.5, down=-0.5)
    else:
        # fallback: derive bias from the same frame's z-score so that
        # single-timeframe backtests still produce signals
        htf_bias = ic.zscore_bias(ic.valeyre_zscore(close_s, period=z_period), up=0.5, down=-0.5)

    if sweep:
        avg_vol = vol_s.rolling(lookback, min_periods=2).mean().shift(1)
        atr_ = ic.atr(high_s, low_s, close_s, period=14)
        recent_high = high_s.rolling(recent_window).max().shift(2)
        recent_low = low_s.rolling(recent_window).min().shift(2)

        vol_spike = vol_s > avg_vol * vol_multiplier
        displ = (close_s - open_s).abs() > atr_ * displacement_atr

        # bearish sweep (buy-side swept)
        bear_sweep = (high_s > recent_high) & (close_s < recent_high)
        # bullish sweep (sell-side swept)
        bull_sweep = (low_s < recent_low) & (close_s > recent_low)

        # HTF bias alignment: bull sweep requires bull bias, bear requires bear
        sweep_entries = bull_sweep & vol_spike & displ & (htf_bias == 1)
        sweep_shorts = bear_sweep & vol_spike & displ & (htf_bias == -1)

        # SL/TP: fixed 1% SL, 1:3 RR (market entry = close)
        for leg, m in ((1, sweep_entries), (-1, sweep_shorts)):
            idx = m[m].index
            if len(idx) == 0:
                continue
            e = close_s.loc[idx]
            if leg == 1:
                sl.loc[idx] = e * (1 - sl_pct)
            else:
                sl.loc[idx] = e * (1 + sl_pct)
            dir_sig.loc[idx] = leg

    if ote and htf_bias is not None:
        z = ic.valeyre_zscore(close_s, period=z_period)
        strong = z.abs() > z_strong
        recent_high_ote = high_s.rolling(ote_lookback).max()
        recent_low_ote = low_s.rolling(ote_lookback).min()
        diff = (recent_high_ote - recent_low_ote).replace(0, np.nan)

        # LONG: price in OTE zone of a bullish leg down from high
        ote_lo = recent_high_ote - diff * ote_fib_lo
        ote_hi = recent_high_ote - diff * ote_fib_hi
        in_ote_long = close_s.between(ote_lo, ote_hi)
        # SHORT: price in OTE zone of bearish leg up from low
        ote_lo_s = recent_low_ote + diff * ote_fib_hi
        ote_hi_s = recent_low_ote + diff * ote_fib_lo
        in_ote_short = close_s.between(ote_lo_s, ote_hi_s)

        ote_entries = in_ote_long & strong & (htf_bias == 1) & ~sweep_entries
        ote_shorts = in_ote_short & strong & (htf_bias == -1) & ~sweep_shorts

        for leg, m in ((1, ote_entries), (-1, ote_shorts)):
            idx = m[m].index
            if len(idx) == 0:
                continue
            e = close_s.loc[idx]
            if leg == 1:
                sl.loc[idx] = recent_low_ote.loc[idx] * (1 - 0.001)
            else:
                sl.loc[idx] = recent_high_ote.loc[idx] * (1 + 0.001)
            dir_sig.loc[idx] = leg

    entries = sweep_entries | ote_entries
    short_entries = sweep_shorts | ote_shorts
    dir_sig.loc[entries] = 1
    dir_sig.loc[short_entries] = -1

    return {
        "entries": entries,
        "short_entries": short_entries,
        "sl": sl,
        "dir": dir_sig,
        "sweep_entries": sweep_entries,
        "sweep_shorts": sweep_shorts,
        "ote_entries": ote_entries,
        "ote_shorts": ote_shorts,
        "name": "demon1",
    }
