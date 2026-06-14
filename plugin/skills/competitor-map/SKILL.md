---
name: competitor-map
description: Map the competitive landscape for a finished demand report — direct rivals, adjacent alternatives, and the status-quo "do nothing" option — with each competitor's strengths and an exploitable gap backed by a real cited complaint. Use after a demand report exists and the user asks "who are the competitors", "what's the competitive landscape", "where are the gaps", "what do rivals miss", or wants a competitor table that links to actual customer complaints rather than generic feature grids.
---

You are mapping the real competitive set for one idea, and — unlike every generic
competitor-table tool — every gap you surface points to a real complaint a real
person wrote. No clickthrough to a quote, no gap.

## Steps

1. Get the `report_id`. No report yet → run `/demand-report` first; the map
   stands on the report's clusters and quotes.

2. Call the `competitor_map_from_report` MCP tool with the `report_id` (or, on
   the CLI, `metalworks competitor-map <report_id>`). It enumerates competitors
   with web grounding, harvests strengths + gaps, and matches each gap against
   the report's real complaints.

3. Present the map honestly:
   - **Lead with the status-quo alternative** ("doing nothing"). Its gaps are the
     report's strongest pains, each backed verbatim by a real quote — that's the
     true incumbent any product must beat.
   - For each competitor: name, kind (direct / adjacent), one-liner, its
     strengths, then each **gap** with its **severity** and the cited evidence.
     Resolve each gap's `EvidenceRef` and show the permalink.
   - A competitor with no evidenced gaps still appears (it's real) — just say its
     gaps didn't match a complaint in this corpus.

4. If `partial` is true, lead with the `caveat`. The common case: enumeration ran
   ungrounded (no web grounding), so the named set is unverified — say so; the
   status-quo and cluster-matched gaps are still evidence-backed.

## Rules

- **No-quote-no-gap.** Every gap shown carries one resolvable citation
  (a verbatim complaint or a grounded web finding). Never present an
  uncited gap as fact.
- **Severity is computed, not claimed** — it comes from how many distinct people
  voiced the matched complaint, not from the model's opinion. Don't inflate it.
- The status-quo alternative is mandatory and the most important row — never drop it.
- This skill only maps the landscape. It does not position (that's
  `/position-wedge`) or build. Offer the next step once the user has the map.
