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

from string import Template

import paleta as _paleta

# Sin `color-scheme` ni bloque de modo oscuro, a proposito. Los cinco tableros fijan
# `background:#fff` y no responden al tema del sistema; un menu que si lo hiciera se
# volveria oscuro y mandaria al usuario a un tablero blanco de un clic. La armonia aqui
# vale mas que atender una preferencia que los tableros ignoran.
_ESTILO = Template("""
* { box-sizing: border-box; }
body { margin: 0; padding: 12px; font: 15px/1.55 $FUENTE;
       background: $FONDO; color: $TEXTO; }
.envoltura { max-width: 880px; margin: 0 auto; padding: 20px 8px 60px; }
header { display: flex; align-items: flex-start; justify-content: space-between;
         gap: 20px; margin-bottom: 22px; }
h1 { font-size: 25px; margin: 0; letter-spacing: -.01em; }

/* El filo izquierdo rojo es el gesto que repiten los cinco tableros en sus paneles de
   control. Cada aplicacion del menu es una tarjeta con ese mismo filo, asi que la
   pagina se lee como parte de la familia y no como una portada de otro sitio. */
.tarjeta { display: flex; align-items: center; gap: 16px; background: $PANEL;
           border: 1px solid $BORDE; border-left: $FILO; border-radius: 6px;
           padding: 13px 16px; margin-bottom: 9px; }
.texto { flex: 1; min-width: 0; }
.titulo { font-weight: 600; margin-bottom: 2px; }
.desc { color: $TENUE; font-size: 12px; }
/* El aviso de la emergente bloqueada. En el acento y no en el gris de `.desc`: es lo
   unico que explica por que un tablero que dice "corriendo" no se ve en ninguna parte. */
.aviso { color: $ACENTO_OSCURO; font-size: 12px; margin-top: 4px; }
.punto { width: 9px; height: 9px; border-radius: 50%; flex: none;
         background: $BORDE_FUERTE; }
.punto.corriendo { background: $ACENTO; }
.punto.preparando { background: $BORDE_FUERTE; box-shadow: 0 0 0 3px $BORDE; }
.punto.fallo { background: $ACENTO_OSCURO; }

button { font: inherit; font-size: 13px; font-weight: 600; padding: 6px 12px;
         border-radius: 4px; border: 1px solid $BORDE_FUERTE; background: $FONDO;
         color: $TEXTO; cursor: pointer; white-space: nowrap; }
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
    var linea = app.detalle ? app.detalle
              : app.fase === 'corriendo' ? 'abierta en el puerto ' + app.puerto
              : app.construida ? 'lista, abre en menos de un segundo'
              : app.instalada ? 'hay que construirla la primera vez'
              : 'hay que instalarla la primera vez';
    texto.innerHTML = '<div class="titulo"></div><div class="desc"></div>';
    texto.querySelector('.titulo').textContent = app.titulo;
    texto.querySelector('.desc').textContent = app.descripcion + ' \\u2014 ' + linea;
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


def pagina() -> str:
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
  <div id="lista"></div>
</div>
<script>{_GUION}</script>
</body>
</html>
"""
