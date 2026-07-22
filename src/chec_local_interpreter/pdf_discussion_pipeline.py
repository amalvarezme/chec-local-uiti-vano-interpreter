"""Deterministic PDF-discussion batch pipeline (design D5).

This module owns every non-judgment step of the PDF-discussion extraction
runbook: PDF -> Markdown, candidate-section selection, batch payload
assembly, and xlsx assembly. It replaces the deterministic-Python cells of
the deprecated `the retired PDF-discussion notebook`
end to end -- porting `chunk_pdf_pages`, `is_candidate_fragment`,
`detect_report_period`, and `circuito_from_pdf_name` behavior-preservingly.

The classification JUDGMENT (which sections are real discussion rows, and
their `Análisis`/`Evidencia` text) is agent-authored via the batch CLI in
`agent_tools/pdf_discussion.py` (PR A2b) -- this module has no LLM calls
and no model imports, per the "deterministic Python does I/O, agent does
judgment" boundary established across this change.

PDF library: standardized on `pdfplumber` alone (design D5 drops the
notebook's `fitz`-first path -- one documented dependency, already declared
in `requirements.txt`).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pdfplumber

from chec_local_interpreter.context_builder import save_json_artifact

# Single source of truth for the PDF-discussion 5-column schema (design D5).
# `llm_validation.COLUMNAS_FINALES` (used by `validate_pdf_discussion_row`)
# and `expert_alignment.REQUIRED_PDF_DISCUSSION_COLUMNS` (the xlsx reader)
# both import this exact list object rather than redefining it -- consolidated
# in PR A2b after A2a's verify report flagged three independent literal
# copies as a drift risk (WARNING 1).
COLUMNAS_FINALES = ["Circuito", "Fecha inicio", "Fecha fin", "Análisis", "Evidencia"]

MESES = {
    "enero": "01", "febrero": "02", "marzo": "03", "abril": "04",
    "mayo": "05", "junio": "06", "julio": "07", "agosto": "08",
    "septiembre": "09", "setiembre": "09", "octubre": "10",
    "noviembre": "11", "diciembre": "12",
}

TERMINOS_TECNICOS = [
    "falla", "apertura", "interrupción", "interrupcion", "recierre",
    "protección", "proteccion", "descarga atmosférica", "descarga atmosferica",
    "rayo", "vegetación", "vegetacion", "mantenimiento", "indisponibilidad",
    "MTTR", "MTBF", "cabecera", "ramal", "Gantt", "ventana", "causa",
    "recomendación", "recomendacion", "oscilografía", "oscilografia",
    "topología", "topologia", "maniobra", "evento", "afectación",
    "afectacion", "tramo", "circuito",
]

DATE_PATTERNS = [
    r"\b\d{4}-\d{2}-\d{2}\b",
    r"\b\d{1,2}/\d{1,2}/\d{4}\b",
    r"\b\d{1,2}-\d{1,2}-\d{4}\b",
    r"\b\d{1,2}\s+de\s+(?:" + "|".join(MESES) + r")\s+de\s+\d{4}\b",
    r"\b(?:" + "|".join(MESES) + r")\s+de\s+\d{4}\b",
]
DATE_REGEX = re.compile("|".join(DATE_PATTERNS), flags=re.IGNORECASE)
CIRCUIT_REGEX = re.compile(r"\b[A-Z]{2,5}\d{2}L\d{2}\b", flags=re.IGNORECASE)
PDF_CIRCUIT_REGEX = re.compile(r"(?<![A-Z0-9])[A-Z]{2,5}\d{2}L\d{2}(?![A-Z0-9])", flags=re.IGNORECASE)


def circuito_from_pdf_name(pdf_path: Path | str) -> str | None:
    """Extract the circuit code from a PDF's filename stem (ported verbatim
    from the notebook). Returns `None` if the stem does not contain a
    circuit code, so the caller can skip circuit-less PDFs."""
    stem = Path(pdf_path).stem.strip()
    if not stem or not PDF_CIRCUIT_REGEX.search(stem):
        return None
    return stem


_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse_fecha(value: Any) -> pd.Timestamp:
    """Parse a date-ish string into a `pandas.Timestamp` (ported from the
    notebook's `parse_fecha`, including Spanish month-name forms like
    `"10 de enero de 2026"`/`"enero de 2026"`), with one deliberate bugfix
    vs. the notebook (see below).

    Deviation from verbatim porting: the notebook's final fallback called
    `pd.to_datetime(value, errors="coerce", dayfirst=True)` unconditionally.
    For an already-unambiguous ISO string (`YYYY-MM-DD`, `DATE_PATTERNS`'
    first and most common pattern), `dayfirst=True` still silently
    reinterprets the last two ambiguous (<=12) components as day-first --
    e.g. `"2025-11-01"` (2025-Nov-01) parses as 2025-01-11, silently
    swapping month and day whenever both are <=12. This is the exact
    `UserWarning` visible in the notebook's own captured cell output
    (`Parsing dates in %Y-%m-%d format when dayfirst=True was specified`),
    which was a live, unnoticed bug rather than intended behavior. Bypass
    `dayfirst` entirely for values that already match ISO shape; keep
    `dayfirst=True` for the genuinely day-first slash/dash formats
    (`DD/MM/YYYY`, `DD-MM-YYYY`) the notebook's other `DATE_PATTERNS`
    entries target, where day-first IS the correct interpretation.
    """
    if not value:
        return pd.NaT
    text = str(value).strip().lower()
    match = re.fullmatch(r"(\d{1,2})\s+de\s+([a-záéíóúñ]+)\s+de\s+(\d{4})", text)
    if match:
        day, month_name, year = match.groups()
        month = MESES.get(month_name)
        if month:
            return pd.to_datetime(f"{year}-{month}-{int(day):02d}", errors="coerce")
    match = re.fullmatch(r"([a-záéíóúñ]+)\s+de\s+(\d{4})", text)
    if match:
        month_name, year = match.groups()
        month = MESES.get(month_name)
        if month:
            return pd.to_datetime(f"{year}-{month}-01", errors="coerce")
    if _ISO_DATE_RE.match(text):
        return pd.to_datetime(text, format="%Y-%m-%d", errors="coerce")
    return pd.to_datetime(value, errors="coerce", dayfirst=True)


def _iso_fecha(value: str | pd.Timestamp) -> str | None:
    """Normalize a date-ish value to `YYYY-MM-DD`, or `None` if unparseable
    (ported verbatim from the notebook's `iso_fecha`)."""
    parsed = _parse_fecha(str(value)) if not isinstance(value, pd.Timestamp) else value
    if pd.isna(parsed):
        return None
    return parsed.strftime("%Y-%m-%d")


def detect_report_period(text: str) -> tuple[str, str] | None:
    """Detect a report's overall `(start, end)` period from every date
    mentioned in `text` (ported verbatim from the notebook's
    `detect_report_period`): the earliest and latest of at least two dates
    found via `DATE_REGEX`. Returns `None` if fewer than two dates match."""
    fechas = [_iso_fecha(match.group(0)) for match in DATE_REGEX.finditer(text)]
    fechas = [fecha for fecha in fechas if fecha]
    if len(fechas) < 2:
        return None
    sorted_dates = sorted(set(fechas))
    return sorted_dates[0], sorted_dates[-1]


def is_candidate_section(section: MarkdownSection) -> bool:
    """Same heuristic as the notebook's `is_candidate_fragment`: include a
    section only when it contains a technical term AND (a date match OR a
    circuit-code match), where a non-empty `periodo_general_informe` also
    counts as a date signal (ported verbatim, not redesigned)."""
    text = section.markdown
    text_lower = text.lower()
    has_date = bool(DATE_REGEX.search(text)) or bool(section.periodo_general_informe)
    has_circuit = bool(CIRCUIT_REGEX.search(text))
    has_term = any(term.lower() in text_lower for term in TERMINOS_TECNICOS)
    return has_term and (has_date or has_circuit)


def _table_to_markdown(table: list[list[str | None]]) -> str:
    """Render one `pdfplumber` `extract_tables()` table as a GFM pipe-table.

    `table` is `list[list[str | None]]` (rows of cells); the first row is
    treated as the header. Cells shorter/longer than the header row are
    padded/truncated to the header's column count so the GFM table stays
    well-formed even on a slightly ragged extraction.
    """
    rows = [[cell if cell is not None else "" for cell in row] for row in table]
    if not rows:
        return ""
    header = rows[0]
    width = len(header)
    lines = ["| " + " | ".join(str(cell) for cell in header) + " |"]
    lines.append("| " + " | ".join("---" for _ in range(width)) + " |")
    for row in rows[1:]:
        cells = (list(row) + [""] * width)[:width]
        lines.append("| " + " | ".join(str(cell) for cell in cells) + " |")
    return "\n".join(lines)


def pdf_to_markdown(pdf_path: Path) -> str:
    """Convert a PDF into per-page Markdown (design D5, step 1).

    Emits, per page, a `## Página {n}` heading followed by the page's
    extracted text and any extracted tables rendered as GFM pipe-tables.
    A page with no extractable text (whitespace-only counts as no text)
    emits an inline `<!-- Página {n}: sin texto extraíble -->` marker
    instead of silently dropping the page -- ports the notebook's
    "Advertencia: ... no tiene texto extraible" warning into the Markdown
    itself rather than a side-channel print.
    """
    sections: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for idx, page in enumerate(pdf.pages, start=1):
            text = (page.extract_text() or "").strip()
            tables = page.extract_tables() or []
            table_markdowns = [_table_to_markdown(table) for table in tables if table]

            body_parts = [f"## Página {idx}"]
            if not text and not table_markdowns:
                body_parts.append(f"<!-- Página {idx}: sin texto extraíble -->")
            else:
                if text:
                    body_parts.append(text)
                body_parts.extend(table_markdowns)
            sections.append("\n\n".join(body_parts))

    return "\n\n".join(sections) + "\n"


@dataclass(frozen=True)
class MarkdownSection:
    """One chunked Markdown section of a single PDF, ready for candidate
    evaluation (`is_candidate_section`) and, once selected, inclusion in a
    batch payload (`prepare_pdf_discussion_batch`)."""

    nombre_pdf: str
    circuito_pdf: str
    pagina_inicio: int
    pagina_fin: int
    periodo_general_informe: str
    markdown: str


_PAGE_HEADING_RE = re.compile(r"^## Página (\d+)\s*$", flags=re.MULTILINE)


def _split_into_pages(markdown: str) -> list[tuple[int, str]]:
    """Split a `pdf_to_markdown` output back into `(page_number, block)`
    pairs, one per `## Página {n}` heading (block includes the heading)."""
    matches = list(_PAGE_HEADING_RE.finditer(markdown))
    pages: list[tuple[int, str]] = []
    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(markdown)
        page_number = int(match.group(1))
        block = markdown[start:end].rstrip("\n")
        pages.append((page_number, block))
    return pages


def split_markdown_sections(
    markdown: str,
    *,
    nombre_pdf: str,
    circuito_pdf: str,
    periodo_general_informe: str,
    max_chars: int = 6500,
    overlap: int = 800,
) -> list[MarkdownSection]:
    """Chunk a whole-PDF Markdown string into `MarkdownSection`s on
    `## Página` boundaries (design D5, step 2).

    Faithfully ports the notebook's `chunk_pdf_pages` chunking approach
    (buffer-and-flush on `max_chars`, carry the trailing `overlap` chars of
    the flushed buffer into the next chunk) over `pdf_to_markdown`'s output
    instead of the notebook's raw per-page text list.
    """
    pages = _split_into_pages(markdown)
    if not pages:
        return []

    sections: list[MarkdownSection] = []
    buffer = ""
    start_page: int | None = None
    last_page: int | None = None

    for page_number, block in pages:
        page_text = f"\n\n{block}"
        if start_page is None:
            start_page = page_number
        if len(buffer) + len(page_text) > max_chars and buffer.strip():
            sections.append(
                MarkdownSection(
                    nombre_pdf=nombre_pdf,
                    circuito_pdf=circuito_pdf,
                    pagina_inicio=start_page,
                    pagina_fin=last_page if last_page is not None else page_number,
                    periodo_general_informe=periodo_general_informe,
                    markdown=buffer.strip(),
                )
            )
            buffer = buffer[-overlap:] if overlap else ""
            start_page = last_page or page_number
        buffer += page_text
        last_page = page_number

    if buffer.strip() and start_page is not None:
        sections.append(
            MarkdownSection(
                nombre_pdf=nombre_pdf,
                circuito_pdf=circuito_pdf,
                pagina_inicio=start_page,
                pagina_fin=last_page if last_page is not None else start_page,
                periodo_general_informe=periodo_general_informe,
                markdown=buffer.strip(),
            )
        )

    return sections


def _period_to_text(period: tuple[str, str] | None) -> str:
    """Render a `(start, end)` period tuple as the notebook's
    `"{start} a {end}"` text, or `""` when no period was detected."""
    if not period:
        return ""
    return f"{period[0]} a {period[1]}"


def _batch_candidate_sections(
    candidates: list[MarkdownSection], *, max_batch_chars: int
) -> list[list[tuple[int, MarkdownSection]]]:
    """Greedily pack `candidates` (1-based global index preserved) into the
    minimum number of sequential batches whose combined `markdown` length
    stays within `max_batch_chars`. A single section longer than
    `max_batch_chars` on its own still becomes its own one-section batch
    (never dropped, never forced smaller)."""
    indexed = list(enumerate(candidates, start=1))
    batches: list[list[tuple[int, MarkdownSection]]] = []
    current: list[tuple[int, MarkdownSection]] = []
    current_chars = 0
    for indice, section in indexed:
        section_chars = len(section.markdown)
        if current and current_chars + section_chars > max_batch_chars:
            batches.append(current)
            current = []
            current_chars = 0
        current.append((indice, section))
        current_chars += section_chars
    if current:
        batches.append(current)
    return batches


def prepare_pdf_discussion_batch(
    pdf_dir: Path,
    fecha_inicio_usuario: str,
    fecha_fin_usuario: str,
    run_dir: Path,
    *,
    max_batch_chars: int = 40000,
) -> list[Path]:
    """Build the batch payload files for every candidate-bearing PDF in
    `pdf_dir` (design D5, step 3).

    Globs `*.pdf`, resolves each PDF's circuit via `circuito_from_pdf_name`
    (skipping circuit-less PDFs), builds Markdown, keeps only candidate
    sections (`is_candidate_section`), and writes ONE
    `{stem}.bc-input.json` payload per PDF under `run_dir` -- mirroring the
    `auto-simulator.bc.json` convention (D2). A PDF is sub-split into
    multiple `{stem}.bc-input.json` / `{stem}.bc-input.{n}.json` payloads
    only when its concatenated candidate Markdown exceeds `max_batch_chars`
    (one agent invocation per PDF otherwise -- see design's token-efficiency
    analysis). PDFs with zero candidate sections are skipped entirely (no
    payload written). Returns the list of payload file paths written.
    """
    pdf_dir = Path(pdf_dir)
    run_dir = Path(run_dir)
    written: list[Path] = []

    for pdf_path in sorted(pdf_dir.glob("*.pdf")):
        circuito_pdf = circuito_from_pdf_name(pdf_path)
        if circuito_pdf is None:
            continue

        markdown = pdf_to_markdown(pdf_path)
        general_period = detect_report_period(markdown)
        periodo_general_informe = _period_to_text(general_period)

        sections = split_markdown_sections(
            markdown,
            nombre_pdf=pdf_path.name,
            circuito_pdf=circuito_pdf,
            periodo_general_informe=periodo_general_informe,
        )
        candidates = [section for section in sections if is_candidate_section(section)]
        if not candidates:
            continue

        batches = _batch_candidate_sections(candidates, max_batch_chars=max_batch_chars)
        for batch_index, batch in enumerate(batches, start=1):
            payload = {
                "fecha_inicio_usuario": fecha_inicio_usuario,
                "fecha_fin_usuario": fecha_fin_usuario,
                "nombre_pdf": pdf_path.name,
                "circuito_pdf": circuito_pdf,
                "periodo_general_informe": periodo_general_informe,
                "secciones": [
                    {
                        "indice": indice,
                        "pagina_inicio": section.pagina_inicio,
                        "pagina_fin": section.pagina_fin,
                        "markdown": section.markdown,
                    }
                    for indice, section in batch
                ],
            }
            suffix = "" if batch_index == 1 else f".{batch_index}"
            payload_path = run_dir / f"{pdf_path.stem}.bc-input{suffix}.json"
            save_json_artifact(payload, payload_path)
            written.append(payload_path)

    return written


def assemble_discussion_xlsx(rows: list[dict[str, Any]], output_path: Path) -> pd.DataFrame:
    """Assemble accepted rows into the final `COLUMNAS_FINALES`-shaped
    table and write it to `output_path` (design D5, step 5; ports the
    notebook's cell 7 dedupe/sort/reindex/`to_excel` sequence verbatim).

    Extra keys on a row dict (e.g. a batch's own `indice`) are dropped by
    the final `reindex`, so callers may pass through row dicts unmodified.
    """
    df = pd.DataFrame(rows, columns=COLUMNAS_FINALES)
    if not df.empty:
        df = df.drop_duplicates(subset=COLUMNAS_FINALES).sort_values(
            by=["Circuito", "Fecha inicio", "Fecha fin", "Análisis", "Evidencia"]
        )
    df = df.reindex(columns=COLUMNAS_FINALES)
    df.to_excel(output_path, index=False)
    return df


def assemble_discussion_xlsx_from_run(run_dir: Path, output_path: Path) -> pd.DataFrame:
    """Collect every `{stem}.rows.json` file under `run_dir` (each a JSON
    list of accepted row dicts, written by the batch `validate` verb --
    PR A2b) and assemble them into the final xlsx via
    `assemble_discussion_xlsx` (design D5, step 5)."""
    run_dir = Path(run_dir)
    rows: list[dict[str, Any]] = []
    for rows_path in sorted(run_dir.glob("*.rows.json")):
        payload = json.loads(rows_path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            rows.extend(item for item in payload if isinstance(item, dict))
    return assemble_discussion_xlsx(rows, output_path)
