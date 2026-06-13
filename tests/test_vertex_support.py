"""Tests for the Vertex AI support added to the Google adapters + config.

Covers the paths the pre-landing review flagged as untested: build_genai_client's
Vertex branch, vertex_enabled() truthiness, config routing under Vertex,
GoogleEmbedding batching, and the GoogleChatModel max_output_tokens clamp. The
SDK is faked via sys.modules (no network, no real google-genai needed).
"""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

GOOGLE_MODULES = ("google", "google.genai", "google.genai.types", "google.genai.errors")


class _RecordingClient:
    """Captures construction kwargs and serves a scripted embed_content."""

    last: _RecordingClient | None = None

    drop_one = False  # when True, embed_content returns one fewer embedding than inputs

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.embed_batches: list[int] = []
        _RecordingClient.last = self
        outer = self

        class _Models:
            def embed_content(self, *, model: str, contents: list[str], config: Any) -> Any:
                outer.embed_batches.append(len(contents))
                n = len(contents) - 1 if _RecordingClient.drop_one else len(contents)
                embs = [SimpleNamespace(values=[float(i), 0.5]) for i in range(n)]
                return SimpleNamespace(embeddings=embs)

        self.models = _Models()


def _install_google_fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Install a fake google.genai module tree with a recording Client."""
    google = ModuleType("google")
    genai = ModuleType("google.genai")
    types_mod = ModuleType("google.genai.types")
    errors_mod = ModuleType("google.genai.errors")

    genai.Client = _RecordingClient  # type: ignore[attr-defined]
    # types factories just echo their kwargs so callers can construct config.
    types_mod.GenerateContentConfig = lambda **kw: SimpleNamespace(**kw)  # type: ignore[attr-defined]
    types_mod.EmbedContentConfig = lambda **kw: SimpleNamespace(**kw)  # type: ignore[attr-defined]
    types_mod.ThinkingConfig = lambda **kw: SimpleNamespace(**kw)  # type: ignore[attr-defined]
    types_mod.HttpOptions = lambda **kw: SimpleNamespace(**kw)  # type: ignore[attr-defined]
    errors_mod.ClientError = type("ClientError", (Exception,), {})  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", types_mod)
    monkeypatch.setitem(sys.modules, "google.genai.errors", errors_mod)


def _clear_google_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "GOOGLE_GENAI_USE_VERTEXAI",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "VERTEX_PROJECT_ID",
        "GOOGLE_CLOUD_PROJECT",
        "VERTEX_LOCATION",
        "GOOGLE_CLOUD_LOCATION",
    ):
        monkeypatch.delenv(var, raising=False)


# ── vertex_enabled ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("value", "expected"),
    [("true", True), ("1", True), ("yes", True), ("ON", True), ("false", False),
     ("0", False), ("", False)],
)
def test_vertex_enabled_truthiness(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: bool
) -> None:
    from metalworks._genai_client import vertex_enabled

    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", value)
    assert vertex_enabled() is expected


def test_vertex_enabled_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    from metalworks._genai_client import vertex_enabled

    monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)
    assert vertex_enabled() is False


# ── build_genai_client ───────────────────────────────────────────────────


def test_build_client_vertex_passes_project_and_location(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_google_fakes(monkeypatch)
    _clear_google_env(monkeypatch)
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    monkeypatch.setenv("VERTEX_PROJECT_ID", "proj-x")
    monkeypatch.setenv("VERTEX_LOCATION", "global")
    from metalworks._genai_client import build_genai_client

    client = build_genai_client()
    assert client.kwargs == {"vertexai": True, "project": "proj-x", "location": "global"}


def test_build_client_vertex_defaults_location(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_google_fakes(monkeypatch)
    _clear_google_env(monkeypatch)
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proj-y")  # fallback project source
    from metalworks._genai_client import build_genai_client

    client = build_genai_client()
    assert client.kwargs["project"] == "proj-y"
    assert client.kwargs["location"] == "us-central1"


def test_build_client_vertex_missing_project_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_google_fakes(monkeypatch)
    _clear_google_env(monkeypatch)
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    from metalworks._genai_client import build_genai_client
    from metalworks.errors import MissingKeyError

    with pytest.raises(MissingKeyError):
        build_genai_client()


def test_build_client_api_key_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_google_fakes(monkeypatch)
    _clear_google_env(monkeypatch)
    monkeypatch.setenv("GOOGLE_API_KEY", "k-123")
    from metalworks._genai_client import build_genai_client

    client = build_genai_client()
    assert client.kwargs == {"api_key": "k-123"}


# ── config routing under Vertex ──────────────────────────────────────────


def test_resolve_chat_provider_routes_to_google_under_vertex(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from metalworks.config import _resolve_chat_provider

    _clear_google_env(monkeypatch)
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    monkeypatch.setattr("metalworks.config.load_config", lambda: {})
    provider, model = _resolve_chat_provider("gemini-3.1-pro-preview")
    assert provider == "google"
    assert model == "gemini-3.1-pro-preview"


def test_resolve_embeddings_picks_google_under_vertex(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_google_fakes(monkeypatch)
    _clear_google_env(monkeypatch)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    monkeypatch.setenv("VERTEX_PROJECT_ID", "proj-x")
    from metalworks.config import resolve_embeddings
    from metalworks.embeddings.adapters.google import GoogleEmbedding

    assert isinstance(resolve_embeddings(), GoogleEmbedding)


# ── GoogleEmbedding batching ─────────────────────────────────────────────


def test_embedding_batches_at_100_and_preserves_order(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_google_fakes(monkeypatch)
    _clear_google_env(monkeypatch)
    monkeypatch.setenv("GOOGLE_API_KEY", "k")
    from metalworks.embeddings.adapters.google import GoogleEmbedding

    emb = GoogleEmbedding(dim=2)
    vecs = emb.embed([f"t{i}" for i in range(250)], task="document")
    assert len(vecs) == 250
    # 250 items → three requests of 100/100/50.
    assert _RecordingClient.last is not None
    assert _RecordingClient.last.embed_batches == [100, 100, 50]
    # Order preserved: each batch restarts its index, so first of each batch is [0.0, 0.5].
    assert vecs[0] == [0.0, 0.5]


def test_embedding_count_mismatch_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_google_fakes(monkeypatch)
    _clear_google_env(monkeypatch)
    monkeypatch.setenv("GOOGLE_API_KEY", "k")
    from metalworks.embeddings.adapters.google import GoogleEmbedding

    monkeypatch.setattr(_RecordingClient, "drop_one", True)
    emb = GoogleEmbedding(dim=2)
    with pytest.raises(RuntimeError, match="count mismatch"):
        emb.embed(["a", "b", "c"], task="document")


# ── GoogleChatModel max_output_tokens clamp ──────────────────────────────


def test_config_kwargs_clamps_to_vertex_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_google_fakes(monkeypatch)
    _clear_google_env(monkeypatch)
    monkeypatch.setenv("GOOGLE_API_KEY", "k")
    from metalworks.llm.adapters.google import GoogleChatModel

    model = GoogleChatModel()
    # max_tokens + 2048 headroom would exceed 65536 → clamp.
    kw = model._config_kwargs("sys", 65000, 0.7, 0, 120.0)  # noqa: SLF001 - testing clamp logic
    assert kw["max_output_tokens"] == 65536


def test_config_kwargs_thinking_budget_adds_then_clamps(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_google_fakes(monkeypatch)
    _clear_google_env(monkeypatch)
    monkeypatch.setenv("GOOGLE_API_KEY", "k")
    from metalworks.llm.adapters.google import GoogleChatModel

    model = GoogleChatModel()
    kw = model._config_kwargs("sys", 1000, 0.7, 4000, 120.0)  # noqa: SLF001 - testing budget math
    assert kw["max_output_tokens"] == 5000  # 1000 + 4000, under the cap
    assert "thinking_config" in kw
