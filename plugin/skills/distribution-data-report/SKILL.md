---
name: distribution-data-report
description: Turn a finished demand report into a corpus-derived data report — the on-brand flagship asset metalworks can uniquely generate. A deterministic ranking of the report's real clusters (a complaint index, a feature ranking, or a "State of X"), every row carrying the cluster's REAL distinct-author / mention counts, real Reddit permalinks, and a verbatim quote, with a disclosed methodology. Use after a demand report exists and the user asks "make me a data report", "build a complaint index", "rank the top complaints/features", "give me a State of X report", "what original research can I publish", or wants a shareable, citable data asset grounded in real Reddit discussion rather than a fabricated survey. The numbers are copied from the corpus, never invented — rigor IS the credibility.
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

You are turning one demand report into a **data report** — the data-as-marketing
flagship asset. It stacks every AI-citation driver at once: original research +
a ranking (the top AI-cited format) + verbatim quotes + permalinks, over a
proprietary Reddit corpus (the #1 AI-cited domain). The defensibility is the
corpus others can't reproduce; the credibility is the disclosed method. You are
NOT writing a marketing puff piece — every number traces to the corpus, and the
survey-fabrication base rate is the exact trap to avoid.

## Steps

1. Get the `report_id`. If the user hasn't run a report yet, point them at
   `/demand-report` first — a data report projects an existing report's clusters,
   so it needs a finished one to rank.

2. Pick the `kind` from what the user wants:
   - `complaint_index` — each row is a **pain point** consumers raised (default).
   - `feature_ranking` — each row is a **feature / capability** consumers asked for.
   - `state_of` — each row is a **theme** of the overall state of the category.

3. Call the `distribution_data_report` MCP tool with the `report_id` + `kind`
   (or, on the CLI, run `metalworks distribution data-report <report_id> --kind
   <kind>`). It projects the report's `ranked_clusters` deterministically and does
   one LLM call for the title + per-row labels, returning a `DataReportAsset`.

4. Present it as publishable research:
   - Lead with the **title** and the **methodology** line — the disclosed honest
     base (N threads analyzed, distinct-author counting, the date range). Say the
     method out loud; the rigor is the credibility.
   - Walk the ranked **items**. For each row, give the **rank** + **label**, then
     the REAL **distinct_authors** / **mentions** counts (distinct authors is the
     honest base rate; mentions is total raised — keep them separate), the
     verbatim **quote**, and the **permalinks** to the real threads.

## Rules

- The ranking and the numbers are **deterministic and real** — `rank`,
  `distinct_authors`, and `mentions` are copied straight from the report's
  clusters; `permalinks` are the real `source_url`s; `quote` is verbatim. NEVER
  invent, round, or extrapolate a number, and never paraphrase a quote. If the
  report didn't measure it, it isn't in the report.
- The LLM writes only the **title** and each row's **label** — and only grounded
  in that cluster's claim. A label may not introduce a complaint or feature the
  claim doesn't support.
- **Disclose the method.** Always surface the `methodology` — the count, the
  distinct-author method, the date range. A data report without its method reads
  like a fabricated survey, which is the one thing that destroys its credibility.
- This skill only generates the asset. It does not publish or pitch it — once it
  ships, the human decides where to place it (a niche outlet, a blog, an X
  thread). Data reports take ~3 months to first citation; methodology rigor is
  what earns it.
