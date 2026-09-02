"""
fvg_mtf.py — Multi-TF FVG/orFVG engine (30m entry, 1h + 4h context).

Design (user spec, "FVG + sesión" flexible-bias mode):
    - 4h sets the direction gate: longs only while a recent live bullish FVG
      exists on 4h, shorts only for a live bearish FVG (shifted 1 H4 bar, no
      lookahead from the forming candle). 1h adds confluence, not a hard gate.
    - 30m trigger, two parametrizable variants (`strategy`):
        ifvg — inverse FVG: price enters an existing 30m gap and closes back
               out of it (bearish gap crossed back up -> LONG, bullish gap
               crossed back down -> SHORT).
        fvg  — FVG pullback continuation: pullback into a live 30m gap that
               holds (bull gap re-tested and held -> LONG, bear gap re-tested
               and held -> SHORT).
    - Confluences (score 0..5, gate `min_confluence`):
        4h bias aligned +1 (required when require_4h_bias=True)
        1h live FVG aligned +1
        killzone (London/NY) +1
        gap width >= ATR * gap_atr_mult +1
        volume expansion on the trigger bar +1
    - SL: trigger-bar extreme (ATR-scaled), so the harness 1:2 / 1:5 split
      scheme produces real brackets (fixes power_flow's sl=NaN enterying).

compute() returns the standard envelope plus extras (confluences, bias4, c1).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from indicators import core as ic


def _resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    out = pd.DataFrame({
        "open": df["open"].resample(rule).first(),
        "high": df["high"].resample(rule).max(),
        "low": df["low"].resample(rule).min(),
        "close": df["close"].resample(rule).last(),
        "volume": df["volume"].resample(rule).sum(),
    }).dropna()
    return out


def _htf_bias(frame: pd.DataFrame, rule: str, presence_window: int = 6) -> pd.Series:
    """Direction of recent live FVG presence on an HTF (bull +1 / bear -1 / 0).

    Computed on the resampled frame, shifted 1 HTF bar and rolled over
    `presence_window`, then ffill onto the entry index (causal).
    """
    htf = _resample(frame, rule)
    f = ic.fvg(htf["high"], htf["low"], htf["close"], lookback=30)
    bull = f["fvg_live_bull"].shift(1).rolling(presence_window, min_periods=1).max()
    bear = f["fvg_live_bear"].shift(1).rolling(presence_window, min_periods=1).max()
    dir_s = pd.Series(
        np.select([(bull > 0) & (bear <= 0), (bear > 0) & (bull <= 0)],
                  [1, -1], default=0),
        index=htf.index,
    )
    return dir_s.reindex(frame.index, method="ffill").fillna(0)


def _live_gap_edges(high: pd.Series, low: pd.Series, close: pd.Series,
                    lookback: int = 30) -> dict:
    """Rolling worst-case edges of recently-formed live gaps on the entry frame."""
    f = ic.fvg(high, low, close, lookback=lookback)
    bear_formed = f["fvg_bear"]
    bull_formed = f["fvg_bull"]

    bear_top = low.shift(2).where(bear_formed)      # higher edge of bearish gap
    bear_bottom = high.where(bear_formed)           # lower edge of bearish gap
    bull_bottom = high.shift(2).where(bull_formed)  # lower edge of bullish gap
    bull_top = low.where(bull_formed)               # higher edge of bullish gap

    live_bear = bear_formed & ~f["fvg_filled_bear"]
    live_bull = bull_formed & ~f["fvg_filled_bull"]

    w = lookback
    top_all = pd.concat(
        [bear_top.where(live_bear), bull_top.where(live_bull)], axis=1
    ).max(axis=1)
    bot_all = pd.concat(
        [bear_bottom.where(live_bear), bull_bottom.where(live_bull)], axis=1
    ).min(axis=1)
    return {
        "bear_gap": {
            "max_top": bear_top.where(live_bear).rolling(w, min_periods=1).max(),
            "min_bottom": bear_bottom.where(live_bear).rolling(w, min_periods=1).min(),
        },
        "bull_gap": {
            "max_top": bull_top.where(live_bull).rolling(w, min_periods=1).max(),
            "min_bottom": bull_bottom.where(live_bull).rolling(w, min_periods=1).min(),
        },
        "width": (top_all - bot_all).rolling(w, min_periods=1).max(),
        "live_bear": live_bear,
        "live_bull": live_bull,
    }


def _collect(entries, shorts, sl, direction, extra=None, name="fvg_mtf"):
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


def fvg_mtf(df: pd.DataFrame, strategy: str = "ifvg", **params) -> dict:
    """Multi-TF FVG engine (see module docstring). `strategy` in {ifvg, fvg}."""
    mode = "ifvg" if strategy in (None, "ifvg", "default") else strategy
    if mode not in ("ifvg", "fvg"):
        raise ValueError(f"Unknown fvg_mtf variant '{mode}'")

    htf_4h = params.pop("htf_4h", "4h")
    htf_1h = params.pop("htf_1h", "1h")
    gap_lookback = params.get("gap_lookback", 30)
    min_confluence = params.get("min_confluence", 2)
    require_4h_bias = params.get("require_4h_bias", True)
    atr_sl_mult = params.get("atr_sl_mult", 0.5)
    gap_atr_mult = params.get("gap_atr_mult", 0.5)
    vol_mult = params.get("vol_mult", 1.3)
    window_4h = params.get("window_4h", 6)
    window_1h = params.get("window_1h", 4)

    high = df["high"]
    low = df["low"]
    close = df["close"]
    volume = df["volume"]
    atr_ = ic.atr(high, low, close, period=14)

    # ---- 30m triggers ----
    g = _live_gap_edges(high, low, close, lookback=gap_lookback)
    if mode == "ifvg":
        # inverted gap: crossed the live edge and closed back out of it
        long_raw = (low <= g["bear_gap"]["max_top"]) & (close > g["bear_gap"]["max_top"])
        short_raw = (high >= g["bull_gap"]["min_bottom"]) & (close < g["bull_gap"]["min_bottom"])
    else:
        # pullback FVG that holds the edge
        long_raw = (low <= g["bull_gap"]["max_top"]) & (close > g["bull_gap"]["max_top"])
        short_raw = (high >= g["bear_gap"]["min_bottom"]) & (close < g["bear_gap"]["min_bottom"])

    # ---- context + confluence ----
    bias4 = _htf_bias(df, htf_4h, presence_window=window_4h)
    bias1 = _htf_bias(df, htf_1h, presence_window=window_1h)
    killzone = ic.is_killzone(ic.session(df.index))

    confluences = pd.Series(0, index=df.index)
    confluences += ((bias4 > 0) & long_raw) | ((bias4 < 0) & short_raw)
    confluences += ((bias1 > 0) & long_raw) | ((bias1 < 0) & short_raw)
    confluences += killzone
    confluences += g["width"] >= atr_ * gap_atr_mult
    vol_sma = volume.rolling(20, min_periods=5).mean().replace(0, np.nan)
    confluences += (volume / vol_sma > vol_mult)

    # ---- gates ----
    if require_4h_bias:
        long_raw = long_raw & (bias4 > 0)
        short_raw = short_raw & (bias4 < 0)
    long_entry = long_raw & (confluences >= min_confluence)
    short_entry = short_raw & (confluences >= min_confluence)

    # ---- SL on the trigger-bar extreme (ATR buffer) ----
    sl = pd.Series(np.nan, index=df.index)
    sl[long_entry] = low[long_entry] - atr_[long_entry] * atr_sl_mult
    sl[short_entry] = high[short_entry] + atr_[short_entry] * atr_sl_mult

    # shift 1 bar (no lookahead: execution next bar)
    long_entry = long_entry.shift(1, fill_value=False).astype(bool)
    short_entry = short_entry.shift(1, fill_value=False).astype(bool)
    sl_out = pd.Series(np.nan, index=df.index)
    sl_out[long_entry] = sl.shift(1)[long_entry]
    sl_out[short_entry] = sl.shift(1)[short_entry]

    extras = {
        "confluences": confluences,
        "bias4": bias4.astype(int),
        "bias1": bias1.astype(int),
        "mode": mode,
        "live_bear": g["live_bear"],
        "live_bull": g["live_bull"],
    }
    return _collect(long_entry, short_entry, sl_out, pd.Series(0, index=df.index),
                    extras, name=f"fvg_mtf_{mode}")


def compute(df: pd.DataFrame, strategy: str = "ifvg", **params) -> dict:
    """Dispatch for config/runner compatibility (strategy in {ifvg, fvg})."""
    return fvg_mtf(df, strategy=strategy, **params)