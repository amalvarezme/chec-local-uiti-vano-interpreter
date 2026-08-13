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

_ESTILO = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { margin: 0; font: 15px/1.55 system-ui, -apple-system, 'Segoe UI', sans-serif;
       background: #f4f5f7; color: #1f2328; }
@media (prefers-color-scheme: dark) {
  body { background: #14171a; color: #e6e6e6; }
  .tarjeta { background: #1d2125 !important; border-color: #2f3742 !important; }
  .desc { color: #9aa4b2 !important; }
  header p { color: #9aa4b2 !important; }
}
.envoltura { max-width: 880px; margin: 0 auto; padding: 32px 20px 60px; }
header { display: flex; align-items: flex-start; justify-content: space-between;
         gap: 20px; margin-bottom: 26px; }
h1 { font-size: 25px; margin: 0 0 4px; letter-spacing: -.01em; }
header p { margin: 0; color: #59636e; font-size: 14px; }
.tarjeta { display: flex; align-items: center; gap: 16px; background: #fff;
           border: 1px solid #d8dee4; border-radius: 10px; padding: 15px 18px;
           margin-bottom: 11px; }
.texto { flex: 1; min-width: 0; }
.titulo { font-weight: 600; margin-bottom: 2px; }
.desc { color: #59636e; font-size: 13.5px; }
.punto { width: 9px; height: 9px; border-radius: 50%; flex: none; background: #b9c0c8; }
.punto.corriendo { background: #2da44e; }
.punto.preparando { background: #d29922; }
.punto.fallo { background: #cf222e; }
button { font: inherit; font-size: 13.5px; padding: 7px 15px; border-radius: 6px;
         border: 1px solid #d8dee4; background: #f6f8fa; color: #1f2328;
         cursor: pointer; white-space: nowrap; }
button:hover:not(:disabled) { background: #eef1f4; }
button:disabled { opacity: .55; cursor: default; }
button.principal { border-color: #1f883d; background: #1f883d; color: #fff; }
button.principal:hover:not(:disabled) { background: #1a7f37; }
button.peligro { border-color: #cf222e; background: #fff; color: #cf222e; }
button.peligro:hover:not(:disabled) { background: #fff5f5; }
.avisos { min-height: 20px; font-size: 13px; color: #59636e; margin-top: 3px; }
.pie { margin-top: 26px; font-size: 13px; color: #59636e; }
.cerrado { padding: 60px 20px; text-align: center; }
"""

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
    pestania.document.write(
      '<!doctype html><meta charset=utf-8><title>' + app.titulo + '</title>' +
      '<body style="font:16px/1.7 system-ui;padding:60px 40px;color:#2b2b2b">' +
      '<b style="font-size:20px">Preparando ' + app.titulo + '</b>' +
      '<p id=p>Un momento...</p>' +
      '<p style="color:#666">La primera vez hay que crear su entorno y construir su ' +
      'tablero. Puede tardar varios minutos. No cierres esta pestana.</p>');
  }
  mandar('abrir', app.clave, function () { seguir(app.clave, pestania); });
}

function seguir(clave, pestania) {
  var reloj = setInterval(function () {
    fetch('/estado').then(function (r) { return r.json(); }).then(function (estado) {
      pintar(estado);
      var app = estado.filter(function (a) { return a.clave === clave; })[0];
      if (!app) { return; }
      if (pestania && !pestania.closed && app.detalle) {
        var p = pestania.document.getElementById('p');
        if (p) { p.textContent = app.detalle; }
      }
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
  fetch('/apagar-todo', { method: 'POST' }).catch(function () {}).then(function () {
    document.body.innerHTML =
      '<div class="cerrado"><h1>CriticidadCHEC cerrado</h1>' +
      '<p>Se apagaron las aplicaciones y el menu. Ya puedes cerrar esta pestana.</p>' +
      '<p style="color:#59636e">Para volver a abrirlo: iniciar.command (macOS) o ' +
      'iniciar.bat (Windows).</p></div>';
    window.close();
  });
}

document.getElementById('cerrar-todo').addEventListener('click', cerrarTodo);
refrescar();
// El estado tambien cambia por fuera del menu: una aplicacion se puede cerrar con su
// propio boton o con Ctrl+C en su ventana, y el menu tiene que enterarse.
setInterval(refrescar, 2500);
"""


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
      <p>Tableros de criticidad por vano. Cada uno corre en su propio proceso y su
         propio puerto; este menu los abre, los vigila y los apaga.</p>
    </div>
    <button id="cerrar-todo" class="peligro">Cerrar todo</button>
  </header>
  <div id="lista"></div>
  <p class="pie">Cada tablero abre en su propia pestana, con un boton
     <b>Volver al menu</b> que lo apaga y cierra esa pestana. <b>Cerrar todo</b> apaga
     las cinco aplicaciones y este menu.</p>
</div>
<script>{_GUION}</script>
</body>
</html>
"""
