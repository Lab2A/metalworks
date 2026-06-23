"""D9 — the participation/execution arm of Distribution.

The GEO participation stream (:func:`~metalworks.research.distribution.geo.\
participation_targets`) names *which* threads to engage; THIS module engages them.
It is the one channel metalworks can OPERATE rather than merely plan — the moat
the Distribution thesis rests on ("metalworks knows the real threads"). The
Reddit engagement capability (``metalworks.reddit`` + the discovery reply seam)
is re-homed here as Distribution's execution arm.

:func:`participation_reply` takes one D6
:class:`~metalworks.contract.distribution.ParticipationTarget` (its real
``permalink`` + ``why`` + ``suggested_angle``) and drafts a disclosed,
founder-voiced reply for that exact thread, reusing the existing reply machinery
(:func:`~metalworks.discovery.draft_reply`) and the shared deterministic honesty
gate (:func:`~metalworks.reddit.heuristic_check`). The platform invariants are the
ONE voice system in ``reddit.stylebook`` (no "upvote" ask, native-first, no AI
tells), the same one D4's channel assets enforce.

POSTING STAYS GATED. This drafts only — it never posts. The returned
:class:`~metalworks.contract.distribution.ParticipationReply` carries
``requires_human`` / ``posting_gated`` (both always true); a human posts it via
the triple-gated ``reddit_post_comment`` path (operator opt-in + a confirm-token
over the exact text + a re-run of the gate). DRAFTING ONLY.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from metalworks.contract import (
    ComplianceVerdict,
    DemandReport,
    DiscoveryContext,
    ParticipationReply,
    ParticipationTarget,
    Persona,
    RedditPost,
)
from metalworks.reddit import heuristic_check
from metalworks.reddit.stylebook import strip_upvote_ask

if TYPE_CHECKING:
    from metalworks.research.deps import ResearchDeps


# Pull the base36 post id + subreddit out of a Reddit permalink (mirrors
# `reddit.search._POST_ID_RE` and the `r/Name` matcher in geo.py / channels.py).
_POST_ID_RE = re.compile(r"/comments/([a-z0-9]+)")
_SUBREDDIT_RE = re.compile(r"\br/([A-Za-z0-9][A-Za-z0-9_]{1,50})\b")

# The standing disclosure rule every participation reply is drafted under — the
# usage policy's honesty bar, made explicit to the generator. Affiliation is
# disclosed in the same breath as the help; nothing is astroturfed.
_DISCLOSURE_NOTE = (
    "Disclose your affiliation in the same sentence you offer help. Answer the "
    "question directly and helpfully FIRST; never drop a bare link or lead with a "
    "pitch. Write as the founder, in first person, plainly — not in brand voice. "
    "Never ask anyone to upvote. Earn the citation by being the most useful reply "
    "in the thread."
)


def _subreddit_from_target(target: ParticipationTarget) -> str:
    """The bare subreddit name (no 'r/') for the target's thread.

    Prefers the target's ``community`` label, falls back to parsing the permalink.
    Returns 'unknown' when neither names a subreddit — drafting still proceeds.
    """
    community = target.community.strip()
    if community.lower().startswith("r/"):
        return community[2:].strip() or "unknown"
    m = _SUBREDDIT_RE.search(target.permalink)
    if m:
        return m.group(1)
    return community or "unknown"


def _post_from_target(target: ParticipationTarget) -> RedditPost:
    """Build a minimal :class:`RedditPost` for the target's exact thread.

    The reply machinery drafts against a post; D6 hands us the real ``permalink``
    + the ``why`` (what the audience is asking there). We carry the ``why`` as the
    title and ``suggested_angle`` as the body so the generator has the thread's
    actual question — no network call, so this stays offline-testable. A caller
    that wants the live thread can hydrate a fuller post and pass it through.
    """
    m = _POST_ID_RE.search(target.permalink)
    post_id = m.group(1) if m else "unknown"
    return RedditPost(
        post_id=post_id,
        subreddit=_subreddit_from_target(target),
        title=target.why.strip() or "(thread the audience is asking in)",
        selftext=target.suggested_angle.strip(),
        url=target.permalink,
    )


def participation_reply(
    deps: ResearchDeps,
    report: DemandReport,
    target: ParticipationTarget,
    *,
    voice: str | None = None,
    persona: Persona | None = None,
    live_post: RedditPost | None = None,
) -> ParticipationReply:
    """Draft a disclosed, compliance-gated reply for one D6 participation target.

    Reuses the existing reply machinery (:func:`~metalworks.discovery.draft_reply`,
    persona/voice-aware with the pro→flash degradation retry) to draft for the
    target's exact thread, applies the single voice system's no-"upvote" guard
    (``reddit.stylebook.strip_upvote_ask``), then runs the shared deterministic
    honesty gate (:func:`~metalworks.reddit.heuristic_check`) over the result. The
    returned :class:`ParticipationReply` carries the verdict and references the
    target's thread (``community`` + ``permalink``).

    ``live_post`` lets a caller pass a hydrated thread (live title/body); when
    absent the post is built from the target so the draft stays offline. ``voice``
    + ``persona`` thread the caller's authentic voice through. POSTING STAYS
    GATED — ``requires_human`` / ``posting_gated`` default true and are never
    flipped here; a human posts via ``reddit_post_comment``. DRAFTING ONLY.
    """
    # Local import keeps the discovery seam (and its lazy LLM use) off the import
    # path of `import metalworks` — same pattern the rest of the pillar follows.
    from metalworks.discovery import draft_reply

    _ = report  # the target already carries its grounded `why`; report reserved
    post = live_post if live_post is not None else _post_from_target(target)

    context = DiscoveryContext(
        voice_guidelines=[voice] if voice else [],
        pinned_notes=[_DISCLOSURE_NOTE, f"The angle to take: {target.suggested_angle.strip()}"],
    )
    reply = draft_reply(
        deps.chat,
        post,
        persona or Persona(),
        "founder",
        context,
        subreddit_rules=[],
        fast_chat=deps.fast_chat,
    )
    draft = strip_upvote_ask(reply.reply_text.strip()) if reply is not None else ""
    verdict = (
        heuristic_check(draft)
        if draft
        else ComplianceVerdict.model_validate(
            {"pass": False, "violations": ["empty"], "confidence": 1.0}
        )
    )
    return ParticipationReply(
        community=target.community,
        permalink=target.permalink,
        draft=draft,
        compliance=verdict,
    )
