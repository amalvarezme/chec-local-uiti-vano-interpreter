# 02 - Intérprete de Escenarios por Ventana

Esta habilidad explica qué recibe el agente en cada escenario y cómo debe interpretarlo.

**Un escenario ES una ventana.** El informe estudia tres: la última con eventos del
circuito, que describe cómo está hoy, y las dos de mayor influencia, que explican qué lo
trajo hasta aquí. No son percentiles de filas ni recortes por severidad.

## Unidad de Análisis

La unidad es la **bolsa**: la celda `(vano, ventana)`. Es la unidad sobre la que el
cuaderno 04 define la criticidad y sobre la que opera el simulador del cuaderno 06, así
que el informe y el tablero responden con el mismo modelo y la misma unidad.

El modelo predice **`uiti_acumulado`, y solo eso**.

El **conteo de eventos no es una salida del modelo**: es un eje del espacio K-Means que,
junto con el UITI, fija la clase de la bolsa. Puedes citarlo como dato observado, pero
nunca atribuírselo al modelo. Escribir "el modelo indica que esta variable eleva la
frecuencia de eventos" es una frase plausible, imposible de distinguir de una correcta al
leer el informe, y que el modelo no respalda. El validador la rechaza.

## Qué trae cada escenario

- `ventana` y `nombre`: la etiqueta (`V1`..`V11`) y el nombre citable del escenario.
- `n_vanos`: cuántos vanos del circuito tienen bolsa en esa ventana.
- `relevancia.vanos`: por vano, su `u_base`, su `clase_base` y las variables que pueden
  bajarle el UITI.
- `variables_por_grupo`: ese mismo ranking, partido en **Intervención** y **Escenario**.
- `vanos_criticos`: hasta 15 vanos, primero los del grupo Alto y luego Medio-Alto, cada uno
  con el plan que lo baja de clase.
- `simulacion`: qué le pasa al UITI y al grupo de esos vanos si se ejecuta el plan, más el
  grafo diferencia.

## Intervención contra Escenario

Es la distinción que sostiene el informe, y hay que respetarla al redactar.

- **Intervención**: poda, altura, conductor, calibre del neutro, puesta a tierra, número de
  fases, capacidad, tipo de protección. Una cuadrilla las ejecuta. Es lo que puede
  convertirse en una orden de trabajo.
- **Escenario**: lluvia, viento, ráfaga, temperatura, consumo. Describen la condición en la
  que ocurre el problema. **No se ejecutan.** No desaparecen del modelo: entran con el
  valor observado de cada vano, que es lo que corresponde; lo único que no hacen es
  moverse.

Una variable de escenario suele encabezar el ranking por caída de UITI. Presentarla junto
a la poda como si fueran equivalentes produce una recomendación que nadie puede comprar.
Nómbrala por lo que es.

## Cómo leer el ranking de variables

Cada fila trae:

- `n_vanos_alcanza` / `n_vanos`: en cuántos vanos **esa sola variable** basta para caer al
  grupo Bajo. Es la magnitud que manda: una variable que baja mucho el UITI sin cruzar
  ninguna frontera de grupo no cambia ninguna decisión.
- `avance_mediano`: qué fracción del camino al grupo Bajo cubre esa sola variable. Es
  `null` cuando el vano ya está en el grupo más bajo o cuando ese grupo es inalcanzable con
  sus eventos: ahí no hay camino que medir.
- `valor_tipico`: el valor que consigue el mínimo. Es lo que convierte la fila en una
  instrucción ("lleva `ALTURA` a 18 m") en vez de un puntaje.

La relevancia se mide recorriendo el **interior** del rango de cada control, no solo sus
extremos: 10 de los 15 controles numéricos tienen su mejor valor dentro del rango. Y se
mide **con signo**, hacia el mínimo.

En Medio-Alto y Alto **ninguna variable sola** alcanza el grupo Bajo. Cuando el plan
necesita varios pasos, dilo: un ranking que insinúa lo contrario promete un cambio de grupo
que una sola obra no consigue.

## Cómo leer la simulación

`simulacion` mueve **solo palancas de intervención**, sobre los vanos que el diagnóstico
señaló. Trae, por vano, `u_base` contra `u_simulado` y `clase_base` contra `clase_simulada`.

- `delta_grupo` negativo: el vano baja de grupo. Es el resultado que sostiene la obra.
- `delta_grupo` cero con caída de UITI: la obra mejora el vano sin cruzar la frontera.
  Dilo así; presentarlo como un cambio de grupo sería falso.
- `knobs_usados` vacío: no había palancas de intervención disponibles en esa ventana.

## Cómo leer el grafo diferencia

Es la **diferencia**, no el antes y el después. El grafo reconstruido es casi todo pesos
fijos del experto — las compuertas del MIL solo los reescalan —, así que los dos grafos se
ven iguales lado a lado y el efecto de la intervención, que es lo único que interesa,
queda invisible. Por eso se muestra qué cambió.

Se reconstruye de las compuertas del propio MIL, no de una aproximación RBF sobre otro
modelo.

Si el grafo falta, el escenario trae `grafo_motivo`. Dilo en vez de callarlo: un panel
ausente sin explicación se lee como "la intervención no movió nada", que es lo contrario de
"no hay vanos suficientes para reconstruirlo".

## Forma recomendada de respuesta

Para cada ventana, explica:

- Qué recibió: ventana, periodo, número de vanos, cuántos críticos.
- Qué palanca de **intervención** manda, y con qué valor.
- Qué condición de **escenario** acompaña, nombrada como tal.
- Qué consigue la simulación: cuántos vanos bajan de grupo y cuántos no.
- Qué limitación aplica.

Usa siempre lenguaje de modelo: "el modelo asignó mayor relevancia a…", "es consistente
con…", "podría estar asociado con…", "requiere validación".

## Si falta contexto

Cuando un resultado menciona una variable o relación no documentada, dilo:

- "No se encontró una definición explícita para esta variable."
- "Esta interpretación debe tratarse como una hipótesis hasta que sea validada con
  conocimiento experto."
