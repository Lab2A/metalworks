---
title: "Build your own Reddit corpus"
description: "metalworks doesn't hinge on Arctic Shift. Pull your own local Reddit corpus with the load_arctic_corpus.py sample script, then point ArcticReader at it."
---

metalworks reads submissions through a small `CorpusReader` protocol — Arctic
Shift is the *default* implementation, not a requirement (see
[Use your own corpus](/docs/custom-corpus)). This guide takes the next step:
instead of letting the library reach out to the (slow, rate-limited) Hugging Face
mirror at runtime, you run a **sample loader script once** to materialize a local
Parquet corpus, then point metalworks at that directory.

The script lives at [`scripts/load_arctic_corpus.py`](https://github.com/) in the
repo. It is standalone — standard library plus `duckdb` only — so it doubles as a
copy-paste reference if you want to adapt it for a different mirror or source.

## Why build your own corpus

- **No runtime dependency on the HF mirror.** The mirror is convenient for a
  quick run but slow and rate-limited. A local corpus is fast and offline.
- **Reproducibility.** A committed corpus directory pins exactly what a run saw.
- **Control.** Pull only the subreddits and months you care about, once.

## Prerequisites

```bash
pip install "metalworks[arctic]"
```

That pulls in `duckdb`, which the script uses to read the mirror's Parquet shards
over `httpfs`. (The script will run with a bare `pip install duckdb` too, but
you'll want the full extra to point metalworks at the result.)

## Pull a corpus

```bash
python scripts/load_arctic_corpus.py --subreddit Supplements --months 3 --out ./corpus
```

| Flag | Meaning |
| --- | --- |
| `--subreddit, -s NAME` | Subreddit to pull. Repeatable: `-s Supplements -s Nootropics`. |
| `--months, -m INT` | How many months back to pull, ending at the latest available month (default `1`). |
| `--out, -o PATH` | Output corpus root (default `./corpus`). |
| `--comments` | Also fetch live comment trees for pulled submissions (Arctic Shift API). |
| `--limit INT` | Max submissions per subreddit-month (default: no limit). |
| `--hf-token TOKEN` | Hugging Face token for authenticated mirror reads (optional). |

Run `python scripts/load_arctic_corpus.py --help` for the full list.

## What it produces

The script writes a directory laid out exactly how `ArcticReader` globs for
shards:

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

Submissions are real Parquet (one file per subreddit-month). Empty months are
skipped — no stray files. Comments, when fetched, land as JSONL next to the
submissions for the same month.

## Point metalworks at it

`ArcticReader(data_root=...)` reads the local layout with no `hf://` access:

```python
from metalworks import Metalworks
from metalworks.research.arctic import ArcticReader

mw = Metalworks(reader=ArcticReader(data_root="./corpus"))
mw.research(
    "a focus supplement without the jitters",
    subreddits=["Supplements"],
)
```

That's it — the rest of the pipeline (triage, synthesis, web, triangulation) is
unchanged. If you didn't pull comments, pass `comments=None` and the report comes
back `partial` with submission-level signal only (see
[Comments are optional](/docs/custom-corpus#comments-are-optional)).

## Going further

The loader is deliberately small and source-specific. To run research over a
*non-Arctic* source — your own database, an internal API, a cache — implement the
`CorpusReader` and `CommentSource` protocols directly; that path is documented in
[Use your own corpus](/docs/custom-corpus).
