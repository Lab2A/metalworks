---
name: market-landscape
description: Map the full "what exists today" for a finished demand report — the competitor map (direct rivals, adjacent alternatives, and the status-quo "do nothing" cost, each gap backed by a real cited complaint) PLUS an empirical existing-solutions scan of real shipped products (Product Hunt launches and web), each matched to a demand cluster with its traction. Use after a demand report exists and the user asks "what already exists", "what's the market landscape", "what's been built for this", "who's shipping in this space", or wants the supply side (what people can get today) to weigh against the demand side. This is the surface a GO/PIVOT/NO-GO assessment reads.
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

You are mapping the full supply side for one idea — not just the named rivals, but the
real products people can already get today — so the demand can be weighed against what
exists. Unlike a generic competitor grid, every gap points to a real complaint and every
listed product is matched to a real demand cluster.

## Steps

1. Get the `report_id`. No report yet → run `/demand-report` first; the landscape stands
   on the report's clusters and quotes.

2. Call the `landscape_from_report` MCP tool with the `report_id` (or, on the CLI,
   `metalworks research landscape <report_id>`). It runs the grounded competitor map AND
   pulls real shipped products (Product Hunt by default), keeping only those that map to a
   demand cluster.

3. Present the landscape honestly, in two parts:
   - **Competitors** — lead with the status-quo "doing nothing" alternative (its gaps are
     the report's strongest pains, each backed verbatim); then each competitor with its
     strengths and **cited** gaps (severity is computed from how many people voiced the
     complaint). Resolve each gap's `EvidenceRef` and show the permalink.
   - **Existing solutions** — the real products already shipped, each with its traction
     (e.g. Product Hunt votes) and the demand cluster it addresses. These are empirical,
     not enumerated — a product only appears if its pitch matched a real cluster.

4. If `partial` is true, lead with the `caveat`. Two honest cases: competitor enumeration
   ran ungrounded (named set unverified), or the existing-solutions scan was unavailable
   (no product source / token) — in which case competitors + the status-quo still hold.

## Rules

- **No-quote-no-gap** and **no-cluster-no-solution.** Every gap carries one resolvable
  citation; every existing solution maps to a real demand cluster. Never present an uncited
  gap or an unmatched product as fact.
- **Severity and traction are computed, not claimed** — severity from distinct-author
  breadth, traction from the source's own signal. Don't inflate either.
- The status-quo alternative is mandatory and the most important competitor row — never drop it.
- Not to be confused with `metalworks discovery` (Reddit reply-opportunity discovery) — a
  different subsystem entirely.
- This skill only maps the landscape. It does not decide GO/PIVOT/NO-GO (that's the
  assessment step) or position. Offer the next step once the user has the landscape.
