#!/bin/sh
# NO ES EL DESTINO DEL DOBLE CLIC. Ver la nota de `iniciar.command`, al lado: con Ghostty
# atado a los `.command`, el doble clic sobre este archivo no ejecuta nada.
#
# Crea el entorno de esta aplicacion e instala sus dependencias. Se corre UNA vez, a mano
# desde una terminal ya abierta:
#
#     ./instalar.command
#
# Despues basta con `Iniciar.app`, que instala solo si hace falta.
cd "$(dirname "$0")" || exit 1
python3 ../_comun/gestor.py instalar "$@"
estado=$?
echo ""
printf 'Pulsa Intro para cerrar esta ventana. '
read -r _
exit $estado
