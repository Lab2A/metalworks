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

from typing import TYPE_CHECKING, Literal, cast

if TYPE_CHECKING:
    from pathlib import Path

    from metalworks.contract import (
        Assessment,
        BuildSpec,
        ChannelAsset,
        ChannelStrategy,
        DataReportAsset,
        DemandReport,
        DesignReview,
        DesignSystem,
        DiscoveryContext,
        GeoPlan,
        IdeaSketch,
        IdeationResult,
        InboxItem,
        Landscape,
        LogoSet,
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

        Delegates to :func:`~metalworks.config.resolve_sources`, which maps the
        ordered ``[sources].enabled`` ids (default ``["reddit"]``) through the
        registry, passing this client's Reddit ``reader`` / ``comments`` so the
        Arctic connector is wired while keyless / non-Reddit connectors ignore
        them. With no ``[sources]`` config this returns exactly the prior default
        — one ``ArcticItemSource`` over the resolved reader + comment client — so
        enabling another source (e.g. ``hackernews_archive``) now actually *adds*
        it to what research ingests, rather than being silently inert.
        """
        from metalworks.config import resolve_sources

        return resolve_sources(reader=self.reader(), comments=self.comments())

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
        from metalworks.research.planner import brief_or_question

        deps = self._r.research_deps()
        window = time_window_months if time_window_months is not None else 12
        brief = brief_or_question(
            deps,
            question if isinstance(question, ResearchBrief) else None,
            question if isinstance(question, str) else "",
            subreddits=subreddits,
            time_window_months=window,
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

    def channel_strategy(
        self,
        research: Research | DemandReport,
        positioning: PositioningBrief | None = None,
    ) -> ChannelStrategy:
        """Distribution (D2) — route the report's named entities + signals into the
        structured channel space as **test→focus** channel experiments (not a ranked
        portfolio). Selection is deterministic where it can be; the LLM classifies the
        product type / writes the ICP line; every channel's ``routing_signal`` traces to a
        real corpus entity. Pass the ``positioning`` brief to bias the classification."""
        from metalworks.research import build_channel_strategy

        return build_channel_strategy(self.deps, _demand(research), positioning)

    def geo(self, research: Research | DemandReport) -> GeoPlan:
        """Distribution (D6) — the GEO / LLM-citability stream. Turns the report into
        **participation targets** (real threads to engage, from the report's permalinks),
        **citability probes** (conversational queries to test you're cited, from the cluster
        claims), and answer-first **answer briefs** (grounded, factual answers whose
        ``evidence_refs`` resolve against ``report.evidence`` and whose ``stat_anchors`` carry
        the cluster's real counts). Targets + probes are deterministic; the briefs' prose is
        LLM-authored but cite-or-die — an answer whose evidence doesn't resolve is dropped.
        DRAFTING ONLY — nothing here posts."""
        from metalworks.research import build_geo_plan

        return build_geo_plan(self.deps, _demand(research))

    def data_asset(
        self,
        research: Research | DemandReport,
        kind: Literal["complaint_index", "feature_ranking", "state_of"] = "complaint_index",
    ) -> DataReportAsset:
        """Distribution (D5) — project the report into a corpus-derived **data report**, the
        on-brand flagship asset: a deterministic ranking of the report's clusters carrying their
        REAL distinct-author / mention counts, real permalinks, and a verbatim quote per row. The
        LLM only writes the title + each row's framing label, grounded in the cluster's claim; the
        numbers/links/quotes are never invented, and ``methodology`` discloses the honest base (N
        threads, distinct-author counting, date range). ``kind`` picks the framing —
        ``complaint_index`` (pain points), ``feature_ranking`` (requested features), or
        ``state_of`` (the overall state)."""
        from metalworks.research import build_data_asset

        return build_data_asset(self.deps, _demand(research), kind)

    def channel_assets(
        self,
        research: Research | DemandReport,
        positioning: PositioningBrief | None = None,
    ) -> list[ChannelAsset]:
        """Distribution (D4) — draft channel-SHAPED, drafting-only assets per channel.

        Routes the report into its channel strategy (D2), then drafts one
        :class:`~metalworks.contract.distribution.ChannelAsset` per selected channel,
        shaped to that channel's surface (Product Hunt = tagline + maker comment + gallery
        captions; Show HN = title + first comment; X = N tweets; LinkedIn = carousel).
        Demand/factual claims are grounded (no-cite-no-claim) while persuasive hooks and the
        per-channel ``offer`` are free; the platform invariants (no upvote ask, native-first,
        founder voice) are enforced deterministically. DRAFTING ONLY — never posts."""
        from metalworks.research import build_channel_assets, build_channel_strategy

        report = _demand(research)
        strategy = build_channel_strategy(self.deps, report, positioning)
        return build_channel_assets(self.deps, report, strategy.channels, positioning)

    def landscape(self, research: Research | DemandReport) -> Landscape:
        """Pillar A — the full 'what exists today': direct / adjacent / status-quo rivals
        (each gap cited, each tagged with the demand clusters it competes for) PLUS an
        empirical existing-solutions scan (real shipped products, with traction). This is
        the 'what exists today' surface ``assess()`` consumes."""
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

    def design(
        self,
        research: Research | DemandReport,
        *,
        brand_name: str | None = None,
        taste: str = "editorial",
        max_teardown: int = 3,
    ) -> DesignSystem:
        """Visual-design pillar — a grounded-but-directional :class:`DesignSystem`.

        Reads the competition at the richest tier available (a real renderer
        teardown when a ``Research`` bundle carries a landscape and a browser is
        installed > web text > model knowledge) and records the ``grounding_tier``
        so the look is never overstated. ``taste`` picks the director preset
        (``editorial`` default, ``brutalist`` / ``warm-minimal`` / ``technical``;
        unknown → default); the default preserves prior output. ``max_teardown``
        caps the live teardown (``0`` for the full sweep)."""
        from metalworks.research import build_design_system

        return build_design_system(
            self.deps, research, brand_name=brand_name, taste=taste, max_teardown=max_teardown
        )

    def render_design_preview(self, system: DesignSystem) -> str:
        """Render a :class:`DesignSystem` to a self-contained preview HTML page.

        The preview chrome derives from the system's ``taste`` preset."""
        from metalworks.research import render_design_preview_html

        return render_design_preview_html(system)

    def logo(self, system: DesignSystem, *, n: int = 5) -> LogoSet:
        """The mark submodule — diverse, company-grade logo options that draw under
        a :class:`DesignSystem` (its aesthetic, typography, color). The model authors
        each SVG; an unsafe or empty one is dropped, never faked. Offered, never
        auto-selected. Get a system from :meth:`design` first."""
        from metalworks.research import build_logo_set

        return build_logo_set(self.deps.chat, system, n=n)

    def render_logo_picker(self, logos: LogoSet, *, taste: str | None = None) -> str:
        """Render a :class:`LogoSet` to a self-contained picker HTML page.

        Pass the design system's ``taste`` so the picker chrome tracks the brand's
        chosen voice (default: the ``editorial`` chrome)."""
        from metalworks.research import render_logo_picker_html

        return render_logo_picker_html(logos, taste=taste)

    def design_review(self, url: str, *, system: DesignSystem | None = None) -> DesignReview:
        """Audit a RENDERED page's computed styles deterministically, optionally vs a
        :class:`DesignSystem`. Needs a script-capable renderer (Playwright); raises
        :class:`BrowserNotInstalledError` when none is installed, or
        :class:`StyleAuditUnsupported` for a screenshot-only one."""
        from metalworks.config import resolve_renderer
        from metalworks.errors import BrowserNotInstalledError, StyleAuditUnsupported
        from metalworks.research import review_design

        renderer = resolve_renderer()
        if renderer is None:
            raise BrowserNotInstalledError()
        if not renderer.capabilities.supports_style_audit:
            raise StyleAuditUnsupported(renderer.renderer_id)
        return review_design(renderer, url, system=system)

    def build_spec(
        self,
        research: Research | DemandReport,
        positioning: PositioningBrief | None = None,
        surface: SurfaceKind | Literal["auto"] = "auto",
        *,
        stack: str = "empty",
    ) -> BuildSpec:
        """Pillar D — an evidence-grounded :class:`BuildSpec` for a coding agent.

        ``surface="auto"`` (default) lets the spec pick the surface + rationale; pin
        a surface (e.g. ``"cli"``) to honor it and skip the pick."""
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
