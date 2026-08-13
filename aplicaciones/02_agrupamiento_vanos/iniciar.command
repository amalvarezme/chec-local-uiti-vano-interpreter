#!/bin/sh
# macOS / Linux -- doble clic. Levanta la aplicacion y abre el navegador.
# Ctrl+C en esta ventana la detiene.
cd "$(dirname "$0")" || exit 1
python3 ../_comun/gestor.py iniciar "$@"
