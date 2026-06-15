---
title: "The corpus"
description: "The corpus is metalworks' durable core: a persistent, multi-source store of real conversations that grows across runs. Reports are live, versioned views over it — refresh a report against a bigger corpus and see exactly what changed."
---

**The corpus is the durable core of metalworks.** It's a persistent, multi-source
store of the real records and comments your [sources](/docs/sources) pull —
accumulated across runs, not thrown away after each one. A report is a **live
view** over the corpus, not a frozen artifact: grow the corpus, refresh the
report, and the picture sharpens. Power is in numbers.

## What's in it

Every source maps its items onto one source-neutral spine, so a Reddit post, a
Hacker News story, and a web page all land in the same shape:

- **`CorpusRecord`** — a top-level item: `id`, `source`, `source_id`, `url`,
  `title`, `text`, `author_hash`, `engagement`, `created_at`, and an open `extra`
  map for source-specific fields (subreddit, domain, rating, …).
- **`CorpusComment`** — a quote-bearing sub-item of a record (a reply, a thread
  comment), same spine plus a `parent_id`.
- **Embeddings** — one vector per record/comment id, used for triage and dedup,
  reused across runs.

The records and their comments are what citations resolve against: a quote in a
report carries the `record_id` it came from, so the chain runs from a line on
your landing page all the way back to the real comment.

## Where it lives

In a [project](/docs/projects) the corpus is `.metalworks/corpus.db` — a single
SQLite file that is the project's whole memory. It is **durable but gitignored**:
authoritative and meant to survive across runs, but never committed, because it
holds verbatim user text, salted author hashes, and embedding vectors. Outside a
project, metalworks keeps an in-memory corpus that leaves no footprint.

## Growing the corpus

A `mw.research(...)` run ingests its sources automatically — you never have to
seed the corpus first. But you can also grow it directly, which is how the signal
compounds across sources and over time:

```bash
metalworks corpus add --source hackernews -q "rust developer tooling" --limit 50
metalworks corpus add --source reddit -q "rust developer tooling"
metalworks corpus sync          # re-pull the latest window for enabled sources
metalworks corpus stats         # records + comments, broken down by source
```

Ingestion is idempotent — re-adding the same window upserts by id, so nothing
duplicates. The next report you run reads everything that's in there.

## Live, versioned reports

Because a report is a view, you can **refresh** it against the now-larger corpus.
Each refresh pins a new **version** in the same **lineage** and shows you a
**diff** of what moved:

```bash
metalworks research run --question "rust developer tooling"   # v1
metalworks corpus add --source hackernews -q "rust developer tooling"
metalworks research refresh <report-id>                       # v2 + a diff
metalworks research versions <report-id>                      # the lineage
metalworks research diff <id-a> <id-b>                        # any two versions
```

In Python:

```python
research, diff = mw.refresh(prior_research)
print(diff.summary)              # e.g. "+2 themes, 3 shifted, +180 threads"
```

The **prior version stays frozen** — its citations are materialized inline, so a
report you committed or shipped against still renders even if the corpus moves on.
"What did I ship against?" is never lost; refresh only ever appends a version.

### What the diff tells you

`ReportDiff` has two layers:

- **Deterministic (ground truth)** — thread, distinct-author, and cluster counts,
  and the source distribution, read straight off the two reports.
- **Advisory (claim-matched)** — themes added, faded, or shifted, matched across
  versions by claim-embedding nearest-neighbor. Synthesis is non-deterministic, so
  a theme's wording can drift between runs; the counts are exact, the wording diff
  is a hint. Diffing a report against an identical re-synthesis yields an empty
  diff — the refresh determinism guarantee.

## Next

- [Sources](/docs/sources) — the connectors that feed the corpus.
- [Projects](/docs/projects) — the `.metalworks/` directory the corpus lives in.
- [Bring your own corpus](/docs/custom-corpus) — load records directly.
- [Data model](/docs/data-model) — the full shape of records, citations, and the report.
