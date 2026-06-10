"""Google EmbeddingProvider adapter (``metalworks[google]``, google-genai SDK).

Mapping notes:

- ``task`` → Gemini task types: ``document`` → ``RETRIEVAL_DOCUMENT``,
  ``query`` → ``RETRIEVAL_QUERY`` (Gemini embeddings are asymmetric — using
  the wrong task type degrades retrieval).
- ``dim`` → ``output_dimensionality`` (default 768).
"""

from __future__ import annotations

import importlib
import os
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from metalworks.embeddings import PROTOCOL_VERSION
from metalworks.errors import MissingExtraError, MissingKeyError

if TYPE_CHECKING:
    from collections.abc import Sequence

_TASK_TYPES = {"document": "RETRIEVAL_DOCUMENT", "query": "RETRIEVAL_QUERY"}


class GoogleEmbedding:
    """EmbeddingProvider over the google-genai ``embed_content`` API."""

    protocol_version: ClassVar[str] = PROTOCOL_VERSION

    def __init__(
        self,
        model_id: str = "gemini-embedding-001",
        *,
        dim: int = 768,
        api_key: str | None = None,
    ) -> None:
        try:
            genai = importlib.import_module("google.genai")
            types_module = importlib.import_module("google.genai.types")
        except ImportError as exc:
            raise MissingExtraError("google", package="google-genai") from exc
        key = api_key or os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise MissingKeyError("GOOGLE_API_KEY", provider="Google")
        self.model_id = model_id
        self.dim = dim
        self._types: Any = types_module
        self._client: Any = genai.Client(api_key=key)

    def embed(
        self,
        texts: Sequence[str],
        *,
        task: Literal["document", "query"] = "document",
    ) -> list[list[float]]:
        config = self._types.EmbedContentConfig(
            task_type=_TASK_TYPES[task],
            output_dimensionality=self.dim,
        )
        response = self._client.models.embed_content(
            model=self.model_id, contents=list(texts), config=config
        )
        embeddings: list[Any] = list(getattr(response, "embeddings", None) or [])
        out: list[list[float]] = []
        for embedding in embeddings:
            values: list[Any] = list(getattr(embedding, "values", None) or [])
            out.append([float(v) for v in values])
        return out
