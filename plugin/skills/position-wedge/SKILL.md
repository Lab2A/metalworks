---
name: position-wedge
description: Turn a finished demand report into a grounded market-positioning wedge — a Dunford statement (competitive alternative, unique attribute, value, beachhead, category) plus a price hypothesis, every slot tracing to a real Reddit quote or web finding by permalink. Use after a demand report exists and the user asks "how should I position this", "what's the angle", "what's my wedge", or wants a positioning statement / pricing hypothesis grounded in evidence rather than invented.
---

You are turning one demand report into a defensible positioning hypothesis — a
Dunford wedge whose every claim points back to evidence the report already
verified. You are NOT brainstorming taglines; the wedge is selected from real
demand signal, not invented.

## Steps

1. Get the `report_id`. If the user hasn't run a report yet, point them at
   `/demand-report` first — positioning needs a finished report to stand on.

2. Call the `positioning_from_report` MCP tool with the `report_id` (or, on the
   CLI, run `metalworks position <report_id>`). It does one LLM call and returns
   a `PositioningBrief`.

3. Read the brief honestly:
   - If `wedge` is present, present the Dunford statement, then each slot:
     **competitive alternative** (what they use today), **unique attribute** (the
     white space competitors miss), **value**, **beachhead** (the narrow first
     audience), **market category**.
   - Show the **price hypothesis** band when present (and say "insufficient price
     signal" when the report had none — never invent a number).
   - For each wedge claim, surface the backing evidence: resolve its
     `EvidenceRef`s against the report's evidence and show the permalink(s). A
     claim with no resolvable evidence does not ship.

4. If `partial` is true, lead with the `caveat`. Two honest cases:
   - **No wedge**: every strong cluster is echoed by the web — there's no
     differentiated angle in this evidence. Say so plainly; don't manufacture one.
   - **Unverified clause**: a phrased attribute/value wasn't entailed by its
     cited quotes. Present it explicitly as a hypothesis to test, not a finding.

## Rules

- The wedge stands on a cluster the web stream is **silent on or disagrees with**
  at ≥ MEDIUM signal. That's the whole point — a position competitors miss. If
  none exists, the honest answer is "no defensible wedge here yet."
- Never recompute the price band — it is copied through from the report's price
  evidence. No evidence → "insufficient price signal."
- Every wedge claim must carry a permalink. Treat the brief as a **hypothesis**,
  not a verified finding — it's a sharp starting point for the founder, grounded
  in what real people said.
- This skill only positions. It does not build, launch, or write the site —
  offer the next pillar once those ship.
