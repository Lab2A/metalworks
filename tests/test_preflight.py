"""Preflight + update-check tests — all offline (pytest-socket blocks the network).

Covers: the cached update check (hit / miss / disable / snooze / offline→None),
the ``preflight()`` report shape (incl. ``active_reader`` for each
``ARCTIC_SHIFT_SOURCE``), the contract round-trip + additive old-payload validate,
the doctor smoke + ``preflight`` CLI, the banner gate + silent-when-healthy, and
the MCP ``preflight`` tool envelope.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

import metalworks
from metalworks import _update_check
from metalworks.cli import app
from metalworks.contract import PreflightReport, UpdateStatus
from metalworks.preflight import preflight

runner = CliRunner()

_PROVIDER_ENV = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "OPENROUTER_API_KEY",
    "EXA_API_KEY",
    "TAVILY_API_KEY",
    "REDDIT_CLIENT_ID",
    "FIRECRAWL_API_KEY",
    # the dev-machine Vertex backend would otherwise resolve a chat model
    "GOOGLE_GENAI_USE_VERTEXAI",
    "VERTEX_PROJECT_ID",
    "VERTEX_LOCATION",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "METALWORKS_MODEL",
    "ARCTIC_SHIFT_SOURCE",
)


@pytest.fixture
def home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point ``~/.metalworks`` at a tmp dir + a tmp cwd (no real home, no config)."""
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home_dir)
    monkeypatch.chdir(cwd)
    for var in _PROVIDER_ENV:
        monkeypatch.delenv(var, raising=False)
    return home_dir


# ── update check ─────────────────────────────────────────────────────────────


def test_update_cache_miss_fetches_and_caches(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A cache miss calls the fetch once, returns an UpdateStatus, and writes the cache."""
    calls: list[int] = []

    def fake_fetch() -> str:
        calls.append(1)
        return "999.0.0"

    monkeypatch.setattr(_update_check, "_fetch_latest", fake_fetch)
    status = _update_check.check_for_update()
    assert status is not None
    assert status.update_available is True
    assert status.installed == metalworks.__version__
    assert status.latest == "999.0.0"
    assert len(calls) == 1
    cache = json.loads((home / ".metalworks" / "last-update-check").read_text())
    assert cache["latest"] == "999.0.0"


def test_update_cache_hit_skips_fetch(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A fresh cache is used without hitting the fetch again."""
    (home / ".metalworks").mkdir()
    (home / ".metalworks" / "last-update-check").write_text(
        json.dumps({"latest": "999.0.0", "checked_at": int(time.time())})
    )

    def boom() -> str:
        raise AssertionError("fetch must not run on a fresh cache hit")

    monkeypatch.setattr(_update_check, "_fetch_latest", boom)
    status = _update_check.check_for_update()
    assert status is not None
    assert status.latest == "999.0.0"


def test_update_up_to_date_returns_none(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_update_check, "_fetch_latest", lambda: metalworks.__version__)
    assert _update_check.check_for_update() is None


def test_update_disabled_via_config(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``update_check = false`` disables the check entirely (no fetch)."""
    (home / ".metalworks").mkdir()
    (Path.cwd() / "metalworks.toml").write_text("update_check = false\n")

    def boom() -> str:
        raise AssertionError("fetch must not run when update_check is disabled")

    monkeypatch.setattr(_update_check, "_fetch_latest", boom)
    assert _update_check.check_for_update() is None


def test_update_offline_returns_none(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A fetch failure (offline) with no cache returns None silently."""
    monkeypatch.setattr(_update_check, "_fetch_latest", lambda: None)
    assert _update_check.check_for_update() is None


def test_update_snooze_silences(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_update_check, "_fetch_latest", lambda: "999.0.0")
    _update_check.snooze()
    assert _update_check.check_for_update() is None
    # force bypasses the snooze
    assert _update_check.check_for_update(force=True) is not None


def test_update_fetch_does_not_import_httpx_at_module_load() -> None:
    """Importing the update-check module must not pull httpx (lazy + offline-safe)."""
    import subprocess
    import sys

    code = (
        "import sys, metalworks._update_check\nassert 'httpx' not in sys.modules, 'httpx leaked'\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


# ── preflight() report ───────────────────────────────────────────────────────


def test_preflight_report_shape(home: Path) -> None:
    report = preflight(check_update=False)
    assert isinstance(report, PreflightReport)
    assert report.version == metalworks.__version__
    assert report.update is None  # check_update=False
    # no provider key in this clean env → an error-severity issue, ok is False
    assert report.ok is False
    assert any(i.severity == "error" for i in report.issues)
    assert set(report.extras) >= {"anthropic", "mcp", "browser"}
    assert "anthropic" in report.keys


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("api", "arctic_shift_api"),
        ("", "arctic_shift_api"),
        ("hf", "hf_parquet"),
        ("parquet", "hf_parquet"),
        ("arctic", "hf_parquet"),
        ("mirror", "supabase_mirror"),
    ],
)
def test_preflight_active_reader(
    home: Path, monkeypatch: pytest.MonkeyPatch, source: str, expected: str
) -> None:
    if source:
        monkeypatch.setenv("ARCTIC_SHIFT_SOURCE", source)
    report = preflight(check_update=False)
    assert report.active_reader == expected


def test_preflight_folds_in_update(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_update_check, "_fetch_latest", lambda: "999.0.0")
    report = preflight(check_update=True)
    assert report.update is not None
    assert report.update.update_available is True


# ── contract round-trip + additive ───────────────────────────────────────────


def test_contract_round_trips() -> None:
    report = PreflightReport(
        ok=True,
        version="0.2.0",
        update=UpdateStatus(installed="0.2.0", latest="0.3.0", update_available=True),
        active_reader="arctic_shift_api",
    )
    again = PreflightReport.model_validate_json(report.model_dump_json())
    assert again == report


def test_old_payload_validates_additively() -> None:
    """A minimal/old payload (missing the new fields) still validates — additive only."""
    report = PreflightReport.model_validate({"version": "0.1.1"})
    assert report.ok is True  # defaulted
    assert report.update is None
    assert report.active_reader == ""
    assert report.issues == []


# ── doctor + preflight CLI ───────────────────────────────────────────────────


def test_doctor_renders(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_update_check, "_fetch_latest", lambda: None)
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "extras" in result.output.lower()
    assert "corpus reader" in result.output.lower()


def test_preflight_cli_human(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_update_check, "_fetch_latest", lambda: None)
    result = runner.invoke(app, ["preflight"])
    assert result.exit_code == 0
    assert "arctic_shift_api" in result.output


def test_preflight_cli_json(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_update_check, "_fetch_latest", lambda: None)
    result = runner.invoke(app, ["preflight", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["version"] == metalworks.__version__
    assert payload["active_reader"] == "arctic_shift_api"


# ── banner ───────────────────────────────────────────────────────────────────


def test_banner_disabled_is_silent(home: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    from metalworks.cli import _emit_preflight_banner

    (Path.cwd() / "metalworks.toml").write_text("preflight_banner = false\n")
    _emit_preflight_banner()
    assert capsys.readouterr().err == ""


def test_banner_silent_when_healthy(home: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """A clean report (no issues, no update) prints nothing — silent when healthy."""
    from metalworks import cli
    from metalworks.cli import _emit_preflight_banner

    healthy = PreflightReport(ok=True, version=metalworks.__version__, issues=[], update=None)
    monkeypatch.setattr(cli.preflight, "preflight", lambda *, check_update=True: healthy)
    _emit_preflight_banner()
    assert capsys.readouterr().err == ""


def test_banner_warns_on_issues(home: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    from metalworks.cli import _emit_preflight_banner

    # no provider key → a setup issue; the banner fires once.
    monkeypatch.setattr(_update_check, "_fetch_latest", lambda: None)
    _emit_preflight_banner()
    err = capsys.readouterr().err
    assert "metalworks" in err
    assert "setup issue" in err


def test_banner_session_once(home: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    from metalworks.cli import _emit_preflight_banner

    monkeypatch.setattr(_update_check, "_fetch_latest", lambda: None)
    _emit_preflight_banner()
    assert capsys.readouterr().err != ""
    # second call within the TTL is silent (the guard was written)
    _emit_preflight_banner()
    assert capsys.readouterr().err == ""


# ── MCP tool envelope ────────────────────────────────────────────────────────


def test_mcp_preflight_tool_envelope(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from metalworks.mcp import tools

    monkeypatch.setattr(_update_check, "_fetch_latest", lambda: None)
    result = tools.preflight(check_update=True)
    assert "error" not in result
    assert "preflight" in result
    inner = result["preflight"]
    assert inner["version"] == metalworks.__version__
    assert inner["active_reader"] == "arctic_shift_api"
    # round-trips back into the contract model
    PreflightReport.model_validate(inner)
