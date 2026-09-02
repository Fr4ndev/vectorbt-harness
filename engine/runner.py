"""
runner.py — backtest runner tying signals -> portfolio engine.

Usage (from harness root):
    python -m engine.runner --family demon2:po3 --symbol BTC --tf 4h

Loads data via data.loader, computes the signal dict, builds exit brackets
(1:2 / 1:5 split or simple), runs vectorbt portfolio, and returns a summary
dict with the key stats.
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd

from data import loader
from config import config as cfg
from portfolio import engine, exits


def run_one(
    family: str,
    strategy: str | None = None,
    symbol: str = "BTC",
    tf: str | None = None,
    days: int = 365,
    exchange: str = "hyperliquid",
    params: dict | None = None,
    mode: str | None = None,
    use_cache: bool = True,
    **exit_kwargs,
) -> dict:
    """Run one backtest and return the results dict."""
    reg = cfg.REGISTRY[family]
    mod = cfg.get_strategy_module(family)
    tf = tf or reg["tf"]
    mode = mode or reg.get("exit", "simple")

    df = loader.load(symbol=symbol, timeframe=tf, days=days, exchange=exchange,
                     cache=use_cache)
    if df.empty:
        return {"error": f"No data for {symbol} {tf}", "family": family,
                "strategy": strategy}

    if strategy is not None:
        sig = mod.compute(df, strategy=strategy, **params or {})
    else:
        sig = mod.compute(df, **params or {})

    if "error" in sig:
        return sig

    close = df["close"]
    entries = sig["entries"]
    shorts = sig["short_entries"]
    sl = sig["sl"]

    # Build the exit scheme per user spec: entry + sl -> brackets.
    # Strategy-native TP levels (sig["tp1"]/["tp2"]) take precedence over the
    # generic 1:2 / 1:5 derivation (e.g. fib_retrace wires Natives).
    direction = sig["dir"]
    if sig.get("tp1") is not None or sig.get("tp2") is not None:
        brackets = exits.build_native_brackets(
            entry=close, sl=sl,
            tp1=sig.get("tp1", pd.Series(np.nan, index=df.index)),
            tp2=sig.get("tp2", pd.Series(np.nan, index=df.index)),
            direction=direction,
            weight_tp1=exit_kwargs.get(
                "weight_tp1", sig.get("weight_tp1", cfg.EXIT_DEFAULTS["weight_tp1"])
            ),
        )
    else:
        brackets = exits.build_brackets(
            entry=close, sl=sl, direction=direction,
            rr_tp1=exit_kwargs.get("rr_tp1", cfg.EXIT_DEFAULTS["rr_tp1"]),
            rr_runner=exit_kwargs.get("rr_runner", cfg.EXIT_DEFAULTS["rr_runner"]),
            weight_tp1=exit_kwargs.get("weight_tp1", cfg.EXIT_DEFAULTS["weight_tp1"]),
        )

    f = dict(cfg.EXIT_DEFAULTS)
    f.update(exit_kwargs)
    res = engine.run(
        df, entries=entries, short_entries=shorts, brackets=brackets,
        size=f["size"], fees=f["fees"], slippage=f["slippage"],
        init_cash=f["init_cash"], freq=tf, mode=mode,
    )

    out = {
        "family": family,
        "strategy": strategy or "default",
        "symbol": symbol,
        "timeframe": tf,
        "n_signals": int(entries.sum() + shorts.sum()),
        "n_long": int(entries.sum()),
        "n_short": int(shorts.sum()),
        "mode": mode,
        "result": res,
    }
    return out


def _stats_to_df(stats):
    if isinstance(stats, dict):
        return pd.Series(stats)
    if isinstance(stats, pd.Series):
        return stats
    try:
        return pd.Series(stats.to_dict())
    except Exception:
        return pd.Series()


def summarize(res: dict) -> pd.DataFrame:
    """Flatten a run dict into a one-row summary DataFrame."""
    rec = {
        "family": res.get("family"),
        "strategy": res.get("strategy"),
        "symbol": res.get("symbol"),
        "timeframe": res.get("timeframe"),
        "n_signals": res.get("n_signals"),
        "n_long": res.get("n_long"),
        "n_short": res.get("n_short"),
    }
    mode = res.get("mode")
    if "result" not in res:
        rec["error"] = res.get("error", "unknown")
        return pd.DataFrame([rec])

    result = res["result"]
    if mode == "split":
        stats = result.get("combined_stats", {})
        sa = stats.get("leg_a_stats", {})
        sb = stats.get("leg_b_stats", {})
        rec["total_trades"] = stats.get("Total Trades", None)
        for k, v in sa.items():
            rec[f"a_{k}"] = v
        for k, v in sb.items():
            rec[f"b_{k}"] = v
    else:
        stats = result.get("stats")
        s = _stats_to_df(stats)
        for k in s.index:
            rec[str(k)] = s[k]
    return pd.DataFrame([rec])


def main():
    ap = argparse.ArgumentParser(description="ICT path backtest runner")
    ap.add_argument("--family", required=True, help="e.g. demon2:po3, ictquantum:v11")
    ap.add_argument("--symbol", default="BTC")
    ap.add_argument("--tf", default=None)
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--exchange", default="hyperliquid")
    ap.add_argument("--json", action="store_true", help="emit JSON to stdout")
    args = ap.parse_args()

    fam = args.family
    strategy = None
    if ":" in fam:
        fam, strategy = fam.split(":", 1)

    res = run_one(family=fam, strategy=strategy, symbol=args.symbol,
                  tf=args.tf, days=args.days, exchange=args.exchange)
    if args.json:
        out = {k: v for k, v in res.items() if k != "result"}
        if "result" in res:
            r = res["result"]
            if isinstance(r, dict):
                for key in ("stats", "combined_stats"):
                    if key in r:
                        out[key] = (r[key].to_dict()
                                    if hasattr(r[key], "to_dict")
                                    else r[key])
        print(json.dumps(out, indent=2, default=str))
    else:
        print(summarize(res).to_string(index=False))


if __name__ == "__main__":
    main()