"""
test_functional.py — end-to-end smoke test.

Fetches real Hyperliquid data and runs a signal module through the engine.

Run (from harness root, ccxtv2 venv):
    ~/Escritorio/ccxtv2/venv/bin/python tests/test_functional.py

Skips (exit 0) if no network; prints PASS/FAIL for each stage.
"""
from __future__ import annotations

import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, ".")

from data import loader
from engine import runner
from signals.demon1.demon1 import compute as demon1_compute
from signals.demon2.demon2 import compute as demon2_compute
from signals.demon2volumen.demon2volumen import compute as demon2volumen_compute
from signals.ictquantum.ictquantum import compute as ictquantum_compute
from signals.ict4hsweep.ict4hsweep import compute as ict4hsweep_compute
from signals.ictsuite.ictsuite import compute as ictsuite_compute
from signals.fib_retrace.fib_retrace import compute as fib_retrace_compute
from signals.fvg_mtf.fvg_mtf import compute as fvg_mtf_compute


def _assert(cond, msg):
    if not cond:
        print(f"FAIL: {msg}")
        sys.exit(1)
    print(f"PASS: {msg}")


def main():
    print("== 1. Data: fetch real Hyperliquid BTC 1h (90d, cached) ==")
    try:
        df = loader.load(symbol="BTC", timeframe="1h", days=90, cache=True)
    except Exception as e:
        print(f"SKIP: no network/data ({e})")
        return
    _assert(len(df) > 100, f"loaded {len(df)} candles")

    print("== 2. Signals compute on real data ==")
    r = demon1_compute(df)
    _assert(set(["entries", "short_entries", "sl", "dir"]) <= set(r),
            "demon1.compute returns the standard envelope")

    r2 = demon2_compute(df, strategy="po3")
    _assert(r2["entries"].dtype == bool, "demon2 po3 entries are boolean")

    r3 = demon2volumen_compute(df, strategy="liquidity_sweep_bot")
    _assert(set(["entries", "short_entries"]) <= set(r3),
            "demon2volumen liquidity_sweep_bot computes")

    r4 = ictquantum_compute(df, version="v11", btc_df=df, eth_df=df)
    _assert("score" in r4, "ictquantum v11 returns score")

    r5 = ict4hsweep_compute(df, tier="4h")
    _assert("score" in r5, "ict4hsweep returns score")

    r6 = ictsuite_compute(df, strategy="sfp")
    _assert(r6["entries"].dtype == bool, "ictsuite sfp entries boolean")

    r6b = ictsuite_compute(df, strategy="sfp_institutional")
    _assert(set(["entries", "short_entries", "depth_long", "reclaim_long"]) <= set(r6b),
            "ictsuite sfp_institutional fires with depth + reclaim extras")

    r2b = demon2_compute(df, strategy="po3_fractal")
    _assert(set(["entries", "short_entries", "d_open", "judas_long"]) <= set(r2b),
            "demon2 po3_fractal returns open anchors + judas swing")

    r7 = fib_retrace_compute(df)
    _assert(set(["entries", "short_entries", "sl", "dir"]) <= set(r7),
            "fib_retrace returns the standard envelope")
    _assert("confluences" in r7, "fib_retrace returns confluence scoring")

    r8 = fvg_mtf_compute(df, strategy="ifvg")
    _assert(r8["entries"].dtype == bool and "bias4" in r8,
            "fvg_mtf ifvg computes envelope + 4h bias")
    r9 = fvg_mtf_compute(df, strategy="fvg")
    _assert(r9["entries"].dtype == bool and "sl" in r9,
            "fvg_mtf fvg computes envelope + sl")

    print("== 3. Portfolio engine (split mode) on real data ==")
    res = runner.run_one(family="demon1", strategy=None, symbol="BTC", tf="1h",
                         days=90)
    _assert("result" in res, "run_one returns result")
    result = res["result"]
    if res.get("mode") == "split":
        _assert("leg_a" in result and "leg_b" in result,
                "split mode produced two portfolios")
    else:
        _assert("stats" in result, "simple mode produced stats")
    print(f"   -> n_signals={res.get('n_signals')}")

    print("== all functional checks passed ==")


if __name__ == "__main__":
    main()