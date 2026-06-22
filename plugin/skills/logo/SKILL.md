---
name: logo
description: Generate diverse, company-grade logo options for a finished demand report and present them for the user to choose. The mark submodule of the design pillar — the model authors each SVG directly, under the brand's design system (its aesthetic, typography, color), one per design angle (symbol, logotype, negative-space, reference, expressive). Use after a demand report exists and the user asks to "design a logo", "make a brand mark", "give me logo options", or "what should the logo look like". Options are offered; nothing is auto-selected.
---

You are generating a set of real, company-grade logo options for one brand and
presenting them for the user to pick. This is the **mark submodule of the design
pillar**: the model draws each SVG directly — a logo is a designed artifact, not a
grounded claim — but **under the brand's design system** (its aesthetic, typeface
feel, and colors), not an invented house style. The whole point is to show several
genuinely different directions, not one.

## Steps

1. Get the `report_id`. If the user hasn't run a report yet, point them at
   `/demand-report` first — the logo is designed for that report's product. Ask for
   the brand name if they have one; otherwise one is generated.

2. Call the `logo_generate` MCP tool with the `report_id` (and `name` if the user
   gave a brand name). On the CLI: `metalworks research logo <report_id>`. It builds
   the brand's **design system** first, then draws up to five `options` under it —
   each a different design angle (symbol / logotype / negative-space / reference /
   expressive) — and returns the `LogoSet` plus a self-contained `html` picker page.
   (For the full system itself, run `/design`.)

3. Present all the options. For each, show the angle and the one-line concept, and
   render or save its `svg` so the user can see it. Save the `html` picker and offer
   to open it — it lays the options out side by side. Number them so the user can
   say "option 3".

4. If `partial` is true, lead with the `caveat` — an angle can fail to return a
   valid SVG, and a dropped angle is never faked. (An **unsafe** SVG — one carrying
   a script or event handler — is also dropped automatically, never inlined.)

5. Let the user pick. This is a choice, not an automation: do not declare a winner
   yourself. Once they choose, hand the chosen `svg` off — it is self-contained and
   drops straight into a site or a repo.

## Rules

- Offer options, never auto-select. The human picks the logo.
- The model authors the SVG; keep it as returned (it has already been safety-checked
  and dropped if unsafe). Don't silently redraw it — if the user wants changes, ask
  what to change and regenerate.
- Each option is a single clean concept under the brand's system: at most two
  colors, clean geometry, a mark plus a confident wordmark, legible at favicon size.
- The mark draws under the design system. For a teardown-grounded system first, run
  `/design`; the logo follows the same aesthetic.
