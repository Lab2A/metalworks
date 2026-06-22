"""Shared verbatim-grounding helper.

The honesty rule across the research pillars is "no-cite-no-claim": a claim the
LLM makes survives only when its supporting fragment is a literal slice of a
real, verified :class:`~metalworks.contract.research.ResolvedCitation` — not a
paraphrase. Multiple pillars (launch, content, …) need the same check, so it
lives here once.

The match is a substring scan, but a RAW scan is brittle: the LLM routinely
copies a quote "verbatim" yet swaps a straight quote for a curly one, or
collapses whitespace, and the fragment silently fails to match its own source.
:func:`verbatim_match` normalizes both sides (collapse whitespace, fold curly
quotes and en/em dashes to ASCII) before comparing, so a faithfully-copied
fragment matches even when its punctuation drifted.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from metalworks.contract import ResolvedCitation

# A supporting fragment must be substantive — a 1-2 word substring ("users") is
# a real slice of a quote but doesn't ground the surrounding claim.
_MIN_FRAGMENT_WORDS = 4

# Typographic variants the LLM emits that a raw substring scan would miss:
# curly single/double quotes -> ASCII quote, en/em dashes -> ASCII hyphen.
# Keys are written as escapes so the source stays free of ambiguous glyphs.
_NORMALIZE: dict[int, str] = {
    0x2018: "'",  # LEFT SINGLE QUOTATION MARK
    0x2019: "'",  # RIGHT SINGLE QUOTATION MARK / apostrophe
    0x201C: '"',  # LEFT DOUBLE QUOTATION MARK
    0x201D: '"',  # RIGHT DOUBLE QUOTATION MARK
    0x2013: "-",  # EN DASH
    0x2014: "-",  # EM DASH
}


def _normalize(text: str) -> str:
    """Fold typographic variants and collapse whitespace. Pure.

    Whitespace is collapsed to single spaces and ends are stripped, and curly
    quotes / en-em dashes are mapped to their ASCII forms, so two fragments that
    differ only in punctuation style or spacing compare equal.
    """
    return " ".join(text.translate(_NORMALIZE).split())


def verbatim_match(
    fragment: str,
    quotes: Iterable[ResolvedCitation],
    *,
    min_words: int = _MIN_FRAGMENT_WORDS,
) -> ResolvedCitation | None:
    """The first quote whose text contains ``fragment`` verbatim, or ``None``.

    Both the fragment and each quote's text are normalized (whitespace collapsed,
    curly quotes / en-em dashes folded to ASCII) before the substring check, so a
    fragment the LLM copied faithfully matches even when its punctuation drifted.

    Returns ``None`` when the fragment is blank or shorter than ``min_words``
    words — too thin a slice to ground a claim (no-cite-no-claim).
    """
    needle = _normalize(fragment)
    if not needle or len(needle.split()) < min_words:
        return None
    for quote in quotes:
        if needle in _normalize(quote.text):
            return quote
    return None
