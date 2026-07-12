from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

import chec_local_interpreter.pdf_discussion_pipeline as pdf_discussion_pipeline
from chec_local_interpreter.pdf_discussion_pipeline import (
    COLUMNAS_FINALES,
    MarkdownSection,
    assemble_discussion_xlsx,
    assemble_discussion_xlsx_from_run,
    circuito_from_pdf_name,
    detect_report_period,
    is_candidate_section,
    pdf_to_markdown,
    prepare_pdf_discussion_batch,
    split_markdown_sections,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REAL_PDF_FIXTURE = PROJECT_ROOT / "reports" / "analysis-documents" / "MNA23L12.pdf"


class _FakeTable:
    """Not used directly -- pdfplumber's `extract_tables()` returns
    `list[list[list[str | None]]]` (rows of cells), no wrapper object."""


class _FakePage:
    def __init__(self, text: str | None, tables: list[list[list[str | None]]] | None = None) -> None:
        self._text = text
        self._tables = tables or []

    def extract_text(self) -> str | None:
        return self._text

    def extract_tables(self) -> list[list[list[str | None]]]:
        return self._tables


class _FakePDF:
    def __init__(self, pages: list[_FakePage]) -> None:
        self.pages = pages

    def __enter__(self) -> "_FakePDF":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None


def _patch_pdfplumber_open(monkeypatch: pytest.MonkeyPatch, pages: list[_FakePage]) -> None:
    import chec_local_interpreter.pdf_discussion_pipeline as module

    monkeypatch.setattr(module.pdfplumber, "open", lambda _path: _FakePDF(pages))


# --- Unit tests: page-heading / table-formatting logic (mocked pdfplumber) ---


def test_pdf_to_markdown_emits_page_heading_and_text(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_pdfplumber_open(
        monkeypatch,
        [_FakePage("Texto de la pagina uno."), _FakePage("Texto de la pagina dos.")],
    )

    markdown = pdf_to_markdown(Path("dummy.pdf"))

    assert "## Página 1" in markdown
    assert "Texto de la pagina uno." in markdown
    assert "## Página 2" in markdown
    assert "Texto de la pagina dos." in markdown
    # Page 1's heading must precede page 2's heading.
    assert markdown.index("## Página 1") < markdown.index("## Página 2")


def test_pdf_to_markdown_renders_table_as_gfm_pipe_table(monkeypatch: pytest.MonkeyPatch) -> None:
    table = [["Fecha", "Causa"], ["2026-01-10", "Falla vegetacion"]]
    _patch_pdfplumber_open(monkeypatch, [_FakePage("Texto con tabla.", tables=[table])])

    markdown = pdf_to_markdown(Path("dummy.pdf"))

    assert "| Fecha | Causa |" in markdown
    assert "| --- | --- |" in markdown
    assert "| 2026-01-10 | Falla vegetacion |" in markdown


def test_pdf_to_markdown_no_text_page_emits_explicit_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_pdfplumber_open(
        monkeypatch,
        [_FakePage("Con texto."), _FakePage(None), _FakePage("Con texto otra vez.")],
    )

    markdown = pdf_to_markdown(Path("dummy.pdf"))

    assert "<!-- Página 2: sin texto extraíble -->" in markdown
    # No exception raised (implicit -- reaching this line proves it), and the
    # other pages' real content is unaffected.
    assert "Con texto." in markdown
    assert "Con texto otra vez." in markdown
    assert "## Página 1" in markdown
    assert "## Página 3" in markdown


def test_pdf_to_markdown_whitespace_only_text_counts_as_no_text(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_pdfplumber_open(monkeypatch, [_FakePage("   \n\t  ")])

    markdown = pdf_to_markdown(Path("dummy.pdf"))

    assert "<!-- Página 1: sin texto extraíble -->" in markdown


# --- Integration test: real PDF, ground truth confirmed via manual pdfplumber run ---


@pytest.mark.skipif(not REAL_PDF_FIXTURE.exists(), reason="Real PDF fixture not present in this checkout")
def test_pdf_to_markdown_real_pdf_page_8_has_no_extractable_text() -> None:
    markdown = pdf_to_markdown(REAL_PDF_FIXTURE)

    assert "## Página 1" in markdown
    assert "## Página 8" in markdown
    assert "<!-- Página 8: sin texto extraíble -->" in markdown
    # Page 1 has real text (1606 chars) -- confirm it did not get the marker.
    page_1_section = markdown.split("## Página 1", 1)[1].split("## Página 2", 1)[0]
    assert "sin texto extraíble" not in page_1_section


# --- MarkdownSection / split_markdown_sections (design D5, step 2) ---


def _page_block(n: int, text: str) -> str:
    return f"## Página {n}\n\n{text}"


def test_markdown_section_is_a_frozen_dataclass_with_expected_fields() -> None:
    section = MarkdownSection(
        nombre_pdf="AGU23L15.pdf",
        circuito_pdf="AGU23L15",
        pagina_inicio=1,
        pagina_fin=2,
        periodo_general_informe="2025-01-01 a 2025-02-01",
        markdown="## Página 1\n\ntexto",
    )

    assert section.nombre_pdf == "AGU23L15.pdf"
    assert section.circuito_pdf == "AGU23L15"
    assert section.pagina_inicio == 1
    assert section.pagina_fin == 2
    assert section.periodo_general_informe == "2025-01-01 a 2025-02-01"
    assert section.markdown == "## Página 1\n\ntexto"

    with pytest.raises(Exception):
        section.pagina_inicio = 99  # type: ignore[misc]


def test_split_markdown_sections_single_small_page_yields_one_section() -> None:
    markdown = _page_block(1, "Texto corto.") + "\n\n"

    sections = split_markdown_sections(
        markdown,
        nombre_pdf="AGU23L15.pdf",
        circuito_pdf="AGU23L15",
        periodo_general_informe="2025-01-01 a 2025-02-01",
    )

    assert len(sections) == 1
    assert sections[0].pagina_inicio == 1
    assert sections[0].pagina_fin == 1
    assert sections[0].nombre_pdf == "AGU23L15.pdf"
    assert sections[0].circuito_pdf == "AGU23L15"
    assert sections[0].periodo_general_informe == "2025-01-01 a 2025-02-01"
    assert "Texto corto." in sections[0].markdown


def test_split_markdown_sections_chunks_on_page_boundaries_over_max_chars() -> None:
    # Two pages whose combined text exceeds a tiny max_chars budget --
    # must split into (at least) two sections, one per page-boundary group.
    page_1 = _page_block(1, "A" * 50)
    page_2 = _page_block(2, "B" * 50)
    markdown = page_1 + "\n\n" + page_2 + "\n\n"

    sections = split_markdown_sections(
        markdown,
        nombre_pdf="DON23L13.pdf",
        circuito_pdf="DON23L13",
        periodo_general_informe="",
        max_chars=60,
        overlap=0,
    )

    assert len(sections) >= 2
    # Every page number that appears in the source markdown must appear in
    # at least one section's page range -- no page silently dropped.
    covered_pages = set()
    for section in sections:
        covered_pages.update(range(section.pagina_inicio, section.pagina_fin + 1))
    assert covered_pages == {1, 2}


def test_split_markdown_sections_applies_overlap_between_consecutive_chunks() -> None:
    page_1 = _page_block(1, "A" * 100)
    page_2 = _page_block(2, "B" * 100)
    page_3 = _page_block(3, "C" * 100)
    markdown = page_1 + "\n\n" + page_2 + "\n\n" + page_3 + "\n\n"

    sections = split_markdown_sections(
        markdown,
        nombre_pdf="MAZ23L13.pdf",
        circuito_pdf="MAZ23L13",
        periodo_general_informe="",
        max_chars=120,
        overlap=20,
    )

    assert len(sections) >= 2
    # The tail of one section and the head of the next should share content
    # (the overlap window), proving overlap carries across the split.
    first_tail = sections[0].markdown[-20:]
    assert any(first_tail[-5:] in later.markdown for later in sections[1:])


# --- is_candidate_section / detect_report_period / circuito_from_pdf_name
# (design D5, step 2 -- same heuristic as the notebook's is_candidate_fragment) ---


def _section(markdown: str, periodo: str = "") -> MarkdownSection:
    return MarkdownSection(
        nombre_pdf="AGU23L15.pdf",
        circuito_pdf="AGU23L15",
        pagina_inicio=1,
        pagina_fin=1,
        periodo_general_informe=periodo,
        markdown=markdown,
    )


def test_is_candidate_section_excludes_neither_term_nor_date_or_circuit() -> None:
    section = _section("Texto generico sin ningun senal relevante para el analisis.")
    assert is_candidate_section(section) is False


def test_is_candidate_section_excludes_date_or_circuit_without_technical_term() -> None:
    # Has a date signal but no technical term -- still excluded.
    section = _section("La reunion se realizo el 2026-01-10 sin incidentes reportados.")
    assert is_candidate_section(section) is False


def test_is_candidate_section_excludes_technical_term_without_date_or_circuit() -> None:
    # Has a technical term but neither a date nor a circuit-code signal.
    section = _section("Se reporto una falla en el sistema de proteccion general.")
    assert is_candidate_section(section) is False


def test_is_candidate_section_includes_technical_term_and_date() -> None:
    section = _section("El dia 2026-01-10 se presento una falla asociada a vegetacion en el tramo.")
    assert is_candidate_section(section) is True


def test_is_candidate_section_includes_technical_term_and_circuit_code() -> None:
    section = _section("Se reporto una falla de proteccion en el circuito AGU23L15 recientemente.")
    assert is_candidate_section(section) is True


def test_is_candidate_section_includes_technical_term_via_general_period_without_inline_date() -> None:
    # No inline date/circuit match, but the section carries a
    # periodo_general_informe -- counts as a date signal (ports the
    # notebook's `has_date = bool(DATE_REGEX.search(text)) or
    # bool(fragment.periodo_general_informe)`).
    section = _section(
        "Se identifico una falla de proteccion relevante para el periodo del informe.",
        periodo="2025-01-01 a 2025-02-01",
    )
    assert is_candidate_section(section) is True


def test_detect_report_period_returns_none_with_fewer_than_two_dates() -> None:
    assert detect_report_period("Solo una fecha: 2026-01-10.") is None
    assert detect_report_period("Ninguna fecha aqui.") is None


def test_detect_report_period_returns_earliest_and_latest_iso_dates() -> None:
    text = "Periodo entre 2026-03-15 y 2025-11-01, con revision el 2026-01-01."
    assert detect_report_period(text) == ("2025-11-01", "2026-03-15")


def test_detect_report_period_does_not_swap_day_and_month_on_ambiguous_iso_dates() -> None:
    # Regression test for the dayfirst=True bugfix: "2025-11-01" (day=01,
    # month=11) must stay 2025-11-01, not silently become 2025-01-11.
    text = "Evento registrado el 2025-11-01 y cerrado el 2025-11-02."
    assert detect_report_period(text) == ("2025-11-01", "2025-11-02")


def test_circuito_from_pdf_name_extracts_circuit_code() -> None:
    assert circuito_from_pdf_name(Path("AGU23L15.pdf")) == "AGU23L15"
    assert circuito_from_pdf_name("DON23L13.pdf") == "DON23L13"


def test_circuito_from_pdf_name_returns_none_without_circuit_code() -> None:
    assert circuito_from_pdf_name(Path("reporte_sin_circuito.pdf")) is None
    assert circuito_from_pdf_name("") is None


# --- prepare_pdf_discussion_batch (design D5, step 3) ---


def _fake_pdf_to_markdown(mapping: dict[str, str]):
    def _fake(pdf_path: Path) -> str:
        return mapping[Path(pdf_path).name]

    return _fake


def _touch_pdfs(pdf_dir: Path, names: list[str]) -> None:
    pdf_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        (pdf_dir / name).write_bytes(b"%PDF-1.4 fake\n")


def test_prepare_pdf_discussion_batch_writes_one_payload_per_candidate_pdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf_dir = tmp_path / "pdfs"
    run_dir = tmp_path / "run"
    markdown = (
        "## Página 1\n\n"
        "El dia 2026-01-10 se presento una falla asociada a vegetacion en el tramo."
    )
    _touch_pdfs(pdf_dir, ["AGU23L15.pdf"])
    monkeypatch.setattr(
        pdf_discussion_pipeline, "pdf_to_markdown", _fake_pdf_to_markdown({"AGU23L15.pdf": markdown})
    )

    written = prepare_pdf_discussion_batch(
        pdf_dir, "2026-01-01", "2026-01-31", run_dir, max_batch_chars=40000
    )

    assert len(written) == 1
    payload_path = written[0]
    assert payload_path == run_dir / "AGU23L15.bc-input.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    assert payload["fecha_inicio_usuario"] == "2026-01-01"
    assert payload["fecha_fin_usuario"] == "2026-01-31"
    assert payload["nombre_pdf"] == "AGU23L15.pdf"
    assert payload["circuito_pdf"] == "AGU23L15"
    assert "periodo_general_informe" in payload
    assert len(payload["secciones"]) == 1
    seccion = payload["secciones"][0]
    assert seccion["indice"] == 1
    assert seccion["pagina_inicio"] == 1
    assert seccion["pagina_fin"] == 1
    assert "falla" in seccion["markdown"]


def test_prepare_pdf_discussion_batch_skips_circuit_less_pdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf_dir = tmp_path / "pdfs"
    run_dir = tmp_path / "run"
    markdown = "## Página 1\n\nEl dia 2026-01-10 se presento una falla asociada a vegetacion."
    _touch_pdfs(pdf_dir, ["reporte_generico.pdf"])
    monkeypatch.setattr(
        pdf_discussion_pipeline,
        "pdf_to_markdown",
        _fake_pdf_to_markdown({"reporte_generico.pdf": markdown}),
    )

    written = prepare_pdf_discussion_batch(pdf_dir, "2026-01-01", "2026-01-31", run_dir)

    assert written == []
    assert not run_dir.exists() or list(run_dir.glob("*.json")) == []


def test_prepare_pdf_discussion_batch_skips_zero_candidate_pdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf_dir = tmp_path / "pdfs"
    run_dir = tmp_path / "run"
    markdown = "## Página 1\n\nTexto administrativo sin ninguna senal tecnica relevante."
    _touch_pdfs(pdf_dir, ["AGU23L15.pdf"])
    monkeypatch.setattr(
        pdf_discussion_pipeline, "pdf_to_markdown", _fake_pdf_to_markdown({"AGU23L15.pdf": markdown})
    )

    written = prepare_pdf_discussion_batch(pdf_dir, "2026-01-01", "2026-01-31", run_dir)

    assert written == []


def test_prepare_pdf_discussion_batch_writes_one_payload_per_pdf_regardless_of_section_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf_dir = tmp_path / "pdfs"
    run_dir = tmp_path / "run"
    _touch_pdfs(pdf_dir, ["AGU23L15.pdf", "DON23L13.pdf"])
    markdown_by_name = {
        "AGU23L15.pdf": "## Página 1\n\nEl dia 2026-01-10 se presento una falla en el tramo.",
        "DON23L13.pdf": "## Página 1\n\nEl dia 2026-02-05 hubo un evento de proteccion en el circuito.",
    }
    monkeypatch.setattr(
        pdf_discussion_pipeline, "pdf_to_markdown", _fake_pdf_to_markdown(markdown_by_name)
    )

    written = prepare_pdf_discussion_batch(pdf_dir, "2026-01-01", "2026-03-01", run_dir)

    assert len(written) == 2
    names = {path.name for path in written}
    assert names == {"AGU23L15.bc-input.json", "DON23L13.bc-input.json"}


def test_prepare_pdf_discussion_batch_sub_splits_over_max_batch_chars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf_dir = tmp_path / "pdfs"
    run_dir = tmp_path / "run"
    _touch_pdfs(pdf_dir, ["AGU23L15.pdf"])
    monkeypatch.setattr(
        pdf_discussion_pipeline, "pdf_to_markdown", _fake_pdf_to_markdown({"AGU23L15.pdf": "irrelevant"})
    )

    # 3 already-candidate sections of ~2000 chars each -- force sub-splitting
    # by capping max_batch_chars well below their combined size.
    fixed_sections = [
        MarkdownSection(
            nombre_pdf="AGU23L15.pdf",
            circuito_pdf="AGU23L15",
            pagina_inicio=page,
            pagina_fin=page,
            periodo_general_informe="2026-01-01 a 2026-03-01",
            markdown=(f"El dia 2026-0{page}-01 se presento una falla en el tramo. " * 30),
        )
        for page in (1, 2, 3)
    ]
    monkeypatch.setattr(
        pdf_discussion_pipeline,
        "split_markdown_sections",
        lambda markdown, **kwargs: fixed_sections,
    )

    written = prepare_pdf_discussion_batch(
        pdf_dir, "2026-01-01", "2026-03-01", run_dir, max_batch_chars=2500
    )

    assert len(written) >= 2
    all_indices: list[int] = []
    for payload_path in written:
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        combined_len = sum(len(s["markdown"]) for s in payload["secciones"])
        assert combined_len <= 2500 or len(payload["secciones"]) == 1
        all_indices.extend(s["indice"] for s in payload["secciones"])
    # Every original candidate section is covered exactly once across all
    # sub-split payload files -- no section dropped or duplicated.
    assert sorted(all_indices) == [1, 2, 3]


# --- assemble_discussion_xlsx / assemble_discussion_xlsx_from_run (design D5, step 5) ---


def _row(circuito: str, inicio: str, fin: str, analisis: str, evidencia: str) -> dict:
    return {
        "Circuito": circuito,
        "Fecha inicio": inicio,
        "Fecha fin": fin,
        "Análisis": analisis,
        "Evidencia": evidencia,
    }


def test_assemble_discussion_xlsx_matches_columnas_finales_shape(tmp_path: Path) -> None:
    assert COLUMNAS_FINALES == ["Circuito", "Fecha inicio", "Fecha fin", "Análisis", "Evidencia"]

    rows = [
        _row("DON23L13", "2025-05-02", "2025-05-02", "Mantenimiento programado.", "05-feb-2025."),
        _row("AGU23L15", "2025-12-21", "2025-12-21", "Mediana del MTTR.", "Grafica de MTTR."),
        _row("AGU23L15", "2025-09-23", "2025-12-18", "Comportamiento de senales.", "Ejercicio de senales."),
    ]
    output_path = tmp_path / "tabla_pdfs.xlsx"

    df = assemble_discussion_xlsx(rows, output_path)

    assert list(df.columns) == COLUMNAS_FINALES
    assert len(df) == 3
    # Sorted by Circuito, Fecha inicio, Fecha fin, Análisis, Evidencia.
    assert list(df["Circuito"]) == ["AGU23L15", "AGU23L15", "DON23L13"]
    assert list(df["Fecha inicio"]) == ["2025-09-23", "2025-12-21", "2025-05-02"]
    assert output_path.exists()
    on_disk = pd.read_excel(output_path)
    assert list(on_disk.columns) == COLUMNAS_FINALES
    assert len(on_disk) == 3


def test_assemble_discussion_xlsx_dedupes_identical_rows(tmp_path: Path) -> None:
    row = _row("AGU23L15", "2025-12-21", "2025-12-21", "Mediana del MTTR.", "Grafica de MTTR.")
    rows = [row, dict(row)]
    output_path = tmp_path / "tabla_pdfs.xlsx"

    df = assemble_discussion_xlsx(rows, output_path)

    assert len(df) == 1


def test_assemble_discussion_xlsx_reindexes_to_columnas_finales_even_with_extra_keys(
    tmp_path: Path,
) -> None:
    row = _row("AGU23L15", "2025-12-21", "2025-12-21", "Mediana del MTTR.", "Grafica de MTTR.")
    row["indice"] = 7  # extra key that must not leak into the final xlsx
    output_path = tmp_path / "tabla_pdfs.xlsx"

    df = assemble_discussion_xlsx([row], output_path)

    assert list(df.columns) == COLUMNAS_FINALES


def test_assemble_discussion_xlsx_from_run_collects_every_rows_json(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)
    (run_dir / "AGU23L15.rows.json").write_text(
        json.dumps(
            [_row("AGU23L15", "2025-12-21", "2025-12-21", "Mediana del MTTR.", "Grafica de MTTR.")],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "DON23L13.rows.json").write_text(
        json.dumps(
            [_row("DON23L13", "2025-05-02", "2025-05-02", "Mantenimiento.", "05-feb-2025.")],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "tabla_pdfs.xlsx"

    df = assemble_discussion_xlsx_from_run(run_dir, output_path)

    assert set(df["Circuito"]) == {"AGU23L15", "DON23L13"}
    assert len(df) == 2
    assert output_path.exists()


def test_assemble_discussion_xlsx_from_run_ignores_non_rows_json_files(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)
    (run_dir / "AGU23L15.rows.json").write_text(
        json.dumps(
            [_row("AGU23L15", "2025-12-21", "2025-12-21", "Mediana del MTTR.", "Grafica de MTTR.")],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "AGU23L15.bc-input.json").write_text("{}", encoding="utf-8")
    output_path = tmp_path / "tabla_pdfs.xlsx"

    df = assemble_discussion_xlsx_from_run(run_dir, output_path)

    assert len(df) == 1
