"""
hyperliquid_loader.py — Hyperliquid OHLCV loader for the vectorbt harness.

Adapted from ~/Escritorio/hl_oi_cap_backtest/{api,data}.py with pagination added
so we can pull arbitrary-length backtest windows (the native /info endpoint
caps each request at ~5000 candles).

Public entry point: `load_ohlcv()` returns a pandas DataFrame with a
DatetimeIndex and columns: open, high, low, close, volume, trades.
"""
from __future__ import annotations

import time
from typing import Optional

import numpy as np
import pandas as pd
import requests

API_BASE = "https://api.hyperliquid.xyz"
TIMEOUT = 20
MAX_CANDLES_PER_CALL = 5000

# Hyperliquid native interval strings -> millis per candle
INTERVAL_MS = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
    "1w": 604_800_000,
    "1M": 2_592_000_000,
}


def _post(endpoint: str, body: dict):
    url = f"{API_BASE}/{endpoint}"
    resp = requests.post(url, json=body, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def get_candles(
    coin: str,
    interval: str = "5m",
    start_ms: Optional[int] = None,
    end_ms: Optional[int] = None,
    paginate: bool = True,
) -> list[dict]:
    """Fetch OHLCV candles, optionally paginating backwards in time.

    Genuine HL intervals are fine; each request returns up to 5000 candles.
    When `paginate` is True and a start_ms is given, we page backward from
    end_ms to start_ms in 5000-candle chunks.
    """
    now = int(time.time() * 1000)
    end_ms = end_ms or now
    start_ms = start_ms or (end_ms - 30 * 86400000)

    if not paginate or start_ms >= end_ms:
        return _post(
            "info",
            {
                "type": "candleSnapshot",
                "req": {
                    "coin": coin,
                    "interval": interval,
                    "startTime": start_ms,
                    "endTime": end_ms,
                },
            },
        )

    step = INTERVAL_MS.get(interval, 300_000) * MAX_CANDLES_PER_CALL
    all_rows: list[dict] = []
    cursor = end_ms
    while cursor > start_ms:
        lo = max(start_ms, cursor - step)
        raw = _post(
            "info",
            {
                "type": "candleSnapshot",
                "req": {
                    "coin": coin,
                    "interval": interval,
                    "startTime": lo,
                    "endTime": cursor,
                },
            },
        )
        if not raw:
            break
        all_rows.extend(raw)
        # move cursor to one ms before the earliest candle we already got
        earliest = min(r["t"] for r in raw)
        if earliest >= cursor:
            break  # safety: no progress -> avoid infinite loop
        cursor = earliest
    # de-dup + sort in candles_df
    return all_rows


def candles_df(
    coin: str,
    interval: str = "5m",
    days: int = 30,
    start_ms: Optional[int] = None,
    end_ms: Optional[int] = None,
) -> pd.DataFrame:
    """Return DataFrame (DatetimeIndex) with open/high/low/close/volume/trades."""
    now = int(time.time() * 1000)
    if start_ms is None:
        start_ms = now - int(days) * 86400000
    raw = get_candles(coin, interval, start_ms=start_ms, end_ms=end_ms, paginate=True)
    if not raw:
        return pd.DataFrame()

    df = pd.DataFrame(raw)
    df["t"] = pd.to_datetime(df["t"], unit="ms")
    df = df.set_index("t").sort_index()
    df = df[~df.index.duplicated(keep="first")]
    df = df.rename(
        columns={
            "o": "open",
            "h": "high",
            "l": "low",
            "c": "close",
            "v": "volume",
            "n": "trades",
        }
    )
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["trades"] = pd.to_numeric(df["trades"], errors="coerce")
    # keep only ultimately needed cols, in a stable order
    for col in ["open", "high", "low", "close", "volume", "trades"]:
        if col not in df.columns:
            df[col] = np.nan
    return df[["open", "high", "low", "close", "volume", "trades"]]


def load_ohlcv(
    symbol: str,
    timeframe: str = "4h",
    days: int = 365,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """High-level entry point.

    `symbol` is a bare HL coin name ("BTC", "ETH", "HYPE"). If a slash or
    colon form is passed ("BTC/USDT:USDT"), the coin name is extracted.

    `start_date`/`end_date` (ISO strings) override `days` when given.
    """
    coin = symbol.split("/")[0].split(":")[0]
    start_ms = end_ms = None
    if start_date:
        start_ms = int(pd.Timestamp(start_date).timestamp() * 1000)
    if end_date:
        end_ms = int(pd.Timestamp(end_date).timestamp() * 1000)
    return candles_df(coin, timeframe, days=days, start_ms=start_ms, end_ms=end_ms)
