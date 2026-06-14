---
name: surface-and-ux
description: Decide what product surface to build (sdk, web, mobile, cli, browser extension, ...) and sketch a 3-5 screen UX skeleton for a finished demand report — every decision traced to a real customer voice, not taste. Use after a demand report (and ideally positioning) exists and the user asks "should I build a web app or a CLI", "what surface should this be", "what screens do I need", "what's the MVP UX", or wants a build-shape recommendation grounded in who actually asked, rather than a generic web-app default.
---

You are deciding the product's SHAPE — which surface to build and the screens it
needs — grounded in what real people said. Unlike tools that default everything
to a web app and never cite who asked, every rubric dimension here either cites a
real voice or is openly marked an assumption. You ship text and structure, never
pixels.

## Steps

1. Get the `report_id`. No report yet → run `/demand-report` first; surface
   decisions stand on the report's audience, pains, and positioning.

2. Call `surface_recommend` (MCP) with the `report_id` — or on the CLI,
   `metalworks surface <report_id>` (which also builds the UX skeleton). It runs
   the fixed rubric, grounds each dimension, and recommends a surface + runner-up.

3. Present the recommendation honestly:
   - Lead with the **chosen surface** and **runner-up**, the one-line rationale,
     and the service-assigned **confidence**.
   - Walk the **rubric** (where-are-the-users, technical sophistication, usage
     frequency, realtime/hardware, distribution). For each: the finding, and
     whether it's **cited** (show the permalink) or an **assumption** (say so).
   - If `partial` / low confidence: lead with the caveat. Fewer than two grounded
     dimensions means the pick is a hypothesis — present it as one to test, not a
     verdict.

4. For the UX skeleton (`ux_skeleton_build` with the chosen surface, or already
   included by the CLI): list 3-5 screens with purpose + primary action. Mark
   each **validated** (a real voice backs it — show the permalink) or
   **hypothesis** (no backing voice). Never hide the unvalidated ones.

5. Aesthetics are out of scope here. Hand the `DesignBrief` to
   `/design-consultation` (or the project's `DESIGN.md`) — and say plainly it's
   craft convention, not an evidence-backed finding.

## Rules

- **Decisions ground; pixels don't.** The surface choice and screens trace to
  cited voices; the visual layer is explicitly ungrounded. Keep that line bright.
- **Cite or mark assumption** — never present an ungrounded rubric dimension or
  screen as validated. The confidence is computed from real coverage, not claimed.
- Text + structure only. This skill does not generate mockups, components, or CSS.
- A confident, ungrounded surface answer is the most dangerous output in the arc
  (it's a one-way door). On thin signal, say "low signal — treat as a hypothesis."
