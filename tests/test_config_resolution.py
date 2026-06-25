"""Provider auto-resolution + config precedence (offline)."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

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


def test_resolve_embeddings_prefers_openai_over_local(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pytest.importorskip("openai")  # adapter needs the provider SDK
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "vertex_enabled", lambda: False)
    for key in ("GOOGLE_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    assert type(config.resolve_embeddings()).__name__ == "OpenAIEmbedding"


def test_resolve_embeddings_falls_back_to_local_when_no_keys(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # No embeddings-capable key → the keyless local fastembed adapter. This must
    # construct OFFLINE and WITHOUT fastembed installed (construction does not
    # import the SDK), so the chat-only / Anthropic-only setup works end to end.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "vertex_enabled", lambda: False)
    for key in ("GOOGLE_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    provider = config.resolve_embeddings()
    assert type(provider).__name__ == "FastEmbedEmbedding"


_SEARCH_KEYS = ("EXA_API_KEY", "TAVILY_API_KEY", "PARALLEL_API_KEY", "FIRECRAWL_API_KEY")


def _clear_search_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _SEARCH_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_resolve_search_none_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_search_keys(monkeypatch)
    assert config.resolve_search() is None


def test_resolve_search_picks_parallel_when_only_parallel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # parallel-web gates the extra; install a fake so construction succeeds.
    monkeypatch.setitem(sys.modules, "parallel", ModuleType("parallel"))
    _clear_search_keys(monkeypatch)
    monkeypatch.setenv("PARALLEL_API_KEY", "pk-test")
    provider = config.resolve_search()
    assert type(provider).__name__ == "ParallelSearch"


def test_resolve_search_picks_firecrawl_when_only_firecrawl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "firecrawl", ModuleType("firecrawl"))
    _clear_search_keys(monkeypatch)
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test")
    provider = config.resolve_search()
    assert type(provider).__name__ == "FirecrawlSearch"


def test_resolve_search_precedence_parallel_below_tavily(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Tavily key present alongside Parallel → Tavily wins (earlier in the chain).
    pytest.importorskip("tavily")
    _clear_search_keys(monkeypatch)
    monkeypatch.setenv("TAVILY_API_KEY", "tv-test")
    monkeypatch.setenv("PARALLEL_API_KEY", "pk-test")
    provider = config.resolve_search()
    assert type(provider).__name__ == "TavilySearch"


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


# ── [sources] table + resolve_sources (Phase 2d) ─────────────────────────────


def test_enabled_source_ids_defaults_to_reddit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    assert config.enabled_source_ids() == ["reddit"]
    assert config.default_source_id() == "reddit"


def test_sources_config_is_read_ordered(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "metalworks.toml").write_text(
        '[sources]\nenabled = ["hackernews", "reddit"]\ndefault = "hackernews"\n',
        encoding="utf-8",
    )
    assert config.enabled_source_ids() == ["hackernews", "reddit"]
    assert config.default_source_id() == "hackernews"


def test_save_sources_config_preserves_scalars(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    config.save_config({"provider": "openai", "model": "openai/gpt-5"})
    config.save_sources_config(["reddit", "hackernews"])
    text = (tmp_path / "metalworks.toml").read_text()
    # The scalar settings survive the [sources] rewrite.
    assert 'provider = "openai"' in text
    assert 'model = "openai/gpt-5"' in text
    assert config.enabled_source_ids() == ["reddit", "hackernews"]


def test_resolve_sources_default_is_reddit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # With nothing configured, resolve_sources defaults to the Reddit/Arctic
    # connector. That connector needs a reader (and optional comments client),
    # supplied as kwargs — the CLI callers always pass them; a fake is enough.
    monkeypatch.chdir(tmp_path)

    class _FakeReader:
        def latest_available_month(self, content_type: str = "submissions"):  # pragma: no cover
            from metalworks.research.types import MonthRef

            return MonthRef(2024, 1)

        def close(self) -> None:  # pragma: no cover
            return None

    sources = config.resolve_sources(reader=_FakeReader())
    assert len(sources) == 1
    assert sources[0].source_id == "reddit"


def test_resolve_sources_override_via_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from metalworks.research.sources import register_source

    class _Fake:
        source_id = "fake"

        def pull(self, *, query, window, limit=None):  # pragma: no cover - protocol stub
            return iter(())

        def comments_for(self, record_ids):  # pragma: no cover
            return None

        def latest_window(self):  # pragma: no cover
            from metalworks.research.sources import SourceWindow

            return SourceWindow()

    register_source("fake", lambda **k: _Fake())
    sources = config.resolve_sources(override=["fake"])
    assert [s.source_id for s in sources] == ["fake"]


def test_build_source_drops_unaccepted_kwargs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A keyless source factory that accepts NO kwargs must still construct when
    # resolve_sources is called with reader=/comments= (for the Arctic source).
    from metalworks.research.sources import register_source

    class _Keyless:
        source_id = "keyless"

    register_source("keyless", lambda: _Keyless())
    sources = config.resolve_sources(override=["keyless"], reader=object(), comments=object())
    assert sources[0].source_id == "keyless"


def test_resolve_sources_never_leaks_arctic_reader_into_hn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # resolve_sources passes the Reddit reader/comments to EVERY factory. HN's
    # __init__ accepts ``reader=`` and swallows extras, so a naive wiring would
    # mis-wire it with the Arctic reader. Its factory must drop the foreign reader
    # (and ``comments``) and build its OWN reader — no network, no download.
    pytest.importorskip("duckdb")  # the HN reader needs duckdb
    from metalworks.research.sources.hn_archive import (
        HackerNewsArchiveReader,
        HackerNewsArchiveSource,
    )

    class _FakeArctic:
        """Stand-in for the Reddit reader / comment client resolve_sources passes."""

    sources = config.resolve_sources(
        override=["hackernews_archive"], reader=_FakeArctic(), comments=_FakeArctic()
    )
    assert len(sources) == 1
    hn = sources[0]
    assert isinstance(hn, HackerNewsArchiveSource)
    # Its reader is its OWN archive reader, NOT the foreign Arctic one.
    assert isinstance(hn._reader, HackerNewsArchiveReader)  # noqa: SLF001 - asserting no leak
    assert not isinstance(hn._reader, _FakeArctic)  # noqa: SLF001 - asserting no leak


def test_resolve_sources_adds_hn_alongside_reddit_with_own_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Enabling hackernews_archive next to reddit adds a second source; the Arctic
    # source keeps the passed reader while HN keeps its own (the wiring stays split).
    pytest.importorskip("duckdb")
    from metalworks.research.sources.arctic import ArcticItemSource
    from metalworks.research.sources.hn_archive import (
        HackerNewsArchiveReader,
        HackerNewsArchiveSource,
    )

    class _FakeArctic:
        pass

    arctic_reader = _FakeArctic()
    sources = config.resolve_sources(
        override=["reddit", "hackernews_archive"], reader=arctic_reader, comments=_FakeArctic()
    )
    assert [type(s).__name__ for s in sources] == [
        ArcticItemSource.__name__,
        HackerNewsArchiveSource.__name__,
    ]
    # Reddit/Arctic got the passed reader; HN built its own.
    assert sources[0]._reader is arctic_reader  # noqa: SLF001 - asserting split wiring
    assert isinstance(sources[1]._reader, HackerNewsArchiveReader)  # noqa: SLF001 - split wiring


def test_hn_factory_preserves_explicit_archive_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    # The hardening must NOT clobber a legitimately-passed HN reader (explicit
    # construction via get_source(..., reader=HackerNewsArchiveReader(...))).
    pytest.importorskip("duckdb")
    from metalworks.research.sources import get_source
    from metalworks.research.sources.hn_archive import HackerNewsArchiveReader

    reader = HackerNewsArchiveReader(data_root="./hn-corpus")
    source = get_source("hackernews_archive", reader=reader)
    assert source._reader is reader  # type: ignore[attr-defined]  # noqa: SLF001 - explicit reader kept


# ── llm_timeout_s: the configurable reasoning-safe timeout knob ──


def test_llm_timeout_defaults_to_300(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("METALWORKS_LLM_TIMEOUT", raising=False)
    monkeypatch.setattr(config, "load_config", lambda: {})
    assert config.llm_timeout_s() == 300.0


def test_llm_timeout_reads_config_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("METALWORKS_LLM_TIMEOUT", raising=False)
    monkeypatch.setattr(config, "load_config", lambda: {"llm_timeout": 90})
    assert config.llm_timeout_s() == 90.0


def test_llm_timeout_env_wins_over_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "load_config", lambda: {"llm_timeout": 90})
    monkeypatch.setenv("METALWORKS_LLM_TIMEOUT", "45")
    assert config.llm_timeout_s() == 45.0


def test_llm_timeout_bad_value_degrades_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "load_config", lambda: {})
    monkeypatch.setenv("METALWORKS_LLM_TIMEOUT", "not-a-number")
    assert config.llm_timeout_s() == 300.0
    monkeypatch.setenv("METALWORKS_LLM_TIMEOUT", "-5")
    assert config.llm_timeout_s() == 300.0
