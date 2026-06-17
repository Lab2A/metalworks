"""DeployProvider adapters.

:class:`~metalworks.deploy.adapters.vercel.VercelDeploy` calls the Vercel REST
API over the core ``httpx`` dependency (no SDK, following the ``parallel`` /
``firecrawl`` precedent), so it works on a bare install gated only by the
``VERCEL_TOKEN`` environment variable.
"""
