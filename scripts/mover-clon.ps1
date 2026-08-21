<#
.SYNOPSIS
    Mueve el clon a una ruta mas corta, para que la instalacion quepa en MAX_PATH.

.DESCRIPTION
    Windows no deja CREAR un directorio cuyo camino pase de 248 caracteres, y la cola
    mas honda que crea la instalacion son las licencias de terceros de `kineto`, que
    pone `torch` y solo trae `06_simulador`. Si la suma de la ruta del clon mas esa
    cola pasa del limite, la instalacion del simulador aborta con `WinError 206` y deja
    su `.venv` creado y a medias.

    Hay dos salidas: poner `LongPathsEnabled` en 1, que escribe en `HKLM` y pide a quien
    administre la maquina, o acortar la ruta del clon, que no pide permiso a nadie. Este
    script es la segunda.

    Los dos numeros de la cuenta -- el limite y la cola -- NO se escriben aqui: se leen
    de `scripts/diagnostico_local.py`, que es quien los declara y quien los mide. Una
    segunda copia seria una segunda verdad, y la que se desactualiza es siempre la copia.

.PARAMETER Destino
    A donde va el clon. Por defecto `C:\CHEC\<nombre de la carpeta>`.

.PARAMETER Origen
    Que se mueve. Por defecto el clon al que pertenece este script.

.PARAMETER AunConEntornos
    Mueve aunque ya existan `.venv`. Quedaran ROTOS: hay que rehacerlos. Ver mas abajo.

.PARAMETER AunConVSCode
    Mueve aunque VS Code este abierto. Solo si sabes que NO lo tiene abierto sobre este
    clon: no hay forma de comprobarlo desde fuera. Ver la nota del freno.

.PARAMETER Asistido
    El modo del doble clic, para quien no va a leer nada de esto. Mide la ruta y, si ya
    cabe, lo dice y sale sin tocar nada. Si no cabe, ensenia la cuenta, propone el
    destino y pide una confirmacion escrita antes de mover. Lo usa
    `mover-a-ruta-corta.bat`.

.PARAMETER YaFuera
    Uso interno. Marca la copia que corre desde `%TEMP%`; no se pasa a mano.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\mover-clon.ps1

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\mover-clon.ps1 -Destino D:\CHEC\repo
#>
[CmdletBinding()]
param(
    [string]$Destino,
    [string]$Origen,
    [switch]$AunConEntornos,
    [switch]$AunConVSCode,
    [switch]$Asistido,
    [switch]$YaFuera
)

$ErrorActionPreference = 'Stop'

function Di($texto, $color) { Write-Host $texto -ForegroundColor $color }

if ($env:OS -ne 'Windows_NT') {
    Di "Esto es de Windows: en macOS y Linux no hay MAX_PATH que esquivar." 'Yellow'
    exit 1
}

# --------------------------------------------------------------- que se mueve, y a donde

if (-not $Origen) { $Origen = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path }
$Origen = $Origen.TrimEnd('\')

if (-not (Test-Path (Join-Path $Origen 'scripts\diagnostico_local.py'))) {
    Di "No parece el clon: en $Origen no esta scripts\diagnostico_local.py" 'Red'
    Di "Pasa la carpeta con -Origen si la tienes en otro sitio." 'Yellow'
    exit 1
}

# --------------------------------------------------- la cuenta, leida de quien la declara
#
# Los dos numeros no se escriben aqui: los declara y los mide `scripts/diagnostico_local.py`
# y de alli se leen. Una segunda copia seria una segunda verdad.
#
# Se hace ANTES de nada porque en modo asistido decide si hay algo que hacer, y porque
# despues el script corre desde %TEMP% y el clon ya esta en otro sitio. Que no se pueda
# calcular no tumba la mudanza -- mover a una ruta mas corta nunca empeora --, pero sin la
# cuenta no se puede avisar de un destino que tampoco cabe.

$limite = 0
$cola = 0
if (-not $YaFuera) {
    try {
        $py = 'py'
        if (-not (Get-Command py -ErrorAction SilentlyContinue)) { $py = 'python' }
        Push-Location $Origen
        $salida = & $py -3 -c "from scripts.diagnostico_local import LIMITE_DE_DIRECTORIO, COLA_MAS_LARGA; print(LIMITE_DE_DIRECTORIO, COLA_MAS_LARGA)"
        Pop-Location
        $partes = ($salida | Out-String).Trim() -split '\s+'
        $limite = [int]$partes[0]
        $cola = [int]$partes[1]
    } catch {
        Pop-Location -ErrorAction SilentlyContinue
        Di "AVISO: no se pudo leer la cuenta de scripts\diagnostico_local.py; sigo sin ella." 'Yellow'
    }
}

# El modo asistido se para aqui cuando no hay nada que arreglar. Es la respuesta mas
# frecuente y tiene que ser la mas tranquila: quien hace doble clic en esto no sabe si le
# hace falta, y descubrir que no es un resultado, no un no-evento.
if ($Asistido -and $limite -gt 0 -and ($Origen.Length + $cola) -le $limite) {
    Di "No hace falta mover nada." 'Green'
    Write-Host ""
    Di "  El clon esta en  $Origen" 'Gray'
    Di "  $($Origen.Length) caracteres; torch llegara a $($Origen.Length + $cola), y el corte esta en $limite." 'Gray'
    Di "  Sobran $($limite - $Origen.Length - $cola) caracteres." 'Gray'
    Write-Host ""
    Di "Puedes seguir con la instalacion." 'Cyan'
    exit 0
}

if (-not $Destino) { $Destino = Join-Path 'C:\CHEC' (Split-Path -Leaf $Origen) }
$Destino = $Destino.TrimEnd('\')

if ($Origen -eq $Destino) {
    Di "El clon ya esta en $Destino. No hay nada que mover." 'Yellow'
    exit 0
}
if (Test-Path $Destino) {
    Di "El destino ya existe: $Destino" 'Red'
    Di "Si la mudanza ya se hizo, no vuelvas a correr esto. Si no, elige otro destino." 'Yellow'
    exit 1
}

# Los entornos que ya hay dentro. Se calcula siempre, porque el mensaje final tambien lo
# necesita. Se miran los dos sitios donde el proyecto los pone -- la raiz y cada aplicacion
# -- y no con `-Recurse`: un recorrido recursivo desciende DENTRO de los propios entornos,
# que son ~4 GB de archivos. Medido sobre este clon con los siete puestos: 6,9 s recursivo
# contra 0,03 s dirigido, y los mismos siete. La lista de aplicaciones no se escribe aqui,
# se descubre con el comodin.
$entornos = @(Get-Item -Path (Join-Path $Origen '.venv') -ErrorAction SilentlyContinue) +
            @(Get-Item -Path (Join-Path $Origen 'aplicaciones\*\.venv') -ErrorAction SilentlyContinue)

# Todo lo que sigue -- el informe, los frenos y el salto a %TEMP% -- lo hace SOLO la
# primera invocacion. La copia que corre desde %TEMP% ya llega con el permiso dado y va
# derecha a mover: repetirlo alli imprimiria el informe entero dos veces.
if (-not $YaFuera) {

if ($limite -gt 0) {
    $hondoAntes = $Origen.Length + $cola
    $hondoDespues = $Destino.Length + $cola
    Di "  origen   $($Origen.Length) caracteres; torch llegaria a $hondoAntes" 'Gray'
    Di "  destino  $($Destino.Length) caracteres; torch llegara a $hondoDespues" 'Gray'
    Di "  el corte esta en $limite" 'Gray'
    Write-Host ""
    if ($hondoDespues -gt $limite) {
        Di "El destino TAMPOCO cabe: se pasa por $($hondoDespues - $limite) caracteres." 'Red'
        Di "Elige uno mas corto con -Destino, o que pongan LongPathsEnabled en 1." 'Yellow'
        exit 1
    }
    if ($Destino.Length -ge $Origen.Length) {
        Di "El destino no es mas corto que el origen. Mover no arregla nada." 'Yellow'
    }
}

# ------------------------------------------------------------- lo que bloquea la mudanza
#
# Un archivo abierto por otro proceso hace fallar `Move-Item`. Dentro del mismo volumen es
# un renombrado y falla entero, que no deja rastro; entre volumenes distintos es copiar y
# borrar, y ahi un handle a mitad SI puede dejar el clon partido entre las dos rutas. Por
# eso se comprueba antes en vez de confiar en el error.
#
# El freno de VS Code es global -- cualquier VS Code abierto, no solo el de este clon -- y
# no se puede acotar: la ruta del workspace NO aparece en la linea de comando de sus
# procesos hijo (medido el 2026-08-20 sobre los seis `Code.exe` de una ventana abierta en
# el clon; ninguno la lleva). Sin manera de distinguirlos, se prefiere el falso positivo,
# que cuesta cerrar una ventana, al falso negativo, que cuesta el clon.

if ((Get-Process Code -ErrorAction SilentlyContinue) -and -not $AunConVSCode) {
    Di "VS Code sigue abierto. Cierralo del todo y vuelve a correr esto." 'Yellow'
    Di "Si el que esta abierto NO es este clon, -AunConVSCode salta este freno." 'Yellow'
    exit 1
}

$abiertos = @(Get-Process -ErrorAction SilentlyContinue |
              Where-Object { $_.Path -and $_.Path.StartsWith("$Origen\", 'OrdinalIgnoreCase') })
if ($abiertos.Count -gt 0) {
    Di "Hay procesos corriendo desde dentro del clon. Cierralos primero:" 'Yellow'
    foreach ($p in $abiertos) { Di "  PID $($p.Id)  $($p.Path)" 'Yellow' }
    exit 1
}

# ------------------------------------------------------------------- los entornos, si hay
#
# Los shims de un `.venv` llevan la ruta absoluta DENTRO: `pip.exe` empieza por
# `#!C:\...\.venv\Scripts\python.exe` y `activate.bat` fija `VIRTUAL_ENV=C:\...`. Mover la
# carpeta no reescribe ninguno de los dos, asi que un entorno movido apunta a un
# interprete que ya no esta ahi. Se rehacen, no se reparan.

if ($entornos.Count -gt 0 -and -not $AunConEntornos) {
    Di "El clon ya tiene $($entornos.Count) entorno(s) instalado(s):" 'Red'
    foreach ($e in $entornos) { Di "  $($e.FullName.Substring($Origen.Length + 1))" 'Red' }
    Write-Host ""
    Di "Moverlos los ROMPE: sus shims llevan la ruta absoluta dentro." 'Yellow'
    Di "Dos salidas:" 'Yellow'
    Di "  1. Borralos, mueve, y vuelve a correr /instalar-local en el destino." 'Yellow'
    Di "  2. -AunConEntornos para mover igual, y rehacerlos alli uno por uno con" 'Yellow'
    Di "     gestor.py instalar --recrear --app <carpeta>" 'Yellow'
    exit 1
}

# ------------------------------------------------- correr desde fuera de lo que se mueve
#
# Un directorio con el CWD de algun proceso dentro no se puede renombrar, y este script
# vive dentro del clon: lanzado tal cual, se bloquea a si mismo. Asi que se copia a %TEMP%
# y se relanza desde alli.
#
# Pero eso arregla el CWD del SCRIPT, no el de quien lo llamo. Medido el 2026-08-20: con la
# consola dentro del origen, la copia en %TEMP% corrio bien y `Move-Item` fallo igual con
# `IOException`, porque el handle que sobraba era el de la consola de arriba. Un hijo no
# puede sacar de ahi a su padre, asi que eso se comprueba y se devuelve dicho -- el error
# crudo de PowerShell no menciona el directorio actual por ningun lado.
#
# El nombre de la copia lleva una huella de la ruta del origen. Dos clones -- o un clon y
# un worktree -- se llaman igual en el ultimo tramo, y sin la huella escribirian el MISMO
# archivo temporal: gana el ultimo, y el otro se muda a donde no era.

    # La confirmacion va aqui, la ultima, y no al principio: preguntar antes de haber
    # pasado los frenos seria pedir permiso para algo que a lo mejor no se puede hacer.
    # Se pide escribir la palabra y no una tecla porque mover un repositorio no es una
    # accion de la que se vuelva con Ctrl+Z.
    if ($Asistido) {
        Write-Host ""
        Di "Se va a MOVER el clon:" 'Yellow'
        Di "  de   $Origen" 'Gray'
        Di "  a    $Destino" 'Gray'
        Write-Host ""
        $respuesta = Read-Host "Escribe SI para continuar (cualquier otra cosa cancela)"
        if ($respuesta.Trim().ToUpperInvariant() -ne 'SI') {
            Di "Cancelado. No se movio nada." 'Yellow'
            exit 0
        }
        Write-Host ""
    }

    $aqui = (Get-Location).Path.TrimEnd('\')
    if ($aqui -eq $Origen -or $aqui.StartsWith("$Origen\", 'OrdinalIgnoreCase')) {
        Di "Tu consola esta DENTRO del clon ($aqui)." 'Yellow'
        Di "Nadie puede renombrar la carpeta en la que estas parado. Sal y repite:" 'Yellow'
        Di "  Set-Location C:\; powershell -NoProfile -ExecutionPolicy Bypass -File $PSCommandPath" 'Cyan'
        exit 1
    }

    $sha = [System.Security.Cryptography.SHA1]::Create()
    $bytes = $sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($Origen.ToLowerInvariant()))
    $huella = ([System.BitConverter]::ToString($bytes) -replace '-', '').Substring(0, 12)
    $copia = Join-Path $env:TEMP "mover-clon-$huella.ps1"

    Copy-Item -LiteralPath $PSCommandPath -Destination $copia -Force
    Set-Location $env:TEMP

    $argumentos = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $copia,
                    '-Origen', $Origen, '-Destino', $Destino, '-YaFuera')
    # `-Asistido` NO se reenvia, y es deliberado: la medida, los frenos y la
    # confirmacion ya ocurrieron aqui arriba. La copia de %TEMP% solo mueve. Pasarselo
    # volveria a preguntar, esta vez sin nadie mirando la respuesta.
    if ($AunConEntornos) { $argumentos += '-AunConEntornos' }
    if ($AunConVSCode) { $argumentos += '-AunConVSCode' }

    & powershell @argumentos
    $codigo = $LASTEXITCODE
    Remove-Item -LiteralPath $copia -Force -ErrorAction SilentlyContinue
    exit $codigo
}

# ----------------------------------------------------------------------------- la mudanza

Move-Item -LiteralPath $Origen -Destination $Destino -ErrorAction Stop

Di "MOVIDO -> $Destino" 'Green'
Write-Host ""
if ($AunConEntornos -and $entornos.Count -gt 0) {
    Di "Los $($entornos.Count) entornos que venian dentro estan ROTOS. Rehazlos:" 'Yellow'
    Di "  py -3 aplicaciones\_comun\gestor.py instalar --recrear --app aplicaciones\<carpeta>" 'Yellow'
    Write-Host ""
}
Di "Abre VS Code en $Destino y corre /instalar-local" 'Cyan'
