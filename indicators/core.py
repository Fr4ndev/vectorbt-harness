"""
core.py — vectorized ICT indicator primitives.

Every function is column-vectorized (returns a full-length pandas Series /
boolean mask on the input index) so they can be dropped straight into
vectorbt signal generation and vbt.Indicator run() pipelines.

Conventions
-----------
- Booleans are oriented as Series with the input index.
- Naming of masks: bull/bear suffixes, e.g. `sweep_bull`, `sweep_bear`.
- These are the building blocks the strategy signal modules reuse.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ─────────────────────────────────────────────────────────────────────────
# Valeyre Z-Score (single-scale mean-reversion) — full column
# ─────────────────────────────────────────────────────────────────────────
def valeyre_zscore(close: pd.Series, period: int = 50, sqrt_n: int | None = None) -> pd.Series:
    """Return the full Z-score column.

    z = ((close - EMA)/EMA) / vol
    vol = std(log_ret, period) * sqrt(period)   [sqrt_n overrides the sqrt]
    Note: demon1 uses sqrt(period); demon2/quantum use sqrt(365). Pass
    sqrt_n to switch. Default None -> sqrt(period).
    """
    ema = close.ewm(span=period, adjust=False).mean()
    log_ret = np.log(close / close.shift(1))
    n = sqrt_n if sqrt_n is not None else period
    vol = log_ret.rolling(period).std() * np.sqrt(n)
    vol = vol.replace(0, np.nan).clip(lower=0.001)
    z = ((close - ema) / ema) / vol
    return z


def zscore_bias(z: pd.Series, up: float = 0.5, down: float = -0.5) -> pd.Series:
    """Map z-score column to bias: 1 = bullish, -1 = bearish, 0 = neutral."""
    return np.where(z > up, 1, np.where(z < down, -1, 0))


# ─────────────────────────────────────────────────────────────────────────
# ATR
# ─────────────────────────────────────────────────────────────────────────
def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14, method: str = "ewm") -> pd.Series:
    """True Range average. method: 'ewm' (EMA, demon2 style) or 'sma'."""
    pc = close.shift(1)
    tr = pd.concat(
        [high - low, (high - pc).abs(), (low - pc).abs()], axis=1
    ).max(axis=1)
    if method == "sma":
        return tr.rolling(period).mean()
    return tr.ewm(span=period, adjust=False).mean()


# ─────────────────────────────────────────────────────────────────────────
# Displacement (institutional expansion)
# ─────────────────────────────────────────────────────────────────────────
def displacement(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series,
                 factor: float = 0.8, period: int = 14) -> pd.Series:
    """body > avg_true_range * factor  => displacement.
    Returns direction mask: +1 bullish, -1 bearish, 0 none."""
    body = (close - open_).abs()
    avg_range = atr(high, low, close, period=period, method="sma")
    disp = body > avg_range * factor
    return np.where(disp & close.gt(open_), 1, np.where(disp & close.lt(open_), -1, 0))


# ─────────────────────────────────────────────────────────────────────────
# Liquidity Sweep (BSL/SSL) — vectorized
# ─────────────────────────────────────────────────────────────────────────
def liquidity_sweep(
    high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series,
    lookback: int = 15,
    vol_mult_required: float = 1.3,
    dev_max: float = 0.30,       # Rule 30%: deviation cap as fraction of prior range
    use_deviations: bool = True, # if False, ignore the 30% rule
) -> dict:
    """Detect BSL/SSL sweeps across the full series.

    BSL (bearish / buy-side liquidity swept):
        curr_high > old_high AND curr_close < old_high
    SSL (bullish / sell-side liquidity swept):
        curr_low  < old_low  AND curr_close > old_low

    Confirmation (per original): volume spike OR displacement OR rechazo
    (upper/lower wick > 50% of range). Rule-30% cancels the sweep when the
    penetration exceeds dev_max * prior_range.

    Returns dict with keys: sweep_bsl, sweep_ssl, sweep_dir, deviation_pct,
    rejection_quality, vol_mult.
    """
    open_ = close.shift(1)  # vectorized approx open when open column absent
    old_high = high.rolling(lookback, min_periods=lookback).max().shift(1)
    old_low = low.rolling(lookback, min_periods=lookback).min().shift(1)
    prev_range = (old_high - old_low).replace(0, np.nan)

    upper_wick = high - pd.concat([close, open_], axis=1).max(axis=1)
    lower_wick = pd.concat([close, open_], axis=1).min(axis=1) - low
    rng = (high - low).replace(0, np.nan)
    rq_bsl = upper_wick / rng
    rq_ssl = lower_wick / rng

    return _liquidity_sweep_impl(
        high, low, close, volume, old_high, old_low, prev_range,
        rq_bsl, rq_ssl, vol_mult_required, dev_max, use_deviations,
    )


def _liquidity_sweep_impl(
    high, low, close, volume, old_high, old_low, prev_range,
    rq_bsl, rq_ssl, vol_mult_required, dev_max, use_deviations,
) -> dict:
    vol_sma = volume.rolling(20, min_periods=5).mean().replace(0, np.nan)
    vol_mult = volume / vol_sma

    # raw triggers
    trig_bsl = (high > old_high) & (close < old_high)
    trig_ssl = (low < old_low) & (close > old_low)

    # confirmation: volume spike OR wick rejection > 50%
    strong_rej_bsl = rq_bsl > 0.5
    strong_rej_ssl = rq_ssl > 0.5
    confirm = (vol_mult >= vol_mult_required) | strong_rej_bsl | strong_rej_ssl

    sweep_bsl = trig_bsl & confirm
    sweep_ssl = trig_ssl & confirm

    if use_deviations:
        dev_bsl = (high - old_high) / prev_range
        dev_ssl = (old_low - low) / prev_range
        sweep_bsl = sweep_bsl & (dev_bsl <= dev_max)
        sweep_ssl = sweep_ssl & (dev_ssl <= dev_max)
        deviation_pct = pd.concat(
            [dev_bsl.where(sweep_bsl), dev_ssl.where(sweep_ssl)], axis=1
        ).sum(axis=1) * 100
    else:
        deviation_pct = pd.Series(np.nan, index=close.index)

    rejection_quality = pd.concat(
        [rq_bsl.where(sweep_bsl), rq_ssl.where(sweep_ssl)], axis=1
    ).sum(axis=1)

    sweep_dir = np.where(
        sweep_ssl, 1, np.where(sweep_bsl, -1, 0)
    )
    return {
        "sweep_bsl": sweep_bsl,
        "sweep_ssl": sweep_ssl,
        "sweep_dir": pd.Series(sweep_dir, index=close.index),
        "deviation_pct": deviation_pct,
        "rejection_quality": rejection_quality.fillna(0),
        "vol_mult": vol_mult.fillna(0),
    }


# ─────────────────────────────────────────────────────────────────────────
# Fair Value Gaps (3-candle) — with fill / mitigation check
# ─────────────────────────────────────────────────────────────────────────
def fvg(high: pd.Series, low: pd.Series, close: pd.Series, lookback: int = 30) -> dict:
    """Vectorized FVG positions.

    Bullish FVG  : candle[i].low > candle[i-2].high  => gap [high[i-2], low[i]]
    Bearish FVG  : candle[i].high < candle[i-2].low  => gap [high[i], low[i-2]]

    A mask is True on the *formation* candle i. The filled/mitigated signal
    marks candles where a subsequent close has traded back into the gap.
    """
    bull = (low > high.shift(2)).fillna(False)
    bear = (high < low.shift(2)).fillna(False)

    # mitigation: price closes back inside the gap after formation
    bull_gap_low = high.shift(2)      # bottom of bullish gap
    bull_gap_high = low               # top of bullish gap
    filled_bull = (close.shift(1) > bull_gap_low) & (close.shift(1) < bull_gap_high)

    bear_gap_low = high               # bottom of bearish gap
    bear_gap_high = low.shift(2)      # top of bearish gap
    filled_bear = (close.shift(1) > bear_gap_low) & (close.shift(1) < bear_gap_high)

    # keep only live (not yet filled) gaps within lookback
    active = pd.Series(False, index=close.index)
    active.fillna(False, inplace=True)
    return {
        "fvg_bull": bull,
        "fvg_bear": bear,
        "fvg_filled_bull": filled_bull,
        "fvg_filled_bear": filled_bear,
        "fvg_live_bull": bull & ~filled_bull,
        "fvg_live_bear": bear & ~filled_bear,
    }


def order_blocks(open_: pd.Series, close: pd.Series, fvg_bull: pd.Series,
                 fvg_bear: pd.Series) -> dict:
    """OB = candle immediately before an FVG impulse, opposite-bodied.
    bull OB (demand)  : prior candle bearish before a bullish FVG
    bear OB (supply)  : prior candle bullish before a bearish FVG"""
    ob_bull = fvg_bull.shift(1) & open_.shift(1).gt(close.shift(1))
    ob_bear = fvg_bear.shift(1) & open_.shift(1).lt(close.shift(1))
    return {"ob_bull": ob_bull.fillna(False), "ob_bear": ob_bear.fillna(False)}


# ─────────────────────────────────────────────────────────────────────────
# SMT Divergence (BTC vs ETH) — vectorized, 1h
# ─────────────────────────────────────────────────────────────────────────
def smt_divergence(btc_high, btc_low, eth_high, eth_low, window: int = 5) -> pd.Series:
    """+1 bullish SMT, -1 bearish SMT, 0 neutral.
    Bullish: BTC makes new low, ETH does NOT  -> divergence up.
    Bearish: BTC makes new high, ETH does NOT -> divergence down.
    (The diverging leg anticipates a reversal against BTC's move.)"""
    btc_new_high = btc_high > btc_high.rolling(window + 1).max().shift(1)
    btc_new_low = btc_low < btc_low.rolling(window + 1).min().shift(1)
    eth_new_high = eth_high > eth_high.rolling(window + 1).max().shift(1)
    eth_new_low = eth_low < eth_low.rolling(window + 1).min().shift(1)
    bull = btc_new_low & ~eth_new_low
    bear = btc_new_high & ~eth_new_high
    return np.where(bull, 1, np.where(bear, -1, 0))


def relative_strength_bias(btc_ret: pd.Series, eth_ret: pd.Series, threshold: float = 0.005) -> pd.Series:
    """+1 RISK-ON (ETH outruns BTC), -1 RISK-OFF, 0 neutral (return-based SMT)."""
    diff = eth_ret - btc_ret
    return np.where(diff > threshold, 1, np.where(diff < -threshold, -1, 0))


# ─────────────────────────────────────────────────────────────────────────
# Market Structure Shift (MS Shift) — 3-candle fractal swing
# ─────────────────────────────────────────────────────────────────────────
def swing_highs_lows(high: pd.Series, low: pd.Series) -> tuple:
    is_swing_high = (high > high.shift(1)) & (high > high.shift(-1))
    is_swing_low = (low < low.shift(1)) & (low < low.shift(-1))
    return is_swing_high, is_swing_low


def ms_shift(high: pd.Series, low: pd.Series, close: pd.Series, sweep_bull: pd.Series,
             sweep_bear: pd.Series) -> dict:
    """After an SSL sweep, a bullish MS shift breaks a recent swing high.
    After a BSL sweep, a bearish MS shift breaks a recent swing low."""
    sw_h, sw_l = swing_highs_lows(high, low)
    recent_swing_high = high.where(sw_h).rolling(5, min_periods=1).max().shift(1)
    recent_swing_low = low.where(sw_l).rolling(5, min_periods=1).min().shift(1)
    recent_sweep_bull = sweep_bull.rolling(10).sum().gt(0)
    recent_sweep_bear = sweep_bear.rolling(10).sum().gt(0)
    ms_bull = (close > recent_swing_high) & recent_sweep_bull
    ms_bear = (close < recent_swing_low) & recent_sweep_bear
    return {"ms_bull": ms_bull.fillna(False), "ms_bear": ms_bear.fillna(False)}


# ─────────────────────────────────────────────────────────────────────────
# ICT Killzones / Power of 3 (by UTC hour)
# ─────────────────────────────────────────────────────────────────────────
def session(ts: pd.DatetimeIndex) -> pd.Series:
    """Return PO3 phase per timestamp: ACCUMULATION/MANIPULATION/DISTRIBUTION/
    DISTRIBUTION_LATE/OFF-HOURS."""
    hour = ts.hour
    po3 = np.select(
        [
            (hour >= 0) & (hour < 6),
            (hour >= 7) & (hour < 10),
            (hour >= 12) & (hour < 15),
            (hour >= 15) & (hour < 17),
        ],
        ["ACCUMULATION", "MANIPULATION", "DISTRIBUTION", "DISTRIBUTION_LATE"],
        default="OFF-HOURS",
    )
    return pd.Series(po3, index=ts)


def is_killzone(session_s: pd.Series) -> pd.Series:
    """True during London (MANIPULATION) or NY AM (DISTRIBUTION)."""
    return session_s.isin(["MANIPULATION", "DISTRIBUTION"])


# ─────────────────────────────────────────────────────────────────────────
# EMA cross (for 4hsweep v16 death-cross variant)
# ─────────────────────────────────────────────────────────────────────────
def ema_cross(close: pd.Series, fast: int = 55, slow: int = 200) -> dict:
    ema_f = close.ewm(span=fast, adjust=False).mean()
    ema_s = close.ewm(span=slow, adjust=False).mean()
    golden = (ema_f > ema_s) & (ema_f.shift(1) <= ema_s.shift(1))
    death = (ema_f < ema_s) & (ema_f.shift(1) >= ema_s.shift(1))
    bias = np.where(ema_f > ema_s, 1, np.where(ema_f < ema_s, -1, 0))
    return {"ema_fast": ema_f, "ema_slow": ema_s, "golden": golden, "death": death,
            "bias": pd.Series(bias, index=close.index)}


# ─────────────────────────────────────────────────────────────────────────
# OTE fibonacci zones
# ─────────────────────────────────────────────────────────────────────────
def ote_zones(high: pd.Series, low: pd.Series, direction: int,
              f1: float = 0.618, f2: float = 0.786) -> dict:
    diff = (high - low).abs()
    if direction == 1:  # LONG: retrace down from high
        zone_hi = high - diff * 0.62
        zone_lo = high - diff * 0.79
    else:               # SHORT: retrace up from low
        zone_lo = low + diff * 0.62
        zone_hi = low + diff * 0.79
    return {"ote_low": zone_lo, "ote_high": zone_hi}


# ─────────────────────────────────────────────────────────────────────────
# Deviation % (continuation bias guard)
# ─────────────────────────────────────────────────────────────────────────
def deviation_pct(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """max(|prev_l - curr_l|, |prev_h - curr_h|) / (prev_h - prev_l) * 100."""
    prev_l = low.shift(1)
    prev_h = high.shift(1)
    prev_range = (prev_h - prev_l).replace(0, np.nan)
    dev = pd.concat(
        [(prev_l - low).abs(), (prev_h - high).abs()], axis=1
    ).max(axis=1)
    return dev / prev_range * 100
