"""Playwright PageRenderer adapter (``metalworks[browser]``).

An owned headless Chromium. Renders a URL to a screenshot + HTML and runs a
FIXED, vendored style-extraction script (``_STYLE_SCRIPT``) for computed-style
audits — so it ``supports_style_audit``. There is deliberately no caller-supplied
JavaScript on this adapter's public surface: the only script it ever runs is the
one shipped here, so an untrusted page or model output can't inject JS.

Dependency gating mirrors the search adapters: ``playwright`` is lazy-imported
inside ``__init__`` (absent → :class:`MissingExtraError`); a missing Chromium
binary → :class:`BrowserNotInstalledError`; a launch failure (commonly missing
Linux system libraries, or a stale version-mismatched binary) →
:class:`BrowserLaunchError` / :class:`BrowserNotInstalledError`. The library never
leaks a raw Playwright exception from a launch.
"""

from __future__ import annotations

import importlib
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, ClassVar

from metalworks.errors import (
    BrowserLaunchError,
    BrowserNotInstalledError,
    MissingExtraError,
)
from metalworks.render import (
    PROTOCOL_VERSION,
    ComputedStyle,
    RenderedPage,
    RendererCapabilities,
    chromium_present,
)

if TYPE_CHECKING:
    from playwright.sync_api import Page

# The one script this adapter ever runs in a page. Takes a list of selectors,
# returns one computed-style record per selector (found=false when no match).
_STYLE_SCRIPT = """(selectors) => selectors.map((sel) => {
  const el = document.querySelector(sel);
  if (!el) return { selector: sel, found: false };
  const cs = getComputedStyle(el);
  return {
    selector: sel, found: true,
    font_family: cs.fontFamily, font_size: cs.fontSize, font_weight: cs.fontWeight,
    color: cs.color, background_color: cs.backgroundColor,
  };
})"""


def _launch_error(exc: Exception) -> BrowserNotInstalledError | BrowserLaunchError:
    """Map a Playwright launch failure to a typed metalworks error."""
    first = str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__
    low = str(exc).lower()
    if "executable doesn't exist" in low or "playwright install" in low:
        return BrowserNotInstalledError(detail=first)
    return BrowserLaunchError(detail=first)


class PlaywrightRenderer:
    """PageRenderer over an owned headless Chromium (``metalworks[browser]``)."""

    protocol_version: ClassVar[str] = PROTOCOL_VERSION
    renderer_id: str = "playwright"
    capabilities: RendererCapabilities = RendererCapabilities(supports_style_audit=True)

    def __init__(self, *, headless: bool = True) -> None:
        # Gate the `browser` extra (lazy import, like the search adapters).
        try:
            importlib.import_module("playwright.sync_api")
        except ImportError as exc:
            raise MissingExtraError("browser", package="playwright") from exc
        # Cheap, launch-free probe so construction fails fast with the right fix
        # before any page is rendered.
        if not chromium_present():
            raise BrowserNotInstalledError()
        self._headless = headless

    @contextmanager
    def _page(
        self, url: str, *, viewport: tuple[int, int], timeout_s: float
    ) -> Generator[Page, None, None]:
        """Launch Chromium, open ``url``, yield the page, always tear the browser down."""
        from playwright.sync_api import Error as PWError
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=self._headless)
            except PWError as exc:
                raise _launch_error(exc) from exc
            try:
                context = browser.new_context(
                    viewport={"width": viewport[0], "height": viewport[1]}
                )
                page = context.new_page()
                page.goto(url, timeout=int(timeout_s * 1000), wait_until="load")
                yield page
            finally:
                browser.close()

    def render(
        self,
        url: str,
        *,
        viewport: tuple[int, int] = (1280, 800),
        full_page: bool = False,
        timeout_s: float = 15.0,
    ) -> RenderedPage:
        with self._page(url, viewport=viewport, timeout_s=timeout_s) as page:
            shot = page.screenshot(full_page=full_page)
            return RenderedPage(
                url=url,
                final_url=page.url,
                screenshot=shot,
                html=page.content(),
                title=page.title(),
            )

    def extract_computed_styles(
        self,
        url: str,
        selectors: Sequence[str],
        *,
        timeout_s: float = 15.0,
    ) -> list[ComputedStyle]:
        sels = list(selectors)
        with self._page(url, viewport=(1280, 800), timeout_s=timeout_s) as page:
            rows: list[dict[str, Any]] = page.evaluate(_STYLE_SCRIPT, sels)
        out: list[ComputedStyle] = []
        for row in rows:
            out.append(
                ComputedStyle(
                    selector=str(row.get("selector", "")),
                    found=bool(row.get("found", False)),
                    font_family=str(row.get("font_family", "") or ""),
                    font_size=str(row.get("font_size", "") or ""),
                    font_weight=str(row.get("font_weight", "") or ""),
                    color=str(row.get("color", "") or ""),
                    background_color=str(row.get("background_color", "") or ""),
                )
            )
        return out
