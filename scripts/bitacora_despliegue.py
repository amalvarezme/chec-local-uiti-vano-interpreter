#!/usr/bin/env python3
"""Bitacora de despliegue para los comandos `/app-*` y `/subir-*-databricks`.

Cada corrida de esos comandos escribe aqui un Markdown con lo que hizo, lo que
fallo y lo que quedo bloqueado. El documento se **re-renderiza completo en cada
llamada** a partir de un JSON paralelo, no se va concatenando: una corrida que
se muere a mitad de camino deja igual un archivo legible, que es justamente el
caso para el que existe.

Uso tipico dentro de un comando:

    RUTA=$(python3 scripts/bitacora_despliegue.py init \
             --comando /app-vano-clima --cuaderno notebooks/... \
             --workspace https://... --app vano-clima --perfil azure-chec)

    python3 scripts/bitacora_despliegue.py paso --archivo "$RUTA" \
             --id 2 --titulo "Preflight" --estado ok --detalle "..." \
             --comando "databricks fs ls ..." --salida "$SALIDA"

    python3 scripts/bitacora_despliegue.py restriccion --archivo "$RUTA" \
             --id R1 --titulo "Falta USE CATALOG" --severidad bloqueante \
             --impacto "..." --rodeo "..." --quien-desbloquea "..."

    python3 scripts/bitacora_despliegue.py cerrar --archivo "$RUTA" --url https://...
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ESTADOS_PASO = ("ok", "degradado", "restriccion", "fallo", "omitido")
SEVERIDADES = ("bloqueante", "limitante", "informativa")

LIMITE_SALIDA = 4000

# Nada de esto puede quedar escrito en un archivo que despues se comparte o se
# commitea. El orden importa: los patrones mas especificos van primero.
_PATRONES_SECRETO = (
    re.compile(r"\bdapi[0-9a-fA-F]{32,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"),
    re.compile(r"(?i)\b(?:bearer|token)\s+[A-Za-z0-9_\-\.]{12,}"),
    re.compile(
        r'(?i)"(?:access_token|refresh_token|client_secret|password|token)"\s*:\s*"[^"]+"'
    ),
    re.compile(r"(?i)\b(?:DATABRICKS_TOKEN|CLIENT_SECRET)\s*=\s*\S+"),
)

_ETIQUETA_ESTADO = {
    "ok": "ok",
    "degradado": "degradado",
    "restriccion": "restriccion",
    "fallo": "fallo",
    "omitido": "omitido",
}


# --------------------------------------------------------------------------- io


def _ruta_estado(archivo: Path) -> Path:
    return archivo.with_suffix(".json")


def _cargar(archivo: Path) -> dict:
    estado = _ruta_estado(archivo)
    if not estado.exists():
        raise SystemExit(
            f"No hay bitacora en {archivo}. Corre primero "
            f"`bitacora_despliegue.py init --archivo {archivo} --comando <nombre>`."
        )
    return json.loads(estado.read_text(encoding="utf-8"))


def _guardar(archivo: Path, datos: dict) -> None:
    archivo.parent.mkdir(parents=True, exist_ok=True)
    _ruta_estado(archivo).write_text(
        json.dumps(datos, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    archivo.write_text(_render(datos), encoding="utf-8")


def _ahora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------- saneamiento


def sanear(texto: str | None) -> str:
    """Redacta credenciales y recorta salidas desmedidas."""
    if not texto:
        return ""
    limpio = texto
    for patron in _PATRONES_SECRETO:
        limpio = patron.sub("[REDACTADO]", limpio)
    if len(limpio) > LIMITE_SALIDA:
        sobra = len(limpio) - LIMITE_SALIDA
        limpio = limpio[:LIMITE_SALIDA] + f"\n... (salida recortada, {sobra} caracteres mas)"
    return limpio


def _celda(texto: str | None) -> str:
    """Aplana un valor para que quepa en una celda de tabla Markdown."""
    if not texto:
        return "--"
    return texto.replace("|", "\\|").replace("\n", " ").strip() or "--"


# ------------------------------------------------------------------- render


def _estado_final(datos: dict) -> str:
    if not datos.get("cierre"):
        return "EN CURSO"
    estados = [p["estado"] for p in datos["pasos"]]
    # `omitido` pesa igual que `fallo`: los dos dicen que el comando no hizo lo
    # que venia a hacer. Que no haya tropezado con ningun permiso no lo vuelve
    # COMPLETO -- no tropezo porque no llego a intentarlo.
    if "fallo" in estados or "omitido" in estados:
        return "INCOMPLETO"
    if datos["restricciones"] or "restriccion" in estados or "degradado" in estados:
        return "COMPLETO CON RESTRICCIONES"
    return "COMPLETO"


def _render_encabezado(datos: dict) -> list[str]:
    filas = [
        ("Comando", datos.get("comando")),
        ("Cuaderno", datos.get("cuaderno")),
        ("Workspace", datos.get("workspace")),
        ("App", datos.get("app")),
        ("Perfil", datos.get("perfil")),
        ("Destino UC", datos.get("destino")),
        ("Inicio", datos.get("inicio")),
        ("Cierre", datos.get("cierre")),
        ("URL publicada", datos.get("url")),
        ("Estado final", f"**{_estado_final(datos)}**"),
    ]
    lineas = ["# Bitacora de despliegue", "", "| | |", "|---|---|"]
    lineas += [f"| {k} | {_celda(v)} |" for k, v in filas if v]
    return lineas


def _render_resumen(datos: dict) -> list[str]:
    conteo = {e: 0 for e in ESTADOS_PASO}
    for paso in datos["pasos"]:
        conteo[paso["estado"]] += 1
    piezas = [f"{conteo[e]} {e}" for e in ESTADOS_PASO if conteo[e]]
    total = len(datos["pasos"])

    abiertas = [r for r in datos["restricciones"] if not r.get("resuelta")]
    bloqueantes = [r for r in abiertas if r["severidad"] == "bloqueante"]

    lineas = ["", "## Resumen", ""]
    lineas.append(
        f"- **{total} {'paso' if total == 1 else 'pasos'}**: "
        f"{', '.join(piezas) if piezas else 'ninguno registrado'}"
    )
    if abiertas:
        n, b = len(abiertas), len(bloqueantes)
        lineas.append(
            f"- **{n} {'restriccion' if n == 1 else 'restricciones'}** "
            f"({b} {'bloqueante' if b == 1 else 'bloqueantes'})"
        )
    else:
        lineas.append("- **0 restricciones**")
    if bloqueantes:
        lineas.append("")
        lineas.append("Lo que hay que destrabar antes de que esto sirva:")
        for r in bloqueantes:
            quien = r.get("quien_desbloquea") or "sin responsable identificado"
            lineas.append(f"  - `{r['id']}` {r['titulo']} -- lo desbloquea: {quien}")
    return lineas


def _render_restricciones(datos: dict) -> list[str]:
    lineas = ["", "## Restricciones y errores", ""]
    if not datos["restricciones"]:
        lineas.append("Sin restricciones registradas.")
        return lineas

    for r in datos["restricciones"]:
        marca = " -- RESUELTA" if r.get("resuelta") else ""
        lineas.append(f"### {r['id']} -- {r['titulo']}  `{r['severidad']}`{marca}")
        lineas.append("")
        if r.get("paso"):
            lineas.append(f"- **Paso**: {r['paso']}")
        lineas.append(f"- **Impacto**: {r.get('impacto') or '--'}")
        if r.get("evidencia"):
            lineas.append("- **Evidencia**:")
            lineas.append("")
            lineas.append("  ```")
            lineas += [f"  {ln}" for ln in r["evidencia"].split("\n")]
            lineas.append("  ```")
        if r.get("rodeo"):
            lineas.append(f"- **Rodeo aplicado**: {r['rodeo']}")
        else:
            lineas.append("- **Rodeo aplicado**: ninguno, el paso quedo sin cubrir")
        if r.get("quien_desbloquea"):
            lineas.append(f"- **Quien lo desbloquea**: {r['quien_desbloquea']}")
        lineas.append("")
    return lineas


def _render_pasos(datos: dict) -> list[str]:
    lineas = ["", "## Pasos", ""]
    if not datos["pasos"]:
        lineas.append("Todavia no se registro ningun paso.")
        return lineas

    lineas.append("| # | Paso | Estado | Detalle |")
    lineas.append("|---|---|---|---|")
    for p in datos["pasos"]:
        lineas.append(
            f"| {p['id']} | {_celda(p['titulo'])} | `{_ETIQUETA_ESTADO[p['estado']]}` "
            f"| {_celda(p.get('detalle'))} |"
        )

    con_evidencia = [p for p in datos["pasos"] if p.get("comando") or p.get("salida")]
    if con_evidencia:
        lineas += ["", "## Detalle por paso", ""]
        for p in con_evidencia:
            lineas.append(f"### Paso {p['id']} -- {p['titulo']}  `{p['estado']}`")
            lineas.append("")
            if p.get("comando"):
                lineas += ["```", p["comando"], "```", ""]
            if p.get("salida"):
                lineas += ["```", p["salida"], "```", ""]
    return lineas


def _render(datos: dict) -> str:
    lineas: list[str] = []
    lineas += _render_encabezado(datos)
    lineas += _render_resumen(datos)
    lineas += _render_restricciones(datos)
    lineas += _render_pasos(datos)
    if datos.get("nota_cierre"):
        lineas += ["", "## Cierre", "", datos["nota_cierre"]]
    lineas.append("")
    return "\n".join(lineas)


# ---------------------------------------------------------------- subcomandos


def cmd_init(a: argparse.Namespace) -> int:
    if a.archivo:
        archivo = Path(a.archivo)
    else:
        raiz = Path(a.raiz) if a.raiz else Path("reports") / "despliegues"
        sello = datetime.now().strftime("%Y%m%d_%H%M%S")
        nombre = a.comando.lstrip("/").replace("/", "-")
        archivo = raiz / f"{nombre}_{sello}.md"

    datos = {
        "comando": a.comando,
        "cuaderno": a.cuaderno,
        "workspace": a.workspace,
        "app": a.app,
        "perfil": a.perfil,
        "destino": a.destino,
        "inicio": _ahora(),
        "cierre": None,
        "url": None,
        "nota_cierre": None,
        "pasos": [],
        "restricciones": [],
    }
    _guardar(archivo, datos)
    print(archivo)
    return 0


def cmd_paso(a: argparse.Namespace) -> int:
    archivo = Path(a.archivo)
    datos = _cargar(archivo)
    registro = {
        "id": a.id,
        "titulo": a.titulo,
        "estado": a.estado,
        "detalle": a.detalle,
        "comando": a.comando,
        "salida": sanear(a.salida),
        "momento": _ahora(),
    }
    for i, previo in enumerate(datos["pasos"]):
        if previo["id"] == a.id:
            datos["pasos"][i] = registro
            break
    else:
        datos["pasos"].append(registro)
    _guardar(archivo, datos)
    return 0


def cmd_restriccion(a: argparse.Namespace) -> int:
    archivo = Path(a.archivo)
    datos = _cargar(archivo)
    registro = {
        "id": a.id,
        "titulo": a.titulo,
        "severidad": a.severidad,
        "paso": a.paso,
        "impacto": a.impacto,
        "evidencia": sanear(a.evidencia),
        "rodeo": a.rodeo,
        "quien_desbloquea": a.quien_desbloquea,
        "resuelta": a.resuelta,
        "momento": _ahora(),
    }
    for i, previo in enumerate(datos["restricciones"]):
        if previo["id"] == a.id:
            datos["restricciones"][i] = registro
            break
    else:
        datos["restricciones"].append(registro)
    _guardar(archivo, datos)
    return 0


def cmd_cerrar(a: argparse.Namespace) -> int:
    archivo = Path(a.archivo)
    datos = _cargar(archivo)
    datos["cierre"] = _ahora()
    datos["url"] = a.url or datos.get("url")
    datos["nota_cierre"] = a.nota
    _guardar(archivo, datos)
    print(_estado_final(datos))
    return 0


def cmd_resumen(a: argparse.Namespace) -> int:
    datos = _cargar(Path(a.archivo))
    print(f"Estado: {_estado_final(datos)}")
    print("\n".join(_render_resumen(datos)).strip())
    for r in datos["restricciones"]:
        print(f"\n{r['id']} [{r['severidad']}] {r['titulo']}")
        print(f"  impacto: {r.get('impacto') or '--'}")
        if r.get("quien_desbloquea"):
            print(f"  desbloquea: {r['quien_desbloquea']}")
    return 0


# --------------------------------------------------------------------- cli


def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="sub", required=True)

    i = sub.add_parser("init", help="crea la bitacora y devuelve su ruta")
    i.add_argument("--archivo")
    i.add_argument("--raiz", help="carpeta donde derivar el nombre si no se da --archivo")
    i.add_argument("--comando", required=True)
    i.add_argument("--cuaderno")
    i.add_argument("--workspace")
    i.add_argument("--app")
    i.add_argument("--perfil")
    i.add_argument("--destino", help="catalogo.esquema.volumen resuelto")
    i.set_defaults(func=cmd_init)

    s = sub.add_parser("paso", help="registra o actualiza un paso")
    s.add_argument("--archivo", required=True)
    s.add_argument("--id", required=True)
    s.add_argument("--titulo", required=True)
    s.add_argument("--estado", required=True, choices=ESTADOS_PASO)
    s.add_argument("--detalle")
    s.add_argument("--comando")
    s.add_argument("--salida")
    s.set_defaults(func=cmd_paso)

    r = sub.add_parser("restriccion", help="registra o actualiza una restriccion")
    r.add_argument("--archivo", required=True)
    r.add_argument("--id", required=True)
    r.add_argument("--titulo", required=True)
    r.add_argument("--severidad", default="bloqueante", choices=SEVERIDADES)
    r.add_argument("--paso")
    r.add_argument("--impacto")
    r.add_argument("--evidencia")
    r.add_argument("--rodeo")
    r.add_argument("--quien-desbloquea", dest="quien_desbloquea")
    r.add_argument("--resuelta", action="store_true")
    r.set_defaults(func=cmd_restriccion)

    c = sub.add_parser("cerrar", help="cierra la bitacora y calcula el estado final")
    c.add_argument("--archivo", required=True)
    c.add_argument("--url")
    c.add_argument("--nota")
    c.set_defaults(func=cmd_cerrar)

    q = sub.add_parser("resumen", help="imprime el resumen para el reporte al usuario")
    q.add_argument("--archivo", required=True)
    q.set_defaults(func=cmd_resumen)

    return p


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
