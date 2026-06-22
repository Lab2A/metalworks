"""Compliance gate tests — table-driven over the deterministic rules."""

from __future__ import annotations

import pytest

from metalworks.reddit.compliance import heuristic_check, heuristic_check_post


def test_empty_reply_fails_hard() -> None:
    v = heuristic_check("   ")
    assert v.pass_ is False
    assert v.confidence == 1.0
    assert "empty" in v.violations


def test_clean_reply_passes_high_confidence() -> None:
    text = (
        "I tried citicoline for a few weeks and the afternoon focus was noticeably "
        "steadier without the caffeine jitters. Worth a shot if stimulants wreck your sleep."
    )
    v = heuristic_check(text)
    assert v.pass_ is True
    assert v.confidence >= 0.9
    assert v.violations == []


@pytest.mark.parametrize(
    "text,marker",
    [
        ("Great question! You should look into nootropics for that.", "AI-tells"),
        ("This is a solid stack — really effective for focus and energy daily.", "em-dash"),
        (
            "Our product helps. Our platform is great. Our tool does it all for you here.",
            "over-promotional",
        ),
        ("nice", "too short"),
    ],
)
def test_reply_violations_flagged(text: str, marker: str) -> None:
    v = heuristic_check(text)
    assert v.pass_ is False
    assert any(marker in viol for viol in v.violations)


def test_cta_lowers_confidence_but_passes() -> None:
    text = "I had the same issue and switched to l-theanine. Check out the r/nootropics wiki."
    v = heuristic_check(text)
    assert v.pass_ is True
    assert v.confidence <= 0.6  # CTA verb → caller should escalate


def test_emdash_homoglyph_family_all_caught() -> None:
    body = "x" * 120
    for dash in ("—", "–", " - "):  # noqa: RUF001 - intentionally testing the homoglyph family
        verdict = heuristic_check_post(
            title="A perfectly reasonable title here", body=body + dash + body
        )
        assert verdict.pass_ is False
        assert any(v.code == "em_dash_homoglyph" for v in verdict.violations)


def test_post_title_length_bounds() -> None:
    short = heuristic_check_post(title="too short", body="x" * 150)
    assert any(v.code == "title_too_short" and v.severity == "error" for v in short.violations)

    long_title = heuristic_check_post(
        title="t" * 50, body="x" * 150, sub_rules={"max_title_chars": 40}
    )
    assert any(v.code == "title_too_long" for v in long_title.violations)


def test_post_flair_required_and_invalid() -> None:
    missing = heuristic_check_post(
        title="A reasonable enough title for testing",
        body="x" * 150,
        sub_rules={"flair_required": True},
    )
    assert any(v.code == "flair_required" for v in missing.violations)

    bad = heuristic_check_post(
        title="A reasonable enough title for testing",
        body="x" * 150,
        sub_rules={"allowed_flairs": ["Discussion", "Question"]},
        flair_id="Spam",
    )
    assert any(v.code == "flair_invalid" for v in bad.violations)


def test_post_first_person_verb_warn_not_block() -> None:
    # A clean first-person opener: no warn.
    good = heuristic_check_post(
        title="I built a small focus tracker, here is what I learned",
        body="I built this over a weekend and learned a lot about what actually helps focus. " * 3,
    )
    assert all(v.code != "no_first_person_verb" for v in good.violations)

    # Corporate opener with no first-person verb: warn, but still passes
    # (no error-severity violations).
    corporate = heuristic_check_post(
        title="A reasonable enough title for testing here",
        body="The market for focus supplements continues to expand across many segments. " * 3,
    )
    assert any(
        v.code == "no_first_person_verb" and v.severity == "warn" for v in corporate.violations
    )
    assert corporate.pass_ is True  # warns don't block


def test_ai_tell_list_has_single_definition() -> None:
    # The reply AI-tell denylist lives in exactly one place: reddit.stylebook.
    # Both the linter (compliance) and the generator prompt import it, so the
    # two can't drift. Guard against a second hand-rolled copy reappearing.
    import metalworks.discovery.prompts as prompts
    import metalworks.reddit.compliance as compliance
    from metalworks.reddit import stylebook

    # The linter uses the shared compiled regex — same object, not a copy.
    assert compliance._AI_TELL_REGEX is stylebook.AI_TELL_REGEX  # noqa: SLF001

    # The generator prompt is built from the shared examples, and names them.
    for phrase in stylebook.AI_TELL_EXAMPLES:
        assert phrase in prompts._AI_TELLS_PROMPT  # noqa: SLF001

    # No module other than stylebook defines its own AI-tell phrase list.
    assert not hasattr(compliance, "_AI_TELLS")
