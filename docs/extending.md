---
title: "Extending metalworks"
description: "Every layer is swappable — bring your own model, corpus, search, or storage, or compose the building blocks into your own product."
---

Every layer is swappable — bring your own model, corpus, search, or storage, or
compose the building blocks into your own product. The `Metalworks` facade is the
easy path; underneath it is a kit of small, independent pieces. This page is the
map: what each piece is, and how to swap or compose it.

## Swappable protocols

Each protocol is `runtime_checkable` and has a default implementation behind a
pip extra. Implement the protocol and pass your object anywhere the default is
expected.

| Protocol | Import | Default(s) | How-to |
| --- | --- | --- | --- |
| `ChatModel` | `metalworks.llm` | Anthropic / OpenAI / Google / OpenAI-compatible | [Custom ChatModel](/docs/custom-chatmodel) |
| `EmbeddingProvider` | `metalworks.embeddings` | Google, OpenAI | [Protocols](/docs/protocols) |
| `SearchProvider` | `metalworks.search` | Exa, Tavily | [Protocols](/docs/protocols) |
| `CorpusReader` / `CommentSource` | `metalworks.research.deps` | Arctic Shift | [Use your own corpus](/docs/custom-corpus) |
| storage repos | `metalworks.stores` | `MemoryStores`, `SqliteStores` | [Bring your own store](/docs/custom-store) |

Anything you don't pass to `Metalworks(...)` is resolved from the environment.
Anything you do pass is used verbatim — that's how you swap a layer.

```python
from metalworks import Metalworks
from my_stack import MyChatModel, MyCorpus

mw = Metalworks(chat=MyChatModel(), reader=MyCorpus())   # swap two layers, keep the rest
```

## Composable functions

You don't have to use the facade or the end-to-end pipelines. The steps are
public functions you can wire into your own flow.

**Research steps** (`metalworks.research`):

- `pick_target_subreddits(deps, brief=...)` — LLM-suggested communities.
- `run_exploration_triage(deps, ...)` — three-bucket relevance triage.
- `hydrate_submissions(...)` / `hydrate_comments(...)` — pull a corpus into a repo.
- `synthesize(deps, ...)` — cluster comments into ranked insights.
- `web_research(deps, ...)` — web findings, backed by real quotes or source URLs.
- `triangulate(deps, ...)` — link Reddit clusters to web findings.
- `run_research(deps, brief=...)` — the whole thing, if you want it.

**Functions over a finished report** (`metalworks.research`) — each takes a
`DemandReport` and traces its output back to the report's real quotes:

- `build_positioning_brief(deps, report)` — your positioning angle + a price read,
  backed by real quotes (`metalworks.research.synthesis`).
- `run_competitor_map(deps, report)` — direct / adjacent / status-quo rivals,
  each with an exploitable gap backed by a real complaint.
- `decide_surface(deps, report, positioning)` / `build_ux_skeleton(...)` — a
  surface recommendation and a 3-5 screen UX skeleton.
- `build_spec_from_report(deps, report, positioning=None, surface="web")` /
  `scaffold(spec, report, dest)` (`metalworks.build`) — a `BuildSpec` (each
  feature mapped to a real demand cluster) + a project scaffold for your own
  coding agent. metalworks specs and scaffolds; it writes no product code.
  See the [Build spec](/docs/build-spec).
- `build_launch_assets(deps, report, positioning)` / `plan_channels(report)` —
  drafting-only launch copy (never posts) + a human-executed channel plan.
- `content_plan_from_report(report)` — a deterministic, zero-key content/SEO plan.

These are also on the `Metalworks` facade —
`mw.positioning(research)`, `mw.landscape(...)` (the competitive map + existing solutions),
`mw.surface(...)` / `mw.ux(...)`, `mw.build_spec(...)` / `mw.scaffold(...)`,
`mw.launch(...)` / `mw.channel_plan(...)`, `mw.content_plan(...)` — which thread
the one resolved `ResearchDeps` for you. See the [walkthrough](/docs/walkthrough).

**Reddit + discovery** (`metalworks.reddit`, `metalworks.discovery`):

- `RedditSearch` — search, comments, subreddit rules. No OAuth needed.
- `fetch_subreddit_intel(...)`, `fetch_inbox(...)`, `RedditOAuth` — intel, inbox, posting.
- `filter_post(model, post, context)` — is this thread worth engaging?
- `draft_reply(chat, post, persona, account_type, context)` — draft a reply in a voice.
- `heuristic_check(text)` / `llm_judge(...)` — the deterministic gate, then the escalation.
- `run_discovery(deps, queries=...)` — the whole filter → generate → gate loop.

See [Build your own loop](/docs/build-your-own) for composing the discovery
building blocks into your own product, and the
[Demand research guide](/docs/demand-research) for composing the research steps.

## Verify your swaps

The conformance suites ship as a public module so you can check a custom backend
or adapter against the same tests the defaults pass:

```python
from metalworks.testing import check_all_repos
check_all_repos(MyStore(), corpus_rows=1500)   # incl. the >1000-row pagination case
```
