"""Provider auto-resolution + non-secret config, shared by the CLI and MCP server.

Two responsibilities:

1. **Provider resolution** — turn the ambient environment (which API keys are
   set) into concrete adapter instances. The rule everywhere is *secrets only
   from env*: this module never reads an API key out of a config file. Adapters
   are lazy-imported so importing this module costs nothing and works on a
   bare install with no extras.

2. **Non-secret config** — a small TOML (provider id, model id, store path).
   Discovered, highest precedence first, in the active project's
   ``.metalworks/config.toml``, then a legacy cwd ``metalworks.toml``, then
   ``~/.config/metalworks/``. Precedence for any setting is: **explicit
   argument > environment variable > config file**.

Nothing here imports a provider SDK, ``duckdb``, or ``mcp`` at module top.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from metalworks._genai_client import vertex_enabled
from metalworks.errors import MissingKeyError
from metalworks.project import Project

if TYPE_CHECKING:
    from metalworks.embeddings import EmbeddingProvider
    from metalworks.llm import ChatModel
    from metalworks.research.sources import ItemSource
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

# Single-key fallback paths. These are *recognized* provider keys, but they sit
# below the native order: a native key (above) always wins. When none of the
# native keys is set and no model/config names a provider, the first present key
# here routes to its OpenAI-compatible provider — so one OpenRouter key reaches
# many models, like the bundled-SDK universal-client design intends.
_COMPAT_KEY_ORDER: tuple[tuple[str, str], ...] = (("openrouter", "OPENROUTER_API_KEY"),)

# The full list named in MissingKeyError so the message is actionable.
_ALL_CHAT_KEYS = (
    "ANTHROPIC_API_KEY / OPENAI_API_KEY / GOOGLE_API_KEY (or GEMINI_API_KEY) / OPENROUTER_API_KEY"
)

# `provider/model` slash-ref routing (the Hermes/OpenClaw convention). Native
# heads dispatch to the official SDK adapter; compat heads dispatch to the
# OpenAI-compatible adapter. Any *other* head (a vendor namespace such as
# ``meta-llama/llama-3``) is treated as an OpenRouter model id verbatim, so a
# bare ``anthropic/claude-x`` never silently mis-routes to OpenRouter.
_NATIVE_PROVIDERS = frozenset({"anthropic", "openai", "google", "gemini"})
_COMPAT_PROVIDERS = frozenset({"openrouter", "openai-compatible", "compat"})

_CONFIG_FILENAME = "metalworks.toml"
_DEFAULT_STORE_PATH = Path.home() / ".metalworks" / "store.db"

# The default active source when nothing is configured. Reddit (the Arctic
# connector) stays the default for now — do NOT change this without an explicit
# decision; ``resolve_sources`` falls back to it and every existing caller relies
# on it.
_DEFAULT_SOURCE = "reddit"


# ── Non-secret config (TOML) ────────────────────────────────────────────────


def config_search_paths() -> list[Path]:
    """Where ``load_config`` looks, highest precedence first: the active
    project's ``.metalworks/config.toml``, then a legacy cwd ``metalworks.toml``,
    then ``~/.config/metalworks/``."""
    paths: list[Path] = []
    project = Project.find()
    if project is not None:
        paths.append(project.config_path)
    paths.append(Path.cwd() / _CONFIG_FILENAME)
    paths.append(Path.home() / ".config" / "metalworks" / _CONFIG_FILENAME)
    return paths


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
    """The path ``save_config`` / ``init`` write to: the active project's
    ``.metalworks/config.toml`` if a project exists, else a cwd ``metalworks.toml``
    (legacy / non-project use)."""
    project = Project.find()
    return project.config_path if project is not None else Path.cwd() / _CONFIG_FILENAME


def _toml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _toml_array(values: list[str]) -> str:
    """Emit a TOML array of strings on one line (used for ``[sources].enabled``)."""
    return "[" + ", ".join(_toml_scalar(v) for v in values) + "]"


def save_config(config: dict[str, Any], *, path: Path | None = None) -> Path:
    """Write the non-secret config to ``path`` (default: cwd ``metalworks.toml``).

    Hand-rolled TOML emit (no tomli-w dependency). The body is a flat table of
    scalars; the one nested table we emit is ``[sources]`` (passed as a ``dict``
    under the ``"sources"`` key), so onboarding/CLI writes can persist the
    ordered ``enabled`` array alongside the scalar settings in one file.
    """
    target = path or default_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# metalworks — non-secret settings. Secrets come from the environment only.",
    ]
    scalars: dict[str, Any] = {k: v for k, v in config.items() if not isinstance(v, dict)}
    tables: dict[str, dict[str, Any]] = {
        k: cast("dict[str, Any]", v) for k, v in config.items() if isinstance(v, dict)
    }
    lines.extend(f"{key} = {_toml_scalar(value)}" for key, value in sorted(scalars.items()))
    for table_name, table in sorted(tables.items()):
        lines.append("")
        lines.append(f"[{table_name}]")
        for key, value in sorted(table.items()):
            if isinstance(value, list):
                items = [str(v) for v in cast("list[Any]", value)]
                lines.append(f"{key} = {_toml_array(items)}")
            else:
                lines.append(f"{key} = {_toml_scalar(value)}")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def _full_config_at(path: Path) -> dict[str, Any]:
    """Read every top-level key (scalars AND tables) from one config file.

    ``load_config`` intentionally merges only scalars across files; for an
    in-place rewrite of a single file we need its full contents (so a sources
    edit preserves the scalar settings already in it). Missing file → ``{}``.
    """
    if not path.is_file():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def save_sources_config(
    enabled: list[str], *, default: str | None = None, path: Path | None = None
) -> Path:
    """Persist the ``[sources]`` table into the target config file in place.

    Reads the target file's full contents (scalars + any existing ``[sources]``),
    replaces the ``enabled`` list (and ``default`` when given, preserving a prior
    one otherwise), and rewrites via :func:`save_config` so the scalar settings
    already in the file are kept. Default target: the active project's config,
    else the cwd ``metalworks.toml`` — the same target ``save_config`` uses.
    """
    target = path or default_config_path()
    existing = _full_config_at(target)
    prior_sources = existing.get("sources")
    sources: dict[str, Any] = (
        dict(cast("dict[str, Any]", prior_sources)) if isinstance(prior_sources, dict) else {}
    )
    sources["enabled"] = list(enabled)
    if default is not None:
        sources["default"] = default
    existing["sources"] = sources
    return save_config(existing, path=target)


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


# ── [sources] table ──────────────────────────────────────────────────────────


def load_sources_config() -> dict[str, Any]:
    """Read the merged ``[sources]`` table (cwd winning over the home config).

    ``load_config`` deliberately ignores nested tables (it keeps only scalar
    top-level keys), so the ordered ``[sources]`` table needs its own reader.
    The schema is::

        [sources]
        enabled = ["reddit", "hackernews"]   # ordered active source ids
        default = "reddit"                    # optional preferred id

    Returns an empty dict when no file declares a ``[sources]`` table. Like
    ``load_config`` it never reads secrets — source credentials stay env-only.
    """
    merged: dict[str, Any] = {}
    # Reverse so the cwd file (highest precedence) is applied last.
    for path in reversed(config_search_paths()):
        if not path.is_file():
            continue
        with path.open("rb") as fh:
            data = tomllib.load(fh)
        section = data.get("sources")
        if isinstance(section, dict):
            merged.update(cast("dict[str, Any]", section))
    return merged


def enabled_source_ids() -> list[str]:
    """The ordered active source ids from ``[sources].enabled``.

    Defaults to ``["reddit"]`` (the Arctic connector) when nothing is configured
    — Reddit stays the default for now. Non-string / empty entries are dropped so
    a malformed config degrades to the default rather than crashing a run.
    """
    enabled = load_sources_config().get("enabled")
    if isinstance(enabled, list):
        items = cast("list[object]", enabled)
        ids = [item.strip() for item in items if isinstance(item, str) and item.strip()]
        if ids:
            return ids
    return [_DEFAULT_SOURCE]


def default_source_id() -> str:
    """The preferred source id from ``[sources].default`` (else the first enabled)."""
    configured = load_sources_config().get("default")
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    return enabled_source_ids()[0]


def resolve_sources(override: list[str] | None = None, **source_kwargs: Any) -> list[ItemSource]:
    """Construct the active :class:`ItemSource` connectors, in order.

    Mirrors :func:`resolve_search`: it maps source *ids* — the explicit
    ``override`` list when given, else ``[sources].enabled`` from config, else the
    ``["reddit"]`` default — through :func:`~metalworks.research.sources.get_source`
    from the registry. Each id is constructed with whichever of ``source_kwargs``
    its factory accepts (so a caller can pass ``reader=`` / ``comments=`` for the
    Arctic connector while a keyless connector ignores them). Secrets stay
    env-only — nothing here reads a credential.

    An unknown id raises ``KeyError`` from the registry (the CLI surfaces it).
    """
    from metalworks.research.sources import get_source

    ids = override if override is not None else enabled_source_ids()
    return [_build_source(get_source, sid, source_kwargs) for sid in ids]


def _build_source(get_source: Any, source_id: str, source_kwargs: dict[str, Any]) -> ItemSource:
    """Construct one source, passing only the kwargs its factory accepts.

    A connector like Arctic needs ``reader=`` / ``comments=``; a keyless one
    takes none. Rather than make callers know which is which, we try the full
    kwarg set and fall back to the accepted subset (then to none) on a
    ``TypeError`` so an extra kwarg never breaks a keyless source.
    """
    if not source_kwargs:
        return cast("ItemSource", get_source(source_id))
    try:
        return cast("ItemSource", get_source(source_id, **source_kwargs))
    except TypeError:
        return cast("ItemSource", get_source(source_id))


# ── Provider resolution ─────────────────────────────────────────────────────


def _resolve_chat_provider(model: str | None) -> tuple[str, str | None]:
    """Return (provider, model_id) from an explicit ``provider:id`` arg, the
    config file's ``provider``/``model``, or the first present API key."""
    if model and ":" in model:
        provider, _, model_id = model.partition(":")
        return provider.strip().lower(), (model_id.strip() or None)
    if model and "/" in model:
        head, _, rest = model.partition("/")
        head_l = head.strip().lower()
        if head_l in _NATIVE_PROVIDERS or head_l in _COMPAT_PROVIDERS:
            return head_l, (rest.strip() or None)
        # Unknown vendor namespace → OpenRouter, with the full ref as the id.
        return "openrouter", model.strip()

    cfg = load_config()
    configured = cfg.get("provider")
    if isinstance(configured, str) and configured.strip():
        model_id = model or (str(cfg["model"]) if cfg.get("model") else None)
        return configured.strip().lower(), model_id

    for provider, env_var in _CHAT_KEY_ORDER:
        if os.environ.get(env_var):
            return provider, model
    # Vertex AI uses ADC (a service account), not a chat API key — so the key
    # loop above misses it. When Vertex mode is on, route to the Google adapter.
    if vertex_enabled():
        return "google", model
    # No native key (and no Vertex): fall back to a recognized compat key. This
    # never preempts the native order above — it only fires when none is set.
    for provider, env_var in _COMPAT_KEY_ORDER:
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
    if provider == "openrouter":
        from metalworks.llm.adapters.openai import OpenAIChatModel

        return OpenAIChatModel(
            model_id=model_id or "openrouter/auto",
            api_key_env="OPENROUTER_API_KEY",
            base_url="https://openrouter.ai/api/v1",
            native_structured=False,  # OpenRouter passthrough varies by model
        )
    if provider in ("openai-compatible", "compat"):
        from metalworks.llm.adapters.openai import OpenAIChatModel

        base_url = os.environ.get("OPENAI_BASE_URL")
        if not base_url:
            raise MissingKeyError("OPENAI_BASE_URL", provider="openai-compatible")
        return OpenAIChatModel(
            model_id=model_id or "",
            api_key_env="OPENAI_API_KEY",
            base_url=base_url,
            native_structured=False,
        )

    raise MissingKeyError(_ALL_CHAT_KEYS, provider=f"unknown chat provider '{provider}'")


def _config_fallback_models() -> list[str]:
    """Read the optional non-secret ``fallback_models`` config setting.

    Accepts a TOML array of refs (``fallback_models = ["openai/gpt-5", ...]``).
    Returns ``[]`` when unset or not a list of strings — an empty list means *no
    wrapper*, preserving default behaviour.
    """
    value = load_config().get("fallback_models")
    if isinstance(value, list):
        items = cast("list[object]", value)
        return [item for item in items if isinstance(item, str) and item.strip()]
    return []


def resolve_chat_chain(
    model: str | None = None,
    fallback_models: list[str] | None = None,
) -> ChatModel:
    """Resolve the primary chat model, optionally wrapped in a fallback chain.

    The primary is resolved exactly as :func:`resolve_chat` would. When at least
    one fallback ref is configured — via the explicit ``fallback_models``
    argument, else the ``fallback_models`` config-file setting — each fallback is
    resolved with the same chat resolution and the chain is wrapped in a
    :class:`~metalworks.llm.FallbackChatModel`.

    **Opt-in and behaviour-preserving:** with no fallbacks configured this
    returns exactly what :func:`resolve_chat` returns — the bare single model,
    no wrapper — so the default path is byte-for-byte unchanged. Secrets/env
    handling is unchanged: every model (primary and fallbacks) goes through the
    same :func:`resolve_chat`, which reads keys only from the environment.
    """
    primary = resolve_chat(model)
    refs = fallback_models if fallback_models is not None else _config_fallback_models()
    if not refs:
        return primary
    from metalworks.llm import FallbackChatModel

    chain: list[ChatModel] = [primary]
    chain.extend(resolve_chat(ref) for ref in refs)
    return FallbackChatModel(chain)


def resolve_models(
    model: str | None = None,
    fast_model: str | None = None,
    fallback_models: list[str] | None = None,
) -> tuple[ChatModel, ChatModel]:
    """Resolve a (main, fast) :class:`~metalworks.llm.ChatModel` pair.

    ``model`` and ``fast_model`` are each a ``provider:id`` / ``provider/model``
    ref or ``None`` (env inference). When ``fast_model`` is not given, the fast
    slot falls back to the main model — the same rule the deps objects apply via
    their ``filter_model`` property, lifted to construction time.

    ``fallback_models`` is an opt-in ordered list of additional refs for the
    *main* model's failover chain (see :func:`resolve_chat_chain`). With none
    configured, the main slot is exactly the single :func:`resolve_chat` model —
    no wrapper, no behaviour change — and the fast slot continues to mirror it.
    """
    main = resolve_chat_chain(model, fallback_models=fallback_models)
    fast = resolve_chat(fast_model) if fast_model else main
    return main, fast


def resolve_embeddings() -> EmbeddingProvider:
    """Resolve an :class:`~metalworks.embeddings.EmbeddingProvider`.

    A present Google (``GOOGLE_API_KEY`` / ``GEMINI_API_KEY`` / Vertex) key wins,
    then OpenAI (``OPENAI_API_KEY``). With no embeddings-capable key, falls back
    to a local, keyless fastembed model — so a chat-only setup (including an
    Anthropic-only one, since Anthropic ships no embeddings API) still works end
    to end. The local model is the floor, never a forced downgrade: this never
    raises for a missing key. (The fastembed weights install via the ``research``
    extra; :class:`~metalworks.errors.MissingExtraError` surfaces only on first
    embed if the extra is absent.) The adapter is imported lazily.
    """
    if vertex_enabled() or os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"):
        from metalworks.embeddings.adapters.google import GoogleEmbedding

        return GoogleEmbedding()
    if os.environ.get("OPENAI_API_KEY"):
        from metalworks.embeddings.adapters.openai import OpenAIEmbedding

        return OpenAIEmbedding()
    from metalworks.embeddings.adapters.fastembed import FastEmbedEmbedding

    return FastEmbedEmbedding()


def resolve_search() -> SearchProvider | None:
    """Resolve an external :class:`~metalworks.search.SearchProvider`, or ``None``.

    Precedence by first-present key: Exa (``EXA_API_KEY``) → Tavily
    (``TAVILY_API_KEY``) → Parallel (``PARALLEL_API_KEY``) → Firecrawl
    (``FIRECRAWL_API_KEY``). Each adapter is lazy-imported only when its key is
    present. Returns ``None`` when none is set — the web stream then relies on
    model-native grounding, which is the intended graceful degradation, so this
    never raises.
    """
    if os.environ.get("EXA_API_KEY"):
        from metalworks.search.adapters.exa import ExaSearch

        return ExaSearch()
    if os.environ.get("TAVILY_API_KEY"):
        from metalworks.search.adapters.tavily import TavilySearch

        return TavilySearch()
    if os.environ.get("PARALLEL_API_KEY"):
        from metalworks.search.adapters.parallel import ParallelSearch

        return ParallelSearch()
    if os.environ.get("FIRECRAWL_API_KEY"):
        from metalworks.search.adapters.firecrawl import FirecrawlSearch

        return FirecrawlSearch()
    return None


# ── Store resolution ────────────────────────────────────────────────────────


def default_store(path: str | None = None) -> MemoryStores | SqliteStores:
    """The local store backend for explicit CLI invocations.

    ``":memory:"`` → :class:`~metalworks.stores.MemoryStores` (ephemeral, for
    tests and one-shot runs). Otherwise a :class:`~metalworks.stores.SqliteStores`
    at the resolved path. Resolution order: explicit ``path`` > config ``store`` >
    the active project's ``corpus.db`` > the ``~/.metalworks/store.db`` default.
    (For the library facade's *no-footprint* behaviour, see :func:`auto_store`.)
    """
    resolved = path or setting("store")
    if resolved is None:
        project = Project.find()
        resolved = str(project.corpus_db) if project is not None else str(_DEFAULT_STORE_PATH)
    if resolved == ":memory:":
        from metalworks.stores import MemoryStores

        return MemoryStores()
    from metalworks.stores import SqliteStores

    store_path = Path(resolved).expanduser()
    store_path.parent.mkdir(parents=True, exist_ok=True)
    return SqliteStores(store_path)


def auto_store() -> MemoryStores | SqliteStores:
    """The library facade's no-footprint store.

    Inside a ``.metalworks/`` project → a :class:`~metalworks.stores.SqliteStores`
    on the project's ``corpus.db`` (the memory accumulates across runs). With no
    project → a :class:`~metalworks.stores.MemoryStores` that persists nothing, so
    a casual ``metalworks.research("idea")`` leaves zero footprint, like git
    before ``git init``. Reads no config ``store`` setting — that is a CLI concern
    (see :func:`default_store`).
    """
    project = Project.find()
    if project is None:
        from metalworks.stores import MemoryStores

        return MemoryStores()
    from metalworks.stores import SqliteStores

    # project.root necessarily exists: find() only returns a project when its
    # project.json is present. SqliteStores creates corpus.db + parent as needed.
    return SqliteStores(project.corpus_db)


__all__ = [
    "auto_store",
    "config_search_paths",
    "default_config_path",
    "default_source_id",
    "default_store",
    "enabled_source_ids",
    "load_config",
    "load_sources_config",
    "resolve_chat",
    "resolve_chat_chain",
    "resolve_embeddings",
    "resolve_models",
    "resolve_search",
    "resolve_sources",
    "save_config",
    "save_sources_config",
    "setting",
]
