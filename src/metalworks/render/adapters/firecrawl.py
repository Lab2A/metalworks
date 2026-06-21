"""Firecrawl PageRenderer adapter (``metalworks[firecrawl]``).

A hosted screenshot — no local browser, no system libraries — so it rescues
headless / CI / serverless environments where Chromium is painful. It reuses the
same ``[firecrawl]`` extra and ``FIRECRAWL_API_KEY`` as
:class:`~metalworks.search.adapters.firecrawl.FirecrawlSearch`.

Integration approach — **httpx against the REST endpoint**, like the search
adapter. We POST ``/v2/scrape`` asking for the ``screenshot`` + ``html`` formats;
the ``firecrawl`` package is lazy-imported in ``__init__`` only to gate the extra.

REST reference (Firecrawl ``/v2/scrape``, verified 2026-06):
``POST https://api.firecrawl.dev/v2/scrape`` with a ``Bearer`` token and body
``{"url": ..., "formats": ["screenshot", "html"]}`` (``"screenshot@fullPage"``
for a full-page capture). The response is ``{"data": {"screenshot": <url|base64>,
"html": ..., "metadata": {"title", "url", "sourceURL", "statusCode"}}}``. The
``screenshot`` field is a hosted URL by default (we fetch it for bytes) or a
``data:``/base64 string on some plans (we decode it).

Screenshot-only: ``supports_style_audit`` is ``False`` — a style audit raises
:class:`~metalworks.errors.StyleAuditUnsupported` (it cannot run page scripts).
"""

from __future__ import annotations

import base64
import importlib
import os
from collections.abc import Sequence
from typing import Any, ClassVar

import httpx

from metalworks.errors import MissingExtraError, MissingKeyError, StyleAuditUnsupported
from metalworks.render import (
    PROTOCOL_VERSION,
    ComputedStyle,
    RenderedPage,
    RendererCapabilities,
)

_ENDPOINT = "https://api.firecrawl.dev/v2/scrape"
_TIMEOUT_S = 60.0  # a scrape+screenshot round trip is slower than a search


class FirecrawlRenderer:
    """PageRenderer over the Firecrawl ``/v2/scrape`` screenshot API (no local browser)."""

    protocol_version: ClassVar[str] = PROTOCOL_VERSION
    renderer_id: str = "firecrawl"
    capabilities: RendererCapabilities = RendererCapabilities(supports_style_audit=False)

    def __init__(self, *, api_key: str | None = None) -> None:
        # Gate the `firecrawl` extra; we call the REST endpoint over httpx.
        try:
            importlib.import_module("firecrawl")
        except ImportError as exc:
            raise MissingExtraError("firecrawl", package="firecrawl-py") from exc
        key = api_key or os.environ.get("FIRECRAWL_API_KEY")
        if not key:
            raise MissingKeyError("FIRECRAWL_API_KEY", provider="Firecrawl")
        self._api_key: str = key

    def render(
        self,
        url: str,
        *,
        viewport: tuple[int, int] = (1280, 800),
        full_page: bool = False,
        timeout_s: float = 15.0,
    ) -> RenderedPage:
        shot_format = "screenshot@fullPage" if full_page else "screenshot"
        body: dict[str, Any] = {"url": url, "formats": [shot_format, "html"]}
        headers = {
            "authorization": f"Bearer {self._api_key}",
            "content-type": "application/json",
        }
        response = httpx.post(_ENDPOINT, json=body, headers=headers, timeout=_TIMEOUT_S)
        response.raise_for_status()
        payload: dict[str, Any] = response.json() or {}
        data: dict[str, Any] = payload.get("data") or {}
        meta: dict[str, Any] = data.get("metadata") or {}
        return RenderedPage(
            url=url,
            final_url=str(meta.get("url") or meta.get("sourceURL") or url),
            screenshot=self._screenshot_bytes(data.get("screenshot")),
            html=str(data.get("html") or ""),
            title=str(meta.get("title") or ""),
        )

    def extract_computed_styles(
        self,
        url: str,
        selectors: Sequence[str],
        *,
        timeout_s: float = 15.0,
    ) -> list[ComputedStyle]:
        # Firecrawl returns a rendered screenshot but no way to read back
        # arbitrary getComputedStyle results — so a style audit is unsupported.
        raise StyleAuditUnsupported(self.renderer_id)

    @staticmethod
    def _screenshot_bytes(shot: Any) -> bytes:
        """Resolve Firecrawl's ``screenshot`` field (a URL or a base64 string) to bytes."""
        if not isinstance(shot, str) or not shot:
            return b""
        if shot.startswith("http://") or shot.startswith("https://"):
            resp = httpx.get(shot, timeout=_TIMEOUT_S)
            resp.raise_for_status()
            return resp.content
        b64 = shot.split(",", 1)[1] if shot.startswith("data:") else shot
        try:
            return base64.b64decode(b64)
        except ValueError:  # binascii.Error is a ValueError subclass
            return b""
