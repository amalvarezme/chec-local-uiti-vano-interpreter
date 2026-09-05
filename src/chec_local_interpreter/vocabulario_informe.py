"""El vocabulario del informe, unificado al pintar.

Los agentes escriben "los 208 circuitos de la flota" y "la ventana pico". Ninguna de
las dos es incorrecta, pero la primera es jerga interna -- quien recibe el informe no
tiene una flota, tiene circuitos -- y la segunda convive en el mismo documento con
"ventana de mayor impacto", que nombra exactamente lo mismo. El revisor senalo las dos.

Se aplica al RENDER y no al guardar, por la misma razon que `nombrar_prosa_en_datos`:
el `.out.json` es el artefacto que el propio `validate` del agente acepto, y
reescribirlo lo separaria de su validacion. La ventaja practica de hacerlo aqui es que
las corridas YA archivadas se vuelven a pintar con el vocabulario nuevo sin volver a
gastar un token en los agentes.

**Lo que NO se toca: "eventos".** El revisor pidio cambiar toda referencia a cantidad
de eventos por "vanos probables de causa de falla". No se hace, porque no son lo mismo
y la sustitucion volveria falso el numero: medido sobre la base real, 159.470 filas son
6.455 interrupciones distintas repartidas sobre 27.390 vanos. Decir "235 vanos
probables de causa de falla" donde el dato es "235 interrupciones" multiplicaria el
tamano del problema por veinte. Lo que si se hizo es surtir el numero de vanos como
dato propio y con ese nombre en la ficha de cabecera -- ver `ficha_circuito` --, que es
la informacion que el comentario buscaba.
"""

from __future__ import annotations

import re
from typing import Any

from chec_local_interpreter.glosario_variables import CLAVES_DE_IDENTIDAD

#: (patron, reemplazo). El orden importa: las formas mas especificas van primero, para
#: que "circuitos de la flota" no lo capture antes la regla generica de "la flota".
#:
#: Todas llevan frontera de palabra: `flotante` contiene `flota`, y una regla sin
#: frontera deja "el neutro el total de circuitosnte" -- el mismo error que ya se pago
#: con la enye en la guarda de tildes.
_REGLAS: tuple[tuple[re.Pattern[str], str], ...] = (
    # --- la flota -------------------------------------------------------------
    (re.compile(r"\bcircuitos de la flota\b", re.IGNORECASE), "circuitos totales"),
    (re.compile(r"\bde una flota de\b", re.IGNORECASE), "de un total de"),
    (re.compile(r"\bdentro de su flota\b", re.IGNORECASE), "dentro del total de circuitos"),
    (re.compile(r"\bde su flota\b", re.IGNORECASE), "del total de circuitos"),
    (re.compile(r"\bde la flota\b", re.IGNORECASE), "del total de circuitos"),
    (re.compile(r"\ben la flota\b", re.IGNORECASE), "en el total de circuitos"),
    (re.compile(r"\bla flota\b", re.IGNORECASE), "el total de circuitos"),
    (re.compile(r"\bsu flota\b", re.IGNORECASE), "el total de circuitos"),
    # --- ventana pico / de mayor impacto --------------------------------------
    # Las dos nombran la ventana con mas UITI acumulado. Solo se toca la ventana:
    # `pico` a secas describe la forma de la serie y es castellano correcto, y una
    # regla sobre la palabra suelta deja "un pico temprano en V2" ilegible.
    (re.compile(r"\bventanas? de mayor impacto\b", re.IGNORECASE),
     "ventana de mayor aporte UITI"),
    (re.compile(r"\bventanas? pico\b", re.IGNORECASE), "ventana de mayor aporte UITI"),
)


def _con_la_caja_del_original(original: str, reemplazo: str) -> str:
    """Un reemplazo a principio de frase conserva la mayuscula que sustituye.

    Sin esto, "La flota completa" queda "el total de circuitos completa" a mitad de
    parrafo y el informe se llena de frases que empiezan en minuscula.
    """
    if original[:1].isupper():
        return reemplazo[:1].upper() + reemplazo[1:]
    return reemplazo


def normalizar_vocabulario(texto: str | None) -> str:
    """Una pasada de reglas sobre la prosa de un agente."""
    if not texto:
        return ""
    salida = str(texto)
    for patron, reemplazo in _REGLAS:
        salida = patron.sub(
            lambda m, r=reemplazo: _con_la_caja_del_original(m.group(0), r), salida
        )
    return salida


def normalizar_vocabulario_en_datos(valor: Any, _clave: str | None = None) -> Any:
    """La respuesta de un agente con su prosa normalizada y su identidad intacta.

    Devuelve una copia y respeta `CLAVES_DE_IDENTIDAD` -- la MISMA lista que usa
    `nombrar_prosa_en_datos`, y no una copia suya: dos listas de que es prosa y que es
    identidad divergen en cuanto alguien anade una clave a una sola de las dos.
    """
    if isinstance(valor, dict):
        return {k: normalizar_vocabulario_en_datos(v, k) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [normalizar_vocabulario_en_datos(v, _clave) for v in valor]
    if isinstance(valor, str):
        if _clave in CLAVES_DE_IDENTIDAD:
            return valor
        return normalizar_vocabulario(valor)
    return valor
