"""The Distribution pillar's research arm — one pillar for pushes + streams.

Distribution collapses the two thin pillars that came before it (the former
Pillar F "Launch" and Pillar G "Content/SEO") into a single cadence axis: the
one-shot *pushes* (launch moments) and the compounding *streams* (content/SEO,
ongoing Reddit engagement) are the spike-and-tail of the same thing, so they
live in one pillar instead of two. Off a finished
:class:`~metalworks.contract.research.DemandReport`, Distribution plans and
drafts those surfaces — drafting only, a human executes — with every claim held
to the no-cite-no-claim gate (see
:class:`~metalworks.contract.distribution.ClaimCitation`). Its execution arm is
the Reddit engagement module (``metalworks.reddit``), re-homed here downstream.

This package is the scaffolding the Distribution build fills in over D1+; it is
import-safe with no provider dependencies. D2 fills in the channel-strategy core
(``channels.py``): the entity→channel routing engine that emits test→focus
channel experiments.
"""

from __future__ import annotations

from metalworks.research.distribution.assets import build_channel_assets
from metalworks.research.distribution.channels import (
    build_channel_strategy,
    classify_product,
    extract_channel_signals,
    select_channels,
)
from metalworks.research.distribution.data_asset import build_data_asset
from metalworks.research.distribution.geo import (
    answer_briefs,
    build_geo_plan,
    citability_probes,
    participation_targets,
)
from metalworks.research.distribution.plan import plan_distribution
from metalworks.research.distribution.requirements import (
    conversion_surface_requirement,
    distribution_requirements,
    loop_requirements,
)

__all__ = [
    "answer_briefs",
    "build_channel_assets",
    "build_channel_strategy",
    "build_data_asset",
    "build_geo_plan",
    "citability_probes",
    "classify_product",
    "conversion_surface_requirement",
    "distribution_requirements",
    "extract_channel_signals",
    "loop_requirements",
    "participation_targets",
    "plan_distribution",
    "select_channels",
]
