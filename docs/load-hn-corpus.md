---
title: "Use Hacker News offline"
description: "Read Hacker News in bulk from a local copy of the open-index/hacker-news archive — fast and fully offline, instead of fetching live."
---

metalworks reads Hacker News two ways. The `hackernews` source fetches live from the
public HN search API — keyless and always current, but one request at a time. The
**`hackernews_archive`** source reads the whole of HN (stories *and* comments,
2006→present) from a large public Parquet archive, so you can search across years at
once and run **fully offline**.

**Is this for you?** Use it if you want to search a lot of HN history, run offline, or
avoid hammering the live API. For a quick, current lookup, the live `hackernews` source
is simpler. The tradeoff: the archive is big, and a local copy is a snapshot — re-download
to pick up newer posts.

## Install

```bash
pip install "metalworks[arctic]"
```

This includes `duckdb`, which the reader uses. (The download script itself needs nothing
beyond the standard library.)

## Download a slice

Hacker News isn't split by topic, so one month is a single file covering the whole site —
recent months are hundreds of MB. Start with one month:

```bash
python scripts/load_hn_corpus.py --months 1 --out ./hn-corpus
```

| Flag | Meaning |
| --- | --- |
| `--months, -m INT` | How many months back to download, ending at the latest available (default `1`). |
| `--out, -o PATH` | Where to write the corpus (default `./hn-corpus`). |
| `--hf-token TOKEN` | Access token for the archive, if you have one (optional). |
| `--force` | Re-download months you already have. |

You can also read the archive **directly** with no download by leaving the data root at its
default — but a month is large to stream over the network on every run, so a local copy is
the fast path.

## What you get

One Parquet file per month, holding every story and comment for that month:

```
hn-corpus/
  2026/
    2026-06.parquet
    2026-05.parquet
```

## Point metalworks at it

```python
from metalworks import Metalworks
from metalworks.research.sources.hn_archive import (
    HackerNewsArchiveReader,
    HackerNewsArchiveSource,
)

reader = HackerNewsArchiveReader(data_root="./hn-corpus")
mw = Metalworks(sources=[HackerNewsArchiveSource(reader=reader)])
mw.research("a budget mechanical keyboard for programmers")
```

Stories are matched to your question by keyword; each story's full comment thread is read
straight from the same files, so your quotes come from real HN comments with nothing fetched
live.

## Other sources

This is one of several [sources](/docs/sources) you can read from. For Reddit's archive, see
[Use Reddit's archive offline](/docs/load-reddit-corpus); to plug in something else, [add your
own source](/docs/sources#add-your-own-source).
