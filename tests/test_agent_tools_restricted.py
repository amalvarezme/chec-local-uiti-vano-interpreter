"""Guards the restricted-Bash invariant each L3 agent role file documents in prose.

Each of the 5 agent-native role files claims, in its own "Allowed tools" section, that the
role gets no shell access beyond its own build-context/validate CLI verbs and Read. Without a
`tools:` frontmatter key, Claude Code registers the role with unrestricted tool access
regardless of that prose -- this test makes the restriction load-bearing.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGENT_ROLE_FILES = (
    "historical.md",
    "inference.md",
    "expert-alignment.md",
    "auto-simulator.md",
    "pdf-discussion-extraction.md",
)
_TOOLS_LINE_RE = re.compile(r"^tools:\s*(.+)$", re.MULTILINE)


def _declared_tools(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path} has no YAML frontmatter"
    frontmatter = text[4 : text.index("\n---", 4)]
    match = _TOOLS_LINE_RE.search(frontmatter)
    assert match, f"{path} has no `tools:` frontmatter key"
    return {tool.strip() for tool in match.group(1).split(",")}


@pytest.mark.parametrize("filename", AGENT_ROLE_FILES)
def test_agent_role_declares_restricted_tools(filename: str) -> None:
    path = PROJECT_ROOT / ".claude" / "agents" / filename
    declared = _declared_tools(path)
    assert declared == {"Read", "Bash"}, (
        f"{filename} declares {declared}, expected exactly {{'Read', 'Bash'}} per its own "
        "documented 'Allowed tools' section"
    )
