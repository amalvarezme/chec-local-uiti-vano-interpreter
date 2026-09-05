"""Turn a finished `/report` run directory into one illustrative picture of
what the agents did, without spending a single token.

Everything this needs is already on disk when a run ends: `stage_timing.json`,
`token_usage.json`, `l1_state.json` and each stage's `.bc.json` / `.out.json`.
So there is no LLM call here, no socket, no polling loop and no third-party
dependency -- the module reads files and emits one self-contained SVG string.
That is the whole design constraint, and it is why the output is hand-rolled
SVG rather than a charting library: for four bars, every library on offer
weighs more than the thing it draws, and several of them need the network at
view time. This one renders from `file://` and prints into a PDF.

The timeline is the point, and it is not decoration. `historical` and
`inference` are dispatched CONCURRENTLY by design (`.claude/skills/report/
SKILL.md`: "those two roles are dispatched concurrently by design"), so the
three stage durations do not partition the run's wall clock -- summed end to
end they overrun the true span by 13-40%. Drawing them as a contiguous queue
would render every run about a quarter longer than it was. Measured across the
15 archived runs, `historical` and `inference` each finish within 5-26 s of
`fin_preparacion + su propia duracion`, while a sequential schedule would put
`inference` 216-448 s later; so both branches start at offset zero here, and
the third stage waits on the later of the two.

What is deliberately NOT drawn: the deterministic preparation and the final
HTML render. `report_pipeline.TOKEN_USAGE_STAGES` only instruments the three
agent stages, so those two have no measured duration in the artifacts. Showing
them with invented widths would be the same lie in a different place.
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path
from typing import Any

# The two roles the orchestrator dispatches concurrently for one circuit.
# Order matters: it is the order the bars are stacked in.
_ETAPAS = ("historical", "inference", "expert-alignment")
_CONCURRENTES = ("historical", "inference")

# What each agent actually does, in words a non-technical reader can hold.
_QUE_HACE = {
    "historical": "Lee la historia del circuito y describe como se comporto",
    "inference": "Interpreta el modelo: que variable pesa en cada vano",
    "expert-alignment": "Contrasta lo anterior con los informes de los expertos",
}

_COLOR = {
    "historical": "#2e7d32",
    "inference": "#1f5fa9",
    "expert-alignment": "#8a4bbd",
}


def _leer_json(ruta: Path) -> Any:
    """Read a JSON file, returning `None` for anything unreadable.

    A half-written or truncated artifact must degrade into "no measurement"
    rather than into a traceback: this renderer runs after the work is done
    and must never be the thing that fails a finished run.
    """
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _considerada(run_dir: Path, etapa: str) -> bool:
    """Same "considered stage" gate `report_pipeline` uses: a stage counts
    when it left a context package and/or an ok output behind."""
    if (run_dir / f"{etapa}.bc.json").exists():
        return True
    salida = _leer_json(run_dir / f"{etapa}.out.json")
    return isinstance(salida, dict) and salida.get("ok") is True


def construir_linea_tiempo(run_dir: Path | str) -> dict[str, Any]:
    """Resolve one run directory into the data the picture needs.

    Returns `{circuito, ventanas, etapas, reloj_de_pared_segundos,
    ahorro_segundos, tokens_totales}`, where each entry of `etapas` carries
    `{etapa, que_hace, inicio_segundos, duracion_segundos, tokens,
    entrada_bytes, salida_bytes, color}`.

    `inicio_segundos` is DERIVED, not measured: the two concurrent roles both
    start at 0 and the third starts at the later of their two ends. See the
    module docstring for why that is the honest schedule and a contiguous
    queue is not.
    """
    run_dir = Path(run_dir)

    tiempos = _leer_json(run_dir / "stage_timing.json") or {}
    tokens = _leer_json(run_dir / "token_usage.json") or {}
    estado = _leer_json(run_dir / "l1_state.json") or {}
    if not isinstance(tiempos, dict):
        tiempos = {}
    if not isinstance(tokens, dict):
        tokens = {}
    if not isinstance(estado, dict):
        estado = {}

    def _dur(etapa: str) -> float:
        entrada = tiempos.get(etapa)
        if isinstance(entrada, dict):
            valor = entrada.get("duration_seconds")
            if isinstance(valor, (int, float)):
                return float(valor)
        return 0.0

    def _tok(etapa: str) -> int | None:
        bruto = tokens.get(etapa)
        total = bruto.get("total") if isinstance(bruto, dict) else None
        return total if isinstance(total, int) else None

    crudas = [
        {
            "etapa": etapa,
            "duracion_segundos": _dur(etapa),
            "tokens": _tok(etapa),
            "entrada_bytes": (
                (run_dir / f"{etapa}.bc.json").stat().st_size
                if (run_dir / f"{etapa}.bc.json").exists()
                else None
            ),
            "salida_bytes": (
                (run_dir / f"{etapa}.out.json").stat().st_size
                if (run_dir / f"{etapa}.out.json").exists()
                else None
            ),
        }
        for etapa in _ETAPAS
        if etapa in tiempos and _considerada(run_dir, etapa)
    ]

    return _armar_horario(
        crudas,
        circuito=estado.get("circuito"),
        fecha_inicio=estado.get("fecha_inicio"),
        fecha_fin=estado.get("fecha_fin"),
        ventanas=estado.get("ventanas_estudio") or [],
    )


def _armar_horario(
    crudas: list[dict[str, Any]],
    *,
    circuito: Any = None,
    fecha_inicio: Any = None,
    fecha_fin: Any = None,
    ventanas: Any = None,
) -> dict[str, Any]:
    """Place already-resolved stages on the timeline and total the run.

    The one decision that lives here: the barrier. `historical` and
    `inference` are dispatched concurrently, so both start at 0 and the third
    stage starts at the LATER of their two ends -- the max of their durations,
    never their sum. Both constructors share this so the picture cannot drift
    between the standalone page and the circuit report.
    """
    barrera = max(
        (c["duracion_segundos"] for c in crudas if c["etapa"] in _CONCURRENTES),
        default=0.0,
    )

    etapas: list[dict[str, Any]] = []
    for c in crudas:
        etapa = c["etapa"]
        etapas.append(
            {
                "etapa": etapa,
                "que_hace": _QUE_HACE.get(etapa, ""),
                "inicio_segundos": 0.0 if etapa in _CONCURRENTES else barrera,
                "duracion_segundos": c["duracion_segundos"],
                "tokens": c.get("tokens"),
                "token_source": c.get("token_source"),
                "entrada_bytes": c.get("entrada_bytes"),
                "salida_bytes": c.get("salida_bytes"),
                "color": _COLOR.get(etapa, "#666666"),
            }
        )

    reloj = max((e["inicio_segundos"] + e["duracion_segundos"] for e in etapas), default=0.0)
    suma = sum(e["duracion_segundos"] for e in etapas)
    medidos = [e["tokens"] for e in etapas if e["tokens"] is not None]

    return {
        "circuito": circuito,
        "fecha_inicio": fecha_inicio,
        "fecha_fin": fecha_fin,
        "ventanas": list(ventanas or []),
        "etapas": etapas,
        "reloj_de_pared_segundos": reloj,
        "suma_de_etapas_segundos": suma,
        "ahorro_segundos": suma - reloj,
        "tokens_totales": sum(medidos) if medidos else None,
    }


def linea_desde_desglose(
    stage_breakdown: list[dict[str, Any]] | None,
    *,
    circuito: Any = None,
    fecha_inicio: Any = None,
    fecha_fin: Any = None,
    ventanas: Any = None,
) -> dict[str, Any]:
    """Build the same timeline from `report_pipeline._resolve_stage_breakdown`.

    `plotting.render_llm_analysis` already RECEIVES that list, so the circuit
    report needs no run directory and no new argument to draw the figure. The
    only thing unavailable by this route is each stage's input/output size,
    which requires looking at the files; those come back `None`.

    A stage name outside `_ETAPAS` is dropped rather than scheduled: an
    unknown role has no place in a barrier whose whole meaning is which two
    run concurrently.
    """
    entradas = stage_breakdown or []
    por_nombre = {
        e.get("stage"): e for e in entradas if isinstance(e, dict) and e.get("stage")
    }

    def _num(valor: Any) -> float:
        return float(valor) if isinstance(valor, (int, float)) else 0.0

    crudas = [
        {
            "etapa": etapa,
            "duracion_segundos": _num(por_nombre[etapa].get("duration_seconds")),
            "tokens": (
                por_nombre[etapa].get("tokens_total")
                if isinstance(por_nombre[etapa].get("tokens_total"), int)
                else None
            ),
            "token_source": por_nombre[etapa].get("token_source"),
            "entrada_bytes": None,
            "salida_bytes": None,
        }
        for etapa in _ETAPAS
        if etapa in por_nombre
    ]

    return _armar_horario(
        crudas,
        circuito=circuito,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        ventanas=ventanas,
    )


def _mmss(segundos: float) -> str:
    total = int(round(max(segundos, 0.0)))
    return f"{total // 60}:{total % 60:02d}"


def _miles(n: int) -> str:
    """Spanish thousands separator: 138831 -> '138.831'."""
    return f"{n:,}".replace(",", ".")


def render_svg(linea: dict[str, Any], ancho: int = 860) -> str:
    """Render the timeline as one self-contained SVG string.

    No `<script>`, no `<foreignObject>`, no external reference of any kind:
    the result is safe to inline into an HTML page, open from `file://`, or
    drop into a LaTeX-bound PDF pipeline.
    """
    etapas = linea["etapas"]
    if not etapas:
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{ancho}" height="60" '
            f'viewBox="0 0 {ancho} 60"><text x="12" y="34" font-size="13" '
            'fill="#64748b" font-family="Helvetica,Arial,sans-serif">'
            "Esta corrida no dejo medidas de etapa.</text></svg>"
        )

    izq, der = 208, 150            # gutters for the label and the duration
    fila, sep = 46, 14
    cabecera, pie = 34, 46
    util = ancho - izq - der
    alto = cabecera + len(etapas) * (fila + sep) + pie
    escala = util / linea["reloj_de_pared_segundos"] if linea["reloj_de_pared_segundos"] else 0.0

    o: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{ancho}" height="{alto}" '
        f'viewBox="0 0 {ancho} {alto}" font-family="Helvetica,Arial,sans-serif">',
        f'<rect width="{ancho}" height="{alto}" fill="#ffffff"/>',
    ]

    # Time axis: one tick every whole minute.
    minutos = int(linea["reloj_de_pared_segundos"] // 60) + 1
    for m in range(minutos + 1):
        x = izq + m * 60 * escala
        if x > izq + util + 1:
            break
        o.append(
            f'<line x1="{x:.1f}" y1="{cabecera - 8}" x2="{x:.1f}" y2="{alto - pie + 6}" '
            'stroke="#e2e8f0" stroke-width="1"/>'
        )
        o.append(
            f'<text x="{x:.1f}" y="{cabecera - 14}" font-size="10" fill="#94a3b8" '
            f'text-anchor="middle">{m} min</text>'
        )

    # The concurrency bracket, drawn only when two roles really do overlap.
    concurrentes = [e for e in etapas if e["inicio_segundos"] == 0.0 and len(etapas) > 1]
    if len(concurrentes) > 1:
        y0 = cabecera + 4
        y1 = cabecera + len(concurrentes) * (fila + sep) - sep - 4
        o.append(
            f'<path d="M {izq - 5} {y0} L {izq - 11} {y0} L {izq - 11} {y1} L {izq - 5} {y1}" '
            'fill="none" stroke="#94a3b8" stroke-width="1.2"/>'
        )
        o.append(
            f'<text x="{izq - 11}" y="{(y0 + y1) / 2 + 3.5}" font-size="9.5" fill="#64748b" '
            f'text-anchor="middle" transform="rotate(-90 {izq - 11} '
            f'{(y0 + y1) / 2 + 3.5})">a la vez</text>'
        )

    for i, e in enumerate(etapas):
        y = cabecera + i * (fila + sep)
        x = izq + e["inicio_segundos"] * escala
        w = max(e["duracion_segundos"] * escala, 2.0)

        o.append(
            f'<text x="{izq - 30}" y="{y + 17}" font-size="12.5" font-weight="bold" '
            f'fill="#1e293b" text-anchor="end">{html.escape(e["etapa"])}</text>'
        )
        o.append(
            f'<text x="{izq - 30}" y="{y + 32}" font-size="9.5" fill="#64748b" '
            f'text-anchor="end">{html.escape(_recortar(e["que_hace"], 31))}</text>'
        )
        o.append(
            f'<rect data-etapa="{html.escape(e["etapa"])}" x="{x:.1f}" y="{y}" '
            f'width="{w:.1f}" height="{fila - 12}" rx="3" fill="{e["color"]}" opacity="0.88"/>'
        )
        tok = f' · {_miles(e["tokens"])} tokens' if e["tokens"] is not None else ""
        o.append(
            f'<text x="{izq + util + 12}" y="{y + 22}" font-size="11" fill="#334155">'
            f'{_mmss(e["duracion_segundos"])}{html.escape(tok)}</text>'
        )

    # Footer: the wall clock, and what the overlap bought.
    y = alto - pie + 20
    o.append(
        f'<line x1="{izq}" y1="{y - 12}" x2="{izq + util}" y2="{y - 12}" '
        'stroke="#cbd5e1" stroke-width="1"/>'
    )
    o.append(
        f'<text x="{izq}" y="{y + 6}" font-size="11.5" fill="#1e293b">'
        f'Reloj de pared: <tspan font-weight="bold">{_mmss(linea["reloj_de_pared_segundos"])}</tspan>'
        f'  ·  suma de las etapas: {_mmss(linea["suma_de_etapas_segundos"])}'
        f'  ·  ahorrado por correr a la vez: '
        f'<tspan font-weight="bold">{_mmss(linea["ahorro_segundos"])}</tspan></text>'
    )
    o.append("</svg>")
    return "".join(o)


def _recortar(texto: str, n: int) -> str:
    return texto if len(texto) <= n else texto[: n - 1].rstrip() + "…"


def render_pagina(linea: dict[str, Any]) -> str:
    """Wrap `render_svg` in a standalone HTML page.

    Self-contained on purpose: no stylesheet link, no script, no font
    request. It opens from a double click and survives being emailed.
    """
    circuito = html.escape(str(linea.get("circuito") or "corrida"))
    periodo = ""
    if linea.get("fecha_inicio") and linea.get("fecha_fin"):
        periodo = (
            f'{html.escape(str(linea["fecha_inicio"]))} a '
            f'{html.escape(str(linea["fecha_fin"]))}'
        )
    ventanas = ", ".join(html.escape(str(v)) for v in linea.get("ventanas") or [])
    tokens = (
        _miles(linea["tokens_totales"]) if linea.get("tokens_totales") is not None else "N/D"
    )

    filas = "".join(
        "<tr>"
        f'<td class="n" style="border-left:4px solid {e["color"]}">{html.escape(e["etapa"])}</td>'
        f'<td>{html.escape(e["que_hace"])}</td>'
        f'<td class="r">{_mmss(e["duracion_segundos"])}</td>'
        f'<td class="r">{_miles(e["tokens"]) if e["tokens"] is not None else "N/D"}</td>'
        f'<td class="r">{_kb(e["entrada_bytes"])}</td>'
        f'<td class="r">{_kb(e["salida_bytes"])}</td>'
        "</tr>"
        for e in linea["etapas"]
    )

    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Trabajo de los agentes &middot; {circuito}</title>
<style>
 :root {{ color-scheme: light; }}
 body {{ margin:0; padding:28px; background:#f8fafc; color:#0f172a;
        font:14px/1.55 Helvetica,Arial,sans-serif; }}
 .caja {{ max-width:920px; margin:0 auto; background:#fff; border:1px solid #e2e8f0;
          border-radius:10px; padding:24px 26px; }}
 h1 {{ margin:0 0 2px; font-size:19px; }}
 .sub {{ color:#64748b; font-size:12.5px; margin-bottom:20px; }}
 .fig {{ overflow-x:auto; }}
 table {{ border-collapse:collapse; width:100%; margin-top:20px; font-size:12.5px; }}
 th {{ text-align:left; color:#64748b; font-weight:600; border-bottom:1px solid #e2e8f0;
       padding:7px 9px; }}
 td {{ padding:7px 9px; border-bottom:1px solid #f1f5f9; }}
 td.n {{ font-weight:600; padding-left:10px; }}
 td.r, th.r {{ text-align:right; }}
 .nota {{ margin-top:18px; color:#475569; font-size:12px; border-top:1px solid #e2e8f0;
          padding-top:14px; }}
</style></head><body>
<div class="caja">
 <h1>Que hicieron los agentes &mdash; {circuito}</h1>
 <div class="sub">Periodo {periodo} &middot; ventanas {ventanas} &middot; {tokens} tokens en total</div>
 <div class="fig">{render_svg(linea)}</div>
 <table>
  <tr><th>Agente</th><th>Que hace</th><th class="r">Tiempo</th><th class="r">Tokens</th>
      <th class="r">Leyo</th><th class="r">Escribio</th></tr>
  {filas}
 </table>
 <p class="nota"><strong>Como leer esta figura.</strong> Las dos primeras barras arrancan
 juntas porque esos dos agentes trabajan <strong>en paralelo</strong>: uno describe la
 historia del circuito y el otro interpreta el modelo, y ninguno necesita lo que produce el
 otro. El tercero si espera a los dos, porque su trabajo es contrastarlos. Por eso el reloj
 de pared es menor que la suma de los tiempos.</p>
</div></body></html>"""


def _kb(n: int | None) -> str:
    if n is None:
        return "N/D"
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.0f} KB".replace(".", ",")
    return f"{n / 1024 / 1024:.1f} MB".replace(".", ",")


def main(argv: list[str] | None = None) -> int:
    """`python -m chec_local_interpreter.agentes_linea_tiempo <corrida> [-o SALIDA]`.

    Writes the standalone page next to the run directory by default, so the
    picture travels with the artifacts it describes.
    """
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Dibuja lo que hicieron los agentes en una corrida de /report. "
            "Solo lee archivos: no llama a ningun modelo ni abre conexiones."
        )
    )
    parser.add_argument("corrida", help="carpeta de la corrida (runs/<CIRCUITO>/<SELLO>)")
    parser.add_argument(
        "-o",
        "--salida",
        default=None,
        help="archivo HTML de salida (por omision, <corrida>/agentes.html)",
    )
    args = parser.parse_args(argv)

    run_dir = Path(args.corrida)
    if not run_dir.is_dir():
        # Returned, not raised: `main` stays callable from a test or another
        # script, and the `__main__` wrapper below turns it into an exit code.
        print(f"No existe la carpeta de corrida: {run_dir}", file=sys.stderr)
        return 2

    linea = construir_linea_tiempo(run_dir)
    destino = Path(args.salida) if args.salida else run_dir / "agentes.html"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(render_pagina(linea), encoding="utf-8")

    etapas = len(linea["etapas"])
    print(
        f"{destino}  ({etapas} etapas, reloj de pared {_mmss(linea['reloj_de_pared_segundos'])}, "
        f"ahorro {_mmss(linea['ahorro_segundos'])})"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - envoltura de linea de comandos
    raise SystemExit(main())


# Etiqueta de procedencia de los tokens, con el mismo vocabulario que ya usa
# el informe de circuito (`plotting._token_source_label`): duplicado aqui a
# proposito para no acoplar este modulo -- que tiene que poder correr suelto,
# sin pandas ni plotly -- al modulo de graficas.
_PROCEDENCIA = {
    "measured": "medidos",
    "mixed": "parcialmente medidos",
    "estimated": "estimados",
}


def _celda_tokens(etapa: dict[str, Any]) -> str:
    """Token count, prefixed with `~` when it is not a measured figure.

    Same convention the report already uses for approximate counts
    (`plotting._token_source_label`), so the figure does not invent a second
    vocabulary for the same distinction the old table carried per row.
    """
    if etapa.get("tokens") is None:
        return "N/D"
    prefijo = "" if etapa.get("token_source") == "measured" else "~"
    return f'{prefijo}{_miles(etapa["tokens"])}'


def seccion_agentes_html(linea: dict[str, Any] | None) -> str:
    """The block the circuit report embeds, right above "construido por agentes".

    Returns "" when there is nothing to draw, so a visualization-only run
    (no LLM analysis) does not leave an empty box behind.
    """
    if not linea or not linea.get("etapas"):
        return ""

    etapas = linea["etapas"]
    procedencias = {
        _PROCEDENCIA.get(e.get("token_source") or "", "")
        for e in etapas
        if e.get("tokens") is not None
    }
    procedencias.discard("")
    nota_tokens = (
        f" Tokens {' y '.join(sorted(procedencias))}." if procedencias else ""
    )

    filas = "".join(
        "<tr>"
        f'<td style="border-left:4px solid {e["color"]};padding-left:9px;font-weight:600;">'
        f'{html.escape(e["etapa"])}</td>'
        f'<td>{html.escape(e["que_hace"])}</td>'
        f'<td style="text-align:right;">{_mmss(e["duracion_segundos"])}</td>'
        f'<td style="text-align:right;">{_celda_tokens(e)}</td>'
        "</tr>"
        for e in etapas
    )

    concurrentes = [e for e in etapas if e["inicio_segundos"] == 0.0]
    if len(concurrentes) > 1:
        explicacion = (
            "Las dos primeras barras arrancan juntas porque esos agentes trabajan "
            "<strong>en paralelo</strong>: uno describe la historia del circuito y el otro "
            "interpreta el modelo, y ninguno necesita lo que produce el otro. El tercero sí "
            "espera a los dos, porque su trabajo es contrastarlos."
        )
        # La consecuencia solo se afirma cuando se cumple. Si a una etapa le
        # falta la duracion medida, su barra vale cero y el reloj de pared
        # IGUALA la suma: decir ahi "es menor" seria describir otra corrida.
        if linea.get("ahorro_segundos", 0.0) > 0:
            explicacion += " Por eso el reloj de pared es menor que la suma de los tiempos."
    else:
        explicacion = "Cada barra es una etapa de agente, con su tiempo y su consumo medidos."

    return (
        '<div class="content-box" style="margin-top:26px;">'
        '<h2 style="margin-top:0;">🤖 Cómo se construyó este informe</h2>'
        # `overflow-x` y no un ancho fluido: el SVG lleva rotulos de 9,5 px que
        # a media escala dejan de leerse. En una pantalla angosta se desplaza,
        # que es peor de lo que se ve pero mejor que ilegible.
        '<div style="overflow-x:auto;text-align:center;">'
        f"{render_svg(linea)}"
        "</div>"
        '<table style="width:100%;border-collapse:collapse;font-size:0.9em;margin-top:14px;">'
        '<tr style="color:#64748b;text-align:left;border-bottom:1px solid #e2e8f0;">'
        "<th>Agente</th><th>Qué hace</th>"
        '<th style="text-align:right;">Tiempo</th>'
        '<th style="text-align:right;">Tokens</th></tr>'
        f"{filas}</table>"
        f'<p style="margin:14px 0 0;font-size:0.88em;color:#475569;">{explicacion}'
        f"{html.escape(nota_tokens)}</p>"
        "</div>"
    )
