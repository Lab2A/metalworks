"""Deploy protocol — the seam ``metalworks deploy`` speaks through.

A :class:`DeployProvider` takes a path→content file map (the rendered
``index.html`` and any assets) and pushes it to a host, returning a
:class:`~metalworks.contract.deploy.Deployment`. Because the unit is a plain file
map, the protocol is host-agnostic and trivially fakeable — no Vercel, no
network in the tests that exercise a caller.

``protocol_version`` is versioned as a unit: a minor bump is additive
keyword-only params with defaults; a major bump is breaking.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, ClassVar, Protocol, runtime_checkable

if TYPE_CHECKING:
    from metalworks.contract.deploy import Deployment, DeployTarget

PROTOCOL_VERSION = "1.0"


@runtime_checkable
class DeployProvider(Protocol):
    """Push a rendered artifact to a host. Adapters call the host's REST API.

    ``files`` is a path→content map; ``target="production"`` is the gated,
    irreversible promote (``"preview"`` is the safe default). The provider reads
    its credential from the environment and raises
    :class:`~metalworks.errors.MissingKeyError` when it is absent.
    """

    protocol_version: ClassVar[str]
    provider_id: str

    def deploy(
        self,
        *,
        name: str,
        files: Mapping[str, str],
        target: DeployTarget = "preview",
    ) -> Deployment:
        """Deploy ``files`` under project ``name`` to ``target``."""
        ...
