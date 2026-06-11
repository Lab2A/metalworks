"""Tests for the discovery prompt builders + output models (offline, pure)."""

from __future__ import annotations

from metalworks.contract import DiscoveryContext, Persona, RedditPost
from metalworks.discovery import FilterDecision, ReplyGenerationV2
from metalworks.discovery.prompts import build_filter_prompt, build_generate_prompt


def _post() -> RedditPost:
    return RedditPost(
        post_id="abc123",
        subreddit="sysadmin",
        title="What do you use for log aggregation on a budget?",
        selftext="Self-hosting a 12-node cluster, ELK is too heavy. Alternatives?",
        url="https://reddit.com/r/sysadmin/comments/abc123/x/",
    )


def test_filter_prompt_wraps_post_as_untrusted_content() -> None:
    system, user = build_filter_prompt(post=_post(), context=DiscoveryContext())
    assert "engagement filter" in system
    assert "<post>" in user
    assert "<title>What do you use for log aggregation" in user
    assert "<text>Self-hosting" in user
    assert "keep" in user and "account_type" in user


def test_filter_prompt_injects_pinned_notes_and_avoid() -> None:
    context = DiscoveryContext(
        pinned_notes=["Only engage on technical posts"],
        avoid=["competitor X"],
    )
    _system, user = build_filter_prompt(post=_post(), context=context)
    assert "<user_pinned_rules>" in user
    assert "Only engage on technical posts" in user
    assert "<avoid>" in user
    assert "competitor X" in user
    assert "overrides any conflicting rule" in user


def test_generate_prompt_injects_voice_samples_and_authentic_background() -> None:
    persona = Persona(
        example_posts=["honestly just use loki. way lighter than elk.", "ymmv but works for me"],
        voice_rubric="lowercase, no exclamation marks, lead with the answer",
        background="founder of a log-tooling startup, former SRE",
    )
    context = DiscoveryContext(
        voice_guidelines=["never pitch in the first sentence"],
        winning_examples=["loki + grafana is the budget stack everyone lands on"],
    )
    _system, user = build_generate_prompt(
        post=_post(),
        persona=persona,
        account_type="founder",
        context=context,
        subreddit_rules=["No self-promotion", "Be civil"],
    )
    assert "<voice_samples>" in user
    assert "honestly just use loki" in user
    assert "<voice_rubric>" in user
    assert "<background>founder of a log-tooling startup" in user
    assert "<voice_guidelines>" in user
    assert "<winning_examples>" in user
    assert "<subreddit_rules>" in user
    assert "No self-promotion" in user
    assert "<account_type>founder</account_type>" in user


def test_generate_prompt_omits_empty_optional_blocks() -> None:
    _system, user = build_generate_prompt(
        post=_post(),
        persona=Persona(),
        account_type="expert",
        context=DiscoveryContext(),
    )
    # Block headers sit on their own line; the task text references some tags
    # inline, so assert against the opening-tag lines, not bare substrings.
    assert "\n<voice_samples>" not in user
    assert "  <example index=" not in user
    assert "\n<voice_rubric>" not in user
    assert "\n<winning_examples>" not in user
    assert "\n<subreddit_rules>" not in user
    # The post and task are always present.
    assert "\n<post>" in user
    assert "\n<task>" in user


def test_output_models_validate() -> None:
    fd = FilterDecision(keep=True, account_type="expert", reason="relevant", confidence=0.8)
    assert fd.keep
    rg = ReplyGenerationV2(
        reply_text="x",
        account_type="expert",
        short_description="a post",
        voice_match_self_score=0.9,
        confidence=0.8,
        reasoning="works",
    )
    assert rg.risks == []
