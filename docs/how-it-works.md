---
title: "Why you can trust the output"
description: "metalworks never invents demand. Every claim links to a real Reddit comment, anything it can't back is dropped, and it tells you plainly when there's no opening."
---

Most AI market-research tools have the same flaw: ask them anything and they'll produce a
confident, plausible answer — whether or not it's true. metalworks is built the opposite
way. **The model phrases and organizes; it is never the source of a fact.**

## The promise

1. **Every claim links to a real comment.** Each finding, quote, competitor gap, marketing
   line, and feature carries a link to the actual Reddit thread it came from. You can open
   it and read it yourself.
2. **Anything it can't back, it drops.** If the tool can't tie a statement to a real quote
   (or, for web facts, a real source URL), that statement never ships. It isn't softened or
   guessed — it's removed.
3. **It tells you when there's nothing there.** When the demand is thin or there's no real
   opening, metalworks says so and stops, instead of manufacturing an opportunity to please
   you.

That's what makes the output safe to act on. A "go" from metalworks is one you can defend,
line by line, back to real people.

## How it actually works

- **Quotes are matched, not paraphrased.** A quote in a report is the exact text of a real
  stored comment. If a piece of generated text doesn't match a real comment, it's dropped.
- **Numbers are counted, not asserted.** "312 people raised this" comes from counting
  distinct authors, never from a model estimate.
- **Web facts carry their real source.** When a finding comes from the web, its URL comes
  from the search tool's citation data — never from model prose. No source, no finding.
- **Every later step inherits this.** Positioning, the marketing site, the build spec,
  launch copy — each reads from the same report and links every claim back to it. The chain
  runs from a real comment all the way to the line on your landing page.

This holds even if you [swap in your own model](/docs/custom-chatmodel): the checking
happens in the pipeline, around the model, not inside it.

## What it deliberately won't do

metalworks is for honest, disclosed work. It will not fabricate user personas or backstories,
write fake reviews, or post on your behalf without your explicit, per-action approval. The
Reddit tools draft; a human always approves the post. See the
[usage policy](https://github.com/Lab2A/metalworks/blob/main/USAGE_POLICY.md).

Next: the [data model](/docs/data-model) shows the actual objects (the report, its findings,
the quotes) you get back.
