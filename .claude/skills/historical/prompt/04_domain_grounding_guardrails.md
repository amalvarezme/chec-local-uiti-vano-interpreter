# Reglas de Anclaje de Dominio

Usa el contexto de dominio de `ContextoProyectoSimuladorCHEC.md` únicamente como anclaje
para el dataset estructurado. Trátalo como guía interpretativa, no como prueba.

## Guía Compacta de Dominio

- Los rezagos climáticos pueden indicar estrés ambiental acumulado.
- `NR_T` (nivel de riesgo de vegetación) y `DDT` (densidad de descargas a tierra) son variables **siempre presentes** en la tabla de estudio; deben analizarse en todos los informes como posibles moduladores de eventos y `UITI_VANO`.
- La precipitación, el viento y las ráfagas pueden respaldar hipótesis ambientales junto con `NR_T` y `DDT`.
- El conductor, la longitud, las fases, el neutro/cable de guarda y la taxonomía describen susceptibilidad.
- `LVSW`, `CNT_VN`, `FID_VANO` y `CIRCUITO` describen la topología y el contexto de propagación.
- Los equipos de protección y los usuarios protegidos ayudan a explicar el alcance del impacto y el contexto de restablecimiento.
- Las variables de activos ayudan a describir vulnerabilidad y exposición.
- La duración y los usuarios afectados ayudan a explicar el impacto de la interrupción a nivel de evento.

## Lenguaje Prohibido

- "demuestra que"
- "segun la normativa"
- "la bitacora evidencia"
- "el modelo predice"
- "no se tienen datos de DDT"
- "DDT no está disponible"
- "no hay información de vegetación"
- "NR_T no está disponible"
- "no contamos con datos de DDT"
- cualquier frase que indique ausencia de datos para `DDT` o `NR_T`

## Lenguaje Preferido

- "sugiere"
- "es compatible con"
- "podría estar asociado con"
- "la evidencia tabular muestra"
- "dentro de las variables disponibles"
- "no se puede confirmar con esta versión local"

## Como se nombran las cosas en el informe

Lo escrito aqui lo lee alguien que opera la red, no quien programo el flujo.

### Variables: nombre en castellano, y el codigo entre parentesis

Escribe `Riesgo por vegetacion cercana al vano (NR_T)`, no `NR_T` a secas. El contexto te
entrega los dos: cada grupo de `domain.variable_groups` trae `variables` (los codigos) y
`variables_nombradas` (los mismos codigos ya con su nombre delante). Usa el nombre la
primera vez que aparece una variable en cada seccion; despues basta el codigo.

El codigo NO se omite: es lo que hay que buscar en el dataset y en el tablero, y un
informe que solo diera el nombre obligaria a traducir de vuelta a mano.

Las series de clima conservan su rezago: `Temperatura del aire (temp_3)` es la
temperatura tres horas antes del evento, y `temp_3` y `temp_9` no son lo mismo.

### Nunca nombres de codigo

No escribas identificadores de maquina, nombres de funcion, de modulo, de archivo ni de
proceso interno. Nada de `topology_protection`, `weather_environmental_stress`,
`relevancia_hacia_uiti_minimo`, `_compute_inference_scenarios`, `KMeans`, `plegar_rezagos`
ni rutas de archivo. Las reglas de dominio del contexto vienen con un `nombre` en
castellano: usa ese nombre, o describe la relacion con tus palabras.

Un identificador en snake_case ingles dentro de un informe para operacion no aclara nada:
hace parecer que el texto lo escribio el programa, y quien lo lee no puede comprobarlo
contra nada que tenga delante.

Describe el METODO por lo que hace, no por como se llama. "Se probaron valores a lo largo
del rango observado de cada variable de intervencion" dice mas que el nombre de la funcion
que lo hace.

### Dos escalas de criticidad, y no se mezclan

Son cosas distintas y comparten palabras, que es exactamente por lo que se confunden:

- **La banda del CIRCUITO** es `selected_context.characterization[].criticidad`, y sale del
  mismo calculo que pinta la barra del ranking que el lector tiene delante. Sus valores son
  `Riesgo Bajo`, `Riesgo Medio`, `Riesgo Medio-Alto` y `Riesgo Alto`. Cita el valor que te
  llega, textual. **No inventes ninguna otra etiqueta**: "Riesgo Muy Alto" y "Riesgo
  Medio-Bajo" NO existen en esta escala, y escribirlas contradice la figura.
  Acompanala del puesto: `posicion` de `circuitos_en_la_flota`.
- **La clase de un VANO en una ventana** es `Bajo`, `Medio`, `Medio-Alto` o `Alto`, sin la
  palabra "Riesgo" delante. Es la clase de una bolsa (vano, ventana), no del circuito.

Al escribir cualquiera de las dos, di de que es: "el circuito esta en Riesgo Medio-Alto" o
"nueve vanos estan en Medio-Alto". Sin ese sujeto, un lector que ve las dos frases seguidas
cree que el informe se contradice.

### Ortografia y gramatica: el informe se escribe en castellano correcto

Todo lo que escribes se imprime tal cual en un documento que lee personal de la empresa.
**Escribe con tildes.** Un informe sin tildes se lee como una salida de maquina, y ese es
justo el efecto contrario al que este documento busca.

Las que mas se escapan, y estan en casi todas las frases de este dominio:

| Sin tilde (mal) | Con tilde (bien) |
| --- | --- |
| vegetacion, proteccion, intervencion, simulacion, ubicacion, radiacion, precipitacion, presion, duracion, interrupcion, energizacion, relacion, seccion, atencion, correlacion | vegetación, protección, intervención, simulación, ubicación, radiación, precipitación, presión, duración, interrupción, energización, relación, sección, atención, correlación |
| analisis, diagnostico, hipotesis, metrica, periodo, maximo, minimo, numero, indice, ultimo, proximo, energia, topologia, taxonomia, categoria, dia | análisis, diagnóstico, hipótesis, métrica, período, máximo, mínimo, número, índice, último, próximo, energía, topología, taxonomía, categoría, día |
| electrica, mecanica, fisica, climatica, atmosferica, geografica, critico, tecnico, practico, automatico | eléctrica, mecánica, física, climática, atmosférica, geográfica, crítico, técnico, práctico, automático |
| esta (verbo), mas, aun, solo (adverbio), asi, tambien, ademas, segun, despues, aqui, alli, quiza | está, más, aún, sólo→**solo** (ya no se tilda), así, también, además, según, después, aquí, allí, quizá |

Reglas que ademas se olvidan:

- Las interrogaciones y exclamaciones llevan **los dos** signos: `¿...?`, `¡...!`.
- La `ñ` es una letra: `año`, `diseño`, `mañana`, `pequeño`. Nunca `anio` ni `ano` —
  "ano" y "año" no significan lo mismo, y el error es visible.
- Los nombres de columna del dataset **no se acentuan ni se traducen dentro del
  parentesis**: se escribe `Precipitación (PREP_0)`, nunca `Precipitación (PREP_0́)`.
- Concordancia de genero y numero: "el modelo restringido", "la ventana estudiada",
  "los nueve vanos criticos" -> "los nueve vanos críticos".
- Los numeros con decimales van con coma decimal y punto de miles: `6.729,53`.

Antes de entregar, relee tu texto buscando terminaciones en `-cion`, `-sion`, `-ia`,
`-ico` y `-ica` sin tilde: ahi esta la mayoria de los errores.
