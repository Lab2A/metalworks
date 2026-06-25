"""Storage layer: typed repo protocols + zero-infra backends.

The typed repos ARE the protocol (no public generic doc-store — see
repos.py for why). `MemoryStores` and `SqliteStores` each satisfy the six
substrate repo protocols structurally. Tier-2 pillar artifacts use a separate
`ArtifactStore` protocol whose default backend is `FileStore` (markdown+json on
disk), since deliverables belong in the user's repo as files, not a db blob.
Hosted backends (e.g. a Postgres impl for a SaaS deployment) live downstream in
the consuming app and bind to the same protocols — that downstream-impl path is
exactly what the seam is for, so the OSS core ships only the zero-infra backends.
"""

from metalworks.stores.crypto import TokenCipher
from metalworks.stores.filestore import FileStore
from metalworks.stores.memory import MemoryStores
from metalworks.stores.repos import (
    PROTOCOL_VERSION,
    AccountRepo,
    ArtifactStore,
    BriefRepo,
    CheckpointRepo,
    CorpusRepo,
    InboxRepo,
    OpportunityRepo,
    OpportunityStatus,
    RunRepo,
    StoredArtifact,
    StoredRedditAccount,
)
from metalworks.stores.sqlite import SqliteStores

__all__ = [
    "PROTOCOL_VERSION",
    "AccountRepo",
    "ArtifactStore",
    "BriefRepo",
    "CheckpointRepo",
    "CorpusRepo",
    "FileStore",
    "InboxRepo",
    "MemoryStores",
    "OpportunityRepo",
    "OpportunityStatus",
    "RunRepo",
    "SqliteStores",
    "StoredArtifact",
    "StoredRedditAccount",
    "TokenCipher",
]
