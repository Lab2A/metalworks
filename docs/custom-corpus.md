---
title: "Use your own data"
description: "Run research over data you already have: add a source for anything new, or implement CorpusReader and CommentSource to use your own Reddit data."
---

metalworks can run research over data you already have. Which path you use depends
on what that data is:

- **Not Reddit** (a forum, a reviews API, an internal dataset) → write a
  **source**. You map your items to the standard shape and they work like any
  built-in source. See [Build a source](/docs/build-sources).
- **Reddit data from somewhere other than the public archive** (local files, your
  own database, a cache) → implement **`CorpusReader`** and **`CommentSource`**,
  two small interfaces that hand metalworks raw post and comment rows. That's this
  page.

The `reddit` source normally reads from a public Reddit archive. Implement these
two interfaces and it reads from your data instead.

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

That's all you change — the rest of the pipeline (triage, synthesis, web,
triangulation) works exactly the same.

## Comments are optional

If you have submissions but no comment source, pass `comments=None` (the default
when offline). The pipeline marks the report `partial` with a caveat rather than
failing. Cluster quotes come from comments, so a comments-less run produces
submission-level signal only.

## Fully offline

Point a local reader at committed parquet and use fake models and an in-memory
store, and the whole pipeline runs with no network. This is the pattern for
tests and air-gapped runs.

## Data that isn't Reddit

For anything that isn't Reddit (a forum, reviews, your own dataset), don't use
`CorpusReader` — [build a source](/docs/build-sources) instead. You map your items
to the standard shape and they work like any built-in source. There are three lanes
to pick from: a **grounding** connector that yields quotable records, a **magnitude**
provider that attaches a number (downloads, search volume) to a theme, or an agentic
**discovery** provider that reaches the long tail.
