"""Los cuatro paneles que el informe muestra por escenario, sobre el modelo MIL.

El informe llevaba pares de barras/radar de SHAP. Se fueron con MGCECDL, y lo que el
MIL si puede mostrar es otra cosa. Cada panel contesta algo que los demas no:

- la SERIE por ventana de cada vano identificado: dice si el problema es cronico o
  aparecio el mes pasado, que se atiende distinto. Un vano visto solo en la ventana en
  que salio critico no permite esa lectura;
- las BARRAS DE RELEVANCIA: que palanca mueve a ese vano, y cuanto;
- el UITI medido contra el estimado, con el GRUPO de criticidad de cada uno: una caida
  de UITI que no cambia el grupo no es una orden de trabajo;
- el GRAFO del escenario, como ANILLO: que variables se mueven juntas. Lo que dibuja
  sigue siendo la diferencia entre el grafo base y el simulado -- el grafo en si es casi
  todo pesos fijos del experto, y el antes y el despues se ven iguales lado a lado --,
  pero presentada como estructura y no como una lista de pares. Un grafo contesta "que
  esta conectado con que" y "que variable es el centro", y eso no cabe en barras. Es
  ademas el MISMO anillo del panel del cuaderno 06, con sus mismas dos piezas
  (`plegar_rezagos` y `trazas_grafo`): quien lea el informe y el tablero ve un solo
  dibujo, no dos que hay que reconciliar.

Se guardan como PNG bajo `run_dir` y se citan con ruta RELATIVA, igual que hacia el
camino anterior: el sidecar deja de ser portable si la carpeta se copia con rutas
absolutas dentro.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

# Semaforo de criticidad, el mismo de los cuadernos: verde Bajo, amarillo Medio,
# naranja Medio-Alto, rojo Alto. El color significa lo mismo en el informe y en el
# tablero, que es la unica razon por la que se puede leer uno despues del otro.
COLORES_GRUPOS = ("#1a9641", "#f2c200", "#ef6c00", "#c62828")
NOMBRES_GRUPOS = ("Bajo", "Medio", "Medio-Alto", "Alto")
# Una clase que la paleta de cuatro no cubre. Gris neutro, deliberadamente FUERA del
# semaforo: un vano sin grupo legible pintado del color de un grupo afirma una clase
# que nadie asigno. Es la salida degradada, no un quinto nivel.
COLOR_SIN_GRUPO = "#94a3b8"
# El azul de las barras de relevancia. Alli el color no codifica nada -- todas las
# barras miden lo mismo y el largo ya las ordena --, asi que no toca la paleta de
# criticidad.
COLOR_RELEVANCIA = "#0072b2"
TOP_VARIABLES_PANEL = 10
# `TOP_ARISTAS_GRAFO` se fue con las barras de diferencia: recortaba a las quince
# relaciones mas movidas porque quince filas es lo que cabe en una lista legible. El
# anillo no tiene ese limite -- lo que lo satura es el numero de NODOS, y de eso se
# encarga el plegado de rezagos --, y un recorte de aristas ademas mentiria sobre la
# estructura, que es justo lo que el anillo existe para mostrar.


def _lienzo(alto: float = 3.2, ancho: float = 8.0):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(ancho, alto), dpi=140)
    return plt, fig, ax


def _guardar(plt, fig, destino: Path, nombre: str) -> str:
    destino.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(destino / nombre, bbox_inches="tight")
    plt.close(fig)
    return nombre


def _panel_serie(series: Sequence[Mapping[str, Any]], destino: Path,
                 clave: str) -> str | None:
    if not series:
        return None
    plt, fig, ax = _lienzo()
    for serie in series[:10]:
        ax.plot(serie["w"], serie["uv"], marker="o", linewidth=1.6,
                label=f"vano {serie['fid']}")
    ax.set_ylabel("UITI acumulado")
    ax.set_xlabel("Ventana")
    # La secuencia va COMPLETA, con cero donde no hubo eventos: una ventana tranquila
    # de un vano critico es informacion, y omitirla comprime el eje y sugiere una
    # continuidad que no hubo.
    ax.set_title("Serie por ventana de los vanos identificados")
    ax.grid(alpha=0.25)
    if len(series) > 1:
        ax.legend(fontsize=7, ncol=2)
    return _guardar(plt, fig, destino, f"{clave}_serie.png")


def _panel_relevancia(relevancia: Mapping[str, Any], destino: Path,
                      clave: str) -> str | None:
    vanos = (relevancia or {}).get("vanos") or {}
    filas: list[tuple[str, float]] = []
    for fid, entrada in vanos.items():
        for var in entrada.get("variables", []):
            filas.append((f"{var['label']} · {fid}", float(var["caida"])))
    if not filas:
        return None
    filas.sort(key=lambda f: f[1], reverse=True)
    filas = filas[:TOP_VARIABLES_PANEL]
    plt, fig, ax = _lienzo(alto=max(2.4, 0.32 * len(filas)))
    etiquetas = [f[0] for f in reversed(filas)]
    ax.barh(etiquetas, [f[1] for f in reversed(filas)], color=COLOR_RELEVANCIA)
    ax.set_xlabel("Caída alcanzable de UITI (log10)")
    ax.set_title("Relevancia: qué baja el UITI de cada vano")
    ax.grid(axis="x", alpha=0.25)
    return _guardar(plt, fig, destino, f"{clave}_relevancia.png")


def _color_de_grupo(clase: Any) -> str:
    try:
        return COLORES_GRUPOS[int(clase)]
    except (TypeError, ValueError, IndexError):
        return COLOR_SIN_GRUPO


def colores_de_barras_uiti(
    vanos: Sequence[Mapping[str, Any]]
) -> tuple[list[str], list[str]]:
    """El color de cada barra medida y de cada barra estimada: el de SU grupo.

    Las dos barras iban en gris y azul, colores fuera del semaforo, con el argumento
    de que distinguen dos CORRIDAS y no dos niveles. El argumento no se sostiene
    contra el uso: el grupo es la unidad en la que se decide una obra, y tenerlo solo
    como texto encima de la barra obliga a leerlas una por una para ver donde esta lo
    rojo. Con el color del grupo, la fila entera se lee de un vistazo y ademas dice lo
    mismo que el mapa y que el tablero de agrupamiento, que ya usan esa paleta.

    Lo que el color deja de distinguir -- medido contra estimado -- lo toma la trama:
    la barra estimada va rayada. Ver `_panel_uiti`.
    """
    return (
        [_color_de_grupo(v.get("clase_base")) for v in vanos],
        [_color_de_grupo(v.get("clase_simulada")) for v in vanos],
    )


# La barra estimada va rayada. Es lo que separa las dos corridas ahora que el color
# lo tomo el grupo: una trama es visible en blanco y negro y no compite con el
# semaforo, que es justo lo que un segundo color si haria.
TRAMA_ESTIMADO = "///"


def _panel_uiti(simulacion: Mapping[str, Any], destino: Path,
                clave: str) -> str | None:
    vanos = (simulacion or {}).get("vanos") or []
    if not vanos:
        return None
    import numpy as np
    from matplotlib.patches import Patch

    plt, fig, ax = _lienzo(alto=3.6)
    x = np.arange(len(vanos))
    ancho = 0.38
    color_medido, color_estimado = colores_de_barras_uiti(vanos)
    # Lo MEDIDO cuando el artefacto lo trae. Este panel se titulaba "UITI medido contra
    # estimado" y dibujaba `u_base`, que es la base del MODELO: dos cantidades de
    # naturaleza distinta, y la del modelo corre +34% sobre la observada -- medido sobre
    # 599 bolsas. Bajo ese rotulo, el sesgo del modelo se lee como un dato de la base.
    # Sin observado se cae a la base y el TITULO lo dice.
    hay_medido = all(v.get("u_observado") is not None for v in vanos)
    base = [float(v["u_observado"] if hay_medido else v["u_base"]) for v in vanos]
    ax.bar(x - ancho / 2, base, ancho,
           color=color_medido, edgecolor="#5b4a48", linewidth=0.4)
    ax.bar(x + ancho / 2, [v["u_simulado"] for v in vanos], ancho,
           color=color_estimado, edgecolor="#5b4a48", linewidth=0.4,
           hatch=TRAMA_ESTIMADO)
    # El GRUPO de cada barra, encima. El color ya lo dice, pero el nombre lo dice sin
    # que haya que recordar la paleta -- y una caida de UITI que no cambia el grupo no
    # es una orden de trabajo, asi que las dos etiquetas juntas son la lectura.
    for i, v in enumerate(vanos):
        for desplazamiento, campo in ((-ancho / 2, "clase_base"),
                                      (ancho / 2, "clase_simulada")):
            g = int(v[campo])
            altura = base[i] if campo == "clase_base" else v["u_simulado"]
            ax.annotate(NOMBRES_GRUPOS[g], (i + desplazamiento, altura),
                        ha="center", va="bottom", fontsize=6.5,
                        color=COLORES_GRUPOS[g], fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels([v["fid"] for v in vanos], rotation=45, ha="right", fontsize=7)
    ax.set_ylabel("UITI acumulado")
    ax.set_title(("UITI medido" if hay_medido else "UITI base del modelo")
                 + " contra estimado, con su grupo de criticidad "
                   "(solo palancas de intervención)")
    # La leyenda explica la TRAMA, no el color: con el color puesto por el grupo, una
    # muestra de color aqui tendria que elegir uno de los cuatro y mentiria sobre los
    # otros tres. El grupo lo rotula cada barra encima, con su nombre y su color.
    ax.legend(
        handles=[
            Patch(facecolor="white", edgecolor="#5b4a48",
                  label="Medido" if hay_medido else "Base del modelo"),
            Patch(facecolor="white", edgecolor="#5b4a48", hatch=TRAMA_ESTIMADO,
                  label="Estimado tras intervenir"),
        ],
        fontsize=8,
    )
    ax.grid(axis="y", alpha=0.25)
    return _guardar(plt, fig, destino, f"{clave}_uiti.png")


def datos_grafo_radial(
    grafo: Mapping[str, Any] | None, features: Sequence[str]
) -> tuple[dict[str, Any] | None, str]:
    """La disposicion del anillo, o el motivo por el que no hay grafo que dibujar.

    Parte PURA, separada del dibujo: es lo unico de un PNG que se puede comprobar.

    Se apoya en las MISMAS dos piezas que el panel del cuaderno 06 --
    `plegar_rezagos` y `trazas_grafo` --, no en una copia. El informe y el tablero
    dibujan el mismo grafo del mismo modelo, y dos disposiciones distintas obligarian
    a quien lee las dos a reconciliar de cabeza dos dibujos que son lo mismo.

    El plegado no es cosmetico: sin el, los doce rezagos de cada variable de clima son
    48 de los 66 nodos, y con esas aristas el anillo queda en 13,6 px de arco por
    nombre para una fuente de 10 -- nombres encimados. Plegado quedan 22 nodos y 62,7
    px de arco.
    """
    if not grafo:
        return None, "La simulación no produjo grafo para esta ventana."
    if grafo.get("voided") or grafo.get("matriz") is None:
        return None, ("El grafo se reconstruye con al menos tres vanos; esta selección "
                      "no llega, así que no se dibuja en vez de mostrarse vacío.")

    import numpy as np

    from chec_local_interpreter.mil_simulador_015 import plegar_rezagos, trazas_grafo

    matriz = np.abs(np.asarray(grafo["matriz"], dtype=float))
    if not float(matriz.max(initial=0.0)):
        return None, "La intervención no movió ninguna relación del grafo."

    # La matriz manda: una lista de nombres mas corta se rellena con `f<k>` en vez de
    # tumbar el panel. Es la tolerancia que tenia el dibujo anterior, y sigue siendo
    # preferible un anillo con dos nodos sin nombre que ningun anillo.
    nombres_entrada = [str(f) for f in features][:matriz.shape[0]]
    nombres_entrada += [f"f{k}" for k in range(len(nombres_entrada), matriz.shape[0])]

    plegada, nombres = plegar_rezagos(matriz, nombres_entrada)
    if not float(np.abs(plegada).max(initial=0.0)):
        # Todo lo que se movio estaba DENTRO de una familia de rezagos, y eso plegado
        # es un lazo de un nodo a si mismo: en un anillo, un punto.
        return None, ("Lo único que movió la intervención fueron relaciones dentro de "
                      "una misma familia de rezagos, que plegadas no son una arista.")

    trazas = trazas_grafo(plegada, nombres)
    if not trazas["nodos"]["texto"]:
        return None, "La intervención no movió ninguna relación del grafo."
    return trazas, ""


def _panel_grafo(grafo: Mapping[str, Any] | None, features: Sequence[str],
                 destino: Path, clave: str) -> tuple[str | None, str]:
    """El grafo del escenario como ANILLO, igual que el panel del cuaderno 06.

    Eran barras horizontales, una por par de variables, ordenadas por cuanto se movio
    la relacion. Contestaban "cuanto", que es lo que una barra sabe hacer, pero un
    grafo es una ESTRUCTURA: que esta conectado con que, y que variables son el centro
    de esa estructura. Eso no cabe en una lista de pares, y era ademas otro dibujo del
    mismo grafo que el tablero ya presenta como anillo.

    Devolver un panel vacio se leeria como "la intervencion no movio nada", que es lo
    contrario de "no hay suficientes vanos para reconstruir el grafo": por eso el
    motivo viaja como texto.
    """
    trazas, motivo = datos_grafo_radial(grafo, features)
    if trazas is None:
        return None, motivo

    import numpy as np

    plt, fig, ax = _lienzo(alto=5.4, ancho=5.4)

    aristas_x = trazas["aristas"]["x"]
    aristas_y = trazas["aristas"]["y"]
    pesos = trazas["pesos"]["peso"]
    maximo = max(pesos, default=0.0) or 1.0

    # Una linea por arista, con el grosor y la opacidad ligados a su peso RELATIVO:
    # los pesos absolutos cambian dos ordenes de magnitud entre ventanas, asi que un
    # grosor fijo por valor deja el anillo plano o saturado segun cual se mire.
    for k in range(0, len(aristas_x), 3):
        peso = pesos[k // 3] if k // 3 < len(pesos) else 0.0
        proporcion = peso / maximo
        ax.plot(aristas_x[k:k + 2], aristas_y[k:k + 2],
                color="#be185d", linewidth=0.6 + 2.6 * proporcion,
                alpha=0.25 + 0.6 * proporcion, zorder=1, solid_capstyle="round")

    ax.scatter(trazas["nodos"]["x"], trazas["nodos"]["y"],
               s=46, color="#0072b2", zorder=3, edgecolors="white", linewidths=0.8)

    # El rotulo corre A LO LARGO de su propio radio. Horizontales se enciman entre
    # vecinos, y el apretujon es peor arriba y abajo, donde el circulo es mas plano.
    for x, y, texto in zip(trazas["nodos"]["x"], trazas["nodos"]["y"],
                           trazas["nodos"]["texto"]):
        grados = float(np.degrees(np.arctan2(y, x)))
        izquierda = 90.0 < grados <= 270.0 or grados < -90.0
        ax.annotate(
            str(texto),
            (x * 1.06, y * 1.06),
            rotation=grados + 180.0 if izquierda else grados,
            rotation_mode="anchor",
            ha="right" if izquierda else "left",
            va="center",
            fontsize=7,
            color="#334155",
        )

    ax.set_xlim(-1.55, 1.55)
    ax.set_ylim(-1.55, 1.55)
    ax.set_aspect("equal")
    ax.axis("off")
    # SIN titulo dentro del PNG: la seccion del informe ya rotula la figura, y dos
    # rotulos para un solo dibujo obligan al lector a decidir cual manda.
    return _guardar(plt, fig, destino, f"{clave}_grafo.png"), ""


def figuras_de_escenario(
    escenario: Mapping[str, Any],
    *,
    series: Sequence[Mapping[str, Any]] = (),
    destino: str | Path,
    features: Sequence[str] = (),
) -> dict[str, Any]:
    """Los cuatro paneles de un escenario, con ruta relativa a `destino`.

    Cada panel se dibuja si tiene datos. Perder los cuatro porque falta uno dejaria al
    informe sin la parte que si existe: un circuito sin vanos criticos no tiene barras
    de UITI ni grafo, pero si serie y relevancia.
    """
    destino = Path(destino)
    clave = str(escenario.get("ventana") or escenario.get("nombre", "escenario"))
    clave = "".join(c if c.isalnum() or c in "-_" else "_" for c in clave)
    grafo_png, motivo = _panel_grafo(
        (escenario.get("simulacion") or {}).get("grafo_diferencia"),
        features, destino, clave)
    return {
        "nombre": escenario.get("nombre"),
        "serie_png": _panel_serie(series, destino, clave),
        "relevancia_png": _panel_relevancia(escenario.get("relevancia") or {},
                                            destino, clave),
        "uiti_png": _panel_uiti(escenario.get("simulacion") or {}, destino, clave),
        "grafo_png": grafo_png,
        "grafo_motivo": motivo,
    }
