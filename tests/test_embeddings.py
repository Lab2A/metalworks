"""Embedding guard tests: determinism, task asymmetry, index-identity hard fail."""

import pytest

from metalworks.embeddings import (
    EmbeddingProvider,
    FakeEmbedding,
    IndexIdentity,
    check_index_identity,
)
from metalworks.embeddings.adapters.fastembed import (
    PROVENANCE,
    FastEmbedEmbedding,
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


def test_fastembed_construction_needs_no_sdk_and_has_stable_identity() -> None:
    # Construction must NOT import fastembed (the SDK isn't installed in CI), so
    # the keyless local provider can always be selected/inspected.
    provider = FastEmbedEmbedding()
    assert isinstance(provider, EmbeddingProvider)
    assert provider.model_id == "fastembed/BAAI/bge-small-en-v1.5"
    assert provider.dim == 384

    identity = provider.identity()
    assert identity == IndexIdentity(embedding_model_id="fastembed/BAAI/bge-small-en-v1.5", dim=384)
    # Provenance is encoded in the prefixed model_id so a same-named model on a
    # different runtime gets a distinct identity (the guard fires, not degrade).
    assert PROVENANCE == "fastembed-onnx"
    check_index_identity(identity, provider)  # round-trips against its own guard


@pytest.mark.network
def test_fastembed_embed_smoke() -> None:
    # Real embedding: downloads weights + needs network, so it's gated behind the
    # `network` marker (CI runs with pytest-socket) AND fastembed being present.
    pytest.importorskip("fastembed")
    provider = FastEmbedEmbedding()
    doc = provider.embed(["hello world"], task="document")[0]
    query = provider.embed(["hello world"], task="query")[0]
    assert len(doc) == provider.dim == 384
    assert len(query) == 384
