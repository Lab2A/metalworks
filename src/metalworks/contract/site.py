"""Site contract — the Pillar E (Marketing Website) output.

A :class:`MarketingSite` turns a
:class:`~metalworks.contract.research.DemandReport`'s top demand clusters into a
handful of marketing-copy sections, each of which either ships a VERBATIM
fragment of a real Reddit quote (with a resolvable
:class:`~metalworks.contract.evidence.EvidenceRef`) or carries claim-free
connective copy with no refs at all.

Honesty contract (the no-quote-no-section gate, the same spine the demand
report and positioning brief use):
- A claim-bearing section's ``copy`` MUST contain a fragment that exact-matches
  a real ``ResolvedCitation.text`` in its source cluster. That fragment is the
  load-bearing claim; the section ships ``provenance="verbatim"`` with one
  ``EvidenceRef(kind="quote")`` resolving against the source report's
  ``evidence``. A section whose fragment matches nothing — or that carries no
  ref — is DROPPED at assembly, never shipped on trust.
- Connective copy (the transitions the LLM may add between verbatim sections)
  ships ``provenance="connective"`` with ZERO refs and MUST be claim-free: no
  numbers, no superlatives. It is glue, not evidence.
- ``derived`` is reserved for future computed-but-sourceless copy; the current
  builder only emits ``verbatim`` and ``connective``.

This is the stable shape ``build_marketing_site(...)`` returns; the demand
report's evidence list is what its ``EvidenceRef``s resolve against (by
``EvidenceRecord.id``). ``partial`` + ``caveat`` carry the honesty signal when
synthesis is unavailable.
"""

from __future__ import annotations

import warnings
from typing import Literal

from pydantic import BaseModel, Field

from metalworks.contract.evidence import EvidenceRef

# `copy` is a deliberate wire-contract field name that shadows the deprecated
# BaseModel.copy attribute; the override is intentional (see SiteSection), so
# suppress pydantic's shadow warning narrowly rather than renaming the field.
warnings.filterwarnings("ignore", message=r'Field name "copy".*', category=UserWarning)


class SiteSection(BaseModel):
    """One marketing-site section — a verbatim claim or claim-free connective glue.

    ``role`` is the section's job on the page (hero/feature/objection/pricing/
    social_proof/cta). ``copy`` is the rendered text. A ``verbatim`` section's
    ``copy`` contains a fragment that exact-matches a real ``ResolvedCitation.text``
    and carries exactly the ``EvidenceRef``s that back it; a ``connective``
    section carries no refs and no claims.
    """

    role: str = Field(
        description="Section job on the page: hero/feature/objection/pricing/social_proof/cta."
    )
    # `copy` shadows BaseModel.copy by design — it is the contract field name
    # (the section's rendered text). The model is data-only; we never call the
    # deprecated BaseModel.copy() on it.
    copy: str = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        description="Rendered section text (contains a verbatim fragment if claimed)."
    )
    evidence_refs: list[EvidenceRef] = Field(
        default_factory=list[EvidenceRef],
        description="Refs backing the section — one quote ref for verbatim, empty for connective.",
    )
    provenance: Literal["verbatim", "derived", "connective"] = Field(
        description="verbatim = exact-matched quote fragment; connective = claim-free glue."
    )


class MarketingSite(BaseModel):
    """Pillar E output — a grounded marketing site for one report.

    FKs to exactly one report via ``report_id``; every ``EvidenceRef`` any
    section carries resolves against THAT report's ``evidence``. ``partial`` +
    ``caveat`` carry the honesty signal: an LLM failure yields an empty
    ``sections`` list with ``partial=True`` and a caveat, never a crash and never
    an invented section.
    """

    site_id: str = Field(description="Stable id for this generated site.")
    report_id: str = Field(description="The DemandReport this site was derived from.")
    sections: list[SiteSection] = Field(
        default_factory=list[SiteSection],
        description="Ordered sections; verbatim sections carry quote refs, connective ones none.",
    )
    partial: bool = Field(
        default=False, description="True when synthesis was unavailable and the site is empty."
    )
    caveat: str | None = Field(
        default=None, description="Why the site is partial / what to treat as unbuilt."
    )
