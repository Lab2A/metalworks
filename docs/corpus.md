---
title: "Your corpus"
description: "What metalworks reads demand from — quotable conversations across three lanes and every buyer layer, plus where that data is saved and how to update an old report."
---

When metalworks runs research, it reads real demand and saves what it read. That saved
collection is **your corpus** (your research data). This page is the bigger picture first —
what the corpus *is* now — then the practical part: where it lives and how to update an old
report.

## What the corpus is

The corpus is the evidence the whole product rests on: every claim in a report, a positioning
wedge, or a launch line resolves back to a real quote in it. Three things make it more than a
pile of threads.

**It spans three lanes.** A source declares which lane it serves, and the lanes do different
jobs:

- **Grounding** — quotable records: a post, a comment, a Q&A answer, a job description, an
  issue. Each carries its real permalink and a pseudonymized author, so a downstream quote
  always traces back. This is the cite-or-die spine.
- **Magnitude** — an absolute number (downloads, installs, search volume) attached to a theme
  *after* clustering. It weights how a need ranks; it never creates a theme on its own.
- **Web** — the agentic discovery lane, which reaches the long tail (niche forums, blogs,
  community threads) without a per-venue connector, ingesting only verbatim citations.

**It spans every buyer layer.** The shipped catalog reaches from consumers (Reddit) through
developers (Hacker News, Stack Exchange, GitHub) to IT admins (WordPress, Discourse),
procurement (SAM.gov), and the exec/hiring layer (ATS job boards) — so a need isn't measured
from one crowd's voice alone. See the [live catalog](/docs/sources) for what's available and
reachable.

**It carries a demand-volume signal.** Beyond *how many distinct people* raised a need (the
breadth that drives the verdict), a magnitude overlay can attach *how big* a theme is — a
package's downloads, a search term's volume. That lifts a high-volume theme in the **ranking**,
but the GO / NO-GO **verdict band stays breadth-only**: a number can sharpen the sort order, it
can never manufacture a verdict. (See [How it works](/docs/how-it-works).)

To read from more sources, mix them per run or save your choices to config — see
[Sources](/docs/sources). To add a source of your own, see [Build a source](/docs/build-sources).

## Where it's saved

Inside a [project](/docs/projects), your research data is a single file:
`.metalworks/corpus.db`. Everything you read — the posts, the comments — lives there, and it
stays between runs, so your collection grows as you do more research.

It's kept out of git on purpose: it's your raw research data, and you should decide whether and
where it goes. Your reports (the summaries you'd actually share) *are* saved to git; the raw
data isn't.

If you're not in a project, metalworks keeps the data in memory for the run and writes nothing
to disk.

## Growing it

Every `mw.research(...)` saves what it read automatically — you never have to load anything
first. You can also add to your collection directly, which is useful for building up evidence
over time or across [sources](/docs/sources):

```bash
metalworks corpus add --source hackernews -q "rust developer tooling"
metalworks corpus add --source reddit    -q "rust developer tooling"
metalworks corpus sync     # fetch the latest for the sources you have on
metalworks corpus stats    # how much you've collected, by source
```

Adding the same thing twice is safe — nothing gets duplicated. The next report you run reads
everything you've collected.

## Updating an old report

A report reflects what you'd read at the time. After you've collected more, you can **update**
a report instead of starting over — metalworks re-runs it against everything you have now and
shows you what changed:

```bash
metalworks research run --question "rust developer tooling"   # your first report
metalworks corpus add --source hackernews -q "rust developer tooling"
metalworks research refresh <report-id>     # an updated report + what changed
metalworks research versions <report-id>    # every version of this report
metalworks research diff <id-a> <id-b>      # compare any two versions
```

In Python:

```python
research, changes = mw.refresh(prior_research)
print(changes.summary)        # e.g. "2 new needs, 3 grew, 180 more conversations"
```

Updating never overwrites the old version — each one is kept exactly as it was, so a report you
already shared or shipped against still reads the same. You just get a new version next to it.

### What "what changed" tells you

The comparison has two parts:

- **The numbers** — how many more conversations and distinct people showed up, and which needs
  appeared or faded. These are exact.
- **The needs** — which demand themes are new, gone, or moved. Because the analysis is written
  fresh each time, the wording of a need can shift slightly between runs even when it's the same
  underlying thing; the numbers are the reliable part. Re-running on the exact same data shows
  no change.

## Next

- [Sources](/docs/sources) — the live catalog of where the data comes from.
- [Build a source](/docs/build-sources) — add a grounding, magnitude, or discovery source.
- [Projects](/docs/projects) — the `.metalworks/` folder this lives in.
- [Use your own data](/docs/custom-corpus) — load conversations you already have.
