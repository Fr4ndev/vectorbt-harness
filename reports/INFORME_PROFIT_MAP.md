# Informe de Rentabilidad — Mapa BTC+ETH, 1 año (1h/2h/4h/1d)

Fecha: 2026-09-02 · Harness: `~/Escritorio/harness_vectorbt` · Runtime: venv ccxtv2
Fuente de datos: Hyperliquid nativo paginado (caché en `data/cache/`).
Exits: esquema unificado (80% TP1 1:2, 20% runner 1:5, SL→BE; fees 0.0006,
slippage 0.0003, cash 10 000).

## Veredicto por estrategia

| Estrategia | Veredicto | Media ret % | Celdas rentables | Celdas | Señales |
|---|---|---|---|---|---|
| demon2:power_flow | **PROFITABLE** | +107.88 | 6 | 8 | 18 079 |
| fvg_mtf:ifvg | **PROFITABLE** | **+41.50** | 6 | 8 | 978 |
| fib_retrace | UNPROFITABLE | −57.19 | 0 | 8 | 2 513 |
| demon2:po3 | UNPROFITABLE | −57.42 | 1 | 8 | 2 118 |
| fvg_mtf:fvg | UNPROFITABLE | −53.64 | 0 | 8 | 3 508 |
| ictsuite:sfp | UNPROFITABLE | −58.32 | 0 | 8 | 5 586 |
| demon2:mmxm (breaker ON) | SIN SEÑALES | — | — | 8 | 0 |
| ictsuite:scalp_sweep | SIN SEÑALES | — | — | 8 | 0 |
| ictsuite:intraday_quantum | SIN SEÑALES | — | — | 8 | 0 |
| ictsuite:macro_swing | SIN SEÑALES | — | — | 8 | 0 |

## Detalle fvg_mtf:ifvg por celda (1 año)

| Celda | Ret % | n | WinRate leg A |
|---|---|---|---|
| BTC 1h | −103.2 | 230 | 35.0 |
| BTC 2h | +66.1 | 200 | 44.1 |
| BTC 4h | **+279.7** | 105 | 42.1 |
| BTC 1d | +63.3 | 19 | 36.4 |
| ETH 1h | −3.7 | 159 | 35.3 |
| ETH 2h | +12.6 | 153 | 42.2 |
| ETH 4h | +10.4 | 91 | 43.5 |
| ETH 1d | +6.8 | 21 | 49.4 |

Nota: en BTC 4h el leg runner (1:5) es −101% — el resultado lo carga el leg A;
validar con gestión alternativa del runner.

## Lectura

- **Rentables:** `power_flow` (+107.88%, bias-only, sl=NaN → sin stop; refleja
  seguimiento M>W>D, validar con SL explícito) y **`fvg_mtf:ifvg` (+41.50%,
  la nueva estrategia MTF: inversión de gap 30m con bias 4h)**. ifvg gana sobre
  todo en BTC 2h/4h/1d y ETH todas las TFs; la única celda rota es BTC 1h.

- **fvg_mtf:fvg (continuación)** pierde en 8/8 → no es el pullback, es la
  inversión lo que tiene edge bajo este esquema de exits.

- **fib_retrace:** 2 513 señales; pierde en las 8 celdas. El S de invalidación
  −0.17/−0.27 medido desde el swing deja riesgo ~0.77R vs TP 1:2 que rara vez
  alcanza → **descartar defaults** o revisar SL / imponer los TPs 1.17/1.27 reales.

- **po3 / sfp:** pierden homogéneamente → flag de descarte salvo revisión.

- **mmxm incluso con breaker ON; scalp_sweep / intraday_quantum / macro_swing:**
  0 señales → necesitan menor TF (3m/5m) o relajar umbrales.

- CSVs por celda: `reports/profit_map_20260902_091415.csv` y
  `reports/verdict_20260902_091415.csv`.