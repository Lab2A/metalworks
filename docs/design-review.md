---
title: "Design review"
description: "Audit a rendered page's actual computed styles — fonts, heading scale, colors — against design hard-rules and your design system. Deterministic, not taste."
---

**Audit what's actually on screen, not what a `DESIGN.md` says.**

The QA counterpart to the [design pillar](/docs/design-system). It opens a
rendered page in a real browser, reads its **actual computed styles** (the fonts,
heading scale, and colors the browser resolved), and grades them
**deterministically** — every finding is a pure function of the page, not an LLM
opinion. With a report, it also grades the page against that report's design
system.

<CodeGroup>

```text Claude Code
/design-review https://your-site.com
```

```python Python
from metalworks import Metalworks

mw = Metalworks()
review = mw.design_review("https://your-site.com")     # or pass system=… to grade against a brand
print(review.score, "/10", "—", "pass" if review.passed else "review")
for f in review.findings:
    print(f.severity, f.category, "—", f.detail)
```

```bash CLI
metalworks research design-review https://your-site.com
metalworks research design-review https://your-site.com --report <report-id>   # grade vs the system
```

</CodeGroup>

## What it checks

Deterministic hard-rules over the rendered styles:

- **Fonts** — more than three distinct families in use; a body face that's one of
  the AI-default *convergence-trap* fonts (Inter / Roboto / system-ui / …).
- **Headings** — a heading scale that isn't monotonically decreasing (h1 ≥ h2 ≥ h3).
- **System match** (when a report's design system is supplied) — whether the
  rendered body font actually matches the brand's typography choice.

## What you get back

| Field | What it is |
| --- | --- |
| `score` / `passed` | 0–10 (10 minus penalties); `passed` is true with no `fail`-severity findings. |
| `fonts` | The distinct font families actually rendered. |
| `headings` | The rendered h1/h2/h3 sizes. |
| `findings[]` | Each a `StyleFinding`: `severity` (`fail` / `warn` / `ok`), `category`, and a one-line `detail`. |
| `against_system` | Whether it was graded against a design system, not just the hard-rules. |

## Needs the browser

Design review reads computed styles, which requires a **script-capable** renderer
(Playwright):

```bash
pip install "metalworks[browser]"
metalworks browser install
```

A screenshot-only backend (Firecrawl) **cannot** read computed styles — design
review raises a clear error pointing you to install the browser.
