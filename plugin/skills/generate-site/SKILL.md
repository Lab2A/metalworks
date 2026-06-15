---
name: generate-site
description: Turn a finished demand report into a small, grounded marketing site — hero, feature, objection, pricing, social-proof and CTA sections whose every claim-bearing line is a verbatim fragment of a real Reddit quote, footnoted to its permalink. Use after a demand report (and optionally a positioning wedge) exists and the user asks "build me a landing page", "draft the marketing site", "what should the homepage say", or wants website copy grounded in what real people actually said rather than invented marketing claims.
---

You are turning one demand report into a small marketing site whose every
load-bearing line points back to a real Reddit quote by permalink. You are NOT
writing aspirational marketing copy; each claim is a VERBATIM fragment the
report already verified, and a section with no backing quote does not ship.

## Steps

1. Get the `report_id`. If the user hasn't run a report yet, point them at
   `/demand-report` first — a site needs a finished report to stand on. If a
   positioning wedge already exists (`/position-wedge`), pass it through so the
   copy honors that angle.

2. Call the `site_render` MCP tool with the `report_id` (or, on the CLI, run
   `metalworks site <report_id>`). It takes the top 3 clusters by demand, makes
   one constrained LLM call to assign each a section role and pick a verbatim
   fragment, then re-verifies every fragment against the real quotes and returns
   a `MarketingSite` plus the rendered `index.html`.

3. Read the site honestly:
   - For each `verbatim` section, present the role (hero / feature / objection /
     pricing / social_proof / cta) and the copy, and surface the backing quote:
     resolve its single `EvidenceRef` against the report's evidence and show the
     permalink. The hero is built on the cluster with the most DISTINCT authors —
     the broadest base rate, not the loudest post.
   - `connective` sections are claim-free transitions with no refs. They are
     glue, not evidence — never present them as findings.

4. If `partial` is true, lead with the `caveat`. The honest cases:
   - **No quote-backed clusters**: the report had no clusters carrying verified
     quotes to build on. Say so; don't fabricate sections.
   - **No fragment matched**: the LLM's picked fragments didn't exact-match any
     verified quote, so every section was dropped (no-quote-no-section).
   - **Synthesis unavailable**: the LLM call failed; the site is empty by design,
     never invented.

5. To finalize the look, hand the rendered `index.html` to `design-html` /
   `clique-feel` to style it against `DESIGN.md` — keep the footnotes and the
   `data-evidence` attributes intact so the provenance chain survives styling.

## Rules

- Every claim-bearing line cites a real permalink. A section's load-bearing copy
  is a verbatim substring of a real `ResolvedCitation.text`; if it isn't, the
  section is DROPPED. No-quote-no-section — the same gate the report uses.
- Connective copy must be claim-free: no numbers, no superlatives
  (best/most/fastest/only/…). It carries no `EvidenceRef`. If glue smuggles in a
  claim, it is dropped.
- The hero stands on the highest-distinct-author cluster. Don't reorder it onto
  a louder-but-narrower cluster.
- Never invent a testimonial, a stat, or a guarantee. If the evidence doesn't
  say it, the site doesn't say it.
- This skill only drafts grounded copy + a bare `index.html`. It does not design,
  theme, or deploy — hand the render to `design-html` / `clique-feel` for the
  visual pass against the design system.
