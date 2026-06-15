---
title: "Use your own corpus"
description: "Feed research from your own data: write an ItemSource for a new source, or implement CorpusReader / CommentSource to swap the Reddit archive backend."
---

There are two ways to feed research from your own data, depending on what you have:

- **A new source** (a forum, a reviews API, an internal dataset, anything not
  Reddit-shaped) → write an **`ItemSource`** connector. It's the modern,
  source-neutral path: you map your items onto `CorpusRecord` / `CorpusComment`
  and they ingest into the shared corpus alongside Reddit, Hacker News, and the
  web. See [Sources → bring your own source](/docs/sources#bring-your-own-source).
- **Your own Reddit data** (local parquet, a database, a cache instead of the
  Arctic Shift archive) → implement **`CorpusReader`** + **`CommentSource`**, the
  Reddit-archive backend seam covered below.

This page covers the second path. Arctic Shift is the default Reddit backend, not
a requirement — once those two small protocols are satisfied, the `reddit` /
`arctic` connectors read from your data instead.

## The protocols

```python
from collections.abc import Iterator, Sequence
from typing import Any
from metalworks.research.deps import CorpusReader, CommentSource, MonthRef

class MyReader:                                    # satisfies CorpusReader
    def latest_available_month(self, content_type: str = "submissions") -> MonthRef: ...
    def pull_subreddit(self, *, subreddit: str, content_type: str,
                       months: Sequence[MonthRef], select_cols: Sequence[str] | None = None,
                       limit: int | None = None) -> Iterator[dict[str, Any]]: ...
    def fetch_submissions_by_ids(self, post_ids: Sequence[str],
                                 months: Sequence[MonthRef]) -> Iterator[dict[str, Any]]: ...
    def close(self) -> None: ...

class MyComments:                                  # satisfies CommentSource
    def comments_for_links(self, link_ids: Sequence[str]) -> Iterator[list[dict[str, Any]]]: ...
```

Both yield plain dicts (post / comment rows), so there is no Reddit-specific type
to import. The pipeline hydrates those dicts into `RedditPost` / `RedditComment`
and writes them to your store.

## Wire it in

```python
from metalworks import Metalworks

mw = Metalworks(reader=MyReader(), comments=MyComments())
mw.research("...", subreddits=["..."])
```

That's the whole "no Arctic Shift" story — the rest of the pipeline (triage,
synthesis, web, triangulation) is unchanged.

## Comments are optional

If you have submissions but no comment source, pass `comments=None` (the default
when offline). The pipeline marks the report `partial` with a caveat rather than
failing. Cluster quotes come from comments, so a comments-less run produces
submission-level signal only.

## Fully offline

Point a local reader at committed parquet and use fake models and an in-memory
store, and the whole pipeline runs with no network. This is the pattern for
tests and air-gapped runs.

## Arbitrary, non-Reddit data

If your data isn't Reddit-shaped, don't use `CorpusReader` — write an
[`ItemSource`](/docs/sources#bring-your-own-source) instead. It maps any items
onto the source-neutral `CorpusRecord` / `CorpusComment` spine, so they ingest,
triage, cluster, and rank exactly like every built-in source. That's the
shipped path for a true non-Reddit corpus.
