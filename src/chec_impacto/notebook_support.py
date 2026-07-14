"""Notebook support helpers for local and Kaggle execution."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_REPO_NAME = "chec-local-uiti-vano-interpreter"
DEFAULT_REPO_URL = "https://github.com/jclugor/chec-local-uiti-vano-interpreter.git"
DEFAULT_LFS_DATA_PATH = Path("data") / "Indicadores_vano_v3.csv"


def resolve_project_root(
    *,
    package_marker: str = "chec_impacto",
    repo_name: str = DEFAULT_REPO_NAME,
    repo_url: str = DEFAULT_REPO_URL,
    clone_if_missing: bool = True,
) -> Path:
    """Resolve the repository root, optionally cloning it in Kaggle-like environments."""
    cwd = Path.cwd().resolve()
    for candidate in (cwd, *cwd.parents):
        if (candidate / "src" / package_marker).exists():
            return candidate

    if not clone_if_missing:
        return cwd

    working_root = Path("/kaggle/working") if Path("/kaggle/working").exists() else cwd
    clone_dir = working_root / repo_name
    if not clone_dir.exists():
        subprocess.run(["git", "clone", repo_url, str(clone_dir)], check=True)
    return clone_dir.resolve()


def find_repo_root(marker_path: str | Path = Path("src") / "data" / "variables.json") -> Path:
    """Find the repository root containing a marker file."""
    marker = Path(marker_path)
    for candidate in (Path.cwd(), *Path.cwd().parents):
        if (candidate / marker).is_file():
            return candidate.resolve()
    raise FileNotFoundError(
        f"No se encontró {marker}. Abre el notebook desde la raíz del repositorio."
    )


def add_src_to_path(project_root: str | Path) -> Path:
    """Add `<project_root>/src` to `sys.path` and return that path."""
    src_path = Path(project_root) / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))
    return src_path


def install_project_requirements(project_root: str | Path) -> None:
    """Install requirements for notebook execution."""
    requirements_path = Path(project_root) / "requirements.txt"
    if not requirements_path.exists():
        raise FileNotFoundError(f"No existe requirements.txt en {project_root}")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", "-r", str(requirements_path)],
        check=True,
    )


def ensure_lfs_data(
    project_root: str | Path,
    data_path: str | Path = DEFAULT_LFS_DATA_PATH,
) -> None:
    """Pull Git LFS data when available and fail if the dataset is still a pointer."""
    root = Path(project_root)
    resolved_data_path = root / data_path
    if shutil.which("git-lfs") and (root / ".git").exists():
        subprocess.run(["git", "lfs", "install", "--local"], cwd=root, check=False)
        subprocess.run(["git", "lfs", "pull"], cwd=root, check=True)
    if resolved_data_path.exists() and resolved_data_path.stat().st_size < 1024:
        head = resolved_data_path.read_text(errors="ignore")[:120]
        if "git-lfs" in head:
            raise RuntimeError(
                f"{resolved_data_path.name} quedo como puntero Git LFS. "
                "Descarga el archivo LFS antes de continuar."
            )
