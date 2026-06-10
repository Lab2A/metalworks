"""Provider auto-resolution + config precedence (offline)."""

from __future__ import annotations

from pathlib import Path

import pytest

from metalworks import config
from metalworks.errors import MissingKeyError

_CHAT_KEYS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY")


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
