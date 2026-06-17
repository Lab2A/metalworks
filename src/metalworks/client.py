"""The high-level ``Metalworks`` client — the front door.

Everything in metalworks is composable from the underlying functions
(:func:`~metalworks.research.run_research`, :func:`~metalworks.discovery.run_discovery`,
the protocols, the typed repos). This facade is the easy path on top of them:
construct one object and call ``.research(...)``, ``.reddit.search(...)``,
``.discovery.run(...)``. Nothing is constructed until a call needs it, so a
bare ``Metalworks()`` with no API keys still serves the zero-key surfaces (the
Reddit reads and the deterministic compliance gate).

This module imports no provider SDK, ``duckdb``, ``redditwarp``, or ``mcp`` at
top level — every such symbol is imported inside the method that needs it, so
``import metalworks`` stays free on a bare install.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from pathlib import Path

    from metalworks.contract import (
        Assessment,
        BuildSpec,
        ChannelPlan,
        CompetitorMap,
        ContentPlan,
        DemandReport,
        DiscoveryContext,
        IdeaSketch,
        IdeationResult,
        InboxItem,
        Landscape,
        LaunchAsset,
        MarketingSite,
        Opportunity,
        Persona,
        PositioningBrief,
        RedditComment,
        RedditPost,
        ReportDiff,
        Research,
        ResearchBrief,
        SubredditIntel,
        SurfaceKind,
        SurfaceRecommendation,
        UxSkeleton,
        ValidationResult,
    )
    from metalworks.discovery.prompts import FilterDecision, ReplyGenerationV2
    from metalworks.embeddings import EmbeddingProvider
    from metalworks.llm import ChatModel
    from metalworks.reddit import PostResult, RateLimiter, RedditSearch
    from metalworks.research import ResearchDeps
    from metalworks.research.deps import CommentSource, CorpusReader
    from metalworks.research.sources import ItemSource
    from metalworks.research.synthesis.demand import AssessPolicy
    from metalworks.search import SearchProvider
    from metalworks.stores import MemoryStores, SqliteStores

    Store = MemoryStores | SqliteStores


def _demand(research: Research | DemandReport) -> DemandReport:
    """Accept the `Research` bundle (what `.research()` returns) or a bare
    `DemandReport`, and return the `DemandReport` the pillars run on."""
    return cast("DemandReport", getattr(research, "demand", research))


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
        fallback_models: list[str] | None = None,
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
        self._fallback_models = fallback_models
        self._search_resolved = False
        self._comments_resolved = False
        self._limiter_obj: RateLimiter | None = None
        self._reddit_obj: RedditSearch | None = None

    def chat(self) -> ChatModel:
        if self._chat is None:
            from metalworks import config

            # Opt-in failover: wraps in a FallbackChatModel only when ≥1 fallback
            # ref is configured (arg here, else the config file). With none, this
            # returns exactly config.resolve_chat(self._model) — no wrapper.
            self._chat = config.resolve_chat_chain(
                self._model, fallback_models=self._fallback_models
            )
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
            from metalworks import config

            # No-footprint: a project's corpus.db inside `.metalworks/`, else an
            # in-process MemoryStores that persists nothing.
            self._store = config.auto_store()
        return self._store

    def reader(self) -> CorpusReader:
        if self._reader is None:
            import os

            if (os.environ.get("ARCTIC_SHIFT_SOURCE") or "").strip().lower() == "mirror":
                # Supabase Storage mirror tier (metalworks[supabase]) — faster
                # than HF and removes it as a runtime dependency.
                from metalworks.research.arctic import ArcticMirrorReader

                self._reader = ArcticMirrorReader()
            else:
                from metalworks.research.arctic import ArcticReader

                self._reader = ArcticReader(probe_sleep_s=0.0)
        return self._reader

    def search(self) -> SearchProvider | None:
        if not self._search_resolved and self._search is None:
            from metalworks import config

            self._search = config.resolve_search()
        self._search_resolved = True
        return self._search

    def comments(self) -> CommentSource | None:
        if not self._comments_resolved and self._comments is None:
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

    def sources(self) -> list[ItemSource]:
        """The configured ItemSource connectors — default Reddit/Arctic.

        Built here as the single place the default source is chosen. For now the
        default is Reddit/Arctic, derived from the resolved reader + comment
        client; which-source-is-default stays configurable by a later
        ``[sources]`` config stream without re-plumbing this seam.
        """
        from metalworks.research.sources.arctic import ArcticItemSource

        return [ArcticItemSource(reader=self.reader(), comments=self.comments())]

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
            sources=self.sources(),
        )


class Metalworks:
    """One-object entry point to the research, Reddit, and discovery surfaces.

    All constructor arguments are optional. Anything not supplied is resolved
    lazily on first use: chat / embeddings / external search from the ambient
    API keys (see :mod:`metalworks.config`), the store as an in-memory backend,
    and the corpus reader as the Hugging Face Arctic mirror. Pass ``model`` /
    ``fast_model`` as ``provider:id`` or ``provider/model`` refs to pick a
    provider explicitly, or pass fully-constructed objects to swap any layer.

    ``fallback_models`` is an opt-in ordered list of additional model refs: when
    the primary chat model fails with a retryable error (rate limit / transient),
    the chain tries each fallback in turn. With none configured (the default),
    the chat model is exactly the single resolved model — no wrapper, no change.
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
        fallback_models: list[str] | None = None,
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
            fallback_models=fallback_models,
        )
        self._reddit_ns: _RedditNamespace | None = None
        self._discovery_ns: _DiscoveryNamespace | None = None

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
        window defaults to 12 months.

        The demand report is on ``.demand``; ``.evidence`` surfaces its grounded
        evidence on the bundle. ``.competitors`` / ``.positioning`` are reserved
        for the landscape and positioning pillars and are ``None`` until they
        ship — so today this returns one demand report wrapped for forward
        compatibility, and the front door's return shape never breaks as the
        stage grows.
        """
        from metalworks.contract import Research, ResearchBrief
        from metalworks.research import run_research
        from metalworks.research.planner import brief_from_question

        deps = self._r.research_deps()
        if isinstance(question, ResearchBrief):
            brief = question
        else:
            window = time_window_months if time_window_months is not None else 12
            brief = brief_from_question(
                deps, question, subreddits=subreddits, time_window_months=window
            )
        report = run_research(
            deps, brief=brief, per_sub_limit=per_sub_limit, max_findings=max_findings
        )
        result = Research(demand=report)
        # Persist as committed files when run inside a `.metalworks/` project;
        # casual use (no project) leaves no footprint.
        from metalworks.project import Project

        project = Project.find()
        if project is not None:
            from metalworks.runs import write_run

            write_run(project, result, question=brief.question)
        return result

    def refresh(self, prior: Research | DemandReport) -> tuple[Research, ReportDiff]:
        """Re-synthesize a prior report against the current corpus.

        Returns ``(research, diff)``: a new :class:`~metalworks.contract.Research`
        bundle pinned as the next version in ``prior``'s lineage, and the
        :class:`~metalworks.contract.ReportDiff` from ``prior`` to it. A report is
        a live view — re-running its brief picks up corpus growth (new sources,
        freshly ingested material) while the prior version stays frozen. Persists
        the new version as committed files when run inside a project, like
        :meth:`research`.
        """
        from metalworks.contract import Research
        from metalworks.research.refresh import refresh_report

        new_report, diff = refresh_report(self._r.research_deps(), _demand(prior))
        result = Research(demand=new_report)
        from metalworks.project import Project

        project = Project.find()
        if project is not None:
            from metalworks.runs import write_run

            write_run(project, result, question=new_report.query, diff=diff)
        return result, diff

    def plan(self, prompt: str) -> ResearchBrief:
        """Walk the D1-D8 planner (recommended answers) → a ``ResearchBrief``."""
        from metalworks.research.planner import plan_brief

        return plan_brief(self._r.research_deps(), prompt)

    # ── the pillar arc (each runs on a finished `research()` bundle) ──────────

    @property
    def deps(self) -> ResearchDeps:
        """The resolved :class:`~metalworks.research.ResearchDeps` this client
        threads through every pillar — the escape hatch for composing the raw
        pillar functions yourself without rebuilding chat / embeddings / corpus /
        reader by hand."""
        return self._r.research_deps()

    def positioning(self, research: Research | DemandReport) -> PositioningBrief:
        """Pillar B — a grounded Dunford positioning wedge + price hypothesis."""
        from metalworks.research import build_positioning_brief

        return build_positioning_brief(self.deps, _demand(research))

    def competitors(self, research: Research | DemandReport) -> CompetitorMap:
        """Pillar A — direct / adjacent / status-quo rivals, each gap cited."""
        from metalworks.research import run_competitor_map

        return run_competitor_map(self.deps, _demand(research))

    def landscape(self, research: Research | DemandReport) -> Landscape:
        """Pillar A (thick) — the competitor map PLUS an empirical existing-solutions
        scan (real shipped products, with traction, matched to demand clusters).
        This is the 'what exists today' surface ``assess()`` consumes."""
        from metalworks.research import run_landscape

        return run_landscape(self.deps, _demand(research))

    def ideate(self, idea: str) -> IdeaSketch:
        """Idea-first ideation — sharpen a raw idea into a testable hypothesis plus
        a brief to run demand on. The front of the validate loop."""
        from metalworks.research import ideate_from_idea

        return ideate_from_idea(self.deps, idea)

    def ideate_from_evidence(self, research: Research | DemandReport) -> IdeationResult:
        """Evidence-first ideation — surface an existing report's forks (candidate
        wedges, else top clusters) as grounded idea sketches to pick from."""
        from metalworks.research import ideate_from_report

        return ideate_from_report(self.deps, _demand(research))

    def assess(
        self,
        research: Research | DemandReport,
        landscape: Landscape,
        *,
        policy: AssessPolicy | None = None,
    ) -> Assessment:
        """The GO / PIVOT / NO-GO verdict — a deterministic gap over demand (does the
        pain exist) and landscape (can people already solve it). Demand is relative and
        self-calibrating; the verdict is computed per fork (see ``assessment.fork_verdicts``)
        and synthesized. PIVOT carries a target fork; a partial landscape never yields GO.
        Pass ``policy`` (an ``AssessPolicy``) to override the surfaced thresholds."""
        from metalworks.research import run_assessment
        from metalworks.research.synthesis.demand import DEFAULT_POLICY

        return run_assessment(
            self.deps, _demand(research), landscape, policy=policy or DEFAULT_POLICY
        )

    def validate(self, idea: str, *, max_iterations: int = 4) -> ValidationResult:
        """Run the validate loop headlessly (--auto): ideate → demand → landscape → assess,
        looping on PIVOT toward the under-served fork until GO, NO-GO, or exhausted. The
        interactive, human-gated loop lives in the `validate` Claude Code skill."""
        from metalworks.research import validate as _validate

        return _validate(self.deps, idea, max_iterations=max_iterations)

    def surface(
        self, research: Research | DemandReport, positioning: PositioningBrief
    ) -> SurfaceRecommendation:
        """Pillar C — the grounded surface recommendation (sdk/web/mobile/...)."""
        from metalworks.research import decide_surface

        return decide_surface(self.deps, _demand(research), positioning)

    def ux(
        self,
        research: Research | DemandReport,
        positioning: PositioningBrief,
        surface: SurfaceKind,
    ) -> UxSkeleton:
        """Pillar C — a 3-5 screen UX skeleton for the chosen ``surface``."""
        from metalworks.research import build_ux_skeleton

        return build_ux_skeleton(self.deps, _demand(research), positioning, surface)

    def site(
        self, research: Research | DemandReport, positioning: PositioningBrief | None = None
    ) -> MarketingSite:
        """Pillar E — a grounded marketing site (verbatim, cited copy)."""
        from metalworks.research import build_marketing_site

        return build_marketing_site(self.deps, _demand(research), positioning)

    def render_site(
        self, site: MarketingSite, research: Research | DemandReport | None = None
    ) -> str:
        """Render a :class:`MarketingSite` to a self-contained ``index.html``."""
        from metalworks.research import render_site_html

        return render_site_html(site, _demand(research) if research is not None else None)

    def build_spec(
        self,
        research: Research | DemandReport,
        positioning: PositioningBrief | None = None,
        surface: SurfaceKind = "web",
        *,
        stack: str = "empty",
    ) -> BuildSpec:
        """Pillar D — an evidence-grounded :class:`BuildSpec` for a coding agent."""
        from metalworks.build import build_spec_from_report

        return build_spec_from_report(
            self.deps, _demand(research), positioning, surface, stack=stack
        )

    def scaffold(
        self,
        spec: BuildSpec,
        research: Research | DemandReport,
        dest: Path,
        *,
        base: str = "empty",
    ) -> list[Path]:
        """Pillar D — write the cite-or-die build harness under ``dest``."""
        from metalworks.build import scaffold

        return scaffold(spec, _demand(research), dest, base=base)

    def launch(
        self, research: Research | DemandReport, positioning: PositioningBrief | None = None
    ) -> list[LaunchAsset]:
        """Pillar F — channel-native cited launch drafts (drafting only, never posts)."""
        from metalworks.research import build_launch_assets

        return build_launch_assets(self.deps, _demand(research), positioning)

    def channel_plan(
        self, research: Research | DemandReport, surfaces: list[str] | None = None
    ) -> ChannelPlan:
        """Pillar F — a deterministic, human-executed launch sequence."""
        from metalworks.research import plan_channels

        return plan_channels(_demand(research), surfaces)

    def content_plan(self, research: Research | DemandReport) -> ContentPlan:
        """Pillar G — a deterministic, zero-key content/SEO plan."""
        from metalworks.research import content_plan_from_report

        return content_plan_from_report(_demand(research))

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
