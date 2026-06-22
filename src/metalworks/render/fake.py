"""FakeRenderer — a deterministic :class:`PageRenderer` for offline tests.

Ships in core (no extra): returns a real 1x1 PNG so consumers that sniff the
screenshot see valid PNG magic bytes, plus canned HTML and computed styles, with
no browser and no network. Drives the design teardown / style-audit code paths in
the offline suite exactly like ``FakeChatModel`` / ``FakeEmbedding`` do.
"""

from __future__ import annotations

import base64
from collections.abc import Sequence
from typing import ClassVar

from metalworks.render import (
    PROTOCOL_VERSION,
    ComputedStyle,
    RenderedPage,
    RendererCapabilities,
)

# A minimal valid 1x1 transparent PNG — magic bytes intact (\x89PNG\r\n\x1a\n).
_PNG_1x1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "+P+/HgAFhAJ/wlseKgAAAABJRU5ErkJggg=="
)


class FakeRenderer:
    """Deterministic renderer for tests: a real-PNG screenshot + canned HTML/styles."""

    protocol_version: ClassVar[str] = PROTOCOL_VERSION
    renderer_id: str = "fake"
    capabilities: RendererCapabilities = RendererCapabilities(supports_style_audit=True)

    def __init__(
        self,
        *,
        html: str = "<html><head><title>Fake</title></head><body><h1>Fake</h1></body></html>",
        font_family: str = "Georgia, serif",
    ) -> None:
        self._html = html
        self._font_family = font_family

    def render(
        self,
        url: str,
        *,
        viewport: tuple[int, int] = (1280, 800),
        full_page: bool = False,
        timeout_s: float = 15.0,
    ) -> RenderedPage:
        return RenderedPage(
            url=url, final_url=url, screenshot=_PNG_1x1, html=self._html, title="Fake"
        )

    def extract_computed_styles(
        self,
        url: str,
        selectors: Sequence[str],
        *,
        timeout_s: float = 15.0,
    ) -> list[ComputedStyle]:
        return [
            ComputedStyle(
                selector=sel,
                found=True,
                font_family=self._font_family,
                font_size="16px",
                font_weight="400",
                color="rgb(0, 0, 0)",
                background_color="rgba(0, 0, 0, 0)",
            )
            for sel in selectors
        ]
