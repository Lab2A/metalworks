"""Tests for the shared verbatim-grounding helper.

The regression that motivated extracting :func:`verbatim_match`: a raw substring
scan silently failed when the LLM copied a quote "verbatim" but swapped a
straight apostrophe for a curly one, or collapsed whitespace. Normalizing both
sides before the comparison fixes it.
"""

from __future__ import annotations

from metalworks.contract import ResolvedCitation
from metalworks.research.grounding import verbatim_match


def _quote(text: str) -> ResolvedCitation:
    return ResolvedCitation(text=text, source_url="https://example.com/c", author_hash="a1")


def test_curly_quote_and_whitespace_fragment_matches_source() -> None:
    """The brittleness regression: a faithfully-copied fragment whose punctuation
    drifted to curly quotes / dashes and whose whitespace collapsed still matches.
    """
    source = _quote("I really don't think the app is worth the money at all")
    # LLM-emitted fragment: curly apostrophe + doubled/odd whitespace.
    fragment = "don’t  think the app   is worth the money"  # noqa: RUF001 (curly apostrophe is the point)

    assert verbatim_match(fragment, [source]) is source


def test_en_dash_fragment_matches_hyphen_source() -> None:
    source = _quote("the onboarding is a make-or-break moment for new users")
    fragment = "a make–or–break moment for new"  # noqa: RUF001 (en dashes are the point)

    assert verbatim_match(fragment, [source]) is source


def test_exact_substring_still_matches() -> None:
    source = _quote("the support team never replies to my emails")
    assert verbatim_match("never replies to my emails", [source]) is source


def test_paraphrase_does_not_match() -> None:
    source = _quote("the support team never replies to my emails")
    assert verbatim_match("the team ignores all my messages", [source]) is None


def test_short_fragment_is_rejected() -> None:
    """A 1-2 word slice is real but too thin to ground a claim (default min 4)."""
    source = _quote("the support team never replies to my emails")
    assert verbatim_match("the support", [source]) is None


def test_blank_fragment_is_rejected() -> None:
    source = _quote("the support team never replies to my emails")
    assert verbatim_match("   ", [source]) is None


def test_min_words_override() -> None:
    source = _quote("ships fast and breaks rarely")
    assert verbatim_match("ships fast", [source]) is None
    assert verbatim_match("ships fast", [source], min_words=2) is source


def test_first_matching_quote_wins() -> None:
    a = _quote("the dashboard is slow to load every single time")
    b = _quote("the dashboard is slow to load and crashes often")
    assert verbatim_match("the dashboard is slow to load", [a, b]) is a


def test_no_quotes_returns_none() -> None:
    assert verbatim_match("anything substantive enough here", []) is None
