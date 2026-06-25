"""Preflight — the proactive "is everything set up + is there an update" report.

This is doctor's machine-readable twin and its single source of truth: the pure
check helpers (extras / keys / resolved-models / renderer / corpus-reader /
hints) live HERE, and BOTH :func:`metalworks.preflight.preflight` and the
``metalworks doctor`` command call them, so the two can never drift.

It is pure reporting — no LLM, no verdict, no network beyond the cached update
check (and even that is opt-in via ``check_update``). ``import metalworks`` stays
free: this module imports no provider SDK at top level, and every probe is guarded
so a resolution error degrades to "unresolved" instead of crashing the report.
"""

from __future__ import annotations

import importlib.util
import os
from typing import TYPE_CHECKING, Any

from metalworks import config
from metalworks.contract import PreflightIssue, PreflightReport

if TYPE_CHECKING:
    from metalworks.contract import UpdateStatus

# Provider → (key env var(s), importable SDK/extra module) for the reachability
# matrix. OpenRouter is keyed on OPENROUTER_API_KEY and rides the OpenAI SDK.
PROVIDER_MATRIX: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("anthropic", ("ANTHROPIC_API_KEY",), "anthropic"),
    ("openai", ("OPENAI_API_KEY",), "openai"),
    ("google", ("GOOGLE_API_KEY", "GEMINI_API_KEY"), "google.genai"),
    ("openrouter", ("OPENROUTER_API_KEY",), "openai"),
)

EXTRA_PROBES: tuple[tuple[str, str], ...] = (
    ("anthropic", "anthropic"),
    ("openai", "openai"),
    ("google", "google.genai"),
    ("reddit", "redditwarp"),
    ("arctic", "duckdb"),
    ("exa", "exa_py"),
    ("tavily", "tavily"),
    ("browser", "playwright"),
    ("mcp", "mcp"),
)

KEY_PROBES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("anthropic", ("ANTHROPIC_API_KEY",)),
    ("openai", ("OPENAI_API_KEY",)),
    ("google", ("GOOGLE_API_KEY", "GEMINI_API_KEY")),
    ("exa", ("EXA_API_KEY",)),
    ("tavily", ("TAVILY_API_KEY",)),
    ("reddit", ("REDDIT_CLIENT_ID",)),
)

# Corpus-reader class name → (short id, human note). The live Arctic Shift API is
# the keyless default (see config.resolve_corpus_reader).
_READER_IDS: dict[str, tuple[str, str]] = {
    "ArcticShiftReader": ("arctic_shift_api", "live Arctic Shift posts API (keyless, default)"),
    "ArcticReader": ("hf_parquet", "Hugging Face open-index/arctic Parquet mirror ([arctic])"),
    "ArcticMirrorReader": ("supabase_mirror", "Supabase Storage mirror ([supabase])"),
}


def module_available(module: str) -> bool:
    """True when ``module`` can be imported (probed via importlib, no side effects)."""
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def resolved_model_id(resolver: Any) -> str | None:
    """Run a model resolver and return its plain model id, or ``None`` when unresolved.

    Every resolver call is guarded (it can raise ``MissingKeyError`` without a
    key), so a missing provider degrades to ``None`` instead of a traceback.
    """
    try:
        model = resolver()
    except Exception:
        return None
    model_id = getattr(model, "model_id", None) or model.__class__.__name__
    return str(model_id)


def renderer_status() -> tuple[str, str]:
    """Which renderer tier the next teardown would use — without launching one.

    Returns ``(tier, human_detail)``: ``playwright`` (full teardown + style
    audits), ``firecrawl`` (hosted, screenshot-only), or ``none`` (design falls
    back to the model's own knowledge).
    """
    from metalworks.render import chromium_present

    if module_available("playwright") and chromium_present():
        return ("playwright", "Playwright (owned Chromium) → full teardown + style audits")
    if os.environ.get("FIRECRAWL_API_KEY"):
        return ("firecrawl", "Firecrawl (hosted) → screenshot-only, no style audits")
    return ("none", "no renderer → design runs from model knowledge (no competitor teardown)")


def reader_status() -> tuple[str, str]:
    """The corpus reader a run would use right now → ``(short_id, human_detail)``.

    Maps the resolved reader class to a short id; reporting the active reader +
    endpoint is enough — no slow/blocking reachability probe runs by default.
    """
    try:
        reader = config.resolve_corpus_reader()
    except Exception as exc:  # never let a resolution error crash the report
        return ("unknown", f"could not resolve reader: {exc}")
    name = reader.__class__.__name__
    return _READER_IDS.get(name, (name, ""))


def doctor_hints() -> list[str]:
    """The actionable Hints lines (the same set doctor prints and ``--fix`` acts on).

    Pure read-only: inspects env keys and importable modules only.
    """
    # openrouter shares the openai SDK, so its missing-extra hint points at [openai].
    _extra_for = {"openrouter": "openai"}
    hints: list[str] = []
    for provider, env_vars, module in PROVIDER_MATRIX:
        found = next((v for v in env_vars if os.environ.get(v)), None)
        if found and not module_available(module):
            extra = _extra_for.get(provider, provider)
            hints.append(
                f"{found} is set but `{module}` is not installed → "
                f'pip install "metalworks[{extra}]"'
            )
    if not any(os.environ.get(v) for _, evs, _ in PROVIDER_MATRIX for v in evs):
        hints.append("No provider key found → set one (e.g. OPENAI_API_KEY) to run the pipeline.")
    if not any(os.environ.get(v) for v in ("GOOGLE_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY")):
        if module_available("fastembed"):
            hints.append(
                "No embedding key → using the local model (no key needed). "
                "Run `metalworks models warm` to pre-download it."
            )
        else:
            hints.append(
                'No embedding key and fastembed not installed → pip install "metalworks[research]" '
                "(or set GOOGLE_API_KEY / OPENAI_API_KEY)."
            )
    if module_available("playwright"):
        from metalworks.render import chromium_present

        if not chromium_present():
            hints.append(
                "Browser extra installed but Chromium is missing → metalworks browser install "
                "(or set FIRECRAWL_API_KEY to render without a local browser)."
            )
    return hints


def _hint_severity(hint: str) -> str:
    """A no-provider-key hint is an error (the pipeline can't run); the rest warn."""
    return "error" if hint.startswith("No provider key found") else "warn"


def _fix_for(hint: str) -> str:
    """Pull the copy-paste fix out of a hint line (the part after the arrow)."""
    if "→" in hint:
        return hint.split("→", 1)[1].strip()
    return ""


def preflight(*, check_update: bool = True) -> PreflightReport:
    """Build the proactive setup + update report — doctor's single source of truth.

    Reuses the pure check helpers above for extras / keys / resolved-models /
    renderer / corpus-reader / hints, then (when ``check_update`` is True) folds
    in the cached, offline-safe PyPI update check. Pure reporting: no LLM, no
    network beyond the cached update check, and every probe is guarded so this
    never raises.
    """
    import metalworks

    extras = {extra: module_available(module) for extra, module in EXTRA_PROBES}
    keys = {label: any(os.environ.get(v) for v in env_vars) for label, env_vars in KEY_PROBES}

    model_ref = config.setting("model")
    resolved_chat = resolved_model_id(lambda: config.resolve_chat(model_ref))
    resolved_embeddings = resolved_model_id(config.resolve_embeddings)

    reader_id, reader_detail = reader_status()
    renderer_tier, _renderer_detail = renderer_status()

    hints = doctor_hints()
    issues = [
        PreflightIssue(
            severity="error" if _hint_severity(h) == "error" else "warn",
            message=h,
            fix=_fix_for(h),
        )
        for h in hints
    ]
    ok = not any(i.severity == "error" for i in issues)

    update: UpdateStatus | None = None
    if check_update:
        from metalworks._update_check import check_for_update

        update = check_for_update()

    return PreflightReport(
        ok=ok,
        version=metalworks.__version__,
        update=update,
        issues=issues,
        active_reader=reader_id,
        reader_detail=reader_detail,
        resolved_chat=resolved_chat,
        resolved_embeddings=resolved_embeddings,
        extras=extras,
        keys=keys,
        renderer=renderer_tier,
    )


__all__ = ["preflight"]
