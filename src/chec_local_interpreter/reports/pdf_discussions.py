"""PDF discussion extraction helpers for report notebooks."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Callable

import pandas as pd

from chec_local_interpreter.llm.client import call_llm

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover - optional dependency fallback
    fitz = None

try:
    import pdfplumber
except ImportError:  # pragma: no cover - optional dependency fallback
    pdfplumber = None

MESES = {
    "enero": "01",
    "febrero": "02",
    "marzo": "03",
    "abril": "04",
    "mayo": "05",
    "junio": "06",
    "julio": "07",
    "agosto": "08",
    "septiembre": "09",
    "setiembre": "09",
    "octubre": "10",
    "noviembre": "11",
    "diciembre": "12",
}

TERMINOS_TECNICOS = [
    "falla",
    "apertura",
    "interrupción",
    "interrupcion",
    "recierre",
    "protección",
    "proteccion",
    "descarga atmosférica",
    "descarga atmosferica",
    "rayo",
    "vegetación",
    "vegetacion",
    "mantenimiento",
    "indisponibilidad",
    "MTTR",
    "MTBF",
    "cabecera",
    "ramal",
    "Gantt",
    "ventana",
    "causa",
    "recomendación",
    "recomendacion",
    "oscilografía",
    "oscilografia",
    "topología",
    "topologia",
    "maniobra",
    "evento",
    "afectación",
    "afectacion",
    "tramo",
    "circuito",
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
PDF_CIRCUIT_REGEX = re.compile(
    r"(?<![A-Z0-9])[A-Z]{2,5}\d{2}L\d{2}(?![A-Z0-9])", flags=re.IGNORECASE
)


@dataclass(frozen=True)
class PDFPageText:
    nombre_pdf: str
    pagina: int
    texto: str


@dataclass(frozen=True)
class PDFFragment:
    nombre_pdf: str
    pagina_inicio: int
    pagina_fin: int
    periodo_general_informe: str
    fragmento: str


def circuito_from_pdf_name(pdf_path: Path | str) -> str | None:
    """Return the PDF stem when it contains a valid circuit identifier."""
    stem = Path(pdf_path).stem.strip()
    if not stem or not PDF_CIRCUIT_REGEX.search(stem):
        return None
    return stem


def parse_fecha(value: str | None) -> pd.Timestamp | pd.NaT:
    """Parse Spanish and numeric date strings using pandas coercion."""
    if not value:
        return pd.NaT
    text = str(value).strip().lower()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return pd.to_datetime(value, errors="coerce", format="%Y-%m-%d")
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
    return pd.to_datetime(value, errors="coerce", dayfirst=True)


def iso_fecha(value: str | pd.Timestamp) -> str | None:
    """Return YYYY-MM-DD for a parseable date value."""
    parsed = parse_fecha(str(value)) if not isinstance(value, pd.Timestamp) else value
    if pd.isna(parsed):
        return None
    return parsed.strftime("%Y-%m-%d")


def overlaps(start: str, end: str, user_start: str, user_end: str) -> bool:
    """Check whether two date intervals overlap."""
    start_ts = parse_fecha(start)
    end_ts = parse_fecha(end)
    user_start_ts = parse_fecha(user_start)
    user_end_ts = parse_fecha(user_end)
    if any(pd.isna(x) for x in [start_ts, end_ts, user_start_ts, user_end_ts]):
        return False
    return start_ts <= user_end_ts and end_ts >= user_start_ts


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Extract the first JSON object from plain or fenced model output."""
    if not text:
        return None
    cleaned = re.sub(r"```(?:json)?|```", "", text).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            return json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            return None


def validate_llm_row(
    payload: dict[str, Any],
    user_start: str,
    user_end: str,
    *,
    final_columns: list[str],
) -> tuple[bool, list[str]]:
    """Validate one extracted discussion row against required fields and date range."""
    errors = []
    if payload.get("include") is not True:
        return False, [payload.get("reason", "include=false")]
    for col in final_columns:
        if not str(payload.get(col, "")).strip():
            errors.append(f"{col} vacio")
    start = iso_fecha(payload.get("Fecha inicio"))
    end = iso_fecha(payload.get("Fecha fin"))
    if start is None:
        errors.append("Fecha inicio invalida")
    if end is None:
        errors.append("Fecha fin invalida")
    if start and end and parse_fecha(start) > parse_fecha(end):
        errors.append("Fecha inicio posterior a Fecha fin")
    if start and end and not overlaps(start, end, user_start, user_end):
        errors.append("La discusion no se traslapa con el rango del usuario")
    return len(errors) == 0, errors


def extract_pdf_pages(pdf_path: Path) -> list[PDFPageText]:
    """Extract text pages using PyMuPDF or pdfplumber."""
    pages = []
    if fitz is not None:
        with fitz.open(pdf_path) as doc:
            for idx, page in enumerate(doc, start=1):
                text = page.get_text("text") or ""
                if not text.strip():
                    print(f"Advertencia: {pdf_path.name} pagina {idx} no tiene texto extraible.")
                pages.append(PDFPageText(pdf_path.name, idx, text))
        return pages
    if pdfplumber is not None:
        with pdfplumber.open(pdf_path) as doc:
            for idx, page in enumerate(doc.pages, start=1):
                text = page.extract_text() or ""
                if not text.strip():
                    print(f"Advertencia: {pdf_path.name} pagina {idx} no tiene texto extraible.")
                pages.append(PDFPageText(pdf_path.name, idx, text))
        return pages
    raise ImportError("Instala pymupdf o pdfplumber para extraer texto de PDFs.")


def detect_report_period(text: str) -> tuple[str, str] | None:
    """Detect a report period from date mentions in text."""
    dates = [iso_fecha(match.group(0)) for match in DATE_REGEX.finditer(text)]
    dates = [date for date in dates if date]
    if len(dates) < 2:
        return None
    sorted_dates = sorted(set(dates))
    return sorted_dates[0], sorted_dates[-1]


def period_to_text(period: tuple[str, str] | None) -> str:
    """Format a detected period for prompt context."""
    if not period:
        return ""
    return f"{period[0]} a {period[1]}"


def chunk_pdf_pages(
    pages: list[PDFPageText],
    general_period: tuple[str, str] | None,
    *,
    chunk_chars: int,
    chunk_overlap: int = 0,
) -> list[PDFFragment]:
    """Chunk PDF pages into overlapping text fragments."""
    if not pages:
        return []
    fragments = []
    buffer = ""
    start_page = None
    last_page = None
    period_text = period_to_text(general_period)
    for page in pages:
        page_text = f"\n\n[Pagina {page.pagina}]\n{page.texto.strip()}"
        if start_page is None:
            start_page = page.pagina
        if len(buffer) + len(page_text) > chunk_chars and buffer.strip():
            fragments.append(PDFFragment(page.nombre_pdf, start_page, last_page or page.pagina, period_text, buffer.strip()))
            buffer = buffer[-chunk_overlap:] if chunk_overlap else ""
            start_page = last_page or page.pagina
        buffer += page_text
        last_page = page.pagina
    if buffer.strip() and start_page is not None:
        fragments.append(PDFFragment(pages[0].nombre_pdf, start_page, last_page or start_page, period_text, buffer.strip()))
    return fragments


def is_candidate_fragment(fragment: PDFFragment, *, technical_terms: list[str] | None = None) -> bool:
    """Select fragments with technical terms and either date or circuit evidence."""
    terms = technical_terms or TERMINOS_TECNICOS
    text = fragment.fragmento
    text_lower = text.lower()
    has_date = bool(DATE_REGEX.search(text)) or bool(fragment.periodo_general_informe)
    has_circuit = bool(CIRCUIT_REGEX.search(text))
    has_term = any(term.lower() in text_lower for term in terms)
    return has_term and (has_date or has_circuit)


class PDFDiscussionExtractionSkill:
    """Load a versioned PDF discussion extraction skill and call an LLM."""

    def __init__(
        self,
        skill_path: Path,
        provider: str,
        model: str,
        call_enabled: bool,
        max_output_tokens: int = 2048,
        llm_caller: Callable[..., Any] = call_llm,
    ):
        self.skill_path = Path(skill_path)
        self.skill_template = self.skill_path.read_text(encoding="utf-8")
        self.provider = provider
        self.model = model
        self.call_enabled = call_enabled
        self.max_output_tokens = max_output_tokens
        self.llm_caller = llm_caller

    def build_prompt(self, context: dict[str, Any]) -> str:
        prompt = self.skill_template
        for key, value in context.items():
            prompt = prompt.replace("{" + key + "}", str(value))
        return prompt.strip()

    def extract(self, context: dict[str, Any]) -> dict[str, Any]:
        prompt = self.build_prompt(context)
        result = self.llm_caller(
            prompt,
            provider=self.provider,
            model=self.model,
            call_enabled=self.call_enabled,
            display_progress=False,
            display_content=False,
            max_output_tokens=self.max_output_tokens,
        )
        return {
            "prompt": prompt,
            "skill_path": str(self.skill_path),
            "context": context,
            "called": result.called,
            "message": result.message,
            "raw_output": result.output_text,
            "parsed": extract_json_object(result.output_text or ""),
        }
