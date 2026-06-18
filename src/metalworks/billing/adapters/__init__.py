"""BillingProvider adapters.

:class:`~metalworks.billing.adapters.stripe.StripeBilling` lives behind the
``metalworks[stripe]`` extra and lazy-imports the ``stripe`` SDK inside its
methods, raising :class:`~metalworks.errors.MissingExtraError` when it is absent —
so ``import metalworks.billing`` stays SDK-free. The secret key is read from the
environment (``STRIPE_SECRET_KEY``) at call time, never at import.
"""
