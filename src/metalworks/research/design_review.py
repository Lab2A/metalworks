"""Design review — a deterministic audit of a RENDERED page vs its design system.

The QA counterpart to the design pillar. It uses a script-capable renderer
(Playwright) to read a page's ACTUAL computed styles — fonts, heading scale,
colors — and grades them DETERMINISTICALLY: hard rules (too many fonts, the
AI-default convergence-trap body face, a non-monotonic heading scale) plus, when
a :class:`~metalworks.contract.design.DesignSystem` is supplied, whether the
rendered look matches the brand. The model writes nothing — every finding is a
pure function of the computed styles (the deterministic-decisions rule).

Requires a renderer whose ``capabilities.supports_style_audit`` is True; a
screenshot-only backend (Firecrawl) raises
:class:`~metalworks.errors.StyleAuditUnsupported`.
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from metalworks.contract.design import DesignReview, StyleFinding

if TYPE_CHECKING:
    from metalworks.contract.design import DesignSystem
    from metalworks.render import ComputedStyle, PageRenderer

_SELECTORS = ["body", "h1", "h2", "h3", "a", "button"]
# Faces every AI design tool reaches for — flagged when they're the body face.
_CONVERGENCE = {
    "inter",
    "roboto",
    "arial",
    "helvetica",
    "system-ui",
    "-apple-system",
    "open sans",
    "montserrat",
    "poppins",
    "space grotesk",
}


def _first_family(style: ComputedStyle | None) -> str:
    if style is None or not style.font_family:
        return ""
    return style.font_family.split(",")[0].strip().strip("'\"")


def _px(style: ComputedStyle | None) -> float:
    if style is None or not style.font_size:
        return 0.0
    try:
        return float(style.font_size.lower().replace("px", "").strip())
    except ValueError:
        return 0.0


def review_design(
    renderer: PageRenderer, url: str, *, system: DesignSystem | None = None
) -> DesignReview:
    """Audit the rendered styles of ``url`` deterministically (optionally vs ``system``).

    Reads the computed styles of a fixed set of selectors and flags hard-rule
    violations (font count, convergence-trap body face, non-monotonic heading
    scale) plus, when ``system`` is given, whether the rendered fonts match it.
    Raises :class:`StyleAuditUnsupported` if ``renderer`` can't read computed styles.
    """
    styles = {s.selector: s for s in renderer.extract_computed_styles(url, _SELECTORS)}
    body = styles.get("body")

    fonts: list[str] = []
    for sel in _SELECTORS:
        fam = _first_family(styles.get(sel))
        if fam and fam not in fonts:
            fonts.append(fam)
    headings = [
        styles[h].font_size for h in ("h1", "h2", "h3") if h in styles and styles[h].font_size
    ]

    findings: list[StyleFinding] = []
    if len(fonts) > 3:
        findings.append(
            StyleFinding(
                severity="warn",
                category="fonts",
                detail=f"{len(fonts)} distinct font families rendered (keep it to 3 or fewer): "
                f"{', '.join(fonts)}.",
            )
        )
    body_face = _first_family(body)
    if body_face and body_face.lower() in _CONVERGENCE:
        findings.append(
            StyleFinding(
                severity="warn",
                category="fonts",
                detail=f"Body font is '{body_face}' — the AI-default convergence-trap face. "
                "Pick a typeface with a point of view.",
            )
        )
    h_px = [_px(styles.get(h)) for h in ("h1", "h2", "h3")]
    present = [x for x in h_px if x > 0]
    if len(present) >= 2 and any(a < b for a, b in itertools.pairwise(present)):
        findings.append(
            StyleFinding(
                severity="warn",
                category="headings",
                detail="Heading scale isn't monotonically decreasing (expect h1 >= h2 >= h3).",
            )
        )

    against = system is not None
    if system is not None:
        typ = next((c.decision for c in system.choices if c.dimension == "typography"), "").lower()
        if body_face and typ and body_face.lower() not in typ:
            findings.append(
                StyleFinding(
                    severity="warn",
                    category="system_match",
                    detail=f"Rendered body font '{body_face}' isn't in the design system's "
                    "typography choice.",
                )
            )
        else:
            findings.append(
                StyleFinding(
                    severity="ok",
                    category="system_match",
                    detail="Rendered fonts align with the design system.",
                )
            )

    fails = sum(f.severity == "fail" for f in findings)
    warns = sum(f.severity == "warn" for f in findings)
    score = max(0, 10 - 3 * fails - warns)
    return DesignReview(
        url=url,
        fonts=fonts,
        headings=headings,
        ink=body.color if body else "",
        background=body.background_color if body else "",
        findings=findings,
        score=score,
        passed=fails == 0,
        against_system=against,
        generated_at=datetime.now(UTC),
    )
