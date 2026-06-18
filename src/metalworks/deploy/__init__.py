"""Deploy — push the rendered marketing site to a host, get a live URL.

``metalworks deploy`` renders a report's ``MarketingSite`` to ``index.html`` and
pushes it through a :class:`DeployProvider`. Preview is the default; production
is the gated promote.

The provider protocol speaks a path→content file map, so it is host-agnostic and
fakeable (:class:`metalworks.deploy.fake.FakeDeploy`). The only adapter today is
:class:`VercelDeploy`, which calls the Vercel REST API over the core ``httpx``
dependency — no SDK, gated solely by ``VERCEL_TOKEN``. Import it lazily
(``from metalworks.deploy.adapters.vercel import VercelDeploy``).
"""

from __future__ import annotations

from metalworks.deploy.protocol import PROTOCOL_VERSION, DeployProvider

__all__ = ["PROTOCOL_VERSION", "DeployProvider"]
