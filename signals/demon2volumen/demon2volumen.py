"""
demon2volumen.py — Demon v2 Volumen signals.

The demon2volumen family is the same 10 demon2 ICT/SMC strategies but with an
institutional-volume confirmation layer (order-flow / large-trade gates from
demon2volumen/indicators.py) layered on top, plus the standalone short-only
Liquidity Sweep bot (liquidity_sweep_bot/strategies/liquidity_sweep.py).

Because order-book / large-trade data is live-only (not OHLC), the volume gate
here is approximated from the OHLCV `volume` column (a rolling "accumulation /
distribution" proxy). The Liquidity Sweep bot (short-only) is fully ported.

Sub-strategies:
    liquidity_sweep_bot  — 4H short-only SFP of a prior 10-bar swing high, RR 1:2
    (all 10 demon2 strategies are available via demon2.compute with a
     volume-gate overlay applied here)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from indicators import core as ic
from signals.demon2 import demon2


# ---------------------------------------------------------------------------
# Institutional volume confirmation (OHLCV proxy)
# ---------------------------------------------------------------------------
def volume_gate(df: pd.DataFrame, lookback: int = 20,
                ratio: float = 0.6) -> pd.Series:
    """Approximate accumulation(->+1)/distribution(->-1) from volume + wicks.

    In the live code this uses order-book imbalance and aggressive-trade delta.
    Here we proxy with a rolling signed-volume where a close near the high of
    the range with above average volume counts as buying pressure.
    """
    close = df["close"]
    high = df["high"]
    low = df["low"]
    vol = df["volume"]
    rng = (high - low).replace(0, np.nan)
    pos = (close - low) / rng  # 0..1 location of close in the bar
    signed = (pos - 0.5) * 2   # -1..+1
    cum = (signed * vol).rolling(lookback, min_periods=5).sum()
    vol_sum = vol.rolling(lookback, min_periods=5).sum().replace(0, np.nan)
    delta_ratio = (cum / vol_sum).abs()
    gate = pd.Series(np.where((cum > 0) & (delta_ratio > ratio), 1,
                              np.where((cum < 0) & (delta_ratio > ratio), -1, 0)),
                     index=df.index)
    return gate


# ---------------------------------------------------------------------------
# Liquidity Sweep bot — short only, 4H
# ---------------------------------------------------------------------------
def liquidity_sweep_bot(df, swing_lookback: int = 10, atr_buf: float = 0.1,
                        rr: float = 2.0) -> dict:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    atr_ = ic.atr(high, low, close, period=14, method="sma")

    rolling_high = high.rolling(swing_lookback).max().shift(1)
    # entry: sweep buy-side pool + fake-out close back below
    bearish = (high > rolling_high) & (close < rolling_high)
    bearish &= rolling_high.notna()

    sl = pd.Series(np.nan, index=df.index)
    sl[bearish] = high[bearish] + atr_[bearish] * atr_buf

    conf = pd.Series(5, index=df.index)
    ru, pw = demon2._confluence_matrix(conf)
    return demon2._collect(
        pd.Series(False, index=df.index), bearish, sl,
        pd.Series(0, index=df.index),
        {"confluences": conf, "risk_unit": ru, "prob_win": pw},
        name="demon2volumen_liquidity_sweep_bot",
    )


def compute(df: pd.DataFrame, strategy: str = "liquidity_sweep_bot",
            use_volume_gate: bool = False, **params) -> dict:
    """Dispatch. If use_volume_gate and the strategy is one of the demon2 ones,
    the entries get filtered by the volume-gate direction matching the signal.
    """
    if strategy == "liquidity_sweep_bot":
        return liquidity_sweep_bot(df, **params)

    res = demon2.compute(df, strategy=strategy, **params)
    if use_volume_gate:
        gate = volume_gate(df)
        res["entries"] = res["entries"] & (gate == 1)
        res["short_entries"] = res["short_entries"] & (gate == -1)
    res["name"] = f"demon2volumen_{strategy}"
    return res
