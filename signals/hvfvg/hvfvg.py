"""
hvfvg.py — High-Volume FVG (HVFVG) signal for the harness.

Vectorized, direction-agnostic (long/short) port of the HERMES HVFVG spec
(~/Escritorio/HERMES_HVFVG_STRATEGY.md / hvfvg_engine_v2.py) adapted to the
harness compute() envelope.

Pipeline (all causal / no lookahead):
    1. 3-candle FVG detection (formation candle i):
           Bullish: low[i] > high[i-2]  -> gap [high[i-2], low[i]]
           Bearish: high[i] < low[i-2]  -> gap [high[i], low[i-2]]
    2. Volume-anomaly filter on the displacement candle (i-1), NO z-score:
           volume[i-1] > volume.rolling(lookback).mean()[i-1] * vol_mult
           (defaults: lookback=50, vol_mult=1.8)
    3. Retest + institutional defense validation per live HV-FVG:
           - price retests (touches) the gap zone without a close through it
             (i.e. the FVG is not mitigated)
           - absorption: a retest candle with volume > rolling_mean(20) * 1.5
             AND body ratio abs(close-open)/(high-low+eps) < 0.4
           - rejection: a subsequent close outside the zone in the direction
             of the original impulse (long: close > gap_high; short: close <
             gap_low)
    4. Levels:
           Entry : deep inside the FVG (fvg_low + entry_ratio*height long /
                   fvg_high - entry_ratio*height short), entry_ratio=0.15
           SL    : FVG extreme +/- ATR(14) * atr_sl_mult (default 0.25)
           TP    : nearest ERL swing point beyond the impulse extreme, or
                   fallback entry +/- ATR(14) * tp_atr_mult
    The signal fires on the rejection bar; entries/SL/TP are shifted 1 bar so
    execution happens at the next open (matches the harness no-lookahead rule).

compute() -> standard envelope + extras (fvg_zone, entry, tp sources, ...).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from indicators import core as ic


def _infer_tf(index: pd.DatetimeIndex) -> str:
    freq = getattr(index, "freq", None)
    freq = str(freq.freqstr if freq is not None else "")
    if freq in ("h", "60min", "60T", "H"):
        return "1h"
    if freq == "30min":
        return "30m"
    if freq == "2h":
        return "2h"
    if freq == "4h":
        return "4h"
    if freq in ("D", "d"):
        return "1d"
    if len(index) >= 2:
        hours = np.median(np.diff(index.asi8)) / 3.6e12
        if hours <= 0.75:
            return "30m"
        if hours <= 1.5:
            return "1h"
        if hours <= 3.0:
            return "2h"
        if hours <= 6.0:
            return "4h"
        if hours <= 30.0:
            return "1d"
    return "30m"


def _swing_pivots(high: pd.Series, low: pd.Series,
                  window: int) -> tuple:
    """Fractal pivots (n_left=n_right=window), causal.

    A pivot is only True once its right flank is fully confirmed, so a pivot
    never uses future bars (no lookahead).
    """
    k = 2 * window + 1
    pivot_h = high == high.rolling(k, center=True, min_periods=1).max()
    pivot_l = low == low.rolling(k, center=True, min_periods=1).min()
    return (pivot_h.shift(window + 1, fill_value=False),
            pivot_l.shift(window + 1, fill_value=False))


def _erl_swing_target(high: pd.Series, low: pd.Series, impulse_end: float,
                      direction: int, swing_window: int,
                      fallback: float) -> tuple:
    """Nearest confirmed swing point beyond the impulse extreme (ERL).

    Long: nearest confirmed swing-high strictly above impulse_end.
    Short: nearest confirmed swing-low strictly below impulse_end.
    Returns (target_level, kind).
    """
    sw_h, sw_l = _swing_pivots(high, low, swing_window)
    if direction == 1:
        highs = high.where(sw_h).dropna()
        cand = highs[highs > impulse_end * 1.001]
        if len(cand):
            return float(cand.min()), "swing_high"
    else:
        lows = low.where(sw_l).dropna()
        cand = lows[lows < impulse_end * 0.999]
        if len(cand):
            return float(cand.max()), "swing_low"
    return fallback, "fallback_atr"


def _collect(entries, shorts, sl, direction, extra=None, name="hvfvg"):
    direction = direction.astype(int)
    direction[entries | shorts] = np.where(entries, 1, -1)[entries | shorts]
    out = {
        "entries": entries.astype(bool),
        "short_entries": shorts.astype(bool),
        "sl": sl,
        "dir": direction,
        "name": name,
    }
    if extra:
        out.update(extra)
    return out


def compute(df: pd.DataFrame, **params) -> dict:
    """HVFVG signal envelope (see module docstring)."""
    high = df["high"]
    low = df["low"]
    close = df["close"]
    volume = df["volume"]
    open_ = df["open"]
    n = len(df)

    lookback = int(params.get("lookback", 50))          # volume anomaly window
    vol_mult = float(params.get("vol_mult", 1.8))       # displacement volume
    atr_sl_mult = float(params.get("atr_sl_mult", 0.25))  # SL buffer (ATR)
    tp_atr_mult = float(params.get("tp_atr_mult", 2.0))   # fallback TP (ATR)
    entry_ratio = float(params.get("entry_ratio", 0.15))
    abs_vol_mult = float(params.get("abs_vol_mult", 1.5))  # absorption volume
    abs_body_max = float(params.get("abs_body_max", 0.4))  # absorption body
    retest_max = int(params.get("retest_max", 12))         # defense window
    swing_window = int(params.get("swing_window", 5))      # ERL swing fractal

    atr_ = ic.atr(high, low, close, period=14)

    # ---- 1. FVG formation (candle i) ----
    bull_form = (low > high.shift(2)).fillna(False)
    bear_form = (high < low.shift(2)).fillna(False)

    # ---- 2. volume anomaly on the displacement candle (i-1), no z-score ----
    vol_sma = volume.rolling(lookback, min_periods=lookback).mean().shift(1)
    disp_vol = volume.shift(1)
    vol_ok = (disp_vol > vol_sma * vol_mult) & vol_sma.notna()

    bull_fvg = (bull_form & vol_ok).to_numpy()
    bear_fvg = (bear_form & vol_ok).to_numpy()

    bull_gap_low = high.shift(2).to_numpy()   # bottom
    bull_gap_high = low.to_numpy()            # top
    bear_gap_low = high.to_numpy()            # bottom
    bear_gap_high = low.shift(2).to_numpy()   # top

    # absorption context (SMA20 of volume + body ratio)
    vol_sma20 = volume.rolling(20, min_periods=5).mean().replace(0, np.nan)
    rng_ = (high - low).replace(0, np.nan)
    body_ratio = ((close - open_).abs() / rng_).replace([np.inf, -np.inf], np.nan)

    c_high = high.to_numpy()
    c_low = low.to_numpy()
    c_close = close.to_numpy()
    c_vol = volume.to_numpy()
    c_vs20 = vol_sma20.to_numpy()
    c_body = body_ratio.to_numpy()
    c_atr = atr_.to_numpy()

    entry_sig = np.zeros(n, dtype=bool)
    short_sig = np.zeros(n, dtype=bool)
    sl_levels = np.full(n, np.nan)
    tp1_levels = np.full(n, np.nan)
    tp2_levels = np.full(n, np.nan)
    entry_price = np.full(n, np.nan)
    erl_kind = np.array([""] * n, dtype=object)

    # ---- 3. retest + defense per candidate HV-FVG (forward scan) ----
    for i in range(2, n):
        if not (bull_fvg[i] or bear_fvg[i]):
            continue
        if bull_fvg[i]:
            gl, gh = bull_gap_low[i], bull_gap_high[i]
        else:
            gl, gh = bear_gap_low[i], bear_gap_high[i]
        if not (np.isfinite(gl) and np.isfinite(gh)) or gh <= gl:
            continue
        direction = 1 if bull_fvg[i] else -1

        end = min(i + 1 + retest_max, n)
        absorbed = False
        emit_at = -1
        for t in range(i + 1, end):
            # mitigation: price closed through the whole gap before rejection
            if direction == 1 and c_close[t] < gl:
                break
            if direction == -1 and c_close[t] > gh:
                break
            # touches the zone?
            touches = c_low[t] <= gh and c_high[t] >= gl
            if not touches and not absorbed:
                continue
            # (once absorbed, keep scanning for a rejection close)
            if not absorbed:
                vol_ok_abs = (not np.isnan(c_vs20[t])) and c_vol[t] > c_vs20[t] * abs_vol_mult
                body_ok = (not np.isnan(c_body[t])) and c_body[t] < abs_body_max
                if vol_ok_abs and body_ok:
                    absorbed = True
            # rejection close in favor of the move
            if absorbed:
                if direction == 1 and c_close[t] > gh:
                    entry_sig[t] = True
                    emit_at = t
                    break
                if direction == -1 and c_close[t] < gl:
                    short_sig[t] = True
                    emit_at = t
                    break

        if emit_at < 0:
            continue
        t = emit_at

        if direction == 1:
            height = gh - gl
            _entry = gl + entry_ratio * height
            _sl = gl - c_atr[t] * atr_sl_mult
        else:
            height = gh - gl
            _entry = gh - entry_ratio * height
            _sl = gh + c_atr[t] * atr_sl_mult

        impulse_end = c_high[i - 1] if direction == 1 else c_low[i - 1]
        fallback_tp = _entry + c_atr[t] * tp_atr_mult if direction == 1 \
            else _entry - c_atr[t] * tp_atr_mult
        erl, kind = _erl_swing_target(high, low, impulse_end, direction,
                                      swing_window, fallback_tp)
        if direction == 1:
            erl = max(erl, _entry)
            tp1, tp2 = erl, erl
        else:
            erl = min(erl, _entry)
            tp1, tp2 = erl, erl

        entry_price[t] = _entry
        sl_levels[t] = _sl
        tp1_levels[t] = tp1
        tp2_levels[t] = tp2
        erl_kind[t] = kind

    # ---- shift 1 bar (execution at next open, no lookahead) ----
    long_entry = pd.Series(entry_sig, index=df.index).shift(1, fill_value=False).astype(bool)
    short_entry = pd.Series(short_sig, index=df.index).shift(1, fill_value=False).astype(bool)

    sl_out = pd.Series(np.nan, index=df.index)
    tp1_out = pd.Series(np.nan, index=df.index)
    tp2_out = pd.Series(np.nan, index=df.index)
    entry_out = pd.Series(np.nan, index=df.index)
    erlkind_out = pd.Series("", index=df.index)
    sl_out[long_entry] = pd.Series(sl_levels, index=df.index).shift(1)[long_entry]
    sl_out[short_entry] = pd.Series(sl_levels, index=df.index).shift(1)[short_entry]
    tp1_out[long_entry] = pd.Series(tp1_levels, index=df.index).shift(1)[long_entry]
    tp1_out[short_entry] = pd.Series(tp1_levels, index=df.index).shift(1)[short_entry]
    tp2_out[long_entry] = pd.Series(tp2_levels, index=df.index).shift(1)[long_entry]
    tp2_out[short_entry] = pd.Series(tp2_levels, index=df.index).shift(1)[short_entry]
    entry_out[long_entry | short_entry] = pd.Series(entry_price, index=df.index).shift(1)[long_entry | short_entry]
    erlkind_out[long_entry | short_entry] = pd.Series(erl_kind, index=df.index).shift(1)[long_entry | short_entry]

    direction = pd.Series(0, index=df.index)
    extras = {
        "tp1": tp1_out,
        "tp2": tp2_out,
        "entry": entry_out,
        "erl_kind": erlkind_out,
        "vol_anomaly": pd.Series(vol_ok.to_numpy(), index=df.index),
        "bull_fvg": pd.Series(bull_fvg, index=df.index),
        "bear_fvg": pd.Series(bear_fvg, index=df.index),
        "fvg_zone_low": pd.Series(bull_gap_low, index=df.index),
        "fvg_zone_high": pd.Series(bull_gap_high, index=df.index),
        "atr": atr_,
    }
    return _collect(long_entry, short_entry, sl_out, direction, extras,
                    name="hvfvg")
