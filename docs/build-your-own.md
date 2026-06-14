---
title: "Build your own loop"
description: "Compose the building blocks into your own Reddit engagement product — your filter, your voice, your compliance rules, your storage."
---

Build your own Reddit engagement loop. The discovery loop metalworks ships is one
opinionated assembly — every step is a public function you can call, replace, or
reorder, so you can wire your own filter, voice, compliance rules, and storage
into your own product.

<Note>
This page is about composing the **Reddit engagement / discovery loop** yourself.
Turning a demand report into a build spec for your coding agent is a different
capability — see [Build spec](/docs/build-spec).
</Note>

## The loop, unbundled

`run_discovery` is essentially this, and each line is yours to swap:

```python
from metalworks.reddit import RedditSearch, heuristic_check
from metalworks.discovery import filter_post, draft_reply
from metalworks.contract import DiscoveryContext, Persona

search = RedditSearch()                      # or your own search
context = DiscoveryContext(voice_guidelines=["..."])
persona = Persona(voice_rubric="terse senior engineer", background="ran ops for years")

for post in search.search_posts("elk alternatives", subreddit="devops"):
    decision = filter_post(search_model, post, context)        # 1. is it worth it?
    if not decision or not decision.keep:
        continue
    reply = draft_reply(capable_model, post, persona,          # 2. draft in your voice
                        decision.account_type or "expert", context)
    if reply is None:
        continue
    verdict = heuristic_check(reply.reply_text)                # 3. your compliance gate
    if verdict.pass_:
        ship(post, reply.reply_text)                           # 4. your action
```

The same three building blocks are on the facade as `mw.discovery.filter(...)`
and `mw.discovery.generate(...)`.

## Bring your own pieces

- **Your own filter.** `filter_post` is a convenience over a `complete_structured`
  call. Replace it with your own classifier, a keyword rule, or an embedding score
  — `draft_reply` doesn't care how a post was selected.
- **Your own voice.** `DiscoveryContext` + `Persona` carry voice guidelines,
  winning examples, pinned notes, an avoid-list, and per-account-type personas.
  This is the seam a memory system renders into.
- **Your own compliance.** `heuristic_check` is deterministic and offline. Wrap it,
  extend it, or replace it with your own rules — then escalate to `llm_judge` only
  when you want a model's second opinion.
- **Your own storage.** Persist `Opportunity` objects wherever you like via the
  `OpportunityRepo` protocol (see [Bring your own store](/docs/custom-store)).
- **Your own action.** metalworks never posts unless you call `RedditOAuth.post_comment`
  (or `mw.reddit.post`). Queue drafts for human review, post to Slack, write to a
  DB — the gate hands you a vetted draft and stops.

## Adaptive loops

`run_discovery` also exposes the seams an adaptive product needs without baking in
a memory system or a database:

- `query_performance: Callable[[str], float]` — rank queries by your own metric.
- `on_query_result: Callable[[str, int, int], None]` — write back per-query metrics.
- `OpportunityRepo.opportunity_exists(url)` — dedup so a seen post never re-burns
  two LLM calls.

Wire those to your store and you have the skeleton of a self-improving engagement
product. metalworks gives you the building blocks; you compose them.

## Verify your custom pieces

```python
from metalworks.testing import check_all_repos      # repos
# ChatModel: assert isinstance(MyModel(), ChatModel)  — it's runtime_checkable
```

See [Custom ChatModel](/docs/custom-chatmodel) and
[Bring your own store](/docs/custom-store) for the conformance details.
