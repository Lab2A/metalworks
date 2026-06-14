---
name: build-spec
description: Turn a finished demand report into an evidence-grounded build harness for a coding agent — a BuildSpec (core features each mapped to a real demand cluster and carrying that cluster's verbatim quotes, ICP personas from the audience segments, pricing tiers copied through from the report's price evidence) plus a scaffolded repo (CLAUDE.md cite-or-die rule, docs/SPEC.md, a frozen docs/EVIDENCE.md quote table, a build-pack of skills, and the metalworks MCP wiring). Use after a demand report exists and the user asks "what should I build", "spec the product", "scaffold the app", "turn this into a build", "give me a build plan", or wants to hand the validated demand to a coding agent. metalworks specs and scaffolds — it does NOT write product code. No un-grounded feature survives.
---

You are turning one finished demand report into a build the user's OWN coding
agent will execute. metalworks researched and specced; it does not write the
product. The output is two things: a grounded `BuildSpec` and an on-disk harness
that carries the evidence forward so the downstream agent cannot drift from
validated demand.

## Steps

1. Get the `report_id`. If the user hasn't run a report yet, point them at
   `/demand-report` first — the build spec needs a finished report to ground in.

2. Generate the spec. On the CLI this is one command that also writes the
   harness: `metalworks build init <report_id> --dest ./build --surface web
   --base <stack-hint>`. Via MCP, call the `build_spec` tool with the `report_id`
   (optionally `surface` and `stack`) to get the `BuildSpec` JSON without writing
   files. It needs a chat + embedding key (Tier 2).

3. Walk the spec honestly:
   - **Features** — each one maps to a numbered demand cluster and carries that
     cluster's verbatim quotes as evidence. A feature the LLM proposed with no
     real cluster behind it is DROPPED at assembly (no-cite-no-feature) — what
     survives is only what real users asked for.
   - **Personas** — the ICP, derived from the report's audience segments, each
     tied to a real voice.
   - **Pricing tiers** — copied through from the report's price evidence, never
     recomputed. If the report had no price signal, there are no tiers — say so;
     don't invent a price.
   - If the spec is `partial` (no feature grounded), surface the caveat plainly:
     this is a stub, not a buildable plan. Do not paper over it.

4. The `build init` command scaffolds the harness into `--dest`:
   - `CLAUDE.md` — Rule 0 is cite-or-die, then how to build.
   - `docs/SPEC.md` — the features/personas/pricing, each line carrying its cites.
   - `docs/EVIDENCE.md` — the FROZEN verbatim quote + permalink table the build
     must not drift from.
   - `.claude/skills/` — a build-pack (`scaffold-startup`, `spec-from-report`,
     `cite-or-die`) for the downstream agent.
   - `.claude/scripts/cite_or_die.py` + `.claude/hooks.json` — a PostToolUse lint
     that fails on a dangling citation.
   - `.mcp.json` — points the build back at metalworks to re-spec or pull more
     evidence without leaving the repo.

5. Hand off: tell the user to open the scaffolded directory in their coding agent
   and run `/scaffold-startup`. metalworks specced it; they build it.

## Rules

- **No-cite-no-feature.** Every surviving feature carries ≥1 evidence ref that
  resolves in the report. Never present a feature without its grounding.
- **Copy-through pricing.** Tiers come from the report's price evidence verbatim.
  No price signal → no tiers. Never guess a price.
- **`--base` is a hint, not boilerplate.** metalworks records the stack choice in
  the spec; it does NOT vendor a starter. The downstream agent picks and stands
  up the stack.
- **metalworks is not a coding agent.** This skill stops at the spec + scaffold.
  It does not write features, components, or product code — that is the user's
  agent's job, held to cite-or-die.
- **Infra errors are not "thin demand".** If the spec generation fails on a key
  or model error, surface that — never relabel a broken setup as a partial spec.
- This skill is the end of the build pillar. Offer `/launch-kit` or
  `/content-plan` for what comes after the product exists.
