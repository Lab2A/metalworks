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
    build_design_system,
    render_design_md,
    render_design_preview_html,
)
from metalworks.research.ideate import ideate_from_idea, ideate_from_report
from metalworks.research.landscape import run_competitor_map, run_landscape
from metalworks.research.launch import build_launch_assets, plan_channels
from metalworks.research.logo import build_logo_set, render_logo_picker_html
from metalworks.research.marketing import content_plan_from_report
from metalworks.research.pipeline import run_research
from metalworks.research.site import build_marketing_site, render_site_html
from metalworks.research.surface import build_ux_skeleton, decide_surface
from metalworks.research.synthesis import build_positioning_brief
from metalworks.research.validate import validate

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
    "build_design_system",
    "build_launch_assets",
    "build_logo_set",
    "build_marketing_site",
    "build_positioning_brief",
    "build_ux_skeleton",
    "content_plan_from_report",
    "decide_surface",
    "ideate_from_idea",
    "ideate_from_report",
    "plan_channels",
    "render_design_md",
    "render_design_preview_html",
    "render_logo_picker_html",
    "render_site_html",
    "run_assessment",
    "run_competitor_map",
    "run_landscape",
    "run_research",
    "validate",
]
