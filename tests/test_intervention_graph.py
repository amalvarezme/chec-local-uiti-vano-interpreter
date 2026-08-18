"""Tests for `intervention_graph`: the radial causes/intervention-strategies
meta-graph embedded in the managerial report.

The module under test reads each sampled circuit's OWN already-persisted agent
artifacts (`historical.out.json`, `expert-alignment.out.json`) -- never the raw
event database, never `graphify`, never an LLM -- so every test here builds a
fake runs tree and asserts against it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chec_local_interpreter import intervention_graph as ig

# ---------------------------------------------------------------------------
# Fixtures: a fake runs tree shaped exactly like reports/reportescircuitos/runs
# ---------------------------------------------------------------------------


def _write_run(
    runs_root: Path,
    circuito: str,
    *,
    cause_note: str | None = None,
    variables: list[dict] | None = None,
    temas: list[str] | None = None,
    stamp: str = "20260101T000000000000",
) -> Path:
    run_dir = runs_root / circuito / stamp
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "historical.out.json").write_text(
        json.dumps(
            {
                "ok": True,
                "data": {
                    "cause_hypothesis_note": cause_note,
                    "key_findings": [],
                    "recommended_actions": [],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "expert-alignment.out.json").write_text(
        json.dumps(
            {
                "ok": True,
                "data": {
                    "variables_a_priorizar": variables or [],
                    "coincidencias": [{"tema": t} for t in (temas or [])],
                    "diferencias": [],
                    "sintesis_final": "sintesis",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return run_dir


def _variable(
    name: str,
    *,
    prioridad: str = "alta",
    validacion: str = "Revisar en campo el estado de los activos.",
    justificacion: str = "Mayor peso normalizado.",
) -> dict:
    return {
        "variable": name,
        "prioridad": prioridad,
        "justificacion": justificacion,
        "tipo_de_validacion_sugerida": validacion,
        "fuentes_que_la_respaldan": ["inference"],
    }


@pytest.fixture()
def runs_root(tmp_path: Path) -> Path:
    root = tmp_path / "runs"
    root.mkdir()
    return root


# ---------------------------------------------------------------------------
# Intervention-family classification
# ---------------------------------------------------------------------------


class TestClassifyIntervention:
    @pytest.mark.parametrize(
        ("texto", "familia"),
        [
            ("Revisar en campo el estado de los transformadores.", "Inspección en campo"),
            ("Revisión de la topología de los vanos implicados.", "Inspección en campo"),
            ("Inspección física del tramo con mayor severidad.", "Inspección en campo"),
            ("Contrastar los registros de ráfaga con el histórico.", "Contraste con fuente externa"),
            ("Validar contra la base de mantenimiento.", "Contraste con fuente externa"),
            ("Verificar la coherencia con el reporte de campo.", "Contraste con fuente externa"),
            ("Incorporar el dato de NR_T al inventario.", "Captura de dato faltante"),
            ("Solicitar al área de activos la ficha del transformador.", "Captura de dato faltante"),
        ],
    )
    def test_clasifica_por_el_verbo_que_uso_el_agente(self, texto: str, familia: str) -> None:
        assert ig.classify_intervention(texto) == familia

    def test_texto_sin_verbo_reconocido_cae_en_la_familia_de_reserva(self) -> None:
        assert ig.classify_intervention("Algo completamente distinto.") == ig.FALLBACK_FAMILY
        assert ig.classify_intervention("Sin acción asociada.") == ig.FALLBACK_FAMILY

    def test_texto_vacio_o_nulo_cae_en_la_familia_de_reserva(self) -> None:
        assert ig.classify_intervention("") == ig.FALLBACK_FAMILY
        assert ig.classify_intervention(None) == ig.FALLBACK_FAMILY

    def test_ignora_acentos_y_mayusculas(self) -> None:
        assert ig.classify_intervention("REVISIÓN en campo") == ig.classify_intervention(
            "revision en campo"
        )


# ---------------------------------------------------------------------------
# Cause themes -- shared with the report prose, accent-insensitive
# ---------------------------------------------------------------------------


class TestCauseThemes:
    def test_reconoce_el_tema_aunque_la_nota_venga_sin_acentos(self) -> None:
        con = ig.cause_themes("condiciones atmosféricas con ráfagas elevadas")
        sin = ig.cause_themes("condiciones atmosfericas con rafagas elevadas")
        assert con == sin
        assert "clima/atmosférico" in con

    def test_linea_de_media_tension_rota_es_un_tema_propio(self) -> None:
        temas = ig.cause_themes("falla fisica en linea de media tension rota")
        assert "línea MT / falla física" in temas

    def test_una_nota_puede_activar_varios_temas(self) -> None:
        temas = ig.cause_themes(
            "combinacion de condiciones atmosfericas actuando sobre un conjunto "
            "reducido de vanos con presencia de fauna"
        )
        assert {"clima/atmosférico", "topológico/recurrencia de vanos", "fauna"} <= set(temas)

    def test_nota_vacia_no_activa_ningun_tema(self) -> None:
        assert ig.cause_themes("") == []
        assert ig.cause_themes(None) == []

    def test_el_orden_es_deterministico(self) -> None:
        nota = "fauna sobre las redes con rafagas y vanos recurrentes"
        assert ig.cause_themes(nota) == ig.cause_themes(nota)


# ---------------------------------------------------------------------------
# Concept model: what each circuit contributes
# ---------------------------------------------------------------------------


class TestBuildConceptModel:
    def test_una_causa_compartida_por_dos_circuitos_sobrevive_el_soporte_minimo(
        self, runs_root: Path
    ) -> None:
        _write_run(runs_root, "AAA23L11", cause_note="rafagas de viento elevadas")
        _write_run(runs_root, "BBB23L12", cause_note="precipitacion acumulada alta")

        modelo = ig.build_concept_model(["AAA23L11", "BBB23L12"], runs_root=runs_root)

        causas = {c["concepto"]: c for c in modelo["causas"]}
        assert "clima/atmosférico" in causas
        assert causas["clima/atmosférico"]["soporte"] == 2
        assert causas["clima/atmosférico"]["circuitos"] == ["AAA23L11", "BBB23L12"]

    def test_una_causa_de_un_solo_circuito_no_llega_al_grafo(self, runs_root: Path) -> None:
        _write_run(runs_root, "AAA23L11", cause_note="presencia de fauna sobre las redes")
        _write_run(runs_root, "BBB23L12", cause_note="rafagas de viento elevadas")

        modelo = ig.build_concept_model(["AAA23L11", "BBB23L12"], runs_root=runs_root)

        assert [c["concepto"] for c in modelo["causas"]] == []

    def test_la_estrategia_agrupa_familia_y_variable(self, runs_root: Path) -> None:
        for circuito in ("AAA23L11", "BBB23L12"):
            _write_run(
                runs_root,
                circuito,
                cause_note="rafagas elevadas",
                variables=[
                    _variable("CNT_TRF", validacion="Revisar en campo los transformadores.")
                ],
            )

        modelo = ig.build_concept_model(["AAA23L11", "BBB23L12"], runs_root=runs_root)

        estrategias = {e["concepto"]: e for e in modelo["estrategias"]}
        assert "Inspección en campo · CNT_TRF" in estrategias
        assert estrategias["Inspección en campo · CNT_TRF"]["soporte"] == 2
        assert estrategias["Inspección en campo · CNT_TRF"]["variable"] == "CNT_TRF"

    def test_la_misma_variable_con_verbos_distintos_produce_estrategias_distintas(
        self, runs_root: Path
    ) -> None:
        for circuito in ("AAA23L11", "BBB23L12"):
            _write_run(
                runs_root,
                circuito,
                variables=[
                    _variable("CNT_TRF", validacion="Revisar en campo los transformadores."),
                    _variable("CNT_TRF", validacion="Contrastar con el histórico de mantenimiento."),
                ],
            )

        modelo = ig.build_concept_model(["AAA23L11", "BBB23L12"], runs_root=runs_root)

        conceptos = {e["concepto"] for e in modelo["estrategias"]}
        assert "Inspección en campo · CNT_TRF" in conceptos
        assert "Contraste con fuente externa · CNT_TRF" in conceptos

    def test_la_evidencia_conserva_el_texto_del_agente_palabra_por_palabra(
        self, runs_root: Path
    ) -> None:
        texto = "Revisar en campo el estado y capacidad de los transformadores."
        for circuito in ("AAA23L11", "BBB23L12"):
            _write_run(runs_root, circuito, variables=[_variable("CNT_TRF", validacion=texto)])

        modelo = ig.build_concept_model(["AAA23L11", "BBB23L12"], runs_root=runs_root)

        evidencia = modelo["estrategias"][0]["evidencia"]
        assert any(item["texto"] == texto for item in evidencia)
        assert {item["circuito"] for item in evidencia} == {"AAA23L11", "BBB23L12"}

    def test_la_prioridad_reportada_es_la_mas_alta_que_algun_agente_le_dio(
        self, runs_root: Path
    ) -> None:
        _write_run(
            runs_root,
            "AAA23L11",
            variables=[_variable("CNT_TRF", prioridad="baja", validacion="Revisar en campo.")],
        )
        _write_run(
            runs_root,
            "BBB23L12",
            variables=[_variable("CNT_TRF", prioridad="alta", validacion="Revisar en campo.")],
        )

        modelo = ig.build_concept_model(["AAA23L11", "BBB23L12"], runs_root=runs_root)

        assert modelo["estrategias"][0]["prioridad"] == "alta"

    def test_un_circuito_sin_corrida_previa_simplemente_no_aporta(self, runs_root: Path) -> None:
        _write_run(runs_root, "AAA23L11", cause_note="rafagas elevadas")
        _write_run(runs_root, "BBB23L12", cause_note="rafagas elevadas")

        modelo = ig.build_concept_model(
            ["AAA23L11", "BBB23L12", "ZZZ23L99"], runs_root=runs_root
        )

        assert modelo["circuitos_sin_corrida"] == ["ZZZ23L99"]
        assert modelo["causas"][0]["soporte"] == 2

    def test_un_artefacto_ilegible_no_revienta_el_modelo(self, runs_root: Path) -> None:
        _write_run(runs_root, "AAA23L11", cause_note="rafagas elevadas")
        roto = _write_run(runs_root, "BBB23L12", cause_note="rafagas elevadas")
        (roto / "historical.out.json").write_text("{ esto no es json", encoding="utf-8")

        modelo = ig.build_concept_model(["AAA23L11", "BBB23L12"], runs_root=runs_root)

        assert modelo["causas"] == []

    def test_los_temas_del_agente_de_alineamiento_viajan_como_evidencia_de_la_causa(
        self, runs_root: Path
    ) -> None:
        for circuito in ("AAA23L11", "BBB23L12"):
            _write_run(
                runs_root,
                circuito,
                cause_note="rafagas de viento elevadas",
                temas=["Rol relevante del entorno climático en el evento dominante"],
            )

        modelo = ig.build_concept_model(["AAA23L11", "BBB23L12"], runs_root=runs_root)

        textos = [item["texto"] for item in modelo["causas"][0]["evidencia"]]
        assert "Rol relevante del entorno climático en el evento dominante" in textos


# ---------------------------------------------------------------------------
# Graph elements: rings, angles, edges
# ---------------------------------------------------------------------------


class TestGraphElements:
    @staticmethod
    def _modelo(runs_root: Path, circuitos: tuple[str, ...] = ("AAA23L11", "BBB23L12")) -> dict:
        for circuito in circuitos:
            _write_run(
                runs_root,
                circuito,
                cause_note="rafagas de viento elevadas sobre vanos recurrentes",
                variables=[_variable("CNT_TRF", validacion="Revisar en campo.")],
            )
        return ig.build_concept_model(list(circuitos), runs_root=runs_root)

    def test_la_causa_va_dentro_y_la_estrategia_fuera(self, runs_root: Path) -> None:
        """La mitad derecha se lee de dentro hacia fuera igual que la cadena
        circuito -> causa -> estrategia. Antes era al reves porque los tres eran
        circunferencias completas y lo que mandaba era el conteo de nodos."""
        nodes, _ = ig.build_graph_elements(self._modelo(runs_root))

        radios = {}
        for node in nodes:
            radios.setdefault(node["kind"], set()).add(
                round((node["x"] ** 2 + node["y"] ** 2) ** 0.5, 2)
            )
        assert max(radios["causa"]) < max(radios["estrategia"])

    def test_los_circuitos_van_en_orden_alfabetico_canonico(self, runs_root: Path) -> None:
        modelo = self._modelo(runs_root, ("CCC23L13", "AAA23L11", "BBB23L12"))
        nodes, _ = ig.build_graph_elements(modelo)

        circuitos = [n["label"] for n in nodes if n["kind"] == "circuito"]
        assert circuitos == sorted(circuitos)

    def test_hay_aristas_circuito_causa_y_causa_estrategia(self, runs_root: Path) -> None:
        _, edges = ig.build_graph_elements(self._modelo(runs_root))

        kinds = {edge["kind"] for edge in edges}
        assert kinds == {"circuito_causa", "causa_estrategia"}

    def test_ninguna_arista_salta_del_circuito_a_la_estrategia(self, runs_root: Path) -> None:
        nodes, edges = ig.build_graph_elements(self._modelo(runs_root))

        kind_by_id = {node["id"]: node["kind"] for node in nodes}
        for edge in edges:
            par = {kind_by_id[edge["source"]], kind_by_id[edge["target"]]}
            assert par != {"circuito", "estrategia"}

    def test_ninguna_estrategia_queda_huerfana(self, runs_root: Path) -> None:
        nodes, edges = ig.build_graph_elements(self._modelo(runs_root))

        conectados = {edge["source"] for edge in edges} | {edge["target"] for edge in edges}
        for node in nodes:
            if node["kind"] == "estrategia":
                assert node["id"] in conectados

    def test_los_nodos_de_un_anillo_no_se_encima(self, runs_root: Path) -> None:
        """El primer diseño ponía cada concepto en la media circular de sus
        circuitos y con radio fijo; diez estrategias caían casi en el mismo
        punto y la figura era ilegible. El anillo tiene que crecer con sus
        rótulos.
        """
        variables = [
            _variable(f"VARIABLE_LARGA_{i:02d}", validacion="Contrastar con el histórico.")
            for i in range(10)
        ]
        for circuito in ("AAA23L11", "BBB23L12"):
            _write_run(
                runs_root,
                circuito,
                cause_note="rafagas elevadas sobre vanos recurrentes con fauna",
                variables=variables,
            )
        modelo = ig.build_concept_model(["AAA23L11", "BBB23L12"], runs_root=runs_root)

        nodes, _ = ig.build_graph_elements(modelo)

        por_anillo: dict[str, list[dict]] = {}
        for node in nodes:
            por_anillo.setdefault(node["kind"], []).append(node)
        for kind, del_anillo in por_anillo.items():
            for i, a in enumerate(del_anillo):
                for b in del_anillo[i + 1 :]:
                    separacion = ((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2) ** 0.5
                    assert separacion > 90, f"{kind}: {a['label']} y {b['label']} se encima"

    def test_los_dos_arcos_no_se_invaden_entre_si(self, runs_root: Path) -> None:
        variables = [
            _variable(f"VARIABLE_LARGA_{i:02d}", validacion="Contrastar con el histórico.")
            for i in range(10)
        ]
        for circuito in ("AAA23L11", "BBB23L12"):
            _write_run(
                runs_root, circuito, cause_note="rafagas elevadas", variables=variables
            )
        modelo = ig.build_concept_model(["AAA23L11", "BBB23L12"], runs_root=runs_root)

        nodes, _ = ig.build_graph_elements(modelo)

        radio = {}
        for node in nodes:
            radio.setdefault(node["kind"], []).append((node["x"] ** 2 + node["y"] ** 2) ** 0.5)
        # Los dos arcos de la mitad derecha no se pisan, ni con rotulos largos.
        assert max(radio["causa"]) < min(radio["estrategia"])
        # Los circuitos viven en la OTRA mitad, asi que su radio ya no tiene que
        # superar al de nadie: lo que los separa es el signo de la x.
        assert all(n["x"] < 0 for n in nodes if n["kind"] == "circuito")
        assert all(n["x"] > 0 for n in nodes if n["kind"] in ("causa", "estrategia"))

    def test_el_rotulo_se_parte_en_dos_lineas(self) -> None:
        assert ig._wrap_label("Inspección en campo · CNT_TRF") == "Inspección en campo\nCNT_TRF"
        assert ig._wrap_label("clima/atmosférico") == "clima/atmosférico"

    def test_el_mismo_modelo_produce_los_mismos_nodos_y_aristas(self, runs_root: Path) -> None:
        modelo = self._modelo(runs_root)
        assert ig.build_graph_elements(modelo) == ig.build_graph_elements(modelo)

    def test_el_tope_de_estrategias_se_respeta_y_es_determinista(self, runs_root: Path) -> None:
        variables = [
            _variable(f"VAR_{i:02d}", validacion="Revisar en campo.") for i in range(10)
        ]
        for circuito in ("AAA23L11", "BBB23L12"):
            _write_run(runs_root, circuito, cause_note="rafagas elevadas", variables=variables)
        modelo = ig.build_concept_model(["AAA23L11", "BBB23L12"], runs_root=runs_root)

        nodes, _ = ig.build_graph_elements(modelo, max_estrategias=4)

        assert sum(1 for n in nodes if n["kind"] == "estrategia") == 4


# ---------------------------------------------------------------------------
# Public builder + CLI
# ---------------------------------------------------------------------------


class TestBuildInterventionGraph:
    def test_menos_de_dos_circuitos_no_produce_grafo(self, runs_root: Path, tmp_path: Path) -> None:
        outcome = ig.build_intervention_graph(
            ["AAA23L11"], tmp_path / "out.html", runs_root=runs_root
        )
        assert outcome.status == "skipped_empty"
        assert not (tmp_path / "out.html").exists()

    def test_sin_conceptos_compartidos_no_produce_grafo(
        self, runs_root: Path, tmp_path: Path
    ) -> None:
        _write_run(runs_root, "AAA23L11", cause_note="presencia de fauna")
        _write_run(runs_root, "BBB23L12", cause_note="rafagas elevadas")

        outcome = ig.build_intervention_graph(
            ["AAA23L11", "BBB23L12"], tmp_path / "out.html", runs_root=runs_root
        )

        assert outcome.status == "skipped_empty"

    def test_escribe_un_html_autocontenido_con_los_tres_anillos(
        self, runs_root: Path, tmp_path: Path
    ) -> None:
        for circuito in ("AAA23L11", "BBB23L12"):
            _write_run(
                runs_root,
                circuito,
                cause_note="rafagas de viento elevadas",
                variables=[_variable("CNT_TRF", validacion="Revisar en campo.")],
            )
        destino = tmp_path / "out.html"

        outcome = ig.build_intervention_graph(
            ["AAA23L11", "BBB23L12"], destino, runs_root=runs_root
        )

        assert outcome.status == "success"
        assert outcome.output_path == str(destino)
        assert outcome.causa_count >= 1 and outcome.estrategia_count >= 1
        html = destino.read_text(encoding="utf-8")
        # Plotly y ya no `vis-network`: el informe por circuito, el tablero y este grafo
        # dibujan anillos que se leen igual, y en dos motores distintos obligaban a
        # reconciliar dos comportamientos de zoom, de hover y de arrastre. Se comprueba
        # por lo que NO trae: mientras quede el `<script>` de vis-network, el informe
        # sigue cargando dos motores de grafo.
        assert "vis-network" not in html
        assert "plotly" in html.lower()
        assert "Causa" in html and "Estrategia" in html and "Circuito" in html

    def test_el_html_es_byte_identico_entre_corridas(
        self, runs_root: Path, tmp_path: Path
    ) -> None:
        for circuito in ("AAA23L11", "BBB23L12"):
            _write_run(
                runs_root,
                circuito,
                cause_note="rafagas elevadas",
                variables=[_variable("CNT_TRF", validacion="Revisar en campo.")],
            )

        # Mismo nombre de archivo en dos carpetas: el titulo del HTML lleva el
        # nombre del destino, asi que compararlos con nombres distintos no
        # probaria el determinismo del grafo sino esa diferencia.
        primero = tmp_path / "uno" / "grafo.html"
        segundo = tmp_path / "dos" / "grafo.html"
        primero.parent.mkdir()
        segundo.parent.mkdir()
        ig.build_intervention_graph(["AAA23L11", "BBB23L12"], primero, runs_root=runs_root)
        ig.build_intervention_graph(["AAA23L11", "BBB23L12"], segundo, runs_root=runs_root)

        assert primero.read_bytes() == segundo.read_bytes()

    def test_un_destino_imposible_no_lanza_excepcion(
        self, runs_root: Path, tmp_path: Path
    ) -> None:
        for circuito in ("AAA23L11", "BBB23L12"):
            _write_run(
                runs_root,
                circuito,
                cause_note="rafagas elevadas",
                variables=[_variable("CNT_TRF", validacion="Revisar en campo.")],
            )
        bloqueado = tmp_path / "archivo"
        bloqueado.write_text("no soy un directorio", encoding="utf-8")

        outcome = ig.build_intervention_graph(
            ["AAA23L11", "BBB23L12"], bloqueado / "out.html", runs_root=runs_root
        )

        assert outcome.status == "execution_error"
        assert outcome.errors

    def test_la_evidencia_va_escapada_dentro_del_html(
        self, runs_root: Path, tmp_path: Path
    ) -> None:
        for circuito in ("AAA23L11", "BBB23L12"):
            _write_run(
                runs_root,
                circuito,
                cause_note="rafagas elevadas",
                variables=[
                    _variable("CNT_TRF", validacion="Revisar <script>alert(1)</script> en campo.")
                ],
            )
        destino = tmp_path / "out.html"

        ig.build_intervention_graph(["AAA23L11", "BBB23L12"], destino, runs_root=runs_root)

        html = destino.read_text(encoding="utf-8")
        assert "<script>alert(1)</script>" not in html
        assert "alert(1)" in html


class TestCli:
    def _prepare(self, runs_root: Path) -> None:
        for circuito in ("AAA23L11", "BBB23L12"):
            _write_run(
                runs_root,
                circuito,
                cause_note="rafagas elevadas",
                variables=[_variable("CNT_TRF", validacion="Revisar en campo.")],
            )

    def test_build_exitoso_sale_con_cero(
        self, runs_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        self._prepare(runs_root)
        code = ig.main(
            [
                "build",
                "--sampled",
                "AAA23L11",
                "BBB23L12",
                "--output",
                str(tmp_path / "out.html"),
                "--runs-root",
                str(runs_root),
            ]
        )
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["status"] == "success"
        assert payload["schema_version"] == ig.SCHEMA_VERSION

    def test_un_grafo_vacio_tambien_sale_con_cero(
        self, runs_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        code = ig.main(
            [
                "build",
                "--sampled",
                "AAA23L11",
                "--output",
                str(tmp_path / "out.html"),
                "--runs-root",
                str(runs_root),
            ]
        )
        assert code == 0
        assert json.loads(capsys.readouterr().out)["status"] == "skipped_empty"

    def test_un_error_real_sale_con_dos(
        self, runs_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        self._prepare(runs_root)
        bloqueado = tmp_path / "archivo"
        bloqueado.write_text("no soy un directorio", encoding="utf-8")
        code = ig.main(
            [
                "build",
                "--sampled",
                "AAA23L11",
                "BBB23L12",
                "--output",
                str(bloqueado / "out.html"),
                "--runs-root",
                str(runs_root),
            ]
        )
        assert code == 2
        assert json.loads(capsys.readouterr().out)["status"] == "execution_error"


# ---------------------------------------------------------------------------
# Disposicion en DOS semicircunferencias enfrentadas
# ---------------------------------------------------------------------------


def _modelo_de_prueba():
    return {
        "circuitos": ["C1", "C2", "C3", "C4"],
        "causas": [
            {"concepto": "clima/atmosférico", "soporte": 3,
             "circuitos": ["C1", "C2", "C3"], "evidencia": {}},
            {"concepto": "conductor/vegetación", "soporte": 2,
             "circuitos": ["C3", "C4"], "evidencia": {}},
        ],
        "estrategias": [
            {"concepto": "Inspección en campo · NR_T", "soporte": 3, "variable": "NR_T",
             "prioridad": "alta", "circuitos": ["C1", "C2", "C3"], "evidencia": {}},
            {"concepto": "Inspección en campo · CONDUCTOR", "soporte": 2, "variable": "CONDUCTOR",
             "prioridad": "media", "circuitos": ["C3", "C4"], "evidencia": {}},
        ],
        "causas_por_circuito": {
            "C1": {"clima/atmosférico"}, "C2": {"clima/atmosférico"},
            "C3": {"clima/atmosférico", "conductor/vegetación"},
            "C4": {"conductor/vegetación"},
        },
        "estrategias_por_circuito": {
            "C1": {"Inspección en campo · NR_T"}, "C2": {"Inspección en campo · NR_T"},
            "C3": {"Inspección en campo · NR_T", "Inspección en campo · CONDUCTOR"},
            "C4": {"Inspección en campo · CONDUCTOR"},
        },
        "circuitos_sin_corrida": [],
    }


def _por_tipo(nodes):
    salida = {}
    for n in nodes:
        salida.setdefault(n["kind"], []).append(n)
    return salida


def test_los_circuitos_ocupan_un_semicirculo_y_los_conceptos_el_otro():
    """Tres anillos concentricos hacian que las aristas cruzaran la figura entera. Con dos
    semicircunferencias enfrentadas, toda arista circuito->causa cruza el centro UNA vez y
    en la misma direccion, y el ojo puede seguirla."""
    from chec_local_interpreter import intervention_graph as ig

    nodes, _ = ig.build_graph_elements(_modelo_de_prueba())
    t = _por_tipo(nodes)

    assert all(n["x"] < 0 for n in t["circuito"]), "algun circuito se salio de su mitad"
    assert all(n["x"] > 0 for n in t["causa"]), "alguna causa se salio de su mitad"
    assert all(n["x"] > 0 for n in t["estrategia"]), "alguna estrategia se salio de su mitad"


def test_la_estrategia_va_por_FUERA_de_su_causa():
    """Dentro de la mitad derecha se lee de dentro hacia fuera, igual que la cadena
    circuito -> causa -> estrategia. Se compara el RADIO y no la x: cerca del borde del
    arco el coseno achica la x de un nodo lejano, y eso no significa que este mas cerca."""
    from chec_local_interpreter import intervention_graph as ig

    nodes, _ = ig.build_graph_elements(_modelo_de_prueba())
    t = _por_tipo(nodes)
    radio = lambda n: (n["x"] ** 2 + n["y"] ** 2) ** 0.5

    assert max(radio(n) for n in t["causa"]) < min(radio(n) for n in t["estrategia"])


def test_ningun_nodo_queda_encima_de_otro():
    from chec_local_interpreter import intervention_graph as ig

    nodes, _ = ig.build_graph_elements(_modelo_de_prueba())
    posiciones = [(round(n["x"], 1), round(n["y"], 1)) for n in nodes]

    assert len(posiciones) == len(set(posiciones))


def test_la_estrategia_nombra_la_variable_con_su_codigo():
    from chec_local_interpreter import intervention_graph as ig
    from chec_local_interpreter.glosario_variables import nombre_con_codigo

    nodes, _ = ig.build_graph_elements(_modelo_de_prueba())
    etiquetas = " ".join(n["label"] for n in nodes if n["kind"] == "estrategia")

    assert nombre_con_codigo("NR_T").split(" (")[0] in etiquetas
    assert "(NR_T)" in etiquetas


def test_la_disposicion_es_reproducible():
    from chec_local_interpreter import intervention_graph as ig

    a, _ = ig.build_graph_elements(_modelo_de_prueba())
    b, _ = ig.build_graph_elements(_modelo_de_prueba())

    assert [(n["id"], n["x"], n["y"]) for n in a] == [(n["id"], n["x"], n["y"]) for n in b]


# ---------------------------------------------------------------------------
# Rotulos y hover: lo que el lector ve cuando el texto no cabe
# ---------------------------------------------------------------------------


_ROTULO_LARGO = "Inspección en campo · Riesgo por vegetación cercana al vano (NR_T)"


def test_el_rotulo_del_anillo_no_se_corta_a_la_mitad_de_una_palabra():
    """`[:38]` dejaba "Inspección en campo · Riesgo por veget" en el informe.

    Y no era un limite del espacio: `_ring_radius` YA calcula el radio del anillo a
    partir del rotulo ENVUELTO en dos lineas, asi que el hueco estaba reservado y el
    dibujo no lo usaba. La geometria y el dibujo se contradecian, y ganaba el corte.
    """
    nodes = [{
        "id": "e1", "kind": "estrategia", "label": _ROTULO_LARGO,
        "x": 200.0, "y": 0.0, "soporte": 3, "total_circuitos": 12,
    }]
    fig = ig.figura_plotly(nodes, [])
    textos = [a.text for a in fig.layout.annotations]

    assert textos, "el anillo tiene que llevar su rotulo"
    entero = "".join(textos).replace("<br>", " ")
    assert "vegetación cercana al vano" in entero, f"rotulo cortado: {textos}"


def test_el_rotulo_largo_se_reparte_en_dos_lineas_por_su_propio_separador():
    """El corte va en el ` · ` que el propio concepto trae, no a mitad de palabra:
    es el mismo criterio con el que `_ring_radius` midio el anillo."""
    nodes = [{
        "id": "e1", "kind": "estrategia", "label": _ROTULO_LARGO,
        "x": 200.0, "y": 0.0, "soporte": 3, "total_circuitos": 12,
    }]
    fig = ig.figura_plotly(nodes, [])
    texto = fig.layout.annotations[0].text

    assert "<br>" in texto
    cabeza, _, cola = texto.partition("<br>")
    assert cabeza.strip() == "Inspección en campo"
    assert cola.strip().startswith("Riesgo por vegetación")


def test_el_hover_parte_las_lineas_largas():
    """Plotly no envuelve el globo de hover: una linea de 200 caracteres lo hace mas
    ancho que la figura y el navegador lo recorta por los DOS lados, que es como se veia
    en el informe -- texto cortado a izquierda y a derecha a la vez.
    """
    larga = ("Entorno/Riesgo aporta NR_T, que describe el riesgo por vegetación cercana "
             "al vano, y DDT, que describe la densidad de descargas a tierra, junto con "
             "precipitación, nubosidad, viento y ráfagas, y las reglas del contexto los "
             "vinculan de forma explícita con el indicador")
    nodo = {
        "label": "Clima/atmosférico", "soporte": 9, "total_circuitos": 12,
        "detalle": [larga],
    }

    hover = ig._hover_de_nodo(nodo)
    lineas = hover.split("<br>")

    assert max(len(l) for l in lineas) <= ig.ANCHO_HOVER + 20, (
        f"linea de {max(len(l) for l in lineas)} caracteres sin partir")
    assert "vegetación cercana" in hover.replace("<br>", " ")


def test_el_hover_no_parte_palabras():
    nodo = {"label": "X", "detalle": ["palabra " * 60]}
    hover = ig._hover_de_nodo(nodo)

    for linea in hover.split("<br>"):
        assert not linea.startswith("abra"), "corto una palabra por la mitad"
