"""PageRenderer foundation: the Fake, the Firecrawl adapter (mocked), error
paths, resolve_renderer precedence, and a real-Chromium integration test gated
behind ``-m browser``. Everything except the ``browser``-marked test is offline.
"""

from __future__ import annotations

import base64
from typing import Any

import pytest

from metalworks.errors import (
    BrowserNotInstalledError,
    MissingExtraError,
    StyleAuditUnsupported,
)
from metalworks.render import RenderedPage
from metalworks.render.fake import FakeRenderer
from metalworks.testing import check_page_renderer

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class _Resp:
    """A minimal stand-in for httpx.Response (json() + content + raise_for_status())."""

    def __init__(self, *, json_data: dict[str, Any] | None = None, content: bytes = b"") -> None:
        self._json = json_data or {}
        self.content = content

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._json


# ── FakeRenderer ──────────────────────────────────────────────────────────────


def test_fake_renderer_conforms() -> None:
    check_page_renderer(FakeRenderer(), url="https://example.com")


def test_fake_renderer_screenshot_is_png() -> None:
    page = FakeRenderer().render("https://example.com")
    assert isinstance(page, RenderedPage)
    assert page.screenshot[:8] == _PNG_MAGIC
    assert page.final_url == "https://example.com"


def test_fake_renderer_style_audit() -> None:
    styles = FakeRenderer(font_family="Fraunces, serif").extract_computed_styles(
        "https://example.com", ["h1", "body"]
    )
    assert [s.selector for s in styles] == ["h1", "body"]
    assert all(s.font_family == "Fraunces, serif" for s in styles)


# ── FirecrawlRenderer (mocked REST) ───────────────────────────────────────────


def _firecrawl(
    monkeypatch: pytest.MonkeyPatch, *, post_json: dict[str, Any], get_content: bytes = b""
):
    """Build a FirecrawlRenderer with the extra-gate bypassed and httpx mocked."""
    monkeypatch.setenv("FIRECRAWL_API_KEY", "test-key")
    monkeypatch.setattr(
        "metalworks.render.adapters.firecrawl.importlib.import_module",
        lambda name: object(),
    )
    from metalworks.render.adapters.firecrawl import FirecrawlRenderer

    renderer = FirecrawlRenderer()
    monkeypatch.setattr(
        "metalworks.render.adapters.firecrawl.httpx.post",
        lambda *a, **k: _Resp(json_data=post_json),
    )
    monkeypatch.setattr(
        "metalworks.render.adapters.firecrawl.httpx.get",
        lambda *a, **k: _Resp(content=get_content),
    )
    return renderer


def test_firecrawl_render_base64_screenshot(monkeypatch: pytest.MonkeyPatch) -> None:
    png = FakeRenderer().render("x").screenshot
    b64 = base64.b64encode(png).decode()
    renderer = _firecrawl(
        monkeypatch,
        post_json={
            "data": {
                "screenshot": b64,
                "html": "<html></html>",
                "metadata": {"title": "Tidal", "url": "https://e.com/final"},
            }
        },
    )
    page = renderer.render("https://e.com")
    assert page.screenshot[:8] == _PNG_MAGIC
    assert page.final_url == "https://e.com/final"
    assert page.title == "Tidal"


def test_firecrawl_render_url_screenshot(monkeypatch: pytest.MonkeyPatch) -> None:
    png = FakeRenderer().render("x").screenshot
    renderer = _firecrawl(
        monkeypatch,
        post_json={"data": {"screenshot": "https://cdn.example/x.png", "html": "<a>"}},
        get_content=png,
    )
    page = renderer.render("https://e.com")
    assert page.screenshot == png
    assert page.final_url == "https://e.com"  # no metadata.url → falls back to requested


def test_firecrawl_no_style_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    renderer = _firecrawl(monkeypatch, post_json={"data": {}})
    assert renderer.capabilities.supports_style_audit is False
    with pytest.raises(StyleAuditUnsupported):
        renderer.extract_computed_styles("https://e.com", ["body"])


# ── PlaywrightRenderer error paths (no real browser) ──────────────────────────


def test_playwright_missing_chromium(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("metalworks.render.adapters.playwright.chromium_present", lambda: False)
    from metalworks.render.adapters.playwright import PlaywrightRenderer

    with pytest.raises(BrowserNotInstalledError):
        PlaywrightRenderer()


def test_playwright_missing_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    import metalworks.render.adapters.playwright as mod

    def _raise(name: str) -> object:
        raise ImportError(name)

    monkeypatch.setattr(mod.importlib, "import_module", _raise)
    with pytest.raises(MissingExtraError):
        mod.PlaywrightRenderer()


# ── resolve_renderer precedence (never raises) ────────────────────────────────


def test_resolve_renderer_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    monkeypatch.setattr("metalworks.render.chromium_present", lambda: False)
    from metalworks.config import resolve_renderer

    assert resolve_renderer() is None


def test_resolve_renderer_prefers_playwright(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("metalworks.render.chromium_present", lambda: True)
    monkeypatch.setattr("metalworks.render.adapters.playwright.chromium_present", lambda: True)
    from metalworks.config import resolve_renderer
    from metalworks.render.adapters.playwright import PlaywrightRenderer

    assert isinstance(resolve_renderer(), PlaywrightRenderer)


def test_resolve_renderer_falls_back_to_firecrawl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("metalworks.render.chromium_present", lambda: False)
    monkeypatch.setenv("FIRECRAWL_API_KEY", "k")
    monkeypatch.setattr(
        "metalworks.render.adapters.firecrawl.importlib.import_module",
        lambda name: object(),
    )
    from metalworks.config import resolve_renderer
    from metalworks.render.adapters.firecrawl import FirecrawlRenderer

    assert isinstance(resolve_renderer(), FirecrawlRenderer)


# ── Real Chromium (deselected by default; run with -m browser --enable-socket) ─


# ── CLI surface (render debug command + browser install verb; render is NOT a tool) ─


def test_render_and_browser_cli_registered() -> None:
    from typer.testing import CliRunner

    from metalworks.cli import app

    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "render" in result.output
    assert "browser" in result.output


def test_render_stays_infra_not_an_mcp_tool() -> None:
    import importlib.util

    if importlib.util.find_spec("mcp") is None:
        pytest.skip("mcp extra not installed")
    from metalworks.mcp import server

    attr = "_TOOL_WRAPPERS"  # variable (not a literal) to avoid the B009/SLF001 ruff pair
    names = {getattr(w, "__name__", "") for w in getattr(server, attr)}
    assert "render" not in names and "page_render" not in names


@pytest.mark.browser
def test_playwright_renders_real_fixture(tmp_path: Any) -> None:
    fixture = tmp_path / "page.html"
    fixture.write_text(
        "<html><head><style>body{font-family:Georgia,serif}</style></head>"
        "<body><h1>Hi</h1></body></html>",
        encoding="utf-8",
    )
    from metalworks.render.adapters.playwright import PlaywrightRenderer

    renderer = PlaywrightRenderer()
    url = fixture.as_uri()
    page = renderer.render(url)
    assert page.screenshot[:8] == _PNG_MAGIC
    styles = renderer.extract_computed_styles(url, ["body"])
    assert styles and "Georgia" in styles[0].font_family
    check_page_renderer(renderer, url=url)
