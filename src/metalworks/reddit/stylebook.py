"""Shared voice stylebook — the ONE founder-voiced, platform-invariant rule set.

This is metalworks' single voice system. Two things used to live in two places:

- The AI-tell phrase list was encoded twice — the linter's regex denylist in
  `compliance.py` and prose inside the generator prompt (`discovery/prompts.py`,
  "never say 'great question'…"). This module is the one definition both import.
- The "never ask for upvotes" platform invariant lived only in the Distribution
  channel-assets path (D4, `research/distribution/assets.py`). D9 consolidates it
  here: :data:`UPVOTE_REGEX` / :data:`UPVOTE_SENTENCE_REGEX` and
  :func:`strip_upvote_ask` are the canonical no-"upvote" guard, and the
  participation/reply execution arm and D4 both import THIS one, so the
  founder-voiced / native-first / no-upvote rules can't drift into two voices.

The AI-tell denylist is a *cheap deterministic first pass*, not the authoritative
gate for authentic voice — a finite hand-list catches only its exact strings, so
any model not using them sails through. The real arbiter of "does this read as
authentic" is the LLM judge (`discovery/judge.py`), which the discovery pipeline
escalates a heuristic-pass to. Keep this list tight and high-precision: it exists
to reject the obvious tells fast, and to *name examples* for the generator so it
avoids the whole family, not just these strings. The upvote guard, by contrast,
is deterministic and load-bearing — an upvote ask is platform-fatal on Product
Hunt + Hacker News (both auto-detect and penalize vote solicitation) and reads as
begging everywhere, so it is stripped wholesale, never merely warned on.
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

# ── No-"upvote" platform invariant (deterministic, load-bearing) ──────────────

# An "upvote ask" is a platform-fatal tell on Product Hunt + Hacker News (both
# auto-detect and penalize vote solicitation) and reads as begging everywhere.
# Matches "upvote", "up-vote", "up vote". This is the single source D4's channel
# assets and the D9 participation/reply arm both guard against.
UPVOTE_REGEX = re.compile(r"\bup[\s-]?vote", re.IGNORECASE)
# A whole sentence/line that asks for upvotes — stripped wholesale from a body.
UPVOTE_SENTENCE_REGEX = re.compile(r"[^.!?\n]*\bup[\s-]?vote[^.!?\n]*[.!?]?", re.IGNORECASE)


def strip_upvote_ask(text: str) -> str:
    """Strip any 'please upvote'/'upvote us' ask from a span. Deterministic guard.

    Removes the whole offending sentence/line, then collapses the whitespace it
    leaves behind (preserving paragraph breaks). The model is told never to write
    one; this backstops it on the same text the compliance gate runs over, so the
    founder-voiced / no-upvote invariant is enforced once, not per-surface.
    """
    if not UPVOTE_REGEX.search(text):
        return text
    cleaned = UPVOTE_SENTENCE_REGEX.sub("", text)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n[ \t]+", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


__all__ = [
    "AI_TELLS",
    "AI_TELL_EXAMPLES",
    "AI_TELL_REGEX",
    "UPVOTE_REGEX",
    "UPVOTE_SENTENCE_REGEX",
    "strip_upvote_ask",
]
