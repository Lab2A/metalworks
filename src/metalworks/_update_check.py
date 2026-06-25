"""Cached, offline-safe PyPI update check.

Mirrors the discipline a gstack skill preamble uses: a once-daily cached probe of
PyPI for a newer ``metalworks`` release, disable-able via the ``update_check``
config setting, snooze-able with a marker file, and SILENT on any failure
(offline, timeout, parse error → ``None``).

Hard rules (there is a test that ``import metalworks`` stays free + offline):

- This module is NEVER imported at ``import metalworks`` time and NEVER hits the
  network on import. ``httpx`` is lazy-imported inside the fetch function only.
- Any network / parse / timeout error returns ``None`` — the report still works
  offline. The cache caps PyPI hits at roughly once per day.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from metalworks.contract import UpdateStatus

_PYPI_URL = "https://pypi.org/pypi/metalworks/json"
_TTL_SECONDS = 24 * 60 * 60  # once-daily
_TIMEOUT_SECONDS = 3.0


def _home() -> Path:
    """The ``~/.metalworks`` state directory (created on demand)."""
    return Path.home() / ".metalworks"


def _cache_path() -> Path:
    return _home() / "last-update-check"


def _snooze_path() -> Path:
    return _home() / "update-snoozed"


def _disabled() -> bool:
    """True when ``update_check = false`` is set in the config."""
    # Imported here (not at module top) so this stays a leaf with no import-time
    # config read; config itself does no network or env work on import.
    from metalworks import config

    value = config.setting("update_check")
    return value is not None and value.strip().lower() in ("false", "0", "no", "off")


def _snoozed() -> bool:
    """True when the snooze marker exists (the user asked to be left alone)."""
    try:
        return _snooze_path().exists()
    except OSError:
        return False


def snooze() -> None:
    """Write the snooze marker so the update line stays quiet until it's cleared."""
    try:
        _home().mkdir(parents=True, exist_ok=True)
        _snooze_path().write_text(str(int(time.time())), encoding="utf-8")
    except OSError:
        pass


def _read_cache() -> tuple[str, float] | None:
    """Return ``(latest_seen, epoch)`` from the cache, or ``None`` when absent/bad."""
    try:
        raw = _cache_path().read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(raw)
        latest = data["latest"]
        checked = float(data["checked_at"])
    except (ValueError, KeyError, TypeError):
        return None
    if not isinstance(latest, str):
        return None
    return latest, checked


def _write_cache(latest: str) -> None:
    try:
        _home().mkdir(parents=True, exist_ok=True)
        _cache_path().write_text(
            json.dumps({"latest": latest, "checked_at": int(time.time())}),
            encoding="utf-8",
        )
    except OSError:
        pass


def _fetch_latest() -> str | None:
    """Fetch the latest version string from PyPI, or ``None`` on any failure.

    ``httpx`` is imported HERE (lazily) so importing this module never pulls it
    and never touches the network. Every error path is swallowed — offline,
    timeout, non-200, malformed JSON all return ``None``.
    """
    try:
        import httpx
    except ImportError:
        return None
    try:
        response = httpx.get(_PYPI_URL, timeout=_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
        version = data["info"]["version"]
    except Exception:
        return None
    return version if isinstance(version, str) and version else None


def _version_tuple(version: str) -> tuple[int, ...]:
    """A best-effort numeric tuple for comparison; non-numeric tails are dropped."""
    parts: list[int] = []
    for chunk in version.split("."):
        digits = ""
        for ch in chunk:
            if ch.isdigit():
                digits += ch
            else:
                break
        if digits == "":
            break
        parts.append(int(digits))
    return tuple(parts)


def _is_newer(latest: str, installed: str) -> bool:
    """True when ``latest`` is a strictly newer release than ``installed``."""
    lt, it = _version_tuple(latest), _version_tuple(installed)
    if lt and it:
        return lt > it
    # Fall back to a string compare only when parsing failed for either side.
    return latest != installed


def check_for_update(*, force: bool = False) -> UpdateStatus | None:
    """Compare the installed version against PyPI's latest; cached + offline-safe.

    Returns an :class:`~metalworks.contract.UpdateStatus` ONLY when a strictly
    newer release is available. Returns ``None`` when up-to-date, disabled,
    snoozed, offline, or on any error. ``force=True`` bypasses the snooze and the
    cache TTL (it still respects ``update_check = false``).

    Cached in ``~/.metalworks/last-update-check`` with a ~24h TTL, so a healthy
    install hits PyPI at most once per day.
    """
    import metalworks

    if _disabled():
        return None
    if _snoozed() and not force:
        return None

    installed = metalworks.__version__
    cached = _read_cache()
    latest: str | None = None

    fresh = cached is not None and (time.time() - cached[1]) < _TTL_SECONDS
    if cached is not None and fresh and not force:
        latest = cached[0]
    else:
        fetched = _fetch_latest()
        if fetched is not None:
            latest = fetched
            _write_cache(fetched)
        elif cached is not None:
            # Offline / transient failure: fall back to the last value we saw so a
            # known update keeps surfacing, but never invent one.
            latest = cached[0]

    if not latest:
        return None
    if not _is_newer(latest, installed):
        return None

    from metalworks.contract import UpdateStatus

    return UpdateStatus(installed=installed, latest=latest, update_available=True)
