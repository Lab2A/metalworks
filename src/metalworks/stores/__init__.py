"""Storage layer: typed repo protocols + zero-infra backends.

The typed repos ARE the protocol (no public generic doc-store — see
repos.py for why). `MemoryStores` and `SqliteStores` each satisfy all six
repo protocols structurally. Hosted backends (e.g. a Postgres impl for a
SaaS deployment) live downstream in the consuming app and bind to the same
protocols — that downstream-impl path is exactly what the seam is for, so the
OSS core ships only the two zero-infra backends.
"""

from metalworks.stores.crypto import TokenCipher
from metalworks.stores.memory import MemoryStores
from metalworks.stores.repos import (
    PROTOCOL_VERSION,
    AccountRepo,
    BriefRepo,
    CorpusRepo,
    InboxRepo,
    OpportunityRepo,
    OpportunityStatus,
    RunRepo,
    StoredRedditAccount,
)
from metalworks.stores.sqlite import SqliteStores

__all__ = [
    "PROTOCOL_VERSION",
    "AccountRepo",
    "BriefRepo",
    "CorpusRepo",
    "InboxRepo",
    "MemoryStores",
    "OpportunityRepo",
    "OpportunityStatus",
    "RunRepo",
    "SqliteStores",
    "StoredRedditAccount",
    "TokenCipher",
]
