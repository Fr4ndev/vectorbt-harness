# Informe de Rentabilidad — Mapa BTC+ETH, 1 año (1h/2h/4h/1d)

Fecha: 2026-09-02 · Harness: `~/Escritorio/harness_vectorbt` · Runtime: venv ccxtv2
**Actualización OOS (70/30 walk-forward): ver sección al final — los dos
verdictos "PROFITABLE" in-sample (ifvg, mmxm) NO sobreviven la muestra OOS.
Ninguna estrategia es desplegable hoy.**
Fuente de datos: Hyperliquid nativo paginado (caché en `data/cache/`).
Exits: esquema unificado (80% TP1 1:2, 20% runner 1:5, SL→BE; fees 0.0006,
slippage 0.0003, cash 10 000).
Hardening ifvg: `strict_min_confluence=4` en TFs estrictos (1h/4h) + runner
`rr_runner=3.0` / `weight_tp1=0.9` en esas celdas (default 2 en el resto).
Trailing invalidation: `runner_inv` (FVG 4h opuesto, `trail_4h=True`) activo en
ifvg/fvg — el runner se ancla al borde del FVG 4h contrario en lugar de a una
ratio fija.

## Veredicto por estrategia — in-sample (run final 20260902_105952, post-revert po3_fractal)

| Estrategia | Veredicto | Media ret % | Celdas rentables | Celdas | Señales |
|---|---|---|---|---|---|
| fvg_mtf:ifvg | **PROFITABLE (IS) → FALLO OOS** | **+79.81** | **7** | 8 | 560 |
| demon2:mmxm (breaker + SL ATR) | **PROFITABLE (IS) → FALLO OOS** | **+38.97** | **5** | 8 | 382 |
| fvg_mtf:fvg | UNPROFITABLE | −16.81 | 3 | 8 | 2 122 |
| demon2:po3_fractal | UNPROFITABLE | −2.03 | 3 | 8 | 38 |
| ictsuite:sfp_institutional | UNPROFITABLE | −1.34 | 2 | 8 | 32 |
| demon2:power_flow | UNPROFITABLE | −46.99 | 0 | 8 | 18 079 |
| fib_retrace | UNPROFITABLE | −53.94 | 0 | 8 | 2 718 |
| demon2:po3 | UNPROFITABLE | −57.42 | 1 | 8 | 2 118 |
| ictsuite:sfp | UNPROFITABLE | −58.32 | 0 | 8 | 5 586 |
| ictsuite:scalp_sweep | SIN SEÑALES | 0.0 | — | 8 | 0 |
| ictsuite:intraday_quantum | SIN SEÑALES | 0.0 | — | 8 | 0 |
| ictsuite:macro_swing | SIN SEÑALES | 0.0 | — | 8 | 0 |

## Detalle fvg_mtf:ifvg por celda (trail activo, hardening activo)

| Celda | Ret % | n | Leg A ret % | Leg B ret % | WinRate leg A % |
|---|---|---|---|---|---|
| BTC 1h | **+16.1** | 42 | +23.4 | −12.8 | 57.7 |
| BTC 2h | +66.1 | 200 | +68.7 | +55.6 | 44.1 |
| BTC 4h | **+465.6** | 46 | +510.1 | +287.7 | 51.5 |
| BTC 1d | +63.3 | 19 | +76.9 | +9.1 | 36.4 |
| ETH 1h | −3.6 | 40 | −3.1 | −5.6 | 33.3 |
| ETH 2h | +12.6 | 153 | +15.2 | +1.8 | 42.2 |
| ETH 4h | +11.6 | 39 | +12.3 | +8.6 | 52.0 |
| ETH 1d | +6.8 | 21 | +9.5 | −4.1 | 60.0 |

## Detalle demon2:mmxm por celda (SL real ATR×1.5, breaker ON)

| Celda | Ret % | n | WinRate leg A % |
|---|---|---|---|
| BTC 1h | **+83.0** | 90 | 39.0 |
| BTC 2h | **+164.7** | 56 | 52.1 |
| BTC 4h | −46.6 | 33 | 25.9 |
| BTC 1d | **+124.0** | 6 | 40.0 |
| ETH 1h | −4.9 | 86 | 29.4 |
| ETH 2h | +2.2 | 67 | 37.0 |
| ETH 4h | −10.7 | 38 | 23.3 |
| ETH 1d | +0.1 | 6 | 20.0 |

## Estrategias nuevas (fase 2) — estado

- **`demon2:po3_fractal`**: con defaults originales restaurados
  (acc_range 0.0030 / judas_window 10 / ms_lookback 5 / killzones ON) dispara 38
  señales (run 105952) — el bake de `ee3681a` (acc 0.006/ms 10/killzone off) era
  ruido de n=7 y se revirtió. Por celda: BTC 1h −56.4 (12), 2h −72.0 (6), 4h
  **+109.2** (7), 1d n=0; ETH 1h −0.1 (8), 2h +0.8 (2), 4h +2.2 (3), 1d n=0.
  Media **−2.03, 3/8**. Con n=38 hay muestra mínima pero sigue sin edge claro →
  UNPROFITABLE mecánico, a vigilar con más core / calibración del Judas Swing.
- **`ictsuite:sfp_institutional`**: 32 señales. BTC 1h +4.28 / 2h −11.83 / 4h +4.01
  (1d 0); ETH −1.31 / −2.94 / −2.96 (1d 0). Marginalmente positivo en BTC 1h/4h,
  negativo en el resto → de momento **sin edge claro**, pero muy por delante del
  `sfp` clásico (−58.32) al que sustituye.

## Evolución del hardening (mapa completo, misma data)

| Run | Configuración | Media ret % | Celdas rentables | BTC 1h | BTC 4h |
|---|---|---|---|---|---|
| 092636 | sin strict (freq=None → mc=2) | +42.26 | 6/8 | −103.3 | +287.3 |
| 093120 | strict mc=3 (inferencia de TF corregida) | +50.47 | 6/8 | −70.9 | +318.2 |
| 093533 | strict mc=4 (sin trail) | +69.73 | 7/8 | +14.0 | +387.6 |
| **100004** | **strict mc=4 + trail runner + fixes** | **+79.81** | **7/8** | **+16.1** | **+465.6** |

El run 100004 es el final de la fase 2. Incluye además: fix `_trail` del runner
(las 8 celdas de `fib_retrace` fallaban en el run 095843 con `local variable
'_trail' referenced before assignment` — tp nativos y trail genérico en la misma
rama) y SL real ATR×1.5 en `mmxm` (el +100.08% previo era exposición pasiva con
`sl=NaN`, mismo artefacto que power_flow).

## Lectura

- **IMPORTANTE: las medias "PROFITABLE" de abajo son in-sample.** La validación
  OOS 70/30 (sección final) concluye que **ifvg y mmxm NO sobreviven fuera de
  muestra** → hoy ninguna estrategia pasa las 5 condiciones de la sección 4 del
  prompt y **no hay nada desplegable a Telegram ni a `estrategias_produccion/`**.
- **Única familia de peso rentable en IS: `fvg_mtf:ifvg` (+79.81%, 7/8)**. El
  trail anclado al FVG 4h opuesto añade ~10 puntos sobre el hardening sin trail
  (+69.73): BTC 4h 387.6 → 465.6 y BTC 1h 14.0 → 16.1. La única celda negativa
  es ETH 1h (−3.6, n=40) — marginal. Sin embargo el edge se desvanece en OOS
  (−10.37%, 4/8).
- **`demon2:mmxm` resucitado y ahora rentable con riesgo real**: con
  `enable_breaker=True` (fix `min_periods=1` de pandas 2.3.3 en `_breaker_block`)
  dispara 382 señales; con SL ATR×1.5 firma +38.97 (5/8) — el +100% sin SL era
  exposición pasiva. BTC 2h (+164.7) y BTC 1d (+124.0) son las celdas fuertes.
- **`power_flow` refutado como edge:** el +107.88% era exposición pasiva sin SL;
  con SL ATR explícito → −46.99 → descartado.
- **fib_retrace (tp nativos 1.17/1.27 + invalidation v2):** sigue sin rentabilidad
  (−53.94) → revisión de SL/invalidation o descarte.
- **fvg (pullback) mejora (−24 → −16.8) pero sigue sin edge**: la inversión
  (ifvg) es lo que aporta, no la continuación.
- **po3_fractal y sfp_institutional** (nuevas) aún no entregan: 38 y 32 señales,
  medias −2.03 y −1.34. sfp_institutional al menos supera claramente al sfp
  clásico (−58.32); po3_fractal (ya con defaults revertidos) sigue sin edge con
  su primera muestra válida de 38 señales.
- po3/sfp pierden homogéneamente; scalp_sweep, intraday_quantum y macro_swing
  siguen sin generar señales en TFs ≥1h.

## Actualización OOS — walk-forward 70/30 (2026-09-02)

Script: `run_oos_validation.py` (misma config que el profit map, sin re-mutación
sobre OOS; exit_kwargs estrictos 2.0/5.0 solo para ifvg en 1h/4h). Split por
celda `cut = int(len(df)*0.70)`, `DAYS=365`, BTC+ETH en 1h/2h/4h/1d. Salida:
`reports/oos_validation.csv`.

### Régimen del mercado IS vs OOS (close-to-close)

| Celda | IS ret % (70%) | OOS ret % (30%) | OOS MDD % |
|---|---|---|---|
| BTC 1h | −4.4 | **+29.3** | −6.4 |
| BTC 2h | −27.9 | −1.9 | −26.4 |
| BTC 4h | −28.2 | −2.0 | −26.2 |
| BTC 1d | −28.9 | −0.7 | −25.0 |
| ETH 1h | −11.5 | **+49.6** | −6.7 |
| ETH 2h | −49.1 | +8.9 | −31.0 |
| ETH 4h | −49.2 | +8.9 | −30.7 |
| ETH 1d | −48.6 | +11.0 | −28.1 |

El IS fue un régimen **bajista** (drawdowns −30/−62%) y el OOS una
**recuperación alcista** (ETH 1h +49.6%, BTC 1h +29.3%). Aun así ambas
estrategias pierden en OOS → **el FAIL es sobreajuste real, no un régimen
adverso** (perdieron incluso con viento a favor).

### Verdicto OOS por candidato

| Candidato | IS mean | IS celdas | OOS mean | OOS celdas | OOS señales | OOS winrate |
|---|---|---|---|---|---|---|
| fvg_mtf:ifvg | +76.41% | 7/8 (n=390) | **−10.37%** | 4/8 | 165 | 37.4% |
| demon2:mmxm | +57.20% | 6/8 (n=279) | **−14.70%** | **0/8** | 95 | 19.1% |

- **ifvg por celda OOS**: BTC 1h −14.68 (n=14), 2h −44.59 (52), 4h **+69.66**
  (14), 1d −102.95 (5); ETH 1h −0.76 (10), 2h +1.55 (52), 4h +5.71 (12), 1d
  +3.12 (6). Cond1 (mean>0) **FAIL**, cond5 (≥2 celdas) PASS → **no desplegable**.
- **mmxm por celda OOS**: todas negativas — BTC 1h −6.46 (30), 2h −33.87 (19),
  4h −67.67 (9), 1d −0.91 (1); ETH 1h −1.98 (13), 2h −3.37 (16), 4h −2.90 (6),
  1d −0.40 (1). Cond1 **FAIL**, cond5 **FAIL** → **no desplegable**.

**Reclasificación**: ambos pasan de "PROFITABLE" a **"FALLO OOS — no
desplegable"** (sección 4 del prompt). No hay runner de Telegram ni backup en
`estrategias_produccion/` hasta que una variante los pase con muestra OOS ≥30.

### Caveats metodológicos

- La selección de parámetros (grid/hardening) se hizo sobre el histórico
  completo; por tanto el slice IS del 70% **no es independiente** de la
  selección → el OOS (30% final) es la única señal honesta.
- OOS n por celda es pequeño en las celdas bajas (mmxm 1d n=1, ifvg 1d n=5);
  conclusión robusta = media agregada por candidato (165/95 señales).
- Los buffers por TF (1h ~5000 velas, 2h ~4381, 4h ~2191, 1d ~366) hacen que la
  ventana OOS cubra ≈110 días en 2h/4h/1d pero ≈62 días en 1h (no alineada en
  fechas entre TFs; dentro de cada celda el split es limpio).
- Pendiente: revisar si un split alternativo (p.ej. fecha fija) mantiene el
  veredicto sin re-seleccionar parámetros.

## Datasets

- Profit map final post-revert: `reports/profit_map_20260902_105952.csv` +
  `reports/verdict_20260902_105952.csv`.
- Profit map de la fase 2 (referencia): `profit_map_20260902_100004.csv` /
  `verdict_20260902_100004.csv` (fixes `_trail` + mmxm con SL ATR real).
- Hardening ifvg: 092636/093120/093533 (ver tabla de evolución más arriba).
- Grid de po3_fractal/sfp_institutional: `reports/grid_search_results.csv`.
- Walk-forward OOS: `reports/oos_validation.csv`.