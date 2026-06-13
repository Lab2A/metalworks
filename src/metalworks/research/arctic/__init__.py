"""Arctic Shift data-access subtree: submission corpus reader + comment API.

Submissions come from the Hugging Face ``open-index/arctic`` Parquet mirror via
:class:`ArcticReader` (DuckDB-over-Parquet, ``[arctic]`` extra); comments come
from the live Arctic Shift API via :class:`ArcticShiftApiClient` (the HF comment
tree is stale). :func:`hydrate_submissions` / :func:`hydrate_comments` persist
the post-triage subset through ``ResearchDeps.corpus``.

The Supabase Storage *mirror* reader (the optional perf tier behind
``metalworks[supabase]``) is :class:`ArcticMirrorReader`. Select it at runtime
with ``ARCTIC_SHIFT_SOURCE=mirror`` (the client resolver wires it up) or
construct it directly. It reads a Supabase bucket populated by an upstream
mirror job, removing HF as a runtime dependency.
"""

from metalworks.research.arctic.api import ArcticShiftApiClient
from metalworks.research.arctic.hydration import hydrate_comments, hydrate_submissions
from metalworks.research.arctic.mirror_reader import ArcticMirrorReader
from metalworks.research.arctic.reader import ArcticReader

__all__ = [
    "ArcticMirrorReader",
    "ArcticReader",
    "ArcticShiftApiClient",
    "hydrate_comments",
    "hydrate_submissions",
]
