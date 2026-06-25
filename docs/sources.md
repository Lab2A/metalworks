---
title: "Sources"
description: "Choose where metalworks reads from — Reddit, Hacker News, the web, or your own data. Turn sources on or off, mix several at once, or plug in your own."
---

<!-- GENERATED FILE — do not edit by hand.
     Source of truth: each connector's SourceSpec (metalworks.research.sources).
     Regenerate: python scripts/gen_sources_md.py -->

**A source is where metalworks reads conversations.** Out of the box it can read from Reddit,
Hacker News, and the web; you can also plug in your own. Read from more than one and you get
more evidence behind every report.

## What's available

| Name | Reads | Lane | Needs a key? | Env |
| --- | --- | --- | --- | --- |
| `arctic` | A large archive of past Reddit posts — see [Use Reddit's archive](/docs/load-reddit-corpus) | grounding | No | — |
| `ats` | Public company job boards (Greenhouse, Lever, Ashby) — the JD states the hiring need | grounding | No | — |
| `discourse` | Public Discourse community forums (vendor/product/practitioner boards) + their replies | grounding | No | — |
| `hackernews` | Hacker News stories and comments (live) | grounding | No | — |
| `hackernews_archive` | A large archive of past Hacker News, read offline — see [Use Hacker News offline](/docs/load-hn-corpus) | grounding | No | — |
| `hn_archive` | Alias of `hackernews_archive` (the offline Hacker News archive) | grounding | No | — |
| `producthunt` | Product Hunt launches + their comments | grounding | A free key | `PRODUCT_HUNT_TOKEN` |
| `reddit` | Public Reddit posts and comments | grounding | No | — |
| `samgov` | U.S. government procurement notices (SAM.gov) — explicit unmet needs with a budget | grounding | A free key | `SAM_GOV_API_KEY` |
| `stackexchange` | Stack Exchange Q&A across 170+ sites (Stack Overflow, Server Fault, DBA, …) | grounding | No | — |
| `web` | Web pages from a search engine (Exa, Tavily, parallel.ai, or Firecrawl) | web | A free key | `EXA_API_KEY`, `TAVILY_API_KEY`, `PARALLEL_API_KEY`, `FIRECRAWL_API_KEY` |

## Pick what to read from

By default metalworks reads Reddit. To use others, name them when you run:

```bash
# read both Reddit and Hacker News for this run
metalworks research run --question "..." --source reddit --source hackernews

# see what's available and reachable (lane / auth / key-status from each SourceSpec)
metalworks sources list

# only sources that need a key, or only one lane
metalworks sources list --needs-key
metalworks sources list --lane web

# turn a source on or off for good (saved to your config)
metalworks sources enable hackernews
metalworks sources disable arctic
```

In Python, pass the sources you want:

```python
from metalworks import Metalworks
from metalworks.research.sources import get_source

mw = Metalworks(sources=[get_source("reddit"), get_source("hackernews")])
report = mw.research("an affordable, jitter-free focus supplement").demand
```

You don't have to set anything up first — a single `mw.research(...)` reads the sources you
chose and produces a report in one call.

## How mixed sources are ranked

When a report draws on more than one source, a need is ranked by **how many different people
raised it** — not by how viral a single post was. Fifty people each mentioning a problem
once outranks one post with five hundred upvotes. Web pages (which have no author) count by
how many different sites raised the point. The upshot: no single source can drown out the
others.

## Add your own source

A source is a small piece of code that fetches items and hands them to metalworks in a common
shape. The fastest way in is to scaffold one:

```bash
metalworks sources scaffold mysource --lane grounding --auth none
```

That writes a connector module (with a filled `SourceSpec` and a `register_signal` block), a
conformance test, prints the `pyproject.toml` extra to add, and the `docs/sources.md` row.
Fill in the `pull` / `comments_for` bodies and you're done — see
[Adding a source connector](https://github.com/Lab2A/metalworks/blob/main/CONTRIBUTING.md) in
`CONTRIBUTING.md` for the worked example. To wire one up by hand instead, copy
`research/sources/template.py`:

```python
from collections.abc import Iterator, Sequence

from metalworks.contract import CorpusComment, CorpusRecord
from metalworks.research.sources import SourceSpec, SourceWindow, register_source


class MySource:
    source_id = "mysource"

    def pull(self, *, query, window, limit=None) -> Iterator[CorpusRecord]:
        # Fetch items and yield them as CorpusRecord (id, url, title, text, …).
        ...

    def comments_for(self, record_ids: Sequence[str]):
        # Return the comments under each item — or None if your source has no comments.
        ...

    def latest_window(self) -> SourceWindow:
        # The most recent time range your source can return.
        ...


register_source(
    "mysource",
    lambda **_: MySource(),
    spec=SourceSpec(
        source_id="mysource",
        lane="grounding",
        signals=("upvotes",),
        targeting="keyword",
        auth="none",
        env=(),
        access="open",
        relevance_hint="what this source is best at surfacing",
    ),
)
```

Once registered, it works like any built-in: `--source mysource`, `get_source("mysource")`, or
`Metalworks(sources=[MySource()])`.

**If your source has no comments** (a web page, a product listing), return `None` from
`comments_for` and add `yields_units = True` to the class. metalworks then treats each item's
own text as the thing people are talking about.

To check your source is wired up correctly, use `metalworks.testing.check_item_source` in your
tests (the scaffold writes one for you).

## Next

- [Your research data](/docs/corpus) — where what you read is saved, and how to update a
  report later.
- [Demand research](/docs/demand-research) — run a report.
- [Use your own data](/docs/custom-corpus) — load conversations you already have.
