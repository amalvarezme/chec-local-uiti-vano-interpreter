from __future__ import annotations

from types import SimpleNamespace

from chec_local_interpreter.reports.pdf_discussions import (
    PDFDiscussionExtractionSkill,
    PDFPageText,
    chunk_pdf_pages,
    circuito_from_pdf_name,
    detect_report_period,
    extract_json_object,
    is_candidate_fragment,
    iso_fecha,
    overlaps,
    parse_fecha,
    validate_llm_row,
)


def test_circuito_from_pdf_name_requires_circuit_pattern():
    assert circuito_from_pdf_name("DON23L13.pdf") == "DON23L13"
    assert circuito_from_pdf_name("reporte_general.pdf") is None


def test_parse_and_format_spanish_dates():
    assert iso_fecha("15 de noviembre de 2025") == "2025-11-15"
    assert iso_fecha("noviembre de 2025") == "2025-11-01"
    assert iso_fecha("bad") is None


def test_overlaps_detects_intersecting_ranges():
    assert overlaps("2025-11-01", "2025-11-30", "2025-11-15", "2025-12-01")
    assert not overlaps("2025-10-01", "2025-10-31", "2025-11-01", "2025-12-01")


def test_extract_json_object_handles_fenced_output():
    assert extract_json_object('```json\n{"include": true}\n```') == {"include": True}
    assert extract_json_object('prefix {"include": false} suffix') == {"include": False}


def test_validate_llm_row_checks_required_fields_and_range():
    payload = {
        "include": True,
        "Circuito": "DON23L13",
        "Fecha inicio": "2025-11-01",
        "Fecha fin": "2025-11-15",
        "Análisis": "Evento relevante",
        "Evidencia": "Página 1",
    }

    ok, errors = validate_llm_row(
        payload,
        "2025-11-01",
        "2026-04-30",
        final_columns=["Circuito", "Fecha inicio", "Fecha fin", "Análisis", "Evidencia"],
    )

    assert ok
    assert errors == []


def test_detect_period_and_candidate_fragment():
    pages = [
        PDFPageText("DON23L13.pdf", 1, "Discusión de falla del 2025-11-01"),
        PDFPageText("DON23L13.pdf", 2, "Recomendación posterior al 2025-12-01"),
    ]
    period = detect_report_period("\n".join(page.texto for page in pages))
    fragments = chunk_pdf_pages(pages, period, chunk_chars=10_000, chunk_overlap=0)

    assert period == ("2025-11-01", "2025-12-01")
    assert len(fragments) == 1
    assert is_candidate_fragment(fragments[0])


def test_pdf_discussion_extraction_skill_builds_prompt_and_parses_output(tmp_path):
    skill_path = tmp_path / "skill.md"
    skill_path.write_text("Circuito: {circuito}", encoding="utf-8")

    def fake_call_llm(prompt, **kwargs):
        return SimpleNamespace(
            called=True,
            message="ok",
            output_text='{"include": true, "Circuito": "DON23L13"}',
        )

    skill = PDFDiscussionExtractionSkill(
        skill_path,
        provider="test",
        model="fake",
        call_enabled=True,
        llm_caller=fake_call_llm,
    )

    result = skill.extract({"circuito": "DON23L13"})

    assert result["prompt"] == "Circuito: DON23L13"
    assert result["parsed"] == {"include": True, "Circuito": "DON23L13"}
