"""
ccxt_loader.py — generic ccxt OHLCV loader for backup exchanges
(Binance, Bybit, OKX). Heavier than the Hyperliquid loader; used only when
you want to cross-check signals on a CEX or when HL data is unavailable.

Returns a pandas DataFrame with DatetimeIndex and
open/high/low/close/volume columns.

Standard ccxt symbol format:
    Binance/Bybit/OKX perp: "BTC/USDT:USDT"
    (Hyperliquid via ccxt would be "BTC/USDC:USDC", but prefer the native
     loader for HL.)
"""
from __future__ import annotations

from typing import Optional

import ccxt
import pandas as pd

TF_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
    "30m": 1_800_000, "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000,
    "6h": 21_600_000, "12h": 43_200_000, "1d": 86_400_000, "1w": 604_800_000,
}


def load_ohlcv(
    exchange: str = "binance",
    symbol: str = "BTC/USDT:USDT",
    timeframe: str = "4h",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    days: int = 365,
) -> pd.DataFrame:
    """Paginated OHLCV fetch for a ccxt exchange."""
    exchange_cls = getattr(ccxt, exchange)
    ex = exchange_cls({"enableRateLimit": True, "timeout": 30000})
    try:
        ex.load_markets()
    except Exception:
        pass

    end_ms = int(pd.Timestamp(end_date).timestamp() * 1000) if end_date else ex.milliseconds()
    start_ms = (
        int(pd.Timestamp(start_date).timestamp() * 1000)
        if start_date
        else end_ms - int(days) * 86400000
    )

    rows = []
    since = start_ms
    while since < end_ms:
        ohlcv = ex.fetch_ohlcv(symbol, timeframe, since=since, limit=1000)
        if not ohlcv:
            break
        rows.extend(ohlcv)
        since = ohlcv[-1][0] + TF_MS.get(timeframe, 300_000)
        if len(ohlcv) < 1000:
            break

    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df["datetime"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.set_index("datetime").sort_index()
    df = df[~df.index.duplicated(keep="first")]
    return df[["open", "high", "low", "close", "volume"]]
