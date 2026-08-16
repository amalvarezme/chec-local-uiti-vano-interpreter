"""Los tableros del proyecto, como codigo importable en vez de celdas de cuaderno.

Hasta ahora las cinco aplicaciones de escritorio tenian su fuente real dentro de
un `.ipynb`, y `aplicaciones/_comun/cuaderno.py` la ejecutaba con `exec()`. Este
paquete es el destino de esa migracion: un modulo por tablero, con pruebas de
comportamiento propias.

Se puebla por rebanadas (`sdd/retire-base-apps-notebooks`). Que hoy solo viva
aqui el arranque del simulador no es un descuido: cada tablero entra con su
prueba contra el golden congelado en `tests/golden/tableros_pre_migracion/`.
"""
