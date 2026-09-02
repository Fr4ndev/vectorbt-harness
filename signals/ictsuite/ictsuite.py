"""
ictsuite.py — ICT Agentic Suite signals (4 strategy types).

Ports ict-agentic-suite/extracted_strategies/* into vectorized compute()
functions:

    scalp_sweep      — HF liquidity sweep: z-extreme 4H bias + 1H single-candle
                       sweep confirmation + OTE ladder (0.62/0.705/0.79), RR 1:2
    intraday_quantum — SMT + displacement + MSS scored confluence (>=2.5)
    macro_swing      — weekly-z extreme + daily MSB + 4H sweep, RR 1:5
    sfp              — swing failure pattern (rejection > 50%), long/short
    sfp_institutional — absorption SFP: sweep depth 0.15-0.50%, strict reclaim
                        <=2 bars, London/NY killzone gate

Each returns the standard dict (entries / short_entries / sl / dir + extras).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from indicators import core as ic


def _ote_ladder(low, high, direction):
    diff = (high - low).abs()
    if direction == 1:  # LONG
        return (high - diff * 0.62, high - diff * 0.705, high - diff * 0.79)
    return (low + diff * 0.62, low + diff * 0.705, low + diff * 0.79)


# ---------------------------------------------------------------------------
# 1. Scalp Sweep (HF liquidity sweep; 4H z bias + 1H sweep, OTE entry)
# ---------------------------------------------------------------------------
def scalp_sweep(df, z_period: int = 50, z_threshold: float = 2.0,
                ote_lookback: int = 10, rr: float = 2.0) -> dict:
    close = df["close"]
    high = df["high"]
    low = df["low"]

    z = ic.valeyre_zscore(close, period=z_period)
    bias_long = z <= -z_threshold
    bias_short = z >= z_threshold

    # single-candle sweep (immediately preceding candle)
    ph = high.shift(1)
    pl = low.shift(1)
    sweep_bull = (low < pl) & (close > pl)
    sweep_bear = (high > ph) & (close < ph)

    entries = sweep_bull & bias_long
    shorts = sweep_bear & bias_short

    # OTE ladder on the sweep candle
    ote_buy = _ote_ladder(low, high, 1)
    ote_sell = _ote_ladder(low, high, -1)
    in_ote_buy = close.between(ote_buy[2], ote_buy[0])
    in_ote_sell = close.between(ote_sell[2], ote_sell[0])
    entries = entries & in_ote_buy
    shorts = shorts & in_ote_sell

    sl = pd.Series(np.nan, index=df.index)
    sl[entries] = low[entries]
    sl[shorts] = high[shorts]

    direction = pd.Series(0, index=df.index)
    direction[entries] = 1
    direction[shorts] = -1
    return {
        "entries": entries, "short_entries": shorts, "sl": sl,
        "dir": direction.astype(int), "z": z,
        "ote_buy_62": ote_buy[0], "ote_buy_705": ote_buy[1], "ote_buy_79": ote_buy[2],
        "ote_sell_62": ote_sell[0], "ote_sell_705": ote_sell[1], "ote_sell_79": ote_sell[2],
        "name": "ictsuite_scalp_sweep",
    }


# ---------------------------------------------------------------------------
# 2. Intraday Quantum (SMT + displacement + MSS, score >= 2.5)
# ---------------------------------------------------------------------------
def intraday_quantum(df, btc_df=None, eth_df=None,
                     smt_lookback: int = 5, ms_shift_scan: int = 11,
                     actionable: float = 2.5) -> dict:
    close = df["close"]
    high = df["high"]
    low = df["low"]
    open_ = df["open"]

    score = pd.Series(0.0, index=df.index)
    smt = pd.Series(0, index=df.index)

    if btc_df is not None and eth_df is not None:
        smt = pd.Series(ic.smt_divergence(btc_df["high"], btc_df["low"],
                                          eth_df["high"], eth_df["low"],
                                          window=smt_lookback), index=df.index)
    score += (smt != 0) * 1.5

    disp = pd.Series(ic.displacement(open_, high, low, close, factor=0.8, period=14),
                     index=df.index)
    score += (disp != 0) * 1.0

    # MSS vs a recent swing, using smt as sweep-direction proxy
    sw_h, sw_l = ic.swing_highs_lows(high, low)
    recent_h = high.where(sw_h).rolling(max(ms_shift_scan // 2, 3), min_periods=1).max().shift(1)
    recent_l = low.where(sw_l).rolling(max(ms_shift_scan // 2, 3), min_periods=1).min().shift(1)
    ms_bull = (close > recent_h) & (smt == 1)
    ms_bear = (close < recent_l) & (smt == -1)
    score += ((ms_bull | ms_bear)) * 1.0

    signal = score >= actionable
    entries = signal & smt.eq(1)
    shorts = signal & smt.eq(-1)

    sl = pd.Series(np.nan, index=df.index)
    sl[entries] = recent_l[entries]
    sl[shorts] = recent_h[shorts]

    direction = pd.Series(0, index=df.index)
    direction[entries] = 1
    direction[shorts] = -1
    return {
        "entries": entries, "short_entries": shorts, "sl": sl,
        "dir": direction.astype(int), "score": score, "smt": smt,
        "displacement": disp, "ms_bull": ms_bull, "ms_bear": ms_bear,
        "name": "ictsuite_intraday_quantum",
    }


# ---------------------------------------------------------------------------
# 3. Macro Swing (weekly z + daily MSB + 4H sweep, depth-bias confluence)
# ---------------------------------------------------------------------------
def macro_swing(df, z_period: int = 50, z_threshold: float = 1.5,
                require_depth_bias: bool = False, rr: float = 5.0,
                depth_bias=None) -> dict:
    close = df["close"]
    high = df["high"]
    low = df["low"]

    z = ic.valeyre_zscore(close, period=z_period)
    # daily MSB
    d_prev_h = high.shift(1)
    d_prev_l = low.shift(1)
    bull_msb = (z > z_threshold) & (close > d_prev_h)
    bear_msb = (z < -z_threshold) & (close < d_prev_l)

    # 4H single-candle sweep
    ph = high.shift(1)
    pl = low.shift(1)
    sweep_bull = (low < pl) & (close > pl)
    sweep_bear = (high > ph) & (close < ph)

    if depth_bias is None:
        # if not required, any signal works; else require the matching OB
        if require_depth_bias:
            # depth_bias is an external context signal; without it we use the
            # z-score sign as a weak proxy.
            depth = pd.Series(np.where(z > 0, "BULLISH_DEPTH", "BEARISH_DEPTH"), index=df.index)
            bull_ok = depth == "BULLISH_DEPTH"
            bear_ok = depth == "BEARISH_DEPTH"
        else:
            bull_ok = pd.Series(True, index=df.index)
            bear_ok = pd.Series(True, index=df.index)
    else:
        bull_ok = depth_bias == "BULLISH_DEPTH"
        bear_ok = depth_bias == "BEARISH_DEPTH"

    entries = sweep_bull & bull_msb & bull_ok
    shorts = sweep_bear & bear_msb & bear_ok

    sl = pd.Series(np.nan, index=df.index)
    sl[entries] = low[entries]
    sl[shorts] = high[shorts]

    direction = pd.Series(0, index=df.index)
    direction[entries] = 1
    direction[shorts] = -1
    return {
        "entries": entries, "short_entries": shorts, "sl": sl,
        "dir": direction.astype(int), "z": z,
        "sweep_bull": sweep_bull, "sweep_bear": sweep_bear,
        "bull_msb": bull_msb, "bear_msb": bear_msb,
        "name": "ictsuite_macro_swing",
    }


# ---------------------------------------------------------------------------
# 4. Swing Failure Pattern (rejection > 50% of candle range)
# ---------------------------------------------------------------------------
def sfp(df, rejection_min: float = 50.0) -> dict:
    close = df["close"]
    high = df["high"]
    low = df["low"]
    open_ = df["open"]

    ph = high.shift(1)
    pl = low.shift(1)
    pc = close.shift(1)
    candle_range = (high - low).replace(0, np.nan)

    # SFP_SHORT (bull trap): wick above prior high, close back below, red candle
    sfp_short = (high > ph) & (close < open_) & (close < pc) & \
                ((high - close) / candle_range * 100 > rejection_min)
    # SFP_LONG (bear trap): wick below prior low, close back above, green candle
    sfp_long = (low < pl) & (close > open_) & (close > pc) & \
               ((close - low) / candle_range * 100 > rejection_min)

    direction = pd.Series(0, index=df.index)
    direction[sfp_long] = 1
    direction[sfp_short] = -1

    sl = pd.Series(np.nan, index=df.index)
    sl[sfp_long] = low[sfp_long]
    sl[sfp_short] = high[sfp_short]
    rejection_long = (close - low) / candle_range * 100
    rejection_short = (high - close) / candle_range * 100
    return {
        "entries": sfp_long, "short_entries": sfp_short, "sl": sl,
        "dir": direction.astype(int),
        "rejection_long": rejection_long, "rejection_short": rejection_short,
        "level_long": pl, "level_short": ph,
        "name": "ictsuite_sfp",
    }


# ---------------------------------------------------------------------------
# 5. SFP Institutional (depth-filtered swing failure, strict reclaim, killzone)
# ---------------------------------------------------------------------------
def sfp_institutional(df, depth_min: float = 0.0015, depth_max: float = 0.0050,
                      rejection_min: float = 50.0, killzones: bool = True,
                      reclaim_bars: int = 2) -> dict:
    """Absorption SFP: sweep a real swing low/high by 0.15-0.50% only.

    Depth filter (the 0.15-0.50% zone) discards both shallow continuation
    sweeps (<0.15%) and clean structural breaks (>0.50%). Reclaim requires
    price to close back inside the prior swing range within the activation
    candle or the next one (<= `reclaim_bars`). Signals are restricted to the
    London / NY killzones for absorption volume.
    """
    close = df["close"]
    high = df["high"]
    low = df["low"]
    open_ = df["open"]

    sw_h, sw_l = ic.swing_highs_lows(high, low)
    ph = high.where(sw_h).ffill()   # last confirmed swing high
    pl = low.where(sw_l).ffill()    # last confirmed swing low
    candle_range = (high - low).replace(0, np.nan)

    # depth of the sweep beyond the swing level (0.15% .. 0.50%)
    depth_short = ((high - ph) / ph.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)
    depth_long = ((pl - low) / pl.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)

    sweep_short = (high > ph) & depth_short.between(depth_min, depth_max)
    sweep_long = (low < pl) & depth_long.between(depth_min, depth_max)

    # strict reclaim: close back inside the prior swing range <= 2 candles
    in_prev_range = close.between(pl, ph)
    reclaim_short = in_prev_range | in_prev_range.shift(1)
    reclaim_long = in_prev_range | in_prev_range.shift(1)

    # candle rejection quality (wick vs body)
    rejection_long = (close - low) / candle_range * 100
    rejection_short = (high - close) / candle_range * 100
    rq_long = (close > open_) & (rejection_long >= rejection_min)
    rq_short = (close < open_) & (rejection_short >= rejection_min)

    kz = pd.Series(True, index=df.index)
    if killzones:
        kz = ic.is_killzone(ic.session(df.index))

    entries = (sweep_long & reclaim_long & rq_long & kz).fillna(False)
    shorts = (sweep_short & reclaim_short & rq_short & kz).fillna(False)

    sl = pd.Series(np.nan, index=df.index)
    sl[entries] = low[entries]     # swept wick low
    sl[shorts] = high[shorts]      # swept wick high

    direction = pd.Series(0, index=df.index)
    direction[entries] = 1
    direction[shorts] = -1
    return {
        "entries": entries, "short_entries": shorts, "sl": sl,
        "dir": direction.astype(int),
        "depth_long": depth_long.fillna(0),
        "depth_short": depth_short.fillna(0),
        "reclaim_long": reclaim_long.fillna(False),
        "reclaim_short": reclaim_short.fillna(False),
        "level_long": pl, "level_short": ph,
        "name": "ictsuite_sfp_institutional",
    }


def compute(df: pd.DataFrame, strategy: str = "scalp_sweep", **params) -> dict:
    """Dispatch to one of the suite strategies."""
    registry = {
        "scalp_sweep": scalp_sweep,
        "intraday_quantum": intraday_quantum,
        "macro_swing": macro_swing,
        "sfp": sfp,
        "sfp_institutional": sfp_institutional,
    }
    if strategy not in registry:
        raise ValueError(f"Unknown ictsuite strategy '{strategy}'. "
                         f"Choose from {sorted(registry)}")
    return registry[strategy](df, **params)