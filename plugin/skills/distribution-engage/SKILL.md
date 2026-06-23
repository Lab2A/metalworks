---
name: distribution-engage
description: Distribution's participation/execution arm — the one channel metalworks can OPERATE rather than merely plan. Take a GEO participation target (a real Reddit thread the demand report surfaced) and draft a disclosed, founder-voiced reply for that exact thread, run it through the deterministic compliance gate, and hand it to the human to post. Use after a demand report (and ideally its GEO plan) exists and the user asks "draft a reply for this thread", "engage this participation target", "help me reply where my audience is asking", "execute the GEO participation stream", or wants to actually show up in the threads the report found rather than only plan to. Reuses the Reddit reply machinery + the shared honesty gate; the no-upvote / native-first / no-AI-tell invariants are the same single voice system the launch assets use. DRAFTING ONLY — posting is human-gated and never automatic.
---

You are drafting one disclosed, founder-voiced Reddit reply for a GEO
participation target — a real thread the demand report's `distribution_geo`
stream surfaced (the threads the audience is *already* asking in). This is
Distribution's execution arm: D6 names *which* thread; you engage it, value-first
and compliance-gated. DRAFTING ONLY — a human posts.

## Steps

1. Get a participation target. Run `/distribution-geo` (or the `distribution_geo`
   MCP tool) on the `report_id` first if you don't have one — each
   `participation_target` carries a real `permalink`, a grounded `why` (what the
   audience is asking there), a `community`, and a `suggested_angle`. If the user
   hasn't run a report, point them at `/demand-report` first.

2. Call the `distribution_engage` MCP tool with the `report_id` and the target's
   `permalink` + `why` (plus `community`, `suggested_angle`, and an optional
   `voice`). On the CLI: `metalworks distribution engage <report_id> --permalink
   <url> --why "<what they're asking>" --community r/Name --angle "<angle>"`. It
   drafts the reply for that exact thread, applies the no-upvote / native-first
   invariants, and runs the deterministic honesty gate (`heuristic_check`) over it.

3. Read the returned `participation_reply`:
   - `draft` — the reply text, in a plain founder voice, disclosing affiliation,
     answering the thread's question first, never a bare link or an upvote ask.
   - `compliance` — the gate verdict (`pass`, `violations`, `confidence`). If it
     did not pass, surface the violations and revise the angle/voice and re-draft.
   - It references the target's thread (`community` + `permalink`) so the human
     knows exactly where it goes.

4. Present the draft and the verdict. Stop there. `requires_human` and
   `posting_gated` are always true — do NOT post.

## Posting (only on explicit confirmation)

Posting is a separate, deliberate, gated action — the same path `/draft-reply`
uses. Only if the user explicitly says to post this exact reply:

- Run `compliance_lint` on the exact `draft` text to get a `confirm_token`.
- Posting also requires `METALWORKS_ALLOW_POSTING=1` and a connected account
  (`metalworks reddit auth login`).
- Call `reddit_post_comment` with the permalink, the exact text, and the token.
  If the token doesn't match the text or posting isn't enabled, the tool refuses
  by design — relay the refusal honestly.

## Rules

- The target is a **real thread from the report** (`distribution_geo`'s
  permalinks). This skill engages targets the report found; it does not invent
  threads. For a one-off reply to an arbitrary URL the user pastes, use
  `/draft-reply` instead — same honesty gate, different entry.
- Value-first and disclosed: answer the question, disclose affiliation in the same
  breath, never drop a bare link, never ask for upvotes (the gate strips it).
- Never edit the text after the compliance pass without re-linting; the
  confirm_token is bound to the exact text.
- Authentic engagement only. Decline if the only honest reply would be a plug.
- DRAFTING ONLY — this never posts. A human reviews and posts, gated.
