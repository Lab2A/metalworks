---
title: "Use your own corpus (no Arctic Shift)"
description: "Run research over any Reddit data — local parquet, a database, a cache — by implementing CorpusReader and CommentSource."
---

Run research over any Reddit data in three steps: implement `CorpusReader` for
submissions, implement `CommentSource` for comments, and wire them in. Arctic
Shift is the default path, not a requirement — once those two small protocols are
satisfied, you can feed research from anything: local parquet, your own database,
an internal API, or a cache.

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
store, and the whole pipeline runs with no network — exactly what `Metalworks.demo()`
does internally. This is the pattern for tests and air-gapped runs.

> Heads up: a true *non-Reddit* corpus (arbitrary documents, no subreddits or
> permalinks) is a planned future seam — today the data *shape* is still
> Reddit-flavored even though the data *source* is fully swappable.
