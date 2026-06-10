"""OpenAI EmbeddingProvider adapter (``metalworks[openai]``).

Mapping notes:

- ``dim`` → the ``dimensions`` request parameter (default 1536, the native
  size of ``text-embedding-3-small``).
- ``task`` is accepted (protocol surface) but ignored: OpenAI's
  ``text-embedding-3-*`` models are symmetric — documents and queries share
  one vector space, with no task-specific variants to select.
"""

from __future__ import annotations

import importlib
import os
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from metalworks.embeddings import PROTOCOL_VERSION
from metalworks.errors import MissingExtraError, MissingKeyError

if TYPE_CHECKING:
    from collections.abc import Sequence


class OpenAIEmbedding:
    """EmbeddingProvider over the OpenAI embeddings API."""

    protocol_version: ClassVar[str] = PROTOCOL_VERSION

    def __init__(
        self,
        model_id: str = "text-embedding-3-small",
        *,
        dim: int = 1536,
        api_key: str | None = None,
    ) -> None:
        try:
            openai = importlib.import_module("openai")
        except ImportError as exc:
            raise MissingExtraError("openai") from exc
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise MissingKeyError("OPENAI_API_KEY", provider="OpenAI")
        self.model_id = model_id
        self.dim = dim
        self._client: Any = openai.OpenAI(api_key=key)

    def embed(
        self,
        texts: Sequence[str],
        *,
        task: Literal["document", "query"] = "document",
    ) -> list[list[float]]:
        # `task` ignored — OpenAI embeddings are symmetric (module docstring).
        response = self._client.embeddings.create(
            model=self.model_id, input=list(texts), dimensions=self.dim
        )
        data: list[Any] = list(getattr(response, "data", None) or [])
        out: list[list[float]] = []
        for item in data:
            values: list[Any] = list(getattr(item, "embedding", None) or [])
            out.append([float(v) for v in values])
        return out
