"""Vector helpers shared by the store backends — brute-force cosine + blob codec.

The locked v1 vector store is brute-force numpy cosine over blob embeddings (no
sqlite-vec dependency; fine at corpus scale of hundreds to low-thousands of
comments — re-plan section 10 / Decision 10). Vectors serialize with the stdlib
``array`` module, so WRITING needs no numpy; only the cosine math in
:func:`cosine_topk` imports numpy lazily, behind the ``[research]`` extra.
"""

from __future__ import annotations

from array import array
from typing import TYPE_CHECKING, Any

from metalworks.errors import MissingExtraError

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


def check_dims(vectors: Mapping[str, Sequence[float]], dim: int) -> None:
    """Reject a batch whose vectors don't all match ``dim``.

    A wrong-length vector would otherwise store happily and only blow up later in
    ``cosine_topk`` (``np.asarray`` over ragged rows raises far from the upsert that
    admitted it). Fail fast at the boundary instead.
    """
    for corpus_id, vector in vectors.items():
        if len(vector) != dim:
            raise ValueError(
                f"embedding for {corpus_id!r} has length {len(vector)}, expected dim={dim}"
            )


def vector_to_blob(vector: Sequence[float]) -> bytes:
    """Pack a float vector into bytes for a sqlite BLOB column.

    Uses float64 (``'d'``) so a vector round-tripped through the db is bit-identical
    to the provider's native float and to what ``MemoryStores`` keeps in memory.
    f32 would silently drift dedup/triage cosine scores near their thresholds,
    making results differ across backends and across runs of the same corpus.
    """
    return array("d", vector).tobytes()


def blob_to_vector(blob: bytes) -> list[float]:
    """Unpack bytes written by :func:`vector_to_blob` back into a float list."""
    out = array("d")
    out.frombytes(blob)
    return out.tolist()


def cosine_topk(
    query: Sequence[float], vectors: Mapping[str, Sequence[float]], k: int
) -> list[tuple[str, float]]:
    """The ``k`` ids whose vectors are most cosine-similar to ``query``, score
    descending. Empty store → ``[]``. Needs numpy (the ``[research]`` extra)."""
    ids = list(vectors)
    if not ids or k <= 0:
        return []
    try:
        import numpy
    except ImportError as exc:  # pragma: no cover - exercised only on a bare install
        raise MissingExtraError("research", package="numpy") from exc

    # numpy's overloaded stubs (2.5.0+) report linalg.norm / where / argsort as
    # "partially unknown" under pyright strict; bind numpy behind Any so this
    # pure-math helper stays green across numpy stub churn (the SDK-behind-Any rule).
    np: Any = numpy

    matrix = np.asarray([list(vectors[i]) for i in ids], dtype="float64")
    q = np.asarray(list(query), dtype="float64")
    norms = np.linalg.norm(matrix, axis=1) * (np.linalg.norm(q) or 1.0)
    sims = (matrix @ q) / np.where(norms == 0.0, 1.0, norms)
    order = np.argsort(-sims)[:k]
    return [(ids[int(i)], float(sims[int(i)])) for i in order]


__all__ = ["blob_to_vector", "check_dims", "cosine_topk", "vector_to_blob"]
