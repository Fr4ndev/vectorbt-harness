"""
loader.py — unified data loader facade.

Normalizes Hyperliquid + ccxt loaders behind one `load()` entry point so the
engine and every signal module can request data the same way regardless of
source.

Returns a DataFrame with DatetimeIndex and columns
open/high/low/close/volume (optionally trades).
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from . import hyperliquid_loader, ccxt_loader

_SUPPORTED = {"hyperliquid", "binance", "bybit", "okx"}


def load(
    symbol: str = "BTC",
    timeframe: str = "4h",
    days: int = 365,
    exchange: str = "hyperliquid",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    cache: bool = True,
    cache_dir: str = "data/cache",
) -> pd.DataFrame:
    """Unified loader.

    Args:
        symbol: bare coin ("BTC") for Hyperliquid, or ccxt form for CEX.
        timeframe: candle interval.
        days: window in days (used when start_date/end_date not given).
        exchange: one of _SUPPORTED.
        cache: whether to cache CSVs to disk for fast re-runs.
    """
    exchange = exchange.lower()
    if exchange not in _SUPPORTED:
        raise ValueError(f"Unsupported exchange '{exchange}'. Use one of {_SUPPORTED}")

    import os

    if cache:
        os.makedirs(cache_dir, exist_ok=True)
        cache_file = os.path.join(cache_dir, f"{exchange}_{symbol}_{timeframe}_{days}d.csv")

        if os.path.exists(cache_file):
            df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
            if len(df) > 10:
                return df

    if exchange == "hyperliquid":
        df = hyperliquid_loader.load_ohlcv(
            symbol, timeframe, days=days, start_date=start_date, end_date=end_date
        )
    else:
        df = ccxt_loader.load_ohlcv(
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
            days=days,
        )

    if df.empty:
        return df

    df = df.ffill()
    if cache and len(df):
        df.to_csv(cache_file, index=True)
    return df
