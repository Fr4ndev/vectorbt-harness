"""
download_history.py — download 5-7 years of OHLCV for the HVFVG regime validation.

Source: Binance (spot + perp via ccxt) — the only source with full 2019-2026
history (Hyperliquid only lists since ~2023). Cached to data/cache/hist so the
heavy pagination runs once.

Run (from harness root, ccxtv2 venv):
    ~/Escritorio/ccxtv2/venv/bin/python download_history.py
"""
from __future__ import annotations

import os
import time

import pandas as pd
import ccxt

START = "2019-01-01"
END = None  # now
SYMBOLS = ["BTC", "ETH"]
TIMEFRAMES = ["1h", "2h", "4h", "30m"]
CEX_SYMBOL = "BTC/USDT:USDT"  # perp; loader uses bare symbol but we pass full here

CACHE = "data/cache/hist"


def main() -> int:
    os.makedirs(CACHE, exist_ok=True)
    ex = ccxt.binance({"enableRateLimit": True, "timeout": 60000})
    try:
        ex.load_markets()
    except Exception:
        pass

    end_ms = ex.milliseconds()
    start_ms = int(pd.Timestamp(START).timestamp() * 1000)

    for sym in SYMBOLS:
        csym = sym + "/USDT:USDT"
        for tf in TIMEFRAMES:
            out = os.path.join(CACHE, f"{sym}_{tf}_hist.csv")
            if os.path.exists(out):
                df = pd.read_csv(out, index_col=0, parse_dates=True)
                if len(df) > 50000:
                    print(f"{sym} {tf}: cached {len(df)} rows, skip")
                    continue
            rows = []
            since = start_ms
            while since < end_ms:
                ohlcv = ex.fetch_ohlcv(csym, tf, since=since, limit=1000)
                if not ohlcv:
                    break
                rows.extend(ohlcv)
                since = ohlcv[-1][0] + 1
                if len(ohlcv) < 1000:
                    break
                time.sleep(0.05)
            if not rows:
                print(f"{sym} {tf}: NO DATA")
                continue
            df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
            df["datetime"] = pd.to_datetime(df["ts"], unit="ms")
            df = df.set_index("datetime").sort_index()
            df = df[~df.index.duplicated(keep="first")]
            df = df[["open", "high", "low", "close", "volume"]].ffill()
            df.to_csv(out, index=True)
            print(f"{sym} {tf}: {len(df)} rows, {df.index[0].date()} -> {df.index[-1].date()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())