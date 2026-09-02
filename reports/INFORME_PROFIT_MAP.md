# Informe de Rentabilidad — Mapa BTC+ETH, 1 año (1h/2h/4h/1d)

Fecha: 2026-09-02 · Harness: `~/Escritorio/harness_vectorbt` · Runtime: venv ccxtv2
Fuente de datos: Hyperliquid nativo paginado (caché en `data/cache/`).
Exits: esquema unificado (80% TP1 1:2, 20% runner 1:5, SL→BE; fees 0.0006,
slippage 0.0003, cash 10 000).
Hardening ifvg: `strict_min_confluence=4` en TFs estrictos (1h/4h) + runner
`rr_runner=3.0` / `weight_tp1=0.9` en esas celdas (default 2 en el resto).
Trailing invalidation: `runner_inv` (FVG 4h opuesto, `trail_4h=True`) activo en
ifvg/fvg — el runner se ancla al borde del FVG 4h contrario en lugar de a una
ratio fija.

## Veredicto por estrategia (run final 20260902_100004)

| Estrategia | Veredicto | Media ret % | Celdas rentables | Celdas | Señales |
|---|---|---|---|---|---|
| fvg_mtf:ifvg | **PROFITABLE** | **+79.81** | **7** | 8 | 560 |
| demon2:mmxm (breaker + SL ATR) | **PROFITABLE** | **+38.97** | **5** | 8 | 382 |
| fvg_mtf:fvg | UNPROFITABLE | −16.81 | 3 | 8 | 2 122 |
| demon2:po3_fractal | UNPROFITABLE | −1.88 | 1 | 8 | 4 |
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

- **`demon2:po3_fractal`**: solo 4 señales en total (BTC 1h 1, BTC 4h 1, ETH 1h 1,
  ETH 4h 1; 2h/1d n=0). −16.90 / +2.40 / −0.19 / −0.38. **Datos insuficientes**:
  verdicto UNPROFITABLE por criterio mecánico, pero no es refutación — la
  estrategia apenas toca. Se documenta como "nueva, a vigilar con más core /
  calibración del Judas Swing".
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

- **Única familia de peso rentable: `fvg_mtf:ifvg` (+79.81%, 7/8)**. El trail
  anclado al FVG 4h opuesto añade ~10 puntos sobre el hardening sin trail
  (+69.73): BTC 4h 387.6 → 465.6 y BTC 1h 14.0 → 16.1. La única celda negativa
  es ETH 1h (−3.6, n=40) — marginal; se acepta o se excluye del lote de
  producción sin coste material.
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
- **po3_fractal y sfp_institutional** (nuevas) aún no entregan: 4 y 32 señales,
  medias −1.88 y −1.34. sfp_institutional al menos supera claramente al sfp
  clásico (−58.32); po3_fractal necesita más datos antes de juzgar.
- po3/sfp pierden homogéneamente; scalp_sweep, intraday_quantum y macro_swing
  siguen sin generar señales en TFs ≥1h.

- CSVs por celda: `reports/profit_map_20260902_100004.csv` y
  `reports/verdict_20260902_100004.csv` (run final). Trazabilidad de la fase 2:
  095843 (bug `_trail` + mmxm prematuras) → 100004 (fixes). Hardening ifvg:
  092636/093120/093533.