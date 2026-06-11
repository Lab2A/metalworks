"""Project layer: `.metalworks/` discovery, init, and config resolution (offline)."""

from __future__ import annotations

from pathlib import Path

import pytest

from metalworks import config
from metalworks.project import DIRNAME, Project, ProjectManifest


def test_init_creates_dir_manifest_gitignore(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve()  # macOS: /var → /private/var, matching init's resolve()
    project = Project.init(tmp_path, idea="a focus supplement for developers")

    assert project.root == tmp_path / DIRNAME
    assert project.manifest_path.is_file()
    assert project.config_path.parent == project.root
    assert (project.root / ".gitignore").read_text().strip().endswith("corpus.db")

    manifest = project.read_manifest()
    assert isinstance(manifest, ProjectManifest)
    assert manifest.slug == "a-focus-supplement-for-developers"
    assert manifest.idea == "a focus supplement for developers"
    assert manifest.id
    assert manifest.runs == []


def test_init_slug_falls_back_to_dir_name(tmp_path: Path) -> None:
    repo = tmp_path / "MyStartup"
    repo.mkdir()
    project = Project.init(repo)
    assert project.read_manifest().slug == "mystartup"


def test_init_is_idempotent_and_never_clobbers(tmp_path: Path) -> None:
    first = Project.init(tmp_path, idea="first")
    original = first.manifest_path.read_text()
    second = Project.init(tmp_path, idea="second")
    assert second.root == first.root
    assert second.manifest_path.read_text() == original  # untouched
    assert second.read_manifest().idea == "first"


def test_find_walks_up_like_git(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve()
    Project.init(tmp_path, idea="root project")
    nested = tmp_path / "src" / "deep" / "module"
    nested.mkdir(parents=True)

    found = Project.find(nested)
    assert found is not None
    assert found.root == tmp_path / DIRNAME


def test_find_returns_none_with_no_project(tmp_path: Path) -> None:
    assert Project.find(tmp_path) is None


def test_find_ignores_a_project_at_the_home_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A `.metalworks/project.json` at $HOME must never capture runs beneath it.
    home = tmp_path.resolve()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    Project.init(home, idea="stray home project")
    nested = home / "work" / "repo"
    nested.mkdir(parents=True)
    assert Project.find(nested) is None


def test_find_ignores_a_bare_metalworks_dir_without_manifest(tmp_path: Path) -> None:
    # ~/.metalworks/ (post-log, default store) is a bare dir, not a project.
    (tmp_path / DIRNAME).mkdir()
    assert Project.find(tmp_path) is None


def test_config_resolves_from_project_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    project = Project.init(tmp_path)
    config.save_config({"provider": "openai"}, path=project.config_path)

    assert config.default_config_path() == project.config_path
    assert config.load_config().get("provider") == "openai"


def test_legacy_cwd_toml_still_read_without_a_project(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "metalworks.toml").write_text('provider = "anthropic"\n', encoding="utf-8")
    assert Project.find(tmp_path) is None
    assert config.load_config().get("provider") == "anthropic"


def test_auto_store_is_memory_and_leaves_no_footprint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    from metalworks.stores import MemoryStores

    assert isinstance(config.auto_store(), MemoryStores)
    assert not (tmp_path / DIRNAME).exists()  # casual use = zero footprint


def test_auto_store_is_sqlite_on_corpus_db_inside_a_project(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    Project.init(tmp_path)
    from metalworks.stores import SqliteStores

    store = config.auto_store()
    assert isinstance(store, SqliteStores)
    assert (tmp_path / DIRNAME / "corpus.db").is_file()
    store.close()
