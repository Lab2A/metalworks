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

## Read your local slice

To search the slice you just downloaded, point a `HackerNewsArchiveReader` at the
output directory and wrap it in a `HackerNewsArchiveSource`. The source matches stories
to your query by keyword and reads each story's full comment thread straight from the
same Parquet files — so your quotes come from real HN comments with nothing fetched live:

```python
from metalworks.research.sources.hn_archive import (
    HackerNewsArchiveReader,
    HackerNewsArchiveSource,
)

source = HackerNewsArchiveSource(reader=HackerNewsArchiveReader(data_root="./hn-corpus"))

window = source.latest_window()
stories = list(source.pull(query="a budget mechanical keyboard for programmers", window=window))
for story in stories:
    print(story.title, story.url)

# comments_for takes a batch of story ids and yields one comment list per id
for thread in source.comments_for([s.id for s in stories]) or []:
    for comment in thread:
        print("  ", comment.text[:80])
```

<Note>
The HN archive is a corpus connector, not yet a one-line `Metalworks(...)` option.
`Metalworks` does **not** take a `sources=` constructor argument — passing one raises
`TypeError`. Wiring a custom source into the full `mw.research(...)` pipeline by config
(a `[sources]` stream) is planned but not yet plumbed; today you drive the archive through
the source object above, or via the CLI below.
</Note>

## From the CLI

The `hackernews_archive` source self-registers under the `--source` flag, so the CLI can
ingest it into your local corpus store (`metalworks corpus add`) or run a report against it
(`metalworks research run --source hackernews_archive`):

```bash
metalworks corpus add --source hackernews_archive --query "mechanical keyboards" --months 1
```

The CLI path reads from the archive's default data root (the public HF mirror), or from a
Supabase mirror when `HN_ARCHIVE_SOURCE=mirror` is set (below). To search a custom **local**
`--out` directory like `./hn-corpus`, construct the reader with `data_root=` as shown above —
the `--source` flag doesn't take a local path yet.

## Read from a Supabase mirror

For a shared, always-available copy (instead of a local download on each machine),
you can mirror the months you want into a private Supabase Storage bucket and read
them over signed URLs — no HF and no local files at query time. Use a
`HackerNewsArchiveMirrorReader` (needs the `supabase` extra):

```python
from metalworks.research.sources.hn_archive import (
    HackerNewsArchiveMirrorReader,
    HackerNewsArchiveSource,
)

# reads months tracked in a `hackernews_pulls` table + shards under <YYYY>/<MM>/
reader = HackerNewsArchiveMirrorReader()   # SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY from env
source = HackerNewsArchiveSource(reader=reader)
```

Or set `HN_ARCHIVE_SOURCE=mirror` in the environment and `--source hackernews_archive`
resolves to the mirror automatically. This mirrors how Reddit's Supabase tier works.

## Other sources

This is one of several [sources](/docs/sources) you can read from. For Reddit's archive, see
[Use Reddit's archive offline](/docs/load-reddit-corpus); to plug in something else, [add your
own source](/docs/sources#add-your-own-source).
