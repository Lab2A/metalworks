"""CLI surface tests via typer's CliRunner (offline)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from metalworks.cli import app

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "metalworks" in result.output


def test_help_runs_with_no_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0


def test_discovery_help_lists_run() -> None:
    result = runner.invoke(app, ["discovery", "--help"])
    assert result.exit_code == 0
    assert "run" in result.output


def test_doctor_runs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "extras" in result.output.lower()
    assert "store" in result.output.lower()


def test_init_scaffolds_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert (tmp_path / "metalworks.toml").is_file()
    assert (tmp_path / ".env.example").is_file()


def test_config_set_get_list(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    set_result = runner.invoke(app, ["config", "set", "provider", "openai"])
    assert set_result.exit_code == 0
    get_result = runner.invoke(app, ["config", "get", "provider"])
    assert get_result.exit_code == 0
    assert "openai" in get_result.output
    list_result = runner.invoke(app, ["config", "list"])
    assert list_result.exit_code == 0
    assert "provider" in list_result.output


def test_config_set_refuses_secret(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["config", "set", "ANTHROPIC_API_KEY", "sk-leak"])
    assert result.exit_code == 1
    assert not (tmp_path / "metalworks.toml").exists()


def test_quickstart_offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pytest.importorskip("duckdb")
    # Zero keys: quickstart must succeed with Fake models + local corpus.
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["quickstart"])
    assert result.exit_code == 0, result.output
    assert "Report" in result.output


def test_reddit_post_dry_run_passes_compliance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    # A clean, human-sounding reply passes the gate; without --yes it's a dry-run
    # (exit 0) and never touches Reddit.
    text = "I tried the same thing last winter and switching to magnesium glycinate "
    text += "before bed genuinely helped me sleep through the night."
    result = runner.invoke(
        app,
        ["reddit", "post", "https://reddit.com/r/x/comments/abc123/t/", "--text", text],
    )
    assert result.exit_code == 0
    assert "PASS" in result.output
    assert "Dry-run" in result.output


def test_reddit_post_refuses_without_yes_on_failing_compliance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    # Em-dash + AI tell + CTA → compliance FAIL → refuse even though --yes given.
    bad = "Great question — you should definitely check out our product, it's robust!"
    result = runner.invoke(
        app,
        ["reddit", "post", "https://reddit.com/r/x/comments/abc123/t/", "--text", bad, "--yes"],
    )
    assert result.exit_code == 1
    assert "FAIL" in result.output


def test_mcp_serve_sse_refuses_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("METALWORKS_MCP_TOKEN", raising=False)
    result = runner.invoke(app, ["mcp", "serve", "--transport", "sse"])
    assert result.exit_code == 1
    assert "token" in result.output.lower()


# Every registered command group, so the smoke test below fails the moment a new
# group is added without help that renders.
_COMMAND_GROUPS = [
    [],
    ["research"],
    ["reddit"],
    ["reddit", "subreddit"],
    ["reddit", "auth"],
    ["arctic"],
    ["discovery"],
    ["config"],
    ["mcp"],
]


@pytest.mark.parametrize("group", _COMMAND_GROUPS)
def test_help_renders_for_every_command_group(group: list[str]) -> None:
    result = runner.invoke(app, [*group, "--help"])
    assert result.exit_code == 0, f"`metalworks {' '.join(group)} --help` failed to render"


def test_help_text_points_at_real_post_command_not_a_phantom_subcommand() -> None:
    """Regression: the discovery help told users to run `reddit post comment`,
    which is not a command (the real one is `reddit post`). Naming drift across
    surfaces is exactly what the help should never do."""
    result = runner.invoke(app, ["discovery", "run", "--help"])
    assert result.exit_code == 0
    assert "reddit post comment" not in result.output
    assert "reddit post" in result.output
