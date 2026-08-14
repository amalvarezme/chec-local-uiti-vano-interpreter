#!/bin/sh
# NO ES EL DESTINO DEL DOBLE CLIC. Para eso esta `Iniciar.app`, al lado.
#
# Un `.command` queda a merced de la atadura de LaunchServices de cada maquina, y esa
# atadura no viaja con el repositorio. Con Ghostty instalado -- que se declara manejador
# de `.command` con CFBundleTypeRole = Editor -- el doble clic sobre este archivo NO
# EJECUTA NADA: solo se lleva el foco a la sesion ya abierta. Si estas leyendo esto en un
# editor porque hiciste doble clic aqui, eso es exactamente lo que acaba de pasar: cierra
# esto y abre `Iniciar.app`.
#
# Este archivo se conserva para correrlo A MANO desde una terminal ya abierta:
#
#     ./iniciar.command
#
# Ctrl+C en esa ventana lo detiene. Ver `aplicaciones/README.md`, "La regla de Ghostty".
cd "$(dirname "$0")" || exit 1
python3 ../_comun/gestor.py iniciar "$@"
