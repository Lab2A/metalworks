"""Cross-stream triangulation: link Reddit clusters to web findings + weight
confidence.

Two stages:
- `triangulate(...)` — the LLM cross-reference + must_address resolution call,
  with list-id-prefixed index validation and 3x retry (raises
  `TriangulationFailedError` on persistent failure).
- `apply_cross_stream_confidence(...)` — the pure downgrade-on-disagreement
  signal adjustment, applicable independently of the LLM call.
"""

from __future__ import annotations

from metalworks.research.triangulate.confidence_weighter import apply_cross_stream_confidence
from metalworks.research.triangulate.triangulator import (
    TriangulationFailedError,
    triangulate,
)

__all__ = [
    "TriangulationFailedError",
    "apply_cross_stream_confidence",
    "triangulate",
]
