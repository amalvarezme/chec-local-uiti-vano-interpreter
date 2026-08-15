#!/bin/sh
# NO ES EL DESTINO DEL DOBLE CLIC. Para eso esta `Iniciar.app`, al lado.
#
# Este archivo se llamaba `iniciar.command`, y ese nombre era el fallo. Un `.command`
# queda a merced de la atadura de LaunchServices de cada maquina, y esa atadura no viaja
# con el repositorio. Con Ghostty instalado -- que se declara manejador de `.command` con
# CFBundleTypeRole = Editor -- el doble clic sobre este archivo NO EJECUTA NADA: abre el
# archivo en un editor y se lleva el foco. Y el arreglo no cabe DENTRO del guion, porque
# el guion no llega a correr. Solo cabe en el nombre: llamandose `iniciar` y estando al
# lado de `Iniciar.app`, el doble clic caia aqui una y otra vez.
#
# Se conserva para correrlo A MANO desde una terminal ya abierta -- y es el camino de
# Linux, donde no hay bundle:
#
#     ./abrir-en-terminal.command
#
# Ctrl+C en esa ventana lo detiene. Ver `aplicaciones/README.md`, "La regla de Ghostty".
cd "$(dirname "$0")" || exit 1
python3 ../_comun/gestor.py iniciar "$@"
