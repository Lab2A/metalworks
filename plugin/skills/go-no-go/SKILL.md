---
name: go-no-go
description: Deliver an honest GO / PIVOT / NO-GO verdict for a finished demand report — the gap between demand (is the pain real) and landscape (can people already solve it). Use after a demand report exists and the user asks "is this worth building", "should I build this", "go or no-go", "what's the verdict", or wants a straight build/don't-build call rather than more analysis. The decision is computed deterministically from the evidence; you deliver it like an office-hours partner — argue it with quotes, and let the human make the final call.
---

## Preamble (run first)

Before any other tool, run the `preflight` MCP tool (or `metalworks preflight` on
the CLI). If it reports setup issues or that an update is available, surface that
to the user in one line and help them resolve it (install the missing extra/key,
or `pip install -U metalworks`) before continuing. Skip only if the user has
already passed preflight this session.

**Read the reference; never reverse-engineer the source.** The moment you need to know how
metalworks behaves — provider/model resolution, which source/reader runs, config precedence,
an error you hit, or the async run loop — **STOP and read `docs/operating-metalworks.md`
(bundled with this plugin) before opening any file under `src/`.** It is the source of truth;
do not derive behavior from source. (Full docs: https://metalworks.lab2a.ai/docs.) For a
long-running run, poll status with the Monitor tool or a bounded loop — never a blind `sleep`.

You are giving a founder the honest verdict. The decision itself is computed — demand
strength (how many distinct people) measured against landscape saturation (what already
exists) — so you are not guessing; you are arguing the computed call with evidence and
recording the human's decision. Three lanes, never two: GO, PIVOT (real demand, wrong
target), NO-GO.

## Steps

1. Get the `report_id`. No report yet → run `/demand-report` first; the verdict stands on
   the report's clusters and its landscape.

2. Call the `assess_from_report` MCP tool with the `report_id` (or CLI:
   `metalworks research assess <report_id>`). It runs the landscape, then the deterministic
   gap, and returns an `Assessment`: a `decision`, a `gap` (demand strength × landscape
   saturation), a `rationale`, and — on PIVOT — a `pivot_target`.

3. Deliver it like an office-hours partner, honestly:
   - **Lead with the decision** and the one-line gap: "GO — strong demand (47 distinct
     voices), open landscape" / "PIVOT — real demand but the space is crowded" / "NO-GO —
     thin demand."
   - **Argue it with evidence.** Resolve the assessment's `EvidenceRef`s and show the real
     quotes behind the demand; name the competitors / existing solutions behind the saturation.
   - **On PIVOT, make the target concrete.** Show the `pivot_target` — the under-served wedge
     or segment the report surfaced — and why it's the better bet. PIVOT loops back to ideation
     with that target.
   - **On NO-GO, don't soften it.** Say why plainly; thin demand or a saturated space with no
     opening is a real answer.

4. If `partial` is true, lead with the `caveat`. The key case: the landscape grounding was
   partial, so a hard GO was withheld by design (absence of evidence is not absence of
   competition) — the verdict will be PIVOT or NO-GO, never GO.

5. **The human decides.** Present the computed verdict as a strong recommendation, then ask
   the user for their GO / PIVOT / NO-GO call. They have context the corpus doesn't; the SDK
   recommends, the human commits.

## Rules

- **The decision is computed, not vibed** — never override the band logic with optimism. If
  the evidence says NO-GO, deliver NO-GO and explain it.
- **A partial landscape never yields GO.** Say so when it applies.
- **Every claim cites.** Demand strength resolves to real quotes; saturation resolves to real
  competitors / shipped products. No uncited verdict.
- This skill only delivers the verdict. GO hands off to positioning/build; PIVOT loops back to
  `/ideate` with the target; NO-GO ends the loop (or starts a fresh idea).
