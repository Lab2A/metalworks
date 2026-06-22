"""Visual-design pillar — turn a finished report into a grounded design system.

The visual counterpart to positioning. ``build_design_system(deps, research)``
reads the demand report and the competitive landscape and authors a
:class:`~metalworks.contract.design.DesignSystem`: an aesthetic direction, one
SAFE/RISK :class:`~metalworks.contract.design.DesignChoice` per design dimension,
and directional :class:`~metalworks.contract.design.LandscapeSignal`s. The model
authors under a constant house craft bar (``TASTE``); metalworks records WHICH
grounding tier produced the system so the look is never overstated.

Grounding is DIRECTIONAL, never cited per-decision. The grounding tier is set by
how the competition was actually read:

* **renderer** — a real teardown: a script-capable renderer (Playwright)
  screenshots rival sites and reads their computed fonts/colors. Richest.
* **web** — no live teardown, but the landscape gives real competitor
  names/taglines to read directionally.
* **model_knowledge** — nothing to read; the model designs from its own knowledge
  of the category (an honest ``partial`` + caveat).

The teardown is resilient: a rival site that blocks the headless browser or times
out is dropped and the sweep continues. ``max_teardown`` caps how many sites are
toredown (default 3, the highest-traction first); pass ``0`` for the full sweep.

``render_design_md(system)`` is the per-project ``DESIGN.md`` source of truth;
``render_design_preview_html(system)`` is a self-contained preview page.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html import escape
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from metalworks.contract.design import (
    DesignChoice,
    DesignSystem,
    GroundingTier,
    LandscapeSignal,
)

if TYPE_CHECKING:
    from metalworks.contract.bundle import Research
    from metalworks.contract.landscape import Landscape
    from metalworks.contract.research import DemandReport
    from metalworks.render import PageRenderer
    from metalworks.research.deps import ResearchDeps

# The seven design dimensions every system covers, in render order.
_DIMENSIONS = ("aesthetic", "decoration", "layout", "color", "typography", "spacing", "motion")

# The house craft bar + the curated knowledge, held constant across every brand.
# This is the portable design IP: the quality bar, the aesthetic taxonomy, the
# font allow/block + convergence-trap lists, and the anti-slop rules.
TASTE = """You are the house design director. Hold to this system exactly.

THE BAR
A design system a well-funded startup would actually ship — the craft of Stripe,
Linear, Vercel, Mono. Coherent, restrained, and memorable. Coherence is table
stakes; the RISKS are where the brand gets its own face.

AESTHETIC DIRECTIONS (pick the one that fits the product, name it in one line):
brutally-minimal · editorial/magazine · luxury/refined · industrial/utilitarian ·
playful/toy · retro-futuristic · organic/natural · brutalist/raw.

TYPOGRAPHY
- Display/hero: Fraunces, Cabinet Grotesk, Instrument Serif, General Sans, Clash Grotesk.
- Body: Geist, Inter Tight, Instrument Sans, Source Sans 3.
- Data/mono: Geist Mono, JetBrains Mono, IBM Plex Mono.
- BLACKLIST (never): Papyrus, Comic Sans, Lobster, Impact, Trajan, Raleway.
- CONVERGENCE TRAP (never as the default — every AI tool reaches for these):
  Inter, Roboto, Arial, Helvetica, Open Sans, Montserrat, Poppins, Space Grotesk.

COLOR
Define hex. At most one ink + one accent + neutrals unless the aesthetic demands more.
Color is rare and meaningful, not decoration.

ANTI-SLOP (never): purple/violet gradient accents; 3-column icon-in-a-circle grids;
centered-everything with uniform spacing; uniform bubbly border-radius; gradient CTAs;
generic stock-photo heroes; system-ui as the display/body face.

OUTPUT
Exactly one DesignChoice per dimension (aesthetic, decoration, layout, color,
typography, spacing, motion), each labelled SAFE (category baseline users expect)
or RISK (a deliberate departure — say what it gains AND costs). At least TWO RISKs.
Plus the one memorable thing someone should remember, and directional landscape
signals (what rivals converge on → the move it implies). Be specific and opinionated."""


class _DesignDraft(BaseModel):
    """The single structured LLM output the system is assembled from."""

    brand_name: str = Field(default="", description="Brand wordmark (echo the one given).")
    memorable_thing: str = Field(description="The one thing to remember on first sight.")
    aesthetic: str = Field(description="The aesthetic direction in one line.")
    choices: list[DesignChoice] = Field(
        default_factory=list[DesignChoice],
        description="Exactly one per dimension; >=2 must be stance='risk'.",
    )
    landscape_signals: list[LandscapeSignal] = Field(
        default_factory=list[LandscapeSignal],
        description="Directional reads of the competition (not cited).",
    )


@dataclass
class _Teardown:
    """What the competitive read produced, and at which grounding tier."""

    observations: list[str] = field(default_factory=list[str])
    competitors: list[str] = field(default_factory=list[str])
    tier: GroundingTier = "model_knowledge"


def _teardown_competitors(
    landscape: Landscape | None,
    renderer: PageRenderer | None,
    *,
    max_teardown: int,
) -> _Teardown:
    """Read the competition directionally, at the richest tier available.

    A real teardown needs a script-capable renderer (Playwright) — it screenshots
    rival sites and reads their computed fonts/colors. A site that blocks the
    browser or times out is dropped and the sweep continues. With no live
    teardown, real competitor names/taglines from the landscape feed the model as
    text (``web``); with neither, the model designs from category knowledge.
    """
    if landscape is None:
        return _Teardown(tier="model_knowledge")

    names = [c.name for c in landscape.competitor_map.competitors]
    with_urls = sorted(
        (s for s in landscape.existing_solutions if s.url),
        key=lambda s: s.traction,
        reverse=True,
    )
    targets = with_urls if max_teardown <= 0 else with_urls[:max_teardown]

    observations: list[str] = []
    if renderer is not None and renderer.capabilities.supports_style_audit and targets:
        for sol in targets:
            try:
                styles = {
                    s.selector: s
                    for s in renderer.extract_computed_styles(sol.url, ["body", "h1", "a"])
                }
            except Exception:
                continue  # bot-block / timeout / unreachable — drop and keep sweeping
            obs = _describe_styles(sol.name, styles)
            if obs:
                observations.append(obs)

    if observations:
        return _Teardown(observations=observations, competitors=names, tier="renderer")

    taglines = [f"{s.name} — {s.tagline}".strip(" —") for s in landscape.existing_solutions]
    text = [t for t in taglines if t]
    if names or text:
        return _Teardown(observations=text[:8], competitors=names, tier="web")
    return _Teardown(tier="model_knowledge")


def _describe_styles(name: str, styles: Mapping[str, object]) -> str:
    """One directional observation line from a competitor's computed styles."""
    from metalworks.render import ComputedStyle

    parts: list[str] = []
    body = styles.get("body")
    h1 = styles.get("h1")
    if isinstance(body, ComputedStyle) and body.font_family:
        parts.append(f"body {body.font_family.split(',')[0].strip()}")
    if isinstance(h1, ComputedStyle) and h1.font_family:
        parts.append(f"heading {h1.font_family.split(',')[0].strip()}")
    if isinstance(body, ComputedStyle) and body.color:
        parts.append(f"ink {body.color}")
    if isinstance(body, ComputedStyle) and body.background_color:
        parts.append(f"bg {body.background_color}")
    return f"{name}: {', '.join(parts)}" if parts else ""


def _suggest_brand_name(deps: ResearchDeps, report: DemandReport) -> str:
    """Model-suggested short brand name when none was supplied (best-effort)."""
    try:
        out = deps.chat.complete_text(
            system="You name software products. Reply with ONLY a short, brandable name "
            "(one or two words). No punctuation, no quotes, no explanation.",
            user=f"Product: {report.query}",
            max_tokens=24,
            temperature=0.7,
        )
        words = out.text.strip().splitlines()[0].strip().strip('".').split()
        return " ".join(w for w in words[:2] if w) or "Brand"
    except Exception:
        return "Brand"


def _cluster_labels(report: DemandReport, limit: int = 4) -> list[str]:
    labels: list[str] = []
    for cluster in list(getattr(report, "ranked_clusters", []))[:limit]:
        claim = getattr(cluster, "claim", "")
        if isinstance(claim, str) and claim.strip():
            labels.append(claim.strip()[:90])
    return labels


def _synthesize(
    deps: ResearchDeps,
    report: DemandReport,
    research: Research,
    teardown: _Teardown,
    brand_name: str,
) -> _DesignDraft:
    """The one constrained structured call that authors the system under TASTE."""
    lines = [f"Brand (the wordmark): {brand_name}", f"What it does: {report.query}"]
    labels = _cluster_labels(report)
    if labels:
        lines.append("What customers care about: " + "; ".join(labels))
    positioning = research.positioning
    wedge = getattr(positioning, "wedge", None) if positioning is not None else None
    if wedge is not None:
        lines.append(f"Positioning wedge: {getattr(wedge, 'value', '') or ''}")

    if teardown.tier == "renderer":
        lines.append("REAL COMPETITOR TEARDOWN (their actual rendered styles):")
        lines += [f"- {o}" for o in teardown.observations]
        lines.append("Read directionally: converge on table stakes, break to stand out.")
    elif teardown.tier == "web":
        lines.append("Competitors in this space (names / taglines):")
        named = [f"- {c}" for c in teardown.competitors]
        lines += [f"- {o}" for o in teardown.observations] or named
        lines.append("Read directionally; you can't see their visuals, only what they are.")
    else:
        lines.append(
            "No competitor data available — design from your own knowledge of this category, "
            "and say so honestly in the landscape signals."
        )

    user = "\n".join(lines)
    return deps.chat.complete_structured(
        system=TASTE,
        user=user,
        output_model=_DesignDraft,
        max_tokens=2400,
        temperature=0.8,
    )


def build_design_system(
    deps: ResearchDeps,
    research: Research,
    *,
    brand_name: str | None = None,
    renderer: PageRenderer | None = None,
    max_teardown: int = 3,
) -> DesignSystem:
    """Author a grounded :class:`DesignSystem` from a finished research bundle.

    Reads the competition at the richest tier available (a real renderer teardown
    > web text > model knowledge), makes ONE constrained LLM call under the house
    craft bar, and stamps the actual ``grounding_tier`` so the look is never
    overstated. On any synthesis failure, returns an honest partial system — never
    raises. ``max_teardown`` caps the live teardown (default 3 by traction; ``0``
    for the full sweep); ``renderer`` defaults to ``config.resolve_renderer()``.
    """
    report = research.demand
    if renderer is None:
        from metalworks import config

        renderer = config.resolve_renderer()

    teardown = _teardown_competitors(research.landscape, renderer, max_teardown=max_teardown)
    name = (brand_name or "").strip() or _suggest_brand_name(deps, report)
    now = datetime.now(UTC)

    try:
        draft = _synthesize(deps, report, research, teardown, name)
    except Exception as exc:  # synthesis failed — honest partial, never a crash
        return DesignSystem(
            report_id=report.report_id,
            brand_name=name,
            memorable_thing="",
            grounding_tier=teardown.tier,
            aesthetic="",
            generated_at=now,
            partial=True,
            caveat=f"Design synthesis unavailable ({type(exc).__name__}); no system authored.",
        )

    caveat: str | None = None
    if teardown.tier == "model_knowledge":
        caveat = (
            "Grounding tier: model_knowledge — no competitor teardown was available, so the "
            "system reflects category convention, not this brand's actual competitive landscape. "
            "Install the browser renderer (metalworks browser install) for a real teardown."
        )

    system = DesignSystem(
        report_id=report.report_id,
        brand_name=name or draft.brand_name or "Brand",
        memorable_thing=draft.memorable_thing,
        grounding_tier=teardown.tier,
        aesthetic=draft.aesthetic,
        choices=list(draft.choices),
        landscape_signals=list(draft.landscape_signals),
        generated_at=now,
        partial=teardown.tier == "model_knowledge",
        caveat=caveat,
    )
    return system.model_copy(update={"design_md": render_design_md(system)})


# ── Rendering ─────────────────────────────────────────────────────────────────


def render_design_md(system: DesignSystem) -> str:
    """The per-project ``DESIGN.md`` — the design source of truth, as markdown."""
    out: list[str] = [
        f"# {system.brand_name} — Design System",
        "",
        f"> {system.memorable_thing}",
        "",
        f"**Aesthetic:** {system.aesthetic}",
        f"**Grounding:** {system.grounding_tier}",
    ]
    if system.caveat:
        out += ["", f"> ⚠️ {system.caveat}"]
    order = {dim: i for i, dim in enumerate(_DIMENSIONS)}
    out += ["", "## Choices"]
    for choice in sorted(system.choices, key=lambda c: order.get(c.dimension, 99)):
        out += [
            "",
            f"### {choice.dimension} — _{choice.stance.upper()}_",
            choice.decision,
            "",
            f"_{choice.rationale}_",
        ]
    if system.landscape_signals:
        out += ["", "## Landscape signals (directional)"]
        out += [f"- **{s.observation}** → {s.implication}" for s in system.landscape_signals]
    return "\n".join(out) + "\n"


def render_design_preview_html(system: DesignSystem) -> str:
    """A self-contained preview page: the aesthetic, the SAFE/RISK choices, signals."""
    order = {dim: i for i, dim in enumerate(_DIMENSIONS)}
    rows: list[str] = []
    for choice in sorted(system.choices, key=lambda c: order.get(c.dimension, 99)):
        tag = "risk" if choice.stance == "risk" else "safe"
        rows.append(
            f'<tr><td class="dim">{escape(choice.dimension)}</td>'
            f'<td><span class="stance {tag}">{escape(choice.stance.upper())}</span></td>'
            f"<td><b>{escape(choice.decision)}</b><span>{escape(choice.rationale)}</span></td></tr>"
        )
    signals = "".join(
        f"<li><b>{escape(s.observation)}</b> &rarr; {escape(s.implication)}</li>"
        for s in system.landscape_signals
    )
    note = f'<p class="note">{escape(system.caveat)}</p>' if system.caveat else ""
    name = escape(system.brand_name)
    signals_block = (
        "<h2 style='font-size:13px;color:var(--muted);text-transform:uppercase;"
        f"letter-spacing:.06em;margin-top:44px;'>Landscape signals</h2><ul>{signals}</ul>"
        if signals
        else ""
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name} — design system</title><style>
:root{{--bg:#0E0E0E;--ink:#F4F1EA;--muted:#8A8578;--line:#26251F;--card:#161614;}}
*{{box-sizing:border-box;}}
body{{margin:0;background:var(--bg);color:var(--ink);
 font-family:'Geist','Inter',system-ui,sans-serif;-webkit-font-smoothing:antialiased;}}
.wrap{{max-width:920px;margin:0 auto;padding:64px 36px 120px;}}
h1{{font-size:32px;font-weight:600;letter-spacing:-0.02em;margin:0;}}
.sub{{color:var(--muted);font-size:14px;margin:10px 0 0;}}
.memo{{font-size:20px;margin:28px 0 4px;line-height:1.4;}}
.tier{{display:inline-block;font-family:'Geist Mono',monospace;font-size:12px;color:var(--muted);
 border:1px solid var(--line);border-radius:4px;padding:2px 8px;margin-top:14px;}}
.note{{color:#C9893F;font-size:13px;margin-top:14px;}}
table{{width:100%;border-collapse:collapse;margin-top:34px;}}
td{{border-top:1px solid var(--line);padding:16px 10px;vertical-align:top;font-size:14px;}}
td.dim{{text-transform:uppercase;letter-spacing:0.05em;font-size:12px;color:var(--muted);width:130px;}}
td span{{display:block;color:var(--muted);font-size:13px;margin-top:5px;}}
.stance{{font-family:'Geist Mono',monospace;font-size:11px;border-radius:4px;padding:2px 7px;}}
.stance.safe{{color:var(--muted);border:1px solid var(--line);}}
.stance.risk{{color:#0E0E0E;background:var(--ink);}}
ul{{margin-top:18px;padding-left:18px;color:var(--muted);font-size:13px;line-height:1.7;}}
ul b{{color:var(--ink);}}
</style></head><body><div class="wrap">
<h1>{name}</h1>
<p class="sub">Design system &mdash; {escape(system.aesthetic)}</p>
<p class="memo">{escape(system.memorable_thing)}</p>
<span class="tier">grounding: {escape(system.grounding_tier)}</span>
{note}
<table>{"".join(rows)}</table>
{signals_block}
</div></body></html>"""
