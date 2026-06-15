"""Local, keyless EmbeddingProvider adapter (``metalworks[research]``, fastembed).

This is the *floor* provider: it runs a quantized ONNX model on-device with no
API key, so any chat-only setup (including an Anthropic-only one, since Anthropic
ships no embeddings API) can still build and query a vector index end to end.

Mapping notes:

- Model: ``BAAI/bge-small-en-v1.5`` — 384-dim, the fastembed default small
  English model. The ``fastembed/`` prefix on ``model_id`` keeps the persisted
  :class:`~metalworks.embeddings.IndexIdentity` distinct from any same-named
  model served through a different runtime (the provenance tag is
  ``fastembed-onnx``).
- ``task`` → bge is asymmetric: ``query`` routes to fastembed's ``query_embed``
  (which prepends the retrieval instruction), ``document`` to ``embed``.

Construction does **not** import fastembed, so the adapter can be selected (and
its identity inspected) on a bare install. The SDK is imported lazily on the
first :meth:`embed` call and the model instance is cached thereafter.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from metalworks.embeddings import PROTOCOL_VERSION, IndexIdentity
from metalworks.errors import MissingExtraError

if TYPE_CHECKING:
    from collections.abc import Sequence

# Provenance tag baked into the persisted identity — same vectors from a
# different runtime must not be treated as interchangeable.
PROVENANCE = "fastembed-onnx"

_DEFAULT_FASTEMBED_MODEL = "BAAI/bge-small-en-v1.5"


class FastEmbedEmbedding:
    """EmbeddingProvider over fastembed's local ONNX ``TextEmbedding``.

    Keyless and offline-capable once the model weights are cached. The first
    :meth:`embed` call downloads the weights (a few tens of MB) — there is no
    network cost at construction time.
    """

    protocol_version: ClassVar[str] = PROTOCOL_VERSION

    def __init__(
        self,
        fastembed_model: str = _DEFAULT_FASTEMBED_MODEL,
        *,
        dim: int = 384,
    ) -> None:
        # Intentionally NO fastembed import here: selecting this provider (and
        # reading its identity) must work even when the extra isn't installed.
        self._fastembed_model = fastembed_model
        self.model_id = f"fastembed/{fastembed_model}"
        self.dim = dim
        self._model: Any = None

    def _load_model(self) -> Any:
        if self._model is None:
            try:
                fastembed = importlib.import_module("fastembed")
            except ImportError as exc:
                raise MissingExtraError("research", package="fastembed") from exc
            self._model = fastembed.TextEmbedding(model_name=self._fastembed_model)
        return self._model

    def identity(self) -> IndexIdentity:
        """The stable identity persisted next to vectors this provider emits.

        Provenance (:data:`PROVENANCE`) is encoded in ``model_id`` via the
        ``fastembed/`` prefix, so a same-named model on a different runtime gets
        a distinct identity and the mismatch guard fires instead of degrading
        retrieval silently.
        """
        return IndexIdentity(embedding_model_id=self.model_id, dim=self.dim)

    def embed(
        self,
        texts: Sequence[str],
        *,
        task: Literal["document", "query"] = "document",
    ) -> list[list[float]]:
        model = self._load_model()
        items = list(texts)
        # bge is asymmetric — queries get the retrieval instruction prepended.
        generator = model.query_embed(items) if task == "query" else model.embed(items)
        return [[float(v) for v in vector] for vector in generator]
