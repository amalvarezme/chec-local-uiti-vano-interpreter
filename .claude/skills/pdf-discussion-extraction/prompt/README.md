# Extracción de Discusiones PDF

Habilidades para generar la tabla base de discusiones técnicas verificables desde reportes expertos en PDF.

Esta carpeta separa el contrato del agente extractor del antiguo cuaderno ejecutor. El flujo cargaba `01_pdf_discussion_extractor.md`, rellenaba los metadatos del fragmento y validaba la salida antes de agregar filas al Excel final.

Restricciones de esta función:

- No usa embeddings.
- No usa FAISS.
- No usa Chroma.
- No crea base vectorial.
- No crea agente comparador.
- Solo genera filas con circuito, fecha o intervalo valido, analisis y evidencia textual verificable.
