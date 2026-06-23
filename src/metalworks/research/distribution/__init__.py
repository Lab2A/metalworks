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

from metalworks.research.distribution.channels import (
    build_channel_strategy,
    classify_product,
    extract_channel_signals,
    select_channels,
)

__all__ = [
    "build_channel_strategy",
    "classify_product",
    "extract_channel_signals",
    "select_channels",
]
