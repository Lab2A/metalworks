"""Embedding cache — reuse persisted corpus vectors, embed only misses (offline)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

import pytest

from metalworks.embeddings import FakeEmbedding
from metalworks.research.embedding_cache import cached_embed
from metalworks.stores import MemoryStores, SqliteStores


class _CountingEmbedding:
    """Deterministic FakeEmbedding that counts how many texts it embedded."""

    protocol_version = "test"

    def __init__(self, *, dim: int = 8) -> None:
        self._fake = FakeEmbedding(dim=dim)
        self.model_id = self._fake.model_id
        self.dim = dim
        self.texts_embedded = 0

    def embed(
        self, texts: Sequence[str], *, task: Literal["document", "query"] = "document"
    ) -> list[list[float]]:
        self.texts_embedded += len(texts)
        return self._fake.embed(texts, task=task)


def _deps(store: object) -> object:
    emb = _CountingEmbedding()
    return SimpleNamespace(embeddings=emb, corpus=store)


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_cached_embed_reuses_and_embeds_only_misses(kind: str, tmp_path: Path) -> None:
    store = MemoryStores() if kind == "memory" else SqliteStores(tmp_path / "c.db")
    deps = _deps(store)
    emb = deps.embeddings  # type: ignore[attr-defined]

    pairs = [("c1", "alpha"), ("c2", "beta")]
    first = cached_embed(deps, pairs)  # type: ignore[arg-type]
    assert emb.texts_embedded == 2
    assert set(first) == {"c1", "c2"}

    # 2nd run, same ids → full reuse, nothing re-embedded.
    emb.texts_embedded = 0
    second = cached_embed(deps, pairs)  # type: ignore[arg-type]
    assert emb.texts_embedded == 0
    assert set(second) == {"c1", "c2"}
    for cid in first:
        assert second[cid] == pytest.approx(first[cid])

    # A new id embeds only itself; the seen one is reused.
    emb.texts_embedded = 0
    third = cached_embed(deps, [("c1", "alpha"), ("c3", "gamma")])  # type: ignore[arg-type]
    assert emb.texts_embedded == 1
    assert set(third) == {"c1", "c3"}


def test_cached_embed_reembeds_after_model_change(tmp_path: Path) -> None:
    store = SqliteStores(tmp_path / "c.db")
    deps = _deps(store)
    emb = deps.embeddings  # type: ignore[attr-defined]

    cached_embed(deps, [("c1", "alpha")])  # type: ignore[arg-type]
    emb.texts_embedded = 0
    emb.model_id = "v2/embedding"  # the embedding model changed
    cached_embed(deps, [("c1", "alpha")])  # type: ignore[arg-type]
    assert emb.texts_embedded == 1  # a vector from the old model is not reused


def test_cached_embed_empty_pairs_is_noop(tmp_path: Path) -> None:
    deps = _deps(SqliteStores(tmp_path / "c.db"))
    assert cached_embed(deps, []) == {}  # type: ignore[arg-type]
    assert deps.embeddings.texts_embedded == 0  # type: ignore[attr-defined]
