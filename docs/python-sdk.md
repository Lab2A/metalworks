---
title: "Python SDK reference"
description: "The complete Metalworks facade API: construction, research, every stage method, the .reddit and .discovery namespaces, the objects you get back, and the exceptions to catch."
---

`from metalworks import Metalworks` — one object you construct, and everything hangs off it.
This page is the full reference: every public method, its signature, what it takes, and what
it returns. New to the library? Start with the [walkthrough](/docs/walkthrough); come here when
you need the exact surface.

The one rule that shapes every return type: **nothing is invented.** Every claim carries an
`EvidenceRef` that resolves to a real Reddit quote or web finding on the report's evidence
list. When a method can't ground something, it drops it or marks the result `partial` — it
does not fill the gap with plausible text.

## Constructing the client

```python
class Metalworks:
    def __init__(
        self,
        *,
        chat: ChatModel | None = None,
        fast_chat: ChatModel | None = None,
        embeddings: EmbeddingProvider | None = None,
        store: Store | None = None,
        reader: CorpusReader | None = None,
        search: SearchProvider | None = None,
        comments: CommentSource | None = None,
        model: str | None = None,
        fast_model: str | None = None,
    ) -> None: ...
```

The common cases:

```python
mw = Metalworks()                       # provider inferred from your env key
mw = Metalworks(model="anthropic/claude-opus-4-8")   # pin a provider/model
mw = Metalworks(model="openai/gpt-5", fast_model="openai/gpt-5-mini")  # cheap triage model
```

| Argument | What it does |
| --- | --- |
| `model` | The main model, as `"provider/model"` or `"provider:model"`. If omitted, resolved from the first env key present: `ANTHROPIC_API_KEY` → `OPENAI_API_KEY` → `GOOGLE_API_KEY`. |
| `fast_model` | A cheaper model for triage/filtering. Falls back to `model` when unset. |
| `chat` / `fast_chat` / `embeddings` / `search` / `reader` / `comments` | Pass a fully-built object to swap any single layer (e.g. an OpenAI-compatible endpoint, a custom corpus). See [Extending metalworks](/docs/extending). |
| `store` | Where runs/reports persist. Defaults to your project's `.metalworks/corpus.db` if one exists, else in-memory. See [Projects & memory](/docs/projects). |

Provider refs route by namespace: `anthropic`, `openai`, `google`/`gemini` are native; anything
else (`openrouter/...`, `meta-llama/...`) routes through an OpenAI-compatible endpoint. To point
at a local or custom endpoint, construct an `OpenAIChatModel(base_url=..., api_key_env=...)` and
pass it as `chat=`.

## Research

### `.research(...)`

```python
def research(
    self,
    question: str | ResearchBrief,
    *,
    subreddits: list[str] | None = None,
    time_window_months: int | None = None,
    per_sub_limit: int | None = None,
    max_findings: int = 10,
) -> Research: ...
```

Runs the demand pipeline and returns a frozen [`Research`](#the-research-bundle) bundle.

| Argument | Default | Notes |
| --- | --- | --- |
| `question` | — | A plain sentence, or a fully-built `ResearchBrief` (from `.plan()`) for full control. |
| `subreddits` | planner picks | Names without `r/`. Omit to let the planner choose. |
| `time_window_months` | `12` | How far back the corpus window reaches. |
| `per_sub_limit` | pipeline default | Cap submissions pulled per subreddit. |
| `max_findings` | `10` | Max demand clusters to surface. |

If you're inside a [project](/docs/projects), the run is automatically persisted to
`.metalworks/runs/<report_id>/`. Casual use (no project) leaves no footprint.

```python
research = mw.research("a jitter-free focus supplement for developers",
                       subreddits=["Nootropics", "Supplements"])
report = research.demand
print(report.verdict)                         # one-line go / no-go (str | None)
for c in report.ranked_clusters:
    print(c.distinct_author_count, "people:", c.claim)
    for q in c.quotes:
        print("  ", q.permalink, q.text[:80])
```

### `.plan(prompt)`

```python
def plan(self, prompt: str) -> ResearchBrief: ...
```

Walks the planner end-to-end (taking the recommended answer at each decision) and returns a
`ResearchBrief` you can inspect, edit, and pass straight back into `.research(brief)`.

### The `Research` bundle

`research()` returns a frozen `Research`. The demand report is on `.demand`; `.evidence` is the
flat, resolvable evidence list every downstream method's `EvidenceRef`s point at.

| Attribute | Type | Notes |
| --- | --- | --- |
| `.demand` | `DemandReport` | The report (see [Data model](/docs/data-model)). |
| `.evidence` | `list[EvidenceRecord]` | The grounded evidence, surfaced for resolving refs. |
| `.competitors` / `.positioning` | `… \| None` | Reserved accessors; `None` today (forward-compatible). |

Key fields you'll read on `.demand`:

| Field | Type | Meaning |
| --- | --- | --- |
| `verdict` | `str \| None` | The go/no-go summary line. |
| `ranked_clusters` | `list[InsightCluster]` | The demand clusters, ranked by `demand_score`. |
| `total_distinct_authors` | `int` | Distinct people across the corpus (the honest base rate). |
| `price_finding` | `PriceFinding \| None` | Price band, if the corpus carried price signal. |
| `segments` / `audience_profile` | … | Inferred audience, when grounded. |
| `web_findings` | `list[WebFinding]` | External findings, each with a source URL. |
| `partial` / `caveat` | `bool` / `str \| None` | Set when the signal was too thin to be confident. |

Each `InsightCluster` carries `rank`, `claim`, `demand_score`, `distinct_author_count`,
`mention_count`, `signal`, and `quotes` (verbatim `QuoteCitation`s with `text`, `permalink`,
`subreddit`, `author_hash`, `upvotes`).

## The stage methods

Each method below runs on a finished `research()` bundle (or a bare `DemandReport`). They're
the Research → Design → Build → Launch → Grow arc. All read from the same report, so every
output traces back to the same evidence.

### Research stage

```python
def positioning(self, research: Research | DemandReport) -> PositioningBrief: ...
def competitors(self, research: Research | DemandReport) -> CompetitorMap: ...
```

`positioning` returns a Dunford-style wedge + price hypothesis. `competitors` returns
direct/adjacent/status-quo rivals, each gap backed by a real complaint. Both set `partial=True`
with a `caveat` when there's no defensible wedge / the named set couldn't be grounded.

```python
pos = mw.positioning(research)
print(pos.positioning_statement)
if pos.wedge:                      # None when no white-space cluster qualifies
    print(pos.wedge.unique_attribute)

comp = mw.competitors(research)
for rival in comp.competitors:
    for gap in rival.gaps:
        print(rival.name, "misses:", gap.claim)   # each gap has a resolvable EvidenceRef
```

### Design stage

```python
def surface(self, research, positioning: PositioningBrief) -> SurfaceRecommendation: ...
def ux(self, research, positioning: PositioningBrief, surface: SurfaceKind) -> UxSkeleton: ...
def site(self, research, positioning: PositioningBrief | None = None) -> MarketingSite: ...
def render_site(self, site: MarketingSite, research=None) -> str: ...
```

`surface` picks `sdk`/`web`/`mobile`/`cli`/… with a cited rubric; `ux` sketches 3–5 screens,
each flagged validated (evidence-backed) or hypothesis. `site` builds marketing copy where
every load-bearing line is a verbatim quote; `render_site` turns it into a self-contained
`index.html` string.

```python
surface = mw.surface(research, pos)
ux = mw.ux(research, pos, surface.chosen)
site = mw.site(research, pos)
open("index.html", "w").write(mw.render_site(site, research))
```

### Build stage

```python
def build_spec(self, research, positioning=None, surface: SurfaceKind = "web",
               *, stack: str = "empty") -> BuildSpec: ...
def scaffold(self, spec: BuildSpec, research, dest: Path, *, base: str = "empty") -> list[Path]: ...
```

`build_spec` maps demand to a feature list (each feature tied to ≥1 real quote; ungrounded ones
are dropped). `scaffold` writes a cite-or-die build harness under `dest` and returns the paths
written. **metalworks writes the spec, not the product** — your coding agent builds from the
scaffold.

```python
spec = mw.build_spec(research, pos, surface.chosen)
paths = mw.scaffold(spec, research, Path("./my-startup"))
```

`scaffold` raises `ValueError` if `spec.report_id` doesn't match the research bundle.

### Launch & Grow stages

```python
def launch(self, research, positioning=None) -> list[LaunchAsset]: ...
def channel_plan(self, research, surfaces: list[str] | None = None) -> ChannelPlan: ...
def content_plan(self, research) -> ContentPlan: ...
```

`launch` drafts channel-native assets (Product Hunt / Show HN / X), each claim carrying a
`ClaimCitation` with exact character spans — **it never posts**. `channel_plan` is a
deterministic, human-executed checklist (every step is `requires_human=True`). `content_plan`
is deterministic and zero-key: one page per demand cluster, with FAQ blocks and citation
targets.

```python
assets = mw.launch(research, pos)
plan = mw.channel_plan(research, surfaces=["product_hunt", "show_hn"])
content = mw.content_plan(research)        # no LLM call, no key needed
```

### `.deps`

```python
@property
def deps(self) -> ResearchDeps: ...
```

The resolved dependency container (chat, embeddings, corpus, reader…). The escape hatch for
calling the raw stage functions yourself — e.g. `build_positioning_brief(mw.deps, report)` —
without rebuilding the providers by hand.

## `.reddit` — Reddit surfaces

Reads are zero-key; the rate limiter is shared across all calls on one client.

```python
def search(self, query: str, *, subreddit: str | None = None, limit: int = 15) -> list[RedditPost]
def subreddit(self, name: str) -> SubredditIntel
def comments(self, post_url: str, *, limit: int = 10) -> list[RedditComment]
def rules(self, name: str) -> list[str]
def inbox(self, *, access_token: str, limit: int = 25) -> list[InboxItem]
def post(self, post_url: str, text: str, *, username: str) -> PostResult
```

```python
posts = mw.reddit.search("focus supplement", subreddit="Nootropics", limit=10)
intel = mw.reddit.subreddit("Nootropics")          # subscribers, rules, top posts
rules = mw.reddit.rules("Nootropics")
comments = mw.reddit.comments(posts[0].url)
```

`.inbox` and `.post` are the authenticated surfaces. **`.post` is gated**: it runs the
deterministic compliance check first and refuses on a block verdict (returning a failed
`PostResult`), and every attempt — blocked or sent — is appended to
`~/.metalworks/post-log.jsonl`. It needs `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` and a
previously connected account. See [Reddit engagement](/docs/reddit-engagement).

## `.discovery` — find threads, draft replies

```python
def run(self, queries: list[str], *, subreddits: list[str] | None = None,
        max_opportunities: int = 30, context: DiscoveryContext | None = None) -> list[Opportunity]
def filter(self, post: RedditPost, *, context: DiscoveryContext | None = None) -> FilterDecision | None
def generate(self, post: RedditPost, *, persona: Persona | None = None,
             account_type: str = "expert", context: DiscoveryContext | None = None,
             subreddit_rules: list[str] | None = None) -> ReplyGenerationV2 | None
```

`run` is the full loop (search → filter → generate → compliance-gate) and returns draft
`Opportunity` objects — **it never posts**. `filter` and `generate` are the building blocks if
you want to drive the loop yourself.

```python
from metalworks.contract import DiscoveryContext, Persona

ctx = DiscoveryContext(
    voice_guidelines=["be direct", "cite specifics"],
    personas={"founder": Persona(background="founder of a sleep-tech startup")},
)
opps = mw.discovery.run(["focus supplement", "nootropic stack"],
                        subreddits=["Nootropics"], context=ctx)
for o in opps:
    print(o.post.title)
    print(o.draft_reply)
    print(o.compliance.pass_)        # the compliance verdict on the draft
```

`Persona.background` must be **authentic** — fabricated personas and invented backstories are
prohibited by the [usage policy](https://github.com/Lab2A/metalworks/blob/main/USAGE_POLICY.md).

## Exceptions

All inherit from `MetalworksError`, which carries an optional `fix` hint and `docs_url`. Import
them from `metalworks.errors`.

| Exception | Raised when | Fix |
| --- | --- | --- |
| `MissingExtraError` | A feature needs an optional dependency | `pip install "metalworks[<extra>]"` |
| `MissingKeyError` | A required API key isn't set | Export the env var it names |
| `RateLimitedError` | An upstream returns 429 after retries | Back off and retry |
| `StructuredOutputError` | A model can't match the required schema | Retry, simplify, or use a stronger model |
| `GroundingUnavailable` | The model can't do grounded web search | Use a grounding-capable model or pass a `SearchProvider` |
| `ReauthRequiredError` | A Reddit OAuth token expired/was revoked | `metalworks reddit auth login` |
| `EmbeddingModelMismatch` | A cached index was built with a different embed model | Re-embed, or switch back to that model |
| `StoreError` / `RedditError` | The storage backend / Reddit API failed | Check the backend / credentials |

## See also

- [Projects & memory](/docs/projects) — how runs and artifacts persist so commands chain.
- [Data model](/docs/data-model) — the objects you get back, field by field.
- [CLI](/docs/cli) — the same surface from the command line.
- [Extending metalworks](/docs/extending) — swap any model, store, or corpus.
