---
title: "Python SDK reference"
description: "The complete Metalworks facade API: construction, research, every stage method, the .reddit and .discovery namespaces, the objects you get back, and the exceptions to catch."
---

`from metalworks import Metalworks` — one object you construct, and everything hangs off it.
This page is the full reference: every public method, its signature, what it takes, and what
it returns. New to the library? Start with the [walkthrough](/docs/walkthrough); come here when
you need the exact surface.

The one rule that shapes every return type: **nothing is invented.** Every claim carries an
`EvidenceRef` that resolves to a real quote or web finding on the report's evidence
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
print(report.demand_summary)                  # one-line demand-strength summary (str | None)
for c in report.ranked_clusters:
    print(c.distinct_author_count, "people:", c.claim)
    for q in c.quotes:
        print("  ", q.source_url, q.text[:80])
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
| `.competitors` / `.positioning` | `CompetitorMap \| None` / `PositioningBrief \| None` | The Pillar-A/B outputs, when composed onto the bundle. |
| `.landscape` / `.assessment` / `.ideation` | `Landscape` / `Assessment` / `IdeaSketch`, each `\| None` | The validation-loop outputs, when composed on. All default `None` (additive). |

Key fields you'll read on `.demand`:

| Field | Type | Meaning |
| --- | --- | --- |
| `demand_summary` | `str \| None` | The one-line demand-strength summary (not the go/no-go — that's `assess`). |
| `ranked_clusters` | `list[InsightCluster]` | The demand clusters, ranked by `demand_score`. |
| `total_distinct_authors` | `int` | Distinct people across the corpus (the honest base rate). |
| `price_finding` | `PriceFinding \| None` | Price band, if the corpus carried price signal. |
| `segments` | `list[SegmentChoice]` | The audience forks the report surfaces. |
| `audience_profile` | `AudienceProfile \| None` | **Currently always `None`** — demographic inference was cut. |
| `web_findings` | `list[WebFinding]` | External findings, each with a source URL. |
| `partial` / `caveat` | `bool` / `str \| None` | Set when the signal was too thin to be confident. |

Each `InsightCluster` carries `rank`, `claim`, `demand_score`, `distinct_author_count`,
`mention_count`, `signal`, and `quotes` (verbatim `ResolvedCitation`s with `text`, `source_url`,
`source`/`source_name`, `author_hash`, `engagement`).

## The stage methods

Each method below runs on a finished `research()` bundle (or a bare `DemandReport`). They're
the Research → Design → Build → Launch → Grow arc. All read from the same report, so every
output traces back to the same evidence.

### Research stage

```python
def positioning(self, research: Research | DemandReport) -> PositioningBrief: ...
```

`positioning` returns a Dunford-style wedge + price hypothesis, with `partial=True` + a `caveat`
when there's no defensible wedge. (The competitive map lives inside `landscape()` below — there's
one "what exists today" door now, not two.)

```python
pos = mw.positioning(research)
print(pos.positioning_statement)
if pos.wedge:                      # None when no white-space cluster qualifies
    print(pos.wedge.unique_attribute)
```

### The validation loop

The discovery loop — frame an idea, weigh demand against what already exists, get an honest
verdict. See the [validation loop](/docs/validation-loop) for the full picture.

```python
def ideate(self, idea: str) -> IdeaSketch: ...
def ideate_from_evidence(self, research: Research | DemandReport) -> IdeationResult: ...
def landscape(self, research: Research | DemandReport) -> Landscape: ...
def assess(self, research: Research | DemandReport, landscape: Landscape) -> Assessment: ...
def validate(self, idea: str, *, max_iterations: int = 4) -> ValidationResult: ...
```

- `ideate` (idea-first) sharpens a raw idea into a testable hypothesis + a `ResearchBrief`;
  `ideate_from_evidence` (evidence-first) surfaces a report's forks — candidate wedges, else top
  clusters — as grounded `IdeaSketch`es to pick from.
- `landscape` is the full "what exists today": the nested `competitor_map` (direct/adjacent/status-quo
  rivals, each gap cited and each tagged with the clusters it competes for) plus an empirical
  existing-solutions scan (real shipped products, matched to demand clusters).
- `assess` is the heart: a **deterministic** GO / PIVOT / NO-GO gap over demand × landscape (the LLM
  only writes the rationale). PIVOT carries a `pivot_target` — a real fork id to aim at. A partial
  landscape never yields a hard GO.
- `validate` runs the loop headlessly: ideate → demand → landscape → assess, looping on PIVOT. It
  pulls the corpus **once** and reuses it for every in-corpus pivot — a fresh pull happens only if a
  pivot leaves the corpus.

```python
landscape = mw.landscape(research)
verdict = mw.assess(research, landscape)
print(verdict.decision)                    # "go" | "pivot" | "no_go"
if verdict.pivot_target:
    print("aim at:", verdict.pivot_target.target_id, "—", verdict.gap.reasoning)

result = mw.validate("a privacy-first habit tracker for therapists")
print(result.outcome, "in", result.iterations, "round(s)")
```

### Design stage

```python
def design(self, research, *, brand_name: str | None = None,
           max_teardown: int = 3) -> DesignSystem: ...
```

`design` authors a grounded-but-directional `DesignSystem` (an aesthetic direction + a SAFE/RISK
choice per dimension), read from a real browser teardown of competitor sites where available and
honest about its grounding tier.

### Build stage

```python
def build_spec(self, research, positioning=None, surface: SurfaceKind | Literal["auto"] = "auto",
               *, stack: str = "empty") -> BuildSpec: ...
def scaffold(self, spec: BuildSpec, research, dest: Path, *, base: str = "empty") -> list[Path]: ...
```

`build_spec` maps demand to a feature list (each feature tied to ≥1 real quote; ungrounded ones
are dropped), picks the surface with a one-line rationale when `surface="auto"` (the default), and
sketches a feature-grounded screen skeleton. `scaffold` writes a cite-or-die build harness under
`dest` and returns the paths written. **metalworks writes the spec, not the product** — your coding
agent builds from the scaffold.

```python
spec = mw.build_spec(research, pos)        # surface="auto" → the spec picks + explains it
paths = mw.scaffold(spec, research, Path("./my-startup"))
```

`scaffold` raises `ValueError` if `spec.report_id` doesn't match the research bundle.

### Distribution stage

```python
def channel_strategy(self, research, positioning=None) -> ChannelStrategy: ...
def distribution_requirements(self, research, positioning=None) -> tuple[list[LoopRequirement], list[ConversionSurfaceRequirement]]: ...
def channel_assets(self, research, positioning=None) -> list[ChannelAsset]: ...
def data_asset(self, research, kind="complaint_index") -> DataReportAsset: ...
def distribution_plan(self, research, positioning=None) -> DistributionPlan: ...
def channel_metrics(self, research, positioning=None) -> list[ChannelMetric]: ...
def geo(self, research) -> GeoPlan: ...
def distribution_engage(self, research, target, *, voice=None) -> ParticipationReply: ...
```

`channel_strategy` routes the report's real named entities + signals into **test→focus** channel
experiments (D2) — every `routing_signal` traces to a real corpus entity. `distribution_requirements`
emits the embedded loops + conversion surface distribution designs INTO the product as BUILD
requirements (D3): a `LoopRequirement` per `embedded_loop` channel (loop kind → concrete build
requirements grounded in the channel's signal) plus a `ConversionSurfaceRequirement` for the
destination the channels point at — feed it to `build_spec(..., distribution_requirements=...)`.
`channel_assets` drafts channel-SHAPED, drafting-only assets per channel (D4) — one `ChannelAsset`
per selected channel, shaped to its surface (Product Hunt tagline + maker comment; Show HN title +
first comment; X thread; LinkedIn carousel); demand/factual claims are grounded, persuasive hooks
free, platform invariants enforced — **it never posts**. `data_asset` projects the report into a
corpus-derived **data report** (D5), the on-brand flagship asset: a deterministic ranking of the
report's clusters carrying their REAL distinct-author / mention counts, real permalinks, and a
verbatim quote per row; `kind` picks the framing (`complaint_index` | `feature_ranking` |
`state_of`). `distribution_plan`
sequences those channels into a campaign (D7): **pushes** (the `spike`-cadence channels placed into
concentrated launch moments, their `timing` READ from a deterministic playbook table — Product Hunt
12:01am PT Tue/Wed, Show HN Tue-Thu 8-10am, … — never invented hours; one all-day-attention channel
per day, never Product Hunt + a big HN push the same day; pre-launch warming → push week → a 30-day
post step) + **streams** (the `compounding`-cadence channels run continuously). `channel_metrics`
closes the loop (D8): one `ChannelMetric` per channel — its `success_metric` (what "worked") + its
`instrumentation` (how to track it), read deterministically by `surface_type`; record a
`ChannelResult` per channel after the push and pass them as `prior_results` to
`build_channel_strategy` / `plan_distribution` to re-rank the next push (winners rise). `geo` is the
GEO / LLM-citability stream (D6): **participation targets** (real threads to engage, from the
report's permalinks), **citability probes** (conversational queries to test you're cited, from the
cluster claims), and answer-first **answer briefs** (grounded — each `evidence_refs` resolves against
`report.evidence`, `stat_anchors` carry the cluster's real counts, ungrounded answers dropped).
`distribution_engage` is the **participation/execution arm** (D9) — the one channel metalworks can
OPERATE rather than merely plan: it takes one of `geo`'s `participation_targets` (a real thread) and
drafts a disclosed, founder-voiced reply for that exact thread, reusing the Reddit reply machinery +
the single voice system's invariants (no upvote ask, native-first, no AI tells), then runs the shared
honesty gate (`heuristic_check`) over it — returning a `ParticipationReply` (the draft + the compliance
verdict + `requires_human` / `posting_gated`, both always true). All are **drafting only** — nothing
posts; a human posts a participation reply through the gated `mw.reddit.post(...)` path.

```python
dist = mw.distribution_plan(research)
for p in dist.pushes:
    print(p.timing, "—", p.channel_name, "→ sparks", p.spark_channel)
for s in dist.streams:
    print(s.channel_name, "—", s.cadence_note)

plan = mw.geo(research)
for t in plan.participation_targets:
    print(t.community, t.permalink, "—", t.why)
for b in plan.answer_briefs:
    print(b.question, b.stat_anchors)

# the execution arm: engage one of the GEO targets (drafting only, gated)
reply = mw.distribution_engage(research, plan.participation_targets[0])
print(reply.compliance.pass_, reply.community)
print(reply.draft)
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
