"""Offline smoke test for the standalone ``scripts/load_arctic_corpus.py``.

Loads the script as a module by file path (``scripts/`` is not a package) and
checks its CLI surface — the expected flags, arg parsing, and that bad input is
rejected — all without touching the network. A real pull is marked
``@pytest.mark.network`` and skipped by default.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "load_arctic_corpus.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("load_arctic_corpus", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_script_file_exists() -> None:
    assert _SCRIPT.is_file()


def test_parser_has_expected_flags() -> None:
    mod = _load_script()
    parser = mod.build_parser()
    opts = {action.dest for action in parser._actions}  # noqa: SLF001 - introspecting argparse
    for expected in ("subreddits", "months", "out", "comments", "limit", "hf_token"):
        assert expected in opts, f"missing --{expected}"


def test_parses_canonical_invocation() -> None:
    mod = _load_script()
    parser = mod.build_parser()
    args = parser.parse_args(["--subreddit", "Supplements", "--months", "3", "--out", "./corpus"])
    assert args.subreddits == ["Supplements"]
    assert args.months == 3
    assert str(args.out) == "corpus"
    assert args.comments is False


def test_subreddit_is_repeatable() -> None:
    mod = _load_script()
    parser = mod.build_parser()
    args = parser.parse_args(["-s", "Supplements", "-s", "Nootropics"])
    assert args.subreddits == ["Supplements", "Nootropics"]


def test_run_requires_a_subreddit() -> None:
    mod = _load_script()
    parser = mod.build_parser()
    # No --subreddit: run() should fail fast (exit 2) before any network/duckdb.
    args = parser.parse_args(["--months", "1"])
    assert mod.run(args) == 2


def test_month_glob_matches_arctic_layout() -> None:
    mod = _load_script()
    m = mod.MonthRef(2026, 6)
    assert m.path_segment == "2026/06"
    glob = mod._month_glob("submissions", m, root="ROOT")  # noqa: SLF001
    assert glob == "ROOT/submissions/2026/06/*.parquet"


def test_months_back_oldest_first() -> None:
    mod = _load_script()
    window = mod.months_back(3, anchor=mod.MonthRef(2026, 1))
    assert [str(m) for m in window] == ["2025-11", "2025-12", "2026-01"]


def test_help_runs_without_args(capsys: pytest.CaptureFixture[str]) -> None:
    mod = _load_script()
    with pytest.raises(SystemExit) as exc:
        mod.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--subreddit" in out
    assert "--months" in out


@pytest.mark.network
def test_real_pull_smoke(tmp_path: pytest.TempPathFactory) -> None:  # pragma: no cover
    """A real one-month pull against the live HF mirror. Network-only."""
    mod = _load_script()
    parser = mod.build_parser()
    args = parser.parse_args(
        ["--subreddit", "Supplements", "--months", "1", "--out", str(tmp_path)]
    )
    assert mod.run(args) == 0
