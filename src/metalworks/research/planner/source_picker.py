"""Brief-aware source selector + per-target picker registry (the 0.4 chassis).

Going wide on sources moves the risk from "we only have Reddit" to "something
picks which 3-5 of N sources to trust per brief." This module is that picker. It
reads the declarative :class:`~metalworks.research.sources.SourceSpec` registry
(``SOURCE_SPECS``) and turns a :class:`~metalworks.contract.ResearchBrief` into an
ordered, **access-gated**, **relevance-ranked** source id list — then a
:class:`~metalworks.contract.SourceSelection` that also names what it *skipped*
(no key) and whether it fell back to the **non-removable floor**.

Two-stage selection
--------------------
1. **Deterministic access gate** (pure, no LLM): a source is reachable when its
   ``auth`` is ``none`` (open / free, no key) OR any of its declared ``env`` vars
   is set in the environment. An authed source with none of its keys set is
   *skipped*, carrying the :class:`~metalworks.errors.MissingKeyError`-shaped
   ``env_var`` / ``fix`` so a pre-flight line can tell the operator what to set.
2. **LLM relevance ranking** on each reachable source's ``relevance_hint``
   (append-only, same posture as the subreddit picker): the model ranks the
   reachable ids; on any failure we keep the deterministic (registry) order. The
   ranking only *reorders* the gated set — it can never add an unreachable source.

The non-removable floor
-----------------------
When the gated ranking yields nothing — e.g. a brief that matches only paid
sources with no keys set — :func:`select_sources` falls back to the configured
default (or ``reddit``) with a *distinct caveat*. A run never produces an empty
corpus blamed on subreddits; the floor is the review's hard acceptance criterion.

Per-target picker registry
---------------------------
Each non-``none`` ``targeting`` value a source declares needs a picker that turns
a brief into the per-target knobs (which subreddits / which Discourse instance /
which company board / which keyword). The existing subreddit picker is the
``"subreddit"`` entry; ``instance`` / ``slug`` / ``keyword`` register stubs here
until their connectors' content registries land (out of scope for 0.4). The
``test_targeting_picker_conformance`` guardrail fails if a registered source
declares a targeting with no registered picker.
"""

from __future__ import annotations

import logging
import os
import re
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, Field

from metalworks.contract import SkippedSource, SourceSelection
from metalworks.errors import MissingKeyError
from metalworks.research.sources.spec import SOURCE_SPECS, Targeting

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

    from metalworks.contract import ResearchBrief
    from metalworks.research.deps import ResearchDeps
    from metalworks.research.sources.spec import SourceSpec

logger = logging.getLogger(__name__)

# The non-removable floor: when the gated ranking is empty, the run falls back to
# this id (an open, keyless grounding source) rather than an empty corpus.
FLOOR_SOURCE = "reddit"


# ── Per-target picker registry ───────────────────────────────────────────────


class TargetPicker(Protocol):
    """A picker that turns a brief into the per-target knobs for one targeting kind.

    The canonical example is the subreddit picker (``targeting == "subreddit"``):
    it appends LLM-suggested on-topic subreddits to the brief's listed ones. A
    ``keyword`` picker would derive query terms; an ``instance`` picker would pick
    which Discourse/StackExchange host; a ``slug`` picker which company board.
    Pickers return source-specific objects, so this Protocol is intentionally
    untyped on the return — the registry is a dispatch table, not a contract.
    """

    def __call__(self, deps: ResearchDeps, *, brief: ResearchBrief) -> object: ...


_TARGET_PICKERS: dict[Targeting, TargetPicker] = {}


def register_target_picker(targeting: Targeting, picker: TargetPicker) -> None:
    """Register ``picker`` for a ``targeting`` kind (idempotent on re-import).

    Re-registering the same kind overwrites — module re-imports under pytest must
    not raise, and a downstream override is intentional. ``targeting == "none"``
    needs no picker (the source has no per-target knob), so registering one is a
    no-op-friendly but pointless call; the conformance guardrail only requires a
    picker for the non-``none`` kinds a registered source actually declares.
    """
    _TARGET_PICKERS[targeting] = picker


def target_picker_for(targeting: Targeting) -> TargetPicker | None:
    """The registered picker for ``targeting``, or ``None`` when none is registered."""
    return _TARGET_PICKERS.get(targeting)


def registered_targetings() -> frozenset[Targeting]:
    """The set of targeting kinds that currently have a registered picker."""
    return frozenset(_TARGET_PICKERS)


# ── Per-target picker stubs (real content registries are out of 0.4 scope) ───


def _keyword_picker(deps: ResearchDeps, *, brief: ResearchBrief) -> list[str]:
    """Derive keyword query terms for a keyword-targeted source.

    Stub: the brief's question is the query a keyword source pulls on today (the
    HN / web connectors already pull on the question text). A future revision can
    expand this into ranked term variants; for 0.4 it just satisfies conformance
    and returns a one-element list so the dispatch table is total.
    """
    return [brief.question]


# A small, well-known set of Stack Exchange site api-params the picker ranks over.
# Not exhaustive (SE has 170+); these are the B2B/role-bearing sites a demand brief
# most often wants. ``stackoverflow`` is the non-removable default (always first).
_SE_DEFAULT_SITE = "stackoverflow"
_SE_KNOWN_SITES: tuple[str, ...] = (
    "stackoverflow",
    "serverfault",
    "superuser",
    "dba",
    "security",
    "softwareengineering",
    "devops",
    "salesforce",
    "sharepoint",
    "magento",
    "wordpress",
    "datascience",
    "ai",
    "stats",
    "networkengineering",
    "webmasters",
    "ux",
    "sysadmin",
)


class _SiteSuggestion(BaseModel):
    site: str = Field(
        description="A Stack Exchange site api-param (e.g. 'serverfault', 'dba', 'security')."
    )


class _SitePickerOutput(BaseModel):
    sites: list[_SiteSuggestion] = Field(
        default_factory=list["_SiteSuggestion"],
        description="Candidate Stack Exchange sites for the brief, most relevant first.",
    )


_SE_SITE_SYSTEM = (
    "You are a Stack Exchange research scout. Given a research brief, name the Stack Exchange "
    "sites (by their api site-param, e.g. 'serverfault', 'dba', 'security', 'salesforce', "
    "'softwareengineering') whose Q&A is most likely to discuss THIS brief's topic.\n"
    "\n"
    "Hard rules:\n"
    "1. Return only real Stack Exchange api site-params (the subdomain before "
    "'.stackexchange.com', or 'stackoverflow' / 'serverfault' / 'superuser').\n"
    "2. Order most-relevant first. Prefer the role/topic site over the catch-all: a sysadmin/"
    "cloud brief favors 'serverfault' or 'devops'; a database brief 'dba'; a security brief "
    "'security'; a generic programming brief 'stackoverflow'.\n"
    "3. Return 1-4 sites; fewer is better than padding with weak picks."
)


def _instance_picker(deps: ResearchDeps, *, brief: ResearchBrief) -> list[str]:
    """Pick which Stack Exchange site(s) to pull from for ``brief``.

    Append-only over the default (the same posture as the subreddit picker): the
    list ALWAYS leads with ``stackoverflow`` (the non-removable floor site), then
    appends LLM-suggested role/topic sites (``serverfault`` / ``dba`` / ``security``
    …) deduped, in the model's relevance order. On any LLM failure — or no key — it
    degrades to ``[stackoverflow]`` so a run never has an empty instance list. The
    connector reads the first entry as its ``site=`` per source.
    """
    ranked: list[str] = [_SE_DEFAULT_SITE]
    seen = {_SE_DEFAULT_SITE}
    known = set(_SE_KNOWN_SITES)
    try:
        out = deps.chat.complete_structured(
            system=_SE_SITE_SYSTEM,
            user=(
                f"RESEARCH QUESTION:\n{brief.question}\n\n"
                f"DECISION CONTEXT:\n{brief.decision_context}\n\n"
                "Name the Stack Exchange sites whose Q&A best covers this topic."
            ),
            output_model=_SitePickerOutput,
            max_tokens=512,
            temperature=0.2,
        )
    except Exception as exc:
        logger.debug("source_picker: SE instance ranking failed (%s); default site only", exc)
        return ranked
    for s in out.sites:
        site = (s.site or "").strip().lower().removesuffix(".stackexchange.com")
        # Only accept known site-params — the model occasionally invents one.
        if site in known and site not in seen:
            seen.add(site)
            ranked.append(site)
    return ranked


# A small, seeded set of well-known public Discourse forums the picker ranks over
# until the web-discovery lane can answer "which Discourse discusses X" (Phase 4,
# out of scope here). ``meta.discourse.org`` is the non-removable default (always
# first) — Discourse's own forum, always public. The connector reads the first
# entry as its ``instance=`` host per source; brief-named hosts append after these.
_DISCOURSE_DEFAULT_INSTANCE = "meta.discourse.org"
_DISCOURSE_SEED_INSTANCES: tuple[str, ...] = (
    "meta.discourse.org",
    "community.openai.com",
    "discuss.huggingface.co",
    "forum.obsidian.md",
    "community.home-assistant.io",
    "forums.docker.com",
    "discourse.julialang.org",
    "forum.rclone.org",
)

# A loose host shape: ``label.label[.label…]`` with no scheme/path/whitespace. Used
# to accept a brief-named forum host the model surfaces without trusting arbitrary
# free text as a URL.
_HOST_RE = re.compile(r"^(?=.{4,253}$)([a-z0-9-]+\.)+[a-z]{2,}$")


def discourse_instances(brief_hosts: Sequence[str] | None = None) -> list[str]:
    """Candidate Discourse hosts for a brief: the seed list plus any brief-named hosts.

    Append-only over the seeded default (the same posture as the SE site picker):
    the list ALWAYS leads with ``meta.discourse.org`` (the non-removable floor host,
    Discourse's own public forum), then the rest of the seed list, then any
    brief-named hosts that look like a real host — deduped, normalized to a bare
    lowercase host (scheme / path / ``www.`` stripped). The connector reads the
    first entry as its ``instance=`` per source. Host discovery proper (which
    Discourse discusses X) is the web-discovery lane's job (Phase 4); for now this
    is the curated seed + brief-named hosts.
    """
    ranked: list[str] = []
    seen: set[str] = set()

    def _add(raw: str) -> None:
        host = raw.strip().lower()
        host = host.partition("://")[2] or host  # drop a scheme if present
        host = host.split("/", 1)[0].removeprefix("www.").rstrip(".")
        if host and host not in seen and _HOST_RE.match(host):
            seen.add(host)
            ranked.append(host)

    for host in _DISCOURSE_SEED_INSTANCES:
        _add(host)
    for host in brief_hosts or ():
        _add(host)
    return ranked or [_DISCOURSE_DEFAULT_INSTANCE]


def _slug_picker(deps: ResearchDeps, *, brief: ResearchBrief) -> list[str]:
    """Pick which company board / Product Hunt slug to pull (stub).

    The Product Hunt connector pulls by category slug; deriving the right slug
    from a brief is its own content registry, out of 0.4 scope. The stub keeps the
    dispatch table total and returns an empty list until that lands.
    """
    return []


# ── Deterministic access gate ────────────────────────────────────────────────


def _has_key(spec: SourceSpec) -> bool:
    """Whether the source's auth is satisfied in the current environment.

    Open / keyless sources (``auth == "none"``) are always reachable. An authed
    source (``key`` / ``oauth`` / ``paid``) is reachable when ANY of its declared
    ``env`` vars is set — a source that accepts either of two keys is reachable
    with either. A ``blocked`` access source is never first-class reachable here.
    """
    if spec.access == "blocked":
        return False
    if spec.auth == "none":
        return True
    return any(os.environ.get(var) for var in spec.env)


def _skipped_from(spec: SourceSpec) -> SkippedSource:
    """Build the :class:`SkippedSource` row for an unreachable authed source.

    Reuses :class:`~metalworks.errors.MissingKeyError`'s ``env_var`` / ``fix``
    shape so the pre-flight line is the same wording the rest of the system uses
    for a missing credential.
    """
    env_label = " / ".join(spec.env) if spec.env else ""
    err = MissingKeyError(env_label or spec.source_id, provider=spec.source_id)
    return SkippedSource(
        source_id=spec.source_id,
        reason="no key",
        env_var=env_label,
        fix=err.fix or "",
    )


def _gate(specs: list[SourceSpec]) -> tuple[list[SourceSpec], list[SkippedSource]]:
    """Split candidate specs into (reachable, skipped) by the access gate."""
    reachable: list[SourceSpec] = []
    skipped: list[SkippedSource] = []
    for spec in specs:
        if _has_key(spec):
            reachable.append(spec)
        elif spec.access != "blocked":
            # An authed source we can't reach for lack of a key — surface it so the
            # operator can unlock it. A ``blocked`` source is silently web-only, not
            # a "set a key" case, so it is neither reachable nor a skipped-key row.
            skipped.append(_skipped_from(spec))
    return reachable, skipped


# ── LLM relevance ranking (append-only; deterministic order on failure) ──────


class _Ranked(BaseModel):
    source_id: str = Field(description="A source id from the provided candidate list.")


class _RankingOutput(BaseModel):
    ranked: list[_Ranked] = Field(
        default_factory=list["_Ranked"],
        description="Candidate source ids in descending relevance for the brief.",
    )


_RANK_SYSTEM = (
    "You are a research source scout. Given a research brief and a list of candidate "
    "data sources (each with a one-line description of what it provides), rank the sources "
    "from most to least relevant to answering THIS brief.\n"
    "\n"
    "Hard rules:\n"
    "1. Only return ids from the provided candidate list — never invent a source.\n"
    "2. Rank by how directly the source's data answers the brief's question, not by general "
    "popularity. A consumer-pain brief favors community sources; a 'what already ships' brief "
    "favors product/launch sources.\n"
    "3. You may omit a source you judge irrelevant, but prefer ranking all candidates — the "
    "caller appends any you omit in registry order, so omission only deprioritizes."
)


def _rank_prompt(brief: ResearchBrief, specs: list[SourceSpec]) -> str:
    lines = "\n".join(f"- {s.source_id}: {s.relevance_hint}" for s in specs)
    return (
        f"RESEARCH QUESTION:\n{brief.question}\n\n"
        f"DECISION CONTEXT:\n{brief.decision_context}\n\n"
        f"CANDIDATE SOURCES:\n{lines}\n\n"
        "Rank these source ids from most to least relevant to the question."
    )


def _rank(deps: ResearchDeps, brief: ResearchBrief, specs: list[SourceSpec]) -> list[str]:
    """LLM-rank the reachable specs; fall back to registry order on any failure.

    Append-only: every reachable id is returned exactly once. The LLM only
    reorders — ids it ranks come first (in its order), then any it omitted follow
    in the candidate (registry) order, so nothing reachable is ever dropped.
    """
    candidate_ids = [s.source_id for s in specs]
    if len(candidate_ids) <= 1:
        return candidate_ids
    try:
        out = deps.chat.complete_structured(
            system=_RANK_SYSTEM,
            user=_rank_prompt(brief, specs),
            output_model=_RankingOutput,
            max_tokens=2048,
            temperature=0.2,
        )
    except Exception as exc:
        logger.debug(
            "source_picker: LLM ranking failed (%s); using registry order of %d sources",
            exc,
            len(candidate_ids),
        )
        return candidate_ids

    allowed = set(candidate_ids)
    ranked: list[str] = []
    seen: set[str] = set()
    for r in out.ranked:
        sid = (r.source_id or "").strip()
        if sid in allowed and sid not in seen:
            seen.add(sid)
            ranked.append(sid)
    # Append any reachable id the model omitted, in registry order (append-only).
    ranked.extend(sid for sid in candidate_ids if sid not in seen)
    return ranked


# ── Public surface ───────────────────────────────────────────────────────────


# The built-in connector modules whose import populates ``SOURCE_SPECS``. The
# specs only register as a side effect of importing the connector module (each
# calls ``register_source`` at module scope), and a bare ``import metalworks``
# imports none of them (lean-core). The selector must see the full registry, so it
# triggers these imports once before reading the specs.
_BUILTIN_SPEC_MODULES = (
    "metalworks.research.sources.arctic",
    "metalworks.research.sources.hackernews",
    "metalworks.research.sources.hn_archive",
    "metalworks.research.sources.producthunt",
    "metalworks.research.sources.stackexchange",
    "metalworks.research.sources.discourse",
    "metalworks.research.sources.web",
)


def _ensure_specs_registered() -> None:
    """Import the built-in connectors so their ``SourceSpec``s are in the registry.

    Idempotent: a re-import is a no-op once the module is loaded. A connector that
    can't import (a missing optional dep at module top — there are none today, the
    SDKs are lazy-imported inside functions) is skipped rather than crashing the
    selector, so a partially-installed environment still selects over what it has.
    """
    import importlib

    for mod in _BUILTIN_SPEC_MODULES:
        try:
            importlib.import_module(mod)
        except Exception as exc:  # pragma: no cover - lean-core keeps tops import-free
            logger.debug("source_picker: could not import %s for its spec (%s)", mod, exc)


def candidate_specs() -> list[SourceSpec]:
    """The registry's specs in a stable (id-sorted) order — the selector's input.

    Triggers the built-in connector imports (so the registry is populated on a lean
    install), then returns the specs id-sorted so the deterministic fallback order
    (when the LLM ranking is skipped or fails) is reproducible across runs, not
    dict-insertion-dependent.
    """
    _ensure_specs_registered()
    return [SOURCE_SPECS[sid] for sid in sorted(SOURCE_SPECS)]


def preflight_skipped(specs: list[SourceSpec] | None = None) -> list[SkippedSource]:
    """The pre-flight "skipped (no key)" rows for the candidate specs.

    Computed from the specs alone (no LLM, no brief) so a surface can print the
    "Skipped (no key): X — set ENV" lines BEFORE any pull. Defaults to the full
    registry when ``specs`` is omitted.
    """
    _, skipped = _gate(specs if specs is not None else candidate_specs())
    return skipped


def preflight_lines(selection: SourceSelection) -> list[str]:
    """Human pre-flight lines for a selection: one "Selected:" + one per skipped.

    The "Skipped (no key): X — set ENV" shape reuses each row's
    :class:`~metalworks.errors.MissingKeyError`-derived ``fix``.
    """
    lines = [f"Selected: {', '.join(selection.selected) or '(none)'}"]
    for s in selection.skipped:
        env = f" — {s.fix}" if s.fix else ""
        lines.append(f"Skipped (no key): {s.source_id}{env}")
    return lines


def pick_sources(deps: ResearchDeps, *, brief: ResearchBrief) -> list[str]:
    """Return the relevance-ranked, access-gated source id list for ``brief``.

    Deterministic access gate first (reachable iff keyless or its key is set),
    then an append-only LLM relevance rank over the reachable set. Returns the
    gated+ranked ids — possibly empty when nothing is reachable; callers that need
    the non-removable floor use :func:`select_sources`.
    """
    reachable, _ = _gate(candidate_specs())
    return _rank(deps, brief, reachable)


def select_sources(
    deps: ResearchDeps, *, brief: ResearchBrief, configured_floor: str | None = None
) -> SourceSelection:
    """The full brief-aware pick with the non-removable floor + skipped rationale.

    Runs :func:`pick_sources`, records what the gate skipped (no key), and — when
    the gated ranking yields nothing — falls back to ``configured_floor`` (else
    :data:`FLOOR_SOURCE` = ``reddit``) with a *distinct* caveat, so a run never
    produces an empty corpus. The returned :class:`SourceSelection` is surfaced on
    the report and drives the pre-flight lines.
    """
    specs = candidate_specs()
    reachable, skipped = _gate(specs)
    selected = _rank(deps, brief, reachable)

    floor_applied = False
    caveat: str | None = None
    if not selected:
        floor = configured_floor or FLOOR_SOURCE
        selected = [floor]
        floor_applied = True
        caveat = (
            f"No source matched the brief's access tier; fell back to {floor}. "
            "Set the keys named in the skipped list to widen the corpus."
        )
        logger.info(
            "source_picker: gated ranking empty (%d skipped for keys); floor=%s",
            len(skipped),
            floor,
        )
    elif skipped:
        names = ", ".join(s.source_id for s in skipped)
        caveat = f"Some sources were skipped for missing keys: {names}."

    rationale = (
        f"Ranked {len(selected)} reachable source(s) for the brief"
        + (f"; {len(skipped)} skipped for missing keys" if skipped else "")
        + ("; floor applied" if floor_applied else "")
        + "."
    )
    return SourceSelection(
        selected=selected,
        skipped=skipped,
        rationale=rationale,
        floor_applied=floor_applied,
        caveat=caveat,
    )


# Register the per-target stubs at import. The ``subreddit`` picker is registered
# in ``planner/__init__.py`` (it lives in ``subreddit_picker.py``; registering it
# here would import that module and risk a cycle). Importing this module is enough
# to make ``keyword`` / ``instance`` / ``slug`` conformant.
register_target_picker("keyword", _keyword_picker)
register_target_picker("instance", _instance_picker)
register_target_picker("slug", _slug_picker)


__all__ = [
    "FLOOR_SOURCE",
    "TargetPicker",
    "candidate_specs",
    "discourse_instances",
    "pick_sources",
    "preflight_lines",
    "preflight_skipped",
    "register_target_picker",
    "registered_targetings",
    "select_sources",
    "target_picker_for",
]
