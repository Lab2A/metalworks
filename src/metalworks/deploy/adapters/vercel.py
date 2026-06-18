"""Vercel DeployProvider adapter — httpx over the core dependency.

Pushes a rendered artifact (the marketing site's ``index.html`` and any assets)
to Vercel via the documented REST endpoint, following the ``parallel`` /
``firecrawl`` precedent: no SDK, just the core ``httpx`` dependency, gated solely
by the ``VERCEL_TOKEN`` environment variable. So ``metalworks deploy`` works on a
bare install with just the token — no extra to install.

Preview is the default; ``target="production"`` is the gated, irreversible
promote (the CLI requires ``--prod`` and a confirmation for it).

REST reference (verified 2026-06): ``POST https://api.vercel.com/v13/deployments``
with ``Authorization: Bearer <token>``. Inline files go as
``[{"file": path, "data": content}]``; ``projectSettings.framework = null`` makes
it a static deploy. An optional team is passed as the ``teamId`` query param
(``VERCEL_TEAM_ID`` / ``VERCEL_ORG_ID``). The response's ``url`` carries no
scheme, so it is prefixed with ``https://``; ``readyState == "READY"`` sets
``ready``.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from typing import Any, ClassVar

import httpx

from metalworks.contract.deploy import Deployment, DeployTarget
from metalworks.deploy.protocol import PROTOCOL_VERSION
from metalworks.errors import DeployError, MissingKeyError

_ENDPOINT = "https://api.vercel.com/v13/deployments"
_TIMEOUT_S = 60.0
_PROJECT_FALLBACK = "metalworks-site"


class VercelDeploy:
    """DeployProvider over the Vercel REST API. Gated by ``VERCEL_TOKEN``."""

    protocol_version: ClassVar[str] = PROTOCOL_VERSION
    provider_id: str = "vercel"

    def __init__(
        self,
        *,
        token: str | None = None,
        team_id: str | None = None,
        project: str | None = None,
    ) -> None:
        key = token or os.environ.get("VERCEL_TOKEN")
        if not key:
            raise MissingKeyError("VERCEL_TOKEN", provider="Vercel")
        self._token: str = key
        self._team_id = (
            team_id or os.environ.get("VERCEL_TEAM_ID") or os.environ.get("VERCEL_ORG_ID")
        )
        self._project = project or os.environ.get("VERCEL_PROJECT")

    def deploy(
        self,
        *,
        name: str,
        files: Mapping[str, str],
        target: DeployTarget = "preview",
    ) -> Deployment:
        if not files:
            raise DeployError("Nothing to deploy: the file map is empty.")
        project_name = _slugify(self._project or name or _PROJECT_FALLBACK)
        body: dict[str, Any] = {
            "name": project_name,
            "files": [{"file": path, "data": content} for path, content in files.items()],
            "projectSettings": {"framework": None},
        }
        if target == "production":
            body["target"] = "production"
        params = {"teamId": self._team_id} if self._team_id else None
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }
        try:
            response = httpx.post(
                _ENDPOINT, json=body, headers=headers, params=params, timeout=_TIMEOUT_S
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise self._status_error(exc) from exc
        except httpx.HTTPError as exc:
            raise DeployError(f"Vercel deployment request failed: {exc}") from exc

        payload: dict[str, Any] = response.json() or {}
        url = str(payload.get("url") or "")
        if not url:
            raise DeployError("Vercel returned no deployment URL.")
        return Deployment(
            url=url if url.startswith("http") else f"https://{url}",
            target=target,
            provider=self.provider_id,
            inspector_url=payload.get("inspectorUrl") or payload.get("inspector_url"),
            ready=str(payload.get("readyState") or "").upper() == "READY",
        )

    @staticmethod
    def _status_error(exc: httpx.HTTPStatusError) -> DeployError | MissingKeyError:
        status = exc.response.status_code
        if status in (401, 403):
            return MissingKeyError(
                "VERCEL_TOKEN",
                provider="Vercel",
                detail="the token was rejected or lacks scope for this project/team.",
            )
        return DeployError(
            f"Vercel returned HTTP {status}: {exc.response.text[:300]}", status=status
        )


def _slugify(name: str) -> str:
    """Vercel project names: lowercase, alphanumeric + hyphens, <=100 chars."""
    slug = re.sub(r"[^a-z0-9-]+", "-", name.strip().lower()).strip("-")
    return (slug or _PROJECT_FALLBACK)[:100]
