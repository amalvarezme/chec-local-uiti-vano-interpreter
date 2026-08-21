@echo off
rem ===========================================================================
rem  Doble clic aqui si acabas de clonar el repositorio en Windows.
rem
rem  Mide donde quedo el clon y te dice si cabe. Si cabe -- que es lo normal --
rem  no toca nada. Si no cabe, propone moverlo a C:\CHEC y te pide que lo
rem  confirmes escribiendo SI.
rem
rem  ## Por que hace falta medir
rem
rem  Windows no deja CREAR un directorio cuyo camino pase de 248 caracteres. La
rem  instalacion del simulador anida 187 caracteres por debajo de la raiz del
rem  clon -- las licencias de terceros de `kineto`, que pone `torch` --, asi que
rem  el clon tiene que caber en 61. Clonado en el Escritorio no cabe, y la
rem  instalacion aborta a mitad con `WinError 206` dejando un entorno CREADO Y A
rem  MEDIAS, que es el peor final: parece que esta.
rem
rem  ## Por que un .bat y no el .ps1 de al lado
rem
rem  Tres trabas que este archivo resuelve solo, y que si no tendria que
rem  resolver a mano quien lo use:
rem
rem    1. Un .ps1 NO se ejecuta con doble clic: Windows lo abre en el Bloc de
rem       notas. Un .bat si. Y el `-ExecutionPolicy Bypass` se lo pasa este
rem       archivo, en vez de tener que escribirlo nadie.
rem    2. El directorio actual del proceso que lanza no puede estar DENTRO de lo
rem       que se mueve, o el renombrado falla con un `IOException` que no
rem       menciona el directorio actual por ningun lado. Al hacer doble clic,
rem       ese directorio es exactamente el clon -- por eso el `cd /d "%TEMP%"`
rem       de abajo es la primera orden y no un detalle.
rem    3. Sin `pause`, la ventana se cierra encima del resultado y lo unico que
rem       se ve es un parpadeo.
rem ===========================================================================

setlocal

rem La carpeta de este archivo, sin la barra final: es la raiz del clon.
set "CLON=%~dp0"
set "CLON=%CLON:~0,-1%"

rem FUERA del clon antes de nada. Ver la traba 2 de arriba.
cd /d "%TEMP%"

powershell -NoProfile -ExecutionPolicy Bypass -File "%CLON%\scripts\mover-clon.ps1" -Origen "%CLON%" -Asistido %*

echo.
pause
endlocal
