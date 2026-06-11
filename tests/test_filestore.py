"""FileStore — the files-first ArtifactStore (offline)."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from metalworks.stores import ArtifactStore, FileStore


class _Toy(BaseModel):
    headline: str
    score: int


def test_save_get_roundtrip(tmp_path: Path) -> None:
    store = FileStore(tmp_path / "artifacts")
    toy = _Toy(headline="a clean-label focus supplement", score=3)

    stored = store.save_artifact("proj1", "rep-1", "design", "positioning", toy)
    assert stored.report_id == "rep-1"
    assert stored.kind == "positioning"
    assert (tmp_path / "artifacts" / "positioning.json").is_file()

    latest = store.get_latest("proj1", "positioning")
    assert latest is not None
    assert latest.report_id == "rep-1"
    assert latest.parse(_Toy) == toy


def test_get_latest_is_none_when_absent(tmp_path: Path) -> None:
    assert FileStore(tmp_path / "artifacts").get_latest("p", "nope") is None


def test_persist_only_latest_overwrites(tmp_path: Path) -> None:
    store = FileStore(tmp_path / "a")
    store.save_artifact("p", "rep-1", "design", "positioning", _Toy(headline="old", score=1))
    store.save_artifact("p", "rep-2", "design", "positioning", _Toy(headline="new", score=2))

    latest = store.get_latest("p", "positioning")
    assert latest is not None
    assert latest.report_id == "rep-2"  # newest run's snapshot wins
    assert latest.parse(_Toy).headline == "new"
    assert len(store.list_artifacts("p")) == 1  # one kind = one file


def test_list_artifacts_spans_kinds(tmp_path: Path) -> None:
    store = FileStore(tmp_path / "a")
    store.save_artifact("p", "r", "design", "positioning", _Toy(headline="a", score=1))
    store.save_artifact("p", "r", "launch", "channel_plan", _Toy(headline="b", score=2))
    assert {a.kind for a in store.list_artifacts("p")} == {"positioning", "channel_plan"}


def test_list_artifacts_empty_when_no_dir(tmp_path: Path) -> None:
    assert FileStore(tmp_path / "never-created").list_artifacts("p") == []


def test_filestore_satisfies_the_artifact_store_protocol(tmp_path: Path) -> None:
    assert isinstance(FileStore(tmp_path), ArtifactStore)
