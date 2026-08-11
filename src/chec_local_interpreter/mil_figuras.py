"""Los cuatro paneles que el informe muestra por escenario, sobre el modelo MIL.

El informe llevaba pares de barras/radar de SHAP. Se fueron con MGCECDL, y lo que el
MIL si puede mostrar es otra cosa. Cada panel contesta algo que los demas no:

- la SERIE por ventana de cada vano identificado: dice si el problema es cronico o
  aparecio el mes pasado, que se atiende distinto. Un vano visto solo en la ventana en
  que salio critico no permite esa lectura;
- las BARRAS DE RELEVANCIA: que palanca mueve a ese vano, y cuanto;
- el UITI medido contra el estimado, con el GRUPO de criticidad de cada uno: una caida
  de UITI que no cambia el grupo no es una orden de trabajo;
- el GRAFO DIFERENCIA: que movio la intervencion en el grafo reconstruido. El grafo en
  si es casi todo pesos fijos del experto, asi que el antes y el despues se ven iguales
  lado a lado; solo la diferencia aisla el efecto.

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
# Medido contra predicho. Colores fuera de la escala de criticidad a proposito: aqui
# distinguen dos CORRIDAS, no dos niveles, y reusar la paleta invitaria a leerlos como
# clases.
COLOR_MEDIDO = "#94a3b8"
COLOR_SIMULADO = "#0072b2"
TOP_VARIABLES_PANEL = 10
TOP_ARISTAS_GRAFO = 15


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
    ax.barh(etiquetas, [f[1] for f in reversed(filas)], color=COLOR_SIMULADO)
    ax.set_xlabel("Caida alcanzable de UITI (log10)")
    ax.set_title("Relevancia: que baja el UITI de cada vano")
    ax.grid(axis="x", alpha=0.25)
    return _guardar(plt, fig, destino, f"{clave}_relevancia.png")


def _panel_uiti(simulacion: Mapping[str, Any], destino: Path,
                clave: str) -> str | None:
    vanos = (simulacion or {}).get("vanos") or []
    if not vanos:
        return None
    import numpy as np

    plt, fig, ax = _lienzo(alto=3.6)
    x = np.arange(len(vanos))
    ancho = 0.38
    ax.bar(x - ancho / 2, [v["u_base"] for v in vanos], ancho,
           label="Medido", color=COLOR_MEDIDO)
    ax.bar(x + ancho / 2, [v["u_simulado"] for v in vanos], ancho,
           label="Estimado tras intervenir", color=COLOR_SIMULADO)
    # El GRUPO de cada barra, encima. Sin el, una caida de UITI no dice si el vano
    # cambio de grupo -- y el grupo es la unidad en la que se decide la obra.
    for i, v in enumerate(vanos):
        for desplazamiento, campo in ((-ancho / 2, "clase_base"),
                                      (ancho / 2, "clase_simulada")):
            g = int(v[campo])
            altura = v["u_base"] if campo == "clase_base" else v["u_simulado"]
            ax.annotate(NOMBRES_GRUPOS[g], (i + desplazamiento, altura),
                        ha="center", va="bottom", fontsize=6.5,
                        color=COLORES_GRUPOS[g], fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels([v["fid"] for v in vanos], rotation=45, ha="right", fontsize=7)
    ax.set_ylabel("UITI acumulado")
    ax.set_title("UITI medido contra estimado, con su grupo de criticidad "
                 "(solo palancas de intervencion)")
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.25)
    return _guardar(plt, fig, destino, f"{clave}_uiti.png")


def _panel_grafo(grafo: Mapping[str, Any] | None, features: Sequence[str],
                 destino: Path, clave: str) -> tuple[str | None, str]:
    """El grafo diferencia, o el motivo por el que no hay panel.

    Devolver un panel vacio se leeria como "la intervencion no movio nada", que es lo
    contrario de "no hay suficientes vanos para reconstruir el grafo".
    """
    if not grafo:
        return None, "La simulacion no produjo grafo para esta ventana."
    if grafo.get("voided") or grafo.get("matriz") is None:
        return None, ("El grafo se reconstruye con al menos tres vanos; esta seleccion "
                      "no llega, asi que no se dibuja en vez de mostrarse vacio.")
    import numpy as np

    matriz = np.asarray(grafo["matriz"], dtype=float)
    n = matriz.shape[0]
    triangulo = [(i, j, abs(matriz[i, j])) for i in range(n) for j in range(i + 1, n)]
    triangulo = [t for t in triangulo if t[2] > 0]
    if not triangulo:
        return None, "La intervencion no movio ninguna relacion del grafo."
    triangulo.sort(key=lambda t: t[2], reverse=True)
    triangulo = triangulo[:TOP_ARISTAS_GRAFO]

    def _nombre(k: int) -> str:
        return str(features[k]) if k < len(features) else f"f{k}"

    plt, fig, ax = _lienzo(alto=max(2.4, 0.32 * len(triangulo)))
    etiquetas = [f"{_nombre(i)} — {_nombre(j)}" for i, j, _ in reversed(triangulo)]
    ax.barh(etiquetas, [t[2] for t in reversed(triangulo)], color="#be185d")
    ax.set_xlabel("|grafo base - grafo simulado|")
    ax.set_title("Grafo diferencia: que movio la intervencion")
    ax.grid(axis="x", alpha=0.25)
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
