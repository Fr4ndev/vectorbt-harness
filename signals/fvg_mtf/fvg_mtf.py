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
    - SSRN-quality gate (`quality_tfs`, default 1h): Score = (GapWidth/ATR)*
      (Vol/SMA20) must be >= `quality_min` before the trigger fires.
    - Adaptive confluence (`adaptive_confluence`): when entry ATR > its rolling
      p75 (`adaptive_window`) the gate jumps to `adaptive_high` (4), else stays
      at `adaptive_low` (2); replaces the rigid strict gate for strict_tfs.
    - Runner invalidation (`trail_4h`): leg B stop is anchored to the opposite
      extreme of the live 4h FVG (rising bottom for longs / falling top for
      shorts) instead of static BE — exposed as `runner_inv` in the envelope.

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


def _htf_fvg_inv(frame: pd.DataFrame, rule: str,
                 presence_window: int = 6) -> tuple:
    """Trailing-invalidation anchors: opposite extremes of recent live HTF FVGs.

    For LONG runner invalidation we keep the *highest* live bullish-FVG bottom
    within the presence window (tightest protective level); for SHORT the
    *lowest* live bearish-FVG top. Shifted 1 HTF bar (causal) and ffill.
    """
    htf = _resample(frame, rule)
    f = ic.fvg(htf["high"], htf["low"], htf["close"], lookback=30)
    live_bull = f["fvg_live_bull"].shift(1)
    live_bear = f["fvg_live_bear"].shift(1)
    bull_bottom = htf["high"].shift(2).where(live_bull)
    bear_top = htf["low"].shift(2).where(live_bear)
    inv_long = bull_bottom.rolling(presence_window, min_periods=1).max()
    inv_short = bear_top.rolling(presence_window, min_periods=1).min()
    return (inv_long.reindex(frame.index, method="ffill"),
            inv_short.reindex(frame.index, method="ffill"))


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


def fvg_mtf(df: pd.DataFrame, strategy: str = "ifvg", **params) -> dict:
    """Multi-TF FVG engine (see module docstring). `strategy` in {ifvg, fvg}."""
    mode = "ifvg" if strategy in (None, "ifvg", "default") else strategy
    if mode not in ("ifvg", "fvg"):
        raise ValueError(f"Unknown fvg_mtf variant '{mode}'")

    entry_tf = params.pop("tf", None) or _infer_tf(df.index)
    htf_4h = params.pop("htf_4h", "4h")
    htf_1h = params.pop("htf_1h", "1h")
    gap_lookback = params.get("gap_lookback", 30)
    # stricter confluence on the weak entry TFs (BTC 1h blowout / 4h noise)
    strict_tfs = params.get("strict_tfs", ("1h", "4h"))
    strict_min = params.get("strict_min_confluence", 4)
    user_min = params.get("min_confluence")
    min_confluence = user_min if user_min is not None else (
        strict_min if entry_tf in strict_tfs else 2
    )
    require_4h_bias = params.get("require_4h_bias", True)
    atr_sl_mult = params.get("atr_sl_mult", 0.5)
    gap_atr_mult = params.get("gap_atr_mult", 0.5)
    vol_mult = params.get("vol_mult", 1.3)
    window_4h = params.get("window_4h", 6)
    window_1h = params.get("window_1h", 4)
    # ---- SSRN-quality gate: Score = (Gap Width / ATR) * (Vol / SMA(Vol,20)) ----
    quality_tfs = params.get("quality_tfs", ("1h",))
    quality_min = params.get("quality_min", 0.30)
    # ---- adaptive confluence: ATR > its rolling p75 -> high gate, else low ----
    adaptive_confluence = params.get("adaptive_confluence", False)
    adaptive_window = params.get("adaptive_window", 250)
    adaptive_high = params.get("adaptive_high", 4)
    adaptive_low = params.get("adaptive_low", 2)
    # ---- runner invalidation anchored to the opposite 4h-FVG extreme ----
    trail_4h = params.get("trail_4h", True)
    trail_tfs = params.get("trail_tfs", strict_tfs)
    trail_min_atr = params.get("trail_min_atr", 0.5)

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
    vol_mult_s = (volume / vol_sma).replace([np.inf, -np.inf], np.nan)
    confluences += (vol_mult_s > vol_mult)

    # ---- quality score (SSRN gap filter): width/ATR * volume/SMA20 ----
    gap_quality = (g["width"] / atr_.replace(0, np.nan)) * vol_mult_s
    use_quality = entry_tf in quality_tfs
    quality_ok = gap_quality >= quality_min
    if use_quality:
        long_raw = long_raw & quality_ok
        short_raw = short_raw & quality_ok

    # ---- gates ----
    if require_4h_bias:
        long_raw = long_raw & (bias4 > 0)
        short_raw = short_raw & (bias4 < 0)
    if adaptive_confluence and entry_tf in strict_tfs:
        atr_p75 = atr_.rolling(adaptive_window, min_periods=60).quantile(0.75)
        min_conf = pd.Series(
            np.where(atr_ > atr_p75, adaptive_high, adaptive_low), index=df.index
        )
    else:
        min_conf = min_confluence
    long_entry = long_raw & (confluences >= min_conf)
    short_entry = short_raw & (confluences >= min_conf)

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

    # ---- runner invalidation anchored to the opposite 4h-FVG extreme ----
    trail = pd.Series(np.nan, index=df.index)
    if trail_4h and entry_tf in trail_tfs:
        inv_long, inv_short = _htf_fvg_inv(df, htf_4h, presence_window=window_4h)
        inv_long_raw = inv_long.shift(1)
        inv_short_raw = inv_short.shift(1)
        # force an anchor floor at entry - ATR*k and keep the FVG level when present
        atr_lim = atr_.shift(1) * trail_min_atr
        anchor_long = inv_long_raw.where(inv_long_raw.notna(), close - atr_lim)
        anchor_short = inv_short_raw.where(inv_short_raw.notna(), close + atr_lim)
        trail[long_entry] = anchor_long[long_entry]
        trail[short_entry] = anchor_short[short_entry]
        trail[long_entry] = trail[long_entry].clip(upper=close[long_entry])
        trail[short_entry] = trail[short_entry].clip(lower=close[short_entry])

    extras = {
        "confluences": confluences,
        "bias4": bias4.astype(int),
        "bias1": bias1.astype(int),
        "mode": mode,
        "live_bear": g["live_bear"],
        "live_bull": g["live_bull"],
        "gap_quality": gap_quality,
        "min_confluence_per_bar": min_conf,
        "trail_4h": trail_4h,
        "runner_inv": trail,
    }
    return _collect(long_entry, short_entry, sl_out, pd.Series(0, index=df.index),
                    extras, name=f"fvg_mtf_{mode}")


def compute(df: pd.DataFrame, strategy: str = "ifvg", **params) -> dict:
    """Dispatch for config/runner compatibility (strategy in {ifvg, fvg})."""
    return fvg_mtf(df, strategy=strategy, **params)