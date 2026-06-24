"""``scripts/gen_sources_md.py`` — the source catalog is generated, not hand-kept.

Mirrors the ``gen_ts_types --check`` drift gate: the committed ``docs/sources.md``
must equal what the generator emits from ``SOURCE_SPECS``, and ``--check`` must
FAIL the moment they diverge (a new/changed spec without a regen). These tests
import the generator module directly so they run offline.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "scripts" / "gen_sources_md.py"


def _load_module():  # type: ignore[no-untyped-def]
    """Import scripts/gen_sources_md.py as a module (it lives outside the package)."""
    spec = importlib.util.spec_from_file_location("gen_sources_md", _SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["gen_sources_md"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_committed_catalog_is_up_to_date() -> None:
    """The committed docs/sources.md matches the generator (no drift on main)."""
    mod = _load_module()
    assert mod.cmd_check() == 0, (
        "docs/sources.md drifted from SOURCE_SPECS — run `python scripts/gen_sources_md.py`"
    )


def test_check_detects_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`--check` returns nonzero when the file on disk differs from the render."""
    mod = _load_module()
    mod._load_specs()  # noqa: SLF001 — the script's test seam
    # Point the generator at a tampered copy and confirm the gate trips.
    tampered = tmp_path / "sources.md"
    tampered.write_text(mod._render() + "\n<!-- drift -->\n")  # noqa: SLF001
    monkeypatch.setattr(mod, "_OUT", tampered)
    assert mod.cmd_check() == 1


def test_check_passes_after_regen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Regenerating into a fresh path makes `--check` pass (round-trip)."""
    mod = _load_module()
    fresh = tmp_path / "sources.md"
    monkeypatch.setattr(mod, "_OUT", fresh)
    assert mod.cmd_write() == 0
    assert mod.cmd_check() == 0


def test_catalog_lists_every_builtin() -> None:
    """The generated table has a row per built-in source (catalog completeness)."""
    mod = _load_module()
    mod._load_specs()  # noqa: SLF001 — the script's test seam

    table = mod._catalog_table()  # noqa: SLF001
    for source_id in mod._BUILTIN_IDS:  # noqa: SLF001
        assert f"| `{source_id}` |" in table, f"{source_id} missing from generated catalog"
