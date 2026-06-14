"""The research vertical: brief → Reddit corpus → triage → clustered demand
report with verified, permalinked quotes.

Every stage takes a `ResearchDeps` instead of reaching for module-level
LLM / embedding / storage singletons, so the pipeline runs offline with fakes
and against any provider with real adapters.

Public surface lands incrementally across M2; this package is import-safe with
no provider dependencies (the heavy bits live behind the `[research]` extra).
"""

from metalworks.research.deps import CommentSource, CorpusReader, ResearchDeps
from metalworks.research.landscape import run_competitor_map
from metalworks.research.pipeline import run_research
from metalworks.research.surface import build_ux_skeleton, decide_surface

# Public surface: the entry point (`run_research`), the dependency bundle
# (`ResearchDeps`), and the two injection protocols a caller implements to swap
# the corpus / comment source. The pipeline's intermediate result types
# (ExplorationItem, LoadedPost, SynthesisOutput, …) are internal — import them
# from `metalworks.research.types` if you need them; they are not part of the
# stable surface.
__all__ = [
    "CommentSource",
    "CorpusReader",
    "ResearchDeps",
    "build_ux_skeleton",
    "decide_surface",
    "run_competitor_map",
    "run_research",
]
