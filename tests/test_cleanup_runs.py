from __future__ import annotations

import pytest

from chec_local_interpreter.cleanup_runs import (
    CATEGORIES,
    delete_targets,
    discover_targets,
    format_summary,
    main,
)

CONFIRM_PHRASE = "BORRAR TODO"


# ---------------------------------------------------------------------------
# Fixture project tree builder
# ---------------------------------------------------------------------------


def _build_fake_project(tmp_path):
    """Build a fake project tree mirroring the real repo's 10 cleanup categories,
    plus untouchable siblings (analysis-documents, geo)."""
    root = tmp_path

    # 1. reports/interpretability/runs/ -- fully gitignored, no .gitkeep
    runs = root / "reports" / "interpretability" / "runs"
    run_dir = runs / "CHA23L14" / "20260717T000722423017"
    run_dir.mkdir(parents=True)
    (run_dir / "historical.out.json").write_text("{}")
    (run_dir / "inference.out.json").write_text("{}")
    figs = run_dir / "inference_figures"
    figs.mkdir()
    (figs / "chart.png").write_bytes(b"fake-png-bytes")

    # 2. reports/interpretability/artifacts/ -- .gitkeep preserved
    artifacts = root / "reports" / "interpretability" / "artifacts"
    (artifacts / "historical").mkdir(parents=True)
    (artifacts / "historical" / "foo.json").write_text("{}")
    (artifacts / ".gitkeep").write_text("")

    # 3. reports/interpretability/published/ -- .gitkeep preserved
    published = root / "reports" / "interpretability" / "published"
    published.mkdir(parents=True)
    (published / "report.html").write_text("<html></html>")
    (published / ".gitkeep").write_text("")

    # 4. reports/interpretability/html/ -- may or may not have .gitkeep
    html_dir = root / "reports" / "interpretability" / "html"
    html_dir.mkdir(parents=True)
    (html_dir / "CHA23L14_report.html").write_text("<html></html>")
    (html_dir / ".gitkeep").write_text("")

    # 5. reports/graphify/ -- raw/ and graphify-out/ subdirs, .gitkeep at root preserved
    graphify = root / "reports" / "graphify"
    (graphify / "raw").mkdir(parents=True)
    (graphify / "raw" / "input.json").write_text("{}")
    (graphify / "graphify-out").mkdir(parents=True)
    (graphify / "graphify-out" / "graph.json").write_text("{}")
    (graphify / ".gitkeep").write_text("")

    # 6. reports/mgcecdl-results/ -- .gitkeep preserved
    mgcecdl = root / "reports" / "mgcecdl-results"
    mgcecdl.mkdir(parents=True)
    (mgcecdl / "result.csv").write_text("a,b\n1,2\n")
    (mgcecdl / ".gitkeep").write_text("")

    # 7. reports/legacy-model-assets/ -- .gitkeep preserved
    legacy = root / "reports" / "legacy-model-assets"
    legacy.mkdir(parents=True)
    (legacy / "model.zip").write_bytes(b"fake-zip-bytes")
    (legacy / ".gitkeep").write_text("")

    # 8. outputs/graphify_workspace/ -- may be removed entirely
    outputs_ws = root / "outputs" / "graphify_workspace"
    outputs_ws.mkdir(parents=True)
    (outputs_ws / "workspace.tmp").write_text("scratch")

    # 9. notebooks/outputs/graphify_workspace/ -- may be removed entirely
    nb_outputs_ws = root / "notebooks" / "outputs" / "graphify_workspace"
    nb_outputs_ws.mkdir(parents=True)
    (nb_outputs_ws / "workspace.tmp").write_text("scratch")

    # 10. reports/vault/ -- disposable/regenerable circuit notes, .gitkeep preserved
    vault = root / "reports" / "vault"
    vault.mkdir(parents=True)
    (vault / "CHA23L14.md").write_text("# CHA23L14\n")
    (vault / ".gitkeep").write_text("")

    # Hard exclusions -- must NEVER be touched
    analysis_docs = root / "reports" / "analysis-documents"
    analysis_docs.mkdir(parents=True)
    (analysis_docs / "real-doc.md").write_text("# Real document\n")

    geo = root / "reports" / "geo"
    geo.mkdir(parents=True)
    (geo / "some.csv").write_text("lat,lon\n1,2\n")

    return root


def _real_doc(root):
    return root / "reports" / "analysis-documents" / "real-doc.md"


def _geo_csv(root):
    return root / "reports" / "geo" / "some.csv"


# ---------------------------------------------------------------------------
# discover_targets
# ---------------------------------------------------------------------------


def test_discover_targets_finds_expected_files_and_counts(tmp_path):
    root = _build_fake_project(tmp_path)

    categories = discover_targets(root)

    by_name = {c.name for c in categories}
    assert len(categories) == 10
    assert by_name == {c[0] for c in CATEGORIES}

    runs_cat = next(c for c in categories if c.name == "runs")
    assert runs_cat.item_count > 0
    assert runs_cat.total_bytes > 0

    artifacts_cat = next(c for c in categories if c.name == "artifacts")
    # .gitkeep itself must not count as a deletable item
    assert all(p.name != ".gitkeep" for p in artifacts_cat.paths)
    assert artifacts_cat.item_count >= 1

    vault_cat = next(c for c in categories if c.name == "vault")
    assert all(p.name != ".gitkeep" for p in vault_cat.paths)
    assert vault_cat.item_count >= 1
    assert vault_cat.total_bytes > 0


def test_discover_targets_reports_missing_roots_as_empty_not_error(tmp_path):
    # Fresh empty tmp_path -- none of the 10 roots exist on disk yet.
    root = tmp_path

    categories = discover_targets(root)

    assert len(categories) == 10
    for cat in categories:
        assert cat.item_count == 0
        assert cat.total_bytes == 0
        assert cat.paths == []


def test_vault_category_registered_with_correct_root_and_must_survive():
    vault_entry = next((c for c in CATEGORIES if c[0] == "vault"), None)
    assert vault_entry is not None, "'vault' category must be present in CATEGORIES"
    _name, relative_root, must_survive = vault_entry
    assert relative_root == "reports/vault"
    assert must_survive is True


def test_discover_targets_rejects_relative_path_outside_allowlist(tmp_path):
    root = _build_fake_project(tmp_path)
    # A relative path that is NOT one of the 9 known category roots (even
    # though it exists on disk) must be refused -- defense against a future
    # typo/bug in the category table, e.g. someone accidentally wiring up
    # the excluded analysis-documents dir.
    bogus_categories = [("bogus", "reports/analysis-documents", True)]

    with pytest.raises(ValueError):
        discover_targets(root, categories=bogus_categories)


def test_discover_targets_rejects_path_traversal_escape(tmp_path):
    root = _build_fake_project(tmp_path)
    escaping_categories = [("escape", "../outside-project", True)]

    with pytest.raises(ValueError):
        discover_targets(root, categories=escaping_categories)


# ---------------------------------------------------------------------------
# format_summary
# ---------------------------------------------------------------------------


def test_format_summary_lists_all_categories_including_empty(tmp_path):
    root = tmp_path  # nothing exists

    categories = discover_targets(root)
    summary = format_summary(categories)

    for name, _rel, _survive in CATEGORIES:
        assert name in summary


def test_format_summary_includes_grand_total(tmp_path):
    root = _build_fake_project(tmp_path)
    categories = discover_targets(root)

    summary = format_summary(categories)

    assert "total" in summary.lower()


# ---------------------------------------------------------------------------
# CLI: dry-run (default, no --confirm)
# ---------------------------------------------------------------------------


def test_dry_run_deletes_nothing(tmp_path, capsys):
    root = _build_fake_project(tmp_path)

    exit_code = main(["--project-root", str(root)])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "no se elimin" in out.lower() or "nothing" in out.lower() or "dry" in out.lower()

    # every fixture file must still exist
    assert (root / "reports" / "interpretability" / "runs" / "CHA23L14" / "20260717T000722423017" / "historical.out.json").exists()
    assert (root / "reports" / "interpretability" / "artifacts" / "historical" / "foo.json").exists()
    assert (root / "reports" / "interpretability" / "published" / "report.html").exists()
    assert (root / "reports" / "interpretability" / "html" / "CHA23L14_report.html").exists()
    assert (root / "reports" / "graphify" / "raw" / "input.json").exists()
    assert (root / "reports" / "graphify" / "graphify-out" / "graph.json").exists()
    assert (root / "reports" / "mgcecdl-results" / "result.csv").exists()
    assert (root / "reports" / "legacy-model-assets" / "model.zip").exists()
    assert (root / "outputs" / "graphify_workspace" / "workspace.tmp").exists()
    assert (root / "notebooks" / "outputs" / "graphify_workspace" / "workspace.tmp").exists()
    assert (root / "reports" / "vault" / "CHA23L14.md").exists()
    assert _real_doc(root).exists()
    assert _geo_csv(root).exists()


# ---------------------------------------------------------------------------
# CLI: confirmed deletion
# ---------------------------------------------------------------------------


def test_confirmed_deletion_removes_selected_categories_but_preserves_gitkeep_and_exclusions(tmp_path, capsys):
    root = _build_fake_project(tmp_path)

    exit_code = main(["--project-root", str(root), "--confirm", CONFIRM_PHRASE])

    assert exit_code == 0

    # deleted content
    assert not (root / "reports" / "interpretability" / "runs" / "CHA23L14").exists()
    assert not (root / "reports" / "interpretability" / "artifacts" / "historical").exists()
    assert not (root / "reports" / "interpretability" / "published" / "report.html").exists()
    assert not (root / "reports" / "interpretability" / "html" / "CHA23L14_report.html").exists()
    assert not (root / "reports" / "graphify" / "raw" / "input.json").exists()
    assert not (root / "reports" / "graphify" / "graphify-out" / "graph.json").exists()
    assert not (root / "reports" / "mgcecdl-results" / "result.csv").exists()
    assert not (root / "reports" / "legacy-model-assets" / "model.zip").exists()
    assert not (root / "reports" / "vault" / "CHA23L14.md").exists()

    # .gitkeep preserved
    assert (root / "reports" / "interpretability" / "artifacts" / ".gitkeep").exists()
    assert (root / "reports" / "interpretability" / "published" / ".gitkeep").exists()
    assert (root / "reports" / "interpretability" / "html" / ".gitkeep").exists()
    assert (root / "reports" / "graphify" / ".gitkeep").exists()
    assert (root / "reports" / "mgcecdl-results" / ".gitkeep").exists()
    assert (root / "reports" / "legacy-model-assets" / ".gitkeep").exists()
    assert (root / "reports" / "vault" / ".gitkeep").exists()

    # "root must survive" category roots still exist as (empty/.gitkeep-only) dirs
    assert (root / "reports" / "interpretability" / "runs").is_dir()
    assert (root / "reports" / "interpretability" / "artifacts").is_dir()
    assert (root / "reports" / "interpretability" / "published").is_dir()
    assert (root / "reports" / "interpretability" / "html").is_dir()
    assert (root / "reports" / "graphify").is_dir()
    assert (root / "reports" / "mgcecdl-results").is_dir()
    assert (root / "reports" / "legacy-model-assets").is_dir()
    assert (root / "reports" / "vault").is_dir()

    # hard exclusions untouched
    assert _real_doc(root).exists()
    assert _geo_csv(root).exists()

    out = capsys.readouterr().out
    assert out  # some final summary was printed


def test_confirmed_deletion_wrong_phrase_deletes_nothing_and_exits_nonzero(tmp_path, capsys):
    root = _build_fake_project(tmp_path)

    exit_code = main(["--project-root", str(root), "--confirm", "not the phrase"])

    assert exit_code != 0
    assert (root / "reports" / "interpretability" / "runs" / "CHA23L14" / "20260717T000722423017" / "historical.out.json").exists()
    assert (root / "reports" / "interpretability" / "artifacts" / "historical" / "foo.json").exists()
    assert _real_doc(root).exists()
    assert _geo_csv(root).exists()


def test_confirmed_deletion_wrong_phrase_prints_error(tmp_path, capsys):
    root = _build_fake_project(tmp_path)

    main(["--project-root", str(root), "--confirm", "BORRAR PARCIAL"])

    err = capsys.readouterr()
    combined = (err.out + err.err).lower()
    assert "confirm" in combined or "phrase" in combined or "frase" in combined


# ---------------------------------------------------------------------------
# --only / --skip narrowing
# ---------------------------------------------------------------------------


def test_only_narrows_deletion_to_selected_category(tmp_path):
    root = _build_fake_project(tmp_path)

    exit_code = main(["--project-root", str(root), "--only", "runs", "--confirm", CONFIRM_PHRASE])

    assert exit_code == 0
    # runs category emptied
    assert not (root / "reports" / "interpretability" / "runs" / "CHA23L14").exists()
    # everything else untouched
    assert (root / "reports" / "interpretability" / "artifacts" / "historical" / "foo.json").exists()
    assert (root / "reports" / "interpretability" / "published" / "report.html").exists()
    assert (root / "reports" / "mgcecdl-results" / "result.csv").exists()


def test_skip_excludes_category_from_deletion(tmp_path):
    root = _build_fake_project(tmp_path)

    exit_code = main([
        "--project-root", str(root),
        "--skip",
        "runs,artifacts,published,html,graphify,mgcecdl-results,legacy-model-assets,"
        "graphify-workspace-outputs,notebooks-graphify-workspace-outputs,vault",
        "--confirm", CONFIRM_PHRASE,
    ])

    assert exit_code == 0
    # everything skipped -- nothing deleted
    assert (root / "reports" / "interpretability" / "runs" / "CHA23L14").exists()
    assert (root / "notebooks" / "outputs" / "graphify_workspace" / "workspace.tmp").exists()
    assert (root / "reports" / "vault" / "CHA23L14.md").exists()


def test_only_with_unknown_name_errors_clearly(tmp_path, capsys):
    root = _build_fake_project(tmp_path)

    exit_code = main(["--project-root", str(root), "--only", "not-a-real-category"])

    assert exit_code != 0
    err = capsys.readouterr()
    combined = (err.out + err.err).lower()
    assert "not-a-real-category" in combined


# ---------------------------------------------------------------------------
# delete_targets unit-level check (counts returned)
# ---------------------------------------------------------------------------


def test_delete_targets_returns_counts_of_deleted_items(tmp_path):
    root = _build_fake_project(tmp_path)
    categories = discover_targets(root)
    selected = {c[0] for c in CATEGORIES}

    result = delete_targets(categories, root, selected)

    assert result.deleted_count > 0
    assert result.freed_bytes > 0
