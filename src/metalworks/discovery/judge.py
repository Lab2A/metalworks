"""Optional LLM compliance judge — fires only when the heuristic is uncertain.

The deterministic gate (`metalworks.reddit.heuristic_check`) returns a verdict
plus a confidence; a confidence < 0.7 is the signal that the cheap heuristic
can't call it. This module ports the source's `build_llm_judge_prompt`
(clique-api `prompts/judge.py`) and runs it on the cheap `filter_model`
(Haiku judging Sonnet output, or vice versa).

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
    "or (c) genuinely add value. You are STRICT — false positives (rejecting "
    "a good reply) cost less than false negatives (shipping spam). Output a "
    "single structured verdict, never as free text."
)


def build_llm_judge_prompt(
    *,
    reply_text: str,
    post: RedditPost,
    subreddit_rules: list[str] | None = None,
) -> tuple[str, str]:
    """Build (system, user) for the optional LLM compliance judge.

    Use this when `heuristic_check` returns confidence < 0.7.
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
            "or genuinely add value?",
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
