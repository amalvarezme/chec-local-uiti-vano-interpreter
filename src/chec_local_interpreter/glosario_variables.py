"""Las variables del dataset, en castellano.

El informe escribia los codigos de columna pelados. En el de DON23L14, `NR_T`
veinticuatro veces y `DDT` veintisiete, sin decir en ningun sitio que son. Quien lo lee
sabe de redes de distribucion; no tiene por que saberse los nombres de columna de este
CSV en particular, y menos los de las series de clima con su rezago pegado.

La forma es `Nombre natural (CODIGO)`. El codigo NO se pierde: es lo que hay que buscar
en el dataset, en el tablero del simulador y en el archivo de seleccion de variables, y
un informe que solo diera el nombre bonito obligaria a traducir de vuelta a mano.

Los nombres no se inventan aqui. Salen de la tabla de variables de
`docs/ContextoProyectoSimuladorCHEC.md`, que es el documento de contexto del proyecto, y
coinciden con los que ya usa el tablero del clima (`src/chec_tableros/clima.py`) para las
dos que ese tablero pinta. Un tercer juego de nombres para las mismas columnas seria
exactamente el problema que este modulo existe para cerrar.

**Los VALORES llevan tilde; los comentarios y los nombres de codigo, no.** El repositorio
escribe sin tildes a proposito, pero esa convencion vale para el CODIGO: estas cadenas se
imprimen tal cual dentro del informe, asi que caen del lado de "lo que llega a la
pantalla". Escritas sin tilde produjeron 22 "vegetacion", 23 "proteccion" y 13
"intervencion" en un informe para operacion. Hay una prueba que lo impide.
"""

from __future__ import annotations

import re

#: Codigo de columna -> nombre en castellano. Las claves van en MAYUSCULAS; la busqueda
#: pliega mayusculas porque la documentacion escribe `TEMP_i` y las features `temp_0`.
NOMBRE_NATURAL: dict[str, str] = {
    # --- Evento, impacto e indicadores ---
    "FECHA": "Fecha de la falla",
    "DURACION": "Duración de la interrupción",
    "UITI": "Usuarios interrumpidos por tiempo de interrupción",
    "UITI_VANO": "UITI atribuido al vano",
    "TOT_USUS": "Usuarios afectados",
    "CNT_TRF": "Transformadores afectados",
    "COD_CAUSA": "Código de causa de la falla",
    "DESC_CAUSA": "Causa de la falla",
    # --- Proteccion y maniobra ---
    "FID_SW": "Equipo de protección del vano",
    "COD_EQ_PROTEGE": "Código del equipo que protege",
    "TIPO": "Tipo de equipo de protección",
    "CNT_VN_SW": "Vanos protegidos por el equipo",
    "T_USUS_EQ_PROT": "Usuarios protegidos por el equipo",
    # --- Topologia ---
    # `CIRCUITO` no entra: su nombre natural ES el codigo, y `Circuito (CIRCUITO)` no
    # traduce nada y ocupa el doble. El glosario solo tiene sentido donde aclara algo.
    "FID_VANO": "Vano",
    "X1": "Coordenada inicial del vano (longitud)",
    "Y1": "Coordenada inicial del vano (latitud)",
    "X2": "Coordenada final del vano (longitud)",
    "Y2": "Coordenada final del vano (latitud)",
    "LVSW": "Distancia del vano al equipo de protección",
    "CNT_VN": "Vanos del circuito",
    "PORC_APORTE_VANO": "Aporte del vano al equipo que lo protege",
    # --- Fisicas y electricas del vano ---
    "FECHA_OPERACION_VANO": "Fecha de energización del vano",
    "LONGITUD": "Longitud del vano",
    "CNT_FASES": "Fases eléctricas del vano",
    "CONDUCTOR": "Material del conductor",
    "CALIBRE_NEUTRO": "Calibre del cable neutro",
    "NG_RED": "Cable de guarda o neutro",
    "PROMEDIO_KWH_VANO": "Energía mensual que circula por el vano",
    "TIPO_TAX": "Taxonomía constructiva del vano",
    # --- Activos: apoyo final y transformador ---
    "COD_APOYO_FIN": "Código del apoyo final",
    "FID_APOYO_FIN": "Apoyo final del vano",
    "PROPIETARIO": "Propietario del apoyo",
    "CLASE": "Clase mecánica del apoyo",
    "ELEMENTO": "Tipo de soporte",
    "NORMA": "Norma de la estructura",
    "ALTURA": "Altura del apoyo",
    "LONG_CRUCETA": "Longitud de la cruceta",
    "CANTIDAD_TIERRA": "Puesta a tierra del apoyo",
    "VAL_CRIT_APOYO": "Criticidad del apoyo",
    "FID_TRAFO": "Transformador del apoyo final",
    "CODIGO": "Código del transformador",
    "CAPACIDAD_NOMINAL": "Capacidad del transformador",
    "CNT_USUS": "Usuarios conectados al transformador",
    "FECHA_OPERACION_TRF": "Fecha de energización del transformador",
    "PROMEDIO_KWH_TRF": "Energía mensual del transformador",
    # --- Entorno y riesgo ---
    "NR_T": "Riesgo por vegetación cercana al vano",
    "DDT": "Densidad de descargas a tierra",
}

#: Las familias de series de clima. Se resuelven aparte porque su codigo lleva el rezago
#: pegado (`temp_0` .. `temp_11`) y el nombre es el mismo para los doce: lo que cambia es
#: cuantas horas antes del evento se midio, y eso ya lo dice el propio codigo.
FAMILIAS_CLIMA: dict[str, str] = {
    "PREP": "Precipitación",
    "CLOUDS": "Nubosidad",
    "VIS": "Visibilidad",
    "WIND_SPD": "Velocidad del viento",
    "WIND_GUST_SPD": "Ráfagas de viento",
    "TEMP": "Temperatura del aire",
    "PRES": "Presión atmosférica al nivel del mar",
    "SP": "Presión atmosférica en superficie",
    "RH": "Humedad relativa",
    "SOLAR_RAD": "Radiación solar",
}

# Un sufijo de rezago es TODO digitos. `X2` y `TIPO_TAX` no son rezagos, y recortarlos
# por el ultimo `_` los volveria `X` y `TIPO` -- y `TIPO` existe como variable aparte.
# Es la misma regla que usa `plegar_rezagos` para plegar el grafo, y tiene que serlo:
# dos criterios distintos de "que es un rezago" separarian el anillo de su leyenda.
#
# La `i` literal se acepta ademas porque es como la DOCUMENTACION nombra a la familia
# entera: `domain.variable_groups` lista `PREP_i` y `TEMP_i`, no los doce rezagos. Sin
# esta rama se colaban sin traducir justo en la lista que el agente recibe.
_REZAGO = re.compile(r"^(?P<familia>.+?)_(?P<indice>\d+|[iI])$")


def nombre_natural(codigo: str) -> str:
    """El nombre en castellano de una columna, o el codigo si no esta en el glosario.

    Devolver el codigo tal cual es deliberado: inventarle un nombre a una columna
    desconocida es peor que mostrarlo, porque el lector no puede distinguir un nombre
    real de uno adivinado.
    """
    if not codigo:
        return ""
    clave = str(codigo).strip()
    directo = NOMBRE_NATURAL.get(clave.upper())
    if directo:
        return directo
    familia = FAMILIAS_CLIMA.get(clave.upper())
    if familia:
        return familia
    coincidencia = _REZAGO.match(clave)
    if coincidencia:
        base = FAMILIAS_CLIMA.get(coincidencia.group("familia").upper())
        if base:
            return base
    return clave


def nombre_con_codigo(codigo: str) -> str:
    """`Nombre natural (CODIGO)`, o solo el codigo cuando no hay nombre que anteponer.

    Sin la segunda rama, una columna fuera del glosario saldria como `X (X)`, que se lee
    como un fallo del informe -- y lo es.
    """
    if not codigo:
        return ""
    clave = str(codigo).strip()
    nombre = nombre_natural(clave)
    return clave if nombre == clave else f"{nombre} ({clave})"
