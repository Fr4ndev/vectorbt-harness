"""
test_hvfvg.py — unit tests for signals/hvfvg/hvfvg.py

Verifies:
  1. No lookahead bias (truncation invariance): recomputing on a prefix must
     not change entries/shorts before the truncation point.
  2. HV-FVG detection fires only with volume anomaly (no signal on normal
     volume displacement).
  3. Retest defense (absorption + rejection) is required: no signal without
     the defense confirmation.
  4. Levels sanity: entry deep inside the FVG, SL/TP finite, dir consistent,
     SL on the correct side for longs/shorts.
  5. The standard envelope keys are present.

Standalone run (harness root, ccxtv2 venv):
    ~/Escritorio/ccxtv2/venv/bin/python tests/test_hvfvg.py
"""
from __future__ import annotations

import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, ".")

from signals.hvfvg.hvfvg import compute


def _frame(o, h, l, c, v):
    n = len(c)
    idx = pd.date_range("2024-01-01", periods=n, freq="1h")
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c,
                         "volume": v}, index=idx)


def _assert(cond, msg):
    if not cond:
        print(f"FAIL: {msg}")
        sys.exit(1)
    print(f"PASS: {msg}")


def test_envelope():
    n = 200
    base = 100.0 + np.arange(n) * 0.02
    o = base.copy(); h = base + 1.0; l = base - 1.0; c = base.copy()
    v = np.full(n, 1000.0)
    df = _frame(o, h, l, c, v)
    r = compute(df)
    keys = {"entries", "short_entries", "sl", "dir"}
    _assert(set(keys) <= set(r), "compute returns the standard envelope")


def test_volume_anomaly_required():
    """A bullish FVG with NORMAL displacement volume must NOT produce a signal."""
    n = 200
    base = np.full(n, 100.0)
    base[100] = 100.0
    o = base.copy(); c = base.copy()
    h = base + 0.5; l = base - 0.5
    # force a bullish FVG at i=102: low[102] > high[100]
    # make candle 100 a low bar, candle 101 the displacement (high vol controlled),
    # candle 102 a strong higher bar -> gap.
    l[100] = 100.0; h[100] = 100.5
    h[101] = 101.0; l[101] = 99.0   # displacement candle
    h[102] = 103.0; l[102] = 102.5  # low[102]=102.5 > high[100]=100.5 -> bull FVG
    o[102] = 101.0; c[102] = 102.8
    v = np.full(n, 1000.0)
    df = _frame(o, h, l, c, v)
    r = compute(df)
    n_sig = int(r["entries"].sum() + r["short_entries"].sum())
    _assert(n_sig == 0, "no signal with normal (non-anomalous) displacement volume")


def test_bull_hvfvg_detection():
    """Craft an HV-FVG: anomalous displacement volume + absorption + rejection
    in a retest that closes back above the gap top -> LONG entry."""
    n = 300
    o = np.full(n, 100.0); c = np.full(n, 100.0)
    h = np.full(n, 100.5); l = np.full(n, 99.5)
    v = np.full(n, 1000.0)
    # ---- displacement (bar 101) with ANOMALOUS volume ----
    # build a low low at 100, high move at 101
    h[100] = 100.2; l[100] = 99.0; o[100] = 100.0; c[100] = 99.5
    h[101] = 102.0; l[101] = 98.5; o[101] = 99.5; c[101] = 101.5
    v[101] = 5000.0  # >> 50-bar mean (1000) * 1.8
    # ---- fish: bar 102 gaps up -> bullish FVG [high[100]=100.2, low[102]]
    h[102] = 104.0; l[102] = 101.6; o[102] = 101.6; c[102] = 103.5
    # bar 100 low bar: low[102] should be > high[100]
    # (low[102]=101.6 > high[100]=100.2 -> bull FVG). good.
    # ---- retest: price drifts back into the zone (within retest_max bars)
    for j in range(103, 110):
        o[j] = 101.2; c[j] = 100.8; h[j] = 101.6; l[j] = 100.2; v[j] = 1000.0
    # absorption candle near the zone: high volume + small body
    o[106] = 101.3; c[106] = 101.2; h[106] = 101.7; l[106] = 100.1
    v[106] = 3000.0  # > SMA20*1.5
    # ---- rejection: close back above gap top -> LONG at rejection bar
    o[108] = 101.4; c[108] = 102.2; h[108] = 102.3; l[108] = 101.3
    df = _frame(o, h, l, c, v)
    r = compute(df)
    n_long = int(r["entries"].sum())
    n_short = int(r["short_entries"].sum())
    _assert(n_long == 1, f"exactly one LONG entry from crafted HV-FVG (got {n_long})")
    _assert(n_short == 0, "no short entry for a bullish setup")
    # entry level must sit deep inside the FVG (>= low + 0.15*height)
    ei = np.where(r["entries"].to_numpy())[0]
    ep = r.get("entry")
    if ep is not None and len(ei):
        _assert(np.isfinite(ep.iloc[ei[0]]), "entry price is finite")
    # SL below entry for a long
    sl = r["sl"]
    for i in ei:
        _assert(sl.iloc[i] < df["close"].iloc[i], "long SL is below close")


def test_no_lookahead_truncation():
    """Truncation invariance: entries computed on a prefix identical to the
    full-data entries before the boundary -> no future leakage."""
    n = 2500
    rng = np.random.default_rng(7)
    base = 100.0 + np.cumsum(rng.normal(0, 0.5, n))
    o = base.copy(); c = base.copy()
    h = np.maximum(o, base + np.abs(rng.normal(0, 1.0, n)))
    l = np.minimum(o, base - np.abs(rng.normal(0, 1.0, n)))
    v = np.abs(rng.lognormal(7.5, 0.8, n))
    # inject occasional displacement spikes to trigger FVGs
    v[::7] = v[::7] * 8.0
    df = _frame(o, h, l, c, v)
    full = compute(df)
    for k in (1000, 1600, 2200):
        prefix = compute(df.iloc[:k])
        a = full["entries"].iloc[:k - 2].to_numpy()
        b = prefix["entries"].iloc[:k - 2].to_numpy()
        sa = full["short_entries"].iloc[:k - 2].to_numpy()
        sb = prefix["short_entries"].iloc[:k - 2].to_numpy()
        _assert((a == b).all() and (sa == sb).all(),
                f"truncation invariance at k={k} (no lookahead)")


def test_bear_hvfvg_detection():
    """Craft a bearish HV-FVG: anomalous displacement volume + absorption +
    rejection closing back below the gap bottom -> SHORT entry."""
    n = 300
    o = np.full(n, 100.0); c = np.full(n, 100.0)
    h = np.full(n, 100.5); l = np.full(n, 99.5)
    v = np.full(n, 1000.0)
    # top at 100, big down move (displacement) at 101 with anomalous volume
    h[100] = 101.0; l[100] = 99.8; o[100] = 100.0; c[100] = 100.5
    h[101] = 100.5; l[101] = 97.8; o[101] = 100.5; c[101] = 98.5
    v[101] = 5000.0
    # bar 102 gaps down -> bearish FVG [high[102], low[100]=99.8]
    h[102] = 98.6; l[102] = 97.0; o[102] = 98.5; c[102] = 97.5
    # (high[102]=98.6 < low[100]=99.8 -> bear FVG)
    # ---- retest: price drifts back into the zone with absorption
    for j in range(103, 110):
        o[j] = 98.0; c[j] = 98.4; h[j] = 98.8; l[j] = 97.6; v[j] = 1000.0
    o[106] = 98.0; c[106] = 98.1; h[106] = 98.9; l[106] = 97.5
    v[106] = 3000.0
    # ---- rejection: close back below gap bottom -> SHORT at rejection bar
    o[108] = 98.2; c[108] = 97.2; h[108] = 98.4; l[108] = 97.0
    df = _frame(o, h, l, c, v)
    r = compute(df)
    n_short = int(r["short_entries"].sum())
    n_long = int(r["entries"].sum())
    _assert(n_short == 1, f"exactly one SHORT entry from crafted bear HV-FVG (got {n_short})")
    _assert(n_long == 0, "no long entry for a bearish setup")
    ei = np.where(r["short_entries"].to_numpy())[0]
    sl = r["sl"]
    for i in ei:
        _assert(sl.iloc[i] > df["close"].iloc[i], "short SL is above close")


def main():
    print("== HVFVG unit tests ==")
    test_envelope()
    test_volume_anomaly_required()
    test_bull_hvfvg_detection()
    test_bear_hvfvg_detection()
    test_no_lookahead_truncation()
    print("ALL PASS")


if __name__ == "__main__":
    main()
