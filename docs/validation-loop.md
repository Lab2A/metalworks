---
title: "Validation loop"
description: "Turn a fuzzy idea into an honest build/don't-build call. metalworks runs a loop — frame the idea, measure demand, map what already exists, then deliver a GO / PIVOT / NO-GO verdict grounded in real quotes — and loops back on PIVOT toward the under-served angle until you hit a GO or run out of road."
---

**Find out whether your idea is worth building — and if not, where to aim instead.**

A demand report tells you what people want. The validation loop goes further: it weighs that
demand against what people can *already* get, and gives you a straight verdict — **GO**, **PIVOT**,
or **NO-GO** — with every claim backed by a real quote. On a PIVOT it hands you the under-served
angle to try next, and loops.

```
ideate  →  demand  +  landscape  →  assess (GO / PIVOT / NO-GO)
  ▲                                        │
  └──────────────  PIVOT  ─────────────────┘
```

The verdict is computed deterministically from the evidence (demand strength vs. how crowded the
landscape is), so it's defensible and reproducible — the model only writes the explanation, never
the decision.

## Two ways in

- **Idea-first** — you have an idea ("a jitter-free focus app for devs"). metalworks sharpens it
  into a testable hypothesis and runs the loop.
- **Evidence-first** — you have a space, not an idea ("what should I build for night-shift
  nurses?"). metalworks surfaces the real pains as candidate ideas, each grounded in a complaint,
  and you pick one.

## Run the whole loop

One call runs it end to end (headless, auto-deciding at each gate using the computed verdict):

<CodeGroup>

```text Claude Code
Validate this idea end to end: "a jitter-free focus supplement for developers"
```

```python Python
from metalworks import Metalworks

mw = Metalworks()
result = mw.validate("a jitter-free focus supplement for developers")

print(result.outcome)          # "go" | "no_go" | "exhausted"
for round in result.decision_log:
    print(round.iteration, round.decision, "→", round.idea)
```

```bash CLI
metalworks research validate "a jitter-free focus supplement for developers"
```

</CodeGroup>

In Claude Code the loop is **interactive** — it pauses at each verdict and you make the GO / PIVOT /
NO-GO call (you have context the corpus doesn't). The Python and CLI forms run `--auto`, taking the
computed recommendation at each gate.

## Or drive the stages yourself

The loop is just four composable primitives. Run them one at a time when you want control:

### 1. Ideate — frame the idea

<CodeGroup>

```text Claude Code
I have an idea — help me sharpen it: a focus app for developers
```

```python Python
sketch = mw.ideate("a focus app for developers")
print(sketch.hypothesis)       # the sharpened, testable version
report = mw.research(sketch.brief)   # run demand on it
```

```bash CLI
metalworks research ideate "a focus app for developers"
```

</CodeGroup>

Evidence-first instead? Surface the forks from a report and pick one:

<CodeGroup>

```text Claude Code
Show me the real pains in this report and which to build for: <report_id>
```

```python Python
ideas = mw.ideate_from_evidence(report)
for sketch in ideas.sketches:
    print(sketch.idea, "—", sketch.hypothesis)
```

```bash CLI
metalworks research ideate --from-report <report_id>
```

</CodeGroup>

### 2. Landscape — what already exists

The competitor map plus an empirical scan of real shipped products, and the cost of doing nothing:

<CodeGroup>

```text Claude Code
What already exists for this report? <report_id>
```

```python Python
landscape = mw.landscape(report)
print(landscape.competitor_map.status_quo_alternative)   # the do-nothing cost
for product in landscape.existing_solutions:
    print(product.name, product.traction)
```

```bash CLI
metalworks research landscape <report_id>
```

</CodeGroup>

### 3. Assess — the verdict

<CodeGroup>

```text Claude Code
Is this worth building? Give me the verdict for <report_id>
```

```python Python
assessment = mw.assess(report, landscape)
print(assessment.decision)              # GO | PIVOT | NO_GO
print(assessment.gap.reasoning)
if assessment.pivot_target:
    print("pivot to:", assessment.pivot_target.target_id)
```

```bash CLI
metalworks research assess <report_id>
```

</CodeGroup>

## How the verdict is decided

The decision is a gap function, not an opinion:

- **Demand strength** — how many distinct people voiced the pain (50 voices outweighs one viral post).
- **Landscape saturation** — how crowded the supply is (named competitors + real shipped products),
  held down by competitors who badly miss something (an opening).

| Demand | Landscape | Verdict |
| --- | --- | --- |
| moderate+ | open | **GO** |
| moderate+ | crowded, but an under-served fork exists | **PIVOT** (aimed at that fork) |
| thin, or crowded with no opening | — | **NO-GO** |

One honest guardrail: if the landscape scan couldn't fully ground (no product source configured),
a hard **GO** is withheld — absence of evidence is not absence of competition.

## Not to be confused with

`metalworks discovery` is a different feature — it finds Reddit threads where you can helpfully
reply. The validation loop is about deciding *what to build*.

## Next

- [Demand research](/docs/demand-research) — the pull signal the loop builds on.
- [Competitors](/docs/competitors) — the lean competitor map on its own.
- [Positioning](/docs/positioning) — once you have a GO, find the angle.
