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


def test_init_scaffolds_project(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init", "--idea", "focus supplement for devs"])
    assert result.exit_code == 0
    assert (tmp_path / ".metalworks" / "project.json").is_file()
    assert (tmp_path / ".metalworks" / "config.toml").is_file()
    assert (tmp_path / ".metalworks" / ".gitignore").is_file()
    assert (tmp_path / ".env.example").is_file()


def test_init_is_idempotent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    first = runner.invoke(app, ["init", "--idea", "first"])
    assert first.exit_code == 0
    manifest = (tmp_path / ".metalworks" / "project.json").read_text()
    second = runner.invoke(app, ["init", "--idea", "second"])
    assert second.exit_code == 0
    assert "already exists" in second.output
    # Re-init never clobbers the original manifest (slug/id stay put).
    assert (tmp_path / ".metalworks" / "project.json").read_text() == manifest


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


_PROVIDER_KEYS = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "OPENROUTER_API_KEY",
)


def test_models_list_runs_without_keys(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # With no provider key set, every resolver is guarded: `models list` shows
    # the matrix + "unresolved" model slots, and still exits 0 (no traceback).
    monkeypatch.chdir(tmp_path)
    for key in _PROVIDER_KEYS:
        monkeypatch.delenv(key, raising=False)
    result = runner.invoke(app, ["models", "list"])
    assert result.exit_code == 0
    assert "reachable" in result.output.lower()
    assert "anthropic" in result.output
    assert "openrouter" in result.output


def test_models_list_runs_with_a_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # A present key flips the reachability row; the command still exits 0.
    monkeypatch.chdir(tmp_path)
    for key in _PROVIDER_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    result = runner.invoke(app, ["models", "list"])
    assert result.exit_code == 0
    assert "ANTHROPIC_API_KEY" in result.output


def test_models_set_writes_and_is_reflected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    set_result = runner.invoke(app, ["models", "set", "openai/gpt-5"])
    assert set_result.exit_code == 0
    assert "openai/gpt-5" in set_result.output
    # The cwd metalworks.toml now carries `model = "openai/gpt-5"` (same write
    # path as `config set`).
    assert 'model = "openai/gpt-5"' in (tmp_path / "metalworks.toml").read_text()
    # `config list` reflects the written `model` value.
    list_result = runner.invoke(app, ["config", "list"])
    assert list_result.exit_code == 0
    assert "model" in list_result.output
    assert "openai/gpt-5" in list_result.output
    # With an OpenAI key present the ref resolves: `models list` shows the
    # written model id in the chat slot (offline — the adapter constructs from a
    # dummy key without a network call).
    for key in ("ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    models_result = runner.invoke(app, ["models", "list"])
    assert models_result.exit_code == 0
    assert "gpt-5" in models_result.output


def test_models_set_fast_writes_fast_model(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["models", "set-fast", "openai/gpt-5-mini"])
    assert result.exit_code == 0
    get_result = runner.invoke(app, ["config", "get", "fast_model"])
    assert get_result.exit_code == 0
    assert "openai/gpt-5-mini" in get_result.output


def test_models_set_rejects_empty_ref(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["models", "set", "   "])
    assert result.exit_code == 2
    assert not (tmp_path / "metalworks.toml").exists()


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
    ["models"],
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


def test_research_run_requires_a_question_or_brief() -> None:
    result = runner.invoke(app, ["research", "run"])
    assert result.exit_code == 2
    assert "exactly one" in result.output.lower()


def test_research_run_rejects_both_question_and_brief(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["research", "run", "--question", "q", "--brief", str(tmp_path / "b.json")]
    )
    assert result.exit_code == 2


def test_research_list_runs_with_empty_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The command 8 help strings promise must exist and not crash on an empty store.
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["research", "list"])
    assert result.exit_code == 0
    assert "No stored runs" in result.output


def test_research_list_is_in_help() -> None:
    result = runner.invoke(app, ["research", "--help"])
    assert result.exit_code == 0
    assert "list" in result.output
