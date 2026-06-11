"""Discovery prompt builders + their structured output models.

The filter and generate prompt builders. Two structural choices:

- Inputs are contract models, not loose dicts. Posts are `RedditPost`; voice
  and knowledge come from `DiscoveryContext` + `Persona` (the public seam),
  not from Supabase-shaped persona dicts. The persona's authentic `background`
  replaces the source's `story` — there is NO backstory-fabrication path.
- The DELIM-wrapped, untrusted-content structure is preserved verbatim: the
  post title/body are framed as `<post>` data the model must treat as content
  to act on, never as instructions. The voice/persona/tone injection and the
  false-negative bias of the filter are kept exactly.

The `model=` constants are dropped — the model is bound on the `ChatModel`.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from metalworks.contract import DiscoveryContext, Persona, RedditPost

# ── Filter (cheap model) ───────────────────────────────────────────────────


class FilterDecision(BaseModel):
    """Relevance filter output — cheap yes/no on whether to engage."""

    keep: bool = Field(description="True if this post is worth replying to. Be strict.")
    account_type: str = Field(
        description=(
            "Which account type fits best: founder | expert | company. "
            "Pick founder if the reply talks about the user's product, "
            "expert if it shares industry knowledge without product mention, "
            "company only if posting from an official company channel. "
            "Set even when keep=False."
        )
    )
    reason: str = Field(description="One sentence explaining the decision")
    confidence: float = Field(ge=0.0, le=1.0, description="0-1 confidence in the decision")


_FILTER_SYSTEM = (
    "You are a Reddit engagement filter. Your job: decide whether replying to "
    "this post would be value-add for the asker — given the business context — "
    "or whether engaging would feel like spam. You are STRICT. When in doubt, "
    "skip. The cost of skipping a marginal post is zero (more posts will arrive). "
    "The cost of engaging on an irrelevant post is community trust + spam reports. "
    "Output a single structured decision — never free text."
)


def build_filter_prompt(*, post: RedditPost, context: DiscoveryContext) -> tuple[str, str]:
    """Build (system, user) for one relevance filter call.

    `context.pinned_notes` are injected as the most-authoritative rules
    (mirroring the source's user-pinned-rules override); `context.avoid` lists
    topics to skip. Both come from the caller's `DiscoveryContext` seam.
    """
    pinned = [n.strip() for n in context.pinned_notes if n.strip()]
    avoid = [a.strip() for a in context.avoid if a.strip()]

    lines: list[str] = [
        "<post>",
        f"  <subreddit>r/{post.subreddit}</subreddit>",
        f"  <title>{post.title}</title>",
        f"  <text>{post.selftext}</text>",
        "</post>",
    ]

    if avoid:
        lines.append("")
        lines.append("<avoid>")
        lines.extend(f"  - {a}" for a in avoid)
        lines.append("</avoid>")

    if pinned:
        lines.append("")
        lines.append("<user_pinned_rules>")
        lines.extend(f"  - {p}" for p in pinned)
        lines.append("</user_pinned_rules>")

    lines.extend(
        [
            "",
            "<task>",
            "Decide: should we reply to this post?",
            "",
            "Reply YES (keep=True) only if:",
            "1. The asker is genuinely facing a problem worth a helpful reply, AND",
            "2. There is a natural way to add value without it reading as a pitch, AND",
            "3. The post is recent enough that a reply would still matter.",
            "",
            "Reply NO (keep=False) if:",
            "- The post is off-topic / unrelated to the relevant domain",
            "- The asker has already received good answers and a reply would be redundant",
            "- Engaging would feel forced or promotional",
            "- The community would mod-remove a reply for self-promotion",
            "",
            "Account type guide (set even when keep=False):",
            "- founder: the asker is debating tools or asking 'what do you use for X' — "
            "a founder voice adds product-specific credibility (always disclose affiliation).",
            "- expert: any post where outside domain knowledge adds value, including casual "
            "framings ('has anyone tried X', 'how do you handle Y'). Default to expert when "
            "unsure.",
            "- company: rare; only when the question is explicitly about the company itself.",
        ]
    )

    if avoid:
        lines.append("")
        lines.append("Skip any post that touches an item in <avoid>.")
    if pinned:
        lines.append(
            "<user_pinned_rules> overrides any conflicting rule above — apply it strictly."
        )

    lines.extend(
        [
            "",
            "Output: keep, account_type, reason (one sentence), confidence (0-1).",
            "</task>",
        ]
    )

    user = "\n".join(lines)
    return _FILTER_SYSTEM, user


# ── Generate (capable model) ───────────────────────────────────────────────


class ReplyGenerationV2(BaseModel):
    """Voice-matched reply output, with observability signals."""

    reply_text: str = Field(description="The Reddit reply text. Match the voice samples exactly.")
    account_type: str = Field(description="Account type used: founder, expert, or company")
    short_description: str = Field(
        description="Concise 5-10 word summary of what the post is about"
    )
    voice_match_self_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Self-rated voice match 0-1: did you actually match the voice samples?",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence this reply will be well-received "
        "(not downvoted, removed, or feel like spam)",
    )
    risks: list[str] = Field(
        default_factory=list[str],
        description="Flag any risks: 'promotional', 'off-topic', 'rule-violation', "
        "'AI-tells', 'low-info-gain'. Empty list if none.",
    )
    reasoning: str = Field(description="One sentence on why this reply works for this post")


_GENERATE_SYSTEM = (
    "You are an expert at writing Reddit comments that match a specific brand voice "
    "and add net-new information beyond what the asker already knows. You match the "
    "voice samples exactly — capitalization, punctuation, openers, hedging language. "
    "You write Reddit-native, not marketing-native. You never say 'great question', "
    "never use exclamation marks unless the samples do, never hedge before answering. "
    "If your reply mentions a product, you only do it when it's genuinely the best "
    "answer — and you disclose affiliation in the same sentence. You output a single "
    "structured reply — never free text."
)

_TONE_INSTRUCTIONS: dict[str, str] = {
    "helpful": "Lead with the answer. Be specific. Cite numbers, named alternatives, "
    "or hidden costs the asker doesn't know.",
    "casual": "Sound like a fellow Redditor in this community, not a marketing rep. "
    "Match the register of the top comments shown.",
    "professional": "Authoritative but not stiff. Concrete examples beat abstract claims.",
}


def build_generate_prompt(
    *,
    post: RedditPost,
    persona: Persona,
    account_type: str,
    context: DiscoveryContext,
    subreddit_rules: list[str] | None = None,
    tone: str = "helpful",
) -> tuple[str, str]:
    """Build (system, user) for a single reply generation call.

    Voice samples (`persona.example_posts`) come first because they are what the
    model pattern-matches against. `persona.voice_rubric` is the explicit
    checklist; `persona.background` is the AUTHENTIC background (never
    fabricated). `context.winning_examples` are style anchors,
    `context.voice_guidelines` + `context.pinned_notes` are caller rules.
    """
    return _GENERATE_SYSTEM, _build_generate_user(
        post=post,
        persona=persona,
        account_type=account_type,
        context=context,
        subreddit_rules=subreddit_rules or [],
        tone=tone,
    )


def _build_generate_user(
    *,
    post: RedditPost,
    persona: Persona,
    account_type: str,
    context: DiscoveryContext,
    subreddit_rules: list[str],
    tone: str,
) -> str:
    parts: list[str] = []

    # 1. Voice samples — first, the highest-signal voice training data.
    examples = [e.strip() for e in persona.example_posts if e.strip()]
    if examples:
        parts.append("<voice_samples>")
        for i, ex in enumerate(examples[:5], 1):  # Cap at 5 to keep cache hot
            parts.append(f"  <example index={i}>")
            parts.append(f"    {ex}")
            parts.append("  </example>")
        parts.append("</voice_samples>")

    # 2. Voice rubric — the explicit checklist.
    rubric = (persona.voice_rubric or "").strip()
    if rubric:
        parts.append("")
        parts.append("<voice_rubric>")
        parts.append(rubric)
        parts.append("</voice_rubric>")

    # 3. Persona — AUTHENTIC background only.
    background = (persona.background or "").strip()
    parts.append("")
    parts.append("<persona>")
    parts.append(f"  <account_type>{account_type}</account_type>")
    if background:
        parts.append(f"  <background>{background}</background>")
    parts.append("</persona>")

    # 4. Voice guidelines — caller-supplied standing voice rules.
    guidelines = [g.strip() for g in context.voice_guidelines if g.strip()]
    if guidelines:
        parts.append("")
        parts.append("<voice_guidelines>")
        parts.extend(f"  - {g}" for g in guidelines)
        parts.append("</voice_guidelines>")

    # 5. Winning examples — replies that performed well, as style anchors.
    winners = [w.strip() for w in context.winning_examples if w.strip()]
    if winners:
        parts.append("")
        parts.append("<winning_examples>")
        for w in winners[:5]:
            parts.append("  ---")
            parts.append(f"  {w}")
        parts.append("</winning_examples>")

    # 6. Pinned notes — always-injected, wins on conflict.
    pinned = [n.strip() for n in context.pinned_notes if n.strip()]
    if pinned:
        parts.append("")
        parts.append("<user_pinned_rules>")
        parts.extend(f"  - {p}" for p in pinned)
        parts.append("</user_pinned_rules>")

    # 7. Avoid — topics/claims/phrasings to never use.
    avoid = [a.strip() for a in context.avoid if a.strip()]
    if avoid:
        parts.append("")
        parts.append("<avoid>")
        parts.extend(f"  - {a}" for a in avoid)
        parts.append("</avoid>")

    # 8. Subreddit rules — community register anchor.
    rules = [r.strip() for r in subreddit_rules if r.strip()]
    if rules:
        parts.append("")
        parts.append("<subreddit_rules>")
        for r in rules[:8]:
            parts.append(f"  - {r}")
        parts.append("</subreddit_rules>")

    # 9. The post itself — full text, no truncation.
    parts.append("")
    parts.append("<post>")
    parts.append(f"  <subreddit>r/{post.subreddit}</subreddit>")
    parts.append(f"  <title>{post.title}</title>")
    parts.append(f"  <text>{post.selftext}</text>")
    parts.append("</post>")

    # 10. Task instruction.
    tone_instruction = _TONE_INSTRUCTIONS.get(tone, _TONE_INSTRUCTIONS["helpful"])
    parts.append("")
    parts.append("<task>")
    parts.append(f"Write a Reddit reply to <post> as the {account_type}.")
    parts.append("")
    parts.append("Hard constraints:")
    parts.append(
        "- Match <voice_samples> exactly. Capitalization, punctuation, openers, sentence rhythm."
    )
    if rubric:
        parts.append("- Follow every rule in <voice_rubric>.")
    if guidelines:
        parts.append("- Follow every rule in <voice_guidelines>.")
    if pinned:
        parts.append("- <user_pinned_rules> overrides any conflict above — apply it strictly.")
    if avoid:
        parts.append("- Never touch anything in <avoid>.")
    parts.append(
        "- Add information the asker doesn't already know. Concrete numbers, named "
        "alternatives, hidden costs, specific tradeoffs."
    )
    parts.append(
        "- Never paraphrase the post. Never give generic advice "
        "('it depends', 'consider your needs')."
    )
    parts.append("- Never use 'great question', 'happy to help', or other AI-tells.")
    parts.append(f"- Tone: {tone_instruction}")
    parts.append("- Disclose affiliation in the same sentence if you mention a product.")
    parts.append("")
    parts.append("Then output:")
    parts.append("- reply_text: the comment to post")
    parts.append(
        "- account_type: which persona you wrote as (founder | expert | company). "
        "Founder = your own product. Expert = industry knowledge, no product pitch. "
        "Company = official company channel."
    )
    parts.append("- short_description: 5-10 words summarizing the post")
    parts.append(
        "- voice_match_self_score: rate 0-1 how exactly your reply matches <voice_samples>. "
        "1.0 = identical voice, 0.0 = totally different."
    )
    parts.append(
        "- confidence: 0-1 how confident this reply will land "
        "(not downvoted, removed, feel-like-spam)"
    )
    parts.append(
        "- risks: any of ['promotional', 'off-topic', 'rule-violation', 'AI-tells', "
        "'low-info-gain']"
    )
    parts.append("- reasoning: one sentence on why this reply works")
    parts.append("</task>")

    return "\n".join(parts)
