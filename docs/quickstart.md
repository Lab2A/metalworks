---
title: "Quickstart"
description: "Install metalworks, run the zero-key offline demo, then plug in a provider key for a real report."
---

## Install

```bash
pip install metalworks
```

Core stays lean (pydantic, httpx, typer, rich). Everything that pulls a provider
SDK lives behind an extra, so you install only what matches the key you have.

## The offline demo (no keys, no network)

```bash
metalworks quickstart    # planned for 0.1
```

This runs the full research pipeline against bundled Reddit sample data using
the in-memory store and bundled fake models. It prints a small report so you can
see the output shape before plugging in a provider.

## A real report

You need one LLM provider extra and the matching API key:

```bash
pip install "metalworks[google,research]"
export GOOGLE_API_KEY=...     # or ANTHROPIC_API_KEY / OPENAI_API_KEY
```

```python
from metalworks.contract import ResearchBrief, TargetSubreddit
from metalworks.research import ResearchDeps, run_research
from metalworks.research.arctic.reader import ArcticReader
from metalworks.stores import MemoryStores
from metalworks.llm.adapters.google import GoogleChatModel
from metalworks.embeddings.adapters.google import GoogleEmbedding

brief = ResearchBrief(
    brief_id="demo-1",
    question="Is there demand for a focus supplement aimed at developers?",
    decision_context="Deciding whether to build a nootropic brand.",
    success_criteria=["Find the top unmet needs"],
    must_address=["What do people dislike about current options?"],
    target_subreddits=[TargetSubreddit(name="Nootropics", rationale="core community")],
    web_research_directions=[],
    relevance_rubric="Posts discussing focus, energy, or nootropic supplements.",
)

deps = ResearchDeps(
    chat=GoogleChatModel("gemini-2.5-pro"),
    embeddings=GoogleEmbedding("gemini-embedding-001"),
    corpus=MemoryStores(),
    reader=ArcticReader(),
)

report = run_research(deps, brief=brief)
print(report.partial, len(report.ranked_clusters))
```

## The Claude Code plugin

```
/plugin marketplace add Lab2A/metalworks
/plugin install metalworks@lab2a
```

Then `/demand-report <your idea>`. The data tools run with no API key; the
pipeline tools use whatever provider key is in your environment. Requires
[uv](https://docs.astral.sh/uv/) on your PATH.

## Next

<CardGroup cols={2}>
  <Card title="Your first demand report" href="/docs/tutorial-first-demand-report" />
  <Card title="Custom ChatModel" href="/docs/how-to-custom-chatmodel" />
</CardGroup>
