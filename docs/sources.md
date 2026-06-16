---
title: "Sources"
description: "Choose where metalworks reads from — Reddit, Hacker News, the web, or your own data. Turn sources on or off, mix several at once, or plug in your own."
---

**A source is where metalworks reads conversations.** Out of the box it can read from Reddit,
Hacker News, and the web; you can also plug in your own. Read from more than one and you get
more evidence behind every report.

## What's available

| Name | Reads | Needs a key? |
| --- | --- | --- |
| `reddit` | Public Reddit posts and comments | No |
| `hackernews` | Hacker News stories and comments (live) | No |
| `hackernews_archive` | A large archive of past Hacker News, read offline — see [Use Hacker News offline](/docs/load-hn-corpus) | No |
| `web` | Web pages from a search engine (Exa, Tavily, parallel.ai, or Firecrawl) | A search key |
| `producthunt` | Product Hunt launches + their comments | A free developer token |
| `arctic` | A large archive of past Reddit posts — see [Use Reddit's archive](/docs/load-reddit-corpus) | No |

**Product Hunt** is launches and the discussion around them — strongest for sizing up the
*competitive landscape* (what already exists and how it landed), a complement to the
unmet-need signal on Reddit and Hacker News. It needs a free, non-expiring **developer token**
from the [Product Hunt API dashboard](https://api.producthunt.com/v2/docs); set it as
`PRODUCT_HUNT_TOKEN`. Product Hunt has no keyword search, so the source pulls the top launches
(by votes) in your time window and lets the relevance step filter them.

## Pick what to read from

By default metalworks reads Reddit. To use others, name them when you run:

```bash
# read both Reddit and Hacker News for this run
metalworks research run --question "..." --source reddit --source hackernews

# see what's available and reachable
metalworks sources list

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
shape. To add one, copy `research/sources/template.py` and fill in three methods:

```python
from collections.abc import Iterator, Sequence
from metalworks.contract import CorpusComment, CorpusRecord
from metalworks.research.sources import SourceWindow, register_source


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


register_source("mysource", lambda **_: MySource())
```

Once registered, it works like any built-in: `--source mysource`, `get_source("mysource")`, or
`Metalworks(sources=[MySource()])`.

**If your source has no comments** (a web page, a product listing), return `None` from
`comments_for` and add `yields_units = True` to the class. metalworks then treats each item's
own text as the thing people are talking about.

To check your source is wired up correctly, use `metalworks.testing.check_item_source` in your
tests.

## Next

- [Your research data](/docs/corpus) — where what you read is saved, and how to update a
  report later.
- [Demand research](/docs/demand-research) — run a report.
- [Use your own data](/docs/custom-corpus) — load conversations you already have.
