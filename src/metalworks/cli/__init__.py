"""metalworks CLI — the ``metalworks`` console script.

typer + rich are core dependencies by design: a CLI-first tool whose entry
point can crash with ModuleNotFoundError on first touch is fighting its own
product. Everything heavier (provider SDKs, duckdb, redditwarp, mcp) is
lazy-imported inside the command that needs it, so ``metalworks --help`` and
``metalworks version`` work on a bare install with no extras.

Sub-apps: ``research``, ``reddit``, ``arctic``, ``config``, plus ``mcp serve``.
Secrets come from the environment only; every Reddit write goes through the
deterministic compliance gate and requires an explicit ``--yes``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

import metalworks
from metalworks import config

if TYPE_CHECKING:
    from metalworks.contract import DemandReport
    from metalworks.embeddings import EmbeddingProvider
    from metalworks.llm import ChatModel
    from metalworks.stores.repos import RunRepo

app = typer.Typer(
    name="metalworks",
    help="Marketing research and Reddit engagement toolkit.",
    no_args_is_help=True,
)
console = Console()
err_console = Console(stderr=True)

# Sub-apps registered at the bottom of the module.
research_app = typer.Typer(help="Plan and run demand-research reports.", no_args_is_help=True)
reddit_app = typer.Typer(help="Search Reddit, fetch intel, post (gated).", no_args_is_help=True)
arctic_app = typer.Typer(help="Read the Arctic Shift historical corpus.", no_args_is_help=True)
config_app = typer.Typer(help="Read and write non-secret config.", no_args_is_help=True)
models_app = typer.Typer(
    help="Inspect and set the chat/fast/embedding model and provider reachability.",
    no_args_is_help=True,
)
mcp_app = typer.Typer(help="Run the metalworks MCP server.", no_args_is_help=True)
sources_app = typer.Typer(
    help="List, enable, and disable the data sources research ingests from.",
    no_args_is_help=True,
)
corpus_app = typer.Typer(
    help="Ingest sources into, and inspect, the local corpus store.",
    no_args_is_help=True,
)

_ENV_EXAMPLE = """\
# metalworks — secrets come from the environment ONLY (never the config file).
# One chat key is enough; the CLI auto-resolves by which is present. Embeddings
# need no separate key — a Google/OpenAI key is used if present, else a local
# model (no key, bundled with [research]).

# Chat model (first present wins: anthropic > openai > google > openrouter):
# ANTHROPIC_API_KEY=
# OPENAI_API_KEY=
# GOOGLE_API_KEY=          # or GEMINI_API_KEY
# OPENROUTER_API_KEY=      # one key reaches 200+ models

# External web search (optional; exa preferred, then tavily):
# EXA_API_KEY=
# TAVILY_API_KEY=

# Reddit posting (optional; only needed for the engagement path):
# REDDIT_CLIENT_ID=
# REDDIT_CLIENT_SECRET=
# METALWORKS_FERNET_KEY=   # token-at-rest encryption key
"""


# ── Top-level commands ──────────────────────────────────────────────────────


@app.command()
def version() -> None:
    """Print the installed metalworks version."""
    console.print(f"metalworks {metalworks.__version__}")


def _doctor_hints() -> list[str]:
    """Compute the actionable Hints lines `doctor` prints (and `--fix` acts on).

    Pure read-only: inspects env keys and importable modules only. Returns the
    same human-readable lines the report shows, so the report and the repair
    path can never drift.
    """
    # openrouter shares the openai SDK, so its missing-extra hint points at [openai].
    _extra_for = {"openrouter": "openai"}
    hints: list[str] = []
    for provider, env_vars, module in _PROVIDER_MATRIX:
        found = next((v for v in env_vars if os.environ.get(v)), None)
        if found and not _module_available(module):
            extra = _extra_for.get(provider, provider)
            hints.append(
                f"{found} is set but `{module}` is not installed → "
                f'pip install "metalworks[{extra}]"'
            )
    if not any(os.environ.get(v) for _, evs, _ in _PROVIDER_MATRIX for v in evs):
        hints.append("No provider key found → set one (e.g. OPENAI_API_KEY) to run the pipeline.")
    if not any(os.environ.get(v) for v in ("GOOGLE_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY")):
        if _module_available("fastembed"):
            hints.append(
                "No embedding key → using the local model (no key needed). "
                "Run `metalworks models warm` to pre-download it."
            )
        else:
            hints.append(
                'No embedding key and fastembed not installed → pip install "metalworks[research]" '
                "(or set GOOGLE_API_KEY / OPENAI_API_KEY)."
            )
    return hints


def _embeddings_are_local() -> bool:
    """True when the resolved embedding provider is the keyless local fastembed model.

    Used by `doctor --fix` to decide whether warming (pre-download) is the safe,
    in-process repair to run. Guarded so a resolution error never crashes doctor.
    """
    from metalworks.embeddings.adapters.fastembed import FastEmbedEmbedding

    try:
        return isinstance(config.resolve_embeddings(), FastEmbedEmbedding)
    except Exception:
        return False


@app.command()
def doctor(
    fix: Annotated[
        bool,
        typer.Option(
            "--fix",
            help="Run SAFE in-process repairs (e.g. pre-download the local embedding model); "
            "print pip/export commands for the rest as guidance. Never runs pip or mutates env.",
        ),
    ] = False,
) -> None:
    """Report installed extras, configured keys, store path, and Reddit auth.

    With ``--fix``, after printing the report it performs only safe, reversible,
    in-process repairs (currently: warming the local embedding model) and prints
    the remaining steps (``pip install …`` / ``export …``) as copy-paste guidance.
    It never runs pip and never mutates the environment.
    """
    console.print(f"[bold]metalworks {metalworks.__version__}[/bold]")

    console.print("\n[bold]Optional extras[/bold]")
    for extra, module in _EXTRA_PROBES:
        present = _module_available(module)
        mark = "[green]installed[/green]" if present else "[dim]not installed[/dim]"
        console.print(f"  {extra:<10} {mark}")

    console.print("\n[bold]API keys (from environment)[/bold]")
    for label, env_vars in _KEY_PROBES:
        found = next((v for v in env_vars if os.environ.get(v)), None)
        status = f"[green]set[/green] ({found})" if found else "[dim]unset[/dim]"
        console.print(f"  {label:<14} {status}")

    console.print("\n[bold]Resolved models[/bold]")
    model_ref = config.setting("model")
    for label, resolver in (
        ("chat", lambda: config.resolve_chat(model_ref)),
        ("embedding", config.resolve_embeddings),
    ):
        markup, _ = _resolved_model_id(label, resolver)
        console.print(f"  {label:<10} {markup}")

    store_path = config.setting("store") or str(Path.home() / ".metalworks" / "store.db")
    console.print("\n[bold]Store[/bold]")
    console.print(f"  path  {store_path}")

    console.print("\n[bold]Reddit auth[/bold]")
    try:
        store = config.default_store()
        accounts = store.list_accounts()
        if accounts:
            console.print(
                f"  [green]{len(accounts)} account(s)[/green]: "
                + ", ".join(a.username for a in accounts)
            )
        else:
            console.print("  [dim]no connected accounts[/dim] (run: metalworks reddit auth login)")
    except Exception as exc:
        console.print(f"  [yellow]could not read store: {exc}[/yellow]")

    console.print("\n[bold]Hints[/bold]")
    hints = _doctor_hints()
    if hints:
        for h in hints:
            console.print(f"  [yellow]•[/yellow] {h}")
    else:
        console.print("  [green]all set[/green]")

    if fix:
        _doctor_fix(hints)


def _doctor_fix(hints: list[str]) -> None:
    """Perform SAFE in-process repairs and print the rest as copy-paste guidance.

    Only reversible, in-process actions run automatically (warming the local
    embedding model). Anything that would run pip or mutate the environment is
    printed for the user to run, never executed.
    """
    console.print("\n[bold]Fix[/bold]")
    acted = False

    # Safe, in-process, reversible: pre-download the keyless local embedding model.
    if _embeddings_are_local():
        acted = True
        from metalworks.errors import MetalworksError

        embeddings = config.resolve_embeddings()
        model_id = getattr(embeddings, "model_id", embeddings.__class__.__name__)
        console.print(f"  [bold]warming[/bold] local embedding model: {model_id}")
        console.print("  [dim]downloading on first use; may take a minute…[/dim]")
        try:
            embeddings.embed(["warmup"], task="query")
            console.print("  [green]embedding model cached locally.[/green]")
        except MetalworksError as exc:
            console.print(f"  [yellow]could not warm embeddings: {exc.message}[/yellow]")
            if exc.fix:
                console.print(f"  [dim]{exc.fix}[/dim]")
        except Exception as exc:  # never let a download error crash doctor
            console.print(f"  [yellow]could not warm embeddings: {exc}[/yellow]")

    # Everything else (pip install / export) is guidance only — print, never run.
    guidance = [h for h in hints if "pip install" in h or "set one" in h or "set GOOGLE" in h]
    if guidance:
        console.print("  [dim]Run these yourself (not auto-run):[/dim]")
        for h in guidance:
            console.print(f"    [yellow]•[/yellow] {h}")
        acted = True

    if not acted:
        console.print("  [green]nothing to repair.[/green]")


@app.command()
def init(
    idea: Annotated[
        str | None,
        typer.Option("--idea", help="One line on what you're building (seeds the project slug)."),
    ] = None,
) -> None:
    """Create a ``.metalworks/`` project in the current directory, like ``git init``.

    Writes ``.metalworks/`` (a ``project.json`` manifest, a ``config.toml`` for
    non-secret settings, and a gitignored ``corpus.db`` cache) plus a
    ``.env.example``. Idempotent — an existing project is left untouched.
    """
    from metalworks.project import DIRNAME, Project

    existed = (Path.cwd() / DIRNAME / "project.json").is_file()
    project = Project.init(Path.cwd(), idea=idea)
    if existed:
        console.print(f"[yellow]{DIRNAME}/ already exists; leaving it untouched.[/yellow]")
    else:
        console.print(f"[green]Created[/green] {DIRNAME}/ (project '{project.slug}')")

    if project.config_path.exists():
        console.print(
            f"[yellow]{project.config_path.name} already exists; leaving it untouched.[/yellow]"
        )
    else:
        config.save_config({"provider": "anthropic"}, path=project.config_path)
        console.print(f"[green]Wrote[/green] {project.config_path}")

    env_path = Path.cwd() / ".env.example"
    if env_path.exists():
        console.print("[yellow].env.example already exists; leaving it untouched.[/yellow]")
    else:
        env_path.write_text(_ENV_EXAMPLE, encoding="utf-8")
        console.print(f"[green]Wrote[/green] {env_path}")
    console.print("\nNext: set a provider key in your shell, then `metalworks doctor`.")


def _present_providers() -> list[tuple[str, str]]:
    """Providers with a key present in the env → [(provider, found_env_var)].

    Reuses the `_PROVIDER_MATRIX` key logic so `setup` reports exactly what the
    resolvers can reach. Never reads the secret value — only which var is set.
    """
    out: list[tuple[str, str]] = []
    for provider, env_vars, _module in _PROVIDER_MATRIX:
        found = next((v for v in env_vars if os.environ.get(v)), None)
        if found:
            out.append((provider, found))
    return out


@app.command()
def setup(
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="Non-interactive: accept every default (no project, no warm, no model write).",
        ),
    ] = False,
) -> None:
    """Interactive onboarding: detect keys, pick a model, scaffold a project, warm embeddings.

    Idempotent and non-destructive. Secrets are never read or written — when no
    provider key is present it tells you which env var to ``export``. Every
    prompt has a default, so it is fully scriptable: pipe newlines for the
    defaults, or pass ``--yes`` to accept them all non-interactively.
    """
    console.print("[bold]metalworks setup[/bold]\n")

    # 1. Detect provider keys.
    present = _present_providers()
    chosen_provider: str | None = None
    if not present:
        console.print("[yellow]No provider key found in the environment.[/yellow]")
        console.print(
            "  Set one, e.g.:  [bold]export OPENAI_API_KEY=…[/bold]  "
            "(or ANTHROPIC_API_KEY / GOOGLE_API_KEY / OPENROUTER_API_KEY)"
        )
        console.print(
            "  [dim]Secrets come from the environment only — setup never writes them.[/dim]"
        )
    elif len(present) == 1:
        chosen_provider, var = present[0]
        console.print(
            f"[green]Found[/green] one provider key: {chosen_provider} ({var}). Using it."
        )
    else:
        labels = ", ".join(f"{p} ({v})" for p, v in present)
        console.print(f"[green]Found[/green] {len(present)} provider keys: {labels}")
        default = present[0][0]
        if yes:
            chosen_provider = default
            console.print(f"  [dim]--yes → using {chosen_provider}.[/dim]")
        else:
            chosen_provider = typer.prompt("Which provider should be the default?", default=default)
            chosen_provider = (chosen_provider or default).strip()

    # 2. Optionally set a default model ref (writes `model` to the cwd config).
    write_model = False
    if not yes:
        write_model = typer.confirm("Set a default model ref now?", default=False)
    if write_model:
        ref = typer.prompt(
            "Model ref (e.g. openai/gpt-5, anthropic:claude-sonnet-4)", default=""
        ).strip()
        if ref:
            _set_model_setting("model", ref)
        else:
            console.print("[dim]No model ref entered — skipping.[/dim]")

    # 3. Choose data sources (writes [sources].enabled). Default: keep current.
    _setup_sources_step(yes)

    # 4. Offer to create a project (same path as `init` / Project.init).
    make_project = yes is False and typer.confirm(
        "Create a .metalworks/ project here?", default=False
    )
    if make_project:
        from metalworks.project import DIRNAME, Project

        existed = (Path.cwd() / DIRNAME / "project.json").is_file()
        project = Project.init(Path.cwd())
        if existed:
            console.print(f"  [yellow]{DIRNAME}/ already exists; left untouched.[/yellow]")
        else:
            console.print(f"  [green]Created[/green] {DIRNAME}/ (project '{project.slug}')")
        if not project.config_path.exists():
            seed = {"provider": chosen_provider} if chosen_provider else {}
            config.save_config(seed, path=project.config_path)
            console.print(f"  [green]Wrote[/green] {project.config_path}")

    # 5. Offer to pre-download the local embedding model (same path as `models warm`).
    warm = yes is False and typer.confirm(
        "Pre-download the local embedding model now?", default=False
    )
    if warm:
        from metalworks.errors import MetalworksError

        embeddings = _resolve_embeddings_or_exit()
        model_id = getattr(embeddings, "model_id", embeddings.__class__.__name__)
        console.print(f"  [bold]Warming[/bold] embedding model: {model_id}")
        try:
            embeddings.embed(["warmup"], task="query")
            console.print("  [green]Ready.[/green] Cached locally.")
        except MetalworksError as exc:
            console.print(f"  [yellow]could not warm: {exc.message}[/yellow]")
            if exc.fix:
                console.print(f"  [dim]{exc.fix}[/dim]")

    # 6. Finish with the doctor summary.
    console.print("\n[bold]── doctor ──[/bold]")
    doctor(fix=False)


def _setup_sources_step(yes: bool) -> None:
    """Setup's "choose your data sources" step.

    Lists registered sources (keyless/needs-extra annotated) and lets the user
    pick a comma-separated set, writing ``[sources].enabled``. The default is the
    CURRENT enabled set (Reddit out of the box) so accepting the default is a
    no-op. Under ``--yes`` (or a defaulted prompt) it keeps the current set and
    writes nothing — non-destructive and fully scriptable.
    """
    current = config.enabled_source_ids()
    discovered = _discover_sources()
    console.print("\n[bold]Data sources[/bold]")
    for sid in sorted({*discovered, *current}):
        note, probe = _SOURCE_REACH.get(sid, ("registered", None))
        on = "[green]enabled[/green]" if sid in current else "[dim]available[/dim]"
        reach = (
            ""
            if probe is None or _module_available(probe)
            else f" [yellow](needs {probe})[/yellow]"
        )
        console.print(f"  {sid:<12} {on}  [dim]{note}[/dim]{reach}")
    default = ",".join(current)
    if yes:
        console.print(f"  [dim]--yes → keeping current sources: {default}.[/dim]")
        return
    picked = typer.prompt(
        "Which sources should research ingest from? (comma-separated)", default=default
    )
    chosen = [s.strip() for s in (picked or default).split(",") if s.strip()]
    if not chosen or chosen == current:
        console.print(f"  [dim]Keeping current sources: {', '.join(current)}.[/dim]")
        return
    path = config.save_sources_config(chosen)
    console.print(f"  [green]Wrote[/green] sources = {chosen} [dim]({path})[/dim]")


# ── config sub-app ──────────────────────────────────────────────────────────


@config_app.command("list")
def config_list() -> None:
    """Print the merged non-secret config (cwd over ~/.config/metalworks/)."""
    cfg = config.load_config()
    sources_cfg = config.load_sources_config()
    if not cfg and not sources_cfg:
        console.print("[dim]No config set. Run `metalworks init` to scaffold one.[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("key")
    table.add_column("value")
    for key, value in sorted(cfg.items()):
        table.add_row(key, str(value))
    # The [sources] table is nested, so load_config() (scalars only) skips it;
    # surface it here so `config list` reflects enabled sources.
    for key, value in sorted(sources_cfg.items()):
        table.add_row(f"sources.{key}", str(value))
    console.print(table)


@config_app.command("get")
def config_get(key: str) -> None:
    """Print one config value (env/arg precedence not applied — file only)."""
    value = config.load_config().get(key)
    if value is None:
        err_console.print(f"[yellow]{key} is not set.[/yellow]")
        raise typer.Exit(code=1)
    console.print(str(value))


@config_app.command("set")
def config_set(key: str, value: str) -> None:
    """Set one non-secret config value in the cwd metalworks.toml."""
    if key in _SECRET_KEYS:
        err_console.print(
            f"[red]{key} is a secret and must come from the environment, not the config file.[/red]"
        )
        raise typer.Exit(code=1)
    cfg = config.load_config()
    cfg[key] = value
    path = config.save_config(cfg)
    console.print(f"[green]Set[/green] {key} = {value} [dim]({path})[/dim]")


# ── models sub-app ──────────────────────────────────────────────────────────

# Provider → (key env var(s), importable SDK/extra module) for the reachability
# matrix. Mirrors `doctor`'s _EXTRA_PROBES / _KEY_PROBES but keyed by the
# provider the resolvers actually route to, so a row maps 1:1 to "can metalworks
# reach this provider right now". OpenRouter is keyed on OPENROUTER_API_KEY and
# rides the OpenAI SDK (it is an OpenAI-compatible endpoint).
_PROVIDER_MATRIX: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("anthropic", ("ANTHROPIC_API_KEY",), "anthropic"),
    ("openai", ("OPENAI_API_KEY",), "openai"),
    ("google", ("GOOGLE_API_KEY", "GEMINI_API_KEY"), "google.genai"),
    ("openrouter", ("OPENROUTER_API_KEY",), "openai"),
)


def _resolved_model_id(label: str, resolver: Any) -> tuple[str, str]:
    """Run a model resolver and return (status_markup, plain_detail).

    Wrapped per the brief: on this branch ``resolve_embeddings`` can raise
    ``MissingKeyError`` without a key (another stream changes that), so every
    resolver call is guarded and rendered as a message + fix instead of a
    traceback.
    """
    from metalworks.errors import MetalworksError

    try:
        model = resolver()
    except MetalworksError as exc:
        fix = f" [dim]({exc.fix})[/dim]" if getattr(exc, "fix", None) else ""
        return f"[yellow]unresolved[/yellow] — {exc.message}{fix}", "unresolved"
    except Exception as exc:  # display, never crash `models list`
        return f"[yellow]unresolved[/yellow] — {exc}", "unresolved"
    model_id = getattr(model, "model_id", None) or model.__class__.__name__
    return f"[green]{model_id}[/green]", str(model_id)


@models_app.command("list")
def models_list() -> None:
    """Show the resolved chat/fast/embedding models and provider reachability.

    Read-only: it calls the same resolvers the pipeline uses (each guarded) and
    introspects keys/extras — it never changes how models resolve.
    """
    model_ref = config.setting("model")
    fast_ref = config.setting("fast_model")

    console.print("[bold]Resolved models[/bold]")
    rows: tuple[tuple[str, Any], ...] = (
        ("chat", lambda: config.resolve_chat(model_ref)),
        # fast falls back to the main model ref when no fast_model is set.
        ("fast", lambda: config.resolve_chat(fast_ref or model_ref)),
        ("embedding", config.resolve_embeddings),
    )
    model_table = Table(show_header=True, header_style="bold")
    model_table.add_column("slot")
    model_table.add_column("model")
    for label, resolver in rows:
        markup, _ = _resolved_model_id(label, resolver)
        model_table.add_row(label, markup)
    console.print(model_table)

    console.print("\n[bold]Provider reachability[/bold]")
    matrix = Table(show_header=True, header_style="bold")
    matrix.add_column("provider")
    matrix.add_column("key")
    matrix.add_column("extra")
    matrix.add_column("reachable")
    for provider, env_vars, module in _PROVIDER_MATRIX:
        found = next((v for v in env_vars if os.environ.get(v)), None)
        key_cell = f"[green]set[/green] ({found})" if found else "[dim]unset[/dim]"
        importable = _module_available(module)
        extra_cell = (
            f"[green]importable[/green] ({module})"
            if importable
            else f"[dim]missing[/dim] ({module})"
        )
        reachable = bool(found) and importable
        reach_cell = "[green]yes[/green]" if reachable else "[dim]no[/dim]"
        matrix.add_row(provider, key_cell, extra_cell, reach_cell)
    console.print(matrix)


def _set_model_setting(key: str, ref: str) -> None:
    """Write a model ref to the cwd config via the same path as ``config set``."""
    ref = ref.strip()
    if not ref:
        err_console.print(f"[red]{key} must be a non-empty model ref (e.g. openai/gpt-5).[/red]")
        raise typer.Exit(code=2)
    cfg = config.load_config()
    cfg[key] = ref
    path = config.save_config(cfg)
    console.print(f"[green]Set[/green] {key} = {ref} [dim]({path})[/dim]")


@models_app.command("set")
def models_set(
    ref: Annotated[
        str, typer.Argument(help="Model ref, e.g. openai/gpt-5 or anthropic:claude-sonnet-4.")
    ],
) -> None:
    """Set the main chat model (writes ``model`` to the cwd metalworks.toml)."""
    _set_model_setting("model", ref)


@models_app.command("set-fast")
def models_set_fast(
    ref: Annotated[
        str, typer.Argument(help="Model ref for the fast slot, e.g. openai/gpt-5-mini.")
    ],
) -> None:
    """Set the fast model (writes ``fast_model`` to the cwd metalworks.toml)."""
    _set_model_setting("fast_model", ref)


@models_app.command("warm")
def models_warm() -> None:
    """Pre-download the embedding model so the first research run isn't blocked.

    Resolves the embedding provider (the local fastembed model when no
    Google/OpenAI key is set) and embeds a tiny input, which fetches the model
    on first use. A no-op for hosted embedding providers (nothing to download).
    """
    from metalworks.errors import MetalworksError

    embeddings = _resolve_embeddings_or_exit()
    model_id = getattr(embeddings, "model_id", embeddings.__class__.__name__)
    console.print(f"[bold]Warming[/bold] embedding model: {model_id}")
    console.print("[dim]Downloading on first use (local models only); may take a minute…[/dim]")
    try:
        embeddings.embed(["warmup"], task="query")
    except MetalworksError as exc:
        err_console.print(f"[red]{exc.message}[/red]")
        if exc.fix:
            err_console.print(f"[dim]{exc.fix}[/dim]")
        raise typer.Exit(code=1) from exc
    console.print("[green]Ready.[/green] The embedding model is cached locally.")


# ── sources sub-app ─────────────────────────────────────────────────────────

# Reachability annotation for known source ids: which keyless extra (importable
# module) a built-in connector rides, and whether it needs a key/extra at all.
# Stream 2c owns the connectors; this map is the CLI's display-only hint so
# `sources list` can mirror `models list`'s "reachable?" column without reaching
# into the connectors. An id not listed here is shown as registered-only.
_SOURCE_REACH: dict[str, tuple[str, str | None]] = {
    # source_id -> (human note, importable module to probe; None = keyless, no extra)
    "reddit": ("keyless (Arctic corpus)", "duckdb"),
    "arctic": ("keyless (Arctic corpus)", "duckdb"),
    "hackernews": ("keyless (public API)", None),
}


def _discover_sources() -> list[str]:
    """All known source ids: the registry, plus the built-ins that self-register
    lazily on first ``get_source``. Triggers those lazy imports (best-effort) so
    a freshly-imported CLI still lists Reddit/Arctic and any registered connector.
    """
    import contextlib

    from metalworks.research.sources import SOURCES, get_source

    for builtin in ("reddit", "hackernews"):
        if builtin not in SOURCES:
            # Best-effort: a built-in may not be importable / may need kwargs.
            with contextlib.suppress(Exception):
                get_source(builtin)
    return sorted(SOURCES)


@sources_app.command("list")
def sources_list() -> None:
    """Show registered data sources, which are enabled, and their reachability.

    Read-only. Mirrors ``models list``: one row per registered source with its
    enabled state (from ``[sources].enabled``) and a keyless/needs-extra hint.
    """
    enabled = config.enabled_source_ids()
    discovered = _discover_sources()
    # Show every id that is either registered or named in config (so a configured
    # but not-yet-importable source still appears, flagged unreachable).
    ids = sorted({*discovered, *enabled})

    console.print("[bold]Data sources[/bold]")
    table = Table(show_header=True, header_style="bold")
    table.add_column("source")
    table.add_column("enabled")
    table.add_column("reachable")
    table.add_column("notes")
    for sid in ids:
        registered = sid in discovered
        note, probe = _SOURCE_REACH.get(
            sid, ("registered" if registered else "not registered", None)
        )
        on = sid in enabled
        if not registered:
            reach_cell = "[dim]no[/dim]"
        elif probe is not None and not _module_available(probe):
            reach_cell = f"[yellow]missing[/yellow] ({probe})"
        else:
            reach_cell = "[green]yes[/green]"
        en_cell = "[green]on[/green]" if on else "[dim]off[/dim]"
        table.add_row(sid, en_cell, reach_cell, note)
    console.print(table)
    console.print(f"\n[dim]enabled order:[/dim] {', '.join(enabled)}")


def _edit_enabled(source_id: str, *, enable: bool) -> None:
    """Add/remove ``source_id`` in ``[sources].enabled`` and persist it.

    Preserves order (append on enable; filter on disable) and is idempotent.
    Refuses to disable the last source — an empty enabled list would silently
    fall back to the Reddit default, which is surprising; keep at least one.
    """
    current = config.enabled_source_ids()
    if enable:
        if source_id in current:
            console.print(f"[dim]{source_id} is already enabled.[/dim]")
            return
        # Warn (don't block) when the id isn't registered yet: a connector may
        # ship in a later install/extra. It's persisted and shown as unreachable
        # in `sources list` until it can be constructed.
        if source_id not in _discover_sources():
            console.print(
                f"[yellow]Note:[/yellow] {source_id!r} is not a registered source yet — "
                "it'll show as unreachable until its connector is installed."
            )
        new = [*current, source_id]
    else:
        if source_id not in current:
            console.print(f"[dim]{source_id} is not enabled.[/dim]")
            return
        new = [s for s in current if s != source_id]
        if not new:
            err_console.print(
                "[red]Refusing to disable the last source[/red] — at least one must stay enabled. "
                "Enable another first, then disable this one."
            )
            raise typer.Exit(code=1)
    path = config.save_sources_config(new)
    verb = "Enabled" if enable else "Disabled"
    console.print(f"[green]{verb}[/green] {source_id} [dim]({path})[/dim]")
    console.print(f"[dim]enabled order:[/dim] {', '.join(new)}")


@sources_app.command("enable")
def sources_enable(
    source_id: Annotated[str, typer.Argument(help="Source id to enable, e.g. hackernews.")],
) -> None:
    """Enable a source: append it to ``[sources].enabled`` in the cwd metalworks.toml."""
    _edit_enabled(source_id, enable=True)


@sources_app.command("disable")
def sources_disable(
    source_id: Annotated[str, typer.Argument(help="Source id to disable, e.g. hackernews.")],
) -> None:
    """Disable a source: remove it from ``[sources].enabled`` in the cwd metalworks.toml."""
    _edit_enabled(source_id, enable=False)


# ── corpus sub-app ──────────────────────────────────────────────────────────


def _arctic_source_kwargs() -> dict[str, Any]:
    """Build the kwargs the Arctic (reddit) connector needs: a reader + live
    comment client. Other (keyless) connectors ignore these — ``resolve_sources``
    only passes the kwargs a factory accepts.
    """
    from metalworks.research.arctic import ArcticReader, ArcticShiftApiClient

    return {
        "reader": ArcticReader(probe_sleep_s=0.0),
        "comments": ArcticShiftApiClient(),
    }


def _widen_window(source: Any, months: int | None) -> Any:
    """Take ``source.latest_window()`` and widen it to ``months`` if it has a
    month anchor. A keyless date-ranged source keeps its own latest window."""
    from metalworks.research.sources import SourceWindow
    from metalworks.research.types import months_back

    window = source.latest_window()
    if months and months > 1 and getattr(window, "months", None):
        anchor = list(window.months)[-1]
        return SourceWindow(months=tuple(months_back(months, anchor=anchor)))
    return window


@corpus_app.command("add")
def corpus_add(
    source: Annotated[
        str, typer.Option("--source", help="Source id to ingest from (e.g. reddit, hackernews).")
    ],
    query: Annotated[
        str, typer.Option("--query", "-q", help="Query for the source (a subreddit for reddit).")
    ],
    months: Annotated[
        int | None,
        typer.Option("--months", help="Window in months back (sources with a month anchor)."),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option("--limit", help="Cap records pulled (dev guard; default unlimited)."),
    ] = None,
) -> None:
    """Ingest one source's items for a query into the local corpus store.

    Resolves ``--source`` via the registry, pulls records (+ comments) for the
    query over the window, and upserts them into ``config.default_store()``.
    Idempotent — re-running the same window upserts by id (no duplicates).
    """
    from metalworks.research.sources.ingest import ingest_source

    store = config.default_store()
    kwargs = _arctic_source_kwargs() if source in ("reddit", "arctic") else {}
    try:
        item_source = config.resolve_sources(override=[source], **kwargs)[0]
    except KeyError:
        err_console.print(
            f"[red]Unknown source {source!r}.[/red] Run `metalworks sources list` for ids."
        )
        raise typer.Exit(code=1) from None

    window = _widen_window(item_source, months)
    console.print(f"[bold]Ingesting[/bold] {source} for {query!r}...")
    reader = kwargs.get("reader")
    try:
        result = ingest_source(store, item_source, query=query, window=window, limit=limit)
    finally:
        if reader is not None and hasattr(reader, "close"):
            reader.close()
    tail = "" if result.has_comments else " (source has no comments)"
    console.print(
        f"[green]Ingested[/green] {result.records} records, "
        f"{result.comments} comments{tail} from {source}."
    )


@corpus_app.command("sync")
def corpus_sync(
    query: Annotated[
        list[str] | None,
        typer.Option("--query", "-q", help="Query per source (repeatable; default: 'all')."),
    ] = None,
    months: Annotated[
        int | None, typer.Option("--months", help="Window in months back (default: latest).")
    ] = None,
    limit: Annotated[
        int | None, typer.Option("--limit", help="Cap records pulled per query (dev guard).")
    ] = None,
) -> None:
    """Re-ingest the enabled sources for a recent window into the local store.

    Iterates ``config.resolve_sources()`` (the ``[sources].enabled`` set) and
    ingests each over its latest window (or ``--months`` back). Pass ``--query``
    (repeatable) to scope each source; with none, a broad ``"all"`` query is used.
    """
    from metalworks.research.sources.ingest import ingest_source

    store = config.default_store()
    kwargs = _arctic_source_kwargs()
    sources = config.resolve_sources(**kwargs)
    queries = query or ["all"]
    reader = kwargs.get("reader")
    total_records = total_comments = 0
    try:
        for item_source in sources:
            sid = getattr(item_source, "source_id", "?")
            window = _widen_window(item_source, months)
            for q in queries:
                result = ingest_source(store, item_source, query=q, window=window, limit=limit)
                total_records += result.records
                total_comments += result.comments
                console.print(
                    f"  [dim]{sid}[/dim] {q!r}: {result.records} records, "
                    f"{result.comments} comments"
                )
    finally:
        if reader is not None and hasattr(reader, "close"):
            reader.close()
    console.print(
        f"[green]Synced[/green] {len(sources)} source(s): "
        f"{total_records} records, {total_comments} comments total."
    )


def _corpus_counts(store: Any) -> dict[str, Any]:
    """Count records/comments in ``store``, broken down by source.

    The CorpusRepo protocol exposes only id-keyed reads, so this duck-types the
    two concrete backends: SqliteStores (a ``_con`` over the ``records`` /
    ``corpus_comments`` tables, both with a ``source`` column) and MemoryStores
    (``_records`` / ``_corpus_comments`` dicts of pydantic models). Returns
    ``{records, comments, by_source: {src: {records, comments}}}``.
    """
    from collections import Counter

    rec_by: Counter[str] = Counter()
    com_by: Counter[str] = Counter()

    con = getattr(store, "_con", None)
    if con is not None:  # SqliteStores
        lock = getattr(store, "_lock", None)
        ctx = lock if lock is not None else _nullcontext()
        with ctx:
            for src, n in con.execute("SELECT source, COUNT(*) FROM records GROUP BY source"):
                rec_by[str(src)] += int(n)
            for src, n in con.execute(
                "SELECT source, COUNT(*) FROM corpus_comments GROUP BY source"
            ):
                com_by[str(src)] += int(n)
    else:  # MemoryStores
        for rec in getattr(store, "_records", {}).values():
            rec_by[str(getattr(rec, "source", "?"))] += 1
        for com in getattr(store, "_corpus_comments", {}).values():
            com_by[str(getattr(com, "source", "?"))] += 1

    by_source: dict[str, dict[str, int]] = {}
    for src in sorted({*rec_by, *com_by}):
        by_source[src] = {"records": rec_by[src], "comments": com_by[src]}
    return {
        "records": sum(rec_by.values()),
        "comments": sum(com_by.values()),
        "by_source": by_source,
    }


class _nullcontext:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *_exc: object) -> None:
        return None


@corpus_app.command("stats")
def corpus_stats() -> None:
    """Show local corpus counts: total records/comments, broken down by source."""
    store = config.default_store()
    counts = _corpus_counts(store)
    console.print("[bold]Corpus[/bold]")
    console.print(f"  records:  {counts['records']}")
    console.print(f"  comments: {counts['comments']}")
    by_source = counts["by_source"]
    if not by_source:
        console.print("  [dim]empty store — run `metalworks corpus add` or `corpus sync`.[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("source")
    table.add_column("records", justify="right")
    table.add_column("comments", justify="right")
    for src, c in sorted(by_source.items()):
        table.add_row(src, str(c["records"]), str(c["comments"]))
    console.print(table)


# ── research sub-app ────────────────────────────────────────────────────────


@research_app.command("plan")
def research_plan(
    prompt: str,
    out: Annotated[Path, typer.Option("--out", "-o", help="Where to write the brief.")] = Path(
        "brief.json"
    ),
) -> None:
    """Walk the D1-D8 planner over a prompt and write a brief.json.

    Uses the configured chat model (auto-resolved from env) to draft each turn;
    the recommended option is auto-selected so this is non-interactive. Edit the
    emitted brief.json before `research run` if you want different answers.
    """
    import uuid

    from metalworks.research.arctic import ArcticReader
    from metalworks.research.deps import ResearchDeps
    from metalworks.research.planner import (
        QUESTIONS,
        BriefState,
        assemble_brief,
        provide_content,
    )

    chat = _resolve_chat_or_exit()
    embeddings = _resolve_embeddings_or_exit()
    store = config.default_store()
    reader = ArcticReader(probe_sleep_s=0.0)
    deps = ResearchDeps(chat=chat, embeddings=embeddings, corpus=store, reader=reader)

    state = BriefState(brief_id=str(uuid.uuid4()), prompt=prompt)
    for spec in QUESTIONS:
        brief_turn = provide_content(
            deps, question_spec=spec, prompt=prompt, prior_answers=dict(state.answers)
        )
        rec = next((i for i, o in enumerate(brief_turn.options) if o.is_recommended), 0)
        labels = [brief_turn.options[rec].label] if brief_turn.options else []
        state.answers[spec.decision_id] = {
            "option_indices": [rec] if brief_turn.options else [],
            "custom_text": "",
            "selected_labels": labels,
        }
        console.print(f"  [dim]{spec.header_chip}[/dim] -> {labels[0] if labels else '(none)'}")

    research_brief = assemble_brief(deps, state=state)
    out.write_text(research_brief.model_dump_json(indent=2), encoding="utf-8")
    console.print(f"\n[green]Wrote brief[/green] {out}")


@research_app.command("run")
def research_run(
    question: Annotated[
        str | None,
        typer.Option("--question", "-q", help="Research question; skips the brief.json step."),
    ] = None,
    brief: Annotated[
        Path | None,
        typer.Option("--brief", help="Path to a brief.json (alternative to --question)."),
    ] = None,
    subreddit: Annotated[
        list[str] | None,
        typer.Option("--subreddit", help="Subreddit to cover, repeatable; else auto."),
    ] = None,
    months: Annotated[
        int | None, typer.Option("--months", help="Corpus time window in months (default 12).")
    ] = None,
    source: Annotated[
        list[str] | None,
        typer.Option(
            "--source",
            help="Override the data sources to ingest from (repeatable); else configured/Reddit.",
        ),
    ] = None,
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write the report JSON here.")
    ] = None,
) -> None:
    """Run the research pipeline from a --question (no brief.json needed) or a --brief file."""
    from metalworks.contract import ResearchBrief, RunSummary
    from metalworks.research import run_research
    from metalworks.research.arctic import ArcticReader, ArcticShiftApiClient
    from metalworks.research.deps import ResearchDeps
    from metalworks.research.planner import brief_from_question

    if (question is None) == (brief is None):
        err_console.print("[red]Pass exactly one of --question or --brief.[/red]")
        raise typer.Exit(code=2)

    chat = _resolve_chat_or_exit()
    embeddings = _resolve_embeddings_or_exit()
    store = config.default_store()
    reader = ArcticReader(probe_sleep_s=0.0)
    comments = ArcticShiftApiClient()
    # --source overrides the run's connectors; without it deps.sources stays None
    # so effective_sources() keeps the configured/Reddit default (unchanged path).
    override_sources = None
    if source:
        try:
            override_sources = config.resolve_sources(
                override=source, reader=reader, comments=comments
            )
        except KeyError as exc:
            err_console.print(
                f"[red]{exc}[/red] Run `metalworks sources list` to see registered ids."
            )
            raise typer.Exit(code=1) from exc
    deps = ResearchDeps(
        chat=chat,
        embeddings=embeddings,
        corpus=store,
        reader=reader,
        search=config.resolve_search(),
        comments=comments,
        sources=override_sources,
    )

    if brief is not None:
        if not brief.is_file():
            err_console.print(f"[red]No such brief file: {brief}[/red]")
            raise typer.Exit(code=1)
        research_brief = ResearchBrief.model_validate_json(brief.read_text(encoding="utf-8"))
        if months is not None:
            research_brief = research_brief.model_copy(update={"time_window_months": months})
    else:
        assert question is not None  # guaranteed by the exactly-one check above
        research_brief = brief_from_question(
            deps, question, subreddits=subreddit, time_window_months=months or 12
        )

    console.print(f"[bold]Running research[/bold] for: {research_brief.question}")
    try:
        report = run_research(deps, brief=research_brief)
    finally:
        reader.close()

    store.save_report(report)
    store.save_run(RunSummary.from_report(report, question=research_brief.question))
    if out is not None:
        out.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        console.print(f"[green]Wrote report[/green] {out}")
    _print_report(report)


@research_app.command("list")
def research_list(
    limit: Annotated[int, typer.Option("--limit", help="Max runs to show.")] = 20,
) -> None:
    """List stored research runs (report ids the pillar commands take)."""
    runs = config.default_store().list_runs(limit=limit)
    if not runs:
        console.print(
            "[dim]No stored runs.[/dim] Run "
            '[bold]metalworks research run --question "..."[/bold] first.'
        )
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("report_id")
    table.add_column("query")
    table.add_column("authors", justify="right")
    table.add_column("generated")
    for r in runs:
        when = r.generated_at.strftime("%Y-%m-%d %H:%M") if r.generated_at else "—"
        query = r.query if len(r.query) <= 50 else r.query[:47] + "…"
        table.add_row(r.report_id, query, str(r.total_distinct_authors), when)
    console.print(table)


def _print_diff(diff: object) -> None:
    """Render a ReportDiff to the console (the version-to-version movement)."""
    from metalworks.contract import ReportDiff

    assert isinstance(diff, ReportDiff)
    console.print(
        f"\n[bold]Refresh diff[/bold] v{diff.from_version} → v{diff.to_version} — {diff.summary}"
    )
    console.print(
        f"  threads {diff.total_threads_before} → {diff.total_threads_after} "
        f"({diff.total_threads_delta:+d}) · "
        f"authors {diff.total_distinct_authors_before} → {diff.total_distinct_authors_after} "
        f"({diff.total_distinct_authors_delta:+d}) · "
        f"themes {diff.cluster_count_before} → {diff.cluster_count_after}"
    )
    for claim in diff.clusters_added:
        console.print(f"  [green]+ new[/green] {claim}")
    for claim in diff.clusters_dropped:
        console.print(f"  [red]- faded[/red] {claim}")
    for d in diff.clusters_changed:
        console.print(
            f"  [yellow]~ shift[/yellow] {d.claim_after} "
            f"(demand {d.demand_score_delta:+.2f}, authors {d.distinct_authors_delta:+d})"
        )


def _lineage_head(store: RunRepo, prior: DemandReport) -> DemandReport:
    """The highest-version stored report in ``prior``'s lineage (so a refresh
    advances from the head and version numbers stay monotonic). Falls back to
    ``prior`` when no run rows exist for the lineage (e.g. pre-lineage reports)."""
    lineage = prior.effective_lineage_id
    runs = [r for r in store.list_runs(limit=10_000) if (r.lineage_id or r.report_id) == lineage]
    if not runs:
        return prior
    head_ref = max(runs, key=lambda r: r.version)
    head = store.get_report(head_ref.report_id)
    return head or prior


@research_app.command("refresh")
def research_refresh(
    report_id: Annotated[
        str, typer.Argument(help="A stored report id (any version in the lineage).")
    ],
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write the new report JSON here.")
    ] = None,
) -> None:
    """Re-synthesize a stored report against the current corpus → a new pinned version + diff."""
    from metalworks.contract import DemandReport, RunSummary
    from metalworks.research.arctic import ArcticReader, ArcticShiftApiClient
    from metalworks.research.deps import ResearchDeps
    from metalworks.research.refresh import refresh_report

    store = config.default_store()
    prior = store.get_report(report_id)
    if prior is None:
        err_console.print(
            f"[red]No stored report {report_id}.[/red] "
            "Run `metalworks research list` to see report ids."
        )
        raise typer.Exit(code=1)
    head = _lineage_head(store, prior)
    assert isinstance(head, DemandReport)
    if head.brief is None:
        err_console.print(
            "[red]That report has no brief and can't be refreshed.[/red] "
            "Run `metalworks research run` for a fresh lineage."
        )
        raise typer.Exit(code=1)

    chat = _resolve_chat_or_exit()
    embeddings = _resolve_embeddings_or_exit()
    reader = ArcticReader(probe_sleep_s=0.0)
    comments = ArcticShiftApiClient()
    deps = ResearchDeps(
        chat=chat,
        embeddings=embeddings,
        corpus=store,
        reader=reader,
        search=config.resolve_search(),
        comments=comments,
    )
    console.print(f"[bold]Refreshing[/bold] v{head.version} → v{head.version + 1}: {head.query}")
    try:
        new_report, diff = refresh_report(deps, head)
    finally:
        reader.close()

    store.save_report(new_report)
    store.save_run(RunSummary.from_report(new_report))
    if out is not None:
        out.write_text(new_report.model_dump_json(indent=2), encoding="utf-8")
        console.print(f"[green]Wrote report[/green] {out}")
    _print_diff(diff)
    console.print(f"[green]New version[/green] {new_report.report_id} (v{new_report.version})")


@research_app.command("versions")
def research_versions(
    report_id: Annotated[str, typer.Argument(help="Any report id in the lineage.")],
) -> None:
    """List the versions in a report's lineage, oldest → newest."""
    from metalworks.contract import RunSummary

    store = config.default_store()
    prior = store.get_report(report_id)
    if prior is None:
        err_console.print(f"[red]No stored report {report_id}.[/red]")
        raise typer.Exit(code=1)
    lineage = prior.effective_lineage_id
    runs = sorted(
        (r for r in store.list_runs(limit=10_000) if (r.lineage_id or r.report_id) == lineage),
        key=lambda r: r.version,
    )
    if not runs:
        runs = [RunSummary.from_report(prior)]
    table = Table(show_header=True, header_style="bold", title=f"lineage {lineage}")
    table.add_column("v", justify="right")
    table.add_column("report_id")
    table.add_column("authors", justify="right")
    table.add_column("generated")
    for r in runs:
        when = r.generated_at.strftime("%Y-%m-%d %H:%M") if r.generated_at else "—"
        table.add_row(str(r.version), r.report_id, str(r.total_distinct_authors or 0), when)
    console.print(table)


@research_app.command("diff")
def research_diff_cmd(
    report_a: Annotated[str, typer.Argument(help="The earlier report id.")],
    report_b: Annotated[str, typer.Argument(help="The later report id.")],
) -> None:
    """Show the diff between two stored report versions."""
    from metalworks.research.diff import diff_reports

    store = config.default_store()
    a = store.get_report(report_a)
    b = store.get_report(report_b)
    missing = [rid for rid, rep in ((report_a, a), (report_b, b)) if rep is None]
    if missing:
        err_console.print(f"[red]No stored report(s): {', '.join(missing)}.[/red]")
        raise typer.Exit(code=1)
    assert a is not None and b is not None
    embeddings = _resolve_embeddings_or_exit()
    _print_diff(diff_reports(a, b, embeddings=embeddings))


def _print_positioning(brief: object) -> None:
    stmt = getattr(brief, "positioning_statement", "")
    console.print(f"\n[bold]Positioning[/bold] — report {getattr(brief, 'report_id', '')}")
    console.print(f"  [italic]{stmt}[/italic]")
    wedge = getattr(brief, "wedge", None)
    if wedge is not None:
        console.print("  [bold]wedge:[/bold]")
        console.print(f"    alternative: {wedge.competitive_alternative}")
        console.print(f"    unique:      {wedge.unique_attribute}")
        console.print(f"    value:       {wedge.value}")
        console.print(f"    beachhead:   {wedge.beachhead}")
        console.print(f"    category:    {wedge.market_category}")
    price = getattr(brief, "price_hypothesis", None)
    if price is not None and not price.insufficient_signal and price.low is not None:
        console.print(f"  [bold]price:[/bold] {price.currency} {price.low:g}-{price.high:g}")
    if getattr(brief, "partial", False):
        console.print(f"  [yellow]partial:[/yellow] {getattr(brief, 'caveat', '')}")


@research_app.command("position")
def research_position(
    report_id: Annotated[
        str, typer.Argument(help="Report id (from `research run` / `research list`).")
    ],
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write the positioning brief JSON here.")
    ] = None,
) -> None:
    """Derive a grounded positioning wedge from a stored report (one LLM call)."""
    from metalworks.research.arctic import ArcticReader
    from metalworks.research.deps import ResearchDeps
    from metalworks.research.synthesis import build_positioning_brief

    chat = _resolve_chat_or_exit()
    store = config.default_store()
    report = store.get_report(report_id)
    if report is None:
        err_console.print(
            f"[red]No report {report_id!r} in the local store.[/red] "
            "Run `metalworks research run` first, or check the id."
        )
        raise typer.Exit(code=1)
    reader = ArcticReader(probe_sleep_s=0.0)
    deps = ResearchDeps(
        chat=chat, embeddings=_resolve_embeddings_or_exit(), corpus=store, reader=reader
    )
    console.print(f"[bold]Positioning[/bold] report {report_id}...")
    try:
        brief = build_positioning_brief(deps, report)
    finally:
        reader.close()
    if out is not None:
        out.write_text(brief.model_dump_json(indent=2), encoding="utf-8")
        console.print(f"[green]Wrote brief[/green] {out}")
    _print_positioning(brief)


def _print_competitor_map(cmap: object) -> None:
    console.print(f"\n[bold]Competitive landscape[/bold] — report {getattr(cmap, 'report_id', '')}")
    if getattr(cmap, "partial", False):
        console.print(f"  [yellow]partial:[/yellow] {getattr(cmap, 'caveat', '')}")
    sq = getattr(cmap, "status_quo_alternative", None)
    competitors = getattr(cmap, "competitors", [])
    rows = [sq, *competitors] if sq is not None else list(competitors)
    for c in rows:
        console.print(f"  [bold]{c.name}[/bold] ({c.kind}) — {c.one_liner}")
        for g in c.gaps:
            console.print(f"    [red]gap[/red] [{g.severity}]: {g.claim}")


@research_app.command("competitor-map")
def research_competitor_map(
    report_id: Annotated[
        str, typer.Argument(help="Report id (from `research run` / `research list`).")
    ],
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write the competitor map JSON here.")
    ] = None,
) -> None:
    """Map the competitive landscape for a stored report (grounded names, cited gaps)."""
    from metalworks.research import run_competitor_map
    from metalworks.research.arctic import ArcticReader
    from metalworks.research.deps import ResearchDeps

    chat = _resolve_chat_or_exit()
    store = config.default_store()
    report = store.get_report(report_id)
    if report is None:
        err_console.print(
            f"[red]No report {report_id!r} in the local store.[/red] "
            "Run `metalworks research run` first, or check the id."
        )
        raise typer.Exit(code=1)
    reader = ArcticReader(probe_sleep_s=0.0)
    deps = ResearchDeps(
        chat=chat,
        embeddings=_resolve_embeddings_or_exit(),
        corpus=store,
        reader=reader,
        search=config.resolve_search(),
    )
    console.print(f"[bold]Mapping competitors[/bold] for report {report_id}...")
    try:
        cmap = run_competitor_map(deps, report)
    finally:
        reader.close()
    if out is not None:
        out.write_text(cmap.model_dump_json(indent=2), encoding="utf-8")
        console.print(f"[green]Wrote competitor map[/green] {out}")
    _print_competitor_map(cmap)


def _print_landscape(landscape: object) -> None:
    _print_competitor_map(getattr(landscape, "competitor_map", None))
    sols = getattr(landscape, "existing_solutions", [])
    if sols:
        console.print("\n[bold]Existing solutions[/bold] (real shipped products):")
        for s in sols:
            tag = f" — {s.tagline}" if getattr(s, "tagline", "") else ""
            console.print(f"  [bold]{s.name}[/bold] ({s.source}, {s.traction} traction){tag}")
    if getattr(landscape, "partial", False):
        console.print(f"  [yellow]partial:[/yellow] {getattr(landscape, 'caveat', '')}")


@research_app.command("landscape")
def research_landscape(
    report_id: Annotated[
        str, typer.Argument(help="Report id (from `research run` / `research list`).")
    ],
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write the landscape JSON here.")
    ] = None,
) -> None:
    """Map the full landscape: competitors + existing solutions + cost of doing nothing."""
    from metalworks.research import run_landscape
    from metalworks.research.arctic import ArcticReader
    from metalworks.research.deps import ResearchDeps

    chat = _resolve_chat_or_exit()
    store = config.default_store()
    report = store.get_report(report_id)
    if report is None:
        err_console.print(
            f"[red]No report {report_id!r} in the local store.[/red] "
            "Run `metalworks research run` first, or check the id."
        )
        raise typer.Exit(code=1)
    reader = ArcticReader(probe_sleep_s=0.0)
    deps = ResearchDeps(
        chat=chat,
        embeddings=_resolve_embeddings_or_exit(),
        corpus=store,
        reader=reader,
        search=config.resolve_search(),
    )
    console.print(f"[bold]Mapping landscape[/bold] for report {report_id}...")
    try:
        landscape = run_landscape(deps, report)
    finally:
        reader.close()
    if out is not None:
        out.write_text(landscape.model_dump_json(indent=2), encoding="utf-8")
        console.print(f"[green]Wrote landscape[/green] {out}")
    _print_landscape(landscape)


def _print_idea_sketch(s: object) -> None:
    console.print(f"\n[bold]Idea[/bold] ({getattr(s, 'provenance', '')}): {getattr(s, 'idea', '')}")
    console.print(f"  [bold]hypothesis:[/bold] {getattr(s, 'hypothesis', '')}")
    if getattr(s, "pain", ""):
        console.print(f"  pain: {s.pain}")  # type: ignore[attr-defined]
    if getattr(s, "partial", False):
        console.print(f"  [yellow]partial:[/yellow] {getattr(s, 'caveat', '')}")


def _print_ideation(r: object) -> None:
    console.print(f"\n[bold]Ideas surfaced[/bold] from report {getattr(r, 'report_id', '')}:")
    for s in getattr(r, "sketches", []):
        console.print(f"  • [bold]{s.idea}[/bold] — {s.hypothesis}")
    if getattr(r, "partial", False):
        console.print(f"  [yellow]{getattr(r, 'caveat', '')}[/yellow]")


@research_app.command("ideate")
def research_ideate(
    idea: Annotated[str | None, typer.Argument(help="A raw idea to sharpen (idea-first).")] = None,
    from_report: Annotated[
        str | None,
        typer.Option("--from-report", help="Surface ideas from a stored report's forks."),
    ] = None,
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write the result JSON here.")
    ] = None,
) -> None:
    """Frame an idea to test — idea-first (sharpen a pitch) or evidence-first (--from-report)."""
    if not idea and not from_report:
        err_console.print("[red]Provide an idea, or --from-report <report_id>.[/red]")
        raise typer.Exit(code=1)
    from metalworks.research import ideate_from_idea, ideate_from_report
    from metalworks.research.arctic import ArcticReader
    from metalworks.research.deps import ResearchDeps

    chat = _resolve_chat_or_exit()
    store = config.default_store()
    reader = ArcticReader(probe_sleep_s=0.0)
    deps = ResearchDeps(
        chat=chat,
        embeddings=_resolve_embeddings_or_exit(),
        corpus=store,
        reader=reader,
        search=config.resolve_search(),
    )
    try:
        if from_report:
            report = store.get_report(from_report)
            if report is None:
                err_console.print(f"[red]No report {from_report!r} in the local store.[/red]")
                raise typer.Exit(code=1)
            result: object = ideate_from_report(deps, report)
            _print_ideation(result)
        else:
            assert idea is not None
            result = ideate_from_idea(deps, idea)
            _print_idea_sketch(result)
    finally:
        reader.close()
    if out is not None:
        out.write_text(result.model_dump_json(indent=2), encoding="utf-8")  # type: ignore[attr-defined]
        console.print(f"[green]Wrote[/green] {out}")


def _print_assessment(a: object) -> None:
    decision = str(getattr(a, "decision", ""))
    color = {"go": "green", "pivot": "yellow", "no_go": "red"}.get(decision, "white")
    label = decision.upper().replace("_", "-")
    console.print(f"\n[bold {color}]{label}[/bold {color}] — report {getattr(a, 'report_id', '')}")
    gap = getattr(a, "gap", None)
    if gap is not None:
        console.print(f"  demand: {gap.demand_strength} · saturation: {gap.landscape_saturation}")
    console.print(f"  {getattr(a, 'rationale', '')}")
    pt = getattr(a, "pivot_target", None)
    if pt is not None:
        console.print(f"  [bold]pivot →[/bold] {pt.kind} {pt.target_id}: {pt.why}")
    if getattr(a, "partial", False):
        console.print(f"  [yellow]partial:[/yellow] {getattr(a, 'caveat', '')}")


@research_app.command("assess")
def research_assess(
    report_id: Annotated[
        str, typer.Argument(help="Report id (from `research run` / `research list`).")
    ],
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write the assessment JSON here.")
    ] = None,
) -> None:
    """Verdict: GO / PIVOT / NO-GO — the deterministic gap over demand + landscape."""
    from metalworks.research import run_assessment, run_landscape
    from metalworks.research.arctic import ArcticReader
    from metalworks.research.deps import ResearchDeps

    chat = _resolve_chat_or_exit()
    store = config.default_store()
    report = store.get_report(report_id)
    if report is None:
        err_console.print(f"[red]No report {report_id!r} in the local store.[/red]")
        raise typer.Exit(code=1)
    reader = ArcticReader(probe_sleep_s=0.0)
    deps = ResearchDeps(
        chat=chat,
        embeddings=_resolve_embeddings_or_exit(),
        corpus=store,
        reader=reader,
        search=config.resolve_search(),
    )
    console.print(f"[bold]Assessing[/bold] report {report_id} (landscape → verdict)...")
    try:
        landscape = run_landscape(deps, report)
        assessment = run_assessment(deps, report, landscape)
    finally:
        reader.close()
    if out is not None:
        out.write_text(assessment.model_dump_json(indent=2), encoding="utf-8")
        console.print(f"[green]Wrote assessment[/green] {out}")
    _print_assessment(assessment)


def _print_validation(v: object) -> None:
    outcome = str(getattr(v, "outcome", ""))
    color = {"go": "green", "no_go": "red", "exhausted": "yellow"}.get(outcome, "white")
    console.print(
        f"\n[bold {color}]{outcome.upper()}[/bold {color}] after "
        f"{getattr(v, 'iterations', 0)} round(s)"
    )
    for e in getattr(v, "decision_log", []):
        console.print(f"  {e.iteration}. [{e.decision}] {e.idea} — {e.why}")


@research_app.command("validate")
def research_validate(
    idea: Annotated[str, typer.Argument(help="The idea to run through the validate loop.")],
    max_iterations: Annotated[
        int, typer.Option("--max-iterations", help="Loop cap before 'exhausted'.")
    ] = 4,
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write the result JSON here.")
    ] = None,
) -> None:
    """Run the validate loop (--auto): ideate → demand → landscape → assess, looping on PIVOT."""
    from metalworks.research import validate as run_validate
    from metalworks.research.arctic import ArcticReader
    from metalworks.research.deps import ResearchDeps

    chat = _resolve_chat_or_exit()
    store = config.default_store()
    reader = ArcticReader(probe_sleep_s=0.0)
    deps = ResearchDeps(
        chat=chat,
        embeddings=_resolve_embeddings_or_exit(),
        corpus=store,
        reader=reader,
        search=config.resolve_search(),
    )
    console.print(f"[bold]Validating[/bold] '{idea}' (auto loop, ≤{max_iterations} rounds)...")
    try:
        result = run_validate(deps, idea, max_iterations=max_iterations)
    finally:
        reader.close()
    if out is not None:
        out.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        console.print(f"[green]Wrote result[/green] {out}")
    _print_validation(result)


def _print_surface(rec: object, skeleton: object) -> None:
    console.print(f"\n[bold]Surface[/bold] — report {getattr(rec, 'report_id', '')}")
    console.print(
        f"  [bold]{getattr(rec, 'chosen', '?')}[/bold]"
        f" (runner-up: {getattr(rec, 'runner_up', None) or 'none'})"
        f"  [{getattr(rec, 'confidence', '')}]"
    )
    console.print(f"  [italic]{getattr(rec, 'rationale', '')}[/italic]")
    for d in getattr(rec, "rubric", []):
        tag = "assumption" if d.is_assumption else f"{len(d.evidence_refs)} cited"
        console.print(f"    - {d.name}: {d.finding}  [dim]({tag})[/dim]")
    if getattr(rec, "partial", False):
        console.print(f"  [yellow]partial:[/yellow] {getattr(rec, 'caveat', '')}")
    console.print(f"  [bold]UX skeleton[/bold] ({getattr(skeleton, 'surface', '')}):")
    for s in getattr(skeleton, "screens", []):
        mark = "validated" if s.validated else "[yellow]hypothesis[/yellow]"
        console.print(f"    - {s.name}: {s.purpose} → {s.primary_action}  [dim]({mark})[/dim]")


@research_app.command("surface")
def research_surface(
    report_id: Annotated[
        str, typer.Argument(help="Report id (from `research run` / `research list`).")
    ],
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write the surface recommendation JSON here.")
    ] = None,
) -> None:
    """Recommend a product surface + UX skeleton for a stored report (grounded)."""
    from metalworks.research import build_ux_skeleton, decide_surface
    from metalworks.research.arctic import ArcticReader
    from metalworks.research.deps import ResearchDeps
    from metalworks.research.synthesis import build_positioning_brief

    chat = _resolve_chat_or_exit()
    store = config.default_store()
    report = store.get_report(report_id)
    if report is None:
        err_console.print(
            f"[red]No report {report_id!r} in the local store.[/red] "
            "Run `metalworks research run` first, or check the id."
        )
        raise typer.Exit(code=1)
    reader = ArcticReader(probe_sleep_s=0.0)
    deps = ResearchDeps(
        chat=chat,
        embeddings=_resolve_embeddings_or_exit(),
        corpus=store,
        reader=reader,
        search=config.resolve_search(),
    )
    console.print(f"[bold]Deciding surface[/bold] for report {report_id}...")
    try:
        positioning = build_positioning_brief(deps, report)
        rec = decide_surface(deps, report, positioning)
        skeleton = build_ux_skeleton(deps, report, positioning, rec.chosen)
    finally:
        reader.close()
    if out is not None:
        out.write_text(rec.model_dump_json(indent=2), encoding="utf-8")
        console.print(f"[green]Wrote surface recommendation[/green] {out}")
    _print_surface(rec, skeleton)


@research_app.command("site")
def research_site(
    report_id: Annotated[
        str, typer.Argument(help="Report id (from `research run` / `research list`).")
    ],
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write the rendered index.html here.")
    ] = None,
    json_out: Annotated[
        Path | None, typer.Option("--json", help="Write the MarketingSite JSON here.")
    ] = None,
) -> None:
    """Build a grounded marketing site from a stored report (verbatim, cited copy)."""
    from metalworks.research import build_marketing_site, render_site_html
    from metalworks.research.arctic import ArcticReader
    from metalworks.research.deps import ResearchDeps
    from metalworks.research.synthesis import build_positioning_brief

    chat = _resolve_chat_or_exit()
    store = config.default_store()
    report = store.get_report(report_id)
    if report is None:
        err_console.print(f"[red]No report {report_id!r} in the local store.[/red]")
        raise typer.Exit(code=1)
    reader = ArcticReader(probe_sleep_s=0.0)
    deps = ResearchDeps(
        chat=chat, embeddings=_resolve_embeddings_or_exit(), corpus=store, reader=reader
    )
    console.print(f"[bold]Building site[/bold] for report {report_id}...")
    try:
        site = build_marketing_site(deps, report, build_positioning_brief(deps, report))
    finally:
        reader.close()
    if json_out is not None:
        json_out.write_text(site.model_dump_json(indent=2), encoding="utf-8")
    if out is not None:
        out.write_text(render_site_html(site, report), encoding="utf-8")
        console.print(f"[green]Wrote site[/green] {out}")
    if site.partial:
        console.print(f"  [yellow]partial:[/yellow] {site.caveat}")
    for s in site.sections:
        console.print(f"  [bold]{s.role}[/bold] [{s.provenance}]: {s.copy[:70]}")


@research_app.command("launch")
def research_launch(
    report_id: Annotated[
        str, typer.Argument(help="Report id (from `research run` / `research list`).")
    ],
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write the launch assets JSON here.")
    ] = None,
) -> None:
    """Draft grounded, channel-native launch assets + a human-run channel plan (never posts)."""
    from metalworks.research import build_launch_assets, plan_channels
    from metalworks.research.arctic import ArcticReader
    from metalworks.research.deps import ResearchDeps
    from metalworks.research.synthesis import build_positioning_brief

    chat = _resolve_chat_or_exit()
    store = config.default_store()
    report = store.get_report(report_id)
    if report is None:
        err_console.print(f"[red]No report {report_id!r} in the local store.[/red]")
        raise typer.Exit(code=1)
    reader = ArcticReader(probe_sleep_s=0.0)
    deps = ResearchDeps(
        chat=chat, embeddings=_resolve_embeddings_or_exit(), corpus=store, reader=reader
    )
    console.print(f"[bold]Drafting launch assets[/bold] for report {report_id}...")
    try:
        assets = build_launch_assets(deps, report, build_positioning_brief(deps, report))
    finally:
        reader.close()
    plan = plan_channels(report)
    if not assets:
        console.print("[yellow]No-go:[/yellow] demand is too thin to draft launch assets.")
    for a in assets:
        console.print(f"\n[bold]{a.surface}[/bold]: {a.title}")
        console.print(f"  {a.body[:200]}")
        for c in a.claim_citations:
            console.print(f"  [dim]cited:[/dim] {c.claim_text[:50]}")
    console.print("\n[bold]Channel plan[/bold] (every step human-gated):")
    for step in plan.steps:
        console.print(f"  {step.scheduled_offset} {step.surface}: {step.action}")
    if out is not None:
        out.write_text(
            json.dumps([a.model_dump(mode="json") for a in assets], indent=2), encoding="utf-8"
        )
        console.print(f"[green]Wrote launch assets[/green] {out}")


@research_app.command("content-plan")
def research_content_plan(
    report_id: Annotated[
        str, typer.Argument(help="Report id (from `research run` / `research list`).")
    ],
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write the content plan JSON here.")
    ] = None,
) -> None:
    """Project a stored report into a deterministic content/SEO plan (no LLM, zero-key)."""
    from metalworks.research import content_plan_from_report
    from metalworks.research.marketing import render_content_markdown

    store = config.default_store()
    report = store.get_report(report_id)
    if report is None:
        err_console.print(
            f"[red]No report {report_id!r} in the local store.[/red] "
            "Run `metalworks research run` first, or check the id."
        )
        raise typer.Exit(code=1)
    plan = content_plan_from_report(report)
    if out is not None:
        out.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        console.print(f"[green]Wrote content plan[/green] {out}")
    console.print(render_content_markdown(plan))


# ── build sub-app ────────────────────────────────────────────────────────────

build_app = typer.Typer(
    help="Scaffold an evidence-grounded build harness from a report.", no_args_is_help=True
)


def _load_report_for_build(report: str):
    """Resolve a report id or a report.json path into a DemandReport (or exit)."""
    from metalworks.contract import DemandReport

    candidate = Path(report)
    if candidate.exists() and candidate.suffix == ".json":
        return DemandReport.model_validate_json(candidate.read_text(encoding="utf-8"))
    stored = config.default_store().get_report(report)
    if stored is None:
        err_console.print(
            f"[red]No report {report!r}[/red] — pass a stored report id "
            "(`metalworks research list`) or a path to a report.json."
        )
        raise typer.Exit(code=1)
    return stored


@build_app.command("init")
def build_init(
    report: Annotated[
        str, typer.Argument(help="Report id (from `research list`) or a path to report.json.")
    ],
    dest: Annotated[
        Path, typer.Option("--dest", "-d", help="Directory to scaffold the build harness into.")
    ] = Path("./build"),
    surface: Annotated[
        str,
        typer.Option(
            "--surface",
            help="Target surface: web | mobile | cli | api | sdk | browser_extension | desktop.",
        ),
    ] = "web",
    base: Annotated[
        str, typer.Option("--base", help="Stack hint recorded in the spec (e.g. next-shipfast).")
    ] = "empty",
) -> None:
    """Derive a grounded BuildSpec and scaffold a cite-or-die build harness (no product code)."""
    from typing import cast, get_args

    from metalworks.build import build_spec_from_report, scaffold
    from metalworks.contract.surface import SurfaceKind
    from metalworks.research.arctic import ArcticReader
    from metalworks.research.deps import ResearchDeps
    from metalworks.research.synthesis import build_positioning_brief

    valid_surfaces = get_args(SurfaceKind)
    if surface not in valid_surfaces:
        err_console.print(
            f"[red]Unknown surface {surface!r}.[/red] Choose one of: {', '.join(valid_surfaces)}."
        )
        raise typer.Exit(code=1)

    report_obj = _load_report_for_build(report)
    chat = _resolve_chat_or_exit()
    reader = ArcticReader(probe_sleep_s=0.0)
    deps = ResearchDeps(
        chat=chat,
        embeddings=_resolve_embeddings_or_exit(),
        corpus=config.default_store(),
        reader=reader,
    )
    console.print(f"[bold]Speccing build[/bold] for report {report_obj.report_id} ({surface})...")
    try:
        positioning = build_positioning_brief(deps, report_obj)
        spec = build_spec_from_report(
            deps, report_obj, positioning, cast(SurfaceKind, surface), stack=base
        )
    finally:
        reader.close()
    if spec.partial:
        console.print(f"  [yellow]partial:[/yellow] {spec.caveat}")
    written = scaffold(spec, report_obj, dest, base=base)
    console.print(
        f"[green]Scaffolded {len(written)} files[/green] into {dest} "
        f"({len(spec.features)} features, {len(spec.personas)} personas, "
        f"{len(spec.pricing_tiers)} tiers)."
    )
    for path in written:
        console.print(f"  [dim]{path}[/dim]")
    console.print(
        "\nOpen the harness in your coding agent and run [bold]/scaffold-startup[/bold]. "
        "metalworks specced it; you build it."
    )


# ── reddit sub-app ──────────────────────────────────────────────────────────


@reddit_app.command("search")
def reddit_search(
    query: str,
    subreddit: Annotated[str | None, typer.Option("--subreddit", help="Restrict to r/X.")] = None,
    limit: Annotated[int, typer.Option("--limit", help="Max results.")] = 15,
) -> None:
    """Search public Reddit submissions ([reddit] extra, no key needed)."""
    from metalworks.reddit import RedditSearch

    posts = RedditSearch().search_posts(query, subreddit=subreddit, limit=limit)
    if not posts:
        console.print("[dim]No results.[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("score", justify="right")
    table.add_column("subreddit")
    table.add_column("title")
    for p in posts:
        table.add_row(str(p.score), p.subreddit, p.title)
    console.print(table)


subreddit_app = typer.Typer(help="Per-subreddit intel and rules.", no_args_is_help=True)
auth_app = typer.Typer(help="Connect a Reddit account (OAuth).", no_args_is_help=True)


@subreddit_app.command("info")
def subreddit_info(name: str) -> None:
    """Fetch a subreddit's intel (description, subscribers, top titles, rules)."""
    from metalworks.reddit import fetch_subreddit_intel

    intel = fetch_subreddit_intel(name)
    console.print(f"[bold]r/{intel.name}[/bold]")
    if intel.subscribers is not None:
        console.print(f"  subscribers: {intel.subscribers:,}")
    if intel.description:
        console.print(f"  {intel.description}")
    if intel.rules:
        console.print("  [bold]rules:[/bold]")
        for rule in intel.rules:
            console.print(f"    - {rule}")


@subreddit_app.command("rules")
def subreddit_rules(name: str) -> None:
    """List a subreddit's posting rules."""
    from metalworks.reddit import RedditSearch

    rules = RedditSearch().get_subreddit_rules(name)
    if not rules:
        console.print("[dim]No rules found.[/dim]")
        return
    for rule in rules:
        console.print(f"- {rule}")


@auth_app.command("login")
def auth_login(
    redirect_uri: Annotated[
        str, typer.Option("--redirect-uri", help="Registered redirect URI.")
    ] = "http://localhost:8765/callback",
) -> None:
    """Start the Reddit OAuth loopback flow and store the connected account.

    Builds the authorize URL and exchanges the returned code via
    ``RedditOAuth.exchange_code``. The localhost loopback HTTP listener that
    auto-captures the ``code`` is STUBBED — see the TODO below — so for now you
    paste the ``code`` from the redirect URL.
    """
    import urllib.parse
    import uuid

    from metalworks.reddit import RedditOAuth
    from metalworks.stores import TokenCipher

    client_id = os.environ.get("REDDIT_CLIENT_ID")
    if not client_id:
        err_console.print("[red]Set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET first.[/red]")
        raise typer.Exit(code=1)

    state = uuid.uuid4().hex
    params = {
        "client_id": client_id,
        "response_type": "code",
        "state": state,
        "redirect_uri": redirect_uri,
        "duration": "permanent",
        "scope": "identity submit read",
    }
    authorize_url = "https://www.reddit.com/api/v1/authorize?" + urllib.parse.urlencode(params)
    console.print("[bold]Open this URL, approve, then copy the `code` from the redirect:[/bold]")
    console.print(authorize_url)
    # TODO(oauth-loopback): run a one-shot localhost HTTP server on the redirect
    # port to auto-capture `code` (and verify `state`) instead of pasting. The
    # exchange below is the real, wired path; only the capture is manual.
    code = typer.prompt("Paste the code")

    store = config.default_store()
    oauth = RedditOAuth(accounts=store, cipher=TokenCipher())
    try:
        bundle = oauth.exchange_code(code, redirect_uri)
        account = oauth.store_account(bundle)
    finally:
        oauth.close()
    console.print(f"[green]Connected[/green] u/{account.username}")


@reddit_app.command("post")
def reddit_post(
    url: Annotated[str, typer.Argument(help="The thread URL to reply to.")],
    text: Annotated[str, typer.Option("--text", help="The reply text.")],
    username: Annotated[
        str | None, typer.Option("--username", help="Which connected account to post as.")
    ] = None,
    yes: Annotated[bool, typer.Option("--yes", help="Actually send (default: dry-run).")] = False,
) -> None:
    """Reply to a Reddit thread. Runs the compliance gate FIRST; refuses on fail.

    Without ``--yes`` this is a dry-run: it prints the verdict and stops. With
    ``--yes`` it posts via the connected account — but still refuses if the
    deterministic compliance gate fails.
    """
    from metalworks.reddit import RedditOAuth, heuristic_check
    from metalworks.stores import TokenCipher

    verdict = heuristic_check(text)
    _print_verdict(verdict)
    if not verdict.pass_:
        err_console.print("[red]Compliance gate FAILED — refusing to post.[/red]")
        raise typer.Exit(code=1)

    if not yes:
        console.print("[yellow]Dry-run.[/yellow] Re-run with --yes to actually post.")
        return

    store = config.default_store()
    accounts = store.list_accounts()
    if not accounts:
        err_console.print("[red]No connected account. Run: metalworks reddit auth login[/red]")
        raise typer.Exit(code=1)
    target = username or accounts[0].username
    oauth = RedditOAuth(accounts=store, cipher=TokenCipher())
    try:
        result = oauth.post_comment(username=target, post_url=url, text=text)
    finally:
        oauth.close()
    if not result.success:
        err_console.print(f"[red]Post failed: {result.error}[/red]")
        raise typer.Exit(code=1)
    console.print(f"[green]Posted[/green] as u/{result.username}: {result.comment_url}")


# ── arctic sub-app ──────────────────────────────────────────────────────────


@arctic_app.command("months")
def arctic_months(subreddit: str) -> None:
    """Print the latest available submissions month in the Arctic corpus."""
    from metalworks.research.arctic import ArcticReader

    _ = subreddit  # availability is corpus-wide; arg kept for symmetry/UX
    reader = ArcticReader(probe_sleep_s=0.0)
    try:
        latest = reader.latest_available_month("submissions")
        console.print(f"latest available month: [bold]{latest}[/bold]")
    finally:
        reader.close()


@arctic_app.command("pull")
def arctic_pull(
    subreddit: str,
    months: Annotated[int, typer.Option("--months", help="How many months back.")] = 1,
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write rows as JSONL here.")
    ] = None,
) -> None:
    """Pull submissions for a subreddit from the Arctic corpus → table or JSONL."""
    from metalworks.research.arctic import ArcticReader
    from metalworks.research.types import months_back

    sub = subreddit.strip().lstrip("r/").lstrip("/")
    reader = ArcticReader(probe_sleep_s=0.0)
    try:
        window = months_back(months, anchor=reader.latest_available_month("submissions"))
        rows = list(
            reader.pull_subreddit(
                subreddit=sub,
                content_type="submissions",
                months=window,
                select_cols=["id", "title", "score", "num_comments"],
            )
        )
    finally:
        reader.close()

    if out is not None:
        with out.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, default=str) + "\n")
        console.print(f"[green]Wrote[/green] {len(rows)} rows -> {out}")
        return
    console.print(f"Pulled {len(rows)} threads from r/{sub} across {len(window)} month(s).")
    for row in rows[:20]:
        console.print(f"  [dim]{row.get('score')}[/dim]  {row.get('title')}")


# ── mcp sub-app ─────────────────────────────────────────────────────────────


@mcp_app.command("serve")
def mcp_serve(
    transport: Annotated[
        str, typer.Option("--transport", help="stdio (default) or sse.")
    ] = "stdio",
    port: Annotated[int, typer.Option("--port", help="SSE port.")] = 8000,
    host: Annotated[str, typer.Option("--host", help="SSE bind host.")] = "127.0.0.1",
    token: Annotated[
        str | None, typer.Option("--token", help="Bearer token (REQUIRED for sse).")
    ] = None,
) -> None:
    """Launch the metalworks MCP server.

    ``stdio`` is the keyless default. ``sse`` is network-exposed and REQUIRES a
    bearer token (``--token`` or METALWORKS_MCP_TOKEN) — it refuses to start
    without one.
    """
    from metalworks.errors import MetalworksError
    from metalworks.mcp import server as mcp_server

    try:
        mcp_server.serve(transport=transport, host=host, port=port, token=token)
    except MetalworksError as exc:
        err_console.print(f"[red]{exc.message}[/red]")
        if exc.fix:
            err_console.print(f"[dim]{exc.fix}[/dim]")
        raise typer.Exit(code=1) from exc


# ── Shared helpers ──────────────────────────────────────────────────────────

_EXTRA_PROBES: tuple[tuple[str, str], ...] = (
    ("anthropic", "anthropic"),
    ("openai", "openai"),
    ("google", "google.genai"),
    ("reddit", "redditwarp"),
    ("arctic", "duckdb"),
    ("exa", "exa_py"),
    ("tavily", "tavily"),
    ("mcp", "mcp"),
)

_KEY_PROBES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("anthropic", ("ANTHROPIC_API_KEY",)),
    ("openai", ("OPENAI_API_KEY",)),
    ("google", ("GOOGLE_API_KEY", "GEMINI_API_KEY")),
    ("exa", ("EXA_API_KEY",)),
    ("tavily", ("TAVILY_API_KEY",)),
    ("reddit", ("REDDIT_CLIENT_ID",)),
)

_SECRET_KEYS = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "EXA_API_KEY",
        "TAVILY_API_KEY",
        "REDDIT_CLIENT_ID",
        "REDDIT_CLIENT_SECRET",
        "METALWORKS_FERNET_KEY",
        "METALWORKS_MCP_TOKEN",
    }
)


def _module_available(module: str) -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _resolve_chat_or_exit() -> ChatModel:
    from metalworks.errors import MetalworksError

    try:
        return config.resolve_chat()
    except MetalworksError as exc:
        err_console.print(f"[red]{exc.message}[/red]")
        if exc.fix:
            err_console.print(f"[dim]{exc.fix}[/dim]")
        raise typer.Exit(code=1) from exc


def _resolve_embeddings_or_exit() -> EmbeddingProvider:
    """Resolve embeddings, or exit cleanly with guidance (never a raw traceback).

    The research pipeline needs an embeddings provider. With no Google/OpenAI key
    it falls back to the local fastembed model; this surfaces any resolution error
    (e.g. the model's extra missing) as a one-line message + fix, not a stack trace.
    """
    from metalworks.errors import MetalworksError

    try:
        return config.resolve_embeddings()
    except MetalworksError as exc:
        err_console.print(f"[red]{exc.message}[/red]")
        if exc.fix:
            err_console.print(f"[dim]{exc.fix}[/dim]")
        raise typer.Exit(code=1) from exc


def _print_verdict(verdict: object) -> None:
    pass_ = getattr(verdict, "pass_", False)
    violations = getattr(verdict, "violations", [])
    confidence = getattr(verdict, "confidence", 0.0)
    color = "green" if pass_ else "red"
    console.print(
        f"compliance: [{color}]{'PASS' if pass_ else 'FAIL'}[/{color}] "
        f"(confidence {confidence:.2f})"
    )
    if violations:
        for v in violations:
            console.print(f"  - {v}")


def _print_report(report: object) -> None:
    query = getattr(report, "query", "")
    total = getattr(report, "total_threads", 0)
    partial = getattr(report, "partial", False)
    clusters = getattr(report, "ranked_clusters", [])
    console.print(f"\n[bold]Report[/bold] — {query}")
    console.print(f"  threads: {total}   partial: {partial}")
    caveat = getattr(report, "caveat", None)
    if caveat:
        console.print(f"  [yellow]caveat:[/yellow] {caveat}")
    if clusters:
        console.print("  [bold]top clusters:[/bold]")
        for c in clusters[:5]:
            console.print(f"    - {getattr(c, 'claim', c)}")


# ── Discovery ───────────────────────────────────────────────────────────────

discovery_app = typer.Typer(help="Find and draft Reddit reply opportunities.", no_args_is_help=True)


@discovery_app.command("run")
def discovery_run(
    query: Annotated[list[str], typer.Option("--query", "-q", help="Search query (repeatable).")],
    subreddit: Annotated[
        list[str] | None, typer.Option("--subreddit", help="Restrict to these subs (repeatable).")
    ] = None,
    max_opportunities: Annotated[
        int, typer.Option("--max", help="Stop after this many opportunities.")
    ] = 10,
    voice: Annotated[
        str | None, typer.Option("--voice", help="Voice guideline for drafts.")
    ] = None,
) -> None:
    """Search Reddit, draft replies, and gate each through the compliance check.

    Produces draft opportunities only. It never posts. Review the drafts, then
    post a chosen one with `metalworks reddit post <url> --text ...`.
    """
    from metalworks.contract import DiscoveryContext
    from metalworks.discovery import DiscoveryDeps, run_discovery
    from metalworks.reddit import RedditSearch

    chat = config.resolve_chat()
    store = config.default_store()
    deps = DiscoveryDeps(
        chat=chat,
        search=RedditSearch(),
        opportunities=store,
        context=DiscoveryContext(voice_guidelines=[voice] if voice else []),
    )
    opportunities = run_discovery(
        deps, queries=query, subreddits=subreddit, max_opportunities=max_opportunities
    )
    if not opportunities:
        console.print("[dim]No opportunities found.[/dim]")
        return
    for opp in opportunities:
        gate = opp.compliance
        mark = "[green]pass[/green]" if (gate and gate.pass_) else "[yellow]review[/yellow]"
        console.print(f"\n[bold]{opp.post.subreddit}[/bold] {mark}  {opp.post.url}")
        console.print(f"  {opp.post.title}")
        console.print(f"  [dim]draft:[/dim] {opp.draft_reply[:240]}")
    console.print(
        f"\n[dim]{len(opportunities)} draft(s). Nothing was posted. "
        "Post a chosen one with: metalworks reddit post <url> --text ...[/dim]"
    )


# ── Register sub-apps ───────────────────────────────────────────────────────

reddit_app.add_typer(subreddit_app, name="subreddit")
reddit_app.add_typer(auth_app, name="auth")

app.add_typer(research_app, name="research")
app.add_typer(build_app, name="build")
app.add_typer(reddit_app, name="reddit")
app.add_typer(arctic_app, name="arctic")
app.add_typer(discovery_app, name="discovery")
app.add_typer(config_app, name="config")
app.add_typer(models_app, name="models")
app.add_typer(sources_app, name="sources")
app.add_typer(corpus_app, name="corpus")
app.add_typer(mcp_app, name="mcp")


__all__ = ["app"]
