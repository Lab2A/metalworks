"""Protocol-layer tests: ladder helpers, fake conformance, error envelopes."""

import pytest
from pydantic import BaseModel

from metalworks.errors import (
    EmbeddingModelMismatch,
    GroundingUnavailable,
    MissingExtraError,
    MissingKeyError,
    StructuredOutputError,
)
from metalworks.llm import (
    ChatModel,
    FakeChatModel,
    GroundedChatModel,
    GroundedResult,
    GroundingChunk,
    GroundingSupport,
)
from metalworks.llm.structured import (
    extract_first_json_object,
    prompt_embedded_structured,
    validate_payload,
)


class Verdict(BaseModel):
    keep: bool
    reason: str


def test_fake_satisfies_protocols() -> None:
    fake = FakeChatModel(grounded=True)
    assert isinstance(fake, ChatModel)
    assert isinstance(fake, GroundedChatModel)
    assert fake.capabilities.native_grounding


def test_fake_structured_scripting() -> None:
    fake = FakeChatModel().script(Verdict, Verdict(keep=True, reason="relevant"))
    out = fake.complete_structured(system="s", user="u", output_model=Verdict)
    assert out.keep is True
    assert fake.calls[0]["kind"] == "structured"


def test_fake_grounded_requires_capability() -> None:
    fake = FakeChatModel(grounded=False)
    with pytest.raises(GroundingUnavailable):
        fake.complete_grounded(system="s", user="u")


def test_grounded_result_carries_supports() -> None:
    """The provenance contract: chunks + char-offset supports, not flat citations."""
    r = GroundedResult(
        text="Prices rose 12% in 2025.",
        chunks=(GroundingChunk(uri="https://example.com/a", title="A"),),
        supports=(GroundingSupport(start_char=0, end_char=24, chunk_indices=(0,)),),
    )
    span = r.text[r.supports[0].start_char : r.supports[0].end_char]
    assert span == "Prices rose 12% in 2025."
    assert r.chunks[r.supports[0].chunk_indices[0]].uri == "https://example.com/a"


def test_extract_first_json_object_handles_fences_and_prose() -> None:
    assert extract_first_json_object('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert extract_first_json_object('Here you go: {"a": {"b": [1, 2]}} trailing') == (
        '{"a": {"b": [1, 2]}}'
    )
    assert extract_first_json_object('{"s": "brace } in string"}') == '{"s": "brace } in string"}'
    with pytest.raises(ValueError, match="no JSON object"):
        extract_first_json_object("no json here")


def test_validate_payload_wraps_validation_errors() -> None:
    with pytest.raises(StructuredOutputError) as exc_info:
        validate_payload("m", Verdict, '{"keep": "not-a-bool-at-all", "reason": 5}')
    assert exc_info.value.error_code == "structured_output"


def test_prompt_embedded_ladder_retries_once_with_feedback() -> None:
    responses = iter(["not json at all", '{"keep": false, "reason": "fixed on retry"}'])
    prompts: list[str] = []
    budgets: list[int] = []

    def complete(prompt: str, max_tokens: int) -> str:
        prompts.append(prompt)
        budgets.append(max_tokens)
        return next(responses)

    out = prompt_embedded_structured(
        model_id="m",
        output_model=Verdict,
        complete_text=complete,
        user="judge this",
        max_tokens=1024,
    )
    assert out.reason == "fixed on retry"
    assert len(prompts) == 2
    assert "previous response was invalid" in prompts[1]
    # The retry asks for a BIGGER token budget — a truncated reasoning-model
    # response needs more room, not the same room re-tried.
    assert budgets == [1024, 8192]


def test_prompt_embedded_ladder_fails_typed_after_retry() -> None:
    def complete(prompt: str, max_tokens: int) -> str:
        return "still not json"

    with pytest.raises(StructuredOutputError):
        prompt_embedded_structured(
            model_id="m", output_model=Verdict, complete_text=complete, user="judge"
        )


def test_error_envelopes_are_actionable() -> None:
    """Every error a host model sees must carry a fix it can relay verbatim."""
    cases = [
        MissingExtraError("anthropic"),
        MissingKeyError("ANTHROPIC_API_KEY", provider="Anthropic"),
        GroundingUnavailable("openai/gpt-x"),
        EmbeddingModelMismatch(index_model="a", current_model="b"),
    ]
    for err in cases:
        env = err.envelope()
        assert env["error_code"]
        assert env["message"]
        assert env["fix"], f"{type(err).__name__} has no actionable fix"
    assert 'pip install "metalworks[anthropic]"' in str(MissingExtraError("anthropic").fix)
