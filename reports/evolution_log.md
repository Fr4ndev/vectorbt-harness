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

### Cola: mutaciones pendientes (in-sample → OOS único)

Las familias UNPROFITABLE en la tabla necesitan **mutación in-sample** (cambiar
params, adds filters, ajustar exits) hasta alcanzar IS profitable, y solo
entonces un único OOS check. Orden de prioridad:

1. **`fvg_mtf:fvg`** (−16.81, 3/8, n=2122): el pullback de fvg, no la
   inversión. Tiene n alto; podría beneficiarse de filtros de régimen o ajuste
   de SL para reducir la caída en celdas negativas (BTC 1d −102.8, BTC 2h
   −102.9). Si se puede convertir en profitable → buen candidato por volumen
   de señales.
2. **`fib_retrace`** (−53.94, 0/8, n=2718): retracement Fibonacci multi-TF.
   Con n alto y 0/8 celdas rentables, necesita un cambio estructural significativo
   (SL/invalidation, possibly drop to simpler exits). Bajo prioridad por
   profundidad del tuning necesario.
3. **`demon2:po3`** (−57.42, 1/8, n=2118): Power of 3 clásico. Una sola celda
   positiva (BTC 4h) no compensa. Requiere revisión de la condición AMD
   (manipulación + distribución) y SL.
4. **`ictsuite:sfp`** (−58.32, 0/8, n=5586): SFP clásico. Refutado; `sfp_institutional`
   ya lo reemplaza con peores números pero menos ruido. Descartar o asignar a
   `sfp_institutional` como familia sucesora.