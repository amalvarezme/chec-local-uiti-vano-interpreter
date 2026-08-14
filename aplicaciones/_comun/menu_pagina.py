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
    t.appendChild(texto);

    if (app.fase === 'corriendo') {
      t.appendChild(boton('Ver', 'principal', function () {
        window.open(app.url, 'app-' + app.clave);
      }));
      t.appendChild(boton('Detener', '', function () { mandar('detener', app.clave); }));
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
        if (pestania && !pestania.closed) { pestania.location = app.url; }
      } else if (app.fase === 'fallo') {
        clearInterval(reloj);
        if (pestania && !pestania.closed) { pestania.close(); }
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
    <button id="cerrar-todo" class="peligro">Cerrar todo</button>
  </header>
  <div id="lista"></div>
</div>
<script>{_GUION}</script>
</body>
</html>
"""
