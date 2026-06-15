---
title: "Content & SEO"
description: "Turn your demand report into a content plan — one page per real demand theme, formatted answer-first and citing the actual Reddit threads, so AI search engines (ChatGPT, Perplexity, Google's AI answers) cite you."
---

Turn your demand report into a content plan: **one page per real demand theme, written so AI
search engines (ChatGPT, Perplexity, Google's AI answers) cite you.** Each page is the
genuinely-best answer to a question people actually asked, citing the real Reddit threads that
surfaced it.

To be clear up front: this is a structural plan for citable content, **not an SEO ranking
guarantee.**

`content_plan` is fully deterministic — it's instant, free, and gives the same result every time
(no AI guessing): **no model, no embeddings, no network, no API key.** It's a pure projection of
the report, so nothing is invented and no ranking is promised.

```python
from metalworks import Metalworks
mw = Metalworks()
research = mw.research("an affordable, jitter-free focus supplement for developers")

content = mw.content_plan(research)          # ContentPlan — deterministic, zero-key
for page in content.pages:
    print(page.target_phrase, page.page_kind)
    print("  ", page.stat_anchors)           # {'distinct_authors': N, 'mentions': M}

content.citation_strategy.reddit_targets     # the real Reddit permalinks to cite
content.citation_strategy.prompt_set         # example prompts to check citability against
```

From the CLI (`report-id` comes from `metalworks research list`):

```bash
metalworks research content-plan <report-id>
```

## What you give it / what you get back

**You give it:** a finished `Research` bundle (the report lives on `.demand`). That's all — no
keys, no model.

**You get back:** a `ContentPlan` with one `ContentPage` per ranked demand cluster, plus a
`CitationStrategy`. Every field is taken straight from the report:

- **`target_phrase`** — the cluster's own claim, normalized. Never a conjured keyword.
- **`page_kind`** — the page template (comparison, guide, or answer), read from that phrase:
  `comparison` (vs/versus/or/best), `guide` (how/guide/tips), otherwise `answer`.
- **`stat_anchors`** — the real numbers to cite (how many people, how many mentions): the
  cluster's distinct-author and mention counts, so the page brief is as honest as the demand
  behind it.
- **`faq`** — built verbatim from the report brief's sub-questions, each with an empty answer slot
  for a citable answer to fill. The plan marks the slot; it never fabricates the answer.
- **`outline`** — a fixed, answer-first section list: *What people actually want → Common
  approaches → The honest answer → FAQ.*

## Why answer-first, and why real permalinks

Reddit is one of the most heavily cited sources in AI search engines, so the legitimate play is
to write the genuinely-best answer to a real question and cite the real threads that surfaced it.
Two choices make a page citable:

- **Answer-first formatting** plus a **FAQPage JSON-LD** stub (structured data that helps AI
  search engines quote you), so an assistant can lift a clean, self-contained answer.
- A `CitationStrategy` whose `reddit_targets` are the **actual permalinks** from your report's top
  clusters — disclosed, real sources to cite, not placeholders. Its `prompt_set` holds example
  citability prompts derived from the target phrases.

Render the typed plan into shippable artifacts, both built mechanically from typed fields:

```python
from metalworks.research.marketing import render_content_markdown, render_faq_jsonld

md     = render_content_markdown(content)   # a markdown outline pack
jsonld = render_faq_jsonld(content)         # a schema.org FAQPage stub
```

## When the result is thin

A content plan is only as deep as the report behind it: thin demand → few clusters → few pages.
Because every value is projected from the report — no invented keywords, real stat anchors, real
permalinks — the plan is exactly as defensible as the demand research.

This is the legitimate way to get cited — the opposite of astroturf. Citing real permalinks and
writing the best answer is authentic, disclosed work. Fake personas and invented backstories are
excluded by design and prohibited by the
[usage policy](https://github.com/Lab2A/metalworks/blob/main/USAGE_POLICY.md).

---

Next: the authentic [Reddit engagement](/docs/reddit-engagement) loop — find threads worth
joining and draft honest, disclosed replies. Or draft your [launch assets](/docs/launch) from the
same report. See also [why you can trust the output](/docs/how-it-works).
