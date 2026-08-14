"""La organizacion de `reports/`: quien escribe donde.

`reports/interpretability/` mezclaba en un solo arbol las corridas de `/report`, las
del lote y el HTML del informe gerencial -- este ultimo escondido en un subdirectorio
del `html/` de los circuitos, que es justo donde nadie lo busca. La carpeta se parte en
dos raices que se nombran por lo que producen:

    reports/reportescircuitos/    -- `/report` y `/reporte-lote`
    reports/informesgerenciales/  -- `/informe-gerencial`

Y quedan como estaban las dos que no son corridas: `reports/vault/` (las notas) y
`reports/graphify/` (su grafo).

Se comprueban las CONSTANTES y no los directorios: una corrida limpia puede no haber
creado todavia ninguno, y este contrato tiene que valer igual antes de la primera.
"""

from __future__ import annotations

from pathlib import Path

from chec_local_interpreter import config
from chec_local_interpreter.config import PROJECT_ROOT

REPORTES_CIRCUITOS = PROJECT_ROOT / "reports" / "reportescircuitos"
INFORMES_GERENCIALES = PROJECT_ROOT / "reports" / "informesgerenciales"


def test_the_circuit_report_runs_live_under_reportescircuitos():
    from chec_local_interpreter import report_pipeline

    assert report_pipeline.DEFAULT_RUNS_ROOT == REPORTES_CIRCUITOS / "runs"


def test_the_batch_runs_live_under_the_same_root():
    """El lote es `/report` repetido, no otra cosa: sus corridas van al mismo arbol, en
    su propio subdirectorio, para que una limpieza no tenga que conocer dos sitios."""
    from chec_local_interpreter import batch_report_contract

    assert batch_report_contract.DEFAULT_RUNS_ROOT == REPORTES_CIRCUITOS / "runs" / "_batch"


def test_the_html_and_artifacts_of_a_circuit_live_under_reportescircuitos():
    import inspect

    from chec_local_interpreter import plotting

    assert config.DEFAULT_OUTPUT_DIR == REPORTES_CIRCUITOS / "artifacts"
    firma = inspect.signature(plotting.render_llm_analysis)
    assert firma.parameters["output_dir"].default == REPORTES_CIRCUITOS / "html"


def test_the_managerial_report_has_its_own_root_not_a_subfolder_of_the_circuits():
    """Estaba en `html/informe-gerencial/`, colgando del HTML de los circuitos. Es otro
    producto, con otro destinatario y otra periodicidad; que su ruta lo diga."""
    from chec_local_interpreter import informe_gerencial_contract as gerencial

    assert gerencial.DEFAULT_REPORT_OUTPUT_ROOT == INFORMES_GERENCIALES
    # Y sigue LEYENDO de donde escriben los circuitos: sintetiza sus corridas.
    assert gerencial.DEFAULT_RUNS_ROOT == REPORTES_CIRCUITOS / "runs"
    assert gerencial.DEFAULT_CIRCUIT_HTML_ROOT == REPORTES_CIRCUITOS / "html"


def test_the_vault_and_its_graph_stay_where_they_were():
    from chec_local_interpreter import informe_gerencial_contract as gerencial
    from chec_local_interpreter import vault_note_contract

    assert vault_note_contract.DEFAULT_VAULT_ROOT == PROJECT_ROOT / "reports" / "vault"
    assert gerencial.DEFAULT_VAULT_ROOT == PROJECT_ROOT / "reports" / "vault"
    # La nota se proyecta desde la corrida, asi que el vault mira al arbol nuevo.
    assert vault_note_contract.DEFAULT_RUNS_ROOT == REPORTES_CIRCUITOS / "runs"


def test_nothing_in_the_package_still_points_at_the_old_tree():
    """Una constante olvidada no rompe ninguna prueba: escribe en `interpretability/`,
    la corrida termina bien y el archivo aparece donde ya nadie lo busca."""
    paquete = Path(config.__file__).resolve().parent
    culpables = [
        f"{ruta.relative_to(PROJECT_ROOT)}:{i}"
        for ruta in sorted(paquete.rglob("*.py"))
        for i, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), 1)
        if "reports/interpretability" in linea or '"reports" / "interpretability"' in linea
    ]
    assert not culpables, f"todavia apuntan al arbol viejo: {culpables}"


# --- La limpieza conoce la nueva organizacion --------------------------------------


def test_the_cleanup_covers_the_two_new_roots_and_forgets_the_deleted_ones():
    """`cleanup_runs` es la unica pieza que enumera el arbol de salidas, asi que una
    categoria de mas apunta a una carpeta que ya no existe y una de menos deja una
    carpeta que nadie limpia -- justo el informe gerencial, que es el artefacto mas
    pesado por corrida."""
    from chec_local_interpreter.cleanup_runs import CATEGORIES

    rutas = {rel for _n, rel, _s in CATEGORIES}
    assert "reports/reportescircuitos/runs" in rutas
    assert "reports/reportescircuitos/html" in rutas
    assert "reports/informesgerenciales" in rutas
    # Las dos carpetas del pipeline MGCECDL se borraron con su stack.
    assert not [r for r in rutas if "mgcecdl-results" in r or "legacy-model-assets" in r]
    # Y las dos que el usuario conserva siguen siendo limpiables por separado.
    assert {"reports/vault", "reports/graphify"} <= rutas
