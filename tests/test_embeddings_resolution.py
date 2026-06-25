"""Regression tests for embeddings resolution robustness (0.3.2).

The bug: a machine with stray Vertex env (`GOOGLE_GENAI_USE_VERTEXAI=true` +
a `GOOGLE_APPLICATION_CREDENTIALS` pointing at a deleted key) made
`resolve_embeddings()` return a doomed Google adapter that crashed on first
embed — even for an OpenRouter-only user who wanted the keyless local model.
Now it degrades to local, and `METALWORKS_EMBEDDINGS` is an explicit override.
"""

from __future__ import annotations

import pytest

from metalworks import config
from metalworks.embeddings.adapters.fastembed import FastEmbedEmbedding

_EMBED_ENV = (
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_GENAI_USE_VERTEXAI",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "METALWORKS_EMBEDDINGS",
)


def _clear(monkeypatch: pytest.MonkeyPatch) -> None:
    for v in _EMBED_ENV:
        monkeypatch.delenv(v, raising=False)


def test_vertex_on_with_missing_creds_degrades_to_local(monkeypatch: pytest.MonkeyPatch) -> None:
    """The exact reported crash: Vertex on, creds path missing, no other key → local."""
    _clear(monkeypatch)
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/nonexistent/vertex.json")
    assert isinstance(config.resolve_embeddings(), FastEmbedEmbedding)


def test_openrouter_only_uses_local(monkeypatch: pytest.MonkeyPatch) -> None:
    """An OpenRouter-only setup (no Google/OpenAI key, no Vertex) → local embeddings."""
    _clear(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-x")
    assert isinstance(config.resolve_embeddings(), FastEmbedEmbedding)


def test_metalworks_embeddings_local_override_beats_google_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`METALWORKS_EMBEDDINGS=local` forces fastembed even with a Google key present."""
    _clear(monkeypatch)
    monkeypatch.setenv("GOOGLE_API_KEY", "g-x")
    monkeypatch.setenv("METALWORKS_EMBEDDINGS", "local")
    assert isinstance(config.resolve_embeddings(), FastEmbedEmbedding)


def test_vertex_on_with_present_creds_still_uses_google(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    """A REAL Vertex setup (creds file exists) is unaffected — still Google."""
    pytest.importorskip("google.genai")
    _clear(monkeypatch)
    creds = tmp_path / "vertex.json"  # type: ignore[operator]
    creds.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(creds))
    monkeypatch.setenv("VERTEX_PROJECT_ID", "test-project")  # Vertex client needs a project
    from metalworks.embeddings.adapters.google import GoogleEmbedding

    assert isinstance(config.resolve_embeddings(), GoogleEmbedding)


def test_google_key_present_uses_google(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("google.genai")
    _clear(monkeypatch)
    monkeypatch.setenv("GOOGLE_API_KEY", "g-x")
    from metalworks.embeddings.adapters.google import GoogleEmbedding

    assert isinstance(config.resolve_embeddings(), GoogleEmbedding)


def test_preflight_flags_vertex_missing_creds(monkeypatch: pytest.MonkeyPatch) -> None:
    """preflight surfaces the missing-creds degrade (now non-fatal, but visible)."""
    from metalworks import preflight

    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/nonexistent/vertex.json")
    monkeypatch.setattr(preflight, "module_available", lambda m: True)  # google.genai present
    hints = preflight.doctor_hints()
    assert any("points at a\nmissing file" in h or "missing file" in h for h in hints)
