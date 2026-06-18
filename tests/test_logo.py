"""Logo generation — five diverse SVG options per report, the model authoring SVG.

Offline. FakeChatModel.text_responses is the FIFO queue complete_text drains, so
each design angle pops one scripted SVG. No network, no keys.
"""

from __future__ import annotations

from datetime import UTC, datetime

from metalworks.contract import DemandReport, Fork, LogoOption, LogoSet
from metalworks.llm import FakeChatModel
from metalworks.research.logo import (
    ANGLES,
    _extract_svg,
    build_logo_set,
    render_logo_picker_html,
)


def _report() -> DemandReport:
    now = datetime(2026, 2, 1, tzinfo=UTC)
    return DemandReport(
        report_id="rpt-1",
        query="a tool that turns Reddit demand into validated SaaS ideas",
        fork=Fork.PRODUCT_PINNED,
        pinned_axis="product",
        optimized_axis="audience",
        date_range_start=now,
        date_range_end=now,
        total_threads=10,
        total_distinct_authors=9,
        ranked_clusters=[],
        generated_at=now,
    )


def _svg(tag: str) -> str:
    return f'<svg viewBox="0 0 320 200"><title>{tag}</title></svg>'


def test_extract_svg_pulls_first_svg() -> None:
    assert _extract_svg("blah " + _svg("a") + " trailing") == _svg("a")
    assert _extract_svg("no svg here") is None


def test_build_logo_set_returns_five_options() -> None:
    chat = FakeChatModel()
    chat.text_responses = [_svg(f"o{i}") for i in range(len(ANGLES))]
    logos = build_logo_set(chat, _report(), brand_name="Acme")

    assert isinstance(logos, LogoSet)
    assert logos.brand_name == "Acme"
    assert len(logos.options) == len(ANGLES) == 5
    assert logos.partial is False
    assert {o.angle for o in logos.options} == {key for key, _ in ANGLES}
    assert all(o.svg.startswith("<svg") for o in logos.options)
    # brand name supplied -> no extra naming call, one call per angle
    assert sum(1 for c in chat.calls if c["kind"] == "text") == len(ANGLES)


def test_partial_when_an_angle_returns_no_svg() -> None:
    chat = FakeChatModel()
    resp = [_svg(f"o{i}") for i in range(len(ANGLES))]
    resp[2] = "the model rambled and drew nothing"
    chat.text_responses = resp
    logos = build_logo_set(chat, _report(), brand_name="Acme")

    assert len(logos.options) == len(ANGLES) - 1
    assert logos.partial is True
    assert logos.caveat and ANGLES[2][0] in logos.caveat


def test_brand_name_generated_when_absent() -> None:
    chat = FakeChatModel()
    # first text call is the name suggestion, then one per angle
    chat.text_responses = ["Forge", *[_svg(f"o{i}") for i in range(len(ANGLES))]]
    logos = build_logo_set(chat, _report(), brand_name=None)
    assert logos.brand_name == "Forge"
    assert len(logos.options) == len(ANGLES)


def test_picker_html_lists_every_option() -> None:
    logos = LogoSet(
        report_id="rpt-1",
        brand_name="Acme",
        options=[LogoOption(angle="logotype", concept="wordmark", svg=_svg("x"))],
    )
    html = render_logo_picker_html(logos)
    assert "Acme" in html
    assert "Option 1" in html
    assert "<svg" in html
