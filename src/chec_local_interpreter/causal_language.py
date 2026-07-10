"""Shared causal-language guard, agent-agnostic.

Closes pilot Known Limitation #3: `expert_alignment.py`'s bare-word check
(`\\bcausa\\b`) rejected the singular noun "causa" but missed plural
("causas") and adjective ("causal"/"causales") forms — and
`llm_validation._guardrail_errors` had no causal-language check at all,
despite the base agent's invariants claiming it was enforced (a latent gap
for any future agent built on that validator).

This module is the single home of the matching logic so both the
expert-alignment validator and the base/historical validator enforce the
exact same rule — duplicating the regex per agent is exactly the drift class
this module exists to prevent.
"""

from __future__ import annotations

import re

# Word-boundary matching (not a substring check) so an unrelated Spanish word
# that merely contains "causa", e.g. "encausar" ("to channel/prosecute"), is
# never flagged.
_CAUSAL_WORD_RE = re.compile(
    r"\bcaus[óo]\b"  # causó / causo
    r"|\bcausa(?:s|l|les|nte|ntes|da|das|do|dos)?\b"  # causa(s), causal(es), causante(s), causad[oa](s)
    r"|\bcausalidad(?:es)?\b",  # causalidad(es)
    re.IGNORECASE,
)

_CAUSAL_PHRASE_RE = re.compile(
    r"demuestra causalidad|prueba causal",
    re.IGNORECASE,
)


def find_causal_language(text: str | None) -> list[str]:
    """Return every causal-language term/phrase found in `text`.

    Returns an empty list when nothing matches (including for empty/`None`
    input), so callers can use the result directly as a truthy validation
    signal (`if find_causal_language(text): ...`).
    """
    if not text:
        return []
    matches = [match.group(0) for match in _CAUSAL_WORD_RE.finditer(text)]
    matches.extend(match.group(0) for match in _CAUSAL_PHRASE_RE.finditer(text))
    return matches
