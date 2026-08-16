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
body { margin: 0; padding: 12px; font: 15px/1.55 $FUENTE;
       background: $FONDO; color: $TEXTO; }
/* 1.720 y no 1.180: con la columna de botones al triple -- 760 px -- un tope de 1.180
   dejaba al diagrama con 386 px, y a ese tamanio su texto no se lee. El tope existe para
   que la portada no se estire sin fin en un monitor ancho, no para apretarla. */
.envoltura { max-width: 1720px; margin: 0 auto; padding: 20px 8px 60px; }

/* La portada: los botones a la izquierda y el diagrama a la derecha.
   La columna de los botones lleva ancho FIJO y la del diagrama toma el resto. Con las dos
   al 50% -- o con `1fr 1fr` -- la lista de cinco tarjetas se estira en una pantalla ancha
   y el diagrama, que es lo que hay que leer de un vistazo, se queda con una franja.
   `minmax(0, 1fr)` en la derecha y no `1fr` a secas: una celda de rejilla no baja de su
   contenido minimo, y el SVG tiene uno propio. */
.portada { display: grid; grid-template-columns: 760px minmax(0, 1fr); gap: 34px;
           align-items: start; }
/* 760 px y no 420: el texto y los botones de esta columna van al TRIPLE, y una columna
   que no crece con ellos parte cada tarjeta en tres renglones. */
/* Y en pantalla estrecha se apilan, con los botones primero: son lo unico accionable. */
@media (max-width: 1240px) { .portada { grid-template-columns: 1fr; } }

/* Los logos, debajo de los botones y CENTRADOS. Viajan tal cual los aprobo la marca: aqui
   no se recolorean. */
.logos { margin: 34px 4px 0; padding-top: 26px; border-top: 1px solid $BORDE;
         text-align: center; }
/* El de CHEC al TRIPLE -- 132 px donde habia 44 -- y solo en su renglon. */
.logos .marca img { height: 132px; width: auto; }
/* El del LabIA va DEBAJO y con su rotulo. Mas pequenio a proposito: no es la marca del
   producto sino la firma de quien lo hizo, y al mismo tamanio se leerian como iguales. */
.logos .firma { margin-top: 30px; display: flex; align-items: center;
                justify-content: center; gap: 16px; }
.logos .firma span { font-size: 26px; color: $TENUE; }
.logos .firma img { height: 78px; width: auto; }

.col-der svg { width: 100%; height: auto; }
header { display: flex; align-items: flex-start; justify-content: space-between;
         gap: 20px; margin-bottom: 22px; }
h1 { font-size: 25px; margin: 0; letter-spacing: -.01em; }

/* El filo izquierdo rojo es el gesto que repiten los cinco tableros en sus paneles de
   control. Cada aplicacion del menu es una tarjeta con ese mismo filo, asi que la
   pagina se lee como parte de la familia y no como una portada de otro sitio. */
/* Al TRIPLE: 45px de texto donde habia 15, y el relleno y los huecos con el, o el
   contenido se sale de una caja que no crecio. El filo izquierdo sube de 4 a 12 px por lo
   mismo -- a 4 px se pierde contra una tarjeta tres veces mas alta. */
.tarjeta { display: flex; align-items: center; gap: 48px; background: $PANEL;
           border: 1px solid $BORDE; border-left: 12px solid $ACENTO; border-radius: 10px;
           padding: 26px 32px; margin-bottom: 18px; font-size: 45px; line-height: 1.25; }
.texto { flex: 1; min-width: 0; }
.titulo { font-weight: 600; margin-bottom: 2px; }
.desc { color: $TENUE; font-size: 36px; }
/* El aviso de la emergente bloqueada. En el acento y no en el gris de `.desc`: es lo
   unico que explica por que un tablero que dice "corriendo" no se ve en ninguna parte. */
.aviso { color: $ACENTO_OSCURO; font-size: 12px; margin-top: 4px; }
.punto { width: 27px; height: 27px; border-radius: 50%; flex: none;
         background: $BORDE_FUERTE; }
.punto.corriendo { background: $ACENTO; }
.punto.preparando { background: $BORDE_FUERTE; box-shadow: 0 0 0 3px $BORDE; }
.punto.fallo { background: $ACENTO_OSCURO; }

button { font: inherit; font-size: 13px; font-weight: 600; padding: 6px 12px;
         border-radius: 4px; border: 1px solid $BORDE_FUERTE; background: $FONDO;
         color: $TEXTO; cursor: pointer; white-space: nowrap; }
/* Los de las TARJETAS al triple. `Cerrar todo` no: vive en la cabecera, no en la columna,
   y ampliarlo lo pondria a competir con el titulo. */
.tarjeta button { font-size: 39px; padding: 18px 36px; border-radius: 10px;
                  border-width: 3px; }
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
    // Bajo el nombre no va nada que el usuario no necesite. Se fue la DESCRIPCION -- prosa
    // fija, la misma en cada apertura -- y con ella la linea de relleno del caso normal,
    // que decia que la aplicacion estaba lista: lo que la tarjeta ya dice con su punto.
    //
    // Lo que se queda es lo que NO se puede deducir mirando: un fallo, en que paso va,
    // en que puerto quedo, o que falta instalarla. `menu.py` lo dice en su encabezado --
    // cuando algo falla "el usuario no esta mirando ninguna terminal: el menu es su unica
    // ventana" --, y `_fallo()` escribe ahi la ultima linea de pip o del constructor.
    // Vaciar la linea entera se habria llevado eso por delante.
    var linea = app.detalle ? app.detalle
              : app.fase === 'corriendo' ? 'abierta en el puerto ' + app.puerto
              : app.construida ? ''
              : app.instalada ? 'hay que construirla la primera vez'
              : 'hay que instalarla la primera vez';
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

    Resume el camino real y con el vocabulario real del tablero -- `Diagnostico`,
    `Intervencion`, `Escenario`, `Simular` son los botones que existen, y "sensibilidad
    min-max" es como el propio codigo llama a ese estudio y NUNCA "SHAP".

    `titulos` entra para dejar constancia de que los cinco tableros son la familia de la
    que sale el simulador; se nombra el ultimo, que es el.
    """
    _ = titulos
    return """
<svg viewBox="0 0 520 792" role="img"
     aria-label="Como funciona el simulador Que pasa si de CriticidadCHEC">
  <defs>
    <marker id="pf" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7"
            orient="auto"><path d="M0 0 L8 4 L0 8 z" fill="$BORDE_FUERTE"/></marker>
  </defs>
  <style>
    .db {{ font: 11.5px $FUENTE; fill: $TEXTO; }}
    .dt {{ font: 600 12.5px $FUENTE; fill: $TEXTO; }}
    .dn {{ font: 10px $FUENTE; fill: $TENUE; }}
    .dh {{ font: 600 10.5px $FUENTE; fill: $TENUE; letter-spacing: .06em; }}
    .fl {{ stroke: $BORDE_FUERTE; stroke-width: 1.4; fill: none; marker-end: url(#pf); }}
    .fp {{ stroke: $ACENTO_CLARO; stroke-width: 2; fill: none; marker-end: url(#pf); }}
  </style>

  <text x="12" y="18" class="dh">1 &middot; LO QUE ELIGES</text>
  <rect x="12" y="26" width="496" height="46" rx="6" fill="$PANEL" stroke="$BORDE"/>
  <text x="260" y="45" text-anchor="middle" class="dt">Circuito, ventana y vanos marcados</text>
  <text x="260" y="61" text-anchor="middle" class="dn">mas las variables y las actividades del contrato que quieras mover</text>
  <path d="M260 72 V92" class="fl"/>

  <text x="12" y="110" class="dh">2 &middot; EL MODELO</text>
  <rect x="12" y="118" width="496" height="62" rx="6" fill="$ACENTO" stroke="$ACENTO"/>
  <text x="260" y="139" text-anchor="middle" class="dt" style="fill:#fff">Modelo MIL congelado</text>
  <text x="260" y="155" text-anchor="middle" class="dn" style="fill:#fff">la bolsa es el par vano x ventana; atencion por segmento y fusion FiLM</text>
  <text x="260" y="170" text-anchor="middle" class="dn" style="fill:#fff">compuertas por arista sobre el grafo experto, que no se reentrena</text>
  <path d="M140 180 V204" class="fl"/>
  <path d="M380 180 V204" class="fl"/>

  <text x="12" y="222" class="dh">3 &middot; LO QUE EL TABLERO ESTUDIA POR TI</text>
  <rect x="12" y="230" width="240" height="86" rx="6" fill="$PANEL" stroke="$BORDE"/>
  <text x="132" y="250" text-anchor="middle" class="dt">Sensibilidad min-max</text>
  <text x="132" y="266" text-anchor="middle" class="dn">barre cada variable de su minimo</text>
  <text x="132" y="279" text-anchor="middle" class="dn">a su maximo, vano por vano</text>
  <text x="132" y="299" text-anchor="middle" class="dn">no es SHAP: es un barrido medido</text>

  <rect x="268" y="230" width="240" height="86" rx="6" fill="$PANEL" stroke="$BORDE"/>
  <text x="388" y="250" text-anchor="middle" class="dt">Diagnostico semi-automatico</text>
  <text x="388" y="266" text-anchor="middle" class="dn">toma los vanos marcados y, si faltan,</text>
  <text x="388" y="279" text-anchor="middle" class="dn">completa con los de mayor UITI</text>
  <text x="388" y="299" text-anchor="middle" class="dn">y propone que mover en cada uno</text>
  <path d="M132 316 V344" class="fl"/>
  <path d="M388 316 V344" class="fl"/>

  <text x="12" y="362" class="dh">4 &middot; LOS DOS RANKINGS</text>
  <rect x="12" y="370" width="240" height="70" rx="6" fill="#fff" stroke="$BORDE_FUERTE"/>
  <text x="132" y="390" text-anchor="middle" class="dt">Top: que baja el UITI</text>
  <text x="132" y="406" text-anchor="middle" class="dn">las variables ordenadas por la</text>
  <text x="132" y="419" text-anchor="middle" class="dn">caida que consiguen en cada vano</text>

  <rect x="268" y="370" width="115" height="70" rx="6" fill="#fff" stroke="$BORDE_FUERTE"/>
  <text x="325" y="390" text-anchor="middle" class="dt">Intervencion</text>
  <text x="325" y="408" text-anchor="middle" class="dn">que HACER</text>
  <text x="325" y="421" text-anchor="middle" class="dn">valor sugerido</text>

  <rect x="393" y="370" width="115" height="70" rx="6" fill="#fff" stroke="$BORDE_FUERTE"/>
  <text x="450" y="390" text-anchor="middle" class="dt">Escenario</text>
  <text x="450" y="408" text-anchor="middle" class="dn">bajo que</text>
  <text x="450" y="421" text-anchor="middle" class="dn">CONDICIONES</text>

  <!-- Los tres rankings bajan a un mismo canal y de ahi UNA flecha a la pregunta. Con
       tres trazos convergiendo directamente, los dos que llegaban en diagonal se leian
       como una cunia rellena y no como dos lineas. -->
  <path d="M132 440 V464" style="stroke:$BORDE_FUERTE;stroke-width:1.4;fill:none"/>
  <path d="M325 440 V464" style="stroke:$BORDE_FUERTE;stroke-width:1.4;fill:none"/>
  <path d="M450 440 V464" style="stroke:$BORDE_FUERTE;stroke-width:1.4;fill:none"/>
  <path d="M132 464 H450" style="stroke:$BORDE_FUERTE;stroke-width:1.4;fill:none"/>
  <path d="M260 464 V498" class="fl"/>

  <text x="12" y="492" class="dh">5 &middot; LA PREGUNTA</text>
  <!-- Ancha de verdad: el subtitulo mide lo que mide y una caja de 220 px lo dejaba
       saliendose por los dos lados. -->
  <rect x="60" y="498" width="400" height="46" rx="6" fill="$ACENTO_CLARO" stroke="$ACENTO"/>
  <text x="260" y="518" text-anchor="middle" class="dt">Que pasa si?</text>
  <text x="260" y="535" text-anchor="middle" class="dn">aplicas lo sugerido, o lo mueves a mano, y pulsas Simular</text>
  <path d="M260 544 V584" class="fp"/>

  <text x="12" y="584" class="dh">6 &middot; LAS CUATRO LECTURAS</text>
  <rect x="12" y="592" width="240" height="62" rx="6" fill="$PANEL" stroke="$BORDE"/>
  <text x="132" y="612" text-anchor="middle" class="dt">Mapa simulado</text>
  <text x="132" y="629" text-anchor="middle" class="dn">el circuito con la criticidad</text>
  <text x="132" y="642" text-anchor="middle" class="dn">de despues, junto al de antes</text>

  <rect x="268" y="592" width="240" height="62" rx="6" fill="$PANEL" stroke="$BORDE"/>
  <text x="388" y="612" text-anchor="middle" class="dt">UITI medido contra simulado</text>
  <text x="388" y="629" text-anchor="middle" class="dn">vano por vano, con la barra</text>
  <text x="388" y="642" text-anchor="middle" class="dn">de error del desfase del modelo</text>

  <rect x="12" y="664" width="240" height="62" rx="6" fill="$PANEL" stroke="$BORDE"/>
  <text x="132" y="684" text-anchor="middle" class="dt">Grafo de relaciones</text>
  <text x="132" y="701" text-anchor="middle" class="dn">lo que la simulacion MOVIO:</text>
  <text x="132" y="714" text-anchor="middle" class="dn">grafo base menos grafo simulado</text>

  <rect x="268" y="664" width="240" height="62" rx="6" fill="$PANEL" stroke="$BORDE"/>
  <text x="388" y="684" text-anchor="middle" class="dt">Costo del plan</text>
  <text x="388" y="701" text-anchor="middle" class="dn">las actividades del contrato por</text>
  <text x="388" y="714" text-anchor="middle" class="dn">vano y su acumulado</text>

  <rect x="12" y="742" width="496" height="38" rx="6" fill="#fff" stroke="$BORDE"/>
  <text x="260" y="766" text-anchor="middle" class="dn">El riesgo lo estima el modelo y el costo lo suma la lista: unirlos es tu decision</text>
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
    <div>
      <h1>CriticidadCHEC</h1>
    </div>
    <button id="cerrar-todo" class="peligro"
      title="Apaga los cinco tableros, libera sus puertos y cierra las ventanas de
terminal que abrieron. Despues cierra este menu.">Cerrar todo</button>
  </header>
  <div class="portada">
    <div class="col-izq">
      <div id="lista"></div>
      <div class="logos">
        <div class="marca">{_marca_chec}</div>
        <div class="firma"><span>Elaborado por</span>{_marca_labia}</div>
      </div>
    </div>
    <div class="col-der">{_diagrama_html}</div>
  </div>
</div>
<script>{_GUION}</script>
</body>
</html>
"""
