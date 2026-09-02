"""
engine.py — vectorbt portfolio runner.

Wraps vbt.Portfolio with the project conventions:
  - data columns: open/high/low/close/volume on a DatetimeIndex
  - signal inputs: entries (bool) / short_entries (bool) masks, or a dict
    of brackets produced by portfolio.exits.build_brackets
  - default exit scheme (see exits.py): 1:2 partial (80%) + runner to 1:5
    + SL to break-even.

Two modes:
  * near_tp_strategy=False -> simple vbt.Portfolio.from_signals with
    sl_stop/tp_stop (whole position bracket).
  * near_tp_strategy=True  -> simulates the partial+runner scheme by running
    the 80% leg (tp1) and the 20% runner (tp2 with BE) and merging stats.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import vectorbt as vbt


def run(
    df: pd.DataFrame,
    entries: pd.Series | None = None,
    short_entries: pd.Series | None = None,
    brackets: dict | None = None,
    size: float = 1.0,
    fees: float = 0.0006,
    slippage: float = 0.0003,
    init_cash: float = 10000.0,
    freq: str | None = None,
    mode: str = "simple",  # 'simple' | 'split'
    partial: bool = True,
) -> dict:
    """Run a vectorbt portfolio and return a dict of results.

    Args:
        df: OHLCV frame (needs at least 'close', optionally 'open').
        entries/short_entries: boolean signal masks.
        brackets: output of exits.build_brackets (entries/sl/tp1/tp2).
        mode='simple': one from_signals call (needs entries / short_entries).
        mode='split':  partial (80% tp1) + runner (20% tp2, SL to BE).
    """
    close = df["close"]
    if freq is None:
        freq = _infer_freq(df.index)

    if mode == "simple":
        pf = vbt.Portfolio.from_signals(
            close=close,
            entries=entries,
            short_entries=short_entries,
            size=size,
            fees=fees,
            slippage=slippage,
            init_cash=init_cash,
            freq=freq,
        )
        return _wrap(pf, df, close)

    if mode == "split":
        if brackets is None:
            raise ValueError("mode='split' requires brackets from portfolio.exits")
        res = _run_split(close, brackets, size, fees, slippage, init_cash, freq, partial)
        return res

    raise ValueError("mode must be 'simple' or 'split'")


def _run_split(close, brackets, size, fees, slippage, init_cash, freq, partial):
    has = brackets["has_signal"].fillna(False).astype(bool)
    entry = brackets["entry"]
    tp1 = brackets["tp1"]
    tp2 = brackets["tp2"]
    sl_tp1 = brackets["sl_tp1"]
    sl_be = brackets["sl_be"]
    w1 = brackets["weight_tp1"] if partial else 1.0

    # direction from entry vs sl: long if sl < entry
    is_long = (~np.isnan(entry)) & (entry > sl_tp1)
    long_entries = has & is_long
    short_entries = has & ~is_long

    # ---- Leg A: 80% at TP1 (1:2) with original SL ----
    rel_sl_a = ((close - sl_tp1) / close).abs()
    rel_tp_a = ((tp1 - close) / close).abs()
    pf_a = vbt.Portfolio.from_signals(
        close=close,
        entries=long_entries,
        short_entries=short_entries,
        sl_stop=rel_sl_a.fillna(np.inf),
        tp_stop=rel_tp_a.fillna(np.inf),
        size=size * w1,
        fees=fees, slippage=slippage, init_cash=init_cash * w1, freq=freq,
    )

    # ---- Leg B: 20% runner to 1:5, SL moved to BE (or trailing anchor) ----
    trail = brackets.get("trail")
    if trail is not None and trail.notna().any():
        # per-bar trailing invalidation (e.g. 4h-FVG opposite extreme)
        rel_sl_b = ((close - trail) / close).abs()
    else:
        rel_sl_b = ((close - sl_be) / close).abs()
    rel_tp_b = ((tp2 - close) / close).abs()
    pf_b = vbt.Portfolio.from_signals(
        close=close,
        entries=long_entries,
        short_entries=short_entries,
        sl_stop=rel_sl_b.fillna(np.inf),
        tp_stop=rel_tp_b.fillna(np.inf),
        size=size * (1 - w1),
        fees=fees, slippage=slippage, init_cash=init_cash * (1 - w1), freq=freq,
    )

    return {
        "portfolio": None,  # combined object not natively supported
        "leg_a": pf_a,
        "leg_b": pf_b,
        "combined_stats": _combine_split_stats(pf_a, pf_b),
    }


def _combine_split_stats(pf_a, pf_b):
    sa = pf_a.stats()
    sb = pf_b.stats()
    combined = {}
    # DataFrame of trade records available via .records
    try:
        n_trades = int(sa["Total Trades"]) + int(sb["Total Trades"])
        combined["Total Trades"] = n_trades
    except Exception:
        pass
    combined["leg_a_stats"] = sa.to_dict() if isinstance(sa, pd.Series) else sa
    combined["leg_b_stats"] = sb.to_dict() if isinstance(sb, pd.Series) else sb
    return combined


def _run_simple(pf, df, close):
    return _wrap(pf, df, close)


def _wrap(pf, df, close):
    stats = pf.stats()
    trades = None
    try:
        trades = pf.trades.records
    except Exception:
        trades = pd.DataFrame()
    return {
        "portfolio": pf,
        "stats": stats,
        "trades": trades,
        "close": close,
    }


def _infer_freq(index: pd.DatetimeIndex) -> str:
    try:
        return pd.infer_freq(index) or "D"
    except Exception:
        return "D"
