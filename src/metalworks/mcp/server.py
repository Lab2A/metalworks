"""FastMCP server wiring for metalworks.

This module imports cleanly with the ``[mcp]`` extra ABSENT — the ``mcp`` SDK is
imported lazily inside :func:`build_server` / :func:`serve`, raising
:class:`~metalworks.errors.MissingExtraError` only when a server is actually
built. So a host can ``import metalworks.mcp.server`` (and unit-test the tool
bodies in :mod:`metalworks.mcp.tools`) on a bare install.

Each registered tool is a thin async wrapper (module-level functions below)
around the corresponding plain body in :mod:`metalworks.mcp.tools`; the bodies
own the error-envelope contract. :func:`build_server` registers them all.

Transports:
- ``stdio`` (default) is keyless — the client is the local process.
- ``sse`` is network-exposed and therefore REQUIRES a bearer token; :func:`serve`
  refuses to start an SSE server without one.
"""

from __future__ import annotations

from typing import Any

from metalworks.errors import MetalworksError, MissingExtraError
from metalworks.mcp import tools

# ── Tool wrappers (module-level so static analysis sees them referenced in
#    `build_server`; each is a thin async shim over a plain body in `tools`). ──


# Tier 1 (zero-key)
async def compliance_lint(text: str, subreddit_rules: list[str] | None = None) -> dict[str, Any]:
    """TIER 1. Deterministic offline compliance check; emits a confirm_token on pass."""
    return tools.compliance_lint(text, subreddit_rules)


async def reddit_search_posts(
    query: str, subreddit: str | None = None, limit: int = 15
) -> dict[str, Any]:
    """TIER 1. Search public Reddit submissions ([reddit] extra, no key)."""
    return tools.reddit_search_posts(query, subreddit=subreddit, limit=limit)


async def reddit_get_post_comments(url: str, limit: int = 10) -> dict[str, Any]:
    """TIER 1. Top-level comments for a public post URL ([reddit] extra)."""
    return tools.reddit_get_post_comments(url, limit=limit)


async def reddit_subreddit_info(name: str) -> dict[str, Any]:
    """TIER 1. Subreddit intel: description, rules, top titles ([reddit] extra)."""
    return tools.reddit_subreddit_info(name)


async def reddit_subreddit_rules(name: str) -> dict[str, Any]:
    """TIER 1. Subreddit posting rules ([reddit] extra)."""
    return tools.reddit_subreddit_rules(name)


async def arctic_list_months(content_type: str = "submissions") -> dict[str, Any]:
    """TIER 1. Latest available month in the Arctic corpus ([arctic] extra)."""
    return tools.arctic_list_months(content_type)


async def arctic_pull_threads(subreddit: str, months: int = 1, limit: int = 200) -> dict[str, Any]:
    """TIER 1. Pull submissions for a subreddit (scoped: <=3 months, <=1000 rows)."""
    return tools.arctic_pull_threads(subreddit, months=months, limit=limit)


async def corpus_stats(store_path: str | None = None) -> dict[str, Any]:
    """TIER 1. Counts of runs/reports in the local store (offline)."""
    return tools.corpus_stats(store_path)


async def research_list_runs(store_path: str | None = None, limit: int = 50) -> dict[str, Any]:
    """TIER 1. List runs (including in-flight) from the local store."""
    return tools.research_list_runs(store_path, limit=limit)


async def research_get_report(report_id: str, store_path: str | None = None) -> dict[str, Any]:
    """TIER 1. Fetch a finished report from the local store by id."""
    return tools.research_get_report(report_id, store_path)


# Tier 2 (key-gated)
async def research_plan_brief(prompt: str, store_path: str | None = None) -> dict[str, Any]:
    """TIER 2. Walk the D1-D8 planner with default answers -> a ResearchBrief (chat key)."""
    return tools.research_plan_brief(prompt, store_path)


async def positioning_from_report(report_id: str, store_path: str | None = None) -> dict[str, Any]:
    """TIER 2. Derive a grounded positioning wedge from a stored report (chat key, synchronous)."""
    return tools.positioning_from_report(report_id, store_path)


async def distribution_strategy(report_id: str, store_path: str | None = None) -> dict[str, Any]:
    """TIER 2. Route a stored report's signals into test→focus channel experiments (chat key)."""
    return tools.distribution_strategy(report_id, store_path)


async def landscape_from_report(report_id: str, store_path: str | None = None) -> dict[str, Any]:
    """TIER 2. Map the full landscape — competitors + existing solutions + do-nothing cost."""
    return tools.landscape_from_report(report_id, store_path)


async def ideate_from_idea(idea: str, store_path: str | None = None) -> dict[str, Any]:
    """TIER 2. Idea-first ideation — sharpen a raw idea into a hypothesis + a brief."""
    return tools.ideate_from_idea(idea, store_path)


async def ideate_from_report(report_id: str, store_path: str | None = None) -> dict[str, Any]:
    """TIER 2. Evidence-first ideation — surface a stored report's forks as sketches."""
    return tools.ideate_from_report(report_id, store_path)


async def assess_from_report(report_id: str, store_path: str | None = None) -> dict[str, Any]:
    """TIER 2. The GO/PIVOT/NO-GO verdict — landscape then the demand-vs-landscape gap."""
    return tools.assess_from_report(report_id, store_path)


async def validate_from_idea(
    idea: str, max_iterations: int = 3, store_path: str | None = None
) -> dict[str, Any]:
    """TIER 2. Run the validate loop headlessly (--auto) from a raw idea (synchronous, slow)."""
    return tools.validate_from_idea(idea, max_iterations, store_path)


async def design_from_report(
    report_id: str,
    name: str | None = None,
    taste: str = "editorial",
    store_path: str | None = None,
) -> dict[str, Any]:
    """TIER 2. Author a grounded design system (+ preview HTML) for a stored report (chat key).
    taste picks the director preset: editorial (default) / brutalist / warm-minimal / technical."""
    return tools.design_from_report(report_id, name, taste, store_path)


async def logo_generate(
    report_id: str,
    name: str | None = None,
    taste: str = "editorial",
    store_path: str | None = None,
) -> dict[str, Any]:
    """TIER 2. Generate diverse logo options (under the design system) + a picker (chat key).
    taste picks the design preset the mark draws under (editorial / brutalist / …)."""
    return tools.logo_generate(report_id, name, taste, store_path)


async def design_review(
    url: str, report_id: str | None = None, store_path: str | None = None
) -> dict[str, Any]:
    """TIER 2. Audit a rendered page's computed styles vs design rules (+ a report's system)."""
    return tools.design_review(url, report_id, store_path)


async def build_spec(
    report_id: str, surface: str = "auto", stack: str = "empty", store_path: str | None = None
) -> dict[str, Any]:
    """TIER 2. Derive an evidence-grounded BuildSpec for a stored report; surface='auto'
    picks the surface + sketches feature-grounded screens (chat + embedding keys)."""
    return tools.build_spec(report_id, surface, stack, store_path)


async def research_start(
    brief: dict[str, Any], months: int | None = None, store_path: str | None = None
) -> dict[str, Any]:
    """TIER 2. Start the pipeline as a background job -> run_id (chat + embedding keys)."""
    return tools.research_start(brief, months=months, store_path=store_path)


async def research_status(run_id: str, store_path: str | None = None) -> dict[str, Any]:
    """TIER 2. Status of a background research job."""
    return tools.research_status(run_id, store_path)


async def research_result(run_id: str, store_path: str | None = None) -> dict[str, Any]:
    """TIER 2. Finished report for a job, or a status payload while running."""
    return tools.research_result(run_id, store_path)


async def generate_reply(thread_url: str, voice: str | None = None) -> dict[str, Any]:
    """TIER 2. Draft a reply + compliance verdict (+ confirm_token on pass) (chat key)."""
    return tools.generate_reply(thread_url, voice=voice)


async def discovery_run(
    queries: list[str],
    subreddits: list[str] | None = None,
    max_opportunities: int = 10,
    voice: str | None = None,
) -> dict[str, Any]:
    """TIER 2. Run discovery over queries → gated draft opportunities (never posts) (chat key)."""
    return tools.discovery_run(
        queries, subreddits=subreddits, max_opportunities=max_opportunities, voice=voice
    )


async def reddit_post_comment(
    url: str, text: str, confirm_token: str, username: str | None = None
) -> dict[str, Any]:
    """TIER 2 -- SECURITY BOUNDARY. Post a reply.

    Requires a confirm_token from a prior compliance pass plus
    METALWORKS_ALLOW_POSTING=1.
    """
    return tools.reddit_post_comment(url, text, confirm_token, username=username)


# Registration order = the tool list the server exposes.
_TOOL_WRAPPERS = (
    compliance_lint,
    reddit_search_posts,
    reddit_get_post_comments,
    reddit_subreddit_info,
    reddit_subreddit_rules,
    arctic_list_months,
    arctic_pull_threads,
    corpus_stats,
    research_list_runs,
    research_get_report,
    research_plan_brief,
    positioning_from_report,
    distribution_strategy,
    landscape_from_report,
    ideate_from_idea,
    ideate_from_report,
    assess_from_report,
    validate_from_idea,
    design_from_report,
    logo_generate,
    design_review,
    build_spec,
    research_start,
    research_status,
    research_result,
    generate_reply,
    discovery_run,
    reddit_post_comment,
)


def _import_fastmcp() -> Any:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - exercised via MissingExtra test
        raise MissingExtraError("mcp", package="mcp[cli]") from exc
    return FastMCP


def build_server(name: str = "metalworks") -> Any:
    """Build and return a :class:`FastMCP` instance with all tools registered.

    Lazy-imports the ``mcp`` SDK; raises
    :class:`~metalworks.errors.MissingExtraError` if the ``[mcp]`` extra is not
    installed.
    """
    fast_mcp = _import_fastmcp()
    server: Any = fast_mcp(name)
    for wrapper in _TOOL_WRAPPERS:
        server.tool()(wrapper)
    return server


def serve(
    *,
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 8000,
    token: str | None = None,
) -> None:
    """Run the MCP server.

    ``stdio`` (default) is keyless. ``sse`` is network-exposed and REQUIRES a
    bearer ``token`` (or ``METALWORKS_MCP_TOKEN`` in the env); it refuses to
    start without one. Raises :class:`~metalworks.errors.MissingExtraError` when
    the ``[mcp]`` extra is absent.
    """
    transport = transport.lower()
    if transport == "stdio":
        server = build_server()
        server.run(transport="stdio")
        return

    if transport == "sse":
        import os

        bearer = token or os.environ.get("METALWORKS_MCP_TOKEN")
        if not bearer:
            raise MetalworksError(
                "SSE transport refuses to start without a bearer token.",
                fix="Pass --token or set METALWORKS_MCP_TOKEN; stdio is the keyless default.",
            )
        _serve_sse(host=host, port=port, token=bearer)
        return

    raise MetalworksError(
        f"Unknown MCP transport {transport!r}.",
        fix="Use --transport stdio (default) or --transport sse.",
    )


def _serve_sse(*, host: str, port: int, token: str) -> None:
    """Wrap the FastMCP SSE app in bearer-auth middleware and run it under
    uvicorn. The token gate rejects any request lacking ``Authorization: Bearer
    <token>``."""
    import uvicorn
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import PlainTextResponse
    from starlette.routing import Mount

    server = build_server()
    expected = f"Bearer {token}"

    class BearerAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Any, call_next: Any) -> Any:
            if request.url.path in ("/health",):
                return await call_next(request)
            if request.headers.get("authorization", "") != expected:
                return PlainTextResponse(
                    "Unauthorized — set Authorization: Bearer <token>.", status_code=401
                )
            return await call_next(request)

    app = Starlette(
        routes=[Mount("/", app=server.sse_app())],
        middleware=[Middleware(BearerAuthMiddleware)],
    )
    uvicorn.run(app, host=host, port=port)


__all__ = ["build_server", "serve"]
