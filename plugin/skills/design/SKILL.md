---
name: design
description: Author a grounded-but-flexible visual design system for a finished demand report — an aesthetic direction, a SAFE/RISK choice per design dimension (typography, color, layout, spacing, motion, decoration), and a DESIGN.md source of truth. Use after a demand report exists and the user asks "design the brand", "what should this look like", "give me a design system", "what fonts/colors", or wants a look grounded in what rivals actually do rather than generic taste. The competition is read at the richest tier available (a real browser teardown of competitor sites > web text > the model's own knowledge); the result is honest about which tier produced it. Authors a system; it does NOT write product CSS.
---

You are authoring the VISUAL design system for one report — the look's counterpart
to positioning's words. Unlike copy, design is taste, so grounding here is
DIRECTIONAL, never cited: the competitive landscape INFORMS the bet ("rivals skew
serif → lean serif, or break to sans"); it does not cite it. Two honesty signals
carry the weight: every choice is labelled SAFE (category baseline) or RISK (a
deliberate departure), and the system records its GROUNDING TIER so the look is
never overstated.

## Steps

1. Get the `report_id`. No report yet → run `/demand-report` first; a design
   system stands on the report's audience + the competitive landscape.

2. Call the `design_from_report` MCP tool with the `report_id` (and `name` for the
   brand, else the model suggests one). On the CLI: `metalworks design <report_id>`.
   It builds the landscape, reads the competition at the richest tier available, and
   returns a `DesignSystem` + a self-contained preview HTML. It writes a `DESIGN.md`.

3. **Lead with the grounding tier — this is the honesty bit.** The result's
   `grounding_tier` is one of:
   - `renderer` — a REAL teardown: a browser screenshotted rival sites and read
     their actual fonts/colors. Trust the landscape signals.
   - `web` — no live teardown, but real competitor names/taglines informed it.
   - `model_knowledge` — **no competitor data; the system is category convention,
     not this brand's actual landscape.** Say so plainly — lead with "low signal —
     treat as a hypothesis." Tell the user a real teardown needs the browser:
     `metalworks browser install`.

4. Present the system honestly:
   - the **aesthetic** direction and the **one memorable thing**;
   - the **SAFE vs RISK** choices — walk each dimension, and call out the RISKs as
     the deliberate departures where the brand gets its face (what each gains AND
     costs);
   - the **landscape signals** (what rivals converge on → the move it implies).

5. The `DESIGN.md` is the per-project source of truth; `preview.html` is a visual.
   This skill authors a SYSTEM — it does not write the product's CSS. Hand the
   `DESIGN.md` to the build step (or the marketing site) to apply it.

## Rules

- **Grounding is directional, not cited.** Never present a design choice as
  evidence-backed; the honesty is the SAFE/RISK stance + the grounding tier, not a
  permalink.
- **Lead with the tier when it's `model_knowledge`.** A confident look that never
  saw a competitor is the most misleading output here — flag it before the choices.
- **Authors a system, not pixels.** No product CSS, no component code.
- A grounded teardown (`renderer` tier) needs the browser extra + Chromium
  (`metalworks browser install`); without it the pillar still works, just at a
  lower, clearly-labelled tier.
