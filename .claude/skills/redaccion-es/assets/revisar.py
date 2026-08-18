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
import html
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
# basta con mirar si hay un `?`.
#
# TODO lo que sale de aqui es DUDOSO por construccion y va a su propia clase: el `que`
# atono es la palabra mas comun del idioma y ninguna heuristica sin analisis sintactico
# distingue "no se QUE pasa" de "la pregunta QUE se repite". La clase `tilde-dudosa` se
# reporta para que la mire una persona; un corrector automatico NO la aplica.
# Verbos de saber/decir en forma conjugada o infinitiva. SIN `\w*` al final y sin
# `pregunta`/`muestra`/`ver`: los tres son tambien sustantivos o comodines, y "la pregunta
# que se repite" disparaba con ellos -- que es exactamente el falso positivo que hay que
# evitar aqui, porque acentuar un `que` relativo cambia lo que la frase dice.
_ANTES_INDIRECTA = re.compile(
    r"\b(?<!la\s)(?<!una\s)(sabe|sabemos|saber|sabia|dice|decir|explica|explicar|"
    r"indica|indicar|averiguar|preguntar|preguntarse|define|definir|depende)\s+(?:de\s+)?$",
    re.I)

# El diccionario vive en `src/chec_local_interpreter/ortografia.py`, no aqui. Se importa en
# vez de copiarse porque la copia FUE el fallo: esta lista tenia 153 palabras y ninguna de
# las seis del dominio que de verdad salieron mal en un informe del grupo Riesgo Alto --
# `vegetacion`, `hipotesis`, `proteccion`, `atribucion`, `asociacion`, `topologico` --, asi
# que el verificador no podia verlas por mucho que se corriera. Ahora la guarda de los
# validadores de los tres agentes y este verificador miran exactamente la misma lista.
_RAIZ = Path(__file__).resolve().parents[4]
if str(_RAIZ / "src") not in sys.path:
    sys.path.insert(0, str(_RAIZ / "src"))
from chec_local_interpreter.ortografia import SIEMPRE_CON_TILDE as _SIEMPRE_CON_TILDE
from chec_local_interpreter.ortografia import TONICOS as _TONICOS
from chec_local_interpreter.ortografia import es_codigo as _es_codigo

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
    # Desplazamiento DENTRO del fragmento analizado, o -1 si el hallazgo no es de una
    # posicion concreta. Sin esto, un corrector solo tiene la palabra, y `que` aparece
    # siete veces en un parrafo donde solo UNA la necesita: parchearlas todas cambia lo
    # que el texto dice. Es exactamente el fallo que costo revertir un cuaderno entero.
    columna: int = -1


#: Clases que un corrector automatico puede aplicar sin leer la frase. El resto se
#: reporta y lo decide una persona.
AUTOMATICAS = frozenset({"tilde"})


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


def _con_la_caja_de(original: str, correcta: str) -> str:
    """La palabra acentuada, en la MISMA caja que traia.

    Tres casos y no dos. `.capitalize()` sobre una palabra en mayusculas la destruye --
    `GEOMETRIA` acababa en `Geometria` --, y en este repositorio las mayusculas dentro de
    una frase son enfasis deliberado del autor, no un descuido que haya que normalizar.
    Y las mayusculas TAMBIEN se acentuan: `GEOMETRÍA`, no `GEOMETRIA`.
    """
    if original.isupper():
        return correcta.upper()
    if original[:1].isupper():
        return correcta[:1].upper() + correcta[1:]
    return correcta


def _tildes(texto: str, archivo: str, linea: int) -> list[Hallazgo]:
    fuera = []
    for m in re.finditer(r"\b[a-záéíóúñü]+\b", texto, re.I):
        palabra, baja = m.group(0), m.group(0).lower()
        # Un CODIGO de columna no lleva tilde y no se toca: `DURACION`, `TOT_USUS`,
        # `PROMEDIO_KWH_TRF`. El verificador proponia `DURACIÓN`, y aplicarlo rompe el
        # codigo que lee esa columna. La regla es mecanica -- mayusculas sostenidas, o un
        # `_`/digito pegado -- para no tener que mantener una lista de excepciones.
        entorno = texto[max(0, m.start() - 1):min(len(texto), m.end() + 1)]
        if _es_codigo(palabra, entorno):
            continue
        if palabra != _sin_tildes(palabra):
            continue  # ya lleva tilde
        if baja in _SIEMPRE_CON_TILDE:
            correcta = _SIEMPRE_CON_TILDE[baja]
            if correcta is None:
                continue  # las dos formas existen: no es decidible aqui
            fuera.append(Hallazgo(archivo, linea, "tilde", palabra,
                                  _con_la_caja_de(palabra, correcta), m.start()))
        elif baja in _TONICOS:
            # La frase, no el bloque. Con el bloque entero, un `¿...?` en el primer
            # renglon marcaba todos los `que` de los veinte siguientes.
            ini = max((texto.rfind(c, 0, m.start()) for c in ".;\n¿"), default=-1)
            fin = min((p for p in (texto.find(c, m.end()) for c in ".;\n?") if p >= 0),
                      default=len(texto))
            frase_antes, frase_despues = texto[max(ini, 0):m.start()], texto[m.end():fin + 1]
            interroga = "¿" in texto[max(ini, 0):m.start()] and "?" in frase_despues
            indirecta = bool(_ANTES_INDIRECTA.search(frase_antes))
            if interroga or indirecta:
                fuera.append(Hallazgo(archivo, linea, "tilde-dudosa", palabra,
                                      _TONICOS[baja], m.start()))
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
                     "caso oracion: solo la primera palabra y los nombres propios",
                     seguidas.start())]


def _listas(texto: str, archivo: str, linea: int) -> list[Hallazgo]:
    fuera, plano = [], _sin_tildes(texto.lower())
    for frase, mejor in _MULETILLAS.items():
        if frase in plano:
            fuera.append(Hallazgo(archivo, linea, "verboseo", frase, mejor or "(sobra)",
                                  plano.index(frase)))
    for frase in _REDUNDANCIAS:
        if frase in plano:
            fuera.append(Hallazgo(archivo, linea, "redundancia", frase, "(sobra la mitad)",
                                  plano.index(frase)))
    for frase in _DIALECTO:
        if frase in plano:
            fuera.append(Hallazgo(archivo, linea, "dialecto", frase, "termino neutro",
                                  plano.index(frase)))
    for m in re.finditer(r"\b\w+\b", plano):
        if m.group(0) in _ANGLICISMOS:
            fuera.append(Hallazgo(archivo, linea, "dialecto", m.group(0),
                                  _ANGLICISMOS[m.group(0)], m.start()))
    return fuera


def _es_espaniol(texto: str) -> bool:
    """Filtro barato: sin esto, cada identificador ingles del repositorio seria un hallazgo.

    Se pide una palabra funcional espaniola, que es lo que distingue una frase de una
    lista de nombres tecnicos.
    """
    # `en` faltaba, y es de las preposiciones mas comunes del castellano: una frase cuya
    # unica palabra funcion fuera esa -- "Requiere validacion en campo" -- se saltaba
    # ENTERA, sin revisar. Con ella entran las demas del mismo grupo, por la misma razon.
    return bool(re.search(
        r"\b(el|la|los|las|un|una|de|del|que|con|por|para|sin|sobre|como|es|son|"
        r"se|su|sus|no|y|o|al|lo|le|este|esta|cada|mas|pero|si|"
        r"en|entre|desde|hasta|ante|tras|durante|contra|hacia)\b",
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


def _fragmentos_json(fuente: str):
    """Las cadenas que son VALOR dentro de un `*.out.json` de agente.

    Las CLAVES se saltan: una clave es una interfaz, y ponerle una tilde rompe a quien la
    lee. Un JSON ilegible no es un defecto de redaccion: se devuelve vacio, no se revienta.
    """
    try:
        datos = json.loads(fuente)
    except (json.JSONDecodeError, ValueError):
        return
    pila = [datos]
    while pila:
        actual = pila.pop()
        if isinstance(actual, str):
            yield actual, 1
        elif isinstance(actual, dict):
            pila.extend(actual.values())
        elif isinstance(actual, list):
            pila.extend(actual)


#: `<script>` y `<style>` son CODIGO dentro del HTML: una variable llamada `proteccion` ahi
#: no es un defecto de redaccion. Se recortan enteros antes de mirar nada.
_CODIGO_EN_HTML = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)
_ETIQUETA = re.compile(r"<[^>]+>")


def _fragmentos_html(fuente: str):
    """El texto VISIBLE de un informe renderizado, renglon a renglon."""
    cuerpo = _CODIGO_EN_HTML.sub(" ", fuente)
    for i, renglon in enumerate(_ETIQUETA.sub(" ", cuerpo).splitlines(), 1):
        texto = html.unescape(renglon).strip()
        if texto:
            yield texto, i


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
    elif ruta.suffix == ".json":
        pares = _fragmentos_json(fuente)
    elif ruta.suffix in (".html", ".htm"):
        pares = _fragmentos_html(fuente)
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
            for suf in ("*.py", "*.md", "*.ipynb", "*.json", "*.html"):
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
