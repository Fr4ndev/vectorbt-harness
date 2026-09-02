"""
fib_retrace.py — Fibonacci retracement strategies (port of ccxtv4 FibonacciEngine).

Two variants:
  v3 (fib_retrace) — swing detected on the SAME TF. DISCARDED 2026-09-02 (IS-only,
      bad RR due to noisy short swings). Kept for reference.
  v4 (fib_htf)     — swing detected on HTF (faithful to the action server's
      tf_high parameter). Entry on LTF at the retracement zone of the HTF swing.
      Targets: conservative (0.618R from entry) + classic (1.272R runner).

CCXtv4 engine constants (exact port):
    RETRACEMENT_LEVELS  = {0.236, 0.382, 0.5, 0.618, 0.786, 0.886, 1.0}
    GOLDEN_POCKET       = [0.618, 0.786]
    CONSERVATIVE_TARGETS= {0.5, 0.618, 0.66}   (realistic, actionable)
    EXPANSION_LEVELS    = {1.272, 1.618, 2.0, 2.618, 4.236}  (classic ABCD)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from indicators import core as ic

# ── CCXtv4 fib_engine constants (exact port) ─────────────────────────────
RETRACEMENT_LEVELS: dict[str, float] = {
    "0.0": 0.0, "0.236": 0.236, "0.382": 0.382, "0.5": 0.500,
    "0.618": 0.618, "0.786": 0.786, "0.886": 0.886, "1.0": 1.000,
}
EXPANSION_LEVELS: dict[str, float] = {
    "1.272": 1.272, "1.618": 1.618, "2.0": 2.0, "2.618": 2.618, "4.236": 4.236,
}
CONSERVATIVE_TARGETS: dict[str, float] = {
    "0.5": 0.5, "0.618": 0.618, "0.66": 0.66,
}
GOLDEN_POCKET_LOW = 0.618
GOLDEN_POCKET_HIGH = 0.786

# per-TF defaults (v3 — fib_retrace, same-TF swing, DISCARDED)
TFS = {
    "1h": {"htf": ["4h", "1d"], "min_confluence": 2},
    "2h": {"htf": ["4h", "1d"], "min_confluence": 2},
    "4h": {"htf": ["1d", "1w"], "min_confluence": 2},
    "1d": {"htf": ["1w"], "min_confluence": 1},
}

# v4 (fib_htf) — default swing TF per entry TF (faithful to action server tf_high)
_SWING_TF_MAP = {"1h": "1D", "2h": "1D", "4h": "1D", "1d": "1W"}
_RESAMPLE_RULE = {"1h": "1D", "2h": "1D", "4h": "1D", "1d": "1W"}


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


def _swing_pivots(high: pd.Series, low: pd.Series, window: int) -> tuple:
    """Fractal pivots, CCXtv4-style (n_left=n_right=window), causal.

    Returns (sw_high, sw_low) booleans shifted by window+1 bars so a pivot is
    only True once its right flank is fully confirmed (no lookahead).
    """
    k = 2 * window + 1
    pivot_h = high == high.rolling(k, center=True, min_periods=1).max()
    pivot_l = low == low.rolling(k, center=True, min_periods=1).min()
    return pivot_h.shift(window + 1, fill_value=False), pivot_l.shift(window + 1, fill_value=False)


def _impulse_series(high: pd.Series, low: pd.Series, direction: int,
                    window: int = 2) -> tuple:
    """Causal per-bar impulse leg from confirmed swing pivots.

    direction=+1 -> bull impulse (last confirmed pivot is a HIGH after the last
    low); direction=-1 -> bear impulse (last confirmed pivot a LOW after the
    last high). Returns (leg_low, leg_high, range, valid_mask).
    """
    idx = high.index
    sw_h, sw_l = _swing_pivots(high, low, window)
    ff_h = high.where(sw_h).ffill()
    ff_l = low.where(sw_l).ffill()

    ts = pd.Series(idx, index=idx)
    t_h = ts.where(sw_h).ffill()
    t_l = ts.where(sw_l).ffill()

    if direction == 1:
        valid = t_h > t_l
    else:
        valid = t_l > t_h

    leg_low = ff_l
    leg_high = ff_h
    valid = valid & (leg_high > leg_low)
    rng = (leg_high - leg_low).where(valid)
    return leg_low, leg_high, rng, valid


def _htf_bias(df: pd.DataFrame, rule: str, window: int) -> pd.Series:
    """Direction of the last completed impulse on the HTF (ffill onto entry TF)."""
    htf = _resample(df, rule)
    _, _, rng_b, valid_b = _impulse_series(htf["high"], htf["low"], +1, window)
    _, _, rng_s, valid_s = _impulse_series(htf["high"], htf["low"], -1, window)
    dir_htf = pd.Series(
        np.where(valid_b & rng_b.notna(), 1, np.where(valid_s & rng_s.notna(), -1, 0)),
        index=htf.index,
    )
    return dir_htf.reindex(df.index, method="ffill").fillna(0)


def _htf_mid(frame: pd.DataFrame, rule: str) -> pd.Series:
    htf = _resample(frame, rule)
    mid = (htf["high"] + htf["low"]) / 2
    return mid.reindex(frame.index, method="ffill")


def _expand(entry: pd.Series, rng: pd.Series, ratio: float, direction: int) -> pd.Series:
    """CCXtv4 expansion formula: D = entry +/- ratio*R (ABCD pattern)."""
    return entry + direction * ratio * rng


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
    tf = _infer_tf(df.index)
    conf = TFS.get(tf, TFS["4h"])

    swing_window = params.get("swing_window", 2)
    entry_levels = params.get("entry_levels", [0.5, 0.618])   # retracements tested
    exit_cons = params.get("exit_cons", 0.618)                # conservative target ratio
    exit_classic = params.get("exit_classic", 1.272)          # classic expansion ratio
    invalidation = params.get("invalidation", 0.10)           # beyond swing extreme
    atr_sl_mult = params.get("atr_sl_mult", 0.5)
    min_confluence = params.get("min_confluence", conf["min_confluence"])
    htf_rules = params.get("htf", conf["htf"])
    atr_mult = params.get("atr_mult", 1.5)
    vol_mult = params.get("vol_mult", 1.3)
    block_opposing = params.get("block_opposing", True)
    weight_tp1 = params.get("weight_tp1", 0.7)

    high = df["high"]
    low = df["low"]
    close = df["close"]
    volume = df["volume"]
    atr_ = ic.atr(high, low, close, period=14)

    lo_b, hi_b, rng_b, valid_b = _impulse_series(high, low, +1, swing_window)
    lo_s, hi_s, rng_s, valid_s = _impulse_series(high, low, -1, swing_window)

    # ---- LONG context ----
    long_raw = pd.Series(False, index=df.index)
    sl_long = pd.Series(np.nan, index=df.index)
    tp1_long = pd.Series(np.nan, index=df.index)
    tp2_long = pd.Series(np.nan, index=df.index)
    gp_long = pd.Series(False, index=df.index)
    for lv in entry_levels:
        level = hi_b - rng_b * lv
        tested = low <= level
        confirm = close > level
        hit = tested & confirm & valid_b & rng_b.notna()
        long_raw |= hit
        gp_long |= hit & (lv >= GOLDEN_POCKET_LOW)
    sl_long[long_raw] = (lo_b - rng_b * invalidation - atr_ * atr_sl_mult)[long_raw]
    tp1_long[long_raw] = _expand(close, rng_b, exit_cons, +1)[long_raw]
    tp2_long[long_raw] = _expand(close, rng_b, exit_classic, +1)[long_raw]

    # ---- SHORT context ----
    short_raw = pd.Series(False, index=df.index)
    sl_short = pd.Series(np.nan, index=df.index)
    tp1_short = pd.Series(np.nan, index=df.index)
    tp2_short = pd.Series(np.nan, index=df.index)
    gp_short = pd.Series(False, index=df.index)
    for lv in entry_levels:
        level = lo_s + rng_s * lv
        tested = high >= level
        confirm = close < level
        hit = tested & confirm & valid_s & rng_s.notna()
        short_raw |= hit
        gp_short |= hit & (lv >= GOLDEN_POCKET_LOW)
    sl_short[short_raw] = (hi_s + rng_s * invalidation + atr_ * atr_sl_mult)[short_raw]
    tp1_short[short_raw] = _expand(close, rng_s, exit_cons, -1)[short_raw]
    tp2_short[short_raw] = _expand(close, rng_s, exit_classic, -1)[short_raw]

    # ---- MTF confluence scoring ----
    confluences = pd.Series(0, index=df.index)
    htf_dirs = {}
    opposing = pd.Series(False, index=df.index)
    for rule in htf_rules:
        htf_dir = _htf_bias(df, rule, swing_window)
        htf_dirs[rule] = htf_dir
        aligned = ((htf_dir > 0) & long_raw) | ((htf_dir < 0) & short_raw)
        against = ((htf_dir < 0) & long_raw) | ((htf_dir > 0) & short_raw)
        confluences += aligned
        opposing |= against

    # premium/discount: longs prefer discount (below HTF mid), shorts the reverse
    ref_rule = htf_rules[0] if htf_rules else "1d"
    mid = _htf_mid(df, ref_rule)
    in_discount = (long_raw & close < mid) | (short_raw & close > mid)
    confluences += in_discount

    # impulse quality (range vs ATR) + volume expansion + golden-pocket touch
    rng_ref = rng_b.where(long_raw).fillna(rng_s.where(short_raw))
    strong = rng_ref > atr_ * atr_mult
    confluences += strong.astype(bool).fillna(False)
    vol_sma = volume.rolling(20, min_periods=5).mean().replace(0, np.nan)
    vol_exp = volume / vol_sma > vol_mult
    confluences += (vol_exp & (long_raw | short_raw))
    confluences += (gp_long | gp_short)
    confluences += (ic.is_killzone(ic.session(df.index)) & (long_raw | short_raw))

    # ---- gates ----
    if block_opposing:
        long_raw = long_raw & ~opposing
        short_raw = short_raw & ~opposing
    long_entry = long_raw & (confluences >= min_confluence)
    short_entry = short_raw & (confluences >= min_confluence)

    # shift 1 bar (no lookahead: execution at the next open)
    long_entry = long_entry.shift(1, fill_value=False).astype(bool)
    short_entry = short_entry.shift(1, fill_value=False).astype(bool)
    sl_out = pd.Series(np.nan, index=df.index)
    sl_out[long_entry] = sl_long.shift(1)[long_entry]
    sl_out[short_entry] = sl_short.shift(1)[short_entry]
    tp1_out = pd.Series(np.nan, index=df.index)
    tp2_out = pd.Series(np.nan, index=df.index)
    tp1_out[long_entry] = tp1_long.shift(1)[long_entry]
    tp1_out[short_entry] = tp1_short.shift(1)[short_entry]
    tp2_out[long_entry] = tp2_long.shift(1)[long_entry]
    tp2_out[short_entry] = tp2_short.shift(1)[short_entry]

    direction = pd.Series(0, index=df.index)
    extras = {
        "confluences": confluences,
        "htf_dir": htf_dirs,
        "tp1": tp1_out,
        "tp2": tp2_out,
        "weight_tp1": weight_tp1,
        "exit_cons": exit_cons,
        "exit_classic": exit_classic,
        "inv_levels": invalidation,
        "valid_long": valid_b,
        "valid_short": valid_s,
        "golden_pocket": gp_long | gp_short,
    }
    return _collect(long_entry, short_entry, sl_out, direction, extras,
                    name="fib_retrace")


# ─────────────────────────────────────────────────────────────────────────────
# v4: fib_htf — swing HTF → entry LTF (faithful to action server tf_high)
# ─────────────────────────────────────────────────────────────────────────────

def _htf_swing_segments(htf_high: pd.Series, htf_low: pd.Series,
                        window: int) -> dict:
    """Compute running bull/bear legs on the HTF frame.

    Bull segments start at each confirmed pivot-low; within each segment,
    run_high = cummax(high) and leg_low = pivot-low price, R = run_high - leg_low.
    Bear segments start at each confirmed pivot-high; within each segment,
    run_low = cummin(low) and leg_high = pivot-high price, R = leg_high - run_low.

    Direction: bull = last pivot-low is more recent than last pivot-high.

    Returns dict of Series on the HTF index.
    """
    sw_h, sw_l = _swing_pivots(htf_high, htf_low, window)

    # timestamps for direction detection
    idx = htf_high.index
    ts = pd.Series(idx, index=idx)
    t_h = ts.where(sw_h).ffill()
    t_l = ts.where(sw_l).ffill()

    # ---- Bull segments (start at each pivot low) ----
    seg_bull = sw_l.astype(int).cumsum()
    run_high_b = htf_high.groupby(seg_bull).cummax()
    leg_low_b = htf_low.where(sw_l).ffill()
    R_b = run_high_b - leg_low_b

    # ---- Bear segments (start at each pivot high) ----
    seg_bear = sw_h.astype(int).cumsum()
    run_low_b = htf_low.groupby(seg_bear).cummin()
    leg_high_b = htf_high.where(sw_h).ffill()
    R_bear = leg_high_b - run_low_b

    return {
        "bull": t_l > t_h,
        "bear": t_h > t_l,
        "run_high": run_high_b,
        "leg_low": leg_low_b,
        "R_bull": R_b,
        "run_low": run_low_b,
        "leg_high": leg_high_b,
        "R_bear": R_bear,
        "sw_h": sw_h,
        "sw_l": sw_l,
    }


def fib_htf(df: pd.DataFrame, **params) -> dict:
    """v4: swing detected on HTF, entry on LTF. Faithful to fib_engine tf_high."""
    tf = _infer_tf(df.index)

    swing_tf = params.get("swing_tf", _SWING_TF_MAP.get(tf, "1D"))
    resample_rule = params.get("resample_rule", _RESAMPLE_RULE.get(tf, "1D"))
    swing_window = params.get("swing_window", 2)
    entry_levels = params.get("entry_levels", [0.5, 0.618])
    exit_cons = params.get("exit_cons", 0.618)
    exit_classic = params.get("exit_classic", 1.272)
    invalidation = params.get("invalidation", 0.10)
    min_confluence = params.get("min_confluence", 2)
    atr_mult = params.get("atr_mult", 1.5)
    vol_mult = params.get("vol_mult", 1.3)
    weight_tp1 = params.get("weight_tp1", 0.7)

    high = df["high"]
    low = df["low"]
    close = df["close"]
    volume = df["volume"]
    atr_ = ic.atr(high, low, close, period=14)

    # ---- HTF swing (causal, no lookahead) ----
    htf = _resample(df, resample_rule)
    if len(htf) < swing_window * 2 + 3:
        return _collect(
            pd.Series(False, index=df.index),
            pd.Series(False, index=df.index),
            pd.Series(np.nan, index=df.index),
            pd.Series(0, index=df.index),
            name="fib_htf",
        )
    htf = htf.iloc[:-1]  # drop last partial HTF bar

    segs = _htf_swing_segments(htf["high"], htf["low"], swing_window)

    # ---- Map HTF data onto LTF index (ffill) ----
    def _to_ltf(s: pd.Series) -> pd.Series:
        return s.reindex(df.index, method="ffill")

    bull_ltf = _to_ltf(segs["bull"]).fillna(False)
    bear_ltf = _to_ltf(segs["bear"]).fillna(False)
    run_high_ltf = _to_ltf(segs["run_high"])
    leg_low_ltf = _to_ltf(segs["leg_low"])
    R_bull_ltf = _to_ltf(segs["R_bull"])
    run_low_ltf = _to_ltf(segs["run_low"])
    leg_high_ltf = _to_ltf(segs["leg_high"])
    R_bear_ltf = _to_ltf(segs["R_bear"])

    htf_mid_rule = resample_rule
    mid = _htf_mid(df, htf_mid_rule)

    # ---- LONG (bull HTF pullback) ----
    long_raw = pd.Series(False, index=df.index)
    sl_long = pd.Series(np.nan, index=df.index)
    tp1_long = pd.Series(np.nan, index=df.index)
    tp2_long = pd.Series(np.nan, index=df.index)
    gp_long = pd.Series(False, index=df.index)
    level_long = pd.Series(np.nan, index=df.index)

    for lv in entry_levels:
        lv_price = run_high_ltf - R_bull_ltf * lv
        tested = low <= lv_price
        # momentum confirmation: close crosses back above level (single shot)
        confirm = (close > lv_price) & (close.shift(1, fill_value=0) <= lv_price)
        hit = tested.shift(1, fill_value=False) & confirm & bull_ltf & R_bull_ltf.notna() & (R_bull_ltf > 0)
        # paranoias: price hasn't already broken the swing low (invalidation)
        hit = hit & (low >= leg_low_ltf - invalidation * R_bull_ltf)
        long_raw |= hit
        gp_long |= hit & (lv >= GOLDEN_POCKET_LOW)
        level_long = level_long.where(~hit).fillna(lv_price).where(long_raw)

    sl_long[long_raw] = (leg_low_ltf - invalidation * R_bull_ltf)[long_raw]
    tp1_long[long_raw] = _expand(close, R_bull_ltf, exit_cons, +1)[long_raw]
    tp2_long[long_raw] = _expand(close, R_bull_ltf, exit_classic, +1)[long_raw]

    # ---- SHORT (bear HTF pullback) ----
    short_raw = pd.Series(False, index=df.index)
    sl_short = pd.Series(np.nan, index=df.index)
    tp1_short = pd.Series(np.nan, index=df.index)
    tp2_short = pd.Series(np.nan, index=df.index)
    gp_short = pd.Series(False, index=df.index)

    for lv in entry_levels:
        lv_price = run_low_ltf + R_bear_ltf * lv
        tested = high >= lv_price
        confirm = (close < lv_price) & (close.shift(1, fill_value=np.inf) >= lv_price)
        hit = tested.shift(1, fill_value=False) & confirm & bear_ltf & R_bear_ltf.notna() & (R_bear_ltf > 0)
        hit = hit & (high <= leg_high_ltf + invalidation * R_bear_ltf)
        short_raw |= hit
        gp_short |= hit & (lv >= GOLDEN_POCKET_LOW)

    sl_short[short_raw] = (leg_high_ltf + invalidation * R_bear_ltf)[short_raw]
    tp1_short[short_raw] = _expand(close, R_bear_ltf, exit_cons, -1)[short_raw]
    tp2_short[short_raw] = _expand(close, R_bear_ltf, exit_classic, -1)[short_raw]

    # ---- Confluences ----
    confluences = pd.Series(0, index=df.index)

    # strong impulse (R vs ATR)
    rng_ref = R_bull_ltf.where(long_raw).fillna(R_bear_ltf.where(short_raw))
    strong = rng_ref > atr_ * atr_mult
    confluences += strong.astype(bool).fillna(False)

    # volume expansion
    vol_sma = volume.rolling(20, min_periods=5).mean().replace(0, np.nan)
    vol_exp = volume / vol_sma > vol_mult
    confluences += (vol_exp & (long_raw | short_raw))

    # golden pocket touch
    confluences += (gp_long | gp_short)

    # premium/discount vs HTF mid
    in_discount = (long_raw & close < mid) | (short_raw & close > mid)
    confluences += in_discount

    # ---- Gate ----
    long_entry = long_raw & (confluences >= min_confluence)
    short_entry = short_raw & (confluences >= min_confluence)

    # shift 1 bar (execution at next open)
    long_entry = long_entry.shift(1, fill_value=False).astype(bool)
    short_entry = short_entry.shift(1, fill_value=False).astype(bool)
    sl_out = pd.Series(np.nan, index=df.index)
    sl_out[long_entry] = sl_long.shift(1)[long_entry]
    sl_out[short_entry] = sl_short.shift(1)[short_entry]
    tp1_out = pd.Series(np.nan, index=df.index)
    tp2_out = pd.Series(np.nan, index=df.index)
    tp1_out[long_entry] = tp1_long.shift(1)[long_entry]
    tp1_out[short_entry] = tp1_short.shift(1)[short_entry]
    tp2_out[long_entry] = tp2_long.shift(1)[long_entry]
    tp2_out[short_entry] = tp2_short.shift(1)[short_entry]

    direction = pd.Series(0, index=df.index)
    extras = {
        "confluences": confluences,
        "tp1": tp1_out,
        "tp2": tp2_out,
        "weight_tp1": weight_tp1,
        "exit_cons": exit_cons,
        "exit_classic": exit_classic,
        "invalidation": invalidation,
        "golden_pocket": gp_long | gp_short,
        "swing_tf": swing_tf,
    }
    return _collect(long_entry, short_entry, sl_out, direction, extras,
                    name="fib_htf")


def compute(df: pd.DataFrame, strategy: str = "fib_retrace", **params) -> dict:
    if strategy in ("fib_htf",):
        return fib_htf(df, **params)
    if strategy in ("all", "default", "fib_retrace"):
        return fib_retrace(df, **params)
    raise ValueError(f"Unknown fib_retrace variant '{strategy}'")