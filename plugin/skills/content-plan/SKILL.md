---
name: content-plan
description: Turn a finished demand report into a deterministic content/SEO plan — one page per ranked demand cluster, each with an answer-first outline, a FAQPage block built verbatim from the brief's must-address questions, and real distinct-author / mention counts as stat anchors. Plus a citation strategy that lists the actual disclosed Reddit permalinks to cite. Use after a demand report exists and the user asks "what should I write", "what content should we make", "what pages should we build", "give me an SEO plan", "how do we get cited by LLMs", or wants a content brief grounded in evidence rather than invented keywords. NO ranking promises.
---

You are projecting one demand report into a content/SEO plan. This is a PURE
DETERMINISTIC extraction — there is no LLM call, no embeddings, no keys. Every
page, phrase, FAQ, and citation target is *projected* from the report. You are
NOT brainstorming keywords or topics; the plan stands entirely on real demand
signal the report already verified.

## Steps

1. Get the `report_id`. If the user hasn't run a report yet, point them at
   `/demand-report` first — the content plan needs a finished report to project
   from.

2. Call the `content_plan_from_report` MCP tool with the `report_id` (or, on the
   CLI, run `metalworks content-plan <report_id>`). It is zero-key and
   deterministic — it returns a `ContentPlan` immediately, no job pattern.

3. Walk the plan honestly:
   - One **page per ranked cluster**, in rank order. For each page show the
     `target_phrase` (the cluster's own claim, normalized — not an invented
     keyword), the `page_kind` (`comparison` / `guide` / `answer`), and the
     `outline` (answer-first sections ending in an FAQ block).
   - Surface the **stat anchors** — the real `distinct_authors` and `mentions`
     counts. This is the evidence density that makes the content credible; lead
     with it, don't bury it.
   - Show the **FAQ** items. They are copied verbatim from the brief's
     `must_address` questions — the answers are left empty on purpose (authored
     later, never fabricated by the plan).

4. Present the **citation strategy**:
   - `reddit_targets` are the REAL, disclosed quote permalinks from the top
     clusters. These are the sources to cite in the content — show them as links.
   - `prompt_set` are example prompts a consumer might ask an assistant; the goal
     is that this content becomes the citable answer.

5. Offer the renderers when useful: a markdown outline pack
   (`render_content_markdown`) for a writer, and a FAQPage JSON-LD stub
   (`render_faq_jsonld`) to drop into the page head for structured data.

## Rules

- **Deterministic extraction only.** Never invent a keyword, topic, quote, or
  answer. If it isn't projected from the report, it doesn't belong in the plan.
- **Answer-first, FAQPage formatting.** The outline and the JSON-LD exist to make
  the content citable by LLMs — direct answers up top, structured Q&A below.
- **Real-count stat density.** Always present the distinct-author and mention
  counts. They are the honest base rate; they're what separates this from generic
  SEO filler.
- **NO ranking promises.** This is a structural plan for citable, evidence-backed
  content — never a guarantee of search position. Don't imply one.
- The `--reddit` arm lists the real disclosed permalink targets. Those are
  sources to cite, openly, not scraping targets — present them as such.
- This skill only plans content. It does not write the pages, build the site, or
  launch — offer the next pillar once those ship.
