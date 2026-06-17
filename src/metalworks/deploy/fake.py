"""FakeDeploy — deterministic, offline, ships in core.

Stand in for a real :class:`DeployProvider` (Vercel) with no network. The
returned URL is derived from the project name and target so assertions are
stable, and every call — including the file map — is recorded on ``.calls`` so a
test can prove the right artifact was handed over.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar

from metalworks.contract.deploy import Deployment, DeployTarget
from metalworks.deploy.protocol import PROTOCOL_VERSION


class FakeDeploy:
    """Deterministic DeployProvider for tests."""

    protocol_version: ClassVar[str] = PROTOCOL_VERSION
    provider_id: str = "fake"

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def deploy(
        self,
        *,
        name: str,
        files: Mapping[str, str],
        target: DeployTarget = "preview",
    ) -> Deployment:
        self.calls.append({"name": name, "files": dict(files), "target": target})
        slug = name.strip().lower().replace(" ", "-") or "site"
        suffix = "" if target == "production" else "-preview"
        return Deployment(
            url=f"https://{slug}{suffix}.fake.app",
            target=target,
            provider=self.provider_id,
            inspector_url=f"https://fake.app/inspect/{slug}",
            ready=True,
        )
