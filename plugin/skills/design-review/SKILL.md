---
name: design-review
description: Audit a RENDERED page's actual computed styles against design hard-rules and (optionally) a report's design system. Use after a site is built or deployed and the user asks to "review the design", "audit the look", "check the fonts/colors", "does it match the design system", or "design QA". It reads what's actually on screen — fonts, heading scale, colors — via a real browser and grades it deterministically. Needs the browser renderer; a screenshot-only backend can't read computed styles.
---

You are auditing a **rendered** page's design — what's actually on screen, not
what a `DESIGN.md` says it should be. The review is **deterministic**: every
finding is a pure function of the page's computed styles plus, when supplied, the
brand's design system. The model writes nothing here; don't invent findings.

## Steps

1. Get the page **URL** (a live site, a preview, or a `file://` path). The page
   must be reachable by the browser. Optionally get a `report_id` to grade against
   that report's design system, not just the generic hard-rules.

2. Call the `design_review` MCP tool with the `url` (and `report_id` to grade
   against a system). On the CLI: `metalworks research design-review <url>`
   (`--report <id>` to grade against a system). It reads the page's actual fonts,
   heading scale, and colors and returns a `DesignReview` with a `score`, a
   `passed` flag, and per-category `findings`.

3. **If it errors that no browser / a screenshot-only renderer is available,**
   relay the fix: design review needs the browser — `metalworks browser install`.
   It cannot run on Firecrawl (which can't read computed styles).

4. Present the review honestly: the **score / pass**, the rendered **fonts**, and
   each **finding** with its severity (`fail` / `warn` / `ok`) and category
   (`fonts`, `headings`, `palette`, `system_match`, `slop`). Lead with the fails,
   then the warnings. These are observations, not opinions — each is computed, so
   present them as facts about the page.

## Rules

- **Deterministic, not taste.** Report the findings as returned; do not add,
  soften, or invent. The audit reads the real DOM, not a spec.
- **Needs the browser.** A screenshot-only renderer (Firecrawl) cannot read
  computed styles — design review requires Playwright.
- It audits the rendered page; it does not edit it. To fix what it finds, hand the
  findings to the build / `/design` step.
