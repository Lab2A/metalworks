"""Near-duplicate dedup over LoadedComment bodies via cosine similarity.

Greedy single-pass grouping: each comment either joins the first existing group
whose centroid sits above the cosine threshold, or seeds its own. Comments whose
embedding fails become their own singleton group (never silently dropped).

The LLM later sees one representative per group, so this is what keeps it
labelling distinct ideas instead of 40 paraphrases of the same one.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from metalworks.research.types import LoadedComment

if TYPE_CHECKING:
    from collections.abc import Callable

# Comments closer than this are treated as near-duplicates.
DEDUP_COSINE_THRESHOLD = 0.92


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def embed_group(
    comments: list[LoadedComment],
    embed: Callable[[LoadedComment], list[float] | None],
    *,
    threshold: float = DEDUP_COSINE_THRESHOLD,
) -> list[list[int]]:
    """Return groups of indices into `comments`. Each comment is in exactly one
    group. Empty `comments` → empty list.

    `embed` receives the whole `LoadedComment` (not just its body) so the caller
    can key a vector cache on `comment_id`. A comment whose embed returns None
    becomes its own singleton."""
    if not comments:
        return []
    vectors: list[list[float] | None] = [embed(c) for c in comments]
    groups: list[list[int]] = []
    centroids: list[list[float]] = []
    for i, vec in enumerate(vectors):
        if vec is None:
            groups.append([i])
            centroids.append([])  # never matches → stays singleton
            continue
        placed = False
        for g, centroid in enumerate(centroids):
            if centroid and _cosine(vec, centroid) >= threshold:
                groups[g].append(i)
                placed = True
                break
        if not placed:
            groups.append([i])
            centroids.append(vec)
    return groups
