"""The research vertical: brief → Reddit corpus → triage → clustered demand
report with verified, permalinked quotes.

Every stage takes a `ResearchDeps` instead of reaching for module-level
LLM / embedding / storage singletons, so the pipeline runs offline with fakes
and against any provider with real adapters.

Public surface lands incrementally across M2; this package is import-safe with
no provider dependencies (the heavy bits live behind the `[research]` extra).
"""

from metalworks.research.assess import run_assessment
from metalworks.research.deps import CommentSource, CorpusReader, ResearchDeps
from metalworks.research.design import (
    DEFAULT_TASTE,
    TASTE_PRESETS,
    build_design_system,
    render_design_md,
    render_design_preview_html,
)
from metalworks.research.design_review import review_design
from metalworks.research.distribution import (
    answer_briefs,
    build_channel_assets,
    build_channel_strategy,
    build_data_asset,
    build_geo_plan,
    citability_probes,
    conversion_surface_requirement,
    distribution_requirements,
    loop_requirements,
    participation_targets,
    plan_distribution,
)
from metalworks.research.ideate import ideate_from_idea, ideate_from_report
from metalworks.research.landscape import run_competitor_map, run_landscape
from metalworks.research.logo import build_logo_set, render_logo_picker_html
from metalworks.research.pipeline import run_research
from metalworks.research.synthesis import build_positioning_brief
from metalworks.research.validate import validate

# Public surface: the entry point (`run_research`), the dependency bundle
# (`ResearchDeps`), and the two injection protocols a caller implements to swap
# the corpus / comment source. The pipeline's intermediate result types
# (ExplorationItem, LoadedPost, SynthesisOutput, …) are internal — import them
# from `metalworks.research.types` if you need them; they are not part of the
# stable surface.
__all__ = [
    "DEFAULT_TASTE",
    "TASTE_PRESETS",
    "CommentSource",
    "CorpusReader",
    "ResearchDeps",
    "answer_briefs",
    "build_channel_assets",
    "build_channel_strategy",
    "build_data_asset",
    "build_design_system",
    "build_geo_plan",
    "build_logo_set",
    "build_positioning_brief",
    "citability_probes",
    "conversion_surface_requirement",
    "distribution_requirements",
    "ideate_from_idea",
    "ideate_from_report",
    "loop_requirements",
    "participation_targets",
    "plan_distribution",
    "render_design_md",
    "render_design_preview_html",
    "render_logo_picker_html",
    "review_design",
    "run_assessment",
    "run_competitor_map",
    "run_landscape",
    "run_research",
    "validate",
]
