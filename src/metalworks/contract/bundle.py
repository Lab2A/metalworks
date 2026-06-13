"""Stage-1 output bundle — `Research`.

The five-stage arc (Research → Design → Build → Launch → Growth) makes each
stage produce one frozen, typed bundle. `Research` is the first: it composes
the demand signal with (eventually) the competitor map and positioning brief,
so a caller holds one object for "everything stage 1 learned about this idea"
instead of three loose returns.

Today only the demand pillar exists, so `Research` carries a single
`DemandReport`. `competitors` (Phase 2, `CompetitorMap`) and `positioning`
(Phase 1, `PositioningBrief`) are exposed as read-only accessors that return
`None` until those pillars ship; they become real optional fields then, which
is an additive, non-breaking change for callers (`research.competitors is None`
holds before and after). `Research.evidence` delegates to the demand report's
evidence so the grounded-evidence chain is reachable straight off the bundle.

`Research` is the stable return type of `Metalworks.research()` and the stage-1
durable artifact — it is frozen, so the bundle a caller gets back cannot be
mutated out from under the evidence ids it carries.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from metalworks.contract.evidence import EvidenceRecord
from metalworks.contract.landscape import CompetitorMap
from metalworks.contract.positioning import PositioningBrief
from metalworks.contract.research import DemandReport


class Research(BaseModel):
    """Everything stage 1 ("Research") produced for one idea.

    Returned by :meth:`metalworks.Metalworks.research`. Compose-only: the
    pillars stay pure functions; this bundle just holds their typed outputs and
    re-exposes the demand report's evidence so downstream stages resolve
    ``EvidenceRef``s against ``research.evidence``.
    """

    model_config = ConfigDict(frozen=True)

    demand: DemandReport
    competitors: CompetitorMap | None = None
    positioning: PositioningBrief | None = None

    @property
    def evidence(self) -> list[EvidenceRecord]:
        """The flat, resolvable evidence backing this research — the demand
        report's evidence, surfaced on the bundle so every stage can resolve
        ``EvidenceRef``s against one object."""
        return self.demand.evidence
