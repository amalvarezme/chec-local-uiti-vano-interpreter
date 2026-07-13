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
