"""Corpus vector memory — blob storage + brute-force cosine (offline).

numpy is present in the dev/test env (the [research] extra), so the cosine
search paths run here. The conformance suite separately guards search on numpy
availability for the bare matrix.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from metalworks.embeddings import IndexIdentity
from metalworks.errors import EmbeddingModelMismatch
from metalworks.stores import MemoryStores, SqliteStores
from metalworks.stores.vectors import blob_to_vector, vector_to_blob

_IDENT = IndexIdentity(embedding_model_id="fake/embedding", dim=4)


def _backends(tmp_path: Path) -> list[object]:
    return [MemoryStores(), SqliteStores(tmp_path / "vec.db")]


def test_blob_codec_roundtrips_floats() -> None:
    vec = [0.5, -1.25, 3.0, 0.0]
    restored = blob_to_vector(vector_to_blob(vec))
    assert restored == pytest.approx(vec)


@pytest.mark.parametrize("backend_index", [0, 1])
def test_cosine_returns_nearest_first(backend_index: int, tmp_path: Path) -> None:
    repo = _backends(tmp_path)[backend_index]
    repo.upsert_embeddings(  # type: ignore[attr-defined]
        {
            "c_x": [1.0, 0.0, 0.0, 0.0],
            "c_y": [0.0, 1.0, 0.0, 0.0],
            "c_z": [0.0, 0.0, 1.0, 0.0],
        },
        identity=_IDENT,
    )
    hits = repo.search_embeddings([0.9, 0.1, 0.0, 0.0], k=2, identity=_IDENT)  # type: ignore[attr-defined]
    assert [cid for cid, _ in hits] == ["c_x", "c_y"]
    assert hits[0][1] > hits[1][1]  # scores descending


@pytest.mark.parametrize("backend_index", [0, 1])
def test_empty_index_returns_empty(backend_index: int, tmp_path: Path) -> None:
    repo = _backends(tmp_path)[backend_index]
    assert repo.search_embeddings([1.0, 0.0, 0.0, 0.0], k=3, identity=_IDENT) == []  # type: ignore[attr-defined]


@pytest.mark.parametrize("backend_index", [0, 1])
def test_model_mismatch_raises(backend_index: int, tmp_path: Path) -> None:
    repo = _backends(tmp_path)[backend_index]
    repo.upsert_embeddings({"c_x": [1.0, 0.0, 0.0, 0.0]}, identity=_IDENT)  # type: ignore[attr-defined]
    other = IndexIdentity(embedding_model_id="different/model", dim=4)
    with pytest.raises(EmbeddingModelMismatch):
        repo.search_embeddings([1.0, 0.0, 0.0, 0.0], k=1, identity=other)  # type: ignore[attr-defined]


@pytest.mark.parametrize("backend_index", [0, 1])
def test_reembedding_with_new_model_replaces_index(backend_index: int, tmp_path: Path) -> None:
    repo = _backends(tmp_path)[backend_index]
    repo.upsert_embeddings({"c_old": [1.0, 0.0, 0.0, 0.0]}, identity=_IDENT)  # type: ignore[attr-defined]
    new_model = IndexIdentity(embedding_model_id="v2/embedding", dim=4)
    repo.upsert_embeddings({"c_new": [0.0, 1.0, 0.0, 0.0]}, identity=new_model)  # type: ignore[attr-defined]
    hits = repo.search_embeddings([0.0, 1.0, 0.0, 0.0], k=5, identity=new_model)  # type: ignore[attr-defined]
    assert [cid for cid, _ in hits] == ["c_new"]  # old-model vectors were dropped


def test_sqlite_vectors_persist_across_reopen(tmp_path: Path) -> None:
    db = tmp_path / "persist.db"
    first = SqliteStores(db)
    first.upsert_embeddings({"c_x": [1.0, 0.0, 0.0, 0.0]}, identity=_IDENT)
    first.close()

    reopened = SqliteStores(db)
    hits = reopened.search_embeddings([1.0, 0.0, 0.0, 0.0], k=1, identity=_IDENT)
    assert [cid for cid, _ in hits] == ["c_x"]
    reopened.close()
