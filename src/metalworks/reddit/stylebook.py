"""Shared AI-tell stylebook — the single source of the reply AI-tell phrase list.

The AI-tell phrase list used to be encoded twice: once as the linter's regex
denylist in `compliance.py`, and again in prose inside the generator prompt
(`discovery/prompts.py` — "never say 'great question'…"). Two copies drift. This
module is the one definition both import.

The denylist is a *cheap deterministic first pass*, not the authoritative gate
for authentic voice — a finite hand-list catches only its exact strings, so any
model not using them sails through. The real arbiter of "does this read as
authentic" is the LLM judge (`discovery/judge.py`), which the discovery pipeline
escalates a heuristic-pass to. Keep this list tight and high-precision: it exists
to reject the obvious tells fast, and to *name examples* for the generator so it
avoids the whole family, not just these strings.
"""

from __future__ import annotations

import re

# Reply/comment AI-tell phrases. Each entry is a regex fragment; the compiled
# `AI_TELL_REGEX` OR-joins them (case-insensitive). Plain-English examples for
# the generator prompt live in `AI_TELL_EXAMPLES` below — keep the two in sync
# by construction (the examples describe what these patterns catch).
AI_TELLS: list[str] = [
    r"\bgreat question\b",
    r"\bgreat point\b",
    r"\bhope this helps\b",
    r"\blet me know if\b",
    r"\bhappy to help\b",
    r"\bI completely understand\b",
    r"\bI hear you\b",
    r"\bdelve into\b",
    r"\bin today's\s+(landscape|world|environment)\b",
    r"\b(crucial|pivotal|robust|comprehensive|nuanced|multifaceted)\b",
    r"\bAs an AI\b",
]

AI_TELL_REGEX = re.compile("|".join(AI_TELLS), re.IGNORECASE)

# Plain-English examples named in the generator prompt. Not the gate — the LLM
# judge is — but they tell the model which family of openers/fillers to avoid so
# it doesn't reach for novel phrasings the regex can't enumerate.
AI_TELL_EXAMPLES: list[str] = [
    "great question",
    "happy to help",
    "hope this helps",
    "I completely understand",
    "delve into",
]

__all__ = ["AI_TELLS", "AI_TELL_EXAMPLES", "AI_TELL_REGEX"]
