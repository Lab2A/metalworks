---
name: distribution-geo
description: Turn a finished demand report into the GEO / LLM-citability stream — the participation targets (the real Reddit threads/communities to engage, pulled from the report's own permalinks), the citability probes (the real conversational queries to test whether you're the cited answer, derived from the cluster claims), and the answer-first answer briefs (grounded, factual answers whose evidence resolves against the report and whose stat anchors carry real distinct-author / mention counts). Use after a demand report exists and the user asks "how do I get cited by AI", "how do I get cited by ChatGPT/Perplexity", "what's my GEO play", "which Reddit threads should I join", "how do I show up in answer engines", or wants a grounded plan to become the cited answer rather than generic SEO advice. Reddit is the #1 AI-cited domain; this names where to participate and what to say — DRAFTING ONLY, it never posts.
---

You are turning one demand report into its GEO / LLM-citability stream — the
compounding play to become the answer AI engines cite. Reddit is the #1 AI-cited
domain and most AI citations are Q&A threads, so the move is to participate in the
threads the audience is *already* asking in and to publish answer-first content
for the questions they ask. Every output traces to the report: participation
targets to real permalinks, probes + briefs to the real cluster claims, and each
answer brief to resolvable evidence. You are NOT inventing threads or keywords.

## Steps

1. Get the `report_id`. If the user hasn't run a report yet, point them at
   `/demand-report` first — GEO needs a finished report to ground on.

2. Call the `distribution_geo` MCP tool with the `report_id` (or, on the CLI, run
   `metalworks distribution geo <report_id>`). It returns a `GeoPlan` with three
   streams: deterministic `participation_targets` + `citability_probes`, and the
   grounded `answer_briefs`.

3. Read the plan honestly, in three parts:
   - **Participation targets** — the real threads to engage. Walk each one: the
     `community`, the real `permalink`, the `why` (what that audience is asking),
     and the `suggested_angle`. These are REAL threads from the report — never
     present an invented one.
   - **Citability probes** — the conversational queries to test whether you're
     cited. Each `prompt` is a real question the audience asks; its `target_phrase`
     is the cluster claim it traces to. Tell the user to run these against an
     answer engine (ChatGPT / Perplexity / Google AI) and check for a citation.
   - **Answer briefs** — the answer-first content to publish. For each: lead with
     the `question`, then the grounded `answer`, and call out the `stat_anchors`
     (the real distinct-author / mention counts) and that it carries
     `evidence_refs` resolving to real quotes.

4. Close with the honest read: GEO is a **compounding stream** — first citations
   take roughly three months, so this is a patient play, not a launch-day spike.

## Rules

- Participation targets use **real permalinks** from the report's verified quotes.
  If a thread isn't in the report, it isn't a target — never invent one.
- Citability probes come from the **cluster claims** — the real questions the
  audience asked — not templated keyword fluff.
- Answer briefs are **cite-or-die**: the answer is a factual claim, so every brief
  resolves against `report.evidence`. A brief whose evidence doesn't resolve is
  dropped before it ships — present only what survived, and never pad with
  unevidenced answers.
- Participate value-first: answer the question, disclose affiliation, never drop a
  bare link. This skill plans and drafts; it does **not** post anything.
