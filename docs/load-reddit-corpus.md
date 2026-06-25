---
title: "Use Reddit's archive offline"
description: "Download the slice of Reddit you care about to your machine, so research runs fast and offline instead of fetching over the network."
---

The `reddit` source normally fetches posts from a large public Reddit archive
(called Arctic Shift) over the network, which can be slow and rate-limited. If you
want research to run **fast or fully offline**, download the slice you care about
once with a small script, then point metalworks at the local copy.

**Is this for you?** Use it if you'll run research repeatedly over the same
subreddits, need to work offline, or want to pin exactly what a run sees. The
tradeoff: a local copy is a snapshot — it won't include new posts until you
re-download. For a one-off run, you don't need this; just use the `reddit` source.

The script is
[`scripts/load_arctic_corpus.py`](https://github.com/Lab2A/metalworks/blob/main/scripts/load_arctic_corpus.py)
in the repo. It's standalone (standard library plus `duckdb`), so you can also
adapt it for a different archive.

## Install

```bash
pip install "metalworks[arctic]"
```

This includes `duckdb`, which the script uses to read the archive.

## Download a slice

```bash
python scripts/load_arctic_corpus.py --subreddit Supplements --months 3 --out ./corpus
```

| Flag | Meaning |
| --- | --- |
| `--subreddit, -s NAME` | Subreddit to pull. Repeatable: `-s Supplements -s Nootropics`. |
| `--months, -m INT` | How many months back to pull, ending at the latest available month (default `1`). |
| `--out, -o PATH` | Where to write the corpus (default `./corpus`). |
| `--comments` | Also fetch the comment threads for those posts. |
| `--limit INT` | Max posts per subreddit-month (default: no limit). |
| `--hf-token TOKEN` | Access token for the archive, if you have one (optional). |

Run `python scripts/load_arctic_corpus.py --help` for the full list.

## What you get

A folder with one Parquet file per subreddit and month (and comments alongside, if
you asked for them):

```
corpus/
  submissions/
    2026/
      04/Supplements.parquet
      05/Supplements.parquet
      06/Supplements.parquet
  comments/                       # only with --comments
    2026/
      06/Supplements.jsonl
```

## Point metalworks at it

```python
from metalworks import Metalworks
from metalworks.research.arctic import ArcticReader

mw = Metalworks(reader=ArcticReader(data_root="./corpus"))
mw.research(
    "a focus supplement without the jitters",
    subreddits=["Supplements"],
)
```

Everything else works the same. If you didn't download comments, the report comes
back marked `partial` and uses the posts alone (your quotes come from comments, so
they'll be thinner) — see
[Comments are optional](/docs/custom-corpus#comments-are-optional).

## Other data

This script is just for Reddit. To run research over something else — your own
database, an internal API, a forum — [build a source](/docs/build-sources)
or implement [`CorpusReader`](/docs/custom-corpus) for non-archive Reddit data.
