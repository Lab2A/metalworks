---
title: "Marketing site"
description: "Generate a marketing page whose every claim is a verbatim quote from a real user, footnoted to the thread it came from — no AI prose, nothing invented."
---

**A landing page where every claim is a real quote.**

With a [demand report](/docs/demand-research) and your [positioning](/docs/positioning) in
hand, one call drafts a small marketing site — and renders it as a self-contained page you can
open. The copy isn't AI prose: every claim-bearing line is a word-for-word quote from a real
user, footnoted back to the thread it came from.

<CodeGroup>

```text Claude Code
/demand-report an affordable, jitter-free focus supplement for developers
/generate-site
```

```python Python
from metalworks import Metalworks

mw = Metalworks()
research = mw.research("an affordable, jitter-free focus supplement for developers")
positioning = mw.positioning(research)

site = mw.site(research, positioning)             # marketing copy, every line a real quote
for sec in site.sections:
    print(sec.role, f"[{sec.provenance}]", "→", sec.copy[:60])

html = mw.render_site(site, research)             # a self-contained index.html
open("index.html", "w").write(html)
```

```bash CLI
metalworks research site <report-id>
```

</CodeGroup>

`mw.site(...)` drafts a small marketing page; `mw.render_site(...)` turns it into one
self-contained `index.html` you can open. The copy isn't AI prose — **every
claim-bearing line is a word-for-word quote from a real user**, and each one renders
with a footnote linking back to the thread it came from, so any visitor is one
click from the real comment.

## What you give it / what you get back

| Field | What it is |
| --- | --- |
| `site.sections[].role` | What the section does: `hero`, `feature`, `objection`, `pricing`, `social_proof`, or `cta`. |
| `site.sections[].copy` | The text. For a claimed section it contains a verbatim fragment of a real quote. |
| `site.sections[].provenance` | `verbatim` (a cited real quote) or `connective` (claim-free glue between sections). |

The hero is built on the need the most distinct people raised — the broadest demand,
not the loudest single post. metalworks may add short connective lines to bridge
sections, but those carry no claims at all: any glue line that sneaks in a number or a
superlative like "best" or "only" is dropped, so unsourced claims can't slip in.

## When the result is thin

metalworks drops anything it can't back with a real quote. If a line doesn't exactly
match a stored comment, that section is removed rather than shipped on the model's
word. If nothing matches at all, the site comes back empty with `partial=True` and a
caveat — never an invented section, never a crash.

## Next

You have a site. Now turn the demand into a build plan and launch:
→ [Build spec](/docs/build-spec) · [Launch assets](/docs/launch) ·
[the full walkthrough](/docs/walkthrough) · [why you can trust the output](/docs/how-it-works)
