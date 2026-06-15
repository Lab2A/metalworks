# scripts/

Standalone developer scripts. Each is runnable on its own and depends only on
the standard library plus, where noted, a single extra. They are **not** part of
the published package and do not change library behavior.

## `load_arctic_corpus.py`

Build a local Reddit corpus from the Arctic Shift Hugging Face Parquet mirror,
laid out so metalworks' `ArcticReader(data_root=...)` can read it. This demotes
Arctic from "the corpus the library hinges on" to a sample loader you run
yourself — see [`docs/load-reddit-corpus.md`](../docs/load-reddit-corpus.md) for
the full guide.

```bash
# Pull 3 months of r/Supplements submissions into ./corpus
python scripts/load_arctic_corpus.py --subreddit Supplements --months 3 --out ./corpus

# Multiple subreddits + live comments
python scripts/load_arctic_corpus.py -s Supplements -s Nootropics --months 1 --comments --out ./corpus
```

Writes `<out>/submissions/<YYYY>/<MM>/<subreddit>.parquet` (and, with
`--comments`, `<out>/comments/<YYYY>/<MM>/<subreddit>.jsonl`). Requires `duckdb`
(`pip install "metalworks[arctic]"`). Run `--help` for all flags.

## `gen_ts_types.py`

Generate TypeScript types + JSON-schema snapshots from the Pydantic contract.
Dependency-free; re-run whenever anything in `src/metalworks/contract/` changes.
