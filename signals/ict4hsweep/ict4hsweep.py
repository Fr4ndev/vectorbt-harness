"""
ict4hsweep.py — ICT 4H Sweep tier family (v10 -> v16).

Ports the 4hsweep/ict_signalbot_* family. The production bot scans a tier
hierarchy (1M -> 1D -> 4H -> 1H) for a two-candle liquidity sweep where the
current candle wicks past a prior candle's level and closes back inside,
gated by:
    C1 (deviation): penetration D <= H * DEV_LIMIT  (else breakout, rejected)
    C2 (timing):    sweep happened within TIMING_LIMIT of the candle's span

Then an OTE-fibonacci SL/TP and a confluence score decide whether to fire.

Vectorized single-frame implementation: compute() operates on ONE timeframe
(the sweep/entry TF). The tier is supplied as metadata (base_score) via the
`tier` param rather than scanning multiple frames internally — multi-TF
alignment is left to the runner, which can call compute() per tier frame.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from indicators import core as ic


# ---------------------------------------------------------------------------
# Tier config (v16 alpha) + death-cross EMA variant
# ---------------------------------------------------------------------------
TIERS_V16 = {
    "1M": {"base_score": 4.0},
    "1d": {"base_score": 3.0},
    "4h": {"base_score": 2.0},
    "1h": {"base_score": 1.0},
}

TIERS_DC = {
    "1M": {"base_score": 4.0},
    "1W": {"base_score": 3.5},
    "1D": {"base_score": 3.0},
    "4H": {"base_score": 2.0},
    "1H": {"base_score": 1.0},
}


def _sweep2(high, low, close, dev_limit):
    """Two-candle sweep detection with C1 deviation gate.

    BULLISH (SSL): current.low < prior.low AND current.close > prior.low
    BEARISH (BSL): current.high > prior.high AND current.close < prior.high

    C1: penetration D <= (prior candle range) * dev_limit
    Returns (sweep_dir, prior_high, prior_low, prior_high_2, prior_low_2, dev_ok)
    """
    ph = high.shift(1)
    pl = low.shift(1)
    H = (ph - pl).replace(0, np.nan)

    bull_raw = (low < pl) & (close > pl)
    bear_raw = (high > ph) & (close < ph)

    D_bull = (pl - low)
    D_bear = (high - ph)
    c1_bull = (D_bull > 0) & (D_bull <= H * dev_limit)
    c1_bear = (D_bear > 0) & (D_bear <= H * dev_limit)

    bull = bull_raw & c1_bull.fillna(False)
    bear = bear_raw & c1_bear.fillna(False)
    sweep_dir = pd.Series(np.where(bull, 1, np.where(bear, -1, 0)), index=close.index)

    return {
        "sweep_dir": sweep_dir,
        "prior_high": ph,
        "prior_low": pl,
        "prior_high_2": high.shift(2),
        "prior_low_2": low.shift(2),
        "bull": bull,
        "bear": bear,
        "H": H,
    }


def compute(df: pd.DataFrame, version: str = "v16",
            tier: str = "4h",
            dev_limit: float = 0.45,
            min_rr: float = 1.4,
            min_score: float = 1.5,
            sl_atr_mult: float = 0.5,
            fib_tp1: float = 0.66,
            fib_tp2: float = 0.705,
            fib_tp3: float = 0.79,
            atr_period: int = 14,
            use_death_cross: bool = False,
            ema_fast: int = 55,
            ema_slow: int = 200,
            require_mss: bool = True,
            **_) -> dict:
    """Compute 4H-sweep signals on a single OHLCV frame.

    Returns entries / short_entries / sl / dir plus breakdown (score, sweep_dir,
    tp1/2/3, tier base score).
    """
    high = df["high"]
    low = df["low"]
    close = df["close"]
    open_ = df["open"]
    idx = df.index

    sweep = _sweep2(high, low, close, dev_limit)
    sweep_dir = sweep["sweep_dir"]

    # temporal gate is a live-time concept; in backtest we emulate with the
    # position of the sweep in the bar being irrelevant (always passes) unless
    # a real C2 approximation is desired. We keep it as a pass-through.

    # ---- ATR on this frame for SL buffer (entry tf ideally 15m; we use frame) ----
    atr_ = ic.atr(high, low, close, period=atr_period)

    # wick quality & impulse body (score bonuses)
    candle_range = (high - low).replace(0, np.nan)
    bull_wick = (open_ - low)  # lower wick on bullish sweep
    bear_wick = (high - open_)
    body = (close - open_).abs()
    wick_quality = pd.concat([bull_wick, bear_wick], axis=1).max(axis=1) / candle_range
    impulse_body = body / candle_range
    wick_quality = wick_quality.fillna(0)
    impulse_body = impulse_body.fillna(0)

    # ---- SL / TP (OTE fibre) from swept level ----
    swept_low = low.where((sweep_dir == 1), np.nan)
    swept_high = high.where((sweep_dir == -1), np.nan)
    H = sweep["H"]

    sl = pd.Series(np.nan, index=idx)
    tp1 = pd.Series(np.nan, index=idx)
    tp2 = pd.Series(np.nan, index=idx)
    tp3 = pd.Series(np.nan, index=idx)

    bull = sweep_dir == 1
    bear = sweep_dir == -1
    if use_death_cross:
        # 0.2% SL variant
        sl[bull] = low[bull] * (1 - 0.002)
        sl[bear] = high[bear] * (1 + 0.002)
        # OTE from opposite end of range
        range_b = high - low
        tp1[bull] = low[bull] + range_b[bull] * 0.66
        tp2[bull] = low[bull] + range_b[bull] * 0.705
        tp3[bull] = low[bull] + range_b[bull] * 0.79
        tp1[bear] = high[bear] - range_b[bear] * 0.66
        tp2[bear] = high[bear] - range_b[bear] * 0.705
        tp3[bear] = high[bear] - range_b[bear] * 0.79
    else:
        sl[bull] = swept_low[bull] - atr_[bull] * sl_atr_mult
        sl[bear] = swept_high[bear] + atr_[bear] * sl_atr_mult
        tp1[bull] = swept_low[bull] + H[bull] * fib_tp1
        tp2[bull] = swept_low[bull] + H[bull] * fib_tp2
        tp3[bull] = swept_low[bull] + H[bull] * fib_tp3
        tp1[bear] = swept_high[bear] - H[bear] * fib_tp1
        tp2[bear] = swept_high[bear] - H[bear] * fib_tp2
        tp3[bear] = swept_high[bear] - H[bear] * fib_tp3

    # ---- RR gate (on TP1) ----
    risk = (close - sl).abs().replace(0, np.nan)
    reward = (tp1 - close).abs()
    rr = reward / risk
    rr_ok = rr >= min_rr
    rr_ok = rr_ok.fillna(False)

    # ---- killzone bonus ----
    sess = ic.session(idx)
    kz_bonus = pd.Series(0.0, index=idx)
    kz_bonus[sess.isin(["MANIPULATION", "DISTRIBUTION"])] = 0.5

    # ---- MSS (requires prior_high_2 break) ----
    if require_mss:
        mss_bull = close > sweep["prior_high_2"]
        mss_bear = close < sweep["prior_low_2"]
        mss = pd.Series(np.where(mss_bull, 1, np.where(mss_bear, -1, 0)), index=idx)
    else:
        mss = sweep_dir * 1

    # ---- score ----
    tier_base = TIERS_DC.get(tier, TIERS_V16.get(tier, {"base_score": 1.0}))["base_score"] \
        if use_death_cross else TIERS_V16.get(tier, {"base_score": 1.0})["base_score"]

    score = pd.Series(0.0, index=idx)
    active = sweep_dir != 0
    score += tier_base
    score += (wick_quality > 0.60) * 0.5
    score += (impulse_body > 0.45) * 0.5
    score += ((mss == sweep_dir) & active) * 1.0      # MSS
    score += rr_ok * 1.0                              # RR gate
    score += kz_bonus                                 # killzone
    score = score.where(active, 0.0)

    signal = active & rr_ok & (score >= min_score)
    entries = signal & bull
    short_entries = signal & bear

    direction = pd.Series(0, index=idx)
    direction[entries] = 1
    direction[short_entries] = -1

    return {
        "entries": entries,
        "short_entries": short_entries,
        "sl": sl,
        "dir": direction.astype(int),
        "score": score,
        "sweep_dir": sweep_dir,
        "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "rr": rr,
        "tier": tier,
        "name": f"ict4hsweep_{version}",
    }
