# Revisión del informe de criticidad por circuito

Estado de aplicación de los comentarios de `Ajuste Reporte criticidad circuito html.docx`,
y qué se traslada al informe gerencial.

Rama: `revision-informe-html-criticidad`. Suite: 3.230 pasan, 52 saltadas.

---

## 1. Comentarios del revisor

| # | Comentario | Estado | Solución |
|---|---|---|---|
| 1 | Valores generales en el encabezado: aporte UITI, vanos probables de causa de falla, longitud total, urbana y rural, transformadores | Aplicado | Módulo nuevo `ficha_circuito`. Longitud y transformadores salen de `MVLINSEC.LONGITUD`/`CLASIFICAC` y `GDBCHEC_TRANSFOR`, los mismos shapefiles que ya lee el mapa. Medido en DON23L13: 214,9 km (2,1 urbana / 209,4 rural), 204 transformadores |
| 2 | Explicar al comienzo cómo se conforman las ventanas | Aplicado | Bloque fijo antes de todo: ventanas de 30 días que avanzan de 15 en 15, la bolsa `vano × ventana`, por qué existe el solape y por qué los valores no son aditivos |
| 3 | Clasificación de criticidad en tabla, con el número de ubicación en la gráfica y en la tabla | Aplicado | Tabla con el circuito y sus vecinos visibles, las 208 filas plegadas. Los rótulos de la barra pasan a `1. DON23L13` |
| 4 | Donde diga «cantidad de eventos», poner «vanos probables de causa de falla» | **Parcial, a propósito** | Ver §2 |
| 5 | Resumen ejecutivo en cuatro bloques | Aplicado | Ficha comparativa, ventanas de mayor aporte, vanos de mayor impacto y la prosa del agente |
| 6 | «Circuitos de la flota» → «circuitos totales» | Aplicado | Módulo `vocabulario_informe`, aplicado al pintar: los informes ya archivados cambian sin volver a gastar un token |
| 7 | No queda clara la diferencia entre ventana pico y ventana de mayor impacto | Aplicado | No hay diferencia. Se unifican en «ventana de mayor aporte UITI» y se dice explícitamente que son la misma |
| 8 | Notas de lectura en Hallazgos: traslape, suma que duplica, lectura descriptiva | Aplicado | Las tres, literales, al frente de la sección 2 |
| 9 | Ventanas estudiadas: tabla con fechas, aporte UITI, registros y vanos, más resumen comparativo | Aplicado | Tabla calculada sobre la misma rejilla que usa el modelo. La comparación en prosa se conserva debajo, y se omite cuando el agente entrega solo etiquetas |
| 10 | Análisis de vanos: mayor aporte UITI, más apariciones, y los coincidentes | Aplicado | Subsección 2.4, tres columnas. Recupera dos listas que se habían retirado; la intersección resuelve el motivo por el que se retiraron |
| 11 | Inferencias complementarias dentro del punto de ventanas | Aplicado | Bajan al análisis por ventana, marcadas como proyección y no como observación |
| 12 | Primera frase de la hipótesis sin viñeta | Aplicado | `_hipotesis_html`: la frase de contexto va como párrafo, el resto en viñetas |
| 13 | Eliminar «Caracterización del circuito» y llevar las justificaciones físico-lógicas a Hallazgos | Aplicado | La sección desaparece; el contenido útil se muda |
| 14 | Mapa más pequeño, con opción de pantalla completa | Aplicado | 560 → 380 px, botón de pantalla completa que reencuadra el iframe |
| 15 | Flechas a lado y lado del deslizador de ventanas | Aplicado | Con deshabilitado en los extremos |
| 16 | Síntesis del modelo como cierre del numeral 2 | Aplicado | Cierra la sección 2, antes de la hipótesis |
| 17 | Numerales | Aplicado | Secciones 1..3, subsecciones 2.1..2.7 |
| 18 | Subsecciones propias: tipo de afectación, ventana de máximo aporte, variables relevantes, evolución temporal, conclusión general | **Aplicado en esta corrida** | Ver §3 |

---

## 2. El comentario 4, y por qué no se aplica literal

Medido sobre `Indicadores_vano_v3.csv`: **159.470 filas** son **6.455 interrupciones
distintas** repartidas sobre **27.390 vanos**. Son tres magnitudes y el informe las
llamaba «eventos» a todas.

Renombrar «cantidad de eventos» a «vanos probables de causa de falla» habría hecho que
DON23L13 —235 interrupciones, 845 vanos señalados— se leyera como si tuviera 235 vanos.
El comentario multiplica el problema por veinte en lugar de aclararlo.

Lo aplicado es lo que el comentario buscaba:

| Término | Qué cuenta | Dónde |
|---|---|---|
| Interrupción | Una salida. Golpea muchos vanos a la vez | Prosa del agente |
| Vano probable de causa de falla | Un vano que aparece en registros de interrupción | Ficha, tabla de clasificación, hover del ranking |
| Registro vano-evento | Una fila. Siempre el mayor de los tres | Ficha, tabla de ventanas, hover |

La definición de las tres va pegada a la tabla de cabecera, no en un glosario aparte.

---

## 3. El comentario 18: qué lo resuelve

Las siete subsecciones del revisor se reparten en dos grupos según de dónde puede salir
cada una.

### Lo que se calcula (no necesita agente)

| Subsección | Cómo |
|---|---|
| 2.1 Tipo de afectación: sostenida o puntual | Umbral determinista sobre la serie por ventana: cuántas ventanas registran actividad y qué fracción del UITI se lleva la mayor. Es una lectura de datos, no un juicio: pedírsela a un modelo la haría variar entre corridas sobre los mismos números |
| 2.2 Ventana de máximo aporte | Ya sale marcada en la tabla de ventanas; se promueve a llamada propia |
| 2.4 Análisis de vanos | Calculado (comentario 10) |

### Lo que produce la corrida

| Subsección | Campo | Estado antes |
|---|---|---|
| 2.3 Ventanas estudiadas | `circuit_characterization.ventanas_estudiadas` | Existía; en corridas reales llegaba como `["V6","V7","V11"]`, sin prosa |
| 2.5 Análisis de variables relevantes | `variables_relevantes` | **Nuevo** |
| 2.6 Análisis de evolución temporal | `period_synthesis` | Existía. El contrato ya lo define como «cómo evolucionó en el tiempo»; lo que faltaba era que fuera subsección propia y no un bloque suelto |
| 2.7 Conclusión general | `conclusion_general` | **Nuevo** |

Los dos campos nuevos entran al esquema como **opcionales**. `additionalProperties` está
en `false`, así que un campo no declarado invalidaría la respuesta del agente; declararlo
opcional deja además que las corridas ya archivadas sigan validando y renderizando.

Sin la corrida, 2.5 y 2.7 no existen y el informe se dibuja sin ellas —degradación
silenciosa, no error—. Con la corrida, las siete subsecciones quedan cubiertas.

---

## 4. Defectos encontrados al verificar el HTML renderizado

Ninguno lo reportó el revisor. Salieron de mirar el informe real, no las pruebas.

| Defecto | Alcance | Causa |
|---|---|---|
| `&mdash;` dibujado literal en el título de la figura del ranking y en los paneles del grafo | Todos los informes de circuito emitidos | Plotly no decodifica entidades en el título; `_chart_panel` escapa el suyo |
| Lo mismo en «Panorama del grupo &mdash; …» y en la columna Período | Todos los gerenciales emitidos | Igual |
| `<b>` dibujado como `&lt;b&gt;` en los bloques calculados | Introducido en esta revisión, corregido antes de commit | `_envolver_items` escapa su contenido, que es correcto para prosa de agente |
| «Lectura comparativa entre ventanas» con tres viñetas vacías | Corridas donde el agente entrega solo etiquetas | El esquema pide `ventanas_estudiadas` y no exige prosa |
| Ventanas estudiadas sin marcar en informes rearmados desde disco | Todo re-render desde `.out.json` | El escenario archivado no escribe clave `ventana`: solo `nombre: "DON23L13 -- ventana V6"` |

---

## 5. Qué se traslada al informe gerencial

El documento del revisor va sobre el informe por circuito. Estos son los comentarios que
valen igual en el gerencial, y los que no.

| # | Traslado | Razón |
|---|---|---|
| 1 | **Sí**, como ficha del grupo | Circuitos, vanos, UITI y kilómetros agregados del grupo: la misma pregunta de apertura, sobre otro sujeto |
| 2 | **Sí** | Tiene una sección «Concentración por ventana» sobre la misma rejilla |
| 3 | **Sí** | El ranking es la misma figura; la tabla con ubicación se lee igual de mal sin ella |
| 4, 6, 7 | **Sí** | Vocabulario. Los dos informes se leen seguidos: que uno diga «flota» y el otro «circuitos totales» para lo mismo es el problema que el comentario venía a resolver |
| 8 | **Sí** | Ahí la tabla suma ventanas de **varios** circuitos, así que la tentación de leer un total al pie es mayor |
| 17 | **Sí** | Numerales |
| 5 | Parcial | Tiene «Resumen ejecutivo del grupo», pero sus cuatro bloques son los del circuito |
| 9 | Parcial | Su tabla por ventana ya trae período; le faltan las cifras de aporte |
| 10 | **No** | Su unidad es el circuito, no el vano |
| 11, 12, 13, 16, 18 | **No** | No tiene inferencias por ventana, ni hipótesis de causa, ni caracterización, ni prosa de agente: es Python puro |
| 14, 15 | **No** | No tiene mapa |

### Además: el costo de los agentes

El informe de circuito ganó una sección «Cómo se construyó este informe» con la línea de
tiempo de los tres agentes, sus tokens y el ahorro por paralelismo.

El gerencial **no ejecuta ningún agente** —es Python puro, cero tokens—. Su costo son las
corridas de `/report` que sintetiza, y esas ya dejaron `stage_timing.json` y
`token_usage.json` en disco. La sección equivalente agrega esos archivos: cuántas corridas
hay detrás, cuántos tokens costaron y cuánto reloj de pared.

La barrera de paralelismo se aplica **por corrida**, no a la suma: en cada una
`historical` e `inference` van a la vez y `expert-alignment` espera a las dos. Sumar las
duraciones y aplicar la barrera al total afirmaría un paralelismo entre corridas que no
existe.

Cero datos nuevos y cero tokens: los archivos ya están escritos.
