---
title: "Build guide"
description: "Turn a validated demand report into a grounded BuildSpec and a cite-or-die build harness — metalworks specs and scaffolds; your own coding agent builds."
---

The Build stage (Pillar D) is the bridge between "we proved the demand" and
"someone is writing the code." It takes a finished `DemandReport` and produces
two things: a grounded **`BuildSpec`** — a short feature list where every feature
maps to a real demand cluster and carries that cluster's verbatim quotes — and a
deterministic **on-disk harness** that the user's OWN coding agent then builds
inside.

<Note>
**metalworks specs and scaffolds; it does NOT write product code.** There is no
stage here that emits React components, API routes, or schema migrations. The
Build pillar's job is to carry the validated demand forward — as a spec and a
frozen evidence table — so the agent that *does* write the code (your Claude
Code, in the scaffolded repo) cannot drift from what real users actually asked
for. `--base` records a stack *hint*; metalworks never vendors a starter.
</Note>

This is the same provenance discipline as the research vertical, moved one stage
downstream. Research enforces `no-quote-no-theme` (a cluster with no verified
quote is never shipped). Build enforces its sibling rule, **`no-cite-no-feature`**:
a feature the model proposed with no real demand cluster behind it is dropped at
assembly. The model cannot smuggle in demand nobody voiced.

## Generate the spec

The facade is two calls — spec, then scaffold:

```python
from metalworks import Metalworks

mw = Metalworks()                       # provider from your env key

# 1. Derive the grounded spec from a finished report (+ positioning + surface):
spec = mw.build_spec(research, positioning, surface="web", stack="next-shipfast")

# 2. Write the build harness for your coding agent to work inside:
paths = mw.scaffold(spec, research, "./build", base="next-shipfast")
```

`build_spec` returns a `BuildSpec`; `scaffold` writes the harness to disk and
returns the `list[Path]` it wrote. The two are kept separate on purpose: speccing
is one LLM call, scaffolding is pure deterministic templating (no model, fully
reproducible).

### From the CLI

`metalworks build init` does both in one command — it derives the positioning,
specs the build, and scaffolds the harness:

```bash
# report_id comes from `metalworks research list`
metalworks build init <report_id> --dest ./build --surface web --base next-shipfast
```

| Flag | Default | What it does |
| --- | --- | --- |
| `--dest` / `-d` | `./build` | Directory to scaffold the harness into. |
| `--surface` | `web` | Target surface: `web` · `mobile` · `cli` · `api` · `sdk` · `browser_extension` · `desktop`. |
| `--base` | `empty` | Stack **hint** recorded in the spec (e.g. `next-shipfast`). Not vendored boilerplate. |

The `report` argument is a stored report id (from `metalworks research list`) or
a path to a `report.json`. When the spec comes back `partial`, the command prints
the caveat before scaffolding — a partial spec still writes (so you can read the
evidence), but it is a stub, not a buildable plan.

### From an MCP host

The `build_spec` MCP tool (Tier-2 — needs a chat + embedding key) returns the
spec JSON for a host model to read:

```jsonc
// build_spec(report_id="rep_…", surface="web", stack="next-shipfast")
{ "build_spec": { "spec_id": "spec:rep_…", "features": [ … ], "personas": [ … ], … } }
```

The MCP tool **does not write files** — scaffolding to disk is the `metalworks
build init` CLI's job. (In the scaffolded repo, the bundled `spec-from-report`
skill uses this same tool to re-spec without leaving the build.)

### The raw functions

If you want the stages without the facade:

```python
from metalworks.build import build_spec_from_report, scaffold

spec  = build_spec_from_report(deps, report, positioning, "web", stack="next-shipfast")
paths = scaffold(spec, report, dest, base="next-shipfast")
```

## What's in a BuildSpec

A `BuildSpec` FKs to exactly one report via `report_id`; every `EvidenceRef` it
carries resolves against that report's evidence. It has three grounded parts.

```python
spec.features        # list[FeatureSpec]  — each maps to a demand cluster, carries its quotes
spec.personas        # list[BuildPersona] — the ICP, from the report's segments
spec.pricing_tiers   # list[PricingTier]  — copied through from the report's price evidence
spec.partial, spec.caveat   # honesty signal when grounding is thin
```

The grounding rules — these are what make the spec trustworthy:

- **Features — `no-cite-no-feature`.** One LLM call maps the report's demand
  clusters to candidate features, tagging each with the `source_cluster_rank` it
  derives from. The builder then attaches *that cluster's* verified quotes as the
  feature's evidence. A feature whose source cluster is invalid or quote-less is
  **dropped** — the model cannot invent a feature with no cluster behind it. What
  survives is only what real users asked for (capped at 8 core features).
- **Personas — grounded ICPs.** Derived from the report's audience segments, each
  tied to a real Reddit voice. A persona must carry a resolvable ref; if the
  report has no quote anywhere, none are emitted.
- **Pricing — copy-through, never recomputed.** Tiers are copied straight from the
  report's price evidence (`Starter` at the low end of observed willingness to
  pay, `Pro` at the high end). No price signal in the report → no tiers. A price
  the report can't back never ships.

One more honesty guarantee: an infra error (a 404, an auth failure, a network
blip during the LLM call) **propagates** as a real failure — it is never silently
relabelled a thin-demand `partial`. The only honest `partial` is a successful
call whose features all failed to ground.

## The scaffolded harness

`scaffold()` writes a build harness the downstream agent works inside. It is pure
templating — deterministic, idempotent (re-running overwrites in place), no LLM —
and it carries the evidence forward so the build can't drift:

```text
build/
  CLAUDE.md                        cite-or-die Rule 0 + how to build
  docs/
    SPEC.md                        features / personas / pricing, each cited
    EVIDENCE.md                    FROZEN quote + permalink table (the spine)
  .claude/
    skills/
      scaffold-startup/SKILL.md    stand up the product, feature by feature
      spec-from-report/SKILL.md    re-spec via the metalworks MCP server
      cite-or-die/SKILL.md         the no-cite-no-claim rule, explained
    scripts/cite_or_die.py         the PostToolUse lint that enforces it
    hooks.json                     wires the lint in on Edit/Write/MultiEdit
  .mcp.json                        points the agent back at metalworks' MCP server
```

What each piece is for:

- **`CLAUDE.md`** — the downstream agent's top-level rule file. **Rule 0 is
  cite-or-die**, stated before anything else: every feature, persona, and pricing
  claim in `SPEC.md` traces to a verbatim voice in `EVIDENCE.md`, and any new
  user-facing claim must cite an evidence id. Then a short "how to build" — pick
  the stack hint, stand up the surface, build the features in order, keep
  `EVIDENCE.md` frozen.
- **`docs/SPEC.md`** — the buildable plan: features, personas, pricing, each line
  carrying its citations (`q:…` quotes, `p:…` prices). If the spec is partial, it
  opens with a "Partial spec" banner instead of pretending to be buildable.
- **`docs/EVIDENCE.md`** — the **frozen** verbatim quote + permalink table. Every
  id `SPEC.md` cites appears here with its exact Reddit text and a source link.
  This is the ground truth the build must not drift from — the harness tells the
  agent not to edit it; to add a feature, go back to metalworks and re-run the
  research.
- **The build-pack** (`.claude/skills/`) — a *second* skill pack that LANDS in the
  scaffolded repo (distinct from metalworks' own plugin skills). `scaffold-startup`
  walks the agent through standing the product up; `spec-from-report` re-derives
  the spec via MCP when it's thin; `cite-or-die` explains the rule.
- **`cite_or_die.py` + `hooks.json`** — a PostToolUse hook that runs the lint
  whenever the agent edits a markdown/copy file. It **hard-fails (exit 2)** on a
  dangling citation (an id not in `EVIDENCE.md`) and **warns** on a claim with no
  citation at all.
- **`.mcp.json`** — wires the metalworks MCP server into the build repo, so the
  agent can re-spec or pull more evidence without leaving the project.

<Warning>
`scaffold()` raises `ValueError` if the spec was not built from the report you
pass it (an FK mismatch). Otherwise the frozen `EVIDENCE.md` would render the
spec's refs against the wrong report and silently fill with `UNRESOLVED` rows.
Always scaffold a spec against the report it was built from.
</Warning>

## How your coding agent uses it

Once the harness is written, metalworks is done. The hand-off:

1. **Open the scaffolded directory in your coding agent** (Claude Code, with the
   harness's `CLAUDE.md` and build-pack now in scope).
2. **Run `/scaffold-startup`.** The agent reads `docs/SPEC.md` (what to build) and
   `docs/EVIDENCE.md` (why — the proof), picks the stack hint's starter, stands up
   the surface, and builds the features top to bottom — each one delivering a
   demand a real user voiced.
3. **The cite-or-die lint holds it to the evidence.** As the agent writes
   user-facing copy, the PostToolUse hook runs `cite_or_die.py` on the edited
   files. A headline or value prop that cites a dangling id fails the build; the
   agent has to find the real supporting quote in `EVIDENCE.md` or drop the claim.

```bash
# the lint, run by hand before shipping copy:
python .claude/scripts/cite_or_die.py docs/SPEC.md
```

The result: every feature in the spec gets built, every claim on the page traces
back to a real Reddit voice, and nothing on the site asserts demand the report
did not find.

## `no-cite-no-feature`

This rule is the whole reason the Build pillar exists, so it's worth stating
plainly. It is the Build-stage sibling of research's `no-quote-no-theme`.

> A model is never the source of demand. The LLM clusters, phrases, and proposes
> features — but every feature that survives into the spec is one that maps to a
> demand cluster the research pipeline independently verified, and it carries that
> cluster's exact quotes. A feature with no resolvable evidence is dropped at
> assembly.

It holds at two layers. The **spec** drops un-grounded features when it assembles
the `BuildSpec`. The **scaffold** then carries the surviving evidence into a
frozen `EVIDENCE.md`, and the cite-or-die lint enforces the rule on every edit the
downstream agent makes — at the SPEC / feature / copy level, **not** per line of
generated code (that would be traceability theater). The discipline you proved in
research follows the demand all the way into the build.

---

- See [Structural provenance](/docs/explanation-provenance) for why `no-quote-no-theme`
  — the rule `no-cite-no-feature` mirrors — makes fabricated evidence impossible
  by construction.
- See [The arc](/docs/the-arc) for where the Build stage sits in the full
  research-to-launch pipeline.
