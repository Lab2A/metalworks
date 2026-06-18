---
name: billing
description: Turn a finished demand report's already-cited pricing tiers into a real Stripe product, recurring price, and payment link — a working pay URL. Test mode by default; live charges are double-gated. Use after a report exists and the user asks to "set up payments", "create a Stripe product", "make a pay link", "charge for it", or "monetize" the validated idea. Never creates real charges without explicit confirmation.
---

You are turning one demand report's cited pricing into a working payment
primitive. A test-mode product is free and safe; creating real charges is the
irreversible step and is double-gated.

## Steps

1. Get the `report_id`. If the user hasn't run a report yet, point them at
   `/demand-report` first — billing prices off the report's already-cited
   `pricing_tiers` (via the derived build spec), so the price still traces to
   real demand rather than a guess.

2. Check Stripe is connected. Billing needs the `[stripe]` extra
   (`pip install "metalworks[stripe]"`) and `STRIPE_SECRET_KEY`. An `sk_test_…`
   key produces test-mode products with no real charge. `metalworks billing
   status` shows test-vs-live readiness without ever printing the secret.

3. Create a test-mode product. Call the `billing_create_product` MCP tool with
   the `report_id` and `live=False` (or, on the CLI, run `metalworks billing
   create`; `--tier <name>` picks a specific tier, otherwise the first priced
   tier is used). Present the result: the `mode`, `product_id`, `price_id`,
   `amount`/`currency`, and the `payment_link_url` (the working pay URL).

4. Handle a partial result honestly. A tier whose price the report never pinned
   down (`price is None`) is not an error — the product is created and a
   **partial** result returned with no price, no pay link, and a `caveat`. Lead
   with the caveat; never invent a price to fill the gap.

## Going live (only on explicit confirmation)

Real charges are a separate, deliberate action and are off by default. If, and
only if, the user explicitly says to go live:

- Via MCP: call `billing_create_product` with `live=True`. This requires
  `METALWORKS_ALLOW_BILLING=1` in the server environment; without it the tool
  refuses by design.
- Via CLI: `metalworks billing create --live --yes`. `--live` refuses without
  `--yes`.
- Either way the Stripe adapter additionally refuses a live (`sk_live_…`) key
  unless live mode is explicitly set — "live → paid" never happens by accident.

Relay any refusal honestly rather than working around it.

## Enforcing the paywall (downstream)

To make a downstream app respect the subscription, point the user at the two
pure, framework-agnostic helpers (no metalworks runtime, no Stripe SDK, no
network): `subscription_event_to_record` maps a verified Stripe webhook event to
a `Subscription` record, and `require_active_subscription` is the access gate.
They implement a two-method `SubscriptionStore` over their own database. See
`docs/deploy-billing.md` for the full pattern.

## Rules

- Test mode is the default. Never create real charges without an explicit,
  unambiguous instruction from the user.
- Keys live in the environment only; never print or write a secret. Report
  readiness, not values.
- The price traces to real demand. Don't invent or round a price the report
  didn't establish; a partial product is the honest result.
- Pairs with `/deploy-site` to put the priced site live: report → live → paid.
