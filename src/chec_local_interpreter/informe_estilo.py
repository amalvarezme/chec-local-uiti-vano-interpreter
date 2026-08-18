"""La identidad visual que comparten los dos informes, en UN solo sitio.

El informe por circuito (`plotting.render_llm_analysis`) y el gerencial
(`informe_gerencial_contract`) son dos productos del mismo proyecto y llegan al mismo
lector. Tenian dos hojas de estilo escritas por separado, y se habian separado: distinta
tipografia, distinto marco, y el escudo de CHEC y el pie de los agentes solo en uno de
los dos. Copiar la hoja en cada archivo es lo que produjo esa divergencia, y la volveria
a producir.

Aqui vive lo COMPARTIDO -- tipografia, marco, encabezados, tablas, escudo y pie -- y
cada informe conserva lo suyo: el visor de mapas y las pestañas son del informe por
circuito, y las insignias de procedencia son del gerencial.

## Las llaves, que son la trampa de este archivo

Las dos plantillas son f-strings, asi que escriben sus propias reglas con llaves DOBLES
-- `body {{ ... }}` -- y la f-string las reduce a una al evaluar. Un valor INYECTADO no
se vuelve a escanear: sus llaves viajan tal cual. Por eso esta hoja se escribe con
llaves SIMPLES.

Equivocarse no da error, y ese es el problema: `.clase {{ }}` es CSS sintacticamente
valido cuyo cuerpo es la cadena `{ }` -- una regla VACIA. Ya paso en este repositorio
con el diagrama del menu, que estuvo semanas sin flechas y con la fuente equivocada
porque nadie miro la hoja. `test_informe_estilo_compartido` tiene el guardian.
"""

from __future__ import annotations

from pathlib import Path

from chec_local_interpreter.config import PROJECT_ROOT

#: De donde salen los dos logos. Se aisla para que una prueba pueda apuntarlo a otro
#: sitio y comprobar el degradado sin tocar el arbol del proyecto.
DIR_LOGOS = PROJECT_ROOT / "site" / "assets" / "site" / "logos"

#: Llaves SIMPLES: esto se inyecta como VALOR en dos f-strings. Ver el docstring.
CSS_IDENTIDAD = """
/* --- Identidad compartida por los dos informes (informe_estilo) ------------- */
body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f8fafc;
        color: #334155; margin: 0; padding: 20px; }
/* El marco. `position: relative` no es decoracion: es lo que ancla al escudo, que va
   posicionado en absoluto contra este contenedor y no contra la pagina. */
.container { position: relative; max-width: 1200px; margin: auto; padding: 25px;
             border: 1px solid #e2e8f0; border-radius: 12px; background: #ffffff;
             box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); }
h1 { color: #0f172a; border-bottom: 3px solid #2563eb; padding-bottom: 10px; }
h2 { color: #1e3a8a; margin-top: 30px; }
h3 { color: #1e40af; margin-top: 18px; margin-bottom: 8px; font-size: 1rem; }
h4 { color: #334155; margin-bottom: 5px; margin-top: 15px; }
ul { margin: 6px 0 4px 0; padding-left: 20px; }
li { margin-bottom: 5px; line-height: 1.55; }
/* Tablas: bordes de fila y columna, encabezado tenido, y desbordamiento propio para
   que la pagina nunca se desplace en horizontal. */
.table-scroll { overflow-x: auto; }
.compact-table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
.compact-table th, .compact-table td { border: 1px solid #e2e8f0; padding: 8px 10px;
                                       text-align: left; vertical-align: top; }
.compact-table th { background: #f8fafc; color: #1e3a8a; }
/* El escudo de quien OPERA la red, arriba a la derecha de cada informe. */
.escudo-chec { position: absolute; top: 18px; right: 22px; height: 54px; width: auto; }
/* El pie alinea el texto y el logo del laboratorio a la DERECHA, sobre la misma linea
   de base: el logo firma la frase, no la encabeza. */
.pie-agentes { display: flex; align-items: center; justify-content: flex-end; gap: 12px;
               color: #64748b; font-size: 12px; padding: 14px 22px 8px 0;
               border-top: 1px solid #e2e8f0; margin-top: 26px; }
.logo-labia { height: 34px; width: auto; }
"""


def _escape(texto: object) -> str:
    import html

    return html.escape("" if texto is None else str(texto))


def logo_html(nombre_archivo: str, clase: str, alt: str) -> str:
    """Un logo del proyecto, embebido como `data:` URI.

    DENTRO del HTML y no como `<img src="site/...">`: los informes se abren desde
    cualquier carpeta del disco y se mandan por correo, y una ruta relativa da un icono
    roto en cuanto el archivo cambia de sitio.

    Si el PNG falta no se dibuja nada. Un informe no se pierde por un adorno.
    """
    ruta = DIR_LOGOS / nombre_archivo
    if not ruta.is_file():
        return ""
    import base64

    dato = base64.b64encode(ruta.read_bytes()).decode("ascii")
    return (f"<img class='{clase}' alt='{_escape(alt)}' "
            f"src='data:image/png;base64,{dato}'>")


def escudo_chec_html() -> str:
    """El escudo de quien OPERA la red: es el destinatario del informe."""
    return logo_html("checlogo.png", "escudo-chec", "CHEC Grupo EPM")


def pie_agentes_html() -> str:
    """Quien PRODUJO el informe, abajo a la derecha.

    Separado del escudo a proposito: juntos arriba se leerian como dos marcas del mismo
    emisor. El TEXTO va siempre, aunque falte el logo -- decir como se produjo el
    informe no es el adorno.
    """
    return ('<div class="pie-agentes"><span>Reporte construido por agentes de IA</span>'
            f'{logo_html("logo_labIA.png", "logo-labia", "Laboratorio de Inteligencia Artificial")}'
            "</div>")
