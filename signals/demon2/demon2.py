"""
demon2.py — Demon v2 signals (10 ICT/SMC sub-strategies).

Ports the strategy family from ICTdemon/demon2/strategies.py into a
vectorized `compute()` interface compatible with the harness engine.

Each sub-strategy returns a dict with (at minimum) entries / short_entries /
sl / dir if it produces executable trades. Bias-only regimes return only a
direction series for inspection.

The strategies (id -> name):
    1.  continuation_bias    — Continuation Bias + Deviation rule (D + 4H ATR)
    2.  po3                 — Power of 3 (AMD) 2.0
    3.  power_flow          — Power Flow Sweeps hierarchy (M/W/D) [bias only]
    4.  weekly_bias         — Weekly Extension Bias (Tue/Wed gate)
    5.  abc                 — ABC Retrace / Wave 3 (short only)
    6.  mmxm                — Market Maker Model (breaker-block; bias only)
    7.  ote_tbr             — OTE 2.0 + TBR Macro
    8.  liquidity_trap      — Liquidity Trap / Breaker
    9.  ifvg                — Inversion FVG (iFVG)
    10. silver_bullet       — Silver Bullet + Judas Swing

All detection in the original code inspects iloc[-1] / iloc[-2] (live).
For backtesting we shift each condition down 1 row so a signal at bar t uses
bars <= t-1 as past (avoids lookahead).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from indicators import core as ic


# ---------------------------------------------------------------------------
# Helper: OTE + 1:1 extension levels (from get_fib_levels)
# ---------------------------------------------------------------------------
def _fib_levels(low: pd.Series, high: pd.Series, direction: int) -> dict:
    diff = (high - low).abs()
    if direction == 1:  # BULLISH (long)
        return {
            "ote_h": high - diff * 0.618,
            "ote_l": high - diff * 0.786,
            "sl": low,
            "tp1": high + diff * 1.0,
        }
    return {  # BEARISH (short)
        "ote_h": low + diff * 0.618,
        "ote_l": low + diff * 0.786,
        "sl": high,
        "tp1": low - diff * 1.0,
    }


def _confluence_matrix(confluences: pd.Series, forced: float | None = None) -> tuple:
    """risk_unit and prob_win from confluence count. Vectorized."""
    ru = pd.Series(0.0, index=confluences.index)
    pw = pd.Series(0.50, index=confluences.index)
    ru[confluences >= 5] = 0.015
    pw[confluences >= 5] = 0.75
    ru[confluences == 4] = 0.010
    pw[confluences == 4] = 0.70
    ru[confluences == 3] = 0.005
    pw[confluences == 3] = 0.60
    ru[confluences == 2] = 0.003
    pw[confluences == 2] = 0.55
    if forced is not None:
        ru[:] = forced
    return ru, pw


def _collect(entries, shorts, sl, direction, extra=None, name="demon2"):
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


# ---------------------------------------------------------------------------
# Strategy 1 — Continuation Bias + Deviation rule
# TF: Daily (detect) + 4H ATR (risk)
# ---------------------------------------------------------------------------
def continuation_bias(df, atr_df=None, dev_fire: float = 33.0,
                      atr_mult_sl: float = 0.5, atr_mult_tp: float = 1.5) -> dict:
    close = df["close"]
    high = df["high"]
    low = df["low"]

    prev_h = high.shift(1)
    prev_l = low.shift(1)
    prev_range = (prev_h - prev_l).replace(0, np.nan)
    dev = pd.concat([(prev_l - low).abs(), (prev_h - high).abs()], axis=1).max(axis=1)
    dev_pct = dev / prev_range * 100

    bearish = (close < prev_l) & (dev_pct < dev_fire)
    bullish = (close > prev_h) & (dev_pct < dev_fire)

    risk = ic.atr(atr_df["high"], atr_df["low"], atr_df["close"], period=14) \
        if atr_df is not None else (high - low) * 0.1

    sl = pd.Series(np.nan, index=df.index)
    sl[bullish] = close[bullish] - risk[bullish] * atr_mult_sl
    sl[bearish] = close[bearish] + risk[bearish] * atr_mult_sl

    conf = pd.Series(3, index=df.index)
    ru, pw = _confluence_matrix(conf)
    return _collect(bullish, bearish, sl, pd.Series(0, index=df.index),
                    {"confluences": conf, "risk_unit": ru, "prob_win": pw},
                    name="demon2_continuation_bias")


# ---------------------------------------------------------------------------
# Strategy 2 — PO3 Fractal (AMD anchored to 00:00 UTC Daily/Weekly Open)
# Fractal PO3, not restricted to daily bars: the accumulation consolidates
# around the session open, the Judas Swing sweeps the Asian liquidity during
# the London killzone, and distribution is confirmed by an MSS + FVG.
# Entry fires when price returns to the Daily Open after the MSS.
# ---------------------------------------------------------------------------
def po3_fractal(df, acc_range: float = 0.0030, judas_window: int = 10,
                ms_lookback: int = 5, fvg_lookback: int = 6,
                sl_atr: float = 0.2, daily_anchor: bool = True,
                weekly_anchor: bool = True, require_weekly: bool = False,
                killzones: bool = True) -> dict:
    open_ = df["open"]
    high = df["high"]
    low = df["low"]
    close = df["close"]
    idx = df.index
    hour = idx.hour

    d_open = open_.resample("D").first().reindex(idx, method="ffill")
    w_open = open_.resample("W-SUN").first().reindex(idx, method="ffill")
    if not daily_anchor:
        d_open = w_open

    # ---- Accumulation around the open (00:00-06:00 UTC = Asia) ----
    acc_mask = (hour >= 0) & (hour < 6)
    consolidated = acc_mask & (high <= d_open * (1 + acc_range)) & \
        (low >= d_open * (1 - acc_range))
    day = idx.normalize()
    acc_low = low.where(consolidated).groupby(day).transform("min")
    acc_high = high.where(consolidated).groupby(day).transform("max")
    tidy = (acc_high - acc_low) <= (acc_range * d_open)
    acc_low = acc_low.where(tidy)
    acc_high = acc_high.where(tidy)

    # ---- Judas Swing: London killzone wick sweeps Asian liquidity ----
    manip = (hour >= 7) & (hour < 10)
    judas_long = manip & low.lt(acc_low) & low.lt(d_open)
    judas_short = manip & high.gt(acc_high) & high.gt(d_open)
    had_judas_long = judas_long.rolling(judas_window, min_periods=1).max().gt(0)
    had_judas_short = judas_short.rolling(judas_window, min_periods=1).max().gt(0)

    # ---- MSS after the sweep (close breaks a recent swing) ----
    sw_h, sw_l = ic.swing_highs_lows(high, low)
    recent_h = high.where(sw_h).rolling(ms_lookback, min_periods=1).max().shift(1)
    recent_l = low.where(sw_l).rolling(ms_lookback, min_periods=1).min().shift(1)
    ms_bull = close.gt(recent_h) & had_judas_long
    ms_bear = close.lt(recent_l) & had_judas_short

    # ---- FVG on the entry TF confirming the reversal ----
    f = ic.fvg(high, low, close, lookback=30)
    fvg_bull = f["fvg_live_bull"].rolling(fvg_lookback, min_periods=1).max().gt(0)
    fvg_bear = f["fvg_live_bear"].rolling(fvg_lookback, min_periods=1).max().gt(0)

    # ---- Entry: price returns to the Daily Open after MSS + FVG ----
    ret_long = (close > d_open) & (close.shift(1) <= d_open.shift(1))
    ret_short = (close < d_open) & (close.shift(1) >= d_open.shift(1))
    entries = ret_long & ms_bull & fvg_bull
    shorts = ret_short & ms_bear & fvg_bear

    if weekly_anchor:
        if require_weekly:
            entries = entries & close.gt(w_open)
            shorts = shorts & close.lt(w_open)

    kz = pd.Series(True, index=df.index)
    if killzones:
        kz = ic.is_killzone(ic.session(idx))
        entries = entries & kz
        shorts = shorts & kz
    entries = entries.fillna(False)
    shorts = shorts.fillna(False)

    # ---- SL below the Judas sweep low / above the sweep high ----
    atr = ic.atr(high, low, close, period=14)
    sweep_low = low.where(judas_long).rolling(judas_window, min_periods=1).min()
    sweep_high = high.where(judas_short).rolling(judas_window, min_periods=1).max()
    sl = pd.Series(np.nan, index=df.index)
    sl[entries] = (sweep_low - atr * sl_atr)[entries]
    sl[shorts] = (sweep_high + atr * sl_atr)[shorts]

    conf = pd.Series(4, index=df.index)
    ru, pw = _confluence_matrix(conf)
    return _collect(entries, shorts, sl, pd.Series(0, index=df.index),
                    {"confluences": conf, "risk_unit": ru, "prob_win": pw,
                     "d_open": d_open, "w_open": w_open,
                     "acc_low": acc_low, "acc_high": acc_high,
                     "judas_long": judas_long, "judas_short": judas_short,
                     "ms_bull": ms_bull, "ms_bear": ms_bear,
                     "fvg_bull": fvg_bull, "fvg_bear": fvg_bear,
                     "ret_long": ret_long, "ret_short": ret_short},
                    name="demon2_po3_fractal")


def _resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Convert an OHLCV frame to a target rule (e.g. 'W' weekly, 'M' monthly)."""
    out = pd.DataFrame({
        "open": df["open"].resample(rule).first(),
        "high": df["high"].resample(rule).max(),
        "low": df["low"].resample(rule).min(),
        "close": df["close"].resample(rule).last(),
        "volume": df["volume"].resample(rule).sum(),
    }).dropna()
    return out


# ---------------------------------------------------------------------------
# Strategy 3 — Power Flow Sweeps hierarchy (M/W/D). Bias only.
# Priority M > W > D, represented as a direction grade 1..-1 via np.select.
# NOTE: refuted as an edge by the profit map — the +107.88% was a stopless
# (passive-exposure) artifact; with a real ATR stop it scores -46.99. Kept in
# the codebase for reference, excluded from run_profit_map.RUNS.
# ---------------------------------------------------------------------------
def power_flow(df: pd.DataFrame, df_m: pd.DataFrame | None = None,
               df_w: pd.DataFrame | None = None,
               df_d: pd.DataFrame | None = None,
               atr_sl_mult: float = 1.5) -> dict:
    df_d = df_d if df_d is not None else _resample(df, "D")
    df_w = df_w if df_w is not None else _resample(df, "W")
    df_m = df_m if df_m is not None else _resample(df, "M")

    def sweep_pair(df):
        h = df["high"]; l = df["low"]; c = df["close"]
        prev_h = h.shift(1); prev_l = l.shift(1)
        bear = (h > prev_h) & (c < prev_h)
        bull = (l < prev_l) & (c > prev_l)
        return pd.Series(np.where(bull, 1, np.where(bear, -1, 0)), index=df.index)

    m = sweep_pair(df_m)
    w = sweep_pair(df_w)
    d = sweep_pair(df_d)
    # merge on the DAILY timeline (bias per closed bar)
    idx_d = d.index
    m = m.reindex(idx_d).ffill().fillna(0)
    w = w.reindex(idx_d).ffill().fillna(0)
    dir_d = pd.Series(
        np.select([(m != 0), (w != 0), (d != 0)], [m, w, d], default=0),
        index=idx_d,
    )
    conf = pd.Series(0, index=idx_d)
    conf[m != 0] = 5
    conf[(m == 0) & (w != 0)] = 4
    conf[(m == 0) & (w == 0) & (d != 0)] = 3

    # back onto the operative (entry) frame index: the bias is active on every
    # bar of the following day(s)
    direction = dir_d.reindex(df.index, method="ffill").fillna(0).astype(int)
    entries = (direction == 1)
    shorts = (direction == -1)
    # explicit ATR stop on the operative frame (no more stopless positions)
    atr_ = ic.atr(df["high"], df["low"], df["close"], period=14)
    sl = pd.Series(np.nan, index=df.index)
    sl[entries] = df["close"][entries] - atr_[entries] * atr_sl_mult
    sl[shorts] = df["close"][shorts] + atr_[shorts] * atr_sl_mult
    return _collect(entries, shorts, sl, direction, {"confluences": conf},
                    name="demon2_power_flow")


# ---------------------------------------------------------------------------
# Strategy 4 — Weekly Extension Bias (Tue/Wed gate, bullish only)
# ---------------------------------------------------------------------------
def weekly_bias(df: pd.DataFrame, min_rr: float = 1.0,
                ext_buffer: float = 0.005, is_daily: bool | None = None) -> dict:
    if "D" not in str(getattr(df.index, "freq", "")) and is_daily is None:
        # input is finer than daily -> resample to daily for the weekly-bias view
        df_d = _resample(df, "D")
    else:
        df_d = df
    close = df_d["close"]
    high = df_d["high"]
    low = df_d["low"]

    prev_w_low = low.rolling(5).min().shift(5)
    prev_w_high = high.rolling(5).max().shift(5)

    # gate: Tuesday (1) / Wednesday (2) UTC
    gate = df_d.index.dayofweek.isin([1, 2])
    min5_low = low.rolling(5).min()
    is_extension_off = min5_low > prev_w_low * (1 + ext_buffer)

    bullish = gate & is_extension_off & prev_w_low.notna()

    entry = close
    rr = (prev_w_high * 0.999 - entry) / (entry - prev_w_low * 0.998).replace(0, np.nan)
    valid = (entry > prev_w_low * 0.998) & (rr >= min_rr)
    bullish = bullish & valid

    sl = pd.Series(np.nan, index=df_d.index)
    sl[bullish] = prev_w_low[bullish] * 0.998

    # reindex the bias back onto the operative (entry) frame index
    bullish = bullish.reindex(df.index, method="ffill").fillna(False)
    sl = sl.reindex(df.index, method="ffill")
    conf = pd.Series(3, index=df.index)
    ru, pw = _confluence_matrix(conf, forced=0.005)
    return _collect(bullish, pd.Series(False, index=df.index), sl,
                    pd.Series(0, index=df.index),
                    {"confluences": conf, "risk_unit": ru, "prob_win": pw},
                    name="demon2_weekly_bias")


# ---------------------------------------------------------------------------
# Strategy 5 — ABC Retrace / Wave 3 (short only, 4H)
# ---------------------------------------------------------------------------
def abc(df, atr_mult_w3: float = 2.0, rr: float = 2.0) -> dict:
    close = df["close"]
    high = df["high"]
    atr_ = ic.atr(df["high"], df["low"], close, period=14)
    # Wave A down, B retrace up, C continuation (2 closes down)
    c_last = (close < close.shift(1))
    c_prev = (close.shift(1) < close.shift(2))
    b_up = close.shift(2) > close.shift(3)
    a_dn = close.shift(3) < close.shift(4)
    bearish = a_dn & b_up & c_prev & c_last

    entry = close
    sl = high.shift(3)
    risk = (sl - entry).replace(0, np.nan)
    tp = entry - risk * rr
    risk_atr = risk > atr_.shift(1) * atr_mult_w3
    conf = pd.Series(3, index=df.index)
    conf[risk_atr] = 4

    sl = pd.Series(np.nan, index=df.index)
    sl[bearish] = high.shift(3)[bearish]
    ru, pw = _confluence_matrix(conf)
    return _collect(pd.Series(False, index=df.index), bearish, sl,
                    pd.Series(0, index=df.index),
                    {"confluences": conf, "risk_unit": ru, "prob_win": pw},
                    name="demon2_abc")


# ---------------------------------------------------------------------------
# Strategy 6 — MMXM Market Maker Model. Needs a real breaker-block detector.
# The shipped code hardcodes breaker columns to 0 (never fires). We implement
# a functional breaker detector so the strategy can actually produce signals,
# gated behind breaker_enabled=True (default False -> never fires, faithful).
# ---------------------------------------------------------------------------
def _breaker_block(high, low, close, lookback: int = 10) -> dict:
    """Real breaker-block detection (intent from source docs):
       bearish = last significant LL preceding a structure-breaking HH;
       bullish = last significant HH preceding a structure-breaking LL."""
    sw_h, sw_l = ic.swing_highs_lows(high, low)
    swing_h = close.where(sw_h).rolling(lookback, min_periods=1).max().shift(1)
    swing_l = close.where(sw_l).rolling(lookback, min_periods=1).min().shift(1)
    hi = close.rolling(lookback * 2).max().shift(lookback)
    lo = close.rolling(lookback * 2).min().shift(lookback)
    bb_bull = (close > hi) & swing_l.notna()          # broke HH above a recent LL
    bb_bear = (close < lo) & swing_h.notna()          # broke LL below a recent HH
    return {"breaker_bull": bb_bull.fillna(False), "breaker_bear": bb_bear.fillna(False),
            "swing_h": swing_h, "swing_l": swing_l}


def mmxm(df, enable_breaker: bool = False, atr_sl_mult: float = 1.5) -> dict:
    fvg_ = ic.fvg(df["high"], df["low"], df["close"])
    if enable_breaker:
        bb = _breaker_block(df["high"], df["low"], df["close"])
        bullish = bb["breaker_bull"] & fvg_["fvg_live_bear"]
        bearish = bb["breaker_bear"] & fvg_["fvg_live_bull"]
    else:
        bullish = pd.Series(False, index=df.index)
        bearish = pd.Series(False, index=df.index)
    atr = ic.atr(df["high"], df["low"], df["close"], period=14)
    sl = pd.Series(np.nan, index=df.index)
    sl[bullish] = df["close"][bullish] - atr[bullish] * atr_sl_mult
    sl[bearish] = df["close"][bearish] + atr[bearish] * atr_sl_mult
    conf = pd.Series(4, index=df.index)
    ru, pw = _confluence_matrix(conf)
    dir_sig = pd.Series(0, index=df.index)
    return _collect(bullish, bearish, sl, dir_sig,
                    {"confluences": conf, "risk_unit": ru, "prob_win": pw,
                     "breaker_bull": bullish, "breaker_bear": bearish},
                    name="demon2_mmxm")


# ---------------------------------------------------------------------------
# Strategy 7 — OTE 2.0 + TBR Macro (1H)
# ---------------------------------------------------------------------------
def ote_tbr(df, displ_atr: float = 2.0, tbr_h_start: int = 9,
            tbr_h_end: int = 13, ote_lookback: int = 10) -> dict:
    open_ = df["open"]
    high = df["high"]
    low = df["low"]
    close = df["close"]
    atr_ = ic.atr(high, low, close, period=14)

    is_displacement = (close - open_).abs() > atr_ * displ_atr

    # impulse legs: BULLISH uses min of prior 10 lows (excl last) + last high
    window_h = high.shift(1).rolling(ote_lookback - 1).max()
    window_l = low.shift(1).rolling(ote_lookback - 1).min()

    fib_bull = _fib_levels(window_l, high, 1)
    fib_bear = _fib_levels(low, window_h, -1)

    in_ote_long = close.between(fib_bull["ote_l"], fib_bull["ote_h"])
    in_ote_short = close.between(fib_bear["ote_l"], fib_bear["ote_h"])

    # displacement defines the impulse direction (recent displaced bar);
    # a long OTE setup wants a prior bullish impulse
    bullish = in_ote_long & is_displacement & (close > open_)
    bearish = in_ote_short & is_displacement & (close < open_)

    # TBR window confluence -> conf 4
    hour = df.index.hour
    tbr = (hour >= tbr_h_start) & (hour <= tbr_h_end)
    conf = pd.Series(3, index=df.index)
    conf[tbr] = 4

    sl = pd.Series(np.nan, index=df.index)
    sl[bullish] = fib_bull["sl"][bullish]
    sl[bearish] = fib_bear["sl"][bearish]
    ru, pw = _confluence_matrix(conf)
    return _collect(bullish, bearish, sl, pd.Series(0, index=df.index),
                    {"confluences": conf, "risk_unit": ru, "prob_win": pw},
                    name="demon2_ote_tbr")


# ---------------------------------------------------------------------------
# Strategy 8 — Liquidity Trap / Breaker (1H)
# ---------------------------------------------------------------------------
def liquidity_trap(df, atr_mult_sl: float = 0.5, atr_mult_tp: float = 1.5) -> dict:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    atr_ = ic.atr(high, low, close, period=14)

    prev_h = high.shift(1)
    prev_l = low.shift(1)
    bearish = (high > prev_h) & (close < prev_h)
    bullish = (low < prev_l) & (close > prev_l)

    sl = pd.Series(np.nan, index=df.index)
    sl[bullish] = close[bullish] - atr_[bullish] * atr_mult_sl
    sl[bearish] = close[bearish] + atr_[bearish] * atr_mult_sl

    conf = pd.Series(4, index=df.index)
    ru, pw = _confluence_matrix(conf)
    return _collect(bullish, bearish, sl, pd.Series(0, index=df.index),
                    {"confluences": conf, "risk_unit": ru, "prob_win": pw},
                    name="demon2_liquidity_trap")


# ---------------------------------------------------------------------------
# Strategy 9 — Inversion FVG (iFVG), 4H, RR 1:3
# ---------------------------------------------------------------------------
def ifvg(df, rr: float = 3.0, lookback: int = 3) -> dict:
    high = df["high"]
    low = df["low"]
    close = df["close"]

    # FVG references indexed on middle candle (offset approach)
    bull_gap_bottom = high.shift(1)      # bottom of bullish gap = prior high
    bull_gap_top = low.shift(-1)         # top of bullish gap
    bear_gap_top = low.shift(1)
    bear_gap_bottom = high.shift(-1)

    bearish = pd.Series(False, index=df.index)
    bullish = pd.Series(False, index=df.index)
    # Simplified per-bar inversion: a bearish/bullish FVG reference formed k bars
    # ago gets inverted when the current close breaches it. Most-recent FVG
    # (offset 2) takes precedence over more distant (3, 4).
    known_bear = bear_gap_top.notna() & bear_gap_bottom.notna()
    known_bull = bull_gap_bottom.notna() & bull_gap_top.notna()
    for k in range(2, 2 + lookback):
        broken_bear = (close < bear_gap_bottom.shift(k)) & known_bear.shift(k)
        broken_bull = (close > bull_gap_top.shift(k)) & known_bull.shift(k)
        bearish = bearish | broken_bear
        bullish = bullish | broken_bull
    bearish.fillna(False, inplace=True)
    bullish.fillna(False, inplace=True)

    sl = pd.Series(np.nan, index=df.index)
    # SL = top of the broken bearish gap (supply above entry) / bottom of the
    # broken bullish gap (demand below entry), using the nearest reference.
    sl[bullish] = bull_gap_bottom.shift(2)[bullish]
    sl[bearish] = bear_gap_top.shift(2)[bearish]

    conf = pd.Series(3, index=df.index)
    ru, pw = _confluence_matrix(conf)
    return _collect(bullish, bearish, sl, pd.Series(0, index=df.index),
                    {"confluences": conf, "risk_unit": ru, "prob_win": pw},
                    name="demon2_ifvg")


# ---------------------------------------------------------------------------
# Strategy 10 — Silver Bullet + Judas Swing (3M, RR 1:2)
# ---------------------------------------------------------------------------
def silver_bullet(df, atr_mult_sl: float = 1.5, atr_mult_tp: float = 3.0,
                  recent_window: int = 4, sessions=None) -> dict:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    atr_ = ic.atr(high, low, close, period=14)

    prev_high = high.shift(1).rolling(recent_window).max()
    prev_low = low.shift(1).rolling(recent_window).min()

    bullish = (low < prev_low) & (close > prev_low)
    bearish = (high > prev_high) & (close < prev_high)

    sl = pd.Series(np.nan, index=df.index)
    sl[bullish] = close[bullish] - atr_[bullish] * atr_mult_sl
    sl[bearish] = close[bearish] + atr_[bearish] * atr_mult_sl

    conf = pd.Series(5, index=df.index)
    ru, pw = _confluence_matrix(conf)
    return _collect(bullish, bearish, sl, pd.Series(0, index=df.index),
                    {"confluences": conf, "risk_unit": ru, "prob_win": pw},
                    name="demon2_silver_bullet")


# ---------------------------------------------------------------------------
# Compute dispatcher
# ---------------------------------------------------------------------------
def compute(df: pd.DataFrame, strategy: str = "all", **params) -> dict:
    """Dispatch to the requested demon2 sub-strategy.

    Args:
        df: entry-timeframe OHLCV (some strategies need HTF frames passed via
            params, e.g. power_flow needs df_m/df_w/df_d; weekly_bias needs
            df_d).
        strategy: name of one sub-strategy, or 'all' (returns nested dict).
    """
    registry = {
        "continuation_bias": continuation_bias,
        "po3_fractal": po3_fractal,
        "power_flow": power_flow,  # refuted (stopless artifact), kept for reference
        "weekly_bias": weekly_bias,
        "abc": abc,
        "mmxm": mmxm,
        "ote_tbr": ote_tbr,
        "liquidity_trap": liquidity_trap,
        "ifvg": ifvg,
        "silver_bullet": silver_bullet,
    }
    if strategy == "all":
        out = {}
        for k, fn in registry.items():
            try:
                out[k] = fn(df, **params.get(k, {}))
            except Exception as e:  # isolated failures shouldn't block others
                out[k] = {"error": f"{type(e).__name__}: {e}", "name": k}
        return out
    if strategy not in registry:
        raise ValueError(f"Unknown demon2 strategy '{strategy}'")
    return registry[strategy](df, **params)
