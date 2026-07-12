from __future__ import annotations

import pytest

from chec_local_interpreter import web_export


def test_export_latest_interpretability_report_copies_html_to_results_dir(tmp_path, monkeypatch):
    results_dir = tmp_path / "site_results"
    monkeypatch.setattr(web_export, "_RESULTS_DIR", results_dir)

    source = tmp_path / "run_dir" / "report.html"
    source.parent.mkdir(parents=True)
    source.write_text("<html><body>informe</body></html>", encoding="utf-8")

    dest = web_export.export_latest_interpretability_report(source)

    assert dest == results_dir / "latest_interpretability_report.html"
    assert dest.exists()
    assert "informe" in dest.read_text(encoding="utf-8")


def test_export_latest_interpretability_report_missing_source_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(web_export, "_RESULTS_DIR", tmp_path / "site_results")

    with pytest.raises(FileNotFoundError):
        web_export.export_latest_interpretability_report(tmp_path / "does_not_exist.html")
