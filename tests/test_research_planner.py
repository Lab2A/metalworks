"""Offline tests for the conversational planner subtree."""

from __future__ import annotations

from typing import Any

import pytest

from metalworks.contract import ResearchBrief, TargetSubreddit
from metalworks.llm import FakeChatModel
from metalworks.research.deps import ResearchDeps
from metalworks.research.planner import (
    QUESTIONS,
    BriefState,
    DecisionBrief,
    InMemoryBriefStates,
    Option,
    assemble_brief,
    brief_from_question,
    brief_or_question,
    pick_target_subreddits,
    provide_content,
)
from metalworks.research.planner.question_bank import find_question, next_decision_id
from metalworks.research.planner.subreddit_picker import _PickerOutput, _Suggestion
from metalworks.stores.memory import MemoryStores


def _deps(chat: FakeChatModel) -> ResearchDeps:
    from metalworks.embeddings import FakeEmbedding

    class _Reader:
        def latest_available_month(self, content_type: str = "submissions") -> Any:
            from metalworks.research.types import MonthRef

            return MonthRef(2026, 2)

        def pull_subreddit(self, **_kwargs: Any) -> Any:
            return iter(())

        def fetch_submissions_by_ids(self, *_args: Any, **_kwargs: Any) -> Any:
            return iter(())

        def close(self) -> None:
            return None

    return ResearchDeps(
        chat=chat,
        embeddings=FakeEmbedding(),
        corpus=MemoryStores(),
        reader=_Reader(),
    )


def _valid_brief(decision_id: str = "D1") -> DecisionBrief:
    return DecisionBrief(
        decision_id=decision_id,
        header=f"{decision_id} · Test",
        eli10="x" * 90,
        stakes="Things break if we pick wrong here.",
        recommendation="Recommendation: do the thing because it is good.",
        options=[
            Option(
                label="Yes",
                pros=[
                    "This is a sufficiently long pro string to pass validation here ok",
                    "Another sufficiently long pro string to clear the two-pro minimum",
                ],
                cons=["This is a sufficiently long con string to pass validation here ok"],
                net="Net positive.",
                is_recommended=True,
            ),
            Option(
                label="No",
                pros=[
                    "This is a sufficiently long pro string to pass validation here ok",
                    "Another sufficiently long pro string to clear the two-pro minimum",
                ],
                cons=["This is a sufficiently long con string to pass validation here ok"],
                net="Net negative.",
            ),
        ],
    )


# ── question bank ────────────────────────────────────────────────────────


def test_question_bank_shape() -> None:
    assert [q.decision_id for q in QUESTIONS] == [f"D{i}" for i in range(1, 9)]
    assert find_question("D5") is not None
    assert find_question("D5").multi_select is True  # type: ignore[union-attr]
    assert next_decision_id("D1") == "D2"
    assert next_decision_id("D8") is None


# ── provide_content ──────────────────────────────────────────────────────


def test_provide_content_returns_scripted_brief() -> None:
    chat = FakeChatModel()
    chat.script(DecisionBrief, _valid_brief("D1"))
    deps = _deps(chat)
    spec = find_question("D1")
    assert spec is not None
    out = provide_content(deps, question_spec=spec, prompt="sleep supplements", prior_answers={})
    assert isinstance(out, DecisionBrief)
    assert out.decision_id == "D1"


def test_provide_content_falls_back_on_llm_failure() -> None:
    # FakeChatModel with no script raises AssertionError -> fallback kicks in.
    chat = FakeChatModel()
    deps = _deps(chat)
    spec = find_question("D6")
    assert spec is not None
    out = provide_content(deps, question_spec=spec, prompt="p", prior_answers={})
    assert isinstance(out, DecisionBrief)
    assert out.decision_id == "D6"
    assert out.header == spec.header_chip
    # Exactly one recommended option in the canned fallback.
    assert sum(1 for o in out.options if o.is_recommended) == 1


def test_provide_content_fallback_covers_every_question() -> None:
    chat = FakeChatModel()  # never scripted -> always falls back
    deps = _deps(chat)
    for q in QUESTIONS:
        out = provide_content(deps, question_spec=q, prompt="p", prior_answers={})
        assert out.decision_id == q.decision_id
        assert out.multi_select == q.multi_select


# ── subreddit picker ─────────────────────────────────────────────────────


def _brief_with_subs(subs: list[TargetSubreddit]) -> ResearchBrief:
    return ResearchBrief(
        brief_id="b1",
        question="Will people buy a sleep supplement?",
        decision_context="Validating a v0",
        success_criteria=["clear verdict"],
        must_address=["price point"],
        target_subreddits=subs,
        web_research_directions=["pricing"],
        relevance_rubric="rubric",
    )


def test_subreddit_picker_appends_and_dedupes() -> None:
    chat = FakeChatModel()
    chat.script(
        _PickerOutput,
        _PickerOutput(
            suggestions=[
                _Suggestion(name="Insomnia", rationale="sleep talk"),
                _Suggestion(name="supplements", rationale="dup, case-insensitive"),
                _Suggestion(name="r/Nootropics", rationale="strip prefix"),
            ]
        ),
    )
    deps = _deps(chat)
    brief = _brief_with_subs([TargetSubreddit(name="Supplements", rationale="user")])
    result = pick_target_subreddits(deps, brief=brief)
    names = [s.name for s in result]
    # user's sub first, dup dropped, prefix stripped
    assert names[0] == "Supplements"
    assert "Insomnia" in names
    assert "Nootropics" in names
    assert names.count("Supplements") == 1
    # never mutated the brief
    assert [s.name for s in brief.target_subreddits] == ["Supplements"]


def test_subreddit_picker_falls_back_on_failure() -> None:
    chat = FakeChatModel()  # no script -> raises -> fallback to user list
    deps = _deps(chat)
    subs = [TargetSubreddit(name="Supplements", rationale="user")]
    brief = _brief_with_subs(subs)
    result = pick_target_subreddits(deps, brief=brief)
    assert [s.name for s in result] == ["Supplements"]


def test_subreddit_picker_respects_cap() -> None:
    chat = FakeChatModel()
    subs = [TargetSubreddit(name=f"sub{i}", rationale="u") for i in range(8)]
    brief = _brief_with_subs(subs)
    result = pick_target_subreddits(deps=_deps(chat), brief=brief, max_total=8)
    assert len(result) == 8


# ── brief assembler ──────────────────────────────────────────────────────


def test_assemble_brief_from_answers() -> None:
    chat = FakeChatModel()
    chat.script(_PickerOutput, _PickerOutput(suggestions=[]))
    deps = _deps(chat)
    states = InMemoryBriefStates()
    state = states.create(prompt="Is there demand for a sleep supplement?")
    state.answers = {
        "D1": {"custom_text": "Will GenZ buy a melatonin gummy?"},
        "D2": {"selected_labels": ["Should we build this v0 at all"]},
        "D3": {"selected_labels": ["Surfaces what consumers say", "Names competitors"]},
        "D4": {"selected_labels": ["What price point will the audience accept"]},
        "D5": {"custom_text": "Supplements, r/Nootropics"},
        "D6": {"selected_labels": ["24 months"]},
        "D7": {"selected_labels": ["Competitive landscape and pricing"]},
        "D8": {"selected_labels": ["Full report at investment-grade confidence"]},
    }
    brief = assemble_brief(deps, state=state)
    assert isinstance(brief, ResearchBrief)
    assert brief.question == "Will GenZ buy a melatonin gummy?"
    assert brief.decision_context == "Should we build this v0 at all"
    assert brief.success_criteria == ["Surfaces what consumers say", "Names competitors"]
    assert brief.time_window_months == 24
    assert brief.output_template == "full"
    # investment-grade -> HIGH
    from metalworks.contract import SignalStrength

    assert brief.confidence_threshold == SignalStrength.HIGH
    # D5 custom subs parsed, prefix stripped
    names = {s.name for s in brief.target_subreddits}
    assert {"Supplements", "Nootropics"} <= names
    assert brief.brief_id == state.brief_id


def test_assemble_brief_defaults_when_sparse() -> None:
    chat = FakeChatModel()
    chat.script(_PickerOutput, _PickerOutput(suggestions=[]))
    deps = _deps(chat)
    state = BriefState(brief_id="b9", prompt="some prompt")
    brief = assemble_brief(deps, state=state)
    # falls back to prompt for the question, sensible defaults elsewhere
    assert brief.question == "some prompt"
    assert brief.time_window_months == 12
    assert brief.web_research_directions == ["Competitive landscape and pricing"]
    assert brief.success_criteria  # non-empty default


# ── store ────────────────────────────────────────────────────────────────


def test_in_memory_brief_states_roundtrip() -> None:
    states = InMemoryBriefStates()
    s = states.create(prompt="p")
    assert states.get(s.brief_id) is s
    s.status = "finalized"
    states.save(s)
    assert states.get(s.brief_id).status == "finalized"  # type: ignore[union-attr]
    assert len(states.list()) == 1
    assert states.get("missing") is None


def test_decision_brief_validates_recommended_count() -> None:
    with pytest.raises(ValueError, match="is_recommended"):
        DecisionBrief(
            decision_id="D1",
            header="h",
            eli10="x" * 90,
            stakes="s",
            recommendation="r",
            options=[
                Option(
                    label="A",
                    pros=[
                        "a sufficiently long pro string here to pass the length validator yes",
                        "a second sufficiently long pro string here to clear the minimum count",
                    ],
                    cons=["a sufficiently long con string here to pass the length validator yes"],
                    net="n",
                    is_recommended=False,
                ),
                Option(
                    label="B",
                    pros=[
                        "a sufficiently long pro string here to pass the length validator yes",
                        "a second sufficiently long pro string here to clear the minimum count",
                    ],
                    cons=["a sufficiently long con string here to pass the length validator yes"],
                    net="n",
                    is_recommended=False,
                ),
            ],
        )


# ── brief_from_question (the lightweight --question path) ────────────────────


def test_brief_from_question_uses_explicit_subreddits() -> None:
    deps = _deps(FakeChatModel())
    brief = brief_from_question(
        deps,
        "demand for a focus supplement?",
        subreddits=["Supplements", "Nootropics"],
        time_window_months=6,
    )
    assert brief.question == "demand for a focus supplement?"
    assert [t.name for t in brief.target_subreddits] == ["Supplements", "Nootropics"]
    assert brief.time_window_months == 6
    assert brief.relevance_rubric.endswith("demand for a focus supplement?")


def test_brief_from_question_invokes_picker_when_subreddits_omitted() -> None:
    # Unscripted FakeChatModel → the picker raises and falls back, but the brief
    # still assembles with a default 12-month window.
    deps = _deps(FakeChatModel())
    brief = brief_from_question(deps, "is there demand for X?")
    assert brief.question == "is there demand for X?"
    assert brief.time_window_months == 12
    assert isinstance(brief.target_subreddits, list)


# ── brief_or_question (the one shared brief-fallback) ────────────────────────


def test_brief_or_question_returns_existing_brief_unchanged() -> None:
    # When a brief is supplied, the helper returns it verbatim — no model call,
    # no fabricated fallback.
    deps = _deps(FakeChatModel())
    existing = ResearchBrief(
        brief_id="b-1",
        question="pre-built",
        decision_context="ctx",
        success_criteria=["c"],
        must_address=[],
        target_subreddits=[TargetSubreddit(name="preset", rationale="given")],
        web_research_directions=[],
        relevance_rubric="r",
        time_window_months=3,
    )
    out = brief_or_question(deps, existing, "ignored question", subreddits=["unused"])
    assert out is existing


def test_brief_or_question_builds_from_question_when_brief_is_none() -> None:
    deps = _deps(FakeChatModel())
    out = brief_or_question(deps, None, "demand for a focus supplement?", subreddits=["Nootropics"])
    assert out.question == "demand for a focus supplement?"
    assert [t.name for t in out.target_subreddits] == ["Nootropics"]
