"""``FileStore`` — the default :class:`~metalworks.stores.repos.ArtifactStore`.

Tier-2 pillar artifacts are committed *files*, not database rows: they live in
``.metalworks/artifacts/`` where both the founder and their coding agent read
them, and git is the history layer (re-plan §10.1). gstack and Claude Code work
the same way — human deliverables are files (``CLAUDE.md``, markdown), not blobs.

``FileStore`` is project-scoped: construct it on a project's ``artifacts/``
directory. It persists each artifact kind as ``<kind>.json`` (the
:class:`~metalworks.stores.repos.StoredArtifact` envelope: the serialized pillar
output plus its ``report_id`` provenance stamp), overwriting on each save —
persist-only-latest. A pillar that also wants a human-readable ``<kind>.md``
provides its own renderer (the way :mod:`metalworks.runs` renders a research
run); the generic store keeps the round-trippable JSON.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from metalworks.stores.repos import StoredArtifact


class FileStore:
    """A project-scoped, files-first ``ArtifactStore`` over one ``artifacts/`` dir."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    def _path(self, kind: str) -> Path:
        return self._root / f"{kind}.json"

    def save_artifact(
        self, project_id: str, report_id: str, stage: str, kind: str, obj: BaseModel
    ) -> StoredArtifact:
        artifact = StoredArtifact(
            project_id=project_id,
            report_id=report_id,
            stage=stage,
            kind=kind,
            generated_at=datetime.now(UTC),
            payload_json=obj.model_dump_json(),
        )
        self._root.mkdir(parents=True, exist_ok=True)
        self._path(kind).write_text(artifact.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return artifact

    def get_latest(self, project_id: str, kind: str) -> StoredArtifact | None:
        path = self._path(kind)
        if not path.is_file():
            return None
        return StoredArtifact.model_validate_json(path.read_text(encoding="utf-8"))

    def list_artifacts(self, project_id: str) -> list[StoredArtifact]:
        if not self._root.is_dir():
            return []
        return [
            StoredArtifact.model_validate_json(p.read_text(encoding="utf-8"))
            for p in sorted(self._root.glob("*.json"))
        ]


__all__ = ["FileStore"]
