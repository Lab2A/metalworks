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
    from metalworks.render import PageRenderer
    from metalworks.research.deps import CorpusReader
    from metalworks.research.discovery import DiscoveryProvider
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


# The single honest per-call LLM timeout budget (seconds). Raised from the old
# 120s adapter default because a reasoning model's hidden thinking phase plus
# its output must fit inside one non-retried call — 120s could time out
# mid-reasoning before any output existed. Overridable per machine/run.
_DEFAULT_LLM_TIMEOUT_S = 300.0


def llm_timeout_s() -> float:
    """Resolve the per-call LLM timeout budget in seconds.

    Precedence: ``METALWORKS_LLM_TIMEOUT`` env > ``llm_timeout`` config setting >
    ``300.0`` default. This is the budget the chat adapters apply when a caller
    passes no explicit ``timeout_s`` — for the streaming OpenAI path it is the
    READ (gap-between-chunks) timeout, so a long-but-progressing reasoning
    stream completes while a genuinely stalled one fails cleanly. A non-positive
    or unparseable value degrades to the default rather than crashing a run.
    Lazy by design: nothing here runs at import (env/config read on call only).
    """
    raw: str | None = os.environ.get("METALWORKS_LLM_TIMEOUT")
    if not raw:
        configured = load_config().get("llm_timeout")
        raw = str(configured) if configured is not None else None
    if raw:
        try:
            parsed = float(raw)
        except (TypeError, ValueError):
            return _DEFAULT_LLM_TIMEOUT_S
        if parsed > 0:
            return parsed
    return _DEFAULT_LLM_TIMEOUT_S


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


def magnitude_provider_ids() -> list[str]:
    """The ordered active lane-② magnitude provider ids from ``[sources].magnitude``.

    Magnitude providers (search volume, package downloads, funding) run AFTER
    clustering and attach numbers to existing themes — they are **opt-in** and OFF
    by default: with ``[sources].magnitude`` unset, this returns ``[]`` and the
    pipeline's magnitude hook is a no-op, so the default run is byte-for-byte
    unchanged. Set ``magnitude = ["npm"]`` to enable the npm-downloads provider.
    Non-string / empty entries are dropped so a malformed config degrades to "off".
    """
    enabled = load_sources_config().get("magnitude")
    if isinstance(enabled, list):
        items = cast("list[object]", enabled)
        return [item.strip() for item in items if isinstance(item, str) and item.strip()]
    return []


def default_source_id() -> str:
    """The preferred source id from ``[sources].default`` (else the first enabled)."""
    configured = load_sources_config().get("default")
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    return enabled_source_ids()[0]


def source_selector_enabled() -> bool:
    """Whether the brief-aware source SELECTOR is enabled (``[sources].select``).

    **On by default** (#167 — sources-by-idea is the smart default): with ``select``
    unset, a run with no explicit source override lets the picker CUT to the
    brief-relevant, access-gated sources per run (``planner.select_sources``) — the
    ultra-wide corpus is visible on the first run instead of reddit-only. Set
    ``select = false`` to opt back out to the configured ``[sources].enabled`` /
    ``reddit`` default. An explicit source override (CLI ``--source`` /
    ``[sources].enabled`` passed as the override) ALWAYS wins over the selector:
    the precedence is **explicit override > selector > reddit floor** — unchanged.

    The blast-radius guard lives in :func:`~metalworks.research.planner.select_sources`:
    when there is no chat model, or the ranking call fails / returns nothing usable,
    the cut degrades to the reddit floor (just ``reddit``), so a default-on run with
    no model is exactly the old reddit-only default — deterministic and offline-safe.
    """
    value = load_sources_config().get("select")
    return value is not False


def discovery_loop_enabled() -> bool:
    """Whether the homegrown agentic discovery LOOP is opt-in enabled (``[sources].discover``).

    **Opt-in by default** (the #123 ``[sources]`` opt-in posture; note
    :func:`source_selector_enabled` itself flipped ON in #167): with
    ``discover`` unset or false, a configured single-shot ``SearchProvider`` drives the
    legacy **single-pass** web-research path exactly as before — no extra LLM follow-up-query
    rounds, default behavior and cost unchanged. Set ``discover = true`` to run the
    iterate-and-dig loop (`research.discovery.HomegrownDiscovery`). NOTE: an **agentic**
    ``DiscoveryProvider`` (Exa Research / Parallel Task), when configured, always delegates
    regardless of this flag — the flag only gates metalworks' own loop over a single-shot
    provider, which is the behavior change that should not ship silently.
    """
    return load_sources_config().get("discover") is True


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
    ``METALWORKS_MODEL`` env override, the config file's ``provider``/``model``,
    or the first present API key.

    ``METALWORKS_MODEL`` behaves exactly like an explicit ``--model`` ref, so it
    wins over config and over key-order autodetection (the env var is the
    every-surface escape hatch: CLI, MCP server, and the SDK all honor it)."""
    model = model or os.environ.get("METALWORKS_MODEL") or None
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

    # No provider pinned and no explicit/env ref: honor a config ``model`` that is
    # a routable ref on its own (e.g. "deepseek/deepseek-v4-flash" → OpenRouter),
    # so setting ``model`` alone works without also pinning ``provider`` — and it
    # routes BEFORE key-order/Vertex autodetection (which would otherwise hijack it
    # on a machine with stray GOOGLE_GENAI_USE_VERTEXAI).
    cfg_model = cfg.get("model")
    if not model and isinstance(cfg_model, str) and cfg_model.strip():
        ref = cfg_model.strip()
        if ":" in ref:
            provider, _, mid = ref.partition(":")
            return provider.strip().lower(), (mid.strip() or None)
        if "/" in ref:
            head, _, rest = ref.partition("/")
            head_l = head.strip().lower()
            if head_l in _NATIVE_PROVIDERS or head_l in _COMPAT_PROVIDERS:
                return head_l, (rest.strip() or None)
            return "openrouter", ref

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


def _vertex_creds_usable() -> bool:
    """True when Vertex mode could actually authenticate.

    ``vertex_enabled()`` only reads ``GOOGLE_GENAI_USE_VERTEXAI`` — it does NOT
    mean Vertex is usable. When ``GOOGLE_APPLICATION_CREDENTIALS`` is set, the
    file must exist (a stale path pointing at a deleted key is the #1 way a
    machine that once used Vertex now crashes on first embed). When it is unset
    we assume ambient ADC (gcloud / GCE metadata) may exist and don't preempt it.
    """
    creds = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if creds:
        return Path(creds).expanduser().is_file()
    return True


def resolve_embeddings() -> EmbeddingProvider:
    """Resolve an :class:`~metalworks.embeddings.EmbeddingProvider`.

    Precedence: an explicit ``METALWORKS_EMBEDDINGS`` override
    (``local`` / ``openai`` / ``google``) > a present Google key (``GOOGLE_API_KEY``
    / ``GEMINI_API_KEY``, or Vertex with usable creds) > OpenAI (``OPENAI_API_KEY``)
    > a local, keyless fastembed model. The local model is the floor — a chat-only
    setup (Anthropic- or OpenRouter-only) just works, and a misconfigured Vertex
    env (``GOOGLE_GENAI_USE_VERTEXAI=true`` but a missing creds file) **degrades to
    local instead of crashing** rather than returning a doomed Google adapter. This
    never raises for a missing key. (fastembed installs via the ``research`` extra;
    :class:`~metalworks.errors.MissingExtraError` surfaces only on first embed if
    absent.) Adapters are imported lazily.
    """
    override = (os.environ.get("METALWORKS_EMBEDDINGS") or "").strip().lower()
    if override == "local":
        from metalworks.embeddings.adapters.fastembed import FastEmbedEmbedding

        return FastEmbedEmbedding()
    if override == "openai":
        from metalworks.embeddings.adapters.openai import OpenAIEmbedding

        return OpenAIEmbedding()
    if override in ("google", "gemini", "vertex"):
        from metalworks.embeddings.adapters.google import GoogleEmbedding

        return GoogleEmbedding()

    google_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if google_key or (vertex_enabled() and _vertex_creds_usable()):
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


def resolve_discovery() -> DiscoveryProvider | None:
    """Resolve an **agentic** discovery provider, or ``None`` (mirrors :func:`resolve_search`).

    Returns a :class:`~metalworks.research.discovery.DiscoveryProvider` whose
    ``agentic`` is ``True``. The agentic tier ABOVE single-shot search: an
    iterate-and-dig provider that does its own loop (Exa Research, Parallel
    Task). When one is configured, the
    web stream delegates discovery to it and metalworks' homegrown loop does NOT
    run (the capability-ladder gate in :mod:`metalworks.research.web`).

    Mirrors :func:`resolve_search` — lazy-imported adapters, first-present key
    wins, never raises (returns ``None`` so the gate falls through to the
    homegrown loop over a plain ``SearchProvider``, then to single-pass search).

    Recognizes both agentic adapters, first-present key wins: **Exa Research**
    (P4.1, ``EXA_API_KEY``) then **Parallel Task** (P4.2, ``PARALLEL_API_KEY``) —
    Exa first as the recommended fit (neural community search + reddit-path
    filters at the cheapest deep tier). With one configured the gate trips and
    metalworks' homegrown loop stays off; with no agentic key set this returns
    ``None`` and the homegrown loop is the active rung. Each adapter (and its
    extra) is imported lazily only when its key is present, so ``import
    metalworks`` and the bare matrix stay free; a present key with an absent
    extra falls through rather than crashing a run.
    """
    from metalworks.errors import MissingExtraError, MissingKeyError

    if os.environ.get("EXA_API_KEY"):
        from metalworks.research.discovery.exa import ExaResearchDiscovery

        try:
            return ExaResearchDiscovery()
        except (MissingExtraError, MissingKeyError):
            pass
    if os.environ.get("PARALLEL_API_KEY"):
        from metalworks.research.discovery.parallel import ParallelTaskDiscovery

        try:
            return ParallelTaskDiscovery()
        except (MissingExtraError, MissingKeyError):
            pass
    return None


def resolve_renderer() -> PageRenderer | None:
    """Resolve a :class:`~metalworks.render.PageRenderer`, or ``None``.

    Precedence: an installed owned browser (``metalworks[browser]`` + a Chromium
    binary) → Playwright (full capability, including style audits); else
    ``FIRECRAWL_API_KEY`` → Firecrawl (hosted, screenshot-only); else ``None``.
    Like :func:`resolve_search`, this never raises — a pillar with no renderer
    degrades to text research, which is the intended graceful fallback. The
    Chromium check is the cheap, launch-free probe so this stays fast.
    """
    from metalworks.errors import BrowserNotInstalledError, MissingExtraError
    from metalworks.render import chromium_present

    if chromium_present():
        try:
            from metalworks.render.adapters.playwright import PlaywrightRenderer

            return PlaywrightRenderer()
        except (MissingExtraError, BrowserNotInstalledError):
            pass  # extra absent or binary vanished between probe and construct
    if os.environ.get("FIRECRAWL_API_KEY"):
        try:
            from metalworks.render.adapters.firecrawl import FirecrawlRenderer

            return FirecrawlRenderer()
        except (MissingExtraError, MissingKeyError):
            return None
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


def resolve_corpus_reader() -> CorpusReader:
    """Resolve the submissions corpus reader from ``ARCTIC_SHIFT_SOURCE``.

    Default (unset or ``api``) → :class:`ArcticShiftReader`, the LIVE Arctic
    Shift posts API: current data, core ``httpx``, no extra, no HF rate limits.
    This is the right first-run default — a keyless, extra-less install can pull
    real submissions immediately.

    Opt-in tiers for offline / bulk work: ``hf`` (aliases ``parquet``,
    ``arctic``) → :class:`ArcticReader`, the HF Parquet mirror (``[arctic]``
    extra; reads ``HF_TOKEN`` from the env); ``mirror`` →
    :class:`ArcticMirrorReader`, the Supabase mirror (``[supabase]`` extra).
    """
    source = (os.environ.get("ARCTIC_SHIFT_SOURCE") or "api").strip().lower()
    if source in ("hf", "parquet", "arctic"):
        from metalworks.research.arctic import ArcticReader

        return ArcticReader(probe_sleep_s=0.0)
    if source == "mirror":
        from metalworks.research.arctic import ArcticMirrorReader

        return ArcticMirrorReader()
    from metalworks.research.arctic import ArcticShiftReader

    return ArcticShiftReader()


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
    "llm_timeout_s",
    "load_config",
    "load_sources_config",
    "magnitude_provider_ids",
    "resolve_chat",
    "resolve_chat_chain",
    "resolve_discovery",
    "resolve_embeddings",
    "resolve_models",
    "resolve_renderer",
    "resolve_search",
    "resolve_sources",
    "save_config",
    "save_sources_config",
    "setting",
    "source_selector_enabled",
]
