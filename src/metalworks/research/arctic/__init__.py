"""Arctic Shift data-access subtree: submission corpus reader + comment API.

Submissions come from the Hugging Face ``open-index/arctic`` Parquet mirror via
:class:`ArcticReader` (DuckDB-over-Parquet, ``[arctic]`` extra); comments come
from the live Arctic Shift API via :class:`ArcticShiftApiClient` (the HF comment
tree is stale). :func:`hydrate_submissions` / :func:`hydrate_comments` persist
the post-triage subset through ``ResearchDeps.corpus``.

NOTE: the source's Supabase Storage *mirror* reader (the optional perf tier
behind ``metalworks[supabase]``) is intentionally NOT ported here — see
``reader.py`` for the TODO. The HF/local-Parquet path is the only source.
"""

from metalworks.research.arctic.api import ArcticShiftApiClient
from metalworks.research.arctic.hydration import hydrate_comments, hydrate_submissions
from metalworks.research.arctic.reader import ArcticReader

__all__ = [
    "ArcticReader",
    "ArcticShiftApiClient",
    "hydrate_comments",
    "hydrate_submissions",
]
