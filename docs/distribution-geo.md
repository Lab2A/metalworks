---
title: "GEO / LLM-citability"
description: "Become the answer AI engines cite — participation targets, citability probes, and answer-first briefs, all grounded in your demand report."
---

**Get cited by AI — built from the demand you found.**

GEO ("get cited by AI") is a compounding distribution *stream*, not a separate pillar. Reddit is
the #1 AI-cited domain and most AI citations are Q&A threads, so the fastest path to being the
cited answer is to participate in the threads your audience is *already* asking in and to publish
answer-first content for the questions they ask. One call off a finished
[demand report](/docs/demand-research) turns it into a grounded GEO plan.

<CodeGroup>

```text Claude Code
/demand-report an affordable, jitter-free focus tool for indie developers
/distribution-geo
```

```python Python
from metalworks import Metalworks

mw = Metalworks()
research = mw.research("an affordable, jitter-free focus tool for indie developers")

plan = mw.geo(research)
for t in plan.participation_targets:
    print(t.community, "→", t.permalink)
    print("  why:", t.why)
for p in plan.citability_probes:
    print("probe:", p.prompt, "→", p.target_phrase)
for b in plan.answer_briefs:
    print("Q:", b.question, b.stat_anchors)
    print("  ", b.answer)
```

```bash CLI
metalworks distribution geo <report-id>
```

</CodeGroup>

## What you get back

A `GeoPlan` with three grounded streams:

- **`participation_targets`** — the real threads/communities to engage. Each `ParticipationTarget`
  carries a `community`, a real `permalink` (a verbatim `source_url` from a verified quote — never
  invented), the `why` (what that audience is asking, from a cluster claim), and a value-first
  `suggested_angle`.
- **`citability_probes`** — the conversational queries to test whether you're cited. Each
  `CitabilityProbe`'s `prompt` is a real question phrased the way someone would ask an answer
  engine, derived from a cluster claim (`target_phrase`). Run them against ChatGPT / Perplexity /
  Google AI and check for your citation.
- **`answer_briefs`** — the answer-first content to publish. Each `AnswerBrief` leads with the
  `question`, then a grounded `answer`, and carries `stat_anchors` (the cluster's real
  distinct-author / mention counts) plus `evidence_refs` that resolve against the report's evidence.

## The honesty contract

Participation targets and citability probes are **deterministic** — pulled straight from the
report's permalinks and cluster claims, never the model's imagination. The answer briefs' prose is
LLM-authored, but the answer is a factual claim, so **cite-or-die is correct here**: every brief's
`evidence_refs` resolve against `report.evidence`, and a brief whose evidence doesn't resolve is
dropped before it ships. The `stat_anchors` are the report's real counts.

GEO is a **compounding stream** — first citations take roughly three months. Treat this as a
patient play: show up value-first in the real threads, disclose your affiliation, never drop a bare
link. metalworks plans and drafts; a human runs it — nothing here posts.
