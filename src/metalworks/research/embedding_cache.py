"""Embedding cache — reuse persisted corpus vectors, embed only the misses.

The pipeline embeds the same Reddit corpus on every run. Routed through the
project store's vector memory (`corpus.db`), vectors already computed under the
current embedding model are reused and only new texts hit the provider — and the
new ones are persisted for next time. With a `MemoryStores` one-shot the store is
fresh each run, so everything is a miss and embeds on the fly: the prior
behaviour, unchanged. No numpy needed (a keyed lookup + upsert, not cosine).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from metalworks.embeddings import IndexIdentity

if TYPE_CHECKING:
    from collections.abc import Sequence

    from metalworks.research.deps import ResearchDeps


def cached_embed(
    deps: ResearchDeps,
    pairs: Sequence[tuple[str, str]],
    *,
    task: Literal["document", "query"] = "document",
) -> dict[str, list[float]]:
    """Embed ``(corpus_id, text)`` pairs, reusing any vectors already stored for
    the current embedding model and persisting the newly-computed ones. Returns
    ``{corpus_id: vector}`` covering every input id.

    Assumes corpus ids are content-stable: a cache hit reuses the stored vector by
    id and ignores the supplied text. This holds because corpus ids (post_id /
    comment_id) key immutable Reddit content in our append-only corpus. If a future
    refresh ever re-fetches an *edited* comment under the same id, key the cache on
    (id, content-hash) instead — today the id IS the content key.
    """
    if not pairs:
        return {}
    identity = IndexIdentity(embedding_model_id=deps.embeddings.model_id, dim=deps.embeddings.dim)
    cached = deps.corpus.get_embeddings([cid for cid, _ in pairs], identity=identity)

    missing = [(cid, text) for cid, text in pairs if cid not in cached]
    if missing:
        fresh = deps.embeddings.embed([text for _, text in missing], task=task)
        new = {cid: vec for (cid, _), vec in zip(missing, fresh, strict=True)}
        deps.corpus.upsert_embeddings(new, identity=identity)
        cached = {**cached, **new}
    return cached


__all__ = ["cached_embed"]
