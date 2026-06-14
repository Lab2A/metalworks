---
title: "Launch & growth guide"
description: "Pillar F drafts grounded, channel-native launch assets (drafting only — metalworks never posts); Pillar G projects a deterministic, zero-key content plan tuned for LLM-citability."
---

A finished `DemandReport` is the input to the last two stages of the arc. **Launch
(Pillar F)** turns it into channel-native copy a human reviews and posts. **Growth
(Pillar G)** projects it into a deterministic content plan tuned for citability,
and pairs that with the authentic Reddit engagement loop.

Both stages inherit the same discipline as the research that feeds them: a model
is never the source of a fact (see [Structural provenance](/docs/explanation-provenance)).
Launch grounds every claim to a verbatim quote and drops the ones it can't. Growth
runs without any model at all — it's a pure projection of the report.

```python
from metalworks import Metalworks
mw = Metalworks()

research = mw.research("Is there demand for a focus supplement aimed at developers?",
                       subreddits=["Nootropics", "Supplements"])

assets  = mw.launch(research, positioning)   # -> list[LaunchAsset] ([] on a no-go report)
plan    = mw.channel_plan(research)          # -> ChannelPlan (human-gated steps)
content = mw.content_plan(research)          # -> ContentPlan (deterministic, zero-key)
```

CLI: `metalworks research launch <id>` and `metalworks research content-plan <id>`.

## Launch (drafting only)

The single most important thing about Pillar F: **it is drafting only. metalworks
never posts.** `launch(...)` returns drafts; `channel_plan(...)` returns a checklist
a human runs by hand. Nothing in this pillar touches a network.

### Grounded, channel-native assets

`mw.launch(research, positioning)` drafts one `LaunchAsset` per surface — Product
Hunt, Show HN, and an X thread — each in that channel's native voice. The
positioning brief is optional; pass it to keep the copy consistent with your
[positioning statement](/docs/the-arc).

```python
for asset in assets:
    print(asset.surface, "—", asset.title)
    print(asset.body)
    for v in asset.variants:               # alternate hooks a human can pick
        print("  variant:", v)
```

Launch copy is the easiest place in the whole pipeline to over-claim, so every
factual, quantified, or attitudinal claim an asset makes is **grounded**. The model
returns a body plus a list of claims, each paired with the verbatim Reddit quote it
says supports it. The builder then, for each claim:

1. finds the supporting quote in the report by exact substring match against a real
   `QuoteCitation` — a literal slice of a verified quote, never a paraphrase;
2. locates the claim text inside the asset body to get a character span;
3. emits a `ClaimCitation` **only when both resolve**.

A claim whose support doesn't resolve against the report's evidence, or whose text
isn't present verbatim in the body, is **dropped** — no-cite-no-claim. A surviving
citation always satisfies `body[span_start:span_end] == claim_text`, and its
`evidence_ref` resolves against the source report's evidence by quote id.

```python
asset = assets[0]
for c in asset.claim_citations:
    quote = asset.body[c.span_start:c.span_end]   # == c.claim_text
    print(quote, "→ grounded to", c.evidence_ref.evidence_id)
```

> The char offsets are Python code-point offsets. A non-Python consumer (JS counts
> UTF-16 code units) should treat `claim_text` as authoritative and re-find it
> rather than slicing by offset when the body contains astral characters (emoji).

### The refusal gate

`launch(...)` **refuses — returns `[]`** — when the report signals no-go:

- a negative demand verdict (thin signal / no demand / insufficient evidence), or
- no cluster with at least 2 distinct authors.

The verdict check reads only the **demand-strength segment** (the part before the
first `;`). The verdict appends market and price caveats — e.g. *"not enough price
signal to recommend a price"* — whose wording collides with the negative-demand
phrases. A strong-demand report with a thin *price* signal is still launch-worthy,
so those caveats are never read as a no-go.

Each drafted body is also run through the deterministic `heuristic_check`
compliance gate, best-effort — a drafting-time signal only, never a blocker. A
single surface whose model call fails is skipped, never fatal to the batch.

### The human-run channel plan

`mw.channel_plan(research)` returns a `ChannelPlan`: a fully deterministic sequence,
no model involved. One `ChannelStep` per surface, each `requires_human=True` and
`posting_gated=True` by construction — the library plans, a person posts.

```python
plan = mw.channel_plan(research)
for step in plan.steps:
    print(step.scheduled_offset, step.surface, "—", step.action)
```

**Show HN is never automated.** Its step explicitly says to post it manually and
answer replies yourself — the HN audience expects a human, and the plan encodes
that. The plan is a checklist a founder runs by hand; holding a `LaunchAsset` or a
`ChannelPlan` never posts anything.

## Growth: content & AEO

`mw.content_plan(research)` is the opposite kind of stage from launch: **pure
deterministic, zero-key, no LLM, no embeddings, no network.** It projects one
`ContentPage` per ranked cluster, plus a `CitationStrategy`. Every field is taken
from the report — no keyword, quote, or answer is invented, and no ranking is
promised.

```python
content = mw.content_plan(research)
for page in content.pages:
    print(page.target_phrase, page.page_kind)
    print("  ", page.stat_anchors)          # {'distinct_authors': N, 'mentions': M}
```

Each page is honest by construction:

- **`target_phrase`** is the cluster's own `claim`, normalized — never a conjured
  keyword.
- **`page_kind`** is a deterministic heuristic on that phrase: `comparison`
  (vs/versus/or/best), `guide` (how/guide/tips), otherwise `answer`.
- **`stat_anchors`** carry the cluster's *real* distinct-author and mention counts,
  so the base-rate honesty travels straight into the content brief.
- **`faq`** is built **verbatim** from the brief's `must_address` sub-questions,
  each with an empty `answer_hint` — the plan marks the slot a citable answer must
  fill, it never fabricates the answer.
- **`outline`** is a fixed, answer-first section list: *What people actually want →
  Common approaches → The honest answer → FAQ.*

### Why answer-first, and why disclosed permalinks

The framing here is **AEO / GEO** — answer-engine / generative-engine optimization.
Reddit is one of the most heavily cited sources in answer engines, so the authentic
play is to write the genuinely-best answer to a real question and cite the real
threads that surfaced it. Two structural choices make the content citable:

- **Answer-first formatting** plus a **FAQPage JSON-LD** stub, so an assistant can
  lift a clean, self-contained answer.
- A `CitationStrategy` whose `reddit_targets` are the **actual `QuoteCitation`
  permalinks** from the report's top clusters — disclosed, real sources to cite, not
  placeholders. Its `prompt_set` holds a few example citability prompts derived
  mechanically from the target phrases.

```python
content.citation_strategy.reddit_targets   # real Reddit permalinks to cite
content.citation_strategy.prompt_set        # example LLM prompts to check citability against
```

Two renderers turn the typed plan into shippable artifacts, both built mechanically
from typed fields — never from free text:

```python
from metalworks.research.marketing import render_content_markdown, render_faq_jsonld

md     = render_content_markdown(content)   # a markdown outline pack
jsonld = render_faq_jsonld(content)         # a schema.org FAQPage stub
```

This is a structural plan for citable, evidence-anchored content — **not an SEO
guarantee.** The honest stat anchors and the no-invented-keyword rule are the point:
the content is as defensible as the demand report behind it.

## Growth: Reddit engagement

The other arm of growth is direct, authentic participation: searching for live
threads, drafting replies in a real persona's voice, gating them through compliance,
and posting only through an explicit, audited, human-connected account. That loop
has its own guide — it is not duplicated here.

See **[Reddit engagement](/docs/guide-reddit-engagement)** for search, the discovery
loop, the compliance gate, and gated posting.

The throughline across both arms is the same as the provenance rule: authentic,
disclosed engagement only. Citing real permalinks and writing the best answer-first
content is the legitimate AEO play — the opposite of astroturf. Fake personas,
invented backstories, and aged-account fabrication are excluded by design and
prohibited by the [usage policy](https://github.com/Lab2A/metalworks/blob/main/USAGE_POLICY.md).

## Where this sits

- [The arc](/docs/the-arc) — how research → positioning → launch → growth fit
  together end to end.
- [Structural provenance](/docs/explanation-provenance) — why a metalworks report,
  and everything projected from it, can't contain fabricated evidence.
