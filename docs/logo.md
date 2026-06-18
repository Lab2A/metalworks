---
title: "Logo"
description: "Generate five diverse, company-grade logo options for a validated idea — the model authors each SVG directly under a fixed house design system, one per design angle, and you pick."
---

**Turn a validated idea into a brand mark you can ship.**

Every other metalworks artifact is *grounded*: a claim traces to a real quote. A
logo is different — it is a designed object, not a claim — so this is the one place
metalworks lets the model author the geometry directly. It writes clean SVG under a
fixed house design system, and it does it five ways, so you get real options to
choose from rather than one take.

```bash
metalworks research logo                 # five options for your latest report, opens a picker
metalworks research logo rpt-abc123      # a specific report
metalworks research logo --name Tidal    # set the wordmark name (else one is generated)
metalworks research logo --out brand     # write the SVGs + picker.html into ./brand
```

## What you get

Up to five `LogoOption`s, each a self-contained SVG lockup (a mark plus a confident
wordmark) and the design angle that produced it:

| Angle | The move |
| --- | --- |
| `symbol` | One concept icon tied to what the company does, beside a wordmark. |
| `logotype` | The wordmark itself is the logo, with one custom letterform intervention. |
| `negative-space` | Two ideas fused, the second hidden in the negative space of the first. |
| `reference` | An original mark in the tradition of admired marks in the space. |
| `expressive` | A distinctive mark drawn from a vivid one-line art-direction brief. |

The CLI writes each option as an `.svg` and a `picker.html` that lays them out side
by side, then opens it. Pick one; the SVG drops straight into a
[marketing site](/docs/marketing-site) or a repo.

## Why five single passes, not a critique loop

Quality came down to two things, found empirically: a strong house design system
held constant, and **concept diversity**. Five independent passes, each a different
angle, beat a generate→critique→refine loop, which polished marks but sanded off
what made them distinctive and sometimes picked the blander concept. So the tool
generates diverse options and leaves the choice to you.

## The house design system

The taste is held constant in `metalworks.research.logo.TASTE`: one idea per mark,
two colors at most, clean construction, the wordmark as half the logo, legible at
favicon size. It is brand-agnostic and applies to any product.

## Honesty

An angle that returns no valid SVG is dropped, never faked; the `LogoSet` is marked
`partial` with a `caveat` naming what was dropped. Logos are *offered*, never
auto-selected — the choice is yours.

## In Claude Code and via MCP

The `/logo` skill and the `logo_generate` MCP tool expose the same capability:
`logo_generate(report_id, name?)` returns the `LogoSet` plus the picker HTML.
Generation needs a chat-model key; no embeddings required.

```python
from metalworks import config
from metalworks.research import build_logo_set, render_logo_picker_html

logos = build_logo_set(config.resolve_chat(), report, brand_name="Tidal")
for opt in logos.options:
    print(opt.angle, opt.concept)
open("picker.html", "w").write(render_logo_picker_html(logos))
```
