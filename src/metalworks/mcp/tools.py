"""MCP tool bodies as plain, unit-testable functions.

Each public function here is the *body* of one MCP tool; the FastMCP server in
:mod:`metalworks.mcp.server` registers a thin async wrapper around each. Keeping
the bodies plain means they're testable on a bare install with no ``mcp`` SDK.

Error contract: every body returns either its success payload or an error
*envelope* (``{error_code, message, fix, docs_url}``). The :func:`guard`
decorator turns any raised exception — typed or not — into that envelope, so a
host model never sees a raw traceback. Tier-2 bodies that need a credential
surface a :class:`~metalworks.errors.MissingKeyError` envelope naming the env
var and extra.

The posting tool is the security boundary. ``reddit_post_comment`` requires a
``confirm_token`` that only :func:`compliance_lint` emits, over the *exact* text,
and the env flag ``METALWORKS_ALLOW_POSTING=1`` — so a model cannot post without
a prior passing compliance check on the identical text plus an operator opt-in.
"""

from __future__ import annotations

import functools
import hashlib
import hmac
import os
import uuid
from typing import TYPE_CHECKING, Any, TypeVar

from metalworks.errors import MetalworksError, MissingKeyError

if TYPE_CHECKING:
    from collections.abc import Callable

    from metalworks.contract.research import DemandReport

ToolResult = dict[str, Any]
F = TypeVar("F", bound="Callable[..., ToolResult]")

_DOCS_BASE = "https://github.com/Lab2A/metalworks"

# Default caps for the zero-key Arctic pull tool — bounded so a Tier-1 caller
# can't trigger an unbounded network read.
_ARCTIC_DEFAULT_MONTHS = 1
_ARCTIC_MAX_MONTHS = 3
_ARCTIC_DEFAULT_LIMIT = 200
_ARCTIC_MAX_LIMIT = 1000


def _unexpected_envelope(exc: Exception) -> ToolResult:
    return {
        "error_code": "internal_error",
        "message": f"{type(exc).__name__}: {str(exc)[:300]}",
        "fix": "Retry; if this persists, file an issue with the message above.",
        "docs_url": _DOCS_BASE,
    }


def guard(fn: F) -> F:
    """Wrap a tool body so any exception becomes an error envelope.

    Typed :class:`MetalworksError` carries its own actionable envelope; anything
    else is normalized into an ``internal_error`` envelope.
    """

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> ToolResult:
        try:
            return fn(*args, **kwargs)
        except MetalworksError as exc:
            return {"error": exc.envelope()}
        except Exception as exc:
            return {"error": _unexpected_envelope(exc)}

    return wrapper  # type: ignore[return-value]


# ── Confirm-token (the posting gate) ────────────────────────────────────────


# Per-process HMAC key for confirm tokens, lazily initialized. Stable within a
# process so a token emitted by ``compliance_lint`` verifies in a later
# ``reddit_post_comment`` call against the *same* server; a per-process random
# key (not a fixed constant) means tokens don't survive a restart, which is the
# safe default.
_confirm_key: bytes | None = None


def _confirm_secret() -> bytes:
    global _confirm_key
    if _confirm_key is None:
        _confirm_key = os.urandom(32)
    return _confirm_key


def _confirm_token_for(text: str) -> str:
    digest = hmac.new(_confirm_secret(), text.encode("utf-8"), hashlib.sha256)
    return digest.hexdigest()


def _confirm_token_valid(text: str, token: str) -> bool:
    return hmac.compare_digest(_confirm_token_for(text), token or "")


# ── Tier 1 — zero-key ───────────────────────────────────────────────────────


@guard
def compliance_lint(text: str, subreddit_rules: list[str] | None = None) -> ToolResult:
    """TIER 1. Deterministic, fully-offline compliance check on reply text.

    Returns the verdict plus, when it passes, a ``confirm_token`` over this exact
    text — the only way to later authorize ``reddit_post_comment`` on it.
    """
    from metalworks.reddit import heuristic_check

    verdict = heuristic_check(text, subreddit_rules)
    payload: ToolResult = {
        "pass": verdict.pass_,
        "violations": list(verdict.violations),
        "confidence": verdict.confidence,
    }
    if verdict.pass_:
        payload["confirm_token"] = _confirm_token_for(text)
    return payload


@guard
def reddit_search_posts(
    query: str,
    *,
    subreddit: str | None = None,
    limit: int = 15,
) -> ToolResult:
    """TIER 1. Search public Reddit submissions → list of posts. Needs the
    ``[reddit]`` extra (no API key)."""
    from metalworks.reddit import RedditSearch

    posts = RedditSearch().search_posts(query, subreddit=subreddit, limit=limit)
    return {"posts": [p.model_dump(mode="json") for p in posts]}


@guard
def reddit_get_post_comments(url: str, *, limit: int = 10) -> ToolResult:
    """TIER 1. Top-level comments for a public post URL. Needs ``[reddit]``."""
    from metalworks.reddit import RedditSearch

    comments = RedditSearch().get_post_comments(url, limit=limit)
    return {"comments": [c.model_dump(mode="json") for c in comments]}


@guard
def reddit_subreddit_info(name: str) -> ToolResult:
    """TIER 1. Community intel (description, rules, top titles). Needs ``[reddit]``."""
    from metalworks.reddit import fetch_subreddit_intel

    return {"intel": fetch_subreddit_intel(name).model_dump(mode="json")}


@guard
def reddit_subreddit_rules(name: str) -> ToolResult:
    """TIER 1. The subreddit's posting rules → list of strings. Needs ``[reddit]``."""
    from metalworks.reddit import RedditSearch

    return {"rules": RedditSearch().get_subreddit_rules(name)}


@guard
def arctic_list_months(content_type: str = "submissions") -> ToolResult:
    """TIER 1. The latest available month in the Arctic corpus. Needs ``[arctic]``."""
    from metalworks.research.arctic import ArcticReader

    reader = ArcticReader(probe_sleep_s=0.0)
    try:
        latest = reader.latest_available_month(content_type)
        return {"latest_available_month": str(latest), "content_type": content_type}
    finally:
        reader.close()


@guard
def arctic_pull_threads(
    subreddit: str,
    *,
    months: int = _ARCTIC_DEFAULT_MONTHS,
    limit: int = _ARCTIC_DEFAULT_LIMIT,
) -> ToolResult:
    """TIER 1. Pull submissions for one subreddit from the Arctic corpus.

    Scoped: ``months`` is capped at 3 (default 1) and ``limit`` at 1000 (default
    200) so a Tier-1 caller can't kick off an unbounded archive read. Needs
    ``[arctic]``.
    """
    from metalworks.research.arctic import ArcticReader
    from metalworks.research.types import months_back

    months = max(1, min(int(months), _ARCTIC_MAX_MONTHS))
    limit = max(1, min(int(limit), _ARCTIC_MAX_LIMIT))
    sub = subreddit.strip().lstrip("r/").lstrip("/")

    reader = ArcticReader(probe_sleep_s=0.0)
    try:
        window = months_back(months, anchor=reader.latest_available_month("submissions"))
        rows = list(
            reader.pull_subreddit(
                subreddit=sub,
                content_type="submissions",
                months=window,
                select_cols=["id", "title", "selftext", "subreddit", "score", "num_comments"],
                limit=limit,
            )
        )
        return {
            "subreddit": sub,
            "months": [str(m) for m in window],
            "count": len(rows),
            "threads": rows,
        }
    finally:
        reader.close()


@guard
def corpus_stats(store_path: str | None = None) -> ToolResult:
    """TIER 1. Counts of persisted runs and reports in the local store (offline)."""
    from metalworks import config

    store = config.default_store(store_path)
    runs = store.list_runs(limit=10_000)
    return {
        "total_runs": len(runs),
        "complete_runs": sum(1 for r in runs if r.status == "complete"),
        "failed_runs": sum(1 for r in runs if r.status == "failed"),
        "in_flight_runs": sum(
            1 for r in runs if r.status not in ("complete", "failed", "compile_failed")
        ),
    }


@guard
def research_list_runs(store_path: str | None = None, *, limit: int = 50) -> ToolResult:
    """TIER 1. List runs (including in-flight) from the local store."""
    from metalworks import config

    store = config.default_store(store_path)
    runs = store.list_runs(limit=limit)
    return {"runs": [r.model_dump(mode="json") for r in runs]}


@guard
def research_get_report(report_id: str, store_path: str | None = None) -> ToolResult:
    """TIER 1. Fetch a finished report from the local store by id."""
    from metalworks import config

    store = config.default_store(store_path)
    report = store.get_report(report_id)
    if report is None:
        return {
            "error": {
                "error_code": "not_found",
                "message": f"No report with id {report_id!r} in the local store.",
                "fix": "Check the id from research_list_runs, or wait for the run to complete.",
                "docs_url": _DOCS_BASE,
            }
        }
    return {"report": report.model_dump(mode="json")}


# ── Tier 2 — key-gated ──────────────────────────────────────────────────────


def _build_deps(store_path: str | None) -> Any:
    """Assemble ResearchDeps from the environment. Raises MissingKeyError when a
    required provider key is absent (the envelope names the key + extra)."""
    from metalworks import config
    from metalworks.research.arctic import ArcticReader
    from metalworks.research.deps import ResearchDeps

    chat = config.resolve_chat()
    embeddings = config.resolve_embeddings()
    store = config.default_store(store_path)
    reader = ArcticReader(probe_sleep_s=0.0)
    return ResearchDeps(
        chat=chat,
        embeddings=embeddings,
        corpus=store,
        reader=reader,
        search=config.resolve_search(),
    )


@guard
def research_plan_brief(prompt: str, store_path: str | None = None) -> ToolResult:
    """TIER 2 (chat key). Walk the D1-D8 planner with default answers and return
    an assembled ResearchBrief for this prompt. Needs a chat-model key."""
    from metalworks import config
    from metalworks.research.arctic import ArcticReader
    from metalworks.research.deps import ResearchDeps
    from metalworks.research.planner import plan_brief

    chat = config.resolve_chat()
    store = config.default_store(store_path)
    reader = ArcticReader(probe_sleep_s=0.0)
    deps = ResearchDeps(
        chat=chat, embeddings=config.resolve_embeddings(), corpus=store, reader=reader
    )
    research_brief = plan_brief(deps, prompt)
    return {"brief": research_brief.model_dump(mode="json")}


@guard
def positioning_from_report(report_id: str, store_path: str | None = None) -> ToolResult:
    """TIER 2 (chat key). Derive a grounded positioning wedge from a stored
    report — one LLM call, synchronous (no job pattern). Needs a chat-model key."""
    from metalworks import config
    from metalworks.research.synthesis import build_positioning_brief

    store = config.default_store(store_path)
    report = store.get_report(report_id)
    if report is None:
        return {
            "error": {
                "error_code": "not_found",
                "message": f"No report with id {report_id!r} in the local store.",
                "fix": "Check the id from research_list_runs, or wait for the run to complete.",
                "docs_url": _DOCS_BASE,
            }
        }
    deps = _build_deps(store_path)
    brief = build_positioning_brief(deps, report)
    return {"positioning": brief.model_dump(mode="json")}


@guard
def distribution_strategy(report_id: str, store_path: str | None = None) -> ToolResult:
    """TIER 2 (chat key). Route a stored report's named entities + signals into the
    structured channel space as test→focus channel experiments (D2) — one LLM
    classify call + deterministic routing, synchronous. Every channel's
    routing_signal traces to a real corpus entity. Needs a chat-model key."""
    from metalworks import config
    from metalworks.research import build_channel_strategy

    store = config.default_store(store_path)
    report = store.get_report(report_id)
    if report is None:
        return {
            "error": {
                "error_code": "not_found",
                "message": f"No report with id {report_id!r} in the local store.",
                "fix": "Check the id from research_list_runs, or wait for the run to complete.",
                "docs_url": _DOCS_BASE,
            }
        }
    deps = _build_deps(store_path)
    strategy = build_channel_strategy(deps, report)
    return {"strategy": strategy.model_dump(mode="json")}


@guard
def distribution_assets(report_id: str, store_path: str | None = None) -> ToolResult:
    """TIER 2 (chat key). Draft channel-SHAPED, drafting-only distribution assets (D4)
    for a stored report — routes it into its channel strategy, then drafts one
    asset per channel shaped to its surface (PH = tagline + maker comment + gallery
    captions; Show HN = title + first comment; X = N tweets; LinkedIn = carousel).
    Demand claims ground (no-cite-no-claim); persuasive hooks + the per-channel offer
    are free; no 'upvote' ask, native-first, founder-voiced. DRAFTING ONLY — never
    posts. Needs a chat-model key."""
    from metalworks import config
    from metalworks.research import build_channel_assets, build_channel_strategy

    store = config.default_store(store_path)
    report = store.get_report(report_id)
    if report is None:
        return {
            "error": {
                "error_code": "not_found",
                "message": f"No report with id {report_id!r} in the local store.",
                "fix": "Check the id from research_list_runs, or wait for the run to complete.",
                "docs_url": _DOCS_BASE,
            }
        }
    deps = _build_deps(store_path)
    strategy = build_channel_strategy(deps, report)
    assets = build_channel_assets(deps, report, strategy.channels)
    return {"assets": [a.model_dump(mode="json") for a in assets]}


@guard
@guard
def landscape_from_report(report_id: str, store_path: str | None = None) -> ToolResult:
    """TIER 2 (chat + embedding keys). Map the full landscape for a stored report —
    the competitor map PLUS an empirical existing-solutions scan (real shipped
    products matched to demand clusters), synchronous. Degrades honestly when no
    product source / token is configured (competitors + status-quo still hold)."""
    from metalworks import config
    from metalworks.research import run_landscape

    store = config.default_store(store_path)
    report = store.get_report(report_id)
    if report is None:
        return {
            "error": {
                "error_code": "not_found",
                "message": f"No report with id {report_id!r} in the local store.",
                "fix": "Check the id from research_list_runs, or wait for the run to complete.",
                "docs_url": _DOCS_BASE,
            }
        }
    deps = _build_deps(store_path)
    landscape = run_landscape(deps, report)
    return {"landscape": landscape.model_dump(mode="json")}


@guard
def ideate_from_idea(idea: str, store_path: str | None = None) -> ToolResult:
    """TIER 2 (chat key). Idea-first ideation — sharpen a raw idea into a testable
    hypothesis plus a research brief to run demand on. The front of the validate loop."""
    from metalworks.research import ideate_from_idea as _ideate

    deps = _build_deps(store_path)
    sketch = _ideate(deps, idea)
    return {"idea_sketch": sketch.model_dump(mode="json")}


@guard
def ideate_from_report(report_id: str, store_path: str | None = None) -> ToolResult:
    """TIER 2 (chat key). Evidence-first ideation — surface a stored report's forks
    (candidate wedges, else top clusters) as grounded idea sketches to pick from."""
    from metalworks import config
    from metalworks.research import ideate_from_report as _ideate

    store = config.default_store(store_path)
    report = store.get_report(report_id)
    if report is None:
        return {
            "error": {
                "error_code": "not_found",
                "message": f"No report with id {report_id!r} in the local store.",
                "fix": "Check the id from research_list_runs, or wait for the run to complete.",
                "docs_url": _DOCS_BASE,
            }
        }
    deps = _build_deps(store_path)
    result = _ideate(deps, report)
    return {"ideation": result.model_dump(mode="json")}


@guard
def assess_from_report(report_id: str, store_path: str | None = None) -> ToolResult:
    """TIER 2 (chat + embedding keys). The GO/PIVOT/NO-GO verdict for a stored report —
    runs the landscape, then the deterministic gap over demand + landscape. A partial
    landscape never yields a hard GO (anti-confirmation)."""
    from metalworks import config
    from metalworks.research import run_assessment, run_landscape

    store = config.default_store(store_path)
    report = store.get_report(report_id)
    if report is None:
        return {
            "error": {
                "error_code": "not_found",
                "message": f"No report with id {report_id!r} in the local store.",
                "fix": "Check the id from research_list_runs, or wait for the run to complete.",
                "docs_url": _DOCS_BASE,
            }
        }
    deps = _build_deps(store_path)
    landscape = run_landscape(deps, report)
    assessment = run_assessment(deps, report, landscape)
    return {"assessment": assessment.model_dump(mode="json")}


@guard
def validate_from_idea(
    idea: str, max_iterations: int = 3, store_path: str | None = None
) -> ToolResult:
    """TIER 2 (chat + embedding keys). Run the validate loop headlessly (--auto) from a raw
    idea — ideate → demand → landscape → assess, looping on PIVOT toward the under-served fork.
    Synchronous and can be slow (runs demand each round); the human-gated loop lives in the
    `validate` skill, which drives the discrete ideate / landscape / assess tools."""
    from metalworks.research import validate as _validate

    deps = _build_deps(store_path)
    result = _validate(deps, idea, max_iterations=max_iterations)
    return {"validation": result.model_dump(mode="json")}


def _report_or_not_found(report_id: str, store_path: str | None) -> DemandReport | ToolResult:
    from metalworks import config

    report = config.default_store(store_path).get_report(report_id)
    if report is None:
        envelope: ToolResult = {
            "error": {
                "error_code": "not_found",
                "message": f"No report with id {report_id!r} in the local store.",
                "fix": "Check the id from research_list_runs, or wait for the run to complete.",
                "docs_url": _DOCS_BASE,
            }
        }
        return envelope
    return report


@guard
def design_from_report(
    report_id: str,
    name: str | None = None,
    taste: str = "editorial",
    store_path: str | None = None,
) -> ToolResult:
    """TIER 2 (chat key). Author a grounded design system for a stored report:
    builds the landscape, reads the competition at the richest tier available
    (a real browser teardown > web text > model knowledge), and returns the
    DesignSystem plus a self-contained preview HTML. ``taste`` picks the director
    preset (editorial / brutalist / warm-minimal / technical; default editorial
    preserves prior output). The result's grounding_tier records how grounded the
    look actually is."""
    from metalworks.contract.bundle import Research
    from metalworks.research import build_design_system, render_design_preview_html, run_landscape

    report = _report_or_not_found(report_id, store_path)
    if isinstance(report, dict):
        return report
    deps = _build_deps(store_path)
    try:
        landscape = run_landscape(deps, report)
    except Exception:  # landscape is best-effort; design degrades honestly without it
        landscape = None
    system = build_design_system(
        deps, Research(demand=report, landscape=landscape), brand_name=name, taste=taste
    )
    return {
        "design_system": system.model_dump(mode="json"),
        "preview_html": render_design_preview_html(system),
    }


@guard
def logo_generate(
    report_id: str,
    name: str | None = None,
    taste: str = "editorial",
    store_path: str | None = None,
) -> ToolResult:
    """TIER 2 (chat key). Generate diverse logo options for a stored report, drawn
    under its design system. Returns a LogoSet + a self-contained picker HTML. The
    model authors each SVG; an unsafe or empty one is dropped, never faked. Options
    are offered, never auto-selected. ``taste`` picks the design preset the mark
    draws under (editorial / brutalist / warm-minimal / technical)."""
    from metalworks.research import build_design_system, build_logo_set, render_logo_picker_html

    report = _report_or_not_found(report_id, store_path)
    if isinstance(report, dict):
        return report
    deps = _build_deps(store_path)
    system = build_design_system(deps, report, brand_name=name, taste=taste)
    logos = build_logo_set(deps.chat, system, n=5)
    return {
        "logo_set": logos.model_dump(mode="json"),
        "html": render_logo_picker_html(logos, taste=system.taste),
    }


@guard
def design_review(
    url: str, report_id: str | None = None, store_path: str | None = None
) -> ToolResult:
    """TIER 2 (chat key only when ``report_id`` is given). Deterministically audit a
    rendered page's computed styles (fonts, heading scale, colors) against design
    hard-rules, and — with ``report_id`` — that report's design system. Needs a
    script-capable browser renderer (Playwright); screenshot-only backends can't
    read computed styles."""
    from metalworks.config import resolve_renderer
    from metalworks.errors import BrowserNotInstalledError, StyleAuditUnsupported
    from metalworks.research import build_design_system, review_design

    renderer = resolve_renderer()
    if renderer is None:
        raise BrowserNotInstalledError()
    if not renderer.capabilities.supports_style_audit:
        raise StyleAuditUnsupported(renderer.renderer_id)
    system = None
    if report_id is not None:
        report = _report_or_not_found(report_id, store_path)
        if isinstance(report, dict):
            return report
        system = build_design_system(_build_deps(store_path), report)
    review = review_design(renderer, url, system=system)
    return {"design_review": review.model_dump(mode="json")}


@guard
def build_spec(
    report_id: str,
    surface: str = "auto",
    stack: str = "empty",
    store_path: str | None = None,
) -> ToolResult:
    """TIER 2 (chat + embedding keys). Derive an evidence-grounded BuildSpec for a
    stored report — each feature maps to a real demand cluster and carries its
    quotes (un-grounded features are dropped). With surface='auto' (default) the
    spec also picks the surface + a one-line rationale and sketches feature-grounded
    screens; pin a surface (web/cli/...) to skip the pick. Does NOT write files (that
    is the `metalworks build init` CLI); returns the spec for a coding agent."""
    from typing import Literal, cast, get_args

    from metalworks.build import build_spec_from_report
    from metalworks.contract.surface import SurfaceKind
    from metalworks.research.synthesis import build_positioning_brief

    valid = get_args(SurfaceKind)
    if surface != "auto" and surface not in valid:
        return {
            "error": {
                "error_code": "invalid_argument",
                "message": f"Unknown surface {surface!r}.",
                "fix": f"Pass 'auto' or one of: {', '.join(valid)}.",
                "docs_url": _DOCS_BASE,
            }
        }
    report = _report_or_not_found(report_id, store_path)
    if isinstance(report, dict):
        return report
    deps = _build_deps(store_path)
    spec = build_spec_from_report(
        deps,
        report,
        build_positioning_brief(deps, report),
        cast("SurfaceKind | Literal['auto']", surface),
        stack=stack,
    )
    return {"build_spec": spec.model_dump(mode="json")}


@guard
def research_start(
    brief: dict[str, Any],
    *,
    months: int | None = None,
    store_path: str | None = None,
) -> ToolResult:
    """TIER 2 (chat + embedding keys). Start the pipeline as a background job and
    return a ``run_id`` immediately. Poll with ``research_status`` /
    ``research_result``. The pipeline takes minutes, so it never runs inline."""
    from metalworks.contract import ResearchBrief
    from metalworks.mcp.jobs import start_research_job

    research_brief = ResearchBrief.model_validate(brief)
    if months is not None:
        research_brief = research_brief.model_copy(update={"time_window_months": int(months)})
    deps = _build_deps(store_path)
    run_id = str(uuid.uuid4())
    start_research_job(run_id=run_id, deps=deps, brief=research_brief, runs=deps.corpus)
    return {"run_id": run_id, "status": "queued"}


@guard
def research_status(run_id: str, store_path: str | None = None) -> ToolResult:
    """TIER 2. Status of a background research job."""
    from metalworks import config

    store = config.default_store(store_path)
    run = store.get_run(run_id)
    if run is None:
        return {
            "error": {
                "error_code": "not_found",
                "message": f"No run with id {run_id!r}.",
                "fix": "Use the run_id returned by research_start.",
                "docs_url": _DOCS_BASE,
            }
        }
    return {"run": run.model_dump(mode="json")}


@guard
def research_result(run_id: str, store_path: str | None = None) -> ToolResult:
    """TIER 2. The finished report for a completed job, or a status payload while
    it's still running."""
    from metalworks import config

    store = config.default_store(store_path)
    report = store.get_report(run_id)
    if report is not None:
        return {"report": report.model_dump(mode="json")}
    run = store.get_run(run_id)
    status = run.status if run is not None else "not_found"
    return {"ready": False, "status": status}


@guard
def generate_reply(thread_url: str, *, voice: str | None = None) -> ToolResult:
    """TIER 2 (chat key). Draft a Reddit reply for a thread and run it through
    the deterministic compliance gate. Returns the draft, the verdict, and — when
    it passes — a ``confirm_token`` usable with ``reddit_post_comment``."""
    from metalworks import config
    from metalworks.contract import DiscoveryContext, Persona
    from metalworks.discovery import draft_reply
    from metalworks.reddit import RedditSearch, heuristic_check

    chat = config.resolve_chat()
    post = RedditSearch().get_post(thread_url)
    if post is None:
        return {
            "error": {
                "error_code": "not_found",
                "message": f"Could not fetch a post from {thread_url!r}.",
                "fix": "Pass a full Reddit thread URL (https://reddit.com/r/.../comments/...).",
                "docs_url": _DOCS_BASE,
            }
        }
    # Delegate to the real discovery reply seam (persona/voice-aware, with the
    # pro→flash degradation retry) rather than a bespoke prompt.
    context = DiscoveryContext(voice_guidelines=[voice] if voice else [])
    reply = draft_reply(chat, post, Persona(), "expert", context, subreddit_rules=[])
    if reply is None or not reply.reply_text.strip():
        return {
            "error": {
                "error_code": "generation_failed",
                "message": "The model did not return a usable reply draft.",
                "fix": "Retry, or try a different thread or chat model.",
                "docs_url": _DOCS_BASE,
            }
        }
    draft = reply.reply_text
    verdict = heuristic_check(draft)
    payload: ToolResult = {
        "draft": draft,
        "compliance": {
            "pass": verdict.pass_,
            "violations": list(verdict.violations),
            "confidence": verdict.confidence,
        },
    }
    if verdict.pass_:
        payload["confirm_token"] = _confirm_token_for(draft)
    return payload


@guard
def reddit_post_comment(
    url: str,
    text: str,
    confirm_token: str,
    *,
    username: str | None = None,
) -> ToolResult:
    """TIER 2 — THE SECURITY BOUNDARY. Post a reply to a public Reddit thread.

    Triple-gated:
    1. ``METALWORKS_ALLOW_POSTING=1`` must be set (operator opt-in).
    2. ``confirm_token`` must be the token a prior ``compliance_lint`` /
       ``generate_reply`` pass emitted over this *exact* text (proof the text
       cleared the deterministic gate unchanged).
    3. A re-run of the compliance gate must still pass (defense in depth).

    Needs ``[reddit]`` plus ``REDDIT_CLIENT_ID`` / ``REDDIT_CLIENT_SECRET`` and a
    connected account (``metalworks reddit auth login``).
    """
    from metalworks.reddit import heuristic_check

    if os.environ.get("METALWORKS_ALLOW_POSTING") != "1":
        raise MissingKeyError(
            "METALWORKS_ALLOW_POSTING=1", provider="posting (disabled by default)"
        )

    if not _confirm_token_valid(text, confirm_token):
        return {
            "error": {
                "error_code": "confirm_token_invalid",
                "message": "confirm_token does not match this exact text.",
                "fix": "Call compliance_lint on the exact text first and pass its confirm_token.",
                "docs_url": _DOCS_BASE,
            }
        }

    verdict = heuristic_check(text)
    if not verdict.pass_:
        return {
            "error": {
                "error_code": "compliance_block",
                "message": f"Compliance gate blocked this text: {list(verdict.violations)}",
                "fix": "Revise the text until compliance_lint passes, then re-confirm.",
                "docs_url": _DOCS_BASE,
            }
        }

    return _do_post(url=url, text=text, username=username)


@guard
def discovery_run(
    queries: list[str],
    *,
    subreddits: list[str] | None = None,
    max_opportunities: int = 10,
    voice: str | None = None,
    store_path: str | None = None,
) -> ToolResult:
    """TIER 2 (chat key). Run the discovery loop over `queries`: search Reddit,
    filter for intent, draft replies, and gate each through the compliance check.

    Returns draft opportunities only — discovery NEVER posts. Posting is a
    separate, explicitly-confirmed `reddit_post_comment` call. Needs a chat-model
    key and the `[reddit]` extra.
    """
    from metalworks import config
    from metalworks.contract import DiscoveryContext
    from metalworks.discovery import DiscoveryDeps, run_discovery
    from metalworks.reddit import RedditSearch

    chat = config.resolve_chat()
    store = config.default_store(store_path)
    context = DiscoveryContext(voice_guidelines=[voice] if voice else [])
    deps = DiscoveryDeps(
        chat=chat,
        search=RedditSearch(),
        opportunities=store,
        context=context,
    )
    opportunities = run_discovery(
        deps,
        queries=queries,
        subreddits=subreddits,
        max_opportunities=max_opportunities,
    )
    return {"opportunities": [o.model_dump(mode="json") for o in opportunities]}


def _do_post(*, url: str, text: str, username: str | None) -> ToolResult:
    """Resolve a connected account and post via RedditOAuth. Factored out so the
    gate logic above stays readable."""
    from metalworks import config
    from metalworks.reddit import RedditOAuth
    from metalworks.stores import TokenCipher

    store = config.default_store(None)
    accounts = store.list_accounts()
    if not accounts:
        return {
            "error": {
                "error_code": "reauth_required",
                "message": "No connected Reddit account.",
                "fix": "Run: metalworks reddit auth login",
                "docs_url": _DOCS_BASE,
            }
        }
    target = username or accounts[0].username
    oauth = RedditOAuth(accounts=store, cipher=TokenCipher())
    try:
        result = oauth.post_comment(username=target, post_url=url, text=text)
    finally:
        oauth.close()
    if not result.success:
        return {
            "error": {
                "error_code": "reddit_error",
                "message": result.error or "Post failed.",
                "fix": "Check the account's auth and that the thread still accepts comments.",
                "docs_url": _DOCS_BASE,
            }
        }
    return {
        "posted": True,
        "comment_id": result.comment_id,
        "comment_url": result.comment_url,
        "username": result.username,
    }


__all__ = [
    "arctic_list_months",
    "arctic_pull_threads",
    "compliance_lint",
    "corpus_stats",
    "discovery_run",
    "generate_reply",
    "guard",
    "reddit_get_post_comments",
    "reddit_post_comment",
    "reddit_search_posts",
    "reddit_subreddit_info",
    "reddit_subreddit_rules",
    "research_get_report",
    "research_list_runs",
    "research_plan_brief",
    "research_result",
    "research_start",
    "research_status",
]
