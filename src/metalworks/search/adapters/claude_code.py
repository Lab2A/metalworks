"""Claude Code SearchProvider (``metalworks[claude-code]``).

Keyless web search via the Claude Agent SDK's `WebSearch` tool — the search
analogue of the keyless chat floor (see ``llm/adapters/claude_code.py``). Returns
``SearchResult{url, title, snippet}`` that the web-research stage grounds exactly
the way it grounds Exa/Tavily hits (the ``_external_search`` rung extracts verbatim
findings from the snippets).

**Grounding posture (no-cite-no-claim).** Native web-search citations are not
reachable through the SDK (it drops the Messages-API ``citations`` array), so this
reconstructs grounding the way research agents do: it captures the URLs the
`WebSearch` tool actually returned, asks the model for structured
``{url, title, snippet}`` results, and **drops any result whose URL is not one of
the real hits** — so an invented URL can never enter the corpus. The snippet is the
model's faithful summary of a real hit; downstream extraction still requires a
verbatim anchor from it.
"""

from __future__ import annotations

import asyncio
import importlib
import re
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import Any, ClassVar, cast

from metalworks.errors import MetalworksError, MissingExtraError
from metalworks.llm.adapters._claude_code_runtime import background_loop, sdk_model
from metalworks.llm.adapters._timeout import resolve_timeout_s
from metalworks.search import PROTOCOL_VERSION, SearchResult

# Real source URLs are parsed out of the WebSearch tool-result content (which
# carries a `Links: [{"title","url"}, ...]` block) to validate the model's output.
_URL_RE = re.compile(r'https?://[^\s"\\<>)\]]+')

# Web search is slower than a plain completion (search turns + synthesis), so the
# per-call budget keeps a higher floor — same posture as grounded calls elsewhere.
_WEB_FLOOR_S = 300.0

_MAX_TURNS = 6

# A FLAT json-schema (no ``$ref``/``$defs``) — the CLI's ``output_format`` accepts
# this reliably, where a nested pydantic ``model_json_schema()`` would emit refs.
_HITS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "title": {"type": "string"},
                    "snippet": {"type": "string"},
                },
                "required": ["url", "title", "snippet"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}


def _norm(url: str) -> str:
    """Normalize a URL for hit-membership comparison (trailing slash / whitespace)."""
    return url.strip().rstrip("/")


class ClaudeCodeSearch:
    """SearchProvider over Claude Code's keyless `WebSearch` tool."""

    protocol_version: ClassVar[str] = PROTOCOL_VERSION
    provider_id: str = "claude-code"

    def __init__(self, *, model_id: str = "claude-code/sonnet") -> None:
        try:
            sdk = importlib.import_module("claude_agent_sdk")
        except ImportError as exc:
            raise MissingExtraError("claude-code", package="claude-agent-sdk") from exc
        self._sdk: Any = sdk
        self._query: Any = sdk.query
        self._Options: Any = sdk.ClaudeAgentOptions
        self._ResultMessage: Any = sdk.ResultMessage
        self._model = sdk_model(model_id)

    def search(
        self,
        *,
        query: str,
        max_results: int = 10,
        recency_days: int | None = None,
    ) -> list[SearchResult]:
        timeout_s = resolve_timeout_s(None, floor=_WEB_FLOOR_S)
        recency = (
            f" Prefer pages published in the last {recency_days} days." if recency_days else ""
        )
        prompt = (
            f"Use the WebSearch tool to find up to {max_results} relevant, credible web pages "
            f"about: {query}.{recency} Then return them as JSON. For each result give its exact "
            "url (copied verbatim from the search results), its title, and a faithful 1-3 sentence "
            "snippet of what the page says. Only include results you actually found via WebSearch."
        )
        options = self._Options(
            allowed_tools=["WebSearch"],
            max_turns=_MAX_TURNS,
            permission_mode="bypassPermissions",
            system_prompt="You are a web search tool. Search the web and return only real results.",
            model=self._model,
            output_format={"type": "json_schema", "schema": _HITS_SCHEMA},
        )
        real_urls, result = self._run(prompt, options, timeout_s)
        return self._assemble(real_urls, result, max_results)

    # ── internal ──

    def _run(self, prompt: str, options: Any, timeout_s: float) -> tuple[set[str], Any]:
        """Drive one agentic WebSearch run; return (real hit URLs, final ResultMessage)."""

        async def _drive() -> tuple[set[str], Any]:
            real: set[str] = set()
            final: Any = None
            async for message in self._query(prompt=prompt, options=options):
                blocks: Any = getattr(message, "content", None) or []
                for block in blocks:
                    if type(block).__name__ == "ToolResultBlock":
                        content: Any = getattr(block, "content", "")
                        text = content if isinstance(content, str) else str(content)
                        real.update(_URL_RE.findall(text))
                if isinstance(message, self._ResultMessage):
                    final = message
            return real, final

        loop = background_loop()
        future = asyncio.run_coroutine_threadsafe(_drive(), loop)
        try:
            return future.result(timeout=timeout_s)
        except FuturesTimeoutError as exc:
            future.cancel()
            raise MetalworksError(
                f"Claude Code web search exceeded the {timeout_s:.0f}s timeout.",
                fix="Raise METALWORKS_LLM_TIMEOUT, or set EXA_API_KEY for a faster search path.",
            ) from exc
        except Exception as exc:
            raise MetalworksError(
                f"Claude Code web search failed ({type(exc).__name__}): {str(exc)[:200]}",
                fix="Make sure the `claude` CLI is installed and logged in, or set a search key.",
            ) from exc

    def _assemble(self, real_urls: set[str], result: Any, max_results: int) -> list[SearchResult]:
        """Validate the model's structured hits against the real WebSearch URLs."""
        raw: Any = getattr(result, "structured_output", None) if result is not None else None
        raw_results: list[Any] = []
        if isinstance(raw, dict):
            value = cast("dict[str, Any]", raw).get("results")
            if isinstance(value, list):
                raw_results = cast("list[Any]", value)

        real_norm = {_norm(u) for u in real_urls}
        out: list[SearchResult] = []
        seen: set[str] = set()
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            hit = cast("dict[str, Any]", item)
            url = str(hit.get("url", "")).strip()
            key = _norm(url)
            # no-cite-no-claim: keep only URLs the WebSearch tool actually returned.
            if not url or key not in real_norm or key in seen:
                continue
            seen.add(key)
            out.append(
                SearchResult(
                    url=url,
                    title=str(hit.get("title", "")).strip(),
                    snippet=str(hit.get("snippet", "")).strip(),
                )
            )
            if len(out) >= max_results:
                break

        # Fallback: structured extraction yielded nothing usable — still return the
        # real hit URLs (bare), so the run degrades to URL-only grounding, never to
        # an invented source.
        if not out:
            for url in sorted(real_urls)[:max_results]:
                out.append(SearchResult(url=url, title="", snippet=""))
        return out
