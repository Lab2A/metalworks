"""LLM compliance judge — the authoritative gate for "does this read as authentic."

The deterministic gate (`metalworks.reddit.heuristic_check`) is a cheap first
pass: its regex denylist hard-rejects the obvious AI-tells, but a finite phrase
list can't enumerate every inauthentic phrasing. So the discovery pipeline
escalates any heuristic *pass* to this judge — it, not the phrase list, is the
real arbiter of whether a reply reads as a genuine human contribution. Runs on
the cheap `filter_model` (Haiku judging Sonnet output, or vice versa).

The judge is STRICT by design: rejecting a good reply (false positive) costs
less than shipping spam (false negative). It returns a `ComplianceVerdict`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from metalworks.contract import ComplianceVerdict, RedditPost

if TYPE_CHECKING:
    from metalworks.discovery.deps import DiscoveryDeps

_LLM_JUDGE_SYSTEM = (
    "You are a Reddit reply compliance judge. Given a reply, the post it's "
    "responding to, and the subreddit rules, you decide whether posting it "
    "would: (a) get the comment removed by mods, (b) get downvoted as spam, "
    "or (c) genuinely add value. You are the authoritative gate for whether the "
    "reply READS AS AUTHENTIC — written by a real person in this community, not "
    "generated. Judge the whole voice: AI-tell openers and filler, generic "
    "advice, marketing register, hedging — not just a fixed list of phrases. You "
    "are STRICT — false positives (rejecting a good reply) cost less than false "
    "negatives (shipping spam). Output a single structured verdict, never as "
    "free text."
)


def build_llm_judge_prompt(
    *,
    reply_text: str,
    post: RedditPost,
    subreddit_rules: list[str] | None = None,
) -> tuple[str, str]:
    """Build (system, user) for the LLM compliance judge.

    The pipeline runs this on any reply the deterministic `heuristic_check`
    passes — the judge, not the regex denylist, is the real authentic-voice gate.
    """
    rules_block = ""
    if subreddit_rules:
        rules_block = (
            "<subreddit_rules>\n"
            + "\n".join(f"- {r}" for r in subreddit_rules[:8])
            + "\n</subreddit_rules>"
        )

    lines: list[str] = [
        "<post>",
        f"  <subreddit>r/{post.subreddit}</subreddit>",
        f"  <title>{post.title}</title>",
        f"  <text>{post.selftext}</text>",
        "</post>",
        "",
    ]
    if rules_block:
        lines.append(rules_block)
        lines.append("")
    lines.extend(
        [
            "<generated_reply>",
            reply_text,
            "</generated_reply>",
            "",
            "<task>",
            "Would shipping this reply: get removed by mods, get downvoted as spam, "
            "or genuinely add value? Does it read as authentic — a real person in "
            "this community — or does it carry AI-tells (any inauthentic opener, "
            "filler, or generic phrasing, not just a fixed list)?",
            "Output with: pass (bool), violations (list of specific issues — "
            "empty when pass=True), confidence (0-1).",
            "</task>",
        ]
    )
    user = "\n".join(lines)
    return _LLM_JUDGE_SYSTEM, user


def llm_judge(
    deps: DiscoveryDeps,
    *,
    reply_text: str,
    post: RedditPost,
    subreddit_rules: list[str] | None = None,
) -> ComplianceVerdict:
    """Escalate an uncertain reply to the LLM judge → ComplianceVerdict.

    Runs on the cheap `deps.filter_model` (a different model than the generator).
    """
    system, user = build_llm_judge_prompt(
        reply_text=reply_text, post=post, subreddit_rules=subreddit_rules
    )
    return deps.filter_model.complete_structured(
        system=system,
        user=user,
        output_model=ComplianceVerdict,
        max_tokens=300,
        temperature=0.0,
    )
