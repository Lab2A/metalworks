---
title: "Build spec"
description: "Turn the demand report you already ran into a feature spec and a ready-to-build project. metalworks writes the spec and scaffolds the repo — your own coding agent writes the product code."
---

You proved the demand. Now turn it into a plan your coding agent can build from. `build_spec`
maps the demand report you already ran to a feature list — every feature *grounded* (backed by a
real quote) — and `scaffold` writes a project on disk for your agent (Claude Code, Cursor, etc.)
to build inside.

**metalworks writes the spec and scaffolds the project. It does not write your product code.**
No React components, no API routes, no migrations. It carries the demand forward — as a spec and
a frozen quote table — so the agent that *does* write the code can't drift from what real users
asked for.

<CodeGroup>

```text Claude Code
# uses the report you already made
/build-spec
```

```python Python
from metalworks import Metalworks

mw = Metalworks()
research = mw.research("an affordable, jitter-free focus supplement for developers")
positioning = mw.positioning(research)

# 1. Spec the build from a finished report (+ positioning):
#    surface="auto" (default) lets the spec pick the surface + explain why;
#    pin it (surface="cli") when you already know the build shape.
spec = mw.build_spec(research, positioning, stack="next-shipfast")
print(spec.surface, "—", spec.surface_rationale)   # the chosen surface + why
for feature in spec.features:
    print(feature.title, "—", feature.rationale)   # each tied to real demand
for screen in spec.screens:
    print(screen.name, "→", screen.feature_ids)     # each mapped to real features

# 2. Scaffold the project your coding agent builds inside:
paths = mw.scaffold(spec, research, "./build", base="next-shipfast")
```

> **`stack` vs `base`** — same value, two names, by design: the spec **records** the
> chosen stack as `stack`, and `scaffold` **consumes** it as its `base` template. It's
> not a typo — pass the same template id to both.

```bash CLI
# report-id comes from `metalworks research list`
# --surface auto (the default) lets the spec pick + explain the surface
metalworks build init <report-id> --dest ./build --surface auto --base next-shipfast
```

</CodeGroup>

| Flag | Default | What it does |
| --- | --- | --- |
| `--dest` / `-d` | `./build` | Directory to scaffold the project into. |
| `--surface` | `auto` | `auto` lets the spec pick + explain, or pin one: `web` · `mobile` · `cli` · `api` · `sdk` · `browser_extension` · `desktop`. |
| `--base` | `empty` | Stack **hint** recorded in the spec (e.g. `next-shipfast`). Not vendored boilerplate. |

## What you give it / what you get back

**You give it:** a finished `Research` bundle (the report on `.demand`), your positioning, and a
target surface (`"auto"` to let the spec choose). The `report` argument to the CLI is a stored
report id or prefix (`metalworks research list`), a path to a `report.json`, or — omitted entirely
— your latest run.

**You get back:** a `BuildSpec` — each line tied to a real quote:

```python
spec.surface             # SurfaceKind — the surface to build (chosen or pinned)
spec.surface_rationale   # one line on why that surface (set only when surface="auto")
spec.features            # list[FeatureSpec]  — each maps to a demand cluster, carries its quotes
spec.screens             # list[Screen] — the UX skeleton, each mapped to real feature_ids
spec.personas            # list[BuildPersona] — the ICP, from the report's audience segments
spec.pricing_tiers       # list[PricingTier]  — copied from the report's price evidence
spec.partial, spec.caveat   # honesty signal when the grounding is thin
```

The grounding rules are what make the spec safe to build from:

- **Features.** The model proposes features from the demand clusters; metalworks attaches each
  cluster's real quotes as the feature's evidence. A feature with no real cluster behind it is
  **dropped** — the build stays tied to real demand. What survives is only what people actually
  asked for (capped at 8 core features).
- **Build order is grounded, not arbitrary.** Features come back ordered by the demand strength of
  the cluster behind them (`source_cluster_rank`, 1 = strongest). `features[0]` is the spine — the
  feature to build first — and `SPEC.md` renders them as a numbered build order. The sequence is a
  deterministic read of real demand, not a model's guess at importance.
- **Surface.** With `surface="auto"` the same model call that maps features also picks the surface
  (`sdk` / `web` / `mobile` / `cli` / ...) and returns a one-line `surface_rationale`, grounded in
  who asked and how technical they are — no generic web-app default, no second model call. Pin a
  surface and the spec honors it and skips the pick (no rationale).
- **Screens.** The UX skeleton is sketched **after** the features exist, so each screen maps to real
  `feature_id`s (the old standalone skeleton was blind to what got built). A screen inherits its
  feature's evidence: it ships `validated` when a real voice backs it, an unvalidated hypothesis
  otherwise. Shell screens (auth/settings) are flagged `scaffolding` — needed by every product, not
  a demand bet.
- **Personas.** Derived from the report's audience segments, each tied to a real voice.
- **Pricing.** Tiers are copied straight from the report's price evidence (`Starter` at the low
  end of observed willingness to pay, `Pro` at the high end). No price signal → no tiers.

Then `scaffold` writes the project — pure deterministic templating, no model, idempotent:

```text
build/
  CLAUDE.md                        the build rules + how to build, for your agent
  docs/
    SPEC.md                        surface / features / screens / personas / pricing, each backed by a quote
    EVIDENCE.md                    FROZEN quote + permalink table — the ground truth
  .claude/
    skills/                        scaffold-startup, spec-from-report, the citation rule
    scripts/cite_or_die.py         a check that blocks your agent from shipping a claim with no quote behind it
    hooks.json                     runs the lint on every Edit/Write
  .mcp.json                        points the agent back at metalworks' MCP server
```

`EVIDENCE.md` is the frozen verbatim quote + permalink table — every id `SPEC.md` cites appears
here with its exact Reddit text and a source link. The agent must not edit it; to add a feature,
go back to metalworks and re-run the research.

## How your coding agent uses it

Once the project is written, metalworks is done. The hand-off:

1. **Open the scaffolded directory in your coding agent** (the project's `CLAUDE.md` and skills
   are now in scope).
2. **Run `/scaffold-startup`.** The agent reads `docs/SPEC.md` (what to build) and
   `docs/EVIDENCE.md` (the proof), picks the stack hint's starter, stands up the surface, and
   builds the features in order — top is the spine (strongest demand), each one a demand a real
   user voiced.
3. **The lint holds it to the evidence.** As the agent writes user-facing copy, a hook runs
   `cite_or_die.py` on the edited files. A headline that cites an id not in `EVIDENCE.md` fails
   the build; the agent has to find the real supporting quote or drop the claim.

```bash
# the lint, run by hand before shipping copy:
python .claude/scripts/cite_or_die.py docs/SPEC.md
```

## When the result is thin

When the report can't back a buildable plan, the spec comes back `partial` with a `caveat`. A
partial spec still writes (so you can read the evidence), but it opens with a "Partial spec"
banner instead of pretending to be buildable. The CLI prints the caveat before scaffolding.

One honesty guarantee: an infra error (a 404, an auth failure, a network blip during the model
call) surfaces as a real failure — it's never silently relabelled a thin-demand `partial`.

`scaffold()` raises `ValueError` if the spec wasn't built from the report you pass it — otherwise
the frozen `EVIDENCE.md` would resolve the spec's refs against the wrong report. Always scaffold a
spec against the report it came from.

---

Next: draft your [launch assets](/docs/launch) and a [content & SEO plan](/docs/content-seo)
from the same report. Or read [why you can trust the output](/docs/how-it-works) — the rule that
keeps every feature tied to a real quote.
