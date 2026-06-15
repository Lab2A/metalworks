"""Provider auto-resolution + config precedence (offline)."""

from __future__ import annotations

from pathlib import Path

import pytest

from metalworks import config
from metalworks.config import _resolve_chat_provider as resolve_provider
from metalworks.errors import MissingKeyError

_CHAT_KEYS = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "OPENROUTER_API_KEY",
)


def _clear_chat_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _CHAT_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_resolve_chat_picks_anthropic(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pytest.importorskip("anthropic")  # adapter needs the provider SDK
    monkeypatch.chdir(tmp_path)  # no config file in scope
    _clear_chat_keys(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    model = config.resolve_chat()
    assert type(model).__name__ == "AnthropicChatModel"


def test_resolve_chat_picks_openai_when_only_openai(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("openai")  # adapter needs the provider SDK
    monkeypatch.chdir(tmp_path)
    _clear_chat_keys(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    model = config.resolve_chat()
    assert type(model).__name__ == "OpenAIChatModel"


def test_resolve_chat_picks_google_on_gemini_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("google.genai")  # adapter needs the provider SDK
    monkeypatch.chdir(tmp_path)
    _clear_chat_keys(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "sk-test")
    model = config.resolve_chat()
    assert type(model).__name__ == "GoogleChatModel"


def test_resolve_chat_anthropic_wins_over_openai(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("anthropic")  # adapter needs the provider SDK
    monkeypatch.chdir(tmp_path)
    _clear_chat_keys(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    monkeypatch.setenv("OPENAI_API_KEY", "b")
    assert type(config.resolve_chat()).__name__ == "AnthropicChatModel"


def test_resolve_chat_explicit_provider_id(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pytest.importorskip("anthropic")  # adapter needs the provider SDK
    monkeypatch.chdir(tmp_path)
    _clear_chat_keys(monkeypatch)
    # An explicit provider:id beats env-key order — only OpenAI key is set, but
    # we ask for anthropic explicitly.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    model = config.resolve_chat("anthropic:claude-test-id")
    assert type(model).__name__ == "AnthropicChatModel"
    assert model.model_id == "claude-test-id"


def test_resolve_chat_no_keys_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    _clear_chat_keys(monkeypatch)
    with pytest.raises(MissingKeyError) as exc:
        config.resolve_chat()
    # Message names all three providers so the fix is actionable.
    assert "ANTHROPIC_API_KEY" in exc.value.fix or "ANTHROPIC_API_KEY" in str(exc.value)


def test_resolve_embeddings_prefers_google(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("google.genai")  # adapter needs the provider SDK
    monkeypatch.setenv("GOOGLE_API_KEY", "g")
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    assert type(config.resolve_embeddings()).__name__ == "GoogleEmbedding"


def test_resolve_embeddings_none_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("GOOGLE_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(MissingKeyError):
        config.resolve_embeddings()


def test_resolve_search_none_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    assert config.resolve_search() is None


def test_config_save_load_round_trip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    config.save_config({"provider": "openai", "model": "gpt-test", "store": ":memory:"})
    loaded = config.load_config()
    assert loaded["provider"] == "openai"
    assert loaded["model"] == "gpt-test"
    assert (tmp_path / "metalworks.toml").is_file()


def test_setting_precedence_arg_over_env_over_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    config.save_config({"store": "/from/file"})
    monkeypatch.setenv("MW_TEST_STORE", "/from/env")
    # arg wins
    assert config.setting("store", arg="/from/arg", env="MW_TEST_STORE") == "/from/arg"
    # env wins over file
    assert config.setting("store", env="MW_TEST_STORE") == "/from/env"
    # file is the floor
    monkeypatch.delenv("MW_TEST_STORE", raising=False)
    assert config.setting("store") == "/from/file"


def test_default_store_memory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    store = config.default_store(":memory:")
    assert type(store).__name__ == "MemoryStores"


def test_default_store_sqlite_path(tmp_path: Path) -> None:
    store = config.default_store(str(tmp_path / "s.db"))
    assert type(store).__name__ == "SqliteStores"
    assert (tmp_path / "s.db").exists()


# ── provider/model slash refs (A1 routing) + resolve_models ──────────────────


def test_slash_ref_known_provider_routes_native() -> None:
    # A bare known-provider slash stays native (never mis-routes to OpenRouter).
    assert resolve_provider("anthropic/claude-opus") == ("anthropic", "claude-opus")
    assert resolve_provider("google/gemini-3-pro") == ("google", "gemini-3-pro")


def test_slash_ref_explicit_compat_prefix() -> None:
    assert resolve_provider("openrouter/x/y") == ("openrouter", "x/y")
    assert resolve_provider("openai-compatible/local") == (
        "openai-compatible",
        "local",
    )


def test_slash_ref_unknown_vendor_routes_to_openrouter() -> None:
    # Unknown head (a vendor namespace) → OpenRouter, full ref as the id.
    assert resolve_provider("meta-llama/llama-3-70b") == (
        "openrouter",
        "meta-llama/llama-3-70b",
    )


def test_colon_ref_still_works() -> None:
    assert resolve_provider("anthropic:claude-x") == ("anthropic", "claude-x")


def test_resolve_chat_openrouter_branch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pytest.importorskip("openai")  # compat adapter wraps the openai SDK
    monkeypatch.chdir(tmp_path)
    _clear_chat_keys(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    model = config.resolve_chat("openrouter/meta-llama/llama-3-70b")
    assert type(model).__name__ == "OpenAIChatModel"
    assert model.capabilities.native_structured is False


def test_resolve_chat_openrouter_anthropic_ref_routes_compat(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # An explicit openrouter/ ref carrying a native vendor namespace
    # (anthropic/claude-…) must still route to the OpenAI-compatible client when
    # OPENROUTER_API_KEY is set — construction only, no network call.
    pytest.importorskip("openai")
    monkeypatch.chdir(tmp_path)
    _clear_chat_keys(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    model = config.resolve_chat("openrouter/anthropic/claude-opus-4-6")
    assert type(model).__name__ == "OpenAIChatModel"
    assert model.model_id == "anthropic/claude-opus-4-6"
    assert model.capabilities.native_structured is False


def test_resolve_chat_openrouter_single_key_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # With no native key set, a lone OPENROUTER_API_KEY is a recognized
    # single-key path: env inference routes to the OpenAI-compatible client.
    pytest.importorskip("openai")
    monkeypatch.chdir(tmp_path)
    _clear_chat_keys(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    assert resolve_provider(None) == ("openrouter", None)
    model = config.resolve_chat()
    assert type(model).__name__ == "OpenAIChatModel"


def test_resolve_chat_native_key_wins_over_openrouter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # OpenRouter recognition must never preempt the native order: a native key
    # present alongside OPENROUTER_API_KEY still resolves native.
    pytest.importorskip("openai")
    monkeypatch.chdir(tmp_path)
    _clear_chat_keys(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    assert resolve_provider(None) == ("openai", None)


def test_resolve_models_fast_falls_back_to_main(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("anthropic")
    monkeypatch.chdir(tmp_path)
    _clear_chat_keys(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    main, fast = config.resolve_models()
    assert main is fast  # no fast_model given → fast slot is the main model
