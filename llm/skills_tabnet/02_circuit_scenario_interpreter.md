# 02 - Circuit Scenario Interpreter

Esta skill explica que recibe el agente en cada escenario del analisis por circuito y como
debe interpretarlo. El circuito, fechas, Top-N y cantidad de variables no son fijos:
dependen de la seleccion del usuario y de los resultados del cuaderno.

## Unidad de analisis

La unidad operativa es el `FID_VANO` dentro del circuito seleccionado. El agente recibe
eventos filtrados para ese circuito-periodo y, a partir de ellos, tablas o resultados
agregados por vano.

Una tabla agregada por vano normalmente contiene:

- `FID_VANO`: identificador del vano.
- `CIRCUITO`: circuito al que pertenece.
- `UITI_VANO_PROM`: impacto promedio del vano en los eventos seleccionados.
- `N_APARICIONES`: cantidad de eventos asociados al vano.
- `RELEVANCIA_VARS`: ranking agregado de variables, si el dataframe ya incluye `_TOP_VARS`.

Interpretacion base:

- `UITI_VANO_PROM` habla de severidad promedio.
- `N_APARICIONES` habla de recurrencia.
- La combinacion de ambas permite distinguir vanos severos, cronicos o ambas cosas.

## Que devuelve un escenario explicado

La funcion de graficos/interpretacion puede devolver un objeto con:

```python
{
  "eventos": df_eventos_con_TOP_VARS,
  "borda": serie_feature_a_puntaje_borda_crudo,
  "variables_normalizadas": serie_top_variables_score_0_1,
  "modos_normalizados": serie_modos_score_0_1
}
```

Como leer cada campo:

- `eventos`: filas reales usadas para explicar el escenario. Permite revisar cuantos eventos
  sostienen la conclusion.
- `borda`: puntaje acumulado por variable antes de normalizar. Sirve para ranking interno,
  no para comparar escenarios con distinto numero de eventos.
- `variables_normalizadas`: Top de variables en escala 0-1 dentro del escenario. Sirve para
  narrar importancia relativa.
- `modos_normalizados`: peso relativo de cada modo CHEC dentro del escenario.

## Metodologia comun

Cada escenario sigue esta logica:

1. Construir tabla por vano desde los eventos filtrados.
2. Ordenar por el criterio del escenario.
3. Calcular el Top-N efectivo segun vanos disponibles.
4. Filtrar los eventos que pertenecen a esos vanos.
5. Calcular SHAP por evento solo para la seleccion.
6. Agregar variables por Borda ponderado.
7. Normalizar variables y modos para graficar.
8. Interpretar variable, modo y contexto operativo juntos.

## Escenario de severidad por UITI_VANO

Criterio esperado:

```text
ordenar por UITI_VANO_PROM descendente
```

Pregunta que responde:

- Cuales vanos tienen mayor impacto promedio en el periodo analizado.
- Que variables uso el modelo para explicar los eventos de esos vanos.

Como interpretarlo:

- Alto `UITI_VANO_PROM` no significa automaticamente alta frecuencia.
- Si domina un modo de usuarios, duracion o proteccion, la lectura apunta a escala del
  impacto operativo.
- Si domina topologia, ubicacion o activos, la lectura apunta a condiciones estructurales
  del tramo o su posicion.
- Si domina clima/riesgo, hablar de condiciones asociadas al evento, no de causa probada.

## Escenario de recurrencia por frecuencia

Criterio esperado:

```text
ordenar por N_APARICIONES descendente, usando UITI_VANO_PROM como desempate si existe
```

Pregunta que responde:

- Cuales vanos aparecen mas veces en los eventos del periodo.
- Si la recurrencia tiene los mismos patrones explicativos que la severidad.

Como interpretarlo:

- Alta frecuencia con bajo impacto promedio: comportamiento cronico pero contenido.
- Alta frecuencia con alto impacto promedio: prioridad operativa fuerte.
- Variables dominantes en este escenario pueden describir repeticion del patron, no
  necesariamente magnitud del dano.

## Escenario de fechas de interes

Criterio esperado:

```text
filtrar eventos cuyo dia este en fechas_interes y luego ordenar por UITI_VANO_PROM
```

Pregunta que responde:

- Que vanos explican los dias o puntos criticos definidos por el usuario o por otro modulo.
- Que variables fueron mas relevantes para el modelo en esos eventos puntuales.

Como interpretarlo:

- Las fechas de interes son una ventana de foco, no una demostracion causal.
- Si una fecha no tiene eventos despues del filtro, no debe narrarse como evidencia.
- Si el escenario concatena varias fechas, la interpretacion corresponde al conjunto de
  fechas, no necesariamente a cada dia por separado.

## Barras de variables

Las barras representan variables ordenadas por importancia relativa dentro del escenario.
El flujo es:

```text
Kernel SHAP por evento -> abs(SHAP) -> Top-K por evento -> Borda ponderado -> min-max 0-1
```

Lectura correcta:

- Barra alta: variable consistentemente importante para la salida del modelo en ese
  escenario.
- Barra presente pero baja: variable secundaria dentro del Top-K.
- Scores cercanos no deben sobre-interpretarse como diferencias fuertes.

## Radar por modos

El radar agrupa variables en modos CHEC y normaliza los puntajes a 0-1 dentro del mismo
escenario.

Lectura correcta:

- Modo dominante: familia que concentra la explicacion del modelo.
- Modo bajo: familia con poca participacion relativa.
- Comparar modos dentro del escenario es valido.
- Comparar valores crudos entre escenarios no es valido si cambia la cantidad de eventos.

## Forma recomendada de respuesta

Para cada escenario, el agente debe explicar:

- Que recibio: eventos, vanos, criterio, Top-N efectivo.
- Que variable o grupo domina.
- Que modo CHEC domina.
- Que significa electricamente.
- Que limitacion aplica.

Usar siempre lenguaje de modelo:

```text
El modelo asigno mayor relevancia a...
```

No usar lenguaje causal fuerte:

```text
La variable causo...
```
