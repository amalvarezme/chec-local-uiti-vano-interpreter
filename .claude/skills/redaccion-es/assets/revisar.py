#!/usr/bin/env python3
"""Verificador determinista de redaccion en espanol.

Decide lo MECANICO -- signos sin pareja, tildes que no dependen del sentido, caso titulo,
muletillas y redundancias de lista cerrada -- para que la revision no gaste juicio en lo
que una regla resuelve. Todo lo que depende del contexto se queda fuera a proposito: este
programa no adivina si `mas` es `mas` o `mas`, porque las dos formas existen.

Uso:
    python3 revisar.py <ruta> [<ruta> ...]
    python3 revisar.py --json <ruta>

Lee `.py`, `.md` y `.ipynb`. De los `.py` mira comentarios, docstrings y cadenas de una
sola linea; de los `.ipynb`, las celdas markdown y el codigo de las de codigo.
"""
from __future__ import annotations

import ast
import io
import json
import re
import sys
import tokenize
import unicodedata
from dataclasses import dataclass, asdict
from pathlib import Path

# --------------------------------------------------------------------------- reglas

# Interrogativos y exclamativos. Llevan tilde tambien en pregunta indirecta, asi que no
# basta con mirar si hay un `?`: se busca la palabra atona en contextos donde solo cabe la
# tonica. Se exige una marca de pregunta o un verbo de saber/decir delante para no marcar
# el `que` conjuncion, que es el caso comun y NO lleva tilde.
_TONICOS = {"que": "qué", "cual": "cuál", "cuales": "cuáles", "como": "cómo",
            "cuando": "cuándo", "donde": "dónde", "cuanto": "cuánto",
            "cuantos": "cuántos", "cuanta": "cuánta", "cuantas": "cuántas",
            "quien": "quién", "quienes": "quiénes"}
_ANTES_INDIRECTA = re.compile(
    r"\b(sabe|saber|dice|decir|explica|explicar|indica|indicar|muestra|mostrar|"
    r"pregunta|preguntar|ver|mira|mirar|define|definir|depende)\w*\s+(?:de\s+)?$",
    re.I)

# Palabras cuya forma sin tilde NO existe en espanol: aqui no hay ambiguidad posible.
_SIEMPRE_CON_TILDE = {
    "ademas": "además", "asi": "así", "aqui": "aquí", "alli": "allí", "ahi": "ahí",
    "aun": None,  # `aun` y `aún` existen las dos: se reporta, no se corrige
    "analisis": "análisis", "aplicacion": "aplicación", "atencion": "atención",
    "caida": "caída", "calculo": None,  # `calculo` (yo calculo) y `cálculo` existen
    "categoria": "categoría", "codigo": "código", "condicion": "condición",
    "criterio": None, "dia": "día", "dias": "días", "diagnostico": None,
    "direccion": "dirección", "energia": "energía", "esta": None,
    "estadistica": "estadística", "geografia": "geografía", "grafico": "gráfico",
    "graficos": "gráficos", "informacion": "información", "interpretacion": "interpretación",
    "linea": "línea", "lineas": "líneas", "maximo": "máximo", "maxima": "máxima",
    "maximos": "máximos", "maximas": "máximas", "metodo": "método", "minimo": "mínimo",
    "minima": "mínima", "minimos": "mínimos", "minimas": "mínimas", "medicion": "medición",
    "numero": "número", "numeros": "números", "opcion": "opción", "parametro": "parámetro",
    "parametros": "parámetros", "periodo": None,  # `periodo` y `período` valen las dos
    "prediccion": "predicción", "proximo": "próximo", "rapido": "rápido",
    "razon": "razón", "region": "región", "seleccion": "selección", "simulacion": "simulación",
    "tambien": "también", "tecnico": "técnico", "tecnica": "técnica", "ultimo": "último",
    "ultima": "última", "ultimos": "últimos", "ultimas": "últimas", "unico": "único",
    "unica": "única", "version": "versión", "visualizacion": "visualización",
    "estan": "están", "estara": "estará", "sera": "será", "seran": "serán",
    "habra": "habrá", "podra": "podrá", "deberia": "debería", "podria": "podría",
    "fisica": "física", "fisico": "físico", "electrico": "eléctrico",
    "electrica": "eléctrica", "automatico": "automático", "automatica": "automática",
}

_MULETILLAS = {
    "de manera que": "para", "con el fin de": "para", "con el objetivo de": "para",
    "en el caso de que": "si", "a fin de": "para", "llevar a cabo": "hacer",
    "realizar una comprobacion": "comprobar", "hacer el calculo de": "calcular",
    "en relacion con el hecho de": "sobre", "es importante destacar que": "",
    "cabe mencionar que": "", "por lo que respecta a": "sobre",
    "de acuerdo a": "de acuerdo con", "en base a": "con base en",
}

_REDUNDANCIAS = ["subir arriba", "bajar abajo", "entrar adentro", "salir afuera",
                 "crear un nuevo", "crear una nueva", "planificar de antemano",
                 "accidente fortuito", "prever con antelacion", "repetir de nuevo",
                 "volver a repetir", "insertar dentro"]

_DIALECTO = ["chevere", "ahorita", "platica", "vos sos", "que tal si vos",
             "recien llegado a", "guay", "vale la pena que te", "porfa"]

# Anglicismos con termino asentado. Los que son nombre propio de una tecnologia se quedan.
_ANGLICISMOS = {"deployar": "desplegar", "deploy": "despliegue", "performance": "rendimiento",
                "chart": "grafico", "feature": "variable", "features": "variables",
                "setear": "fijar", "linkear": "enlazar", "printear": "imprimir",
                "customizar": "personalizar", "randomico": "aleatorio"}


@dataclass
class Hallazgo:
    archivo: str
    linea: int
    clase: str
    fragmento: str
    sugerencia: str


def _sin_tildes(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")


def _signos(texto: str, archivo: str, linea: int) -> list[Hallazgo]:
    """Apertura y cierre de `¿ ?` y `¡ !`, contados por pares dentro del fragmento."""
    fuera = []
    for abre, cierra, nombre in (("¿", "?", "interrogacion"), ("¡", "!", "exclamacion")):
        n_abre, n_cierra = texto.count(abre), texto.count(cierra)
        if n_abre > n_cierra:
            fuera.append(Hallazgo(archivo, linea, "signos", texto.strip()[:90],
                                  f"sobra un `{abre}` sin su `{cierra}`"))
        elif n_cierra > n_abre:
            # Un `?` suelto en prosa espaniola casi siempre es una pregunta sin abrir. En
            # una expresion regular o una URL no lo es, asi que se exige que la frase
            # tenga aspecto de prosa: al menos tres palabras antes del cierre.
            antes = texto[:texto.index(cierra)] if cierra in texto else ""
            if len(antes.split()) >= 3 and not re.search(r"[\\\[\]{}()|*+]", antes[-12:]):
                fuera.append(Hallazgo(archivo, linea, "signos", texto.strip()[:90],
                                      f"falta el `{abre}` que abre la {nombre}"))
    return fuera


def _tildes(texto: str, archivo: str, linea: int) -> list[Hallazgo]:
    fuera = []
    for m in re.finditer(r"\b[a-záéíóúñü]+\b", texto, re.I):
        palabra, baja = m.group(0), m.group(0).lower()
        if palabra != _sin_tildes(palabra):
            continue  # ya lleva tilde
        if baja in _SIEMPRE_CON_TILDE:
            correcta = _SIEMPRE_CON_TILDE[baja]
            if correcta is None:
                continue  # las dos formas existen: no es decidible aqui
            fuera.append(Hallazgo(archivo, linea, "tilde", palabra,
                                  correcta if palabra.islower() else correcta.capitalize()))
        elif baja in _TONICOS:
            antes, despues = texto[:m.start()], texto[m.end():]
            interroga = "¿" in antes and "?" in despues
            indirecta = bool(_ANTES_INDIRECTA.search(antes))
            if interroga or indirecta:
                fuera.append(Hallazgo(archivo, linea, "tilde", palabra, _TONICOS[baja]))
    return fuera


# Una palabra capitalizada de verdad (lleva minusculas), y una sigla, que se ATRAVIESA sin
# contar. En este dominio casi cualquier titulo lleva una -- UITI, MIL, CHEC, EPM, SHAP --,
# y si la sigla cortara la racha el detector se apagaria justo donde mas falta hace.
_CAPITAL = r"[A-ZÁÉÍÓÚÑ][a-záéíóúñü]+"
_SIGLA = r"(?:[A-ZÁÉÍÓÚÑ0-9]{2,}\s+)*"
_CASO_TITULO = re.compile(rf"\b{_CAPITAL}(?:\s+{_SIGLA}{_CAPITAL}){{2,}}")


def _mayusculas(texto: str, archivo: str, linea: int) -> list[Hallazgo]:
    """Caso titulo a la inglesa: TRES palabras capitalizadas seguidas.

    Cada una tiene que llevar alguna minuscula, y eso es lo que sostiene la regla: la
    racha se corta en cuanto aparece un conector en minuscula, que es como se escribe de
    verdad en espaniol -- `Nube por vano`, `Central Hidroelectrica de Caldas`.

    Con DOS palabras habria falsos positivos por todas partes: cualquier frase que empiece
    con un nombre propio. Con tres, el patron ya es intencional.
    """
    seguidas = _CASO_TITULO.search(texto)
    if not seguidas:
        return []
    return [Hallazgo(archivo, linea, "mayusculas", seguidas.group(0).strip(),
                     "caso oracion: solo la primera palabra y los nombres propios")]


def _listas(texto: str, archivo: str, linea: int) -> list[Hallazgo]:
    fuera, plano = [], _sin_tildes(texto.lower())
    for frase, mejor in _MULETILLAS.items():
        if frase in plano:
            fuera.append(Hallazgo(archivo, linea, "verboseo", frase, mejor or "(sobra)"))
    for frase in _REDUNDANCIAS:
        if frase in plano:
            fuera.append(Hallazgo(archivo, linea, "redundancia", frase, "(sobra la mitad)"))
    for frase in _DIALECTO:
        if frase in plano:
            fuera.append(Hallazgo(archivo, linea, "dialecto", frase, "termino neutro"))
    for m in re.finditer(r"\b\w+\b", plano):
        if m.group(0) in _ANGLICISMOS:
            fuera.append(Hallazgo(archivo, linea, "dialecto", m.group(0),
                                  _ANGLICISMOS[m.group(0)]))
    return fuera


def _es_espaniol(texto: str) -> bool:
    """Filtro barato: sin esto, cada identificador ingles del repositorio seria un hallazgo.

    Se pide una palabra funcional espaniola, que es lo que distingue una frase de una
    lista de nombres tecnicos.
    """
    return bool(re.search(
        r"\b(el|la|los|las|un|una|de|del|que|con|por|para|sin|sobre|como|es|son|"
        r"se|su|sus|no|y|o|al|lo|le|este|esta|cada|mas|pero|si)\b",
        texto, re.I))


def revisar_texto(texto: str, archivo: str, linea: int) -> list[Hallazgo]:
    if not _es_espaniol(texto):
        return []
    return (_signos(texto, archivo, linea) + _tildes(texto, archivo, linea)
            + _mayusculas(texto, archivo, linea) + _listas(texto, archivo, linea))


# ------------------------------------------------------------------------ extraccion


def _fragmentos_py(fuente: str, archivo: str):
    """Comentarios, docstrings y cadenas literales, cada uno con su linea real."""
    try:
        for tok in tokenize.generate_tokens(io.StringIO(fuente).readline):
            if tok.type == tokenize.COMMENT:
                yield tok.string.lstrip("# ").rstrip(), tok.start[0]
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    try:
        arbol = ast.parse(fuente)
    except SyntaxError:
        return
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str):
            for i, renglon in enumerate(nodo.value.splitlines()):
                if renglon.strip():
                    yield renglon, (nodo.lineno or 0) + i


def _fragmentos_ipynb(fuente: str, archivo: str):
    try:
        cuaderno = json.loads(fuente)
    except json.JSONDecodeError:
        return
    for n, celda in enumerate(cuaderno.get("cells", []), 1):
        origen = celda.get("source", [])
        texto = "".join(origen) if isinstance(origen, list) else origen
        if celda.get("cell_type") == "markdown":
            for i, renglon in enumerate(texto.splitlines(), 1):
                if renglon.strip():
                    yield renglon, n * 1000 + i   # celda*1000 + renglon
        elif celda.get("cell_type") == "code":
            for renglon, i in _fragmentos_py(texto, archivo):
                yield renglon, n * 1000 + i


def revisar_archivo(ruta: Path) -> list[Hallazgo]:
    try:
        fuente = ruta.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    if ruta.suffix == ".ipynb":
        pares = _fragmentos_ipynb(fuente, str(ruta))
    elif ruta.suffix == ".py":
        pares = _fragmentos_py(fuente, str(ruta))
    elif ruta.suffix in (".md", ".txt"):
        pares = ((r, i) for i, r in enumerate(fuente.splitlines(), 1) if r.strip())
    else:
        return []
    fuera = []
    for texto, linea in pares:
        fuera.extend(revisar_texto(texto, str(ruta), linea))
    return fuera


def _recorrer(rutas: list[str]):
    for bruta in rutas:
        p = Path(bruta)
        if p.is_dir():
            for suf in ("*.py", "*.md", "*.ipynb"):
                for hijo in sorted(p.rglob(suf)):
                    if any(x in hijo.parts for x in (".venv", "node_modules", ".git",
                                                     "__pycache__", "graphify-out")):
                        continue
                    yield hijo
        elif p.is_file():
            yield p


def main(argv: list[str]) -> int:
    como_json = "--json" in argv
    rutas = [a for a in argv[1:] if not a.startswith("--")]
    if not rutas:
        print(__doc__)
        return 2
    todos: list[Hallazgo] = []
    for archivo in _recorrer(rutas):
        todos.extend(revisar_archivo(archivo))
    if como_json:
        print(json.dumps([asdict(h) for h in todos], ensure_ascii=False, indent=2))
        return 0
    if not todos:
        print("sin hallazgos mecanicos")
        return 0
    por_clase: dict[str, list[Hallazgo]] = {}
    for h in todos:
        por_clase.setdefault(h.clase, []).append(h)
    for clase in sorted(por_clase):
        print(f"\n== {clase} ({len(por_clase[clase])}) ==")
        for h in por_clase[clase]:
            print(f"  {h.archivo}:{h.linea}  {h.fragmento!r} -> {h.sugerencia}")
    print(f"\ntotal: {len(todos)} hallazgos mecanicos en "
          f"{len({h.archivo for h in todos})} archivos")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
