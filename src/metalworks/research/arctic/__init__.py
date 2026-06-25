"""Arctic Shift data-access subtree: submission corpus reader + comment API.

Submissions come, by DEFAULT, from the live Arctic Shift posts API via
:class:`ArcticShiftReader` (``/posts/search`` + ``/posts/ids``, core ``httpx``,
no extra, current month included). Comments come from the same live API via
:class:`ArcticShiftApiClient` (the HF comment tree is stale to 2021-04).
:func:`hydrate_submissions` / :func:`hydrate_comments` persist the post-triage
subset through ``ResearchDeps.corpus``.

Two opt-in reader tiers exist for offline / bulk work, selected at runtime by
``ARCTIC_SHIFT_SOURCE`` (see :func:`metalworks.config.resolve_corpus_reader`):
``hf`` → :class:`ArcticReader`, the Hugging Face ``open-index/arctic`` Parquet
mirror (DuckDB-over-Parquet, ``[arctic]`` extra); ``mirror`` →
:class:`ArcticMirrorReader`, a Supabase Storage mirror (``[supabase]`` extra)
populated by an upstream job. Both lag the live API and require their extra.
"""

from metalworks.research.arctic.api import ArcticShiftApiClient
from metalworks.research.arctic.api_reader import ArcticShiftReader
from metalworks.research.arctic.hydration import hydrate_comments, hydrate_submissions
from metalworks.research.arctic.mirror_reader import ArcticMirrorReader
from metalworks.research.arctic.reader import ArcticReader

__all__ = [
    "ArcticMirrorReader",
    "ArcticReader",
    "ArcticShiftApiClient",
    "ArcticShiftReader",
    "hydrate_comments",
    "hydrate_submissions",
]
