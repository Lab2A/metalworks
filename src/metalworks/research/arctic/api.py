"""Rate-limited HTTP client for the public Arctic Shift API.

Ported from clique-research-api's ``arctic_shift_api.py``. The endpoint at
``arctic-shift.photon-reddit.com`` serves CURRENT comments — including the
present month — which the ``open-index/arctic`` HF mirror does not (its comment
tree stops at 2021-04). Submissions come from the Parquet mirror via
:class:`~metalworks.research.arctic.reader.ArcticReader`; comments come from
here.

Implements the :class:`metalworks.research.deps.CommentSource` protocol.

Port changes vs. the source:

- After ``max_retries`` exhausted on 429, raise
  :class:`~metalworks.errors.RateLimitedError` (the source looped silently).
- ``comments_for_links`` keeps per-link error handling but ACCUMULATES failures
  (``skipped`` count + ``errors`` strings) so the hydration caller can populate
  ``HydrationResult.skipped`` / ``.errors`` instead of silently yielding ``[]``.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator, Sequence
from typing import Any, cast

import httpx

from metalworks.errors import RateLimitedError

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://arctic-shift.photon-reddit.com/api"
DEFAULT_MIN_INTERVAL = 1.0 / 1.5  # ~1.5 req/sec sustained
DEFAULT_TIMEOUT_S = 30.0
DEFAULT_MAX_RETRIES = 4


class ArcticShiftApiError(Exception):
    """Non-retryable API error (4xx other than 429)."""


def _flatten_listing(nodes: Any, out: list[dict[str, Any]]) -> None:
    """Walk Reddit's nested Listing shape into a flat list of comment dicts.

    Tree shape from the API::

        [{"kind":"t1","data":{...,"replies": "" | {"kind":"Listing",...}}}, …]
    """
    if not nodes:
        return
    seq: list[Any] = cast("list[Any]", nodes) if isinstance(nodes, list) else []
    for node in seq:
        if not isinstance(node, dict):
            continue
        node_d = cast("dict[str, Any]", node)
        kind: Any = node_d.get("kind")
        data: Any = node_d.get("data")
        if not isinstance(data, dict):
            continue
        data_d = cast("dict[str, Any]", data)
        if kind == "t1":
            # Pop replies so callers don't accidentally serialize the subtree.
            replies: Any = data_d.pop("replies", None)
            out.append(data_d)
            if isinstance(replies, dict):
                replies_d = cast("dict[str, Any]", replies)
                child_data: Any = replies_d.get("data", {})
                child_data_d: dict[str, Any] = (
                    cast("dict[str, Any]", child_data) if isinstance(child_data, dict) else {}
                )
                _flatten_listing(child_data_d.get("children", []), out)
        elif kind == "Listing":
            _flatten_listing(data_d.get("children", []), out)


class ArcticShiftApiClient:
    """Rate-limited HTTP client for the public Arctic Shift API.

    Thread-safe — the inter-call gate uses a lock so concurrent callers share
    the same rate budget. After ``comments_for_links`` returns, inspect
    ``last_skipped`` / ``last_errors`` for per-link failures.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        min_interval: float | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        max_retries: int = DEFAULT_MAX_RETRIES,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.min_interval = min_interval if min_interval is not None else DEFAULT_MIN_INTERVAL
        self.max_retries = max_retries
        self._lock = threading.Lock()
        self._last_request_at = 0.0
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=timeout_s,
            headers={"User-Agent": "metalworks-research/0.1 (+https://github.com)"},
        )
        # Per-link failure accumulation for the most recent comments_for_links.
        self.last_skipped: int = 0
        self.last_errors: list[str] = []

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> ArcticShiftApiClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ── Public surface ──────────────────────────────────────────────────

    def comments_tree(self, *, link_id: str) -> list[dict[str, Any]]:
        """Every comment under one submission, flattened depth-first.

        ``link_id`` is Reddit's bare submission id (no ``t3_`` prefix).
        """
        payload = self._request_with_retries("/comments/tree", params={"link_id": link_id})
        wrapped = payload["data"] if isinstance(payload, dict) else payload
        out: list[dict[str, Any]] = []
        _flatten_listing(wrapped, out)
        return out

    def comments_for_links(self, link_ids: Sequence[str]) -> Iterator[list[dict[str, Any]]]:
        """Stream comment threads for many submissions, one batch per link.

        Yields one ``list[dict]`` per link_id in input order. A failure on one
        link yields ``[]`` for that link AND records it in ``last_skipped`` /
        ``last_errors`` so the caller can mark the run partial.
        """
        self.last_skipped = 0
        self.last_errors = []
        for link_id in link_ids:
            try:
                yield self.comments_tree(link_id=link_id)
            except Exception as exc:
                self.last_skipped += 1
                self.last_errors.append(f"{link_id}: {type(exc).__name__}: {exc}")
                logger.warning(
                    "ArcticShiftApiClient: skip link_id=%s after %s",
                    link_id,
                    type(exc).__name__,
                )
                yield []

    # ── Internal HTTP plumbing ──────────────────────────────────────────

    def _gate(self) -> None:
        """Sleep just long enough to hold us under ``min_interval``."""
        with self._lock:
            now = time.monotonic()
            wait = self.min_interval - (now - self._last_request_at)
            if wait > 0:
                time.sleep(wait)
            self._last_request_at = time.monotonic()

    def _request_with_retries(
        self, path: str, *, params: dict[str, Any]
    ) -> dict[str, Any] | list[Any]:
        url = f"{self.base_url}{path}"
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            self._gate()
            try:
                resp: httpx.Response = self._client.get(url, params=params)
            except httpx.HTTPError as exc:
                last_exc = exc
                wait = min(2**attempt, 30)
                logger.warning(
                    "ArcticShiftApiClient: %s failed (%s), retrying in %.1fs (%d/%d)",
                    path,
                    type(exc).__name__,
                    wait,
                    attempt,
                    self.max_retries,
                )
                time.sleep(wait)
                continue

            if resp.status_code == 429:
                reset = resp.headers.get("X-RateLimit-Reset")
                wait = (
                    float(reset)
                    if reset and reset.replace(".", "").isdigit()
                    else float(2**attempt)
                )
                wait = min(wait, 60)
                logger.warning("ArcticShiftApiClient: 429 on %s, sleeping %.1fs", path, wait)
                time.sleep(wait)
                continue

            if 500 <= resp.status_code < 600:
                wait = min(2**attempt, 30)
                logger.warning(
                    "ArcticShiftApiClient: %d on %s, retrying in %.1fs (%d/%d)",
                    resp.status_code,
                    path,
                    wait,
                    attempt,
                    self.max_retries,
                )
                time.sleep(wait)
                continue

            if resp.status_code >= 400:
                raise ArcticShiftApiError(f"{resp.status_code} on {path}: {resp.text[:200]}")

            try:
                payload: Any = resp.json()
            except Exception as exc:
                raise ArcticShiftApiError(f"non-JSON body from {path}: {exc}") from exc
            return payload

        # Exhausted retries. If the last failure was a 429 storm, surface the
        # typed rate-limit error; otherwise re-raise the transport exception.
        if last_exc is not None:
            raise last_exc
        raise RateLimitedError("ArcticShift")
