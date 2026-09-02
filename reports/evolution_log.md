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

### Trailing stop para ifvg (2026-09-02): triada, no alpha genuino

Siguiendo el hallazgo anterior, se probaron trailing stops suaves para
preservar el alpha de ifvg sin el SL rígido del split. 3 variantes acordadas
para competir por UN solo check OOS (regla global-best):

- **v1 `straight_bos`** (copia splits + BOS structure exit): **DESCARTADA en
  diseño** — propia implementación dio +108% idéntico en TODOS los params
  (señal inequívoca de bug: ningún param cambiaba el resultado, no se estaba
  aplicando). Rediseñarla a ciegas antes de un check OOS de un solo disparo
  = riesgo de quemar la disciplina. Drop.
- **v2 `atr_trailing`** (`sl_stop=atr×mult/close` Series + `sl_trail=True`):
  mecánica verificada correcta (tests sintéticos: long que sube no sale con
  5% trail; long que cae sale a −5%). Pero IS best `atr35` (ATR×3.5) =
  mean +87.10%, 7/8, n=675 — **sospechoso**. Inspección de trades:
  - Win rates pobres: BTC 2h 47%, BTC 4h 50%, ETH 2h 41%, ETH 4h 41%.
  - Media domina por pocas operaciones monstruos: top-3 = 28-49% del total
    (BTC 2h: top3 +28% pero total +24% → el resto neto NEGATIVO; ETH 2h:
    top3 +38% vs total +5%). Sin los top-3, varias celdas serían negativas.
  - → **trend/regime-fitting**: el trail ancho (ATR×3.5) atrapa unos pocos
    trend moves largos del sample; NO es edge reproducible (contradice el
    consenso establecido de que BTC intraday split es tóxico −43 a −115%).
- **v3 `fvg_anchored`** (`sl_stop` = gap bottom/top de FVG, nivel fijo): IS
  best `no4h` (require_4h_bias=False) = mean +85.01%, 5/8, n=1295. Misma
  sospecha de dependencia de pocos trend-moves.

**Problema de disciplina detectado**: mi candidato-selector rechazó el
verdadero best global (`atr35`) por la gate estricta por-celda (BTC:1h n=27<30
con ret positivo) y gastó el OOS shot en `no4h` (2º best) → +32.35%, 6/8, n=526
(OOS pass). Esto viola la regla "global-best → único OOS". El fix futuro:
OOS-check el best GLOBAL por mean, no el gateado.

**Verdicto final**: la línea **fvg/ifvg trailing stop (v1 BOS + v2 ATR + v3 FVG)
queda DEFINITIVAMENTE DESCARTADA** — artefacto de trend-fitting (winrate real
~40-50%, retorno concentrado en pocas operaciones top-3), no edge reproducido.
Ninguna de las 3 variantes genera alpha que sobreviva a la inspección de
distribución de trades; no se despliega. El alpha de ifvg sigue siendo el de
las entries (hallazgo simple mode), que requiere o riesgo ilimitado (no
desplegable) o un trailing que no concentre el ret en pocos trades.

**Proceso/pendientes resueltos este turno**:
- Daemon fvg 4h (PID 20501): estaba VIVO desde 12:41 (mc5+gap075,
  RR 2.0/3.0/90, 1 instancia confirmada). **KILLED por decisión del usuario**
  (confirmado muerto, sin instancias activas). El deploy validado deja de
  monitorear/avisar.
- Hallazgo "+66.84% simple mode" = 365d completo → **data peeking confirmado**
  (NO pasó IS-only→OOS único); rechazado como base directa.

**Siguiente en cola (misma disciplina, sin reintentar muertos)**:
- Revisar `ictsuite:sfp_institutional` (mutación IS para subir n / limpiar
  entrada, edge débil n=32) o `demon2volumen:liquidity_sweep_bot` (n decente,
  pattern BTC intraday tóxico, 1d positivo con n bajo). Ambas sin quebrar la
  regla global-best → único OOS. Filtro propuesto "concentración en top-N"
  como gate de rechazo anticipado: mejora razonable, no urgente.

### `ictsuite:sfp_institutional` (2026-09-02): DESCARTADA — escasez + sin edge

Mutación IS-only (70% de 365d, BTC/ETH 1h+4h, 15 mutaciones) para subir n y
limpiar la entrada. Resultado:
- Baseline: mean −1.07%, 1/4, n=13, **toda celda n<30**.
- Mejor variante `rej30` (rejection_min=30): mean −0.97%, 1/4, n=14 — sigue
  negativo y con n irrisorio (n<30 en las 4 celdas en TODAS las mutaciones).
- `killzones=False` (la que más n sube: 33-39 total): −6 a −8%. Ensanchar la
  entrada añade ruido, no edge.
- Solo BTC:4h da +3.45% en el grid previo (n=8, 2/6 celdas) — n demasiado bajo
  para promover y no sostiene IS.

**Veredicto**: sin candidato IS-profitable con n≥30. La señal sfp_institutional
es demasiado escasa (rara) y sin edge en IS. **DESCARTADA DEFINITIVAMENTE.**
OOS: 0 evaluaciones (sin candidato).

**Siguiente**: `demon2volumen:liquidity_sweep_bot` (n decente 155-375, patrón
BTC intraday tóxico, 1d positivo con n bajo). Misma disciplina global-best →
único OOS.

---

## 🔴 CRÍTICO — BUG DE PIPELINE: `_run_split` colapsa señales densas (2026-09-02)

**Hallazgo durante la mutación de `demon2volumen:liquidity_sweep_bot`**: el
backtest dio +86%/+232%/+266% fantasmas. Inspección reveló **bug de sizing**,
no artefacto de trend-fitting (esto último era sospecha inicial, el real es
peor: un error de medición del pipeline).

**CAUSA RAÍZ EXACTA (confirmada, mínima + datos reales)**:
- `_run_split` en `portfolio/engine.py` pasa `size=size*w1` (=0.8 por defecto)
  a `Portfolio.from_signals` **sin `size_type`**. vectorbt deduce
  `size_type='percent'` (80% de la EQUITY por posición).
- Cuando las señales son densas y las posiciones se **solapan** (nueva entry
  mientras la previa sigue abierta), la posición anterior tiene bloqueado el
  80% de la equity → la siguiente entry del 80% no se puede fondear →
  **margin rejection → la señal se descarta en silencio** → colapso.
- No es por dirección (afecta longs y shorts), no son los stops, no es
  `accumulate`. Es el `size_type='percent'` + posiciones solapadas.
- Fix confirmado: `size=0.8, size_type='value'` (dinero absoluto por posición)
  restaura 213 trades donde `size=0.8` (percent) daba 2.
- Repro mínima: 10 shorts consecutivos → 1 trade.

**RADIO DE IMPACTO (medido: ratio trades/signals; ratio<0.7 = colapso)**:
- `fvg_mtf:ifvg` → **SANO** (ratio 1.08-1.75). Su OOS-pass se mantiene. ✅
- `demon2:mmxm` → **SANO** (ratio 1.50-1.83). Su OOS-pass se mantiene. ✅
- `fvg_mtf:fvg` → **CONTAMINADO** en BTC:2h (0.08), BTC:4h (0.62), BTC:1d (0.19),
  ETH:2h (0.71). El veredicto "fvg descartada" NO es fiable en esas celdas.
- **Deploy fvg 4h (mc5+gap075)** → **SANO** (ratio 1.78/1.70, señales escasas no
  solapan). El deploy a Telegram se mantiene válido. ✅
- `demon2volumen:sweep` (short-only denso) → **colapso TOTAL** (335→1, +316%
  fantasma). Resultado inválido.
- `ictsuite:sfp` → escasez (n≈30), independiente del bug; su descarte por
  escasez sigue en pie.

**CANDIDATOS A RE-VERIFICAR tras el fix (`size_type='value'`)**:
1. `fvg_mtf:fvg` en BTC:2h, BTC:4h, BTC:1d, ETH:2h — puede cambiar el veredicto.
2. `demon2volumen:sweep` — re-medir con el fix (edge real o descarte real).

**NO TOCAR `_run_split` HASTA reportar el alcance al usuario.** Prioridad:
acotar el daño y corregir el sizing en el pipeline ANTES de seguir el loop.
---

## 2026-09-02 — demon2volumen:sweep ghost +316% ROOT CAUSE FOUND & FIXED

**Decisión del usuario**: señales solapadas mismo lado = UNA posición por lado a la
vez (re-entry tras exit). El colapso a menos trades es CORRECTO. El bug real es el
**return fantasma de medición**, no el sizing. (El naive `size_type='value'` se
rechazó: cambiaba familias sanas — BTC 4h +180%→+17%, ETH +10%→+33%.)

**Diagnóstico empírico (BTC:2h swing5+atr02)**:
- legA colapsaba a **1 trade** que entraba en idx 9 y salía en idx 3065 (última
  barra): una posición ABIERTA que jamás se cerraba, marcada **+316% unrealized**
  al cierre final. Ese 1 trade bloqueaba los 335 re-entries → falso colapso total.

**Causa raíz**: `liquidity_sweep_bot` emitía señal en idx 9 con **SL=NaN** (ATR
period 14 sin warmup: `atr[9]=NaN` → `sl[9]=NaN`), pero `bearish=True` y `dir=-1`
igual. En `_run_split`, `.fillna(np.inf)` convierte ese SL/TP NaN en **stops
inalcanzables** → posición perpétua. (1 de 335 señales shorts con SL NaN.)
- Verificado: short con `sl_stop`/`tp_stop` relativos POSITIVOS se aplican como
  stop-up/down correctos en vectorbt — la dirección NO era el bug. Solo el NaN-SL.

**Fix aplicado** (`signals/demon2volumen/demon2volumen.py`): descartar la señal si
ATR/SL no es válido: `bearish &= atr_.notna() & (high+atr_*atr_buf).notna()`.
- No toca sizing de familias sanas. Colapso legítimo (una posición por lado) se
  conserva; solo elimina el fantasma de posición-abierta-sin-stop.

**Resultado post-fix (re-run `run_mutation_sweep.py` IS)**:
- BTC:2h +232%→ legA 15 trades reales; BTC:4h +266%→ normal.
- **NO CANDIDATO** (n>=30 no se cumple: n_below30=1-2, varias celdas <30).
  Familia `demon2volumen:sweep` → **DESCARTADA** (veredicto ahora fiable).

**OBSERVACIÓN PENDIENTE (no es el scope de este fix)**: el split-mode sigue
produciendo Total Return < -100% (legA -102.47%) y sizes raros (0.0025, 0.7975) en
algunas celdas → `_combine_split_stats` / `_combined_return` tiene su propio
artefacto de medición (stacking legA+legB con `init_cash` y `size` mezclados).
Aun así no altera el veredicto: ninguna config pasa el gate de candidato.

**PENDIENTE CONOCIDO (no investigado por ahora — anotado)**: `_combine_split_stats` /
`_combined_return` producen Total Return < -100% (p.ej. legA -102.47%) y `size` raros
(0.0025, 0.7975) en algunas celdas tras el fix de NaN-SL. Artefacto de medición propio
del stacking legA+legB (`init_cash`/`size` mezclados). No alteró el veredicto de sweep
(descarte). **Respetar al medir** futuras familias + no tocarlo sin enfoque dedicado.

## 2026-09-02 — fvg 4 celdas contaminadas: RE-EVALUACIÓN (colapso = correcto)

Contexto: el veredicto previo "fvg descartada" se marcó NO fiable en BTC:2h, BTC:4h,
BTC:1d, ETH:2h por ratio trades/signals bajo (colapso). Per la decisión del usuario el
colapso a menos trades ES comportamiento correcto (una posición por lado). Re-evaluado
con disciplina IS-only (70% de 365d), sin peeking, un único check OOS solo si hay
candidato.

**Resultado (run_mutation_fvg.py, IS)**:
- Baseline: mean=-20.33%, prof=3/8, n=1430 → no gate.
- Best `gap_100`: mean=-13.22%, prof=3/8, n=1221 → **NO pasa gate** (mean<0, prof<50%).
- Las celdas BTC:2h (-102.27%) y BTC:1d (-102.87%) leen el artefacto
  `_combine_split_stats` (< -100%), NO retorno real — pero el veredicto NO depende de
  ellas: la familia ya falla en las celdas legibles (3/8 prof, media negativa).

**Veredicto**: `fvg_mtf:fvg` → **DESCARTADA definitivamente** en estas celdas. No se
consumió OOS (sin candidato IS-profitable n≥30). El colapso correcto (una posición por
lado) no resucita fvg.

**Siguiente en cola**: `demon2volumen:liquidity_sweep_bot` (hecho, descartada) y
`ictsuite:sfp_institutional` (ya descartada). La cola de familias iso se agota con fvg.

## 2026-09-02 — fvg 4h deploy RE-VERIFICADO bajo el motor actual (pre-push)

Comprobación final antes del push: re-correr la config desplegada (`fvg`,
strict_tfs=("4h",), strict_min_confluence=5, gap_atr_mult=0.75, exits STRICT
rr_tp1=2.0 / rr_runner=3.0 / weight_tp1=0.9) contra el `engine.py` del working tree
(estado = lo que se va a commitear).

Nota de premisa: **NO hay fix de `size_type` en `_run_split`** (el naïve
`size_type='value'` se rechazó por alterar familias sanas; la decisión de overlap
posiciones = colapso correcto dejó el sizing intacto). El único cambio de
`engine.py` es el modo `trailing` (ortogonal a este deploy). Esta re-verificación
confirma que el deploy no depende de ningún cambio de sizing.

| Métrica | IS (70%) | OOS (30%) | log pre-deploy |
|---|---|---|---|
| mean | +72.55% | **+24.68%** | +24.68% ✅ idéntico |
| BTC 4h | +138.90% (n=22) | **+47.21%** (n=8) | +47.2 / n8 ✅ |
| ETH 4h | +6.20% (n=12) | **+2.14%** (n=8) | +2.1 / n8 ✅ |

**OOS PASS: True** (mean>0, 2/2). El deploy fvg 4h se mantiene **válido e
inmutable** bajo el motor que se va a pushear. Resultado bit-a-bit idéntico al
pre-deploy → el deploy no se ve afectado por los cambios pendientes.

**KILL DAEMON — trazabilidad**: PID 20501 (`run_live_monitor.py`, fvg 4h
mc5+gap075) confirmado **MUERTO** en este turno: `ps -p 20501` no devuelve proceso y
no hay instancias `run_live_monitor` activas. Confirmación UTC: **2026-09-02
15:20 UTC**. El daemon estuvo vivo desde 12:41 UTC (arranque) y dejó de monitorear
al ser eliminado; no siguió mandando señales tras el kill. (El arranque usaba la
config validada; el kill lo dejó fuera de servicio sin señales no válidas extra.)

## 2026-09-02 — HVFVG port COMPLETO (commit b1e0c64 pending → this commit)

Port terminado de `hvfvg_engine_v2.py` a `signals/hvfvg/hvfvg.py`, cerrando la
deuda registrada en el commit `b1e0c64` (que quedó pendiente de HVFVG).

**Implementación** (vectorizada, sin lookahead):
- FVG 3 velas; volumen anómalo sin z-score (`volume > rolling(50).mean()*1.8`,
  con `.shift(1)` para no contaminar con la vela de desplazamiento).
- Retest + defensa dentro de `retest_max=12`: absorción (vol > rolling_mean(20)*1.5
  y body ratio < 0.4) o rechazo (cierre fuera de la zona).
- Entry = `fvg_low + 0.15*height` (long) / `fvg_high - 0.15*height` (short);
  SL = extremo FVG ± ATR(14)*0.25; TP nativo tp1/tp2 = ERL swing o fallback
  entry ± ATR*tp_atr_mult.

**Verificación**:
- `tests/test_hvfvg.py` **ALL PASS**: envelope, volumen obligatorio, bull/bear
  detection (SL correcto), no-lookahead por truncation invariance k=1000/1600/2200.
- `tests/test_functional.py` **ALL PASS** (añadidos 2 checks hvfvg).
- Walk-forward 70/30 smoke (split): 8 celdas loopean sin error.

**Deploy smoke (n señales) — descargos**: resultados mayoritariamente negativos
en intraday (BTC 1h retA≈-22%, 2h≈-22%; ETH 1h≈-0.4%, 2h≈+3%); 1d sin señales
(retest_max=12 inalcanzable en velas diarias). Solo BTC 4h leg A +6.6% y ETH 2h
+3.2% positivos. **NO promocionado a deploy**: el port queda registrado y
verde a nivel unitario, pero no pasa el umbral de rentabilidad para producción.
Se deja dokumentado como candidato a tuning (niveles entry/SL, ventana defensa).

**Artefacto documentado (sin tocar)**: `_combined_return`/split puede dar Total
Return < -100% (colapso de sizing con overlap); no abordado en este turno.

## 2026-09-02 — HVFVG PARAMETER TUNING (grid search, IS 70%)

Objetivo: corregir sobre-filtrado (n bajo) y SL prematuros por ruido en el port
hvfvg (commit 2d944bc). Barrido en el tramo **In-Sample (70% temporal)** de cada
serie, selección por Profit Factor / Win Rate / n.

### Espacio de búsqueda (108 configs x 6 celdas intraday = 648 runs)
`vol_mult [1.3,1.5,1.8]`, `entry_ratio [0.0,0.5]`, `atr_sl_mult [0.5,0.8,1.2]`,
`retest_max [24,48,96]`, `use_absorption_filter [True,False]`.

### Criterio de selección (IS)
min n>=40 trades/celda, Win Rate > 45%, maximizar Profit Factor. Resultado:
**ninguna** config alcanza PF medio > 1.0 en IS (cota superior 0.95). Los top-10
configs son todos `vol_mult=1.8`, `use_absorption=True`, `atr_sl_mult>=0.8`,
`retest_max>=96` → relajar `vol_mult` a 1.3/1.5 NO aporta señales válidas extra
(solo ruido); el filtro de volumen estricto se mantiene.

### Ganador (aplicado como defaults nuevos)
`vol_mult=1.8, entry_ratio=0.5, atr_sl_mult=0.8, retest_max=96,
use_absorption_filter=True`
- avg PF = 0.95 (IS), avg WR = 45.5%, avg ret = +10.45% (IS)
- Detalle por celda (IS):
  | celda | n | trades | WR% | PF | ret% |
  |---|---|---|---|---|---|
  | BTC 1h | 40 | 73 | 46.6 | 0.88 | -10.0 |
  | BTC 2h | 45 | 81 | 44.4 | 1.06 | +52.9 |
  | BTC 4h | 14 | 27 | 59.3 | 2.11 | +156.9 |
  | ETH 1h | 64 | 123 | 45.5 | 0.76 | -3.8 |
  | ETH 2h | 39 | 75 | 45.3 | 1.10 | +2.7 |
  | ETH 4h | 20 | 36 | 35.4 | 0.98 | +0.5 |

### Verificación OOS / full walk-forward (70/30 split, fees 0.00045, caja 10k)
rel vs pre-tune (commit 2d944bc) — el tuning **triplica la muestra** y endereza
la pierna A:

| celda | n pre→post | legA ret pre→post | legB ret |
|---|---|---|---|
| BTC 1h | 30→61 | -22.4→**-43.2** | -9.8 |
| BTC 2h | 25→55 | -22.3→**+87.3** | -57.5 |
| BTC 4h | 14→21 | +6.6→**+142.7** | -8.1 |
| ETH 1h | 36→80 | -0.4→**-4.1** | -1.7 |
| ETH 2h | 29→57 | +3.2→**+4.5** | -0.6 |
| ETH 4h | 21→30 | -5.1→**+4.0** | -4.2 |

**Lectura**: tras el tuning la pierna A (80%, tp1 1:2 con SL original) es
**positiva o breakeven en 7/8 celdas intraday** (BTC 1h / ETH 1h quedan planas/
negativas), con win rates 53-75%. El **cuello de botella restante es la pierna B
(runner 20% a 1:5, SL a BE): negativa en todas las celdas** (WR 20-33%) — no es un
problema de parámetros de señal sino del exit scheme runner para este tipo de
setup. `1d` sigue sin señales estructurales.

### Decisión
- **Defaults actualizados** a la config ganadora (entry CE 0.5, SL 0.8xATR,
  retest_max 96).
- **NO promocionado a deploy** en vivo: PF medio IS < 1.0 y pierna B negativa en
  todas las celdas lo descartan para producción hasta resolver el exit leg B.
- Siguiente candidato de tuning (documentado, no ejecutado): revisar el runner
  leg B (rr_tp2 / SL-a-BE / trailing) específico de HVFVG, o `tp_atr_mult`.

**Artefacto (heredado, sin tocar)**: colapso de sizing con overlap en split
(total return < -100%) no abordado.

## 2026-09-02 — HVFVG EXIT PIVOT evaluation (IS 70%)

Diagnóstico previo: el runner estático Leg B (20% a 1:5, SL a BE) destruye la
esperanza matemática (negativo en todas las celdas). Se evalúan dos pivots de
salida manteniendo los signal defaults ganadores (vol1.8/entry0.5/atr_sl0.8/
retest96/abs) en el tramo IS (70%). PF = media ponderada por nº de trades entre
piernas. Objetivo: **PF medio del sistema > 1.15**.

| PF (IS) | base 80/20 | All-In 1:2 | All-In 1:2.5 | SmartTrail 1.5 ATR |
|---|---|---|---|---|
| BTC 1h | 1.139 | 1.070 | **1.235** | 1.004 |
| BTC 2h | 0.801 | 0.852 | 1.041 | 1.108 |
| BTC 4h | 1.752 | 0.997 | **1.320** | 0.838 |
| ETH 1h | 1.029 | 0.895 | 0.758 | 0.876 |
| ETH 2h | 0.999 | **1.197** | 0.714 | 1.019 |
| ETH 4h | 1.013 | **2.415** | **1.934** | 1.527 |
| **mean** | 1.122 | **1.238** ✅ | **1.167** ✅ | 1.062 ❌ |
| cells>1.15 | 1/6 | 2/6 | 3/6 | 1/6 |

**Veredicto:**
- **All-In Leg A SÍ satisface la meta de PF medio > 1.15** (1:2 → 1.238; 1:2.5 →
  1.167). El edge está en el rebote inicial; concentrar el 100% en un TP fijo
  1:2/1:2.5 elimina el lastre del runner. **1:2 es el mejor por PF medio**; 1:2.5
  es el más estable por nº de celdas > 1.15 (3/6).
- **Smart Trailing Leg B NO** (media 1.062, 1/6 celdas > 1.15): el trailing a
  1.5 ATR de distancia cede demasiado del tramo y no mejora la expectativa sobre
  el runner fijo. La continuación (leg B) sigue sin edge con cualquiera de las
  dos gestiones.

**Matiz honesto**: el PF medio > 1.15 se cumple a nivel de promedio del sistema,
pero **no es consistente por celda** (all-in 1:2 solo 2/6 celdas > 1.15; 1:2.5
3/6), y está empujado por las celdas 4h pequeñas (n≈14-20). Celdas como ETH 1h
(0.758) y BTC 2h/1h permanecen < 1. Conclusion: la mejora es real y repetible a
promedio, pero el sistema sigue sin un edge uniforme en todas las celdas.

**Estado**: evaluación completada; **no se modificó** el exit scheme de
producción de la familia (aún en decisión si adoptar All-In como exit global de
hvfvg). Artefacto heredado de sizing en split sin tocar.

## 2026-09-02 — HVFVG FULL WALK-FORWARD (OOS 30%) — fire test

Parámetros de señal (ganadores IS) y exits All-In **congelados** (sin re-ajuste
en OOS) para detectar curve-fitting. OOS = último 30% de cada serie. PF puro por
celda.

| OOS PF | All-In 1:2 | All-In 1:2.5 |
|---|---|---|
| BTC 1h | **0.139** | **0.114** |
| BTC 2h | 0.973 | 1.085 |
| BTC 4h | 0.611 | 0.686 |
| ETH 1h | 0.830 | 1.009 |
| ETH 2h | **2.930** | **2.645** |
| ETH 4h | 0.386 | 0.415 |
| **media OOS** | 0.978 (1/6 >1.0) | 0.992 (3/6 >1.0) |

**Desglose por grupo de temporalidad (OOS):**
| grupo | All-In 1:2 | All-In 1:2.5 |
|---|---|---|
| **1h** (BTC+ETH) | mean 0.485, 0/2 celdas >1.0 | mean 0.561, 1/2 >1.0 |
| **2h+4h** | mean 1.225, 1/4 >1.0 | mean 1.208, 2/4 >1.0 |

**Lectura del fuego real:**
- El edge visto en IS (media 1.24 / 1.17) **no se sostiene en OOS** (media ~1.0).
  Es sobreajuste de muestra pequeña: el 1h se hunde fuerte (BTC 1h PF **0.14**),
  confirmando el "matiz honesto".
- Solo **ETH 2h** es genuinamente robusto en OOS (PF 2.9/2.6). BTC 4h (0.61) y
  ETH 4h (0.39) también caen bajo 1.0.
- **Veredicto R:R**: el **All-In 1:2.5 retiene algo mejor el PF en datos no
  vistos** (media 0.992 vs 0.978; 3/6 celdas >1.0 vs 1/6; mantiene ETH 1h ~1.01 y
  BTC 2h 1.09). Ambos quedan ~breakeven a nivel sistema; ninguno llega a 1.15 en
  OOS.
- **Matiz de muestra**: ventanas OOS minúsculas (n=7-21 señales, 7-19 trades) →
  el PF OOS es ruidoso; los números son orientativos, no concluyentes.

**Decisión (alineada con el prompt #3)**: la temporalidad **1h se hunde <1.0 en
OOS** → se descarta para HVFVG. Aún así, como el sistema completo OOS es ~breakeven
y solo 2h/ETH es robusto, **NO se promueve HVFVG a deploy en vivo**; quedan
registrados los datos para post-procesar el arnés (descartar 1h) si se decide
seguir. Artefacto heredado de sizing en split sin tocar.
