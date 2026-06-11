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
from metalworks.discovery.judge import llm_judge
from metalworks.discovery.prompts import FilterDecision, ReplyGenerationV2
from metalworks.discovery.service import draft_reply, filter_post, run_discovery

# Public surface: the loop (`run_discovery`), its dependency bundle
# (`DiscoveryDeps`), the three standalone seams a caller composes
# (`filter_post`, `draft_reply`, `llm_judge`), and the two structured-output
# types they return (`FilterDecision`, `ReplyGenerationV2`). The prompt builders
# (`build_filter_prompt`, `build_generate_prompt`, `build_llm_judge_prompt`) are
# internal — import them from `metalworks.discovery.prompts` / `.judge`.
__all__ = [
    "DiscoveryDeps",
    "FilterDecision",
    "ReplyGenerationV2",
    "draft_reply",
    "filter_post",
    "llm_judge",
    "run_discovery",
]
