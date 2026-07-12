"""Guard test for `sdd/agent-native-pipeline-and-site-split` PR B (site relocation).

Pins the site relocation from `src/pages`, `src/assets/site`, `src/data` to a
new top-level `site/` folder (design D4): the astro source tree lives under
`site/`, not under `src/`, and `astro.config.mjs`'s `srcDir` points at it.

Mirrors `tests/test_llm_directory_retired.py`'s pattern: assert the old paths
are gone and the new paths exist.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

OLD_SITE_PATHS = (
    "src/pages",
    "src/assets/site",
    "src/data",
)

NEW_SITE_PATHS = (
    "site/pages",
    "site/assets/site",
    "site/data",
)


def test_no_site_files_remain_under_src():
    for old_path in OLD_SITE_PATHS:
        assert not (PROJECT_ROOT / old_path).exists(), (
            f"{old_path} should have been relocated out of src/ (see design D4)"
        )


def test_site_files_exist_at_new_top_level_location():
    for new_path in NEW_SITE_PATHS:
        assert (PROJECT_ROOT / new_path).exists(), (
            f"{new_path} should exist after the site relocation (see design D4)"
        )
