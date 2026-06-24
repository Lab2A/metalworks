"""Generate ``docs/sources.md`` from the source registry (``SOURCE_SPECS``).

The source catalog is no longer hand-maintained. Each connector declares its
lane / auth / access / env / relevance hint in a :class:`SourceSpec` and
self-registers on import; this script imports the built-in connector modules so
:data:`~metalworks.research.sources.SOURCE_SPECS` is fully populated, then renders
the "What's available" table from it. The surrounding prose (how to pick a
source, ranking, BYO) is static and emitted verbatim, so the whole file is
deterministic and CI can diff-gate it — exactly like ``scripts/gen_ts_types.py``.

Usage:

    python scripts/gen_sources_md.py
        # → docs/sources.md (regenerated from SOURCE_SPECS)

    python scripts/gen_sources_md.py --check
        # exits 1 if docs/sources.md on disk differs from what would be
        # generated now (drift alarm for CI)
"""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))

from metalworks.research.sources import SOURCE_SPECS, SourceSpec  # noqa: E402

# Connector modules whose import self-registers a source (the same map the CLI's
# lazy ``get_source`` and the spec conformance test use). Importing — not
# constructing — is enough: ``register_source(..., spec=...)`` runs at module
# scope, populating ``SOURCE_SPECS`` without needing live readers/keys.
_CONNECTOR_MODULES: tuple[str, ...] = (
    "metalworks.research.sources.arctic",
    "metalworks.research.sources.hackernews",
    "metalworks.research.sources.hn_archive",
    "metalworks.research.sources.producthunt",
    "metalworks.research.sources.web",
)

# The built-in source ids the shipped catalog documents (every id the modules
# above register). Pinning the set keeps the generated file independent of any
# third-party source registered in the same process — the drift gate stays
# deterministic. When a new built-in connector lands, add its id(s) here.
_BUILTIN_IDS: tuple[str, ...] = (
    "arctic",
    "hackernews",
    "hackernews_archive",
    "hn_archive",
    "producthunt",
    "reddit",
    "web",
)

_OUT = _REPO / "docs" / "sources.md"

# The frontmatter description renders as one physical line in the output, but is
# stored split here so this source file stays under the 100-col lint.
_DESCRIPTION = (
    "Choose where metalworks reads from — Reddit, Hacker News, the web, or your own data. "
    "Turn sources on or off, mix several at once, or plug in your own."
)

_HEADER = f"""\
---
title: "Sources"
description: "{_DESCRIPTION}"
---

<!-- GENERATED FILE — do not edit by hand.
     Source of truth: each connector's SourceSpec (metalworks.research.sources).
     Regenerate: python scripts/gen_sources_md.py -->

**A source is where metalworks reads conversations.** Out of the box it can read from Reddit,
Hacker News, and the web; you can also plug in your own. Read from more than one and you get
more evidence behind every report.
"""

# Static prose emitted verbatim after the generated table.
_BODY = """\
## Pick what to read from

By default metalworks reads Reddit. To use others, name them when you run:

```bash
# read both Reddit and Hacker News for this run
metalworks research run --question "..." --source reddit --source hackernews

# see what's available and reachable (lane / auth / key-status from each SourceSpec)
metalworks sources list

# only sources that need a key, or only one lane
metalworks sources list --needs-key
metalworks sources list --lane web

# turn a source on or off for good (saved to your config)
metalworks sources enable hackernews
metalworks sources disable arctic
```

In Python, pass the sources you want:

```python
from metalworks import Metalworks
from metalworks.research.sources import get_source

mw = Metalworks(sources=[get_source("reddit"), get_source("hackernews")])
report = mw.research("an affordable, jitter-free focus supplement").demand
```

You don't have to set anything up first — a single `mw.research(...)` reads the sources you
chose and produces a report in one call.

## How mixed sources are ranked

When a report draws on more than one source, a need is ranked by **how many different people
raised it** — not by how viral a single post was. Fifty people each mentioning a problem
once outranks one post with five hundred upvotes. Web pages (which have no author) count by
how many different sites raised the point. The upshot: no single source can drown out the
others.

## Add your own source

A source is a small piece of code that fetches items and hands them to metalworks in a common
shape. The fastest way in is to scaffold one:

```bash
metalworks sources scaffold mysource --lane grounding --auth none
```

That writes a connector module (with a filled `SourceSpec` and a `register_signal` block), a
conformance test, prints the `pyproject.toml` extra to add, and the `docs/sources.md` row.
Fill in the `pull` / `comments_for` bodies and you're done — see
[Adding a source connector](https://github.com/Lab2A/metalworks/blob/main/CONTRIBUTING.md) in
`CONTRIBUTING.md` for the worked example. To wire one up by hand instead, copy
`research/sources/template.py`:

```python
from collections.abc import Iterator, Sequence

from metalworks.contract import CorpusComment, CorpusRecord
from metalworks.research.sources import SourceSpec, SourceWindow, register_source


class MySource:
    source_id = "mysource"

    def pull(self, *, query, window, limit=None) -> Iterator[CorpusRecord]:
        # Fetch items and yield them as CorpusRecord (id, url, title, text, …).
        ...

    def comments_for(self, record_ids: Sequence[str]):
        # Return the comments under each item — or None if your source has no comments.
        ...

    def latest_window(self) -> SourceWindow:
        # The most recent time range your source can return.
        ...


register_source(
    "mysource",
    lambda **_: MySource(),
    spec=SourceSpec(
        source_id="mysource",
        lane="grounding",
        signals=("upvotes",),
        targeting="keyword",
        auth="none",
        env=(),
        access="open",
        relevance_hint="what this source is best at surfacing",
    ),
)
```

Once registered, it works like any built-in: `--source mysource`, `get_source("mysource")`, or
`Metalworks(sources=[MySource()])`.

**If your source has no comments** (a web page, a product listing), return `None` from
`comments_for` and add `yields_units = True` to the class. metalworks then treats each item's
own text as the thing people are talking about.

To check your source is wired up correctly, use `metalworks.testing.check_item_source` in your
tests (the scaffold writes one for you).

## Next

- [Your research data](/docs/corpus) — where what you read is saved, and how to update a
  report later.
- [Demand research](/docs/demand-research) — run a report.
- [Use your own data](/docs/custom-corpus) — load conversations you already have.
"""

# How each ``access`` value reads in the human "Needs a key?" column.
_NEEDS_KEY: dict[str, str] = {
    "open": "No",
    "free_key": "A free key",
    "paid": "A paid key",
    "blocked": "No (context only)",
}

# A one-line "Reads" blurb per source id, keyed off the relevance hint when no
# nicer phrasing is known. Built-in ids get a curated line; everything else falls
# back to its declared ``relevance_hint`` so a scaffolded source still documents
# itself without a code change here.
_READS: dict[str, str] = {
    "reddit": "Public Reddit posts and comments",
    "arctic": "A large archive of past Reddit posts — see [Use Reddit's archive](/docs/load-reddit-corpus)",  # noqa: E501
    "hackernews": "Hacker News stories and comments (live)",
    "hackernews_archive": "A large archive of past Hacker News, read offline — see [Use Hacker News offline](/docs/load-hn-corpus)",  # noqa: E501
    "hn_archive": "Alias of `hackernews_archive` (the offline Hacker News archive)",
    "web": "Web pages from a search engine (Exa, Tavily, parallel.ai, or Firecrawl)",
    "producthunt": "Product Hunt launches + their comments",
}


def _md_escape(text: str) -> str:
    """Escape the one Markdown-table metacharacter (``|``) in a cell value."""
    return text.replace("|", "\\|")


def _reads_blurb(spec: SourceSpec) -> str:
    return _READS.get(spec.source_id) or _md_escape(spec.relevance_hint or "Custom source")


def _needs_key(spec: SourceSpec) -> str:
    return _NEEDS_KEY.get(spec.access, "No")


def _catalog_ids() -> list[str]:
    """The built-in source ids this catalog documents (sorted).

    Restricted to the known built-in ids — NOT every entry in the live
    ``SOURCE_SPECS`` — so a third-party (or test-registered) source in the same
    process can't drift the committed file. A third-party source carries its own
    catalog row; the shipped docs cover the built-ins. Specs must be loaded first
    (``_load_specs``) so every id resolves.
    """
    return sorted(i for i in _BUILTIN_IDS if i in SOURCE_SPECS)


def _catalog_table() -> str:
    """Render the "What's available" table from the built-in specs (sorted by id)."""
    lines = [
        "## What's available",
        "",
        "| Name | Reads | Lane | Needs a key? | Env |",
        "| --- | --- | --- | --- | --- |",
    ]
    for source_id in _catalog_ids():
        spec = SOURCE_SPECS[source_id]
        env = ", ".join(f"`{e}`" for e in spec.env) if spec.env else "—"
        lines.append(
            f"| `{source_id}` | {_reads_blurb(spec)} | {spec.lane} | {_needs_key(spec)} | {env} |"
        )
    return "\n".join(lines)


def _load_specs() -> None:
    """Import every connector module so the built-in specs are populated."""
    for module in _CONNECTOR_MODULES:
        importlib.import_module(module)


def _rel(path: Path) -> str:
    """``path`` relative to the repo when possible, else its plain string."""
    try:
        return str(path.relative_to(_REPO))
    except ValueError:
        return str(path)


def _render() -> str:
    """Return the full ``docs/sources.md`` content — pure (after specs loaded)."""
    return f"{_HEADER}\n{_catalog_table()}\n\n{_BODY}"


def cmd_write() -> int:
    _load_specs()
    content = _render()
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(content)
    print(f"wrote {_rel(_OUT)} ({len(SOURCE_SPECS)} sources)")
    return 0


def cmd_check() -> int:
    _load_specs()
    content = _render()
    if not _OUT.exists():
        print(f"x {_OUT} — does not exist", file=sys.stderr)
        return 1
    if _OUT.read_text() != content:
        print(
            f"x {_rel(_OUT)} — drifted from SOURCE_SPECS.\n"
            "    Run: python scripts/gen_sources_md.py",
            file=sys.stderr,
        )
        return 1
    print(f"ok {_rel(_OUT)} — {len(SOURCE_SPECS)} sources in catalog.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Exit 1 on drift.")
    args = parser.parse_args(argv)
    return cmd_check() if args.check else cmd_write()


if __name__ == "__main__":
    sys.exit(main())
