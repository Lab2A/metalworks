"""``metalworks sources scaffold`` codegen — the emitted skeleton is real.

The DX promise (0.7): adding a source is a fill-in-the-bodies job. The scaffold
must emit a connector that (a) compiles, (b) self-registers a real ``SourceSpec``
on import, and (c) passes the 0.5 conformance sweep once ``pull`` returns records
— with nothing but the ``pull`` / ``comments_for`` bodies left to write. These
tests prove that without touching the filesystem the CLI writes to.
"""

from __future__ import annotations

import ast
import types
from collections.abc import Iterator, Sequence

import pytest
from typer.testing import CliRunner

from metalworks.cli import app
from metalworks.contract import CorpusComment, CorpusRecord
from metalworks.research.sources import SOURCE_SPECS, SourceWindow
from metalworks.research.sources.scaffold import (
    ScaffoldPlan,
    render_connector,
    render_docs_row,
    render_pyproject_extra,
    render_test,
)
from metalworks.testing import check_item_source

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolate_registries() -> Iterator[None]:
    """Snapshot + restore the global source/signal registries.

    The scaffold tests exec generated connectors that self-register ids into the
    shared ``SOURCES`` / ``SOURCE_SPECS``. Without this, those stray ids leak into
    other tests (e.g. the gen_sources_md drift check would see extra catalog rows).
    """
    from metalworks.research.sources import SOURCE_SPECS as specs
    from metalworks.research.sources import SOURCES as factories
    from metalworks.research.synthesis.signals import SIGNAL_SPECS as signals

    snap_factories = dict(factories)
    snap_specs = dict(specs)
    snap_signals = dict(signals)
    try:
        yield
    finally:
        factories.clear()
        factories.update(snap_factories)
        specs.clear()
        specs.update(snap_specs)
        signals.clear()
        signals.update(snap_signals)


def _exec_connector(
    source_id: str, *, lane: str = "grounding", auth: str = "none"
) -> types.ModuleType:
    """Render + exec a scaffolded connector as a throwaway module (no fs write)."""
    plan = ScaffoldPlan.build(source_id, lane=lane, auth=auth)  # type: ignore[arg-type]
    src = render_connector(plan)
    ast.parse(src)  # must compile
    mod = types.ModuleType(f"mw_scaffold_{source_id}")
    mod.__file__ = f"<scaffold:{source_id}>"
    exec(compile(src, mod.__file__, "exec"), mod.__dict__)  # generated, trusted
    return mod


def test_scaffold_connector_registers_real_spec() -> None:
    """Importing the scaffolded module lands a real SourceSpec (lane/auth honored)."""
    _exec_connector("scaffoldgrounding", lane="grounding", auth="none")
    spec = SOURCE_SPECS["scaffoldgrounding"]
    assert spec.source_id == "scaffoldgrounding"
    assert spec.lane == "grounding"
    assert spec.auth == "none"
    assert spec.signals == ("upvotes",)


def test_scaffold_keyed_source_names_env() -> None:
    """A --auth key scaffold emits a valid spec (env named, so __post_init__ passes)."""
    _exec_connector("scaffoldkeyed", lane="grounding", auth="key")
    spec = SOURCE_SPECS["scaffoldkeyed"]
    assert spec.auth == "key"
    assert spec.access == "free_key"
    assert spec.env == ("SCAFFOLDKEYED_API_KEY",)


def test_scaffold_web_lane_has_no_signal() -> None:
    """A web-lane scaffold declares no endorsement signal (web is context)."""
    _exec_connector("scaffoldweb", lane="web", auth="none")
    spec = SOURCE_SPECS["scaffoldweb"]
    assert spec.lane == "web"
    assert spec.signals == ()


def test_scaffold_web_connector_omits_unused_signal_import() -> None:
    """A no-signal connector must NOT import the signals API (else ruff/pyright trip).

    Regression guard: the emitted module has to be gate-clean as written, so a
    web/context source (no declared signal) carries no unused ``register_signal``
    import.
    """
    plan = ScaffoldPlan.build("scaffoldnoimport", lane="web", auth="none")
    src = render_connector(plan)
    assert "from metalworks.research.synthesis.signals import" not in src


def test_scaffold_grounding_connector_keeps_signal_import() -> None:
    """A grounding connector DOES import the signals API (it registers a kind)."""
    plan = ScaffoldPlan.build("scaffoldwithimport", lane="grounding", auth="none")
    src = render_connector(plan)
    assert "from metalworks.research.synthesis.signals import SignalSpec, register_signal" in src


def test_scaffold_output_passes_conformance_when_pull_filled() -> None:
    """The scaffold's SHAPE is conformance-ready: fill in pull and the sweep passes.

    This is the acceptance criterion — the emitted skeleton needs ONLY the pull /
    comments_for bodies. We subclass the generated class and supply minimal bodies,
    then run the real ``check_item_source`` against it.
    """
    mod = _exec_connector("scaffoldconforms", lane="grounding", auth="none")
    base = mod.ScaffoldconformsSource

    class _Filled(base):  # type: ignore[valid-type, misc]
        def pull(
            self, *, query: str, window: SourceWindow, limit: int | None = None
        ) -> Iterator[CorpusRecord]:
            _ = (query, window, limit)
            yield CorpusRecord(
                id="r1",
                source=self.source_id,
                source_id="r1",
                url="https://example.com/r1",
                title="t",
                text="real pain about the topic",
                author_hash="u_abc",
                engagement=3,
                created_at=None,
            )

        def comments_for(self, record_ids: Sequence[str]) -> Iterator[list[CorpusComment]] | None:
            for rid in record_ids:
                yield [
                    CorpusComment(
                        id=f"{rid}-c1",
                        parent_id=rid,
                        source=self.source_id,
                        url="https://example.com/c1",
                        text="a real comment",
                        author_hash="u_def",
                        engagement=1,
                        created_at=None,
                    )
                ]

    check_item_source(_Filled())  # must not raise


def test_scaffold_rejects_bad_id() -> None:
    with pytest.raises(ValueError, match="lowercase identifier"):
        ScaffoldPlan.build("Bad Id", lane="grounding", auth="none")


def test_render_pyproject_extra_and_docs_row() -> None:
    plan = ScaffoldPlan.build("forum", lane="grounding", auth="none")
    extra = render_pyproject_extra(plan)
    assert extra.startswith("forum = [")
    row = render_docs_row(plan)
    assert row.startswith("| `forum` |")
    assert "grounding" in row


def test_render_test_imports_the_generated_class() -> None:
    plan = ScaffoldPlan.build("forum", lane="grounding", auth="none")
    test_src = render_test(plan, module_path="metalworks.research.sources.forum")
    ast.parse(test_src)  # the generated test compiles
    assert "from metalworks.research.sources.forum import ForumSource" in test_src
    assert "def test_forum_conforms()" in test_src


def test_scaffold_cli_writes_files(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The CLI command writes the connector + test and prints the extra / row."""
    monkeypatch.chdir(tmp_path)
    out_dir = tmp_path / "connectors"
    result = runner.invoke(
        app,
        [
            "sources",
            "scaffold",
            "mywidget",
            "--lane",
            "web",
            "--auth",
            "key",
            "--out-dir",
            str(out_dir),
        ],
    )
    assert result.exit_code == 0, result.output
    assert (out_dir / "mywidget.py").is_file()
    assert (tmp_path / "tests" / "test_source_mywidget.py").is_file()
    # The extra + docs row are PRINTED, never auto-applied.
    assert "mywidget = [" in result.output
    assert "| `mywidget` |" in result.output


def test_scaffold_cli_refuses_overwrite_without_force(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    out_dir = tmp_path / "connectors"
    first = runner.invoke(app, ["sources", "scaffold", "dup", "--out-dir", str(out_dir)])
    assert first.exit_code == 0, first.output
    again = runner.invoke(app, ["sources", "scaffold", "dup", "--out-dir", str(out_dir)])
    assert again.exit_code == 1
    assert "already exists" in again.output


def test_scaffold_cli_rejects_bad_lane(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app, ["sources", "scaffold", "x", "--lane", "bogus", "--out-dir", str(tmp_path / "c")]
    )
    assert result.exit_code == 2
    assert "--lane" in result.output
