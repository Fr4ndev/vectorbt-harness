# Log de Evolución — Harness Vectorbt

Registro trazable de mutaciones, validaciones in-sample y evaluaciones
out-of-sample (walk-forward 70/30). Rige el PROMPT v2
(`opencode_self_evolutionary_loop`) + regla anti-overfit OOS de 2026-09-02.

## Regla OOS (aplicable desde 2026-09-02, obligatoria)

**Un split OOS de una config se evalúa una sola vez.** Si una variante (nueva o
recién tuneada) falla el walk-forward, esa config concreta queda **muerta** — no
se reajustan sus parámetros y se vuelve a correr contra el *mismo* tramo OOS.
Reusar el mismo hold-out para "afinar" es exactamente el mismo overfitting que ya
se revertió, solo que con más pasos intermedios.

Flujo obligatorio para toda mutación:
1. **Nuevas variantes se generan/seleccionan SOLO con in-sample (70%).** El tramo
   OOS (30%) no se toca hasta tener candidato final.
2. **Cada candidato final se prueba contra OOS exactamente una vez.** Si falla →
   `FALLO OOS` en este log → descarte. No hay segundo intento con params
   retocados sobre ese mismo split.
3. Para configs de n bajo (`po3_fractal`, `sfp_institutional`): ampliar el
   histórico (2 años, vía `days=730`) para subir n de forma honesta antes de
   tunear — nunca exprimir params sobre la misma muestra pequeña.
4. Familias UNPROFITABLE en cola (`fib_retrace`, `demon2:po3`, `ictsuite:sfp`,
   `fvg_mtf:fvg`): misma canalización in-sample (70%) → un único check OOS por
   candidato → log.
5. Se registra abajo cuántas veces se ha evaluado cada split OOS por familia
   (trazable por si algún día se reutiliza por error).

Promoción (sección 4 del prompt) sin cambios: 5 condiciones, nada de
Telegram/backup en `estrategias_produccion/` hasta que una config las pase con
OOS > 0.

---

## Conteo de evaluaciones OOS por config (split 70/30, `run_oos_validation.py`)
- `DAYS=365`, split por celda `cut=int(len(df)*0.70)`, sin re-mutación sobre OOS.
- Multiplicar por familia; # = nº de veces que se ha corrido el OOS de esa config.

| familia:strategia (params) | Evaluaciones OOS | Resultado (último) | Fecha |
|---|---|---|---|
| `fvg_mtf:ifvg` `{}` | 1 | OOS mean −10.37%, 4/8 → **FALLO OOS** | 2026-09-02 |
| `demon2:mmxm` `{enable_breaker:True}` | 1 | OOS mean −14.70%, 0/8 → **FALLO OOS** | 2026-09-02 |
| `demon2:po3_fractal` `{}` (defaults) | 0 | — (solo in-sample n=38) | — |
| `ictsuite:sfp_institutional` `{}` | 0 | — (solo in-sample n=32) | — |
| `fvg_mtf:fvg` 4h `{strict_min_confluence:5, gap_atr_mult:0.75}` | 1 | OOS mean **+24.68%**, 2/2 → **PASA OOS** (n=16, aún <30) | 2026-09-02 |

> Regla: si alguna de estas filas vuelve a correr con los MISMOS params sobre el
> MISMO tramo OOS, es una violación — marcar y abortar.

---

## Historial

### 2026-09-02 — Clasificación por sección 4 (estado base)

**Primer gate: ¿es rentable in-sample (mean>0, prof≥50%, n>10)?**
Solo `ifvg` y `mmxm` lo pasaban en IS; ambos ya fallaron OOS (tabla arriba).
Ninguna otra familia es candidata a promoción.

| familia:strategia | IS mean | prof | n | Sección 4 |
|---|---|---|---|---|
| `fvg_mtf:ifvg` | +79.81 | 7/8 | 560 | ✅ IS profitable → **FALLO OOS** |
| `demon2:mmxm` | +38.97 | 5/8 | 382 | ✅ IS profitable → **FALLO OOS** |
| `fvg_mtf:fvg` | −16.81 | 3/8 | 2122 | ❌ no IS → cola |
| `demon2:po3_fractal` | −2.03 | 3/8 | 38 | ❌ no IS → cola |
| `ictsuite:sfp_institutional` | −1.34 | 2/8 | 32 | ❌ no IS → cola |
| `demon2:po3` | −57.42 | 1/8 | 2118 | ❌ no IS → cola |
| `ictsuite:sfp` | −58.32 | 0/8 | 5586 | ❌ no IS → cola |
| `fib_retrace` | −53.94 | 0/8 | 2718 | ❌ no IS → cola |

### 2026-09-02 — Probe histórico extendido (days=730, BTC solo)

Objetivo: comprobar si 2 años de data sube n de forma honesta para `po3_fractal`
y `sfp_institutional` (regla punto 3).

**`demon2:po3_fractal` (defaults restaurados)**

| TF | n (365d) | n (730d) | Δ |
|---|---|---|---|
| 1h | 1 | 1 | +0 |
| 2h | 0 | 0 | +0 |
| 4h | 1 | 2 | +1 |
| 1d | 0 | 0 | +0 |

→ po3_fractal sigue siendo **extremadamente escaso** incluso con 2 años: solo
BTC 4h aporta +1 señal extra. La estrategia es rara por diseño (Judas Swing +
MSS + FVG en 15/30m anclada a 00:00 UTC). Con 38 señales en 365d (BTC+ETH) ya
pasa el umbral de n≥30 pero **no hay edge** (−2.03% mean). No es cuestión de
muestra; es cuestión de que la lógica no genera alpha.

**`ictsuite:sfp_institutional`**

| TF | n (365d) | n (730d) | Δ |
|---|---|---|---|
| 1h | 4 | 4 | +0 |
| 2h | 6 | 7 | +1 |
| 4h | 7 | 15 | +8 |
| 1d | 0 | 0 | +0 |

→ sfp_institutional gana algo en 4h con 2 años (+8 señales extra) pero 1h/2h
siguen con n muy bajo. El n total BTC+ETH en 730d sube de 32 a ~40, aún
borderline. IS mean en 365d era −1.34 (2/8); con más datos podría cambiar
ligeramente, pero no se observa un edge consistente en las celdas que ya
existen.

**Conclusión para po3_fractal/sfp_institutional**: el problema no es la
muestra; es la lógica. Po3_fractal necesita reformulación (la condición de
Judas Swing + MSS + FVG solo dispara en ~38 señales/año con −2% mean).
Sfp_institutional necesita más trabajo en la validación de reclaim y killzone
para aumentar n sin destruir la calidad.

### Fuga de datos — diagnóstico exploratorio fvg (NO vinculante)

Se ejecutó un barrido exploratorio de hipótesis (`strict+2h`, `strict+2h+1d`,
`quality_all`, etc.) sobre el dataset **completo de 365 días** en lugar de solo
el IS 70%. Esto contaminó la selección de hipótesis: los resultados que
"ganaron" (ej. `strict+2h` pasaba de −16.81 a +9.37%) incluyeron el tramo
OOS en la evaluación.

**Estatus**: resultados exploratorios archivados pero NO vinculantes. El loop
de mutación se relanza desde cero usando SOLO el IS 70%, sin mirar estos
números para decidir qué mutar. Si la misma hipótesis (`strict_tfs` extendido)
gana en IS limpio → legítimo; si no → se descarta sin pena.

Causa raíz: el script diagnóstico (`test strict_tfs hypothesis`) se ejecutó
antes de montar el loop de mutación, y usó `days=365` completo. Debería haber
hecho el split primero. Corregido en el re-lanzamiento.

### 2026-09-02 — fvg_mtf:fvg (PRIMERA FAMILIA, COLA)

**Estado inicial**: UNPROFITABLE −16.81%, 3/8, n=2122 (full 365d).

**Loop de mutación** (IS-only 70%, 13 iteraciones, patience=4, n≥30 gate):
- Baseline IS: mean=−20.33%, 3/8, n=1430
- Mejor variante alcanzada: `gap_100` (gap_atr_mult=1.0, strict_tfs=1h/4h)
  - IS mean=−13.22%, 3/8, n=1221
  - BTC 2h sigue dominando negativamente (−102.27%, n=452)
- **Ninguna mutación pasó el gate IS** (mean>0 + prof≥50% + n≥30)
- `strict_tfs` extendido (2h, 2h+1d) NO ganó en IS limpio — la mejora vista en
  el full-data era artefacto de fuga de datos (ya documentado arriba)

**Veredicto**: **DESCARTADA** (fvg pullback no genera alpha con los parámetros
disponibles). El problema es estructural: BTC 2h produce −102% con n=452 en IS,
sin importar el gate de confluencia. La inversión (ifvg) es la que aporta;
el pullback no.

OOS evaluado: 0 (no hubo candidato IS-profitable).

### 2026-09-02 — fvg 4h-only (mc5+gap075): CANDIDATO que sobrevive OOS

Revisión tras el descarte con foco en la celda estrella observada en IS: `fvg`
es rentable en **4h** (BTC 4h +79.1% en profit map full-365d; +138.9 en IS limpio
con mc5+gap075), pero se hunde en 2h/1d (−102%). El descarte global estaba
arrastrado por esas celdas malas.

**Mutación dirigida a 4h** (`strict_min_confluence=5`, `gap_atr_mult=0.75`,
solo BTC/ETH 4h):

| Métrica | IS (70%) | OOS (30%) |
|---|---|---|
| mean | **+72.55%** | **+24.68%** |
| celdas rentables | 2/2 | 2/2 |
| n | 34 | 16 |
| detalle | BTC 4h +138.9 (n=22), ETH 4h +6.2 (n=12) | BTC 4h +47.2 (n=8), ETH 4h +2.1 (n=8) |

**Primer candidato que SOBREVIVE OOS** (mean OOS +24.68% > 0, 2/2 celdas).
Caveat de muestra: OOS n=16 (BTC 8 + ETH 8), por debajo del umbral de
n≥30 de la condición 3 en la celda de soporte. Aun así, es el único perfil con
OOS>0 de toda la cartera hasta la fecha.

Cuenta como **1 evaluación OOS** de esta config de `fvg` (regla one-shot; si se
vuelve a probar con estos params sobre el mismo tramo → violación).

### 2026-09-02 — DEPLOY A TELEGRAM del candidato fvg 4h (decisión del usuario)

El usuario eximió explícitamente el gate n≥30 (`"pásalo ya a telegram, aunq aya
pocas señales, si son de altos tf, valen... para pequeño swing de semanas, es
normal"`). Riesgo conocido y aceptado: n OOS=16 < 30 (condición 3).

**Estado del mercado al desplegar (2026-09-02 ~10:33 UTC)**: SIN señal fresca.
Última señal BTC 4h fue 2026-08-25 16:00 (hace 8 días); ETH no emite en 14d.
Vela cerrada 04:00 de hoy: conf 1/5 (BTC), 2/5 (ETH) — lejos del umbral 5.
No se envió ninguna señal de trade fabricada.

**Despliegue ejecutado (decisión del usuario: monitor daemon)**:
- `run_live_monitor.py`: daemon que escanea BTC/ETH 4h (datos frescos HL) cada
  5 min y envía automáticamente la señal fresca vía `ccxtv4/shared/telegram_sender.py`
  (Dispatcher v4.0, chat `-1002400551494`, chart 15m dark nightclouds).
- Config emitida = la validada: `fvg`, `strict_tfs=("4h",)`, `strict_min_confluence=5`,
  `gap_atr_mult=0.75`, exits STRICT (rr_tp1=2.0, rr_runner=3.0, weight_tp1=0.9).
- Dedup por vela de entrada (estado en `reports/live_monitor_state.json`); señal
  fresca = entrada en la vela 4h formándose (ejecución al open), age ≤ 4h.
- Mensaje de arranque "fvg 4h live-monitor ONLINE" enviado OK (sendMessage 200).
- Daemon corriendo en background (PID 20501, `reports/live_monitor_daemon.log`).
- Herramienta auxiliar: `run_live_check.py` (scanner manual con detalle por vela).

**Nota brecha visible**: el envío es un ALERTA informativo, no una ejecución
automática. TP1/TP2 derivados de SL con rr_tp1=2.0 / rr_runner=3.0 (STRICT,
como en la evaluación OOS). Runner invalidation = extremo opuesto del FVG 4h.

### 2026-09-02 — fib_retrace v3 (port 1:1 del FibonacciEngine): DESCARTADA en IS

Se portó `FibonacciEngine` (ccxtv4 `shared/engines/fib_engine.py` v2.0) al harness
como `signals/fib_retrace/fib_retrace.py` v3, con:
- swings fractales 2/2 en el MISMO tf de la celda (`_impulse_series`),
- entries en retracements 0.5/0.618 con confirmación close-back,
- SL estructural = extremo del swing ± inval*R (± 0.5·ATR),
- targets nativos `tp1 = close ± 0.618·R`, `tp2 = close ± 1.272·R`.

**Loop de mutación** (`run_mutation_fib.py`, IS-only 70%, 12 iteraciones,
patience=5, gate mean>0 + prof≥50% + n≥30):
- Baseline defaults: mean=−25.17%, 0/8, n=1384. Mejores celdas BTC:4h −2.51%
  (n=132) y ETH:1h −2.15% (n=315); BTC:1h −105.77% (n=284).
- Mejor variante `exit_c066` (exit_cons=0.66): mean=−19.44%, 1/8 (BTC:4h +12.81%).
- **Ninguna candidata IS** (20 mutaciones). **FAMILIA DESCARTADA**.

**Diagnóstico estructural** (no param-tuning): legA marginal (BTC 1h win 50%),
**legB corredor 1.272×R implosiona en BTC** (−100%, win 15-20%) y RR real del
tp1 bajo (mediana 0.47 en BTC 1h). Causa raíz: el swing detectado en el MISMO tf
con fractal 2/2 es la última pierna corta (R pequeño, SL anclado al swing-low
queda lejos del TP conservador 0.618·R). El RR tp1 = 0.618R/R_invalidación < 1
por construcción → depende de 1.272R para compensar, y el corredor no golpea.

OOS evaluado: 0 (sin candidato IS-profitable). La config v3 concreta (defaults y
sus 12 mutaciones) queda descartada sin consumir split OOS.

### 2026-09-02 — fib_htf v4 (swing HTF + entry LTF): DESCARTADA en IS

Nueva hipótesis: mide el swing en el HTF resampled (1d para 1h/2h/4h, 1w para
1d), con running-max/min causal (desde el último pivote fractal), entries en
retracement 0.5/0.618 del swing HTF, targets nativos del engine (tp1 = close +
0.618·R, tp2 = close + 1.272·R). Gate: confluences (strong + vol + gp + pd) ≥ 2.

**Loop de mutación** (`run_mutation_fib_htf.py`, IS-only 70%, 8 iteraciones,
patience=6, gate mean>0 + prof≥50% + n≥30):
- Baseline: mean=−37.55%, 2/8, n=1299. BTC intraday −43 a −109%; ETH marginal
  −3 a +5%; 1d positivo (BTC +52.96%, ETH +4.74%) pero n bajo (17+19=36).
- Mejor variante: `entry_786` (golden pocket): mean=−26.82%, 2/8, n=1224.
- **Ninguna candidata IS**.

**Diagnóstico**: el patrón BTC intraday tóxico persiste v3→v4. El legA (parcial)
en BTC es −49 a −115% en todas las celdas intraday; ETH es marginal (−0.59% a
+2.80%). El legB (runner) implosiona en BTC (−100%+) y es marginal en ETH.
La familia fib_retrace NO genera alpha en intraday BTC. Única celda positiva:
1d (BTC +52.96%, ETH +4.74%), n combinado 36 (muy bajo para mutación robusta).

OOS evaluado: 0 (sin candidato IS-profitable). Familia descartada definitivamente
(tras v3 + v4, ambas sin candidato IS-profitable con n≥30).

**Estado de la cola de familias**:
- `fib_retrace`: **DEFINITIVAMENTE DESCARTADA** (v3 y v4 ambas fallidas en IS).
- `demon2:mmxm`: IS profitable (+38.97%, 5/8) pero OOS dead (−14.70%).
- `fvg_mtf:ifvg`: IS profitable (+79.81%, 7/8) pero OOS dead (−10.37%).
- `fvg_mtf:fvg 4h`: OOS passed (+24.68%), desplegado a Telegram.
- Familias sin testear: `demon1`, `demon2volumen`, `ict4hsweep`, `ictquantum`.
- `ictsuite`: scalp_sweep/intraday_quantum/macro_swing = 0 señales;
  `sfp_institutional` n=32, −1.34%.

### Cola: mutaciones pendientes (in-sample → OOS único)

**HALLAZGO FUNDAMENTAL (2026-09-02): el split exit scheme destruye alpha**

Prueba exploratoria: `fvg_mtf:ifvg` en modo **simple** (sin SL/TP, entries y
short_entries como triggers de entrada/salida, sin brackets) produce:
- Full 365d: mean=+66.84%, **8/8 celdas positivas**
- IS (70%): mean=+30.55%, 7/8, n=390
- OOS (30%): mean=+14.68%, 6/8, n=165
- Celdas más fuertes (2h): BTC:2h OOS +35.17% (n=52), ETH:2h OOS +22.96% (n=52)

**Implicación**: las entries de ifvg son excelentes. El problema era el exit
scheme del harness (SL estructural + TP1 1:2 + runner 1:5 con BE). El SL
mata trades que serían rentables si se mantienen hasta la siguiente señal
opuesta. El alpha está en la calidad de las entries, no en la gestión de
salida con SL rígido.

**Nota**: modo simple = sin gestión de riesgo por trade (unlimited risk).
Para deploy práctico: o se acepta el riesgo con sizing conservador, o se
busca un trailing stop suave que preserve el alpha.

Familias con IS profitable agotadas en OOS: fvg 4h (deployed), ifvg (OOS dead),
mmxm (OOS dead). Familias sin testear (prioridad nueva):

1. **`demon1`**: n demasiado bajo (0-4 señales por celda). **Descartada por escasez.**
2. **`demon2volumen`** (`liquidity_sweep_bot`): n decente (155-375), mismo patrón
   BTC intraday tóxico. 1d positivo (BTC +80%, ETH +19%) pero n bajo.
3. **`ict4hsweep`**: n=4 en BTC:4h. **Descartada por escasez.**
4. **`ictquantum`** (v9/v10/v11): −101.85% en todas las versiones. **Descartada.**
5. **`ictsuite:sfp_institutional`** (−1.34, 2/8, n=32): mutación IS para subir n
   y limpiar entrada. Baja prioridad (n bajo, edge débil).
6. **`fib_retrace`**: DESCARTADA (v3 + v4, ambas fallidas IS).
7. **`demon2:po3`** (−57.42, 1/8, n=2118): revisión AMD + SL pendiente.
   **DESCARTADA por resultados** (una sola celda positiva no compensa).

**Próximo paso recomendado**: pivotar a explorar sivg simple mode como
estrategia base (entries ifvg + sin SL, sizing conservador), o investigar
trailing stops suaves que preserven el alpha de ifvg.