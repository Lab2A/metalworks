---
title: "Architecture"
description: "How metalworks fits together and the principles behind it — contract-first, one capability on four surfaces, a deterministic core with LLM prose, no-cite-no-claim, lean core with lazy extras, and offline-by-default tests."
---

The mental model behind metalworks — why it's shaped the way it is. If you're extending it or
[contributing](https://github.com/Lab2A/metalworks/blob/main/CONTRIBUTING.md), read this first.

## Contract-first

`metalworks.contract` is a set of Pydantic models — `DemandReport`, `Landscape`, `Assessment`,
`ResearchBrief`, and the rest. It is **the stable spine**: the one thing that doesn't change casually
below 1.0, and the shape every other layer speaks. The TypeScript twin (`ts/contract.ts`) and the
JSON-schema snapshots (`src/metalworks/contract/schema/`) are *generated* from these models by
`scripts/gen_ts_types.py` — one source of truth, no hand-maintained copies. A contract change is a
deliberate act: regenerate, commit the generated files, and stay additive (new fields default so an
old payload still validates).

## One capability, four surfaces

Every capability is exposed the same way on all four surfaces, so the Python SDK user, an agent
talking over MCP, and someone in Claude Code all get the *same* thing:

```
run_* function (src/metalworks/research)
   │
   ├─ Python facade    Metalworks.<verb>()         src/metalworks/client.py
   ├─ CLI              metalworks research <verb>   src/metalworks/cli/__init__.py
   ├─ MCP tool         <verb>_from_report           src/metalworks/mcp/{tools,server}.py
   └─ Claude Code skill plugin/skills/<name>/SKILL.md
```

Parity is a rule, not a nicety: a primitive that only exists on the facade is a half-built feature.
When you add or change one, all four move together (the MCP side needs the tool body, the async
wrapper, *and* its entry in `_TOOL_WRAPPERS`). [CONTRIBUTING.md](https://github.com/Lab2A/metalworks/blob/main/CONTRIBUTING.md)
has the file-by-file checklist; `/pr-ready` verifies it.

## Deterministic core, LLM prose

The decisions are **pure, testable functions** — the model never makes the call. The `assess()`
verdict (GO / PIVOT / NO-GO) is a deterministic gap over demand strength and landscape saturation;
gap severity is service-assigned from distinct-author breadth; demand bands self-calibrate to the
run. The LLM writes only the human-facing *rationale* — the prose explaining a decision that was
already computed. This is what makes the output defensible and CI-testable: the same inputs always
produce the same verdict, and a unit test can pin the whole decision matrix without a model in the
loop.

## No-cite-no-claim

Every claim resolves to a real quote. A cluster carries verbatim `ResolvedCitation`s; a competitor
gap or a launch-copy line carries an `EvidenceRef` that resolves against `report.evidence`. If a
claim can't be backed by a real comment (or a grounded web finding), it is **dropped, not shipped** —
no hallucinated competitors, no invented quotes, no confident-looking output built on nothing. This
is the trust property the whole product rests on.

## Lean core, lazy extras

The core depends only on `pydantic`, `httpx`, `typer`, and `rich`. Everything heavier — the provider
SDKs, `duckdb`, `supabase`, `mcp` — lives behind an [extra](/docs/installation) and is **lazy-imported
inside the function that needs it**, never at module top level. So `import metalworks` is free and
pulls in zero provider modules (CI asserts this on a bare install), and a missing extra raises a
`MissingExtraError` carrying the exact `pip install` command rather than a raw `ModuleNotFoundError`.

## Swappable protocols

Underneath the facade, each external dependency is a small versioned protocol with thin adapters:
`ChatModel` / `GroundedChatModel`, `SearchProvider`, `EmbeddingProvider`, and the typed storage repos.
Bring your own and the rest of the pipeline doesn't care — see [Extending](/docs/extending) and
[Protocols](/docs/protocols). Conformance suites (`metalworks.testing.check_all_repos`,
`FakeChatModel`) hold your adapter to the same behavior the built-ins demonstrate.

## Offline by default

The test suite runs with no network: `pytest-socket` blocks sockets, and tests needing the real
network are marked `network` and deselected by default. Synthesis is exercised for real against
fixtures using `FakeChatModel` (scripted per output model — it raises on an unscripted call so drift
is caught, never silently nulled), `FakeEmbedding`, and `MemoryStores`. A test that needs a live
service is the exception, not the rule.

---

Next: the [protocols reference](/docs/protocols) for the exact seams, or
[CONTRIBUTING.md](https://github.com/Lab2A/metalworks/blob/main/CONTRIBUTING.md) for the
file-by-file workflow and the pre-PR gate.
