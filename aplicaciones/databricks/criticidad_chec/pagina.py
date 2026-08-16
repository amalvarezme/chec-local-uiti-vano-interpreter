"""La portada de la app consolidada: cuatro tarjetas y nada mas.

## Por que no reusa `menu_pagina.py`

El menu local y esto se parecen en la pantalla y en nada mas. Aquel gobierna procesos:
instala entornos, lanza cada tablero como hijo, vigila su fase, lo apaga. Su JavaScript
esta construido entero alrededor de un detalle de eso -- abrir la pestania con
`window.open()` DENTRO del clic, porque preparar un tablero puede tardar minutos y una
ventana abierta despues la bloquea el navegador.

Aqui no hay nada que preparar: los cuatro paneles ya estan construidos y una ruta los
sirve. Reusar aquella pagina obligaria a colar un "modo" por el servidor, por el JSON
de estado y por el JavaScript, para apagar en uno de los dos modos justo lo que la hace
existir. Son cuatro enlaces.

Lo que si se comparte es la PALETA, que es lo que hace que las dos se vean del mismo
proyecto, y los titulos y descripciones, que salen de `tableros.py`.
"""
from __future__ import annotations

import html

import paleta as _paleta

_PLANTILLA = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CriticidadCHEC</title>
<style>
* {{ box-sizing: border-box; }}
body {{ margin: 0; padding: 12px; font: 15px/1.55 {fuente};
       background: {fondo}; color: {texto}; }}
.envoltura {{ max-width: 880px; margin: 0 auto; padding: 20px 8px 60px; }}
h1 {{ font-size: 25px; margin: 0 0 6px; letter-spacing: -.01em; }}
p.intro {{ margin: 0 0 26px; color: {tenue}; }}
a.tarjeta {{ display: block; text-decoration: none; color: inherit;
            background: {panel}; border: 1px solid {borde};
            border-left: {filo}; border-radius: 8px;
            padding: 16px 18px; margin-bottom: 12px; }}
a.tarjeta:hover {{ border-color: {borde_fuerte}; }}
a.tarjeta h2 {{ font-size: 17px; margin: 0 0 4px; }}
a.tarjeta p {{ margin: 0; color: {tenue}; font-size: 14px; }}
footer {{ margin-top: 34px; color: {tenue}; font-size: 13px; }}
</style>
</head>
<body>
<div class="envoltura">
<h1>CriticidadCHEC</h1>
<p class="intro">Tableros de criticidad por vano y por circuito. Cada uno se construyo
antes de publicarse y se sirve como archivos: abren en segundos y no necesitan un
cluster encendido.</p>
{tarjetas}
<footer>El <b>simulador de riesgo por vano</b> no esta aqui: necesita un interprete de
Python en ejecucion para correr el modelo MIL sobre lo que elijas, y esto sirve
archivos. Se publica aparte.</footer>
</div>
</body>
</html>
"""

_TARJETA = """<a class="tarjeta" href="{ruta}">
<h2>{titulo}</h2>
<p>{descripcion}</p>
</a>"""


def portada(rutas) -> str:
    """El documento completo. Sin dependencias externas y sin JavaScript.

    Sin JS a proposito: lo unico que esta pagina hace es enlazar, y un enlace lo sabe
    hacer el navegador. El JavaScript del menu local existe por su ciclo de vida, que
    aqui no hay.
    """
    tarjetas = "\n".join(
        _TARJETA.format(ruta=html.escape(r.ruta), titulo=html.escape(r.titulo),
                        descripcion=html.escape(r.descripcion))
        for r in rutas
    )
    return _PLANTILLA.format(
        fuente=_paleta.FUENTE, fondo=_paleta.FONDO, texto=_paleta.TEXTO,
        tenue=_paleta.TENUE, panel=_paleta.PANEL, borde=_paleta.BORDE,
        borde_fuerte=_paleta.BORDE_FUERTE, filo=_paleta.FILO,
        tarjetas=tarjetas,
    )
