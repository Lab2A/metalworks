"""Cross-pillar evidence references — the spine of the grounded evidence chain.

Every downstream pillar artifact (positioning, competitor map, site, launch
asset, content plan) references upstream evidence by id via `EvidenceRef`,
never by free text — mirroring the index discipline `CrossReference` already
uses. `DemandReport.evidence` collates the leaf evidence (quotes, web
findings, price evidence) into a flat `EvidenceRecord` list that refs resolve
against.

Evidence ids are content-addressed and stable across (de)serialization (see
`metalworks.contract.research._evidence_id`). They are scoped by
resolution-within-report — an `EvidenceRef` resolves against the
`DemandReport` it travels with — so the id only has to be unique and stable
*within* one report, not globally. A re-run that surfaces the same source
text yields the same id; different text yields a different one.

The no-cite-no-claim gate (the generalization of the pipeline's existing
no-quote-no-theme rule): a downstream claim-bearing field with zero resolvable
`EvidenceRef`s is dropped at assembly. Resolution is exact — an
`evidence_id` that does not match any `EvidenceRecord.id` in the source report
is treated as unresolvable.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

EvidenceKind = Literal["quote", "web", "price", "cluster"]
Provenance = Literal["verbatim", "grounded-web", "derived"]


class EvidenceRef(BaseModel):
    """A downstream pillar's pointer to one piece of upstream evidence.

    Resolves against the source `DemandReport.evidence` list by `evidence_id`,
    or against an `InsightCluster` by `cluster_rank` when `kind == "cluster"`
    (clusters have no leaf id of their own).
    """

    evidence_id: str = Field(
        default="",
        description="Target ResolvedCitation/WebFinding/PriceEvidence id. Empty for a cluster ref.",
    )
    kind: EvidenceKind = Field(description="Which evidence family this points at.")
    cluster_rank: int | None = Field(
        default=None,
        description="Set only when kind=='cluster' — 1-based InsightCluster.rank.",
    )


class EvidenceRecord(BaseModel):
    """One flat, resolvable piece of evidence — the shape `report.evidence` returns.

    `provenance` is the two-tier honesty label: `verbatim` (exact-matched
    corpus quote, high trust), `grounded-web` (LLM paraphrase over a real
    cited URL, medium), `derived` (computed/structural, no single source).
    """

    id: str
    kind: Literal["quote", "web", "price"]
    text: str
    url: str = Field(description="permalink (quote/price) or source_url (web); '' if none.")
    provenance: Provenance
