---
name: distribution-requirements
description: Turn a finished demand report's distribution channel plan into BUILD requirements — the embedded loops and the conversion surface that distribution designs INTO the product, emitted as concrete things the build must ship. For each selected embedded-loop channel (a watermark, UGC-SEO, referral, free-tool, OSS, or single-player loop) it maps the loop kind to its build requirements (watermark ⇒ public share-URLs + branded viewer + badge-gating; UGC-SEO ⇒ SSR public pages + sitemap; single-player ⇒ solo aha before invite), grounded in the channel's routing signal; and it always emits the conversion destination every channel points at (its funnel job + what it must ship). Use after a demand report exists and the user asks "what does distribution need the build to include", "what are the build requirements for my loops", "where do the channels convert", "what's the conversion surface", or wants the distribution→build feed before scaffolding. Feed the result into build-spec so the spec records it. DETERMINISTIC — no invented features.
---

## Preamble (run first)

Before any other tool, run the `preflight` MCP tool (or `metalworks preflight` on
the CLI). If it reports setup issues or that an update is available, surface that
to the user in one line and help them resolve it (install the missing extra/key,
or `pip install -U metalworks`) before continuing. Skip only if the user has
already passed preflight this session.

You are turning one demand report's distribution channel plan into the BUILD
requirements distribution implies. Embedded loops and the conversion surface are
designed INTO the product — they are not marketing tactics bolted on after the
fact — so the moment distribution selects them, the build must ship concrete
things to make them work. Notion's public-page SEO underperformed precisely
because the build lacked SSR + a sitemap; a watermark loop is worthless without a
branded public viewer and badge-gating. Every requirement traces to a real,
audience-derived channel — you are NOT inventing features.

## Steps

1. Get the `report_id`. If the user hasn't run a report yet, point them at
   `/demand-report` first — these requirements derive from the report's channel
   strategy, which needs a finished report to ground on.

2. Call the `distribution_requirements` MCP tool with the `report_id` (or, on the
   CLI, run `metalworks distribution requirements <report_id>`). It routes the
   report into its channel strategy (D2), then returns two lists:
   `loop_requirements` (one per selected embedded-loop channel) and
   `conversion_surface_requirements` (always one — the conversion destination).

3. Read the requirements honestly, in two parts:
   - **Embedded loops** — for each `LoopRequirement`: the `loop_kind` (watermark /
     ugc_seo / referral / free_tool / oss / single_player), the concrete
     `build_requirements` the build must ship, and the `rationale` (why, grounded
     in the channel's routing signal). If no embedded-loop channel was selected,
     there are no loop requirements — say so plainly, don't invent one.
   - **Conversion surface** — the `ConversionSurfaceRequirement`: the `destination`
     the channels point at, its `funnel_job`, the `build_requirements`, and the
     `rationale`. This is ALWAYS emitted: channels create attention, and attention
     with no surface to catch it leaks out, so the build must include a place to
     convert.

4. Tell the user to feed these into the build spec — `metalworks build` /
   `build_spec` accepts `distribution_requirements`, and the resulting `BuildSpec`
   records them on `loop_requirements` / `conversion_surface_requirements`. This is
   the distribution→build feed: strategy runs BEFORE the build, so the build ships
   the loop machinery + conversion destination from day one rather than discovering
   it's missing later.

## Rules

- The mapping `loop_kind` → `build_requirements` is DETERMINISTIC — a fixed table,
  not an LLM guess. Present what the tool returned; never embellish the
  requirement list.
- Each loop requirement's `rationale` traces to the channel's grounded
  `routing_signal`. If a loop isn't backed by a selected channel, it isn't a
  requirement — never invent one.
- The conversion surface is always emitted, even when the plan already converts —
  the framing of its `funnel_job` adapts (catch conversion-stage intent vs. plug
  the all-top-of-funnel leak), but a conversion destination is always a build
  requirement.
- This skill plans the build requirements; it does not write product code. Hand the
  requirements to `/build-spec` (or the user's own coding agent) to build against.
