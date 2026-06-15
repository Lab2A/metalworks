---
title: "Your research data"
description: "Where metalworks saves the conversations it reads, how that collection grows as you run more research, and how to update an old report to see what changed."
---

When metalworks runs research, it saves the conversations it read. That saved collection is
**your research data** (metalworks calls it your *corpus*). This page answers three questions:
where is it, does it stick around, and can you update an old report later.

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

- [Sources](/docs/sources) — where the data comes from.
- [Projects](/docs/projects) — the `.metalworks/` folder this lives in.
- [Use your own data](/docs/custom-corpus) — load conversations you already have.
