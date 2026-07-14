# Contexto del Simulador Automático Mínimo/Máximo

Esta habilidad orienta al agente que analiza la tabla producida por el simulador automático
de sensibilidad. La tabla compara el escenario base del modelo con dos escenarios extremos
por variable: valor mínimo observado y valor máximo observado, siempre en escala original.

## Fuentes Permitidas

- Tabla `simulador_automatico_minmax`, generada por código determinístico.
- Metadata del simulador: circuito, periodo, número de filas base, advertencias y modelo.
- Contexto opcional `curvas_softmax_top_variables`, generado por código determinístico para
  hasta 4 variables más relevantes. Contiene probabilidades promedio por clase de riesgo
  al recorrer valores originales de cada variable y el valor probado con menor riesgo
  ordinal estimado.
- Contexto opcional `costos_items_contratos`, construido desde `data/COSTOS ITEMS CONTRATOS.xlsx`.
  Este contexto contiene ítems de contrato cercanos por texto y su `costo_promedio`.
- Contexto de inferencia disponible en el cuaderno, incluyendo escenarios, `top_variables`,
  modos CHEC y grafos HTML cuando existan.
- Contexto general de las skills de inferencia y grafos, solo como guía interpretativa.

## Reglas de Interpretación

- No inventes variables, valores, riesgos ni cambios.
- No uses valores escalados, codificados ni embeddings en la explicación visible.
- Trata `riesgo_base`, `riesgo_valor_minimo` y `riesgo_valor_maximo` como salidas del modelo,
  no como causalidad operacional.
- Prioriza las columnas de etiqueta de riesgo:
  `riesgo_base_etiqueta`, `riesgo_valor_minimo_etiqueta` y `riesgo_valor_maximo_etiqueta`.
- Antes de discutir sensibilidad numérica, revisa si el escenario mínimo o máximo cambia la
  categoría de riesgo frente al escenario base.
- Da máxima prioridad a transiciones fuertes como riesgo bajo -> riesgo alto o riesgo alto ->
  riesgo bajo. Después considera cambios bajo -> medio, medio -> alto, alto -> medio y medio ->
  bajo.
- No hagas una explicación larga variable por variable. Resume patrones generales y menciona
  solo las variables necesarias para justificar transiciones o sensibilidad destacada.
- Usa `magnitud_max_cambio_abs` para identificar las variables más sensibles.
- Distingue si el mínimo o el máximo aumenta, disminuye o no cambia de forma relevante el
  riesgo frente al escenario base.
- Si una variable aparece en `top_variables`, modos CHEC o grafos, puedes usar ese contexto
  para enriquecer la lectura, pero no para cambiar el resultado numérico del simulador.
- Si `costos_items_contratos` está disponible, úsalo para complementar la discusión económica:
  menciona rangos o ítems cercanos solo con los costos entregados, y aclara que son aproximaciones
  por cercanía textual, no presupuestos definitivos.
- Si `curvas_softmax_top_variables` está disponible, úsalo para discutir de forma general cómo
  se desplazan las probabilidades de Q1, Q2, Q3 y Q4 en las variables graficadas. Enfócate en
  si el valor de menor riesgo estimado coincide con una mayor probabilidad de Q1 o con menor
  probabilidad de Q4.
- Puedes mencionar los `mejor_escenario_menor_riesgo` como valores propios estimados por el
  modelo, pero siempre aclara que son valores simulados dentro del rango observado y no una
  instrucción operativa automática.
- No conviertas un ítem cercano en recomendación automática de intervención; úsalo solo como señal
  económica para priorización o revisión.
- Si hay advertencias, incorpóralas como limitaciones o brechas de ejecución.

## Lecturas Útiles

- Una transición de categoría tiene prioridad interpretativa sobre un cambio numérico pequeño.
- Si no hay cambios de categoría, dilo explícitamente y enfoca la discusión en estabilidad del
  nivel de riesgo, aumentos o disminuciones numéricas, variables con mayor sensibilidad y
  diferencias generales entre los escenarios mínimo y máximo.
- Cuando existan costos cercanos, contrasta la sensibilidad del riesgo con el orden de magnitud del
  costo promedio de los ítems asociados.
- Cuando existan curvas softmax y costos cercanos, coteja el valor de menor riesgo estimado con los
  ítems de contrato cercanos para dar una lectura económica orientativa. No sumes costos si el
  contexto no entrega valores numéricos suficientes.
- Una variable es más sensible cuando alguno de sus extremos produce mayor cambio absoluto
  frente al escenario base.
- Un patrón es consistente cuando mínimo y máximo mueven el riesgo en direcciones opuestas
  o cuando el extremo esperado por el contexto aumenta el riesgo.
- Un patrón es contradictorio cuando los cambios no coinciden con la lectura contextual o
  cuando ambos extremos producen señales similares sin una explicación clara.
- Un cambio pequeño debe describirse como estabilidad o baja sensibilidad.

## Lenguaje

Usa lenguaje cauteloso:

- "el simulador muestra"
- "el modelo responde con"
- "es compatible con"
- "sugiere sensibilidad"
- "requiere validación operativa"

Evita:

- "la variable causa"
- "demuestra"
- "el modelo prueba"
- "la causa fue"
