---
name: draft-reply
description: Draft an authentic Reddit reply for a thread and run it through the compliance gate before the user posts. Use when the user wants help replying to a specific Reddit thread or comment. Drafting is free; posting requires explicit confirmation and is never automatic.
---

## Preamble (run first)

Before any other tool, run the `preflight` MCP tool (or `metalworks preflight` on
the CLI). If it reports setup issues or that an update is available, surface that
to the user in one line and help them resolve it (install the missing extra/key,
or `pip install -U metalworks`) before continuing. Skip only if the user has
already passed preflight this session.

**Read the reference; never reverse-engineer the source.** The moment you need to know how
metalworks behaves — provider/model resolution, which source/reader runs, config precedence,
an error you hit, or the async run loop — **STOP and read `docs/operating-metalworks.md`
(bundled with this plugin) before opening any file under `src/`.** It is the source of truth;
do not derive behavior from source. (Full docs: https://metalworks.lab2a.ai/docs.) For a
long-running run, poll status with the Monitor tool or a bounded loop — never a blind `sleep`.

You are drafting one genuine, disclosed Reddit reply for a thread the user
provides, and gating it before anything is posted.

## Steps

1. Read the thread: call `reddit_get_post_comments` on the URL and
   `reddit_subreddit_rules` on its subreddit. Understand what the person is
   actually asking and what the subreddit allows.

2. Draft a reply in the user's own voice. It must read as a real person sharing
   real experience: specific, helpful, no marketing tone, no calls to action,
   no em-dashes, no AI tells. If the user has an affiliation worth disclosing,
   disclose it plainly in the reply.

3. Run the draft through `compliance_lint`. If it does not pass, revise and
   lint again. Loop until it passes. Show the user the violations you fixed.

4. Present the final draft and the compliance verdict. Stop there. Do not post.

## Posting (only on explicit confirmation)

Posting is a separate, deliberate action and is off by default. If, and only if,
the user explicitly says to post it:

- A passing `compliance_lint` returns a `confirm_token` over that exact text.
- Posting also requires `METALWORKS_ALLOW_POSTING=1` in the server environment
  and a connected Reddit account (`metalworks reddit auth login`).
- Call `reddit_post_comment` with the URL, the exact drafted text, and that
  `confirm_token`. If the token does not match the text, or posting is not
  enabled, the tool refuses by design. Relay the refusal honestly.

## Rules

- Never post without an explicit, unambiguous instruction from the user for that
  specific reply.
- Never edit the text after the compliance pass without re-linting; the
  confirm_token is bound to the exact text.
- Authentic engagement only. Decline if the only honest reply would be a plug.
