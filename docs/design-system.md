---
title: "Design system"
description: "Author a grounded-but-flexible visual design system for your report — an aesthetic direction and a SAFE/RISK choice per dimension, read from what rivals actually do, honest about how grounded the look is."
---

**Design the look, informed by the competition — not generic taste.**

Positioning grounds the *words*; the design pillar grounds the *look*. From a finished
[demand report](/docs/demand-research) it authors a **design system**: an aesthetic
direction, the one thing someone should remember, and one **SAFE/RISK** choice per
design dimension (typography, color, layout, spacing, motion, decoration), plus a
`DESIGN.md` source of truth and a preview page.

Unlike the rest of metalworks, design is **taste**, so grounding here is *directional,
not cited*: the competitive landscape **informs** the bet ("rivals skew serif → lean
serif, or break to sans"); it does not cite it. Two honesty signals carry the weight
instead — every choice is labelled **SAFE** (category baseline) or **RISK** (a
deliberate departure), and the system records its **grounding tier**.

<CodeGroup>

```text Claude Code
/demand-report a calm focus timer for makers
/design
```

```python Python
from metalworks import Metalworks

mw = Metalworks()
research = mw.research("a calm focus timer for makers")

system = mw.design(research, brand_name="Cadence", taste="editorial")  # author under a preset
print(system.grounding_tier)                          # renderer | web | model_knowledge
print(system.taste)                                   # the preset it was authored under
for c in system.choices:
    print(c.dimension, c.stance, "—", c.decision)     # SAFE / RISK per dimension
open("preview.html", "w").write(mw.render_design_preview(system))
```

```bash CLI
metalworks research design <report-id> --taste brutalist --out ./brand
```

</CodeGroup>

## The grounding tier (read this first)

The system records **how grounded the look actually is**, so a confident design that
never saw a competitor can't masquerade as a grounded one:

| Tier | What happened |
| --- | --- |
| `renderer` | A **real teardown** — a headless browser screenshotted rival sites and read their actual fonts/colors. Richest; needs the browser ([install below](#a-real-teardown-needs-the-browser)). |
| `web` | No live teardown, but real competitor names/taglines from the landscape informed it. |
| `model_knowledge` | No competitor data — the system is category convention, not this brand's landscape. Returned `partial` with a caveat. |

## Taste presets

A small, curated set of opinionated directors — pick one with `taste=` (Python/MCP)
or `--taste` (CLI). The chosen preset is recorded on `system.taste` and drives the
preview/logo-picker chrome. The same report under two presets yields a visibly
different system.

| Preset | Voice |
| --- | --- |
| `editorial` *(default)* | The house voice — editorial monochrome, dark-first. Preserves the original output. |
| `brutalist` | Raw, structural, anti-decorative; one loud signal color, hard edges. |
| `warm-minimal` | Calm and warm; soft paper ground, a single muted earthy accent. |
| `technical` | Instrument-grade tool aesthetic; mono/grotesque type, dense, precise. |

## What you get back

| Field | What it is |
| --- | --- |
| `aesthetic` | The direction in one line (e.g. "editorial monochrome, dark-first"). |
| `memorable_thing` | The one thing someone should remember on first sight. |
| `choices[]` | One `DesignChoice` per dimension: the `decision`, a `stance` (`safe`/`risk`), and the rationale. |
| `landscape_signals[]` | Directional reads of the competition (observation → the move it implies). |
| `taste` | The preset it was authored under (`editorial` / `brutalist` / `warm-minimal` / `technical`). |
| `grounding_tier` | `renderer` / `web` / `model_knowledge` — how grounded the look is. |
| `design_md` | The rendered `DESIGN.md` — your per-project source of truth. |

The choices carry **no** `evidence_refs` by design — design grounding is directional,
not cited. This pillar authors a **system**, not pixels: hand the `DESIGN.md` to your
build step to apply it.

## A real teardown needs the browser

The `renderer` tier — a real screenshot-and-style teardown of competitor sites — needs
the browser extra and Chromium:

```bash
pip install "metalworks[browser]"
metalworks browser install        # downloads Chromium (the post-install step)
```

Without it the pillar still works, just at the `web` or `model_knowledge` tier — always
clearly labelled. On a server, set `FIRECRAWL_API_KEY` to render without a local browser.
