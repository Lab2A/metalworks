"""Local posting audit log.

Posting is the one irreversible action in metalworks, so every attempt is
recorded locally as a JSON line in ``~/.metalworks/post-log.jsonl``: the
permalink/url, a timestamp, the account, whether it succeeded, and (when the
caller gated the text) the compliance verdict. Writing is best-effort — a
failure to log never propagates into the caller's posting path.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_POST_LOG = Path.home() / ".metalworks" / "post-log.jsonl"


def append_post_log(entry: dict[str, Any], *, path: Path | None = None) -> Path:
    """Append one record (stamped with a UTC timestamp) to the audit log.

    Returns the log path. Never raises: an unwritable home directory degrades
    to a no-op so it can't break a post that already happened.
    """
    log_path = path or DEFAULT_POST_LOG
    record = {"ts": datetime.now(UTC).isoformat(), **entry}
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError:
        pass
    return log_path


__all__ = ["DEFAULT_POST_LOG", "append_post_log"]
