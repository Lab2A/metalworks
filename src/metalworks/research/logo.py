"""Logo generation — five diverse, company-grade SVG options per brand.

The model AUTHORS the SVG directly. This is deliberate and the one place
metalworks lets the LLM draw geometry, because a logo is a designed artifact,
not a grounded claim. Quality came down to two things, found empirically:

1. A strong house design system, held constant (``TASTE``).
2. Concept DIVERSITY — five independent passes, each a different design angle.

A critique/refine loop was tried and was not worth its cost; five diverse single
passes with a human picking the winner beat it. So this module makes one
``complete_text`` call per angle and returns the set for a person to choose from.
"""

from __future__ import annotations

import re
from html import escape
from typing import TYPE_CHECKING

from metalworks.contract.logo import LogoOption, LogoSet

if TYPE_CHECKING:
    from metalworks.contract import DemandReport
    from metalworks.llm import ChatModel

# The house design system. Held constant across every angle and every brand.
TASTE = """You are the house logo designer. Hold to this system exactly.

WHAT WE MAKE
One logo: a single concept-driven mark plus a confident wordmark, together as one
balanced lockup, in a restrained editorial style. The bar is a logo a well-funded
startup would actually ship (the craft level of Stripe, Linear, Vercel, Mono), not
a clip-art icon next to text.

PRINCIPLES
- One idea. The mark expresses a single concept tied to what the company does.
  Never generic geometric filler, never a stock symbol.
- Restraint. Two colors at most (one ink, one accent) plus neutrals. Generous
  negative space.
- Clean construction. Primitives and simple, deliberate curves. Even stroke
  weights. Optical centering. No lumpy freehand, no gradients, no filters, no shadows.
- The wordmark is half the logo. A typeface that carries the brand's personality,
  tracked deliberately. Mark and wordmark share weight, rhythm, and color.
- Timeless over trendy. Must read at 32px favicon size.

CRAFT
- One stroke weight through the mark. Match the mark's height to the wordmark's
  cap height; sit them on one optical baseline. Round/pointed shapes overshoot
  flats slightly. 2-3 anchor points beat a busy path.

OUTPUT
Return ONLY one clean SVG, nothing else. viewBox "0 0 320 200", lockup centered.
System font stacks only via font-family, no external fonts. Transparent or cream
(#FBFAF6) ground.

NEVER
A generic centered sans with a clip-art icon; more than one concept crammed in;
rainbow palettes, gradients, bevels, shadows; wobbly symmetry; a mark that means
nothing about the business."""

# The five angles that won the bake-off. Diversity is the lever, so each pass gets
# a genuinely different design strategy.
ANGLES: list[tuple[str, str]] = [
    (
        "symbol",
        "DESIGN ANGLE: A symbol-led mark. One concept icon tied to what the "
        "company does, beside a clean wordmark. Commit to ONE idea.",
    ),
    (
        "logotype",
        "DESIGN ANGLE: The wordmark itself is the logo. Apply ONE distinctive "
        "custom intervention to the letterforms (a ligature, a cut counter, a "
        "swapped terminal, a meaningful negative space in a letter). A symbol is "
        "optional and secondary.",
    ),
    (
        "negative-space",
        "DESIGN ANGLE: Fuse two brand-relevant ideas so the second is formed "
        "by the negative space inside the first (in the spirit of the FedEx "
        "arrow). The hidden element must be genuine, never forced.",
    ),
    (
        "reference",
        "DESIGN ANGLE: Work in the tradition of two or three admired marks in this "
        "company's space. Extract the construction principles they share and design "
        "an ORIGINAL mark in that idiom. Never copy an existing logo.",
    ),
    (
        "expressive",
        "DESIGN ANGLE: First write yourself a vivid one-line art-direction brief "
        "for this brand, then draw an expressive, distinctive mark straight from it.",
    ),
]

DEFAULT_N = 5
_SVG_RE = re.compile(r"<svg\b.*?</svg>", re.DOTALL | re.IGNORECASE)


def _extract_svg(text: str) -> str | None:
    """Pull the first complete <svg>…</svg> out of model output, or None."""
    m = _SVG_RE.search(text)
    return m.group(0).strip() if m else None


def _cluster_labels(report: DemandReport, limit: int = 3) -> list[str]:
    """Best-effort short labels of what customers care about, for the brief."""
    labels: list[str] = []
    for cluster in getattr(report, "ranked_clusters", [])[:limit]:
        for attr in ("label", "name", "title", "claim", "theme", "summary"):
            val = getattr(cluster, attr, None)
            if isinstance(val, str) and val.strip():
                labels.append(val.strip()[:80])
                break
    return labels


def suggest_brand_name(chat: ChatModel, report: DemandReport) -> str:
    """Ask the model for a short brandable name when none was supplied."""
    try:
        out = chat.complete_text(
            system="You name software products. Reply with ONLY a short, brandable product "
            "name (one or two words). No punctuation, no quotes, no explanation.",
            user=f"Product: {report.query}",
            max_tokens=24,
            temperature=0.7,
        )
        name = out.text.strip().splitlines()[0].strip().strip('".').split()
        cleaned = " ".join(w for w in name[:2] if w)
        return cleaned or "Brand"
    except Exception:
        return "Brand"


def _brand_brief(report: DemandReport, brand_name: str) -> str:
    lines = [f"Brand name (the wordmark): {brand_name}", f"What it does: {report.query}"]
    labels = _cluster_labels(report)
    if labels:
        lines.append("What customers care about: " + "; ".join(labels))
    if getattr(report, "verdict", None):
        lines.append(f"Signal: {report.verdict}")
    lines.append(f"Wordmark text to set: {brand_name}")
    return "\n".join(lines)


def build_logo_set(
    chat: ChatModel,
    report: DemandReport,
    *,
    brand_name: str | None = None,
    n: int = DEFAULT_N,
) -> LogoSet:
    """Generate up to ``n`` diverse, company-grade logo options for one report.

    One ``complete_text`` pass per design angle. An angle that returns no valid
    SVG is dropped (never faked); the result is marked ``partial`` when fewer than
    ``n`` options survive.
    """
    name = (brand_name or "").strip() or suggest_brand_name(chat, report)
    brief = _brand_brief(report, name)
    angles = ANGLES[: max(1, n)]

    options: list[LogoOption] = []
    dropped: list[str] = []
    for key, instruction in angles:
        try:
            result = chat.complete_text(
                system=f"{TASTE}\n\n{instruction}",
                user=brief,
                max_tokens=2400,
                temperature=0.85,
            )
            svg = _extract_svg(result.text)
        except Exception:
            svg = None
        if svg is None:
            dropped.append(key)
            continue
        concept = instruction.split(": ", 1)[-1].split(".")[0].strip()
        options.append(LogoOption(angle=key, concept=concept, svg=svg))

    partial = len(options) < len(angles)
    caveat = None
    if not options:
        caveat = "No angle produced a valid SVG. Check the chat model key and retry."
    elif partial:
        caveat = (
            f"{len(options)}/{len(angles)} angles produced a logo; dropped: {', '.join(dropped)}."
        )
    return LogoSet(
        report_id=report.report_id,
        brand_name=name,
        options=options,
        partial=partial,
        caveat=caveat,
    )


def render_logo_picker_html(logo_set: LogoSet) -> str:
    """A self-contained page showing every option for a human to pick from."""
    cards: list[str] = []
    for i, opt in enumerate(logo_set.options, 1):
        cards.append(
            f'<figure class="card"><div class="art">{opt.svg}</div>'
            f"<figcaption><b>Option {i}</b> &middot; {escape(opt.angle)}"
            f"<span>{escape(opt.concept)}</span></figcaption></figure>"
        )
    note = ""
    if logo_set.partial and logo_set.caveat:
        note = f'<p class="note">{escape(logo_set.caveat)}</p>'
    name = escape(logo_set.brand_name)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name} — pick a logo</title><style>
:root{{--bg:#F4F1EA;--ink:#1A1A1A;--muted:#8A8578;--line:#E3DECF;--card:#FBFAF6;}}
*{{box-sizing:border-box;}}
body{{margin:0;background:var(--bg);color:var(--ink);
 font-family:'Inter','Helvetica Neue',Arial,sans-serif;-webkit-font-smoothing:antialiased;}}
.wrap{{max-width:1080px;margin:0 auto;padding:64px 36px 120px;}}
.top{{border-bottom:1px solid var(--line);padding-bottom:20px;}}
.top h1{{font-size:24px;font-weight:600;margin:0;letter-spacing:-0.01em;}}
.top p{{color:var(--muted);font-size:13px;margin:8px 0 0;}}
.note{{color:#9a5b2a;font-size:13px;}}
.grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:18px;margin-top:28px;}}
.card{{margin:0;background:var(--card);border:1px solid var(--line);border-radius:14px;
 padding:18px;transition:border-color .15s;}}
.card:hover{{border-color:var(--ink);}}
.art{{display:flex;align-items:center;justify-content:center;min-height:200px;}}
.art svg{{width:100%;height:auto;max-height:220px;}}
figcaption{{margin-top:12px;font-size:12px;letter-spacing:0.04em;text-transform:uppercase;
 color:var(--muted);}}
figcaption span{{display:block;text-transform:none;letter-spacing:0;font-size:13px;
 color:#444;margin-top:5px;}}
</style></head><body><div class="wrap"><div class="top">
<h1>{name}</h1>
<p>Pick a logo &mdash; {len(logo_set.options)} options, each a different design angle.</p>
{note}</div><div class="grid">{"".join(cards)}</div></div></body></html>"""
