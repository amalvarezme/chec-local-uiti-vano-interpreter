# PDF Discussion Extraction

Skills para generar la tabla base de discusiones tecnicas verificables desde reportes expertos en PDF.

Esta carpeta separa el contrato del agente extractor del cuaderno que lo ejecuta. El cuaderno `notebooks/core/03_pdf_discussion_table_from_pdfs.ipynb` carga `01_pdf_discussion_extractor.md`, rellena los metadatos del fragmento y valida la salida antes de agregar filas al Excel final.

Restricciones de esta funcion:

- No usa embeddings.
- No usa FAISS.
- No usa Chroma.
- No crea base vectorial.
- No crea agente comparador.
- Solo genera filas con circuito, fecha o intervalo valido, analisis y evidencia textual verificable.
