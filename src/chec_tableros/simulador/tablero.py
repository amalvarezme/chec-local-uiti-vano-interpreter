"""El tablero del simulador de riesgo por vano: la interfaz viva.

`derivacion.py` responde por lo que se calcula una vez y se congela. Aqui vive lo
otro: los ocho paneles, los selectores, el panel de controles y los callbacks que
los atan. Se separan porque tienen ciclos de vida distintos -- la derivacion corre
al CONSTRUIR el paquete y esto corre en CADA apertura, dentro de un kernel vivo.

## Por que es una funcion y no un modulo que se ejecuta

Todo esto vivia en las celdas 8 a 16 del cuaderno 06, y la aplicacion lo servia
parcheando ese `.ipynb` por texto: seis marcas que tenian que aparecer
exactamente una vez, en celdas identificadas por su INDICE. Cambiar una linea del
cuaderno rompia la aplicacion en un sitio que no la mencionaba.

`construir()` recibe lo que distinguia a los dos: de donde salen los datos
derivados y donde estan los tres archivos de catalogo. El cuaderno pasaba
`data/`; la aplicacion pasa su paquete congelado. Nada mas cambiaba entre ellos,
y por eso nada mas es parametro.

## El estado vive en la llamada

Los callbacks son cierres sobre las variables de `construir()`. En el cuaderno
eran globales del kernel -- una sola sesion, un solo tablero --, y aqui son
locales, lo que permite construir dos tableros en el mismo proceso sin que uno le
pise el estado al otro. Es tambien la razon de que los once `nonlocal` de abajo
digan `nonlocal` y no `global`.

## Lo que se muestra, no se decide aqui

`construir()` DEVUELVE el widget; no lo muestra. Quien llama decide si va a un
`display()` de cuaderno o dentro de una pagina de Voila con su barra de cierre --
que entra por `encabezado` y es lo unico que la aplicacion agrega.
"""
from __future__ import annotations

import asyncio
import gc
import os
import time
import warnings
from pathlib import Path

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

try:
    import ipywidgets as widgets
except ImportError as exc:  # pragma: no cover -- entorno sin interfaz
    raise ImportError(
        "El tablero del simulador requiere ipywidgets para su interfaz interactiva."
    ) from exc

from chec_local_interpreter.costos_items import (
    MAX_REPETICIONES,
    costos_de_intervencion,
    leer_catalogo_costos,
)
from chec_local_interpreter.mil_simulador_015 import (
    gates_de_bolsas,
    grafo_diferencia,
    plegar_rezagos,
    relevancia_hacia_uiti_minimo,
    seleccionar_bolsas,
    simular_bolsas,
    trazas_grafo,
    valores_actuales_por_vano,
)
from chec_local_interpreter.simulador_variables import (
    UNIDADES,
    VARIABLE_ENTORNO_RUTA,
    abreviatura,
    barras_uiti_por_vano,
    catalogo_simulacion,
    columnas_panel,
    definicion_de_knob,
    definiciones_de_knobs,
    descripciones_de_variables,
    grupo_por_knob,
    incoherencias_del_catalogo,
    knobs_bloqueados,
    knobs_simulables,
    rotacion_radial,
    rotulo_y_posicion,
)
from chec_local_interpreter.vano_app_015 import (
    DEBOUNCE_SEGUNDOS,
    ESTADO_BASE,
    ESTADO_SIMULADO,
    aplicar_si_vigente,
    clases_por_fid_para_estado,
    siguiente_epoca,
)
from chec_local_interpreter.vano_controls import expand_knob_overrides
from chec_local_interpreter.vano_widgets import (
    MAX_VANOS_ANALISIS,
    VANOS_POR_PAGINA,
    construir_selector_casillas,
    construir_selector_vanos,
    figura_de_mapas,
    widget_for_knob,
)
from chec_local_interpreter.ventanas_015 import (
    CAMBIO_EMPEORA,
    CAMBIO_IGUAL,
    CAMBIO_MEJORA,
    CAMBIOS,
    bounds_de_fids,
    cajas_por_cambio_de_grupo,
    cajas_seleccion_por_clase,
    capas_mapa_historico,
    centro_y_zoom,
    clases_de_series,
    construir_hist_class_cache,
    construir_mask_cache,
    fid_de_punto,
    perfil_uiti_por_vano,
    series_temporal_vanos,
    top_vanos_de_ventana,
    vanos_para_diagnostico,
    ventanas_sin_traslape,
)

RAIZ_REPO = Path(__file__).resolve().parents[3]
DATOS = RAIZ_REPO / "data"

# Los tres archivos de catalogo, en su sitio del repositorio. La aplicacion pasa
# los suyos -- copias congeladas dentro de `paquete/` -- y por eso son parametros
# con valor por defecto y no constantes: era exactamente esto lo que los parches
# de texto de `preparar.py` reescribian celda por celda.
COSTOS_POR_DEFECTO = DATOS / "Actividades_mantenimiento_costos_2026.xlsx"
VARIABLES_SELECCION_POR_DEFECTO = DATOS / "Variables_seleccion.xlsx"
VARIABLES_SIMULAR_POR_DEFECTO = DATOS / "Variables_simular.xlsx"


# --------------------------------------------------------------------------------
# Lo que le da forma al tablero sin ser un dato
# --------------------------------------------------------------------------------
# De aqui abajo, y dentro de `construir()`, los comentarios vienen LITERALES del
# cuaderno 06 y por eso dicen "este cuaderno", "01.4" o "la celda del panel". Se
# conservan tal cual a proposito: son mediciones y decisiones concretas -- contrastes
# contra el fondo del mapa, anchos de trazo comparables entre tableros, por que una
# capa va debajo de las trazas -- y reescribir 3.600 lineas de prosa para cambiarle
# el sustantivo es la forma de perder alguna por el camino. Donde dice "cuaderno",
# leer "tablero".
# --------------------------------------------------------------------------------


# Misma paleta que 01.4: los grupos historicos de este cuaderno SON los de 01.4, nunca se
# reajustan, asi que el color tiene que significar lo mismo en los dos cuadernos.
NOMBRES_GRUPOS = ['Bajo', 'Medio', 'Medio-Alto', 'Alto']
# Semaforo: verde Bajo, amarillo Medio, naranja Medio-Alto, rojo Alto. Antes era una
# rampa de rojos, que ordenaba por SATURACION: `Bajo` y `Medio` eran dos rosas que solo
# se distinguian mirandolos uno al lado del otro, y en el mapa el mas claro quedaba a un
# paso del fondo. El semaforo ordena por TONO, que es lo que se lee de un vistazo y sin
# tener la leyenda al lado.
# Contraste medido contra el fondo de carto-positron (#f2f0eb): 3,36 / 1,48 / 2,71 / 4,94.
# El amarillo es el mas flojo de los cuatro, pero el peor caso NO empeora -- el `Bajo`
# salmon de la rampa vieja medía 1,44 --, y oscurecerlo mas lo acerca al naranja hasta
# volver indistinguibles los dos niveles del medio.
# En formato `rgb(...)` y no hexadecimal a proposito: el relleno de los violines y de los
# contornos sale de `.replace('rgb', 'rgba')`, que sobre un hex no encuentra nada y deja
# el relleno sin aplicar, en silencio.
COLORES_GRUPOS = ['rgb(26,150,65)', 'rgb(242,194,0)', 'rgb(239,108,0)', 'rgb(198,40,40)']
# UN solo codigo de ausencia en los DOS mapas: negro, el `COLOR_SIN_EVENTO` de 01.4.
# El vano sin eventos en la ventana no tiene clase, y la ausencia no es la clase mas baja;
# que el base lo pintara gris y el simulado negro obligaba a recordar dos codigos para la
# misma cosa. Los cuatro colores KMeans significan lo mismo en los dos mapas.
COLOR_SIN_EVENTO = 'rgb(0,0,0)'
# La otra ausencia, la del punto de la serie y la del recuadro de un vano marcado sin
# celda en la ventana: no tiene grupo, y eso tampoco es el grupo mas bajo. Gris, fuera de
# la escala de criticidad. Vive AQUI, junto a `COLOR_SIN_EVENTO`, y no abajo entre los
# colores de las barras: los dos codifican lo mismo -- que no hay dato -- y separarlos era
# lo que dejaba al recuadro sin poder citarlo.
COLOR_SIN_GRUPO = '#94a3b8'
COLOR_MARCADO = '#0072b2'
# Equipos: mismos colores que 01.4, por el mismo motivo que la paleta de grupos --
# un naranja tiene que seguir siendo un transformador al pasar de un cuaderno a otro.
# Estilo del mapa, TOMADO DEL CUADERNO 01 (`01_uiti_vano_clima`, celda 4). Los cuatro
# mapas del proyecto dibujan los mismos objetos sobre la misma geografia, asi que un
# transformador, un vano con eventos y uno sin ellos tienen que medir lo mismo en todos:
# de otro modo el mismo circuito se lee como dos circuitos distintos al pasar de cuaderno.
# 01 subio los equipos de 6/5 a 14/12 px y la capa de vano de 3.5 a 7.0 px cuando su figura
# doblo de alto; aqui se adoptan esos valores, que es lo que hace comparables los mapas.
# Contrapartida: este mapa es mas bajo que el de 01, asi que el mismo trazo pesa mas sobre
# el. Se asume: la comparacion entre cuadernos vale mas que el equilibrio de cada uno.
COLOR_TRAFO = '#f59e0b'
COLOR_SWITCH = '#7c3aed'
TAM_TRAFO = 14
TAM_SWITCH = 12
ANCHO_MAPA = 7.0                 # vano CON eventos (o CON clase simulada)
# El vano SIN celda en la ventana baja a la linea de estructura de 01. Antes se dibujaba
# igual de gruesa que un vano con eventos y solo cambiaba de color, asi que la ausencia de
# dato competia en peso visual con el dato -- que es justo lo contrario de lo que dice.
ANCHO_SIN_EVENTOS = 1.5
ANCHO_MAPA_MARCADO = round(ANCHO_MAPA * 1.4, 2)

# Fila 1, paridad 01.4: un vano MARCADO se dibuja con el color de SU clase, sobre un halo
# blanco que lo despega del fondo (01.4: `width=ANCHO_MAPA_RESALTE * 2.6, color='white'`).
# Un color plano de "seleccionado" encima de la clase congela lo que se ve: la ventana
# cambia la clase por debajo y el vano marcado sigue igual en pantalla. COLOR_MARCADO
# queda solo para la fila 2, donde la clase la pone el modelo y no el KMeans.
COLOR_HALO = 'white'
ANCHO_HALO = round(ANCHO_MAPA_MARCADO * 2.6, 2)
# El vano SELECCIONADO se encierra ademas en una caja amarilla translucida, GIRADA a la
# inclinacion del propio vano. El halo blanco y el ancho extra lo separan de su vecino
# inmediato, pero no lo hacen ENCONTRABLE en un circuito de cientos de tramos; una caja
# si, y sigue siendo una caja a cualquier zoom, donde una linea deja de distinguirse de
# las de al lado.
# El giro no es cosmetica: con el rectangulo min/max, el grosor del resalte dependia del
# rumbo y del largo del vano. Medido sobre los 59.776 tramos, la caja de ejes es 1,3 veces
# mas gorda que la banda a traves del trazo en la mediana, 4 veces en el p90 y 169 veces
# en el peor caso, y el 52,8% de los tramos corre en diagonal. La misma marca se veia como
# una funda ajustada sobre un vano norte-sur y como un parche suelto sobre uno diagonal.
# Va por `layout.map.layers` con `below='traces'` y NO como traza. Las dos cosas importan:
# una traza rellena por encima se comeria el clic -- que es justo lo que alterna la
# seleccion -- y ademas tiniria la linea del vano, borrando el color de su clase. Debajo
# de las trazas, la caja rodea al vano y la clase se sigue leyendo.
#
# El relleno lleva el color del GRUPO KMeans del propio vano, no un rojo de acento. El
# rojo contestaba "esto es lo que estoy mirando", y esa pregunta ya la contestan el halo
# blanco y el trazo un 40% mas ancho de la linea. Con el color del grupo, el recuadro
# contesta ademas en que nivel de criticidad cayo -- la misma lectura que su linea, pero
# en una mancha de ~50 m de lado que se sigue viendo al zoom en que la linea deja de
# distinguirse de sus vecinas.
#
# Al 50%: por debajo el verde `Bajo` se pierde contra el fondo de carto-positron, y por
# encima el relleno compite con la linea que esta senialando.
COLORES_CAJA_SELECCION = list(COLORES_GRUPOS)
# El vano marcado que en ESTA ventana no tiene celda no tiene grupo, y eso no es el grupo
# mas bajo: es la ausencia del dato. Lleva el mismo gris con que la serie de tiempo pinta
# sus puntos sin celda, para que "sin grupo" se diga igual en los dos paneles.
COLOR_CAJA_SIN_CLASE = COLOR_SIN_GRUPO
OPACIDAD_CAJA_SELECCION = 0.5
# El recuadro del mapa SIMULADO sale de la MISMA geometria, asi que hereda la inclinacion
# sin codigo aparte: los dos mapas tienen que encerrar el mismo vano con el mismo
# rectangulo, y dos formas distintas se leerian como dos vanos. No contesta "cual estoy
# estudiando" -- eso ya lo dice el del mapa base, con el mismo vano encerrado a la
# izquierda -- sino QUE LE PASO al vano:
# verde claro si bajo de grupo de criticidad, amarillo si se quedo en el mismo, rojo si
# subio. Son TRES capas y no una porque una capa de `layout.map.layers` pinta con UN color.
# El amarillo de "no cambio" ya NO se hereda de la caja de seleccion: esa paso a roja, y
# heredarla dejaria a "se quedo igual" del mismo color que "subio de grupo", que es la
# lectura contraria. Cada mapa contesta una pregunta distinta -- el base "cual elegi", el
# simulado "que le paso" -- asi que sus colores dejan de estar atados.
COLOR_CAJA_MEJORA = '#4ade80'
COLOR_CAJA_IGUAL = '#ffd400'
COLOR_CAJA_EMPEORA = '#dc2626'
# Lado minimo de la caja, en grados (~50 m a esta latitud). A TRAVES del trazo la caja
# nace de ancho CERO -- una linea no tiene grosor --, y cero pixeles de ancho no se ve.
# Con la caja girada este es el ancho de la banda en TODOS los vanos, no solo en los que
# corrian sobre un eje.
LADO_MINIMO_CAJA = 0.00045
# Margen a cada lado (~10 m): sin el, el borde de la caja cae encima del trazo del vano y
# no se distingue cual es cual.
MARGEN_CAJA = 0.00009
OPACIDAD_NUBE = 0.45               # 01.4, para que la nube de fondo no tape el resaltado
OPACIDAD_FRONTERA = 0.28           # 01.4: el contorno es fondo, no dato
# Paleta de 01.4 para las series por vano: apta para daltonismo y distinta de la escala de
# grupos, porque aqui el color identifica AL VANO, no a su clase.
# QUINCE colores, uno por cupo de vano: el tope subio a quince con el diagnostico, y
# `COLORES_VANOS[_s]` se indexa con el cupo, asi que una lista mas corta que el tope no
# es un color repetido sino un IndexError al construir la figura. Los seis primeros son
# los de 01.4 y no se tocan: un vano que era azul en un cuaderno tiene que seguir siendo
# azul en el otro. Los nueve siguientes se eligen lejos de esos seis y entre si -- los
# cinco ultimos se separan ademas por CLARIDAD de su pariente mas cercano (#b2df8a
# contra #009e73, #b39ddb contra #6a3d9a) --, porque el color aqui identifica AL VANO y
# dos parecidos serian dos series indistinguibles.
COLORES_VANOS = ['#0072b2', '#009e73', '#cc79a7', '#56b4e9', '#e69f00', '#8c564b',
                 '#d55e00', '#6a3d9a', '#17becf', '#666666',
                 '#b2df8a', '#bcbd22', '#004949', '#920000', '#b39ddb']
# Cuantas barras lleva cada grupo del top por vano. DIEZ y no cinco: el barrido puntua
# trece variables numericas y cortar en cinco dejaba fuera de la vista mas de la mitad del
# ranking que ya se calculo -- las pasadas del modelo son las mismas, solo cambia cuantas
# se muestran. Lo que el cinco protegia era el rotulo escrito dentro de la barra, y de eso
# se encarga ahora la cascada resumen -> inicial -> nada de
# `simulador_variables.rotulo_en_barra`, que decide barra por barra segun lo que mida.
TOP_VARIABLES_POR_VANO = 10
# Cuantos valores se prueban de cada control al buscar el que MINIMIZA el UITI del vano.
# Nueve y no dos: medido sobre el modelo real, 10 de los 15 controles numericos tienen su
# mejor valor en el INTERIOR del rango para alguna bolsa -- `DDT` para todas --, asi que
# mirar solo los extremos muestrea los dos puntos equivocados. Nueve puntos son 136
# pasadas de bolsas para toda la seleccion, medidas en 0,2 s.
PUNTOS_REJILLA_RELEVANCIA = 9
# El TOPE del diagnostico: cuantos vanos entran como maximo a una corrida. Quince y no
# diez porque es lo que cabe en una orden de trabajo de una jornada, y porque el
# diagnostico ya no elige solo -- parte de lo que el usuario marco, y un tope corto le
# dejaba poco sitio al relleno. Es el MISMO numero que `MAX_VANOS_ANALISIS`: el
# diagnostico marca los vanos que identifica, asi que un tope mayor que el del selector
# se recortaria en silencio al escribirlos.
TOP_VANOS_CIRCUITO = 15
# Ya no hay filtro por grupo de criticidad. El diagnostico mira TODOS los vanos con
# eventos en la ventana y los ordena por UITI, que es lo que ordena la urgencia. El
# filtro anterior -- Alto primero, Medio-Alto para completar -- dejaba fuera vanos con
# eventos y UITI alto solo porque su celda cayo del otro lado de una frontera KMeans, y
# eso es una decision de la geometria de 01.4 y no de la urgencia de la obra. El grupo
# sigue reportandose por vano en la tabla, que es donde sirve para leer.
# Sin tope. La pregunta del diagnostico es que hace falta para bajar a grupo Bajo, y un
# corte fijo la contestaba a medias: si el vano necesita siete palancas, cinco no lo bajan
# y la tabla no dejaba ver las dos que faltaban. `None` = todas las que tengan efecto; las
# de caida cero se siguen descartando, porque una variable que no mueve el UITI no es una
# variable necesaria sino ruido en la tabla.
TOP_INTERVENCION_CIRCUITO = None
TOP_ESCENARIO_CIRCUITO = None
# Fuente del rotulo dentro de la barra. Los anchos de caracter con los que
# `rotulo_en_barra` decide si el nombre cabe estan MEDIDOS a este tamanio
# (`simulador_variables.TAM_FUENTE_MEDIDO`): cambiarlo aqui sin volver a medir en el
# modulo deja al panel decidiendo con numeros de otra fuente.
TAM_FUENTE_BARRA = 8
# La fuente de los nombres de nodo del grafo. Manda el ESPACIO: son 66 nombres alrededor
# del anillo, y el arco disponible para cada uno es 2*pi*radio/66. Con el grafo en las
# columnas 2-3 el radio ronda los 150 px, o sea 14 px de arco por nombre: a 14 se tocan y
# a 10 caben. Ademas el largo del rotulo decide el RANGO del eje -- y con el, cuanto del
# panel le queda al circulo --, asi que bajarla agranda el grafo dos veces.
TAM_FUENTE_NODO = 10
# Como se llama cada familia de rezagos en el anillo. Los nombres son los MISMOS que usa
# la tabla del diagnostico -- "Viento (12 lags)" y companiia --, asi que `abreviatura`
# los reconoce y el lector no tiene que aprender dos vocabularios para la misma variable.
NOMBRE_DE_FAMILIA = {
    'temp': 'Temperatura (12 lags)',
    'prep': 'Precipitacion (12 lags)',
    'wind_spd': 'Viento (12 lags)',
    'wind_gust_spd': 'Rafaga de viento (12 lags)',
}
# El punto de la VENTANA VIGENTE en las dos series se dibuja al triple, como el dia
# vigente en la serie del cuaderno 01. `marker.size` es un ARRAY por eso: mover el
# deslizador solo reescribe ese arreglo y el punto grande viaja con el.
SERIE_TAM_UITI = 9
SERIE_TAM_EVENTOS = 8
FACTOR_PUNTO_ACTIVO = 3
# Las dos barras de la fila 4. NO son la misma cantidad medida dos veces: la gris es lo
# que dice la base de datos y la azul es lo que predice el modelo. Ver `_pintar_barras_uiti`
# -- el color separa medicion de prediccion, y por eso no comparten paleta con los grupos.
# Colores fuera de la escala de criticidad a proposito -- aqui el color distingue dos
# CORRIDAS, no dos niveles, y reusar la paleta de grupos invitaria a leerlos como clases.
COLOR_BARRA_MEDIDA = '#94a3b8'
COLOR_BARRA_SIMULADA = '#0072b2'
# A que distancia del centro se planta el rotulo de cada nodo del grafo. Los nodos viven
# sobre el circulo de radio 1; 1,05 despega el texto de su propio marcador sin alejarlo
# tanto como para que deje de leerse como suyo.
RADIO_ROTULO_GRAFO = 1.05
# La fila del costo de intervencion. El azul identifica a un VANO, igual que en las
# series; el gris oscuro es el TOTAL, que no es un vano mas sino la suma de todos y por
# eso no comparte su color. Ninguno de los dos toca la paleta de criticidad: aqui se
# miden pesos, no riesgo, y un rojo aqui se leeria como un grupo.
COLOR_BARRA_COSTO = '#0072b2'
COLOR_BARRA_TOTAL = '#5b4a48'
# El perfil del circuito lleva UN color plano y no la rampa de posicion del top de
# variables: alli la rampa separa diez barras que miden lo mismo, y aqui el LARGO de
# la barra ya dice la posicion. Una rampa encima seria el mismo dato dos veces. Se
# elige el rojo de acento del tablero -- el del borde del panel y el del deslizador --
# porque el perfil es historia MEDIDA, del mismo lado que el mapa de la izquierda, y
# no una prediccion: el azul de `COLOR_BARRA_SIMULADA` lo leeria como simulado.
COLOR_BARRA_PERFIL = 'rgb(203,24,29)'
# Cuantos vanos entran al perfil del circuito. Quince es el mismo numero que
# `TOP_VANOS_CIRCUITO`, y a proposito NO es la misma constante: aquel es el tope de
# una corrida del diagnostico y este es cuantas barras se leen de un vistazo. Que
# coincidan hoy no es razon para que uno arrastre al otro maniana.
TOP_VANOS_PERFIL = 15
# Cuantos vanos se marcan SOLOS al mover el deslizador: los de mayor UITI en esa ventana.
# Mover la ventana cambia el sujeto -- los vanos que fallaron en marzo no son los de abril
# --, y dejar la marca anterior deja al mapa, a la serie y al ranking describiendo vanos
# que en esta ventana no tienen ni una celda. Es un REEMPLAZO y no una suma: acumular
# ventanas terminaria con todo lo que alguna vez tuvo un evento marcado a la vez.
# Quince, el mismo numero que el perfil y que el diagnostico, porque las tres listas
# contestan la misma pregunta sobre distintos periodos y tres topes distintos obligarian a
# recordar cual manda en cada panel.
TOP_VANOS_VENTANA = 15
# Cuantas series de tiempo caben dibujadas a la vez. Es el DOBLE del tope de la
# auto-marca, y esa holgura es justo lo que hace falta: la ventana marca hasta quince y el
# usuario puede seguir agregando vanos con la casilla o tocandolos en el mapa, sin que el
# tope de la auto-marca sea tambien un tope para el. Las trazas se crean vacias al armar
# la figura, asi que las que sobran no cuestan datos, solo su ranura.
# Treinta y no ilimitado porque el numero de trazas de un `FigureWidget` se fija al
# construirlo: crecerlo en vivo obligaria a agregar trazas despues del `display`, que es
# justo el camino por el que el tablero se queda en blanco. Pasado ese tope el panel lo
# DICE (ver `_actualizar_aviso_vanos`); lo que no hace es recortar en silencio.
MAX_VANOS_SERIE = 2 * MAX_VANOS_ANALISIS
ETIQUETA_TOTAL = 'TOTAL'
# Un boton "i" por actividad, o solo el detalle al posar el mouse.
#
# Medido: con las 142 actividades del contrato, un boton por renglon suma 285 widgets
# -- el boton y la caja que lo empareja con su casilla --, y el tablero pasa de ~300 a
# 585. En JupyterLab eso no se nota; el visor de VS Code es mas fragil y ese salto
# coincide con que el tablero dejara de montarse alli.
#
# En False el detalle sigue estando: viaja como `title` de cada casilla, que el
# navegador muestra al posar el mouse y NO cuesta un solo widget. Se pierde el clic,
# no la informacion. Las 18 variables del simulador conservan su boton en los dos
# modos: dieciocho botones no son un problema de volumen.
BOTONES_INFO_ACTIVIDADES = True

# Ancho de la casilla de cada actividad del contrato. Los nombres del contrato son
# largos -- mediana de 63 caracteres, maximo 143 -- asi que el rotulo arranca por el
# PRECIO: es el dato con el que se elige, y puesto al final lo recortaria el ancho fijo.
ANCHO_CASILLA_ITEM = '580px'

# Paleta de los MODOS de variable en el grafo. Deliberadamente fuera de la familia de los
# grupos KMeans (rojos/naranjas) y de los equipos: un rojo en el mapa y un rojo en el grafo
# significarian cosas sin ninguna relacion. Se recorre en el orden de las modalidades del
# artefacto.
PALETA_MODALIDADES = ['#0d9488', '#be185d']   # verde azulado y rosa oscuro

# Guion horizontal negro en cada extremo de CADA vano, tenga o no eventos, igual que el
# mapa de 01: grados de longitud a cada lado del extremo (~14 m a esta latitud). Marca
# donde empieza y donde termina un vano, que es lo unico que distingue dos vanos vecinos
# dibujados con el mismo color.
MARCA_VANO = 0.00013
# Densificacion del hover del mapa: el hover de una traza de lineas en Scattermap se
# resuelve contra los VERTICES y no contra la linea, y los tramos de MVLINSEC traen
# exactamente dos. Sin esto el centro de un vano largo no muestra etiqueta y, como Plotly
# solo convierte un clic en evento donde hay hover, tampoco se puede marcar tocandolo ahi.
PASO_VERTICE = 0.00022      # grados ~= 25 m a esta latitud


def construir(
    derivado,
    *,
    costos: Path | str | None = None,
    variables_seleccion: Path | str | None = None,
    encabezado=(),
):
    """Arma el tablero completo sobre un `Derivado` y lo devuelve.

    `derivado` sale de `derivacion.derivar()` (camino caro) o de
    `derivacion.cargar(paquete)` (camino barato). Los dos devuelven el mismo
    objeto, asi que desde aqui no se sabe -- ni hace falta saber -- cual corrio.

    `encabezado` son widgets que se pintan ARRIBA del tablero, del ancho
    completo. La aplicacion mete ahi su barra de cierre; nadie mas mete nada. Va
    como parametro y no como una bandera `es_aplicacion` porque lo que cambia
    entre los dos no es un modo: es un widget.

    El tercer catalogo -- `Variables_simular.xlsx` -- NO entra por aqui. Ver el
    comentario junto a `catalogo_simulacion()` mas abajo: la biblioteca lo
    resuelve por su cuenta desde el entorno, y un parametro seria una segunda
    fuente que tendria que coincidir con la primera.
    """
    costos = COSTOS_POR_DEFECTO if costos is None else Path(costos)
    variables_seleccion = (VARIABLES_SELECCION_POR_DEFECTO if variables_seleccion is None
                           else Path(variables_seleccion))
    encabezado = list(encabezado)

    # --- UN solo modelo: el MIL por bolsas del cuaderno 05 (cierra el SEAM D1) ------------
    # El tablero entero -- mapa "Criticidad Simulada", grafo reconstruido e "Importancia
    # Variables" -- responde a este modelo y a esta unidad: la BOLSA (vano x ventana), que es
    # la unidad en la que 04 define la criticidad.
    #
    # Las tres guardas que hacian comparables los dos mapas -- geometria del modelo contra la
    # versionada, ejes logaritmicos, y que las features del MIL empiecen por las de MGCECDL --
    # corren dentro de `derivacion.derivar()`. Estan alli y no aqui porque tambien tienen que
    # proteger al constructor del paquete, que ya no ejecuta esta celda.
    X_INST, FEATURES_MIL, BAG_INDEX, MIL = (derivado.x_inst, derivado.features_mil,
                                            derivado.bag_index, derivado.mil)

    # Los MODOS de variable con los que el modelo agrupa las columnas -- son los mismos que
    # usa la fusion FiLM (el clima reescala lo estructural), asi que colorear los nodos del
    # grafo por modalidad muestra exactamente la particion que el modelo usa por dentro.
    COLUMNAS_MODALIDAD = {m: set(int(i) for i in idx)
                          for m, idx in MIL.model.base.modality_feature_indices.items()}
    MODALIDADES_MIL = list(COLUMNAS_MODALIDAD)
    if len(MODALIDADES_MIL) != len(PALETA_MODALIDADES):
        raise ValueError(
            f'El artefacto trae {len(MODALIDADES_MIL)} modalidades y la figura tiene '
            f'trazas de nodo para {len(PALETA_MODALIDADES)}: agrega la traza que falta '
            'antes de seguir.')
    COLORES_MODALIDAD = dict(zip(MODALIDADES_MIL, PALETA_MODALIDADES))

    # --- Lo que se deriva de la tabla, que es barato y no vale la pena congelar ----------
    # `VENTANAS`, `TABLA` y las trazas de mapa vienen del arranque; los caches y los indices
    # de abajo se recalculan en cada apertura porque son milisegundos sobre objetos que ya
    # estan en memoria.
    VENTANAS, TABLA = derivado.ventanas, derivado.tabla
    mask_para = construir_mask_cache(TABLA)
    clases_para = construir_hist_class_cache(TABLA, mask_para)

    CIRCUITOS = sorted(TABLA['CIRCUITO'].astype(str).unique())
    VANOS_POR_CIRCUITO = {
        c: sorted(g['FID_VANO'].unique().tolist())
        for c, g in TABLA.groupby(TABLA['CIRCUITO'].astype(str))
    }
    # Las ventanas en que ESE circuito registro al menos un evento. No son las once para
    # todos: un circuito tranquilo puede no tener una sola celda en media ventana del ano, y
    # el deslizador lo llevaba igual hasta ahi -- a un mapa sin un solo tramo de color, que se
    # lee como que el tablero se rompio y no como que no hubo eventos.
    VENTANAS_POR_CIRCUITO = {
        c: sorted(int(i) for i in g['ventana_i'].unique())
        for c, g in TABLA.groupby(TABLA['CIRCUITO'].astype(str))
    }


    # Geometria FISICA de cada vano (no confundir con la geometria KMeans): sale del mismo
    # shapefile y del mismo join que el mapa de 01.3/01.4, ya reducida a listas de coordenadas
    # redondeadas a cinco decimales. Los 180 MB de shapefile no vuelven a abrirse.
    GEO_POR_CIRCUITO, TRAFOS, SWITCHES = (derivado.geo_por_circuito, derivado.trafos,
                                          derivado.switches)

    # UITI y eventos por vano y ventana: solo alimentan el hover, igual que 01.4. El grupo
    # NO se guarda aqui -- sale de `clases_para`, que es la unica fuente de clases.
    DATOS_VENTANA = [{} for _ in VENTANAS]
    for _fid, _vi, _u, _n in zip(TABLA['FID_VANO'], TABLA['ventana_i'],
                                 TABLA['uiti_acumulado'], TABLA['num_eventos']):
        DATOS_VENTANA[int(_vi)][str(_fid)] = (float(_u), int(_n))

    gc.collect()

    label_encoders = derivado.label_encoders
    max_values_imputed = derivado.max_values_imputed
    KNOBS = derivado.knobs

    # UNA sola fuente para el catalogo de variables simulables, y es la variable de
    # entorno. Un parametro aqui seria una SEGUNDA: `widget_for_knob` consulta el
    # catalogo por su cuenta al pintar cada control (`simulador_variables.py:522`,
    # sin ruta), asi que un archivo pasado por argumento y otro en el entorno
    # pintarian el panel con un catalogo y lo simularian con el otro.
    # `setdefault` y no asignacion: la aplicacion servida ya apunto su copia
    # congelada antes de llamar, y pisarla la mandaria a leer `data/`.
    os.environ.setdefault(VARIABLE_ENTORNO_RUTA, str(VARIABLES_SIMULAR_POR_DEFECTO))
    CATALOGO_SIM = catalogo_simulacion()
    GRUPO_POR_KNOB = grupo_por_knob(CATALOGO_SIM)
    for _aviso in incoherencias_del_catalogo(KNOBS, CATALOGO_SIM):
        warnings.warn(_aviso, RuntimeWarning, stacklevel=2)

    # --- El catalogo de actividades del contrato -------------------------------------------
    # El simulador contesta que le pasa al riesgo del vano; esto contesta cuanto cuesta el
    # plan. Es la otra mitad de la decision de mantenimiento, y juntas producen la frase con
    # la que se aprueba una orden de trabajo: "baja un grupo de criticidad por 283.472 pesos".
    #
    # Las dos mitades NO estan atadas entre si, y es a proposito. Marcar "PODA EN REDES
    # RURALES TIPO A" no mueve `NR_T`, y bajar `NR_T` no programa una poda: el modelo no
    # tiene ningun mapa de actividades del contrato a features, e inventarlo produciria un
    # numero con toda la pinta de ser el beneficio estimado de esa actividad sin serlo. Lo
    # que el panel pone lado a lado es el efecto simulado y el costo cotizado del plan que
    # el usuario dice que ejecutaria; el puente entre los dos se queda en su cabeza, que es
    # el sitio honesto hasta que CHEC entregue esa correspondencia.
    #
    # El libro es una exportacion de tabla dinamica, y `leer_catalogo_costos` se ocupa de
    # las dos trampas que trae: su ultima fila es el pie `Total general` -- que ofrecido
    # como actividad agrega 254 mil pesos de puro artefacto -- y doce filas no traen costo
    # unitario. Esas doce no se pueden costear, pero tampoco se hacen desaparecer.
    CATALOGO_COSTOS = leer_catalogo_costos(costos)
    # El detalle de cada actividad, para el boton "i" del panel. Sale del MISMO libro
    # que el precio: dos lecturas del mismo archivo se separan en cuanto alguien cambia
    # una. 52 de las 142 no traen descripcion, y esas lo DICEN en vez de salir en blanco.
    TEXTO_ITEMS = {
        _it.nombre: (f'{_it.nombre}\n'
                     f'Tipo: {_it.tipo or "sin tipo"}  |  '
                     f'Unidad: {_it.unidad or "sin unidad"}  |  '
                     f'Código máximo: {_it.codigo_maximo or "sin código"}\n'
                     f'{_it.descripcion}')
        for _it in CATALOGO_COSTOS.items
    }
    INFO_ITEMS = {
        _it.nombre: (f'<b>{_it.nombre}</b><br>'
                     f'Tipo: {_it.tipo or "sin tipo"} &nbsp;|&nbsp; '
                     f'Unidad: {_it.unidad or "sin unidad"} &nbsp;|&nbsp; '
                     f'Código máximo: {_it.codigo_maximo or "sin código"}<br>'
                     f'<span style="color:#4b5563;">{_it.descripcion}</span>')
        for _it in CATALOGO_COSTOS.items
    }
    COSTO_POR_ITEM = CATALOGO_COSTOS.por_nombre

    # --- Inventario de trazas -------------------------------------------------------------
    # La figura tiene OCHO paneles. Los dos mapas ocupan el cuadrante superior, uno al lado
    # del otro; las filas 3 y 4 responden cuatro preguntas distintas sobre los vanos elegidos
    # -- como vienen en el tiempo, que variable mueve a CADA uno, como se relacionan esas
    # variables entre si, y cuanto cambia el UITI al simular --; y la fila 5 contesta la que
    # convierte el analisis en una orden de trabajo: cuanto cuesta, por vano y en total.
    # Salieron la nube KMeans, la barra de importancia agregada de la seleccion -- la
    # reemplaza el top 5 POR VANO, que es la pregunta que sostiene una orden de trabajo -- y
    # el violin de eventos por grupo, cuyo hueco pasa a comparar medido contra simulado.
    #
    # El inventario ya no esta congelado por indices sueltos: se ARMA sobre la marcha y `IDX`
    # se llena con lo que devuelve `add_trace`. Congelarlo a mano tenia sentido cuando las
    # trazas se agregaban de a una en PRs sucesivos; ahora el orden lo fija este bloque y
    # cualquier reordenamiento se ve aqui mismo.
    IDX = {}

    # El recuadro del vano seleccionado vive en el LAYOUT del mapa base y no en el inventario
    # de trazas: `below='traces'` lo deja debajo de todos los tramos, con lo que no intercepta
    # ni el hover ni el clic -- que es justo lo que alterna la seleccion -- y no tapa el color
    # de clase del vano que esta senialando. Nacen vacias; el repintado les escribe el
    # `source`.
    #
    # CINCO capas y no una, por el mismo motivo que el mapa simulado lleva tres: una capa de
    # `layout.map.layers` pinta con UN color, y el relleno del recuadro paso a ser el color
    # del grupo KMeans del propio vano. Cuatro grupos mas la del marcado que en esta ventana
    # no tiene celda -- sin grupo, que no es el grupo mas bajo.
    #
    # El ORDEN es fijo (`CLASES_CAJA`) y las cinco existen siempre, vacias incluidas: asi el
    # repintado es una escritura de `source` por capa y nunca un quitar y poner capas, que en
    # MapLibre reordena lo que hay debajo.
    CLASES_CAJA = (0, 1, 2, 3, None)
    COLOR_CAJA_POR_CLASE = {
        **{_clase: COLORES_CAJA_SELECCION[_clase] for _clase in range(4)},
        None: COLOR_CAJA_SIN_CLASE,
    }
    CAPAS_CAJA_SELECCION = [
        dict(sourcetype='geojson', type='fill', below='traces',
             source={'type': 'FeatureCollection', 'features': []},
             color=COLOR_CAJA_POR_CLASE[_clase], opacity=OPACIDAD_CAJA_SELECCION)
        for _clase in CLASES_CAJA
    ]
    IDX_CAPA_CLASE = {_clase: _i for _i, _clase in enumerate(CLASES_CAJA)}
    # El mapa simulado lleva TRES capas de caja, una por desenlace, por la misma razon por la
    # que la de la izquierda es una sola: una capa pinta con UN color. Nacen vacias y siempre
    # en el mismo orden (`CAMBIOS`), asi que el repintado es una escritura de `source` por capa
    # y nunca un quitar y poner capas del mapa -- que en MapLibre reordena lo que hay debajo.
    COLOR_POR_CAMBIO = {CAMBIO_MEJORA: COLOR_CAJA_MEJORA,
                        CAMBIO_IGUAL: COLOR_CAJA_IGUAL,
                        CAMBIO_EMPEORA: COLOR_CAJA_EMPEORA}
    CAPAS_CAJA_SIMULADA = [
        dict(sourcetype='geojson', type='fill', below='traces',
             source={'type': 'FeatureCollection', 'features': []},
             color=COLOR_POR_CAMBIO[_cambio], opacity=OPACIDAD_CAJA_SELECCION)
        for _cambio in CAMBIOS
    ]
    IDX_CAPA_CAMBIO = {_cambio: _i for _i, _cambio in enumerate(CAMBIOS)}


    def _agregar(traza, fila, columna, **kwargs):
        """Agrega la traza y devuelve su indice, que es lo unico que el resto del cuaderno
    necesita saber de ella."""
        _fig.add_trace(traza, row=fila, col=columna, **kwargs)
        return len(_fig.data) - 1


    _fig = make_subplots(
        rows=7, cols=4,
        specs=[[{'type': 'map', 'rowspan': 2, 'colspan': 2}, None,
                {'type': 'map', 'rowspan': 2, 'colspan': 2}, None],
               [None, None, None, None],
               # El perfil del circuito y el grafo COMPARTEN esta fila, justo debajo de
               # los mapas. El perfil va antes que todo lo demas porque contesta la
               # primera pregunta que se hace al aterrizar en un circuito -- donde esta
               # concentrado el riesgo -- y es el unico panel que no depende ni de la
               # ventana ni de los vanos marcados: ya esta dibujado cuando se toman esas
               # dos decisiones.
               #
               # El grafo estaba solo en una septima fila, centrado y a media fila: un
               # disco con franjas blancas a los lados y otra debajo. Aqui llena las
               # columnas 3-4 y la fila entera desaparece. La fila se queda con el alto
               # que tenia la del grafo -- lo que manda el diametro del circulo -- y el
               # perfil pasa de ancho completo a media fila: quince rotulos de ocho
               # digitos en la mitad del ancho, que es lo que hay que vigilar aqui.
               # Fila 3: el perfil a la izquierda y la serie de UITI acumulado a su
               # derecha. El grafo, que compartia esta fila, se fue a su propia figura
               # debajo del panel de control.
               [{'type': 'xy', 'colspan': 2}, None,
                {'type': 'xy', 'colspan': 2, 'secondary_y': True}, None],
               # Fila 4: el top de variables, ahora de ancho completo. Compartia fila con
               # la serie, y con la serie arriba se queda con las cuatro columnas.
               [{'type': 'xy', 'colspan': 4}, None, None, None],
               # Tres columnas para los vanos y UNA para el acumulado del circuito. Iban
               # juntos, y no son la misma pregunta ni la misma escala: el total del
               # circuito es la suma de sus 81 vanos y aplasta contra el eje a los diez
               # grupos de al lado, que es justo donde se decide la obra. Separados, cada
               # panel tiene su propio eje y los vanos vuelven a leerse.
               [{'type': 'xy', 'colspan': 3}, None, None, {'type': 'xy'}],
               # El costo se parte igual que el UITI de arriba: los vanos en las columnas
               # 1-3 y el acumulado del plan en la 4. Compartiendo eje, el total -- que es
               # la suma -- era siempre la barra mas alta y dejaba a las de los vanos
               # pegadas a la base, que es justo donde se compara una obra con otra.
               [{'type': 'xy', 'colspan': 3}, None, None, {'type': 'xy'}],
               # Fila 7: el grafo, debajo del costo y en las columnas 2-3. A media anchura
               # porque el anillo lo acota la dimension MENOR del panel: de ancho completo
               # el circulo no crece, solo aparecen dos franjas blancas a los lados.
               [None, {'type': 'xy', 'colspan': 2}, None, None]],
        subplot_titles=(
            'Criticidad Original',
            'Criticidad Simulada',
            'Perfil del circuito',
            # Cuarto y no ultimo: los titulos van en el orden de la rejilla, y el grafo
            # ahora esta en la fila 3. El cuaderno los BUSCA por texto para reescribirlos,
            # asi que reordenarlos aqui no rompe ningun indice.
            'UITI acumulado y eventos por ventana',
            f'Top {TOP_VARIABLES_POR_VANO}: que baja el UITI de cada vano',
            'UITI acumulado: medido contra simulado',
            # Corto porque su panel es UNA columna: el titulo era mas ancho que el
            # panel y su voladizo caia justo sobre la marca mas alta del eje y.
            'Todo el circuito',
            'Costo de la intervencion',
            'Costo acumulado',
            'Grafo - Relaciones relevantes de la simulación',
        ),
        # El grafo es circular y su diametro lo fija la dimension MENOR del panel. Esa NO es
        # siempre la altura: el panel ocupa las columnas 2-3, o sea el 44,25% del ancho del
        # area de dibujo, y ese ancho depende de la ventana. Medido con la fila a 1.206 px de
        # alto: a 850 px de ventana el panel era de 347 x 1.206 y mandaba el ANCHO, con lo
        # que el circulo se quedaba en 89 px de radio -- menos que antes -- y sobraban 859 px
        # de banda blanca arriba y abajo. Subir la fila no agranda el grafo; solo agrega
        # vacio.
        # La fila se fija en 590 px, que es el ancho de las columnas 2-3 en una ventana de
        # 1.400 px. De ahi para arriba manda la altura: el circulo la llena entera y no queda
        # vacio vertical, que es el defecto que se ve. Por debajo el vacio se reduce a 243 px
        # en el peor caso medido, contra los 859 de antes.
        # Las otras cinco filas conservan su alto ABSOLUTO -- 336, 336, 408, 408 y 336 px --:
        # su fraccion sube solo porque el total baja de 3.552 a 2.667 px.
        # Cuidado al leer estos numeros: plotly reparte `row_heights` sobre lo que SOBRA
        # despues del espaciado, no sobre el alto total. Con seis huecos de 0,05 el
        # espaciado se lleva el 30%, asi que el alto REAL de una fila es
        # `fraccion x 0,70 x 3.003`. Medido sobre la figura ya construida: 235,2 px las
        # filas de 0,1119, 285,7 px las de 0,1359 y 589,8 px la del grafo.
        # Las seis filas viejas conservan su alto EXACTO -- median 235,2 / 285,7 / 589,8 px
        # sobre los 2.667 px de antes --: la fila nueva sale de los 336 px que la figura
        # crece, no de quitarselos a las demas.
        # 235,2 px alcanzan para quince barras porque lo que las aprieta es el ANCHO, y el
        # perfil ocupa la fila entera.
        # Seis filas y cinco huecos, no siete y seis. `row_heights` reparte lo que SOBRA
        # despues del espaciado, asi que quitar una fila cambia las dos cosas a la vez y
        # hay que recalcular fracciones y alto total juntos para que las filas que se
        # quedan conserven su alto en pixeles.
        #
        # Antes: 3.003 px, seis huecos de 0,05 -> el espaciado se llevaba el 30% y los
        # paneles median 235,2 / 235,2 / 235,2 / 285,7 / 285,7 / 235,2 / 589,8 px.
        # Ahora: cinco huecos de 0,05 -> el 25%, y la fila 3 hereda los 589,8 px de la
        # del grafo, que es lo que fija el diametro del circulo. Los paneles suman
        # 1.866,8 px, asi que el alto total baja de 3.003 a 2.489 px -- los 235,2 de la
        # fila que se va, mas su hueco.
        # La fila 3 baja a la MITAD de alto: su tamanio lo mandaba el diametro del grafo,
        # que ya no esta ahi, y con el perfil y la serie basta con la mitad.
        #
        # Halvar una fila no es dividir su fraccion por dos: `row_heights` reparte lo que
        # sobra DESPUES del espaciado, asi que cambiar una cambia a todas. Se recalculan las
        # seis desde los pixeles MEDIDOS -- 189,4 | 189,4 | 474,8 | 230 | 230 | 189,4 sobre
        # 1.503 px repartibles, con huecos de 162:
        #
        #     filas' = 189,4 + 189,4 + 237,4 (la mitad) + 230 + 230 + 189,4 = 1.265,6
        #     cada fraccion = su alto / 1.265,6
        # SIETE filas. La septima es la del grafo, y su alto lo manda el diametro del
        # circulo -- 430 px, los mismos que tenia cuando vivia en su propia figura.
        #
        # Las otras seis conservan sus pixeles. `row_heights` reparte lo que sobra DESPUES
        # del espaciado, asi que agregar una fila cambia a todas: se recalculan las siete
        # desde lo MEDIDO -- 189,4 | 189,4 | 237,5 | 230 | 230 | 189,4 -- mas los 430:
        #
        #     filas  = 1.265,6 + 430              = 1.695,6
        #     area   = 1.695,6 + 6 x 162 (huecos) = 2.667,6
        #     height = 2.667,6 + 106 + 44         = 2.817,6
        row_heights=[0.1117, 0.1117, 0.1400, 0.1356, 0.1356, 0.1117, 0.2535],
        # 0,05 y no 0,035: en el hueco entre la serie de tiempo y el top 5 tienen que caber
        # CUATRO cosas -- las marcas del eje secundario de la serie, su rotulo "Eventos", el
        # rotulo "Relevancia variables" del top y las marcas de ese eje. Medido a 1.900 px,
        # con 0,035 el hueco era de 64 px y las marcas del eje secundario ya llegaban a 21 de
        # esos: los dos rotulos se encimaban.
        # 0,06 y no 0,095: el espaciado vertical es una fraccion POR HUECO, y al pasar de
        # cinco filas a seis los huecos pasaron de cuatro a cinco. Con 0,095 se llevaban el
        # 47,5% del alto util y no quedaba panel que repartir.
        # 0,05 y no 0,06: el espaciado es una fraccion POR HUECO y los huecos pasan de
        # cinco a seis al entrar la fila del perfil. Con 0,06 los seis se habrian llevado
        # el 36% del alto contra el 30% de antes, y esos seis puntos salen de los paneles:
        # el grafo habria bajado de 589,8 a 539 px sin que nadie lo pidiera. A 0,05 los
        # seis huecos vuelven a pesar exactamente el 30% y TODAS las filas viejas conservan
        # su alto al pixel -- verificado midiendo los dominios de la figura construida.
        # El hueco que manda sigue siendo el de la fila 4, el que tiene que albergar los
        # dos rotulos de los ejes de la serie mas sus marcas: pasa de 160 px (0,06 x 2.667)
        # a 150 px (0,05 x 3.003), todavia muy por encima de los 64 px medidos en que los
        # dos rotulos se encimaban.
        # 0.055 daba 52 px de hueco entre columnas y 0.075 daba 71. Medido: los rotulos
        # girados de 'Eventos' y 'Caida de UITI' quedaban a 13 px uno de otro y cada uno
        # mide 17 de grosor, asi que seguian pisandose. En ese hueco tienen que caber
        # CUATRO capas -- marcas del eje derecho de la izquierda, su rotulo, el rotulo del
        # panel de la derecha y sus marcas --, que piden unos 90 px.
        # El hueco entre filas se conserva en PIXELES -- 162 --, no en fraccion: lo que cabe
        # ahi son rotulos y marcas, y el texto no encoge con la figura. 162 / 2.075,6 = 0.078.
        # El hueco sigue valiendo 162 px; lo que cambia es de que area es fraccion.
        # 162 / 2.667,6 = 0.0607.
        horizontal_spacing=0.095, vertical_spacing=0.0607,
    )

    # --- Mapa base (filas 1-2, columnas 1-2) ---------------------------------------------
    IDX['clases'] = [
        _agregar(go.Scattermap(
            lat=[], lon=[], mode='lines', name=NOMBRES_GRUPOS[_clase], legendgroup='hist',
            line=dict(width=ANCHO_MAPA, color=COLORES_GRUPOS[_clase]),
            hovertext=[], hoverinfo='text',
        ), 1, 1) for _clase in range(4)
    ]
    IDX['sin_dato'] = _agregar(go.Scattermap(
        lat=[], lon=[], mode='lines', name='Sin evento en la ventana', legendgroup='hist',
        line=dict(width=ANCHO_SIN_EVENTOS, color=COLOR_SIN_EVENTO),
        hovertext=[], hoverinfo='text',
    ), 1, 1)
    # El marcado va en DOS capas, como en 01.4: primero el halo blanco ancho y despues la
    # linea con el color de SU clase. Un color plano de "seleccionado" encima congelaria lo
    # que se ve: la ventana cambia la clase por debajo y el vano seguiria igual en pantalla.
    IDX['marcados'] = _agregar(go.Scattermap(
        lat=[], lon=[], mode='lines', name='Vano marcado', legendgroup='hist', showlegend=False,
        line=dict(width=ANCHO_HALO, color=COLOR_HALO), hovertext=[], hoverinfo='text',
    ), 1, 1)
    IDX['marcados_clases'] = [
        _agregar(go.Scattermap(
            lat=[], lon=[], mode='lines', name=NOMBRES_GRUPOS[_clase], legendgroup='hist',
            showlegend=False, line=dict(width=ANCHO_MAPA_MARCADO, color=COLORES_GRUPOS[_clase]),
            hovertext=[], hoverinfo='text',
        ), 1, 1) for _clase in range(4)
    ]
    IDX['marcados_sin_dato'] = _agregar(go.Scattermap(
        lat=[], lon=[], mode='lines', name='Marcado sin eventos', legendgroup='hist',
        showlegend=False, line=dict(width=ANCHO_MAPA_MARCADO, color=COLOR_SIN_EVENTO),
        hovertext=[], hoverinfo='text',
    ), 1, 1)

    # --- Mapa simulado (filas 1-2, columnas 3-4) -----------------------------------------
    IDX['pred_clases'] = [
        _agregar(go.Scattermap(
            lat=[], lon=[], mode='lines', name=NOMBRES_GRUPOS[_clase], legendgroup='pred',
            showlegend=False, line=dict(width=ANCHO_MAPA, color=COLORES_GRUPOS[_clase]),
            hovertext=[], hoverinfo='text',
        ), 1, 3) for _clase in range(4)
    ]
    IDX['pred_sin_dato'] = _agregar(go.Scattermap(
        lat=[], lon=[], mode='lines', name='Sin evento / no simulado', legendgroup='pred',
        showlegend=False, line=dict(width=ANCHO_SIN_EVENTOS, color=COLOR_SIN_EVENTO),
        hovertext=[], hoverinfo='text',
    ), 1, 3)

    # Los equipos van DESPUES de los tramos para dibujarse encima. Se repiten por mapa porque
    # una traza pertenece a un solo subplot: sin ellos la derecha se leeria como otra geografia.
    for _columna_mapa, _leyenda in ((1, True), (3, False)):
        _claves = ('trafos', 'switches') if _columna_mapa == 1 else ('pred_trafos', 'pred_switches')
        for _clave, _nombre, _color, _tam in zip(
                _claves, ('Transformadores', 'Switches'),
                (COLOR_TRAFO, COLOR_SWITCH), (TAM_TRAFO, TAM_SWITCH)):
            IDX[_clave] = _agregar(go.Scattermap(
                lat=[], lon=[], mode='markers', name=_nombre, legendgroup='equipos',
                showlegend=_leyenda, marker=dict(size=_tam, color=_color),
                hovertext=[], hoverinfo='text',
            ), 1, _columna_mapa)

    # --- Fila 3: el perfil del circuito ---------------------------------------------------
    # Los quince vanos que mas UITI acumulan en TODA la serie, de mayor a menor. Contesta
    # una pregunta que ningun otro panel contesta: los dos mapas y la serie de tiempo miran
    # una ventana a la vez, y el deslizador obliga a recorrer once para saber si el riesgo
    # del circuito esta repartido o concentrado en un puniado de vanos.
    #
    # El total NO es la suma de `uiti_acumulado` sobre las once ventanas. Las ventanas se
    # TRASLAPAN -- seis son meses y cinco son cortes del 15 al 15 --, asi que casi todo
    # evento cae en dos y esa suma lo cuenta dos veces. `perfil_uiti_por_vano` suma solo
    # sobre las ventanas que embaldosan el periodo una vez. Medido sobre las 111.231
    # celdas: la suma ingenua infla el total entre 1,00 y 2,09 veces segun el vano, y como
    # el factor no es constante tampoco se cancela al ordenar -- 74 de los 208 circuitos
    # cambian su top 15.
    IDX['perfil_circuito'] = _agregar(go.Bar(
        x=[], y=[], name='UITI acumulado del periodo', showlegend=False,
        marker=dict(color=COLOR_BARRA_PERFIL,
                    line=dict(width=0.4, color='rgba(60,10,10,0.6)')),
        hovertext=[], hoverinfo='text',
    ), 3, 1)
    # `type='category'`: los fid son cadenas de digitos y sin esto plotly los leeria como
    # numeros, con lo que las quince barras se repartirian por su VALOR sobre un eje
    # continuo -- quince postes separados por millones de unidades vacias -- en vez de
    # quedar una al lado de la otra en el orden del ranking.
    _fig.update_xaxes(title_text='Vano', type='category', tickfont=dict(size=9),
                      row=3, col=1)
    _fig.update_yaxes(title_text='UITI acumulado del periodo', rangemode='tozero',
                      tickfont=dict(size=9), row=3, col=1)
    # El titulo se reescribe en cada circuito para publicar cuanto concentra el top, que es
    # la lectura del panel y no cabe en una barra. Se BUSCA por el texto con que nacio, por
    # la misma razon que `IDX_TITULO_BARRAS`: contar posiciones depende de la rejilla.
    IDX_TITULO_PERFIL = next(
        i for i, _a in enumerate(_fig.layout.annotations)
        if (_a.text or '') == 'Perfil del circuito')

    # --- Fila 4, columnas 1-2: la serie de tiempo de los vanos elegidos --------------------
    # Paridad con 03 y 04: la LINEA y el ANILLO del punto llevan el color de identidad del
    # vano -- dicen de QUE vano es la serie -- y el RELLENO del punto lleva el color del grupo
    # de riesgo en que cayo ese vano en esa ventana. Son dos codigos sobre el mismo dato,
    # separados por canal para que los dos se lean a la vez. Un relleno gris es una ventana sin
    # celda, que no tiene grupo -- distinto de caer en el mas bajo. Doble eje porque UITI y eventos viven en escalas muy distintas y
    # compartir eje aplastaria una de las dos.
    # `marker.size` es un ARRAY: el punto de la ventana activa va al triple y viaja con el
    # deslizador sin partir la serie en una segunda traza.
    _VACIO = [None] * len(VENTANAS)
    # El eje x son los INDICES de ventana, pero las marcas llevan la FECHA en que empieza
    # cada una y no su etiqueta "V1", "V2": un rotulo "V7" obliga a ir a buscar a que periodo
    # corresponde cada vez que se mira el panel. El ano se recorta como en 03 y 04 -- todas
    # las ventanas caen en el mismo -- para que las once quepan sin apilarse.
    _X_VENTANAS = [v['i'] for v in VENTANAS]
    _FECHAS_VENTANA = [str(v['desde'].date()) for v in VENTANAS]
    _ANIOS_VENTANA = sorted({f[:4] for f in _FECHAS_VENTANA})
    _TICKS_VENTANA = ([f[5:] for f in _FECHAS_VENTANA] if len(_ANIOS_VENTANA) == 1
                      else _FECHAS_VENTANA)
    # Hay `MAX_VANOS_SERIE` ranuras y solo `len(COLORES_VANOS)` colores, porque el pozo se
    # duplico para dejar sitio a los vanos que el usuario agrega a mano por encima de la
    # auto-marca y no habia quince colores mas que fueran de verdad distinguibles entre si.
    # La paleta se recorre en circulo y la SEGUNDA vuelta va con trazo discontinuo: dos series
    # del mismo color se separan igual por el patron de la linea, que es un canal que aqui
    # estaba libre. Es preferible a inventar quince tonos que se confundirian de a pares --
    # eso serian dos series indistinguibles de verdad, no dos que hay que mirar dos veces.
    def _estilo_de_cupo(_s):
        return COLORES_VANOS[_s % len(COLORES_VANOS)], (
            'solid' if _s < len(COLORES_VANOS) else 'dash')


    IDX['serie_uiti'] = [
        _agregar(go.Scatter(
            x=_X_VENTANAS, y=list(_VACIO), mode='lines+markers', name='', showlegend=False,
            line=dict(color=_estilo_de_cupo(_s)[0], width=2, dash=_estilo_de_cupo(_s)[1]),
            marker=dict(size=[SERIE_TAM_UITI] * len(VENTANAS),
                        color=[COLOR_SIN_GRUPO] * len(VENTANAS),
                        line=dict(width=1.2, color=_estilo_de_cupo(_s)[0])),
            hovertext=[], hoverinfo='text', connectgaps=False,
        ), 3, 3, secondary_y=False) for _s in range(MAX_VANOS_SERIE)
    ]
    IDX['serie_eventos'] = [
        _agregar(go.Scatter(
            x=_X_VENTANAS, y=list(_VACIO), mode='lines+markers', name='', showlegend=False,
            line=dict(color=_estilo_de_cupo(_s)[0], width=1.1, dash='dot'),
            marker=dict(size=[SERIE_TAM_EVENTOS] * len(VENTANAS), symbol='square',
                        color=[COLOR_SIN_GRUPO] * len(VENTANAS),
                        line=dict(width=1.1, color=_estilo_de_cupo(_s)[0])),
            hovertext=[], hoverinfo='text', connectgaps=False,
        ), 3, 3, secondary_y=True) for _s in range(MAX_VANOS_SERIE)
    ]
    _fig.update_xaxes(title_text=('Inicio de la ventana'
                                  + (f' ({_ANIOS_VENTANA[0]})' if len(_ANIOS_VENTANA) == 1 else '')),
                      tickmode='array', tickvals=_X_VENTANAS, ticktext=_TICKS_VENTANA,
                      tickangle=-45, tickfont=dict(size=8), row=3, col=3)
    # Eje LINEAL. Con `type='log'` las ventanas sin eventos -- que ahora valen cero, no un
    # hueco -- desaparecian del panel: `log(0)` no existe y Plotly descarta el punto en
    # silencio, asi que la secuencia completa de ventanas que el eje promete no se dibujaba.
    _fig.update_yaxes(title_text='UITI acumulado', rangemode='tozero',
                      row=3, col=3, secondary_y=False)
    # Marcas mas pequenias en los dos ejes que comparten el hueco: cada digito que se
    # ahorran es espacio para separar sus rotulos, que estaban a 5 px uno del otro.
    _fig.update_yaxes(title_text='Eventos', rangemode='tozero', showgrid=False,
                      title_standoff=6, tickfont=dict(size=9),
                      row=3, col=3, secondary_y=True)

    # --- Fila 4, columnas 3-4: el top de variables POR VANO -------------------------------
    # Un grupo de barras por vano. Cada traza es una POSICION del ranking (la 1a, la 2a...),
    # no una variable: las variables cambian de vano a vano, asi que una traza por variable
    # necesitaria tantas como el catalogo entero y casi todas vacias.
    # El nombre de la variable va DENTRO de la barra: con cinco grupos de diez barras no hay
    # sitio para una leyenda de cincuenta entradas, y el rotulo pegado al dato no obliga a
    # cruzarlo. Cual de los tres rotulos posibles -- resumen, inicial o ninguno -- se escribe
    # lo decide el repintado segun lo que mida cada barra, y el nombre completo esta siempre en
    # la etiqueta del mouse.
    # El color codifica la POSICION en el ranking y nada mas. Antes salia de `COLORES_GRUPOS`,
    # lo que con diez posiciones dejaba siete del mismo rojo oscuro y, peor, invitaba a leer
    # una barra como un grupo de criticidad, que es otra cosa. Una rampa de opacidad sobre UN
    # color dice "primera, segunda, tercera" sin pedir prestada la paleta del mapa.
    # El color por defecto codifica la POSICION en el ranking y nada mas: una rampa de
    # opacidad sobre UN color, deliberadamente ajena a la paleta de los grupos para que una
    # barra no se lea como un grupo de criticidad. El repintado la sobrescribe con VERDE en
    # las barras cuya variable, sola, ya baja al vano al grupo Bajo.
    COLOR_POSICION_BARRA = [f'rgba(203,24,29,{0.95 - 0.055 * _p:.2f})'
                            for _p in range(TOP_VARIABLES_POR_VANO)]
    IDX['top_vano'] = [
        _agregar(go.Bar(
            x=[], y=[], name=f'{_p + 1}o', showlegend=False,
            # `textposition` va por PUNTO y no por traza: dentro de la misma posicion del
            # ranking conviven barras largas -- que llevan su rotulo dentro -- y barras
            # cortas, que lo llevan encima. El repintado escribe la lista.
            text=[], textposition=[], insidetextanchor='middle',
            textangle=-90, constraintext='none',
            insidetextfont=dict(size=TAM_FUENTE_BARRA, color='white'),
            # El de FUERA no puede ser blanco: encima de la barra el fondo es el del panel.
            # Es la unica diferencia entre los dos rotulos, y no es de estilo -- con el
            # blanco heredado el texto existe y no se ve. `#2b2b2b` es el gris de texto de
            # la paleta, escrito como en el resto de este archivo: el tablero corre dentro
            # del kernel de Voila y `aplicaciones/_comun` no esta en su `sys.path`.
            outsidetextfont=dict(size=TAM_FUENTE_BARRA, color='#2b2b2b'),
            marker=dict(color=[], line=dict(width=0.4, color='rgba(60,10,10,0.6)')),
            hovertext=[], hoverinfo='text',
        ), 4, 1) for _p in range(TOP_VARIABLES_POR_VANO)
    ]
    _fig.update_yaxes(title_text='Caída de UITI (órdenes de magnitud)',
                      title_standoff=6, tickfont=dict(size=9), row=4, col=1)
    _fig.update_xaxes(title_text='Vano', type='category', tickfont=dict(size=9),
                      row=4, col=1)

    # --- Fila 7, columnas 2-3: cuanto MOVIO la simulacion el grafo ---------------------
    # Estuvo debajo del panel de control, en figura propia. Vuelve a la figura grande y a
    # una fila para el solo, debajo del costo de la intervencion.
    #
    # Centrado y a media anchura: el anillo lo acota la dimension MENOR del panel, asi que
    # de ancho completo solo anadiria franjas blancas a los lados.
    #
    # Sus rotulos son ANOTACIONES guardadas POR POSICION, y las de los otros paneles
    # tambien. Volver no rompe esos indices porque cada uno se toma con `len(...) - 1` al
    # crear la anotacion; lo que no puede quedar es ninguna a medias en el camino.
    # Ya no es el grafo de la seleccion sino |grafo_base - grafo_simulado|. Los dos comparten
    # los pesos fijos del experto y solo difieren por las compuertas, asi que puestos uno al
    # lado del otro se ven iguales y el efecto de la intervencion -- que es lo que el panel
    # viene a mostrar -- se pierde. La diferencia aisla exactamente lo que cambio.
    # El peso viaja en un marcador en el PUNTO MEDIO de cada arista y no en el ancho de la
    # linea: una sola traza de lineas no puede variar su ancho por segmento, y partirla en una
    # traza por arista serian decenas que hay que restilar una por una.
    IDX['grafo_aristas'] = _agregar(go.Scattergl(
        x=[], y=[], mode='lines', showlegend=False,
        line=dict(width=1.0, color='rgba(120,110,110,0.45)'), hoverinfo='skip',
    ), 7, 2)
    IDX['grafo_pesos'] = _agregar(go.Scattergl(
        x=[], y=[], mode='markers', showlegend=False,
        marker=dict(size=[], color=[], colorscale='Reds', cmin=0.0, showscale=False,
                    line=dict(width=0.4, color='#5b4a48')),
        hovertext=[], hoverinfo='text',
    ), 7, 2)
    # `mode='markers'` a secas: el NOMBRE del nodo ya no viaja en la traza. Un `Scatter` no
    # puede girar su texto -- comprobado contra plotly 6.8.0, solo `Bar` y las anotaciones
    # llevan `textangle` --, y con los rotulos horizontales los nombres de nodos vecinos se
    # montaban unos sobre otros alrededor del anillo. Van como anotaciones, mas abajo.
    IDX['grafo_nodos'] = [
        _agregar(go.Scatter(
            x=[], y=[], mode='markers', name=_modalidad, legendgroup='grafo',
            marker=dict(size=7, color=COLORES_MODALIDAD[_modalidad],
                        line=dict(width=0.5, color='#1f2937')),
            hovertext=[], hoverinfo='text',
        ), 7, 2) for _modalidad in MODALIDADES_MIL
    ]
    # Los ejes del grafo se PREGUNTAN a su traza en vez de escribirse a mano: el numero
    # depende de la posicion del subplot en la grilla y del eje secundario de la fila 3, y
    # adivinarlo deja el aviso flotando sobre otro panel.
    _EJE_X_GRAFO = _fig.data[IDX['grafo_aristas']].xaxis or 'x'
    _EJE_Y_GRAFO = _fig.data[IDX['grafo_aristas']].yaxis or 'y'
    # Sin ejes: una disposicion circular no mide nada en x ni en y. El rango se fija a mano y
    # con holgura -- sin ella los rotulos de los nodos del borde salen cortados.
    # Con `scaleanchor` manda el eje con menos pixeles por unidad, asi que el circulo lo
    # acota la dimension MENOR del panel: por debajo de ~1.400 px de ventana es el ancho de
    # las columnas 2-3, y de ahi para arriba la altura de la fila.
    # El rango no se elige a ojo: sale del rotulo mas LARGO. Los nombres arrancan en
    # `RADIO_ROTULO_GRAFO` y corren hacia afuera, asi que el rango tiene que cumplir
    #     RADIO_ROTULO_GRAFO + largo_en_unidades <= rango,
    # y el largo en unidades es `largo_px * 2 * rango / ancho_panel`. Despejando:
    #     rango >= RADIO_ROTULO_GRAFO / (1 - 2 * largo_px / ancho_panel)
    # Medido sobre el panel de 590 px -- las columnas 2-3 en una ventana de 1.400 px, que es
    # donde el panel es cuadrado -- y sobre el rotulo ABREVIADO mas largo, "Crit. apoyo", de
    # 64,6 px a fuente 10. Da 1,34; se deja 1,36 de holgura.
    # Con los nombres crudos el mas largo era FECHA_OPERACION_VANO con 145 px, que pedia 2,07
    # y dejaba el circulo en 142,9 px de radio. Abreviando sube a 219,4 px: el rango es lo que
    # reparte el panel entre el anillo y sus nombres, asi que acortar los nombres agranda el
    # grafo sin tocar el panel.
    # EL MISMO en los dos ejes, y esa es la mitad del asunto. Llevaba 1,36 en x y 1,75 en y,
    # y dos rangos distintos con `scaleanchor` estan SOBREDETERMINADOS: plotly tiene que
    # reconciliarlos y decide el reparto en el navegador, no aqui. Medido con Chrome sobre la
    # figura servida: el mandon acababa siendo el eje Y, que dejaba el circulo clavado en 162
    # px de radio a CUALQUIER ancho de ventana -- 1.280, 1.512 o 1.900 px -- mientras el panel
    # crecia hasta 789 px y el sobrante se iba en dos bandas blancas a los lados.
    # Iguales, el circulo llena el panel y no hay nada que reconciliar.
    #
    # 1,45 y no 1,36: el rango es lo que reparte el panel entre el anillo y los nombres de sus
    # nodos, y tiene que cumplir
    #     RANGO_GRAFO >= RADIO_ROTULO_GRAFO / (1 - 2 * largo_px / lado_panel)
    # El rotulo abreviado mas largo es "Crit. apoyo" -- 64,6 px a fuente 10, comprobado contra
    # los 22 nodos que de verdad tienen arista --, y el lado del panel mas chico medido es 515
    # px (ventana de 1.280). Da 1,402. A 1,36 el margen medido era de 0,7 px, o sea ninguno.
    RANGO_GRAFO = 1.45
    # `constrain='domain'` y no el 'range' por defecto, y es la otra mitad.
    #
    # Con 'range' plotly cuadra los pixeles por unidad ESTIRANDO el rango del eje que le
    # sobra sitio, y el rango es justamente lo que aqui esta calculado para que los rotulos
    # quepan: estirarlo encoge el circulo dentro de un panel que no cambia. Con 'domain'
    # plotly deja los rangos intactos y encoge el RECUADRO, asi que el panel se vuelve
    # cuadrado dentro de su celda y el circulo lo llena entero.
    #
    # Medido en la aplicacion servida, ventana de 1.512 px: con 'range' el panel era de
    # 614 x 559 con el circulo a 157 px de radio; con 'domain' queda de 559 x 559 con el
    # circulo a 193 px. Y lo que sobra se queda DENTRO de la celda, en vez de salirse hacia
    # la columna de al lado, que es lo que no puede pasar aqui.
    _fig.update_xaxes(visible=False, showticklabels=False, constrain='domain',
                      range=[-RANGO_GRAFO, RANGO_GRAFO], row=7, col=2)
    # `scaleanchor` iguala los pixeles por unidad de los dos ejes. Sin el, el panel es mucho
    # mas ancho que alto y la disposicion circular se dibujaba como una ELIPSE aplastada 2,93
    # veces -- medido --, que ademas hace que el giro radial de cada rotulo deje de coincidir
    # con la direccion que se ve.
    _fig.update_yaxes(visible=False, showticklabels=False, constrain='domain',
                      range=[-RANGO_GRAFO, RANGO_GRAFO],
                      scaleanchor=_EJE_X_GRAFO, scaleratio=1.0, row=7, col=2)
    _fig.add_annotation(text='', xref=f'{_EJE_X_GRAFO} domain', yref=f'{_EJE_Y_GRAFO} domain',
                        x=0.5, y=0.5, showarrow=False, align='center',
                        font=dict(size=11, color='#747378'))
    IDX_ANOTACION_GRAFO = len(_fig.layout.annotations) - 1

    # Un rotulo por nodo, como ANOTACION y no como texto de la traza, para poder girarlo.
    # La reserva se crea entera al armar la figura y despues solo se le cambia el contenido:
    # agregar y quitar anotaciones en cada repintado correria los indices de todas las demas
    # -- los avisos del grafo, de los costos y del mapa simulado --, que se guardan por
    # posicion. Sobran las que no se usen; se dejan con texto vacio.
    MAX_NODOS_GRAFO = len(FEATURES_MIL)
    IDX_ANOTACIONES_NODOS = []
    for _ in range(MAX_NODOS_GRAFO):
        _fig.add_annotation(text='', xref=_EJE_X_GRAFO, yref=_EJE_Y_GRAFO, x=0, y=0,
                            showarrow=False, font=dict(size=TAM_FUENTE_NODO, color='#334155'),
                            xanchor='left', yanchor='middle', textangle=0, visible=False)
        IDX_ANOTACIONES_NODOS.append(len(_fig.layout.annotations) - 1)

    # --- Fila 5: UITI acumulado MEDIDO contra el simulado, vano por vano -------------------
    # Un grupo por vano y un ultimo grupo con el circuito entero. Reemplaza a los violines:
    # con diez vanos, dos violines resumian en una densidad lo que aqui se lee vano por vano,
    # que es el grano en que se decide una obra.
    # Las dos barras son cantidades de NATURALEZA distinta -- una medicion contra una
    # prediccion -- y eso no se puede esconder: medido sobre 599 bolsas, el modelo correlaciona
    # 0,950 con el UITI observado pero su nivel corre +34%. Por eso la barra simulada lleva
    # barra de error con el desfase del modelo en la base de ESE vano, y el titulo publica la
    # reduccion con su +-: sin eso, el sesgo del modelo se leeria como ahorro.
    IDX['barra_observada'] = _agregar(go.Bar(
        x=[], y=[], name='UITI medido', marker=dict(color=COLOR_BARRA_MEDIDA,
                                                    line=dict(width=0.4, color='#5b4a48')),
        hovertext=[], hoverinfo='text', legendgroup='uiti',
    ), 5, 1)
    IDX['barra_simulada'] = _agregar(go.Bar(
        x=[], y=[], name='UITI simulado', marker=dict(color=COLOR_BARRA_SIMULADA,
                                                      line=dict(width=0.4, color='#5b4a48')),
        # `visible=True` con `array` vacio no dibuja nada; se llena al simular.
        error_y=dict(type='data', array=[], visible=True, color='#5b4a48', thickness=1.2,
                     width=4),
        hovertext=[], hoverinfo='text', legendgroup='uiti',
    ), 5, 1)
    # El acumulado del circuito, en la columna 4 y con su PROPIO eje. Son las mismas dos
    # cantidades -- medido contra simulado, con el mismo desfase como barra de error -- pero
    # a la escala del circuito entero: compartir eje con los vanos aplastaba a estos contra
    # la base. `showlegend=False` porque la leyenda ya la ponen las barras por vano y es la
    # misma pareja de series; repetirla duplicaria dos entradas identicas.
    IDX['barra_total_observada'] = _agregar(go.Bar(
        x=[], y=[], name='UITI medido', showlegend=False,
        marker=dict(color=COLOR_BARRA_MEDIDA, line=dict(width=0.4, color='#5b4a48')),
        hovertext=[], hoverinfo='text', legendgroup='uiti',
    ), 5, 4)
    IDX['barra_total_simulada'] = _agregar(go.Bar(
        x=[], y=[], name='UITI simulado', showlegend=False,
        marker=dict(color=COLOR_BARRA_SIMULADA, line=dict(width=0.4, color='#5b4a48')),
        error_y=dict(type='data', array=[], visible=True, color='#5b4a48', thickness=1.2,
                     width=4),
        hovertext=[], hoverinfo='text', legendgroup='uiti',
    ), 5, 4)
    _fig.update_yaxes(title_text='UITI acumulado', rangemode='tozero',
                      ticklabelstandoff=6, row=5, col=1)
    # `type='category'` y no el tipo automatico: estos cuatro paneles dibujan barras POR
    # VANO, pero arrancan VACIOS -- esperan a que se pulse Simular --, y un eje sin datos
    # ni tipo declarado cae a lineal y se inventa marcas de -1 a 6. Esa '-1' del origen
    # tocaba el '0' del eje y en la esquina. Un eje categorico vacio no dibuja ninguna.
    _fig.update_xaxes(title_text='Vano', type='category', tickfont=dict(size=9),
                      row=5, col=1)
    _fig.update_yaxes(rangemode='tozero', ticklabelstandoff=6, row=5, col=4)
    _fig.update_xaxes(type='category', tickfont=dict(size=9), row=5, col=4)
    _EJE_X_BARRAS = _fig.data[IDX['barra_observada']].xaxis or 'x'
    _EJE_Y_BARRAS = _fig.data[IDX['barra_observada']].yaxis or 'y'
    _fig.add_annotation(text='', xref=f'{_EJE_X_BARRAS} domain', yref=f'{_EJE_Y_BARRAS} domain',
                        x=0.5, y=0.5, showarrow=False, align='center',
                        font=dict(size=11, color='#747378'))
    IDX_ANOTACION_BARRAS = len(_fig.layout.annotations) - 1
    # El titulo del panel se reescribe en cada simulacion para publicar la reduccion, asi que
    # hace falta su indice. Se BUSCA por el texto con que nacio en vez de contar posiciones:
    # los titulos de subplot son las primeras anotaciones y su orden depende de la rejilla,
    # que ya cambio una vez.
    IDX_TITULO_BARRAS = next(
        i for i, _a in enumerate(_fig.layout.annotations)
        if (_a.text or '').startswith('UITI acumulado: medido'))

    # --- Fila 6: el costo de la intervencion ----------------------------------------------
    # Una barra por vano en las columnas 1-3 y el TOTAL del plan solo, en la 4 y con su propio
    # eje. Iban en la misma traza y en el mismo eje, y la razon para juntarlos era ver cuanto
    # pesa cada vano dentro del total; pero por eso mismo el total es SIEMPRE la barra mas
    # alta -- es la suma de las otras -- y dejaba a las de los vanos pegadas a la base, que es
    # donde se compara una obra con otra. Es la misma particion de la fila 4 y por la misma
    # razon. Lo que se pierde lo devuelve el hover del total, que dice sobre cuantos vanos se
    # reparte.
    # El color de la traza por vano sigue siendo un ARRAY y no un escalar: el repintado
    # escribe un color por barra, y volverlo escalar habria que deshacerlo el dia que un vano
    # tenga que destacarse entre los suyos.
    # El desglose por actividad viaja en el hover: el total contesta cuanto y el detalle
    # contesta por que, sin obligar a reabrir el panel para averiguarlo.
    IDX['costos'] = _agregar(go.Bar(
        x=[], y=[], name='Costo', showlegend=False, width=0.5,
        marker=dict(color=[], line=dict(width=0.4, color='rgba(60,10,10,0.6)')),
        text=[], textposition='outside', textfont=dict(size=10),
        hovertext=[], hoverinfo='text',
    ), 6, 1)
    IDX['costo_total'] = _agregar(go.Bar(
        x=[], y=[], name='Costo total', showlegend=False, width=0.5,
        marker=dict(color=COLOR_BARRA_TOTAL, line=dict(width=0.4, color='rgba(60,10,10,0.6)')),
        text=[], textposition='outside', textfont=dict(size=10),
        hovertext=[], hoverinfo='text',
    ), 6, 4)
    _fig.update_yaxes(title_text='COP', rangemode='tozero', tickformat=',.0f',
                      ticklabelstandoff=6, row=6, col=1)
    _fig.update_xaxes(title_text='Vano', type='category', row=6, col=1)
    # El panel del acumulado no repite el rotulo 'COP' -- lo dice el de al lado y son la misma
    # unidad --, pero si repite el formato de miles: sin el, la unica barra del panel se
    # rotularia en notacion cientifica.
    _fig.update_yaxes(rangemode='tozero', tickformat=',.0f', ticklabelstandoff=6,
                      row=6, col=4)
    _fig.update_xaxes(type='category', row=6, col=4)
    # El aviso de la fila 6 va anclado a SU eje, igual que el del grafo: antes de simular no
    # hay costo, y un panel vacio sin explicacion se lee como que la seleccion no cuesta nada.
    _EJE_X_COSTOS = _fig.data[IDX['costos']].xaxis or 'x'
    _EJE_Y_COSTOS = _fig.data[IDX['costos']].yaxis or 'y'
    _fig.add_annotation(text='', xref=f'{_EJE_X_COSTOS} domain', yref=f'{_EJE_Y_COSTOS} domain',
                        x=0.5, y=0.5, showarrow=False, align='center',
                        font=dict(size=11, color='#747378'))
    IDX_ANOTACION_COSTOS = len(_fig.layout.annotations) - 1

    # El aviso del mapa simulado va en coordenadas de PAPEL y no de eje: un subplot de tipo
    # `map` no tiene ejes cartesianos a los que anclar una anotacion. El centro sale del
    # dominio que `make_subplots` ya calculo, asi que cambiar `row_heights` no lo desalinea.
    _dominio_simulado = _fig.layout.map2.domain
    _fig.add_annotation(
        text='', xref='paper', yref='paper',
        x=(_dominio_simulado.x[0] + _dominio_simulado.x[1]) / 2.0,
        y=(_dominio_simulado.y[0] + _dominio_simulado.y[1]) / 2.0,
        showarrow=False, align='center', font=dict(size=13, color='#5b4a48'),
        bgcolor='rgba(255,255,255,0.88)', bordercolor='#cfe3ac', borderwidth=1, borderpad=8,
    )
    IDX_ANOTACION_SIMULADO = len(_fig.layout.annotations) - 1

    # El alto de la figura y, en unidades de papel, la banda que ocupan los titulos de los
    # mapas. Se despeja para que la leyenda, que sube encima de ellos, no se les monte.
    #
    # 26 px y no una fraccion escrita a ojo: la banda es TEXTO -- fuente 16 mas su relleno --
    # y mide lo mismo pase lo que pase con el alto de la figura. Dividirla aqui es lo que
    # mantiene la cuenta correcta el dia que el alto cambie.
    # 2.818: la fila 3 sigue a la mitad y entra la septima, la del grafo.
    #     area   = 1.695,6 (filas) + 6 x 162 (huecos) = 2.667,6
    #     height = 2.667,6 + 106 + 44 (margenes)      = 2.817,6 -> 2.818
    _ALTO_FIGURA = 2818
    _BANDA_TITULO_MAPAS = 26 / _ALTO_FIGURA

    _fig.update_layout(
        map=dict(style='carto-positron', center=dict(lat=5.07, lon=-75.52), zoom=10,
                 layers=CAPAS_CAJA_SELECCION),
        map2=dict(style='carto-positron', center=dict(lat=5.07, lon=-75.52), zoom=10,
                  layers=CAPAS_CAJA_SIMULADA),
        # SIN titulo de figura. "Simulador Criticidad" paso a ser un rotulo del ENCABEZADO,
        # encima del panel de control y a la izquierda del todo: dentro de la figura quedaba
        # centrado sobre el area de dibujo -- o sea a la derecha del panel, no encima -- y
        # ademas competia por el margen superior con la leyenda de los mapas, que subio a
        # ese mismo hueco. Ver `ENCABEZADO_TITULO`.
        #
        # Con el titulo fuera, el margen de arriba deja de tener que alojarlo: 132 - 22 de
        # titulo - 24 de su aire = 86, que es lo que piden la leyenda (67) y la banda de los
        # titulos de los mapas (19).
        # Margenes explicitos. Los de Plotly por defecto (l=80, r=80, t=100, b=80) se llevaban
        # 160 px de ancho -- medido, el 8,5% de una pantalla de 1.920 -- y a la derecha no hay
        # nada que rotular. El izquierdo NO puede bajar a cero: es donde viven el titulo y las
        # marcas del eje y de los paneles de la primera columna.
        # El margen de arriba sube de 78 a 132 px, y no es un numero redondo: es la suma de
        # lo que hay que apilar ahi, todo MEDIDO en el navegador.
        #
        #     leyenda horizontal, que envuelve en 3 filas   67 px
        #     banda de los titulos de los mapas             19
        #     aire entre las dos                            20
        #                                                  ---
        #                                                  106
        #
        # La leyenda son 67 px y no 20 porque son siete nombres con `tracegroupgap=22`: no
        # caben en una fila y Plotly las envuelve. Contar una sola fila fue lo que una vez
        # dejo el titulo de la figura dentro de la leyenda -- ese titulo ya no esta aqui.
        margin=dict(l=52, r=14, t=106, b=44),
        barmode='group', bargap=0.25, bargroupgap=0.05,
        # SIN `width`: con un ancho fijo Plotly ignora el contenedor. Pero dejarlo en None NO
        # basta por si solo -- `autosize` mide el contenedor UNA vez, al montar, y el widget
        # monta antes de que el CSS de la celda lo estire. Lo que cierra el circulo es
        # `responsive` en el config del widget, mas abajo.
        # 2.489 y no 3.003: el grafo comparte fila con el perfil y su septima fila
        # desaparece. Lo que se va son sus 235,2 px de la fila 3 vieja mas un hueco; el
        # grafo conserva sus 589,8 px porque la fila 3 los hereda. Ver `row_heights`.
        height=_ALTO_FIGURA, autosize=True, template='plotly_white',
        # La leyenda va HORIZONTAL y ENCIMA de los mapas, centrada entre los dos. Horizontal
        # porque vertical y a la derecha se llevaba 196 px medidos de ancho para decir siete
        # nombres. Encima porque abajo quedaba lejos de lo que nombra: entre los mapas y ella
        # se metia todo el alto de las dos filas del mapa.
        #
        # `y` sale del dominio del mapa y no de un numero escrito a mano: cambiar
        # `row_heights` mueve los mapas. Lo que se le suma es la BANDA DE LOS TITULOS: en
        # `domain.y[1]` -- el borde de arriba de los mapas -- ya estan "Criticidad Original"
        # y "Criticidad Simulada", anclados por abajo a esa misma linea. Anclar ahi la
        # leyenda la pondria encima de ellos.
        #
        # `x=0.5` es literalmente "entre los mapas": el primero acaba en 0.4225 y el segundo
        # empieza en 0.5175.
        legend=dict(orientation='h', x=0.5, xanchor='center',
                    y=_fig.layout.map.domain.y[1] + _BANDA_TITULO_MAPAS, yanchor='bottom',
                    font=dict(size=10), tracegroupgap=22),
    )

    # El alto en pixeles del panel del top. Va DESPUES de `update_layout` porque el alto de
    # la figura se fija alli: leido antes, `_fig.layout.height` todavia es None.
    # Es su dominio por el alto de la figura. Es lo que
    # permite decidir, barra por barra, si el nombre de la variable cabe escrito adentro --
    # el rotulo va girado -90, asi que lo que lo limita es el LARGO de la barra y no su ancho.
    # El eje se PREGUNTA a la traza en vez de escribirse a mano: su numero depende del eje
    # secundario de la fila 3, y adivinarlo mediria el panel equivocado.
    _EJE_Y_TOP = _fig.data[IDX['top_vano'][0]].yaxis or 'y'
    _DOMINIO_TOP = _fig.layout[_EJE_Y_TOP.replace('y', 'yaxis', 1)].domain
    ALTO_PANEL_TOP_PX = float(_fig.layout.height) * float(_DOMINIO_TOP[1] - _DOMINIO_TOP[0])

    # Y su ANCHO, que es el otro lado que limita al rotulo: va girado -90, asi que su
    # renglon se apoya contra el GROSOR de la barra. Este numero no se puede leer de la
    # figura como el alto -- no lleva `width`, la fija el contenedor --, asi que se MIDE en
    # el navegador sobre el caso mas ESTRECHO que el tablero soporta: ventana de 1.280 px,
    # figura de 875 y este panel en 719. Decidir con el ancho de una pantalla ancha
    # escribiria en una chica ochenta rotulos verticales unos sobre otros.
    #
    # Valia 360, de cuando este panel ocupaba una fraccion del ancho. Al mover el grafico a
    # las CUATRO columnas paso a ocuparlo casi entero y la suposicion se quedo a la mitad:
    # con 360 la compuerta de grosor calla desde TRES vanos y el diagnostico completa a
    # ocho, asi que el panel llevaba semanas con las 80 barras sin un solo rotulo. Suponer
    # de menos no es el lado seguro: apaga los rotulos que si caben.
    ANCHO_PANEL_TOP_PX_MINIMO = 719.0
    # `bargap=0.25` y `bargroupgap=0.05` salen del `update_layout` de arriba: a las barras
    # de un grupo les queda el 75% de su casilla, y de eso cada una pierde otro 5% en el
    # hueco con su vecina.
    FRACCION_UTIL_BARRA = (1.0 - 0.25) * (1.0 - 0.05)

    # Los indices se verifican al generar: si alguien reordena las trazas, esto falla AQUI y
    # no se descubre en silencio al dibujar.
    # El `+ 2` son las dos barras del acumulado del circuito, que salieron del panel de los
    # vanos a su propia columna; el `+ 2` final son la traza de costo por vano y la del
    # costo acumulado, que se partieron por la misma razon.
    # El `+ 1` del final es la barra del perfil del circuito, que es una sola traza.
    # El `+ 2 + len(MODALIDADES_MIL)` son las trazas del GRAFO: aristas, pesos y una por
    # modalidad, todas de vuelta en esta figura.
    assert len(_fig.data) == 4 + 1 + 1 + 4 + 1 + 4 + 1 + 4 + 2 * MAX_VANOS_SERIE \
        + TOP_VARIABLES_POR_VANO + 2 + 2 + len(MODALIDADES_MIL) + 2 + 2 + 1, len(_fig.data)
    assert _fig.layout.width is None and _fig.layout.height, (
        'la figura no puede llevar ancho fijo: con uno, Plotly ignora el contenedor. El alto '
        'si es propio. Cuidado: sin ancho fijo NO alcanza -- ver `responsive` abajo.')
    # El marcado con color de clase va DESPUES del halo blanco, o el halo lo taparia.
    assert min(IDX['marcados_clases']) > IDX['marcados']
    assert [_fig.data[i].line.color for i in IDX['marcados_clases']] == COLORES_GRUPOS
    # Los equipos son PUNTOS y van despues de todas las lineas: si alguien los adelanta,
    # quedan tapados por los tramos.
    assert all(_fig.data[i].mode == 'markers'
               for i in (IDX['trafos'], IDX['switches'], IDX['pred_trafos'], IDX['pred_switches']))
    assert min(IDX['trafos'], IDX['pred_trafos']) > max(IDX['pred_clases'])
    # UN solo negro para la ausencia en los DOS mapas.
    assert (_fig.data[IDX['sin_dato']].line.color
            == _fig.data[IDX['pred_sin_dato']].line.color == COLOR_SIN_EVENTO)
    assert all(isinstance(_fig.data[i].marker.size, (list, tuple))
               for i in IDX['serie_uiti'] + IDX['serie_eventos']), (
        'marker.size debe ser un array: el punto de la ventana vigente va al triple')
    assert all(_fig.data[i].type == 'bar' for i in IDX['top_vano'])
    # El perfil es un panel PROPIO y no comparte eje con nadie: si alguien lo devuelve a la
    # fila de la serie de tiempo, el total del periodo -- que es la suma de once ventanas --
    # aplasta a la serie contra la base sin que nada mas falle. Es la misma leccion que ya
    # separo el acumulado del circuito de las barras por vano.
    assert _fig.data[IDX['perfil_circuito']].type == 'bar'
    assert _fig.data[IDX['perfil_circuito']].yaxis not in {
        _fig.data[IDX['serie_uiti'][0]].yaxis, _fig.data[IDX['barra_observada']].yaxis}
    # Eje de CATEGORIAS: con uno numerico las quince barras se separarian por el valor del
    # fid y el ranking dejaria de leerse como ranking.
    assert _fig.layout[
        (_fig.data[IDX['perfil_circuito']].xaxis or 'x').replace('x', 'xaxis', 1)
    ].type == 'category'
    assert _fig.layout.barmode == 'group', 'las barras del top 5 se agrupan POR VANO'
    assert all(_fig.data[i].type == 'bar'
               for i in (IDX['barra_observada'], IDX['barra_simulada']))
    # La barra de error existe desde el armado: llenarla en el repintado es escribir un
    # array, no crear la propiedad, que es lo que mantiene el repintado en una sola pasada.
    assert _fig.data[IDX['barra_simulada']].error_y.visible is True
    # El color de la barra de costo por vano es un ARRAY: el repintado escribe un color por
    # barra, y con un escalar habria que volver a partirlo para destacar un vano.
    assert _fig.data[IDX['costos']].type == _fig.data[IDX['costo_total']].type == 'bar'
    assert isinstance(_fig.data[IDX['costos']].marker.color, (list, tuple))
    # Y el acumulado tiene EJE PROPIO: si vuelve a compartirlo con los vanos, su barra --
    # la suma de las otras -- los aplasta contra la base sin que nada mas falle.
    assert _fig.data[IDX['costo_total']].yaxis != _fig.data[IDX['costos']].yaxis
    # El estilo del mapa es el de 01: mismos equipos, mismo ancho de vano con eventos y misma
    # linea de estructura para el vano que en esta ventana no tiene ninguna celda.
    assert (_fig.data[IDX['trafos']].marker.size,
            _fig.data[IDX['switches']].marker.size) == (TAM_TRAFO, TAM_SWITCH) == (14, 12)
    assert all(_fig.data[i].line.width == ANCHO_MAPA == 7.0
               for i in IDX['clases'] + IDX['pred_clases'])
    assert (_fig.data[IDX['sin_dato']].line.width
            == _fig.data[IDX['pred_sin_dato']].line.width == ANCHO_SIN_EVENTOS == 1.5)
    assert [_fig.data[i].name for i in IDX['grafo_nodos']] == MODALIDADES_MIL
    # El recuadro de seleccion es una CAPA del mapa y no una traza, y va DEBAJO de las trazas:
    # si alguien lo sube por encima vuelve a comerse el clic que alterna la seleccion. El mapa
    # base lleva CINCO -- una por grupo KMeans mas la del marcado sin celda -- y el simulado
    # TRES, una por desenlace, porque una capa pinta con un solo color.
    assert len(_fig.layout.map.layers) == len(CLASES_CAJA) == 5
    assert len(_fig.layout.map2.layers) == len(CAMBIOS)
    # El relleno del recuadro tiene que ser EL MISMO color con que la linea pinta ese grupo.
    # Si se separan, el mismo vano queda encerrado en un color y trazado en otro, y el
    # recuadro pasa de reforzar la lectura a contradecirla.
    assert [_fig.layout.map.layers[IDX_CAPA_CLASE[_c]].color for _c in range(4)] \
        == [_fig.data[_i].line.color for _i in IDX['clases']] == COLORES_GRUPOS
    assert _fig.layout.map.layers[IDX_CAPA_CLASE[None]].color == COLOR_SIN_GRUPO
    assert all(_capa.opacity == OPACIDAD_CAJA_SELECCION == 0.5
               for _capa in _fig.layout.map.layers)
    assert all(_capa.below == 'traces'
               for _capa in (*_fig.layout.map.layers, *_fig.layout.map2.layers))
    assert ALTO_PANEL_TOP_PX > 0, 'sin alto de panel no se puede decidir si el rotulo cabe'

    # `figura_de_mapas` y no `go.FigureWidget` a secas: con plotly 6.8.0, arrastrar o hacer
    # zoom sobre un mapa MapLibre devuelve `map._derived` -- las esquinas que MapLibre acaba de
    # calcular -- junto a `map.center` y `map.zoom`, y `plotly_relayout` lo rechaza con
    # `Invalid property path 'map._derived' for layout`. El error salta en CADA arrastre y sale
    # en la salida de la celda que muestra el widget, por encima del tablero, asi que se lee
    # como si una celda anterior se hubiera roto.
    fig = figura_de_mapas(_fig)
    # Un `FigureWidget` NO es fluido por si solo: `width=None` mas `autosize` mas el CSS de la
    # celda estiran el DIV, pero plotly sigue DIBUJANDO al ancho que midio al montar -- medido,
    # 858 px dentro de un contenedor de 1.935. Su bundle trae un `ResizeObserver` que arregla
    # exactamente esto, apagado detras de `config.responsive`. `_config` es un trait
    # SINCRONIZADO: lo que se ponga aqui viaja al `newPlot` del navegador y lo enciende.
    fig._config = {**(fig._config or {}), 'responsive': True}
    assert fig._config.get('responsive') is True, (
        'sin `responsive` el FigureWidget dibuja al ancho de reserva y no al de la celda')

    # --- Fila 1: mapa historico con paridad 01.4 + seleccion por casilla o por clic ------
    # Tres cosas que el mapa de 01.4 hace y este no hacia: se ENCUADRA sobre el circuito
    # elegido (sin eso el circuito queda como un garabato diminuto en un mapa centrado en
    # Manizales), dibuja transformadores e interruptores, y da hover por tramo. La cuarta es
    # la seleccion: en 01.4 un vano se marca con su casilla O tocandolo en el mapa, y las dos
    # vias son EL MISMO estado -- el clic alterna la casilla y deja que todo se rehaga desde
    # ahi. Un registro paralelo es como la lista, el mapa y el ranking empiezan a contar
    # cosas distintas.


    def _seleccion_actual():
        return circuito_widget.value, ventana_widget.value, set(vano_widget.value)


    def _plantilla_hover(campo, nombre_clase, ventana, *, marcado=False, extra=''):
        """El tooltip de una traza, como `hovertemplate` y no como texto por punto.

    Lo que varia DENTRO de una traza son solo el fid, el UITI y los eventos, y esos
    viajan crudos en `customdata`. La clase y la ventana son constantes de la traza --
    hay una traza por clase-- asi que van escritas en la plantilla y no se repiten en
    cada punto. Esa diferencia es la que permite densificar: medido sobre el peor
    circuito, repetir la etiqueta formateada cuesta 2,40 MB por capa y esto cuesta 0,66.

    `extra` agrega renglones que SI varian punto a punto y por eso citan `customdata`:
    es como el mapa simulado dice el grupo base de cada vano, que dentro de una traza --
    que es una clase SIMULADA -- cambia de vano a vano.
    """
        return (f'<b>Vano %{{customdata[0]}}</b><br>{ventana["etiqueta"]}: {ventana["periodo"]}'
                f'<br>{campo}: {nombre_clase}{extra}'
                '<br>UITI acumulado: %{customdata[1]}<br>Eventos: %{customdata[2]}'
                + ('<br>(marcado)' if marcado else '') + '<extra></extra>')


    def _capas_de_la_seleccion(clases_por_fid, *, campo, nombres_clase,
                               extra_por_fid=None, plantilla_extra=''):
        """Las capas de UN mapa, con el customdata que alimentan el tooltip y el clic.

    `campo` nombra en el tooltip a que pertenece la clase -- "Criticidad original" en
    la fila 1, "Criticidad simulada" en la fila 2.

    `extra_por_fid` agrega columnas al `customdata` de cada punto, para lo que varia
    dentro de una traza y no cabe en la plantilla. `plantilla_extra` es el renglon del
    tooltip que las lee.

    `paso_densificado` interpola vertices cada ~25 m. El hover de una traza de lineas en
    Scattermap se resuelve contra los VERTICES, y los tramos de MVLINSEC traen
    exactamente dos: sin esto, el centro de un vano no muestra etiqueta, y como Plotly
    solo convierte un clic en evento donde hay hover, tampoco se puede marcar tocandolo
    ahi. Es la misma correccion que ya tenia el mapa de 01.
    """
        circuito, ventana_i, marcados = _seleccion_actual()
        geo = GEO_POR_CIRCUITO.get(circuito, {'fids': [], 'lat': [], 'lon': []})
        ventana = VENTANAS[ventana_i]
        datos = DATOS_VENTANA[ventana_i]

        # Datos CRUDOS por vano; el formato lo pone la plantilla de cada traza.
        datos_por_fid = {fid: datos.get(fid, (0.0, 0)) for fid in geo['fids']}
        if extra_por_fid is not None:
            # La columna extra viaja para TODOS los fids y no solo para los que la tienen:
            # dentro de una traza `customdata` tiene que medir siempre lo mismo, o
            # `%{customdata[3]}` cae en el hueco del vano de al lado.
            datos_por_fid = {fid: (*crudos, *extra_por_fid.get(fid, ('sin dato',)))
                             for fid, crudos in datos_por_fid.items()}
        capas = capas_mapa_historico(
            geo, clases_por_fid, marcados=marcados, datos_por_fid=datos_por_fid,
            marca_extremos=MARCA_VANO, paso_densificado=PASO_VERTICE)
        # Sin celda en la ventana no hay clase, y eso NO es el grupo mas bajo: es la
        # ausencia del dato. Mismo criterio que el tooltip de 01.4.
        sin_dato = 'sin dato'
        capas['plantillas'] = {
            'clases': [_plantilla_hover(campo, nombres_clase[c], ventana,
                                        extra=plantilla_extra) for c in range(4)],
            'sin_dato': _plantilla_hover(campo, sin_dato, ventana, extra=plantilla_extra),
            'marcados_por_clase': [_plantilla_hover(campo, nombres_clase[c], ventana,
                                                    marcado=True, extra=plantilla_extra)
                                   for c in range(4)],
            'marcados_sin_dato': _plantilla_hover(campo, sin_dato, ventana, marcado=True,
                                                  extra=plantilla_extra),
        }
        return capas


    def _volcar_capa(traza, capa, plantilla=None):
        """Las tres columnas van juntas SIEMPRE: si `customdata` se desfasa de lat/lon,
    Plotly desalinea el resto de la traza y el clic devuelve el vano equivocado.

    `plantilla` es el `hovertemplate` de la traza. Sin ella la traza no muestra tooltip
    -- es lo que corresponde al halo blanco, que es decoracion y esta debajo de la linea
    de color, que si lo muestra."""
        traza.lat = capa['lat']
        traza.lon = capa['lon']
        traza.customdata = capa['customdata']
        if plantilla is None:
            traza.hoverinfo = 'skip'
        else:
            traza.hovertemplate = plantilla


    def _tamanos_ventana_activa(ventana_i):
        """El arreglo de tamanos de marcador de las dos series, con la ventana vigente al
    triple. Es el mismo recurso de la serie del cuaderno 01: `marker.size` es un ARRAY,
    asi que agrandar un punto no obliga a partir la serie en una segunda traza, y mover
    el deslizador solo reescribe once numeros."""
        return (
            [SERIE_TAM_UITI * (FACTOR_PUNTO_ACTIVO if v['i'] == ventana_i else 1)
             for v in VENTANAS],
            [SERIE_TAM_EVENTOS * (FACTOR_PUNTO_ACTIVO if v['i'] == ventana_i else 1)
             for v in VENTANAS],
        )


    # Red de seguridad: cuantos de los vanos marcados puede puntuar el modelo en la ventana
    # activa. Vuelve a tener trabajo real desde que la lista ofrece los vanos con eventos en
    # TODO el dataset: marcar un vano que en esta ventana no tuvo ninguno es ahora un caso
    # normal y legitimo -- su serie de tiempo es justo donde se ve en que ventana si los tuvo
    # --, pero "Simular" no puede puntuarlo, y eso hay que decirlo antes de pulsar el boton y
    # no despues.
    #
    # Las dos cuentas salen de sitios distintos -- la lista, de `VANOS_POR_CIRCUITO`; esta,
    # de `clases_para` en el repintado --, que es lo que la vuelve una comprobacion y no una
    # repeticion.
    AVISO_VANOS = widgets.HTML('')


    def _actualizar_aviso_vanos(clases_por_fid, marcados):
        """El renglon que dice cuantos de los vanos marcados tienen eventos en la ventana.

    `clases_por_fid` trae UNA entrada por vano con celda en esa ventana -- verificado
    contra `seleccionar_bolsas` en doce circuitos: los dos conjuntos coinciden exactamente
    --, asi que sirve de fuente sin volver a resolver las bolsas, que es trabajo del
    boton "Simular" y no de un repintado.

    Dice ademas cuando la seleccion pasa de `MAX_VANOS_SERIE`. Ahi el mapa sigue
    resaltando todos los marcados y el simulador sigue puntuandolos, pero la serie de
    tiempo solo tiene ranuras para los primeros: el numero de trazas de la figura se fija
    al construirla. Recortar en silencio es lo unico que no se puede hacer.
    """
        if not marcados:
            AVISO_VANOS.value = ''
            return
        con_datos = {str(f) for f in clases_por_fid}
        cuantos = sum(1 for f in marcados if str(f) in con_datos)
        sobran = len(marcados) - MAX_VANOS_SERIE
        exceso = (f' Ademas hay {sobran} mas de los {MAX_VANOS_SERIE} que caben dibujados: '
                  'el mapa los resalta y el simulador los puntua, pero su serie de tiempo no '
                  'se dibuja.' if sobran > 0 else '')
        if cuantos == len(marcados):
            AVISO_VANOS.value = (
                f'<span style="font-size:12px;color:#5b4a48;">Los {len(marcados)} vanos '
                f'marcados tienen eventos en la ventana activa.{exceso}</span>'
                if exceso else '')
        elif cuantos:
            AVISO_VANOS.value = (
                f'<span style="font-size:12px;color:#5b4a48;"><b>{cuantos}</b> de los '
                f'{len(marcados)} vanos marcados tienen eventos en la ventana '
                f'activa.{exceso}</span>')
        else:
            AVISO_VANOS.value = (
                '<span style="font-size:12px;color:#c62828;">Ninguno de los '
                f'{len(marcados)} vanos marcados registra eventos en la ventana activa: '
                '<b>"Simular" no va a puntuar nada</b>. Mueve la ventana o marca otros '
                f'vanos.{exceso}</span>')


    # Cambiar de circuito o mover la ventana mueve DOS cosas -- la lista de vanos marcables y
    # el mapa --, y cada una dispara su propio repintado con el mismo resultado. Este
    # interruptor deja que el manejador las ordene: repuebla en silencio y repinta UNA vez al
    # final. Repintar el mapa reescribe las once trazas de tramos del circuito, asi que
    # ahorrar dos pasadas por paso del deslizador es lo que separa arrastrarlo de esperarlo.
    _REPINTADO_EN_PAUSA = False


    def _redibujar_mapa_historico(*_ignorado):
        if _REPINTADO_EN_PAUSA:
            return
        circuito, ventana_i, _marcados = _seleccion_actual()
        clases_por_fid = clases_para(circuito, ventana_i)
        _actualizar_aviso_vanos(clases_por_fid, _marcados)
        capas = _capas_de_la_seleccion(clases_por_fid,
                                       campo='Criticidad original', nombres_clase=NOMBRES_GRUPOS)
        # El orden de las series sale de la GEOMETRIA y no del orden en que se fueron
        # marcando: asi marcar y desmarcar no baraja los colores bajo la mano.
        marcados_ordenados = [f for f in GEO_POR_CIRCUITO.get(circuito, {}).get('fids', [])
                              if f in _marcados]
        marcados_ordenados = list(dict.fromkeys(marcados_ordenados))[:MAX_VANOS_SERIE]
        # La serie describe SOLO los vanos elegidos: sin ninguno marcado queda vacia. Es el
        # mismo criterio que los violines de 01.4 -- una serie sobre el circuito entero y una
        # sobre tres vanos se dibujan igual y no miden lo mismo, asi que caer al circuito
        # cambiaria el sujeto del panel en silencio.
        series = series_temporal_vanos(TABLA, circuito=circuito, fids=marcados_ordenados,
                                       n_ventanas=len(VENTANAS))
        # El grupo de riesgo de cada punto, de UNA sola llamada a la geometria de 01.4 para
        # los hasta 55 puntos dibujados. El repintado corre en cada clic del mapa.
        clases_serie = clases_de_series(series)
        _pl = capas['plantillas']
        with fig.batch_update():
            for _clase in range(4):
                _volcar_capa(fig.data[IDX['clases'][_clase]], capas['clases'][_clase],
                             _pl['clases'][_clase])
                _volcar_capa(fig.data[IDX['marcados_clases'][_clase]],
                             capas['marcados_por_clase'][_clase],
                             _pl['marcados_por_clase'][_clase])
            _volcar_capa(fig.data[IDX['sin_dato']], capas['sin_dato'], _pl['sin_dato'])
            # El halo blanco va SIN tooltip: esta debajo de la linea de color, que ya lo
            # muestra, y dos etiquetas en el mismo punto solo se estorban.
            _volcar_capa(fig.data[IDX['marcados']], capas['marcados'])
            _volcar_capa(fig.data[IDX['marcados_sin_dato']], capas['marcados_sin_dato'],
                         _pl['marcados_sin_dato'])
            # El recuadro de lo seleccionado, repartido en las cinco capas por el GRUPO
            # KMeans del vano en esta ventana: el relleno lleva el mismo color que su linea,
            # al 50%. Sale de la GEOMETRIA y no de las celdas, asi que el recuadro sigue
            # puesto al mover el deslizador incluso sobre un vano que en esa ventana no tiene
            # ni un evento -- ese va a la capa `None`, gris, porque no tiene grupo.
            #
            # Se apaga SOLO al desmarcar el vano, por su casilla o volviendo a tocarlo en el
            # mapa. Y al desmarcarlo no se pierde nada mas: el color y el ancho de la linea
            # dependen de `clases_por_fid` y no de la seleccion, asi que el vano se queda
            # dibujado con el color de su grupo, solo que sin recuadro y sin halo.
            _cajas = cajas_seleccion_por_clase(
                GEO_POR_CIRCUITO.get(circuito, {'fids': [], 'lat': [], 'lon': []}),
                clases_por_fid, marcados=_marcados,
                lado_minimo=LADO_MINIMO_CAJA, margen=MARGEN_CAJA)
            for _clase, _coleccion in _cajas.items():
                fig.layout.map.layers[IDX_CAPA_CLASE[_clase]].source = _coleccion
            # Fila 3 col 1-2: la serie de tiempo de cada vano elegido, UITI contra el eje
            # izquierdo y eventos contra el derecho. Una ventana sin celda va como `None` y
            # NO como cero: un cero se leeria como "no hubo UITI", y lo que paso es que no
            # hubo medicion. `connectgaps=False` corta la linea ahi.
            _tam_uiti, _tam_eventos = _tamanos_ventana_activa(ventana_i)
            for _cupo in range(MAX_VANOS_SERIE):
                _serie = series[_cupo] if _cupo < len(series) else None
                _t_uiti = fig.data[IDX['serie_uiti'][_cupo]]
                _t_eventos = fig.data[IDX['serie_eventos'][_cupo]]
                _sujeto = f'Vano {_serie["fid"]}' if _serie else ''
                _clases = clases_serie[_cupo] if _cupo < len(clases_serie) else []
                # El relleno del punto lleva el grupo de riesgo de ESE vano en ESA ventana;
                # el gris es la ventana sin celda, que no tiene grupo.
                _colores = [COLORES_GRUPOS[c] if c is not None else COLOR_SIN_GRUPO
                            for c in _clases]
                _etiquetas = ([
                    f'<b>{_sujeto}</b><br>{VENTANAS[i]["etiqueta"]}: '
                    f'{VENTANAS[i]["periodo"]}<br>UITI: {u}<br>Eventos: {e}'
                    f'<br>Grupo: {NOMBRES_GRUPOS[c] if c is not None else "sin eventos"}'
                    for i, u, e, c in zip(_serie['x'], _serie['uiti'], _serie['eventos'],
                                          _clases)
                ] if _serie else [])
                _t_uiti.x = _serie['x'] if _serie else []
                _t_uiti.y = _serie['uiti'] if _serie else []
                _t_uiti.hovertext = _etiquetas
                _t_uiti.marker.size = _tam_uiti if _serie else []
                _t_uiti.marker.color = _colores
                _t_uiti.name = _sujeto
                _t_eventos.x = _serie['x'] if _serie else []
                _t_eventos.y = _serie['eventos'] if _serie else []
                _t_eventos.hovertext = _etiquetas
                _t_eventos.marker.size = _tam_eventos if _serie else []
                _t_eventos.marker.color = _colores


    def _alto_del_mapa_px():
        """El alto en pixeles del subplot de mapa, de su dominio por el alto de la figura.

    Sin esto el zoom salia del span en GRADOS, sin mirar el viewport, y un circuito alto
    quedaba recortado arriba y abajo."""
        _dom_y = fig.layout.map.domain.y
        return float(fig.layout.height) * float(_dom_y[1] - _dom_y[0])


    def _ancho_del_mapa_px():
        """El ancho que se ASUME para el subplot de mapa. Es un suelo, no una medida.

    Con `autosize` el ancho real lo decide el navegador y el cuaderno no lo conoce.
    Durante un tiempo eso se resolvio no encuadrando por el ancho -- solo por el alto --
    y el resultado fue el defecto que este suelo corrige: un circuito cuya caja es mas
    ANCHA que alta, despues de Mercator, se salia por los lados sin que nada avisara, y
    el mapa se leia como que no habia ido al circuito que se pidio.

    Medido conduciendo el tablero en Chrome: al abrir en AGU23L12 solo el 4,2% de los
    vertices dibujados caia dentro del recuadro visible, con las trazas llenas y el
    lienzo pintando. Contado sobre los 208 circuitos con geometria y este subplot de
    566 px de alto, se salian 94 con el mapa a 566 px de ancho, 57 a 700 px y todavia
    21 a 1.020 px -- o sea, ni en una pantalla de 2.370 px desaparecia.

    El suelo es el ALTO: el panel ocupa dos de las cuatro columnas, asi que es al menos
    cuadrado en cualquier ventana de 1.345 px para arriba, y por debajo el encuadre se
    degrada en vez de romperse. `centro_y_zoom` toma la restriccion que se queda sin
    sitio primero, de modo que agregar esta solo puede ALEJAR el zoom: un circuito que ya
    cabia a lo ancho no cambia de encuadre.

    La contrapartida asumida: en una pantalla ancha un circuito ancho se dibuja mas
    pequenio de lo que cabria. Se prefiere verlo entero y pequenio que grande y cortado,
    que es lo que se estaba viendo.
    """
        return _alto_del_mapa_px()


    def _vista_del_circuito(circuito):
        """El encuadre del circuito completo, o None si no tiene geometria. Es la vista de
    referencia de los dos mapas y la que el simulado recupera cuando no hay nada marcado
    sobre lo que acercarse."""
        return centro_y_zoom(GEO_POR_CIRCUITO.get(circuito, {}).get('bounds'),
                             ancho_px=_ancho_del_mapa_px(),
                             alto_px=_alto_del_mapa_px())


    def _aplicar_vista(nombre_mapa, vista):
        if vista is not None:
            getattr(fig.layout, nombre_mapa).center = vista['center']
            getattr(fig.layout, nombre_mapa).zoom = vista['zoom']


    def _centrar_mapa(nombre_mapa):
        """Encuadra ESE mapa sobre los vanos marcados, o sobre el circuito si no hay ninguno.

    Existe porque las dos vistas se van de sitio por caminos legitimos: el usuario hace
    zoom para mirar un tramo, o el mapa simulado se acerca solo a los vanos que puntuo y
    deja de compartir geografia con el de la izquierda. Volver no deberia obligar a
    recargar la celda ni a cambiar de circuito y regresar.

    La vista se calcula EN EL CLIC y no se guarda al dibujar: entre un dibujo y el clic
    pueden haber cambiado los vanos marcados, y un encuadre precalculado llevaria a donde
    estaba la seleccion antes.
    """
        circuito, _ventana_i, marcados = _seleccion_actual()
        geo = GEO_POR_CIRCUITO.get(circuito, {'fids': [], 'lat': [], 'lon': []})
        _aplicar_vista(nombre_mapa,
                       centro_y_zoom(bounds_de_fids(geo, marcados),
                                     ancho_px=_ancho_del_mapa_px(),
                                     alto_px=_alto_del_mapa_px())
                       or _vista_del_circuito(circuito))


    def _encuadrar_ventana(circuito, ventana_i):
        """Lleva el mapa base a los vanos CON eventos en la ventana activa.

    Mover el deslizador repintaba sin mover. Medido en el navegador sobre
    AGU23L12, pasar de V11 a V1 redistribuia las capas de clase -- 0,51,30,0,828
    a 42,213,0,0,654 -- y cambiaba la leyenda, pero dejaba `center` y `zoom`
    identicos. Como el 86% del dibujo es la linea negra de "sin evento", lo unico
    que cambiaba era el color de unos pocos tramos cortos, y el tablero se leia
    como que el deslizador no hacia nada.

    El encuadre sale de los MISMOS vanos que la lista ofrece -- los que tienen
    celda en esa ventana --, asi que las dos mitades del panel contestan la misma
    pregunta: esto es lo que paso aqui en este periodo.

    Contrapartida asumida: el mapa base deja de ser la vista fija del circuito
    entero contra la que se leia el acercamiento del mapa simulado. El boton
    "Centrar mapa base" sigue devolviendo esa vista de un clic, y cambiar de
    circuito tambien -- `_pintar_circuito` encuadra el circuito completo --, asi
    que la referencia no se pierde: deja de ser lo que impone el deslizador.

    Una ventana sin un solo evento cae a la vista del circuito y no a un punto
    inventado, que es el mismo contrato que `centro_y_zoom` con bounds vacios.
    """
        geo = GEO_POR_CIRCUITO.get(circuito, {'fids': [], 'lat': [], 'lon': []})
        _aplicar_vista('map',
                       centro_y_zoom(bounds_de_fids(geo, clases_para(circuito, ventana_i)),
                                     ancho_px=_ancho_del_mapa_px(),
                                     alto_px=_alto_del_mapa_px())
                       or _vista_del_circuito(circuito))


    # Cuantas ventanas hacen falta para cubrir el periodo sin contar un evento dos
    # veces. Es el denominador del hover del perfil ("en 2 de 6 ventanas"), y se
    # calcula UNA vez: no depende del circuito ni de la barra.
    VENTANAS_DEL_PERIODO = len(ventanas_sin_traslape(VENTANAS))


    def _pintar_perfil_del_circuito(circuito):
        """La fila 3: los vanos que mas UITI acumulan en TODA la serie del circuito.

    Depende SOLO del circuito -- ni de la ventana ni de lo que este marcado --, asi
    que se repinta una vez por cambio de circuito y no en cada paso del deslizador
    ni en cada casilla. Es deliberado: el panel esta para leerse ANTES de tomar esas
    dos decisiones, y repintarlo con ellas lo convertiria en otro panel de seleccion,
    que ya hay cuatro.

    El total de cada vano NO es la suma de sus `uiti_acumulado` sobre las once
    ventanas: se traslapan y esa suma cuenta casi todo evento dos veces.
    `perfil_uiti_por_vano` suma solo sobre las que embaldosan el periodo una vez.
    """
        perfil = perfil_uiti_por_vano(TABLA, circuito, ventanas=VENTANAS,
                                      top=TOP_VANOS_PERFIL)
        traza = fig.data[IDX['perfil_circuito']]
        if perfil.empty:
            traza.x, traza.y, traza.hovertext = [], [], []
            fig.layout.annotations[IDX_TITULO_PERFIL].text = (
                'Perfil del circuito - sin eventos en el periodo')
            return

        # El denominador son TODOS los vanos del circuito con eventos, no los quince
        # dibujados: la frase del titulo dice cuanto del circuito cabe en el panel, y
        # sobre los dibujados diria siempre el 100%.
        vanos_del_circuito = len(perfil_uiti_por_vano(TABLA, circuito, ventanas=VENTANAS))
        concentracion = 100.0 * float(perfil['participacion'].sum())

        traza.x = perfil['FID_VANO'].tolist()
        traza.y = perfil['uiti_total'].tolist()
        traza.hovertext = [
            f'<b>Vano {fid}</b><br>UITI acumulado del periodo: {uiti:,.1f}'
            f'<br>{ev:,} evento(s) en {nv} de {VENTANAS_DEL_PERIODO} ventanas'
            f'<br>{100.0 * part:.1f}% del UITI del circuito'
            for fid, uiti, ev, nv, part in zip(
                perfil['FID_VANO'], perfil['uiti_total'], perfil['num_eventos'],
                perfil['n_ventanas'], perfil['participacion'])
        ]
        fig.layout.annotations[IDX_TITULO_PERFIL].text = (
            # Corto a proposito: comparte fila con el grafo y a 1.280 y 1.512 px los dos
            # titulos se tocaban. Los tres numeros que importan siguen aqui.
            f'Perfil - {len(perfil)} de {vanos_del_circuito} vanos: '
            f'{concentracion:.1f}% del UITI')


    def _pintar_circuito(*_ignorado):
        """Lo que depende del CIRCUITO y no de la ventana: equipos y encuadre.

    El encuadre de aqui es el del circuito COMPLETO, y es la vista con la que se
    aterriza en un circuito nuevo: primero la panoramica, y a partir de ahi el
    deslizador acerca a cada periodo (`_encuadrar_ventana`). Los equipos van
    aparte porque no dependen de la ventana: repintarlos en cada paso del
    deslizador seria trabajo que nunca cambia de resultado."""
        circuito = circuito_widget.value
        tr = TRAFOS.get(circuito, {'lat': [], 'lon': []})
        sw = SWITCHES.get(circuito, {'lat': [], 'lon': []})
        vista = _vista_del_circuito(circuito)
        with fig.batch_update():
            # Solo la fila 1: los equipos de la fila 2 los pinta el mapa simulado, que antes
            # de la primera simulacion no muestra NADA.
            for _i_tr, _i_sw in ((IDX['trafos'], IDX['switches']),):
                fig.data[_i_tr].lat, fig.data[_i_tr].lon = tr['lat'], tr['lon']
                fig.data[_i_tr].hovertext = ['<b>Transformador</b>'] * len(tr['lat'])
                fig.data[_i_sw].lat, fig.data[_i_sw].lon = sw['lat'], sw['lon']
                fig.data[_i_sw].hovertext = ['<b>Interruptor / switch</b>'] * len(sw['lat'])
            # Los dos arrancan sobre el circuito completo. Despues, cada uno sigue su
            # propia pregunta: el de la derecha se acerca a los vanos marcados (ver
            # `_redibujar_mapa_predicho`) y el de la izquierda a los vanos con eventos
            # de la ventana activa (`_encuadrar_ventana`). Esta vista panoramica se
            # recupera con el boton "Centrar mapa base" o volviendo a este circuito.
            for _mapa in ('map', 'map2'):
                _aplicar_vista(_mapa, vista)
            # Dentro del MISMO `batch_update` que los equipos y el encuadre: son tres
            # cambios que responden al mismo clic, y cada `batch_update` que se abre es
            # un mensaje al navegador que cuesta lo suyo aunque lleve poco dato.
            _pintar_perfil_del_circuito(circuito)


    _DESC = {'description_width': 'initial'}  # sin esto ipywidgets trunca los rotulos
    circuito_widget = widgets.Dropdown(options=CIRCUITOS, description='Circuito',
                                       style=_DESC)
    # El rotulo lleva las fechas del intervalo y no solo "V1": una ventana sin sus fechas
    # obliga a ir a buscar a que periodo corresponde cada vez que se mueve el deslizador.
    def _opciones_de_ventana(circuito):
        """Las ventanas que ESE circuito puede mostrar, como pares (rotulo, indice).

    El rotulo lleva las fechas del intervalo y no solo "V1": una ventana sin sus fechas
    obliga a ir a buscar a que periodo corresponde cada vez que se mueve el deslizador.

    Nunca vacia: un `SelectionSlider` sin opciones lanza al construirse, y un circuito
    sin ninguna celda dejaria el panel sin arrancar. En ese caso el deslizador ofrece la
    primera ventana, y el mapa dira por su cuenta que no hay nada que pintar.
    """
        indices = VENTANAS_POR_CIRCUITO.get(circuito) or [0]
        return [(f'{VENTANAS[i]["etiqueta"]}: {VENTANAS[i]["periodo"]}', i) for i in indices]


    # Arranca en la ULTIMA ventana del circuito, no en la primera: es el periodo mas reciente
    # con eventos, y es la pregunta con la que se abre el tablero -- como esta esto AHORA. La
    # primera ventana es historia, y quien la quiera la alcanza moviendo el deslizador.
    # `_opciones_de_ventana` nunca devuelve vacio, asi que `[-1]` siempre existe.
    _OPCIONES_INICIALES = _opciones_de_ventana(circuito_widget.value)
    ventana_widget = widgets.SelectionSlider(
        options=_OPCIONES_INICIALES, value=_OPCIONES_INICIALES[-1][1],
        description='Ventana', continuous_update=False, style=_DESC,
        layout=widgets.Layout(width='560px'),
    )
    # Casillas, no SelectMultiple: es la unica forma de que un clic en el mapa alterne el
    # MISMO control que el usuario ve, y de que marcar un vano no borre los ya marcados.
    #
    # SIN tope. Lo tuvo -- `maximo=MAX_VANOS_ANALISIS` --, y lo que protegia era la rejilla de
    # controles de mas abajo, donde cada vano marcado recibe su propia COLUMNA. Eso hoy lo
    # resuelve la paginacion (`VANOS_POR_PAGINA`), y a cambio el tope hacia dos cosas que si
    # estorban: deshabilitaba las casillas sin marcar en cuanto la auto-marca de la ventana
    # llenaba el cupo -- o sea, casi siempre --, y `alternar` rechazaba en silencio el clic en
    # el mapa. Agregar un vano que llamo la atencion es exactamente lo que el mapa esta ahi
    # para permitir, y con el cupo lleno era imposible sin desmarcar otro primero.
    def _vanos_marcables(circuito):
        """TODOS los vanos de ESE circuito que registraron eventos en el dataset.

    No depende de la ventana, y ese es el cambio. Antes la lista se recortaba a los
    vanos con celda en la ventana activa, con un argumento razonable -- que puedo
    simular aqui y ahora -- y una consecuencia que resulto peor: la lista se rehacia
    entera en cada paso del deslizador, asi que las casillas cambiaban de sitio bajo la
    mano y un vano que se venia siguiendo desaparecia al mover un mes.

    Con la lista fija, el deslizador mueve la SELECCION (ver `_auto_seleccion_ventana`)
    y no el universo. La lista es el circuito; la ventana es el foco. Y es ademas lo que
    ya hacia el tablero de 04, que es de donde sale el mapa de esta fila: dos tableros
    sobre el mismo circuito no pueden ofrecer dos listas distintas.

    Lo que el recorte protegia -- pulsar "Simular" y no ver aparecer nada -- lo dice
    ahora `_actualizar_aviso_vanos`, que cuenta cuantos de los marcados tienen celda en
    la ventana activa. Decirlo es mejor que impedirlo: un vano sin eventos en marzo
    sigue siendo el vano que interesa, y su serie de tiempo es justo donde se ve que en
    febrero si los tuvo.

    `VANOS_POR_CIRCUITO` sale de `TABLA` y no de la geometria del mapa: la geometria
    trae tambien los tramos que nunca tuvieron un evento, y esos no son marcables en
    ningun periodo.
    """
        return sorted(str(f) for f in VANOS_POR_CIRCUITO.get(circuito, ()))


    vano_widget = construir_selector_vanos(
        _vanos_marcables(circuito_widget.value),
        # Lo que se lee dentro de la caja cuando el circuito no tiene un solo evento en todo
        # el dataset. Una caja vacia y muda se lee como que el tablero se rompio.
        mensaje_vacio='Circuito sin eventos: no registró ningún evento en todo el periodo, '
                      'asi que no hay vanos que simular. Elige otro circuito.')


    # Sigue sin haber "Marcar todos", y ahora por otra razon: sin tope marcaria los cientos de
    # vanos del circuito, y de esos solo los primeros `MAX_VANOS_SERIE` cabrian dibujados. El
    # camino que sirve es el contrario -- "Volver al top de la ventana" --, que rehace la
    # auto-marca despues de haber agregado o quitado vanos a mano.
    boton_desmarcar = widgets.Button(description='Desmarcar', button_style='')
    boton_desmarcar.on_click(lambda _b: vano_widget.desmarcar_todos())
    boton_top_ventana = widgets.Button(
        description='Top de la ventana', button_style='',
        tooltip=f'Vuelve a marcar los {TOP_VANOS_VENTANA} vanos de mayor UITI en la ventana '
                'activa, descartando lo que hayas marcado o desmarcado a mano')


    def _volver_al_top_de_la_ventana(_boton):
        """Rehace la auto-marca del deslizador sin tener que moverlo y volver.

    `_auto_seleccion_ventana` esta definida mas abajo en esta misma celda, y eso no es
    un problema: el cuerpo corre en el CLIC, no al registrar el manejador.
    """
        vano_widget.value = tuple(
            _auto_seleccion_ventana(circuito_widget.value, ventana_widget.value))


    boton_top_ventana.on_click(_volver_al_top_de_la_ventana)


    def _auto_seleccion_ventana(circuito, ventana_i):
        """A quien se le marca la casilla sola al mover el deslizador: los vanos de mayor
    UITI EN ESA VENTANA, hasta `TOP_VANOS_VENTANA`.

    Es un REEMPLAZO y no una suma. Mover la ventana cambia el sujeto -- los vanos que
    fallaron en marzo no son los de abril --, y acumular dejaria marcado todo lo que
    alguna vez tuvo un evento, con lo que el deslizador dejaria de decir nada.

    El criterio vive en `top_vanos_de_ventana` y no aqui: el tablero de 04 auto-marca
    con la misma regla, y dos reglas escritas por separado se separan.
    """
        return top_vanos_de_ventana(TABLA, circuito, ventana_i, top=TOP_VANOS_VENTANA)


    def _auto_seleccion_circuito(circuito):
        """A quien se le marca la casilla sola al aterrizar en un circuito: los vanos de
    mayor UITI acumulado en TODO el periodo, hasta `TOP_VANOS_PERFIL`.

    Son exactamente las quince barras del perfil de la fila 3, y a proposito: al elegir
    circuito, el panel de arriba dice donde esta concentrado el riesgo y la serie de
    tiempo de abajo muestra la historia de esos mismos vanos. Marcar los de la ventana
    inicial en su lugar dejaria a los dos paneles hablando de conjuntos distintos.

    El total NO es la suma de `uiti_acumulado` sobre las once ventanas: se traslapan.
    `perfil_uiti_por_vano` suma solo sobre las que embaldosan el periodo una vez.
    """
        perfil = perfil_uiti_por_vano(TABLA, circuito, ventanas=VENTANAS,
                                      top=TOP_VANOS_PERFIL)
        return perfil['FID_VANO'].tolist()


    def _fijar_seleccion(fids):
        """Escribe la auto-marca sin disparar un repintado por cada casilla.

    `vano_widget.value` mueve todas las casillas de una vez y emite UN solo cambio; el
    interruptor de pausa evita ademas que ese cambio repinte por su cuenta cuando quien
    llama va a repintar de todos modos al terminar.
    """
        nonlocal _REPINTADO_EN_PAUSA
        _REPINTADO_EN_PAUSA = True
        try:
            vano_widget.value = tuple(fids)
        finally:
            _REPINTADO_EN_PAUSA = False


    def _on_ventana_change(_change):
        """Mover el deslizador cambia el FOCO, no el universo.

    La lista de casillas es la del circuito entero y no se toca (ver
    `_vanos_marcables`). Lo que cambia es quien esta marcado: los quince vanos de mayor
    UITI en la ventana nueva, que son los que pasan a describir el mapa, la serie de
    tiempo y el ranking.
    """
        if _REPINTADO_EN_PAUSA:
            # Lo encadeno el cambio de circuito, que fija la seleccion y repinta al final.
            return
        circuito, ventana_i = circuito_widget.value, ventana_widget.value
        _fijar_seleccion(_auto_seleccion_ventana(circuito, ventana_i))
        _redibujar_mapa_historico()
        # El reencuadre va AL FINAL y solo aqui. `_redibujar_mapa_historico` corre
        # tambien en cada clic sobre el mapa y en cada casilla; reencuadrar ahi dentro
        # movería el dibujo bajo la mano justo mientras se esta marcando.
        _encuadrar_ventana(circuito, ventana_i)


    def _on_circuito_change(_change):
        nonlocal _REPINTADO_EN_PAUSA
        circuito = circuito_widget.value
        # El deslizador se resuelve ANTES de fijar la seleccion: la auto-marca de la ventana
        # no llega a usarse aqui -- el circuito arranca con su top del periodo --, pero el
        # orden importa igual, porque mover `value` del deslizador dispara su manejador.
        # La ventana vigente se lee ANTES de tocar `options`: asignar `options` reajusta
        # `value` a la primera opcion de inmediato, asi que leerlo despues siempre devuelve
        # esa primera y la ventana se perdia en cada cambio de circuito. Medido: pasar de un
        # circuito a otro que SI tiene la ventana 10 la dejaba igual en la 0.
        _vigente = ventana_widget.value
        _opciones = _opciones_de_ventana(circuito)
        _disponibles = [i for _rotulo, i in _opciones]
        _REPINTADO_EN_PAUSA = True
        try:
            ventana_widget.options = _opciones
            # Si el circuito nuevo no tiene la ventana vigente, cae en la ULTIMA que si
            # tiene, por el mismo motivo por el que el deslizador arranca ahi: lo reciente
            # antes que lo viejo.
            ventana_widget.value = _vigente if _vigente in _disponibles else _disponibles[-1]
            # Sin conservar la seleccion: el universo de vanos es OTRO, y un fid del circuito
            # anterior no puede quedar marcado sobre el circuito nuevo.
            vano_widget.poblar(_vanos_marcables(circuito))
            # Y se marca el top del PERIODO, no el de la ventana: es la pregunta con la que
            # se aterriza en un circuito, y es la misma lista que dibuja el perfil de arriba.
            vano_widget.value = tuple(_auto_seleccion_circuito(circuito))
        finally:
            _REPINTADO_EN_PAUSA = False
        _pintar_circuito()
        _redibujar_mapa_historico()


    def _al_hacer_clic(traza, puntos, _estado):
        """Un clic sobre un tramo alterna su vano. El fid sale de `customdata` y no del
    indice del punto: los tramos viajan concatenados con un `None` de separador, asi que
    ese indice cambia con la ventana.

    Un clic AGREGA sin tope: la lista ya no lo tiene, asi que un vano que llamo la
    atencion entra al analisis aunque la auto-marca de la ventana ya haya puesto quince.
    Entra tambien a la serie de tiempo, porque la serie sale de los marcados.

    Un clic sobre un tramo que NUNCA tuvo eventos no hace nada: `alternar` ignora las
    claves que la lista no tiene, y esos tramos no estan en `VANOS_POR_CIRCUITO`. Es la
    misma regla que la casilla, por el mismo camino."""
        fid = fid_de_punto(traza.customdata, getattr(puntos, 'point_inds', ()) or ())
        if fid is not None:
            vano_widget.alternar(fid)


    # SOLO el mapa base. La fila 2 es la SALIDA del modelo, no un control: marcar un vano
    # desde ahi mezcla "lo que yo elegi" con "lo que el modelo predijo" sobre la misma
    # superficie, que es justo la confusion que separa a las dos filas (D2).
    # Nota sobre el alcance del clic: plotly solo convierte un clic en evento si en ese punto
    # hay hover, y en un `scattermap` de lineas el hover se calcula contra los VERTICES del
    # tramo (`scattermap/hover.js`: distancia por punto, radio minimo 3 px, tope
    # `layout.hoverdistance`). Antes eso obligaba a tocar el tramo cerca de uno de sus dos
    # extremos; ahora `paso_densificado` pone un vertice cada ~25 m, asi que el clic engancha
    # en cualquier punto del vano. `hoverdistance` sigue en 30 px, por encima de los 20 por
    # defecto, para que el blanco sea generoso sin llegar a marcar un vano lejano.
    #
    # Se cablean TAMBIEN las capas de vano marcado: quedan dibujadas encima de las de clase,
    # asi que son las que recibe el cursor sobre un vano ya marcado. Sin ellas, marcar
    # funcionaba y desmarcar tocando el mapa no.
    for _i_traza in (IDX['clases'] + IDX['marcados_clases']
                     + [IDX['sin_dato'], IDX['marcados'], IDX['marcados_sin_dato']]):
        fig.data[_i_traza].on_click(_al_hacer_clic)
    fig.layout.hoverdistance = 30

    # Tier 0 del presupuesto de interactividad (design section A): elegir circuito, mover la
    # ventana o marcar un vano no llama al modelo -- sin debounce ni epoch guard, que
    # pertenecen al tier 1/2 (fila 2, ranking, boton "Simular"), fuera del alcance de este PR.
    circuito_widget.observe(_on_circuito_change, names='value')
    # La ventana pasa por su propio manejador y no por el repintado suelto: primero recorta
    # la lista de vanos a esa ventana, despues repinta.
    ventana_widget.observe(_on_ventana_change, names='value')
    vano_widget.observe(_redibujar_mapa_historico, names='value')

    # El tablero abre YA con los quince vanos de mayor UITI del periodo marcados, que es lo
    # mismo que hace `_on_circuito_change`. Sin esto, abrir el simulador y cambiar de circuito
    # dejarian dos estados iniciales distintos: uno vacio y otro con el top marcado.
    _fijar_seleccion(_auto_seleccion_circuito(circuito_widget.value))
    _pintar_circuito()               # equipos y encuadre del circuito inicial
    _redibujar_mapa_historico()      # primer dibujo, con la seleccion inicial

    # --- Fila 3, columnas 3-4: que baja el UITI de CADA vano ------------------------------
    # El panel mostraba UN ranking, el de la seleccion entera. Con hasta cinco vanos bajo
    # estudio eso contesta la pregunta equivocada: dice que variable mueve AL GRUPO, cuando la
    # decision de mantenimiento necesita saber cual mueve a ESTE vano, el de la orden de
    # trabajo que se esta costeando.
    # Sigue sin ser SHAP (decision D5), y ahora por un motivo mas fuerte que antes: SHAP
    # ATRIBUYE el UITI que ya hay a las variables que lo explican, y la pregunta del panel es
    # la contraria -- que variable, y en que valor, lo BAJA. Una atribucion alta puede
    # corresponder a una variable que no se puede mover en la direccion util, y su linea base
    # es una distribucion de datos, no una intervencion.
    # Tampoco es ya el barrido min-max, que tenia dos defectos para esa pregunta: su magnitud
    # `max(|delta-|, |delta+|)` no llevaba SIGNO -- una variable que dispara el riesgo en los
    # dos extremos encabezaba el ranking -- y solo miraba los dos EXTREMOS, cuando medido
    # sobre este modelo 10 de los 15 controles tienen su mejor valor en el INTERIOR del rango
    # para alguna bolsa.
    # Lo que corre es una rejilla por control sobre el MISMO modelo y la MISMA unidad que el
    # mapa simulado -- la bolsa (vano, ventana) del cuaderno 05 --: se prueba cada valor, se
    # guarda el que MINIMIZA el u-hat de cada bolsa y se ordena por cuanto lo baja, en
    # ordenes de magnitud. Cuesta `1 + puntos x knobs_numericos` pasadas para TODA la
    # seleccion, no una tanda por vano: cada pasada ya devuelve un u-hat por bolsa (ver
    # `relevancia_hacia_uiti_minimo`). Corre DENTRO del job del boton "Simular" y bajo la
    # misma epoca, para que mapa, grafo y top describan siempre la MISMA seleccion.
    TOP_VACIO = {}

    def _calcular_top_por_vano(seleccion):
        """Que variables pueden llevar a cada vano a su UITI minimo, sobre las bolsas que
    ya resolvio el job de simulacion.

    Recorre `KNOBS_PANEL` y NUNCA `KNOBS` entero: el ranking se queda en los dos
    conjuntos que el panel ofrece -- intervencion y escenario -- por la misma razon por
    la que el panel no los ofrece. Con el catalogo completo entrarian las refutadas, y
    el tablero podria terminar diciendo que la variable mas relevante de un vano es
    `CNT_TRF`, los trafos afectados EN LA FALLA: se mide DESPUES del evento que el
    modelo intenta anticipar. Eso no seria un ranking flojo, seria la flecha del
    analisis al reves, sosteniendo una orden de trabajo que no arregla nada. Tampoco
    entran las de lectura unica: no se puede rankear por relevancia lo que no se deja
    mover.
    """
        return relevancia_hacia_uiti_minimo(
            MIL, X_INST, seleccion=seleccion, feature_names=FEATURES_MIL, knobs=KNOBS_PANEL,
            top=TOP_VARIABLES_POR_VANO, puntos=PUNTOS_REJILLA_RELEVANCIA,
            grupos=GRUPO_POR_KNOB, label_encoders=label_encoders,
            max_values_imputed=max_values_imputed,
        )

    def _diagnostico_del_circuito():
        """Los vanos que el diagnostico estudia -- lo que el usuario marco, completado con
    los de mayor UITI de la ventana hasta `TOP_VANOS_CIRCUITO` -- y que variables los
    bajarian al grupo Bajo.

    Contesta la pregunta con la que se abre una jornada -- por donde empiezo aqui -- que
    las demas vistas del tablero no contestan: el mapa exige mirar tramo a tramo y el
    panel exige haber elegido ya los vanos.

    Lo MARCADO es una entrada y no un estorbo: si el usuario ya toco tres vanos en el
    mapa, esos tres son la orden de trabajo que tiene en la mano y el diagnostico tiene
    que hablar de ellos. Lo que hace el boton es completar la lista, no reemplazarla.
    La regla completa -- y que se cuenta de lo que queda fuera -- vive en
    `vanos_para_diagnostico`, que se prueba con datos: aqui solo se conecta.

    El ranking se AGREGA sobre el conjunto y no se da vano por vano: la pregunta es que
    obra programar para el grupo, y quince rankings sueltos son quince decisiones. Se
    promedia la caida en ordenes de magnitud, que es la escala de la geometria; en
    unidades de UITI, el vano mas caro se llevaria el promedio entero.

    Las dos mitades se reportan por SEPARADO y con tamanios distintos a proposito. Lo que
    se HACE -- intervencion -- es lo que se cotiza, y va mas largo; lo que se ANTICIPA --
    escenario -- sirve para saber bajo que condiciones esa obra rinde, y con tres basta.
    Mezclarlas en una sola lista dejaria al clima copandola, como ya se midio.
    """
        circuito, ventana_i, marcados = _seleccion_actual()
        clases = clases_para(circuito, ventana_i)
        elegidos = vanos_para_diagnostico(
            DATOS_VENTANA[ventana_i], VANOS_POR_CIRCUITO.get(circuito, []),
            marcados=marcados, maximo=TOP_VANOS_CIRCUITO)
        peores = elegidos['vanos']
        # El reparto por grupo se cuenta sobre lo elegido y sobre los CUATRO grupos: ya no
        # hay dos privilegiados, y un conjunto que resulto ser todo Medio tiene que poder
        # decirlo en vez de callarlo.
        reparto = {c: sum(1 for f, _u, _n in peores if clases.get(f) == c) for c in range(4)}
        if not peores:
            return {'circuito': circuito, 'ventana': VENTANAS[ventana_i], 'vanos': [],
                    'por_grupo': reparto, 'n_puntuados': 0, 'seleccion': elegidos,
                    'clases': clases, 'ranking': {}, 'intervencion': [], 'escenario': []}

        seleccion = seleccionar_bolsas(BAG_INDEX, circuito=circuito,
                                       ventana=VENTANAS[ventana_i]['etiqueta'],
                                       marcados=[f for f, _u, _n in peores])
        if not seleccion['n_bolsas']:
            return None
        # `top` sin recorte y sin cuota: la cuota reparte DENTRO de un vano, y aqui el
        # reparto se hace despues, sobre el promedio de los diez.
        ranking = relevancia_hacia_uiti_minimo(
            MIL, X_INST, seleccion=seleccion, feature_names=FEATURES_MIL, knobs=KNOBS_PANEL,
            top=len(KNOBS_PANEL), puntos=PUNTOS_REJILLA_RELEVANCIA,
            grupos=GRUPO_POR_KNOB, label_encoders=label_encoders,
            max_values_imputed=max_values_imputed,
        )
        acumulado = {}
        for datos_vano in ranking.values():
            for fila in datos_vano['filas']:
                entrada = acumulado.setdefault(
                    fila['label'], {'grupo': fila['grupo'], 'knob_id': fila['knob_id'],
                                    'caidas': [], 'alcanza': 0, 'valores': []})
                entrada['caidas'].append(fila['caida_log'])
                entrada['alcanza'] += int(fila['alcanza'])
                entrada['valores'].append(fila['valor'])
        for entrada in acumulado.values():
            entrada['media'] = float(np.mean(entrada['caidas']))
            # El valor sugerido de la tabla es UN resumen de los valores que cada vano
            # pide, no un valor unico que sirva para todos: la columna de al lado ya es
            # una media, y el valor por vano esta en el plan de abajo. Mediana para los
            # numericos -- resiste el vano extremo que arrastraria un promedio -- y el mas
            # frecuente para los categoricos, donde una mediana no significa nada.
            _vals = entrada['valores']
            _nums = [float(x) for x in _vals if isinstance(x, (int, float))]
            entrada['valor'] = (float(np.median(_nums)) if len(_nums) == len(_vals) and _nums
                                else max(set(map(str, _vals)), key=lambda s: list(map(str, _vals)).count(s)))
        def _mejores(grupo, cuantas):
            """Las variables de ese grupo que bajan el UITI, de mayor a menor caida.

        `cuantas=None` no recorta: la pregunta es que hace falta para llegar a grupo
        Bajo, y un corte fijo la contestaba a medias -- si el vano necesita siete
        palancas, cinco no lo bajan y las dos que faltaban no aparecian. Lo que si se
        descarta es la caida CERO: una variable que no mueve el UITI no es una variable
        necesaria, es una fila que estorba en una tabla ya larga.
        """
            filas = [(lab, e) for lab, e in acumulado.items()
                     if e['grupo'] == grupo and e['media'] > 0]
            filas.sort(key=lambda t: -t[1]['media'])
            return filas if cuantas is None else filas[:cuantas]
        return {
            'circuito': circuito,
            'ventana': VENTANAS[ventana_i],
            'vanos': peores,
            # Cuantos aporto cada grupo de criticidad: es contexto de lectura de la lista.
            'por_grupo': reparto,
            # De donde salio cada vano y que quedo fuera: es lo que sostiene los avisos.
            'seleccion': elegidos,
            'clases': clases,
            'n_puntuados': len(ranking),
            # El ranking COMPLETO por vano, no solo el promedio: los botones de aplicar
            # necesitan el valor sugerido para CADA vano, y el promedio no lo tiene.
            'ranking': ranking,
            'intervencion': _mejores('Intervencion', TOP_INTERVENCION_CIRCUITO),
            'escenario': _mejores('Escenario', TOP_ESCENARIO_CIRCUITO),
        }

    def _valor_sugerido(entrada):
        """El valor de la tabla del diagnostico, ya legible.

    Cuatro cifras significativas y no el flotante crudo: la columna es estrecha y un
    `0.8333333333333334` la parte. Los categoricos salen tal cual, que es como se leen.
    """
        v = entrada.get('valor')
        if isinstance(v, (int, float)):
            return f'{v:,.4g}'
        return str(v) if v not in (None, '') else '--'

    def _texto_del_diagnostico(diag):
        """El diagnostico como tabla compacta. Va en HTML y no en la figura: son tres listas
    de largos distintos y meterlas en un panel de plotly obligaria a robarle sitio a los
    mapas para decir algo que se lee mejor como texto."""
        if diag is None:
            return ('<span style="font-size:12px;color:#5b4a48;">Presiona <b>Diagnostico</b> '
                    'para estudiar los vanos que hayas marcado.</span>')
        if not diag['vanos']:
            _marcados_sin = diag['seleccion']['sin_eventos']
            _por_lo_marcado = (
                f' Los {len(_marcados_sin)} vanos que marcaste tampoco tienen eventos ahí.'
                if _marcados_sin else '')
            return ('<span style="font-size:12px;color:#b91c1c;">En '
                    f'{diag["circuito"]}, {diag["ventana"]["etiqueta"]} no hay ningun vano con '
                    f'eventos.{_por_lo_marcado} No hay diagnostico que dar: no es un fallo, es '
                    'que ese circuito no registro nada en esa ventana.</span>')
        _filas_vanos = ''.join(
            f'<tr><td><b>{fid}</b></td>'
            f'<td style="color:#5b4a48;">{NOMBRES_GRUPOS[diag["clases"].get(fid, 0)]}</td>'
            f'<td style="text-align:right;">{u:,.2f}</td>'
            f'<td style="text-align:right;">{n}</td></tr>'
            for fid, u, n in diag['vanos'])
        def _lista(titulo, filas, color):
            if not filas:
                return f'<div><b>{titulo}</b>: sin variables de este tipo.</div>'
            renglones = ''.join(
                f'<tr><td>{i + 1}.</td><td><b>{lab}</b></td>'
                f'<td style="text-align:right;color:#0072b2;">{_valor_sugerido(e)}</td>'
                f'<td style="text-align:right;">{e["media"]:.3f}</td>'
                f'<td style="color:#15803d;">'
                f'{"sola basta en " + str(e["alcanza"]) + " de " + str(diag["n_puntuados"]) if e["alcanza"] else ""}'
                f'</td></tr>'
                for i, (lab, e) in enumerate(filas))
            return (f'<div style="margin-right:26px;"><b style="color:{color};">{titulo}</b>'
                    '<table style="font-size:11px;border-collapse:collapse;">'
                    f'{renglones}</table></div>')
        _reparto = ' + '.join(
            f'{diag["por_grupo"][c]} en {NOMBRES_GRUPOS[c]}' for c in (3, 2, 1, 0)
            if diag['por_grupo'].get(c))
        _sel = diag['seleccion']
        # De donde salio la lista. Sin esto, un usuario que marco tres vanos y recibio quince
        # no sabe cuales son los suyos, y la lista se lee como que el boton ignoro su
        # seleccion.
        _origen = (
            f'<b>{len(_sel["marcados"])}</b> que marcaste'
            + (f' + <b>{len(_sel["completados"])}</b> completados por mayor UITI'
               if _sel['completados'] else '')
            if _sel['marcados'] else
            f'los <b>{len(_sel["completados"])}</b> de mayor UITI de la ventana')
        # Los avisos NO son decoracion. Sin el primero, una lista de quince sobre un circuito
        # con sesenta vanos con eventos se lee como que el circuito tiene quince; sin el
        # segundo, una lista de cuatro se lee como que hay cuatro criticos, cuando lo que
        # pasa es que no hay mas con eventos.
        _aviso = ''
        if _sel['restantes'] > 0:
            # El aviso nombra la composicion REAL de la lista. "Los 15 de mayor UITI" sobre
            # una lista que el usuario marco entera es falso: los suyos entran por marcados
            # y pueden ser los de menor UITI de la ventana.
            _que_quedo = (
                f'los <b>{len(_sel["marcados"])}</b> que marcaste'
                + (f' y se completo con los <b>{len(_sel["completados"])}</b> de mayor UITI'
                   if _sel['completados'] else '')
                if _sel['marcados'] else
                f'los <b>{len(_sel["completados"])}</b> de mayor UITI')
            _aviso += (
                f'<br><span style="color:#b45309;">Se dejaron {_que_quedo}, pero quedan otros '
                f'<b>{_sel["restantes"]}</b> vanos con eventos en esta ventana. Marca los que '
                'te interesen y vuelve a pedir el diagnostico para estudiarlos.</span>')
        elif len(diag['vanos']) < TOP_VANOS_CIRCUITO:
            _aviso += (
                f'<br><span style="color:#b45309;">Se identificaron '
                f'<b>{len(diag["vanos"])}</b> vanos, no {TOP_VANOS_CIRCUITO}: '
                f'{diag["circuito"]} no tiene mas con eventos en esta ventana.</span>')
        if _sel['sin_eventos']:
            _aviso += (
                f'<br><span style="color:#b45309;">Fuera del diagnostico: '
                f'<b>{", ".join(sorted(_sel["sin_eventos"]))}</b> -- marcados, pero sin '
                'eventos en la ventana activa, asi que el modelo no los puede puntuar.</span>')
        return (
            '<div style="font-size:12px;color:#2b2b2b;">'
            f'<b>Diagnostico de {diag["circuito"]}</b> &mdash; {diag["ventana"]["etiqueta"]}: '
            f'{diag["ventana"]["periodo"]} &mdash; '
            f'{len(diag["vanos"])} vanos ({_reparto}), {diag["n_puntuados"]} puntuados'
            f'<br><span style="color:#5b4a48;">Estudia {_origen}.</span>'
            f'{_aviso}'
            '<div style="display:flex;flex-flow:row wrap;align-items:flex-start;'
            'margin-top:4px;">'
            '<div style="margin-right:26px;"><b>Vanos (grupo, UITI, eventos)</b>'
            f'<table style="font-size:11px;border-collapse:collapse;">{_filas_vanos}</table>'
            '</div>'
            + _lista('Intervención &mdash; qué HACER (valor sugerido, caída media)', diag['intervencion'],
                     '#0072b2')
            + _lista('Escenario &mdash; bajo qué CONDICIONES (valor, caída media)', diag['escenario'], '#b45309')
            + '</div></div>')

    def _pintar_top_por_vano(por_vano):
        """Repaint puro, cero pasadas del modelo.

    Un grupo de barras por vano. Cada TRAZA es una posicion del ranking -- la 1a, la 2a...
    -- y no una variable: las variables cambian de vano a vano, asi que una traza por
    variable necesitaria tantas como el catalogo entero y casi todas vacias.
    El nombre va DENTRO de la barra: con cinco grupos de diez barras no hay sitio para una
    leyenda de cincuenta entradas, y el rotulo pegado al dato no obliga a cruzarlo.

    Cual de los tres rotulos se escribe lo decide `rotulo_en_barra` con el largo de CADA
    barra en pixeles: el resumen si cabe, sus iniciales si no, y nada antes que un texto
    cortado que se monte sobre la barra vecina. El nombre completo esta siempre en la
    etiqueta del mouse, que es donde se resuelve la duda.
    """
        vanos = list(por_vano)
        # El rango del eje se decide ANTES de escribir las barras: el rotulo de cada una
        # depende de cuantos pixeles mide, y eso solo se sabe con el rango ya fijado. Con las
        # trazas vacias un eje lineal autoescala a [-1, 4] y muestra marcas negativas para una
        # caida que no puede serlo.
        _tope = max((f['caida_log'] for v in por_vano.values() for f in v['filas']),
                    default=0.0)
        _rango = _tope * 1.15 if _tope > 0 else 1.0
        _px_por_unidad = ALTO_PANEL_TOP_PX / _rango
        # Cada casilla del eje x es un vano y dentro van las diez posiciones del top: con
        # ocho vanos marcados la barra queda en 3,6 px y no cabe ningun rotulo.
        _grosor_barra_px = (ANCHO_PANEL_TOP_PX_MINIMO / max(1, len(vanos))
                            / TOP_VARIABLES_POR_VANO * FRACCION_UTIL_BARRA)
        with fig.batch_update():
            # Fila 4 y no 3: la 3 es el GRAFO. El top bajo una fila cuando el perfil del
            # circuito entro como fila nueva, y esta llamada se quedo donde estaba. Le
            # escribia `[0, _rango]` al eje del grafo, que es circular y necesita su rango
            # SIMETRICO: con `scaleanchor` plotly lo estira conservando el CENTRO, asi que
            # de [0, 1] salia [-0,737, 1,737] -- medido en el navegador -- y el arco de
            # abajo del anillo, con sus rotulos, quedaba fuera del recuadro. Y el top se
            # quedaba sin rango, que es justo lo que este bloque existe para evitar.
            fig.update_yaxes(range=[0, _rango], row=4, col=1)
            for _posicion in range(TOP_VARIABLES_POR_VANO):
                _traza = fig.data[IDX['top_vano'][_posicion]]
                _x, _y, _texto, _hover, _colores = [], [], [], [], []
                _donde = []
                for _fid in vanos:
                    _datos = por_vano[_fid]
                    _filas = _datos['filas']
                    if _posicion >= len(_filas):
                        continue
                    _fila = _filas[_posicion]
                    _x.append(_fid)
                    _y.append(_fila['caida_log'])
                    # Los DOS espacios de la barra, en pixeles: lo que mide ella y lo que
                    # queda entre su punta y el techo del eje. En una barra corta el
                    # segundo es casi todo el panel, y es lo que permite que el rotulo se
                    # vaya ENCIMA en vez de perderse.
                    _largo_px = _fila['caida_log'] * _px_por_unidad
                    _rotulo, _posicion_texto = rotulo_y_posicion(
                        _fila['label'], _largo_px,
                        hueco_px=ALTO_PANEL_TOP_PX - _largo_px,
                        grosor_px=_grosor_barra_px)
                    _texto.append(_rotulo)
                    _donde.append(_posicion_texto)
                    # VERDE si esa sola variable basta para caer en el grupo Bajo. Es el
                    # mismo verde del recuadro del mapa simulado y significa lo mismo --
                    # baja de grupo de criticidad -- asi que el color no pide aprender un
                    # codigo nuevo. El resto conserva la rampa de posicion del ranking.
                    _colores.append(COLOR_CAJA_MEJORA if _fila['alcanza']
                                    else COLOR_POSICION_BARRA[_posicion])
                    _meta = ('ya esta en el grupo Bajo' if _datos['ya_en_clase_minima']
                             else 'el grupo Bajo es inalcanzable con sus eventos'
                             if _datos['objetivo_u'] is None
                             else f'para Bajo: u &lt; {_datos["objetivo_u"]:,.3f}')
                    _avance = ('' if _fila['avance'] is None
                               else f'<br>Cubre el {100 * _fila["avance"]:.0f}% del camino')
                    # El valor de un control CATEGORICO es texto -- su categoria -- y no
                    # un numero: formatearlo con `:,.4g` revienta el repintado entero.
                    _valor = (f'{_fila["valor"]:,.4g}'
                              if isinstance(_fila['valor'], (int, float))
                              else str(_fila['valor']))
                    _hover.append(
                        f'<b>Vano {_fid}</b><br>{_posicion + 1}o: {_fila["label"]}'
                        f'<br>Llevarla a <b>{_valor}</b>'
                        f'<br>UITI: {_datos["u_base"]:,.3f} -> {_fila["u_optimo"]:,.3f}'
                        f'<br>Caida: {_fila["caida_log"]:.2f} ordenes de magnitud'
                        f'{_avance}<br>{_meta}'
                        + ('<br><b>Sola alcanza el grupo Bajo</b>' if _fila['alcanza'] else '')
                    )
                _traza.x, _traza.y = _x, _y
                _traza.text, _traza.hovertext = _texto, _hover
                # Por PUNTO. Dentro de una misma posicion del ranking conviven barras
                # largas, que llevan el rotulo dentro, y cortas, que lo llevan encima.
                _traza.textposition = _donde
                _traza.marker.color = _colores

    def _pintar_barras_uiti(tabla_simulada, ventana_i=None, circuito=None):
        """Fila 4: el UITI acumulado MEDIDO de cada vano contra el que predice la simulacion,
    y un ultimo grupo con el circuito completo.

    Reemplaza a los violines. Con diez vanos, dos violines resumian en una densidad lo
    que aqui se lee vano por vano, que es el grano en el que se decide una obra.

    Las dos barras son cantidades de NATURALEZA distinta -- la izquierda es lo que dice
    la base de datos, la derecha es lo que dice el modelo --, y eso no se puede esconder:
    medido sobre 599 bolsas reales, el modelo correlaciona 0,950 con el UITI observado
    (ordena bien) pero su nivel corre +34%. De ahi las dos cosas que acompanian a las
    barras: el error de la simulada es el desfase del modelo en la BASE de ese mismo vano
    -- lo unico local y medible que hay -- y el titulo publica la reduccion con su +-.
    Sin eso, el sesgo del modelo se leeria como ahorro.

    La alternativa descartada queda dicha porque parece mas rigurosa y no lo es:
    reamuestrear los eventos de cada bolsa y volver a predecir da desviacion 0,000
    (medido con 50 y 200 replicas). La prediccion no depende de que eventos cayeron en
    la bolsa, asi que esa barra de error habria sido adorno sobre la incertidumbre real,
    que es dos ordenes de magnitud mayor.
    """
        if tabla_simulada is None or len(tabla_simulada) == 0:
            barras = barras_uiti_por_vano(None, observados={}, total_circuito=0.0)
        else:
            _datos = DATOS_VENTANA[ventana_i]
            _observados = {str(f): _datos[str(f)][0] for f in tabla_simulada['FID_VANO']
                           if str(f) in _datos}
            # El total del circuito sale de TODOS sus vanos en la ventana activa, no solo de
            # los marcados: es lo que deja ver cuanto pesa la intervencion sobre el conjunto.
            _total = sum(_datos[str(f)][0] for f in VANOS_POR_CIRCUITO.get(circuito, [])
                         if str(f) in _datos)
            barras = barras_uiti_por_vano(tabla_simulada, observados=_observados,
                                          total_circuito=_total)
        # `barras_uiti_por_vano` devuelve los vanos y, de ULTIMO, el grupo del circuito
        # entero. Aqui se corta ahi: los vanos van al panel de las columnas 1-3 y el total
        # al de la 4, cada uno con su eje. Sin el corte, el total -- la suma de los 81 vanos
        # del circuito -- aplastaba contra la base a los diez grupos donde se decide la obra.
        _n = len(barras['x'])
        _corte = max(_n - 1, 0)
        with fig.batch_update():
            _obs = fig.data[IDX['barra_observada']]
            _sim = fig.data[IDX['barra_simulada']]
            _obs.x, _obs.y = barras['x'][:_corte], barras['observado'][:_corte]
            _obs.hovertext = barras['hover'][:_corte]
            _sim.x, _sim.y = barras['x'][:_corte], barras['simulado'][:_corte]
            _sim.hovertext = barras['hover'][:_corte]
            _sim.error_y.array = barras['error'][:_corte]
            _obs_t = fig.data[IDX['barra_total_observada']]
            _sim_t = fig.data[IDX['barra_total_simulada']]
            _obs_t.x, _obs_t.y = barras['x'][_corte:], barras['observado'][_corte:]
            _obs_t.hovertext = barras['hover'][_corte:]
            _sim_t.x, _sim_t.y = barras['x'][_corte:], barras['simulado'][_corte:]
            _sim_t.hovertext = barras['hover'][_corte:]
            _sim_t.error_y.array = barras['error'][_corte:]
            fig.layout.annotations[IDX_ANOTACION_BARRAS].text = (
                '' if barras['x'] else 'Marca vanos y presiona <b>Simular</b>.')
            fig.layout.annotations[IDX_TITULO_BARRAS].text = _titulo_de_barras(barras)

    def _titulo_de_barras(barras):
        """El titulo lleva la cifra que el tablero viene a producir: cuanto baja el UITI
    acumulado de los vanos intervenidos, y con cuanta incertidumbre.

    El `+-` no es un adorno estadistico: es el desfase acumulado del modelo, y en estos
    datos puede ser del orden de la propia reduccion. Publicar la reduccion sola la haria
    pasar por un resultado firme."""
        if barras['reduccion'] is None:
            return 'UITI acumulado: medido contra simulado'
        return (f'UITI acumulado: medido contra simulado: baja '
                f'<b>{barras["reduccion"]:,.1f}</b> &plusmn; {barras["desviacion"]:,.1f} '
                f'en los {len(barras["x"]) - 1} vanos')

    def _pintar_costos(costos):
        """Fila 5: lo que cuesta ejecutar el plan, por vano y en total.

    Es la conclusion del tablero. Todo lo de arriba dice cuanto BAJA el riesgo; esto
    dice cuanto cuesta bajarlo, y una decision de mantenimiento no se toma con una sola
    de las dos mitades.

    El TOTAL va en su PROPIO panel, el de la columna 4, y con su propio eje. Compartirlo
    con los vanos mostraba cuanto pesa cada uno dentro de la suma, pero al precio de que
    esa suma -- siempre la barra mas alta -- dejara a los vanos pegados a la base, que es
    donde se compara una obra con otra. Lo que se pierde lo dice el hover del total: sobre
    cuantos vanos se reparte.

    Un vano marcado sin actividades da una barra en CERO, que es un dato y no un hueco:
    dice que se simulo su riesgo sin obra asociada. Quitarlo del eje lo haria parecer no
    estudiado.
    """
        if not costos or not costos['por_vano']:
            with fig.batch_update():
                _traza = fig.data[IDX['costos']]
                _traza.x, _traza.y = [], []
                _traza.text, _traza.hovertext = [], []
                _traza.marker.color = []
                # Los DOS paneles se limpian juntos: si el acumulado sobrevive, se queda
                # cotizando la corrida anterior al lado de un panel de vanos ya vacio.
                _total = fig.data[IDX['costo_total']]
                _total.x, _total.y = [], []
                _total.text, _total.hovertext = [], []
                fig.layout.annotations[IDX_ANOTACION_COSTOS].text = (
                    'Marca actividades del contrato para cada vano y presiona '
                    '<b>Simular</b>.')
            return

        _por_vano = costos['por_vano']
        _x = list(_por_vano)
        _y = [v['total'] for v in _por_vano.values()]
        _colores = [COLOR_BARRA_COSTO] * len(_por_vano)
        _hover = []
        for _fid, _datos in _por_vano.items():
            # El desglose viaja en el hover: el total contesta cuanto y el detalle contesta
            # por que, sin obligar a volver a abrir el panel para averiguarlo. Va ordenado de
            # mayor a menor, asi que la primera linea es la actividad que hay que negociar.
            _lineas = [f'<b>Vano {_fid}</b><br>Costo: {_datos["total"]:,.0f} COP']
            _lineas += [f'{_r["repeticiones"]} x {_r["item"][:60]}: {_r["subtotal"]:,.0f}'
                        for _r in _datos['renglones']] or ['Sin actividades marcadas']
            _hover.append('<br>'.join(_lineas))
        # El hover del total dice sobre CUANTOS vanos se reparte: es lo unico que se pierde al
        # sacarlo del eje de los vanos, y es barato devolverlo aqui.
        _hover_total = (f'<b>{ETIQUETA_TOTAL}</b><br>{len(_por_vano)} vanos<br>'
                        f'{costos["total"]:,.0f} COP')
        with fig.batch_update():
            _traza = fig.data[IDX['costos']]
            _traza.x, _traza.y = _x, _y
            _traza.marker.color = _colores
            _traza.text = [f'{v:,.0f}' for v in _y]
            _traza.hovertext = _hover
            _total = fig.data[IDX['costo_total']]
            _total.x, _total.y = [ETIQUETA_TOTAL], [costos['total']]
            _total.text = [f'{costos["total"]:,.0f}']
            _total.hovertext = [_hover_total]
            fig.layout.annotations[IDX_ANOTACION_COSTOS].text = ''

    _pintar_top_por_vano(TOP_VACIO)   # vacio hasta el primer "Simular"
    _pintar_barras_uiti(None)
    _pintar_costos(None)

    # --- Fila 2: mapa "Criticidad Simulada" + boton "Simular" (design section A, decision D2)
    # El boton es el UNICO disparador y hace TRES cosas de una sola vez, bajo la misma epoca:
    # el mapa simulado, el grafo reconstruido de la seleccion y el barrido de importancia de
    # la celda anterior. Ya no hay alternador base/simulado/delta: el mapa de la fila 2
    # muestra SIEMPRE la clase simulada, que es lo que el boton promete.
    #
    # El mapa y el grafo salen del modelo MIL del cuaderno 05, que puntua BOLSAS: una bolsa es
    # una celda (vano, ventana) y su clase sale de `asignar_clase(n_obs OBSERVADO, u-hat
    # predicho)` sobre la geometria KMeans de 01.4 -- la MISMA con la que se pinta el mapa
    # base, que es por lo que los dos mapas comparten paleta por construccion y no por
    # convencion. `n_obs` nunca se simula: es un eje del espacio que define la clase.
    # Debounce asincronico (design section A): `asyncio.ensure_future` + cancelacion en el
    # propio event loop del kernel, NUNCA `threading.Timer` -- ipykernel enruta la salida de
    # los widgets con el parent header thread-local, asi que una escritura desde un hilo en
    # segundo plano cae en la celda equivocada. `_EPOCA` es el guard de epoca: cualquier evento
    # que invalide un job en vuelo la avanza y la escritura tardia se descarta.

    # El estado vacio se PIDE a la funcion en vez de escribirlo a mano: escrito a mano se
    # desincroniza en cuanto `trazas_grafo` agrega una columna, que es exactamente lo que
    # paso al sumarle el indice de modalidad a cada nodo.
    GRAFO_VACIO = trazas_grafo(np.zeros((1, 1)), [''])

    _EPOCA = 0
    _tarea_pendiente_simular = None
    _ultimo_resultado_simulacion = None   # DataFrame de simulate_explicit_overrides, o None
    _ultima_seleccion_simulada = None     # (circuito, ventana_i) al que corresponde ese resultado

    # El texto de arranque va en una constante y no repetido: "Limpiar" tiene que devolver
    # el panel EXACTAMENTE a este estado, y dos copias del mismo texto se separan a la
    # primera vez que alguien reescribe una.
    TEXTO_STATUS_INICIAL = (
        'Sin simular todavia -- elige variables (opcional) y presiona "Simular".'
    )
    STATUS = widgets.HTML(TEXTO_STATUS_INICIAL)

    # El panel NO ofrece las variables refutadas. Mientras estuvieran en la lista, el
    # tablero las presentaba como equivalentes a la poda o a la puesta a tierra, y tarde o
    # temprano alguien mueve las coordenadas de un vano creyendo que eso es un escenario.
    # Quitarlas del panel no las saca de la SIMULACION: un override solo se escribe si se
    # fija, asi que entran al modelo con el valor OBSERVADO de cada vano, que es lo que
    # corresponde. Lo unico que se pierde es poder moverlas.
    KNOBS_PANEL = knobs_simulables(KNOBS)
    KNOBS_BLOQUEADOS = knobs_bloqueados(KNOBS)
    _knobs_por_id = {k.id: k for k in KNOBS_PANEL}
    # Casillas y no `SelectMultiple`, por el mismo motivo que la lista de vanos: en un
    # `SelectMultiple` un clic sin ctrl borra todo lo ya elegido, y aqui justamente se quiere
    # simular VARIAS variables a la vez. Cada casilla es independiente y `value` sigue siendo
    # la tupla de knob ids, asi que `_reconstruir_controles_knob` no se entera del cambio.
    # CUATRO columnas: dos para lo que se puede hacer y dos para lo que se quiere
    # anticipar. Una lista corrida de dieciocho casillas obliga a recordar el veredicto de
    # cada variable para saber a cual de las dos preguntas pertenece -- "que obra hago" y
    # "que pasa si" --; en columnas eso lo dice la posicion.
    # El nombre en palabras de cada variable, del diccionario del proyecto. La sigla ya
    # esta escrita en la casilla; lo que falta es que signifique algo.
    NOMBRES_VARIABLES = descripciones_de_variables(variables_seleccion)
    INFO_VARIABLES = {
        _k.id: (f'<b>{NOMBRES_VARIABLES.get(_k.id, _k.label)}</b> <span style="color:#5b4a48;">({_k.label})</span><br>'
                f'Unidad: {UNIDADES.get(_k.id) or "sin unidad documentada"}<br>'
                f'<span style="color:#4b5563;">{definicion_de_knob(_k)}</span>')
        for _k in KNOBS_PANEL
    }
    COLUMNAS_KNOBS = columnas_panel(KNOBS_PANEL)
    knob_selector_widget = construir_selector_casillas(
        columnas=[(titulo, [(k.label, k.id) for k in knobs]) for titulo, knobs in COLUMNAS_KNOBS],
        titulo='', alto='210px', ancho_casilla='215px',
        # La definicion de cada variable, al posar el mouse sobre su casilla. En la casilla
        # solo cabe el nombre, y saber que es `NR_T` obligaba a subir hasta la tabla de la
        # celda 8 -- que queda fuera de pantalla justo cuando se esta eligiendo. Sale de
        # `JUICIO_SIMULACION`, la MISMA fuente que esa tabla: dos redacciones de la misma
        # decision se separan en cuanto alguien edita una sola.
        tooltips=definiciones_de_knobs(KNOBS_PANEL, nombres=NOMBRES_VARIABLES),
        # El mismo boton "i" que las actividades. `NR_T` no le dice nada a quien opera la
        # red: el panel abre con el nombre en palabras del diccionario del proyecto, su
        # unidad y su descripcion. El tooltip sigue estando para quien solo pasa el mouse.
        info=INFO_VARIABLES,
        layout=widgets.Layout(width='100%'),
    )
    # Se NOMBRAN en vez de dejarlas desaparecer: una lista que se acorta sin explicacion se
    # lee como que faltan variables, no como una decision.
    AVISO_BLOQUEADOS = widgets.HTML(
        '' if not KNOBS_BLOQUEADOS else
        '<span style="font-size:12px;color:#5b4a48;">No simulables: <b>'
        + ', '.join(k.label for k in KNOBS_BLOQUEADOS) + '</b>. '
        'Entran a la simulacion con el valor observado de cada vano, pero no se pueden '
        'mover.</span>')
    # --- Las actividades del contrato, la otra mitad de la decision -----------------------
    # Mismo patron que la lista de variables, y por la misma razon: UNA lista compartida de
    # casillas arriba, y cada vano marcado recibe abajo su propia fila por actividad elegida.
    # Repetir las 125 casillas por vano seria una pantalla de 625 casillas para elegir tres.
    # El rotulo arranca por el PRECIO. Es el dato con el que se elige entre dos podas, y los
    # nombres del contrato llegan a 143 caracteres: puesto al final, el ancho fijo de la
    # casilla lo recortaria justo a el.
    item_selector_widget = construir_selector_casillas(
        [(f'$ {_item.costo:,.0f}  --  {_item.nombre}', _item.nombre)
         for _item in CATALOGO_COSTOS.items],
        titulo='', alto='150px', ancho_casilla=ANCHO_CASILLA_ITEM,
        # El boton "i" de cada renglon. La casilla lleva el precio y el nombre porque son
        # los dos datos con los que se elige; el tipo, la unidad, el codigo maximo y la
        # descripcion no caben ahi -- los nombres del contrato llegan a 153 caracteres --,
        # asi que van al panel de detalle, que es UNO solo debajo de la lista: 142
        # emergentes serian 142 sitios donde mirar.
        # Con la constante en False el detalle va como `title` de la casilla -- el
        # navegador lo muestra al posar el mouse -- en vez de 285 widgets extra.
        info=INFO_ITEMS if BOTONES_INFO_ACTIVIDADES else None,
        tooltips=None if BOTONES_INFO_ACTIVIDADES else TEXTO_ITEMS,
        layout=widgets.Layout(width='100%'),
    )
    # Se NOMBRAN, igual que las variables no simulables: doce actividades ausentes sin
    # explicacion se leen como que el contrato no las incluye.
    AVISO_SIN_COSTO = widgets.HTML(
        '' if not CATALOGO_COSTOS.sin_costo else
        '<span style="font-size:12px;color:#5b4a48;">'
        f'{len(CATALOGO_COSTOS.sin_costo)} actividades del contrato no tienen costo unitario '
        'en el libro y no se ofrecen: no se puede costear lo que no tiene precio. '
        f'<i>{", ".join(n[:40] for n in CATALOGO_COSTOS.sin_costo[:3])}...</i></span>')
    controles_knob_box = widgets.VBox([])
    # La rejilla se muestra de a `VANOS_POR_PAGINA` columnas. Los controles de los vanos que
    # NO estan en pantalla siguen existiendo y conservando su valor: la simulacion los aplica
    # igual, y paginar no puede ser una forma silenciosa de descartar lo que se fijo.
    _COLUMNAS_VANO = []          # [(fid, VBox)] de TODOS los vanos, no solo los visibles
    _PAGINA = 0
    boton_pagina_anterior = widgets.Button(description='< Anteriores',
                                           layout=widgets.Layout(width='130px'))
    boton_pagina_siguiente = widgets.Button(description='Siguientes >',
                                            layout=widgets.Layout(width='130px'))
    PAGINA_LABEL = widgets.HTML('')
    # {fid: {nombre_actividad: Dropdown de repeticiones}}. Vive aparte de `_controles_por_vano`
    # porque son dos preguntas distintas -- que le muevo al vano y que obra le hago -- y el
    # modelo solo consume la primera.
    _costos_por_vano = {}
    # {fid o GRANO_CIRCUITO: {knob_id: widget}}. Una COLUMNA por vano, con el vano escrito
    # encima: sin ese encabezado cinco columnas de deslizadores identicos son indistinguibles.
    _controles_por_vano = {}
    GRANO_CIRCUITO = '(todo el circuito)'


    def _seleccion_de_bolsas():
        """Las bolsas de la seleccion activa, o None si no hay ninguna. Es lo que hace falta
    para saber que vanos tienen columna y en que valor arranca cada control."""
        circuito, ventana_i, marcados = _seleccion_actual()
        seleccion = seleccionar_bolsas(BAG_INDEX, circuito=circuito,
                                       ventana=VENTANAS[ventana_i]['etiqueta'],
                                       marcados=marcados)
        return seleccion if seleccion['n_bolsas'] else None


    def _valores_iniciales(seleccion, marcados):
        """En que valor abre cada control. La regla: el valor ACTUAL de esa variable para ESE
    vano en la ventana activa -- mediana si el vano trae varias instancias, moda si la
    variable es categorica (ver `valores_actuales_por_vano`).

    Un control que abriera en un valor por defecto pediria volver a teclear un dato que el
    modelo ya tiene, y peor: cualquier variable que se dejara quieta simularia al vano en
    un valor que nunca fue el suyo.

    Sin vanos marcados el grano es el circuito completo, y entonces hay UNA columna: todas
    las instancias se resumen juntas, que es exactamente lo que el override global escribe.
    """
        if seleccion is None:
            return {}
        X_sel = X_INST[seleccion['filas']]
        if marcados:
            return valores_actuales_por_vano(
                X_sel, FEATURES_MIL, instance_bag=seleccion['instance_bag'],
                fids=seleccion['fid'], knobs=KNOBS_PANEL, label_encoders=label_encoders,
            )
        return valores_actuales_por_vano(
            X_sel, FEATURES_MIL,
            instance_bag=np.zeros(len(X_sel), dtype=np.int64), fids=[GRANO_CIRCUITO],
            knobs=KNOBS_PANEL, label_encoders=label_encoders,
        )


    def _control_con_valor(knob, valor):
        """El control del knob, abierto en `valor`.

    Un valor fuera de lo que el control admite no se fuerza, se acomoda: un deslizador
    lo recorta a sus limites -- `FloatSlider` lanza si el valor cae fuera de [min, max],
    y tumbar el panel entero por un decimal no vale la pena -- y un selector se queda
    con la opcion mas cercana. Ese segundo caso es nuevo y es el normal: el archivo
    declara los apoyos que existen (12, 16, 18 m) y el vano real puede medir 14,2.
    """
        control = widget_for_knob(knob, catalogo=CATALOGO_SIM)
        if valor is None:
            return control

        opciones = list(getattr(control, 'options', ()) or ())
        if opciones:
            valores = [v for _e, v in opciones] if isinstance(opciones[0], tuple) else opciones
            if valor in valores:
                control.value = valor
            elif all(isinstance(v, (int, float)) for v in valores):
                control.value = min(valores, key=lambda v: abs(float(v) - float(valor)))
            return control

        if knob.kind == 'numeric':
            # Los limites del CONTROL, no los del knob: el archivo puede declarar un rango
            # mas estrecho que el observado, y es el del control el que lanza.
            control.value = type(control.value)(
                min(max(float(valor), control.min), control.max))
        return control


    def _fila_de_actividad(nombre, costo):
        """Una actividad dentro de la columna de un vano: cuanto vale y cuantas veces va.

    El costo unitario se muestra AL LADO del desplegable y no solo en el catalogo: al
    componer un plan de tres actividades, ir a buscar cada precio a la lista de arriba
    es exactamente el trabajo que el panel existe para evitar.
    """
        # Arranca en 1 y no en 0: si se marco la actividad es porque va. El CERO esta para
        # el vano donde NO va -- es lo que permite que una lista compartida no obligue a
        # darle la misma obra a los cinco vanos marcados.
        repeticiones = widgets.Dropdown(
            options=[(str(n), n) for n in range(0, MAX_REPETICIONES + 1)], value=1,
            description='', layout=widgets.Layout(width='58px'))
        etiqueta = widgets.HTML(
            f'<span style="font-size:11px;" title="{nombre}">{nombre[:46]}'
            f'{"..." if len(nombre) > 46 else ""}<br>'
            f'<b>$ {costo:,.0f}</b> c/u</span>')
        return repeticiones, widgets.HBox(
            [repeticiones, etiqueta],
            layout=widgets.Layout(align_items='center', margin='0 0 4px 0'))


    def _bloque_de_costos(fid):
        """El bloque de actividades de un vano, o nada si no se marco ninguna.

    Solo aparece con vanos marcados: una intervencion se cotiza sobre vanos concretos,
    y "cuanto cuesta intervenir el circuito entero" no es una pregunta que este panel
    pueda contestar con esta lista de precios.
    """
        elegidas = list(item_selector_widget.value)
        if not elegidas or fid == GRANO_CIRCUITO:
            return []
        filas, controles = [], {}
        for nombre in elegidas:
            control, fila = _fila_de_actividad(nombre, COSTO_POR_ITEM[nombre])
            controles[nombre] = control
            filas.append(fila)
        _costos_por_vano[fid] = controles
        return [widgets.HTML(
            '<div style="font-size:11px;color:#5b4a48;border-top:1px solid #cfe3ac;'
            'margin-top:6px;padding-top:4px;">Actividades del contrato</div>'), *filas]


    _PIE_REJILLA = widgets.HTML('')


    def _mostrar_pagina():
        """La rebanada visible de la rejilla, con su navegacion.

    Con diez vanos y veintiseis controles la rejilla es un muro: cinco columnas es lo que
    cabe legible a lo ancho del panel, y por encima las columnas se estrechan hasta que el
    nombre de la variable y su deslizador dejan de caber en la misma linea.

    La navegacion solo aparece si HAY mas de una pagina. Dos botones deshabilitados sobre
    tres vanos son dos controles que no hacen nada y que hay que leer igual.
    """
        total = len(_COLUMNAS_VANO)
        if not total:
            controles_knob_box.children = [_PIE_REJILLA]
            return
        paginas = (total + VANOS_POR_PAGINA - 1) // VANOS_POR_PAGINA
        desde = _PAGINA * VANOS_POR_PAGINA
        visibles = _COLUMNAS_VANO[desde:desde + VANOS_POR_PAGINA]
        boton_pagina_anterior.disabled = _PAGINA <= 0
        boton_pagina_siguiente.disabled = _PAGINA >= paginas - 1
        PAGINA_LABEL.value = (
            f'<span style="font-size:12px;color:#5b4a48;">Vanos '
            f'<b>{desde + 1}-{min(desde + VANOS_POR_PAGINA, total)}</b> de {total} '
            f'(pagina {_PAGINA + 1} de {paginas}). Los controles de los vanos que no se ven '
            'conservan su valor y entran igual a la simulacion.</span>')
        navegacion = ([widgets.HBox([boton_pagina_anterior, boton_pagina_siguiente,
                                     PAGINA_LABEL],
                                    layout=widgets.Layout(align_items='center'))]
                      if paginas > 1 else [])
        controles_knob_box.children = [
            *navegacion,
            widgets.Box([caja for _fid, caja in visibles],
                        layout=widgets.Layout(display='flex', flex_flow='row wrap',
                                              align_items='flex-start', width='100%')),
            _PIE_REJILLA,
        ]


    def _mover_pagina(paso):
        nonlocal _PAGINA
        paginas = max(1, (len(_COLUMNAS_VANO) + VANOS_POR_PAGINA - 1) // VANOS_POR_PAGINA)
        _PAGINA = min(max(_PAGINA + paso, 0), paginas - 1)
        _mostrar_pagina()


    boton_pagina_anterior.on_click(lambda _b: _mover_pagina(-1))
    boton_pagina_siguiente.on_click(lambda _b: _mover_pagina(1))


    def _reconstruir_controles_knob(_change=None):
        """La rejilla: filas = variables elegidas, columnas = vanos elegidos.

    Se rehace cuando cambia CUALQUIERA de las dos listas, y tambien al mover circuito o
    ventana: el valor inicial de cada control es el del vano EN ESA VENTANA, asi que una
    rejilla que sobreviviera al deslizador estaria mostrando los valores de otra.

    Debajo de las variables, cada columna lleva las ACTIVIDADES del contrato marcadas,
    con su costo unitario y cuantas veces se ejecutan. Son dos preguntas sobre el mismo
    vano -- que le muevo y que obra le hago -- y por eso comparten columna sin mezclarse:
    una linea las separa, y el modelo solo consume la de arriba.
    """
        nonlocal _controles_por_vano, _costos_por_vano, _COLUMNAS_VANO, _PAGINA
        _controles_por_vano = {}
        _costos_por_vano = {}
        knob_ids = list(knob_selector_widget.value)
        _circuito, _ventana_i, marcados = _seleccion_actual()
        seleccion = _seleccion_de_bolsas()
        valores = _valores_iniciales(seleccion, marcados)

        if not knob_ids and not item_selector_widget.value:
            _COLUMNAS_VANO.clear()
            controles_knob_box.children = [widgets.HTML(
                '<span style="font-size:12px;color:#5b4a48;">Elige arriba las variables a '
                'modificar y, si vas a costear, las actividades del contrato.</span>')]
            return
        if seleccion is None:
            _COLUMNAS_VANO.clear()
            controles_knob_box.children = [widgets.HTML(
                '<span style="font-size:12px;color:#5b4a48;">Esta selección no tiene celdas '
                '(vano x ventana) en la ventana activa: no hay valores desde donde '
                'arrancar.</span>')]
            return

        # El ORDEN de las columnas sale de la geometria y no del orden en que se fueron
        # marcando: asi marcar y desmarcar no baraja las columnas bajo la mano.
        columnas_fid = ([f for f in seleccion['fid'] if f in valores] if marcados
                        else [GRANO_CIRCUITO])
        columnas = []
        for fid in columnas_fid:
            controles = {}
            for knob_id in knob_ids:
                knob = _knobs_por_id[knob_id]
                controles[knob_id] = _control_con_valor(knob, valores.get(fid, {}).get(knob_id))
            _controles_por_vano[fid] = controles
            encabezado = widgets.HTML(
                f'<div style="font-weight:600;border-bottom:2px solid rgb(0,128,36);'
                f'padding-bottom:2px;margin-bottom:4px;">{fid}</div>')
            # `flex: 1 1 0%` reparte la fila entre las columnas que haya, y `min-width: 0`
            # apaga el `min-width: auto` que trae todo hijo de flex: sin el, la variable de
            # nombre mas largo manda sobre el reparto, la segunda columna se pasa del ancho
            # y el `row wrap` la baja a la fila siguiente -- justo lo que hay que evitar
            # cuando se quieren DOS por fila.
            columnas.append((fid, widgets.VBox(
                [encabezado, *controles.values(), *_bloque_de_costos(fid)],
                layout=widgets.Layout(margin='0 14px 0 0', align_items='flex-start',
                                      flex='1 1 0%', min_width='0'))))

        # Un vano marcado SIN celda en la ventana activa no tiene de donde sacar un valor
        # inicial, asi que no recibe columna. Se dice: medido, con 5 vanos marcados la rejilla
        # armaba 4 columnas y el quinto desaparecia sin que nada en pantalla lo explicara.
        sin_columna = [f for f in marcados if f not in _controles_por_vano]
        aviso_faltantes = ('' if not sin_columna else
                           f'<br>Sin columna: {", ".join(sorted(sin_columna))} -- '
                           f'{"ese vano no tiene" if len(sin_columna) == 1 else "esos vanos no tienen"} '
                           'eventos en la ventana activa, asi que no hay valor actual desde '
                           'donde arrancar. La simulacion tampoco los puntua.')
        pie = widgets.HTML(
            '<span style="font-size:12px;color:#5b4a48;">Cada control abre en el valor actual '
            'de esa variable para ese vano en la ventana activa (mediana de sus instancias; '
            f'moda si es categorica).{aviso_faltantes}</span>')
        # `flex_flow='row wrap'`: con cinco columnas y una variable de nombre largo la fila se
        # pasa del ancho del panel, y sin el wrap las ultimas columnas quedaban cortadas.
        _COLUMNAS_VANO = columnas
        _PAGINA = 0
        _PIE_REJILLA.value = pie.value
        _mostrar_pagina()


    knob_selector_widget.observe(_reconstruir_controles_knob, names='value')
    item_selector_widget.observe(_reconstruir_controles_knob, names='value')
    # La rejilla depende de la ventana y del circuito por sus VALORES INICIALES, no solo por
    # que vanos existen: mover el deslizador tiene que reabrir los controles en los valores de
    # la ventana nueva.
    vano_widget.observe(_reconstruir_controles_knob, names='value')
    ventana_widget.observe(_reconstruir_controles_knob, names='value')
    circuito_widget.observe(_reconstruir_controles_knob, names='value')

    boton_simular = widgets.Button(description='Simular', button_style='primary')
    # Al lado de "Simular" y no en otro sitio: deshacer una corrida es la operacion hermana de
    # lanzarla, y buscarla al otro extremo del panel obliga a recorrerlo entero. Sin
    # `button_style='danger'`: no destruye nada del disco, solo devuelve el tablero a como
    # empezo, y el rojo lo leeria como una accion peligrosa.
    boton_limpiar = widgets.Button(description='Limpiar',
                                   tooltip='Deja el tablero como al abrirlo: sin vanos ni '
                                           'variables marcadas y sin resultados en pantalla')
    # Disparador PROPIO y no parte de "Simular": contesta otra pregunta -- por donde empiezo
    # en este circuito -- y no depende de lo que el usuario haya marcado ni de las variables
    # que haya fijado. Colgarlo de "Simular" obligaria a recalcularlo en cada escenario que
    # no lo cambia, y a esperarlo aunque no se quiera.
    boton_diagnostico = widgets.Button(description='Diagnostico',
                                       button_style='', tooltip='Estudia los vanos que '
                                       'marcaste y completa con los de mayor UITI de la '
                                       'ventana hasta el tope')
    DIAGNOSTICO = widgets.HTML(_texto_del_diagnostico(None))
    # El ultimo diagnostico se guarda porque los botones de aplicar necesitan el valor
    # sugerido para CADA vano, y el texto en pantalla solo lleva el promedio.
    _ULTIMO_DIAGNOSTICO = None
    # Que mitades del diagnostico se aplicaron al diagnostico VIGENTE. Es lo que permite que
    # el segundo boton sume al primero sin que un solo clic marque las dos.
    GRUPOS_SUGERIDOS = ('intervencion', 'escenario')
    NOMBRES_SUGERIDOS = {'intervencion': 'Intervencion', 'escenario': 'Escenario'}
    _GRUPOS_APLICADOS = []
    boton_aplicar_intervencion = widgets.Button(
        description='Aplicar intervencion sugerida', layout=widgets.Layout(width='260px'),
        tooltip='Marca los vanos del diagnostico y abre sus controles en el valor sugerido')
    boton_aplicar_escenario = widgets.Button(
        description='Aplicar escenario sugerido', layout=widgets.Layout(width='260px'),
        tooltip='Marca los vanos del diagnostico y abre sus controles en el valor sugerido')
    AVISO_APLICAR = widgets.HTML('')


    _CAPA_VACIA = {'lat': [], 'lon': [], 'hovertext': [], 'customdata': []}


    def _redibujar_mapa_predicho(*_ignorado):
        """Repaint puro, CERO llamadas al modelo.

    Antes de la primera simulacion de la seleccion activa el mapa no se dibuja: ni
    tramos, ni equipos, ni leyenda -- solo el aviso de que hay que presionar "Simular".
    Un mapa completo pintado de "aun no simulado" ocupa el mismo lugar y tiene la misma
    forma que un resultado, y esa es justamente la confusion que la fila 2 no puede
    permitirse (D2).

    Con resultado, cada vano va del color del grupo que el simulador le predijo -- la
    MISMA paleta del mapa base, porque es la misma geometria -- y NEGRO todo lo demas
    (vano sin evento en la ventana, o no seleccionado), igual que la estructura del
    circuito en 01.4. Ademas de eso, este mapa hace dos cosas que el base no:

    - encierra a cada vano simulado en un recuadro cuyo COLOR es el desenlace -- bajo,
      se quedo igual o subio de grupo --, en tres capas de `layout.map2.layers`;
    - se ACERCA a los vanos marcados, en vez de quedarse en el encuadre del circuito.
    """
        circuito, ventana_i, _marcados = _seleccion_actual()
        geo = GEO_POR_CIRCUITO.get(circuito, {'fids': [], 'lat': [], 'lon': []})
        hay_resultado = (
            _ultimo_resultado_simulacion is not None
            and _ultima_seleccion_simulada == (circuito, ventana_i)
        )
        if not hay_resultado:
            with fig.batch_update():
                for _i in (IDX['pred_clases'] + [IDX['pred_sin_dato'],
                                                 IDX['pred_trafos'], IDX['pred_switches']]):
                    fig.data[_i].lat, fig.data[_i].lon = [], []
                    fig.data[_i].hovertext = []
                    fig.data[_i].showlegend = False
                # Las tres cajas se apagan juntas: un recuadro de desenlace sobre un mapa que
                # no muestra ningun resultado afirmaria un cambio que nadie calculo.
                for _capa in fig.layout.map2.layers:
                    _capa.source = {'type': 'FeatureCollection', 'features': []}
                _aplicar_vista('map2', _vista_del_circuito(circuito))
                fig.layout.annotations[IDX_ANOTACION_SIMULADO].text = (
                    'El mapa simulado aparece al presionar <b>Simular</b>.'
                )
            return

        clases_por_fid = clases_por_fid_para_estado(_ultimo_resultado_simulacion, ESTADO_SIMULADO)
        # El grupo BASE viaja como una columna mas del `customdata` y no en la plantilla:
        # dentro de una traza -- que es UNA clase simulada -- el grupo base cambia de vano a
        # vano. Sin los dos numeros en la misma etiqueta, saber si el vano mejoro obliga a
        # cruzar al mapa de al lado y acordarse del color.
        clases_base = clases_por_fid_para_estado(_ultimo_resultado_simulacion, ESTADO_BASE)
        capas = _capas_de_la_seleccion(
            clases_por_fid, campo='Criticidad simulada', nombres_clase=NOMBRES_GRUPOS,
            extra_por_fid={_fid: (NOMBRES_GRUPOS[_c],) for _fid, _c in clases_base.items()},
            plantilla_extra='<br>Criticidad base: %{customdata[3]}')
        _pl = capas['plantillas']
        tr = TRAFOS.get(circuito, {'lat': [], 'lon': []})
        sw = SWITCHES.get(circuito, {'lat': [], 'lon': []})
        with fig.batch_update():
            for _clase in range(4):
                _volcar_capa(fig.data[IDX['pred_clases'][_clase]], capas['clases'][_clase],
                             _pl['clases'][_clase])
                # NO vuelve a la leyenda: el mapa simulado usa la MISMA geometria KMeans
                # que el base, asi que sus cuatro clases ya estan nombradas alli. Repetirlas
                # agregaba un renglon a la leyenda horizontal que caia sobre los titulos de
                # la fila 3 -- medido, 22 px de solape.
                fig.data[IDX['pred_clases'][_clase]].showlegend = False
            # Negro: sin evento en la ventana, o fuera de la seleccion simulada. Un vano que
            # el simulador no puntuo no tiene clase, y la ausencia no es la clase mas baja.
            # Este mapa NO lleva halo de marcado: lo coloreado ES la seleccion, asi que un
            # halo encima no distinguiria nada que el color no diga ya.
            _volcar_capa(fig.data[IDX['pred_sin_dato']], capas['sin_dato'], _pl['sin_dato'])
            fig.data[IDX['pred_sin_dato']].name = 'Sin evento / no simulado'
            fig.data[IDX['pred_sin_dato']].line.color = COLOR_SIN_EVENTO
            fig.data[IDX['pred_sin_dato']].showlegend = False
            fig.data[IDX['pred_trafos']].lat, fig.data[IDX['pred_trafos']].lon = tr['lat'], tr['lon']
            fig.data[IDX['pred_trafos']].hovertext = ['<b>Transformador</b>'] * len(tr['lat'])
            fig.data[IDX['pred_switches']].lat, fig.data[IDX['pred_switches']].lon = sw['lat'], sw['lon']
            fig.data[IDX['pred_switches']].hovertext = ['<b>Interruptor / switch</b>'] * len(sw['lat'])
            # El recuadro de este mapa dice QUE LE PASO al vano y no cual elegi -- eso ya lo
            # dice el de la izquierda, sobre el mismo vano. Verde si bajo de grupo, amarillo
            # si se quedo igual, rojo si subio; el amarillo es el mismo del mapa base porque
            # "no cambio" es justo el estado en que los dos mapas dicen lo mismo. Un vano
            # marcado sin celda en la ventana no recibe caja: la simulacion no lo puntuo, asi
            # que no tiene desenlace que pintar.
            # Marcados que la simulacion PUNTUO. No es lo mismo que los marcados: marcar un
            # vano mas despues de simular no lo mete en el resultado, y ni la caja ni el
            # encuadre pueden seguirlo hasta que se vuelva a presionar "Simular".
            _simulados = set(_ultimo_resultado_simulacion['FID_VANO'].astype(str))
            _marcados_simulados = [f for f in _marcados if f in _simulados]
            _cajas = cajas_por_cambio_de_grupo(
                geo, _ultimo_resultado_simulacion, marcados=_marcados_simulados,
                lado_minimo=LADO_MINIMO_CAJA, margen=MARGEN_CAJA)
            for _cambio, _i_capa in IDX_CAPA_CAMBIO.items():
                fig.layout.map2.layers[_i_capa].source = _cajas[_cambio]
            # Y se ACERCA a los vanos marcados. Los dos mapas dejan de compartir vista a
            # proposito: una vez simulado, la pregunta es que le paso a ESOS vanos, y buscarlos
            # otra vez dentro del circuito entero es trabajo que el tablero puede ahorrar. El
            # de la izquierda conserva el encuadre del circuito, que queda como la referencia.
            # Sin vanos marcados -- grano de circuito completo -- no hay sobre que acercarse y
            # se vuelve a ese mismo encuadre, en vez de quedarse en el de la seleccion anterior.
            _aplicar_vista('map2', centro_y_zoom(bounds_de_fids(geo, _marcados_simulados),
                                                 ancho_px=_ancho_del_mapa_px(),
                                                 alto_px=_alto_del_mapa_px())
                           or _vista_del_circuito(circuito))
            fig.layout.annotations[IDX_ANOTACION_SIMULADO].text = ''


    def _limpiar_resultado_simulacion(_change=None):
        """Circuito o ventana cambiaron: el ultimo resultado ya NO corresponde a la
    seleccion activa -- se descarta (fila 2 vuelve a "Aun no simulado" y el panel de
    importancia se vacia) en vez de mostrar la corrida de OTRA seleccion, que violaria
    la regla anti-confusion (D2)."""
        nonlocal _ultimo_resultado_simulacion, _ultima_seleccion_simulada, _EPOCA
        _ultimo_resultado_simulacion = None
        _ultima_seleccion_simulada = None
        _EPOCA = siguiente_epoca(_EPOCA)  # invalida cualquier job en vuelo
        # El texto de estado vuelve al de arranque. Sin esto sobrevivia al cambio de
        # circuito el resumen de la corrida ANTERIOR -- "12 de 40 vanos cambian de grupo" --
        # debajo de una fila 2 ya vaciada, que es justo la confusion que esta funcion
        # existe para evitar: el panel afirmaba una simulacion que ya no estaba en pantalla.
        STATUS.value = TEXTO_STATUS_INICIAL
        _redibujar_mapa_predicho()
        _pintar_grafo(None)
        _pintar_top_por_vano(TOP_VACIO)
        _pintar_barras_uiti(None)
        _pintar_costos(None)


    def _pintar_rotulos_del_grafo(nodos):
        """Los nombres de los nodos, girados para seguir el radio de cada uno.

    Con los rotulos horizontales, los nombres de nodos vecinos se montaban unos sobre
    otros alrededor del anillo -- lo peor arriba y abajo, donde el circulo es mas plano y
    dos nodos consecutivos casi comparten altura. A lo largo del radio se abren en abanico
    con los propios nodos, asi que la separacion entre rotulos crece con la distancia al
    centro en vez de depender de donde caiga cada uno.

    Van como anotaciones y no como texto de la traza porque un `Scatter` no puede girar su
    texto: comprobado contra plotly 6.8.0, solo `Bar` y las anotaciones llevan `textangle`.

    El rotulo se planta un poco AFUERA del nodo (`RADIO_ROTULO_GRAFO`) para que el giro no
    lo haga cruzar por encima de su propio marcador.

    La reserva de anotaciones es fija: las que sobran quedan invisibles en vez de
    borrarse. Quitar anotaciones correria los indices de los avisos del grafo, de los
    costos y del mapa simulado, que se guardan por posicion.
    """
        for _k, _i_anotacion in enumerate(IDX_ANOTACIONES_NODOS):
            _anotacion = fig.layout.annotations[_i_anotacion]
            if _k >= len(nodos['texto']):
                _anotacion.visible = False
                continue
            _x, _y = nodos['x'][_k], nodos['y'][_k]
            _giro, _anclaje = rotacion_radial(_x, _y)
            _anotacion.x = _x * RADIO_ROTULO_GRAFO
            _anotacion.y = _y * RADIO_ROTULO_GRAFO
            # Abreviado, no crudo: el largo del rotulo es lo que fija el rango del eje y
            # con el el tamanio del circulo. El nombre completo sigue en el hover del nodo,
            # asi que no se pierde -- solo deja de ocupar la mitad del panel.
            _crudo = nodos['texto'][_k]
            _anotacion.text = abreviatura(NOMBRE_DE_FAMILIA.get(_crudo, _crudo))
            _anotacion.textangle = _giro
            _anotacion.xanchor = _anclaje
            _anotacion.visible = True


    def _pintar_grafo(grafo):
        """Repaint puro del panel del grafo. Un grafo ANULADO no se dibuja a medias: se
    vacian las trazas y se dice por que. `estadistico_colapso` anula cuando las
    compuertas no varian entre vanos -- y su veredicto incluye `effective_rank <= 1`,
    que con menos de 3 vanos se cumple por construccion (la matriz centrada de 1 o 2
    filas tiene rango 1). Dibujar igual seria presentar el grafo experto FIJO como si
    lo hubiera estimado esta seleccion."""
        if grafo is None:
            trazas, mensaje = GRAFO_VACIO, 'Presiona "Simular" para ver qué movió el grafo.'
        elif grafo['voided']:
            trazas = GRAFO_VACIO
            mensaje = (f'Grafo no estimable: las compuertas no varian entre los '
                       f'{grafo["n_vanos"]} vanos de la selección.<br>'
                       '<sup>Hacen falta al menos 3 vanos con comportamiento distinto.</sup>')
        elif not float(np.abs(grafo['matriz']).max()):
            # Todo en cero es un RESULTADO, no un panel vacio: la simulacion no movio una
            # sola relacion. Decirlo evita que se lea como que el grafo fallo.
            trazas = GRAFO_VACIO
            mensaje = ('La simulación no movió ninguna relación del grafo.<br>'
                       '<sup>Las variables aplicadas no cambian las compuertas de estos '
                       'vanos.</sup>')
        else:
            # Plegado ANTES de disponer: los doce rezagos de cada variable de clima son
            # 48 de los 66 nodos, y con 64 aristas el anillo era casi todo decoracion
            # ilegible. Plegado quedan 22 nodos, 62,7 px de arco por nombre contra 13,6, y
            # el radio sube de 142,9 a 219,4 px.
            _matriz, _nombres = plegar_rezagos(grafo['matriz'], FEATURES_MIL)
            trazas, mensaje = trazas_grafo(_matriz, _nombres), ''

        with fig.batch_update():
            fig.data[IDX['grafo_aristas']].x = trazas['aristas']['x']
            fig.data[IDX['grafo_aristas']].y = trazas['aristas']['y']
            _pesos = trazas['pesos']
            fig.data[IDX['grafo_pesos']].x = _pesos['x']
            fig.data[IDX['grafo_pesos']].y = _pesos['y']
            fig.data[IDX['grafo_pesos']].hovertext = _pesos['hovertext']
            # El tamano codifica el peso relativo DE ESTA seleccion: los pesos absolutos
            # cambian dos ordenes de magnitud entre ventanas y un tamano fijo por valor
            # dejaria el panel vacio o saturado segun cual se mire.
            _maximo = max(_pesos['peso'], default=0.0) or 1.0
            fig.data[IDX['grafo_pesos']].marker.size = [4 + 10 * (p / _maximo) for p in _pesos['peso']]
            fig.data[IDX['grafo_pesos']].marker.color = list(_pesos['peso'])
            # Un nodo por variable, con el color de su modo. El NOMBRE ya no va en la traza:
            # va como anotacion girada, mas abajo, porque un `Scatter` no puede girar texto.
            _nodos = trazas['nodos']
            for _i_traza, _modalidad in zip(IDX['grafo_nodos'], MODALIDADES_MIL):
                _cuales = [k for k, col in enumerate(_nodos['indice'])
                           if col in COLUMNAS_MODALIDAD[_modalidad]]
                _traza_nodo = fig.data[_i_traza]
                _traza_nodo.x = [_nodos['x'][k] for k in _cuales]
                _traza_nodo.y = [_nodos['y'][k] for k in _cuales]
                _traza_nodo.hovertext = [f'<b>{_nodos["texto"][k]}</b><br>Modo: {_modalidad}'
                                         for k in _cuales]
            _pintar_rotulos_del_grafo(_nodos)
            fig.layout.annotations[IDX_ANOTACION_GRAFO].text = mensaje


    def _simular(epoca_job):
        """Computo pesado -- bloqueante dentro de la corutina (design section A: un job ya
    iniciado no se puede interrumpir). Mapa simulado, grafo e importancia, en ese orden y
    en el mismo job. Guarda y repinta SOLO si `epoca_job` sigue vigente al terminar
    (epoch guard)."""
        nonlocal _ultimo_resultado_simulacion, _ultima_seleccion_simulada
        circuito, ventana_i, marcados = _seleccion_actual()
        seleccion = seleccionar_bolsas(BAG_INDEX, circuito=circuito,
                                       ventana=VENTANAS[ventana_i]['etiqueta'],
                                       marcados=marcados)
        if seleccion['n_bolsas'] == 0:
            # Lo dice el MAPA y no solo la linea de estado. El estado vive al final de un
            # panel que mide varias pantallas, asi que quien presiona "Simular" mirando la
            # fila 2 no lo ve: se queda con el aviso de "presiona Simular" sobre un mapa que
            # acaba de no pintar nada, que se lee como que el boton no funciono. Y ocurre a
            # menudo: MEDIDO sobre 30 circuitos, solo el 21% de las casillas de vano tienen
            # eventos en la ventana activa, asi que marcar tres vanos al azar deja la
            # seleccion sin una sola bolsa la mitad de las veces.
            _n_marcados = len(marcados)
            _texto_mapa = (
                f'Los {_n_marcados} vanos marcados no registran eventos en esta ventana:'
                '<br>el modelo no tiene nada que puntuar. Mueve la ventana o marca otros '
                'vanos.'
            ) if _n_marcados else (
                'Este circuito no tiene eventos en la ventana activa.<br>Mueve la ventana.'
            )
            _texto_estado = (
                f'Sin bolsas (vano x ventana): los {_n_marcados} vanos marcados no tienen '
                'eventos en la ventana activa.' if _n_marcados else
                'Sin bolsas (vano x ventana): el circuito no tiene eventos en la ventana '
                'activa.'
            )

            def _sin_bolsas():
                STATUS.value = _texto_estado
                fig.layout.annotations[IDX_ANOTACION_SIMULADO].text = _texto_mapa

            aplicar_si_vigente(_sin_bolsas, epoca_job=epoca_job,
                               epoca_actual=lambda: _EPOCA)
            return

        # Cada columna de la rejilla es un vano, y cada vano lleva SUS valores a sus propias
        # instancias. Con la escritura global anterior el ultimo vano pisaba a todos los demas
        # y la simulacion contestaba por un escenario que nadie habia pedido.
        # Sin vanos marcados el grano es el circuito completo y hay una sola columna: ahi el
        # override vuelve a ser global, que es lo que corresponde a una pregunta sobre todo el
        # circuito.
        # `KNOBS` completo y no `KNOBS_PANEL`: el diccionario solo se usa para resolver
        # que features toca cada knob, y solo llegan aqui los que el panel ofrecio.
        por_vano = {
            fid: expand_knob_overrides(
                {knob_id: control.value for knob_id, control in controles.items()}, KNOBS)
            for fid, controles in _controles_por_vano.items()
        }
        global_ = por_vano.pop(GRANO_CIRCUITO, None)

        t0 = time.perf_counter()
        resultado, metadata = simular_bolsas(
            MIL, X_INST, seleccion=seleccion, feature_names=FEATURES_MIL,
            overrides=global_ if global_ is not None else None,
            overrides_por_vano=por_vano or None,
            label_encoders=label_encoders, max_values_imputed=max_values_imputed,
        )
        # El grafo del panel es |base - simulado|: cuanto MOVIO la simulacion cada relacion.
        # Antes se estimaba solo sobre las features observadas, y ese grafo es casi todo el
        # peso fijo del experto -- las compuertas solo lo reescalan --, asi que el antes y el
        # despues se ven iguales y el efecto de la intervencion no se aprecia.
        # Las features simuladas salen de la metadata y no se rearman aqui: repetir la
        # expansion de overrides es la forma segura de que el grafo acabe describiendo un
        # escenario distinto del que puntuo el mapa.
        _instancias = seleccion['instance_bag']
        gates_base = gates_de_bolsas(MIL, X_INST[seleccion['filas']], _instancias,
                                     seleccion['n_bolsas'])
        gates_simuladas = gates_de_bolsas(MIL, metadata['X_simulado'], _instancias,
                                          seleccion['n_bolsas'])
        grafo = grafo_diferencia(gates_base, gates_simuladas, MIL.model.edge_index,
                                 n_features=len(FEATURES_MIL))
        # El top por vano reusa la MISMA seleccion de bolsas que acaba de puntuar el mapa: no
        # se vuelve a resolver, que era lo que hacia el cache por (circuito, ventana, marcados).
        top_por_vano = _calcular_top_por_vano(seleccion)
        # El plan comparte las bolsas ya resueltas y corre en el MISMO job: un plan que se
        # calculara aparte podria describir una seleccion distinta de la que muestra el mapa.
        # El costo sale de la rejilla, no del modelo: es aritmetica sobre la lista de precios
        # del contrato. Se calcula AQUI y no al marcar una casilla porque el tablero tiene un
        # solo disparador -- "Simular" -- y un costo que cambiara solo, mientras el mapa de
        # al lado sigue mostrando la corrida anterior, describiria dos planes a la vez.
        # Solo los vanos que la simulacion PUNTUO: costear un vano que el modelo no vio
        # pondria un precio al lado de un riesgo que nadie estimo.
        _puntuados = set(resultado['FID_VANO'].astype(str))
        costos = costos_de_intervencion(
            {fid: {nombre: int(control.value) for nombre, control in actividades.items()}
             for fid, actividades in _costos_por_vano.items() if fid in _puntuados},
            CATALOGO_COSTOS,
        )
        duracion = time.perf_counter() - t0

        def _escribir():
            nonlocal _ultimo_resultado_simulacion, _ultima_seleccion_simulada
            _ultimo_resultado_simulacion = resultado
            _ultima_seleccion_simulada = (circuito, ventana_i)
            grano = f'{len(marcados)} vanos marcados' if marcados else 'todo el circuito'
            # DOS cuentas y no una. `variables_aplicadas` son las columnas del modelo que se
            # tocaron, y un solo control del panel abre varias: tres variables de escenario
            # llegan al modelo como veinticinco columnas. Publicar solo la segunda decia
            # "25 variables aplicadas" debajo de un panel con tres casillas marcadas, que se
            # lee como que la simulacion metio variables que nadie eligio.
            del_panel = len({k for c in _controles_por_vano.values() for k in c})
            columnas = len(metadata['variables_aplicadas'])
            aplicadas = (f'{del_panel} variables del panel' if del_panel == columnas else
                         f'{del_panel} variables del panel ({columnas} columnas del modelo)')
            cambian = int((resultado['delta_riesgo_ordinal'] != 0).sum())
            avisos = f' | {len(metadata["avisos"])} avisos' if metadata['avisos'] else ''
            costo = (f' | intervencion: {costos["total"]:,.0f} COP'
                     if costos['total'] else '')
            # Lo que se espera, partido en las dos mitades de la decision: lo que se HACE
            # y lo que se ANTICIPA. Antes esta linea era una ficha tecnica -- duracion,
            # bolsas, granularidad del grafo -- que no contesta la pregunta con la que se
            # aprueba una orden de trabajo. Las variables aplicadas se listan con el valor
            # que se les fijo, porque "se simularon 6 variables" no permite revisar nada.
            _por_grupo = {'Intervencion': [], 'Escenario': [], 'Sin grupo': []}
            for _vano, _ctrls in _controles_por_vano.items():
                for _kid, _control in _ctrls.items():
                    _lab = _knobs_por_id[_kid].label if _kid in _knobs_por_id else _kid
                    # `.value` y no el control: el diccionario guarda WIDGETS, y sin esto
                    # el resumen imprime el `Dropdown(...)` entero con sus 40 opciones.
                    # Es el mismo acceso que usa la simulacion, a proposito.
                    _por_grupo.setdefault(GRUPO_POR_KNOB.get(_kid, 'Sin grupo'), []).append(
                        (_lab, _control.value))

            def _valor_legible(vals):
                # Un solo valor si todos los vanos comparten el mismo; si no, se dice "por
                # vano" en vez de mostrar uno y sugerir que es el de todos.
                if len({str(v) for v in vals}) != 1:
                    return 'por vano'
                v = vals[0]
                return f'{v:,.4g}' if isinstance(v, (int, float)) else str(v)

            def _bloque(titulo, color, filas):
                if not filas:
                    return (f'<div style="margin-right:22px;"><b style="color:{color};">'
                            f'{titulo}</b><br><span style="color:#5b4a48;">sin variables '
                            'de este tipo</span></div>')
                # Una variable puede venir con valor distinto por vano: se agrupa por
                # nombre y se dice EN CUANTOS vanos va, en vez de repetir el renglon.
                _agr = {}
                for _lab, _val in filas:
                    _agr.setdefault(_lab, []).append(_val)
                _r = ''.join(
                    f'<tr><td><b>{lab}</b></td>'
                    f'<td style="text-align:right;color:{color};">'
                    f'{_valor_legible(vals)}</td>'
                    f'<td style="color:#5b4a48;">en {len(vals)} vano(s)</td></tr>'
                    for lab, vals in _agr.items())
                return (f'<div style="margin-right:22px;"><b style="color:{color};">{titulo}'
                        f'</b><table style="font-size:11px;border-collapse:collapse;">{_r}'
                        '</table></div>')

            STATUS.value = (
                '<div style="font-size:12px;color:#2b2b2b;">'
                f'<b>{cambian}</b> de {metadata["n_vanos"]} vanos cambian de grupo de '
                f'criticidad{costo}{avisos}'
                '<div style="display:flex;flex-flow:row wrap;align-items:flex-start;'
                'margin-top:4px;">'
                + _bloque('Intervencion &mdash; lo que se HACE', '#0072b2',
                          _por_grupo['Intervencion'])
                + _bloque('Escenario &mdash; bajo que CONDICIONES', '#b45309',
                          _por_grupo['Escenario'])
                + '</div></div>'
            )
            _redibujar_mapa_predicho()
            _pintar_grafo(grafo)
            _pintar_top_por_vano(top_por_vano)
            _pintar_barras_uiti(resultado, ventana_i, circuito)
            _pintar_costos(costos)

        aplicar_si_vigente(_escribir, epoca_job=epoca_job, epoca_actual=lambda: _EPOCA)


    def _programar_simulacion(*_ignorado):
        nonlocal _EPOCA, _tarea_pendiente_simular
        if _tarea_pendiente_simular is not None and not _tarea_pendiente_simular.done():
            _tarea_pendiente_simular.cancel()
        _EPOCA = siguiente_epoca(_EPOCA)
        epoca_job = _EPOCA
        STATUS.value = 'Simulando...'

        async def _tarea():
            try:
                await asyncio.sleep(DEBOUNCE_SEGUNDOS)
            except asyncio.CancelledError:
                return
            _simular(epoca_job)

        _tarea_pendiente_simular = asyncio.ensure_future(_tarea())


    def _al_pedir_diagnostico(*_ignorado):
        """Calcula el diagnostico y deja MARCADOS los vanos que identifico.

    Marcarlos es parte de la respuesta, no un paso aparte: el diagnostico nombra hasta
    quince vanos y sin marcarlos hay que buscarlos a mano en la lista de casillas y otra
    vez en el mapa, que es justo el trabajo que el boton venia a ahorrar. Al marcarlos,
    el mapa base los encierra en su recuadro y la rejilla les abre columna.

    Lo que el usuario ya tenia marcado SOBREVIVE: entra al diagnostico como entrada y
    vuelve marcado, ahora acompaniado del relleno por UITI. Lo unico que puede caerse es
    un vano marcado sin eventos en la ventana -- el modelo no lo puede puntuar --, y el
    texto del diagnostico lo nombra en vez de dejarlo desaparecer.

    Las VARIABLES no se tocan aqui. Que vanos mirar y que moverles son dos decisiones, y
    los dos botones de aplicar son los que responden la segunda.
    """
        nonlocal _ULTIMO_DIAGNOSTICO, _GRUPOS_APLICADOS
        DIAGNOSTICO.value = ('<span style="font-size:12px;color:#5b4a48;">'
                             'Calculando el diagnostico del circuito...</span>')
        _ULTIMO_DIAGNOSTICO = _diagnostico_del_circuito()
        DIAGNOSTICO.value = _texto_del_diagnostico(_ULTIMO_DIAGNOSTICO)
        # Un diagnostico nuevo empieza sin nada aplicado: los grupos que se hubieran aplicado
        # al anterior describian otros vanos.
        _GRUPOS_APLICADOS = []
        AVISO_APLICAR.value = ''
        if _ULTIMO_DIAGNOSTICO and _ULTIMO_DIAGNOSTICO['vanos']:
            vano_widget.value = tuple(
                f for f, _u, _n in _ULTIMO_DIAGNOSTICO['vanos'][:MAX_VANOS_ANALISIS])


    def _aplicar_sugerencia(clave, nombre):
        """Marca los vanos del diagnostico y abre sus controles en el valor SUGERIDO.

    Es el puente entre el diagnostico y el simulador: sin el, leer "lleva NR_T a 116"
    para diez vanos obliga a marcarlos uno por uno y teclear cuarenta valores, y en ese
    trayecto se pierde justamente lo que el diagnostico acababa de calcular.

    El valor es el de CADA vano y no el promedio: el promedio ordena la lista, pero lo
    que baja a un vano concreto es su propio optimo, y aplicar el promedio simularia un
    escenario que no es el de ninguno.

    La seleccion de variables queda EXACTAMENTE en los grupos aplicados, y no se suma a
    lo que hubiera marcado antes. Es lo que hace que el resultado sea legible: si al
    aplicar intervencion quedaran ademas variables de escenario de una vuelta anterior,
    la simulacion mezclaria obra y clima y no se sabria cual de los dos movio el UITI.
    Para ver los dos efectos juntos se presionan los DOS botones -- el segundo conserva
    lo del primero --, que es una decision del usuario y no un residuo.
    """
        nonlocal _GRUPOS_APLICADOS
        if _ULTIMO_DIAGNOSTICO is None or not _ULTIMO_DIAGNOSTICO['vanos']:
            AVISO_APLICAR.value = ('<span style="font-size:12px;color:#b91c1c;">Primero '
                                   'presiona <b>Diagnostico</b>.</span>')
            return
        diag = _ULTIMO_DIAGNOSTICO
        sugeridas = diag[clave]
        if not sugeridas:
            AVISO_APLICAR.value = (f'<span style="font-size:12px;color:#b91c1c;">El '
                                   f'diagnostico no trae variables de {nombre}.</span>')
            return
        fids = [f for f, _u, _n in diag['vanos']][:MAX_VANOS_ANALISIS]
        if clave not in _GRUPOS_APLICADOS:
            _GRUPOS_APLICADOS.append(clave)
        # El ORDEN es el de los botones y no el de los clics, para que la rejilla no se
        # baraje segun por cual se empezo.
        ids_sugeridos = [e['knob_id'] for g in GRUPOS_SUGERIDOS if g in _GRUPOS_APLICADOS
                         for _lab, e in diag[g]]

        vano_widget.value = tuple(fids)
        knob_selector_widget.value = tuple(dict.fromkeys(ids_sugeridos))
        _reconstruir_controles_knob()

        # Y ahora el valor sugerido de cada vano, encima del valor actual con que abrio cada
        # control. Un valor fuera de los limites del deslizador se recorta: `FloatSlider`
        # lanza si cae fuera de [min, max], y tumbar el panel por un decimal no vale la pena.
        aplicados = 0
        for fid in fids:
            filas = {f['knob_id']: f['valor'] for f in diag['ranking'].get(fid, {}).get('filas', [])}
            for knob_id in ids_sugeridos:
                control = _controles_por_vano.get(fid, {}).get(knob_id)
                if control is None or knob_id not in filas:
                    continue
                knob = _knobs_por_id[knob_id]
                valor = filas[knob_id]
                if knob.kind == 'numeric':
                    lo, hi = knob.bounds
                    control.value = float(min(max(float(valor), lo), hi))
                elif knob.kind == 'categorical' and valor in (knob.categories or ()):
                    control.value = valor
                aplicados += 1
        _activos = ' + '.join(NOMBRES_SUGERIDOS[g] for g in GRUPOS_SUGERIDOS
                              if g in _GRUPOS_APLICADOS)
        AVISO_APLICAR.value = (
            f'<span style="font-size:12px;color:#15803d;">{len(fids)} vanos marcados y '
            f'{aplicados} controles abiertos en su valor sugerido. La simulación va a usar '
            f'<b>solo variables de {_activos}</b>'
            + ('.' if len(_GRUPOS_APLICADOS) == len(GRUPOS_SUGERIDOS) else
               f'; presiona también el otro botón si quieres las dos mitades.')
            + ' Presiona <b>Simular</b> para ver el efecto.</span>')


    boton_aplicar_intervencion.on_click(
        lambda _b: _aplicar_sugerencia('intervencion', 'Intervencion'))
    boton_aplicar_escenario.on_click(lambda _b: _aplicar_sugerencia('escenario', 'Escenario'))


    boton_diagnostico.on_click(_al_pedir_diagnostico)
    # El diagnostico describe UN circuito en UNA ventana: al cambiar cualquiera de los dos
    # deja de corresponder, y dejarlo en pantalla seria describir otra seleccion.
    def _olvidar_diagnostico(_cambio=None):
        nonlocal _ULTIMO_DIAGNOSTICO, _GRUPOS_APLICADOS
        _ULTIMO_DIAGNOSTICO = None
        _GRUPOS_APLICADOS = []
        DIAGNOSTICO.value = _texto_del_diagnostico(None)
        AVISO_APLICAR.value = ''


    circuito_widget.observe(_olvidar_diagnostico, names='value')
    ventana_widget.observe(_olvidar_diagnostico, names='value')

    def _limpiar_todo(*_ignorado):
        """Deja el tablero listo para una simulacion NUEVA, sin recargar el cuaderno.

    Limpiar es una sola cosa para el usuario, pero por dentro son tres estados que se
    mantienen aparte a proposito y que hay que soltar juntos: lo MARCADO (vanos,
    variables, actividades), lo DIAGNOSTICADO y lo SIMULADO. Dejar cualquiera de los
    tres puesto es peor que no limpiar: un diagnostico viejo sobre una seleccion vacia
    afirma sobre vanos que ya nadie eligio.

    El orden importa. Los selectores se vacian PRIMERO porque cada uno dispara
    `_reconstruir_controles_knob`, que es lo que deja sin columnas la rejilla de
    variables por vano y sin filas la de actividades; hacerlo despues de limpiar las
    figuras volveria a poblar la rejilla desde la seleccion que aun no se ha soltado.

    El mapa base se recentra en el circuito de ultimo: encuadrar antes de desmarcar
    calcularia la vista sobre los vanos que estan a punto de dejar de estar marcados.
    """
        circuito = circuito_widget.value
        with fig.batch_update():
            vano_widget.desmarcar_todos()
            knob_selector_widget.desmarcar_todos()
            item_selector_widget.desmarcar_todos()
            _olvidar_diagnostico()
            _limpiar_resultado_simulacion()
            STATUS.value = TEXTO_STATUS_INICIAL
            # El mapa base vuelve al circuito completo. El simulado ya lo devolvio
            # `_limpiar_resultado_simulacion` al vaciar su resultado.
            _aplicar_vista('map', _vista_del_circuito(circuito))


    boton_simular.on_click(_programar_simulacion)
    boton_limpiar.on_click(_limpiar_todo)
    circuito_widget.observe(_limpiar_resultado_simulacion, names='value')
    ventana_widget.observe(_limpiar_resultado_simulacion, names='value')
    vano_widget.observe(_redibujar_mapa_predicho, names='value')  # solo redibuja el halo marcado

    _redibujar_mapa_predicho()  # primer dibujo: sin simulacion todavia -> "Aun no simulado"
    _pintar_grafo(None)
    _pintar_costos(None)
    _reconstruir_controles_knob()   # la rejilla arranca con su aviso, no vacia

    # --- El panel, ARRIBA y del ancho de la figura (paridad 01.4) -----------------------
    # Una sola columna, en el orden en que se usa: circuito -> ventana -> vanos -> variables
    # del simulador -> el control de cada variable elegida -> "Simular" -> estado. Cada paso
    # depende del anterior, asi que apilarlos evita el zigzag de un flex-wrap donde el boton
    # podia quedar antes de los deslizadores que lo alimentan.
    #
    # El estilo va por CSS y no por `Layout` porque ipywidgets 8 no expone `background`,
    # `box-sizing` ni `gap` como traits -- solo `border`, `padding`, `margin` y el flexbox
    # basico. `add_class` es la via soportada para lo demas.
    ESTILO = widgets.HTML('''
<style>
  .panel-v15 {
    box-sizing: border-box;
    border-radius: 6px; background: #f3f8ec; color: #2b2b2b; font-size: 13px;
  }
  /* Cada grupo, un renglon completo: el panel es una columna, no una grilla. */
  .panel-v15 .grupo-v15 { margin: 0 0 10px 0; width: 100%; }
  .panel-v15 .titulo-v15 { font-weight: 600; margin-bottom: 2px; }
  /* La figura no lleva ancho fijo: sin esto se quedaria en el ancho intrinseco que
     plotly.js calcula al montar, en vez de ocupar la celda. */
  .app-v15, .app-v15 > .widget-vbox, .app-v15 .js-plotly-plot,
  .app-v15 .plot-container, .app-v15 .svg-container { width: 100% !important; }
  /* La lista compacta de 01.4: letra 12px, muchas casillas por renglon y scroll propio en
     vez de estirar el panel cuando el circuito tiene cientos de vanos.
     El ancho de cada casilla NO se toca aqui: viaja como estilo inline desde su `Layout`
     y le ganaria a esta hoja igual. */
  /* La barra de ventana se llena de rojo al avanzar, igual que en 03 y 04. Alli son
     `<input type="range">` nativos y basta `accent-color`; aqui NO sirve, porque
     ipywidgets 8 no dibuja un range nativo sino un noUiSlider, y `accent-color` no
     pinta un div. La parte llena es `.noUi-connect` -- el widget crea el deslizador
     con `connect: true`, verificado en `widget_selection.js` --, asi que se pinta esa.
     Vale para TODOS los deslizadores del panel y no solo el de ventana: una barra roja
     al lado de las azules de los controles se lee como un error, no como jerarquia. */
  /* El tramo lleno del deslizador va en el verde CITRICO, que es el color PRIMARIO de la
     marca. El asa se queda en el bosque: es el borde de un control que se toca y necesita
     el contraste que el citrico no da. */
  .app-v15 .noUi-connect { background: rgb(139,194,27); }
  .app-v15 .noUi-handle { border-color: rgb(0,128,36); }
  .lista-vanos, .lista-variables, .lista-items { font-size: 12px; }
  .lista-vanos .widget-checkbox label,
  .lista-variables .widget-checkbox label { white-space: nowrap; font-weight: 400; }
  /* Las actividades del contrato llegan a 143 caracteres y el ancho de la casilla es
     fijo: sin `ellipsis` el nombre se corta a la mitad de una palabra y dos actividades
     de la misma familia se vuelven indistinguibles. El `title` de la casilla lo lleva
     completo. */
  .lista-items .widget-checkbox label {
    white-space: nowrap; font-weight: 400;
    overflow: hidden; text-overflow: ellipsis;
  }
</style>''')


    def _grupo(*hijos):
        """Un bloque del panel: su rotulo y sus controles juntos, como los `div` de 01.4."""
        caja = widgets.VBox(list(hijos), layout=widgets.Layout(align_items='flex-start',
                                                               width='100%'))
        caja.add_class('grupo-v15')
        return caja


    def _titulo(texto):
        return widgets.HTML(f'<span class="titulo-v15">{texto}</span>')


    vano_widget.caja.add_class('lista-vanos')
    knob_selector_widget.caja.add_class('lista-variables')
    item_selector_widget.caja.add_class('lista-items')

    # El panel se alinea con el AREA DE DIBUJO de la figura, no con su borde. Los dos
    # ocupan el mismo ancho, pero la figura reserva margen para los rotulos de los ejes de
    # la primera columna, asi que sus paneles empiezan mas adentro que los controles y las
    # dos cosas se leian corridas. El relleno se DERIVA del margen -- menos el ancho de los
    # bordes del propio panel -- para que cambiar uno mueva al otro y no se desincronicen.
    _BORDE_IZQ, _BORDE = 4, 1     # los mismos que declara `layout` mas abajo
    _RELLENO_IZQ = max(int(fig.layout.margin.l) - _BORDE_IZQ, 0)
    _RELLENO_DER = max(int(fig.layout.margin.r) - _BORDE, 0)

    PANEL = widgets.VBox(
        [
            # Sin rotulo: el desplegable MUESTRA el circuito y el deslizador su rango al
            # lado, asi que nombrarlos era repetir lo que el propio control ya dice.
            _grupo(circuito_widget),
            _grupo(ventana_widget),
            _grupo(vano_widget,
                   widgets.HBox([boton_desmarcar, boton_top_ventana]),
                   AVISO_VANOS),
            _grupo(_titulo('Variables del simulador'), knob_selector_widget,
                   AVISO_BLOQUEADOS),
            # Las actividades van DESPUES de las variables y antes de la rejilla, en el
            # orden en que se usa el panel: primero que le muevo al vano, despues que obra
            # le hago, y la rejilla de abajo reune las dos por vano.
            _grupo(_titulo('Actividades del contrato (costo de intervencion)'),
                   item_selector_widget,
                   widgets.HTML('<span style="font-size:12px;color:#5b4a48;">Lo que marques '
                                'aqui aparece como una fila bajo CADA vano marcado, con su '
                                'costo unitario.</span>'),
                   AVISO_SIN_COSTO),
            _grupo(controles_knob_box),
            _grupo(widgets.HTML(
                       '<span style="font-size:12px;color:#5b4a48;"><b>Diagnostico</b> '
                       'estudia los vanos que hayas marcado arriba y, si no llegan a '
                       f'{TOP_VANOS_CIRCUITO}, completa con los de mayor UITI de la ventana. '
                       'Sin nada marcado toma directamente ese top.</span>'),
                   widgets.HBox([boton_diagnostico]), DIAGNOSTICO,
                   widgets.HBox([boton_aplicar_intervencion, boton_aplicar_escenario]),
                   AVISO_APLICAR),
            _grupo(widgets.HBox([boton_simular, boton_limpiar])),
            _grupo(STATUS),
        ],
        layout=widgets.Layout(
            width='100%', align_items='flex-start',
            padding=f'12px {_RELLENO_DER}px 12px {_RELLENO_IZQ}px', margin='0 0 6px 0',
            border=f'{_BORDE}px solid #cfe3ac',
            border_left=f'{_BORDE_IZQ}px solid rgb(0,128,36)',
        ),
    )
    PANEL.add_class('panel-v15')

    # Un boton de encuadre por mapa, en una fila que los deja cada uno sobre el suyo: los dos
    # mapas ocupan mitades iguales del ancho, asi que dos cajas al 50% ponen cada boton donde
    # empieza su mapa. Son widgets y no botones de plotly (`updatemenus`) porque un
    # `updatemenu` lleva argumentos FIJOS, calculados al dibujar: entre el dibujo y el clic
    # pueden haber cambiado los vanos marcados, y el boton llevaria a donde estaba la
    # seleccion antes. Aqui la vista se calcula en el clic.
    def _boton_encuadre(nombre_mapa, etiqueta):
        boton = widgets.Button(description=etiqueta, layout=widgets.Layout(width='260px'),
                               tooltip='Centra sobre los vanos marcados, o sobre el circuito '
                                       'si no hay ninguno')
        boton.on_click(lambda _b: _centrar_mapa(nombre_mapa))
        return widgets.Box([boton], layout=widgets.Layout(width='50%'))


    ENCUADRES = widgets.HBox(
        [_boton_encuadre('map', 'Centrar mapa base'),
         _boton_encuadre('map2', 'Centrar mapa simulado')],
        layout=widgets.Layout(width='100%',
                              padding=f'0 {_RELLENO_DER}px 0 {_RELLENO_IZQ}px'))

    # El tablero en DOS COLUMNAS: los controles a la izquierda, las figuras a la derecha.
    #
    # Iban uno encima del otro y los dos a lo ancho entero. Medido en el navegador sobre la
    # aplicacion servida, ventana de 1.512 px: 1.341 px de panel MAS 2.489 px de figura, o
    # sea 3.912 px de pagina. Elegir una variable y ver que le hace al mapa quedaban en
    # extremos opuestos del scroll. En columnas la pagina baja a 2.565 px -- un 34% menos --
    # porque las dos piezas dejan de sumarse a lo alto.
    #
    # 30/70 y no mitad y mitad: lo que manda es la figura. Con el panel al 50% la figura se
    # queda en 741 px y sus dos mapas, que ocupan mitades de esa fila, bajarian de 614 a 300
    # px cada uno. Al 70% mide 1.037 px, que es de donde salen los 414 px de lado del grafo.
    #
    # En porcentaje y no en pixeles: esto se sirve en pantallas de 1.280 a 1.900 px y un
    # ancho fijo deja banda blanca en la grande o corta en la chica.
    COLUMNA_CONTROLES = widgets.VBox(
        [PANEL], layout=widgets.Layout(width='30%', align_items='stretch'))
    # Los dos botones de encuadre viajan con la FIGURA y no con los controles: cada uno se
    # posa sobre su mapa, y en la otra columna apuntarian a un sitio donde no hay mapa.
    COLUMNA_FIGURAS = widgets.VBox(
        [ENCUADRES, fig], layout=widgets.Layout(width='70%', align_items='stretch'))
    # `align_items='flex-start'`: sin esto las dos columnas se estiran a la altura de la mas
    # alta, y la corta queda con un vacio abajo que se lee como un panel a medio cargar.
    CUERPO = widgets.HBox([COLUMNA_CONTROLES, COLUMNA_FIGURAS],
                          layout=widgets.Layout(width='100%', align_items='flex-start'))
    # El encabezado: el titulo a la IZQUIERDA del todo y lo que traiga la aplicacion -- su
    # barra de cerrar -- a la derecha, en la misma fila.
    #
    # `space-between` y no dos cajas al 50%: el titulo mide lo que mide y el boton tambien,
    # y repartir a medias deja a uno de los dos flotando en su mitad.
    #
    # Cuando nadie pasa `encabezado` -- el tablero dentro de un cuaderno, sin aplicacion que
    # cerrar -- la fila se queda solo con el titulo, y `space-between` sobre un unico hijo
    # lo deja donde tiene que estar: a la izquierda.
    ENCABEZADO_TITULO = widgets.HTML(
        # `nowrap`: en la fila del encabezado el titulo comparte ancho con la barra de
        # cerrar, y sin esto se parte en dos renglones cuando la ventana se estrecha.
        '<span style="font-family:system-ui,-apple-system,\'Segoe UI\',sans-serif;'
        'font-size:19px;color:#2b2b2b;white-space:nowrap;">'
        '<b>Simulador Criticidad</b></span>')
    # El cierre ABRE la fila y el titulo va detras. `flex-start` y no `space-between`:
    # repartir a los extremos era lo que ponia al boton a pelear el ancho con el titulo,
    # y quien cedia era el boton.
    ENCABEZADO = widgets.HBox(
        [*encabezado, ENCABEZADO_TITULO],
        layout=widgets.Layout(width='100%', justify_content='flex-start',
                              align_items='center', padding='4px 12px'))

    APP = widgets.VBox([ENCABEZADO, ESTILO, CUERPO],
                       layout=widgets.Layout(width='100%'))
    APP.add_class('app-v15')
    # `display` explicito y una sola vez. `add_class` devuelve el propio widget, asi que
    # dejarlo como ultima expresion de la celda hacia que Jupyter lo auto-mostrara ADEMAS del
    # display de la celda siguiente: el tablero aparecia dos veces.
    def _sincronizar_estado_inicial(figura):
        """Deja el dibujo YA HECHO dentro del estado con el que nace la vista del widget.

    `fig` se pinta entera antes de mostrarse: los `batch_update` de arriba dejaron los
    dos mapas con la geometria del circuito inicial y su encuadre. Pero plotly manda esos
    cambios como mensajes `_py2js_*` a las vistas ATADAS, y aqui todavia no hay ninguna
    -- la vista nace con el `display` de abajo --, asi que esos mensajes se pierden. El
    estado con el que la vista nace lo llevan `_widget_data` y `_widget_layout`, y plotly
    solo los refresca en dos sitios (`basewidget.py`, plotly 6.9): al construir la figura
    y dentro de `fig._repr_mimebundle_()`. Ese segundo no corre NUNCA aqui, porque lo que
    se muestra es el VBox y la figura viaja dentro de el.

    Sin esta llamada el tablero abre con los dos mapas VACIOS -- sin tramos, sin equipos y
    sobre el centro y el zoom por defecto -- y solo se pinta cuando algo dispara el
    siguiente repintado: cambiar de circuito, mover la ventana o marcar un vano. Medido
    en la aplicacion servida con Voila: 0 trazas con `lat` en el navegador y zoom 10 sobre
    Manizales, en vez de zoom 15 sobre el circuito.

    Se copia exactamente lo que copia `_repr_mimebundle_`. Si una version futura de plotly
    renombra esos atributos, falla AQUI y con un mensaje que dice que mirar, en vez de
    abrir un tablero mudo.
    """
        import copy

        faltan = [n for n in ("_widget_layout", "_widget_data", "_layout_obj", "_data")
                  if not hasattr(figura, n)]
        if faltan:
            raise AttributeError(
                f"plotly cambio como sincroniza el estado del FigureWidget (faltan {faltan}). "
                "Sin esto el tablero abre con los mapas vacios: mira `_repr_mimebundle_` en "
                "plotly/basewidget.py y actualiza esta funcion.")
        figura._widget_layout = copy.deepcopy(figura._layout_obj._props)
        figura._widget_data = copy.deepcopy(figura._data)


    _sincronizar_estado_inicial(fig)
    return APP
