#!/bin/sh
# macOS / Linux -- doble clic. Crea el entorno de esta aplicacion e instala sus
# dependencias. Se corre UNA vez; despues basta con iniciar.command.
cd "$(dirname "$0")" || exit 1
python3 ../_comun/gestor.py instalar "$@"
estado=$?
echo ""
printf 'Pulsa Intro para cerrar esta ventana. '
read -r _
exit $estado
