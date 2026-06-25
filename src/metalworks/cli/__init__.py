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
from metalworks import config, preflight

if TYPE_CHECKING:
    from metalworks.contract import DemandReport
    from metalworks.contract.assess import Decision
    from metalworks.contract.ideate import IdeaSketch
    from metalworks.embeddings import EmbeddingProvider
    from metalworks.llm import ChatModel
    from metalworks.research.deps import ResearchDeps
    from metalworks.research.sources import SourceSpec
    from metalworks.research.validate import ResearchFn, ValidationStep
    from metalworks.stores.repos import RunRepo

app = typer.Typer(
    name="metalworks",
    help="Marketing research and Reddit engagement toolkit.",
)
console = Console()
err_console = Console(stderr=True)


@app.callback(invoke_without_command=True)
def main_callback(ctx: typer.Context) -> None:
    """Marketing research and Reddit engagement toolkit.

    Run with no command for an interactive menu (validate an idea, configure models /
    sources, run diagnostics, browse runs), or call any sub-command directly
    (`metalworks --help`). `metalworks start` jumps straight to validating an idea.
    """
    if ctx.invoked_subcommand is None:
        _main_menu()


# Sub-apps registered at the bottom of the module.
research_app = typer.Typer(help="Plan and run demand-research reports.", no_args_is_help=True)
reddit_app = typer.Typer(help="Search Reddit, fetch intel, post (gated).", no_args_is_help=True)
arctic_app = typer.Typer(help="Read the Arctic Shift historical corpus.", no_args_is_help=True)
config_app = typer.Typer(help="Read and write non-secret config.", no_args_is_help=False)
models_app = typer.Typer(
    help="Inspect and set the chat/fast/embedding model and provider reachability.",
    no_args_is_help=False,
)
mcp_app = typer.Typer(help="Run the metalworks MCP server.", no_args_is_help=True)
sources_app = typer.Typer(
    help="List, enable, and disable the data sources research ingests from.",
    no_args_is_help=False,
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

# Force one model on every surface (CLI + MCP + SDK), beating key/Vertex
# autodetection. A ref is provider/id or provider:id; an unknown vendor → OpenRouter:
# METALWORKS_MODEL=deepseek/deepseek-v4-flash

# Vertex gotcha: if your shell exports GOOGLE_GENAI_USE_VERTEXAI=true (e.g. inherited)
# but you don't have the [google] extra, chat AND embeddings route to a missing Vertex
# SDK and fail. Turn it off for metalworks, or install metalworks[google]:
# GOOGLE_GENAI_USE_VERTEXAI=false

# Reddit data reader (default: the live Arctic Shift API, keyless — no 429s):
# ARCTIC_SHIFT_SOURCE=api  # api (default) | hf (HF Parquet, needs HF_TOKEN) | mirror
# HF_TOKEN=                # only for ARCTIC_SHIFT_SOURCE=hf (clears the anonymous 429)

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

    Delegates to :func:`metalworks.preflight.doctor_hints` — the single source of
    truth shared with the machine-readable ``preflight()`` report, so the report
    and the repair path can never drift.
    """
    from metalworks.preflight import doctor_hints

    return doctor_hints()


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


def _renderer_status() -> tuple[str, str]:
    """Which renderer tier the next render/teardown would use — without launching one.

    Delegates to :func:`metalworks.preflight.renderer_status` (the shared source of
    truth). Returns ``(tier, human_detail)``: ``playwright`` / ``firecrawl`` /
    ``none``.
    """
    from metalworks.preflight import renderer_status

    return renderer_status()


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
    # Single source of truth: the doctor report is a pretty-printer over the same
    # `preflight()` the SDK / MCP / banner read (plus a few CLI-only sections).
    report = preflight.preflight(check_update=True)

    console.print(f"[bold]metalworks {report.version}[/bold]")
    if report.update is not None and report.update.update_available:
        u = report.update
        console.print(
            f"[yellow]update available[/yellow]: {u.installed} → {u.latest}  "
            "[dim](pip install -U metalworks)[/dim]"
        )

    console.print("\n[bold]Optional extras[/bold]")
    for extra, _module in _EXTRA_PROBES:
        present = report.extras.get(extra, False)
        mark = "[green]installed[/green]" if present else "[dim]not installed[/dim]"
        console.print(f"  {extra:<10} {mark}")

    console.print("\n[bold]API keys (from environment)[/bold]")
    for label, env_vars in _KEY_PROBES:
        found = next((v for v in env_vars if os.environ.get(v)), None)
        status = f"[green]set[/green] ({found})" if found else "[dim]unset[/dim]"
        console.print(f"  {label:<14} {status}")

    console.print("\n[bold]Resolved models[/bold]")
    chat_cell = (
        f"[green]{report.resolved_chat}[/green]"
        if report.resolved_chat
        else "[yellow]unresolved[/yellow]"
    )
    emb_cell = (
        f"[green]{report.resolved_embeddings}[/green]"
        if report.resolved_embeddings
        else "[yellow]unresolved[/yellow]"
    )
    console.print(f"  {'chat':<10} {chat_cell}")
    console.print(f"  {'embedding':<10} {emb_cell}")

    console.print("\n[bold]Corpus reader[/bold]")
    reader_note = f" [dim]({report.reader_detail})[/dim]" if report.reader_detail else ""
    console.print(f"  [green]{report.active_reader}[/green]{reader_note}")

    store_path = config.setting("store") or str(Path.home() / ".metalworks" / "store.db")
    console.print("\n[bold]Store[/bold]")
    console.print(f"  path  {store_path}")

    console.print("\n[bold]Renderer[/bold]")
    tier, detail = _renderer_status()
    color = {"playwright": "green", "firecrawl": "yellow", "none": "dim"}[tier]
    console.print(f"  [{color}]{detail}[/{color}]")
    if tier == "playwright":
        console.print("  [dim]verify: metalworks render https://example.com -o /tmp/shot.png[/dim]")

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

    _doctor_sources_section()

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


@app.command(name="preflight")
def preflight_cmd(
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit the PreflightReport as JSON (for machines)."),
    ] = False,
) -> None:
    """Proactive preflight: is everything set up + is there an update?

    Reuses the same checks ``doctor`` runs (extras / keys / resolved models /
    corpus reader / renderer / hints) plus a cached, offline-safe PyPI update
    check, in one machine-readable :class:`~metalworks.contract.PreflightReport`.
    Pass ``--json`` for the raw report; the skills' preamble runs this first.
    """
    report = preflight.preflight(check_update=True)
    if as_json:
        console.print_json(report.model_dump_json())
        return

    console.print(f"[bold]metalworks {report.version}[/bold]")
    if report.update is not None and report.update.update_available:
        u = report.update
        console.print(
            f"[yellow]update available[/yellow]: {u.installed} → {u.latest}  "
            "[dim](pip install -U metalworks)[/dim]"
        )
    console.print(f"corpus reader  [green]{report.active_reader}[/green]")
    chat_cell = (
        f"[green]{report.resolved_chat}[/green]"
        if report.resolved_chat
        else "[yellow]unresolved[/yellow]"
    )
    console.print(f"chat model     {chat_cell}")
    if report.issues:
        console.print("\n[bold]Issues[/bold]")
        for issue in report.issues:
            color = "red" if issue.severity == "error" else "yellow"
            console.print(f"  [{color}]•[/{color}] {issue.message}")
    else:
        console.print("\n[green]all set[/green]")
    if not report.ok:
        console.print(
            "\n[dim]Some checks need attention — run `metalworks doctor` for the full report.[/dim]"
        )


# The proactive one-line banner — see `_emit_preflight_banner`. Marker files live
# under ~/.metalworks/ so the guard is session-once and survives a process exit.
_BANNER_GUARD = "preflight-banner-shown"
_BANNER_TTL_SECONDS = 6 * 60 * 60  # don't repeat the banner more than ~4x/day


def _banner_disabled() -> bool:
    value = config.setting("preflight_banner")
    return value is not None and value.strip().lower() in ("false", "0", "no", "off")


def _banner_guard_path() -> Path:
    return Path.home() / ".metalworks" / _BANNER_GUARD


def _banner_recently_shown() -> bool:
    """True when the banner fired within the TTL — the session-once guard."""
    import time

    try:
        ts = float(_banner_guard_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return (time.time() - ts) < _BANNER_TTL_SECONDS


def _mark_banner_shown() -> None:
    import time

    try:
        path = _banner_guard_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(int(time.time())), encoding="utf-8")
    except OSError:
        pass


def _emit_preflight_banner() -> None:
    """Print a ONE-LINE stderr banner before heavy work — silent when healthy.

    Cached (the update check uses its ~24h cache; the local probes are cheap),
    session-once (a ~/.metalworks/ timestamp guard), gated by ``preflight_banner``
    (default on), and NON-BLOCKING: every failure path is swallowed and it never
    changes the exit code or stops the command.
    """
    try:
        if _banner_disabled() or _banner_recently_shown():
            return
        report = preflight.preflight(check_update=True)
        parts: list[str] = []
        issue_count = len(report.issues)
        if issue_count:
            parts.append(f"{issue_count} setup issue(s)")
        if report.update is not None and report.update.update_available:
            u = report.update
            parts.append(f"update {u.installed}→{u.latest} available")
        # Always set the guard so we don't recompute every command this session.
        _mark_banner_shown()
        if not parts:
            return  # silent when healthy
        err_console.print(
            f"[yellow]⚠ metalworks:[/yellow] {' · '.join(parts)} — run 'metalworks doctor'"
        )
    except Exception:
        # Non-blocking by contract: a banner failure must never break the command.
        return


def _doctor_sources_section() -> None:
    """Print the registered sources with lane/auth and a computed key-status.

    Reads ``SOURCE_SPECS`` (after triggering the built-in imports) — the same
    spec-driven view ``sources list`` renders, condensed for the doctor report.
    Keyless sources show ``reachable``; an authed source shows whether one of its
    env vars is set so the operator knows what's missing at a glance.
    """
    from metalworks.research.sources import SOURCE_SPECS

    _discover_sources()  # trigger built-in self-registration so specs populate
    enabled = set(config.enabled_source_ids())
    console.print("\n[bold]Sources[/bold]")
    if not SOURCE_SPECS:
        console.print("  [dim]no registered sources[/dim]")
        return
    for sid in sorted(SOURCE_SPECS):
        spec = SOURCE_SPECS[sid]
        on = "[green]on[/green]" if sid in enabled else "[dim]off[/dim]"
        if spec.auth == "none":
            status = "[green]keyless[/green]"
        elif _source_reachable(spec):
            status = "[green]key set[/green]"
        elif spec.env:
            status = f"[yellow]needs key[/yellow] ({spec.env[0]})"
        else:
            status = "[yellow]needs key[/yellow]"
        console.print(f"  {sid:<20} {on:<22} [dim]{spec.lane}/{spec.auth}[/dim]  {status}")


@app.command()
def render(
    url: Annotated[str, typer.Argument(help="Page URL to render (http(s):// or file://).")],
    out: Annotated[
        Path,
        typer.Option("--out", "-o", help="Write the screenshot PNG to this path."),
    ] = Path("screenshot.png"),
) -> None:
    """Render a URL to a screenshot — a quick check that the browser renderer works.

    Uses the resolved renderer (Playwright when installed, else Firecrawl when
    ``FIRECRAWL_API_KEY`` is set). This is a debug / verification command for the
    rendering infrastructure, not a pillar — the design pillar consumes the same
    renderer internally.
    """
    from metalworks.errors import MetalworksError

    renderer = config.resolve_renderer()
    if renderer is None:
        err_console.print("[red]No renderer available.[/red]")
        err_console.print(
            "[dim]Install the browser (metalworks browser install) or set FIRECRAWL_API_KEY.[/dim]"
        )
        raise typer.Exit(code=1)
    try:
        page = renderer.render(url)
    except MetalworksError as exc:
        err_console.print(f"[red]{exc.message}[/red]")
        if exc.fix:
            err_console.print(f"[dim]{exc.fix}[/dim]")
        raise typer.Exit(code=1) from exc
    out.write_bytes(page.screenshot)
    console.print(
        f"[green]Rendered[/green] {page.final_url} via [bold]{renderer.renderer_id}[/bold] "
        f"→ {out} ({len(page.screenshot)} bytes)"
    )


browser_app = typer.Typer(
    help="Manage the owned headless browser (Chromium) used for rendering.",
    no_args_is_help=True,
)


@browser_app.command("install")
def browser_install(
    with_deps: Annotated[
        bool,
        typer.Option(
            "--with-deps",
            help="Also install the OS system libraries Chromium needs (Linux; may need sudo).",
        ),
    ] = False,
) -> None:
    """Download Chromium for the browser renderer — the post-install step for the browser extra.

    Runs ``python -m playwright install chromium`` in this interpreter (so it
    works regardless of how the ``playwright`` script is on PATH). ``--with-deps``
    also installs the Linux system libraries Chromium needs to launch, which fixes
    the most common "installed but won't launch" failure on servers and CI.
    """
    import subprocess
    import sys

    if not _module_available("playwright"):
        err_console.print("[red]The browser extra is not installed.[/red]")
        err_console.print('pip install "metalworks[browser]"', style="dim", markup=False)
        raise typer.Exit(code=1)
    cmd = [sys.executable, "-m", "playwright", "install"]
    if with_deps:
        cmd.append("--with-deps")
    cmd.append("chromium")
    console.print(f"[bold]Installing Chromium[/bold] [dim]({' '.join(cmd)})[/dim]")
    # Fixed argv, no shell, no user-controlled input — just the playwright installer.
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        err_console.print("[red]Chromium install failed.[/red] See the output above.")
        raise typer.Exit(code=result.returncode)
    console.print("[green]Ready.[/green] The browser renderer can now launch Chromium.")


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
    console.print(
        "\nNext: set a provider key in your shell (or METALWORKS_MODEL), then "
        "`metalworks preflight`."
    )


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
    from metalworks.research.sources import SOURCE_SPECS

    current = config.enabled_source_ids()
    discovered = _discover_sources()
    console.print("\n[bold]Data sources[/bold]")
    for sid in sorted({*discovered, *current}):
        spec = SOURCE_SPECS.get(sid)
        on = "[green]enabled[/green]" if sid in current else "[dim]available[/dim]"
        if spec is None:
            note, reach = "not registered", " [yellow](no connector)[/yellow]"
        else:
            note = f"{spec.lane} · {spec.auth}"
            reach = "" if _source_reachable(spec) else " [yellow](needs key)[/yellow]"
        console.print(f"  {sid:<14} {on}  [dim]{note}[/dim]{reach}")
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


# ── guided session ───────────────────────────────────────────────────────────


@app.command()
def start() -> None:
    """Guided session: idea → demand → landscape → verdict, then build next-steps.

    The same flow you get by running bare `metalworks`. Walks you through one idea
    end to end with the GO/PIVOT/NO-GO call in your hands at each round, and offers
    positioning / scaffold once an idea earns a GO.
    """
    _guided_session()


def _next_steps_menu(report_id: str) -> None:
    """After a GO, dispatch to the build pillars (reusing the existing commands)."""
    import contextlib

    actions: list[tuple[str, Any]] = [
        ("Draft positioning", lambda: research_position(report_id=report_id)),
        ("Scaffold build harness", lambda: build_init(report=report_id)),
        ("Done", None),
    ]
    while True:
        console.print("\n[bold]What next?[/bold]")
        for i, (label, _action) in enumerate(actions, start=1):
            console.print(f"  [bold]{i}[/bold]) {label}")
        choice = str(typer.prompt("  Pick", default=str(len(actions)))).strip()
        idx = int(choice) - 1 if choice.isdigit() else len(actions) - 1
        if not 0 <= idx < len(actions):
            idx = len(actions) - 1
        action = actions[idx][1]
        if action is None:
            break
        # A pillar may exit with its own guidance (e.g. missing key); stay in the menu.
        with contextlib.suppress(typer.Exit):
            action()


def _guided_session() -> None:
    """The guided flow behind bare `metalworks` and `metalworks start`."""
    from metalworks.project import Project

    console.print("[bold]metalworks[/bold] — let's validate an idea.")
    console.print("[dim]type 'metalworks --help' for the full command list.[/dim]")

    # 1. Preflight. A chat key (or Vertex ADC) is required; a project is optional.
    if not _present_providers() and not config.vertex_enabled():
        console.print("\n[yellow]No provider key found in the environment.[/yellow]")
        console.print(
            "  Set one, e.g.:  [bold]export OPENAI_API_KEY=…[/bold]  "
            "(or ANTHROPIC_API_KEY / GOOGLE_API_KEY / OPENROUTER_API_KEY), then run me again."
        )
        return
    no_project = Project.find() is None
    if no_project and typer.confirm("\nNo project here yet — set one up?", default=True):
        project = Project.init(Path.cwd())
        console.print(f"  [green]Created[/green] .metalworks/ (project '{project.slug}')")

    # 2. The idea.
    idea = str(typer.prompt("\nWhat's your idea?", default="")).strip()
    if not idea:
        console.print("[dim]No idea entered — nothing to do.[/dim]")
        return

    # 3. The interactive validate loop (you make the GO/PIVOT/NO-GO call each round).
    from metalworks.research import validate as run_validate
    from metalworks.research.deps import ResearchDeps

    chat = _resolve_chat_or_exit()
    store = config.default_store()
    reader = config.resolve_corpus_reader()
    deps = ResearchDeps(
        chat=chat,
        embeddings=_resolve_embeddings_or_exit(),
        corpus=store,
        reader=reader,
        search=config.resolve_search(),
    )
    console.print(f"\n[bold]Running demand research[/bold] for: {idea}")
    try:
        result = run_validate(
            deps,
            idea,
            decide=_interactive_decide,
            research_fn=_saving_research(store),
            max_iterations=4,
        )
    finally:
        reader.close()
    _print_validation(result)

    # 4. After a GO, carry momentum into the build pillars.
    if result.outcome == "go":
        rid = _resolve_report_id(
            store, result.final_assessment.report_id if result.final_assessment else None
        )
        _next_steps_menu(rid)
    else:
        console.print(
            "\n[dim]Not a GO this round — refine the idea and run `metalworks` again.[/dim]"
        )


# ── interactive menus (the whole CLI, not just setup) ────────────────────────


def _menu(title: str, options: list[str], *, default_last: bool = True) -> int:
    """Print a numbered menu and return the 0-based choice. Blank/invalid input picks
    the last option (Back/Quit) when ``default_last``, else the first."""
    console.print(f"\n[bold]{title}[/bold]")
    for i, label in enumerate(options, start=1):
        console.print(f"  [bold]{i}[/bold]) {label}")
    fallback = len(options) - 1 if default_last else 0
    choice = str(typer.prompt("  Pick", default=str(fallback + 1))).strip()
    if choice.isdigit() and 1 <= int(choice) <= len(options):
        return int(choice) - 1
    return fallback


def _models_menu() -> None:
    """Interactive model config — reachable with no project or idea."""
    import contextlib

    while True:
        models_list()
        idx = _menu("Models", ["Set chat model", "Set fast model", "Warm embeddings", "Back"])
        if idx == 0:
            ref = str(typer.prompt("  Chat model ref (e.g. openai/gpt-5)", default="")).strip()
            if ref:
                _set_model_setting("model", ref)
        elif idx == 1:
            ref = str(typer.prompt("  Fast model ref (e.g. openai/gpt-5-mini)", default="")).strip()
            if ref:
                _set_model_setting("fast_model", ref)
        elif idx == 2:
            with contextlib.suppress(typer.Exit):
                models_warm()
        else:
            return


def _sources_menu() -> None:
    """Interactive data-source toggling — reachable with no project or idea."""
    import contextlib

    while True:
        sources_list()
        enabled = set(config.enabled_source_ids())
        ids = sorted({*_discover_sources(), *enabled})
        options = [f"{'[green]on[/green] ' if s in enabled else 'off'} {s}" for s in ids] + ["Back"]
        idx = _menu("Toggle a source", options)
        if idx >= len(ids):
            return
        sid = ids[idx]
        with contextlib.suppress(typer.Exit):
            _edit_enabled(sid, enable=sid not in enabled)


def _config_menu() -> None:
    """Interactive non-secret config — reachable with no project or idea."""
    import contextlib

    while True:
        config_list()
        idx = _menu("Config", ["Set a value", "Back"])
        if idx != 0:
            return
        key = str(typer.prompt("  Key (e.g. provider, model, store)", default="")).strip()
        if not key:
            continue
        value = str(typer.prompt(f"  Value for {key}", default="")).strip()
        if value:
            with contextlib.suppress(typer.Exit):
                config_set(key, value)


def _runs_menu() -> None:
    """Browse stored runs and act on one — no idea entry required."""
    import contextlib

    store = config.default_store()
    runs = store.list_runs(limit=20)
    if not runs:
        console.print(
            "\n[dim]No runs yet — validate an idea or run `metalworks research run`.[/dim]"
        )
        return
    labels: list[str] = []
    for r in runs:
        meta = f"{r.report_id[:8]}, {r.total_distinct_authors or 0} authors"
        labels.append(f"{(r.query or '')[:48]} [dim]({meta})[/dim]")
    labels.append("Back")
    idx = _menu("Past runs — pick one", labels)
    if idx >= len(runs):
        return
    rid = runs[idx].report_id
    actions: list[tuple[str, Any]] = [
        ("Assess (GO / PIVOT / NO-GO)", lambda: research_assess(report_id=rid)),
        ("Landscape", lambda: research_landscape(report_id=rid)),
        ("Positioning", lambda: research_position(report_id=rid)),
        ("Scaffold build harness", lambda: build_init(report=rid)),
        ("Back", None),
    ]
    a = _menu(f"Run {rid[:8]} — what next?", [label for label, _ in actions])
    fn = actions[a][1]
    if fn is not None:
        with contextlib.suppress(typer.Exit):
            fn()


def _main_menu() -> None:
    """The top-level interactive menu behind bare ``metalworks`` — validate is just one
    choice. Config / models / sources / doctor are reachable with no project or idea."""
    import contextlib

    console.print("[bold]metalworks[/bold] — what do you want to do?")
    console.print("[dim]type 'metalworks --help' for the full command list.[/dim]")
    options = [
        "Validate an idea (demand → landscape → verdict)",
        "Configure models",
        "Configure data sources",
        "View / edit config",
        "Check setup (doctor)",
        "Run onboarding (setup)",
        "Browse past runs",
        "Quit",
    ]
    handlers: list[Any] = [
        _guided_session,
        _models_menu,
        _sources_menu,
        _config_menu,
        lambda: doctor(fix=False),
        setup,
        _runs_menu,
        None,
    ]
    while True:
        idx = _menu("What do you want to do?", options)
        handler = handlers[idx]
        if handler is None:
            return
        with contextlib.suppress(typer.Exit, KeyboardInterrupt):
            handler()


@models_app.callback(invoke_without_command=True)
def models_root(ctx: typer.Context) -> None:
    """Inspect and set models. Run with no sub-command for an interactive menu."""
    if ctx.invoked_subcommand is None:
        _models_menu()


@sources_app.callback(invoke_without_command=True)
def sources_root(ctx: typer.Context) -> None:
    """List and toggle data sources. Run with no sub-command for an interactive menu."""
    if ctx.invoked_subcommand is None:
        _sources_menu()


@config_app.callback(invoke_without_command=True)
def config_root(ctx: typer.Context) -> None:
    """Read and write non-secret config. Run with no sub-command for an interactive menu."""
    if ctx.invoked_subcommand is None:
        _config_menu()


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

# Provider/key/extra probe matrices are the shared source of truth in
# `metalworks.preflight` (so `doctor`, `preflight()`, and `models list` all read
# the same rows). Re-exported here under the CLI's historical names.
_PROVIDER_MATRIX = preflight.PROVIDER_MATRIX


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


# Connector modules whose import self-registers a source AND lands its
# ``SourceSpec`` in ``SOURCE_SPECS`` (the same map the gen script + spec test
# use). Importing — not constructing — is enough: ``register_source(..., spec=)``
# runs at module scope, so a freshly-imported CLI sees every built-in's metadata
# without needing live readers/keys. The catalog (`sources list`, scaffold-row
# hints, `doctor`) reads ``SOURCE_SPECS`` — never a hand-kept reachability dict.
def _discover_sources() -> list[str]:
    """All known source ids: the registry, plus the built-ins that self-register
    on import. Triggers those imports (best-effort) so a freshly-imported CLI sees
    Reddit/Arctic and every other built-in spec, then any third-party connector
    already registered in-process.

    The module list derives from the single :data:`BUILTIN_SOURCE_MODULES` source
    of truth — a new connector is registered there, not in a CLI-local list.
    """
    import contextlib
    import importlib

    from metalworks.research.sources import SOURCES, builtin_connector_modules

    for module in builtin_connector_modules():
        # Best-effort: a connector module may need an extra that isn't installed.
        with contextlib.suppress(Exception):
            importlib.import_module(module)
    return sorted(SOURCES)


def _source_reachable(spec: SourceSpec) -> bool:
    """A spec is reachable iff its auth requirement is satisfiable right now.

    Keyless sources (``auth == "none"``) are always reachable. An authed source is
    reachable when at least one of its declared ``env`` vars is set — exactly the
    "is the key present?" check the catalog renders. (Extras/import probing stays
    out of the lane: the spec, not a per-id module map, is the source of truth.)
    """
    if spec.auth == "none":
        return True
    return any(os.environ.get(var) for var in spec.env)


def _wide_console() -> Console:
    """A Console wide enough to render the 8-column sources table un-truncated.

    The default console follows the terminal width (80 in CI / captured tests),
    which ellipsizes source ids and env names in the spec'd view. A fixed minimum
    width keeps every cell legible while still honoring a wider real terminal.
    """
    try:
        terminal_width = console.size.width
    except Exception:
        terminal_width = 0
    return Console(width=max(terminal_width, 120))


@sources_app.command("list")
def sources_list(
    lane: Annotated[
        str | None,
        typer.Option("--lane", help="Only show sources on this lane (grounding/web)."),
    ] = None,
    needs_key: Annotated[
        bool,
        typer.Option("--needs-key", help="Only show sources that require a key (auth != none)."),
    ] = False,
) -> None:
    """Show registered data sources, their lane/auth/env, and whether they're reachable.

    Read-only, driven entirely by each source's ``SourceSpec`` (lane, auth,
    access, env, relevance hint). ``reachable`` is a computed column: keyless
    sources are always reachable; an authed source is reachable when one of its
    env vars is set. ``--lane`` and ``--needs-key`` filter the rows.
    """
    from metalworks.research.sources import SOURCE_SPECS

    enabled = config.enabled_source_ids()
    discovered = _discover_sources()
    # Show every id that is registered or named in config (so a configured but
    # not-yet-importable source still appears, flagged unreachable / specless).
    ids = sorted({*discovered, *enabled})

    console.print("[bold]Data sources[/bold]")
    table = Table(show_header=True, header_style="bold")
    table.add_column("source")
    table.add_column("lane")
    table.add_column("auth")
    table.add_column("access")
    table.add_column("env")
    table.add_column("enabled")
    table.add_column("reachable")
    table.add_column("relevance hint")
    shown = 0
    for sid in ids:
        spec = SOURCE_SPECS.get(sid)
        if spec is None:
            # Configured but not registered (no spec) — surface it as unreachable.
            if lane is not None or needs_key:
                continue
            en = "[green]on[/green]" if sid in enabled else "[dim]off[/dim]"
            table.add_row(
                sid, "[dim]?[/dim]", "[dim]?[/dim]", "[dim]?[/dim]", "—", en, "[dim]no[/dim]", ""
            )
            shown += 1
            continue
        if lane is not None and spec.lane != lane:
            continue
        if needs_key and spec.auth == "none":
            continue
        reachable = _source_reachable(spec)
        env_cell = ", ".join(spec.env) if spec.env else "[dim]—[/dim]"
        en_cell = "[green]on[/green]" if sid in enabled else "[dim]off[/dim]"
        if reachable:
            reach_cell = "[green]yes[/green]"
        elif spec.auth != "none" and spec.env:
            reach_cell = f"[yellow]needs key[/yellow] ({spec.env[0]})"
        else:
            reach_cell = "[dim]no[/dim]"
        table.add_row(
            sid,
            spec.lane,
            spec.auth,
            spec.access,
            env_cell,
            en_cell,
            reach_cell,
            spec.relevance_hint,
        )
        shown += 1
    # Render wide so the env / hint columns aren't ellipsized in a narrow terminal
    # (the spec'd 8-column view doesn't fit 80 cols, and a truncated source id is
    # actively misleading). A non-tty (piped) console honors the width verbatim.
    _wide_console().print(table)
    if shown == 0:
        console.print("[dim](no sources match the filter)[/dim]")
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


@sources_app.command("scaffold")
def sources_scaffold(
    source_id: Annotated[
        str, typer.Argument(help="New source id (lowercase identifier, e.g. discourse).")
    ],
    lane: Annotated[
        str,
        typer.Option("--lane", help="Lane this source serves: grounding | web."),
    ] = "grounding",
    auth: Annotated[
        str,
        typer.Option("--auth", help="Auth it needs: none | key | oauth | paid."),
    ] = "none",
    out_dir: Annotated[
        Path | None,
        typer.Option(
            "--out-dir",
            help="Directory for the connector + test (default: src/metalworks/research/sources/).",
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite the connector/test files if they already exist."),
    ] = False,
) -> None:
    """Scaffold a new source connector: a fill-in-the-bodies ``ItemSource``.

    Emits a connector module (filled ``SourceSpec`` + ``register_signal`` block,
    only ``pull`` / ``comments_for`` left to write) and a conformance test, then
    PRINTS the ``pyproject.toml`` extra snippet and the ``docs/sources.md`` row
    (never auto-edited — the catalog is regenerated by ``scripts/gen_sources_md.py``).
    Adding a source is then a fill-in job, not a 7-step edit across 6 files.
    """
    from typing import cast

    from metalworks.research.sources.scaffold import (
        ScaffoldPlan,
        render_connector,
        render_docs_row,
        render_pyproject_extra,
        render_test,
    )
    from metalworks.research.sources.spec import Lane

    if lane not in ("grounding", "web"):
        err_console.print(f"[red]--lane must be 'grounding' or 'web', got {lane!r}.[/red]")
        raise typer.Exit(code=2)
    if auth not in ("none", "key", "oauth", "paid"):
        err_console.print(f"[red]--auth must be none | key | oauth | paid, got {auth!r}.[/red]")
        raise typer.Exit(code=2)

    try:
        plan = ScaffoldPlan.build(source_id, lane=cast("Lane", lane), auth=auth)
    except ValueError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from exc

    pkg_dir = Path(__file__).resolve().parents[1] / "research" / "sources"
    target_dir = out_dir if out_dir is not None else pkg_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    connector_path = target_dir / f"{plan.source_id}.py"
    test_dir = Path("tests")
    test_path = test_dir / f"test_source_{plan.source_id}.py"

    # The dotted import path the test uses. In-tree (default) → the package path;
    # a custom --out-dir → import by file stem (the caller wires their own path).
    if out_dir is None:
        module_path = f"metalworks.research.sources.{plan.source_id}"
    else:
        module_path = plan.source_id

    for path in (connector_path, test_path):
        if path.exists() and not force:
            err_console.print(
                f"[red]{path} already exists.[/red] Re-run with [bold]--force[/bold] to overwrite."
            )
            raise typer.Exit(code=1)

    connector_path.write_text(render_connector(plan))
    test_dir.mkdir(parents=True, exist_ok=True)
    test_path.write_text(render_test(plan, module_path=module_path))

    console.print(f"[green]Wrote[/green] connector  [dim]{connector_path}[/dim]")
    console.print(f"[green]Wrote[/green] test       [dim]{test_path}[/dim]")

    console.print("\n[bold]Add this extra to pyproject.toml[/bold] [dim](not auto-edited)[/dim]")
    console.print(f"[dim]{render_pyproject_extra(plan)}[/dim]")

    console.print(
        "\n[bold]docs/sources.md row[/bold] "
        "[dim](informational — run scripts/gen_sources_md.py to regenerate)[/dim]"
    )
    console.print(f"[dim]{render_docs_row(plan)}[/dim]")

    console.print(
        f"\n[bold]Next[/bold]: fill in [cyan]{plan.class_name}.pull[/cyan] / "
        f"[cyan].comments_for[/cyan], then run "
        f"[cyan]metalworks sources list[/cyan] and the new conformance test."
    )


# ── corpus sub-app ──────────────────────────────────────────────────────────


def _arctic_source_kwargs() -> dict[str, Any]:
    """Build the kwargs the Arctic (reddit) connector needs: a reader + live
    comment client. Other (keyless) connectors ignore these — ``resolve_sources``
    only passes the kwargs a factory accepts.
    """
    from metalworks.research.arctic import ArcticShiftApiClient

    return {
        "reader": config.resolve_corpus_reader(),
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


@research_app.command("plan", rich_help_panel="Core flow")
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
    reader = config.resolve_corpus_reader()
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


@research_app.command("run", rich_help_panel="Core flow")
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
    model: Annotated[
        str | None,
        typer.Option(
            "--model",
            "-m",
            help="Chat model override, e.g. 'deepseek/deepseek-v4-flash' (routes via "
            "OpenRouter) or 'openai/gpt-5'. Beats config/env autodetection. Or set "
            "METALWORKS_MODEL to apply it to every command.",
        ),
    ] = None,
) -> None:
    """Run the research pipeline from a --question (no brief.json needed) or a --brief file."""
    _emit_preflight_banner()
    from metalworks.contract import ResearchBrief, RunSummary
    from metalworks.research import run_research
    from metalworks.research.arctic import ArcticShiftApiClient
    from metalworks.research.deps import ResearchDeps
    from metalworks.research.planner import brief_from_question

    if (question is None) == (brief is None):
        err_console.print("[red]Pass exactly one of --question or --brief.[/red]")
        raise typer.Exit(code=2)

    chat = _resolve_chat_or_exit(model)
    embeddings = _resolve_embeddings_or_exit()
    store = config.default_store()
    reader = config.resolve_corpus_reader()
    comments = ArcticShiftApiClient()
    # --source overrides the run's connectors (override wins over the selector);
    # without it deps.sources stays None so the brief-aware selector picks by idea
    # (default ON — #167), degrading to the Reddit floor when there's no chat model.
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


@research_app.command("resume", rich_help_panel="Core flow")
def research_resume(
    run_id: Annotated[str, typer.Argument(help="The run id to resume (a prior research run).")],
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write the report JSON here.")
    ] = None,
) -> None:
    """Resume a prior run from its last incomplete stage (reuses checkpoints)."""
    _emit_preflight_banner()
    from metalworks.contract import RunSummary
    from metalworks.research import run_research
    from metalworks.research.arctic import ArcticShiftApiClient
    from metalworks.research.deps import ResearchDeps

    store = config.default_store()
    run = store.get_run(run_id)
    if run is None:
        err_console.print(
            f"[red]No run {run_id}.[/red] Run `metalworks research list` to see run ids."
        )
        raise typer.Exit(code=1)
    if run.status == "complete":
        done = store.get_report(run_id)
        if done is not None:
            console.print(f"[green]Run already complete[/green] {run_id}")
            _print_report(done)
            return
    brief = store.get_brief(run.brief_id) if run.brief_id else None
    if brief is None:
        err_console.print(
            f"[red]No brief stored for run {run_id}; cannot resume.[/red] "
            "Start a fresh run with `metalworks research run`."
        )
        raise typer.Exit(code=1)

    chat = _resolve_chat_or_exit()
    embeddings = _resolve_embeddings_or_exit()
    reader = config.resolve_corpus_reader()
    comments = ArcticShiftApiClient()
    deps = ResearchDeps(
        chat=chat,
        embeddings=embeddings,
        corpus=store,
        reader=reader,
        search=config.resolve_search(),
        comments=comments,
    )
    console.print(f"[bold]Resuming research[/bold] {run_id}: {brief.question}")
    try:
        report = run_research(deps, brief=brief, run_id=run_id, checkpoints=store)
    finally:
        reader.close()

    store.save_report(report)
    store.save_run(RunSummary.from_report(report, question=brief.question))
    if out is not None:
        out.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        console.print(f"[green]Wrote report[/green] {out}")
    _print_report(report)


@research_app.command("status", rich_help_panel="History")
def research_status(
    run_id: Annotated[str, typer.Argument(help="The run id to inspect.")],
) -> None:
    """Show a run's status + fine-grained stage progress (stage N/total · updated)."""
    store = config.default_store()
    run = store.get_run(run_id)
    if run is None:
        err_console.print(f"[red]No run {run_id}.[/red]")
        raise typer.Exit(code=1)
    line = f"[bold]{run.status}[/bold]"
    if run.stage is not None:
        idx = run.stage_index if run.stage_index is not None else "?"
        total = run.stage_total if run.stage_total is not None else "?"
        line += f" · stage {idx}/{total}: {run.stage}"
    if run.updated_at is not None:
        line += f" · updated {run.updated_at.strftime('%Y-%m-%d %H:%M:%S')}"
    console.print(line)
    if run.error:
        err_console.print(f"[red]{run.error}[/red]")
        console.print(f"[dim]Resume with[/dim] [bold]metalworks research resume {run_id}[/bold]")


@research_app.command("list", rich_help_panel="History")
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


@research_app.command("refresh", rich_help_panel="History")
def research_refresh(
    report_id: Annotated[
        str | None,
        typer.Argument(help="Report id/prefix in the lineage; defaults to your latest run."),
    ] = None,
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write the new report JSON here.")
    ] = None,
) -> None:
    """Re-synthesize a stored report against the current corpus → a new pinned version + diff."""
    _emit_preflight_banner()
    from metalworks.contract import DemandReport, RunSummary
    from metalworks.research.arctic import ArcticShiftApiClient
    from metalworks.research.deps import ResearchDeps
    from metalworks.research.refresh import refresh_report

    store = config.default_store()
    report_id = _resolve_report_id(store, report_id)
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
    reader = config.resolve_corpus_reader()
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


@research_app.command("versions", rich_help_panel="History")
def research_versions(
    report_id: Annotated[
        str | None,
        typer.Argument(help="Report id/prefix in the lineage; defaults to your latest run."),
    ] = None,
) -> None:
    """List the versions in a report's lineage, oldest → newest."""
    from metalworks.contract import RunSummary

    store = config.default_store()
    report_id = _resolve_report_id(store, report_id)
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


@research_app.command("diff", rich_help_panel="History")
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


@research_app.command("position", rich_help_panel="Pillars & build")
def research_position(
    report_id: Annotated[
        str | None,
        typer.Argument(help="Report id or prefix; defaults to your latest run."),
    ] = None,
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write the positioning brief JSON here.")
    ] = None,
) -> None:
    """Derive a grounded positioning wedge from a stored report (one LLM call)."""
    _emit_preflight_banner()
    from metalworks.research.deps import ResearchDeps
    from metalworks.research.synthesis import build_positioning_brief

    chat = _resolve_chat_or_exit()
    store = config.default_store()
    report_id = _resolve_report_id(store, report_id)
    report = store.get_report(report_id)
    if report is None:
        err_console.print(
            f"[red]No report {report_id!r} in the local store.[/red] "
            "Run `metalworks research run` first, or check the id."
        )
        raise typer.Exit(code=1)
    reader = config.resolve_corpus_reader()
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
        tags = getattr(c, "addresses_clusters", [])
        tag_str = f" [dim](clusters {', '.join(map(str, tags))})[/dim]" if tags else ""
        console.print(f"  [bold]{c.name}[/bold] ({c.kind}) — {c.one_liner}{tag_str}")
        for g in c.gaps:
            console.print(f"    [red]gap[/red] [{g.severity}]: {g.claim}")


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


@research_app.command("landscape", rich_help_panel="Core flow")
def research_landscape(
    report_id: Annotated[
        str | None,
        typer.Argument(help="Report id or prefix; defaults to your latest run."),
    ] = None,
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write the landscape JSON here.")
    ] = None,
) -> None:
    """Map the full landscape: competitors + existing solutions + cost of doing nothing."""
    _emit_preflight_banner()
    from metalworks.research import run_landscape
    from metalworks.research.deps import ResearchDeps

    chat = _resolve_chat_or_exit()
    store = config.default_store()
    report_id = _resolve_report_id(store, report_id)
    report = store.get_report(report_id)
    if report is None:
        err_console.print(
            f"[red]No report {report_id!r} in the local store.[/red] "
            "Run `metalworks research run` first, or check the id."
        )
        raise typer.Exit(code=1)
    reader = config.resolve_corpus_reader()
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


@research_app.command("ideate", rich_help_panel="Core flow")
def research_ideate(
    idea: Annotated[str | None, typer.Argument(help="A raw idea to sharpen (idea-first).")] = None,
    from_report: Annotated[
        str | None,
        typer.Option("--from-report", help="Surface ideas from a stored report's forks."),
    ] = None,
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write the result JSON here.")
    ] = None,
    model: Annotated[
        str | None,
        typer.Option(
            "--model",
            "-m",
            help="Chat model override, e.g. 'deepseek/deepseek-v4-flash' (routes via "
            "OpenRouter) or 'openai/gpt-5'. Beats config/env autodetection. Or set "
            "METALWORKS_MODEL to apply it to every command.",
        ),
    ] = None,
) -> None:
    """Frame an idea to test — idea-first (sharpen a pitch) or evidence-first (--from-report)."""
    _emit_preflight_banner()
    if not idea and not from_report:
        err_console.print("[red]Provide an idea, or --from-report <report_id>.[/red]")
        raise typer.Exit(code=1)
    from metalworks.research import ideate_from_idea, ideate_from_report
    from metalworks.research.deps import ResearchDeps

    chat = _resolve_chat_or_exit(model)
    store = config.default_store()
    reader = config.resolve_corpus_reader()
    deps = ResearchDeps(
        chat=chat,
        embeddings=_resolve_embeddings_or_exit(),
        corpus=store,
        reader=reader,
        search=config.resolve_search(),
    )
    try:
        if from_report:
            from_report = _resolve_report_id(store, from_report)
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
        line = f"  demand: {gap.demand_strength} · saturation: {gap.landscape_saturation}"
        conf = getattr(gap, "confidence", None)
        if conf is not None:
            line += f" · confidence: {conf:.0%}"
        console.print(line)
        if getattr(gap, "reference", ""):
            console.print(f"  [dim]{gap.reference}[/dim]")
    console.print(f"  {getattr(a, 'rationale', '')}")
    pt = getattr(a, "pivot_target", None)
    if pt is not None:
        console.print(f"  [bold]pivot →[/bold] {pt.kind} {pt.target_id}: {pt.why}")
    forks = getattr(a, "fork_verdicts", [])
    if forks:
        console.print("  [bold]per fork:[/bold] [dim](saturation advisory; gate is global)[/dim]")
        colors = {"go": "green", "pivot": "yellow", "no_go": "red"}
        for f in forks:
            fc = colors.get(str(f.decision), "white")
            verdict = str(f.decision).upper().replace("_", "-")
            console.print(
                f"    [{fc}]{verdict:<5}[/{fc}] {f.kind:<7} {f.label} "
                f"[dim](demand {f.demand_strength}, saturation {f.landscape_saturation}, "
                f"{f.confidence:.0%} conf)[/dim]"
            )
    if getattr(a, "partial", False):
        console.print(f"  [yellow]partial:[/yellow] {getattr(a, 'caveat', '')}")


@research_app.command("assess", rich_help_panel="Core flow")
def research_assess(
    report_id: Annotated[
        str | None,
        typer.Argument(help="Report id or prefix; defaults to your latest run."),
    ] = None,
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write the assessment JSON here.")
    ] = None,
) -> None:
    """Verdict: GO / PIVOT / NO-GO — the deterministic gap over demand + landscape."""
    _emit_preflight_banner()
    from metalworks.research import run_assessment, run_landscape
    from metalworks.research.deps import ResearchDeps

    chat = _resolve_chat_or_exit()
    store = config.default_store()
    report_id = _resolve_report_id(store, report_id)
    report = store.get_report(report_id)
    if report is None:
        err_console.print(f"[red]No report {report_id!r} in the local store.[/red]")
        raise typer.Exit(code=1)
    reader = config.resolve_corpus_reader()
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


def _prompt_decision(default: Decision) -> Decision:
    """Ask the human GO / PIVOT / NO-GO, pre-filled with the engine's recommendation.

    Accepts the number, the word, or just Enter (= the recommendation). Anything
    unrecognized falls back to the recommendation rather than erroring the loop.
    """
    from metalworks.contract.assess import Decision

    options = [Decision.GO, Decision.PIVOT, Decision.NO_GO]
    labels = {Decision.GO: "GO", Decision.PIVOT: "PIVOT", Decision.NO_GO: "NO-GO"}
    default_idx = options.index(default) + 1
    menu = "   ".join(
        f"[bold]{i}[/bold]) {labels[o]}" + (" [dim](recommended)[/dim]" if o is default else "")
        for i, o in enumerate(options, start=1)
    )
    console.print(f"  {menu}")
    choice = str(typer.prompt("  Your call", default=str(default_idx))).strip()
    if choice.isdigit() and 1 <= int(choice) <= len(options):
        return options[int(choice) - 1]
    word = choice.lower().replace("-", "_")
    for o in options:
        if word in (o.value, labels[o].lower().replace("-", "_")):
            return o
    console.print("  [yellow]Unrecognized — using the recommendation.[/yellow]")
    return default


def _interactive_decide(step: ValidationStep) -> Decision:
    """The human-gated `decide` callback: show the round's verdict, then ask."""
    console.print(f"\n[bold]Round {step.iteration}[/bold] — {step.idea}")
    _print_assessment(step.assessment)
    return _prompt_decision(step.assessment.decision)


def _saving_research(store: RunRepo) -> ResearchFn:
    """Wrap the loop's research stage so each pulled report is persisted.

    The validate loop returns only the final assessment (which references a
    report_id) and never saves — so without this the post-GO build menu and
    `_resolve_report_id(None)` would find nothing. Decorating the injectable
    research_fn keeps the loop pure while leaving the report in the store.
    """
    from metalworks.contract import RunSummary
    from metalworks.research.validate import default_research

    def _run(deps: ResearchDeps, sketch: IdeaSketch) -> DemandReport:
        report = default_research(deps, sketch)
        store.save_report(report)
        store.save_run(RunSummary.from_report(report, question=sketch.idea))
        return report

    return _run


@research_app.command("validate", rich_help_panel="Core flow")
def research_validate(
    idea: Annotated[str, typer.Argument(help="The idea to run through the validate loop.")],
    auto: Annotated[
        bool,
        typer.Option(
            "--auto/--no-auto",
            help="Auto-take the engine's recommendation each round "
            "(default: ask you at every GO/PIVOT/NO-GO gate).",
        ),
    ] = False,
    max_iterations: Annotated[
        int, typer.Option("--max-iterations", help="Loop cap before 'exhausted'.")
    ] = 4,
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write the result JSON here.")
    ] = None,
) -> None:
    """Validate loop: ideate → demand → landscape → assess, looping on PIVOT.

    Interactive by default — you make the GO/PIVOT/NO-GO call at each round (the
    engine's recommendation is the pre-filled default). Pass --auto to run it
    headlessly. Either way the final report is saved to the store.
    """
    _emit_preflight_banner()
    from metalworks.research import validate as run_validate
    from metalworks.research.deps import ResearchDeps

    chat = _resolve_chat_or_exit()
    store = config.default_store()
    reader = config.resolve_corpus_reader()
    deps = ResearchDeps(
        chat=chat,
        embeddings=_resolve_embeddings_or_exit(),
        corpus=store,
        reader=reader,
        search=config.resolve_search(),
    )
    mode = "auto loop" if auto else "interactive"
    console.print(f"[bold]Validating[/bold] '{idea}' ({mode}, ≤{max_iterations} rounds)...")
    try:
        result = run_validate(
            deps,
            idea,
            decide=None if auto else _interactive_decide,
            research_fn=_saving_research(store),
            max_iterations=max_iterations,
        )
    finally:
        reader.close()
    if out is not None:
        out.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        console.print(f"[green]Wrote result[/green] {out}")
    _print_validation(result)


@research_app.command("design", rich_help_panel="Pillars & build")
def research_design(
    report_id: Annotated[
        str | None,
        typer.Argument(help="Report id or prefix; defaults to your latest run."),
    ] = None,
    name: Annotated[
        str | None, typer.Option("--name", help="Brand name (else the model suggests one).")
    ] = None,
    taste: Annotated[
        str,
        typer.Option(
            "--taste",
            help="Design taste preset: editorial (default), brutalist, warm-minimal, technical.",
        ),
    ] = "editorial",
    out_dir: Annotated[
        Path | None,
        typer.Option("--out", "-o", help="Directory for DESIGN.md + preview.html (default: cwd)."),
    ] = None,
    max_teardown: Annotated[
        int, typer.Option("--max-teardown", help="Competitor sites to teardown (0 = all).")
    ] = 3,
) -> None:
    """Author a grounded design system from a stored report.

    Builds the landscape, then reads the competition at the richest tier available
    (a real browser teardown when ``metalworks browser install`` has been run > web
    text > model knowledge) and records the grounding tier. ``--taste`` picks the
    director preset (editorial / brutalist / warm-minimal / technical); editorial is
    the default and preserves prior output. Writes DESIGN.md + a preview.html.
    """
    from metalworks.contract.bundle import Research
    from metalworks.research import (
        TASTE_PRESETS,
        build_design_system,
        render_design_md,
        render_design_preview_html,
        run_landscape,
    )
    from metalworks.research.deps import ResearchDeps

    if taste not in TASTE_PRESETS:
        err_console.print(
            f"[red]Unknown taste {taste!r}.[/red] Choose: {', '.join(TASTE_PRESETS)}."
        )
        raise typer.Exit(code=1)
    chat = _resolve_chat_or_exit()
    store = config.default_store()
    report_id = _resolve_report_id(store, report_id)
    report = store.get_report(report_id)
    if report is None:
        err_console.print(f"[red]No report {report_id!r} in the local store.[/red]")
        raise typer.Exit(code=1)
    reader = config.resolve_corpus_reader()
    deps = ResearchDeps(
        chat=chat, embeddings=_resolve_embeddings_or_exit(), corpus=store, reader=reader
    )
    console.print(f"[bold]Designing[/bold] for report {report_id}...")
    try:
        try:
            landscape = run_landscape(deps, report)
        except Exception:  # landscape is best-effort; design degrades honestly without it
            landscape = None
        research = Research(demand=report, landscape=landscape)
        system = build_design_system(
            deps, research, brand_name=name, taste=taste, max_teardown=max_teardown
        )
    finally:
        reader.close()

    tier_color = {"renderer": "green", "web": "yellow"}.get(system.grounding_tier, "yellow")
    console.print(f"  taste: [bold]{system.taste}[/bold]")
    console.print(f"  grounding: [{tier_color}]{system.grounding_tier}[/{tier_color}]")
    if system.partial and system.caveat:
        console.print(f"  [yellow]caveat:[/yellow] {system.caveat}")
    console.print(f"  [bold]{system.brand_name}[/bold] — {system.aesthetic}")
    for choice in system.choices:
        stance_color = "red" if choice.stance == "risk" else "dim"
        console.print(
            f"  {choice.dimension:<11} [{stance_color}]{choice.stance}[/{stance_color}]: "
            f"{choice.decision}"
        )
    dest = out_dir or Path()
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "DESIGN.md").write_text(render_design_md(system), encoding="utf-8")
    (dest / "preview.html").write_text(render_design_preview_html(system), encoding="utf-8")
    console.print(f"[green]Wrote[/green] {dest}/DESIGN.md + {dest}/preview.html")


@research_app.command("logo", rich_help_panel="Pillars & build")
def research_logo(
    report_id: Annotated[
        str | None,
        typer.Argument(help="Report id or prefix; defaults to your latest run."),
    ] = None,
    name: Annotated[
        str | None, typer.Option("--name", help="Brand name (else the model suggests one).")
    ] = None,
    taste: Annotated[
        str,
        typer.Option(
            "--taste",
            help="Design taste preset the mark draws under: editorial (default), brutalist, "
            "warm-minimal, technical.",
        ),
    ] = "editorial",
    out_dir: Annotated[
        Path | None,
        typer.Option("--out", "-o", help="Directory for the SVGs + picker.html (default: cwd)."),
    ] = None,
    count: Annotated[
        int, typer.Option("--count", "-n", help="How many logo options (design angles).")
    ] = 5,
) -> None:
    """Generate diverse logo options for a stored report, drawn under its design system.

    Builds the brand's design system (under ``--taste``), then authors N diverse
    marks under it (one per design angle). Writes each SVG + a `picker.html`. Options
    are offered, never auto-selected; an unsafe or empty SVG is dropped, never faked.
    """
    from metalworks.research import (
        TASTE_PRESETS,
        build_design_system,
        build_logo_set,
        render_logo_picker_html,
    )
    from metalworks.research.deps import ResearchDeps

    if taste not in TASTE_PRESETS:
        err_console.print(
            f"[red]Unknown taste {taste!r}.[/red] Choose: {', '.join(TASTE_PRESETS)}."
        )
        raise typer.Exit(code=1)
    chat = _resolve_chat_or_exit()
    store = config.default_store()
    report_id = _resolve_report_id(store, report_id)
    report = store.get_report(report_id)
    if report is None:
        err_console.print(f"[red]No report {report_id!r} in the local store.[/red]")
        raise typer.Exit(code=1)
    reader = config.resolve_corpus_reader()
    deps = ResearchDeps(
        chat=chat, embeddings=_resolve_embeddings_or_exit(), corpus=store, reader=reader
    )
    console.print(f"[bold]Designing logos[/bold] for report {report_id}...")
    try:
        system = build_design_system(deps, report, brand_name=name, taste=taste)
        logos = build_logo_set(chat, system, n=count)
    finally:
        reader.close()
    if logos.partial and logos.caveat:
        console.print(f"  [yellow]partial:[/yellow] {logos.caveat}")
    dest = out_dir or Path()
    dest.mkdir(parents=True, exist_ok=True)
    for i, opt in enumerate(logos.options, 1):
        (dest / f"{i}_{opt.angle}.svg").write_text(opt.svg, encoding="utf-8")
        console.print(f"  [bold]{i}. {opt.angle}[/bold] — {opt.concept}")
    (dest / "picker.html").write_text(
        render_logo_picker_html(logos, taste=system.taste), encoding="utf-8"
    )
    console.print(f"[green]Wrote[/green] {len(logos.options)} SVGs + {dest}/picker.html")


@research_app.command("design-review", rich_help_panel="Pillars & build")
def research_design_review(
    url: Annotated[str, typer.Argument(help="The page URL to audit (http(s):// or file://).")],
    report_id: Annotated[
        str | None,
        typer.Option("--report", help="Also grade against this report's design system."),
    ] = None,
    json_out: Annotated[
        Path | None, typer.Option("--json", help="Write the DesignReview JSON here.")
    ] = None,
) -> None:
    """Audit a rendered page's computed styles against design hard-rules (deterministic).

    Reads the page's ACTUAL fonts / heading scale / colors and flags hard-rule
    violations; with ``--report`` it also grades them against that report's design
    system. Needs the browser renderer (``metalworks browser install``) — a
    screenshot-only backend can't read computed styles.
    """
    from metalworks.errors import MetalworksError, StyleAuditUnsupported
    from metalworks.research import build_design_system, review_design

    renderer = config.resolve_renderer()
    if renderer is None:
        err_console.print("[red]No renderer available.[/red]")
        err_console.print("[dim]metalworks browser install[/dim]")
        raise typer.Exit(code=1)
    if not renderer.capabilities.supports_style_audit:
        err_console.print(
            f"[red]The '{renderer.renderer_id}' renderer is screenshot-only — "
            "design review needs the browser.[/red]"
        )
        err_console.print("[dim]metalworks browser install[/dim]")
        raise typer.Exit(code=1)

    system = None
    if report_id is not None:
        from metalworks.research.deps import ResearchDeps

        chat = _resolve_chat_or_exit()
        store = config.default_store()
        report_id = _resolve_report_id(store, report_id)
        report = store.get_report(report_id)
        if report is None:
            err_console.print(f"[red]No report {report_id!r} in the local store.[/red]")
            raise typer.Exit(code=1)
        reader = config.resolve_corpus_reader()
        deps = ResearchDeps(
            chat=chat, embeddings=_resolve_embeddings_or_exit(), corpus=store, reader=reader
        )
        try:
            system = build_design_system(deps, report)
        finally:
            reader.close()

    console.print(f"[bold]Reviewing[/bold] {url}...")
    try:
        review = review_design(renderer, url, system=system)
    except (MetalworksError, StyleAuditUnsupported) as exc:
        err_console.print(f"[red]{exc.message}[/red]")
        if exc.fix:
            err_console.print(f"[dim]{exc.fix}[/dim]")
        raise typer.Exit(code=1) from exc

    color = "green" if review.passed else "yellow"
    console.print(
        f"  score: [{color}]{review.score}/10[/{color}]  ({'pass' if review.passed else 'review'})"
    )
    console.print(f"  fonts: {', '.join(review.fonts) or '—'}")
    for finding in review.findings:
        sev_color = {"fail": "red", "warn": "yellow", "ok": "green"}[finding.severity]
        console.print(
            f"  [{sev_color}]{finding.severity}[/{sev_color}] [{finding.category}] {finding.detail}"
        )
    if json_out is not None:
        json_out.write_text(review.model_dump_json(indent=2), encoding="utf-8")
        console.print(f"[green]Wrote[/green] {json_out}")


# ── build sub-app ────────────────────────────────────────────────────────────

build_app = typer.Typer(
    help="Scaffold an evidence-grounded build harness from a report.", no_args_is_help=True
)


def _load_report_for_build(report: str | None):
    """Resolve a report id/prefix, a report.json path, or the latest run into a DemandReport."""
    from metalworks.contract import DemandReport

    if report:
        candidate = Path(report)
        if candidate.exists() and candidate.suffix == ".json":
            return DemandReport.model_validate_json(candidate.read_text(encoding="utf-8"))
    store = config.default_store()
    report_id = _resolve_report_id(store, report)
    stored = store.get_report(report_id)
    if stored is None:  # run row exists but the report blob is missing — defensive
        err_console.print(f"[red]No report {report_id!r} in the local store.[/red]")
        raise typer.Exit(code=1)
    return stored


@build_app.command("init")
def build_init(
    report: Annotated[
        str | None,
        typer.Argument(help="Report id/prefix or report.json path; defaults to latest run."),
    ] = None,
    dest: Annotated[
        Path, typer.Option("--dest", "-d", help="Directory to scaffold the build harness into.")
    ] = Path("./build"),
    surface: Annotated[
        str,
        typer.Option(
            "--surface",
            help="Target surface, or 'auto' to let the spec pick + explain: auto | web | mobile | "
            "cli | api | sdk | browser_extension | desktop.",
        ),
    ] = "auto",
    base: Annotated[
        str, typer.Option("--base", help="Stack hint recorded in the spec (e.g. next-shipfast).")
    ] = "empty",
) -> None:
    """Derive a grounded BuildSpec and scaffold a cite-or-die build harness (no product code)."""
    _emit_preflight_banner()
    from typing import Literal, cast, get_args

    from metalworks.build import build_spec_from_report, scaffold
    from metalworks.contract.surface import SurfaceKind
    from metalworks.research.deps import ResearchDeps
    from metalworks.research.synthesis import build_positioning_brief

    valid_surfaces = get_args(SurfaceKind)
    if surface != "auto" and surface not in valid_surfaces:
        err_console.print(
            f"[red]Unknown surface {surface!r}.[/red] "
            f"Choose 'auto' or one of: {', '.join(valid_surfaces)}."
        )
        raise typer.Exit(code=1)

    report_obj = _load_report_for_build(report)
    chat = _resolve_chat_or_exit()
    reader = config.resolve_corpus_reader()
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
            deps,
            report_obj,
            positioning,
            cast("SurfaceKind | Literal['auto']", surface),
            stack=base,
        )
    finally:
        reader.close()
    if spec.surface_rationale:
        console.print(f"  [dim]surface:[/dim] {spec.surface} — {spec.surface_rationale}")
    if spec.partial:
        console.print(f"  [yellow]partial:[/yellow] {spec.caveat}")
    written = scaffold(spec, report_obj, dest, base=base)
    console.print(
        f"[green]Scaffolded {len(written)} files[/green] into {dest} "
        f"({len(spec.features)} features, {len(spec.personas)} personas, "
        f"{len(spec.pricing_tiers)} tiers, {len(spec.screens)} screens)."
    )
    for path in written:
        console.print(f"  [dim]{path}[/dim]")
    console.print(
        "\nOpen the harness in your coding agent and run [bold]/scaffold-startup[/bold]. "
        "metalworks specced it; you build it."
    )


# ── distribution sub-app (D2: channel strategy) ──────────────────────────────


distribution_app = typer.Typer(
    help="Channel strategy: route the report's signals into test→focus channel experiments.",
    no_args_is_help=True,
)


def _print_channel_strategy(strategy: object) -> None:
    console.print(
        f"\n[bold]Channel strategy[/bold] — report {getattr(strategy, 'report_id', '')} "
        f"([dim]{getattr(strategy, 'product_type', '')}[/dim])"
    )
    console.print(f"  [italic]{getattr(strategy, 'icp_summary', '')}[/italic]")
    for ch in getattr(strategy, "channels", []):
        spark = f" [dim]← spark: {ch.spark_channel}[/dim]" if ch.requires_spark else ""
        console.print(f"\n  [bold]{ch.name}[/bold] ({ch.surface_type}, {ch.funnel_stage}){spark}")
        console.print(f"    [dim]signal:[/dim] {ch.routing_signal}")
        console.print(f"    [dim]test:[/dim] {ch.test}")
        console.print(f"    [dim]pass when:[/dim] {ch.success_threshold}")
    console.print(f"\n  [bold]focus:[/bold] {getattr(strategy, 'focusing_rule', '')}")
    console.print(f"  [bold]funnel:[/bold] {getattr(strategy, 'funnel_note', '')}")


@distribution_app.command("strategy")
def distribution_strategy(
    report_id: Annotated[
        str | None,
        typer.Argument(help="Report id or prefix; defaults to your latest run."),
    ] = None,
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write the channel strategy JSON here.")
    ] = None,
) -> None:
    """Route a stored report's named entities + signals into test→focus channel experiments."""
    _emit_preflight_banner()
    from metalworks.research import build_channel_strategy
    from metalworks.research.deps import ResearchDeps

    chat = _resolve_chat_or_exit()
    store = config.default_store()
    report_id = _resolve_report_id(store, report_id)
    report = store.get_report(report_id)
    if report is None:
        err_console.print(
            f"[red]No report {report_id!r} in the local store.[/red] "
            "Run `metalworks research run` first, or check the id."
        )
        raise typer.Exit(code=1)
    reader = config.resolve_corpus_reader()
    deps = ResearchDeps(
        chat=chat, embeddings=_resolve_embeddings_or_exit(), corpus=store, reader=reader
    )
    console.print(f"[bold]Channel strategy[/bold] report {report_id}...")
    try:
        strategy = build_channel_strategy(deps, report)
    finally:
        reader.close()
    if out is not None:
        out.write_text(strategy.model_dump_json(indent=2), encoding="utf-8")
        console.print(f"[green]Wrote strategy[/green] {out}")
    _print_channel_strategy(strategy)


def _print_channel_assets(assets: list[object]) -> None:
    if not assets:
        console.print("[yellow]No assets drafted.[/yellow]")
        return
    for a in assets:
        console.print(
            f"\n[bold]{getattr(a, 'channel_name', '')}[/bold] "
            f"([dim]{getattr(a, 'surface_type', '')}, {getattr(a, 'funnel_stage', '')}[/dim])"
        )
        for part in getattr(a, "parts", []):
            console.print(f"  [dim]{part.role}:[/dim] {part.text}")
        offer = getattr(a, "offer", "")
        if offer:
            console.print(f"  [bold]offer:[/bold] {offer}")
        cites = getattr(a, "claim_citations", [])
        console.print(f"  [dim]grounded demand claims:[/dim] {len(cites)}")


@distribution_app.command("assets")
def distribution_assets(
    report_id: Annotated[
        str | None,
        typer.Argument(help="Report id or prefix; defaults to your latest run."),
    ] = None,
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write the channel assets JSON here.")
    ] = None,
) -> None:
    """Draft channel-SHAPED, drafting-only distribution assets per channel (DRAFTING ONLY)."""
    _emit_preflight_banner()
    from metalworks.research import build_channel_assets, build_channel_strategy
    from metalworks.research.deps import ResearchDeps

    chat = _resolve_chat_or_exit()
    store = config.default_store()
    report_id = _resolve_report_id(store, report_id)
    report = store.get_report(report_id)
    if report is None:
        err_console.print(
            f"[red]No report {report_id!r} in the local store.[/red] "
            "Run `metalworks research run` first, or check the id."
        )
        raise typer.Exit(code=1)
    reader = config.resolve_corpus_reader()
    deps = ResearchDeps(
        chat=chat, embeddings=_resolve_embeddings_or_exit(), corpus=store, reader=reader
    )
    console.print(f"[bold]Distribution assets[/bold] report {report_id}...")
    try:
        strategy = build_channel_strategy(deps, report)
        assets = build_channel_assets(deps, report, strategy.channels)
    finally:
        reader.close()
    if out is not None:
        import json

        payload = [a.model_dump(mode="json") for a in assets]
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        console.print(f"[green]Wrote {len(assets)} assets[/green] {out}")
    _print_channel_assets(list(assets))


def _print_data_report(asset: object) -> None:
    console.print(
        f"\n[bold]{getattr(asset, 'title', '')}[/bold] "
        f"([dim]{getattr(asset, 'kind', '')} · report {getattr(asset, 'report_id', '')}[/dim])"
    )
    for item in getattr(asset, "items", []):
        console.print(
            f"\n  [bold]{item.rank}. {item.label}[/bold] "
            f"[dim]({item.distinct_authors} authors, {item.mentions} mentions)[/dim]"
        )
        if item.quote:
            console.print(f'    [italic]"{item.quote}"[/italic]')
        for link in item.permalinks[:3]:
            console.print(f"    [dim]{link}[/dim]")
    console.print(f"\n  [dim]{getattr(asset, 'methodology', '')}[/dim]")


@distribution_app.command("data-report")
def distribution_data_report(
    report_id: Annotated[
        str | None,
        typer.Argument(help="Report id or prefix; defaults to your latest run."),
    ] = None,
    kind: Annotated[
        str,
        typer.Option(
            "--kind",
            help="Framing: complaint_index | feature_ranking | state_of.",
        ),
    ] = "complaint_index",
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write the data report JSON here.")
    ] = None,
) -> None:
    """Project a stored report into a corpus-derived data report — a deterministic ranking
    of its clusters with REAL counts, real permalinks, and a verbatim quote per row."""
    _emit_preflight_banner()
    from metalworks.research import build_data_asset
    from metalworks.research.deps import ResearchDeps

    allowed = ("complaint_index", "feature_ranking", "state_of")
    if kind not in allowed:
        err_console.print(
            f"[red]Unknown --kind {kind!r}.[/red] Expected one of: {', '.join(allowed)}."
        )
        raise typer.Exit(code=1)
    chat = _resolve_chat_or_exit()
    store = config.default_store()
    report_id = _resolve_report_id(store, report_id)
    report = store.get_report(report_id)
    if report is None:
        err_console.print(
            f"[red]No report {report_id!r} in the local store.[/red] "
            "Run `metalworks research run` first, or check the id."
        )
        raise typer.Exit(code=1)
    reader = config.resolve_corpus_reader()
    deps = ResearchDeps(
        chat=chat, embeddings=_resolve_embeddings_or_exit(), corpus=store, reader=reader
    )
    console.print(f"[bold]Data report[/bold] ({kind}) report {report_id}...")
    try:
        asset = build_data_asset(deps, report, kind)
    finally:
        reader.close()
    if out is not None:
        out.write_text(asset.model_dump_json(indent=2), encoding="utf-8")
        console.print(f"[green]Wrote data report[/green] {out}")
    _print_data_report(asset)


def _print_geo_plan(plan: object) -> None:
    console.print(f"\n[bold]GEO / LLM-citability[/bold] — report {getattr(plan, 'report_id', '')}")
    targets = getattr(plan, "participation_targets", [])
    console.print(f"\n  [bold]Participation targets[/bold] ({len(targets)})")
    for t in targets:
        console.print(f"    [bold]{t.community}[/bold] — {t.permalink}")
        console.print(f"      [dim]why:[/dim] {t.why}")
        console.print(f"      [dim]angle:[/dim] {t.suggested_angle}")
    probes = getattr(plan, "citability_probes", [])
    console.print(f"\n  [bold]Citability probes[/bold] ({len(probes)})")
    for p in probes:
        console.print(f'    "{p.prompt}"')
        console.print(f"      [dim]maps to:[/dim] {p.target_phrase}")
    briefs = getattr(plan, "answer_briefs", [])
    console.print(f"\n  [bold]Answer briefs[/bold] ({len(briefs)})")
    for b in briefs:
        anchors = ", ".join(f"{k}={v}" for k, v in b.stat_anchors.items())
        console.print(f"    [bold]Q:[/bold] {b.question}  [dim]({anchors})[/dim]")
        console.print(f"      {b.answer}")
        console.print(f"      [dim]cites:[/dim] {len(b.evidence_refs)} evidence ref(s)")


@distribution_app.command("geo")
def distribution_geo(
    report_id: Annotated[
        str | None,
        typer.Argument(help="Report id or prefix; defaults to your latest run."),
    ] = None,
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write the GEO plan JSON here.")
    ] = None,
) -> None:
    """GEO / LLM-citability: participation targets, citability probes, answer-first briefs."""
    _emit_preflight_banner()
    from metalworks.research import build_geo_plan
    from metalworks.research.deps import ResearchDeps

    chat = _resolve_chat_or_exit()
    store = config.default_store()
    report_id = _resolve_report_id(store, report_id)
    report = store.get_report(report_id)
    if report is None:
        err_console.print(
            f"[red]No report {report_id!r} in the local store.[/red] "
            "Run `metalworks research run` first, or check the id."
        )
        raise typer.Exit(code=1)
    reader = config.resolve_corpus_reader()
    deps = ResearchDeps(
        chat=chat, embeddings=_resolve_embeddings_or_exit(), corpus=store, reader=reader
    )
    console.print(f"[bold]GEO / LLM-citability[/bold] report {report_id}...")
    try:
        plan = build_geo_plan(deps, report)
    finally:
        reader.close()
    if out is not None:
        out.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        console.print(f"[green]Wrote GEO plan[/green] {out}")
    _print_geo_plan(plan)


def _print_participation_reply(reply: object) -> None:
    community = getattr(reply, "community", "")
    permalink = getattr(reply, "permalink", "")
    console.print(f"\n[bold]Participation reply[/bold] — [bold]{community}[/bold] {permalink}")
    compliance = getattr(reply, "compliance", None)
    passed = bool(getattr(compliance, "pass_", False))
    label = "[green]PASS[/green]" if passed else "[red]FAIL[/red]"
    violations = list(getattr(compliance, "violations", []) or [])
    console.print(f"  [dim]compliance:[/dim] {label}" + (f"  {violations}" if violations else ""))
    console.print("  [dim](drafting only — a human posts via `metalworks reddit post`)[/dim]\n")
    console.print(getattr(reply, "draft", ""))


@distribution_app.command("engage")
def distribution_engage(
    report_id: Annotated[
        str | None,
        typer.Argument(help="Report id or prefix; defaults to your latest run."),
    ] = None,
    permalink: Annotated[
        str | None,
        typer.Option("--permalink", "-p", help="The target thread's permalink (from geo)."),
    ] = None,
    why: Annotated[
        str | None,
        typer.Option("--why", help="What the audience is asking there (the target's why)."),
    ] = None,
    community: Annotated[
        str, typer.Option("--community", "-c", help="The target's community, e.g. r/SideProject.")
    ] = "",
    angle: Annotated[
        str, typer.Option("--angle", help="The honest, value-first angle to take.")
    ] = "",
    voice: Annotated[
        str | None, typer.Option("--voice", help="A voice guideline for the reply.")
    ] = None,
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write the participation reply JSON here.")
    ] = None,
) -> None:
    """Participation/execution arm (D9): draft a DISCLOSED, compliance-gated reply for one
    GEO participation target (a real thread). DRAFTING ONLY — a human posts it (gated)."""
    _emit_preflight_banner()
    from metalworks.contract import ParticipationTarget
    from metalworks.research import participation_reply
    from metalworks.research.deps import ResearchDeps

    if not permalink or not why:
        err_console.print(
            "[red]--permalink and --why are required.[/red] "
            "Get them from `metalworks distribution geo` (a participation target)."
        )
        raise typer.Exit(code=1)
    chat = _resolve_chat_or_exit()
    store = config.default_store()
    report_id = _resolve_report_id(store, report_id)
    report = store.get_report(report_id)
    if report is None:
        err_console.print(
            f"[red]No report {report_id!r} in the local store.[/red] "
            "Run `metalworks research run` first, or check the id."
        )
        raise typer.Exit(code=1)
    reader = config.resolve_corpus_reader()
    deps = ResearchDeps(
        chat=chat, embeddings=_resolve_embeddings_or_exit(), corpus=store, reader=reader
    )
    target = ParticipationTarget(
        community=community, permalink=permalink, why=why, suggested_angle=angle
    )
    console.print(f"[bold]Drafting participation reply[/bold] for {permalink}...")
    try:
        reply = participation_reply(deps, report, target, voice=voice)
    finally:
        reader.close()
    if out is not None:
        out.write_text(reply.model_dump_json(indent=2), encoding="utf-8")
        console.print(f"[green]Wrote participation reply[/green] {out}")
    _print_participation_reply(reply)


def _print_distribution_requirements(loops: list[object], conversion: list[object]) -> None:
    console.print("\n[bold]Distribution → build requirements[/bold] (D3)")
    if loops:
        console.print("\n  [bold]Embedded loops[/bold]")
        for lr in loops:
            reqs = ", ".join(getattr(lr, "build_requirements", []))
            console.print(f"    [bold]{getattr(lr, 'loop_kind', '')}[/bold] → {reqs}")
            console.print(f"      [dim]{getattr(lr, 'rationale', '')}[/dim]")
    else:
        console.print("\n  [dim]No embedded-loop channel selected — no loop requirements.[/dim]")
    for cr in conversion:
        reqs = ", ".join(getattr(cr, "build_requirements", []))
        console.print(f"\n  [bold]Conversion surface[/bold]: {getattr(cr, 'destination', '')}")
        console.print(f"    [dim]job:[/dim] {getattr(cr, 'funnel_job', '')}")
        console.print(f"    [dim]build:[/dim] {reqs}")
        console.print(f"    [dim]{getattr(cr, 'rationale', '')}[/dim]")


@distribution_app.command("requirements")
def distribution_requirements(
    report_id: Annotated[
        str | None,
        typer.Argument(help="Report id or prefix; defaults to your latest run."),
    ] = None,
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write the requirements JSON here.")
    ] = None,
) -> None:
    """Emit the distribution → build requirements (D3): embedded loops + the conversion surface."""
    _emit_preflight_banner()
    from metalworks.research import build_channel_strategy
    from metalworks.research import distribution_requirements as _distribution_requirements
    from metalworks.research.deps import ResearchDeps

    chat = _resolve_chat_or_exit()
    store = config.default_store()
    report_id = _resolve_report_id(store, report_id)
    report = store.get_report(report_id)
    if report is None:
        err_console.print(
            f"[red]No report {report_id!r} in the local store.[/red] "
            "Run `metalworks research run` first, or check the id."
        )
        raise typer.Exit(code=1)
    reader = config.resolve_corpus_reader()
    deps = ResearchDeps(
        chat=chat, embeddings=_resolve_embeddings_or_exit(), corpus=store, reader=reader
    )
    console.print(f"[bold]Distribution requirements[/bold] report {report_id}...")
    try:
        strategy = build_channel_strategy(deps, report)
        loops, conversion = _distribution_requirements(strategy.channels)
    finally:
        reader.close()
    if out is not None:
        import json

        payload = {
            "loop_requirements": [lr.model_dump(mode="json") for lr in loops],
            "conversion_surface_requirements": [cr.model_dump(mode="json") for cr in conversion],
        }
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        console.print(f"[green]Wrote requirements[/green] {out}")
    _print_distribution_requirements(list(loops), list(conversion))


def _print_distribution_plan(plan: object) -> None:
    console.print(
        f"\n[bold]Distribution plan[/bold] (D7) — report {getattr(plan, 'report_id', '')}"
    )
    pushes = getattr(plan, "pushes", [])
    console.print("\n  [bold]Pushes[/bold] (sequenced moments)")
    if pushes:
        for p in pushes:
            spark = f" [dim]→ sparks: {p.spark_channel}[/dim]" if p.spark_channel else ""
            console.print(f"    [bold]{p.timing}[/bold] — {p.channel_name}{spark}")
            console.print(f"      [dim]{p.action}[/dim]")
    else:
        console.print("    [dim]No spike channels — nothing to sequence into pushes.[/dim]")
    streams = getattr(plan, "streams", [])
    console.print("\n  [bold]Streams[/bold] (run continuously)")
    if streams:
        for s in streams:
            console.print(f"    [bold]{s.channel_name}[/bold] ([dim]{s.surface_type}[/dim])")
            console.print(f"      [dim]{s.cadence_note}[/dim]")
    else:
        console.print("    [dim]No compounding channels — no streams.[/dim]")


@distribution_app.command("plan")
def distribution_plan(
    report_id: Annotated[
        str | None,
        typer.Argument(help="Report id or prefix; defaults to your latest run."),
    ] = None,
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write the distribution plan JSON here.")
    ] = None,
) -> None:
    """Sequence the report's channels into pushes (moments) + streams (continuous) (D7)."""
    _emit_preflight_banner()
    from metalworks.research import build_channel_strategy, plan_distribution
    from metalworks.research.deps import ResearchDeps

    chat = _resolve_chat_or_exit()
    store = config.default_store()
    report_id = _resolve_report_id(store, report_id)
    report = store.get_report(report_id)
    if report is None:
        err_console.print(
            f"[red]No report {report_id!r} in the local store.[/red] "
            "Run `metalworks research run` first, or check the id."
        )
        raise typer.Exit(code=1)
    reader = config.resolve_corpus_reader()
    deps = ResearchDeps(
        chat=chat, embeddings=_resolve_embeddings_or_exit(), corpus=store, reader=reader
    )
    console.print(f"[bold]Distribution plan[/bold] report {report_id}...")
    try:
        strategy = build_channel_strategy(deps, report)
        plan = plan_distribution(report, strategy.channels)
    finally:
        reader.close()
    if out is not None:
        out.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        console.print(f"[green]Wrote distribution plan[/green] {out}")
    _print_distribution_plan(plan)


def _print_channel_metrics(metrics: list[Any]) -> None:
    console.print("\n[bold]Channel metrics[/bold] (D8) — wire these BEFORE the push")
    if not metrics:
        console.print("  [dim]No channels selected — nothing to instrument yet.[/dim]")
        return
    for m in metrics:
        console.print(f"\n  [bold]{m.channel_name}[/bold] ([dim]{m.surface_type}[/dim])")
        console.print(f"    success: [bold]{m.success_metric}[/bold]")
        console.print(f"    [dim]instrument: {m.instrumentation}[/dim]")


@distribution_app.command("measure")
def distribution_measure(
    report_id: Annotated[
        str | None,
        typer.Argument(help="Report id or prefix; defaults to your latest run."),
    ] = None,
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write the channel metrics JSON here.")
    ] = None,
) -> None:
    """Emit the per-channel success metric + instrumentation to wire BEFORE the push (D8)."""
    _emit_preflight_banner()
    from metalworks.research import build_channel_strategy, channel_metrics
    from metalworks.research.deps import ResearchDeps

    chat = _resolve_chat_or_exit()
    store = config.default_store()
    report_id = _resolve_report_id(store, report_id)
    report = store.get_report(report_id)
    if report is None:
        err_console.print(
            f"[red]No report {report_id!r} in the local store.[/red] "
            "Run `metalworks research run` first, or check the id."
        )
        raise typer.Exit(code=1)
    reader = config.resolve_corpus_reader()
    deps = ResearchDeps(
        chat=chat, embeddings=_resolve_embeddings_or_exit(), corpus=store, reader=reader
    )
    console.print(f"[bold]Channel metrics[/bold] report {report_id}...")
    try:
        strategy = build_channel_strategy(deps, report)
        metrics = channel_metrics(strategy.channels)
    finally:
        reader.close()
    if out is not None:
        import json

        payload = [m.model_dump(mode="json") for m in metrics]
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        console.print(f"[green]Wrote channel metrics[/green] {out}")
    _print_channel_metrics(list(metrics))


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

    _ = subreddit  # availability is corpus-wide; arg kept for symmetry/UX
    reader = config.resolve_corpus_reader()
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
    from metalworks.research.types import months_back

    sub = subreddit.strip().lstrip("r/").lstrip("/")
    reader = config.resolve_corpus_reader()
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

# The extras / keys probe matrices are the shared source of truth in
# `metalworks.preflight`; re-exported here under the CLI's historical names.
_EXTRA_PROBES = preflight.EXTRA_PROBES
_KEY_PROBES = preflight.KEY_PROBES

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
    return preflight.module_available(module)


def _resolve_report_id(store: RunRepo, report_id: str | None) -> str:
    """Resolve a report id the user may omit or abbreviate.

    With no id, returns the latest run — so the pillar commands "just work" on the
    report you ran most recently, with no copy/paste. With an id, accepts an exact
    match or a unique prefix. Exits 1 with a friendly message when there are no
    runs, nothing matches, or a prefix is ambiguous.
    """
    if report_id:
        if store.get_report(report_id) is not None:
            return report_id  # exact hit (the fast path)
        matches = [r for r in store.list_runs(limit=10_000) if r.report_id.startswith(report_id)]
        if len(matches) == 1:
            return matches[0].report_id
        if len(matches) > 1:
            err_console.print(
                f"[red]'{report_id}' is ambiguous[/red] — it matches {len(matches)} runs. "
                "Run `metalworks research list` and pass more of the id."
            )
            raise typer.Exit(code=1)
        err_console.print(
            f"[red]No report matching {report_id!r}.[/red] "
            "Run `metalworks research list` to see stored ids."
        )
        raise typer.Exit(code=1)
    runs = store.list_runs(limit=1)
    if not runs:
        err_console.print(
            "[red]No runs yet.[/red] Run [bold]metalworks start[/bold] or "
            '[bold]metalworks research run -q "…"[/bold] first.'
        )
        raise typer.Exit(code=1)
    return runs[0].report_id


def _resolve_chat_or_exit(model: str | None = None) -> ChatModel:
    """Resolve the chat model, or exit cleanly with guidance.

    ``model`` (the command's ``--model`` override, a ``provider/id`` or
    ``provider:id`` ref) wins over the config/env provider when given.
    """
    from metalworks.errors import MetalworksError

    try:
        return config.resolve_chat(model)
    except MetalworksError as exc:
        err_console.print(f"[red]{exc.message}[/red]")
        if exc.fix:
            err_console.print(f"[dim]{exc.fix}[/dim]")
        err_console.print(
            "[dim]Tip: pass --model PROVIDER/MODEL to pick a provider directly, e.g. "
            "--model deepseek/deepseek-v4-flash (with OPENROUTER_API_KEY set), or "
            "--model openai/gpt-5.[/dim]"
        )
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
app.add_typer(distribution_app, name="distribution")
app.add_typer(build_app, name="build")
app.add_typer(reddit_app, name="reddit")
app.add_typer(arctic_app, name="arctic")
app.add_typer(discovery_app, name="discovery")
app.add_typer(config_app, name="config")
app.add_typer(models_app, name="models")
app.add_typer(sources_app, name="sources")
app.add_typer(corpus_app, name="corpus")
app.add_typer(browser_app, name="browser")
app.add_typer(mcp_app, name="mcp")


__all__ = ["app"]
