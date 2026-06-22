"""Logo mark submodule: SVG extraction + safety, diversity, partials, parity.

Offline. FakeChatModel returns a scripted SVG (or not) per angle, so the
five-angle sweep, the drop-and-mark-partial honesty, the SVG SAFETY gate (a
<script>/handler SVG is dropped, never inlined), and the picker render all run
for real. No network, no keys.
"""

from __future__ import annotations

from datetime import UTC, datetime

from metalworks.contract import DesignChoice, DesignSystem
from metalworks.llm import FakeChatModel
from metalworks.research.logo import (
    _extract_svg,
    build_logo_set,
    render_logo_picker_html,
)

_VALID = '<svg viewBox="0 0 320 200"><circle r="22"/><text>Cadence</text></svg>'
_UNSAFE = '<svg viewBox="0 0 320 200"><script>fetch("//x")</script><circle/></svg>'
_UNSAFE_HANDLER = '<svg viewBox="0 0 320 200"><circle onload="alert(1)"/></svg>'
_NO_SVG = "Sorry — I could not produce a mark for that brief."


def _system() -> DesignSystem:
    return DesignSystem(
        report_id="rpt-1",
        brand_name="Cadence",
        memorable_thing="the focus app that whispers",
        grounding_tier="web",
        aesthetic="editorial monochrome, dark-first",
        choices=[
            DesignChoice(
                dimension="typography",
                decision="Fraunces display + Geist body",
                stance="risk",
                rationale="serif display breaks the category's sans default",
            ),
            DesignChoice(
                dimension="color",
                decision="ink #1A1A1A, accent #C2410C, cream ground",
                stance="safe",
                rationale="restrained two-color ink+accent",
            ),
        ],
        generated_at=datetime(2026, 2, 1, tzinfo=UTC),
    )


def _chat(responses: list[str]) -> FakeChatModel:
    chat = FakeChatModel()
    chat.text_responses = list(responses)
    return chat


# ── extraction + safety ───────────────────────────────────────────────────────


def test_extract_svg_valid() -> None:
    assert _extract_svg(f"here you go:\n{_VALID}\nenjoy") == _VALID


def test_extract_svg_rejects_unsafe() -> None:
    assert _extract_svg(_UNSAFE) is None  # <script> dropped
    assert _extract_svg(_UNSAFE_HANDLER) is None  # onload= handler dropped
    assert _extract_svg("no svg here") is None


# ── the set ───────────────────────────────────────────────────────────────────


def test_all_angles_land() -> None:
    logos = build_logo_set(_chat([_VALID] * 5), _system())
    assert len(logos.options) == 5
    assert not logos.partial
    assert logos.brand_name == "Cadence"
    assert {o.angle for o in logos.options} == {
        "symbol",
        "logotype",
        "negative-space",
        "reference",
        "expressive",
    }


def test_missing_svg_drops_angle_partial() -> None:
    logos = build_logo_set(_chat([_VALID, _NO_SVG, _VALID, _VALID, _VALID]), _system())
    assert len(logos.options) == 4
    assert logos.partial and logos.caveat and "dropped" in logos.caveat


def test_unsafe_svg_is_dropped_not_inlined() -> None:
    logos = build_logo_set(_chat([_VALID, _UNSAFE, _VALID, _VALID, _VALID]), _system())
    assert len(logos.options) == 4  # the unsafe angle is dropped
    assert logos.partial
    assert all("<script" not in o.svg for o in logos.options)


def test_no_options_caveat() -> None:
    logos = build_logo_set(_chat([_NO_SVG] * 5), _system())
    assert logos.options == []
    assert logos.partial and logos.caveat and "No angle" in logos.caveat


def test_picker_renders_safe() -> None:
    logos = build_logo_set(_chat([_VALID, _UNSAFE, _VALID, _VALID, _VALID]), _system())
    html = render_logo_picker_html(logos)
    assert html.startswith("<!doctype html>")
    assert "Cadence" in html
    assert "<script" not in html  # the unsafe SVG never reached the page


# ── four-surface parity ───────────────────────────────────────────────────────


def test_logo_wired_on_all_surfaces() -> None:
    import importlib.util

    from typer.testing import CliRunner

    from metalworks import Metalworks
    from metalworks.cli import app

    assert hasattr(Metalworks, "logo") and hasattr(Metalworks, "render_logo_picker")
    result = CliRunner().invoke(app, ["research", "logo", "--help"])
    assert result.exit_code == 0
    if importlib.util.find_spec("mcp") is not None:
        from metalworks.mcp import server, tools

        attr = "_TOOL_WRAPPERS"  # variable, not a literal, to dodge the B009/SLF001 ruff pair
        names = {getattr(w, "__name__", "") for w in getattr(server, attr)}
        assert "logo_generate" in names
        assert hasattr(tools, "logo_generate")
