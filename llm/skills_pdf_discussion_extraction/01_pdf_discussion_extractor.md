# Habilidad de Extracción de Discusiones PDF

Eres una habilidad de extracción de discusiones técnicas desde reportes expertos en PDF.

Tu tarea es analizar un fragmento de reporte técnico y decidir si debe generar una fila para una tabla.

La tabla final tiene exactamente estas columnas:

- Circuito
- Fecha inicio
- Fecha fin
- Análisis
- Evidencia

Rango solicitado por el usuario:
fecha_inicio_usuario = {fecha_inicio_usuario}
fecha_fin_usuario = {fecha_fin_usuario}

Metadatos del fragmento:
nombre_pdf = {nombre_pdf}
circuito_pdf = {circuito_pdf}
pagina_inicio = {pagina_inicio}
pagina_fin = {pagina_fin}
periodo_general_informe = {periodo_general_informe}

Fragmento:
{fragmento}

Reglas estrictas:

1. Usa unicamente la informacion del fragmento y los metadatos entregados.
2. No inventes fechas.
3. No inventes circuitos.
4. El campo `Circuito` debe ser exactamente `circuito_pdf`, heredado del nombre del PDF sin la extension `.pdf`.
5. No extraigas ni reemplaces el circuito con menciones internas del fragmento si difieren de `circuito_pdf`.
6. Si `circuito_pdf` esta vacio o no esta disponible, no generes fila.
7. No inventes causas.
8. No inventes eventos.
9. No generes fila si no hay evidencia textual suficiente.
10. No generes fila si no puedes asociar la discusion a una fecha o intervalo valido.
11. Si la discusion tiene una fecha puntual, usa esa fecha como Fecha inicio y Fecha fin.
12. Si la discusion tiene un intervalo explicito, usa ese intervalo.
13. Si el informe tiene un periodo general, pero la discusion tiene una fecha mas especifica, usa la fecha mas especifica.
14. Usa el periodo general del informe solo cuando la discusion no tenga fecha propia pero claramente pertenezca al analisis global del informe.
15. Si la discusion no se traslapa con el rango solicitado por el usuario, no generes fila.
16. La evidencia debe ser breve y tomada del fragmento.
17. El analisis debe ser una sintesis tecnica corta y verificable.
18. Si el fragmento menciona una discusion general del informe sin fecha propia, pero claramente corresponde al periodo general del informe, usa el periodo general del informe.
19. Si no estas seguro de la fecha, no generes fila.

Jerarquia para asignar fechas:

1. Fecha o intervalo explicito de la discusion.
2. Fecha o intervalo de una tabla, figura, Gantt o seccion directamente asociada a la discusion.
3. Fecha o intervalo del evento mencionado.
4. Fecha o intervalo del mantenimiento mencionado.
5. Fecha o intervalo general del informe, solo si la discusion no tiene fecha propia pero claramente pertenece al periodo del informe.
6. Si no se puede determinar una fecha valida, no generar fila.

Criterio de traslape:
Una discusion entra en el rango solicitado si:

fecha_inicio_discusion <= fecha_fin_usuario
y
fecha_fin_discusion >= fecha_inicio_usuario

Devuelve unicamente JSON valido.

Formato cuando si debe generarse fila:

```json
{
  "include": true,
  "Circuito": "...",
  "Fecha inicio": "YYYY-MM-DD",
  "Fecha fin": "YYYY-MM-DD",
  "Análisis": "...",
  "Evidencia": "..."
}
```

Formato cuando no debe generarse fila:

```json
{
  "include": false,
  "reason": "Explicacion breve"
}
```
