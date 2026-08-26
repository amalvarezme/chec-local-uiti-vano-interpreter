"""Las palabras que en castellano SIEMPRE llevan tilde, y la guarda que lo obliga.

Este modulo existe porque la revision de ortografia era una recomendacion y no un
mecanismo. Un agente lo dejo dicho por escrito en una corrida real: *"el validador no
revisa ortografia ni acentos: la primera version paso con 'Diagnostico historico'"*. Con
la revision como consejo, el informe gerencial del grupo Riesgo Alto salio con 43
apariciones de prosa sin tilde -- `vegetacion` 8 veces, `hipotesis` 8, `validacion` 6 --
y ninguna hizo fallar nada.

**El diccionario vive AQUI y no en el skill.** `redaccion-es/assets/revisar.py` lo importa
de este modulo. Tenerlo duplicado fue justo el fallo: la copia del skill tenia 153
palabras y ninguna de las seis del dominio que de verdad fallaron -- `vegetacion`,
`hipotesis`, `proteccion`, `atribucion`, `asociacion`, `topologico` --, asi que el
verificador no podia verlas por mucho que se corriera.

**Los CODIGOS no llevan tilde y no se tocan.** `DURACION`, `PROMEDIO_KWH_TRF` y
`COD_CAUSA` son nombres de columna del dataset: marcarlos obligaria a romper el codigo
para contentar al corrector. La regla es mecanica -- si va en MAYUSCULAS, o lleva `_` o
digitos, es un codigo --, no una lista de excepciones que haya que mantener.

**Lo ambiguo se reporta pero no se decide.** `periodo`/`período`, `calculo`/`cálculo`,
`critica`/`crítica`, `area`/`área` y `campana`/`campaña` son las dos correctas segun el
caso; llevan `None` o simplemente no estan, y la guarda las deja pasar. Corregirlas a
ciegas cambia el significado.

**La enye no es una tilde.** `_sin_tildes` quitaba toda marca combinante, asi que `ñ` se
descomponia en `n` + virgulilla y la perdia. Como esa funcion es la que decide si una
palabra "ya lleva tilde", TODA palabra con enye se saltaba entera: `añadira` y `señalo` no
se revisaban nunca por la tilde que de verdad les faltaba. Ahora solo se quita la tilde
aguda (U+0301), que es la que acentua.

**El glosario exime al codigo; no tapa a la palabra.** `duracion` en minusculas dentro de
una frase no se marcaba nunca porque `DURACION` es una columna. El token se juzga por como
esta ESCRITO: en mayusculas y en el glosario es la columna, en minusculas es castellano.

Los dos defectos salieron de la misma corrida (`/informe-gerencial todos`, 2026-08-26): 36
agentes pasaron la guarda en verde y aun asi tuvieron que revisarse la prosa a mano, cada
uno cazando entre 1 y 12 palabras que esta guarda no habia visto.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

__all__ = [
    "SIEMPRE_CON_TILDE",
    "es_codigo",
    "TONICOS",
    "errores_de_tilde",
    "palabras_sin_tilde",
]


SIEMPRE_CON_TILDE: dict[str, str | None] = {
    'acompana': 'acompaña',
    'acompanada': 'acompañada',
    'acompanadas': 'acompañadas',
    'acompanado': 'acompañado',
    'acompanados': 'acompañados',
    'acompanamiento': 'acompañamiento',
    'acompanan': 'acompañan',
    'acompanando': 'acompañando',
    'acompanar': 'acompañar',
    'ademas': 'además',
    'adonde': None,
    'afectacion': 'afectación',
    'agrupacion': 'agrupación',
    'ahi': 'ahí',
    'algun': 'algún',
    'alli': 'allí',
    'ambito': 'ámbito',
    'anade': 'añade',
    'anadieron': 'añadieron',
    'anadir': 'añadir',
    'analisis': 'análisis',
    'ano': 'año',
    'anos': 'años',
    'aplicacion': 'aplicación',
    'aqui': 'aquí',
    'area': None,
    'areas': None,
    'asi': 'así',
    'asignacion': 'asignación',
    'asociacion': 'asociación',
    'atencion': 'atención',
    'atmosferica': 'atmosférica',
    'atmosfericas': 'atmosféricas',
    'atmosferico': 'atmosférico',
    'atras': 'atrás',
    'atribucion': 'atribución',
    'aun': None,
    'automatica': 'automática',
    'automatico': 'automático',
    'caida': 'caída',
    'calculo': None,
    'categoria': 'categoría',
    'clasificacion': 'clasificación',
    'climatica': 'climática',
    'climatico': 'climático',
    'climaticos': 'climáticos',
    'codigo': 'código',
    'combinacion': 'combinación',
    'comparacion': 'comparación',
    'comprobacion': 'comprobación',
    'computacion': 'computación',
    'comun': 'común',
    'concentracion': 'concentración',
    'condicion': 'condición',
    'conexion': 'conexión',
    'configuracion': 'configuración',
    'construccion': 'construcción',
    'contribucion': 'contribución',
    'contribuyo': 'contribuyó',
    'coordinacion': 'coordinación',
    'correlacion': 'correlación',
    'criterio': None,
    'critica': None,
    'criticas': None,
    'critico': 'crítico',
    'criticos': 'críticos',
    'dano': 'daño',
    'danos': 'daños',
    'deberia': 'debería',
    'debil': 'débil',
    'debiles': 'débiles',
    'definicion': 'definición',
    'desagregacion': 'desagregación',
    'descripcion': 'descripción',
    'despues': 'después',
    'desviacion': 'desviación',
    'deteccion': 'detección',
    'detras': 'detrás',
    'dia': 'día',
    'diagnostico': None,
    'dias': 'días',
    'dimension': 'dimensión',
    'direccion': 'dirección',
    'discusion': 'discusión',
    'diseno': 'diseño',
    'distribucion': 'distribución',
    'documentacion': 'documentación',
    'duracion': 'duración',
    'ejecucion': 'ejecución',
    'electrica': 'eléctrica',
    'electrico': 'eléctrico',
    'electricos': 'eléctricos',
    'encontro': 'encontró',
    'energetica': 'energética',
    'energetico': 'energético',
    'energia': 'energía',
    'energias': 'energías',
    'esta': None,
    'estadistica': 'estadística',
    'estadistico': 'estadístico',
    'estadisticos': 'estadísticos',
    'estan': 'están',
    'estandar': 'estándar',
    'estara': 'estará',
    'estimacion': 'estimación',
    'estres': 'estrés',
    'evaluacion': 'evaluación',
    'evolucion': 'evolución',
    'explicacion': 'explicación',
    'extension': 'extensión',
    'fisica': 'física',
    'fisico': 'físico',
    'formula': 'fórmula',
    'formulas': 'fórmulas',
    'funcion': 'función',
    'generacion': 'generación',
    'geografia': 'geografía',
    'geografico': 'geográfico',
    'geometria': 'geometría',
    'geometrico': 'geométrico',
    'grafica': 'gráfica',
    'graficas': 'gráficas',
    'grafico': 'gráfico',
    'graficos': 'gráficos',
    'habra': 'habrá',
    'haria': 'haría',
    'hipotesis': 'hipótesis',
    'historica': 'histórica',
    'historico': 'histórico',
    'historicos': 'históricos',
    'implementacion': 'implementación',
    'indice': 'índice',
    'indices': 'índices',
    'informacion': 'información',
    'inicializacion': 'inicialización',
    'inspeccion': 'inspección',
    'integracion': 'integración',
    'interaccion': 'interacción',
    'interpretacion': 'interpretación',
    'interrupcion': 'interrupción',
    'interseccion': 'intersección',
    'intervencion': 'intervención',
    'iria': 'iría',
    'iteracion': 'iteración',
    'jamas': 'jamás',
    'linea': 'línea',
    'lineas': 'líneas',
    'logica': None,
    'logico': 'lógico',
    'margenes': 'márgenes',
    'mas': None,
    'maxima': 'máxima',
    'maximas': 'máximas',
    'maximo': 'máximo',
    'maximos': 'máximos',
    'mecanico': 'mecánico',
    'medicion': 'medición',
    'metodo': 'método',
    'metrica': 'métrica',
    'metricas': 'métricas',
    'minima': 'mínima',
    'minimas': 'mínimas',
    'minimo': 'mínimo',
    'minimos': 'mínimos',
    'moviles': 'móviles',
    'ningun': 'ningún',
    'normalizacion': 'normalización',
    'nucleo': 'núcleo',
    'numerica': 'numérica',
    'numerico': 'numérico',
    'numero': 'número',
    'numeros': 'números',
    'opcion': 'opción',
    'operacion': 'operación',
    'optimizacion': 'optimización',
    'parametro': 'parámetro',
    'parametros': 'parámetros',
    'particion': 'partición',
    'patron': 'patrón',
    'penalizacion': 'penalización',
    'pequena': 'pequeña',
    'pequenas': 'pequeñas',
    'pequenisimo': 'pequeñísimo',
    'pequeno': 'pequeño',
    'pequenos': 'pequeños',
    'periodo': None,
    'perturbacion': 'perturbación',
    'poblacion': 'población',
    'podra': 'podrá',
    'podria': 'podría',
    'posicion': 'posición',
    'practica': None,
    'practico': 'práctico',
    'precipitacion': 'precipitación',
    'prediccion': 'predicción',
    'priorizacion': 'priorización',
    'proteccion': 'protección',
    'proximo': 'próximo',
    'quiza': 'quizá',
    'quizas': 'quizás',
    'rafaga': 'ráfaga',
    'rafagas': 'ráfagas',
    'rapido': 'rápido',
    'razon': 'razón',
    'reduccion': 'reducción',
    'regimen': 'régimen',
    'region': 'región',
    'regularizacion': 'regularización',
    'relacion': 'relación',
    'repeticion': 'repetición',
    'representacion': 'representación',
    'resolucion': 'resolución',
    'revision': 'revisión',
    'rotacion': 'rotación',
    'sabria': 'sabría',
    'seccion': 'sección',
    'segun': 'según',
    'seleccion': 'selección',
    'senal': 'señal',
    'senala': 'señala',
    'senaladas': 'señaladas',
    'senalado': 'señalado',
    'senalan': 'señalan',
    'senalando': 'señalando',
    'senales': 'señales',
    'separacion': 'separación',
    'sera': 'será',
    'seran': 'serán',
    'seria': None,
    'simbolo': 'símbolo',
    'simulacion': 'simulación',
    'simultaneamente': 'simultáneamente',
    'sintesis': 'síntesis',
    'sismico': 'sísmico',
    'situa': 'sitúa',
    'situacion': 'situación',
    'supervision': 'supervisión',
    'tamano': 'tamaño',
    'tambien': 'también',
    'taxonomia': 'taxonomía',
    'tecnica': 'técnica',
    'tecnicas': None,
    'tecnico': 'técnico',
    'tecnicos': 'técnicos',
    'telemetria': 'telemetría',
    'tendria': 'tendría',
    'teorico': 'teórico',
    'termica': 'térmica',
    'termico': 'térmico',
    'tipica': 'típica',
    'tipicas': 'típicas',
    'tipico': 'típico',
    'tipicos': 'típicos',
    'todavia': 'todavía',
    'topologia': 'topología',
    'topologica': 'topológica',
    'topologico': 'topológico',
    'trafico': 'tráfico',
    'transicion': 'transición',
    'tras': None,
    'traves': 'través',
    'ultima': 'última',
    'ultimas': 'últimas',
    'ultimo': 'último',
    'ultimos': 'últimos',
    'unica': 'única',
    'unico': 'único',
    'util': 'útil',
    'utiles': 'útiles',
    'validacion': 'validación',
    'variacion': 'variación',
    'vegetacion': 'vegetación',
    'veria': 'vería',
    'verificacion': 'verificación',
    'version': 'versión',
    'via': 'vía',
    'visualizacion': 'visualización'
}


TONICOS: dict[str, str] = {   'como': 'cómo',
    'cual': 'cuál',
    'cuales': 'cuáles',
    'cuando': 'cuándo',
    'cuanta': 'cuánta',
    'cuantas': 'cuántas',
    'cuanto': 'cuánto',
    'cuantos': 'cuántos',
    'donde': 'dónde',
    'que': 'qué',
    'quien': 'quién',
    'quienes': 'quiénes'}


_PALABRA = re.compile(r"\b[a-záéíóúñüA-ZÁÉÍÓÚÑÜ]+\b")

# La unica marca que en castellano senala el ACENTO. La virgulilla de la enye (U+0303) y
# la dieresis de la u (U+0308) tambien son marcas combinantes, pero no acentuan: forman
# otra letra.
_TILDE_AGUDA = "\u0301"


def _sin_tildes(texto: str) -> str:
    """El texto sin sus tildes de acentuacion, conservando la enye y la dieresis.

    Quitaba TODA marca combinante, y ahi `ñ` se descomponia en `n` + virgulilla y perdia la
    virgulilla. La consecuencia no era cosmetica: `palabras_sin_tilde` usa esta funcion para
    decidir si una palabra "ya lleva tilde", asi que cualquier palabra con enye salia
    distinta de si misma y se saltaba entera. `añadira`, `señalo` y `acompañara` no se
    revisaban NUNCA por la tilde que de verdad les faltaba -- la enye les hacia de escudo.
    """
    return unicodedata.normalize(
        "NFC",
        unicodedata.normalize("NFD", texto).replace(_TILDE_AGUDA, ""),
    )


def es_codigo(palabra: str, entorno: str) -> bool:
    """Si este token es un CODIGO del dataset y no prosa castellana.

    Lo que lo decide es el GLOSARIO, no la caja. `DURACION` no lleva tilde porque es una
    columna de la tabla -- esta en `glosario_variables.NOMBRE_NATURAL` --, no porque vaya en
    mayusculas: `GEOMETRIA` tambien va en mayusculas, en el rotulo de una figura, y SI la
    lleva. Una regla que solo mirase la caja tendria que elegir entre romper el codigo que
    lee la columna o dejar los rotulos sin acentuar.

    `entorno` es el texto inmediatamente alrededor: un `_` o un digito pegado delatan que la
    palabra es un TROZO de un codigo compuesto (`PROMEDIO_KWH_TRF` llega partido en tres).

    **El glosario exime al codigo; no tapa a la palabra.** Decidir solo con
    `palabra.upper() in NOMBRE_NATURAL` hacia que `duracion` en minusculas, en mitad de una
    frase, no se marcara nunca -- porque `DURACION` es una columna. El punto ciego alcanzaba
    a cualquier palabra corriente que chocara con un nombre de columna (`tipo`, `conductor`,
    `altura`, `codigo`), y ahi el diccionario ni llegaba a fallar: la guarda se saltaba la
    palabra antes de mirarlo. Lo que decide es como esta ESCRITO el token: en MAYUSCULAS y en
    el glosario es la columna; escrito como castellano es castellano.
    """
    from chec_local_interpreter.glosario_variables import NOMBRE_NATURAL

    if "_" in entorno or any(c.isdigit() for c in entorno):
        return True
    return palabra.isupper() and palabra.upper() in NOMBRE_NATURAL


def _con_la_caja_de(original: str, correcta: str) -> str:
    """La correccion, con la CAJA de la palabra original.

    `Concentracion` al principio de frase se corrige a `Concentración`. Devolver la forma
    del diccionario tal cual -- siempre en minuscula -- convertiria un arreglo de tilde en
    un error de mayuscula, y el corrector introduciria el defecto que viene a quitar.
    """
    if original.isupper():
        return correcta.upper()
    if original[:1].isupper():
        return correcta[:1].upper() + correcta[1:]
    return correcta


def palabras_sin_tilde(texto: str) -> list[tuple[str, str]]:
    """`[(escrita, correcta), ...]` para cada palabra del texto que deba llevar tilde y no
    la lleve.

    Solo mira PROSA. Un token en mayusculas sostenidas o con `_`/digitos es un codigo de
    columna y se atraviesa sin contar; una palabra de grafia ambigua (`None` en el
    diccionario) tampoco se marca, porque las dos formas existen.
    """
    if not isinstance(texto, str):
        return []
    fuera: list[tuple[str, str]] = []
    for m in _PALABRA.finditer(texto):
        palabra = m.group(0)
        # El token COMPLETO en su contexto: `TOT_USUS` llega partido por el `_`, asi que
        # se mira el entorno inmediato para no leer `USUS` como una palabra suelta.
        entorno = texto[max(0, m.start() - 1):min(len(texto), m.end() + 1)]
        if es_codigo(palabra, entorno):
            continue
        if palabra != _sin_tildes(palabra):
            continue  # ya la lleva
        correcta = SIEMPRE_CON_TILDE.get(palabra.lower())
        if correcta is None:
            continue  # no esta, o es ambigua
        fuera.append((palabra, _con_la_caja_de(palabra, correcta)))
    return fuera


def _cadenas(valor: Any):
    """Todas las cadenas que son VALOR dentro de una estructura anidada.

    Las CLAVES se saltan a proposito: una clave es una interfaz, y renombrarla para
    ponerle una tilde rompe a quien la lee.
    """
    if isinstance(valor, str):
        yield valor
    elif isinstance(valor, dict):
        for v in valor.values():
            yield from _cadenas(v)
    elif isinstance(valor, (list, tuple)):
        for v in valor:
            yield from _cadenas(v)


def _identificadores() -> frozenset[str]:
    """Los VALORES que son interfaz y no prosa, asi que no se acentuan.

    `_cadenas` ya se salta las CLAVES por esta misma razon. Un enum cerrado del esquema es
    el mismo caso del otro lado del `:`: `variable_groups_used` solo admite `Proteccion` y
    `Topologia` sin tilde, porque esa cadena viaja como identificador hasta
    `/informe-gerencial`. Leerlas como prosa dejaba al agente sin ninguna forma valida --
    el esquema exigia la que la guarda prohibia -- y ningun hallazgo podia atribuirse a
    esos dos grupos.

    Sale de `NOMBRE_LEGIBLE_GRUPO` y no de una lista copiada aqui: `Fisicas/Electricas`
    pasaba por CASUALIDAD -- los plurales no estan en el diccionario aunque los singulares
    si -- y una entrada nueva lo habria roto sin que nadie tocara esta guarda.
    """
    from chec_local_interpreter.domain_context import NOMBRE_LEGIBLE_GRUPO

    return frozenset(NOMBRE_LEGIBLE_GRUPO)


def errores_de_tilde(data: Any, *, limite: int = 25) -> list[str]:
    """Los defectos de tilde de una respuesta de agente, listos para la lista de errores
    de `validate`.

    Se corta en `limite` para que un fallo masivo no entierre los demas errores del
    validador; el mensaje dice cuantos quedaron fuera.
    """
    identificadores = _identificadores()
    vistos: dict[str, str] = {}
    for texto in _cadenas(data):
        if texto.strip() in identificadores:
            continue
        for escrita, correcta in palabras_sin_tilde(texto):
            vistos.setdefault(escrita, correcta)
    items = sorted(vistos.items())
    errores = [
        f"ortografia: '{escrita}' va con tilde: '{correcta}'"
        for escrita, correcta in items[:limite]
    ]
    if len(items) > limite:
        errores.append(f"ortografia: y {len(items) - limite} palabra(s) mas sin tilde")
    return errores
