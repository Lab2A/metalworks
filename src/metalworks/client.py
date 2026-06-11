"""The high-level ``Metalworks`` client — the front door.

Everything in metalworks is composable from the underlying functions
(:func:`~metalworks.research.run_research`, :func:`~metalworks.discovery.run_discovery`,
the protocols, the typed repos). This facade is the easy path on top of them:
construct one object and call ``.research(...)``, ``.reddit.search(...)``,
``.discovery.run(...)``. Nothing is constructed until a call needs it, so a
bare ``Metalworks()`` with no API keys still serves the zero-key surfaces, and
``Metalworks.demo()`` runs the whole research pipeline offline with no keys and
no network.

This module imports no provider SDK, ``duckdb``, ``redditwarp``, or ``mcp`` at
top level — every such symbol is imported inside the method that needs it, so
``import metalworks`` stays free on a bare install.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from metalworks.contract import (
        DiscoveryContext,
        InboxItem,
        Opportunity,
        Persona,
        RedditComment,
        RedditPost,
        Research,
        ResearchBrief,
        SubredditIntel,
    )
    from metalworks.discovery.prompts import FilterDecision, ReplyGenerationV2
    from metalworks.embeddings import EmbeddingProvider
    from metalworks.llm import ChatModel
    from metalworks.reddit import PostResult, RateLimiter, RedditSearch
    from metalworks.research import ResearchDeps
    from metalworks.research.deps import CommentSource, CorpusReader
    from metalworks.search import SearchProvider
    from metalworks.stores import MemoryStores, SqliteStores

    Store = MemoryStores | SqliteStores


def _new_id() -> str:
    return str(uuid.uuid4())


class _Resolver:
    """Shared, lazily-memoized dependency resolver.

    Holds the optional explicit objects passed to :class:`Metalworks` and
    resolves anything missing on first use — chat / embeddings / search from the
    ambient API keys, the store as in-memory, the reader as the Arctic mirror.
    One instance is shared by the client and its namespaces so the resolved
    objects (notably the Reddit client and its single rate limiter) are reused
    across every call. Its methods are the internal API the namespaces call.
    """

    def __init__(
        self,
        *,
        chat: ChatModel | None,
        fast_chat: ChatModel | None,
        embeddings: EmbeddingProvider | None,
        store: Store | None,
        reader: CorpusReader | None,
        search: SearchProvider | None,
        comments: CommentSource | None,
        model: str | None,
        fast_model: str | None,
        offline: bool,
    ) -> None:
        self._chat = chat
        self._fast_chat = fast_chat
        self._embeddings = embeddings
        self._store = store
        self._reader = reader
        self._search = search
        self._comments = comments
        self._model = model
        self._fast_model = fast_model
        self.offline = offline
        self._search_resolved = False
        self._comments_resolved = False
        self._limiter_obj: RateLimiter | None = None
        self._reddit_obj: RedditSearch | None = None

    def chat(self) -> ChatModel:
        if self._chat is None:
            from metalworks import config

            self._chat = config.resolve_chat(self._model)
        return self._chat

    def fast_chat(self) -> ChatModel | None:
        if self._fast_chat is None and self._fast_model is not None:
            from metalworks import config

            self._fast_chat = config.resolve_chat(self._fast_model)
        return self._fast_chat

    def embeddings(self) -> EmbeddingProvider:
        if self._embeddings is None:
            from metalworks import config

            self._embeddings = config.resolve_embeddings()
        return self._embeddings

    def store(self) -> Store:
        if self._store is None:
            from metalworks.stores import MemoryStores

            self._store = MemoryStores()
        return self._store

    def reader(self) -> CorpusReader:
        if self._reader is None:
            from metalworks.research.arctic import ArcticReader

            self._reader = ArcticReader(probe_sleep_s=0.0)
        return self._reader

    def search(self) -> SearchProvider | None:
        if not self._search_resolved and self._search is None and not self.offline:
            from metalworks import config

            self._search = config.resolve_search()
        self._search_resolved = True
        return self._search

    def comments(self) -> CommentSource | None:
        if not self._comments_resolved and self._comments is None and not self.offline:
            from metalworks.research.arctic import ArcticShiftApiClient

            self._comments = ArcticShiftApiClient()
        self._comments_resolved = True
        return self._comments

    def limiter(self) -> RateLimiter:
        if self._limiter_obj is None:
            from metalworks.reddit import RateLimiter

            self._limiter_obj = RateLimiter()
        return self._limiter_obj

    def reddit_search(self) -> RedditSearch:
        if self._reddit_obj is None:
            from metalworks.reddit import RedditSearch

            self._reddit_obj = RedditSearch(limiter=self.limiter())
        return self._reddit_obj

    def research_deps(self) -> ResearchDeps:
        from metalworks.research import ResearchDeps

        return ResearchDeps(
            chat=self.chat(),
            fast_chat=self.fast_chat(),
            embeddings=self.embeddings(),
            corpus=self.store(),
            reader=self.reader(),
            search=self.search(),
            comments=self.comments(),
        )


class Metalworks:
    """One-object entry point to the research, Reddit, and discovery surfaces.

    All constructor arguments are optional. Anything not supplied is resolved
    lazily on first use: chat / embeddings / external search from the ambient
    API keys (see :mod:`metalworks.config`), the store as an in-memory backend,
    and the corpus reader as the Hugging Face Arctic mirror. Pass ``model`` /
    ``fast_model`` as ``provider:id`` or ``provider/model`` refs to pick a
    provider explicitly, or pass fully-constructed objects to swap any layer.
    """

    def __init__(
        self,
        *,
        chat: ChatModel | None = None,
        fast_chat: ChatModel | None = None,
        embeddings: EmbeddingProvider | None = None,
        store: Store | None = None,
        reader: CorpusReader | None = None,
        search: SearchProvider | None = None,
        comments: CommentSource | None = None,
        model: str | None = None,
        fast_model: str | None = None,
        _offline: bool = False,
    ) -> None:
        self._r = _Resolver(
            chat=chat,
            fast_chat=fast_chat,
            embeddings=embeddings,
            store=store,
            reader=reader,
            search=search,
            comments=comments,
            model=model,
            fast_model=fast_model,
            offline=_offline,
        )
        self._reddit_ns: _RedditNamespace | None = None
        self._discovery_ns: _DiscoveryNamespace | None = None

    @classmethod
    def demo(cls) -> Metalworks:
        """A fully offline facade — fake models + a bundled local corpus.

        ``Metalworks.demo().research("...", subreddits=["Supplements"])`` runs the
        whole pipeline with **zero API keys and zero network** and returns a
        small :class:`~metalworks.contract.Research` bundle (its ``.demand`` is a
        :class:`~metalworks.contract.research.DemandReport`), so you can see the
        output shape before plugging in a provider. Requires the ``[arctic]``
        extra (duckdb) for the local corpus.
        """
        import tempfile
        from pathlib import Path

        from metalworks.embeddings import FakeEmbedding
        from metalworks.errors import MissingExtraError
        from metalworks.llm.fake import FakeChatModel
        from metalworks.stores import MemoryStores

        try:
            from metalworks.cli._demo import write_demo_corpus
            from metalworks.research.arctic import ArcticReader

            root = Path(tempfile.mkdtemp(prefix="metalworks-demo-"))
            write_demo_corpus(root)
            reader = ArcticReader(data_root=str(root), probe_sleep_s=0.0)
        except ImportError as exc:  # duckdb missing
            raise MissingExtraError("arctic", package="duckdb") from exc

        return cls(
            chat=FakeChatModel(),
            fast_chat=FakeChatModel(),
            embeddings=FakeEmbedding(),
            store=MemoryStores(),
            reader=reader,
            _offline=True,
        )

    # ── research ────────────────────────────────────────────────────────────

    def research(
        self,
        question: str | ResearchBrief,
        *,
        subreddits: list[str] | None = None,
        time_window_months: int | None = None,
        per_sub_limit: int | None = None,
        max_findings: int = 10,
    ) -> Research:
        """Run stage 1 ("Research") → a frozen :class:`~metalworks.contract.Research` bundle.

        Pass a plain ``question`` (and optionally the ``subreddits`` to cover; if
        omitted, the planner picks them) or a fully-formed
        :class:`~metalworks.contract.ResearchBrief` for full control. The corpus
        window defaults to 12 months (1 month in ``demo()`` mode, where the
        bundled corpus is a single month).

        The demand report is on ``.demand``; ``.evidence`` surfaces its grounded
        evidence on the bundle. ``.competitors`` / ``.positioning`` are reserved
        for the landscape and positioning pillars and are ``None`` until they
        ship — so today this returns one demand report wrapped for forward
        compatibility, and the front door's return shape never breaks as the
        stage grows.
        """
        from metalworks.contract import Research, ResearchBrief, TargetSubreddit
        from metalworks.research import run_research

        deps = self._r.research_deps()
        if isinstance(question, ResearchBrief):
            brief = question
        else:
            window = (
                time_window_months
                if time_window_months is not None
                else (1 if self._r.offline else 12)
            )
            targets = [
                TargetSubreddit(name=s, rationale="caller-specified") for s in (subreddits or [])
            ]
            brief = ResearchBrief(
                brief_id=_new_id(),
                question=question,
                decision_context="Assess the Reddit demand signal behind this question.",
                success_criteria=["Surface the top unmet needs and the demand signal."],
                must_address=[],
                target_subreddits=targets,
                web_research_directions=[],
                relevance_rubric=f"Posts and comments relevant to: {question}",
                time_window_months=window,
            )
            if not targets:
                from metalworks.research.planner import pick_target_subreddits

                brief = brief.model_copy(
                    update={"target_subreddits": pick_target_subreddits(deps, brief=brief)}
                )
        report = run_research(
            deps, brief=brief, per_sub_limit=per_sub_limit, max_findings=max_findings
        )
        return Research(demand=report)

    def plan(self, prompt: str) -> ResearchBrief:
        """Walk the D1-D8 planner (recommended answers) → a ``ResearchBrief``."""
        from metalworks.research.planner import plan_brief

        return plan_brief(self._r.research_deps(), prompt)

    # ── namespaces ──────────────────────────────────────────────────────────

    @property
    def reddit(self) -> _RedditNamespace:
        """Reddit surfaces: ``.search``, ``.subreddit``, ``.comments``, ``.rules``,
        ``.inbox``, ``.post``. The Reddit client and its rate limiter are shared
        across calls on this instance."""
        if self._reddit_ns is None:
            self._reddit_ns = _RedditNamespace(self._r)
        return self._reddit_ns

    @property
    def discovery(self) -> _DiscoveryNamespace:
        """Discovery surfaces: ``.run`` (the loop) plus the ``.filter`` and
        ``.generate`` building blocks."""
        if self._discovery_ns is None:
            self._discovery_ns = _DiscoveryNamespace(self._r)
        return self._discovery_ns


class _RedditNamespace:
    """Reddit read/intel surfaces + gated posting."""

    def __init__(self, resolver: _Resolver) -> None:
        self._r = resolver

    def search(
        self, query: str, *, subreddit: str | None = None, limit: int = 15
    ) -> list[RedditPost]:
        """Search public Reddit submissions (zero-key)."""
        return self._r.reddit_search().search_posts(query, subreddit=subreddit, limit=limit)

    def subreddit(self, name: str) -> SubredditIntel:
        """Community intel: description, subscribers, rules, top posts (zero-key)."""
        from metalworks.reddit import fetch_subreddit_intel

        return fetch_subreddit_intel(name, limiter=self._r.limiter())

    def comments(self, post_url: str, *, limit: int = 10) -> list[RedditComment]:
        """Top-level comments for a public post URL (zero-key)."""
        return self._r.reddit_search().get_post_comments(post_url, limit=limit)

    def rules(self, name: str) -> list[str]:
        """A subreddit's posting rules (zero-key)."""
        return self._r.reddit_search().get_subreddit_rules(name)

    def inbox(self, *, access_token: str, limit: int = 25) -> list[InboxItem]:
        """Classified inbox items for an authenticated account."""
        from metalworks.reddit import fetch_inbox

        return fetch_inbox(access_token=access_token, limiter=self._r.limiter(), limit=limit)

    def post(self, post_url: str, text: str, *, username: str) -> PostResult:
        """Post a reply — gated and audited.

        Runs the deterministic compliance check first and refuses on a block
        verdict (returning a failed :class:`~metalworks.reddit.PostResult`);
        every attempt, blocked or sent, is appended to
        ``~/.metalworks/post-log.jsonl``. Requires ``REDDIT_CLIENT_ID`` /
        ``REDDIT_CLIENT_SECRET`` and a previously connected account.
        """
        from metalworks.reddit import PostResult, RedditOAuth, heuristic_check
        from metalworks.reddit.audit import append_post_log
        from metalworks.stores import TokenCipher

        verdict = heuristic_check(text)
        if not verdict.pass_:
            append_post_log(
                {
                    "action": "post_blocked",
                    "url": post_url,
                    "username": username,
                    "success": False,
                    "violations": list(verdict.violations),
                }
            )
            return PostResult(
                success=False,
                username=username,
                error="Blocked by compliance gate: " + "; ".join(verdict.violations),
            )
        oauth = RedditOAuth(
            accounts=self._r.store(),
            cipher=TokenCipher(),
            limiter=self._r.limiter(),
        )
        return oauth.post_comment(username=username, post_url=post_url, text=text)


class _DiscoveryNamespace:
    """The discovery loop plus its standalone filter / reply-generation seams."""

    def __init__(self, resolver: _Resolver) -> None:
        self._r = resolver

    def run(
        self,
        queries: list[str],
        *,
        subreddits: list[str] | None = None,
        max_opportunities: int = 30,
        context: DiscoveryContext | None = None,
    ) -> list[Opportunity]:
        """Search → filter → generate → gate over ``queries`` → ``Opportunity`` list."""
        from metalworks.contract import DiscoveryContext
        from metalworks.discovery import DiscoveryDeps, run_discovery

        deps = DiscoveryDeps(
            chat=self._r.chat(),
            fast_chat=self._r.fast_chat(),
            search=self._r.reddit_search(),
            opportunities=self._r.store(),
            context=context or DiscoveryContext(),
        )
        return run_discovery(
            deps,
            queries=list(queries),
            subreddits=subreddits,
            max_opportunities=max_opportunities,
        )

    def filter(
        self, post: RedditPost, *, context: DiscoveryContext | None = None
    ) -> FilterDecision | None:
        """Relevance-filter one post in your context (a building block)."""
        from metalworks.contract import DiscoveryContext
        from metalworks.discovery import filter_post

        return filter_post(self._r.chat(), post, context or DiscoveryContext())

    def generate(
        self,
        post: RedditPost,
        *,
        persona: Persona | None = None,
        account_type: str = "expert",
        context: DiscoveryContext | None = None,
        subreddit_rules: list[str] | None = None,
    ) -> ReplyGenerationV2 | None:
        """Draft a reply to one thread in your voice (a building block)."""
        from metalworks.contract import DiscoveryContext, Persona
        from metalworks.discovery import draft_reply

        return draft_reply(
            self._r.chat(),
            post,
            persona or Persona(),
            account_type,
            context or DiscoveryContext(),
            subreddit_rules=subreddit_rules,
            fast_chat=self._r.fast_chat(),
        )


__all__ = ["Metalworks"]
