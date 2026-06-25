"""Preflight contract — the proactive "is everything set up + is there an update" report.

A :class:`PreflightReport` is the machine-readable twin of ``metalworks doctor``:
the extras / keys / resolved-models / renderer / corpus-reader status the work
needs, plus an optional :class:`UpdateStatus` from the cached PyPI check. It is
pure reporting — no LLM, no verdict, no network beyond the cached update check.

Additive-only below 1.0: every field is defaulted, so an old payload from a prior
release still validates.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class UpdateStatus(BaseModel):
    """The result of the cached PyPI update check.

    ``None`` (the field on :class:`PreflightReport`) means up-to-date or unknown
    (offline / parse error); a present ``UpdateStatus`` carries the installed and
    latest versions and whether an upgrade is available.
    """

    installed: str = Field(description="The installed metalworks version.")
    latest: str = Field(description="The latest version seen on PyPI.")
    update_available: bool = Field(
        default=False,
        description="True when ``latest`` is newer than ``installed``.",
    )


class PreflightIssue(BaseModel):
    """One actionable setup issue — a warning or error with a copy-paste fix."""

    severity: Literal["warn", "error"] = Field(
        default="warn",
        description="``error`` blocks the pipeline; ``warn`` degrades it. Preflight never "
        "changes an exit code — severity is advisory.",
    )
    message: str = Field(description="What's wrong, in one human-readable line.")
    fix: str = Field(
        default="", description="A copy-paste command or instruction that resolves it."
    )


class PreflightReport(BaseModel):
    """The proactive setup + update report — doctor's machine-readable twin.

    ``ok`` is ``True`` when there are no ``error``-severity issues (warnings don't
    flip it). ``active_reader`` names the corpus reader a run would use right now
    (``arctic_shift_api`` is the keyless live default). ``update`` is ``None`` when
    up-to-date or unknown — only a real, available upgrade populates it.
    """

    ok: bool = Field(default=True, description="True when there are no error-severity issues.")
    version: str = Field(default="", description="The installed metalworks version.")
    update: UpdateStatus | None = Field(
        default=None,
        description="The cached update check result; None when up-to-date / unknown / offline.",
    )
    issues: list[PreflightIssue] = Field(
        default_factory=list[PreflightIssue],
        description="Actionable setup issues (the same lines doctor's Hints prints).",
    )
    active_reader: str = Field(
        default="",
        description="The corpus reader a run would use: arctic_shift_api | hf_parquet | "
        "supabase_mirror.",
    )
    reader_detail: str = Field(
        default="",
        description="A short human note about the active reader (e.g. its endpoint).",
    )
    resolved_chat: str | None = Field(
        default=None,
        description="The resolved chat model id, or None when unresolved (no key / extra).",
    )
    resolved_embeddings: str | None = Field(
        default=None,
        description="The resolved embedding model id, or None when unresolved.",
    )
    extras: dict[str, bool] = Field(
        default_factory=dict[str, bool],
        description="Optional extras → installed? (the doctor 'Optional extras' table).",
    )
    keys: dict[str, bool] = Field(
        default_factory=dict[str, bool],
        description="API key labels → present in the environment? (never the value).",
    )
    renderer: str = Field(
        default="",
        description="The renderer tier a teardown would use: playwright | firecrawl | none.",
    )
