"""Embedding guard tests: determinism, task asymmetry, index-identity hard fail."""

import pytest

from metalworks.embeddings import (
    EmbeddingProvider,
    FakeEmbedding,
    IndexIdentity,
    check_index_identity,
)
from metalworks.errors import EmbeddingModelMismatch


def test_fake_embedding_is_deterministic_and_task_asymmetric() -> None:
    fake = FakeEmbedding(dim=16)
    assert isinstance(fake, EmbeddingProvider)
    a1 = fake.embed(["hello"])[0]
    a2 = fake.embed(["hello"])[0]
    q = fake.embed(["hello"], task="query")[0]
    assert a1 == a2
    assert a1 != q  # asymmetric task types produce different vectors
    assert len(a1) == 16
    assert all(-1.0 <= v <= 1.0 for v in a1)


def test_index_identity_mismatch_is_a_hard_fail() -> None:
    fake = FakeEmbedding(model_id="fake/embedding", dim=32)
    ok = IndexIdentity(embedding_model_id="fake/embedding", dim=32)
    check_index_identity(ok, fake)  # no raise

    wrong_model = IndexIdentity(embedding_model_id="google/gemini-embedding-001", dim=32)
    with pytest.raises(EmbeddingModelMismatch):
        check_index_identity(wrong_model, fake)

    # Same model name, different dim — the silent-degradation case — also hard-fails.
    wrong_dim = IndexIdentity(embedding_model_id="fake/embedding", dim=64)
    with pytest.raises(EmbeddingModelMismatch):
        check_index_identity(wrong_dim, fake)
