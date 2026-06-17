"""Startup-shape contract — the reusable base-stack catalog.

A *shape* is a reusable reference architecture for a class of product, surfaced
in two layers: a small set of irreducible BASE STACKS (the real backend a
generated product inherits) plus composable MODULES, named together as a
PRODUCT SHAPE. metalworks stays a SPEC engine: a shape carries a
``scaffold_target`` pointer that a Claude Code terminal resolves to a starter,
then builds and runs the product against — metalworks never hosts or vendors the
backend. "Real backend, not a thin scaffold" means the shape is a rich enough
spec that the builder produces a real one.

A shape is MATCHED to a finished :class:`~metalworks.contract.bundle.Research`
bundle (never the other way): :class:`~metalworks.shapes.matcher.ShapeMatcher`
reads the demand report and verdict and returns ranked :class:`ShapeMatch`
results, each cited back to the clusters that drove it. The matcher is READ-ONLY
over the report (it cannot mutate it) and VERDICT-REACTIVE (it reads
``Assessment.decision``); it never touches the honesty gates (triage,
quote-verification, breadth, ``assess()``), so the corpus can still falsify a
shape (a NO-GO report yields no match).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from metalworks.contract.evidence import EvidenceRef
from metalworks.contract.research import SignalStrength
from metalworks.contract.surface import SurfaceKind

# The composable modules. ``progress`` is the spaced-repetition / grading /
# progress capability — named to avoid colliding with the ``Assessment`` verdict
# contract.
ModuleId = Literal["payments", "feed", "threads", "progress", "paywall"]

# The six irreducible base stacks, partitioned by dominant backend primitive.
BaseStackId = Literal["store", "match", "synthesize", "automate", "generate", "watch"]


class Module(BaseModel):
    """One composable capability that snaps onto a base stack."""

    id: ModuleId
    adds: str = Field(description="The backend capability this module contributes.")
    requires: list[ModuleId] = Field(
        default_factory=list[ModuleId],
        description="Other modules this one depends on (compatibility).",
    )


class BaseStack(BaseModel):
    """An irreducible reusable backend — the spec a Claude Code terminal builds from.

    ``scaffold_target`` is the bridge to runnable code: a stable pointer (a starter
    repo, a directory, or an archetype id) the builder resolves and builds against.
    The metalworks contract carries only the pointer, never the runnable stack — the
    "spec, don't vendor" identity holds.
    """

    id: BaseStackId
    verb: str = Field(description="The product's dominant verb, e.g. 'store' / 'synthesize'.")
    backend_capabilities: list[str] = Field(
        description="What the inherited backend provides (auth, CRUD, evidence store, ...)."
    )
    default_modules: list[ModuleId] = Field(default_factory=list[ModuleId])
    scaffold_target: str = Field(
        description="Stable pointer the builder resolves to a starter (repo / dir / id)."
    )


class MatchSignature(BaseModel):
    """The structured predicate a matcher scores against a report — never prose."""

    cluster_keywords: list[str] = Field(
        default_factory=list[str],
        description="Scored against InsightCluster.claim (embedding sim, keyword fallback).",
    )
    surface: SurfaceKind | None = Field(
        default=None, description="Preferred build surface, when the shape implies one."
    )
    build_signals: list[str] = Field(
        default_factory=list[str],
        description="Scored against BuildSpec.features[].title when a build spec is supplied.",
    )
    min_signal: SignalStrength = Field(
        default=SignalStrength.MEDIUM,
        description="Breadth floor the matched cluster must clear for this shape to qualify.",
    )


class ProductShape(BaseModel):
    """A named, recognizable product = base stack + modules + a thin domain skin."""

    name: str = Field(description="Recognizable product-shape name, e.g. 'submission-portal'.")
    base_stack: BaseStackId
    modules: list[ModuleId] = Field(default_factory=list[ModuleId])
    domain_skin: str = Field(
        default="", description="The domain framing layered on the base (one line)."
    )
    match_signature: MatchSignature


class ShapeMatch(BaseModel):
    """One ranked match of a ProductShape to a research bundle, cited to its clusters.

    ``evidence_refs`` are the cluster refs that drove the match, so a match is
    itself grounded — the same cite-or-die discipline the rest of the engine uses.
    """

    shape: ProductShape
    base_stack: BaseStack = Field(description="The resolved base stack the shape sits on.")
    score: float = Field(ge=0.0, le=1.0, description="Composite match score (0..1).")
    rationale: str = Field(description="One line: why this shape fits this demand.")
    evidence_refs: list[EvidenceRef] = Field(
        default_factory=list[EvidenceRef],
        description="Cluster refs (kind='cluster') that drove the match.",
    )


__all__ = [
    "BaseStack",
    "BaseStackId",
    "MatchSignature",
    "Module",
    "ModuleId",
    "ProductShape",
    "ShapeMatch",
]
