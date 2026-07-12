"""Single-source-of-truth guard for the PDF-discussion 5-column schema.

PR A2a's verify report (`sdd/agent-native-pipeline-and-site-split/verify-report`,
WARNING 1) found `COLUMNAS_FINALES`/`REQUIRED_PDF_DISCUSSION_COLUMNS` defined as
THREE independent literal copies: `pdf_discussion_pipeline.COLUMNAS_FINALES`
(A2a's new canonical home per design D5), `llm_validation.COLUMNAS_FINALES`
(pre-existing, from `validate_pdf_discussion_row`), and
`expert_alignment.REQUIRED_PDF_DISCUSSION_COLUMNS` (pre-existing xlsx reader).
This test pins the consolidation: `pdf_discussion_pipeline.py` owns the ONE
literal definition; `llm_validation.py` and `expert_alignment.py` both import
it from there instead of redefining it, so a future edit to the schema can
never silently desynchronize the xlsx producer from its two consumers.
"""

from __future__ import annotations

import chec_local_interpreter.expert_alignment as expert_alignment
import chec_local_interpreter.llm_validation as llm_validation
import chec_local_interpreter.pdf_discussion_pipeline as pdf_discussion_pipeline


def test_llm_validation_columnas_finales_is_the_same_object_as_pipeline_source():
    assert llm_validation.COLUMNAS_FINALES is pdf_discussion_pipeline.COLUMNAS_FINALES


def test_expert_alignment_required_columns_is_the_same_object_as_pipeline_source():
    assert (
        expert_alignment.REQUIRED_PDF_DISCUSSION_COLUMNS
        is pdf_discussion_pipeline.COLUMNAS_FINALES
    )


def test_columns_still_match_the_documented_five_column_schema():
    expected = ["Circuito", "Fecha inicio", "Fecha fin", "Análisis", "Evidencia"]
    assert pdf_discussion_pipeline.COLUMNAS_FINALES == expected
    assert list(llm_validation.COLUMNAS_FINALES) == expected
    assert list(expert_alignment.REQUIRED_PDF_DISCUSSION_COLUMNS) == expected
