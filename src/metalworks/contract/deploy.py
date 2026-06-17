"""Deploy contract — the typed shape a deploy provider returns.

``metalworks deploy`` pushes the one runnable artifact the engine emits today —
the rendered marketing site (``MarketingSite`` → ``render_site_html`` →
``index.html``) — to a host (Vercel) and returns a :class:`Deployment`: a live
URL plus whether it landed on a preview or production target. Preview is the
default; production is the gated, irreversible promote.

The provider speaks a path→content file map, so the contract is host-agnostic
and the artifact is whatever the caller renders — no metalworks runtime is
assumed on the other side.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

DeployTarget = Literal["preview", "production"]
"""Where a deployment lands. ``preview`` is the safe default; ``production`` is
the promoted, publicly-addressable target (the gated step)."""


class Deployment(BaseModel):
    """One deployment of a rendered artifact to a host.

    ``url`` is the live address (always ``https://``). ``ready`` reflects whether
    the host reported the deployment as serving yet — a fresh deploy may still be
    building, in which case ``url`` resolves once it finishes.
    """

    url: str = Field(description="The live deployment URL.")
    target: DeployTarget = Field(description="preview (default) or production.")
    provider: str = Field(description="Which provider served it (e.g. 'vercel').")
    inspector_url: str | None = Field(
        default=None, description="Host dashboard URL for build logs/status, when exposed."
    )
    ready: bool = Field(
        default=False, description="True when the host reports the deployment is serving."
    )
