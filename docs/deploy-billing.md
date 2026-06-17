---
title: "Deploy & bill"
description: "Push the generated marketing site live on Vercel, and turn the report's cited pricing tiers into a real Stripe product, price, and payment link — preview and test mode by default, going live human-gated."
---

**Take a validated idea from report to live to paid.**

The research turns an idea into a grounded [marketing site](/docs/marketing-site)
and a [build spec](/docs/build-spec) with cited pricing tiers. Two more verbs
connect that to the real world: `deploy` puts the rendered site on a public URL,
and `billing create` turns a cited tier into a working pay link. Both default to
the safe side — a preview URL, a test-mode product — and the irreversible step
(production, real charges) is human-gated, the same way Reddit posting is.

## Connect the providers

Keys come from the environment only; nothing is written to the config file.

- **Vercel** needs `VERCEL_TOKEN` (and optionally `VERCEL_TEAM_ID` /
  `VERCEL_PROJECT`). No SDK or extra — the adapter calls the Vercel REST API over
  the core `httpx` dependency, so `deploy` works on a bare install with just the
  token.
- **Stripe** needs the `[stripe]` extra and `STRIPE_SECRET_KEY`. An `sk_test_…`
  key produces test-mode products (no real charge); an `sk_live_…` key would
  create real charges, so the adapter refuses to use one unless you explicitly
  ask to go live.

```bash
pip install "metalworks[stripe]"
export VERCEL_TOKEN=...          # deploy
export STRIPE_SECRET_KEY=sk_test_...   # billing (test mode)
metalworks billing status        # what's configured? test or live? (no secret printed)
```

`metalworks doctor` shows the same readiness line.

## Deploy the site

```bash
metalworks deploy                # render the latest report's site → a Vercel preview URL
metalworks deploy --site index.html   # deploy an explicit index.html instead
metalworks deploy --prod --yes   # promote to production (the gated, irreversible step)
```

With no `--site`, `deploy` renders the latest (or named) report's `MarketingSite`
on the fly — the same grounded artifact `metalworks research site` produces — and
pushes its `index.html`. Preview is the default; `--prod` refuses without `--yes`.

```python
from metalworks.deploy.adapters.vercel import VercelDeploy

deploy = VercelDeploy()                       # reads VERCEL_TOKEN
deployment = deploy.deploy(
    name="taxlock",
    files={"index.html": html},               # the rendered site
    target="preview",                          # or "production"
)
print(deployment.url)                          # the live URL
```

## Bill for it

`billing create` reads the report's already-cited `pricing_tiers`, picks one (the
first priced tier by default, or `--tier <name>`), and creates a real Stripe
product, a recurring price, and a payment link — a working pay URL — carrying the
tier's evidence through so the price still traces to real demand.

```bash
metalworks billing create               # cited tier → Stripe product + price + pay link (test)
metalworks billing create --tier Pro    # pick a specific tier
metalworks billing create --live --yes  # real charges (double-gated; needs a live key)
```

A tier whose price the report never pinned down (`price is None`) is not an
error: the product is created and a **partial** result returned — no price, no
pay link, and a caveat saying so — never a guess.

```python
from metalworks.billing.adapters.stripe import StripeBilling

billing = StripeBilling()                      # reads STRIPE_SECRET_KEY
product = billing.create_product(name="taxlock", tier=tier, mode_live=False)
print(product.mode, product.payment_link_url)  # "test"  https://buy.stripe.com/...
```

## Enforce the paywall

The webhook mapper and the subscription gate are pure, framework-agnostic
functions — no metalworks runtime, no Stripe SDK, no network. A downstream app
imports them to keep an access record fresh and to decide who gets in.

```python
from metalworks.billing import subscription_event_to_record, require_active_subscription

# In your Stripe webhook route (after you verify the signature):
record = subscription_event_to_record(event)   # Stripe event → Subscription, or None
if record is not None:
    store.upsert_subscription(record)           # your SubscriptionStore

# In your access guard:
if require_active_subscription(user_id, "taxlock", store):
    ...                                          # active or trialing, period not lapsed
```

`SubscriptionStore` is a two-method port (`get_subscription` / `upsert_subscription`)
you implement over your own database — core ships no hosted store, the same way
it ships no hosted corpus store. Test your gate against
`metalworks.testing.FakeSubscriptionStore` with no database at all.

## The gates, in one place

- **Deploy** is preview by default; `--prod` requires `--yes`. The
  `deploy_marketing_site` MCP tool requires `METALWORKS_ALLOW_DEPLOY=1` for a
  production target.
- **Billing** is test mode by default; `--live` requires `--yes`, and the Stripe
  adapter refuses a live key unless live mode is set. The `billing_create_product`
  MCP tool requires `METALWORKS_ALLOW_BILLING=1` for live charges.
- No secret is ever printed or written to disk; keys live in the environment.
