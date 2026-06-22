"""Pillar A — Competitive Landscape.

``run_competitor_map(deps, report) -> CompetitorMap`` turns a finished
:class:`~metalworks.contract.research.DemandReport` into the real competitive set
— direct, adjacent, and the mandatory status-quo "do nothing" alternative — with
an exploitable, EVIDENCED gap per competitor. Four deterministic stages:

1. **ENUMERATE** — one grounded chat call lists competitors; names with zero
   grounding chunks are dropped (no hallucinated rivals). Degrades to a plain
   structured call (marked ``partial``) when the model can't ground.
2. **HARVEST** — one structured call per competitor produces strengths + gap
   claims (text only; the LLM never assigns severity or invents citations).
3. **COMPLAINT MATCH** — gap claims are embedded and cosine-matched against the
   report's real evidence (cluster quotes first, then web findings). A match
   attaches the resolvable :class:`EvidenceRef`; severity is SERVICE-assigned
   from the matched complaint's distinct-author breadth (or web confidence).
4. **ASSEMBLE** — any gap with no matched evidence is dropped (no-quote-no-gap).
   The status-quo alternative is built deterministically from the top clusters,
   so the cost of doing nothing is always verbatim-grounded.

Best-effort: a failed stage degrades (empty competitors, ``partial`` + caveat),
never crashes. The price/pixel asymmetry is honest — named-competitor gaps lean
``grounded-web``, status-quo and cluster-matched gaps are ``verbatim``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, cast

from pydantic import BaseModel, Field

from metalworks.contract import (
    Competitor,
    CompetitorMap,
    DemandReport,
    EvidenceRef,
    GapClaim,
    InsightCluster,
    SignalStrength,
    StrengthClaim,
)
from metalworks.contract.landscape import ExistingSolution, Landscape
from metalworks.errors import GroundingUnavailable
from metalworks.research.synthesis.demand import relative_band
from metalworks.research.web import parse_numbered_findings

if TYPE_CHECKING:
    from metalworks.llm.protocol import GroundedChatModel, GroundedResult, GroundingSupport
    from metalworks.research.deps import ResearchDeps
    from metalworks.research.sources import ItemSource

# Bounds (the re-plan's "cap N, bound the pull"): keep the call count + latency
# predictable so the synchronous surface stays responsive.
_MAX_COMPETITORS = 6
_MAX_GAPS_PER = 3
_MAX_STATUS_QUO_GAPS = 3
_MAX_TOKENS = 2048


class LandscapeMatchPolicy(BaseModel):
    """Cosine floors for the landscape stage's two evidence-attach matches.

    Surfaced + raised per issue #82. A landscape match decides whether a
    competitor *gap* (and the severity derived from it) or a shipped *product*
    attaches to one of the report's real demand clusters — and both feed the
    GO/NO-GO read. The prior 0.55 / 0.45 floors were loose enough to attach a
    coincidental complaint (same broad topic, different point), inflating
    competitor weakness and supply on noise.

    DECISION (issue #82, option: TIGHTEN, not judge-replace): we RAISE the floors
    rather than route gap→complaint through ``discovery/judge.py``. The judge is
    purpose-built for *reply authenticity* (a different question), and adding a
    per-gap LLM call would make a deterministic, side-effect-free match stage
    non-deterministic and slower — against the repo's "decisions are
    deterministic" rule. Raising the cosine floor is the cheap, reproducible fix:
    it removes the coincidental attachments these specific floors were chosen to
    catch, and the no-quote-no-gap drop already handles a now-unmatched gap
    honestly (it's dropped, not invented).
    """

    gap_complaint_floor: float = Field(
        default=0.62,
        ge=0.0,
        le=1.0,
        description="Cosine floor for a competitor gap → report-complaint match. Raised from the "
        "prior 0.55: at 0.55 two statements about the same broad topic but different points still "
        "matched, attaching a coincidental complaint and inflating the gap's service-assigned "
        "severity. 0.62 keeps genuine paraphrases while dropping topical-but-unrelated matches.",
    )
    product_cluster_floor: float = Field(
        default=0.55,
        ge=0.0,
        le=1.0,
        description="Cosine floor for a shipped-product → demand-cluster match in the existing-"
        "solutions scan. Raised from the prior 0.45 (which let almost any same-domain product "
        "attach to a cluster, overstating real supply). 0.55 requires the product to actually "
        "address the cluster's pain, not merely share its vocabulary.",
    )


DEFAULT_MATCH_POLICY = LandscapeMatchPolicy()
# Back-compat module constants (same names, now sourced from the surfaced policy).
_MATCH_THRESHOLD = DEFAULT_MATCH_POLICY.gap_complaint_floor  # cosine floor: gap↔complaint


# ── LLM I/O shapes (private) ─────────────────────────────────────────────────


class _CompetitorCand(BaseModel):
    name: str = Field(description="The competitor or alternative name.")
    kind: Literal["direct", "adjacent"] = Field(description="direct or adjacent.")
    one_liner: str = Field(description="What it is, one line.")
    # Demand-cluster ranks this candidate was MENTIONED in (corpus-mined cands only;
    # empty for web-enumerated names, which get their clusters from the gap-match).
    clusters: list[int] = Field(default_factory=list[int])


class _CompetitorList(BaseModel):
    competitors: list[_CompetitorCand] = Field(default_factory=list[_CompetitorCand])


class _CorpusMention(BaseModel):
    name: str = Field(description="A real, named product/tool/service the text names.")
    kind: Literal["direct", "adjacent"] = "direct"
    one_liner: str = Field(default="", description="What it is, one line, if discernible.")
    cluster_rank: int = Field(description="The cluster number this mention appeared in.")


class _CorpusMentions(BaseModel):
    mentions: list[_CorpusMention] = Field(default_factory=list[_CorpusMention])


class _Harvest(BaseModel):
    strengths: list[str] = Field(default_factory=list[str], description="What it does well.")
    gaps: list[str] = Field(
        default_factory=list[str], description="What it misses / users complain about."
    )


# ── severity (service-assigned) ──────────────────────────────────────────────


def _cluster_author_population(report: DemandReport) -> list[int]:
    """The report's demand-cluster distinct-author counts — the reference scale gap
    severity bands against (decision: option b). A gap is HIGH-severity when as many
    people complain about it as back the *strongest demand cluster*, tying competitor
    weakness to your own demand scale (the point of a wedge)."""
    return [c.distinct_author_count for c in report.ranked_clusters]


def _severity_from_authors(n: int, population: list[int]) -> SignalStrength:
    """Band a complaint's distinct-author count RELATIVE to the report's demand
    clusters via the shared :func:`relative_band` — not an absolute author cutoff."""
    return relative_band(n, population)


# ── stage 1: enumerate ───────────────────────────────────────────────────────


def _enumerate_context(report: DemandReport) -> str:
    pains = "\n".join(f"- {c.claim}" for c in report.ranked_clusters[:5])
    audience = ""
    if report.segments:
        audience = report.segments[0].name
    elif report.audience_profile and report.audience_profile.age_range:
        audience = report.audience_profile.age_range.estimate or ""
    return (
        f"Product idea / query: {report.query}\n"
        f"Audience: {audience or 'general consumers in this niche'}\n"
        f"Top consumer pains:\n{pains}"
    )


def _parse_grounded_competitors(result: GroundedResult, cap: int) -> list[_CompetitorCand]:
    """Parse a grounded numbered list, keeping only names with a grounding chunk."""
    text = (result.text or "").strip()
    if not text or not result.chunks:
        return []
    cands: list[_CompetitorCand] = []
    for p in parse_numbered_findings(text):
        if not _has_grounding(p.char_start, p.char_end, result.supports, len(result.chunks)):
            continue
        cand = _parse_competitor_line(p.claim)
        if cand is not None:
            cands.append(cand)
        if len(cands) >= cap:
            break
    return cands


def _has_grounding(start: int, end: int, supports: tuple[GroundingSupport, ...], n: int) -> bool:
    for sup in supports:
        if sup.end_char < start or sup.start_char >= end:
            continue
        if any(0 <= idx < n for idx in sup.chunk_indices):
            return True
    return False


def _parse_competitor_line(line: str) -> _CompetitorCand | None:
    parts = [seg.strip(" *_`") for seg in line.split("::")]
    if len(parts) < 2 or not parts[0]:
        return None
    name = parts[0]
    kind: Literal["direct", "adjacent"] = "direct" if "direct" in parts[1].lower() else "adjacent"
    one_liner = parts[2] if len(parts) >= 3 else ""
    return _CompetitorCand(name=name, kind=kind, one_liner=one_liner)


def _enumerate(deps: ResearchDeps, report: DemandReport) -> tuple[list[_CompetitorCand], bool]:
    """Return (candidates, grounded). grounded=False marks an ungrounded degrade."""
    ctx = _enumerate_context(report)
    if deps.chat.capabilities.native_grounding:
        system = (
            "You are a market analyst with a web search tool. You MUST run a web search before "
            "answering — do NOT answer from memory — to find the REAL, CURRENT products people in "
            "this niche use today (direct competitors and adjacent alternatives). Every name must "
            "come from a search result; do not invent names. Output a numbered list, one per line, "
            "formatted exactly as: N. <name> :: <direct|adjacent> :: <one-line description>. "
            "No preamble."
        )
        grounded = cast("GroundedChatModel", deps.chat)
        try:
            result = grounded.complete_grounded(
                system=system, user=ctx, max_tokens=_MAX_TOKENS, temperature=0.2
            )
            return _parse_grounded_competitors(result, _MAX_COMPETITORS), True
        except GroundingUnavailable:
            pass
        except Exception:
            pass
    # Ungrounded fallback — can't drop hallucinated names, so flag it.
    system = (
        "You are a market analyst. List the real products people in this niche use today — direct "
        "competitors and adjacent alternatives. Do not invent names you are unsure exist."
    )
    try:
        out = deps.chat.complete_structured(
            system=system,
            user=ctx,
            output_model=_CompetitorList,
            max_tokens=_MAX_TOKENS,
            temperature=0.2,
        )
        return out.competitors[:_MAX_COMPETITORS], False
    except Exception:
        return [], False


# ── stage 1b: mine the corpus for named competitors (a second enumeration source) ──

_MAX_MENTIONS = 12


def _mine_context(report: DemandReport) -> str:
    """Top clusters with their verbatim quotes, labeled by rank — so a mined name is
    born tied to the cluster it was named in."""
    lines: list[str] = []
    for c in report.ranked_clusters[:8]:
        lines.append(f"Cluster {c.rank}: {c.claim}")
        for q in c.quotes[:3]:
            lines.append(f"  - {q.text}")
    return "\n".join(lines)


def _mine_corpus_competitors(deps: ResearchDeps, report: DemandReport) -> list[_CompetitorCand]:
    """Extract real product/tool names people NAME in their complaints, each tied to the
    cluster it appeared in. A second, corpus-grounded enumeration source beside the web pass.

    Uses a DISTINCT output model (``_CorpusMentions``) so the FakeChatModel script (keyed by
    output type) never collides with the web enumerate call.
    """
    if not report.ranked_clusters:
        return []
    valid_ranks = {c.rank for c in report.ranked_clusters}
    system = (
        "You extract the real, NAMED products / tools / services that people mention in these "
        "complaints as things they currently use, pay for, or compare against. Only concrete names "
        "that literally appear in the text — never categories ('a database', 'a CRM'), never names "
        "you are unsure appear. For each, give the cluster number it was mentioned in."
    )
    user = "Complaints, grouped by cluster:\n" + _mine_context(report)
    try:
        out = deps.chat.complete_structured(
            system=system,
            user=user,
            output_model=_CorpusMentions,
            max_tokens=_MAX_TOKENS,
            temperature=0.1,
        )
    except Exception:
        return []
    cands: list[_CompetitorCand] = []
    for m in out.mentions[:_MAX_MENTIONS]:
        if not m.name.strip() or m.cluster_rank not in valid_ranks:
            continue  # no name, or a hallucinated cluster number → drop
        cands.append(
            _CompetitorCand(
                name=m.name.strip(),
                kind=m.kind,
                one_liner=m.one_liner.strip(),
                clusters=[m.cluster_rank],
            )
        )
    return cands


def _norm_name(name: str) -> str:
    """Casefold + strip non-alphanumerics for dedupe ('PostgreSQL' == 'Postgres SQL')."""
    return "".join(ch for ch in name.casefold() if ch.isalnum())


def _merge_candidates(
    web: list[_CompetitorCand], corpus: list[_CompetitorCand]
) -> list[_CompetitorCand]:
    """Union web + corpus candidates, deduped by normalized name. A name in both keeps the
    web ``kind``/``one_liner`` (the grounded surface) and the UNION of cluster tags."""
    by_key: dict[str, _CompetitorCand] = {}
    order: list[str] = []
    for cand in [*web, *corpus]:  # web first → its kind/one_liner wins on collision
        key = _norm_name(cand.name)
        if not key:
            continue
        if key in by_key:
            ex = by_key[key]
            by_key[key] = ex.model_copy(
                update={
                    "clusters": sorted(set(ex.clusters) | set(cand.clusters)),
                    "one_liner": ex.one_liner or cand.one_liner,
                }
            )
        else:
            by_key[key] = cand
            order.append(key)
    return [by_key[k] for k in order][:_MAX_COMPETITORS]


def _web_id_to_clusters(report: DemandReport) -> dict[str, list[int]]:
    """Map each web-finding evidence id → the cluster ranks it's cross-referenced to, so a
    competitor whose gap matched a WEB finding (not a quote) still gets a cluster tag."""
    by_index = {w.finding_index: w.id for w in report.web_findings}
    out: dict[str, list[int]] = {}
    for cr in report.cross_references:
        for fi in cr.web_finding_indices:
            wid = by_index.get(fi)
            if wid is not None:
                out.setdefault(wid, []).append(cr.cluster_rank)
    return out


# ── stage 2: harvest strengths + gap claims ──────────────────────────────────


def _harvest(deps: ResearchDeps, report: DemandReport, cand: _CompetitorCand) -> _Harvest:
    pains = "\n".join(f"- {c.claim}" for c in report.ranked_clusters[:5])
    system = (
        "You assess one competitor for a founder. List its genuine strengths and the gaps / "
        "common complaints about it. Be concrete and specific to THIS product. Do not invent "
        "citations or numbers — just the claims. Phrase each gap as what the product misses."
    )
    user = (
        f"Competitor: {cand.name} ({cand.kind}) — {cand.one_liner}\n\n"
        f"The audience's unmet pains:\n{pains}\n\n"
        "List strengths and gaps (gaps = what it misses, especially around those pains)."
    )
    try:
        return deps.chat.complete_structured(
            system=system, user=user, output_model=_Harvest, max_tokens=_MAX_TOKENS, temperature=0.3
        )
    except Exception:
        return _Harvest()


# ── stage 3: complaint match ─────────────────────────────────────────────────


def _evidence_index(
    report: DemandReport,
) -> tuple[dict[str, str], dict[str, InsightCluster], set[str]]:
    """Map evidence-id → text, quote-id → owning cluster, and the web-id set."""
    texts: dict[str, str] = {}
    quote_cluster: dict[str, InsightCluster] = {}
    web_ids: set[str] = set()
    for c in report.ranked_clusters:
        for q in c.quotes:
            texts[q.id] = q.text
            quote_cluster.setdefault(q.id, c)
    for w in report.web_findings:
        texts[w.id] = w.claim
        web_ids.add(w.id)
    return texts, quote_cluster, web_ids


def _match_gaps(
    deps: ResearchDeps,
    gap_texts: list[str],
    evidence_texts: dict[str, str],
    quote_cluster: dict[str, InsightCluster],
    web_ids: set[str],
    cluster_population: list[int],
) -> dict[int, tuple[EvidenceRef, SignalStrength]]:
    """Cosine-match each gap (by list index) to its best evidence id; drop misses."""
    if not gap_texts or not evidence_texts:
        return {}
    from metalworks.stores.vectors import cosine_topk

    ids = list(evidence_texts)
    matched: dict[int, tuple[EvidenceRef, SignalStrength]] = {}
    try:
        ev_vecs = deps.embeddings.embed([evidence_texts[i] for i in ids], task="document")
        gap_vecs = deps.embeddings.embed(gap_texts, task="document")
        vectors = {ids[i]: ev_vecs[i] for i in range(len(ids))}
        cosine = [cosine_topk(gvec, vectors, 1) for gvec in gap_vecs]
    except Exception:  # embeddings down, or numpy ([research] extra) absent → no matches
        return {}
    for gi, top in enumerate(cosine):
        if not top or top[0][1] < _MATCH_THRESHOLD:
            continue
        ev_id, _score = top[0]
        if ev_id in quote_cluster:
            sev = _severity_from_authors(
                quote_cluster[ev_id].distinct_author_count, cluster_population
            )
            matched[gi] = (EvidenceRef(evidence_id=ev_id, kind="quote"), sev)
        elif ev_id in web_ids:
            matched[gi] = (EvidenceRef(evidence_id=ev_id, kind="web"), SignalStrength.MEDIUM)
    return matched


# ── stage 4: status quo (deterministic, always verbatim) ─────────────────────


def _status_quo(report: DemandReport) -> Competitor:
    gaps: list[GapClaim] = []
    population = _cluster_author_population(report)
    ranked = sorted(report.ranked_clusters, key=lambda c: c.demand_score, reverse=True)
    for c in ranked:
        if not c.quotes or len(gaps) >= _MAX_STATUS_QUO_GAPS:
            continue
        gaps.append(
            GapClaim(
                gap_index=len(gaps) + 1,
                claim=f"Living with it: {c.claim}",
                severity=_severity_from_authors(c.distinct_author_count, population),
                evidence=EvidenceRef(evidence_id=c.quotes[0].id, kind="quote"),
            )
        )
    return Competitor(
        competitor_index=0,
        name="Doing nothing (status quo)",
        kind="status_quo",
        one_liner="The current routine or workaround — the default any new product must beat.",
        strengths=[StrengthClaim(claim="Costs nothing and requires no change.")],
        gaps=gaps,
    )


# ── public entry ─────────────────────────────────────────────────────────────


def run_competitor_map(deps: ResearchDeps, report: DemandReport) -> CompetitorMap:
    """Build a grounded :class:`CompetitorMap` from a finished report.

    Enumerate (grounded) → harvest per competitor → cosine-match gaps to the
    report's real complaints → assemble, dropping any unevidenced gap. The
    status-quo alternative is always present and verbatim-grounded.
    """
    web_cands, grounded = _enumerate(deps, report)
    corpus_cands = _mine_corpus_competitors(deps, report)
    cands = _merge_candidates(web_cands, corpus_cands)
    evidence_texts, quote_cluster, web_ids = _evidence_index(report)
    web_clusters = _web_id_to_clusters(report)
    cluster_population = _cluster_author_population(report)

    competitors: list[Competitor] = []
    for ci, cand in enumerate(cands, start=1):
        harvest = _harvest(deps, report, cand)
        gap_texts = [g for g in harvest.gaps if g.strip()][:_MAX_GAPS_PER]
        matched = _match_gaps(
            deps, gap_texts, evidence_texts, quote_cluster, web_ids, cluster_population
        )
        gaps: list[GapClaim] = []
        # addresses_clusters = the clusters this rival competes for: mention clusters (corpus)
        # plus quote-matched gap clusters plus web-matched gap clusters (via cross_references).
        cluster_tags: set[int] = set(cand.clusters)
        for gi, text in enumerate(gap_texts):
            if gi not in matched:
                continue  # no-quote-no-gap
            ref, sev = matched[gi]
            gaps.append(GapClaim(gap_index=len(gaps) + 1, claim=text, severity=sev, evidence=ref))
            if ref.kind == "quote" and ref.evidence_id in quote_cluster:
                cluster_tags.add(quote_cluster[ref.evidence_id].rank)
            elif ref.kind == "web":
                cluster_tags.update(web_clusters.get(ref.evidence_id or "", []))
        competitors.append(
            Competitor(
                competitor_index=ci,
                name=cand.name,
                kind=cand.kind,
                one_liner=cand.one_liner,
                strengths=[StrengthClaim(claim=s) for s in harvest.strengths if s.strip()],
                gaps=gaps,
                addresses_clusters=sorted(cluster_tags),
            )
        )

    partial = not grounded
    caveat = (
        "Competitor enumeration ran ungrounded (no web grounding available) — treat the named "
        "set as unverified; the status-quo and cluster-matched gaps are still evidence-backed."
        if not grounded
        else None
    )
    return CompetitorMap(
        map_id=f"cm:{report.report_id}",
        report_id=report.report_id,
        competitors=competitors,
        status_quo_alternative=_status_quo(report),
        generated_at=deps.clock(),
        partial=partial,
        caveat=caveat,
    )


# ── existing-solutions scan (empirical product pull, matched to clusters) ─────

_MAX_EXISTING = 8
_EXISTING_MATCH_THRESHOLD = DEFAULT_MATCH_POLICY.product_cluster_floor  # product↔cluster floor


def _existing_solutions(
    deps: ResearchDeps, report: DemandReport, source: ItemSource | None
) -> tuple[list[ExistingSolution], bool]:
    """Pull real shipped products and keep those that map to a demand cluster.

    Returns ``(solutions, ok)``; ``ok=False`` marks a degrade (no product source
    / token, or embeddings unavailable). A product matched to no cluster is
    dropped — grounded, not guessed.
    """
    if not report.ranked_clusters:
        return [], True  # nothing to ground against; not a failure
    if source is None:
        try:
            from metalworks.research.sources import get_source

            source = get_source("producthunt")
        except Exception:
            return [], False  # no token / source unavailable

    from metalworks.research.sources import SourceWindow

    window = SourceWindow(start=report.date_range_start, end=report.date_range_end)
    try:
        records = list(source.pull(query=report.query, window=window))
    except Exception:
        return [], False
    if not records:
        return [], True

    from metalworks.stores.vectors import cosine_topk

    cluster_texts = {f"c{c.rank}": c.claim for c in report.ranked_clusters}
    cl_ids = list(cluster_texts)
    try:
        cl_vecs = deps.embeddings.embed([cluster_texts[i] for i in cl_ids], task="document")
        prod_texts = [f"{r.title} {r.text}".strip() for r in records]
        prod_vecs = deps.embeddings.embed(prod_texts, task="document")
    except Exception:  # embeddings down or numpy ([research] extra) absent
        return [], False
    vectors = {cl_ids[i]: cl_vecs[i] for i in range(len(cl_ids))}

    solutions: list[ExistingSolution] = []
    for rec, pvec in zip(records, prod_vecs, strict=True):
        top = cosine_topk(pvec, vectors, 1)
        if not top or top[0][1] < _EXISTING_MATCH_THRESHOLD:
            continue  # no cluster match → dropped
        rank = int(top[0][0][1:])  # "c<rank>" → rank
        tagline = str(rec.extra.get("tagline", ""))
        solutions.append(
            ExistingSolution(
                name=rec.title or "Unknown product",
                url=rec.url,
                tagline=str(tagline),
                traction=rec.engagement,
                source=rec.source,
                addresses_clusters=[rank],
                evidence=EvidenceRef(kind="cluster", cluster_rank=rank),
            )
        )
        if len(solutions) >= _MAX_EXISTING:
            break
    return solutions, True


def run_landscape(
    deps: ResearchDeps, report: DemandReport, *, existing_source: ItemSource | None = None
) -> Landscape:
    """Pillar A (thick) — the competitor map PLUS an empirical existing-solutions scan.

    Wraps :func:`run_competitor_map` (competitors + status-quo) and adds real
    shipped products (Product Hunt by default) matched to the report's demand
    clusters. ``existing_source`` is injectable for tests; in production it
    resolves the Product Hunt source. Degrades honestly: a missing token or
    source leaves the competitor map intact and marks ``partial``.
    """
    cmap = run_competitor_map(deps, report)
    solutions, ok = _existing_solutions(deps, report, existing_source)

    caveats: list[str] = []
    if cmap.caveat:
        caveats.append(cmap.caveat)
    if not ok:
        caveats.append(
            "Existing-solutions scan unavailable (no product source / token, or embeddings off) — "
            "competitors and the status-quo cost still hold."
        )
    return Landscape(
        landscape_id=f"ls:{report.report_id}",
        report_id=report.report_id,
        competitor_map=cmap,
        existing_solutions=solutions,
        generated_at=deps.clock(),
        partial=cmap.partial or not ok,
        caveat=" ".join(caveats) or None,
    )
