"""Page rendering — screenshot + structured style extraction over a real page.

A :class:`PageRenderer` turns a URL into a :class:`RenderedPage` (a screenshot
plus the resolved HTML) and, when the backend supports it, extracts computed
styles for a fixed set of selectors. It is INFRASTRUCTURE, like
:class:`~metalworks.search.SearchProvider` /
:class:`~metalworks.embeddings.EmbeddingProvider`: a swappable protocol with
adapters behind extras and a deterministic fake, wired through
:func:`metalworks.config.resolve_renderer` and surfaced via ``doctor`` — never a
user-facing four-surface primitive. Pillars (the design teardown, a future
landscape / deploy check) consume it.

Two adapters, two tiers of capability:

* **Playwright** (``metalworks[browser]``, an owned headless Chromium) renders
  AND runs a fixed, vendored style-extraction script — ``supports_style_audit``
  is ``True``.
* **Firecrawl** (``metalworks[firecrawl]``, a hosted REST screenshot) renders
  only — ``supports_style_audit`` is ``False``; a style audit raises
  :class:`~metalworks.errors.StyleAuditUnsupported`.

Security: the protocol deliberately exposes NO caller-supplied JavaScript. Style
extraction runs a fixed script the library ships; an arbitrary ``evaluate`` escape
hatch (if any) lives on the concrete Playwright adapter, never on this
cross-adapter surface — so an untrusted page or model output can never inject JS
through the protocol.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Protocol, runtime_checkable

PROTOCOL_VERSION = "1.0"


@dataclass(frozen=True)
class RendererCapabilities:
    """What a renderer backend can do. Consumers branch on this, never on type."""

    supports_style_audit: bool = False


@dataclass(frozen=True)
class ComputedStyle:
    """The computed style facts for one matched element (one CSS selector)."""

    selector: str
    found: bool = True
    font_family: str = ""
    font_size: str = ""
    font_weight: str = ""
    color: str = ""
    background_color: str = ""


@dataclass(frozen=True)
class RenderedPage:
    """The result of rendering one URL."""

    url: str  # the URL requested
    final_url: str  # after redirects
    screenshot: bytes  # PNG bytes (may be empty when the backend couldn't capture)
    html: str  # the resolved DOM HTML
    title: str = ""


@runtime_checkable
class PageRenderer(Protocol):
    """Render a URL to a screenshot + HTML; optionally extract computed styles.

    Adapters live behind extras (``metalworks[browser]`` / ``[firecrawl]``). The
    protocol exposes no arbitrary-JS escape hatch by design (see module docstring).
    """

    protocol_version: ClassVar[str]
    renderer_id: str
    capabilities: RendererCapabilities

    def render(
        self,
        url: str,
        *,
        viewport: tuple[int, int] = (1280, 800),
        full_page: bool = False,
        timeout_s: float = 15.0,
    ) -> RenderedPage: ...

    # Computed styles for each selector. Raises StyleAuditUnsupported when
    # ``capabilities.supports_style_audit`` is False (screenshot-only backends).
    def extract_computed_styles(
        self,
        url: str,
        selectors: Sequence[str],
        *,
        timeout_s: float = 15.0,
    ) -> list[ComputedStyle]: ...


def _browsers_root() -> Path:
    """The directory Playwright caches its browser binaries in, per platform.

    Honors ``PLAYWRIGHT_BROWSERS_PATH`` (the documented override); ``"0"`` means
    "next to the package", which we cannot cheaply probe, so we fall through to
    the platform default and let a launch attempt be the source of truth there.
    """
    env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if env and env != "0":
        return Path(env)
    home = Path.home()
    platform: str = sys.platform  # explicit str: don't let pyright narrow to the host literal
    if platform == "darwin":
        return home / "Library" / "Caches" / "ms-playwright"
    if platform.startswith("win"):
        return home / "AppData" / "Local" / "ms-playwright"
    return home / ".cache" / "ms-playwright"


def chromium_present() -> bool:
    """Best-effort, launch-free probe for an installed Chromium build.

    A filesystem glob of the Playwright cache — cheap enough for ``doctor`` and
    :func:`metalworks.config.resolve_renderer` to call without starting a browser.
    Never raises (a probe failure reads as "not present"). It can be optimistic
    (a stale, version-mismatched dir exists) — :class:`PlaywrightRenderer.render`
    is the backstop that maps a launch failure to a typed error.
    """
    try:
        root = _browsers_root()
        if not root.is_dir():
            return False
        return any(any(root.glob(pat)) for pat in ("chromium-*", "chromium_headless_shell-*"))
    except Exception:
        return False


__all__ = [
    "PROTOCOL_VERSION",
    "ComputedStyle",
    "PageRenderer",
    "RenderedPage",
    "RendererCapabilities",
    "chromium_present",
]
