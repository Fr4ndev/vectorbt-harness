"""
hvfvg_ifvg.py — Inversion FVG (IFVG) with Multi-TimeFrame filter.

Evolves `hvfvg` from direct limit entries into a change-of-structure (CoS)
confirmation engine: a mitigated FVG transforms into an Inversion FVG whose
retest triggers the entry, gated by a macro HTF bias (4h/2h).

Inversion definition (user spec):
    - Bullish FVG mitigated/fallen (a later close < fvg_low): the zone is NOT
      removed — it inverts into a Bearish IFVG (old support -> resistance).
    - Bearish FVG mitigated (a later close > fvg_high): inverts into a Bullish
      IFVG (old resistance -> support).
    - Entry fires on a retest of the inverted zone in the direction of the new
      bias.

Multi-TimeFrame (HTF 4h/2h bias -> LTF 30m execution):
    - Macro bias is derived by resampling the LTF frame up to 4h and 2h and
      reading live-FVG direction presence (causal, shifted 1 HTF bar).
    - A 30m IFVG retest aligned with the HTF bias is the execution trigger.
    - `require_htf`: hard gate (default True) — longs only on bullish HTF bias,
      shorts only on bearish.

Signal envelope (compute) returns entries/short_entries/sl/dir + tp1/tp2 (ERL
swing or ATR fallback) so the runner can use All-In exits.

Causal: FVG formation at candle i, mitigation observed forward, retest fires the
signal at bar t, and the envelope is shifted 1 bar (execution at next open).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from indicators import core as ic
from .hvfvg import _swing_pivots


def _infer_tf(index: pd.DatetimeIndex) -> str:
    freq = getattr(index, "freq", None)
    freq = str(freq.freqstr if freq is not None else "")
    if freq == "30min":
        return "30m"
    hours = np.median(np.diff(index.asi8)) / 3.6e12 if len(index) >= 2 else 0
    if hours <= 0.75:
        return "30m"
    return "30m"


def _resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    return pd.DataFrame({
        "open": df["open"].resample(rule).first(),
        "high": df["high"].resample(rule).max(),
        "low": df["low"].resample(rule).min(),
        "close": df["close"].resample(rule).last(),
        "volume": df["volume"].resample(rule).sum(),
    }).dropna()


def _htf_bias(frame: pd.DataFrame, rule: str, presence_window: int = 12) -> pd.Series:
    """Macro bias from live-FVG presence on an HTF (bull +1 / bear -1 / 0).

    Causal: shifted 1 HTF bar, rolled over `presence_window`, ffill to the LTF
    entry index. `require_htf` gates entry direction on this.
    """
    htf = _resample(frame, rule)
    f = ic.fvg(htf["high"], htf["low"], htf["close"], lookback=30)
    bull = f["fvg_live_bull"].shift(1).rolling(presence_window, min_periods=1).max()
    bear = f["fvg_live_bear"].shift(1).rolling(presence_window, min_periods=1).max()
    dir_s = pd.Series(
        np.select([(bull > 0) & (bear <= 0), (bear > 0) & (bull <= 0)],
                  [1, -1], default=0),
        index=htf.index,
    )
    return dir_s.reindex(frame.index, method="ffill").fillna(0)


def _collect(entries, shorts, sl, direction, extra=None, name="hvfvg_ifvg"):
    direction = direction.astype(int)
    direction[entries | shorts] = np.where(entries, 1, -1)[entries | shorts]
    out = {
        "entries": entries.astype(bool),
        "short_entries": shorts.astype(bool),
        "sl": sl,
        "dir": direction,
        "name": name,
    }
    if extra:
        out.update(extra)
    return out


def compute(df: pd.DataFrame, **params) -> dict:
    """IFVG + HTF-bias signal envelope (see module docstring)."""
    high = df["high"]
    low = df["low"]
    close = df["close"]
    volume = df["volume"]
    open_ = df["open"]
    n = len(df)

    # ---- params ----
    htf_rules = params.get("htf_rules", ("4h", "2h"))     # macro bias frames
    presence_window = int(params.get("presence_window", 12))
    require_htf = params.get("require_htf", True)         # hard bias gate
    htf_mode = params.get("htf_mode", "either")           # 'both' | 'either'
    atr_sl_mult = float(params.get("atr_sl_mult", 0.8))
    tp_atr_mult = float(params.get("tp_atr_mult", 2.0))
    retest_max = int(params.get("retest_max", 48))        # forward scan window
    swing_window = int(params.get("swing_window", 5))

    atr_ = ic.atr(high, low, close, period=14)

    # Precompute swing pivots ONCE (O(n)); avoid recomputing inside the loop.
    sw_h, sw_l = _swing_pivots(high, low, swing_window)
    sw_h_vals = high.where(sw_h).dropna().to_numpy()
    sw_l_vals = low.where(sw_l).dropna().to_numpy()

    def _erl(impulse_end, direction, fallback):
        if direction == 1:
            cand = sw_h_vals[sw_h_vals > impulse_end * 1.001]
            return (float(cand.min()), "swing_high") if len(cand) else (fallback, "fallback_atr")
        else:
            cand = sw_l_vals[sw_l_vals < impulse_end * 0.999]
            return (float(cand.max()), "swing_low") if len(cand) else (fallback, "fallback_atr")

    # ---- 1. FVG formation on the LTF (candle i) ----
    bull_form = (low > high.shift(2)).fillna(False).to_numpy()
    bear_form = (high < low.shift(2)).fillna(False).to_numpy()
    bull_gap_low = high.shift(2).to_numpy()   # bottom
    bull_gap_high = low.to_numpy()            # top
    bear_gap_low = high.to_numpy()            # bottom
    bear_gap_high = low.shift(2).to_numpy()   # top

    c_close = close.to_numpy()
    c_low = low.to_numpy()
    c_high = high.to_numpy()
    c_atr = atr_.to_numpy()

    entry_sig = np.zeros(n, dtype=bool)
    short_sig = np.zeros(n, dtype=bool)
    sl_levels = np.full(n, np.nan)
    tp1_levels = np.full(n, np.nan)
    tp2_levels = np.full(n, np.nan)
    entry_price = np.full(n, np.nan)
    erl_kind = np.array([""] * n, dtype=object)

    # Each gap is identified by its formation index -> we forward-scan candidates
    # Iterate over formation candles (sparse) so the inner scan is cheap.
    # For each bullish FVG we look for a later CLOSE BELOW its low => inversion.
    for i in range(2, n):
        if not (bull_form[i] or bear_form[i]):
            continue
        if bull_form[i]:
            gl, gh = bull_gap_low[i], bull_gap_high[i]
        else:
            gl, gh = bear_gap_low[i], bear_gap_high[i]
        if not (np.isfinite(gl) and np.isfinite(gh)) or gh <= gl:
            continue
        # Mitigation (transformation) point:
        #   bullish FVG  -> inverted by a close BELOW gl  => becomes Bearish IFVG
        #   bearish FVG  -> inverted by a close ABOVE gh => becomes Bullish IFVG
        if bull_form[i]:
            inv_dir = -1           # Bearish IFVG; inverted support-zone = [gl,gh]
            mitig = c_close < gl
        else:
            inv_dir = 1            # Bullish IFVG; inverted support-zone = [gl,gh]
            mitig = c_close > gh

        end = min(i + 1 + retest_max, n)
        retreated = False
        emit_at = -1
        for t in range(i + 1, end):
            if mitig[t]:
                retreated = True     # the old zone is gone -> inverted
                break
        if not retreated:
            continue
        # Now scan forward for a RETEST of the inverted zone in the new direction:
        #   Bearish IFVG (inv_dir=-1): price rallies into [gl,gh] then closes back
        #        below gl -> SHORT.
        #   Bullish IFVG (inv_dir=+1): price dips into [gl,gh] then closes back
        #        above gh -> LONG.
        start = t + 1
        for t2 in range(start, end):
            if inv_dir == -1:
                touches = c_high[t2] >= gl and c_low[t2] <= gh
                if touches and c_close[t2] < gl:
                    short_sig[t2] = True
                    emit_at = t2
                    break
            else:
                touches = c_low[t2] <= gh and c_high[t2] >= gl
                if touches and c_close[t2] > gh:
                    entry_sig[t2] = True
                    emit_at = t2
                    break

        if emit_at < 0:
            continue
        t = emit_at
        direction = inv_dir
        if direction == 1:
            _entry = gl + 0.5 * (gh - gl)
            _sl = gl - c_atr[t] * atr_sl_mult
        else:
            _entry = gh - 0.5 * (gh - gl)
            _sl = gh + c_atr[t] * atr_sl_mult

        # ERL/ATR native TP for All-In exits
        impulse_end = c_close[i - 1]
        fallback_tp = _entry + c_atr[t] * tp_atr_mult if direction == 1 \
            else _entry - c_atr[t] * tp_atr_mult
        erl, erl_kind_str = _erl(impulse_end, direction, fallback_tp)
        erl = erl if direction == 1 else min(erl, _entry)

        entry_price[t] = _entry
        sl_levels[t] = _sl
        tp1_levels[t] = erl
        tp2_levels[t] = erl
        erl_kind[t] = erl_kind_str

    # ---- HTF bias gate ----
    bias = None
    for rule in htf_rules:
        b = _htf_bias(df, rule, presence_window=presence_window)
        bias = b if bias is None else bias
    if bias is None:
        bias = pd.Series(0, index=df.index)
    if require_htf:
        entry_sig = pd.Series(entry_sig, index=df.index) & (bias > 0)
        short_sig = pd.Series(short_sig, index=df.index) & (bias < 0)

    # ---- shift 1 bar (no lookahead: execution next open) ----
    long_entry = pd.Series(entry_sig, index=df.index).shift(1, fill_value=False).astype(bool)
    short_entry = pd.Series(short_sig, index=df.index).shift(1, fill_value=False).astype(bool)

    sl_out = pd.Series(np.nan, index=df.index)
    tp1_out = pd.Series(np.nan, index=df.index)
    tp2_out = pd.Series(np.nan, index=df.index)
    entry_out = pd.Series(np.nan, index=df.index)
    erlkind_out = pd.Series("", index=df.index)
    sl_out[long_entry] = pd.Series(sl_levels, index=df.index).shift(1)[long_entry]
    sl_out[short_entry] = pd.Series(sl_levels, index=df.index).shift(1)[short_entry]
    tp1_out[long_entry] = pd.Series(tp1_levels, index=df.index).shift(1)[long_entry]
    tp1_out[short_entry] = pd.Series(tp1_levels, index=df.index).shift(1)[short_entry]
    tp2_out[long_entry] = pd.Series(tp2_levels, index=df.index).shift(1)[long_entry]
    tp2_out[short_entry] = pd.Series(tp2_levels, index=df.index).shift(1)[short_entry]
    entry_out[long_entry | short_entry] = pd.Series(entry_price, index=df.index).shift(1)[long_entry | short_entry]
    erlkind_out[long_entry | short_entry] = pd.Series(erl_kind, index=df.index).shift(1)[long_entry | short_entry]

    extras = {
        "tp1": tp1_out,
        "tp2": tp2_out,
        "entry": entry_out,
        "erl_kind": erlkind_out,
        "bias_htf": bias.astype(int),
        "atr": atr_,
    }
    return _collect(long_entry, short_entry, sl_out, pd.Series(0, index=df.index),
                    extras, name="hvfvg_ifvg")
