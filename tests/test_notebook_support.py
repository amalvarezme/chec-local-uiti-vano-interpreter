from __future__ import annotations

from pathlib import Path

import pytest

from chec_impacto.notebook_support import add_src_to_path, find_repo_root, resolve_project_root


def test_resolve_project_root_finds_package_marker(tmp_path, monkeypatch):
    project = tmp_path / "project"
    marker = project / "src" / "chec_impacto"
    marker.mkdir(parents=True)
    workdir = project / "notebooks" / "inference"
    workdir.mkdir(parents=True)
    monkeypatch.chdir(workdir)

    assert resolve_project_root(clone_if_missing=False) == project


def test_resolve_project_root_returns_cwd_without_clone_when_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert resolve_project_root(clone_if_missing=False) == tmp_path


def test_find_repo_root_uses_marker_file(tmp_path, monkeypatch):
    project = tmp_path / "project"
    marker = project / "src" / "data" / "variables.json"
    marker.parent.mkdir(parents=True)
    marker.write_text("{}", encoding="utf-8")
    workdir = project / "notebooks" / "web"
    workdir.mkdir(parents=True)
    monkeypatch.chdir(workdir)

    assert find_repo_root() == project


def test_find_repo_root_raises_when_marker_is_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with pytest.raises(FileNotFoundError):
        find_repo_root()


def test_add_src_to_path_adds_project_src_once(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.path", [])

    src_path = add_src_to_path(tmp_path)
    add_src_to_path(tmp_path)

    assert src_path == tmp_path / "src"
    assert str(src_path) in __import__("sys").path
    assert __import__("sys").path.count(str(src_path)) == 1
