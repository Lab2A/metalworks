"""Discovery loop — the filter → generate → gate engagement pipeline.

`run_discovery` takes caller-supplied queries, searches Reddit, and for each
candidate post runs a cheap relevance filter, a voice-matched reply generation
(with a pro→flash degradation retry), and a compliance gate (the deterministic
heuristic, escalating to an LLM judge when uncertain), emitting gated
`Opportunity` drafts. Nothing is ever posted from here.

All external surfaces — models, search, storage, and the knowledge a caller
wants injected (voice, personas, pinned notes) — arrive through `DiscoveryDeps`,
so the loop runs fully offline with fakes and against any provider with real
adapters.
"""

from metalworks.discovery.deps import DiscoveryDeps
from metalworks.discovery.judge import build_llm_judge_prompt, llm_judge
from metalworks.discovery.prompts import (
    FilterDecision,
    ReplyGenerationV2,
    build_filter_prompt,
    build_generate_prompt,
)
from metalworks.discovery.service import run_discovery

__all__ = [
    "DiscoveryDeps",
    "FilterDecision",
    "ReplyGenerationV2",
    "build_filter_prompt",
    "build_generate_prompt",
    "build_llm_judge_prompt",
    "llm_judge",
    "run_discovery",
]
