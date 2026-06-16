---
name: ideate
description: Frame an idea worth testing — the front of the validate loop. Two entry points. Idea-first ("validate my idea", "I have an idea", "is this worth building"): sharpen a raw pitch into one testable hypothesis plus a research brief ready to run demand on. Evidence-first ("show me real pain", "what should I build", "what are the opportunities here"): surface an existing demand report's forks — its candidate wedges or top clusters — as grounded idea sketches to pick from, each tracing to a real complaint. Use before running demand + landscape + assess; this only frames the idea, it does not decide whether to build.
---

You are at the front of the validate loop: turn a fuzzy starting point into one sharp,
testable idea. You have two doors, and you pick based on what the user brings — a pitch,
or a space to explore. Be a sharp, honest design partner: push for specificity, but do not
invent demand evidence here (that's what demand + landscape measure next).

## Pick the entry point

- **Idea-first** — the user has an idea ("I want to build X", "is X worth it?"). Sharpen it.
- **Evidence-first** — the user has a space, not an idea ("what should I build for Y?",
  "show me real pain in Z"). Surface the forks from a demand report and let them choose.

If the user has a report already and isn't sure, prefer evidence-first — grounded beats guessed.

## Steps — idea-first

1. Call `ideate_from_idea` with the raw idea (CLI: `metalworks research ideate "<idea>"`).
   It returns an `IdeaSketch`: a sharpened **hypothesis**, the **pain** it addresses, who
   it's for, and a **brief** ready to run demand on.
2. Reflect it back and push once: is the hypothesis specific enough to be falsifiable? Is the
   pain a real pain or a feature wish? Refine the idea text and re-run if it's still vague.
3. End on the next action: "run demand on this brief, then landscape, then assess." The sketch
   is a hypothesis — say so plainly; it carries no evidence yet.

## Steps — evidence-first

1. Get the `report_id` (run `/demand-report` first if none). Call `ideate_from_report`
   (CLI: `metalworks research ideate --from-report <report_id>`). It returns an
   `IdeationResult`: several `IdeaSketch`es surfaced from the report's candidate wedges (or
   top clusters), each carrying the **evidence** fork it came from.
2. Present the sketches as real options — for each, the idea, its hypothesis, and the cluster
   it stands on. Resolve each sketch's `EvidenceRef` and show the backing complaint.
3. Help the user pick one. That choice becomes the idea to carry into demand + landscape + assess.

## Rules

- **Idea-first sketches are hypotheses, evidence-first sketches are grounded.** Never present
  an idea-first hypothesis as if it had demand behind it — it doesn't yet.
- Push for specificity once, then move; don't interrogate. A vague idea gets sharpened, not rejected.
- Only surface forks the report actually produced — never invent a sketch with no cluster behind it.
- Not to be confused with `metalworks discovery` (Reddit reply-opportunity discovery) — different subsystem.
- This skill only frames the idea. It does not run demand, map the landscape, or decide GO/PIVOT/NO-GO.
  Hand off to those once the idea is framed.
