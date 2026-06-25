"""Live-API submissions corpus reader — the DEFAULT.

:class:`ArcticShiftReader` implements the
:class:`~metalworks.research.deps.CorpusReader` protocol over the live Arctic
Shift ``/posts/search`` + ``/posts/ids`` endpoints. Submissions therefore come
from the LIVE API (the current month included) using only core ``httpx`` — no
``[arctic]``/``[supabase]`` extra, no Hugging Face rate limits, no Parquet
mirror that lags reality.

It is the default reader (``ARCTIC_SHIFT_SOURCE`` unset or ``api``). The HF
Parquet mirror (:class:`~metalworks.research.arctic.reader.ArcticReader`) and the
Supabase mirror (:class:`~metalworks.research.arctic.mirror_reader.ArcticMirrorReader`)
are opt-in performance/offline tiers; see
:func:`metalworks.config.resolve_corpus_reader`.

Comments still come from :class:`~metalworks.research.arctic.api.ArcticShiftApiClient`
(the ``CommentSource``); this reader and that client share the same live API.

Note: within a single month the reader returns one page of up to ``page_limit``
newest submissions; cross-page (intra-month) pagination is a deliberate
follow-up — demand research samples newest-first and bounds by ``limit``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from metalworks.research.arctic.api import ArcticShiftApiClient

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from metalworks.research.types import MonthRef


def _month_window(m: MonthRef) -> tuple[int, int]:
    """``[after, before)`` unix-second bounds for one UTC calendar month."""
    start = datetime(m.year, m.month, 1, tzinfo=UTC)
    end = (
        datetime(m.year + 1, 1, 1, tzinfo=UTC)
        if m.month == 12
        else datetime(m.year, m.month + 1, 1, tzinfo=UTC)
    )
    return int(start.timestamp()), int(end.timestamp())


class ArcticShiftReader:
    """A ``CorpusReader`` backed by the live Arctic Shift posts API."""

    def __init__(
        self,
        *,
        client: ArcticShiftApiClient | None = None,
        page_limit: int = 100,
    ) -> None:
        self._client = client or ArcticShiftApiClient()
        self._owns_client = client is None
        self._page_limit = page_limit

    def latest_available_month(self, content_type: str = "submissions") -> MonthRef:
        """The current UTC month — the live API always has it."""
        from metalworks.research.types import MonthRef

        now = datetime.now(UTC)
        return MonthRef(now.year, now.month)

    def pull_subreddit(
        self,
        *,
        subreddit: str,
        content_type: str,
        months: Sequence[MonthRef],
        select_cols: Sequence[str] | None = None,
        limit: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield submission rows for one subreddit across ``months``, newest first.

        ``content_type`` other than ``submissions`` yields nothing — comments
        come from the ``CommentSource``, not the corpus reader. ``select_cols``
        is ignored (the API returns full rows; downstream reads by key).
        """
        if content_type != "submissions":
            return
        cols = list(select_cols) if select_cols else None
        remaining = limit
        for month in sorted(months, key=lambda r: (r.year, r.month), reverse=True):
            if remaining is not None and remaining <= 0:
                return
            after, before = _month_window(month)
            page = self._page_limit if remaining is None else min(self._page_limit, remaining)
            rows = self._client.search_submissions(
                subreddit=subreddit,
                after=after,
                before=before,
                limit=page,
                sort="desc",
            )
            for row in rows:
                yield {k: row.get(k) for k in cols} if cols else row
                if remaining is not None:
                    remaining -= 1
                    if remaining <= 0:
                        return

    def fetch_submissions_by_ids(
        self, post_ids: Sequence[str], months: Sequence[MonthRef]
    ) -> Iterator[dict[str, Any]]:
        """Yield submission rows whose bare id is in ``post_ids`` (hydration).

        ``months`` is accepted for protocol parity but unused — the live
        ``/posts/ids`` endpoint is not window-scoped.
        """
        ids = [i for i in post_ids if i]
        for start in range(0, len(ids), 50):
            yield from self._client.submissions_by_ids(ids[start : start + 50])

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
