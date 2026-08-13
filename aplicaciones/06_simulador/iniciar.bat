@echo off
REM Windows -- doble clic. Levanta la aplicacion y abre el navegador.
REM Ctrl+C en esta ventana la detiene.
setlocal
cd /d "%~dp0"
set "PY=py -3"
py -3 --version >nul 2>&1 || set "PY=python"
%PY% ..\_comun\gestor.py iniciar %*
if errorlevel 1 pause
