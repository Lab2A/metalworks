"""Codegen for ``metalworks sources scaffold`` — turn adding a source into fill-in.

Going wide on sources is only cheap if a new connector is a fill-in-the-bodies
job, not a 7-step edit across 6 files. This module renders the *deterministic*
artifacts the CLI writes/prints for a new source id:

* :func:`render_connector` — the connector module: a real :class:`ItemSource`
  skeleton carrying a filled :class:`SourceSpec` stub and a ``register_signal``
  block for the kinds it declares, with only the ``pull`` / ``comments_for``
  bodies left to write.
* :func:`render_test` — a conformance test that runs ``check_item_source`` once
  the bodies are filled (skipped until then, so the suite stays green).
* :func:`render_pyproject_extra` — the ``[project.optional-dependencies]`` snippet
  to paste (PRINTED, never auto-edited — the CLI does not rewrite ``pyproject``).
* :func:`render_docs_row` — the ``docs/sources.md`` table row (informational; the
  catalog is regenerated from ``SOURCE_SPECS`` by ``scripts/gen_sources_md.py``).

Everything here is a pure string render of ``(source_id, lane, auth)`` plus the
derived defaults, so the same inputs always produce byte-identical output — the
scaffold test asserts the emitted module passes the 0.5 conformance sweep.
"""

from __future__ import annotations

import keyword
from dataclasses import dataclass

from metalworks.research.sources.spec import Access, Auth, Lane

# Per-lane default signal kind(s) the scaffold declares. These are all kinds the
# synthesis registry already knows (so the emitted ``register_signal`` block is a
# no-op re-register that the scorer reads), giving a working source out of the box.
_LANE_SIGNALS: dict[Lane, tuple[str, ...]] = {
    "grounding": ("upvotes",),
    "web": (),  # web is context, never an endorsement signal
}

# auth → the access the scaffold picks (the operator can tighten it). A keyed
# source defaults to free_key (the common case — Product Hunt, Exa); a paid one
# to paid. ``none`` is open.
_AUTH_ACCESS: dict[Auth, Access] = {
    "none": "open",
    "key": "free_key",
    "oauth": "free_key",
    "paid": "paid",
}


def _is_valid_id(source_id: str) -> bool:
    """A source id must be a non-empty lowercase identifier (no spaces/dots)."""
    return bool(source_id) and source_id.isidentifier() and source_id == source_id.lower()


def _class_name(source_id: str) -> str:
    """``my_forum`` → ``MyForumSource`` (a valid, unique connector class name)."""
    parts = [p for p in source_id.split("_") if p]
    return "".join(p.capitalize() for p in parts) + "Source"


@dataclass(frozen=True)
class ScaffoldPlan:
    """The resolved inputs + derived defaults for one scaffolded source."""

    source_id: str
    lane: Lane
    auth: Auth
    access: Access
    signals: tuple[str, ...]
    env: tuple[str, ...]
    targeting: str
    class_name: str
    test_name: str

    @classmethod
    def build(cls, source_id: str, *, lane: Lane, auth: Auth) -> ScaffoldPlan:
        if not _is_valid_id(source_id):
            raise ValueError(
                f"source id {source_id!r} must be a lowercase identifier "
                "(letters/digits/underscores, no spaces or dots)"
            )
        if keyword.iskeyword(source_id):
            raise ValueError(f"source id {source_id!r} is a Python keyword")
        access = _AUTH_ACCESS[auth]
        # A keyed source must name an env var (SourceSpec enforces it); default to
        # an UPPER_SNAKE token off the id so the emitted spec is valid as written.
        env = () if auth == "none" else (f"{source_id.upper()}_API_KEY",)
        # "keyword" is the safe default knob for a brand-new source — the operator
        # tightens it to subreddit/instance/slug if their source targets that way.
        targeting = "keyword"
        return cls(
            source_id=source_id,
            lane=lane,
            auth=auth,
            access=access,
            signals=_LANE_SIGNALS.get(lane, ()),
            env=env,
            targeting=targeting,
            class_name=_class_name(source_id),
            test_name=f"test_{source_id}_conforms",
        )


def _tuple_literal(items: tuple[str, ...]) -> str:
    """Render a Python tuple literal that round-trips (1-tuples keep the comma).

    Uses double quotes to match ruff-format's string-quote style, so the emitted
    module needs no reformat.
    """
    if not items:
        return "()"
    inner = ", ".join(f'"{i}"' for i in items)
    return f"({inner},)" if len(items) == 1 else f"({inner})"


def _register_signal_block(plan: ScaffoldPlan) -> str:
    """The ``register_signal`` lines for the declared kinds (commented if none).

    When the source declares no signal (a web/context lane), the block is fully
    commented AND the connector omits the ``signals`` import — so a no-signal
    source stays ruff/pyright clean with no unused import.
    """
    if not plan.signals:
        return (
            "# This source declares no endorsement signal (a web/context lane). If you add\n"
            "# one to the spec's ``signals``, register its semantics so the scorer can read\n"
            "# it (import SignalSpec / register_signal from\n"
            "# metalworks.research.synthesis.signals), e.g.:\n"
            '#     register_signal(SignalSpec(kind="helpfulness", weight=1.0, transform="log"))'
        )
    lines = [
        "# Register the semantics of each signal kind this source emits so the pure",
        "# scorer can weight it. (A kind already in the registry — e.g. 'upvotes' —",
        "# re-registers idempotently; rename it to your source's real signal.)",
    ]
    for kind in plan.signals:
        lines.append(f'register_signal(SignalSpec(kind="{kind}", weight=1.0, transform="log"))')
    return "\n".join(lines)


def render_connector(plan: ScaffoldPlan) -> str:
    """Render the connector module source for ``plan`` (importable, conformance-ready).

    The output is gate-clean as written: ruff (line-length 100, sorted imports),
    ruff-format, and pyright-strict all pass on the emitted module, so a
    contributor's first ``uv run`` after scaffolding is green.
    """
    cls = plan.class_name
    hint = f"TODO: one line on what {plan.source_id} is best at surfacing"
    # Only import the signals API when the source actually declares a signal kind,
    # so a no-signal (web/context) source carries no unused import.
    signal_import = (
        "from metalworks.research.synthesis.signals import SignalSpec, register_signal\n"
        if plan.signals
        else ""
    )
    return f'''\
"""``{plan.source_id}`` source connector — generated by ``metalworks sources scaffold``.

Fill in the two ``TODO`` bodies (``pull`` and ``comments_for``) and this source is
live: it self-registers on import, declares its lane/auth metadata via
:class:`SourceSpec`, and passes the conformance sweep. See CONTRIBUTING.md →
"Adding a source connector" for the worked walk-through.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from metalworks.contract import CorpusComment, CorpusRecord
from metalworks.research.sources import SourceSpec, SourceWindow, register_source
{signal_import}
if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence


class {cls}:
    """A :class:`~metalworks.research.sources.ItemSource` for ``{plan.source_id}``."""

    source_id = "{plan.source_id}"

    def pull(
        self, *, query: str, window: SourceWindow, limit: int | None = None
    ) -> Iterator[CorpusRecord]:
        """TODO: fetch candidate items for ``query`` over ``window`` and yield
        them as :class:`CorpusRecord`. ``id`` must be STABLE across pulls (the
        corpus upserts by id); honor ``limit`` (a dev guard). Pull broadly — the
        pipeline triages for relevance before any comment fetch.
        """
        _ = (query, window, limit)
        return iter(())

    def comments_for(self, record_ids: Sequence[str]) -> Iterator[list[CorpusComment]] | None:
        """TODO: yield one (possibly empty) ``list[CorpusComment]`` per record id,
        IN INPUT ORDER, each parented (``parent_id``) to its record id. Drop
        tombstones (deleted/removed) rather than emitting empty comments. Return
        ``None`` only if this source has NO comment layer at all (then set
        ``yields_units = True`` on this class so each record's own text is a unit).
        """
        _ = record_ids
        return (list[CorpusComment]() for _ in record_ids)

    def latest_window(self) -> SourceWindow:
        """The most recent window this source can serve (its anchor)."""
        return SourceWindow(end=datetime.now(tz=UTC))


def _factory(**kwargs: Any) -> {cls}:
    return {cls}(**kwargs)


# ── self-registration (runs on import; never edits a shared inline list) ──────
{_register_signal_block(plan)}

register_source(
    "{plan.source_id}",
    _factory,
    spec=SourceSpec(
        source_id="{plan.source_id}",
        lane="{plan.lane}",
        signals={_tuple_literal(plan.signals)},
        targeting="{plan.targeting}",
        auth="{plan.auth}",
        env={_tuple_literal(plan.env)},
        access="{plan.access}",
        relevance_hint="{hint}",
    ),
)


__all__ = ["{cls}"]
'''


def render_test(plan: ScaffoldPlan, *, module_path: str) -> str:
    """Render the conformance test for the scaffolded source.

    ``module_path`` is the dotted import path of the connector module so the test
    imports the real class. The test is ``skip``-guarded until ``pull`` returns
    records, so a freshly scaffolded (still-stubbed) source keeps the suite green
    while still wiring the conformance check up for the moment the body is filled.
    """
    cls = plan.class_name
    # Emit ruff-isort-clean import groups: third-party (pytest) above first-party
    # (metalworks + the connector module), the latter sorted by module path. This
    # keeps the generated test green on the first ``uv run ruff check``.
    first_party = sorted(
        (
            "from metalworks.testing import check_item_source",
            f"from {module_path} import {cls}",
        ),
        key=lambda line: line.split()[1],
    )
    import_block = "import pytest\n\n" + "\n".join(first_party)
    return f'''\
"""Conformance test for the ``{plan.source_id}`` source — generated by scaffold."""

from __future__ import annotations

{import_block}


def {plan.test_name}() -> None:
    """The source honors the ItemSource contract once ``pull`` yields records.

    Fill in ``pull`` / ``comments_for`` (and give this a window/fixture with at
    least one record), then drop the skip below to enforce the contract.
    """
    source = {cls}()
    records = list(source.pull(query="test", window=source.latest_window(), limit=5))
    if not records:
        pytest.skip("{plan.source_id}.pull is still a stub — fill it in, then drop this skip")
    check_item_source(source)
'''


def render_pyproject_extra(plan: ScaffoldPlan) -> str:
    """Render the ``pyproject.toml`` extra snippet to paste (PRINTED, not applied)."""
    return (
        f"{plan.source_id} = [\n"
        f"  # TODO: list the runtime deps your {plan.source_id} connector imports,\n"
        f'  # e.g. "httpx>=0.27". Then add "{plan.source_id}" to the "all" extra.\n'
        f"]"
    )


def render_docs_row(plan: ScaffoldPlan) -> str:
    """Render the ``docs/sources.md`` table row (informational — the catalog is
    regenerated from ``SOURCE_SPECS`` by ``scripts/gen_sources_md.py``)."""
    env = ", ".join(f"`{e}`" for e in plan.env) if plan.env else "—"
    needs = {"open": "No", "free_key": "A free key", "paid": "A paid key"}.get(plan.access, "No")
    reads = "TODO: one line on what this source reads"
    return f"| `{plan.source_id}` | {reads} | {plan.lane} | {needs} | {env} |"


__all__ = [
    "ScaffoldPlan",
    "render_connector",
    "render_docs_row",
    "render_pyproject_extra",
    "render_test",
]
