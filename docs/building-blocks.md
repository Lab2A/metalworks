---
title: "Building blocks"
description: "The swappable protocols and composable functions that make up the kit — what you keep, replace, or compose."
---

The `Metalworks` facade is the easy path. Underneath it is a kit of small,
independent pieces. This page is the map: what each piece is, and how to swap or
compose it.

## Swappable protocols

Each protocol is `runtime_checkable` and has a default implementation behind a
pip extra. Implement the protocol and pass your object anywhere the default is
expected.

| Protocol | Import | Default(s) | How-to |
| --- | --- | --- | --- |
| `ChatModel` | `metalworks.llm` | Anthropic / OpenAI / Google / OpenAI-compatible | [Custom ChatModel](/docs/how-to-custom-chatmodel) |
| `EmbeddingProvider` | `metalworks.embeddings` | Google, OpenAI | [Protocols](/docs/reference-protocols) |
| `SearchProvider` | `metalworks.search` | Exa, Tavily | [Protocols](/docs/reference-protocols) |
| `CorpusReader` / `CommentSource` | `metalworks.research.deps` | Arctic Shift | [Use your own corpus](/docs/how-to-custom-corpus) |
| storage repos | `metalworks.stores` | `MemoryStores`, `SqliteStores` | [Bring your own store](/docs/how-to-custom-store) |

Anything you don't pass to `Metalworks(...)` is resolved from the environment.
Anything you do pass is used verbatim — that's how you swap a layer.

```python
from metalworks import Metalworks
from my_stack import MyChatModel, MyCorpus

mw = Metalworks(chat=MyChatModel(), reader=MyCorpus())   # swap two layers, keep the rest
```

## Composable functions

You don't have to use the facade or the end-to-end pipelines. The stages are
public functions you can wire into your own flow.

**Research stages** (`metalworks.research`):

- `pick_target_subreddits(deps, brief=...)` — LLM-suggested communities.
- `run_exploration_triage(deps, ...)` — three-bucket relevance triage.
- `hydrate_submissions(...)` / `hydrate_comments(...)` — pull a corpus into a repo.
- `synthesize(deps, ...)` — cluster comments into ranked insights.
- `web_research(deps, ...)` — grounded or external-search web findings.
- `triangulate(deps, ...)` — link Reddit clusters to web findings.
- `run_research(deps, brief=...)` — the whole thing, if you want it.

**Reddit + discovery** (`metalworks.reddit`, `metalworks.discovery`):

- `RedditSearch` — search, comments, subreddit rules. No OAuth needed.
- `fetch_subreddit_intel(...)`, `fetch_inbox(...)`, `RedditOAuth` — intel, inbox, posting.
- `filter_post(model, post, context)` — is this thread worth engaging?
- `generate_reply(chat, post, persona, account_type, context)` — draft a reply in a voice.
- `heuristic_check(text)` / `llm_judge(...)` — the deterministic gate, then the escalation.
- `run_discovery(deps, queries=...)` — the whole filter → generate → gate loop.

See [Build your own](/docs/build-your-own) for composing the discovery building
blocks into your own product, and the [Demand Research guide](/docs/guide-demand-research)
for composing the research stages.

## Verify your swaps

The conformance suites ship as a public module so you can check a custom backend
or adapter against the same tests the defaults pass:

```python
from metalworks.testing import check_all_repos
check_all_repos(MyStore(), corpus_rows=1500)   # incl. the >1000-row pagination case
```
