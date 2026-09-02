"""
exits.py — exit-scheme builders.

The user's default management rule (per conversation):
    SL and TP always in a 1:2 relationship.
    80% of the position closes at TP1 (1:2), the rest is a runner up to 1:5,
    and the SL moves to break-even after the 1:2 partial fills.

Each strategy signal produces an `entry` and an absolute `sl` price. From
those we derive the risk distance and build the two bracket legs that
vectorbt can simulate:

  Leg A (80% notional): SL at entry +/- risk
                         TP1 at entry +/- 2*risk   (1:2)
  Leg B (20% notional): SL at entry (break-even) after TP1 bar
                         TP2 at entry +/- 5*risk   (1:5)
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def risk_from_sl(entry: pd.Series, sl: pd.Series, direction: pd.Series) -> pd.Series:
    """Absolute risk distance per signal (long/short aware)."""
    return (entry - sl).abs()


def build_brackets(
    entry: pd.Series,
    sl: pd.Series,
    direction: pd.Series,   # +1 long, -1 short (0 = no signal)
    rr_tp1: float = 2.0,
    rr_runner: float = 5.0,
    weight_tp1: float = 0.8,
    trail: pd.Series | None = None,
) -> dict:
    """Return dict with the two bracket columns keyed on the entry index.

    long : sl is below entry, tp above
    short: sl is above entry, tp below

    Returns:
        tp1        : absolute price for the 1:2 partial
        tp2        : absolute price for the 1:5 runner
        sl_tp1     : SL used on leg A (the 1:2 leg), == user sl
        sl_be      : SL moved to break-even on runner leg
        trail      : optional per-bar trailing-invalidation level for leg B
                     (e.g. the opposite 4h-FVG extreme); when present the
                     runner stop re-anchors to it bar-by-bar.
        has_signal : bool mask where a trade is defined
    """
    risk = risk_from_sl(entry, sl, direction)
    is_long = direction > 0
    is_short = direction < 0
    has = direction != 0

    tp1 = pd.Series(np.nan, index=entry.index)
    tp2 = pd.Series(np.nan, index=entry.index)
    sl_tp1 = pd.Series(np.nan, index=entry.index)
    sl_be = pd.Series(np.nan, index=entry.index)

    tp1 = np.where(is_long, entry + risk * rr_tp1, tp1)
    tp1 = np.where(is_short, entry - risk * rr_tp1, tp1)
    tp2 = np.where(is_long, entry + risk * rr_runner, tp2)
    tp2 = np.where(is_short, entry - risk * rr_runner, tp2)

    sl_tp1 = sl  # leg A keeps the original stop
    sl_be = entry  # runner hits break-even after TP1

    return {
        "entry": entry,
        "sl": sl,
        "tp1": pd.Series(tp1, index=entry.index),
        "tp2": pd.Series(tp2, index=entry.index),
        "sl_tp1": sl_tp1,
        "sl_be": pd.Series(sl_be, index=entry.index),
        "trail": trail,
        "weight_tp1": weight_tp1,
        "rr_tp1": rr_tp1,
        "rr_runner": rr_runner,
        "has_signal": has,
    }


def build_native_brackets(
    entry: pd.Series,
    sl: pd.Series,
    tp1: pd.Series,
    tp2: pd.Series,
    direction: pd.Series,
    weight_tp1: float = 0.8,
) -> dict:
    """Build the two-leg bracket from strategy-native absolute levels.

    Used when a signal module provides its own TP levels (e.g. fib_retrace
    wiring the 1.17/1.27 extensions and 0.5 partial) instead of letting the
    harness derive 1:2 / 1:5 targets from the SL.
    """
    has = (direction != 0) & tp1.notna() & tp2.notna()
    return {
        "entry": entry,
        "sl": sl,
        "tp1": pd.Series(tp1.where(has), index=entry.index),
        "tp2": pd.Series(tp2.where(has), index=entry.index),
        "sl_tp1": sl,
        "sl_be": entry,
        "weight_tp1": weight_tp1,
        "rr_tp1": None,
        "rr_runner": None,
        "has_signal": has,
    }


def relative_sl_tp(close: pd.Series, bracket: dict) -> dict:
    """Convert absolute brackets to the relative values vectorbt's
    sl_stop/tp_stop expect for a single full-position simulation."""
    rel_sl = ((close - bracket["sl"]) / close).abs()
    rel_tp1 = ((bracket["tp1"] - close) / close).abs()
    return {"sl": rel_sl, "tp1": rel_tp1}
