# INVENTARIO DE ESTRATEGIAS — Entry/Exit tal como están implementadas

Estado: **vivir en `~/Escritorio/harness_vectorbt`**. Cada estrategia es un módulo
que implementa `compute(df, **params) -> dict` con `entries`, `short_entries`,
`sl`, `dir`. Los exits se gestionan con el esquema unificado (abajo).

---

## Esquema de gestión de exits (unificado, aplicado por el engine)

| Regla | Valor |
|---|---|
| SL → TP1 | siempre 1:2 |
| Tamaño TP1 | 80% cierra en TP1 (1:2) |
| Runner | 20% restante a TP2 (1:5), SL salta a break-even tras TP1 |
| Fees | 0.0006 |
| Slippage | 0.0003 |
| Caja inicial | 10 000 |
| Tamaño | 1.0 (fraccional) |

Modos del engine: `simple` (posición completa 1 sola) o `split` (simula el
80/20 en dos portfolios leg_a/leg_b).

---

## 1. DEMON1 — `signals/demon1/demon1.py`

TF: 1h (bias HTF 4h via z-score Valeyre).

**A. Liquidity Sweep 1H**
- LONG: `low < recent_low` (máx 10 velas, shift 2) y cierre POR ENCIMA + vol espiga
  (`vol > avg_vol[20] × 1.5`) + displacement (`|close−open| > ATR14 × 1.2`) + bias HTF == 1.
- SHORT: `high > recent_high` y cierre POR DEBAJO + mismas confirmaciones + bias == −1.
- SL: `entry × (1 ∓ 0.01)` (sl_pct=0.01).
- Params: `vol_multiplier=1.5`, `displacement_atr=1.2`, `rr=3.0`, `lookback=20`, `recent_window=10`.

**B. Scalp OTE micro**
- LONG: `|z| > 1.0` + precio dentro OTE fib `[high−0.79·rango, high−0.62·rango]` + bias==1.
- SHORT: mirror + bias==−1.
- SL: `recent_low × 0.999` (LONG) / `recent_high × 1.001` (SHORT).
- Params: `z_period=50`, `z_strong=1.0`, `ote_lookback=25`, `ote_fib_lo=0.79`, `ote_fib_hi=0.62`.

---

## 2. DEMON2 — `signals/demon2/demon2.py`

### continuation_bias (D + ATR 4h)
- **LONG:** `close > prev_high` AND `dev_pct < 33%`.
- **SHORT:** `close < prev_low` AND `dev_pct < 33%`.
- `dev_pct = max(|prev_low−low|, |prev_high−high|) / (prev_high−prev_low) × 100`.
- SL: `entry ∓ ATR14_ewm × 0.5`. Fuente original RR 1:3 (TP en `entry ± ATR×1.5`).
- Confluencias: 3 (risk_unit 0.5%, prob_win 60%).

### po3 — Power of 3 AMD 2.0 (D)
- **LONG:** `low < prev_low` AND `close > prev_open` AND `dev_pct < 35%`
  (`dev_pct = |close−prev_open| / (prev_high−prev_low) × 100`).
- **SHORT:** `high > prev_high` AND `close < prev_open` AND `dev_pct < 35%`.
- SL: `entry ∓ (high−low)_actual × 0.3` (el `atr_d` es el rango de la vela actual).
- Fuente original RR 1:5. Confluencias: 4.

### power_flow — Jerarquía M>W>D (bias + SL ATR)
- Sweep bull: `low < prev_low AND close > prev_low`; sweep bear: `high > prev_high AND close < prev_high`.
- Prioridad: monthly (conf 5) → weekly (conf 4) → daily (conf 3).
- Devuelve dirección (bias) rehecha (ffill) al índice de la vela de entrada, con
  `atr_sl_mult=1.5` (SL ATR explícito). **Refutado por el profit map**: con SL
  pasa a −46.99 (el +107.88% inicial era exposición pasiva sin stop).

### weekly_bias — Extensión weekly (Tue/Wed UTC, sólo LONG)
- Gate: día = martes o miércoles UTC.
- LONG: `min(low[últimas 5D]) > prev_weekly_low × 1.005`.
- SL: `prev_weekly_low × 0.998`; TP fuente: `prev_weekly_high × 0.999` (require RR ≥ 1.0).
- `risk_unit` forzado a 0.5%. Confluencias: 3.

### abc — Retrace ABC / Wave 3 (4h, sólo SHORT)
- Patrón 4 velas: `close[−4] < close[−5]` (A) → `close[−3] > close[−4]` (B) →
  `close[−2] < close[−3] AND close[−1] < close[−2]` (C).
- SL: `high[−3]` (high de la vela B). TP fuente: riesgo × 2 (RR 1:2).
- Confluencias: 3; sube a 4 si `risk > ATR_prev × 2` (impulso).

### mmxm — Market Maker Model (4h)
- Requiere breaker block + FVG. **`enable_breaker=False` por defecto → nunca dispara** (fiel al
  código original, que tenía los breaker hardcodeados a 0). Actívalo con el detector real si quieres.

### ote_tbr — OTE 2.0 + TBR (1h)
- Displacement: `|close−open| > ATR14 × 2.0`.
- LONG: price dentro `[high−0.786·diff, high−0.618·diff]` (dif del impulso de 10 velas previas) + vela alcista.
- SHORT: mirror + vela bajista.
- SL: extremo del impulso (`low` LONG / `high` SHORT).
- Ventana TBR 9–13h UTC → confluencias 4 (si no, 3).

### liquidity_trap — Liquidity Trap / Breaker (1h)
- SHORT: `high > prev_high AND close < prev_high`; LONG: `low < prev_low AND close > prev_low`.
- SL: `entry ∓ ATR14 × 0.5`. Fuente RR 1:3. Confluencias: 4.

### ifvg — Inversion FVG (4h, RR 1:3)
- Para k en 2..4 (más reciente primero): SHORT si `close < under_gap_bottom.shift(k)`, LONG si `close > bull_gap_top.shift(k)`.
- SL: borde del gap roto (`bear_gap_top.shift(2)` / `bull_gap_bottom.shift(2)`).
- Confluencias: 3.

### silver_bullet — Silver Bullet + Judas Swing (3m)
- JUDAS (vs pool de 4 velas previas): LONG `low < prev_low AND close > prev_low`; SHORT `high > prev_high AND close < prev_high`.
- SL: `entry ∓ ATR14 × 1.5`. Fuente RR 1:2. Confluencias: 5 (máxima bonificación).
- ⚠ El filtro de sesión (London 07–08 / NY AM 14–15 / NY PM 18–19 UTC) **NO** está en la función — hay que gatearlo en el harness si se quiere fiel.

---

## 3. DEMON2VOLUMEN — `signals/demon2volumen/demon2volumen.py`

- Reusa las 10 de demon2 + overlay `volume_gate` (proxy acumulación/distribución desde `volume` OHLCV; la OB real es live-only).
- `liquidity_sweep_bot` (4h, SÓLO SHORT):
  - SHORT: `high > Rolling_Max_High` (10 velas, shift 1) AND `close < Rolling_Max_High` (fake-out).
  - SL: `high + ATR_SMA14 × 0.1`. Fuente RR 1:2. Confluencias: 5.

---

## 4. ICTQUANTUM — `signals/ictquantum/ictquantum.py` (scoring)

Dirección = dirección del sweep (SSL→LONG, BSL→SHORT) con regla 30%
(`dev ≤ 0.30 × rango previo`, si no es breakout) + confirmación
(`vol ≥ 1.3` OR `rq > 0.5`). Entra cuando `score ≥ trigger`.

| V (capas activas) | Puntos máx | trigger |
|---|---|---|
| `v9` sweep + displacement + fvg + eth/btc | 4 | ≥ 1 |
| `v9.5` + rejection + zscore | 5.5 | ≥ 1 |
| `v10` + killzone + inst_levels | 7 | ≥ 2 |
| `v11` + fvg_bias + ob + smt + ms_shift + htf_alignment | 11 | ≥ 2 |

- Detalles del score (v11): sweep +1, rejection>0.6 +0.5, displacement alineado +1,
  FVG cerca (<1%) +1, FVG alineado +0.5, OB cerca (<1.5%) +1, SMT +1, z-score +1,
  killzone +0.5/+1.0 (NY AM), inst-levels +0.5×2, MS-shift +1, HTF aligned +0.5 / conflicted −1.
- **SL:** `min(low[últimas 5])` (LONG) / `max(high[últimas 5])` (SHORT).
- **TP fuente:** Fib 0.618 de la ventana. Fallback `entry × 1.02 / 0.98`.
- Params: `sweep_lookback=15`, `vol_threshold=1.3`, `fvg_distance_pct=1.0`,
  `ob_distance_pct=1.5`, `z_period=50`, `fvg_max_lookback=30`.
- Requiere `btc_df`/`eth_df` (SMT en v11; eth/btc en v9-v9.5) y opcional `htf_sweep_dir`.

---

## 5. ICT4HSWEEP — `signals/ict4hsweep/ict4hsweep.py`

Sweep de 2 velas + gates C1/C2 + OTE-fib SL/TP + score.

- **Sweep:** LONG `low < prior.low AND close > prior.low`; SHORT `high > prior.high AND close < prior.high`.
- **C1 (dev):** penetración `D ≤ H × DEV_LIMIT` (0.45; si no, es breakout y se descarta).
- **C2 (timing):** en live evalúa cuándo ocurre el sweep dentro de la vela; en backtest se omite (passthrough).
- **SL:** v16 `swept_wick ∓ ATR14 × 0.5`; death-cross `precio × (1 ∓ 0.2%)`.
- **TP (OTE fib):** TP1 = `wick + H × 0.66`, TP2 = `0.705`, TP3 = `0.79` (dirección según LONG/SHORT).
- **Gate RR:** `RR(TP1) ≥ 1.4`. **Gate score:** `score ≥ 1.5`.
  score = tier_base + `(wick_quality>0.60)×0.5` + `(impulse_body>0.45)×0.5` + MS-shift×1 + RR×1 + killzone×0.5.
- Tier base: `1M 4.0 / 1d 3.0 / 4h 2.0 / 1h 1.0`; death-cross añade `1W 3.5`.
- Death-cross (variant): EMA55/200 en 5m → gancho bias + SL 0.2%.

---

## 6. ICTSUITE — `signals/ictsuite/ictsuite.py`

### scalp_sweep
- Bias 4h: `z ≤ −2.0` → LONG, `z ≥ +2.0` → SHORT (reversal en extremos).
- Confirmación 1h: sweep de la vela previa (LONG `low<prev_low & close>prev_low`; SHORT mirror).
- Entry: cierre dentro OTE ladder `[0.79, 0.62]` de la vela de sweep.
- SL: `low` del sweep (LONG) / `high` (SHORT). RR fuente 1:2.

### intraday_quantum
- score = SMT alineado ×1.5 + displacement ×1.0 + MS-shift ×1.0 → requiere `≥ 2.5`.
- SL: swing reciente (`recent_low` / `recent_high`).

### macro_swing
- Bias: `z semanal ≥ 1.5` + daily close > prev daily high (LONG); mirror SHORT.
- Entry: sweep 4h de la vela previa; requiere `depth_bias` (conviction ≥ 2) si se activa.
- SL: `low/high` del sweep. RR fuente 1:5.

### sfp — Swing Failure Pattern (4h)
- **SFP_SHORT:** `high > prev_high AND close < open AND close < prev_close AND (high−close)/rango × 100 > 50%`.
- **SFP_LONG:** `low < prev_low AND close > open AND close > prev_close AND (close−low)/rango × 100 > 50%`.
- SL: `low/high` de la vela. Nivel: `prev_low/prev_high`.

---

## 7. FIB_RETRACE — `signals/fib_retrace/fib_retrace.py`

Retracement Fibonacci multi-TF. El engine del harness aplica su esquema 1:2/1:5
sobre el SL de la estrategia; los niveles fib reales se exponen como extras.

- **Impulso** (`_impulse_series`): swing high/low automático (`indicators.core`
  `swing_highs_lows`). BULL = último swing low → último swing high; BEAR = último
  swing high → último swing low. Rango `R = H − L`. Válido solo cuando el par
  está completo y `H > L`, proyectado con `ffill` (causal).
- **LONG (impulso alcista):** `low ≤ H − R·0.5` OR `low ≤ H − R·0.8` (test/break)
  AND `close > level` (confirmación de cierre) AND impulso válido.
- **SHORT (impulso bajista):** `high ≥ L + R·0.5` OR `high ≥ L + R·0.8` AND
  `close < level` AND impulso válido.
- **SL / invalidación:** simétrico más allá del swing. Test superficial (solo
  0.5) → `L − 0.17R` (LONG) / `H + 0.17R` (SHORT); test profundo (alcanza 0.8) →
  `L − 0.27R` / `H + 0.27R`.
- **TP / partial (extras):** `partial = 0.5`, extensiones `1.17` / `1.27`
  (sobre el impulso). No se imponen al engine: el esquema unificado los deriva
  del SL.
- **Confluencia MTF (score 0..5), gate `min_confluence` (default 2):**
  1. Bias HTF alineado (`htf` = `["4h","1D"]` en 1h; `["1D","1W"]` en 4h) con
     `ffill` al frame de entrada.
  2. Discount: LONG con `close < mid HTF` (SHORT mirror).
  3. Impulso fuerte: `R > ATR14 × 1.5`.
  4. Expansión de volumen: `vol > sma20 × 1.3`.
  5. Sesión London/NY (killzone).
- `block_opposing=True` descarta entradas con HTF en contra. Todo el conjunto se
  shift 1 vela (sin lookahead: ejecución en la siguiente).
- **Defaults por TF** (`TFS`): 1h → swing 6; 2h → 5; 4h → 4; 1d → 3.
  `symbol=tf` auto-detectado desde el índice; override explícito por params.

---

## 8. FVG_MTF — `signals/fvg_mtf/fvg_mtf.py`

**30m gatillo, contexto 1h + 4h + sesión.** El 4h fija el bias; el 1h suma
confluencia. Variantes vía `strategy` (se registran como
`--family fvg_mtf:ifvg` / `fvg_mtf:fvg`).

- **Contexto 4h (`bias4`):** FVG vivo alcista reciente (rolling win=6 velas H4,
  `shift(1)` para no mirar la vela en formación) → bias +1; bajista → −1;
  ninguno → 0. Puerta dura si `require_4h_bias=True` (default).
- **Contexto 1h (`bias1`):** misma lógica (win=4 velas H1) → +1 confluencia
  (no gate).
- **Gatillo 30m** (edges FVG recién formados, lookback 30):
  - `ifvg` (inversión): LONG `low ≤ max_top_gap_bear` AND `close > max_top_gap_bear`
    (el gap bajista se cruza de vuelta arriba); SHORT mirror sobre
    `min_bottom_gap_bull`.
  - `fvg` (continuación): LONG `low ≤ max_top_gap_bull` AND `close > max_top_gap_bull`
    (pullback sobre FVG alcista que aguanta); SHORT mirror sobre
    `min_bottom_gap_bear`.
- **Score 0..5, gate `min_confluence` (default 2):** bias4 alineado + bias1
  alineado + killzone (London/NY `ic.session`) + `gap_width ≥ ATR14 × 0.5` +
  `vol > sma20 × 1.3`.
- **SL:** extremo de la vela gatillo ∓ `ATR14 × 0.5` (brackets 1:2/1:5 reales).
- Shift 1 vela (sin lookahead). HTFs resampleados internamente desde el frame
  de entrada → funciona también al barrer 1h/2h/4h/1d.

---

## Mapa de rentabilidad (`run_profit_map.py`)

Sweep BTC+ETH × 1h/2h/4h/1d (1 año) de las familias del alcance del usuario:
`fib_retrace`, `demon2:mmxm` (con `enable_breaker=True`), `demon2:po3`,
`demon2:power_flow`, `fvg_mtf:ifvg` / `fvg_mtf:fvg` y las 4 de `ictsuite`.
Emite `reports/profit_map_<ts>.csv` (por celda) y `reports/verdict_<ts>.csv`
(veredicto por estrategia: PROFITABLE/UNPROFITABLE según mean_return_pct > 0,
ratio de celdas rentables ≥ 50% y total de señales).

Veredicto 2026-09-02 (hardening activo): **fvg_mtf:ifvg PROFITABLE +69.73%**
(7/8 celdas); resto UNPROFITABLE (fib_retrace −53.94, power_flow −46.99 con SL,
fvg −24.01, po3 −57.42, sfp −58.32) o SIN SEÑALES (mmxm, scalp_sweep,
intraday_quantum, macro_swing). Detalle en `reports/INFORME_PROFIT_MAP.md`.

```
~/Escritorio/ccxtv2/venv/bin/python run_profit_map.py
```

---

## Cómo correr cada una

```
~/Escritorio/ccxtv2/venv/bin/python run_backtest.py --family <familia>:<estrategia>
  # ej: demon2:po3, ictquantum:v11, ict4hsweep:4h, ictsuite:sfp, demon1
~/Escritorio/ccxtv2/venv/bin/python run_backtest.py --list        # lista todas
~/Escritorio/ccxtv2/venv/bin/python run_backtest.py --sweep --family demon2   # toda la familia
```

Datos: Hyperliquid nativo (cached) por defecto; `--symbol --tf --days --exchange`.