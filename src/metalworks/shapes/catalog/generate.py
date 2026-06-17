"""Generate base stack — produce an artifact from a prompt or input.

The LLM-orchestration backend: a generated product takes a prompt (or structured
input) and produces an artifact — copy, an image, a document, a per-recipient
variation, or a chain of actions. Consolidates the demand pattern of "I make this
thing by hand and want it auto-produced from a prompt." Its product shapes range
from one-shot generators to a ``copilot`` (inline assistance) and an
``autonomous-agent`` (which blends the ``automate`` verb: it plans and executes a
multi-step job rather than returning a single artifact).
"""

from __future__ import annotations

from metalworks.contract.research import SignalStrength
from metalworks.contract.shape import BaseStack, MatchSignature, ProductShape
from metalworks.shapes import register_base_stack, register_shape

GENERATE = BaseStack(
    id="generate",
    verb="generate",
    backend_capabilities=[
        "generation / llm orchestration",
        "prompt + eval harness",
        "artifact store",
        "usage credits / metering",
    ],
    default_modules=[],
    scaffold_target="starter:generate-aitool",
)

ASSET_GENERATOR = ProductShape(
    name="asset-generator",
    base_stack="generate",
    modules=["paywall"],
    domain_skin="A user describes an asset; the product produces it on demand, metered by credits.",
    match_signature=MatchSignature(
        cluster_keywords=[
            "spend hours making assets by hand",
            "create graphics without a designer",
            "generate images from a prompt",
            "produce marketing visuals at scale",
        ],
        surface="web",
        build_signals=["prompt", "generate", "asset", "image", "credits"],
        min_signal=SignalStrength.MEDIUM,
    ),
)

DOC_GENERATOR = ProductShape(
    name="doc-generator",
    base_stack="generate",
    modules=["paywall"],
    domain_skin="A user supplies structured input; the product drafts the document for them.",
    match_signature=MatchSignature(
        cluster_keywords=[
            "write the same documents over and over",
            "draft reports from a template",
            "generate paperwork from structured data",
            "auto fill contracts and proposals",
        ],
        surface="web",
        build_signals=["template", "draft", "document", "export", "generate"],
        min_signal=SignalStrength.MEDIUM,
    ),
)

PERSONALIZATION_AT_SCALE = ProductShape(
    name="personalization-at-scale",
    base_stack="generate",
    modules=[],
    domain_skin="One source message becomes a tailored variation for every recipient.",
    match_signature=MatchSignature(
        cluster_keywords=[
            "personalize emails for every customer by hand",
            "tailor messaging to thousands of users",
            "generate variations for each segment",
            "one off content per recipient at scale",
        ],
        surface="web",
        build_signals=["personalize", "variation", "segment", "recipient", "generate"],
        min_signal=SignalStrength.MEDIUM,
    ),
)

COPILOT = ProductShape(
    name="copilot",
    base_stack="generate",
    modules=[],
    domain_skin="An assistant embedded in the user's work, suggesting the next step inline.",
    match_signature=MatchSignature(
        cluster_keywords=[
            "want an assistant that suggests the next step",
            "inline suggestions while i work",
            "autocomplete my writing as i type",
            "a copilot embedded in the tool",
        ],
        surface="web",
        build_signals=["assistant", "suggestion", "inline", "autocomplete", "copilot"],
        min_signal=SignalStrength.MEDIUM,
    ),
)

AUTONOMOUS_AGENT = ProductShape(
    name="autonomous-agent",
    base_stack="generate",
    modules=[],
    domain_skin="Blends automate: an agent plans and executes a multi-step job end to end.",
    match_signature=MatchSignature(
        cluster_keywords=[
            "an agent that completes tasks autonomously",
            "automate a multi step workflow end to end",
            "run jobs without me babysitting it",
            "let it plan and execute on its own",
        ],
        surface="web",
        build_signals=["agent", "autonomous", "workflow", "plan", "execute"],
        min_signal=SignalStrength.MEDIUM,
    ),
)

register_base_stack(GENERATE)
register_shape(ASSET_GENERATOR)
register_shape(DOC_GENERATOR)
register_shape(PERSONALIZATION_AT_SCALE)
register_shape(COPILOT)
register_shape(AUTONOMOUS_AGENT)
