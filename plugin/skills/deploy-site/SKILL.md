---
name: deploy-site
description: Deploy a finished demand report's grounded marketing site to Vercel and return a live URL. Preview by default; production is the gated, irreversible promote. Use after a demand report exists and the user asks to "put it live", "deploy the site", "ship the landing page", or "get a public URL" for the generated site. Never promotes to production without explicit confirmation.
---

You are taking the grounded marketing site for one demand report and putting it
on a public URL. A preview deploy is free and safe; promoting to production is
the irreversible step and is gated, the same way posting to Reddit is.

## Steps

1. Get the `report_id`. If the user hasn't run a report yet, point them at
   `/demand-report` first — a deploy needs a finished report to stand on. You do
   NOT need to run `/generate-site` first: the site is rendered on the fly from
   the latest (or named) report's `MarketingSite` — the same grounded artifact
   `/generate-site` produces — and its `index.html` is what ships.

2. Check Vercel is connected. Deploy needs `VERCEL_TOKEN` in the environment;
   no SDK or extra is required (the adapter calls the Vercel REST API over the
   core `httpx` dependency). `metalworks billing status` or `metalworks doctor`
   reports readiness without ever printing the secret.

3. Deploy a preview. Call the `deploy_marketing_site` MCP tool with the
   `report_id` and `target="preview"` (or, on the CLI, run `metalworks deploy`).
   Present the returned `deployment.url` as the live preview URL, and the
   `inspector_url` if present. Preview is the default and is non-destructive.

## Production (only on explicit confirmation)

Promoting to production is a separate, deliberate action and is off by default.
If, and only if, the user explicitly says to go live:

- Via MCP: call `deploy_marketing_site` with `target="production"`. This requires
  `METALWORKS_ALLOW_DEPLOY=1` in the server environment — without it the tool
  refuses by design, the same posture as `reddit_post_comment`'s
  `METALWORKS_ALLOW_POSTING`.
- Via CLI: `metalworks deploy --prod --yes`. `--prod` refuses without `--yes`.

Relay any refusal honestly rather than working around it.

## Rules

- Preview is the default. Never promote to production without an explicit,
  unambiguous instruction from the user for that deploy.
- Keys live in the environment only; never print or write a secret. Report
  readiness, not values.
- This skill deploys the grounded artifact as-is; it does not design or theme.
  If the site needs a visual pass, hand the rendered `index.html` to
  `design-html` / `clique-feel` first, then deploy — keep the footnotes and
  `data-evidence` attributes intact so the provenance chain survives.
- Pairs with `/billing` to turn the live site's cited pricing into a real pay
  link: report → live → paid.
