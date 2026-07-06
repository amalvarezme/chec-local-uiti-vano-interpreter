# Constructor de Contexto Estructurado

Construye el contexto estructurado antes de cualquier llamada al LLM. El código
determinístico en Python selecciona los circuitos, el periodo, la serie diaria, los
puntos críticos y los resúmenes de atribución.

## Entradas

- Dataframe filtrado para los circuitos y la ventana de fechas seleccionados.
- Serie diaria de `UITI_VANO`.
- Puntos críticos seleccionados por código.
- Resúmenes de atribución para cada punto crítico.
- Grupos de variables de dominio.
- Reglas de relación.

## Salida

Un paquete de contexto compacto y serializable como JSON, que pueda guardarse y
reproducirse.

## Reglas

- Incluye solo datos derivados de los circuitos y la ventana de fechas seleccionados.
- Incluye explícitamente en la metadata las variables opcionales no disponibles.
- Mantén los IDs como cadenas de texto.
- Resume las filas crudas en lugar de enviar el dataset completo cuando la ventana sea grande.
- Incluye suficientes filas de eventos alrededor de cada punto crítico para permitir la interpretación.
- Incluye la serie diaria en forma compacta.
- Incluye las reglas de protección dentro del paquete de contexto.
- No agregues evidencia externa, documentos, almacenes vectoriales, modelos, máscaras, simulaciones ni material de reporte final.
