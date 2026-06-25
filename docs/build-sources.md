---
title: "Build a source"
description: "Add a new source in one of three lanes — a grounding connector that yields quotable records, a magnitude provider that attaches a number to a theme, or an agentic discovery provider that reaches the long tail. Each with a copy-paste worked example."
---

metalworks reads demand from many sources, and going wide stays safe only because
every source declares **what kind of thing it is**. That kind is its **lane**, and
there are exactly three. This page is the build guide for each — pick the lane that
matches your data, then follow the worked example.

<Note>
The live catalog of shipped sources lives in [Sources](/docs/sources) — it is
**generated** from each source's `SourceSpec` by `scripts/gen_sources_md.py`, so you
never hand-edit it. This page is the *how-to-add-one* guide; the catalog is the
*what's-there* list.
</Note>

## The three lanes

| Lane | Shape | Builds with | When to use |
| --- | --- | --- | --- |
| **grounding** | An `ItemSource` yielding quotable `CorpusRecord` / `CorpusComment` (text + permalink + pseudonymizable author) | `ItemSource` + `SourceSpec` + one line in `BUILTIN_SOURCE_MODULES` | A new venue people talk in — a forum, a Q&A site, a job board, an issue tracker |
| **magnitude** | A `MagnitudeProvider` overlay — an absolute number (downloads, installs, search volume) attached to a theme **after** clustering | `MagnitudeProvider` + `register_magnitude` | A number that *weights* a theme — never a new venue and never a quote |
| **web** (discovery) | A `DiscoveryProvider` that runs its own iterate-and-dig loop to reach the long tail without a per-venue connector | `DiscoveryProvider` + `register_discovery` / `resolve_discovery` | A managed deep-research engine (Exa, Parallel) that returns cited excerpts |

The rule that holds the wide corpus together: **a grounding source quotes; a
magnitude provider counts; a discovery provider digs.** A magnitude number can
never create a cluster, and a discovery provider ingests only verbatim citations,
never a synthesized summary. The 0.5 conformance sweep (`tests/test_conformance_sweep.py`)
enforces this lane discipline across the whole registry on every CI run.

---

## 1. A grounding connector

A grounding source implements the
[`ItemSource`](https://github.com/Lab2A/metalworks/blob/main/src/metalworks/research/sources/__init__.py)
protocol: it knows how to **pull** top-level records (`CorpusRecord`) and their
**comments** (`CorpusComment`) for a query over a time window. The pipeline never
speaks Reddit (or Stack Exchange, or GitHub) directly — it speaks `ItemSource` and
lets the ingest path write the records into the durable corpus. Every record carries
its real permalink and a pseudonymized author, so a downstream quote always resolves
back to its source: cite-or-die.

The fastest start is the scaffold:

```bash
metalworks sources scaffold mysource --lane grounding --auth none
```

That writes a connector module (a real `ItemSource` with a filled `SourceSpec` and a
`register_signal` block, leaving only `pull` / `comments_for` to write) and a
conformance test, then **prints** — never auto-applies — the `pyproject.toml` extra
and the `docs/sources.md` row. Adding a source is then a fill-in job, not a multi-file
edit.

### The worked example: Stack Exchange

[`stackexchange.py`](https://github.com/Lab2A/metalworks/blob/main/src/metalworks/research/sources/stackexchange.py)
is a complete, shipped grounding connector — one keyless API fronting 170+ Q&A sites
(Server Fault, DBA, Security, Salesforce). Read it end to end; the shape below is the
whole contract.

```python
from collections.abc import Iterator, Sequence

from metalworks.contract import CorpusComment, CorpusRecord
from metalworks.research.sources import SourceSpec, SourceWindow, register_source


class StackExchangeSource:
    """An ItemSource over the public, keyless Stack Exchange API."""

    source_id = "stackexchange"

    def pull(
        self, *, query: str, window: SourceWindow, limit: int | None = None
    ) -> Iterator[CorpusRecord]:
        # Page the search API for `query` over `window`, mapping each question
        # onto a CorpusRecord with a STABLE id, its permalink (url), a
        # pseudonymized author_hash, and a `signals` vector.
        for item in self._search(query, window):
            yield CorpusRecord(
                id=str(item["question_id"]),         # stable: the corpus upserts by id
                source="stackexchange",
                source_id=str(item["question_id"]),
                url=item["link"],                    # the real permalink — cite-or-die
                title=item["title"],
                text=clean(item["body"]),
                author_hash=hash_author(item["owner"]),  # pseudonymized HERE
                engagement=item["score"],
                signals={"votes": float(item["score"]), "views": float(item["view_count"])},
                created_at=to_dt(item["creation_date"]),
            )

    def comments_for(
        self, record_ids: Sequence[str]
    ) -> Iterator[list[CorpusComment]] | None:
        # Yield one CorpusComment batch per record id, in input order. Return
        # None ONLY if your source has no comment layer at all.
        return self._answers_for(record_ids)

    def latest_window(self) -> SourceWindow:
        # The most recent window your source can serve (its anchor).
        ...
```

Then declare what it is and self-register, at module scope:

```python
register_source(
    "stackexchange",
    lambda **_: StackExchangeSource(),
    spec=SourceSpec(
        source_id="stackexchange",
        lane="grounding",
        signals=("votes", "views"),   # votes = social; views = magnitude
        targeting="instance",         # the selector varies on the SE site
        auth="none",
        env=(),
        access="open",
        relevance_hint=(
            "developers, sysadmins, DBAs, security & cloud/SaaS pros across "
            "170+ Stack Exchange sites"
        ),
    ),
)
```

### Single registration (#139)

A built-in grounding connector is listed in **exactly one** place — the
`BUILTIN_SOURCE_MODULES` map in
[`src/metalworks/research/sources/__init__.py`](https://github.com/Lab2A/metalworks/blob/main/src/metalworks/research/sources/__init__.py):

```python
BUILTIN_SOURCE_MODULES: dict[str, str] = {
    ...
    "stackexchange": "metalworks.research.sources.stackexchange",
    "mysource": "metalworks.research.sources.mysource",   # ← add one line
}
```

`builtin_connector_modules()` and `builtin_source_ids()` derive everything else
(the lazy-import path, the selector's spec import, the CLI discovery, the catalog
generator) from this one map — so adding a connector touches one list, not six.
Aliases (`reddit` / `arctic` both map to the Arctic module) are just two keys
pointing at the same module path.

### Signals: declare new kinds

A source emits `signals: dict[str, float]` — any named kind it has. The
deterministic scorer reads the *semantics* of each known kind from a parallel
registry: `register_signal(SignalSpec(...))` in
[`metalworks.research.synthesis.signals`](https://github.com/Lab2A/metalworks/blob/main/src/metalworks/research/synthesis/signals.py).
Stack Exchange emits `votes` and `views`, both already registered, so it adds no
new spec. If you emit a kind the registry doesn't know yet (say `likes`), declare
it once:

```python
from metalworks.research.synthesis.signals import SignalSpec, register_signal

register_signal(SignalSpec(kind="likes", weight=1.0, transform="log"))
```

An unknown signal kind degrades to context-only (scored as zero) — it never
errors, but it also never counts, so declare anything you want the ranker to read.

### The `yields_units` / rule-5 rule

A grounding lane must declare **at least one non-magnitude signal** — otherwise it
ranks on nothing but raw volume, which the cite-or-die posture forbids. The 0.5
conformance sweep enforces this as **rule 5**: a grounding source whose only signal
is `is_magnitude` (like `downloads` or `views`) fails.

There is one exception: a source whose records are **self-representing** — each
record's own text *is* the unit people are talking about, because the source has no
comment layer (a web page, a job description). Mark it with `yields_units = True`
on the class:

```python
class MySource:
    source_id = "mysource"
    yields_units = True   # records are the unit; rank by distinct DOMAIN, not author
```

Synthesis then clusters the records themselves, and the ranker measures breadth by
distinct **domain** instead of distinct author. A `yields_units` source is exempt
from rule 5 because it is self-representing — `web` and `ats` are the shipped
examples. This is an explicit opt-in: a comment-bearing source whose comment client
simply isn't wired *also* returns `None` from `comments_for`, but it is **not** a
unit source.

### Verify

```python
from metalworks.testing import check_item_source
check_item_source(StackExchangeSource())
```

`check_item_source` enforces the two non-negotiables: **stable ids** (the corpus
upserts by id) and **idempotent pulls** (re-pulling the same query/window yields the
same id set). The scaffold writes this test for you, and the conformance sweep then
walks your registered `SourceSpec` against the whole-registry lane rules.

---

## 2. A magnitude provider

A magnitude source is a different shape entirely. It has no quotable record and no
author — it is a raw number for an *entity*: a package's downloads, an app's
installs, a keyword's search volume. Forcing it through `ItemSource` would either
fabricate a quote or let a bare number conjure a cluster out of thin air. So
magnitude gets its own lane.

A `MagnitudeProvider` runs **after** clustering. It is handed the entities the
pipeline already extracted *deterministically* from grounded artifacts (cluster
quote source names, the brief's slot-plan product, web-finding domains) and returns
`entity -> {kind: value}` — a measurement for each entity it actually has data for.
The pipeline merges those values into the matching cluster's `demand_signals` and
**rescores ranking only**. The verdict band never sees it.

### The Protocol

```python
from collections.abc import Sequence
from typing import Protocol

class MagnitudeProvider(Protocol):
    provider_id: str
    signals: tuple[str, ...]          # the is_magnitude kinds it emits, e.g. ("downloads",)

    def measure(
        self, *, entities: Sequence[str], window: SourceWindow
    ) -> dict[str, dict[str, float]]:
        """Measure `entities` over `window` → entity -> {kind: value}."""
        ...
```

### The worked example: npm downloads

[`magnitude.py`](https://github.com/Lab2A/metalworks/blob/main/src/metalworks/research/sources/magnitude.py)
ships `NpmDownloadsProvider`, a keyless provider over `api.npmjs.org/downloads`. It
maps each entity that *looks like* an npm package name to its monthly download count.

```python
from dataclasses import dataclass
from collections.abc import Sequence


@dataclass
class NpmDownloadsProvider:
    provider_id: str = "npm"
    signals: tuple[str, ...] = ("downloads",)

    def measure(
        self, *, entities: Sequence[str], window: SourceWindow | None = None
    ) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        for entity in entities:
            if not _is_npm_package_name(entity):
                continue                       # not package-shaped → skip, never mis-query
            count = self._fetch_downloads(entity, window)
            if count is not None:              # omission = unknown; NEVER store 0.0
                out[entity] = {"downloads": float(count)}
        return out
```

Register it with its own `MagnitudeSpec` (whose `lane` is fixed to `"magnitude"`,
the one value an `ItemSource` `SourceSpec` rejects):

```python
from metalworks.research.sources.magnitude import (
    MagnitudeSpec,
    register_magnitude,
)

register_magnitude(
    "npm",
    lambda **kwargs: NpmDownloadsProvider(**kwargs),
    spec=MagnitudeSpec(
        provider_id="npm",
        signals=("downloads",),
        targeting="slug",
        auth="none",
        env=(),
        access="open",
        relevance_hint="package adoption / install demand for a named npm package",
    ),
)
```

Built-in providers also list their module in a small map inside
`get_magnitude_provider` (`_BUILTIN_MODULES`: `npm`, `pypi`, `wikipedia`) so a bare
`import metalworks` stays free of `httpx`.

### Two non-negotiables

- **Omission means unknown, never `0.0`.** `measure` returns only the entities it
  has real data for. A package with no downloads in the window is simply *absent*
  from the result — the pipeline records "unknown", not "zero demand". Returning
  `0.0` would silently demote a real theme.
- **It can NEVER create a cluster.** A magnitude with no theme to attach to is
  dropped, not promoted. A number is only ever evidence *for an already-grounded
  theme*, never a theme on its own. This is the same cite-or-die guardrail in
  numeric form — `merge_magnitude_into_clusters` only ever *adds* a signal to an
  existing cluster.

Magnitude providers are **off by default**: a run only reads them when
`[sources].magnitude` lists them (see [Configuration](/docs/configuration)). A
provider that raises or times out is best-effort — the run records a caveat and
sets `partial`, never aborts.

---

## 3. A discovery provider

The grounding and magnitude lanes both need a *venue* — a known API to pull from.
The **web / discovery** lane reaches everything else: the long tail of niche forums,
blogs, community threads, and the underlying pages of review sites that have no
per-venue connector. It does this with an **agentic loop** — search, read, search
again — rather than one connector per site.

A `DiscoveryProvider` is the abstraction. The capability ladder
([`metalworks.research.discovery`](https://github.com/Lab2A/metalworks/blob/main/src/metalworks/research/discovery/__init__.py)):

```
DiscoveryProvider (agentic):  Exa Research / Parallel Task → DELEGATE (homegrown loop OFF)
   else → HomegrownDiscovery   (metalworks' own iterate-and-dig loop over a SearchProvider)
      else → web.py single-pass _external_search   (unchanged fallback)
```

### The Protocol

```python
from typing import ClassVar, Protocol

class DiscoveryProvider(Protocol):
    protocol_version: ClassVar[str]
    provider_id: str
    agentic: bool                      # the gate signal — see below

    def discover(
        self, *, question: str, directions: list[str], budget: DiscoveryBudget
    ) -> list[DiscoveryFinding]: ...
```

`agentic` is the gate. An `agentic=True` provider does its **own** iterate-and-dig,
so metalworks' homegrown loop does not run — `web.py` delegates the whole discovery
to it. `HomegrownDiscovery` reports `agentic=False`: it is metalworks' own loop over
a plain `SearchProvider`, used only when no agentic provider is configured.

### The worked example: Exa Research

[`discovery/exa.py`](https://github.com/Lab2A/metalworks/blob/main/src/metalworks/research/discovery/exa.py)
adapts Exa's **Research** endpoint — Exa runs its own parallel-search loop and
returns **field-level citations** (verbatim excerpts paired with their source URL).
The adapter consumes *only* those cited excerpts:

```python
class ExaResearchDiscovery:
    protocol_version: ClassVar[str] = PROTOCOL_VERSION
    provider_id: str = "exa_research"
    agentic: bool = True              # → metalworks delegates the whole loop

    def discover(self, *, question, directions, budget) -> list[DiscoveryFinding]:
        task = self._run_research(_instructions(question, directions))
        if task is None:
            return []                  # best-effort: degrade to [], never raise
        return self._findings_from_citations(task, budget)
```

### Cite-or-die when delegating

This is the load-bearing line of any discovery adapter: it **never ingests the
synthesized answer/summary prose** (`output.content`). Only the citations' verbatim
excerpts become `DiscoveryFinding`s — `quote` is the verbatim highlight, `source_url`
its citation URL — so the deterministic scorer downstream runs on **real quotes,
never model prose.** A finding with no verbatim excerpt or no URL is dropped, never
invented. `tests/test_discovery_exa.py` asserts the answer text never leaks into a
finding.

The `DiscoveryBudget` (`max_rounds` / `max_findings` / `max_domains`) is a pure,
deterministic stop condition — the LLM only ever *proposes* the next round's queries;
it never decides when to stop, and never writes the verdict.

### The capability-ladder gate

An agentic provider, when keyed, **always** delegates. `config.resolve_discovery()`
returns the configured agentic provider (Exa first via `EXA_API_KEY`, then Parallel
via `PARALLEL_API_KEY`); whenever it returns one, the gate in `web.py` runs that
provider and the homegrown loop stays off. With no agentic key set, `resolve_discovery`
returns `None` and the homegrown loop is the active rung — but only when
`[sources].discover = true`; otherwise the legacy single-pass search runs, so default
behavior and cost are unchanged. A provider registers via `register_discovery` (the
registry seam, mirroring `register_source`); the shipped agentic adapters are resolved
directly by key in `resolve_discovery`.

---

## Next

- [Sources](/docs/sources) — the live, generated catalog of shipped sources.
- [Your corpus](/docs/corpus) — what the corpus is and how the lanes feed it.
- [Configuration](/docs/configuration) — `[sources].select` / `.magnitude` / `.discover` toggles.
- [How it works](/docs/how-it-works) — where the lanes sit in the pipeline.
