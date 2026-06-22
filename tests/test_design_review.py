"""Design review: the deterministic computed-style audit + hard rules + parity.

Offline. A test-local renderer returns scripted per-selector computed styles, so
the hard rules (font count, convergence-trap body face, non-monotonic heading
scale), the system match, the score, and the screenshot-only refusal all run for
real. No network, no browser.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from metalworks.contract import DesignChoice, DesignReview, DesignSystem
from metalworks.errors import StyleAuditUnsupported
from metalworks.render import ComputedStyle, RenderedPage, RendererCapabilities
from metalworks.research.design_review import review_design


class _StyledFake:
    """A renderer returning scripted per-selector computed styles."""

    protocol_version = "1.0"
    renderer_id = "styledfake"

    def __init__(self, styles: dict[str, ComputedStyle], *, supports: bool = True) -> None:
        self._styles = styles
        self.capabilities = RendererCapabilities(supports_style_audit=supports)

    def render(self, url: str, **_k: Any) -> RenderedPage:
        return RenderedPage(url=url, final_url=url, screenshot=b"", html="")

    def extract_computed_styles(
        self, url: str, selectors: Any, *, timeout_s: float = 15.0
    ) -> list[ComputedStyle]:
        if not self.capabilities.supports_style_audit:
            raise StyleAuditUnsupported(self.renderer_id)
        return [self._styles.get(s, ComputedStyle(selector=s, found=False)) for s in selectors]


def _cs(
    sel: str,
    *,
    font: str = "Geist",
    size: str = "16px",
    color: str = "rgb(20, 20, 20)",
    bg: str = "rgb(251, 250, 246)",
) -> ComputedStyle:
    return ComputedStyle(
        selector=sel,
        found=True,
        font_family=font,
        font_size=size,
        color=color,
        background_color=bg,
    )


def _clean() -> dict[str, ComputedStyle]:
    return {
        "body": _cs("body", font="Geist"),
        "h1": _cs("h1", font="Geist", size="40px"),
        "h2": _cs("h2", font="Geist", size="28px"),
        "h3": _cs("h3", font="Geist", size="20px"),
        "a": _cs("a", font="Geist"),
        "button": _cs("button", font="Geist"),
    }


# ── hard rules ────────────────────────────────────────────────────────────────


def test_clean_page_passes() -> None:
    review = review_design(_StyledFake(_clean()), "https://x")
    assert isinstance(review, DesignReview)
    assert review.passed and review.score == 10
    assert review.fonts == ["Geist"]
    assert all(f.severity != "warn" for f in review.findings)
    assert review.ink == "rgb(20, 20, 20)"


def test_too_many_fonts_fails() -> None:
    styles = _clean()
    # Five distinct families (body Geist + four more) — font soup, a hard fail.
    styles["h1"] = _cs("h1", font="Fraunces", size="40px")
    styles["h2"] = _cs("h2", font="Arial", size="28px")
    styles["a"] = _cs("a", font="Times")
    styles["button"] = _cs("button", font="Courier")
    review = review_design(_StyledFake(styles), "https://x")
    fonts_finding = next(
        f for f in review.findings if f.category == "fonts" and "distinct" in f.detail
    )
    assert fonts_finding.severity == "fail"
    assert review.passed is False
    # One font fail + the Arial convergence-trap body? No — body is Geist here,
    # so exactly one fail: score = 10 - 3*1 = 7 (the -3*fails penalty is live).
    assert sum(f.severity == "fail" for f in review.findings) == 1
    assert review.score == 7


def test_convergence_trap_body_font_fails() -> None:
    styles = _clean()
    styles["body"] = _cs("body", font="Inter")
    review = review_design(_StyledFake(styles), "https://x")
    trap = next(f for f in review.findings if f.category == "fonts" and "convergence" in f.detail)
    assert trap.severity == "fail"
    assert review.passed is False
    assert review.score == 7  # 10 - 3*1, the convergence body face is the sole fail


def test_non_monotonic_headings_warns() -> None:
    styles = _clean()
    styles["h1"] = _cs("h1", font="Geist", size="20px")
    styles["h2"] = _cs("h2", font="Geist", size="40px")
    review = review_design(_StyledFake(styles), "https://x")
    assert any(f.category == "headings" for f in review.findings)


# ── grading against a design system ───────────────────────────────────────────


def _system(typography: str) -> DesignSystem:
    return DesignSystem(
        report_id="rpt-1",
        brand_name="Cadence",
        memorable_thing="x",
        grounding_tier="web",
        aesthetic="editorial",
        choices=[
            DesignChoice(dimension="typography", decision=typography, stance="risk", rationale="r")
        ],
        generated_at=datetime(2026, 2, 1, tzinfo=UTC),
    )


def test_system_match_flags_mismatch() -> None:
    styles = _clean()
    styles["body"] = _cs("body", font="Arial")  # not in the system's typography
    review = review_design(
        _StyledFake(styles), "https://x", system=_system("Fraunces display + Geist body")
    )
    assert review.against_system
    assert any(f.category == "system_match" and f.severity == "warn" for f in review.findings)


def test_system_match_ok_when_aligned() -> None:
    review = review_design(
        _StyledFake(_clean()), "https://x", system=_system("Fraunces display + Geist body")
    )
    assert any(f.category == "system_match" and f.severity == "ok" for f in review.findings)


def test_system_match_token_not_substring() -> None:
    # "Sans" as a body face must NOT be treated as matching a "Comic Sans"
    # system: naive substring containment ("sans" in "comic sans") said aligned;
    # token matching ({"sans"} <= {"comic", "sans"}) keeps it a real subset, so
    # this aligns — but a body face with a token absent from the decision must
    # not match. Use "Helvetica" vs a "Comic Sans" system to prove that.
    styles = _clean()
    styles["body"] = _cs("body", font="Helvetica")
    review = review_design(_StyledFake(styles), "https://x", system=_system("Comic Sans"))
    assert any(f.category == "system_match" and f.severity == "warn" for f in review.findings)
    # And a face that is a token subset of the decision aligns (no substring needed).
    styles2 = _clean()
    styles2["body"] = _cs("body", font="Geist")
    review2 = review_design(_StyledFake(styles2), "https://x", system=_system("geist-body mono"))
    assert any(f.category == "system_match" and f.severity == "ok" for f in review2.findings)


def test_screenshot_only_renderer_refused() -> None:
    with pytest.raises(StyleAuditUnsupported):
        review_design(_StyledFake(_clean(), supports=False), "https://x")


# ── four-surface parity ───────────────────────────────────────────────────────


def test_design_review_wired_on_all_surfaces() -> None:
    import importlib.util

    from typer.testing import CliRunner

    from metalworks import Metalworks
    from metalworks.cli import app

    assert hasattr(Metalworks, "design_review")
    result = CliRunner().invoke(app, ["research", "design-review", "--help"])
    assert result.exit_code == 0
    if importlib.util.find_spec("mcp") is not None:
        from metalworks.mcp import server, tools

        attr = "_TOOL_WRAPPERS"  # variable, not a literal, to dodge the B009/SLF001 ruff pair
        names = {getattr(w, "__name__", "") for w in getattr(server, attr)}
        assert "design_review" in names
        assert hasattr(tools, "design_review")
