"""Embedding providers + the index-identity guard.

The iron rule: vectors from different models live in incompatible geometric
spaces, and same-dimension swaps degrade retrieval SILENTLY. Anything that
persists vectors must persist `IndexIdentity` alongside them and call
`check_index_identity` before querying — a mismatch is a hard
EmbeddingModelMismatch, never a warning.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar, Literal, Protocol, runtime_checkable

from metalworks.errors import EmbeddingModelMismatch

PROTOCOL_VERSION = "1.0"


@runtime_checkable
class EmbeddingProvider(Protocol):
    protocol_version: ClassVar[str]
    model_id: str  # e.g. "google/gemini-embedding-001"
    dim: int

    def embed(
        self,
        texts: Sequence[str],
        *,
        task: Literal["document", "query"] = "document",
    ) -> list[list[float]]: ...


@dataclass(frozen=True)
class IndexIdentity:
    """Persisted next to any vector index; checked before every load/query."""

    embedding_model_id: str
    dim: int


def check_index_identity(stored: IndexIdentity, provider: EmbeddingProvider) -> None:
    if stored.embedding_model_id != provider.model_id or stored.dim != provider.dim:
        raise EmbeddingModelMismatch(
            index_model=f"{stored.embedding_model_id} (dim={stored.dim})",
            current_model=f"{provider.model_id} (dim={provider.dim})",
        )


class FakeEmbedding:
    """Deterministic hash-based vectors for offline tests. Ships in core."""

    protocol_version: ClassVar[str] = PROTOCOL_VERSION

    def __init__(self, *, model_id: str = "fake/embedding", dim: int = 32):
        self.model_id = model_id
        self.dim = dim

    def embed(
        self,
        texts: Sequence[str],
        *,
        task: Literal["document", "query"] = "document",
    ) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            digest = hashlib.sha256(f"{task}:{text}".encode()).digest()
            needed = self.dim
            buf = bytearray()
            counter = 0
            while len(buf) < needed:
                buf += hashlib.sha256(digest + counter.to_bytes(4, "big")).digest()
                counter += 1
            out.append([(b / 127.5) - 1.0 for b in buf[:needed]])
        return out


__all__ = [
    "PROTOCOL_VERSION",
    "EmbeddingProvider",
    "FakeEmbedding",
    "IndexIdentity",
    "check_index_identity",
]
