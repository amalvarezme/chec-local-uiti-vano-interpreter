"""Cuando el navegador bloquea la pestania, el menu tiene que DECIRLO.

## Lo que se midio primero, para no arreglar lo que no estaba roto

Con el menu levantado de verdad y empujado con `curl` -- que es exactamente lo que hace
la pagina -- las CINCO aplicaciones se abrieron a la vez y las cinco quedaron sirviendo:
8801, 8802, 8803, 8804 y 8866, todas HTTP 200 simultaneamente. El lanzador no serializa
nada y no hay ningun cupo. Tambien se descarto que macOS reutilice el perfil de
Terminal cuando dos ventanas comparten el nombre del perfil: se probo con dos
trampolines distintos bajo un mismo `<string>name</string>` y corrieron LOS DOS.

## Donde estaba de verdad

En la pagina. `abrir()` abre la pestania DENTRO del gesto del clic:

    var pestania = window.open('', 'app-' + app.clave);

`window.open()` devuelve **null** cuando el navegador bloquea la ventana emergente, y
ese es justo el caso que aparece cuando ya hay una pestania abierta por un script y el
usuario pide otra: la primera pasa por el gesto, las siguientes las bloquea la politica
de emergentes del navegador salvo que el sitio este permitido.

El codigo comprobaba el null para no escribirle el "Cargando...", y luego seguia como si
nada: mandaba `POST /abrir`, la aplicacion arrancaba, tomaba su puerto, y al llegar a
`corriendo` la unica linea que abre el tablero era

    if (pestania && !pestania.closed) { pestania.location = app.url; }

que con `pestania` en null no hace nada. `recordarPestania` tambien descarta el null en
silencio. Resultado desde la silla del usuario: el tablero ESTA corriendo, pero no
aparece ninguna pestania y nada explica por que. Eso se lee como "no me deja abrir otro".

El arreglo no es forzar la emergente -- eso no se puede desde JavaScript --, sino dejar
de fallar en silencio: se anota el bloqueo y la tarjeta lo dice, con el boton `Ver` a
mano, que al colgar de un clic directo si pasa.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

COMUN = Path(__file__).resolve().parents[1] / "aplicaciones" / "_comun"


def _comun(nombre: str):
    """El modulo de `aplicaciones/_comun`, que no es un paquete importable."""
    sys.path.insert(0, str(COMUN))
    try:
        return __import__(nombre)
    finally:
        sys.path.pop(0)


GUION = _comun("menu_pagina")._GUION


def test_el_bloqueo_de_la_pestania_se_anota():
    """Un `window.open()` que devuelve null tiene que dejar rastro, no perderse."""
    assert re.search(r"if \(!pestania\)", GUION), (
        "`abrir()` no distingue el caso en que el navegador bloqueo la pestania")
    assert "BLOQUEADAS" in GUION, (
        "no hay donde anotar que aplicacion se quedo sin pestania")


def test_la_tarjeta_avisa_cuando_no_hubo_pestania():
    """El aviso va en la tarjeta, que es lo que el usuario esta mirando.

    Un `alert()` no sirve: la aplicacion tarda en levantarse y el aviso llegaria minutos
    despues del clic, encima de cualquier cosa que el usuario estuviera haciendo.
    """
    assert re.search(r"BLOQUEADAS\[app\.clave\]", GUION), (
        "`pintar()` no consulta si esa aplicacion se quedo sin pestania")
    assert "emergente" in GUION or "bloque" in GUION.lower(), (
        "el aviso no nombra el bloqueo del navegador, que es la causa")


def test_ver_limpia_la_marca_y_tambien_avisa_si_lo_bloquean():
    """`Ver` cuelga de un clic directo, asi que normalmente pasa. Cuando no, se dice.

    Si `Ver` tambien se lo comen, repetir el aviso es lo unico honesto: insistir con el
    mismo boton no lo va a arreglar, y el usuario necesita saber que tiene que permitir
    las ventanas emergentes de este sitio.
    """
    ver = re.search(r"boton\('Ver'.*?\}\)\);", GUION, re.S)
    assert ver, "no se pudo leer el boton `Ver`"
    cuerpo = ver.group(0)
    # No se exige el literal `BLOQUEADAS` aqui: quien pone y quita la marca es
    # `recordarPestania`, en UN solo sitio. Que `Ver` pase por ella es el contrato.
    assert "recordarPestania(" in cuerpo, (
        "`Ver` no pasa por `recordarPestania`, que es quien lleva la marca de bloqueo")
    assert "refrescar()" in cuerpo, (
        "`Ver` no repinta, asi que el aviso no se actualiza al pulsarlo")
    marca = re.search(r"function recordarPestania\(clave, pestania\) \{.*?\n\}", GUION, re.S)
    assert marca and "delete BLOQUEADAS[clave]" in marca.group(0) \
        and "BLOQUEADAS[clave] = true" in marca.group(0), (
        "`recordarPestania` no es quien pone Y quita la marca")


def test_seguir_ya_no_termina_en_silencio_sin_pestania():
    """Llegar a `corriendo` sin pestania era el punto exacto donde se perdia el aviso."""
    seguir = re.search(r"function seguir\(clave, pestania\) \{.*?\n\}", GUION, re.S)
    assert seguir, "no se pudo leer `seguir()`"
    cuerpo = seguir.group(0)
    assert re.search(r"if \(pestania && !pestania\.closed\) \{ pestania\.location = app\.url; \}\s*\n\s*else", cuerpo) \
        or "BLOQUEADAS" in cuerpo, (
        "`seguir()` sigue dejando pasar el caso sin pestania sin anotar nada")
