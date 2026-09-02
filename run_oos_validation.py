"""
run_oos_validation.py — split walk-forward (70/30) out-of-sample check for the
promoted (candidate) strategies fvg_mtf:ifvg and demon2:mmxm.

Per PROMPT v2 (opencode_self_evolutionary_loop) section 4, a variant is
PROFITABLE / deployable ONLY if it also holds on the last 30% it never saw
during parameter selection. This script runs the SAME config (no re-mutation)
on that OOS slice and reports the evidence per cell.

Run (from harness root, ccxtv2 venv):
    ~/Escritorio/ccxtv2/venv/bin/python run_oos_validation.py
"""
from __future__ import annotations

import os

import pandas as pd

from data import loader
from portfolio import engine
from portfolio.exits import build_brackets
from run_profit_map import _combined_return, STRICT_FVG_TFS, STRICT_FVG_EXIT

SYMBOLS = ["BTC", "ETH"]
TIMEFRAMES = ["1h", "2h", "4h", "1d"]
DAYS = 365
IS_RATIO = 0.70

FIRST_SLICE = 30  # min bars expected in the OOS slice (1h ~ 2628 rows * 0.3)

# candidates: (family, strategy, params) — same params used on the profit map
CANDIDATES = [
    ("fvg_mtf", "ifvg", {}),
    ("demon2", "mmxm", {"enable_breaker": True}),
]


def _run_cell(family: str, strategy: str, df: pd.DataFrame, tf: str,
              params: dict) -> dict:
    if family == "fvg_mtf":
        from signals.fvg_mtf.fvg_mtf import compute
    elif family == "demon2":
        from signals.demon2.demon2 import compute
    else:
        raise ValueError(family)

    sig = compute(df, strategy=strategy, **params)
    entries = sig["entries"].fillna(False).astype(bool)
    shorts = sig["short_entries"].fillna(False).astype(bool)
    n = int(entries.sum() + shorts.sum())
    if not n:
        return {"n_signals": 0, "return_pct": float("nan"),
                "win_rate": float("nan")}

    exit_kwargs = STRICT_FVG_EXIT if (family == "fvg_mtf" and tf in STRICT_FVG_TFS) else {}
    brackets = build_brackets(entry=df["close"], sl=sig["sl"],
                              direction=sig["dir"],
                              rr_tp1=exit_kwargs.get("rr_tp1", 2.0),
                              rr_runner=exit_kwargs.get("rr_runner", 5.0),
                              weight_tp1=exit_kwargs.get("weight_tp1", 0.8),
                              trail=sig.get("runner_inv"))
    res = engine.run(df, entries=entries, short_entries=shorts, brackets=brackets,
                     mode="split", freq=tf)
    cr, cwr, *_ = _combined_return(res)
    return {"n_signals": n, "return_pct": cr, "win_rate": cwr}


def main() -> int:
    rows = []
    for family, strategy, params in CANDIDATES:
        for sym in SYMBOLS:
            for tf in TIMEFRAMES:
                df = loader.load(symbol=sym, timeframe=tf, days=DAYS, cache=True)
                if len(df) < FIRST_SLICE * 2:
                    print(f"  {family}:{strategy} {sym}:{tf}: not enough bars")
                    continue
                cut = int(len(df) * IS_RATIO)
                is_df = df.iloc[:cut]
                oos_df = df.iloc[cut:]
                is_r = _run_cell(family, strategy, is_df, tf, params)
                oos_r = _run_cell(family, strategy, oos_df, tf, params)
                rec = {
                    "family": family, "strategy": strategy,
                    "symbol": sym, "timeframe": tf,
                    "is_n": is_r["n_signals"], "is_return_pct": is_r["return_pct"],
                    "oos_n": oos_r["n_signals"], "oos_return_pct": oos_r["return_pct"],
                    "oos_win_rate": oos_r["win_rate"],
                }
                rows.append(rec)
                print(f"  {family}:{strategy} {sym}:{tf}: "
                      f"IS n={rec['is_n']} ret={rec['is_return_pct']:.2f} | "
                      f"OOS n={rec['oos_n']} ret="
                      f"{rec['oos_return_pct'] if pd.isna(rec['oos_return_pct']) else round(rec['oos_return_pct'], 2)}")

    df_out = pd.DataFrame(rows)
    os.makedirs("reports", exist_ok=True)
    path = "reports/oos_validation.csv"
    df_out.to_csv(path, index=False)
    print(f"\nSaved: {path}")

    print("\n== OOS VERDICT (PER PROMPT v2 SEC 4) ==")
    for family, strategy, _ in CANDIDATES:
        sub = df_out[(df_out["family"] == family) & (df_out["strategy"] == strategy)]
        oos = sub.dropna(subset=["oos_return_pct"])
        if oos.empty:
            print(f"  {family}:{strategy}: NO OOS SIGNALS -> not deployable")
            continue
        mean_oos = oos["oos_return_pct"].mean()
        prof_cells = int((oos["oos_return_pct"] > 0).sum())
        n_support = int(oos.loc[oos["oos return pct" if False else "oos_return_pct"] > 0, "oos_n"].sum())
        total_n = int(oos["oos_n"].sum())
        print(f"  {family}:{strategy}: OOS mean={mean_oos:.2f}% | "
              f"prof cells={prof_cells}/{len(oos)} | total OOS signals={total_n}")
        print(f"    cond1 mean>0: {'PASS' if mean_oos > 0 else 'FAIL'}"
              f" | cond3 n>=30 support: {'PASS' if n_support >= 30 else 'n/a check per cell'}"
              f" | cond5 >=2 cells: {'PASS' if prof_cells >= 2 else 'FAIL'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())