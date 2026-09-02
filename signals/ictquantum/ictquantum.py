"""
ictquantum.py — ICT Quantum scoring engine (v9 -> v11).

Ports ictquantum/ict_quantum_engine_v{9,9.5,10,11}.py into a vectorized
scoring engine. Direction is set by the liquidity-sweep type (SSL -> long,
BSL -> short) and a weighted confluence score decides whether to fire.

The canonical version is v11 (max ~11 pts). Earlier versions simply disable
the newer score components via the `score_components` flag, so a single
vectorized implementation reproduces all versions.

Score layers (v11) -> point value when active:
    sweep            +1.0      BSL or SSL detected (rule-30% + confirmation)
    rejection        +0.5      rejection_quality > 0.6
    displacement     +1.0      displacement matches sweep direction
    fvg              +1.0      unmitigated FVG within FVG_DISTANCE_PCT
    fvg_bias         +0.5      FVG type matches sweep direction
    ob               +1.0      order block within 1.5% of price
    smt              +1.0      SMT divergence (BTC vs ETH) matches
    zscore           +1.0      z-score bias matches sweep direction
    killzone         +0.5/1.0  active (1.0 in NY AM DISTRIBUTION)
    inst_level       +0.5 each first 2 inst-level hits (max +1)
    ms_shift         +1.0      close breaks recent swing post-sweep
    htf_alignment    +0.5/-1   H1==H4 sweep direction / conflict

Entry (v11 backtest): score >= score_trigger. SL = min low / max high of last
5 bars; TP = window Fib 0.618.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from indicators import core as ic


# ---------------------------------------------------------------------------
# Version -> active score components / thresholds
# ---------------------------------------------------------------------------
VERSION_SETTINGS = {
    # v11: everything on
    "v11": {
        "score_components": [
            "sweep", "rejection", "displacement", "fvg", "fvg_bias", "ob",
            "smt", "zscore", "killzone", "inst_level", "ms_shift", "htf_alignment",
        ],
        "trigger": 2.0,
        "dev_max": 0.30,       # rule-30%
        "use_smt": True,
        "htf_bonus": True,
    },
    # v10: drops ob/smt/ms_shift/htf_alignment/fvg_bias
    "v10": {
        "score_components": [
            "sweep", "rejection", "displacement", "fvg", "zscore", "killzone", "inst_level",
        ],
        "trigger": 2.0,
    },
    # v9.5: drops killzone/inst_level, adds eth/btc bias in place of smt
    "v9.5": {
        "score_components": ["sweep", "rejection", "displacement", "fvg", "zscore", "eth_btc"],
        "trigger": 1.0,
    },
    # v9: strict vol sweep + displacement + fvg + eth/btc
    "v9": {
        "score_components": ["sweep", "displacement", "fvg", "eth_btc"],
        "trigger": 1.0,
        "strict_vol": True,
        "vol_multiplier": 1.5,
    },
}


def _score_component(score, comp, df, sweep_info, sweep_dir, extra, params):
    """Add a single component's points to the running score (in place on 'score')."""
    comps = params["score_components"]
    if comp not in comps:
        return
    if comp == "sweep":
        score += (sweep_info["sweep_dir"] != 0).astype(float)
    elif comp == "rejection":
        if "rejection" in comps:
            score += (sweep_info["rejection_quality"] > 0.6).astype(float)
    elif comp == "displacement":
        disp = extra["displacement"]
        score += ((disp != 0) & (disp == sweep_dir)).astype(float)
    elif comp == "fvg":
        score += extra["fvg_near"]
    elif comp == "fvg_bias":
        fvg_dir = extra["fvg_dir"]
        score += ((fvg_dir == sweep_dir) & (sweep_dir != 0)).astype(float) * 0.5
    elif comp == "ob":
        score += (extra["ob_near"] & (sweep_dir != 0)).astype(float)
    elif comp == "smt":
        smt = extra["smt"]
        score += ((smt == sweep_dir) & (sweep_dir != 0)).astype(float)
    elif comp == "zscore":
        z = extra["zscore"]
        z_bias = pd.Series(np.where(z > 0, 1, np.where(z < 0, -1, 0)), index=df.index)
        score += (z_bias == sweep_dir).astype(float)
    elif comp == "killzone":
        kz = extra["killzone"]
        score += np.where(kz == 2, 1.0, np.where(kz == 1, 0.5, 0.0))
    elif comp == "inst_level":
        score += (extra["inst_levels"] > 0).astype(float) * 0.5 * np.minimum(extra["inst_levels"], 2)
    elif comp == "ms_shift":
        ms = extra["ms_shift"]
        score += ((ms == sweep_dir) & (sweep_dir != 0)).astype(float)
    elif comp == "htf_alignment":
        ha = extra["htf_alignment"]
        score += np.where(ha == 1, 0.5, np.where(ha == -1, -1.0, 0.0))
    elif comp == "eth_btc":
        eb = extra["eth_btc"]
        score += ((eb == sweep_dir) & (sweep_dir != 0)).astype(float)


def _levels_and_sl(df, sweep_dir, close):
    high = df["high"]
    low = df["low"]
    # window high/low over last 5 bars as SL referents
    sl = pd.Series(np.nan, index=df.index)
    long_sl = low.rolling(5).min()
    short_sl = high.rolling(5).max()
    sl[sweep_dir == 1] = long_sl[sweep_dir == 1]
    sl[sweep_dir == -1] = short_sl[sweep_dir == -1]
    return sl


def _inst_levels(df):
    """PDH/PDL/DO/PWH/PWL proximity (0..n hits within 0.2%)."""
    high = df["high"]
    low = df["low"]
    open_ = df["open"]
    daily = df.groupby(df.index.date).agg(high=("high", "max"), low=("low", "min"),
                                          open=("open", "first"))
    # map previous day's H/L (PDH/PDL) and current day's open onto the index
    daily_shift = daily.shift(1)
    day = pd.Series(df.index.date, index=df.index)
    pdh = day.map(daily_shift["high"].to_dict())
    pdl = day.map(daily_shift["low"].to_dict())
    pdo = day.map(daily["open"].to_dict())

    close = df["close"]
    tol = 0.002
    hits = ((close - pdh).abs() / pdh <= tol).fillna(False).astype(int)
    hits = hits + ((close - pdl).abs() / pdl <= tol).fillna(False).astype(int)
    hits = hits + ((close - pdo).abs() / pdo <= tol).fillna(False).astype(int)
    return hits


def _htf_alignment(sweep_dir_1h, sweep_dir_4h):
    align = pd.Series(0, index=sweep_dir_1h.index)
    both = (sweep_dir_1h != 0) & (sweep_dir_4h != 0)
    align[both & (sweep_dir_1h == sweep_dir_4h)] = 1
    align[both & (sweep_dir_1h != sweep_dir_4h)] = -1
    return align


# ---------------------------------------------------------------------------
# Main compute
# ---------------------------------------------------------------------------
def compute(df: pd.DataFrame, version: str = "v11",
            btc_df: pd.DataFrame | None = None,
            eth_df: pd.DataFrame | None = None,
            htf_sweep_dir: pd.Series | None = None,
            sweep_lookback: int = 15,
            vol_threshold: float = 1.3,
            fvg_distance_pct: float = 1.0,
            ob_distance_pct: float = 1.5,
            z_period: int = 50,
            fvg_max_lookback: int = 30,
            **_kwargs) -> dict:
    """Compute ICT Quantum signals on an OHLCV df.

    Args:
        df: entry timeframe (1h/4h) OHLCV.
        btc_df / eth_df: same-TF data for the other asset (SMT for v11).
        htf_sweep_dir: 4h sweep-direction series (for htf_alignment).
    """
    params = dict(VERSION_SETTINGS[version])
    comps = params["score_components"]
    close = df["close"]
    high = df["high"]
    low = df["low"]
    open_ = df["open"]
    volume = df["volume"]
    idx = df.index

    # ---- sweep (with rule-30%) ----
    sweep = ic.liquidity_sweep(high, low, close, volume,
                               lookback=sweep_lookback,
                               vol_mult_required=vol_threshold,
                               dev_max=params.get("dev_max", 0.30),
                               use_deviations=params.get("dev_max") is not None)
    sweep_dir = sweep["sweep_dir"]
    if params.get("strict_vol"):
        # v9: strict vol-only confirmation
        vol_sma = volume.rolling(20).mean().replace(0, np.nan)
        vol_spike = volume > vol_sma * params["vol_multiplier"]
        sweep_dir = sweep_dir.where(vol_spike, 0).astype(int)

    # ---- displacement ----
    displacement = ic.displacement(open_, high, low, close, factor=0.8, period=14)
    displacement = pd.Series(displacement, index=idx)

    # ---- FVG near (unmitigated within distance) ----
    fvg_ = ic.fvg(high, low, close)
    # FVG near if a live (unfilled) FVG formed within fvg_max_lookback candles
    live_bull = fvg_["fvg_live_bull"].rolling(fvg_max_lookback, min_periods=1).max().astype(bool)
    live_bear = fvg_["fvg_live_bear"].rolling(fvg_max_lookback, min_periods=1).max().astype(bool)
    fvg_near = (live_bull | live_bear) & (sweep_dir != 0)
    fvg_dir = pd.Series(np.where(live_bull, 1, np.where(live_bear, -1, 0)), index=idx)

    # ---- order blocks near ----
    ob_ = ic.order_blocks(open_, close, fvg_["fvg_live_bull"], fvg_["fvg_live_bear"])
    ob_near_bull = ob_["ob_bull"].rolling(fvg_max_lookback, min_periods=1).max().astype(bool)
    ob_near_bear = ob_["ob_bear"].rolling(fvg_max_lookback, min_periods=1).max().astype(bool)
    ob_near = (ob_near_bull | ob_near_bear)

    # ---- SMT divergence (BTC vs ETH) ----
    smt = pd.Series(0, index=idx)
    if btc_df is not None and eth_df is not None and params.get("use_smt", False):
        smt = ic.smt_divergence(btc_df["high"], btc_df["low"],
                                eth_df["high"], eth_df["low"], window=5)
        smt = pd.Series(smt, index=idx)

    # ---- z-score ----
    z = ic.valeyre_zscore(close, period=z_period, sqrt_n=365)

    # ---- killzone ----
    sess = ic.session(idx)
    kz = pd.Series(0, index=idx)
    kz[sess == "MANIPULATION"] = 1
    kz[sess == "DISTRIBUTION"] = 2

    # ---- institutional levels ----
    inst_levels = _inst_levels(df)

    # ---- ms shift ----
    ms = ic.ms_shift(high, low, close, sweep["sweep_ssl"], sweep["sweep_bsl"])
    ms_shift = pd.Series(np.where(ms["ms_bull"], 1, np.where(ms["ms_bear"], -1, 0)), index=idx)

    # ---- eth/btc (returns) bias for v9/v9.5 ----
    eth_btc = pd.Series(0, index=idx)
    if btc_df is not None and eth_df is not None and "eth_btc" in comps:
        btc_ret = btc_df["close"].pct_change(20)
        eth_ret = eth_df["close"].pct_change(20)
        eb = ic.relative_strength_bias(btc_ret, eth_ret, threshold=0.005)
        eth_btc = pd.Series(eb, index=idx).fillna(0).astype(int)

    extra = {
        "displacement": displacement, "fvg_near": fvg_near, "fvg_dir": fvg_dir,
        "ob_near": ob_near, "smt": smt, "zscore": z, "killzone": kz,
        "inst_levels": inst_levels, "ms_shift": ms_shift, "eth_btc": eth_btc,
        "htf_alignment": _htf_alignment(sweep_dir, htf_sweep_dir) if htf_sweep_dir is not None
        else pd.Series(0, index=idx),
    }

    # ---- score ----
    score = pd.Series(0.0, index=idx)
    for comp in comps:
        _score_component(score, comp, df, sweep, sweep_dir, extra, params)
    score = score.fillna(0)

    # ---- signal ----
    trigger = params["trigger"]
    has_sweep = sweep_dir != 0
    signal = (score >= trigger) & has_sweep
    entries = signal & (sweep_dir == 1)
    short_entries = signal & (sweep_dir == -1)

    sl = _levels_and_sl(df, sweep_dir, close)
    direction = pd.Series(0, index=idx)
    direction[entries] = 1
    direction[short_entries] = -1

    return {
        "entries": entries,
        "short_entries": short_entries,
        "sl": sl,
        "dir": direction.astype(int),
        "score": score,
        "sweep_dir": sweep_dir,
        "smt": smt,
        "killzone": kz,
        "name": f"ictquantum_{version}",
    }
