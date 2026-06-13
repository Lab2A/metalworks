"""Google EmbeddingProvider adapter (``metalworks[google]``, google-genai SDK).

Mapping notes:

- ``task`` → Gemini task types: ``document`` → ``RETRIEVAL_DOCUMENT``,
  ``query`` → ``RETRIEVAL_QUERY`` (Gemini embeddings are asymmetric — using
  the wrong task type degrades retrieval).
- ``dim`` → ``output_dimensionality`` (default 768).
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from metalworks._genai_client import build_genai_client
from metalworks.embeddings import PROTOCOL_VERSION
from metalworks.errors import MissingExtraError

if TYPE_CHECKING:
    from collections.abc import Sequence

_TASK_TYPES = {"document": "RETRIEVAL_DOCUMENT", "query": "RETRIEVAL_QUERY"}

# Vertex AI's embed_content caps each request at 250 instances (the API-key
# endpoint is more lenient, but 100 is a safe batch for both and keeps payloads
# well under per-request size limits).
_MAX_BATCH = 100


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
            types_module = importlib.import_module("google.genai.types")
        except ImportError as exc:
            raise MissingExtraError("google", package="google-genai") from exc
        self.model_id = model_id
        self.dim = dim
        self._types: Any = types_module
        self._client: Any = build_genai_client(api_key=api_key)

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
        items = list(texts)
        out: list[list[float]] = []
        # Chunk to respect Vertex's 250-instance-per-request ceiling.
        for start in range(0, len(items), _MAX_BATCH):
            batch = items[start : start + _MAX_BATCH]
            response = self._client.models.embed_content(
                model=self.model_id, contents=batch, config=config
            )
            embeddings: list[Any] = list(getattr(response, "embeddings", None) or [])
            for embedding in embeddings:
                values: list[Any] = list(getattr(embedding, "values", None) or [])
                out.append([float(v) for v in values])
        return out
