"""Shared lazy resolution of the per-call LLM timeout budget.

The chat adapters default their ``timeout_s`` parameter to ``None`` and resolve
it here so the env/config knob (``METALWORKS_LLM_TIMEOUT`` →  ``llm_timeout`` →
300.0, see :func:`metalworks.config.llm_timeout_s`) flows through every surface
(CLI, MCP, SDK) without hardcoding the default in any signature. ``config`` is
imported lazily inside the function so importing an adapter module stays cheap.
"""

from __future__ import annotations


def resolve_timeout_s(timeout_s: float | None, *, floor: float | None = None) -> float:
    """Resolve a per-call timeout in seconds.

    When ``timeout_s`` is ``None`` the configurable default is read lazily from
    :func:`metalworks.config.llm_timeout_s`. ``floor`` raises the result to at
    least that many seconds — grounding keeps a higher minimum than plain text.
    """
    if timeout_s is None:
        from metalworks.config import llm_timeout_s

        timeout_s = llm_timeout_s()
    if floor is not None and timeout_s < floor:
        return floor
    return timeout_s
