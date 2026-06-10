"""Structured-output normalization ladder.

All adapters funnel structured output through these helpers so callers never
see which extraction mechanism ran:

  1. Native schema mode (provider-enforced JSON schema) — used when
     `capabilities.native_structured` and the adapter implements it.
  2. Forced tool call — one tool whose input schema is the Pydantic schema,
     tool_choice forced; arguments are validated.
  3. Prompt-embedded schema — schema in the prompt, first JSON object
     extracted, ONE retry with the validation error appended.

Every path ends in `output_model.model_validate(...)`. On final failure the
caller gets a typed StructuredOutputError, never a raw ValidationError.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, TypeVar

from pydantic import BaseModel, ValidationError

from metalworks.errors import StructuredOutputError

if TYPE_CHECKING:
    from collections.abc import Callable

T = TypeVar("T", bound=BaseModel)


def validate_payload(model_id: str, output_model: type[T], payload: Any) -> T:
    """Final step of every ladder path: pydantic validation with typed errors."""
    try:
        if isinstance(payload, str):
            return output_model.model_validate_json(payload)
        return output_model.model_validate(payload)
    except ValidationError as exc:
        raise StructuredOutputError(model_id, _summarize_validation_error(exc)) from exc


def extract_first_json_object(text: str) -> str:
    """Pull the first balanced JSON object/array out of free-form model text.

    Handles markdown fences and leading prose. Raises ValueError when no
    JSON-looking region exists.
    """
    # Strip common fences first.
    stripped = text.strip()
    if stripped.startswith("```"):
        first_newline = stripped.find("\n")
        if first_newline != -1:
            stripped = stripped[first_newline + 1 :]
        if stripped.rstrip().endswith("```"):
            stripped = stripped.rstrip()[:-3]

    start_candidates = [i for i in (stripped.find("{"), stripped.find("[")) if i != -1]
    if not start_candidates:
        raise ValueError("no JSON object found in model output")
    start = min(start_candidates)

    depth = 0
    in_string = False
    escape = False
    opener = stripped[start]
    closer = "}" if opener == "{" else "]"
    for i in range(start, len(stripped)):
        ch = stripped[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return stripped[start : i + 1]
    raise ValueError("unbalanced JSON in model output")


def prompt_embedded_structured(
    *,
    model_id: str,
    output_model: type[T],
    complete_text: Callable[[str], str],
    user: str,
) -> T:
    """Ladder tier 3: schema-in-prompt with one validation-feedback retry.

    `complete_text` is a single-arg closure over the adapter's text
    completion (the adapter binds system/max_tokens/etc.).
    """
    schema = json.dumps(output_model.model_json_schema(), indent=None)
    ask = (
        f"{user}\n\n"
        "Respond with ONLY a JSON object matching this JSON Schema — no prose, "
        f"no markdown fences:\n{schema}"
    )
    text = complete_text(ask)
    try:
        return validate_payload(model_id, output_model, extract_first_json_object(text))
    except (StructuredOutputError, ValueError) as first_error:
        retry_ask = (
            f"{ask}\n\n"
            f"Your previous response was invalid: {first_error}\n"
            "Return ONLY the corrected JSON object."
        )
        text = complete_text(retry_ask)
        try:
            return validate_payload(model_id, output_model, extract_first_json_object(text))
        except ValueError as exc:
            raise StructuredOutputError(model_id, str(exc)) from exc


def _summarize_validation_error(exc: ValidationError) -> str:
    parts: list[str] = []
    for err in exc.errors()[:5]:
        loc = ".".join(str(p) for p in err.get("loc", ()))
        parts.append(f"{loc}: {err.get('msg', 'invalid')}")
    more = len(exc.errors()) - 5
    if more > 0:
        parts.append(f"(+{more} more)")
    return "; ".join(parts)
