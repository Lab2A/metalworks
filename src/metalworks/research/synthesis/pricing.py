"""Willingness-to-pay extraction → PriceFinding.

The LLM proposes verbatim WTP snippets + kind + amount; each snippet is
exact-matched against a real comment body (same anti-fabrication gate as
quotes). `too_expensive` signals are carried as evidence but EXCLUDED from the
range — they express resistance, not willingness to pay.

`build_price_finding` only runs when Price is a Find slot in the brief's
SlotPlan; otherwise the user gave the price and there's nothing to find.
Best-effort: the LLM call is wrapped in retries and returns [] (→
insufficient_signal) on failure, never raising into the report.
"""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from metalworks.contract import PriceEvidence, PriceFinding, SignalStrength, SlotPlan
from metalworks.research.types import LoadedComment

if TYPE_CHECKING:
    from metalworks.research.deps import ResearchDeps

_WILLINGNESS_KINDS = {"paid", "competitor"}
_VALID_KINDS = {"paid", "competitor", "too_expensive"}
LLM_RETRIES = 3


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def assemble_price_finding(
    evidence: list[PriceEvidence],
    *,
    currency: str = "USD",
    min_priced: int = 2,
) -> PriceFinding:
    priced = [
        e.amount
        for e in evidence
        if e.amount is not None and e.amount > 0 and e.kind in _WILLINGNESS_KINDS
    ]
    if len(priced) < min_priced:
        return PriceFinding(insufficient_signal=True, currency=currency, evidence=evidence)

    if len(priced) >= 6:
        confidence = SignalStrength.HIGH
    elif len(priced) >= 3:
        confidence = SignalStrength.MEDIUM
    else:
        confidence = SignalStrength.LOW

    return PriceFinding(
        low=min(priced),
        high=max(priced),
        currency=currency,
        confidence=confidence,
        evidence=evidence,
        insufficient_signal=False,
    )


class _WtpSignal(BaseModel):
    text: str = Field(description="Verbatim snippet from a comment expressing the price signal.")
    kind: str = Field(description="paid | competitor | too_expensive")
    amount: float | None = Field(default=None)


class _WtpExtraction(BaseModel):
    signals: list[_WtpSignal] = Field(default_factory=list["_WtpSignal"])


def extract_price_evidence(
    deps: ResearchDeps,
    comments: list[LoadedComment],
) -> list[PriceEvidence]:
    """Extract WTP signals from comments. The LLM proposes verbatim snippets;
    each is grounded against a real comment body before it survives — the LLM
    can never inject a price nobody actually said."""
    bodies = [c.body for c in comments]
    if not any(bodies):
        return []
    try:
        raw = _default_extract(deps, bodies)
    except Exception:  # best-effort; downstream sees insufficient_signal
        return []

    norm_index = [
        (_norm(b), c.permalink or c.post_url) for c, b in zip(comments, bodies, strict=False)
    ]
    out: list[PriceEvidence] = []
    for s in raw.signals:
        kind = (s.kind or "").strip().lower()
        ns = _norm(s.text)
        if kind not in _VALID_KINDS or not ns:
            continue
        if not any(ns in nb for nb, _ in norm_index):
            continue  # not grounded in any real comment → fabricated, drop
        permalink = next((url for nb, url in norm_index if ns in nb), None)
        amount = s.amount if (s.amount is not None and s.amount > 0) else None
        out.append(
            PriceEvidence(text=s.text.strip(), kind=kind, amount=amount, permalink=permalink)
        )
    return out


def build_price_finding(
    deps: ResearchDeps,
    comments: list[LoadedComment],
    slot_plan: SlotPlan | None,
    *,
    currency: str = "USD",
) -> PriceFinding | None:
    """The found-Price — only when Price is a Find slot. None otherwise."""
    if slot_plan is None or "price" not in (slot_plan.find or []):
        return None
    evidence = extract_price_evidence(deps, comments)
    return assemble_price_finding(evidence, currency=currency)


def _default_extract(deps: ResearchDeps, bodies: list[str]) -> _WtpExtraction:
    listing = "\n".join(f"- {b}" for b in bodies[:60] if b.strip())
    system = (
        "You extract willingness-to-pay signals from Reddit comments. A signal is a price someone "
        "says they PAID (kind='paid'), a COMPETITOR/substitute price (kind='competitor'), "
        "or a 'too expensive' complaint (kind='too_expensive'). Copy the snippet VERBATIM from a "
        "comment — do not paraphrase or invent. Parse the numeric amount when one is stated. "
        "Extract nothing when there is no price talk; never guess a number."
    )
    user = "Comments:\n" + (listing or "(none)") + "\n\nExtract the willingness-to-pay signals."
    last_err: Exception | None = None
    for attempt in range(LLM_RETRIES):
        try:
            return deps.filter_model.complete_structured(
                system=system,
                user=user,
                output_model=_WtpExtraction,
                max_tokens=4096,
                temperature=0.1,
            )
        except Exception as e:  # surfaced after retries
            last_err = e
            time.sleep(0.5 * (2**attempt))
    raise RuntimeError(f"Pricing LLM failed after {LLM_RETRIES} attempts: {last_err}")
