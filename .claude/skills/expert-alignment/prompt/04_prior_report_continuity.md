# Continuidad con el Reporte Previo del Circuito

## Propósito

Cuando existe un reporte previo completo del mismo circuito, sus conclusiones se reutilizan
como una fuente adicional de evidencia: filas normalizadas con la misma forma que
`pdf_expert_matches`, marcadas con `source_kind: "prior_report"` y `confidence: "baja"`. Esta
habilidad indica cómo tratar esas filas sin confundirlas con evidencia experta validada por
humanos.

## Qué es (y qué NO es) una fila del reporte previo

- Una fila `source_kind: "prior_report"` es una síntesis que un modelo produjo en una ejecución
  anterior sobre el mismo circuito. Es continuidad temporal, no evidencia experta independiente.
- NO es una fila del Modelo Experto (`pdf_expert_matches` sin `source_kind`, extraída de PDFs
  humanos). NO la trates como si viniera de un documento experto.
- NO ha sido validada por una persona experta; es una interpretación previa del propio modelo,
  potencialmente heredando sus mismos sesgos o errores.

## Reglas de uso

- Cita las filas del reporte previo como fuente `Reporte previo del circuito`, nunca como
  `Modelo Experto` ni como archivo `CIRCUITO.pdf`.
- Usa frases explícitas de tentatividad: "según el reporte previo", "de forma tentativa", "a
  confirmar con evidencia adicional".
- Una fila del reporte previo, por sí sola, NUNCA debe justificar una `prioridad: "alta"` en
  `variables_a_priorizar`. Solo puede reforzar una prioridad ya respaldada por al menos otra
  fuente (Agente Descriptor, Agente predictivo o Modelo Experto).
- Si una fila del reporte previo entra en conflicto con evidencia de un PDF experto o con un
  hallazgo humano-validado para el mismo periodo, la evidencia PDF/humana prevalece. Señala el
  conflicto explícitamente en `diferencias` en lugar de ocultarlo.
- Si no hay evidencia adicional (Agente Descriptor, Agente predictivo o Modelo Experto) que
  respalde una fila del reporte previo, preséntala en `diferencias` o como contexto de baja
  confianza, nunca como una coincidencia fuerte.

## Lenguaje

- Mantén el registro cauteloso general de esta Skill y agrega el matiz de tentatividad propio
  de esta fuente: "según el reporte previo del circuito, de forma tentativa, ...".
- No repitas literalmente la síntesis previa como si fuera un hallazgo nuevo; contrástala con la
  evidencia actual antes de mencionarla.

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
