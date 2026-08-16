"""Los tableros del proyecto, como codigo importable en vez de celdas de cuaderno.

Hasta agosto de 2026 las cinco aplicaciones de escritorio tenian su fuente real dentro
de un `.ipynb`, y `aplicaciones/_comun/cuaderno.py` la ejecutaba con `exec()`. Ese
diseno tenia una virtud que conviene no perder de vista -- el cuaderno era la UNICA
fuente, asi que no habia copia que desincronizar -- y tres costos que se pagaban cada
dia: el codigo no era navegable, cambiarlo desde una aplicacion exigia parches de texto
por contenido, y las pruebas afirmaban sobre cadenas.

Aqui viven los cinco, uno por modulo:

    clima                   agrupamiento            trayectorias_circuitos
    trayectorias_vanos      simulador/

Los cuatro primeros exponen `construir(*, raiz, ruta_html, abrir) -> Path` y escriben un
HTML autocontenido. `simulador/` va aparte porque son dos ciclos de vida distintos:
`derivacion` corre al CONSTRUIR el paquete congelado y `tablero` corre en CADA apertura,
dentro de un kernel vivo, asi que su `construir()` recibe un `Derivado` y devuelve un
widget.

La migracion se hizo por rebanadas (`sdd/retire-base-apps-notebooks`), cada tablero con
su prueba contra el golden congelado en `tests/golden/tableros_pre_migracion/` ANTES de
que existiera este paquete: la pregunta no era si el tablero se veia bien, sino si salia
identico byte a byte.
"""
