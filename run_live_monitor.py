#!/usr/bin/env python
"""
run_live_monitor.py — Telegram live-monitor daemon for the validated fvg 4h config.

Config (IS +72.55 / OOS +24.68, n=16, one OOS eval):
    strategy=fvg | strict_tfs=("4h",) | strict_min_confluence=5 | gap_atr_mult=0.75
    exits  = STRICT (rr_tp1=2.0, rr_runner=3.0, weight_tp1=0.9)  [OOS-faithful]

Behavior:
    - Loops every SCAN_INTERVAL_MIN scanning BTC/ETH 4h with fresh HL data.
    - A fresh signal = entry on the current forming 4h candle (executed at its
      open), detected within MAX_AGE_HR of its candle start.
    - Sends the alert through ccxtv4/shared/telegram_sender.py (v4.0) with a
      15m chart, deduping on signal timestamp (state kept in reports/).
    - Startup sends a short "online" note to verify credentials.

Run from harness root:
    ~/Escritorio/ccxtv2/venv/bin/python run_live_monitor.py
    ~/Escritorio/ccxtv2/venv/bin/python run_live_monitor.py --once   # single pass
    ~/Escritorio/ccxtv2/venv/bin/python run_live_monitor.py --dry    # detect, no send
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, ".")
try:
    from dotenv import load_dotenv
    load_dotenv(Path.home() / "Escritorio/ccxtv4/.env")
except Exception:
    pass

# Reuse the ccxtv4 v4.0 Telegram dispatcher (no duplicated logic)
sys.path.insert(0, str(Path.home() / "Escritorio/ccxtv4"))
from shared.telegram_sender import get_telegram_sender

import numpy as np
import pandas as pd

from data import loader
from signals.fvg_mtf.fvg_mtf import compute

SYMBOLS = ["BTC", "ETH"]
TF = "4h"
TF_15M = "15m"
WARMUP_DAYS = 45
SCAN_INTERVAL_MIN = 5
MAX_AGE_HR = 4.0
SCAN_INTERVAL_S = SCAN_INTERVAL_MIN * 60
STATE_FILE = "reports/live_monitor_state.json"
LOG_FILE = "reports/live_monitor.log"

PARAMS = {
    "strategy": "fvg",
    "strict_tfs": ("4h",),
    "strict_min_confluence": 5,
    "gap_atr_mult": 0.75,
}
RR_TP1, RR_RUNNER, WEIGHT_TP1 = 2.0, 3.0, 0.9

log = logging.getLogger("live_monitor")


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout),
                  logging.FileHandler(LOG_FILE)],
    )


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception as e:
            log.warning("state unreadable (%s); starting fresh", e)
    return {"version": 2, "last_sent": {}}


def save_state(state: dict):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE_FILE)


def fmt(x):
    return f"{x:,.2f}" if pd.notna(x) else "—"


def detect_fresh(df: pd.DataFrame, now: pd.Timestamp) -> dict | None:
    """Return signal dict if the current forming candle holds a fresh entry."""
    sig = compute(df, **PARAMS)
    entries = sig["entries"].fillna(False).astype(bool)
    shorts = sig["short_entries"].fillna(False).astype(bool)
    sl = sig["sl"]
    conf = sig["confluences"]
    trail = sig["runner_inv"]

    last = df.index[-1]
    if not (entries.iloc[-1] or shorts.iloc[-1]):
        return None

    age = (now - last).total_seconds() / 3600.0
    if age > MAX_AGE_HR:
        log.info("%s entry on %s but candle %.1fh old — too stale to send",
                 df.name if hasattr(df, "name") else "sym", last, age)
        return None

    direction = "SHORT" if shorts.iloc[-1] else "LONG"
    d = -1 if direction == "SHORT" else 1
    entry = float(df["open"].loc[last])
    s = float(sl.loc[last])
    risk = abs(entry - s)
    tp1 = entry + d * risk * RR_TP1
    tp2 = entry + d * risk * RR_RUNNER
    conviction = float(conf.loc[last]) * 20.0
    inv = float(trail.loc[last]) if pd.notna(trail.loc[last]) else 0.0

    return {
        "direction": direction,
        "entry_bar": last,
        "age_hr": round(age, 2),
        "entry": entry,
        "sl": s,
        "tp1": tp1,
        "tp2": tp2,
        "conviction": conviction,
        "runner_inv": inv,
    }


def chart_df(asset: str) -> pd.DataFrame | None:
    try:
        df = loader.load(symbol=asset, timeframe=TF_15M, days=2, cache=False)
        return df.iloc[-64:] if len(df) > 10 else None
    except Exception as e:
        log.warning("chart fetch failed for %s: %s", asset, e)
        return None


def send_signal(sender, s: dict, chart: pd.DataFrame | None) -> bool:
    narrative = (
        f"FVG pullback 4h. Confluencia {s['conviction']:.0f}/100. "
        f"Perfil mc5+gap075 validado: IS +72.5% / OOS +24.7% (n=16, 2/2 celdas)."
    )
    sweep_level = s.get("runner_inv") or 0.0
    return await_send(
        sender, s["asset"], s["direction"], s["entry"], s["sl"],
        s["tp1"], s["tp2"], s["conviction"], narrative, chart, sweep_level,
    )


def await_send(sender, asset, direction, entry, sl, tp1, tp2, conviction,
               narrative, chart, sweep_level) -> bool:
    """Small asyncio wrapper around the async TelegramSender."""
    import asyncio

    async def _go():
        return await sender.send_signal(
            asset=asset, direction=direction, entry=entry, sl=sl,
            tp1=tp1, tp2=tp2, conviction=conviction, narrative=narrative,
            primary_tf="4h", fvg_type="FVG pullback", mss_type="4h bias",
            sweep_level=sweep_level, df_15m=chart,
        )

    return asyncio.run(_go())


async def _status(sender) -> bool:
    return await sender.send_text(
        "🛰️ *fvg 4h live-monitor ONLINE*\n"
        "Vigilando `BTC` y `ETH` 4h · pullback FVG (mc5 + gap075).\n"
        "Config validada: IS +72.5% / OOS +24.7% (n=16, 2/2).\n"
        "La próxima señal fresca se enviará automáticamente."
    )


def main():
    import asyncio
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="single scan pass")
    ap.add_argument("--dry", action="store_true", help="detect but do not send")
    ap.add_argument("--status", action="store_true", help="send online note")
    args = ap.parse_args()

    setup_logging()
    log.info("fvg 4h live-monitor starting (interval=%ds)", SCAN_INTERVAL_S)

    sender = get_telegram_sender()
    if not sender.enabled:
        log.warning("Telegram not configured (missing creds) — running dry.")

    state = load_state()

    if args.status:
        ok = asyncio.run(_status(sender))
        log.info("status message sent=%s", ok)
        return 0

    if args.once or args.dry:
        passes = 1
        if args.dry:
            log.info("dry-run: detect only, nothing sent")
    else:
        passes = None  # infinite

    n = 0
    try:
        while True:
            now = pd.Timestamp.utcnow().tz_localize(None).floor("min")
            for sym in SYMBOLS:
                try:
                    df = loader.load(symbol=sym, timeframe=TF, days=WARMUP_DAYS,
                                     cache=False)
                    if df.empty:
                        log.warning("%s 4h: empty dataset", sym)
                        continue
                    s = detect_fresh(df, now)
                    if s is None:
                        continue
                    s["asset"] = sym
                    key = f"{sym}:{s['direction']}:{s['entry_bar']}"
                    if state["last_sent"].get(key):
                        log.info("%s already sent (%s)", key, s["entry_bar"])
                        continue
                    log.info("FRESH SIGNAL %s %s @ %s (age %.2fh) entry=%s sl=%s "
                             "tp1=%s tp2=%s conv=%.0f",
                             sym, s["direction"], s["entry_bar"], s["age_hr"],
                             fmt(s["entry"]), fmt(s["sl"]), fmt(s["tp1"]),
                             fmt(s["tp2"]), s["conviction"])
                    if args.dry:
                        continue
                    chart = chart_df(sym)
                    ok = send_signal(sender, s, chart)
                    if ok:
                        state["last_sent"][key] = str(s["entry_bar"])
                        save_state(state)
                        log.info("sent to Telegram: %s", key)
                    else:
                        log.error("Telegram send FAILED for %s", key)
                except Exception as e:
                    log.exception("scan failed for %s: %s", sym, e)

            n += 1
            if passes is not None and n >= passes:
                break
            time.sleep(SCAN_INTERVAL_S)
    except KeyboardInterrupt:
        log.info("live-monitor stopped by user")


if __name__ == "__main__":
    raise SystemExit(main())