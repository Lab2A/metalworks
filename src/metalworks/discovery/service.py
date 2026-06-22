"""run_discovery — the filter → generate → gate engagement pipeline.

The discovery service, with the 7 review-mandated
decoupling seams (see the discovery package docstring / plan). The pipeline per
post is:

    dedup-check → filter (cheap model) → [keep?] → generate (capable model, with
    pro→flash degradation retry) → compliance gate (deterministic regex denylist
    as a cheap first pass, the LLM judge as the authoritative authentic-voice
    gate on any pass) → attach verdict → save.

Reductions vs. the source: no MEMORY system (knowledge comes from
`deps.context`), no plan caps (just `max_opportunities`), no DB-loaded queries
(the caller supplies them), no karma table (the `query_performance` callable),
no Supabase writeback (the `on_query_result` callable).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from metalworks.contract import ComplianceVerdict, Opportunity, Persona, RedditPost
from metalworks.discovery.judge import llm_judge
from metalworks.discovery.prompts import (
    FilterDecision,
    ReplyGenerationV2,
    build_filter_prompt,
    build_generate_prompt,
)
from metalworks.errors import StructuredOutputError
from metalworks.reddit import heuristic_check

if TYPE_CHECKING:
    from collections.abc import Callable

    from metalworks.contract import DiscoveryContext
    from metalworks.discovery.deps import DiscoveryDeps
    from metalworks.llm import ChatModel

# Account types the filter may legitimately return; anything else maps to expert.
_VALID_ACCOUNT_TYPES = frozenset({"founder", "expert", "company"})


def run_discovery(
    deps: DiscoveryDeps,
    *,
    queries: list[str],
    max_opportunities: int = 30,
    subreddits: list[str] | None = None,
) -> list[Opportunity]:
    """Run a discovery cycle over caller-supplied queries → list[Opportunity].

    Searches each query (optionally scoped to `subreddits`), filters and
    generates a reply per surviving post, gates it through the compliance
    check, and saves the opportunities. Stops once `max_opportunities` have been
    produced.
    """
    ordered = _order_queries(deps, queries)
    sub_targets: list[str | None] = list(subreddits) if subreddits else [None]

    opportunities: list[Opportunity] = []
    seen_urls: set[str] = set()

    for query in ordered:
        if len(opportunities) >= max_opportunities:
            break
        deps.emit(f"search:{query}")
        posts = _search(deps, query, sub_targets)

        posts_found = 0
        posts_kept = 0
        for post in posts:
            if post.url in seen_urls:
                continue
            seen_urls.add(post.url)
            posts_found += 1

            if len(opportunities) >= max_opportunities:
                break

            opp = _process_single_post(deps, post)
            if opp is not None:
                posts_kept += 1
                opportunities.append(opp)

        if deps.on_query_result is not None:
            deps.on_query_result(query, posts_found, posts_kept)

    if opportunities:
        deps.opportunities.save_opportunities(opportunities)
        deps.emit(f"saved:{len(opportunities)}")

    return opportunities


def _order_queries(deps: DiscoveryDeps, queries: list[str]) -> list[str]:
    """Rank queries by `deps.query_performance` when supplied; else preserve order."""
    if deps.query_performance is None:
        return list(queries)
    score = deps.query_performance
    return sorted(queries, key=score, reverse=True)


def _search(deps: DiscoveryDeps, query: str, sub_targets: list[str | None]) -> list[RedditPost]:
    """Search one query across each subreddit target, deduping within the query."""
    out: list[RedditPost] = []
    seen: set[str] = set()
    for sub in sub_targets:
        try:
            results = deps.search.search_posts(query, subreddit=sub)
        except Exception as exc:
            deps.emit(f"search-error:{query}:{exc}")
            continue
        for post in results:
            if post.url in seen:
                continue
            seen.add(post.url)
            out.append(post)
    return out


def _process_single_post(deps: DiscoveryDeps, post: RedditPost) -> Opportunity | None:
    """Per-post pipeline: dedup → filter → generate → compliance gate → Opportunity."""
    # SEAM (f): dedup BEFORE any LLM call — saves 2 LLM calls per seen post.
    if deps.opportunities.opportunity_exists(post.url):
        return None

    # Pre-LLM sanity: drop empty / near-empty posts before any LLM call.
    if len(post.title.strip()) + len(post.selftext.strip()) < 30:
        return None

    # Stage 1: filter (cheap model) — the public filter_post seam.
    decision = filter_post(deps.filter_model, post, deps.context, on_error=deps.emit)
    if decision is None or not decision.keep:
        return None

    # SEAM (e): persona selection by FilterDecision.account_type.
    account_type = (decision.account_type or "expert").strip().lower()
    if account_type not in _VALID_ACCOUNT_TYPES:
        account_type = "expert"
    persona = deps.context.personas.get(account_type) or Persona()

    subreddit_rules = _subreddit_rules(deps, post.subreddit)

    # Stage 2: draft (capable model, with pro→flash degradation retry) — the
    # public draft_reply seam.
    reply = draft_reply(
        deps.chat,
        post,
        persona,
        account_type,
        deps.context,
        subreddit_rules=subreddit_rules,
        fast_chat=deps.fast_chat,
        on_event=deps.emit,
    )
    if reply is None:
        return None

    # Stage 3: compliance gate — the regex denylist is a cheap deterministic
    # first pass (it hard-rejects the obvious tells); the LLM judge is the
    # authoritative arbiter of authentic voice. A finite phrase list catches
    # only its exact strings, so any pass is escalated to the judge — that is
    # what catches novel AI-tell phrasing the denylist can't enumerate.
    verdict = heuristic_check(reply.reply_text, subreddit_rules)
    if verdict.pass_:
        verdict = llm_judge(
            deps, reply_text=reply.reply_text, post=post, subreddit_rules=subreddit_rules
        )
    if not verdict.pass_:
        deps.emit(f"gate-blocked:{post.url}")
        return None

    return _build_opportunity(deps, post=post, decision=decision, reply=reply, verdict=verdict)


def filter_post(
    model: ChatModel,
    post: RedditPost,
    context: DiscoveryContext,
    *,
    on_error: Callable[[str], None] | None = None,
) -> FilterDecision | None:
    """Relevance-filter one post on ``model`` (a cheap model is enough). None on failure.

    A standalone building block: hand it any :class:`~metalworks.llm.ChatModel`
    and your :class:`~metalworks.contract.DiscoveryContext` to decide whether a
    thread is worth engaging, without running the whole loop. ``on_error`` (if
    given) receives a ``"filter-error:<url>:<exc>"`` string when the model
    declines. Infra errors (auth/network/quota/timeout) propagate so a
    misconfigured key is a real failure, not a silent "no relevant posts".
    """
    system, user = build_filter_prompt(post=post, context=context)
    try:
        return model.complete_structured(
            system=system,
            user=user,
            output_model=FilterDecision,
            max_tokens=300,
            temperature=0.3,
        )
    except StructuredOutputError as exc:
        if on_error is not None:
            on_error(f"filter-error:{post.url}:{exc}")
        return None


def draft_reply(
    chat: ChatModel,
    post: RedditPost,
    persona: Persona,
    account_type: str,
    context: DiscoveryContext,
    *,
    subreddit_rules: list[str] | None = None,
    fast_chat: ChatModel | None = None,
    on_event: Callable[[str], None] | None = None,
) -> ReplyGenerationV2 | None:
    """Draft a reply to ``post`` in a given voice. None when generation fails.

    The standalone reply seam — "draft a reply to THIS thread in MY voice with
    MY persona/context." Tries ``chat``, then retries the same prompt on
    ``fast_chat`` (falling back to ``chat`` when no fast model is given). This
    pro→flash degradation is load-bearing: the capable model can truncate
    structured output mid-string, dropping ~50% of valid candidates, which the
    cheaper retry recovers. Compliance is the caller's job — run
    :func:`~metalworks.reddit.heuristic_check` / :func:`~metalworks.discovery.llm_judge`
    on the returned ``reply_text``.
    """
    system, user = build_generate_prompt(
        post=post,
        persona=persona,
        account_type=account_type,
        context=context,
        subreddit_rules=list(subreddit_rules or []),
    )

    reply = _try_generate(chat, system, user)
    if reply is not None and reply.reply_text.strip():
        return reply

    if on_event is not None:
        on_event(f"generate-retry:{post.url}")
    fallback_model = fast_chat if fast_chat is not None else chat
    fallback = _try_generate(fallback_model, system, user)
    if fallback is not None and fallback.reply_text.strip():
        return fallback
    return None


def _try_generate(model: object, system: str, user: str) -> ReplyGenerationV2 | None:
    """One generate attempt against a ChatModel.

    Returns ``None`` only when the model *declines* — produces no schema-valid
    reply (:class:`StructuredOutputError`), the pro→flash retry's reason for being.
    Infra errors (auth/network/quota/timeout) propagate so a misconfigured key
    surfaces as a real failure, not an indistinguishable "model declined".
    """
    from metalworks.llm import ChatModel

    if not isinstance(model, ChatModel):
        return None
    try:
        return model.complete_structured(
            system=system,
            user=user,
            output_model=ReplyGenerationV2,
            max_tokens=1500,
            temperature=0.7,
        )
    except StructuredOutputError:
        return None


def _subreddit_rules(deps: DiscoveryDeps, subreddit: str) -> list[str]:
    """Best-effort subreddit rules; empty list when the search backend can't supply them."""
    getter = getattr(deps.search, "get_subreddit_rules", None)
    if getter is None:
        return []
    try:
        rules = getter(subreddit)
    except Exception:
        return []
    return [str(r) for r in rules] if rules else []


def _build_opportunity(
    deps: DiscoveryDeps,
    *,
    post: RedditPost,
    decision: FilterDecision,
    reply: ReplyGenerationV2,
    verdict: ComplianceVerdict,
) -> Opportunity:
    return Opportunity(
        opportunity_id=str(uuid.uuid4()),
        post=post,
        draft_reply=reply.reply_text,
        account_type=reply.account_type or decision.account_type,
        relevance_reason=decision.reason,
        confidence=reply.confidence,
        risks=list(reply.risks),
        compliance=verdict,
        status="new",
        discovered_at=deps.clock(),
    )
