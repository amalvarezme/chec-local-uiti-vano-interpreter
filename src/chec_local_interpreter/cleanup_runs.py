"""Safe deletion tool for disposable `/report` pipeline run artifacts.

This module intentionally does one destructive thing and does it carefully:
delete the contents of a fixed, explicitly enumerated set of report/output
directories, while defending against path-traversal/typo bugs and requiring
an exact typed confirmation phrase before touching anything.

The 9 known category roots (relative to the project root) are the ONLY
directories this tool will ever operate on. Nothing outside this allowlist
is ever resolved, even if a caller passes a bogus category table in (see
`discover_targets`'s `categories` parameter, used for defense-in-depth
testing) -- validation always checks against the hardcoded
`_ALLOWED_RELATIVE_ROOTS` set, never against whatever was passed in.
"""

from __future__ import annotations

import argparse
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from chec_local_interpreter.config import PROJECT_ROOT

GITKEEP_NAME = ".gitkeep"

CONFIRM_PHRASE = "BORRAR TODO"

# (name, relative_root, must_survive)
# must_survive=True  -> categories 1-7: root dir itself must exist afterward
#                        (possibly .gitkeep-only), only its contents are removed.
# must_survive=False -> categories 8-9: root dir may be removed entirely.
CATEGORIES: tuple[tuple[str, str, bool], ...] = (
    ("runs", "reports/interpretability/runs", True),
    ("artifacts", "reports/interpretability/artifacts", True),
    ("published", "reports/interpretability/published", True),
    ("html", "reports/interpretability/html", True),
    ("graphify", "reports/graphify", True),
    ("mgcecdl-results", "reports/mgcecdl-results", True),
    ("legacy-model-assets", "reports/legacy-model-assets", True),
    ("graphify-workspace-outputs", "outputs/graphify_workspace", False),
    ("notebooks-graphify-workspace-outputs", "notebooks/outputs/graphify_workspace", False),
)

_ALLOWED_RELATIVE_ROOTS = frozenset(rel for _name, rel, _survive in CATEGORIES)

_CATEGORY_NAMES = tuple(name for name, _rel, _survive in CATEGORIES)


@dataclass
class CleanupCategory:
    name: str
    root: Path
    must_survive: bool
    paths: list[Path] = field(default_factory=list)
    item_count: int = 0
    total_bytes: int = 0


@dataclass
class DeletionResult:
    deleted_count: int = 0
    freed_bytes: int = 0
    per_category: dict[str, int] = field(default_factory=dict)


def _validate_relative_root(relative_root: str) -> None:
    """Refuse anything that is not one of the 9 known allowlisted roots.

    This is deliberately checked against the hardcoded
    `_ALLOWED_RELATIVE_ROOTS`, never against a caller-supplied category
    table, so a bogus/typo'd category can never sneak past this guard.
    """
    if relative_root not in _ALLOWED_RELATIVE_ROOTS:
        raise ValueError(
            f"Refusing unknown category root {relative_root!r}: not in the "
            f"allowlist of 9 known report-run artifact roots."
        )


def _resolve_category_root(project_root: Path, relative_root: str) -> Path:
    _validate_relative_root(relative_root)
    project_root = project_root.resolve()
    resolved = (project_root / relative_root).resolve()
    try:
        resolved.relative_to(project_root)
    except ValueError as exc:
        raise ValueError(
            f"Refusing category root {relative_root!r}: resolves to "
            f"{resolved} which escapes project root {project_root}."
        ) from exc
    return resolved


def _iter_deletable_paths(root: Path) -> list[Path]:
    """Top-level entries directly under `root`, excluding `.gitkeep`."""
    if not root.exists():
        return []
    return sorted(p for p in root.iterdir() if p.name != GITKEEP_NAME)


def _path_size(path: Path) -> int:
    if path.is_file() or path.is_symlink():
        try:
            return path.lstat().st_size
        except OSError:
            return 0
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            try:
                total += child.stat().st_size
            except OSError:
                continue
    return total


def _count_items(path: Path) -> int:
    """Count files (not directories) under `path`, or 1 for a bare file."""
    if path.is_file() or path.is_symlink():
        return 1
    count = 0
    for child in path.rglob("*"):
        if child.is_file():
            count += 1
    return count


def discover_targets(
    project_root: Path,
    categories: Sequence[tuple[str, str, bool]] = CATEGORIES,
) -> list[CleanupCategory]:
    """Resolve the known cleanup categories under `project_root`.

    Every category root is validated against the hardcoded allowlist before
    being included -- a category whose relative root is not one of the 9
    known roots, or whose resolved path escapes `project_root`, raises
    `ValueError` instead of being silently skipped or processed.

    Category roots that don't exist on disk yet are reported as empty
    (0 items), not an error.
    """
    project_root = Path(project_root).resolve()
    result: list[CleanupCategory] = []
    for name, relative_root, must_survive in categories:
        root = _resolve_category_root(project_root, relative_root)
        paths = _iter_deletable_paths(root)
        item_count = sum(_count_items(p) for p in paths)
        total_bytes = sum(_path_size(p) for p in paths)
        result.append(
            CleanupCategory(
                name=name,
                root=root,
                must_survive=must_survive,
                paths=paths,
                item_count=item_count,
                total_bytes=total_bytes,
            )
        )
    return result


def _human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def format_summary(categories: Sequence[CleanupCategory]) -> str:
    lines = ["Resumen de limpieza de artefactos de corridas de /report:", ""]
    total_items = 0
    total_bytes = 0
    for cat in categories:
        total_items += cat.item_count
        total_bytes += cat.total_bytes
        survive_note = "" if cat.must_survive else " (directorio puede eliminarse por completo)"
        lines.append(
            f"  - {cat.name} [{cat.root}]{survive_note}: "
            f"{cat.item_count} archivos, {_human_size(cat.total_bytes)}"
        )
    lines.append("")
    lines.append(f"Total: {total_items} archivos, {_human_size(total_bytes)}")
    return "\n".join(lines)


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def delete_targets(
    categories: Sequence[CleanupCategory],
    project_root: Path,
    selected_names: set[str],
) -> DeletionResult:
    """Delete files/dirs belonging to `selected_names` categories.

    Skips `.gitkeep`. For "must survive" categories, the root dir itself is
    never removed -- only its contents. For categories 8-9 (must_survive is
    False), the root dir may be removed entirely along with its contents.
    """
    result = DeletionResult()
    for cat in categories:
        if cat.name not in selected_names:
            continue
        deleted_here = 0
        freed_here = 0
        for path in cat.paths:
            item_count = _count_items(path)
            item_bytes = _path_size(path)
            _remove_path(path)
            deleted_here += item_count
            freed_here += item_bytes
        if not cat.must_survive and cat.root.exists():
            # Root itself may be removed entirely once contents are gone.
            try:
                cat.root.rmdir()
            except OSError:
                pass
        result.deleted_count += deleted_here
        result.freed_bytes += freed_here
        result.per_category[cat.name] = deleted_here
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m chec_local_interpreter.cleanup_runs",
        description="Safely delete disposable /report pipeline run artifacts.",
    )
    parser.add_argument(
        "--project-root",
        default=str(PROJECT_ROOT),
        help="Repo root to operate under (defaults to the detected project root).",
    )
    parser.add_argument(
        "--only",
        default=None,
        help="Comma-separated list of category names to include (default: all).",
    )
    parser.add_argument(
        "--skip",
        default=None,
        help="Comma-separated list of category names to exclude (default: none).",
    )
    parser.add_argument(
        "--confirm",
        default=None,
        metavar="PHRASE",
        help=(
            'Must be the exact literal phrase "BORRAR TODO" (case-sensitive) '
            "to actually delete anything. Without it, this tool only prints "
            "a dry-run summary and deletes nothing."
        ),
    )
    return parser


def _parse_name_list(raw: str | None) -> set[str] | None:
    if raw is None:
        return None
    return {item.strip() for item in raw.split(",") if item.strip()}


def _validate_names(names: set[str], flag: str) -> str | None:
    unknown = names - set(_CATEGORY_NAMES)
    if unknown:
        unknown_list = ", ".join(sorted(unknown))
        return (
            f"Unknown category name(s) in {flag}: {unknown_list}. "
            f"Known categories: {', '.join(_CATEGORY_NAMES)}."
        )
    return None


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    project_root = Path(args.project_root)

    only_names = _parse_name_list(args.only)
    skip_names = _parse_name_list(args.skip)

    if only_names is not None:
        error = _validate_names(only_names, "--only")
        if error:
            print(f"Error: {error}")
            return 2
    if skip_names is not None:
        error = _validate_names(skip_names, "--skip")
        if error:
            print(f"Error: {error}")
            return 2

    selected_names = set(_CATEGORY_NAMES)
    if only_names is not None:
        selected_names &= only_names
    if skip_names is not None:
        selected_names -= skip_names

    categories = discover_targets(project_root)
    print(format_summary(categories))

    if args.confirm is None:
        print()
        print(
            "Modo dry-run: no se elimino ningun archivo. "
            'Vuelva a ejecutar con --confirm "BORRAR TODO" para confirmar el borrado.'
        )
        return 0

    if args.confirm != CONFIRM_PHRASE:
        print()
        print(
            f'Error: la frase de confirmacion no coincide. Se esperaba '
            f'exactamente "{CONFIRM_PHRASE}". No se elimino ningun archivo.'
        )
        return 2

    result = delete_targets(categories, project_root, selected_names)
    print()
    print(
        f"Borrado confirmado: {result.deleted_count} archivos eliminados, "
        f"{_human_size(result.freed_bytes)} liberados."
    )
    for name, count in sorted(result.per_category.items()):
        print(f"  - {name}: {count} archivos eliminados")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
