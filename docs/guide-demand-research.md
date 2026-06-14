---
title: "Demand Research guide"
description: "From a question to a grounded demand report — the research vertical end to end, simple to advanced."
---

The research vertical answers one kind of question: *is there real demand for
this, and what do people actually say?* It pulls real Reddit conversations,
triages them for relevance, clusters the signal, triangulates against the web,
and returns a `DemandReport` whose every quote is exact-matched to a real comment.

## The simplest call

```python
from metalworks import Metalworks

mw = Metalworks()                       # provider from your env key
research = mw.research(
    "Is there demand for a focus supplement aimed at developers?",
    subreddits=["Nootropics", "Supplements"],
)
report = research.demand                # .research() bundles the report on .demand
```

What you get back:

```python
report.verdict                 # synthesized go / no-go summary (str | None)
report.ranked_clusters         # themes, ranked by distinct-author breadth
report.web_findings            # web findings with real source URLs
report.partial, report.caveat  # set when a best-effort stage degraded
```

Each cluster is honest about its base rate:

```python
for c in report.ranked_clusters:
    print(c.rank, c.signal, f"{c.distinct_author_count} authors", c.claim)
    for q in c.quotes:                 # verified, exact-matched quotes
        print("   ", q.permalink, "→", q.text[:80])
```

## Let the planner shape the brief

`.research(question)` builds a minimal brief. For a richer brief — refined
question, success criteria, must-address sub-questions, suggested subreddits —
walk the planner:

```python
brief = mw.plan("Should I build a focus-supplement brand for developers?")
report = mw.research(brief).demand      # pass the brief straight back
```

Or build a `ResearchBrief` by hand for full control over every field (see
[Core concepts](/docs/concepts)).

## Scope the corpus

```python
mw.research("...", subreddits=["Nootropics"], time_window_months=6, per_sub_limit=500)
```

- `time_window_months` — how far back to pull (default 12; the bundled `demo()`
  corpus is a single month).
- `per_sub_limit` — cap submissions pulled per subreddit.
- `max_findings` — cap web findings.

Submissions come from the Hugging Face Arctic mirror; comments from the live
Arctic Shift API. Set `HF_TOKEN` for windows beyond a few months. To read the
submission corpus from a Supabase Storage bucket instead (no HF runtime
dependency), install `metalworks[supabase]` and set `ARCTIC_SHIFT_SOURCE=mirror`.
To run without Arctic Shift at all, [bring your own corpus](/docs/how-to-custom-corpus).

## Provenance, by construction

The report can't contain fabricated evidence:

- **Quotes** are exact-matched against stored comments; a quote that doesn't
  match a real comment is dropped (`no-quote-no-theme`).
- **Web findings** carry their `source_url` from the grounding tool's citation
  metadata — zero citations means the finding is dropped; URLs are never
  synthesized.
- **Counts** (distinct authors, mentions, must-address resolution) are computed
  from membership, never asserted by a model.

## Compose the stages yourself

`run_research` is one assembly of public stages. To build a custom flow — your
own triage thresholds, a different corpus, an extra synthesis pass — call them
directly:

```python
from metalworks.research import (
    run_exploration_triage, hydrate_submissions, synthesize,
    web_research, triangulate,
)
```

See [Building blocks](/docs/building-blocks) for the full list and signatures.

## Web grounding

When your chat model supports native grounding (Gemini `google_search`, Anthropic
`web_search`), the web stream uses it and maps findings to citations by character
span. Otherwise it falls back to an external `SearchProvider` (Exa, Tavily) — set
`EXA_API_KEY` or `TAVILY_API_KEY` and metalworks picks it up. With neither, the
report notes the web stream degraded and continues.
