"""Dibuja el GRAFO FIJO del modelo MIL como una pagina interactiva autocontenida.

## Por que existe este guion y no un SVG escrito a mano

Los demas diagramas del sitio se escriben a mano porque ilustran una idea. Este NO
ilustra: es el grafo que el modelo usa de verdad, y sale de
`chec_impacto.data.graph.construir_aristas_grafo_chec`. Dibujarlo a mano seria una copia
que se separa del original en cuanto alguien anada una arista, y separarse en silencio es
exactamente lo que este proyecto ya ha pagado dos veces.

## Por que las cadenas de clima van PLEGADAS por defecto

De las 156 aristas, **108 son las cadenas de rezago**: nueve familias climaticas por doce
horas, cada hora apuntando a la anterior y la hora 0 a `COD_CAUSA`. Dibujadas ocupan el
90 % del lienzo y no dicen mas que "hay doce rezagos". Plegadas, la estructura que
importa -- que modo alimenta a que modo -- se lee de un vistazo. El interruptor las
despliega, asi que no se esconde nada.

## El trazado es topologico, no de fuerzas

El grafo es un DAG. Un trazado por fuerzas lo dibujaria distinto en cada ejecucion y sin
significado; por capas topologicas, la posicion horizontal SIGNIFICA algo: cuantos pasos
faltan para llegar al impacto. `UITI_VANO` queda a la derecha del todo porque es el
sumidero.

Uso:

    PYTHONPATH=src .venv/bin/python scripts/generar_grafo_fijo_html.py <salida.html>
"""
from __future__ import annotations

import html
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ / "src") not in sys.path:
    sys.path.insert(0, str(RAIZ / "src"))

from chec_impacto.data.graph import CLIMATE_FAMILIES, construir_aristas_grafo_chec  # noqa: E402
from chec_local_interpreter.domain_context import (NOMBRE_LEGIBLE_GRUPO,  # noqa: E402
                                                   VARIABLE_GROUPS)
from chec_local_interpreter.glosario_variables import NOMBRE_NATURAL  # noqa: E402

#: Un color por modo. Los mismos tonos de la pagina, para que el lector no tenga que
#: traducir entre el grafo y las tablas que lo acompañan.
COLOR_MODO = {
    "Entorno/Riesgo": "#2e8b57",
    "Evento/Impacto": "#c62828",
    "Activos": "#b8860b",
    "Topologia": "#0b5f8a",
    "Proteccion": "#7a4fa3",
    "Fisicas/Electricas": "#c2571a",
}

FAMILIAS = {f.upper() for f in CLIMATE_FAMILIES}


def _modo_de(nodo: str) -> str:
    base = re.sub(r"_\d+$", "", nodo).upper()
    if base in FAMILIAS:
        return "Entorno/Riesgo"
    for grupo, datos in VARIABLE_GROUPS.items():
        if nodo.upper() in {v.upper() for v in datos["variables"]}:
            return grupo
    return "Entorno/Riesgo"


def _familia(nodo: str) -> str | None:
    m = re.match(r"^([a-z_]+)_\d+$", nodo)
    return m.group(1) if m and m.group(1).upper() in FAMILIAS else None


def plegar(aristas):
    """Colapsa cada cadena de rezagos en UN nodo. Devuelve (aristas, notas)."""
    fuera, notas = [], {}
    for a, b, w in aristas:
        fa, fb = _familia(a), _familia(b)
        if fa and fb and fa == fb:
            notas[fa] = notas.get(fa, 0) + 1      # arista interna de la cadena
            continue
        fuera.append((fa or a, fb or b, w))
    vistas, unicas = set(), []
    for a, b, w in fuera:
        if (a, b) in vistas:
            continue
        vistas.add((a, b))
        unicas.append((a, b, w))
    return unicas, notas


def capas(aristas):
    """Capas topologicas: la posicion horizontal es la distancia al impacto."""
    hijos, entrada = defaultdict(list), defaultdict(int)
    nodos = {n for a, b, _ in aristas for n in (a, b)}
    for a, b, _ in aristas:
        hijos[a].append(b)
        entrada[b] += 1
    pendiente = [n for n in nodos if entrada[n] == 0]
    nivel = {n: 0 for n in pendiente}
    cola = list(pendiente)
    while cola:
        n = cola.pop(0)
        for h in hijos[n]:
            nivel[h] = max(nivel.get(h, 0), nivel[n] + 1)
            entrada[h] -= 1
            if entrada[h] == 0:
                cola.append(h)
    porcapa = defaultdict(list)
    for n in sorted(nodos):
        porcapa[nivel.get(n, 0)].append(n)
    return porcapa


def construir(aristas, ancho=1580, alto=1020, margen=55):
    porcapa = capas(aristas)
    ncapas = max(porcapa) + 1
    # Las etiquetas se dibujan a la DERECHA del nodo y miden hasta ~120 px: con las
    # columnas mas juntas que eso, el rotulo de una tapa el nodo de la siguiente. Medido
    # sobre `FECHA_OPERACION_VANO`, que es el codigo mas largo del grafo.
    paso_x = max(126.0, (ancho - 2 * margen) / max(1, ncapas - 1))
    pos = {}
    for c, nodos in porcapa.items():
        nodos = sorted(nodos, key=lambda n: (_modo_de(n), n))
        paso_y = (alto - 2 * margen) / max(1, len(nodos))
        for i, n in enumerate(nodos):
            pos[n] = (margen + c * paso_x, margen + paso_y * (i + 0.5))
    return pos


def html_pagina(titulo: str) -> str:
    todas = construir_aristas_grafo_chec()
    plegadas, notas = plegar(todas)

    datos = {}
    for clave, aristas in (("plegado", plegadas), ("completo", todas)):
        pos = construir(aristas)
        datos[clave] = {
            "nodos": [
                {
                    "id": n,
                    "x": round(pos[n][0], 1),
                    "y": round(pos[n][1], 1),
                    "modo": _modo_de(n),
                    "nombre": NOMBRE_NATURAL.get(n.upper(), ""),
                    "rezagos": notas.get(n, 0) + 1 if n in notas else 0,
                }
                for n in pos
            ],
            "aristas": [{"a": a, "b": b, "w": w} for a, b, w in aristas],
        }

    modos = [{"id": k, "nombre": NOMBRE_LEGIBLE_GRUPO.get(k, k), "color": COLOR_MODO[k]}
             for k in COLOR_MODO]
    return _PLANTILLA.replace("__TITULO__", html.escape(titulo)) \
                     .replace("__DATOS__", json.dumps(datos, ensure_ascii=False)) \
                     .replace("__MODOS__", json.dumps(modos, ensure_ascii=False)) \
                     .replace("__RESUMEN__", json.dumps({
                         "aristas_totales": len(todas),
                         "aristas_plegadas": len(plegadas),
                         "rezagos": len(CLIMATE_FAMILIES),
                     }, ensure_ascii=False))


_PLANTILLA = r"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>__TITULO__</title>
<style>
:root{--ink:#102129;--muted:#5f6f77;--line:#dce7e4;--panel:#fff}
*{box-sizing:border-box}
html,body{margin:0;height:100%;font-family:Inter,system-ui,-apple-system,"Segoe UI",sans-serif;background:#f8fbfa;color:var(--ink)}
.envoltura{display:flex;height:100%;min-height:0}
.lienzo{flex:1 1 auto;min-width:0;position:relative}
svg{width:100%;height:100%;display:block;touch-action:pan-y}
aside{flex:0 0 250px;border-left:1px solid var(--line);background:var(--panel);padding:14px 16px;overflow-y:auto;font-size:13px}
aside h2{margin:0 0 4px;font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.modo{display:flex;align-items:center;gap:8px;padding:5px 6px;border-radius:6px;cursor:pointer;user-select:none}
.modo:hover{background:#f1f6f4}
.modo.apagado{opacity:.35}
.punto{width:11px;height:11px;border-radius:50%;flex:0 0 auto}
.ficha{margin-top:14px;padding-top:12px;border-top:1px solid var(--line);min-height:110px}
.ficha b{display:block;font-size:14px;margin-bottom:2px}
.ficha .cod{font-family:ui-monospace,Menlo,monospace;font-size:12px;color:var(--muted)}
.ficha ul{margin:8px 0 0;padding-left:16px;color:var(--muted);line-height:1.5}
.barra{padding:10px 16px;border-bottom:1px solid var(--line);background:var(--panel);display:flex;gap:14px;align-items:center;flex-wrap:wrap;font-size:13px}
.barra label{display:flex;gap:6px;align-items:center;cursor:pointer}
.pie{color:var(--muted);font-size:12px;margin-left:auto}
.nodo{cursor:pointer}
.nodo text{font-size:9.5px;fill:var(--ink);pointer-events:none}
.nodo circle{stroke:#fff;stroke-width:1.2}
.tenue{opacity:.12}
.arista{stroke:#9fb3ad;fill:none}
.arista.viva{stroke:#102129;stroke-width:2}
@media(max-width:760px){.envoltura{flex-direction:column}aside{flex:0 0 auto;border-left:0;border-top:1px solid var(--line);max-height:42%}}
</style></head><body>
<div class="barra">
  <label><input type="checkbox" id="desplegar"> Desplegar los 12 rezagos de clima</label>
  <span class="pie" id="pie"></span>
</div>
<div class="envoltura" style="height:calc(100% - 46px)">
  <div class="lienzo"><svg id="svg" role="img" aria-label="Grafo fijo de restricciones fisicas del modelo MIL"></svg></div>
  <aside>
    <h2>Modos de variable</h2>
    <div id="modos"></div>
    <div class="ficha" id="ficha"><b>Pulsa un nodo</b><span class="cod">para ver sus conexiones fijadas</span></div>
  </aside>
</div>
<script>
const DATOS=__DATOS__, MODOS=__MODOS__, RESUMEN=__RESUMEN__;
const svg=document.getElementById('svg'), NS='http://www.w3.org/2000/svg';
let vista='plegado', apagados=new Set(), elegido=null;
const color=m=>(MODOS.find(x=>x.id===m)||{}).color||'#888';

document.getElementById('modos').innerHTML=MODOS.map(m=>
 `<div class="modo" data-m="${m.id}"><span class="punto" style="background:${m.color}"></span><span>${m.nombre}</span></div>`).join('');
document.querySelectorAll('.modo').forEach(el=>el.onclick=()=>{
  const m=el.dataset.m;
  if(apagados.has(m)){apagados.delete(m);el.classList.remove('apagado');}
  else{apagados.add(m);el.classList.add('apagado');}
  pintar();});

document.getElementById('desplegar').onchange=e=>{vista=e.target.checked?'completo':'plegado';elegido=null;pintar();};

function pintar(){
  const d=DATOS[vista];
  const visible=n=>!apagados.has(n.modo);
  const porId={}; d.nodos.forEach(n=>porId[n.id]=n);
  const vecinos=new Set();
  if(elegido){ d.aristas.forEach(a=>{ if(a.a===elegido)vecinos.add(a.b); if(a.b===elegido)vecinos.add(a.a); }); }
  let s=`<defs><marker id="f" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#9fb3ad"/></marker>
  <marker id="fv" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#102129"/></marker></defs>`;
  d.aristas.forEach(a=>{
    const na=porId[a.a], nb=porId[a.b]; if(!na||!nb)return;
    const oculta=!visible(na)||!visible(nb);
    const viva=elegido&&(a.a===elegido||a.b===elegido);
    const mx=(na.x+nb.x)/2, cy=(na.y+nb.y)/2-Math.abs(nb.y-na.y)*0.12;
    s+=`<path class="arista${viva?' viva':''}${oculta?' tenue':''}" d="M${na.x},${na.y} Q${mx},${cy} ${nb.x},${nb.y}"
        stroke-width="${viva?2:Math.max(.6,a.w)}" marker-end="url(#${viva?'fv':'f'})" opacity="${oculta?.1:(elegido&&!viva?.12:.5)}"/>`;
  });
  d.nodos.forEach(n=>{
    const oculto=!visible(n);
    const rel=!elegido||n.id===elegido||vecinos.has(n.id);
    const r=n.rezagos?9:(n.id==='UITI_VANO'?10:6.5);
    s+=`<g class="nodo${oculto||!rel?' tenue':''}" data-id="${n.id}" transform="translate(${n.x},${n.y})">
        <circle r="${r}" fill="${color(n.modo)}"/>
        <text x="${r+4}" y="3.5">${n.id}${n.rezagos?' ('+n.rezagos+')':''}</text></g>`;
  });
  // La caja se ajusta al CONTENIDO. Con una caja fija, un grafo ancho y bajo se escala
  // por el ancho y deja media pantalla en blanco arriba y abajo.
  const xs=d.nodos.map(n=>n.x), ys=d.nodos.map(n=>n.y);
  const x0=Math.min(...xs)-30, y0=Math.min(...ys)-30;
  const x1=Math.max(...xs)+160, y1=Math.max(...ys)+30;
  svg.setAttribute('viewBox',`${x0} ${y0} ${x1-x0} ${y1-y0}`);
  svg.setAttribute('preserveAspectRatio','xMidYMid meet');
  svg.innerHTML=s;
  svg.querySelectorAll('.nodo').forEach(g=>g.onclick=()=>{elegido=(elegido===g.dataset.id)?null:g.dataset.id;pintar();ficha();});
  document.getElementById('pie').textContent =
    vista==='plegado'
      ? `${d.aristas.length} relaciones · las ${RESUMEN.rezagos} cadenas de clima van plegadas`
      : `${RESUMEN.aristas_totales} relaciones · 12 rezagos por familia, desplegados`;
}
function ficha(){
  const d=DATOS[vista], f=document.getElementById('ficha');
  if(!elegido){f.innerHTML='<b>Pulsa un nodo</b><span class="cod">para ver sus conexiones fijadas</span>';return;}
  const n=d.nodos.find(x=>x.id===elegido);
  const ent=d.aristas.filter(a=>a.b===elegido), sal=d.aristas.filter(a=>a.a===elegido);
  f.innerHTML=`<b>${n.nombre||n.id}</b><span class="cod">${n.id}</span>`
   +(ent.length?`<ul>${ent.map(a=>`recibe de <b>${a.a}</b> · peso ${a.w}`).join('</li><li>').replace(/^/,'<li>')+'</li>'}</ul>`:'')
   +(sal.length?`<ul>${sal.map(a=>`apunta a <b>${a.b}</b> · peso ${a.w}`).join('</li><li>').replace(/^/,'<li>')+'</li>'}</ul>`:'')
   +((!ent.length&&!sal.length)?'<ul><li>sin conexiones en esta vista</li></ul>':'');
}
pintar();
</script></body></html>
"""


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    destino = Path(argv[0]) if argv else RAIZ / "site" / "assets" / "site" / "results" / "grafo-fijo-mil.html"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(html_pagina("Grafo fijo de restricciones fisicas - modelo MIL"),
                       encoding="utf-8")
    print(f"escrito {destino} ({destino.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
