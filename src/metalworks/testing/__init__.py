"""Public testing utilities — verify YOUR adapters and backends.

Implement a repo backend or a ChatModel adapter, then run metalworks' own
conformance checks against it:

    from metalworks.testing import FakeChatModel, FakeEmbedding, check_all_repos

    def test_my_backend_conforms():
        check_all_repos(MyBackend())

`check_all_repos` runs the same semantic assertions metalworks holds its
built-in backends to — including the >1000-rows-behind-one-filter case that
catches silently-truncating paginated backends.

Source connectors have their own conformance check — implement an
:class:`~metalworks.research.sources.ItemSource` and verify it against the
published contract before you ship it:

    from metalworks.testing import check_item_source

    def test_my_source_conforms():
        check_item_source(MySource())

`check_item_source` asserts the protocol contract: `pull` yields `CorpusRecord`s
with stable, non-empty ids, a re-pull is idempotent (same id set), `comments_for`
returns `CorpusComment`s parented to pulled record ids (or `None`), and
`latest_window` returns a `SourceWindow`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from metalworks.contract import (
    CorpusComment,
    CorpusRecord,
    InboxItem,
    Opportunity,
    RedditComment,
    RedditPost,
    ResearchBrief,
    RunSummary,
    TargetSubreddit,
)
from metalworks.embeddings import FakeEmbedding, IndexIdentity
from metalworks.errors import EmbeddingModelMismatch, MissingExtraError, StyleAuditUnsupported
from metalworks.llm.fake import FakeChatModel
from metalworks.render import ComputedStyle, PageRenderer, RenderedPage, RendererCapabilities
from metalworks.render.fake import FakeRenderer
from metalworks.research.sources import ItemSource, SourceFactory, SourceWindow, get_source
from metalworks.research.sources.magnitude import MagnitudeFactory, MagnitudeProvider, MagnitudeSpec
from metalworks.research.sources.spec import SourceSpec
from metalworks.research.synthesis.signals import SignalSpec
from metalworks.stores.repos import (
    AccountRepo,
    BriefRepo,
    CorpusRepo,
    InboxRepo,
    OpportunityRepo,
    RunRepo,
    StoredRedditAccount,
)

if TYPE_CHECKING:
    pass


class AllRepos(BriefRepo, RunRepo, CorpusRepo, AccountRepo, OpportunityRepo, InboxRepo, Protocol):
    """Intersection protocol: a backend that implements every metalworks repo."""


def _post(i: int) -> RedditPost:
    return RedditPost(
        post_id=f"mwtest-p{i}",
        subreddit="Supplements",
        title=f"Post {i}",
        url=f"https://reddit.com/r/Supplements/comments/mwtest-p{i}/",
    )


def _comment(i: int, post_id: str) -> RedditComment:
    return RedditComment(
        comment_id=f"mwtest-c{i}",
        post_id=post_id,
        subreddit="Supplements",
        body=f"comment body {i}",
        permalink=f"https://reddit.com/r/Supplements/comments/{post_id}/mwtest-c{i}/",
        author_hash=f"author{i % 7}",
    )


def check_brief_repo(repo: BriefRepo) -> None:
    brief = ResearchBrief(
        brief_id="mwtest-b1",
        question="q",
        decision_context="d",
        success_criteria=["s"],
        must_address=["m"],
        target_subreddits=[TargetSubreddit(name="Supplements", rationale="core")],
        web_research_directions=[],
        relevance_rubric="r",
    )
    repo.save_brief(brief)
    got = repo.get_brief("mwtest-b1")
    assert got is not None and got.question == "q", "brief round-trip failed"
    assert repo.get_brief("mwtest-missing") is None, "missing brief must return None"
    assert any(b.brief_id == "mwtest-b1" for b in repo.list_briefs()), "list_briefs missed brief"


def check_run_repo(repo: RunRepo) -> None:
    run = RunSummary(
        report_id="mwtest-r1",
        brief_id="mwtest-b1",
        query="q",
        status="queued",
        created_at=datetime(2026, 6, 9, tzinfo=UTC),
    )
    repo.save_run(run)
    repo.save_run(run.model_copy(update={"status": "complete"}))
    got = repo.get_run("mwtest-r1")
    assert got is not None and got.status == "complete", "save_run must upsert by report_id"
    assert [r.report_id for r in repo.list_runs(brief_id="mwtest-b1")] == ["mwtest-r1"]


def check_corpus_repo(repo: CorpusRepo, *, rows: int = 1500) -> None:
    """The big one: a paginating backend that silently truncates fails here."""
    posts = [_post(i) for i in range(3)]
    repo.upsert_posts(posts)
    comments = [_comment(i, posts[i % 3].post_id) for i in range(rows)]
    repo.upsert_comments(comments)
    repo.upsert_comments(comments[:50])  # idempotent re-upsert must not duplicate

    got = repo.get_comments_for_posts([p.post_id for p in posts])
    assert len(got) == rows, (
        f"get_comments_for_posts returned {len(got)} of {rows} rows — "
        "backend is truncating (paginate to exhaustion!)"
    )
    got_posts = repo.get_posts(["mwtest-p0", "mwtest-p2", "mwtest-missing"])
    assert {p.post_id for p in got_posts} == {"mwtest-p0", "mwtest-p2"}
    _check_corpus_embeddings(repo)


def _check_corpus_embeddings(repo: CorpusRepo) -> None:
    """Vector storage round-trip + cosine search + model-mismatch guard.

    Storage (upsert) is always exercised; the cosine search needs the ``[research]``
    extra (numpy), so it is skipped when numpy is absent — keeping the bare CI
    matrix green while still proving the write path on every backend.
    """
    import importlib.util

    identity = IndexIdentity(embedding_model_id="mwtest-embed", dim=4)
    repo.upsert_embeddings(
        {"mwtest-c0": [1.0, 0.0, 0.0, 0.0], "mwtest-c1": [0.0, 1.0, 0.0, 0.0]},
        identity=identity,
    )

    # get_embeddings (the cache-read path) — numpy-free, always exercised.
    fetched = repo.get_embeddings(["mwtest-c0", "mwtest-absent"], identity=identity)
    assert set(fetched) == {"mwtest-c0"}, "get_embeddings must return only stored ids"
    assert fetched["mwtest-c0"][0] == 1.0
    wrong_model = IndexIdentity(embedding_model_id="mwtest-other", dim=4)
    assert repo.get_embeddings(["mwtest-c0"], identity=wrong_model) == {}, (
        "get_embeddings must miss when the index was built with a different model"
    )

    if importlib.util.find_spec("numpy") is None:
        return  # search needs the [research] extra; the write path is already proven

    nearest = repo.search_embeddings([0.9, 0.1, 0.0, 0.0], k=1, identity=identity)
    assert nearest and nearest[0][0] == "mwtest-c0", "cosine search missed the nearest vector"

    other_model = IndexIdentity(embedding_model_id="mwtest-other", dim=4)
    try:
        repo.search_embeddings([1.0, 0.0, 0.0, 0.0], k=1, identity=other_model)
    except EmbeddingModelMismatch:
        pass
    else:
        raise AssertionError("search must reject a mismatched embedding model")


def check_account_repo(repo: AccountRepo) -> None:
    acct = StoredRedditAccount(username="mwtest-user", encrypted_access_token="ct")
    repo.save_account(acct)
    got = repo.get_account("mwtest-user")
    assert got is not None and got.encrypted_access_token == "ct"
    repo.delete_account("mwtest-user")
    assert repo.get_account("mwtest-user") is None


def check_opportunity_repo(repo: OpportunityRepo) -> None:
    opp = Opportunity(opportunity_id="mwtest-o1", post=_post(900), draft_reply="d")
    repo.save_opportunities([opp])
    assert repo.opportunity_exists(_post(900).url) is True, "dedup gate failed"
    assert repo.opportunity_exists("https://reddit.com/r/none/") is False
    repo.update_opportunity_status("mwtest-o1", "approved")
    assert [o.opportunity_id for o in repo.list_opportunities(status="approved")] == ["mwtest-o1"]


def check_inbox_repo(repo: InboxRepo) -> None:
    repo.upsert_inbox_items([InboxItem(message_id="mwtest-m1", kind="dm", body="hi")])
    assert len(repo.list_inbox_items(unread_only=True)) >= 1
    repo.mark_inbox_read("mwtest-m1")
    assert all(i.message_id != "mwtest-m1" for i in repo.list_inbox_items(unread_only=True))


def check_item_source(
    source: ItemSource,
    *,
    query: str = "test",
    window: SourceWindow | None = None,
    limit: int | None = 25,
) -> None:
    """Assert that ``source`` honors the :class:`ItemSource` contract.

    A third-party connector self-verifies with this BEFORE shipping. It runs a
    small live pull against the source and checks the contract every downstream
    stage relies on:

    * ``source.source_id`` is a non-empty string.
    * ``latest_window()`` returns a :class:`SourceWindow`.
    * ``pull()`` yields :class:`CorpusRecord`s, each with a non-empty ``id``,
      ``source`` matching ``source_id``, and ``source_id`` set.
    * ids are UNIQUE within a pull and STABLE across a re-pull (idempotency — the
      same query/window yields the same id set, so upsert-by-id never duplicates).
    * ``comments_for()`` returns ``None`` (comment-less source) OR yields
      :class:`CorpusComment`s, each parented (``parent_id``) to a pulled record id.

    Pass a ``window`` for sources that require one; otherwise ``latest_window()``
    is used. ``limit`` keeps the probe small — give the source a fixture with at
    least one record so the assertions have something to bite on.
    """
    assert isinstance(source.source_id, str) and source.source_id, (
        "source_id must be a non-empty string"
    )

    win = window if window is not None else source.latest_window()
    assert isinstance(win, SourceWindow), "latest_window() must return a SourceWindow"

    records = list(source.pull(query=query, window=win, limit=limit))
    assert records, "pull() yielded no records — give check_item_source a fixture/window with data"

    ids: list[str] = []
    for r in records:
        assert isinstance(r, CorpusRecord), f"pull() must yield CorpusRecord, got {type(r)!r}"
        assert r.id, "every pulled record must have a non-empty, stable id"
        assert r.source == source.source_id, (
            f"record.source ({r.source!r}) must equal source_id ({source.source_id!r})"
        )
        assert r.source_id, "record.source_id (native id) must be set"
        ids.append(r.id)

    assert len(set(ids)) == len(ids), "pulled record ids must be unique within a pull"

    # Idempotency: a re-pull over the same query/window yields the same id set.
    again = [r.id for r in source.pull(query=query, window=win, limit=limit)]
    assert set(again) == set(ids), (
        "pull() is not idempotent: re-pulling the same query/window changed the id "
        "set — record ids must be stable (the corpus upserts by id)"
    )

    # Comments: None (comment-less) is legal; otherwise every comment must be a
    # CorpusComment parented to one of the pulled records.
    batches = source.comments_for(ids)
    if batches is not None:
        pulled = set(ids)
        for batch in batches:
            for c in batch:
                assert isinstance(c, CorpusComment), (
                    f"comments_for() must yield CorpusComment, got {type(c)!r}"
                )
                assert c.id, "every comment must have a non-empty id"
                assert c.parent_id in pulled, (
                    f"comment.parent_id ({c.parent_id!r}) is not one of the pulled record ids"
                )
                assert c.source == source.source_id, (
                    f"comment.source ({c.source!r}) must equal source_id ({source.source_id!r})"
                )


class FakeMagnitudeProvider:
    """A deterministic, offline :class:`MagnitudeProvider` for tests.

    Constructed with a fixed ``entity -> {kind: value}`` table and the ``signals``
    kinds it emits. :meth:`measure` returns ONLY the requested entities present in
    the table — an absent entity is omitted (unknown, never ``0.0``), exactly the
    contract a real provider honors. Set ``raises=True`` to simulate a transport
    failure so a caller can exercise the best-effort (caveat + ``partial``) path.
    """

    def __init__(
        self,
        table: dict[str, dict[str, float]] | None = None,
        *,
        provider_id: str = "fake_magnitude",
        signals: tuple[str, ...] = ("downloads",),
        raises: bool = False,
    ) -> None:
        self.provider_id = provider_id
        self.signals = signals
        self._table = table or {}
        self._raises = raises
        self.calls: list[tuple[tuple[str, ...], SourceWindow]] = []

    def measure(
        self, *, entities: Sequence[str], window: SourceWindow
    ) -> dict[str, dict[str, float]]:
        self.calls.append((tuple(entities), window))
        if self._raises:
            raise RuntimeError("FakeMagnitudeProvider: simulated transport failure")
        # Omission = unknown: only return entities we actually have data for.
        return {e: dict(self._table[e]) for e in entities if e in self._table}


def check_magnitude_provider(
    provider: MagnitudeProvider,
    *,
    entities: Sequence[str],
    window: SourceWindow | None = None,
) -> None:
    """Assert that ``provider`` honors the :class:`MagnitudeProvider` contract.

    A third-party magnitude provider self-verifies with this before shipping. Give
    it a small entity list it has data for. It checks the contract the lane-②
    overlay relies on:

    * ``provider_id`` is a non-empty string and ``signals`` is a non-empty tuple.
    * ``measure`` returns a ``dict[str, dict[str, float]]`` — entity → kind → value.
    * Every returned entity is one of the REQUESTED entities (a provider never
      invents an entity it wasn't asked about).
    * Every value is a real, finite, non-negative number — and OMISSION is the only
      "unknown": a returned entity must carry at least one real value, never an
      empty/zero stand-in for missing data.
    * Re-measuring the same entities/window is idempotent (same entity key set), so
      a re-run of the overlay attaches the same numbers.
    """
    import math

    assert isinstance(provider.provider_id, str) and provider.provider_id, (
        "provider_id must be a non-empty string"
    )
    assert isinstance(provider.signals, tuple) and provider.signals, (
        "signals must be a non-empty tuple of magnitude kinds"
    )

    win = window if window is not None else SourceWindow()
    result = provider.measure(entities=entities, window=win)
    assert isinstance(result, dict), "measure() must return a dict[str, dict[str, float]]"

    requested = set(entities)
    for entity, kinds in result.items():
        assert entity in requested, (
            f"measure() returned entity {entity!r} that was not requested "
            "(a provider never invents an entity)"
        )
        assert isinstance(kinds, dict) and kinds, (
            f"measure()[{entity!r}] must be a non-empty kind→value map — omit the entity "
            "entirely for 'unknown', never return an empty/zero stand-in"
        )
        for kind, value in kinds.items():
            assert isinstance(kind, str) and kind, "every signal kind must be a non-empty string"
            assert isinstance(value, (int, float)) and not isinstance(value, bool), (
                f"measure()[{entity!r}][{kind!r}] must be a number, got {type(value)!r}"
            )
            assert math.isfinite(value) and value >= 0.0, (
                f"measure()[{entity!r}][{kind!r}] must be finite and non-negative, got {value!r}"
            )

    again = provider.measure(entities=entities, window=win)
    assert set(again) == set(result), (
        "measure() is not idempotent: re-measuring the same entities/window changed "
        "the entity key set"
    )


# ── 0.5 lane conformance sweep ───────────────────────────────────────────────
#
# ``check_item_source`` / ``check_magnitude_provider`` (above) verify ONE connector
# or provider against its protocol. The sweep below is the registry-level backstop:
# it walks the whole :data:`~metalworks.research.sources.spec.SOURCE_SPECS` +
# :data:`~metalworks.research.sources.magnitude.MAGNITUDE_SPECS` and asserts the
# cross-source lane discipline that going wide must never break — a magnitude number
# can never masquerade as grounding, a blocked source can never become a scraper, and
# every declared signal/targeting actually resolves. ``SourceSpec.__post_init__``
# enforces the per-spec matrix (0.1); these are the rules that live BETWEEN the
# registries, which a single spec can't see.

# An env var name is "env-only" shaped: an UPPER_SNAKE identifier (a name the
# ``resolve_*`` pattern reads off ``os.environ``), never a literal secret value.
_ENV_VAR_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
# The ``auth`` values that require an ``env`` declaration (mirrors the spec matrix).
_AUTHED_KINDS = frozenset({"key", "oauth", "paid"})


def _is_quotable_grounding(source: ItemSource, *, records: Sequence[CorpusRecord]) -> None:
    """Assert a grounding source's pull yields ≥1 *quotable* record.

    Two legal shapes (see the :class:`ItemSource` docstring):

    * **comment-bearing** — each record has ``text``/``title`` + ``url``, and a real
      quote with a pseudonymizable author is recoverable: either the record itself
      carries an ``author_hash`` (HN/PH stories) OR a comment under it does (Reddit
      posts are authorless on the spine but their comments carry the author).
    * **unit-yielding** (``yields_units = True``, e.g. a web-style page source whose
      records ARE the synthesis units) — each record has text + url and the pull
      shows DOMAIN breadth (≥1 distinct registrable domain), the breadth axis the
      ranker uses in place of distinct authors.
    """
    quotable = [r for r in records if (r.text or r.title) and r.url]
    assert quotable, (
        f"source {source.source_id!r}: pull yielded no quotable record "
        "(a grounding record needs body/title text AND a resolvable url)"
    )

    if getattr(source, "yields_units", False):
        domains = {_record_domain(r) for r in quotable} - {""}
        assert domains, (
            f"unit source {source.source_id!r}: records carry no registrable domain — "
            "a yields_units source's breadth axis is distinct domains"
        )
        return

    # Comment-bearing: authorship must be recoverable from the record or its comments.
    if any(r.author_hash for r in quotable):
        return
    ids = [r.id for r in quotable]
    batches = source.comments_for(ids)
    assert batches is not None, (
        f"source {source.source_id!r}: no record carries an author_hash and the source "
        "has no comment layer — a grounding quote has no pseudonymizable author "
        "(set yields_units=True if records are self-representing units)"
    )
    has_author = any(c.author_hash for batch in batches for c in batch)
    assert has_author, (
        f"source {source.source_id!r}: neither records nor comments carry an author_hash — "
        "a grounding quote must trace to a pseudonymizable author"
    )


def _record_domain(record: CorpusRecord) -> str:
    """The registrable domain a unit source records (``extra['domain']`` or host)."""
    domain = record.extra.get("domain")
    if isinstance(domain, str) and domain:
        return domain
    from urllib.parse import urlsplit

    host = urlsplit(record.url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def check_grounding_constructible(
    spec: SourceSpec,
    *,
    sources: Mapping[str, SourceFactory],
    fixture_kwargs: Mapping[str, object],
    window: SourceWindow | None = None,
    query: str = "focus",
    limit: int | None = 25,
) -> None:
    """Rule 1 — a grounding source is constructible via ``get_source`` and quotable.

    Constructs the source through the real :func:`get_source` registry path (with the
    caller's offline ``fixture_kwargs`` injected — a stub client / fake reader), pulls
    over ``window``, and asserts ≥1 quotable record (see :func:`_is_quotable_grounding`).
    A non-``grounding`` lane spec is a no-op (web/magnitude lanes are not held to the
    grounding-quote shape).
    """
    if spec.lane != "grounding":
        return
    assert spec.source_id in sources, f"grounding spec {spec.source_id!r} has no factory in SOURCES"
    try:
        source = get_source(spec.source_id, **fixture_kwargs)
        win = window if window is not None else source.latest_window()
        records = list(source.pull(query=query, window=win, limit=limit))
    except MissingExtraError:
        # The source is validly registered; its optional extra (e.g. ``arctic``/duckdb)
        # just isn't installed — the CI ``bare`` matrix. Quotability is exercised in the
        # ``all`` matrix where the extra is present. Registration conformance still holds.
        return
    _is_quotable_grounding(source, records=records)


def check_no_magnitude_in_sources(
    *,
    source_specs: Mapping[str, SourceSpec],
    sources: Mapping[str, SourceFactory],
) -> None:
    """Rules 2 + 3 (source side) — no ``magnitude`` lane and no ``blocked`` id in SOURCES.

    A magnitude number is a lane-② overlay, NEVER a cluster-building source, so it must
    not appear in the ``SOURCES`` factory registry (and ``SourceSpec.__post_init__``
    already forbids ``lane == "magnitude"`` outright). A ``blocked`` source can only
    contribute web-style context, so it must never be a registered scraper either.
    """
    for sid, spec in source_specs.items():
        assert spec.lane != "magnitude", (
            f"source {sid!r}: lane 'magnitude' must never appear in SOURCE_SPECS "
            "(magnitude is a lane-② overlay, not a cluster-building source)"
        )
        if spec.access == "blocked":
            assert sid not in sources, (
                f"source {sid!r}: access 'blocked' must not be a registered SOURCES "
                "factory (blocked ⇒ web-lane context only, never a scraper)"
            )


def check_no_blocked_magnitude(*, magnitude_specs: Mapping[str, MagnitudeSpec]) -> None:
    """Rule 3 (magnitude side) — no ``blocked`` provider in MAGNITUDE_PROVIDERS.

    A blocked provider can never be reached, so registering one as a magnitude factory
    would silently never measure; it must be dropped, not shipped behind the registry.
    """
    for pid, spec in magnitude_specs.items():
        assert spec.access != "blocked", (
            f"magnitude provider {pid!r}: access 'blocked' must not be registered "
            "(a blocked provider can never measure — drop it, don't register it)"
        )


def check_signals_registered(
    spec: SourceSpec | MagnitudeSpec,
    *,
    signal_specs: Mapping[str, SignalSpec],
) -> None:
    """Rule 4 — every kind in a spec's ``signals`` tuple is a registered SignalSpec.

    Catches the silent magnitude-drop (DX-F2): a source that declares ``signals=("foo",)``
    with no ``register_signal`` for ``"foo"`` would have that kind score as zero
    forever. The kind must exist in ``SIGNAL_SPECS`` so the deterministic scorer can
    weight it.
    """
    sid = getattr(spec, "source_id", None) or getattr(spec, "provider_id", "?")
    for kind in spec.signals:
        assert kind in signal_specs, (
            f"spec {sid!r}: signal kind {kind!r} is not registered in SIGNAL_SPECS "
            "(register it with register_signal so the scorer can weight it)"
        )


def check_grounding_has_grounding_signal(
    spec: SourceSpec,
    *,
    signal_specs: Mapping[str, SignalSpec],
    yields_units: bool = False,
) -> None:
    """Rule 5 — a ``grounding`` lane declares ≥1 NON-``is_magnitude`` signal.

    A grounding source ranks on a real endorsement/breadth signal (upvotes, points,
    votes) — a magnitude-only signal vector would let an absolute-volume number stand
    in for grounded demand. A ``web`` lane is exempt (it ranks by domain breadth, not a
    signal vector, so an empty ``signals`` is legal there). A ``yields_units`` grounding
    source is exempt for the SAME reason: its records are self-representing units that
    the ranker scores by distinct-domain breadth, NOT by a per-record signal vector
    (the ATS job-board lane), so an empty ``signals`` is legal — the caller passes
    ``yields_units=True`` after constructing the source. The default/empty stub spec
    (lane grounding, no signals, no units) is still caught here.
    """
    if spec.lane != "grounding" or yields_units:
        return
    grounding_kinds = [
        k for k in spec.signals if (s := signal_specs.get(k)) is not None and not s.is_magnitude
    ]
    assert grounding_kinds, (
        f"grounding source {spec.source_id!r}: declares no non-magnitude signal "
        f"(signals={spec.signals!r}) — a grounding lane must rank on a real endorsement "
        "signal, not a magnitude number alone"
    )


def check_spec_not_stub(spec: SourceSpec) -> None:
    """Rule 6 — ``spec`` is effectively required: the bare grounding stub fails.

    ``register_source(id, factory)`` with no ``spec=`` lands the signal-less,
    hint-less :func:`~metalworks.research.sources.spec._grounding_default`. That stub
    is a back-compat landing pad, NOT a shippable declaration — a real source must
    declare its signals and a relevance hint. This rule fails any source still on the
    stub (the same condition rule 5's no-signal check catches, asserted directly).
    """
    is_stub = (
        spec.lane == "grounding"
        and not spec.signals
        and not spec.relevance_hint
        and spec.targeting == "none"
        and spec.auth == "none"
        and not spec.env
        and spec.access == "open"
    )
    assert not is_stub, (
        f"source {spec.source_id!r}: still on the default/empty grounding stub spec "
        "(no signals, no relevance_hint) — declare a real SourceSpec at register_source"
    )


def check_targeting_has_picker(
    spec: SourceSpec,
    *,
    registered_targetings: frozenset[str],
) -> None:
    """Rule 7 — every non-``none`` targeting a source declares has a registered picker.

    A source that says it targets by ``subreddit`` / ``slug`` / ``keyword`` / ``instance``
    needs a picker in the 0.4 registry to turn a brief into per-target knobs; a declared
    targeting with no picker would have nothing to vary on at selection time.
    """
    if spec.targeting == "none":
        return
    assert spec.targeting in registered_targetings, (
        f"source {spec.source_id!r}: targeting {spec.targeting!r} has no registered "
        f"target picker (registered: {sorted(registered_targetings)})"
    )


def check_keys_env_only(spec: SourceSpec | MagnitudeSpec) -> None:
    """Keys-env-only — an authed spec names UPPER_SNAKE env var(s), never a secret value.

    ``SourceSpec.__post_init__`` already requires an authed spec to declare a non-empty
    ``env`` (so the catalog can name what to set); this adds that each declared entry is
    an env-var *name* (the shape the ``config.py`` ``resolve_*`` pattern reads off
    ``os.environ``), not a literal credential pasted into the spec. The actual read path
    is env-only by construction (``resolve_search`` / ``_has_key`` only touch
    ``os.environ``); this guards the declaration against a config-file-secret smell.
    """
    sid = getattr(spec, "source_id", None) or getattr(spec, "provider_id", "?")
    if spec.auth in _AUTHED_KINDS:
        assert spec.env, f"authed spec {sid!r}: must declare env var(s)"
    for var in spec.env:
        assert _ENV_VAR_NAME.match(var), (
            f"spec {sid!r}: env entry {var!r} is not an UPPER_SNAKE env-var name — "
            "declare the variable NAME the resolve_* pattern reads, never a secret value"
        )


def _spec_yields_units(
    spec: SourceSpec,
    *,
    sources: Mapping[str, SourceFactory],
    fixture_kwargs: Mapping[str, object],
) -> bool:
    """Whether ``spec``'s connector is a ``yields_units`` source (rule-5 exempt).

    ``yields_units`` is a connector CLASS attribute, not a spec field, so we read it
    off a constructed instance (via the real factory with the offline ``fixture_kwargs``).
    A spec with no factory, or one whose optional extra isn't installed (the bare CI
    matrix), is treated as NOT a unit source — its real signal declaration is then held
    to rule 5, which is the safe default (a non-unit grounding source must declare one).
    """
    factory = sources.get(spec.source_id)
    if factory is None:
        return False
    try:
        source = factory(**dict(fixture_kwargs))
    except Exception:
        return False
    return bool(getattr(source, "yields_units", False))


def check_lane_conformance(
    *,
    source_specs: Mapping[str, SourceSpec],
    magnitude_specs: Mapping[str, MagnitudeSpec],
    sources: Mapping[str, SourceFactory],
    magnitude_providers: Mapping[str, MagnitudeFactory],
    signal_specs: Mapping[str, SignalSpec],
    registered_targetings: frozenset[str],
    source_fixtures: Mapping[str, Mapping[str, object]],
) -> None:
    """Run the full 0.5 lane-conformance sweep over both registries.

    The registry-level backstop for going wide. Asserts, across every registered
    source + magnitude provider, the cross-source lane discipline ``SourceSpec.__post_init__``
    can't see (it validates one spec; these are the rules BETWEEN registries):

    1. Every ``grounding`` id is constructible via :func:`get_source` (with the
       caller's offline ``source_fixtures[id]`` deps) and yields ≥1 quotable record.
    2. No ``magnitude`` lane id appears in ``SOURCES``.
    3. No ``blocked`` id appears in ``SOURCES`` or ``MAGNITUDE_PROVIDERS``.
    4. Every kind in a spec's ``signals`` is registered in ``SIGNAL_SPECS``.
    5. A ``grounding`` lane declares ≥1 non-``is_magnitude`` signal.
    6. ``spec`` is effectively required — the default/empty stub fails.
    7. Every non-``none`` targeting a source declares has a registered picker.

    Plus the keys-env-only declaration guard. ``source_fixtures`` maps each grounding
    ``source_id`` to the offline ``get_source`` kwargs (stub client / fake reader) that
    let rule 1 pull without a network — a grounding source with no fixture fails loudly
    (the sweep must cover every shipped grounding id, not silently skip one).
    """
    assert source_specs, "SOURCE_SPECS is empty — import the built-in connectors first"
    assert magnitude_specs, "MAGNITUDE_SPECS is empty — import the magnitude module first"

    check_no_magnitude_in_sources(source_specs=source_specs, sources=sources)
    check_no_blocked_magnitude(magnitude_specs=magnitude_specs)

    for spec in source_specs.values():
        check_signals_registered(spec, signal_specs=signal_specs)
        check_grounding_has_grounding_signal(
            spec,
            signal_specs=signal_specs,
            yields_units=_spec_yields_units(
                spec, sources=sources, fixture_kwargs=source_fixtures.get(spec.source_id, {})
            ),
        )
        check_spec_not_stub(spec)
        check_targeting_has_picker(spec, registered_targetings=registered_targetings)
        check_keys_env_only(spec)
        if spec.lane == "grounding":
            assert spec.source_id in source_fixtures, (
                f"grounding source {spec.source_id!r} has no offline fixture in the sweep "
                "— add its get_source kwargs to source_fixtures so rule 1 can pull it"
            )
            check_grounding_constructible(
                spec, sources=sources, fixture_kwargs=source_fixtures[spec.source_id]
            )

    for mspec in magnitude_specs.values():
        check_signals_registered(mspec, signal_specs=signal_specs)
        check_keys_env_only(mspec)


def check_all_repos(backend: AllRepos, *, corpus_rows: int = 1500) -> None:
    """Run every repo conformance check against one backend instance.

    Use a fresh/empty backend — the checks write `mwtest-` prefixed rows.
    """
    check_brief_repo(backend)
    check_run_repo(backend)
    check_corpus_repo(backend, rows=corpus_rows)
    check_account_repo(backend)
    check_opportunity_repo(backend)
    check_inbox_repo(backend)


_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def check_page_renderer(renderer: PageRenderer, *, url: str = "https://example.com") -> None:
    """Assert that ``renderer`` honors the :class:`~metalworks.render.PageRenderer` contract.

    A renderer adapter self-verifies with this before shipping. Point it at a
    reachable ``url`` (a real page for Playwright/Firecrawl, anything for the
    Fake). It checks the surface every consumer relies on:

    * ``renderer_id`` is a non-empty string and ``capabilities`` is a
      :class:`~metalworks.render.RendererCapabilities`.
    * ``render()`` returns a :class:`~metalworks.render.RenderedPage` whose
      ``screenshot`` is PNG bytes (or empty), ``html`` is a string, and
      ``final_url`` is set.
    * if ``capabilities.supports_style_audit``: ``extract_computed_styles()``
      yields :class:`~metalworks.render.ComputedStyle`; otherwise it raises
      :class:`~metalworks.errors.StyleAuditUnsupported`.
    """
    assert isinstance(renderer.renderer_id, str) and renderer.renderer_id, (
        "renderer_id must be a non-empty string"
    )
    assert isinstance(renderer.capabilities, RendererCapabilities), (
        "capabilities must be a RendererCapabilities"
    )

    page = renderer.render(url)
    assert isinstance(page, RenderedPage), f"render() must return RenderedPage, got {type(page)!r}"
    assert isinstance(page.screenshot, bytes), "screenshot must be bytes"
    assert page.screenshot[:8] == _PNG_MAGIC or page.screenshot == b"", (
        "screenshot must be PNG bytes (or empty when the backend couldn't capture)"
    )
    assert isinstance(page.html, str), "html must be a string"
    assert page.final_url, "final_url must be set (resolved URL after redirects)"

    if renderer.capabilities.supports_style_audit:
        styles = renderer.extract_computed_styles(url, ["body"])
        assert all(isinstance(s, ComputedStyle) for s in styles), (
            "extract_computed_styles() must yield ComputedStyle"
        )
    else:
        raised = False
        try:
            renderer.extract_computed_styles(url, ["body"])
        except StyleAuditUnsupported:
            raised = True
        assert raised, (
            "a screenshot-only renderer (supports_style_audit=False) must raise "
            "StyleAuditUnsupported from extract_computed_styles()"
        )


__all__ = [
    "AllRepos",
    "FakeChatModel",
    "FakeEmbedding",
    "FakeMagnitudeProvider",
    "FakeRenderer",
    "check_account_repo",
    "check_all_repos",
    "check_brief_repo",
    "check_corpus_repo",
    "check_grounding_constructible",
    "check_grounding_has_grounding_signal",
    "check_inbox_repo",
    "check_item_source",
    "check_keys_env_only",
    "check_lane_conformance",
    "check_magnitude_provider",
    "check_no_blocked_magnitude",
    "check_no_magnitude_in_sources",
    "check_opportunity_repo",
    "check_page_renderer",
    "check_run_repo",
    "check_signals_registered",
    "check_spec_not_stub",
    "check_targeting_has_picker",
]
