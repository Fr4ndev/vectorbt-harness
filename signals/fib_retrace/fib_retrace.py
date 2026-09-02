"""
fib_retrace.py — Multi-TF Fibonacci retracement engine.

Spec:
    - Auto swing high/low defines the impulse leg (swing low -> swing high for
      bulls, swing high -> swing low for bears). Impulse range R = H - L.
    - Entries when price tests/breaks the 0.5 or 0.8 retracement of R with
      close-confirmation (close back above the level for longs, back below for
      shorts).
    - Exits / invalidation: stop-invalidation at -0.17/-0.27 (symmetric beyond
      the swing), TP extensions at 1.17/1.27 beyond the impulse, 0.5 partial
      level. The harness engine applies its default 1:2 / 1:5 split scheme on
      top of the strategy SL; the raw fib levels are exposed as extras.
    - Per-TF parametrization (1h/2h/4h/1d defaults) and multitimeframe
      confluence scoring (HTF bias + premium/discount + impulse quality).

compute() returns the standard envelope: entries / short_entries / sl / dir,
plus extras (confluences, fib levels, htf direction).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from indicators import core as ic

# per-TF defaults keyed by inferred frequency
TFS = {
    "1h": {"swing_lookback": 6, "htf": ["4h", "1D"], "min_confluence": 2, "atr_mult": 1.5},
    "2h": {"swing_lookback": 5, "htf": ["4h", "1D"], "min_confluence": 2, "atr_mult": 1.5},
    "4h": {"swing_lookback": 4, "htf": ["1D", "1W"], "min_confluence": 2, "atr_mult": 1.5},
    "1d": {"swing_lookback": 3, "htf": ["1W"], "min_confluence": 1, "atr_mult": 1.5},
}


def _infer_tf(index: pd.DatetimeIndex) -> str:
    freq = getattr(index, "freq", None)
    freq = str(freq.freqstr if freq is not None else "")
    if freq in ("h", "60min", "60T", "H"):
        return "1h"
    if freq == "2h":
        return "2h"
    if freq == "4h":
        return "4h"
    if freq in ("D", "d"):
        return "1d"
    return "4h"


def _resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    out = pd.DataFrame({
        "open": df["open"].resample(rule).first(),
        "high": df["high"].resample(rule).max(),
        "low": df["low"].resample(rule).min(),
        "close": df["close"].resample(rule).last(),
        "volume": df["volume"].resample(rule).sum(),
    }).dropna()
    return out


def _impulse_series(high: pd.Series, low: pd.Series, direction: int) -> tuple:
    """Causal per-bar impulse leg from swing pivots.

    direction=+1 -> bull impulse: last swing low into last swing high (H>L).
    direction=-1 -> bear impulse: last swing high into last swing low (H>L).

    Returns (leg_low, leg_high, range, valid_mask). Range is NaN where the
    impulse is not yet completed.
    """
    idx = high.index
    sw_h, sw_l = ic.swing_highs_lows(high, low)
    ff_h = high.where(sw_h).ffill()
    ff_l = low.where(sw_l).ffill()

    ts = pd.Series(idx, index=idx)
    t_h = ts.where(sw_h).ffill()
    t_l = ts.where(sw_l).ffill()

    if direction == 1:
        valid = t_h > t_l
        leg_low = ff_l
        leg_high = ff_h
    else:
        valid = t_l > t_h
        leg_low = ff_l
        leg_high = ff_h

    valid = valid & (leg_high > leg_low)
    rng = (leg_high - leg_low).where(valid)
    return leg_low, leg_high, rng, valid


def _htf_bias(df: pd.DataFrame, rule: str) -> pd.Series:
    """Bias of the last completed impulse on the higher timeframe, returned on
    the entry-frame index (ffill). +1 bull, -1 bear, 0 none."""
    htf = _resample(df, rule)
    lo, hi, rng, valid = _impulse_series(htf["high"], htf["low"], +1)
    bull = valid & rng.notna()
    lo2, hi2, rng2, valid2 = _impulse_series(htf["high"], htf["low"], -1)
    bear = valid2 & rng2.notna()
    dir_htf = pd.Series(np.where(bull, 1, np.where(bear, -1, 0)), index=htf.index)
    return dir_htf.reindex(df.index, method="ffill").fillna(0)


def _htf_mid(frame: pd.DataFrame, rule: str) -> pd.Series:
    """Mid of the last completed impulse range on HTF (premium/discount ref)."""
    htf = _resample(frame, rule)
    lo, hi, rng, valid = _impulse_series(htf["high"], htf["low"], +1)
    mid = (hi + lo) / 2
    return mid.reindex(frame.index, method="ffill")


def _collect(entries, shorts, sl, direction, extra=None, name="fib_retrace"):
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


def fib_retrace(df: pd.DataFrame, **params) -> dict:
    """Main entry point (see module docstring for the trade spec)."""
    tf = params.pop("tf", None) or _infer_tf(df.index)
    conf = dict(TFS.get(tf, TFS["4h"]))
    conf.update(params)

    swing_lookback = conf["swing_lookback"]
    entry_levels = conf.get("entry_levels", [0.5, 0.8])
    tp_ext = conf.get("tp_ext", [1.17, 1.27])
    inval_lvls = conf.get("invalidation", [0.17, 0.27])
    partial = conf.get("partial", 0.5)
    inval_deep = conf.get("invalidation_deep", max(inval_lvls))
    inval_tight = conf.get("invalidation_tight", min(inval_lvls))
    htf_rules = conf.get("htf", [])
    min_confluence = conf.get("min_confluence", 1)
    atr_mult = conf.get("atr_mult", 1.5)
    vol_mult = conf.get("vol_mult", 1.3)
    block_opposing = conf.get("block_opposing", True)

    high = df["high"]
    low = df["low"]
    close = df["close"]
    volume = df["volume"]
    atr_ = ic.atr(high, low, close, period=14)

    # ---- long context (bull impulse) ----
    lo_bull, hi_bull, rng_bull, valid_bull = _impulse_series(high, low, +1)
    long_entry = pd.Series(False, index=df.index)
    sl_long = pd.Series(np.nan, index=df.index)
    for lv in entry_levels:
        level = hi_bull - rng_bull * lv
        tested = low <= level
        confirm = close > level
        hit = tested & confirm & valid_bull & rng_bull.notna()
        long_entry = long_entry | hit
    sl_long[long_entry] = (lo_bull - rng_bull * inval_deep)[long_entry]
    # tighter invalidation when only the shallower level was tested
    deep_hit = (low <= hi_bull - rng_bull * entry_levels[-1]) & long_entry
    sl_long[deep_hit] = (lo_bull - rng_bull * inval_deep)[deep_hit]
    sl_long[long_entry & ~deep_hit] = (lo_bull - rng_bull * inval_tight)[
        long_entry & ~deep_hit
    ]

    # ---- short context (bear impulse) ----
    lo_bear, hi_bear, rng_bear, valid_bear = _impulse_series(high, low, -1)
    short_entry = pd.Series(False, index=df.index)
    sl_short = pd.Series(np.nan, index=df.index)
    for lv in entry_levels:
        level = lo_bear + rng_bear * lv
        tested = high >= level
        confirm = close < level
        hit = tested & confirm & valid_bear & rng_bear.notna()
        short_entry = short_entry | hit
    sl_short[short_entry] = (hi_bear + rng_bear * inval_deep)[short_entry]
    deep_hit_s = (high >= lo_bear + rng_bear * entry_levels[-1]) & short_entry
    sl_short[short_entry & ~deep_hit_s] = (hi_bear + rng_bear * inval_tight)[
        short_entry & ~deep_hit_s
    ]

    # ---- MTF confluence scoring ----
    confluences = pd.Series(0, index=df.index)
    htf_dirs = {}
    opposing = pd.Series(False, index=df.index)
    for rule in htf_rules:
        htf_dir = _htf_bias(df, rule)
        htf_dirs[rule] = htf_dir
        aligned = ((htf_dir > 0) & long_entry) | ((htf_dir < 0) & short_entry)
        against = ((htf_dir < 0) & long_entry) | ((htf_dir > 0) & short_entry)
        confluences += aligned
        opposing |= against

    # premium/discount: long prefers discount (below HTF mid), short the reverse
    ref_rule = htf_rules[0] if htf_rules else "1D"
    mid = _htf_mid(df, ref_rule)
    in_discount = (long_entry & close < mid) | (short_entry & close > mid)
    confluences += in_discount

    # impulse quality: range vs ATR, volume expansion on the swing
    rng_ref = rng_bull.where(long_entry).fillna(rng_bear.where(short_entry))
    strong = rng_ref > atr_ * atr_mult
    confluences += strong.fillna(False)
    vol_sma = volume.rolling(20, min_periods=5).mean().replace(0, np.nan)
    vol_exp = volume / vol_sma > vol_mult
    confluences += (vol_exp & (long_entry | short_entry))

    # session confluence (London/NY)
    confluences += (ic.is_killzone(ic.session(df.index)) & (long_entry | short_entry))

    # gates
    if block_opposing:
        long_entry = long_entry & ~opposing
        short_entry = short_entry & ~opposing
    long_entry = long_entry & (confluences >= min_confluence)
    short_entry = short_entry & (confluences >= min_confluence)

    # shift 1 bar to avoid lookahead (execution at the next bar)
    long_entry = long_entry.shift(1, fill_value=False).astype(bool)
    short_entry = short_entry.shift(1, fill_value=False).astype(bool)
    sl_out = pd.Series(np.nan, index=df.index)
    sl_out[long_entry] = sl_long.shift(1)[long_entry]
    sl_out[short_entry] = sl_short.shift(1)[short_entry]

    direction = pd.Series(0, index=df.index)
    extras = {
        "confluences": confluences,
        "htf_dir": htf_dirs,
        "tp_ext": tp_ext,
        "partial": partial,
        "inv_levels": inval_lvls,
        "valid_long": valid_bull,
        "valid_short": valid_bear,
    }
    return _collect(long_entry, short_entry, sl_out, direction, extras,
                    name="fib_retrace")


def compute(df: pd.DataFrame, strategy: str = "fib_retrace", **params) -> dict:
    """Dispatch (kept for config/runner compatibility)."""
    if strategy in ("all", "default", "fib_retrace"):
        return fib_retrace(df, **params)
    raise ValueError(f"Unknown fib_retrace variant '{strategy}'")