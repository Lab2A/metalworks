"""Regression tests for the 0.2.1 first-run fixes (from real plugin feedback).

1. The MCP research deps go through ``config.resolve_corpus_reader()`` (the live
   Arctic Shift reader by default) — NOT a hardcoded HF ``ArcticReader`` that 429s.
   This is the bug the live-reader default missed on the MCP surface.
2. A config ``model`` that is a routable ref (``deepseek/...``) works on its own,
   WITHOUT also pinning ``provider``, and beats stray Vertex autodetection.
3. preflight flags the Vertex-on + google-extra-missing landmine as an error.

All offline (pytest-socket blocks network).
"""

from __future__ import annotations

import pytest

from metalworks import config


def test_mcp_build_deps_uses_resolve_corpus_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    """The MCP pipeline's deps reader must come from the resolver (live default),
    not a hardcoded HF ArcticReader."""
    from metalworks.mcp import tools
    from metalworks.stores.memory import MemoryStores

    sentinel = object()
    monkeypatch.setattr(config, "resolve_chat", lambda: object())
    monkeypatch.setattr(config, "resolve_embeddings", lambda: object())
    monkeypatch.setattr(config, "resolve_search", lambda: None)
    monkeypatch.setattr(config, "default_store", lambda _p=None: MemoryStores())
    monkeypatch.setattr(config, "resolve_corpus_reader", lambda: sentinel)

    deps = tools._build_deps(None)  # noqa: SLF001 — exercising the deps builder
    assert deps.reader is sentinel  # the resolver result, not ArcticReader(...)


def test_config_model_alone_routes_without_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """`model = "deepseek/deepseek-v4-flash"` in config (no `provider`) routes to
    OpenRouter and beats stray Vertex env — the footgun the agent hit."""
    from metalworks.config import _resolve_chat_provider

    monkeypatch.delenv("METALWORKS_MODEL", raising=False)
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")  # would otherwise win
    monkeypatch.setattr(config, "load_config", lambda: {"model": "deepseek/deepseek-v4-flash"})

    provider, model_id = _resolve_chat_provider(None)
    assert provider == "openrouter"
    assert model_id == "deepseek/deepseek-v4-flash"


def test_config_provider_plus_model_still_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """A pinned provider + model keeps working exactly as before."""
    from metalworks.config import _resolve_chat_provider

    monkeypatch.delenv("METALWORKS_MODEL", raising=False)
    monkeypatch.setattr(config, "load_config", lambda: {"provider": "openai", "model": "gpt-5"})
    assert _resolve_chat_provider(None) == ("openai", "gpt-5")


def test_bare_config_model_does_not_hijack_vertex(monkeypatch: pytest.MonkeyPatch) -> None:
    """A bare config model id (no vendor namespace) is NOT self-routable, so a
    Vertex machine still resolves Google — the new branch didn't change that."""
    from metalworks.config import _resolve_chat_provider

    monkeypatch.delenv("METALWORKS_MODEL", raising=False)
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    monkeypatch.setattr(config, "load_config", lambda: {"model": "gemini-3.1-pro-preview"})
    provider, _ = _resolve_chat_provider(None)
    assert provider == "google"


def test_preflight_flags_vertex_without_google_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    """The #1 plugin landmine: Vertex on but google extra missing → an error hint."""
    from metalworks import preflight

    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    # google.genai unavailable; everything else available (so no other noise).
    monkeypatch.setattr(preflight, "module_available", lambda m: m != "google.genai")

    hints = preflight.doctor_hints()
    vertex_hints = [h for h in hints if h.startswith("GOOGLE_GENAI_USE_VERTEXAI is on")]
    assert vertex_hints, "preflight must flag Vertex-on + missing google extra"
    assert preflight._hint_severity(vertex_hints[0]) == "error"  # noqa: SLF001


def test_preflight_silent_when_vertex_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)
    from metalworks import preflight

    monkeypatch.setattr(preflight, "module_available", lambda m: True)
    hints = preflight.doctor_hints()
    assert not any(h.startswith("GOOGLE_GENAI_USE_VERTEXAI is on") for h in hints)
