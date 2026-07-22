# 02 - Intérprete de Escenarios de Circuito

Esta habilidad explica qué recibe el agente en cada escenario del análisis por circuito y cómo
debe interpretarlo. El circuito, fechas, Top-N y cantidad de variables no son fijos:
dependen de la selección del usuario y de los resultados del cuaderno.

La interpretación debe usar el grafo de entrenamiento como marco principal. Las variables
top no son etiquetas aisladas: cada una debe relacionarse, cuando sea posible, con su modo
CHEC, su posición en el grafo, sus conexiones directas o preservadas y su camino conceptual
hacia `UITI_VANO`.

En el flujo MGCECDL actual, el cuaderno
`notebooks/project_flow/05_mgcecdl_circuit_analysis.ipynb` agrega un entregable adicional por
escenario: un HTML de grafo estimado. Ese grafo no es la matriz experta original; se deriva
de la capa de reconstrucción del modelo para las muestras del escenario y de una similitud
RBF entre variables. Se usa para explorar asociaciones inducidas por el modelo.

## Unidad de Análisis

La unidad operativa es el `FID_VANO` dentro del circuito seleccionado. El agente recibe
eventos filtrados para ese circuito-periodo y, a partir de ellos, tablas o resultados
agregados por vano.

Una tabla agregada por vano normalmente contiene:

- `FID_VANO`: identificador del vano.
- `CIRCUITO`: circuito al que pertenece.
- `UITI_VANO_PROM`: impacto promedio del vano en los eventos seleccionados.
- `N_APARICIONES`: cantidad de eventos asociados al vano.
- `RELEVANCIA_VARS`: ranking agregado de variables, si el dataframe ya incluye `_TOP_VARS`.
- Variables originales del evento que permitan reconstruir contexto operativo, por ejemplo
  `DURACION`, `TOT_USUS`, `PORC_APORTE_VANO`, equipo de proteccion, coordenadas o clima.

Interpretacion base:

- `UITI_VANO_PROM` habla de severidad promedio.
- `N_APARICIONES` habla de recurrencia.
- La combinacion de ambas permite distinguir vanos severos, cronicos o ambas cosas.
- El grafo permite explicar por que una variable puede ser coherente con severidad,
  recurrencia o ambas: por ejemplo, rutas hacia usuarios/duracion se conectan mas
  naturalmente con impacto, mientras que topologia, proteccion o clima pueden ayudar a
  describir condiciones repetitivas del tramo o del periodo.

## Que devuelve un escenario explicado

La funcion de graficos/interpretacion puede devolver un objeto con:

```python
{
  "eventos": df_eventos_con_TOP_VARS,
  "borda": serie_feature_a_puntaje_borda_crudo,
  "variables_normalizadas": serie_top_variables_score_0_1,
  "modos_normalizados": serie_modos_score_0_1,
  "graph_html_path": ruta_html_del_grafo_estimado_si_fue_generado
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
- `graph_html_path`: archivo interactivo guardado para el escenario. El notebook no debe
  depender de verlo inline; basta con que el HTML quede en
  `reports/mgcecdl-results/interactive_graphs/`.

## Metodología Común

Cada escenario sigue esta logica:

1. Construir tabla por vano desde los eventos filtrados.
2. Ordenar por el criterio del escenario.
3. Calcular el Top-N efectivo segun vanos disponibles.
4. Filtrar los eventos que pertenecen a esos vanos.
5. Calcular SHAP por evento solo para la seleccion.
6. Agregar variables por Borda ponderado.
7. Normalizar variables y modos para graficar.
8. Interpretar variable, modo y contexto operativo juntos.
9. Contrastar cada variable top con el grafo: ruta directa, ruta preservada o sin ruta
   documentada.
10. Si existe, registrar el HTML del grafo estimado del escenario como entregable
    interpretativo complementario.

## Relación Obligatoria con el Grafo

Para cada escenario, el agente debe revisar:

- Si las variables top estan en `features`.
- Si existen en el grafo alineado a la corrida.
- Si tienen camino dirigido hacia `UITI_VANO` o hacia nodos cercanos como `UITI`,
  `TOT_USUS`, `DURACION`, `PORC_APORTE_VANO` o `COD_CAUSA`.
- Si la conexion es directa o preservada por nodos originales no retenidos.
- Si la variable pertenece a un modo que conserva significado operativo aunque el modelo
  solo haya usado un subconjunto.
- Si el grafo mostrado proviene del cuaderno 05, leer sus aristas como asociaciones
  estimadas por reconstruccion MGCECDL. Sus pesos estan normalizados por la conexion maxima
  del grafo (`0-1`) y se presentan en notacion cientifica para evitar confundir valores muy
  pequenos con ceros exactos.

Si no hay ruta documentada, usar una frase explicita:

```text
No se encontró una relación documentada entre <variable> y UITI_VANO dentro del grafo
disponible. Su relevancia debe leerse como comportamiento del modelo, no como explicación
experta validada.
```

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
- Si domina clima/riesgo, hablar de condiciones asociadas al evento.

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

## Escenario de Fechas de Interés

Criterio esperado:

```text
filtrar eventos cuyo dia este en fechas_interes y luego ordenar por UITI_VANO_PROM
```

Pregunta que responde:

- Que vanos explican los dias o puntos criticos definidos por el usuario o por otro modulo.
- Que variables fueron mas relevantes para el modelo en esos eventos puntuales.

Como interpretarlo:

- Las fechas de interes son una ventana de foco.
- Si una fecha no tiene eventos despues del filtro, no debe narrarse como evidencia.
- Si el escenario concatena varias fechas, la interpretacion corresponde al conjunto de
  fechas, no necesariamente a cada dia por separado.

## Escenario de Frecuencia en Fechas de Interés

Criterio esperado:

```text
filtrar eventos cuyo dia este en fechas_interes y luego ordenar por N_APARICIONES
descendente, usando UITI_VANO_PROM como desempate si existe
```

Pregunta que responde:

- Que vanos se repiten mas dentro de los dias criticos o fechas definidas.
- Si la repeticion temporal puntual tiene el mismo soporte explicativo que la recurrencia
  del periodo completo.
- Que variables ayudan al modelo a describir vanos recurrentes en esas fechas.

Como interpretarlo:

- No equivale a severidad maxima; prioriza recurrencia dentro del subconjunto temporal.
- Si coincide con alto `UITI_VANO_PROM`, hablar de doble prioridad: frecuencia puntual e
  impacto promedio.
- Si domina clima, riesgo o fecha, la lectura debe limitarse a condiciones asociadas a los
  dias incluidos.
- Si dominan topologia o proteccion, la interpretacion puede apuntar a tramos o equipos que
  concentran repeticiones durante las fechas de interes.

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
- Una barra alta debe explicarse junto con el grafo: modo, ruta, tipo de conexion y
  significado operativo.
- Si una variable climatica aparece con lag, interpretar el sufijo horario: `lag_0` es la
  condicion mas cercana al evento; lags mayores son contexto previo.

## Radar por modos

El radar agrupa variables en modos CHEC y normaliza los puntajes a 0-1 dentro del mismo
escenario.

Lectura correcta:

- Modo dominante: familia que concentra la explicacion del modelo.
- Modo bajo: familia con poca participacion relativa.
- Comparar modos dentro del escenario es valido.
- Comparar valores crudos entre escenarios no es valido si cambia la cantidad de eventos.
- Un modo dominante no significa que todas sus variables sean relevantes. Revisar las
  variables concretas que aportan al modo.
- Si un modo original tiene pocas variables retenidas por seleccion, aclarar que la lectura
  corresponde al subconjunto disponible.

## Grafo HTML estimado por escenario

El grafo HTML del cuaderno 05 es la tercera salida del analisis por escenario, junto con
las barras y el radar. Reglas de lectura:

- El archivo se guarda como HTML interactivo; no es obligatorio renderizarlo dentro del
  notebook.
- Los nodos son las variables top del escenario y su tamano/color responde al puntaje
  normalizado de importancia.
- Las aristas se calculan desde la matriz estimada por el modelo para las muestras del
  escenario, usando reconstrucciones MGCECDL y similitud RBF.
- Se muestra una sola arista por par de variables, sin doble direccion ni flechas.
- El peso mostrado en tooltip ya esta normalizado por el maximo del grafo y se escribe en
  notacion cientifica, por ejemplo `1.000e+00` o `6.667e-03`.
- Un peso muy pequeno indica asociacion debil relativa dentro del grafo, no ausencia
  absoluta.

## Lectura operativa por familias

- Evento, impacto e indicadores: duracion, usuarios, causa e indicadores cercanos al
  objetivo; coherente con escenarios de severidad.
- Proteccion y maniobra: equipo que opera, tipo de proteccion, vanos protegidos y usuarios
  bajo proteccion; sugiere revisar selectividad, cobertura o tiempos de aislamiento.
- Topologia y configuracion espacial: circuito, vano, coordenadas, distancia a proteccion y
  aporte relativo; sugiere revisar posicion del tramo y concentracion de impacto.
- Caracteristicas fisicas y electricas del vano: longitud, fases, conductor, neutro,
  tipo de red, consumo y antiguedad; sugiere revisar condicion fisica/configuracion del
  tramo.
- Activos: apoyo final y transformador: apoyo, clase, norma, puesta a tierra, transformador,
  capacidad, usuarios y consumo; sugiere revisar activos asociados y concentracion de carga.
- Entorno, riesgo y clima: vegetacion, descargas y clima con lags; sugiere condiciones
  ambientales asociadas o predictivas.

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

## Si falta contexto

Cuando un resultado menciona una variable, relacion o modo no documentado, el agente debe
decirlo. Frases permitidas:

- "No se encontro una definicion explicita para esta variable."
- "La relacion entre estos elementos no esta documentada en los archivos disponibles."
- "Esta interpretacion debe tratarse como una hipotesis hasta que sea validada con
  conocimiento experto."
