---
title: "Logo"
description: "Generate diverse, company-grade logo options for your brand — the model draws each SVG under your design system, one per design angle. Options are offered, never auto-selected."
---

**Diverse, company-grade logo options — drawn under your design system.**

The mark submodule of the [design pillar](/docs/design-system). A logo is a
*designed* object, not a grounded claim, so this is the one place metalworks lets
the model draw geometry. It authors up to five **diverse** SVG marks — one per
design angle (symbol · logotype · negative-space · reference · expressive) — each
**under your brand's design system** (its aesthetic, typeface feel, and colors),
not an invented house style. Options are **offered, never auto-selected**.

<CodeGroup>

```text Claude Code
/demand-report a calm focus timer for makers
/logo
```

```python Python
from metalworks import Metalworks

mw = Metalworks()
research = mw.research("a calm focus timer for makers")
system = mw.design(research, brand_name="Cadence")   # the brand's design system

logos = mw.logo(system)                              # marks drawn under that system
for opt in logos.options:
    print(opt.angle, "—", opt.concept)
open("picker.html", "w").write(mw.render_logo_picker(logos))
```

```bash CLI
metalworks research logo <report-id> --out ./logos
```

</CodeGroup>

## What you get back

| Field | What it is |
| --- | --- |
| `options[]` | Each a `LogoOption`: the `angle`, a one-line `concept`, and a self-contained, **safety-checked** `svg` (mark + wordmark). |
| `brand_name` | The wordmark name the marks were drawn for. |
| `partial` / `caveat` | `partial` is true when an angle didn't land; the `caveat` says which were dropped. |

## Honesty + safety

- **Offered, never auto-selected.** The pillar shows several genuinely different
  directions; the human picks. metalworks never declares a winner.
- **Dropped, never faked.** An angle that returns no valid SVG is dropped and the
  set marked `partial` — never back-filled.
- **SVG safety gate.** The model authors the SVG, and it lands in an HTML picker, so
  a mark carrying a `<script>`, an `on*=` event handler, a `<foreignObject>`, or a
  `javascript:` URL is **rejected** (treated exactly like a missing one — dropped,
  set marked partial). Model-authored geometry never executes.

## Relationship to `/design`

The logo draws under the brand's [`DesignSystem`](/docs/design-system) — its
aesthetic, typography, and color. The CLI/MCP build that system first, so a single
`metalworks research logo` gives you marks consistent with the brand. For the full
system (and a real competitor teardown), run [`/design`](/docs/design-system) — the
logo follows the same aesthetic.
