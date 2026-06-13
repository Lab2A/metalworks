"""Shared google-genai ``Client`` construction — API-key or Vertex AI.

Both Google adapters (chat + embeddings) build their client the same way, so
the API-key-vs-Vertex decision lives here once. Two auth modes:

- **Vertex AI** (``GOOGLE_GENAI_USE_VERTEXAI`` truthy): authenticate via
  Application Default Credentials (a service-account JSON pointed at by
  ``GOOGLE_APPLICATION_CREDENTIALS``, or ambient ``gcloud`` ADC). Requires a
  project (``VERTEX_PROJECT_ID`` or ``GOOGLE_CLOUD_PROJECT``) and a location
  (``VERTEX_LOCATION`` or ``GOOGLE_CLOUD_LOCATION``, default ``us-central1``).
- **API key** (default): ``GOOGLE_API_KEY`` / ``GEMINI_API_KEY``.

google-genai is in the ``[google]`` extra and imported lazily so a bare install
stays import-free.
"""

from __future__ import annotations

import importlib
import os
from typing import Any

from metalworks.errors import MissingExtraError, MissingKeyError


def vertex_enabled() -> bool:
    """True when ``GOOGLE_GENAI_USE_VERTEXAI`` is set to a truthy value."""
    return (os.environ.get("GOOGLE_GENAI_USE_VERTEXAI") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def build_genai_client(*, api_key: str | None = None) -> Any:
    """Construct a ``google.genai.Client`` in Vertex or API-key mode.

    Raises :class:`~metalworks.errors.MissingExtraError` if google-genai is not
    installed, or :class:`~metalworks.errors.MissingKeyError` if the selected
    mode is missing its required configuration.
    """
    try:
        genai = importlib.import_module("google.genai")
    except ImportError as exc:
        raise MissingExtraError("google", package="google-genai") from exc

    if vertex_enabled():
        project = os.environ.get("VERTEX_PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT")
        location = (
            os.environ.get("VERTEX_LOCATION")
            or os.environ.get("GOOGLE_CLOUD_LOCATION")
            or "us-central1"
        )
        if not project:
            raise MissingKeyError(
                "VERTEX_PROJECT_ID (or GOOGLE_CLOUD_PROJECT)", provider="Google Vertex AI"
            )
        return genai.Client(vertexai=True, project=project, location=location)

    key = api_key or os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not key:
        raise MissingKeyError("GOOGLE_API_KEY", provider="Google")
    return genai.Client(api_key=key)
