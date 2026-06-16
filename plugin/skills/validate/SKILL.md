---
name: validate
description: Run the full validation loop on an idea — ideate → demand → landscape → assess (GO/PIVOT/NO-GO) → loop — with the human deciding at each gate. Use when the user wants to find out whether an idea is worth building end to end, asks to "validate this idea", "run the loop", "take this through the whole thing", or wants to keep refining until they hit a GO or run out of road. This is the interactive, human-gated loop; for a headless one-shot run use `metalworks research validate "<idea>"` (the SDK --auto orchestrator). Not to be confused with `metalworks discovery` (Reddit reply opportunities).
---

You are running a founder through the whole discovery loop, and they make the call at each
gate. You drive the stages by calling the discrete tools; the human is the decision callback.
The loop ends on GO (advance to building), NO-GO (kill it honestly), or when you've circled
the space without a new fork to try (exhausted — say so).

## The loop

Repeat until GO, NO-GO, or exhausted (cap ~4 rounds):

1. **Ideate.** Call `ideate_from_idea` with the current idea (first round: the user's idea;
   later rounds: the pivot target from the previous assessment). Reflect the sharpened
   hypothesis back.

2. **Demand.** Run a demand report on the sketch's brief (the `/demand-report` flow). This is
   the slow step — say so.

3. **Landscape.** Call `landscape_from_report` — competitors + existing solutions + the
   do-nothing cost.

4. **Assess.** Call `assess_from_report` (it runs landscape then the verdict). Present the
   GO/PIVOT/NO-GO honestly, with the gap (demand strength vs. saturation) and the evidence.

5. **The human decides.** Show the computed recommendation, then ask the user via
   AskUserQuestion: GO, PIVOT, or NO-GO. They have context the corpus doesn't.
   - **GO** → stop. Hand off to positioning / build.
   - **PIVOT** → take the assessment's `pivot_target` (the under-served fork) as the next
     idea and loop. Never re-propose a fork you've already killed — track what's been ruled out.
   - **NO-GO** → stop. Say plainly why; that's a real answer.

## Rules

- **Don't loop forever.** After ~4 rounds, or when a pivot would repeat a fork you already
  tried, stop and say the space looks exhausted — the honest answer is it lacks an opening.
- **Track ruled-out forks** so a killed idea never comes back around.
- **A partial landscape never yields a hard GO** — the assessment enforces this; respect it.
- **The human is the callback.** You compute and recommend; they commit at each gate.
- Every round's verdict cites real evidence — demand quotes, real competitors. No uncited call.
- This skill orchestrates the loop. Each stage's depth lives in its own skill
  (`/ideate`, `/demand-report`, `/market-landscape`, `/go-no-go`).
