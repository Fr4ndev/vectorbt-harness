# Harness Vectorbt — Master Strategy Index

Reusable vectorbt backtesting harness that ports every strategy family from
`~/Escritorio/ICTdemon` into a common vectorized signal interface.

## How to run

```
# from harness root, using the ccxtv2 venv (vectorbt 0.28.4 / numpy 2.2.6)
~/Escritorio/ccxtv2/venv/bin/python run_backtest.py --family demon2:po3 --symbol BTC --tf 4h
~/Escritorio/ccxtv2/venv/bin/python run_backtest.py --family ictquantum:v11 --symbol ETH --tf 1h --json
~/Escritorio/ccxtv2/venv/bin/python run_backtest.py --sweep --family ictsuite --days 730
~/Escritorio/ccxtv2/venv/bin/python run_backtest.py --list
```

## Signal interface

Every signal module implements `compute(df, **params) -> dict` returning:

| key           | type     | meaning                                |
|---------------|----------|----------------------------------------|
| `entries`     | bool s   | long entry mask                        |
| `short_entries`| bool s   | short entry mask                       |
| `sl`          | float s  | absolute stop-loss price per signal    |
| `dir`         | +1/-1/0  | direction per bar                      |
| extras        | varies   | scores, sweeps, breakdowns             |

## Exit scheme (unified user spec)

- SL/TP always 1:2.
- 80% fills at TP1 (1:2); 20% runner runs to 1:5.
- SL moves to break-even after the 1:2 partial.
- Fees 0.0006, slippage 0.0003, init cash 10 000.

## Data

- Primary: Hyperliquid native REST (`type:"candleSnapshot"`, paginated), via
  `data/loader.py` with CSV caching.
- Fallback: generic ccxt (Binance/Bybit/OKX).
- Intervals: `1m,3m,5m,15m,30m,1h,2h,4h,1d,1w,1M`.

---

## Strategy families

### 1. demon1 — `signals/demon1/demon1.py` (`--family demon1`)
Liquidity Sweep 1H + Scalp OTE micro.
- **A. Liquidity Sweep 1H:** vol spike (1.5x) + displacement (>1.2 ATR) +
  HTF 4h z-bias alignment; SL 1%, RR 1:3.
- **B. Scalp OTE micro:** |z|>1.0 + price inside OTE fib 0.79–0.62.
- TF 1h entry / 4h bias.

### 2. demon2 — `signals/demon2/demon2.py` (`--family demon2:<id>`)
10 ICT sub-strategies. Entry/SL/TP risk sized per strategy:

| id | name | tf | entry logic | RR |
|----|------|----|-------------|----|
| `continuation_bias` | Continuation Bias + deviation | D+4h | close vs prev range, dev<33% | 1:3 |
| `po3` | Power of 3 (AMD) | D | manip low<prevL close>prevO; dev<35% | 1:5 |
| `power_flow` | Power Flow hierarchy (M>W>D) | D | monthly>weekly>daily sweep | bias |
| `weekly_bias` | Weekly extension (Tue/Wed) | D/W | 5-day min > prevW low, RR≥1 | fixed |
| `abc` | ABC retrace / Wave 3 | 4h | A down, B up, C 2x down; short only | 1:2 |
| `mmxm` | Market Maker Model (breaker) | 4h | breaker block + FVG (dead without breaker) | bias |
| `ote_tbr` | OTE 2.0 + TBR macro | 1h | displacement + price in OTE fib | 1:1 |
| `liquidity_trap` | Liquidity trap / breaker | 1h | sweep prior bar + close back | 1:3 |
| `ifvg` | Inversion FVG | 4h | close breaks FVG, inverts support/res | 1:3 |
| `silver_bullet` | Silver Bullet + Judas swing | 3m | sweep prior 4 + close back | 1:2 |

### 3. demon2volumen — `signals/demon2volumen/demon2volumen.py`
Same demon2 set plus institutional-volume gate (order-flow proxy from OHLCV
`volume`) + standalone short-only Liquidity Sweep bot:
- `liquidity_sweep_bot` — 4h short SFP of prior 10-bar swing high, SL above
  wick +0.1 ATR, RR 1:2. Use `use_volume_gate=True` to filter others.

### 4. ictquantum — `signals/ictquantum/ictquantum.py` (`--family ictquantum:v<ver>`)
Scoring engine. Direction = sweep direction (SSL→long, BSL→short). Score
crosses trigger → entry.

| version | active layers (max pts) | trigger |
|---------|-------------------------|---------|
| `v9`    | sweep, displacement, fvg, eth/btc (4) | ≥1 |
| `v9.5`  | + rejection, zscore (5.5)             | ≥1 |
| `v10`   | + killzone, inst levels (7)           | ≥2 |
| `v11`   | + fvg_bias, ob, smt, ms_shift, htf_alignment (11) | ≥2 |

SL = min low / max high of last 5 bars; TP = window Fib 0.618.
Needs `btc_df`/`eth_df` (SMT for v11, eth/btc for v9-v9.5) and optional
`htf_sweep_dir` for alignment.

### 5. ict4hsweep — `signals/ict4hsweep/ict4hsweep.py` (`--family ict4hsweep:<tier>`)
Sweep-tier family. Two-candle sweep (wick past prior candle level, close back)
gated by C1 deviation (`D <= H * DEV_LIMIT`, default 0.45). OTE-fib SL/TP,
score from tier base + MSS + RR + killzone.

| variant | tier base scores | SL |
|---------|------------------|-----|
| `v16` (default) | 1M 4.0 / 1d 3.0 / 4h 2.0 / 1h 1.0 | ATR x0.5 from swept wick |
| `death_cross` (`use_death_cross=True`) | adds 1W 3.5 (5 tiers) | 0.2% of price, EMA55/200 cross bias |

Tiers are passed as `tier=<tf>` — run per tier frame for a full multi-TF scan.

### 6. ictsuite — `signals/ictsuite/ictsuite.py` (`--family ictsuite:<name>`)
Agentic-suite extraction strategies:

| name | logic | rr |
|------|-------|----|
| `scalp_sweep` | 4h z-extreme (±2.0) + 1h single-candle sweep + OTE 0.62/0.705/0.79 | 1:2 |
| `intraday_quantum` | SMT (1.5) + displacement (1.0) + MSS (1.0), score≥2.5 | — |
| `macro_swing` | weekly z ±1.5 + daily MSB + 4h sweep; depth-bias required | 1:5 |
| `sfp` | swing failure (rejection > 50%) long/short | — |

### 7. fib_retrace — `signals/fib_retrace/fib_retrace.py` (`--family fib_retrace`)
Multi-TF Fibonacci retracement engine. Auto swing high/low defines the impulse
(range R), entries on tests/breaks of the 0.5/0.8 retracements with
close-confirmation, stop-invalidation -0.17/-0.27 symmetric beyond the swing,
TP extensions 1.17/1.27 and 0.5 partial (exposed as extras; the harness exit
scheme is applied on the strategy SL).
- Per-TF defaults for 1h/2h/4h/1d (`signals/fib_retrace/fib_retrace.py::TFS`).
- MTF confluence scoring: HTF bias alignment (`htf`), premium/discount vs HTF
  mid, impulse range vs ATR, volume expansion, session (London/NY). Entries
  gated by `min_confluence` and opposing-HTF block (`block_opposing`).
- Params: `swing_lookback` (pivot window), `entry_levels=[0.5,0.8]`,
  `invalidation=[0.17,0.27]` (tight for shallow / deep for 0.8-tested entries),
  `htf=["4h","1D"]`, `atr_mult=1.5`, `vol_mult=1.3`, `min_confluence`.

### 8. fvg_mtf — `signals/fvg_mtf/fvg_mtf.py` (`--family fvg_mtf:<ifvg|fvg>`)
Multi-TF FVG/inverse-FVG engine. 4h live-FVG presence sets the direction gate
(`bias4`); 1h FVG + killzone + gap size + volume add confluence; SL on the
trigger-bar extreme (ATR buffer) → real brackets.
- `ifvg` — inverse FVG 30m: price enters a live gap and closes back out of it
  (bear gap crossed back up → LONG, bull gap crossed back down → SHORT).
- `fvg`  — FVG pullback continuation: retest of a live gap that holds.
- Confluences 0..5, `min_confluence` gate (default 2; **strict 4** en 1h/4h),
  `require_4h_bias=True`,
  shift 1 bar (no lookahead). Default entry TF 30m (`tf:"30m"`); works on any
  entry frame (HTFs resampled internally, e.g. when swept at 1h/2h/4h/1d).
  `_infer_tf` deduce el TF real del dato (freq → mediana de `np.diff` en horas)
  para activar el gate estricto aunque el index no tenga `freq`.
- Verdicto del profit map (2026-09-02): **ifvg PROFITABLE +69.73% (7/8 celdas)**;
  fib_retrace, power_flow, fvg, po3, sfp → UNPROFITABLE; detalles en
  `reports/INFORME_PROFIT_MAP.md`.

---

## Profitability map

`run_profit_map.py` sweeps BTC+ETH × 1h/2h/4h/1d (1 year) for the families of
the backtest scope (fib_retrace, demon2:mmxm/po3/power_flow, fvg_mtf:ifvg/fvg,
ictsuite x4) and writes a per-strategy verdict:

```
~/Escritorio/ccxtv2/venv/bin/python run_profit_map.py
```
Outputs `reports/profit_map_<ts>.csv` (per-cell) and
`reports/verdict_<ts>.csv` (per-strategy verdict + mean return).

---

## Exits

- `portfolio/exits.py::build_brackets(entry, sl, direction)` → 80/20 two-leg
  brackets (tp1 1:2, tp2 1:5, sl→BE).
- `portfolio/engine.py::run(df, entries, short_entries, brackets, mode)`
  - `mode="simple"` — single full-position `from_signals`.
  - `mode="split"`  — simulates 80/20 partial+runner (leg_a/leg_b portfolios).

## Tests

```
~/Escritorio/ccxtv2/venv/bin/python tests/test_functional.py
```

Pulls real Hyperliquid data (default BTC 1h, 90 days) and runs a signal module
through `portfolio/engine.py`.