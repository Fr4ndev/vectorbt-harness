# Informe de Rentabilidad — Mapa BTC+ETH, 1 año (1h/2h/4h/1d)

Fecha: 2026-09-02 · Harness: `~/Escritorio/harness_vectorbt` · Runtime: venv ccxtv2
Fuente de datos: Hyperliquid nativo paginado (caché en `data/cache/`).
Exits: esquema unificado (80% TP1 1:2, 20% runner 1:5, SL→BE; fees 0.0006,
slippage 0.0003, cash 10 000).
Hardening ifvg: `strict_min_confluence=4` en TFs estrictos (1h/4h) + runner
`rr_runner=3.0` / `weight_tp1=0.9` en esas celdas (default 2 en el resto).

## Veredicto por estrategia

| Estrategia | Veredicto | Media ret % | Celdas rentables | Celdas | Señales |
|---|---|---|---|---|---|
| fvg_mtf:ifvg | **PROFITABLE** | **+69.73** | **7** | 8 | 563 |
| fvg_mtf:fvg | UNPROFITABLE | −24.01 | 3 | 8 | 2 128 |
| demon2:power_flow | UNPROFITABLE | −46.99 | 0 | 8 | 18 079 |
| fib_retrace | UNPROFITABLE | −53.94 | 0 | 8 | 2 718 |
| demon2:po3 | UNPROFITABLE | −57.42 | 1 | 8 | 2 118 |
| ictsuite:sfp | UNPROFITABLE | −58.32 | 0 | 8 | 5 586 |
| demon2:mmxm (breaker ON) | SIN SEÑALES | — | — | 8 | 0 |
| ictsuite:scalp_sweep | SIN SEÑALES | — | — | 8 | 0 |
| ictsuite:intraday_quantum | SIN SEÑALES | — | — | 8 | 0 |
| ictsuite:macro_swing | SIN SEÑALES | — | — | 8 | 0 |

## Detalle fvg_mtf:ifvg por celda (1 año, hardening activo)

| Celda | Ret % | n | Leg A ret % | Leg B ret % | WinRate leg A % |
|---|---|---|---|---|---|
| BTC 1h | **+14.0** | 43 | +23.4 | −23.3 | 57.7 |
| BTC 2h | +66.1 | 200 | +68.7 | +55.6 | 44.1 |
| BTC 4h | **+387.6** | 46 | +510.1 | −102.4 | 51.5 |
| BTC 1d | +63.3 | 19 | +76.9 | +9.1 | 36.4 |
| ETH 1h | −2.3 | 42 | −2.5 | −1.5 | 37.1 |
| ETH 2h | +12.6 | 153 | +15.2 | +1.8 | 42.2 |
| ETH 4h | +9.7 | 39 | +12.3 | −0.8 | 52.0 |
| ETH 1d | +6.8 | 21 | +9.5 | −4.1 | 60.0 |

## Evolución del hardening (mapa completo, misma data)

| Run | Configuración | Media ret % | Celdas rentables | BTC 1h | BTC 4h |
|---|---|---|---|---|---|
| 092636 | sin strict (freq=None → mc=2) | +42.26 | 6/8 | −103.3 | +287.3 |
| 093120 | strict mc=3 (inferencia de TF corregida) | +50.47 | 6/8 | −70.9 | +318.2 |
| **093533** | **strict mc=4 (final)** | **+69.73** | **7/8** | **+14.0** | **+387.6** |

## Lectura

- **Única familia rentable: `fvg_mtf:ifvg` (+69.73%, 7/8 celdas)**. El
  endurecimiento quirúrgico (min_confluence 4 en 1h/4h + runner 3.0/0.9) curó la
  celda rota BTC 1h (−103 → +14) y elevó BTC 4h a +387.6. La 2h/1d no son
  estrictas (mc=2) e intactas (BTC 2h +66, ETH 2h +12.6).
- La única celda negativa es ETH 1h (−2.3, n=42) — marginal; se acepta o se
  excluye del lote de producción sin coste material.
- **`power_flow` refutado como edge:** +107.88% previo era exposición pasiva sin
  SL (bias-only). Con SL ATR explícito cae a −46.99 → descartado.
- **fib_retrace con TPs nativos 1.17/1.27 + invalidation v2:** sigue sin
  rentabilidad (−53.94) → revisión de SL/invalidation o descarte.
- fvg (pullback) mejora con el strict (−42 → −24) pero sigue sin edge: la inversión
  es lo que aporta, no la continuación.
- po3/sfp pierden homogéneamente; mmxm, scalp_sweep, intraday_quantum y
  macro_swing siguen sin generar señales en TFs ≥1h.

- CSVs por celda: `reports/profit_map_20260902_093533.csv` y
  `reports/verdict_20260902_093533.csv` (trazabilidad completa en 092636/093120).