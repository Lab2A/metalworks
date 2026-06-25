"""0.5 lane conformance sweep — the registry-level backstop for going wide.

``check_item_source`` verifies ONE connector against its protocol; this sweep walks
the WHOLE ``SOURCE_SPECS`` + ``MAGNITUDE_SPECS`` and asserts the cross-source lane
discipline that keeps cite-or-die honest as the source count grows: a magnitude
number can never masquerade as grounding, a blocked source can never become a
scraper, every declared signal/targeting actually resolves, and the back-compat stub
spec is not shippable. ``SourceSpec.__post_init__`` enforces the per-spec matrix
(0.1); these are the rules that live BETWEEN the registries (review M1/S2/DX-F2).

The sweep runs under pytest, which IS the CI gate, so it is the backstop — not an
opt-in script. Two halves:

* ``test_sweep_passes_on_real_registries`` — the shipped sources/providers conform.
* one NEGATIVE fixture per rule — each rule fails LOUDLY on an injected violation, so
  a future regression that drops a signal or registers a blocked scraper is caught.

Every grounding source is constructed via the real ``get_source`` registry path with
an OFFLINE fixture (a stub httpx client / a fake reader / a canned search provider) —
``pytest-socket`` blocks the network, so the sweep proves rule 1 with zero live calls.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from typing import Any

import pytest

# Importing the built-in connectors + the magnitude module populates the registries:
# registration is lazy (a bare ``import metalworks`` imports none of them), so the
# sweep must trigger each module's module-scope ``register_source`` first.
import metalworks.research.sources.arctic
import metalworks.research.sources.ats
import metalworks.research.sources.discourse
import metalworks.research.sources.hackernews
import metalworks.research.sources.hn_archive
import metalworks.research.sources.magnitude
import metalworks.research.sources.producthunt
import metalworks.research.sources.samgov
import metalworks.research.sources.stackexchange
import metalworks.research.sources.web
import metalworks.research.sources.wordpress  # noqa: F401

# Importing the planner package registers the ``subreddit`` target picker at its scope.
from metalworks.research.planner import register_target_picker  # noqa: F401
from metalworks.research.planner.source_picker import registered_targetings
from metalworks.research.sources import (
    SOURCE_SPECS,
    SOURCES,
    SourceSpec,
    SourceWindow,
    get_source,
    register_source,
)
from metalworks.research.sources.magnitude import (
    MAGNITUDE_PROVIDERS,
    MAGNITUDE_SPECS,
    MagnitudeSpec,
)
from metalworks.research.synthesis.signals import SIGNAL_SPECS, SignalSpec, register_signal
from metalworks.research.types import MonthRef
from metalworks.testing import (
    check_grounding_constructible,
    check_grounding_has_grounding_signal,
    check_keys_env_only,
    check_lane_conformance,
    check_no_blocked_magnitude,
    check_no_magnitude_in_sources,
    check_signals_registered,
    check_spec_not_stub,
    check_targeting_has_picker,
)

_NOW = datetime(2026, 6, 1, tzinfo=UTC)
_MONTH = MonthRef(2026, 5)


# ── Offline fixtures: one per shipped grounding source (no network) ────────────


class _FakeArcticReader:
    """A minimal ``CorpusReader`` over one canned subreddit row. No DuckDB, no I/O."""

    def latest_available_month(self, content_type: str = "submissions") -> MonthRef:
        return _MONTH

    def pull_subreddit(self, **kwargs: Any) -> Iterator[dict[str, Any]]:
        yield {
            "id": "abc1",
            "subreddit": kwargs.get("subreddit", "Supplements"),
            "title": "stim-free focus aid that does not wreck sleep",
            "selftext": "caffeine wrecks my sleep, what else works",
            "url": "https://www.reddit.com/r/Supplements/comments/abc1/",
            "author": "redditor",
            "score": 42,
            "num_comments": 3,
            "created_utc": int(_NOW.timestamp()),
        }

    def fetch_submissions_by_ids(self, *args: Any, **kwargs: Any) -> Iterator[dict[str, Any]]:
        return iter([])

    def close(self) -> None:
        return None


class _FakeArcticComments:
    """A ``CommentSource`` yielding one authored comment per link (so a Reddit post,
    authorless on the spine, still has a pseudonymizable quote underneath)."""

    def comments_for_links(self, link_ids: Sequence[str]) -> Iterator[list[dict[str, Any]]]:
        for lid in link_ids:
            yield [
                {
                    "id": f"{lid}_c1",
                    "link_id": f"t3_{lid}",
                    "subreddit": "Supplements",
                    "body": "l-theanine works for me, no crash",
                    "author": "commenter",
                    "score": 5,
                    "created_utc": int(_NOW.timestamp()),
                    "parent_id": f"t3_{lid}",
                }
            ]


class _StubResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


_HN_SEARCH = {
    "hits": [
        {
            "objectID": "100",
            "title": "Ask HN: best stim-free focus aid?",
            "story_text": "<p>I want focus without jitters.</p>",
            "url": "",
            "author": "alice",
            "points": 42,
            "num_comments": 1,
            "created_at_i": 1_700_000_000,
        }
    ],
    "nbPages": 1,
}
_HN_ITEM_100 = {
    "id": 100,
    "type": "story",
    "children": [
        {
            "id": 201,
            "type": "comment",
            "author": "carol",
            "text": "<p>L-theanine works for me.</p>",
            "created_at_i": 1_700_000_200,
            "children": [],
        }
    ],
}


class _StubHnClient:
    """A minimal httpx.Client stand-in for the HN Algolia API. No network."""

    def get(self, url: str, params: dict[str, Any] | None = None) -> _StubResponse:
        if "/search" in url:
            return _StubResponse(_HN_SEARCH)
        if url.endswith("/items/100"):
            return _StubResponse(_HN_ITEM_100)
        raise AssertionError(f"unexpected URL {url}")

    def close(self) -> None:
        return None


class _FakeHnArchiveReader:
    """A minimal ``HackerNewsArchiveReader`` over one canned story + comment row."""

    def latest_available_month(self) -> MonthRef:
        return _MONTH

    def pull_stories(
        self, *, query: str, months: Sequence[MonthRef], limit: int | None = None
    ) -> Iterator[dict[str, Any]]:
        yield {
            "id": 500,
            "by": "archivist",
            "time": int(_NOW.timestamp()),
            "text": "a budget mechanical keyboard for programmers",
            "url": "",
            "score": 120,
            "title": "Show HN: budget keyboard",
            "descendants": 1,
        }

    def comment_threads(
        self, story_ids: Sequence[str], months: Sequence[MonthRef]
    ) -> dict[str, list[dict[str, Any]]]:
        return {
            str(sid): [
                {
                    "id": int(sid) + 1,
                    "by": "replier",
                    "time": int(_NOW.timestamp()),
                    "text": "I love the tactile switches",
                    "dead": 0,
                    "deleted": 0,
                }
            ]
            for sid in story_ids
        }


_PH_POSTS = {
    "data": {
        "posts": {
            "edges": [
                {
                    "node": {
                        "id": "1",
                        "name": "FocusFlow",
                        "tagline": "a jitter-free focus app for devs",
                        "description": "helps developers stay focused",
                        "slug": "focusflow",
                        "url": "https://www.producthunt.com/posts/focusflow",
                        "votesCount": 340,
                        "commentsCount": 0,
                        "createdAt": "2026-05-15T10:00:00Z",
                        "topics": {"edges": [{"node": {"name": "Productivity"}}]},
                        "user": {"id": "u1", "name": "Ada", "username": "ada"},
                    }
                }
            ],
            "pageInfo": {"hasNextPage": False, "endCursor": "c1"},
        }
    }
}


class _StubPhClient:
    """A minimal Product Hunt GraphQL client stand-in. No network/token."""

    def post(self, _url: str, *, json: dict[str, Any], headers: Any = None) -> _StubResponse:
        return _StubResponse(_PH_POSTS)


_SE_SEARCH = {
    "items": [
        {
            "question_id": 700,
            "title": "stim-free focus aid for sysadmins?",
            "body": "<p>I want focus without jitters.</p>",
            "link": "https://stackoverflow.com/q/700",
            "score": 42,
            "view_count": 47000,
            "answer_count": 1,
            "creation_date": 1_700_000_000,
            "owner": {"user_id": 9, "display_name": "alice"},
        }
    ],
    "has_more": False,
}
_SE_ANSWERS = {
    "items": [
        {
            "answer_id": 701,
            "question_id": 700,
            "body": "<p>L-theanine works for me.</p>",
            "link": "https://stackoverflow.com/a/701",
            "score": 5,
            "is_accepted": True,
            "creation_date": 1_700_000_200,
            "owner": {"user_id": 10, "display_name": "carol"},
        }
    ],
    "has_more": False,
}


class _StubSeClient:
    """A minimal httpx.Client stand-in for the Stack Exchange API. No network."""

    def get(self, url: str, params: dict[str, Any] | None = None) -> _StubResponse:
        if "/search/advanced" in url:
            return _StubResponse(_SE_SEARCH)
        if "/answers" in url:
            return _StubResponse(_SE_ANSWERS)
        raise AssertionError(f"unexpected URL {url}")

    def close(self) -> None:
        return None


_ATS_GREENHOUSE = {
    "jobs": [
        {
            "id": 800,
            "title": "Staff Engineer, Focus Tooling",
            "absolute_url": "https://boards.greenhouse.io/acme/jobs/800",
            "content": "&lt;p&gt;Build focus tools. Caffeine-free.&lt;/p&gt;",
            # No timestamp: the sweep's zero-width [_NOW, _NOW] window keeps an
            # un-dated posting (a JD without an updated_at is still quotable).
            "location": {"name": "Remote"},
        }
    ]
}


class _StubAtsClient:
    """A minimal httpx.Client stand-in for a Greenhouse board. No network."""

    def get(self, url: str, params: dict[str, Any] | None = None) -> _StubResponse:
        if "/jobs" in url:
            return _StubResponse(_ATS_GREENHOUSE)


_SAMGOV_SEARCH = {
    "totalRecords": 1,
    "limit": 100,
    "offset": 0,
    "opportunitiesData": [
        {
            "noticeId": "abc123",
            "title": "Stim-free focus aid for federal employees",
            "solicitationNumber": "SOL-2026-001",
            "fullParentPathName": "GENERAL SERVICES ADMINISTRATION.FAS",
            "uiLink": "https://sam.gov/opp/abc123/view",
            "description": "https://api.sam.gov/opportunities/v1/noticedesc?noticeid=abc123",
            "postedDate": "2026-05-15",
            "type": "Solicitation",
            "award": {"amount": "500000", "date": "2026-05-20"},
        }
    ],
}


class _StubSamGovClient:
    """A minimal httpx.Client stand-in for the SAM.gov Opportunities API. No network."""

    def get(self, url: str, params: dict[str, Any] | None = None) -> _StubResponse:
        if "/opportunities/v2/search" in url:
            return _StubResponse(_SAMGOV_SEARCH)
        raise AssertionError(f"unexpected URL {url}")

    def close(self) -> None:
        return None


_DISCOURSE_SEARCH = {
    "topics": [
        {
            "id": 800,
            "title": "stim-free focus aid for builders?",
            "slug": "stim-free-focus-aid",
            "views": 47000,
            "like_count": 42,
            "posts_count": 2,
            "created_at": "2026-05-15T10:00:00Z",
            "last_poster_username": "alice",
        }
    ],
    "posts": [{"id": 9001, "topic_id": 800, "blurb": "I want focus without jitters."}],
}
_DISCOURSE_TOPIC_800 = {
    "id": 800,
    "slug": "stim-free-focus-aid",
    "post_stream": {
        "posts": [
            {
                "id": 9001,
                "post_number": 1,
                "username": "alice",
                "cooked": "<p>I want focus without jitters.</p>",
                "like_count": 42,
                "created_at": "2026-05-15T10:00:00Z",
            },
            {
                "id": 9002,
                "post_number": 2,
                "username": "carol",
                "cooked": "<p>L-theanine works for me.</p>",
                "like_count": 3,
                "created_at": "2026-05-15T11:00:00Z",
            },
        ]
    },
}


class _StubDiscourseResponse(_StubResponse):
    status_code = 200


class _StubDiscourseClient:
    """A minimal httpx.Client stand-in for the Discourse JSON API. No network."""

    def get(self, url: str, params: dict[str, Any] | None = None) -> _StubResponse:
        if "/search.json" in url:
            return _StubDiscourseResponse(_DISCOURSE_SEARCH)
        if "/t/800.json" in url:
            return _StubDiscourseResponse(_DISCOURSE_TOPIC_800)
        raise AssertionError(f"unexpected URL {url}")

    def close(self) -> None:
        return None


_WP_SEARCH = {
    "info": {"page": 1, "pages": 1, "results": 1},
    "plugins": [
        {
            "slug": "focus-flow",
            "name": "Focus Flow",
            "short_description": "A jitter-free focus aid for site admins.",
            "active_installs": 50000,
            "rating": 92,
            "num_ratings": 120,
            "author": "Ada",
        }
    ],
}
_WP_REVIEWS_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel>
<item>
<guid>https://wordpress.org/support/topic/best-focus-aid-1/</guid>
<title><![CDATA[Best focus aid (5 stars)]]></title>
<link>https://wordpress.org/support/topic/best-focus-aid-1/</link>
<pubDate>Tue, 23 Jun 2026 03:56:12 +0000</pubDate>
<dc:creator>Senri Miura</dc:creator>
<description><![CDATA[<p>Rating: 5 stars</p><p>L-theanine works, no crash.</p>]]></description>
</item>
</channel>
</rss>
"""


class _StubWpResponse(_StubResponse):
    def __init__(self, payload: dict[str, Any] | None = None, *, text: str = "") -> None:
        super().__init__(payload or {})
        self.text = text


class _StubWpClient:
    """A minimal httpx.Client stand-in for the WordPress.org plugin directory. No network."""

    def get(self, url: str, params: dict[str, Any] | None = None) -> _StubWpResponse:
        if "/plugins/info/" in url:
            return _StubWpResponse(_WP_SEARCH)
        if "/reviews/feed/" in url:
            return _StubWpResponse(text=_WP_REVIEWS_FEED)
        raise AssertionError(f"unexpected URL {url}")

    def close(self) -> None:
        return None


class _FakeSearchProvider:
    """A canned ``SearchProvider`` — distinct domains, no network."""

    provider_id: str = "fake"

    def search(
        self, *, query: str, max_results: int = 10, recency_days: int | None = None
    ) -> list[Any]:
        from metalworks.search import SearchResult

        return [
            SearchResult(
                url="https://www.example.com/focus-aids",
                title="Best stim-free focus aids",
                snippet="People want focus without the caffeine crash.",
            ),
            SearchResult(
                url="https://nootropics.io/stacks",
                title="Nootropic stacks that work",
                snippet="L-theanine plus caffeine.",
            ),
        ][:max_results]


def _source_fixtures() -> dict[str, dict[str, object]]:
    """``get_source`` kwargs (offline deps) for every shipped grounding source id.

    Keyed by ``source_id`` so the sweep constructs each via the real ``get_source``
    registry path with a stub client / fake reader injected — proving rule 1 (a
    grounding id is constructible and quotable) without a live network call.
    """
    return {
        "ats": {"provider": "greenhouse", "slug": "acme", "client": _StubAtsClient()},
        "reddit": {"reader": _FakeArcticReader(), "comments": _FakeArcticComments()},
        "arctic": {"reader": _FakeArcticReader(), "comments": _FakeArcticComments()},
        "hackernews": {"client": _StubHnClient(), "author_salt": "t"},
        "hackernews_archive": {"reader": _FakeHnArchiveReader()},
        "hn_archive": {"reader": _FakeHnArchiveReader()},
        "producthunt": {"token": "dev-token", "client": _StubPhClient()},
        "samgov": {"key": "dev-key", "client": _StubSamGovClient()},
        "stackexchange": {"client": _StubSeClient(), "author_salt": "t"},
        "discourse": {"client": _StubDiscourseClient(), "author_salt": "t"},
        "wordpress": {"client": _StubWpClient(), "author_salt": "t"},
        # 'web' is a web lane, not grounding — rule 1 skips it (no fixture needed).
    }


_GROUNDING_WINDOW = SourceWindow(months=(_MONTH,), start=_NOW, end=_NOW)

# The ids the shipped built-in connector modules register (the union imported above).
# Sibling tests (``test_itemsource`` / ``test_source_spec`` / ``test_config_resolution``)
# also self-register throwaway ids (``fake`` / ``spectest_bare`` / ``keyless``) into the
# SAME process-wide registry; the sweep validates the SHIPPED set, so it reads the real
# registries but scopes to these ids — robust to whatever order pytest runs the suite in.
SHIPPED_SOURCE_IDS = frozenset(
    {
        "ats",
        "reddit",
        "arctic",
        "hackernews",
        "hackernews_archive",
        "hn_archive",
        "producthunt",
        "samgov",
        "stackexchange",
        "discourse",
        "wordpress",
        "web",
    }
)
SHIPPED_MAGNITUDE_IDS = frozenset({"npm"})


def _shipped_source_specs() -> dict[str, SourceSpec]:
    return {sid: SOURCE_SPECS[sid] for sid in SHIPPED_SOURCE_IDS if sid in SOURCE_SPECS}


def _shipped_magnitude_specs() -> dict[str, MagnitudeSpec]:
    return {pid: MAGNITUDE_SPECS[pid] for pid in SHIPPED_MAGNITUDE_IDS if pid in MAGNITUDE_SPECS}


# ── 1. The sweep passes on the real, shipped registries ────────────────────────


def test_all_shipped_ids_are_registered() -> None:
    """Guard the sweep's premise: every shipped id is actually in the live registry."""
    assert SHIPPED_SOURCE_IDS.issubset(SOURCE_SPECS), "a shipped source id failed to register"
    assert SHIPPED_SOURCE_IDS.issubset(SOURCES)
    assert SHIPPED_MAGNITUDE_IDS.issubset(MAGNITUDE_SPECS)
    assert SHIPPED_MAGNITUDE_IDS.issubset(MAGNITUDE_PROVIDERS)


def test_sweep_passes_on_real_registries() -> None:
    check_lane_conformance(
        source_specs=_shipped_source_specs(),
        magnitude_specs=_shipped_magnitude_specs(),
        sources=SOURCES,
        magnitude_providers=MAGNITUDE_PROVIDERS,
        signal_specs=SIGNAL_SPECS,
        registered_targetings=frozenset(registered_targetings()),
        source_fixtures=_source_fixtures(),
    )


def test_every_grounding_id_is_constructible_and_quotable() -> None:
    """Rule 1, explicit per-source: each grounding id pulls ≥1 quotable record."""
    fixtures = _source_fixtures()
    grounding = [s for s in _shipped_source_specs().values() if s.lane == "grounding"]
    assert grounding, "no grounding sources registered"
    for spec in grounding:
        check_grounding_constructible(
            spec,
            sources=SOURCES,
            fixture_kwargs=fixtures[spec.source_id],
            window=_GROUNDING_WINDOW,
        )


# ── Negative fixtures: one per rule. Each builds an isolated bad spec/registry and
# asserts the matching check fails LOUDLY (a future regression is caught). ───────


def _grounding_spec(**overrides: Any) -> SourceSpec:
    base: dict[str, Any] = {
        "source_id": "neg",
        "lane": "grounding",
        "signals": ("upvotes",),
        "targeting": "none",
        "auth": "none",
        "env": (),
        "access": "open",
        "relevance_hint": "negative-fixture source",
    }
    base.update(overrides)
    return SourceSpec(**base)


def test_rule1_unquotable_grounding_source_fails() -> None:
    """Rule 1 — a grounding source whose pull yields no authored quote fails."""

    class _AuthorlessSource:
        source_id = "authorless"

        def pull(
            self, *, query: str, window: SourceWindow, limit: int | None = None
        ) -> Iterator[Any]:
            from metalworks.contract import CorpusRecord

            yield CorpusRecord(
                id="x1",
                source="authorless",
                source_id="x1",
                url="https://x.test/1",
                title="a record with text and url but no author anywhere",
                text="body",
            )

        def comments_for(self, record_ids: Sequence[str]) -> None:
            return None  # no comment layer → no recoverable author

        def latest_window(self) -> SourceWindow:
            return SourceWindow()

    register_source(
        "authorless", lambda **_: _AuthorlessSource(), spec=_grounding_spec(source_id="authorless")
    )
    try:
        with pytest.raises(AssertionError, match="pseudonymizable author"):
            check_grounding_constructible(
                SOURCE_SPECS["authorless"], sources=SOURCES, fixture_kwargs={}
            )
    finally:
        SOURCES.pop("authorless", None)
        SOURCE_SPECS.pop("authorless", None)


def test_rule2_magnitude_lane_in_source_specs_fails() -> None:
    """Rule 2 — a ``magnitude`` lane spec in SOURCE_SPECS fails the sweep.

    ``SourceSpec.__post_init__`` forbids constructing one, so we inject a bare object
    carrying ``lane='magnitude'`` straight into the registry mapping to simulate the
    drift the registry-level rule is the backstop for.
    """

    class _MagLikeSpec:
        lane = "magnitude"
        access = "open"

    specs = {**SOURCE_SPECS, "bad_mag": _MagLikeSpec()}
    with pytest.raises(AssertionError, match="lane 'magnitude' must never appear"):
        check_no_magnitude_in_sources(source_specs=specs, sources=SOURCES)  # type: ignore[arg-type]


def test_rule3_blocked_source_registered_as_scraper_fails() -> None:
    """Rule 3 (source) — a ``blocked`` access id registered in SOURCES fails."""
    blocked = _grounding_spec(source_id="blk", lane="web", signals=(), access="blocked")
    specs = {**SOURCE_SPECS, "blk": blocked}
    srcs = {**SOURCES, "blk": (lambda **_: None)}
    with pytest.raises(AssertionError, match="must not be a registered SOURCES"):
        check_no_magnitude_in_sources(source_specs=specs, sources=srcs)  # type: ignore[arg-type]


def test_rule3_blocked_magnitude_provider_fails() -> None:
    """Rule 3 (magnitude) — a ``blocked`` access magnitude provider fails."""
    blocked = MagnitudeSpec(
        provider_id="blk",
        signals=("downloads",),
        targeting="slug",
        auth="none",
        env=(),
        access="blocked",
        relevance_hint="blocked",
    )
    with pytest.raises(AssertionError, match="access 'blocked' must not be registered"):
        check_no_blocked_magnitude(magnitude_specs={**MAGNITUDE_SPECS, "blk": blocked})


def test_rule4_unregistered_signal_kind_fails() -> None:
    """Rule 4 — a spec declaring a signal with no SignalSpec fails."""
    spec = _grounding_spec(signals=("not_a_registered_kind",))
    with pytest.raises(AssertionError, match="not registered in SIGNAL_SPECS"):
        check_signals_registered(spec, signal_specs=SIGNAL_SPECS)


def test_rule5_grounding_with_only_magnitude_signal_fails() -> None:
    """Rule 5 — a grounding lane whose only signal is ``is_magnitude`` fails."""
    spec = _grounding_spec(signals=("downloads",))  # downloads is is_magnitude
    assert SIGNAL_SPECS["downloads"].is_magnitude  # guard the fixture's premise
    with pytest.raises(AssertionError, match="declares no non-magnitude signal"):
        check_grounding_has_grounding_signal(spec, signal_specs=SIGNAL_SPECS)


def test_rule6_default_stub_spec_fails() -> None:
    """Rule 6 — the bare ``_grounding_default`` stub (no spec=) fails."""
    from metalworks.research.sources.spec import _grounding_default

    stub = _grounding_default("stubby")
    with pytest.raises(AssertionError, match="default/empty grounding stub"):
        check_spec_not_stub(stub)


def test_rule7_targeting_without_picker_fails() -> None:
    """Rule 7 — a targeting kind with no registered picker fails."""
    spec = _grounding_spec(targeting="instance")
    with pytest.raises(AssertionError, match=r"no registered .*target picker"):
        check_targeting_has_picker(spec, registered_targetings=frozenset({"subreddit"}))


def test_keys_env_only_rejects_secret_value() -> None:
    """Keys-env-only — an ``env`` entry that is a literal value, not a NAME, fails."""
    spec = _grounding_spec(
        source_id="leaky", auth="key", env=("sk-this-is-a-literal-secret",), access="free_key"
    )
    with pytest.raises(AssertionError, match="not an UPPER_SNAKE env-var name"):
        check_keys_env_only(spec)


def test_keys_env_only_passes_on_real_env_names() -> None:
    """Keys-env-only — the shipped authed specs name UPPER_SNAKE env vars."""
    for spec in _shipped_source_specs().values():
        check_keys_env_only(spec)
    for mspec in _shipped_magnitude_specs().values():
        check_keys_env_only(mspec)


# ── A registered signal kind sanity check (the sweep's premise) ────────────────


def test_shipped_grounding_signals_are_registered_non_magnitude() -> None:
    """Every shipped grounding source ranks on a registered, non-magnitude signal.

    Exception: a ``yields_units`` grounding source (ATS) ranks by distinct-domain
    breadth, not a signal vector, so an empty ``signals`` is legal there — the
    rule-5 helper takes the constructed source's ``yields_units`` flag.
    """
    fixtures = _source_fixtures()
    for spec in _shipped_source_specs().values():
        if spec.lane != "grounding":
            continue
        check_signals_registered(spec, signal_specs=SIGNAL_SPECS)
        source = get_source(spec.source_id, **fixtures[spec.source_id])
        yields_units = bool(getattr(source, "yields_units", False))
        check_grounding_has_grounding_signal(
            spec, signal_specs=SIGNAL_SPECS, yields_units=yields_units
        )
        # Belt-and-suspenders: each declared kind resolves to a real spec object.
        for kind in spec.signals:
            assert isinstance(SIGNAL_SPECS[kind], SignalSpec)


def test_register_signal_is_importable() -> None:
    """Guard the test's own imports (register_signal stays public)."""
    assert callable(register_signal)
