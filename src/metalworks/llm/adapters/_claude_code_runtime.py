"""Shared async→sync runtime for the Claude Code adapters (chat + search).

The Claude Agent SDK is async-only; metalworks' ``ChatModel`` / ``SearchProvider``
protocols are sync and called from a thread pool. One shared background event loop
(a daemon thread, created lazily under a lock) lets concurrent sync callers each
schedule an independent SDK coroutine via ``asyncio.run_coroutine_threadsafe`` and
block for its result. Both adapters share the SAME loop — one daemon thread total.
"""

from __future__ import annotations

import asyncio
import threading

_MODEL_PREFIX = "claude-code/"
_DEFAULT_MODEL = "sonnet"

_loop: asyncio.AbstractEventLoop | None = None
_loop_lock = threading.Lock()


def background_loop() -> asyncio.AbstractEventLoop:
    """The shared daemon event loop, started on first use (double-checked lock)."""
    global _loop
    loop = _loop
    if loop is not None and loop.is_running():
        return loop
    with _loop_lock:
        loop = _loop
        if loop is not None and loop.is_running():
            return loop
        loop = asyncio.new_event_loop()
        thread = threading.Thread(
            target=loop.run_forever, name="metalworks-claude-code", daemon=True
        )
        thread.start()
        _loop = loop
        return loop


def sdk_model(model_id: str) -> str:
    """Map a metalworks ``model_id`` to the SDK ``model`` arg.

    Accepts ``claude-code/sonnet``, a bare alias (``sonnet``/``opus``/``haiku``),
    or a full model id; the ``claude-code/`` prefix is stripped.
    """
    name = model_id.strip()
    if name.startswith(_MODEL_PREFIX):
        name = name[len(_MODEL_PREFIX) :]
    return name or _DEFAULT_MODEL
