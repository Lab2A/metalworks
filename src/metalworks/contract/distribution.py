"""Distribution contract — the output spine of the Distribution pillar.

Distribution is ONE pillar. It replaces the two thin, overlapping pillars that
preceded it — Pillar F ("Launch") and Pillar G ("Content/SEO") — which were just
the spike-vs-compounding ends of a single cadence axis, double-encoded as two
pillars. Distribution collapses them: it plans and drafts the *pushes* (the
one-shot launch moments — Product Hunt, Show HN, an X thread) and the *streams*
(the compounding surfaces — content/SEO pages, ongoing Reddit engagement) off a
finished :class:`~metalworks.contract.research.DemandReport`, and hands them to a
human to execute. Its execution arm is the Reddit engagement module
(``metalworks.reddit``), re-homed under Distribution downstream.

The honesty contract is the same no-cite-no-claim gate the whole library runs
on: every factual / quantified / attitudinal claim a distribution asset makes
carries a :class:`ClaimCitation` — the claim's exact span in the asset body plus
an :class:`~metalworks.contract.evidence.EvidenceRef` to the verbatim Reddit
quote that supports it. The ref resolves against the source report's ``evidence``
by id; a claim whose support doesn't resolve is DROPPED at assembly, never
shipped. DRAFTING ONLY — nothing here posts.

This module is the foundation the Distribution build (D1+) fills in. For now it
carries the one reusable primitive salvaged from the old pillars,
:class:`ClaimCitation`; the asset / plan / page shapes are rebuilt on top of it
downstream.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from metalworks.contract.evidence import EvidenceRef


class ClaimCitation(BaseModel):
    """One factual claim in a distribution asset, grounded to upstream evidence.

    ``span_start`` / ``span_end`` are character offsets of ``claim_text`` within
    the owning asset's body — a surviving citation always satisfies
    ``body[span_start:span_end] == claim_text``. NOTE: these are Python
    code-point offsets; a non-Python consumer (JS uses UTF-16 code units) must
    treat ``claim_text`` as authoritative and re-find it rather than slicing by
    these offsets if the body contains astral characters (emoji). ``evidence_ref``
    points at the verbatim Reddit quote backing the claim and resolves against the
    source report's ``evidence`` by id. A claim whose support doesn't resolve is
    dropped before the asset ships (no-cite-no-claim).
    """

    claim_text: str = Field(
        description="The exact claim substring as it appears in the asset body."
    )
    span_start: int = Field(description="0-based char offset of claim_text in body.")
    span_end: int = Field(
        description="Exclusive char offset; body[span_start:span_end]==claim_text."
    )
    evidence_ref: EvidenceRef = Field(
        description="Ref to the supporting quote — resolves against the report's evidence by id."
    )
