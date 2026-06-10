"""metalworks.testing must hold the built-in backends to its own bar."""

from __future__ import annotations

from pathlib import Path

from metalworks.stores import MemoryStores, SqliteStores
from metalworks.testing import check_all_repos


def test_check_all_repos_passes_on_memory() -> None:
    check_all_repos(MemoryStores(), corpus_rows=1200)


def test_check_all_repos_passes_on_sqlite(tmp_path: Path) -> None:
    backend = SqliteStores(tmp_path / "t.db")
    try:
        check_all_repos(backend, corpus_rows=1200)
    finally:
        backend.close()


def test_check_corpus_catches_truncating_backend() -> None:
    """A backend that silently caps results must FAIL the suite."""
    import pytest

    from metalworks.testing import check_corpus_repo

    class Truncating(MemoryStores):
        def get_comments_for_posts(self, post_ids: object) -> list:  # type: ignore[override]
            return super().get_comments_for_posts(post_ids)[:1000]  # type: ignore[arg-type]

    with pytest.raises(AssertionError, match="truncating"):
        check_corpus_repo(Truncating(), rows=1200)
