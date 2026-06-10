"""Provider auto-resolution + non-secret config, shared by the CLI and MCP server.

Two responsibilities:

1. **Provider resolution** — turn the ambient environment (which API keys are
   set) into concrete adapter instances. The rule everywhere is *secrets only
   from env*: this module never reads an API key out of a config file. Adapters
   are lazy-imported so importing this module costs nothing and works on a
   bare install with no extras.

2. **Non-secret config** — a small ``metalworks.toml`` (provider id, model id,
   store path) discovered in the cwd, then ``~/.config/metalworks/``. Precedence
   for any setting is: **explicit argument > environment variable > config.toml**.

Nothing here imports a provider SDK, ``duckdb``, or ``mcp`` at module top.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any

from metalworks.errors import MissingKeyError

if TYPE_CHECKING:
    from metalworks.embeddings import EmbeddingProvider
    from metalworks.llm import ChatModel
    from metalworks.search import SearchProvider
    from metalworks.stores import MemoryStores, SqliteStores

# Env vars that, when set, select a chat/embedding provider. Order matters:
# the first present key wins when no explicit provider is named.
_CHAT_KEY_ORDER: tuple[tuple[str, str], ...] = (
    ("anthropic", "ANTHROPIC_API_KEY"),
    ("openai", "OPENAI_API_KEY"),
    ("google", "GOOGLE_API_KEY"),
    ("google", "GEMINI_API_KEY"),
)

# The full list named in MissingKeyError so the message is actionable.
_ALL_CHAT_KEYS = "ANTHROPIC_API_KEY / OPENAI_API_KEY / GOOGLE_API_KEY (or GEMINI_API_KEY)"

_CONFIG_FILENAME = "metalworks.toml"
_DEFAULT_STORE_PATH = Path.home() / ".metalworks" / "store.db"


# ── Non-secret config (TOML) ────────────────────────────────────────────────


def config_search_paths() -> list[Path]:
    """Where ``load_config`` looks, highest precedence first: cwd, then
    ``~/.config/metalworks/``."""
    return [
        Path.cwd() / _CONFIG_FILENAME,
        Path.home() / ".config" / "metalworks" / _CONFIG_FILENAME,
    ]


def load_config() -> dict[str, Any]:
    """Merge the discovered config files, cwd winning over the home config.

    Returns an empty dict when no config file exists. Secrets are never read
    here — only non-secret settings (``provider``, ``model``, ``store``).
    """
    merged: dict[str, Any] = {}
    # Reverse so the cwd file (highest precedence) is applied last.
    for path in reversed(config_search_paths()):
        if not path.is_file():
            continue
        with path.open("rb") as fh:
            data = tomllib.load(fh)
        merged.update({k: v for k, v in data.items() if not isinstance(v, dict)})
    return merged


def default_config_path() -> Path:
    """The path ``save_config`` / ``init`` write to (the cwd file)."""
    return Path.cwd() / _CONFIG_FILENAME


def _toml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def save_config(config: dict[str, Any], *, path: Path | None = None) -> Path:
    """Write the non-secret config to ``path`` (default: cwd ``metalworks.toml``).

    Hand-rolled TOML emit (no tomli-w dependency) — the config is a flat table of
    scalars, so the serialization stays trivial.
    """
    target = path or default_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# metalworks — non-secret settings. Secrets come from the environment only.",
    ]
    lines.extend(f"{key} = {_toml_scalar(value)}" for key, value in sorted(config.items()))
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def setting(name: str, *, arg: str | None = None, env: str | None = None) -> str | None:
    """Resolve one setting under the precedence: explicit arg > env > config.toml."""
    if arg is not None:
        return arg
    if env is not None:
        env_val = os.environ.get(env)
        if env_val:
            return env_val
    value = load_config().get(name)
    return str(value) if value is not None else None


# ── Provider resolution ─────────────────────────────────────────────────────


def _resolve_chat_provider(model: str | None) -> tuple[str, str | None]:
    """Return (provider, model_id) from an explicit ``provider:id`` arg, the
    config file's ``provider``/``model``, or the first present API key."""
    if model and ":" in model:
        provider, _, model_id = model.partition(":")
        return provider.strip().lower(), (model_id.strip() or None)

    cfg = load_config()
    configured = cfg.get("provider")
    if isinstance(configured, str) and configured.strip():
        model_id = model or (str(cfg["model"]) if cfg.get("model") else None)
        return configured.strip().lower(), model_id

    for provider, env_var in _CHAT_KEY_ORDER:
        if os.environ.get(env_var):
            return provider, model
    raise MissingKeyError(_ALL_CHAT_KEYS, provider="chat model")


def resolve_chat(model: str | None = None) -> ChatModel:
    """Resolve a :class:`~metalworks.llm.ChatModel` from the environment.

    If ``model`` is ``"provider:id"`` that provider+id is used directly;
    otherwise the provider is taken from config or the first present API key
    (Anthropic → OpenAI → Google/Gemini). Raises
    :class:`~metalworks.errors.MissingKeyError` listing all three when no key
    is set. The adapter (and its SDK) is imported lazily.
    """
    provider, model_id = _resolve_chat_provider(model)

    if provider == "anthropic":
        from metalworks.llm.adapters.anthropic import AnthropicChatModel

        return AnthropicChatModel(model_id=model_id) if model_id else AnthropicChatModel()
    if provider == "openai":
        from metalworks.llm.adapters.openai import OpenAIChatModel

        return OpenAIChatModel(model_id=model_id) if model_id else OpenAIChatModel()
    if provider in ("google", "gemini"):
        from metalworks.llm.adapters.google import GoogleChatModel

        return GoogleChatModel(model_id=model_id) if model_id else GoogleChatModel()

    raise MissingKeyError(_ALL_CHAT_KEYS, provider=f"unknown chat provider '{provider}'")


def resolve_embeddings() -> EmbeddingProvider:
    """Resolve an :class:`~metalworks.embeddings.EmbeddingProvider`.

    Google (``GOOGLE_API_KEY`` / ``GEMINI_API_KEY``) is preferred, then OpenAI.
    Raises :class:`~metalworks.errors.MissingKeyError` when neither is set.
    """
    if os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"):
        from metalworks.embeddings.adapters.google import GoogleEmbedding

        return GoogleEmbedding()
    if os.environ.get("OPENAI_API_KEY"):
        from metalworks.embeddings.adapters.openai import OpenAIEmbedding

        return OpenAIEmbedding()
    raise MissingKeyError(
        "GOOGLE_API_KEY (or GEMINI_API_KEY) / OPENAI_API_KEY", provider="embeddings"
    )


def resolve_search() -> SearchProvider | None:
    """Resolve an external :class:`~metalworks.search.SearchProvider`, or ``None``.

    Exa (``EXA_API_KEY``) is preferred, then Tavily (``TAVILY_API_KEY``). Returns
    ``None`` when neither is set — the web stream then relies on model-native
    grounding, which is the intended graceful degradation, so this never raises.
    """
    if os.environ.get("EXA_API_KEY"):
        from metalworks.search.adapters.exa import ExaSearch

        return ExaSearch()
    if os.environ.get("TAVILY_API_KEY"):
        from metalworks.search.adapters.tavily import TavilySearch

        return TavilySearch()
    return None


# ── Store resolution ────────────────────────────────────────────────────────


def default_store(path: str | None = None) -> MemoryStores | SqliteStores:
    """The local store backend.

    ``":memory:"`` → :class:`~metalworks.stores.MemoryStores` (ephemeral, for
    tests and one-shot runs). Any other ``path`` (or the
    ``~/.metalworks/store.db`` default) → :class:`~metalworks.stores.SqliteStores`.
    Resolution order: explicit ``path`` > config ``store`` > default.
    """
    resolved = path or setting("store") or str(_DEFAULT_STORE_PATH)
    if resolved == ":memory:":
        from metalworks.stores import MemoryStores

        return MemoryStores()
    from metalworks.stores import SqliteStores

    store_path = Path(resolved).expanduser()
    store_path.parent.mkdir(parents=True, exist_ok=True)
    return SqliteStores(store_path)


__all__ = [
    "config_search_paths",
    "default_config_path",
    "default_store",
    "load_config",
    "resolve_chat",
    "resolve_embeddings",
    "resolve_search",
    "save_config",
    "setting",
]
