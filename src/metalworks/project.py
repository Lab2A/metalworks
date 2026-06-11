"""The metalworks project — a ``.metalworks/`` directory, like ``git init``.

A project is the durable root for one idea/company being built. It is an INDEX
over persisted typed artifacts (corpus, research runs, pillar outputs), NOT a
mutable god-object: pillars stay pure functions, and the project just records
where their outputs live on disk.

Layout (see re-plan §10.1)::

    your-startup/
    └─ .metalworks/
        ├─ project.json          # manifest: id, slug, idea, created_at, runs[]   [committed]
        ├─ config.toml           # non-secret provider/model settings             [committed]
        ├─ corpus.db             # sqlite: corpus + runs + embeddings             [gitignored]
        ├─ runs/<id>/research.{md,json}                                           [committed]
        └─ artifacts/            # Tier-2 pillar outputs (positioning/site/…)     [committed]

:meth:`Project.find` walks up from a start directory looking for ``.metalworks/``
(the way git discovers ``.git``). :meth:`Project.init` creates the directory,
writes the manifest, and gitignores the re-pullable corpus cache. Casual use
(no ``.metalworks/``) leaves zero footprint — the project layer is opt-in,
created only by ``metalworks init``.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

DIRNAME = ".metalworks"
_CORPUS_GITIGNORE = (
    "# Re-pullable corpus cache — rebuilt from source, never committed.\ncorpus.db\n"
)


def _slugify(text: str) -> str:
    """A filesystem/url-safe slug: lowercased, non-alphanumerics collapsed to ``-``."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "project"


class RunRef(BaseModel):
    """A manifest pointer to one persisted research run (files live in ``runs/<run_id>/``)."""

    run_id: str
    report_id: str
    question: str
    created_at: datetime


class ProjectManifest(BaseModel):
    """``project.json`` — the committed index of a project's identity and runs.

    Holds no evidence or artifacts itself (those are files / db rows); it is the
    small, human-readable pointer that makes a directory a metalworks project.
    """

    version: int = 1
    id: str
    slug: str
    idea: str | None = None
    created_at: datetime
    runs: list[RunRef] = Field(default_factory=list[RunRef])


@dataclass(frozen=True)
class Project:
    """A handle to a ``.metalworks/`` directory and the paths inside it.

    ``root`` is the ``.metalworks/`` directory itself (not the repo root). The
    manifest is read fresh from disk on each access, so a handle never holds a
    stale copy of a file another process may have changed.
    """

    root: Path

    # ── Paths ─────────────────────────────────────────────────────────────────
    @property
    def repo_root(self) -> Path:
        """The directory that contains ``.metalworks/`` (the user's repo root)."""
        return self.root.parent

    @property
    def manifest_path(self) -> Path:
        return self.root / "project.json"

    @property
    def config_path(self) -> Path:
        return self.root / "config.toml"

    @property
    def corpus_db(self) -> Path:
        """The sqlite memory substrate (corpus + runs + embeddings) — gitignored."""
        return self.root / "corpus.db"

    @property
    def runs_dir(self) -> Path:
        return self.root / "runs"

    @property
    def artifacts_dir(self) -> Path:
        return self.root / "artifacts"

    # ── Manifest ──────────────────────────────────────────────────────────────
    def read_manifest(self) -> ProjectManifest:
        return ProjectManifest.model_validate_json(self.manifest_path.read_text(encoding="utf-8"))

    def write_manifest(self, manifest: ProjectManifest) -> None:
        self.manifest_path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")

    @property
    def id(self) -> str:
        return self.read_manifest().id

    @property
    def slug(self) -> str:
        return self.read_manifest().slug

    @property
    def idea(self) -> str | None:
        return self.read_manifest().idea

    # ── Discovery / creation ──────────────────────────────────────────────────
    @classmethod
    def find(cls, start: Path | None = None) -> Project | None:
        """Walk up from ``start`` (default cwd) to the first ancestor whose
        ``.metalworks/`` holds a ``project.json`` manifest, like git discovering
        ``.git``. ``None`` when no ancestor is a metalworks project.

        The manifest is what marks a real project — a bare ``.metalworks/`` (e.g.
        ``~/.metalworks/``, the home state dir for the post-log and a default
        store) is deliberately NOT matched.
        """
        home = Path.home().resolve()
        current = (start or Path.cwd()).resolve()
        for directory in (current, *current.parents):
            # `~/.metalworks/` is the reserved home state dir (post-log, default
            # store). Never treat it as a project root, even if a stray
            # `project.json` lands there — otherwise it would silently capture
            # every casual run anywhere under $HOME.
            if directory == home:
                continue
            if (directory / DIRNAME / "project.json").is_file():
                return cls(directory / DIRNAME)
        return None

    @classmethod
    def init(cls, repo_root: Path | None = None, *, idea: str | None = None) -> Project:
        """Create ``<repo_root>/.metalworks/`` and return the project.

        Idempotent: if the project already exists it is returned untouched (never
        clobbered). ``slug`` derives from ``idea`` when given, else from the repo
        directory name. The corpus cache is gitignored via ``.metalworks/.gitignore``
        so the project dir is committable without the noisy re-pullable db.
        """
        base = (repo_root or Path.cwd()).resolve()
        project = cls(base / DIRNAME)
        if project.root.is_dir() and project.manifest_path.is_file():
            return project

        project.root.mkdir(parents=True, exist_ok=True)
        project.runs_dir.mkdir(exist_ok=True)
        project.artifacts_dir.mkdir(exist_ok=True)
        project.write_manifest(
            ProjectManifest(
                id=str(uuid.uuid4()),
                slug=_slugify(idea) if idea else _slugify(base.name),
                idea=idea,
                created_at=datetime.now(UTC),
            )
        )
        gitignore = project.root / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text(_CORPUS_GITIGNORE, encoding="utf-8")
        return project


__all__ = ["DIRNAME", "Project", "ProjectManifest", "RunRef"]
