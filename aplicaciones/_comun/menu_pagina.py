"""La pagina del menu de CriticidadCHEC. Un solo documento, sin dependencias.

Va aparte de `menu.py` porque son dos cosas distintas -- gobernar procesos y dibujar
una pagina -- y juntas hacian un archivo en el que ninguna de las dos se encontraba.

## El detalle que gobierna todo el JavaScript de aqui

La pestania del tablero se abre con `window.open()` **dentro del manejador del clic**,
antes de preguntarle nada al servidor. Dos razones, las dos medidas contra navegadores
reales:

1. Un `window.open()` que no cuelga de un gesto del usuario lo bloquea el navegador. Y
   preparar una aplicacion puede tardar minutos la primera vez -- crear su entorno,
   ejecutar su cuaderno --, asi que esperar y abrir despues es exactamente el caso que
   se bloquea.
2. Una ventana que abrio un script SI la puede cerrar un script. Es lo que hace que
   "Volver al menu" pueda cerrar la pestania de verdad, sin depender de si tiene
   historial propio. Abrirla de cualquier otra forma pierde ese permiso.

Asi que se abre en blanco, se le escribe un mensaje de espera, y cuando el servidor
contesta que la aplicacion ya responde se le pone la URL encima.
"""
from __future__ import annotations

import base64
from pathlib import Path
from string import Template

import paleta as _paleta
import raiz as _raiz
# Al NIVEL DEL MODULO y no dentro de `pagina()`: estos modulos se importan con
# `aplicaciones/_comun` puesto en `sys.path` un momento y retirado despues, asi que un
# import diferido corre cuando la ruta ya no esta y no encuentra nada.
import tableros as _tableros

# Donde viven los logos. Se LEEN de donde ya estan y no se copian a otra carpeta: dos
# copias del mismo PNG se separan el dia que alguien actualice una.
_LOGOS = _raiz.RAIZ_REPO / "site" / "assets" / "site" / "logos"


def _logo(nombre: str) -> str:
    """El logo como `data:` URI, o cadena vacia si no esta.

    Embebido y no enlazado porque el menu sirve UNA pagina y nada mas: no tiene ruta para
    archivos estaticos, asi que un `src="/logos/..."` daria 404. Y una ruta del disco
    depende de desde donde se haya abierto la aplicacion.

    Y devuelve vacio en vez de reventar: el menu es lo unico que el usuario tiene para
    arrancar los tableros, y no abrirlo porque falta un PNG decorativo seria cambiar un
    adorno por la aplicacion entera.
    """
    archivo = _LOGOS / nombre
    if not archivo.is_file():
        return ""
    return "data:image/png;base64," + base64.b64encode(archivo.read_bytes()).decode("ascii")

# Sin `color-scheme` ni bloque de modo oscuro, a proposito. Los cinco tableros fijan
# `background:#fff` y no responden al tema del sistema; un menu que si lo hiciera se
# volveria oscuro y mandaria al usuario a un tablero blanco de un clic. La armonia aqui
# vale mas que atender una preferencia que los tableros ignoran.
_ESTILO = Template("""
* { box-sizing: border-box; }
body { margin: 0; padding: 12px; font: 14px/1.55 $FUENTE;
       background: $FONDO; color: $TEXTO; }
/* 1.720 y no 1.180: con la columna de botones en 950 px un tope de 1.180 dejaria al
   diagrama con 200, y a ese tamanio su texto no se lee. El tope existe para que la
   portada no se estire sin fin en un monitor ancho, no para apretarla. */
.envoltura { max-width: 1720px; margin: 0 auto; padding: 20px 8px 60px; }

/* La portada: los botones a la izquierda y el diagrama a la derecha.
   La columna de los botones lleva ancho FIJO y la del diagrama toma el resto. Con las dos
   al 50% -- o con `1fr 1fr` -- la lista de cinco tarjetas se estira en una pantalla ancha
   y el diagrama, que es lo que hay que leer de un vistazo, se queda con una franja.
   `minmax(0, 1fr)` en la derecha y no `1fr` a secas: una celda de rejilla no baja de su
   contenido minimo, y el SVG tiene uno propio. */
.portada { display: grid; grid-template-columns: 665px minmax(0, 1fr); gap: 34px;
           align-items: start; }
/* 665 px: un 30% menos. Los 950 existian porque el texto de esta columna iba al TRIPLE
   y una columna que no crece con el parte cada tarjeta en tres renglones; con las
   tarjetas a la mitad, esos 950 se vuelven aire. Los dos numeros van juntos. */
/* Y en pantalla estrecha se apilan, con los botones primero: son lo unico accionable.
   El umbral se MUEVE con la columna, y no a ojo: 1.259 es el ancho exacto al que el SVG
   sale a escala 1:1 -- 24 de `body` + 16 de `.envoltura` + 665 de columna + 34 de hueco +
   los 520 de su `viewBox` --. Por debajo de eso el diagrama se dibuja MAS PEQUENIO de lo
   disenado, asi que su letra de 9 baja de 9. Y por encima, un umbral que no baje con la
   columna apila la portada en anchos donde las dos columnas ya caben. */
@media (max-width: 1259px) { .portada { grid-template-columns: 1fr; } }

/* Los logos, al pie de su columna y CENTRADOS. Viajan tal cual los aprobo la marca: aqui
   no se recolorean. Los DOS van juntos al pie de la columna izquierda: primero de quien es
   el producto y debajo quien lo construyo. Estuvieron separados -- la firma bajo el
   diagrama, en la otra columna -- y asi se leian como dos marcas de dos sitios distintos
   en vez de como una atribucion. */
.logos { margin: 34px 4px 0; padding-top: 26px; border-top: 1px solid $BORDE;
         text-align: center; }
/* El de CHEC al TRIPLE -- 132 px donde habia 44 -- y solo en su renglon. */
.logos .marca img { height: 132px; width: auto; }
.logos .firma { display: flex; align-items: center; justify-content: center; gap: 16px; }
/* La separacion se ata al hermano que la justifica. Suelta en `.logos .firma` se aplicaba
   tambien debajo del diagrama, donde la firma no tiene nada encima dentro de su caja, y
   se sumaba al `padding-top` del bloque abriendo un hueco que nadie pidio. */
.marca + .firma { margin-top: 30px; }
/* El rotulo no crece con el logo: es una firma, no un titulo. */
.logos .firma span { font-size: 25px; color: $TENUE; }
.logos .firma img { height: 156px; width: auto; }

.col-der svg { width: 100%; height: auto; }
/* La cabecera se quedo con un solo hijo -- el boton -- desde que el titulo bajo a la
   columna izquierda. `flex-end` y no `space-between`: con un solo hijo, repartir el
   espacio entre los extremos lo deja pegado a la IZQUIERDA. */
header { display: flex; align-items: flex-start; justify-content: flex-end;
         gap: 20px; margin-bottom: 22px; }
h1 { font-size: 24px; margin: 0; letter-spacing: -.01em; }
/* Los DOS titulos de la portada, uno por columna, centrados y del mismo tamanio. Una sola
   regla: escritos aparte se separan al primer ajuste de uno solo, y con tamanios distintos
   el mayor se leeria como titulo de la pagina y el otro como subtitulo suyo.
   Va aqui y no en `h1` a secas porque `.cerrado h1` -- la pantalla de despedida, que
   escribe el JavaScript -- es otra cosa y no tiene por que crecer con estos. */
.portada h1 { font-size: 42px; text-align: center; margin-bottom: 22px; }

/* El filo izquierdo rojo es el gesto que repiten los cinco tableros en sus paneles de
   control. Cada aplicacion del menu es una tarjeta con ese mismo filo, asi que la
   pagina se lee como parte de la familia y no como una portada de otro sitio. */
/* A la MITAD, y no solo la letra: el relleno, el hueco y el filo izquierdo se subieron
   A LA VEZ que el texto -- "el contenido se sale de una caja que no crecio" --, asi que
   bajan juntos. Bajar solo la letra deja tarjetas casi igual de altas con un renglon
   perdido en el medio. */
.tarjeta { display: flex; align-items: center; gap: 24px; background: $PANEL;
           border: 1px solid $BORDE; border-left: 6px solid $ACENTO; border-radius: 5px;
           padding: 13px 16px; margin-bottom: 9px; font-size: 19px; line-height: 1.25; }
.texto { flex: 1; min-width: 0; }
.titulo { font-weight: 600; margin-bottom: 2px; }
.desc { color: $TENUE; font-size: 14.5px; }
/* El aviso de la emergente bloqueada. En el acento y no en el gris de `.desc`: es lo
   unico que explica por que un tablero que dice "corriendo" no se ve en ninguna parte.
   SE QUEDA EN 7 px y sale de la escala del panel. Bajo cuatro veces con el resto (12,
   11, 9, 7) porque nadie lo mira: solo aparece cuando el navegador bloquea una emergente.
   A 7 px ya esta 5,7 veces por debajo del titulo de su propia tarjeta, medido, y un aviso
   que no se puede leer es lo mismo que no tenerlo. */
.aviso { color: $ACENTO_OSCURO; font-size: 7px; margin-top: 4px; }
/* Con la letra en 19 px, un punto de 27 seria mas alto que el texto al que acompania. */
.punto { width: 14px; height: 14px; border-radius: 50%; flex: none;
         background: $BORDE_FUERTE; }
.punto.corriendo { background: $ACENTO; }
.punto.preparando { background: $BORDE_FUERTE; box-shadow: 0 0 0 3px $BORDE; }
.punto.fallo { background: $ACENTO_OSCURO; }

button { font: inherit; font-size: 12px; font-weight: 600; padding: 6px 12px;
         border-radius: 4px; border: 1px solid $BORDE_FUERTE; background: $FONDO;
         color: $TEXTO; cursor: pointer; white-space: nowrap; }
/* Y el de cada tarjeta a la mitad, CAJA INCLUIDA: el relleno esta en pixeles y no en
   `em`, asi que achicar solo la letra deja el mismo boton con el texto flotando dentro. */
.tarjeta button { font-size: 16px; padding: 9px 18px; border-radius: 5px;
                  border-width: 1.5px; }
/* `Cerrar todo` al DOBLE del boton base. La caja dobla con el texto: ampliar solo la
   letra la desborda, porque el relleno esta en pixeles y no en `em`. El radio y el filo
   suben con ella o se pierden contra un boton dos veces mas grande. */
#cerrar-todo { font-size: 24px; padding: 12px 24px; border-radius: 8px;
               border-width: 2px; }
button:hover:not(:disabled) { background: $PANEL; }
button:disabled { opacity: .55; cursor: default; }
/* Rojo lleno para la accion principal, igual que los botones de los tableros. */
button.principal { border-color: $ACENTO; background: $ACENTO; color: $FONDO; }
button.principal:hover:not(:disabled) { background: $ACENTO_OSCURO;
                                        border-color: $ACENTO_OSCURO; }
/* "Cerrar todo" va en rojo perfilado y no relleno: es destructivo, pero no es la
   accion que uno viene a hacer. El relleno se reserva para "Abrir". */
button.peligro { border-color: $ACENTO; background: $FONDO; color: $ACENTO; }
button.peligro:hover:not(:disabled) { background: $PANEL; }

.cerrado { padding: 60px 20px; text-align: center; }
.cerrado h1 { margin-bottom: 10px; }
""").substitute(_paleta.TOKENS, FUENTE=_paleta.FUENTE, FILO=_paleta.FILO)

_GUION = """
var APPS = [];

// Las pestanias que ha abierto ESTA pagina, por clave de aplicacion. Es lo unico que da
// permiso para cerrarlas: un navegador solo deja que un script cierre lo que ese mismo
// script abrio. El objeto que devuelve `window.open` era una variable local del
// manejador del clic, o sea que el permiso se tiraba en cuanto acababa el clic, y
// "Cerrar todo" apagaba los cinco servidores dejando cinco pestanias en pantalla sobre
// tableros muertos. Apagar el proceso y dejar su ventana es medio apagado.
var PESTANIAS = {};

// Las aplicaciones a las que el navegador les BLOQUEO la pestania. `window.open()`
// devuelve null cuando eso pasa, y ese null se perdia: la aplicacion arrancaba, tomaba
// su puerto y llegaba a "corriendo", pero la unica linea que le pone la URL encima --
// `pestania.location = app.url` -- no hacia nada, y nadie decia por que. Desde la silla
// del usuario eso se lee como "no me deja abrir otro", que es justo el caso: la primera
// emergente pasa por el gesto del clic y las siguientes las bloquea la politica del
// navegador mientras siga viva una pestania que abrio un script.
//
// Forzar la emergente no se puede desde JavaScript. Lo que si se puede es dejar de
// callarselo.
var BLOQUEADAS = {};

function recordarPestania(clave, pestania) {
  if (pestania) {
    PESTANIAS[clave] = pestania;
    delete BLOQUEADAS[clave];
  } else {
    BLOQUEADAS[clave] = true;
  }
}

function cerrarPestania(clave) {
  var pestania = PESTANIAS[clave];
  delete PESTANIAS[clave];
  if (!pestania) { return; }
  // Protegido a proposito. `close()` sobre una pestania que ya se fue a otro dominio, o
  // que el usuario duplico a mano, puede levantar; sin el `try` ese fallo cortaria el
  // apagado a mitad y dejaria sin cerrar las que vienen detras.
  try {
    if (!pestania.closed) { pestania.close(); }
  } catch (e) { /* el usuario la cerrara a mano; no es motivo para parar */ }
}

function cerrarPestanias() {
  Object.keys(PESTANIAS).forEach(cerrarPestania);
}

function pintar(estado) {
  APPS = estado;
  var lista = document.getElementById('lista');
  lista.innerHTML = '';
  estado.forEach(function (app) {
    var t = document.createElement('div');
    t.className = 'tarjeta';

    var punto = document.createElement('span');
    punto.className = 'punto ' + app.fase;
    t.appendChild(punto);

    var texto = document.createElement('div');
    texto.className = 'texto';
    // Bajo el nombre NO va nada. Ni el puerto, ni "lista", ni "hay que instalarla": el
    // punto de la izquierda ya dice en que estado esta y el boton dice que se puede hacer,
    // asi que cada una de esas lineas era la misma informacion escrita dos veces.
    //
    // La UNICA excepcion es el detalle de un FALLO, y no es una etiqueta de estado: es la
    // ultima linea de pip o del constructor. `menu.py` lo dice en su encabezado -- cuando
    // algo falla "el usuario no esta mirando ninguna terminal: el menu es su unica
    // ventana" --, asi que vaciarlo tambien dejaria un fallo mudo.
    var linea = app.fase === 'fallo' ? app.detalle : '';
    texto.innerHTML = '<div class="titulo"></div><div class="desc"></div>';
    texto.querySelector('.titulo').textContent = app.titulo;
    texto.querySelector('.desc').textContent = linea;
    if (BLOQUEADAS[app.clave]) {
      // En la tarjeta y no en un `alert()`: levantar la aplicacion tarda, y el aviso
      // llegaria minutos despues del clic encima de lo que el usuario estuviera haciendo.
      var nota = document.createElement('div');
      nota.className = 'aviso';
      nota.textContent = 'El navegador bloqueo la ventana emergente: el tablero esta '
        + 'servido, pero su pestania no se abrio. Pulsa Ver, o permite las ventanas '
        + 'emergentes de este sitio.';
      texto.appendChild(nota);
    }
    t.appendChild(texto);

    if (app.fase === 'corriendo') {
      t.appendChild(boton('Ver', 'principal', function () {
        // `recordarPestania` limpia la marca si la pestania abrio, y la pone si no.
        // `Ver` cuelga de un clic directo, asi que normalmente pasa; cuando tampoco
        // pasa, insistir con el mismo boton no lo va a arreglar y el aviso se queda.
        recordarPestania(app.clave, window.open(app.url, 'app-' + app.clave));
        refrescar();
      }));
      t.appendChild(boton('Detener', '', function () {
        // Detener apaga ESA aplicacion, y su pestania es parte de ella. Las otras cuatro
        // no son asunto suyo: el unico apagado general es "Cerrar todo".
        cerrarPestania(app.clave);
        mandar('detener', app.clave);
      }));
    } else if (app.fase === 'preparando') {
      var esperando = boton('Preparando...', '', null);
      esperando.disabled = true;
      t.appendChild(esperando);
    } else {
      t.appendChild(boton('Abrir', 'principal', function () { abrir(app); }));
    }
    lista.appendChild(t);
  });
}

function boton(texto, clase, alPulsar) {
  var b = document.createElement('button');
  b.textContent = texto;
  if (clase) { b.className = clase; }
  if (alPulsar) { b.addEventListener('click', alPulsar); }
  return b;
}

function abrir(app) {
  // La pestania se abre AQUI, dentro del gesto del clic. Ver el docstring del modulo:
  // hacerlo despues de la respuesta la bloquearia el navegador y ademas perderia el
  // permiso para cerrarla desde "Volver al menu".
  var pestania = window.open('', 'app-' + app.clave);
  if (!pestania) {
    // La aplicacion se lanza IGUAL: esta corriendo y el boton `Ver` la alcanza. Lo que
    // no puede pasar es que el usuario no se entere de que no habra pestania.
    BLOQUEADAS[app.clave] = true;
  }
  if (pestania) {
    // Una sola linea. Esta pagina puede estar minutos en pantalla la primera vez, pero
    // lo que pasa mientras tanto -- crear el entorno, construir el tablero, y en que
    // paso va -- se lee en la tarjeta del menu, que sigue viva en la otra pestania. Con
    // la misma paleta: llegar al tablero no puede sentirse como cambiar de aplicacion.
    pestania.document.write(
      '<!doctype html><meta charset=utf-8><title>Cargando...</title>' +
      '<body style="font:16px/1.7 __FUENTE_JS__;padding:60px 40px;' +
      'background:__FONDO__;color:__TEXTO__">Cargando...');
  }
  recordarPestania(app.clave, pestania);
  mandar('abrir', app.clave, function () { seguir(app.clave, pestania); });
}

function seguir(clave, pestania) {
  var reloj = setInterval(function () {
    fetch('/estado').then(function (r) { return r.json(); }).then(function (estado) {
      pintar(estado);
      var app = estado.filter(function (a) { return a.clave === clave; })[0];
      if (!app) { return; }
      if (app.fase === 'corriendo') {
        clearInterval(reloj);
        if (pestania && !pestania.closed) {
          pestania.location = app.url;
        } else {
          // Aqui es donde se perdia el aviso: la aplicacion llegaba a "corriendo" y no
          // habia pestania a la que ponerle la URL. Se anota y se repinta, para que la
          // tarjeta lo diga.
          BLOQUEADAS[clave] = true;
          pintar(APPS);
        }
      } else if (app.fase === 'fallo') {
        clearInterval(reloj);
        cerrarPestania(clave);
        alert('No se pudo abrir ' + app.titulo + ':\\n\\n' + app.detalle);
      }
    });
  }, 1200);
}

function mandar(accion, clave, despues) {
  fetch('/' + accion + '?app=' + encodeURIComponent(clave), { method: 'POST' })
    .then(function (r) { return r.json(); })
    .then(function () { refrescar(); if (despues) { despues(); } });
}

function refrescar() {
  fetch('/estado').then(function (r) { return r.json(); }).then(pintar).catch(function () {});
}

function cerrarTodo() {
  if (!window.confirm('Se apagan TODAS las aplicaciones abiertas y este menu.')) { return; }
  document.getElementById('cerrar-todo').disabled = true;
  // Las pestanias primero, y no al final. Es lo unico de todo el apagado que el usuario
  // ve en el acto -- los puertos y las ventanas de terminal tardan sus segundos --, y
  // dejarlas hasta el final significaria seguir mirando cinco tableros vivos mientras
  // por detras se apagan. Cerrarlas aqui no adelanta nada del apagado de verdad: el
  // `POST` de abajo va igual, y es el que se lleva los procesos.
  cerrarPestanias();
  // Apagar cinco aplicaciones puede llevar unos segundos, y la respuesta no llega hasta
  // que se sabe como acabaron. Sin este aviso la pagina se queda igual que estaba y el
  // clic parece perdido.
  document.getElementById('lista').innerHTML =
    '<div class="tarjeta"><div class="texto">Cerrando las aplicaciones...</div></div>';
  fetch('/apagar-todo', { method: 'POST' })
    .then(function (r) { return r.json(); })
    // El menu se apaga a si mismo justo despues de contestar, asi que una respuesta que
    // se pierda por el camino no significa que fallara nada.
    .catch(function () { return { cerrado: true, vivas: [] }; })
    .then(despedirse);
}

function despedirse(resultado) {
  // Los que no soltaron su puerto se nombran uno a uno, con la orden que los cierra. Es
  // la ultima pantalla que el usuario ve del menu: lo que no se diga aqui, ya no se dice
  // en ninguna parte -- el menu se acaba de apagar.
  var aviso = '';
  (resultado.vivas || []).forEach(function (app) {
    aviso += '<p style="color:__ACENTO__"><b>' + app.titulo + '</b> sigue servida en el ' +
      'puerto ' + app.puerto + '. No la lanzo este menu, asi que no se le mando ninguna ' +
      'senal. Para cerrarla:<br><code>lsof -ti tcp:' + app.puerto +
      ' -sTCP:LISTEN | xargs kill</code></p>';
  });
  document.body.innerHTML =
    '<div class="cerrado"><h1>CriticidadCHEC cerrado</h1>' +
    '<p>Se apago el menu' + (aviso ? '' : ' y las aplicaciones que tenia abiertas') +
    '. Ya puedes cerrar esta pestana.</p>' + aviso +
    '<p style="color:__TENUE__">Para volver a abrirlo: Iniciar.app (macOS) o ' +
    'iniciar.bat (Windows).</p></div>';
  // Solo si no hay nada que leer: cerrar la pestania encima de un aviso lo haria
  // invisible, que es la forma mas silenciosa posible de perder un proceso vivo.
  if (!aviso) { window.close(); }
}

document.getElementById('cerrar-todo').addEventListener('click', cerrarTodo);
refrescar();
// El estado tambien cambia por fuera del menu: una aplicacion se puede cerrar con su
// propio boton o con Ctrl+C en su ventana, y el menu tiene que enterarse.
setInterval(refrescar, 2500);
"""
# Los marcadores se resuelven con `paleta.aplicar` y no con un bucle propio: un bucle
# propio es lo que dejo `__FUENTE_JS__` sin resolver cuando se agrego ese token, porque
# la lista de aqui no se entero. La resolucion vive en un solo sitio por eso.
_GUION = _paleta.aplicar(_GUION)


# El diagrama de bloques de la portada. SVG EN LINEA y no una imagen: es texto, se lee en
# el diff, se corrige sin abrir un editor de imagenes y hereda la paleta desde el mismo
# sitio que el resto de la pagina. Una captura habria que rehacerla cada vez que cambie un
# nombre.
#
# Los nombres de los cinco tableros NO se escriben aqui: salen de `tableros.py`, que es el
# catalogo. Escritos a mano, agregar un tablero dejaria el diagrama contando cuatro de
# cinco sin que nada fallara.
def _diagrama(titulos: list[str]) -> str:
    """El diagrama de la portada, centrado en el simulador "Que pasa si?".

    Cinco pasos, del que elige el usuario al que pulsa Simular. Los nombres de los
    botones son los REALES -- `Diagnostico`, `Intervencion`, `Escenario`, `Simular`
    existen en el tablero --, porque un diagrama que renombre lo que el usuario va a ver
    es peor que no tenerlo.

    ## Las llaves de la hoja, y por que importan

    Este texto NO es un f-string ni pasa por `.format`: lo unico que lo toca es
    `Template.substitute`, que solo resuelve `$TOKEN`. Asi que las llaves del CSS van
    SIMPLES. Escritas dobles -- resto de cuando esto si era un f-string -- viajaban tal
    cual hasta el navegador, que leia `.dn {{ ... }}` como un bloque dentro de otro, se
    quedaba con la regla VACIA y dibujaba todo el diagrama al 15px negro del `body`, sin
    ninguna flecha: un `path` sin `stroke` no pinta nada.

    ## Donde acaba

    En la pregunta. Detras hubo una seccion con las cuatro lecturas del tablero y un pie
    con una moraleja; las dos contaban lo que se ve nada mas abrir el simulador, que es
    justo lo que el simulador ya muestra.

    `titulos` entra para dejar constancia de que los cinco tableros son la familia de la
    que sale el simulador; se nombra el ultimo, que es el.
    """
    _ = titulos
    return """
<svg viewBox="0 0 520 514" role="img"
     aria-label="Cómo funciona el simulador ¿Qué pasa si…? de CriticidadCHEC">
  <defs>
    <marker id="pf" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7"
            orient="auto"><path d="M0 0 L8 4 L0 8 z" fill="$BORDE_FUERTE"/></marker>
  </defs>
  <style>
    .dt { font: 600 12.5px $FUENTE; fill: $TEXTO; }
    .dn { font: 10px $FUENTE; fill: $TENUE; }
    .dh { font: 600 10.5px $FUENTE; fill: $TENUE; letter-spacing: .06em; }
    .fl { stroke: $BORDE_FUERTE; stroke-width: 1.4; fill: none; marker-end: url(#pf); }
  </style>

  <text x="12" y="18" class="dh">1 &middot; LO QUE ELIGES</text>
  <rect x="12" y="26" width="496" height="46" rx="6" fill="$PANEL" stroke="$BORDE"/>
  <text x="260" y="45" text-anchor="middle" class="dt">Circuito, ventana y vanos marcados</text>
  <text x="260" y="61" text-anchor="middle" class="dn">más las variables y las actividades del contrato que quieras modificar</text>
  <path d="M260 72 V92" class="fl"/>

  <text x="12" y="110" class="dh">2 &middot; EL MODELO</text>
  <rect x="12" y="118" width="496" height="52" rx="6" fill="$ACENTO" stroke="$ACENTO"/>
  <text x="260" y="139" text-anchor="middle" class="dt" style="fill:#fff">Modelo de IA predictiva restringido por la física</text>
  <text x="260" y="156" text-anchor="middle" class="dn" style="fill:#fff">para estudiar las posibles causas de los fallos en cada vano</text>
  <path d="M140 170 V194" class="fl"/>
  <path d="M380 170 V194" class="fl"/>

  <text x="12" y="212" class="dh">3 &middot; LO QUE EL TABLERO ESTUDIA POR TI</text>
  <rect x="12" y="220" width="240" height="52" rx="6" fill="$PANEL" stroke="$BORDE"/>
  <text x="132" y="241" text-anchor="middle" class="dt">Sensibilidad de las variables</text>
  <text x="132" y="258" text-anchor="middle" class="dn">para disminuir el impacto en el UITI</text>

  <rect x="268" y="220" width="240" height="52" rx="6" fill="$PANEL" stroke="$BORDE"/>
  <text x="388" y="241" text-anchor="middle" class="dt">Diagnóstico semiautomático</text>
  <text x="388" y="258" text-anchor="middle" class="dn">de los vanos más críticos</text>
  <path d="M132 272 V300" class="fl"/>
  <path d="M388 272 V300" class="fl"/>

  <text x="12" y="318" class="dh">4 &middot; LOS DOS RANKINGS</text>
  <rect x="12" y="326" width="240" height="70" rx="6" fill="#fff" stroke="$BORDE_FUERTE"/>
  <text x="132" y="346" text-anchor="middle" class="dt">Top: lo que más reduce el UITI</text>
  <text x="132" y="362" text-anchor="middle" class="dn">las variables ordenadas según la reducción</text>
  <text x="132" y="375" text-anchor="middle" class="dn">del UITI que logran en cada vano</text>

  <rect x="268" y="326" width="115" height="70" rx="6" fill="#fff" stroke="$BORDE_FUERTE"/>
  <text x="325" y="346" text-anchor="middle" class="dt">Intervencion</text>
  <text x="325" y="364" text-anchor="middle" class="dn">qué hacer</text>
  <text x="325" y="377" text-anchor="middle" class="dn">valor sugerido</text>

  <rect x="393" y="326" width="115" height="70" rx="6" fill="#fff" stroke="$BORDE_FUERTE"/>
  <text x="450" y="346" text-anchor="middle" class="dt">Escenario</text>
  <text x="450" y="364" text-anchor="middle" class="dn">bajo qué</text>
  <text x="450" y="377" text-anchor="middle" class="dn">condiciones</text>

  <!-- Los tres rankings bajan a un mismo canal y de ahi UNA flecha a la pregunta. Con
       tres trazos convergiendo directamente, los dos que llegaban en diagonal se leian
       como una cunia rellena y no como dos lineas. -->
  <path d="M132 396 V420" style="stroke:$BORDE_FUERTE;stroke-width:1.4;fill:none"/>
  <path d="M325 396 V420" style="stroke:$BORDE_FUERTE;stroke-width:1.4;fill:none"/>
  <path d="M450 396 V420" style="stroke:$BORDE_FUERTE;stroke-width:1.4;fill:none"/>
  <path d="M132 420 H450" style="stroke:$BORDE_FUERTE;stroke-width:1.4;fill:none"/>
  <path d="M260 420 V454" class="fl"/>

  <text x="12" y="448" class="dh">5 &middot; LA PREGUNTA</text>
  <!-- Ancha de verdad: el subtitulo mide lo que mide y una caja de 220 px lo dejaba
       saliendose por los dos lados. -->
  <rect x="60" y="454" width="400" height="46" rx="6" fill="$ACENTO_CLARO" stroke="$ACENTO"/>
  <text x="260" y="474" text-anchor="middle" class="dt">¿Qué pasa si…?</text>
  <!-- El gris de `.dn` sobre este verde da 1,9:1. Se veia negro mientras la hoja estuvo
       inerte; en cuanto la regla empezo a aplicarse, aqui -- y solo aqui, que es la unica
       caja de fondo saturado sin texto blanco -- el subtitulo se perdia. -->
  <text x="260" y="491" text-anchor="middle" class="dn" style="fill:$TEXTO">aplicas lo sugerido o lo modificas manualmente y pulsas «Simular»</text>
</svg>
"""


def pagina() -> str:
    _chec, _labia = _logo("checlogo.png"), _logo("logo_labIA.png")
    # Un logo que falta no deja hueco ni etiqueta rota: simplemente no se dibuja.
    _marca_chec = (f'<img src="{_chec}" alt="CHEC Grupo EPM">' if _chec else "")
    _marca_labia = (f'<img src="{_labia}" alt="LabIA">' if _labia else "")
    _diagrama_html = Template(_diagrama([t.titulo for t in _tableros.TABLEROS])).substitute(
        **_paleta.TOKENS, FUENTE=_paleta.FUENTE)
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CriticidadCHEC</title>
<style>{_ESTILO}</style>
</head>
<body>
<div class="envoltura">
  <header>
    <button id="cerrar-todo" class="peligro"
      title="Apaga los cinco tableros, libera sus puertos y cierra las ventanas de
terminal que abrieron. Despues cierra este menu.">Cerrar todo</button>
  </header>
  <div class="portada">
    <div class="col-izq">
      <h1>IA + Criticidad CHEC</h1>
      <div id="lista"></div>
      <div class="logos">
        <div class="marca">{_marca_chec}</div>
        <div class="firma"><span>Elaborado por</span>{_marca_labia}</div>
      </div>
    </div>
    <div class="col-der">
      <h1>¿Cómo funciona el simulador?</h1>
      {_diagrama_html}
    </div>
  </div>
</div>
<script>{_GUION}</script>
</body>
</html>
"""
