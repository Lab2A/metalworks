"""The research vertical: brief → Reddit corpus → triage → clustered demand
report with verified, permalinked quotes.

Every stage takes a `ResearchDeps` instead of reaching for module-level
LLM / embedding / storage singletons, so the pipeline runs offline with fakes
and against any provider with real adapters.

Public surface lands incrementally across M2; this package is import-safe with
no provider dependencies (the heavy bits live behind the `[research]` extra).
"""

from metalworks.research.deps import CommentSource, CorpusReader, ResearchDeps
from metalworks.research.pipeline import run_research
from metalworks.research.types import (
    ClassifierVerdict,
    ExplorationItem,
    HydrationResult,
    LoadedComment,
    LoadedPost,
    MonthRef,
    SynthesisOutput,
    TriageBuckets,
    TriangulationOutput,
)

__all__ = [
    "ClassifierVerdict",
    "CommentSource",
    "CorpusReader",
    "ExplorationItem",
    "HydrationResult",
    "LoadedComment",
    "LoadedPost",
    "MonthRef",
    "ResearchDeps",
    "SynthesisOutput",
    "TriageBuckets",
    "TriangulationOutput",
    "run_research",
]
