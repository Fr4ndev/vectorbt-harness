#!/usr/bin/env python
"""
run_backtest.py — CLI entry point for the ICT path backtesting harness.

Examples (from harness root, using the ccxtv2 venv):
    python run_backtest.py --family demon2:po3 --symbol BTC --tf 4h
    python run_backtest.py --list
    python run_backtest.py --family ictquantum:v11 --symbol ETH --tf 1h --json

Multi-symbol / multi-strategy sweeps:
    python run_backtest.py --sweep --family ictsuite --days 730
"""
from __future__ import annotations

import argparse
import json
import sys

from config import config as cfg
from engine import runner


def _run_one(family, strategy, symbol, tf, days, exchange):
    res = runner.run_one(family=family, strategy=strategy, symbol=symbol,
                         tf=tf, days=days, exchange=exchange)
    return runner.summarize(res)


def main():
    ap = argparse.ArgumentParser(description="ICT path vectorbt backtest harness")
    ap.add_argument("--family", default="demon2:po3",
                    help="strategy id e.g. demon2:po3, ictquantum:v11, ictsuite:sfp")
    ap.add_argument("--symbol", default="BTC")
    ap.add_argument("--tf", default=None)
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--exchange", default="hyperliquid")
    ap.add_argument("--list", action="store_true", help="list runnable strategies")
    ap.add_argument("--json", action="store_true", help="JSON output")
    ap.add_argument("--sweep", action="store_true",
                    help="run the whole family (all inner strategies)")
    args = ap.parse_args()

    if args.list:
        print("\n".join(cfg.list_strategies()))
        return

    family = args.family
    strategy = None
    if ":" in family:
        family, strategy = family.split(":", 1)

    if args.sweep:
        reg = cfg.REGISTRY[family]
        inner = (reg.get("strategies") or reg.get("versions")
                 or reg.get("tiers") or [None])
        frames = []
        for s in inner:
            try:
                frames.append(_run_one(family, s, args.symbol, args.tf, args.days,
                                       args.exchange))
            except Exception as e:
                frames.append({"family": family, "strategy": s, "error": str(e)})
        out = pd.concat(frames, ignore_index=True) if frames else None
        if args.json:
            print(out.to_json(orient="records", lines=True))
        else:
            print(out.to_string(index=False))
        return

    df = _run_one(family, strategy, args.symbol, args.tf, args.days, args.exchange)
    if args.json:
        print(df.to_json(orient="records", lines=True))
    else:
        print(df.to_string(index=False))


if __name__ == "__main__":
    import pandas as pd
    sys.exit(main())