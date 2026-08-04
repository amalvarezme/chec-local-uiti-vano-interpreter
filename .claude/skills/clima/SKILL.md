---
name: clima
description: "Trigger: /clima, actualizar clima v3, consulta de clima por puntos, agregar clima a una tabla, concatenar clima por origen. Enriquece datos con clima Open-Meteo: 3 gates interactivos (ubicaciones, API gratuita/paga, limites) y luego Modo A (actualizar v3) o Modo B (puntos por dia/rango, ancho, resumible)."
license: Apache-2.0
metadata:
  author: chec-local-uiti-vano-interpreter
  version: "0.2.0"
  engine: src/chec_local_interpreter/clima_engine.py
  runbook: .claude/skills/clima/assets/runbook.py
---

## Activation Contract

Load when the user says `/clima` or asks to enrich CHEC data with weather. Fully interactive:
select source, then run the 3 gates IN ORDER, then process the mode. All heavy logic lives in
[`clima_engine.py`](../../../src/chec_local_interpreter/clima_engine.py); the canonical calls are
in [`assets/runbook.py`](assets/runbook.py). This file is the runbook, not the reasoning.

## Hard Rules

- Selecciona la fuente primero, luego corre los gates en orden. Nunca proceses sin pasar los 3.
- **Gate 1 (ubicaciones) es bloqueante y va primero**: sin coordenadas validas, detente.
- La `apikey` (modo paga) la ESCRIBE el usuario, interactiva; solo en memoria, nunca la persistas ni la registres.
- Modo B deja SOLO el CSV de resultado en `data/`; el rate log va a `.clima_cache/`.
- Unificar/concatenar solo entre archivos con el MISMO `origen_id`.
- Run Python with the repo venv: `.venv/bin/python`.

## Decision Gates

| Fuente | Modo | Coordenadas | Salida |
|---|---|---|---|
| `data/Indicadores_vano_v3.csv` (fija) | A | `X1`,`Y1` | reescribe el mismo v3 |
| tabla que el usuario elige de `data/` | B | `XPOS1_RED_BASE`,`YPOS1_RED_AFECTA` | `data/clima_<fuente>_<ini>_a_<fin>.csv` |

## Execution Steps

1. Pregunta el **modo** (A / B). En B, lista `runbook.listar_tablas()` y pide elegir el archivo. STOP.
2. **Gate 1 — Ubicaciones**: `a_gate1()` (A) o `b_gate1(archivo)` (B). Si `ok` es False, detente y reporta.
3. **Gate 2 — API**: pregunta gratuita o paga. Si paga, pide la `apikey` y usa `config_paga(apikey)`; si no, `config_gratuita()`. STOP para la apikey.
4. **Gate 3 — Limites**: compara `a_gate3_necesarios()` / `b_gate3_necesarios(...)` contra `presupuesto_disponible(config)`.
   Si necesarios > disponible, pregunta si acepta el **bloque maximo** (= disponible) y deja el resto pendiente. STOP.
5. **Procesar**:
   - **Modo A**: `a_ejecutar(config, limite_filas=bloque)` (o `None` si entra todo). Reporta el `mensaje`.
   - **Modo B**: `b_calcular(archivo, modo, ini, fin, config, limite_coords=bloque)`; luego `b_previas(res)`.
     Si hay previas del mismo `origen_id`, pregunta **unificar** (`b_unificar_y_guardar`) o **aparte** (`b_guardar`). STOP.
6. **Concatenar** (a pedido): `concatenar([nombres])` valida `origen_id` y devuelve el ancho unido.

En modo `dia` pasa `fin = ini`. Al reanudar un bloque pendiente, vuelve a correr el paso 5 con el mismo archivo/rango.

## Output Contract

Reporta: modo; resultado de cada gate; para A el mensaje (actualizado / pass-through / pendientes);
para B la ruta del CSV, su `origen_id`, filas, columnas de clima, si hubo unificacion y cuantas quedaron pendientes.

## References

- `src/chec_local_interpreter/clima_engine.py` — motor (gates, fetch, Modo A/B, origen, unify, concat).
- `assets/runbook.py` — snippets de invocacion por paso.
- Reemplaza (ya retirados) los cuadernos `01_climate.ipynb` (Modo A) y `01_clima_diario_red_kaggle.ipynb` (Modo B); ver git history.
