"""La paleta de los tableros, en un solo sitio.

Los cinco cuadernos emiten su propio CSS y todos usan los mismos ocho colores: fondo
blanco, texto casi negro, y una familia rosa/roja que sale de la escala `Reds` con la
que se pintan los datos. Ese es el aspecto que comparten, y es lo que hace que pasar de
un tablero a otro no se sienta como cambiar de aplicacion.

Lo que se agrega DESPUES de los cuadernos -- el boton de cerrar, la barra del menu, la
pagina de CriticidadCHEC -- no sale de ellos y por eso puede desentonar sin que nadie
lo note: cada pieza se ve bien por separado y solo canta cuando estan juntas. Aqui
viven esos colores una vez, con el papel que cumple cada uno.

**Los cuadernos siguen siendo la fuente.** Este modulo no se los impone: los copia, y
`tests/test_aplicaciones_locales.py` comprueba que cada valor de aqui aparece de verdad
en el CSS que ellos emiten. Si algun dia cambian de paleta, esa prueba se pone roja y
dice exactamente cual token se quedo atras -- que es el aviso que hoy no existia.
"""
from __future__ import annotations

# Fondo de pagina. Blanco puro, como `html,body{background:#fff}` de los cuadernos, y
# tambien el soporte de fondo generico que pide el manual de marca de EPM.
FONDO = "#fff"

# Texto principal. No es negro: `#000` sobre blanco cansa y ninguno de los tableros
# lo usa.
TEXTO = "#2b2b2b"

# El acento: el VERDE BOSQUE de CHEC / Grupo EPM. Muestreado del propio `checlogo.png`
# del repositorio -- #008024 -- y coincide con el PANTONE 355 del manual de marca de EPM
# (RGB 0/121/52), que es su color secundario. Se usa el bosque y no el verde citrico
# porque los botones llevan texto blanco encima y el citrico no da contraste.
#
# Antes era el rojo fuerte de la escala `Reds` de los datos, y esa coincidencia -- boton
# de accion y extremo caliente de un mapa, el mismo color -- se acabo A PROPOSITO: la
# marca manda en el chrome y la escala de los datos se queda como esta. Son dos cosas
# distintas y ahora se ven distintas.
ACENTO = "rgb(0,128,36)"
ACENTO_OSCURO = "rgb(0,102,29)"       # solo para `:hover`

# El VERDE CITRICO, color PRIMARIO de la marca (#8bc21b en el logo; PANTONE 375 en el
# manual). No sirve de fondo de boton -- no contrasta con texto blanco -- pero si de
# realce y de filo, que es donde la marca se reconoce.
ACENTO_CLARO = "rgb(139,194,27)"

# Fondo de los bloques de control. Un lavado citrico palidisimo que separa el panel del
# lienzo sin dibujarle una caja gris encima. Es el mismo papel que hacia el rosa.
PANEL = "#f3f8ec"

# Bordes. El suave delimita bloques; el fuerte, controles que se pueden tocar
# (`select`, `input`), donde hace falta mas contraste para que se lean como tales.
BORDE = "#cfe3ac"
BORDE_FUERTE = "#a8c97a"

# Texto secundario: avisos, notas al pie, lo que acompania sin competir. Es el GRIS de
# la marca -- #747378 en el logo, PANTONE Cool Gray 8 en el manual --, que alli cumple
# exactamente el mismo papel: acompaniar y neutralizar sin competir con el verde.
TENUE = "#747378"

# El grosor y el color del filo izquierdo de un panel. Es el gesto que mas repiten los
# cinco tableros, y lo que hace que un bloque se lea como "panel de este proyecto".
FILO = f"4px solid {ACENTO}"

# Los ocho colores, para que las pruebas puedan recorrerlos sin listarlos otra vez.
TOKENS = {
    "FONDO": FONDO,
    "TEXTO": TEXTO,
    "ACENTO": ACENTO,
    "ACENTO_OSCURO": ACENTO_OSCURO,
    "PANEL": PANEL,
    "BORDE": BORDE,
    "BORDE_FUERTE": BORDE_FUERTE,
    "TENUE": TENUE,
    "ACENTO_CLARO": ACENTO_CLARO,
}

# La misma pila de fuentes que fijan los cuadernos. Va aqui por lo mismo que los
# colores: una pieza agregada despues con otra fuente desentona igual que con otro
# color, y se nota menos al revisarla.
FUENTE = "system-ui, -apple-system, 'Segoe UI', sans-serif"

# La MISMA pila, escapada para caber dentro de una cadena de JavaScript delimitada por
# comillas simples. `'Segoe UI'` las lleva, y sin escapar cierran la cadena antes de
# tiempo: el guion deja de parsear entero y la pagina se queda quieta. El sintoma es
# mudo -- la pagina se pinta, el estilo se ve bien, y simplemente nada se llena --, asi
# que hay que usar `__FUENTE_JS__` en todo fragmento que se construya DENTRO de una
# cadena de JavaScript, y `__FUENTE__` solo en CSS o en atributos HTML literales.
FUENTE_JS = FUENTE.replace("'", "\\'")


def aplicar(texto: str) -> str:
    """Resuelve los marcadores `__TOKEN__` de un fragmento de HTML o de JavaScript.

    Marcadores y no una f-string porque estos fragmentos van llenos de llaves -- CSS y
    JavaScript --, que una f-string intentaria interpretar. Y no `str.format` por lo
    mismo.

    `FUENTE_JS` va antes que `FUENTE` a proposito: son prefijos el uno del otro, y al
    reves `__FUENTE__` se comeria el principio de `__FUENTE_JS__` y dejaria un `_JS__`
    suelto en medio del estilo.
    """
    reemplazos = [("FUENTE_JS", FUENTE_JS), ("FUENTE", FUENTE), ("FILO", FILO)]
    reemplazos += list(TOKENS.items())
    for clave, valor in reemplazos:
        texto = texto.replace(f"__{clave}__", valor)
    return texto
