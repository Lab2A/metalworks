---
name: logo
description: Generate five diverse, company-grade logo options for a finished demand report and present them for the user to choose. The model authors each SVG directly under a fixed house design system, one per design angle (symbol, logotype, negative-space, reference, expressive). Use after a demand report exists and the user asks to "design a logo", "make a brand mark", "give me logo options", or "what should the logo look like". Options are offered; nothing is auto-selected.
---

You are generating a set of real, company-grade logo options for one brand and
presenting them for the user to pick. The model draws the SVG directly here — a
logo is a designed artifact, not a grounded claim — under a fixed house design
system. The whole point is to show several genuinely different directions, not one.

## Steps

1. Get the `report_id`. If the user hasn't run a report yet, point them at
   `/demand-report` first — the logo is designed for that report's product. Ask
   for the brand name if they have one; otherwise one is generated from the report.

2. Call the `logo_generate` MCP tool with the `report_id` (and `name` if the user
   gave a brand name). On the CLI this is `metalworks research logo <report_id>`.
   It returns a `LogoSet` of up to five `options` — each a different design angle
   (symbol / logotype / negative-space / reference / expressive) — plus a
   self-contained `html` picker page.

3. Present all the options to the user. For each option, show the angle and the
   one-line concept, and render or save its `svg` so they can see it. Save the
   `html` picker to a file and offer to open it — it lays the options out side by
   side, which is the easiest way to choose. Number them so the user can say
   "option 3".

4. If `partial` is true, lead with the `caveat` — some angles can fail to return a
   valid SVG, and a dropped angle is never faked. Present the options that did land.

5. Let the user pick. This is a choice, not an automation: do not declare a winner
   yourself. Once they choose, hand the chosen `svg` off — it is self-contained and
   drops straight into a site (`/generate-site`, `/deploy-site`) or a repo.

## Rules

- Offer options, never auto-select. The human picks the logo.
- The model authors the SVG; keep it as returned. Don't silently redraw it. If the
  user wants changes, ask what to change and regenerate.
- Each option is a single clean concept under the house system: at most two colors,
  clean geometry, a mark plus a confident wordmark, legible at favicon size.
- The logo is designed for this specific business — if the user wants it grounded in
  particular positioning, run `/position-wedge` first and mention the angle.
