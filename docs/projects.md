---
title: "Projects & memory"
description: "How metalworks remembers your work: the .metalworks/ project directory, what persists, and how every command chains off one demand report instead of re-running research."
---

metalworks has a memory. Run research once, and every later step — positioning, the site, the
build spec, launch copy — reads from that same stored report instead of asking you to re-run
anything. That memory lives in a `.metalworks/` directory in your project, created the same way
`git init` creates `.git`.

This is what lets the CLI and the [Claude Code plugin](/docs/claude-code) work in steps: one
command produces a report, the next takes its `report_id` and builds on it.

## It's opt-in — zero footprint until you ask

metalworks writes **nothing** to disk unless you create a project. A one-off
`mw.research(...)` or `metalworks research run` with no project keeps everything in memory and
leaves no trace — exactly like running `git status` outside a repo.

Create the memory when you want it to stick:

```bash
metalworks init --idea "a jitter-free focus supplement for developers"
```

That makes `.metalworks/` in the current directory. From then on, runs persist and commands
chain. (In Python, the facade auto-detects a project by walking up from the working directory,
just like git finds `.git`.)

## What's inside `.metalworks/`

```
your-startup/
└─ .metalworks/
    ├─ project.json          # manifest: id, slug, idea, created_at, runs[]   [commit]
    ├─ config.toml           # non-secret provider/model settings             [commit]
    ├─ corpus.db             # sqlite: corpus + runs + embeddings             [gitignored]
    ├─ runs/<report_id>/research.{md,json}                                    [commit]
    └─ artifacts/            # later-stage outputs (positioning, site, …)     [commit]
```

| File | Holds | Committed? |
| --- | --- | --- |
| `project.json` | The manifest — project id, slug, idea, and a list of every run. | Yes |
| `config.toml` | Non-secret settings (provider, model). **Secrets only ever come from env vars.** | Yes |
| `corpus.db` | The pulled Reddit corpus, finished reports, and embedding cache. Re-pullable, so it's gitignored automatically. | No |
| `runs/<report_id>/research.json` | The full `Research` bundle for one run — the durable, committable artifact. | Yes |
| `runs/<report_id>/research.md` | A human-readable summary of the same run. | Yes |
| `artifacts/<kind>.json` | The latest output of each later stage (positioning, marketing site, content plan, …). | Yes |

`metalworks init` writes a `.gitignore` inside `.metalworks/` that excludes `corpus.db` for
you, so committing the directory captures your research and outputs without the bulky,
re-buildable cache.

## How commands chain

Every run mints a `report_id`. List your runs to find it, then pass it to any later command:

```bash
metalworks research run --question "a jitter-free focus supplement for developers"
metalworks research list          # table of report_id · question · authors · date

# take the report_id from that table:
metalworks research position   <report_id>
metalworks research competitor-map <report_id>
metalworks research site       <report_id>
metalworks build init          <report_id> --dest ./my-startup
```

Re-running research mints a **new** `report_id` and a new `runs/<id>/` directory — your history
is the set of run directories plus git, nothing is overwritten. Later-stage artifacts record
the `report_id` they were built from, so a stale positioning brief is detectable by comparing
its stamp to your latest run.

In Python the chaining is implicit — you hold the bundle and pass it along — but the same
persistence happens underneath when a project exists:

```python
from metalworks import Metalworks

mw = Metalworks()                 # finds .metalworks/ by walking up from cwd
research = mw.research("...")     # auto-saved to .metalworks/runs/<report_id>/
pos = mw.positioning(research)    # reads the same in-memory bundle
```

## Where memory lives when there's no project

| Situation | Store used | Footprint |
| --- | --- | --- |
| Inside a `.metalworks/` project | SQLite on `.metalworks/corpus.db` | Persists; memory accumulates across commands |
| No project (casual use) | In-process memory | Zero — nothing written |

The CLI also keeps a global store at `~/.metalworks/` for runs you make outside any project,
and that's where the Reddit `post-log.jsonl` audit trail and any connected-account tokens
(encrypted at rest) live.

## Under the hood: the stores

The corpus database is backed by a set of typed repositories — `CorpusRepo` (posts, comments,
embeddings), `RunRepo` (runs + finished reports), `OpportunityRepo`, `InboxRepo`, `AccountRepo`,
`BriefRepo`. Two backends ship in core: `MemoryStores` (the zero-footprint default) and
`SqliteStores` (the project file). They're protocols, so you can point metalworks at a hosted
backend (Postgres/PostgREST) — see [Bring your own store](/docs/custom-store).

## See also

- [Python SDK reference](/docs/python-sdk) — `Metalworks(store=...)` and the `.research()` flow.
- [CLI](/docs/cli) — `init`, `research run`, `research list`, `build init`.
- [Data model](/docs/data-model) — what's inside a run's `research.json`.
- [Bring your own store](/docs/custom-store) — swap SQLite for a hosted backend.
