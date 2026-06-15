---
title: "Sources"
description: "metalworks reads from many sources, not just Reddit. Each is an ItemSource connector that ingests into one shared corpus — Reddit, Hacker News, web search, or your own. Choose what to read from, or bring your own."
---

**metalworks reads from many sources, not just Reddit.** Reddit is one first-class
source among several; the signal compounds as you add more. Every source is an
`ItemSource` connector that pulls source-neutral records into one shared
[corpus](/docs/corpus), and synthesis runs over the whole corpus — so a report
can draw on Reddit threads, Hacker News discussions, and web pages at once.

## Shipped connectors

| Source id | What it reads | Key needed |
| --- | --- | --- |
| `reddit` | Live public Reddit submissions + comments | none |
| `arctic` | Reddit historical archive (Arctic Shift) — see [Load a Reddit corpus](/docs/load-reddit-corpus) | none |
| `hackernews` | Hacker News stories + comments (Algolia API) | none |
| `web` | Web pages from a search provider (Exa / Tavily / parallel.ai / Firecrawl) | a search key |

All of them land in the same shape, so a report over a mixed corpus ranks them
comparably — see [flat priority](#flat-priority-and-breadth) below.

## Choosing your sources

Three ways, in increasing permanence:

```bash
# One run, ad hoc — override the sources for this run only:
metalworks research run --question "..." --source reddit --source hackernews

# List what's registered and reachable:
metalworks sources list

# Turn sources on/off persistently (writes the [sources] config table):
metalworks sources enable hackernews
metalworks sources disable arctic
```

In Python, pass the connectors directly:

```python
from metalworks import Metalworks
from metalworks.research.sources import get_source

mw = Metalworks(sources=[get_source("reddit"), get_source("hackernews")])
report = mw.research("an affordable, jitter-free focus supplement").demand
```

With no override, metalworks uses your configured `[sources]` (and falls back to
Reddit). Whatever you pick, a single `mw.research(...)` call still works end to
end on an empty corpus — it ingests the chosen sources on demand, then
synthesizes. The corpus it builds up is durable and reused next time; see
[the corpus](/docs/corpus).

## Flat priority and breadth

Adding web (or any source) **promotes** it to a peer — it does not weight it above
the others. Every source ingests into one corpus and synthesis is
source-agnostic. The one per-source difference is how a cluster's **breadth** is
measured, so sources stay comparable instead of one drowning out another:

- Authored sources (Reddit, Hacker News): breadth = **distinct authors**.
- Authorless web: breadth = **distinct domains**.
- Mixed clusters: the two are summed (`breadth_unit` becomes `"voices"`).

Breadth — not raw engagement — drives a cluster's `demand_score`, so fifty
quiet voices outrank one viral post, and an authorless web hit never scores zero
just for lacking an author. A cluster carries both `distinct_author_count`
(authored voices only) and `breadth_count` / `breadth_unit` for the honest,
source-neutral count.

## Bring your own source

A connector is small. Copy `research/sources/template.py` and implement the
`ItemSource` protocol:

```python
from collections.abc import Iterator, Sequence
from metalworks.contract import CorpusComment, CorpusRecord
from metalworks.research.sources import SourceWindow, register_source


class MySource:
    source_id = "mysource"

    def pull(
        self, *, query: str, window: SourceWindow, limit: int | None = None
    ) -> Iterator[CorpusRecord]:
        # Map your API's items onto the corpus spine.
        ...

    def comments_for(
        self, record_ids: Sequence[str]
    ) -> Iterator[list[CorpusComment]] | None:
        # Return one batch per id, or None if your source has no comment layer.
        ...

    def latest_window(self) -> SourceWindow:
        ...


register_source("mysource", lambda **_: MySource())
```

Then it's selectable like any built-in: `--source mysource`,
`get_source("mysource")`, or `Metalworks(sources=[MySource()])`.

**No comment layer?** Some sources (web pages, link-only feeds) have no comment
thread — the record's own text is the signal. Return `None` from `comments_for`
**and** set the class attribute `yields_units = True`. metalworks then treats
each record as its own synthesis unit and ranks it on domain breadth. This is an
explicit opt-in: a comment-bearing source whose comment client merely isn't wired
also returns `None`, but is not a unit source.

A conformance check (`metalworks.testing.check_item_source`) verifies your
connector satisfies the protocol — wire it into your tests.

## Next

- [The corpus](/docs/corpus) — the durable store your sources feed, and live,
  refreshable reports over it.
- [Demand research](/docs/demand-research) — run a report over your sources.
- [Bring your own corpus](/docs/custom-corpus) — load data directly without a
  connector.
