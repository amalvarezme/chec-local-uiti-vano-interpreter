@echo off
REM Windows -- doble clic. Crea el entorno de esta aplicacion e instala sus
REM dependencias. Se corre UNA vez; despues basta con iniciar.bat.
setlocal
cd /d "%~dp0"
set "PY=py -3"
py -3 --version >nul 2>&1 || set "PY=python"
%PY% ..\_comun\gestor.py instalar %*
echo.
pause
