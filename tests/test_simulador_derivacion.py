"""El arranque caro del simulador: que produce, y que no puede cambiar en silencio.

## De donde viene el "sin cambiar un byte"

`aplicaciones/06_simulador/preparar.py` construia el paquete **ejecutando las siete
primeras celdas del cuaderno 06** con `exec()`. Ese diseno tenia una virtud real -- no
duplicaba la derivacion -- y un costo: el constructor dependia de los INDICES de celda
de un `.ipynb`, y nadie podia importar esa derivacion desde ningun otro sitio ni
probarla por separado.

`chec_tableros.simulador.derivacion` se la llevo a un modulo. La pregunta que decidia
si el movimiento fue correcto no era si el paquete "se ve bien": era si salia
**identico byte a byte**. Salio, y esa pregunta esta cerrada.

## Por que la comparacion de bytes se queda

Porque contesta otra que no caduca. Un dtype, un orden de columnas o un redondeo de
coordenada se propagan al tablero **sin dar ningun error**: el simulador puntua otra
cosa y todo se ve perfectamente bien. Lo demas de este fichero mira FORMA -- que el
campo exista, que sea `float32`, que las features empiecen donde deben --, y un cambio
de valores pasa por ahi sin tocar nada.

Los cuatro sha256 viven ahora en `HUELLAS_DERIVADAS`, unas lineas mas abajo, con lo que
significa cambiarlos. Estuvieron en `tests/golden/tableros_pre_migracion/huellas.json`,
que se retiro al terminar la migracion: su otra mitad pinaba la APARIENCIA de los cuatro
tableros HTML, que se sigue trabajando, y una prueba que falla en cada cambio legitimo
ensena a recapturarla sin mirar.

## Por que se saltan sin datos

`derivar()` abre el CSV de 566 MB, tres shapefiles y el cache de bolsas de 199 MB.
Sin ellos se salta, que es informacion honesta; fingir que paso no lo es.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
CSV = RAIZ / "data" / "Indicadores_vano_v3.csv"
BOLSAS = RAIZ / "data" / "derived" / "bolsas_mil_full.joblib"
MODELO = RAIZ / "data" / "models" / "mil_vano_ventana_v1.pt"

requiere_datos = pytest.mark.skipif(
    not (CSV.exists() and BOLSAS.exists() and MODELO.exists()),
    reason="requiere el CSV, el cache de bolsas y el modelo entrenado",
)

# Los cuatro archivos que `congelar` ESCRIBE, con el sha256 que produjeron. Los otros
# cuatro del paquete son `shutil.copy2` de archivos versionados: sus huellas son las de
# esos archivos y no dicen nada sobre este modulo.
#
# ## Por que estos numeros viven aqui y no en un golden aparte
#
# Estuvieron en `tests/golden/tableros_pre_migracion/huellas.json`, congelado antes de
# que existiera `derivacion.py` para comprobar que sacarlo del cuaderno no movia un
# byte. Ese golden se retiro con la migracion terminada -- su otra mitad, las huellas
# de los cuatro tableros HTML, pinaba una apariencia que se sigue trabajando, y una
# prueba que falla en cada cambio legitimo ensena a recapturarla sin mirar.
#
# Estas cuatro no se fueron con el, porque no eran una prueba de la migracion: son la
# UNICA cosa que atrapa que la derivacion cambie en silencio lo que el simulador
# puntua. Todo lo demas de este fichero mira forma -- que el campo exista, que el dtype
# sea `float32`, que las features empiecen donde deben --, y un cambio de valores pasa
# por ahi sin tocar nada.
#
# Escritas aqui y no en un JSON a proposito: cambiarlas es editar esta prueba, y eso
# aparece en el diff con su motivo al lado. Un archivo de golden se vuelve a capturar
# con un comando, que es justo lo que no debe ser barato.
#
# **Si una de estas cambia**, la pregunta no es "actualizo el numero" sino "que valor
# se movio y por que": un dtype, un orden de columnas o un redondeo de coordenada se
# propaga al tablero sin dar ningun error. Medidas el 2026-08-15 sobre
# `Indicadores_vano_v3.csv` y `bolsas_mil_full.joblib` de esa fecha.
HUELLAS_DERIVADAS = {
    "tabla.parquet": "7788c466939479f43103277e04d3c0d21ea581a2553289f4ff84fe993f1915db",
    "X_inst.npy": "48012f3508062dc228088e8042319449e68701c692c693d448441b0a7f1c4eb5",
    "geo.json": "263eef51860baaa6e1de803c49f0a4d65703fb3b5c9a2b1d040f68be28d69049",
    "catalogo.joblib": "64f09eb75157da856ed1401978210967da52ed07d44ca6acc5ece486b763bd6a",
}
DERIVADOS = tuple(HUELLAS_DERIVADAS)


def test_el_modulo_expone_derivar_y_congelar():
    """Guarda barata: corre sin datos y falla con un mensaje claro si el modulo
    no existe todavia o si se le cambia la firma."""
    from chec_tableros.simulador import derivacion

    assert callable(derivacion.derivar)
    assert callable(derivacion.congelar)


@requiere_datos
def test_la_derivacion_produce_exactamente_los_mismos_bytes(tmp_path):
    """Lo unico que atrapa que el simulador empiece a puntuar otra cosa.

    Nacio comprobando que sacar la derivacion del cuaderno no movia un byte, y esa
    pregunta ya esta contestada. Sigue aqui porque contesta otra que no caduca: que
    nadie cambie en silencio los valores que el modelo lee.

    Se comparan solo los cuatro archivos que la derivacion PRODUCE. Los otros cuatro
    del paquete son `shutil.copy2` de archivos versionados: incluirlos inflaria la
    prueba sin anadir una sola garantia sobre este modulo.
    """
    from chec_tableros.simulador import derivacion

    derivacion.congelar(derivacion.derivar(), tmp_path)

    obtenido = {
        nombre: hashlib.sha256((tmp_path / nombre).read_bytes()).hexdigest()
        for nombre in DERIVADOS
    }
    distintos = [n for n in DERIVADOS if obtenido[n] != HUELLAS_DERIVADAS[n]]
    assert not distintos, (
        f"{distintos} ya no reproducen sus bytes. Algo cambio de dtype, de orden o de "
        "redondeo, y eso se propaga al tablero sin dar ningun error. Antes de tocar "
        "`HUELLAS_DERIVADAS`, averigua QUE valor se movio."
    )


@requiere_datos
def test_derivado_trae_los_nombres_que_el_cuaderno_puentea_al_tablero(tmp_path):
    """Las celdas 8-16 del cuaderno leen 22 nombres de las celdas 3-7.

    De esos, los que produce el arranque CARO son estos. Si `Derivado` deja de
    traer uno, el cuaderno servido se queda sin el y el fallo aparece a mitad del
    tablero, lejos de aqui.
    """
    from chec_tableros.simulador import derivacion

    d = derivacion.derivar()
    for campo in ("tabla", "ventanas", "x_inst", "features_mil", "bag_index",
                  "geo_por_circuito", "trafos", "switches", "knobs",
                  "feature_names", "label_encoders", "max_values_imputed"):
        assert getattr(d, campo) is not None, campo

    assert len(d.tabla) > 100_000, f"la tabla trae {len(d.tabla)} celdas"
    assert d.x_inst.dtype.name == "float32", (
        "el artefacto guarda float64; convertirlo aqui es lo que baja X_inst.npy "
        "de 184,7 a 92,4 MB, y esta medido que no mueve ni un bit del resultado"
    )
    assert list(d.features_mil[:len(d.feature_names)]) == list(d.feature_names), (
        "las features del MIL ya no empiezan por las de MGCECDL: el catalogo de "
        "knobs apuntaria a columnas equivocadas"
    )


# --------------------------------------------------- el puente derivacion -> tablero

PAQUETE = RAIZ / "aplicaciones" / "06_simulador" / "paquete"

# Aqui vivian dos pruebas del "puente": los 23 nombres que las celdas 8-16 leian del
# espacio de nombres que dejaban las celdas 0-7. Se comprobaban ejecutando las celdas
# de arranque en un subproceso y mirando que ninguno faltara.
#
# Ese puente ya no es un espacio de nombres compartido: es la firma
# `tablero.construir(derivado, ...)`, y `Derivado` es un dataclass, asi que un campo
# que falte falla al construirlo y no diez pantallas mas abajo. Lo que aquellas dos
# pruebas querian saber -- "¿el tablero encuentra todo lo que el arranque le deja?" --
# se contesta mejor haciendolo: se arma el tablero de verdad contra el paquete.

_GUION_TABLERO = """
import json, os, sys
sys.path.insert(0, {src!r})
os.environ['RUTA_VARIABLES_SIMULAR'] = {simular!r}
from chec_tableros.simulador import derivacion, tablero
D = derivacion.cargar({paquete!r})


def hojas(w):
    yield w
    for h in getattr(w, 'children', ()):
        yield from hojas(h)


APP = tablero.construir(D, costos={costos!r})
figuras = [w for w in hojas(APP) if hasattr(w, 'data') and hasattr(w, 'layout')]
# La GRANDE es la de mas trazas. Desde que el grafo tiene la suya -- cuatro trazas, debajo
# del panel de control -- tomar `figuras[0]` a ciegas puede caer en la que no es: el orden
# depende de por donde pase el recorrido de widgets, no de cual es cual.
figuras.sort(key=lambda f: len(f.data), reverse=True)
print('RESULTADO ' + json.dumps({{
    'widgets': sum(1 for _ in hojas(APP)),
    'figuras': len(figuras),
    'trazas': len(figuras[0].data) if figuras else 0,
    # Los titulos de TODAS las figuras, y tambien el `layout.title` de cada una: el del
    # grafo no es una anotacion de subplot sino el titulo de su propia figura.
    'titulos': ([a.text for f in figuras for a in f.layout.annotations if a.text]
                + [f.layout.title.text for f in figuras if f.layout.title.text])[:14],
}}))
"""



# Los botones de grupo, PULSADOS. Un `on_click` de ipywidgets corre en el proceso, sin
# kernel y sin navegador, asi que esto se puede afirmar de verdad en vez de pincharlo
# leyendo el fuente. Y hace falta: que un boton SUME en vez de reemplazar no se ve en el
# codigo de un vistazo -- las dos versiones son una sola linea -- y falla en silencio,
# porque una seleccion reemplazada es una seleccion perfectamente plausible.
#
# Se busca un circuito con los CUATRO grupos poblados en su ventana inicial: sin el, la
# prueba de la suma no distingue "sumo" de "reemplazo por algo que ya estaba".
_GUION_BOTONES = """
import json, os, sys
sys.path.insert(0, {src!r})
os.environ['RUTA_VARIABLES_SIMULAR'] = {simular!r}
from chec_tableros.simulador import derivacion, tablero
D = derivacion.cargar({paquete!r})


def hojas(w):
    yield w
    for h in getattr(w, 'children', ()):
        yield from hojas(h)


APP = tablero.construir(D, costos={costos!r})
BOTON = {{w.description: w for w in hojas(APP) if type(w).__name__ == 'Button'}}
SEL = [w for w in hojas(APP) if hasattr(w, 'desmarcar_todos')][0]
CIRCUITO = [w for w in hojas(APP) if type(w).__name__ == 'Dropdown'][0]
HTMLS = [w for w in hojas(APP) if type(w).__name__ == 'HTML']
GRUPOS = ['G. Alto', 'G. Medio-Alto', 'G. Medio', 'G. Bajo']


def aviso():
    for w in HTMLS:
        if 'en la ventana' in (w.value or '') and 'grupo' in (w.value or ''):
            return w.value
    return ''


def solo(etiqueta):
    \"\"\"Cuantos marca ESE boton, partiendo de cero. Medirlo sin desmarcar antes lee la
    seleccion anterior cuando el grupo esta vacio y el boton no toca nada.\"\"\"
    BOTON['Desmarcar'].click()
    BOTON[etiqueta].click()
    return len(SEL.value)


elegido, cuentas = None, {{}}
for c in list(CIRCUITO.options)[:20]:
    CIRCUITO.value = c
    cuentas = {{g: solo(g) for g in GRUPOS}}
    if all(cuentas.values()):
        elegido = c
        break

resultado = {{'circuito': elegido, 'cuentas': cuentas}}
if elegido is not None:
    # La SUMA: los cuatro grupos, uno tras otro, sin desmarcar en el medio.
    BOTON['Desmarcar'].click()
    acumulado = []
    for g in GRUPOS:
        BOTON[g].click()
        acumulado.append(len(SEL.value))
    resultado['acumulado'] = acumulado
    resultado['aviso_lleno'] = aviso()
    # Que ningun grupo pise a otro: la union de los cuatro es la seleccion final.
    resultado['sin_duplicados'] = len(set(SEL.value)) == len(SEL.value)
    # Desmarcar sigue siendo el unico que quita.
    BOTON['Desmarcar'].click()
    resultado['tras_desmarcar'] = len(SEL.value)
    # Y una marca MANUAL sobrevive al boton de grupo.
    fid_ajeno = next(f for f in SEL.casillas if f not in SEL.value)
    SEL.alternar(fid_ajeno)
    antes = set(SEL.value)
    BOTON['G. Alto'].click()
    resultado['manual_sobrevive'] = antes <= set(SEL.value)

print('RESULTADO ' + json.dumps(resultado))
"""


# La serie de tiempo dibuja UNA traza por vano, y las trazas de un `FigureWidget` se fijan
# al construirlo: crecerlas en vivo es el camino por el que el tablero se queda en blanco.
# El pozo tenia treinta ranuras, de cuando la seleccion la ponia una auto-marca de quince;
# con los botones de grupo un circuito marca cientos, y lo que sobraba del tope se dibujaba
# como si no existiera. Esto lo mide PULSANDO: cuantos vanos quedan marcados y cuantos
# aparecen de verdad en el panel.
_GUION_SERIES = """
import json, os, sys
sys.path.insert(0, {src!r})
os.environ['RUTA_VARIABLES_SIMULAR'] = {simular!r}
from chec_tableros.simulador import derivacion, tablero
D = derivacion.cargar({paquete!r})


def hojas(w):
    yield w
    for h in getattr(w, 'children', ()):
        yield from hojas(h)


APP = tablero.construir(D, costos={costos!r})
BOTON = {{w.description: w for w in hojas(APP) if type(w).__name__ == 'Button'}}
SEL = [w for w in hojas(APP) if hasattr(w, 'desmarcar_todos')][0]
CIRCUITO = [w for w in hojas(APP) if type(w).__name__ == 'Dropdown'][0]
FIG = max((w for w in hojas(APP) if hasattr(w, 'data')), key=lambda w: len(w.data))

# El circuito con MAS vanos marcables: es donde el tope de ranuras se nota.
peor = max(D.tabla.groupby(D.tabla['CIRCUITO'].astype(str))['FID_VANO'].nunique().items(),
           key=lambda kv: kv[1])[0]
CIRCUITO.value = peor
BOTON['Desmarcar'].click()
for g in ('G. Alto', 'G. Medio-Alto', 'G. Medio', 'G. Bajo'):
    BOTON[g].click()

marcados = [str(f) for f in SEL.value]
# Una serie "esta dibujada" si su traza lleva su fid en el nombre y algun punto con dato.
con_datos = {{t.name for t in FIG.data
              if t.type == 'scatter' and t.name and any(v is not None for v in (t.y or ()))}}
print('RESULTADO ' + json.dumps({{
    'circuito': peor,
    'marcados': len(marcados),
    'dibujados': sum(1 for f in marcados if 'Vano ' + f in con_datos),
    # El pozo de ranuras: dos trazas de scatter por vano en la fila de series.
    'ranuras': sum(1 for t in FIG.data if t.type == 'scatter') // 2,
}}))
"""


@pytest.mark.skipif(not (PAQUETE / "catalogo.joblib").exists(),
                    reason="requiere el paquete del simulador construido")
def test_la_serie_de_tiempo_dibuja_todos_los_vanos_marcados():
    """El circuito mas grande, con los cuatro grupos marcados, contra el paquete
    congelado. Se pincha `dibujados == marcados` y no un numero fijo: el tope del pozo se
    dimensiona con los datos cargados, asi que fijar una cifra aqui la ataria a este
    paquete. Lo que no puede pasar es que el panel dibuje MENOS de lo que hay marcado y
    se lea como que esos vanos no tuvieron eventos.
    """
    import subprocess

    guion = _GUION_SERIES.format(
        src=str(RAIZ / "src"), paquete=str(PAQUETE),
        simular=str(PAQUETE / "Variables_simular.xlsx"),
        costos=str(PAQUETE / "Actividades_mantenimiento_costos_2026.xlsx"))
    proceso = subprocess.run([sys.executable, "-c", guion], cwd=RAIZ,
                             capture_output=True, text=True)
    assert proceso.returncode == 0, proceso.stderr[-3000:]
    linea = next(l for l in proceso.stdout.splitlines() if l.startswith("RESULTADO "))
    r = json.loads(linea[len("RESULTADO "):])

    assert r["marcados"] > 30, (
        f"{r['circuito']} solo marco {r['marcados']} vanos con los cuatro grupos; por "
        "debajo del tope viejo esta prueba no distingue el arreglo del defecto")
    assert r["dibujados"] == r["marcados"], (
        f"el panel dibuja {r['dibujados']} de {r['marcados']} vanos marcados en "
        f"{r['circuito']} ({r['ranuras']} ranuras)")


@pytest.mark.skipif(not (PAQUETE / "catalogo.joblib").exists(),
                    reason="requiere el paquete del simulador construido")
def test_los_botones_de_grupo_suman_y_solo_desmarcar_quita():
    """Los cuatro botones PULSADOS de verdad contra el paquete congelado.

    Lo que se afirma es lo que el usuario pidio y lo que el fuente no prueba: que
    encadenar dos grupos no pierde el primero, que ningun grupo pisa a otro, que una
    marca hecha a mano sobrevive al boton, y que `Desmarcar` sigue siendo el unico que
    quita. Corre en subproceso por lo mismo que su vecina: arma el tablero entero.
    """
    import subprocess

    guion = _GUION_BOTONES.format(
        src=str(RAIZ / "src"), paquete=str(PAQUETE),
        simular=str(PAQUETE / "Variables_simular.xlsx"),
        costos=str(PAQUETE / "Actividades_mantenimiento_costos_2026.xlsx"))
    proceso = subprocess.run([sys.executable, "-c", guion], cwd=RAIZ,
                             capture_output=True, text=True)
    assert proceso.returncode == 0, proceso.stderr[-3000:]
    linea = next(l for l in proceso.stdout.splitlines() if l.startswith("RESULTADO "))
    r = json.loads(linea[len("RESULTADO "):])

    assert r["circuito"] is not None, (
        "ningun circuito de los 20 primeros tiene los cuatro grupos poblados en su "
        f"ventana inicial; sin eso esta prueba no distingue sumar de reemplazar: {r}")

    # La suma. Cada clic deja la seleccion en el total de los grupos pulsados hasta ahi:
    # si reemplazara, el acumulado seria la cuenta de cada grupo por separado.
    esperado, corriendo = [], 0
    for g in ("G. Alto", "G. Medio-Alto", "G. Medio", "G. Bajo"):
        corriendo += r["cuentas"][g]
        esperado.append(corriendo)
    assert r["acumulado"] == esperado, (
        f"los botones no suman: {r['acumulado']} contra {esperado} ({r['cuentas']})")
    assert r["sin_duplicados"], "un vano quedo marcado dos veces"

    # El aviso dice cuantos hay, tambien cuando SI hay: era el unico caso que callaba.
    assert "vanos en grupo" in r["aviso_lleno"], r["aviso_lleno"]
    assert "en la ventana" in r["aviso_lleno"], r["aviso_lleno"]

    assert r["tras_desmarcar"] == 0, "Desmarcar dejo vanos marcados"
    assert r["manual_sobrevive"], (
        "el boton de grupo se llevo por delante una marca hecha a mano; el mapa y las "
        "casillas marcan igual que el, y ninguno de los dos es menos valido")


@pytest.mark.skipif(not (PAQUETE / "catalogo.joblib").exists(),
                    reason="requiere el paquete del simulador construido")
def test_el_tablero_se_arma_entero_contra_el_paquete_congelado():
    """El camino EXACTO de la aplicacion: `cargar()` y despues `construir()`.

    Corre en subproceso porque arma 593 widgets y un `FigureWidget` con el bundle
    de plotly.js dentro; eso no se devuelve al proceso de pruebas al terminar.

    No sustituye a `test_simulador_flujo_vivo.py`, que conduce el tablero en un
    navegador: aqui no se puede pulsar `Simular` -- corre en el bucle de eventos
    del widget y fuera del navegador deja las barras vacias. Lo que si se afirma es
    lo que aquel no puede permitirse comprobar en cada arranque, y lo hace en
    segundos en vez de en ocho minutos.
    """
    import subprocess

    guion = _GUION_TABLERO.format(
        src=str(RAIZ / "src"), paquete=str(PAQUETE),
        simular=str(PAQUETE / "Variables_simular.xlsx"),
        costos=str(PAQUETE / "Actividades_mantenimiento_costos_2026.xlsx"))
    proceso = subprocess.run([sys.executable, "-c", guion], cwd=RAIZ,
                             capture_output=True, text=True)
    assert proceso.returncode == 0, proceso.stderr[-3000:]
    linea = next(l for l in proceso.stdout.splitlines() if l.startswith("RESULTADO "))
    r = json.loads(linea[len("RESULTADO "):])

    # UNA figura otra vez: el grafo volvio a ella, en una septima fila bajo el costo.
    # Estuvo un tiempo aparte, debajo del panel de control.
    #
    # El numero se fija -- y no se relaja a ">= 1" -- porque cada `FigureWidget` cuesta lo
    # suyo y partir la figura tiene que ser una decision, no algo que se cuele.
    assert r["figuras"] == 1, (
        "el tablero tiene UNA figura, con todos sus paneles dentro")
    assert r["trazas"] > 50, f"la figura salio con {r['trazas']} trazas"
    assert r["widgets"] > 300, (
        f"el tablero armo {r['widgets']} widgets; las casillas de vano, de variable y "
        "de actividad ya pasan de 200 por su cuenta")
    # Los tres paneles que dan sentido al tablero: el mapa medido, el simulado y el
    # grafo. Que la figura tenga trazas no dice que los paneles esten.
    for panel in ("Criticidad Original", "Criticidad Simulada", "Grafo"):
        assert any(panel in t for t in r["titulos"]), (
            f"falta el panel {panel!r}; hay {r['titulos']}")


def test_derivar_no_necesita_ningun_cuaderno():
    """Lo que esta rebanada existe para lograr, comprobado y no prometido.

    Se comprobaba rompiendo `cuaderno.ejecutar` a proposito, y era la forma correcta
    mientras existia: sin eso, el modulo podia envolver la ejecucion de celdas y las
    huellas cuadraban igual. Ese ayudante se borro con el ultimo `.ipynb`, asi que la
    pregunta se contesta un nivel mas arriba y sin datos: `derivacion` no nombra
    ningun cuaderno ni ningun `exec`.

    La version cara -- que `derivar()` produce el paquete byte a byte -- ya la
    comprueba `test_derivar_reproduce_el_paquete_golden` mas arriba.
    """
    import ast

    fuente = (RAIZ / "src" / "chec_tableros" / "simulador" / "derivacion.py").read_text(
        encoding="utf-8")
    arbol = ast.parse(fuente)

    llamadas = {ast.unparse(n.func) for n in ast.walk(arbol) if isinstance(n, ast.Call)}
    assert not {"exec", "eval"} & llamadas
    assert ".ipynb" not in {
        n.value for n in ast.walk(arbol)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
