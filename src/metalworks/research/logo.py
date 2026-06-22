"""Logo generation — diverse, company-grade SVG marks under a design system.

The mark submodule of the visual-design pillar. The model AUTHORS the SVG
directly — the one place metalworks lets it draw geometry, because a logo is a
designed object, not a grounded claim. Two levers, found empirically:

1. A constant house CRAFT bar (``CRAFT``) — the quality floor.
2. Concept DIVERSITY — N independent passes, each a different design angle.

What changed from a standalone logo tool: the brand DIRECTION (aesthetic,
typography, color) is no longer invented per call — it comes from the brand's
:class:`~metalworks.contract.design.DesignSystem`, so the mark draws under the
same system the rest of the brand uses. ``CRAFT`` is just the constant craft bar.

A critique/refine loop was tried and not worth its cost; diverse single passes
with a human picking the winner beat it. So this makes one ``complete_text`` call
per angle and returns the set for a person to choose from. An angle that returns
no valid SVG — or an UNSAFE one (a ``<script>`` / event handler / ``<foreignObject>``
in model-authored markup) — is dropped, never faked.
"""

from __future__ import annotations

import re
from html import escape
from typing import TYPE_CHECKING

from metalworks.contract.logo import LogoOption, LogoSet

if TYPE_CHECKING:
    from metalworks.contract.design import DesignSystem
    from metalworks.llm import ChatModel

# The constant CRAFT bar — the quality floor, held across every angle and brand.
# The brand's specific aesthetic / type / color come from its DesignSystem, not here.
CRAFT = """You are the house logo designer. Hold to this craft bar exactly.

WHAT WE MAKE
One logo: a single concept-driven mark plus a confident wordmark, together as one
balanced lockup. The bar is a logo a well-funded startup would actually ship (the
craft of Stripe, Linear, Vercel, Mono), not a clip-art icon next to text. Draw it
UNDER the brand's design system below — its aesthetic, typeface feel, and colors.

PRINCIPLES
- One idea. The mark expresses a single concept tied to what the company does.
  Never generic geometric filler, never a stock symbol.
- Restraint. Two colors at most (one ink, one accent) plus neutrals, taken from
  the brand's color choice. Generous negative space.
- Clean construction. Primitives and simple, deliberate curves. Even stroke
  weights. Optical centering. No lumpy freehand, no gradients, no filters, no shadows.
- The wordmark is half the logo. Set it in the spirit of the brand's typography
  choice. Mark and wordmark share weight, rhythm, and color.
- Timeless over trendy. Must read at 32px favicon size.

CRAFT
- One stroke weight through the mark. Match the mark's height to the wordmark's
  cap height; sit them on one optical baseline. Round/pointed shapes overshoot
  flats slightly. 2-3 anchor points beat a busy path.

OUTPUT
Return ONLY one clean SVG, nothing else. viewBox "0 0 320 200", lockup centered.
System font stacks only via font-family, no external fonts. No <script>, no event
handlers, no <foreignObject>. Transparent or cream (#FBFAF6) ground.

NEVER
A generic centered sans with a clip-art icon; more than one concept crammed in;
rainbow palettes, gradients, bevels, shadows; wobbly symmetry; a mark that means
nothing about the business."""

# The angles that won the bake-off. Diversity is the lever, so each pass gets a
# genuinely different design strategy.
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
# Active content a model-authored SVG must never carry (it lands in an HTML page).
_UNSAFE_RE = re.compile(r"<script|</script|<foreignObject|\son\w+\s*=|javascript:", re.IGNORECASE)


def _extract_svg(text: str) -> str | None:
    """Pull the first complete, SAFE ``<svg>…</svg>`` out of model output, or None.

    An SVG carrying a ``<script>``, an ``on*=`` event handler, ``<foreignObject>``,
    or a ``javascript:`` URL is rejected (returns None) — model-authored geometry
    is rendered into an HTML picker, so it must not execute. A rejected SVG is
    treated exactly like a missing one: the angle is dropped, the set marked partial.
    """
    m = _SVG_RE.search(text)
    if m is None:
        return None
    svg = m.group(0).strip()
    if _UNSAFE_RE.search(svg):
        return None
    return svg


def _brand_brief(system: DesignSystem) -> str:
    """The brief fed to every angle — the brand's system, so the mark draws under it."""
    lines = [f"Brand name (the wordmark): {system.brand_name}"]
    if system.memorable_thing:
        lines.append(f"The one thing to express: {system.memorable_thing}")
    if system.aesthetic:
        lines.append(f"Aesthetic: {system.aesthetic}")
    for choice in system.choices:
        if choice.dimension in ("typography", "color"):
            lines.append(f"{choice.dimension}: {choice.decision}")
    lines.append(f"Wordmark text to set: {system.brand_name}")
    return "\n".join(lines)


def build_logo_set(chat: ChatModel, system: DesignSystem, *, n: int = DEFAULT_N) -> LogoSet:
    """Generate up to ``n`` diverse logo options that draw under ``system``.

    One ``complete_text`` pass per design angle, each under the constant CRAFT bar
    plus the brand's design system. An angle that returns no valid (or unsafe) SVG
    is dropped (never faked); the set is ``partial`` when fewer than ``n`` survive.
    """
    brief = _brand_brief(system)
    angles = ANGLES[: max(1, n)]

    options: list[LogoOption] = []
    dropped: list[str] = []
    for key, instruction in angles:
        try:
            result = chat.complete_text(
                system=f"{CRAFT}\n\n{instruction}",
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
    caveat: str | None = None
    if not options:
        caveat = "No angle produced a valid SVG. Check the chat model key and retry."
    elif partial:
        caveat = (
            f"{len(options)}/{len(angles)} angles produced a logo; dropped: {', '.join(dropped)}."
        )
    return LogoSet(
        report_id=system.report_id,
        brand_name=system.brand_name,
        options=options,
        partial=partial,
        caveat=caveat,
    )


def render_logo_picker_html(logo_set: LogoSet) -> str:
    """A self-contained page showing every option for a human to pick from.

    Each ``svg`` was validated by :func:`_extract_svg` (no script / handler /
    foreignObject) before it reached the set, so it is safe to inline here.
    """
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
