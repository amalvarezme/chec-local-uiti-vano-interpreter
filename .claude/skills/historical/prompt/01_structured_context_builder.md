# Constructor de Contexto Estructurado

Construye el contexto estructurado antes de cualquier llamada al LLM. El código
determinístico en Python selecciona los circuitos, el periodo, la rejilla de ventanas y
las tres ventanas que el informe estudia.

## Entradas

- Dataframe filtrado para los circuitos y la ventana de fechas seleccionados.
- Serie de `UITI_VANO` por ventana, completa y con cero donde no hubo eventos.
- Las tres ventanas que el informe estudia (`ventanas_estudio`).
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
- Incluye la serie por ventana completa, sin recortar las ventanas en cero.
- Incluye las reglas de protección dentro del paquete de contexto.
- No agregues evidencia externa, documentos, almacenes vectoriales, modelos, máscaras, simulaciones ni material de reporte final.
