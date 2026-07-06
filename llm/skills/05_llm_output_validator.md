# Validador de Salida del LLM

Valida cada respuesta del LLM antes de presentarla como análisis.

## La Respuesta Debe

- Ser JSON válido.
- Cumplir con `uiti_vano_explanation.output_schema.json`.
- Incluir solo fechas presentes en `critical_points` o `daily_series`.
- No referenciar columnas no disponibles como si estuvieran presentes.
- No afirmar el uso de RAG, bitácoras operativas, revisión normativa, modelos predictivos, máscaras, simulaciones ni generación de reportes finales.
- Incluir limitaciones.
- Incluir brechas de datos cuando falten variables opcionales.

## Si la Validación Falla

- Guarda la salida cruda inválida en `reports/interpretability/artifacts/invalid_llm_output_<timestamp>.txt`.
- Guarda los errores de validación en `reports/interpretability/artifacts/llm_validation_errors_<timestamp>.json`.
- No presentes la salida inválida como análisis final.
- Imprime un mensaje claro en el notebook explicando que el prompt y el contexto fueron guardados para revisión manual.
