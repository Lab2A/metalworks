"""Scripted Fake models for the fully-offline demo arc.

``Metalworks.demo()`` runs the WHOLE product arc — research → positioning →
competitors → surface → ux → site → build → launch — with zero API keys and
zero network. Every stage makes structured LLM calls; offline, those calls are
served by a :class:`~metalworks.llm.FakeChatModel` scripted per output_model.

This module builds that scripted model (:func:`build_demo_chat`) and a matching
fake comment source (:class:`DemoComments`). The research-pipeline scripting
mirrors ``tests/test_research_pipeline_e2e.py``; the downstream stage phrasings
mirror the canonical instances in each per-stage test. Every stage phrasing is
scripted as a SINGLE instance (not a FIFO list) so a stage that calls its
phrasing once per surface (launch) never exhausts the queue.

If a stage reaches for an output_model the demo doesn't script,
:class:`DemoChatModel` raises a clean :class:`~metalworks.errors.MetalworksError`
naming the type — the demo covers the full arc with Fakes; anything beyond it
needs a real provider key.
"""
# This offline test-double deliberately scripts the pipeline's internal
# ``_Phrasing`` output models — the same private types the per-stage tests
# construct. They're not part of the public API; reaching for them here is
# intentional, so silence the strict-mode private-usage rule for this file.
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import TYPE_CHECKING, Any, TypeVar

from pydantic import BaseModel

from metalworks.errors import MetalworksError
from metalworks.llm import FakeChatModel, GroundedResult, GroundingChunk, GroundingSupport

if TYPE_CHECKING:
    pass

T = TypeVar("T", bound=BaseModel)


class DemoChatModel(FakeChatModel):
    """A ``FakeChatModel`` that fails *cleanly* on an unscripted type.

    The parent raises a raw ``AssertionError`` (helpful inside tests, noisy as a
    demo). Here, an unscripted ``output_model`` raises a typed
    :class:`~metalworks.errors.MetalworksError` whose message points the user at
    the real-provider path. Scripted (single-instance and list) behavior is
    inherited unchanged.
    """

    def complete_structured(self, *, output_model: type[T], **kwargs: Any) -> T:
        if output_model not in self._structured:
            raise MetalworksError(
                f"The offline demo doesn't script {output_model.__name__}. The demo "
                "covers the full arc with Fake models; for anything beyond it, set a "
                "provider key and use Metalworks().",
                fix="Set a provider key (e.g. ANTHROPIC_API_KEY) and use Metalworks() "
                "instead of Metalworks.demo().",
            )
        return super().complete_structured(output_model=output_model, **kwargs)


class DemoComments:
    """A :class:`~metalworks.research.deps.CommentSource` for the offline demo.

    Yields two distinct, focus-supplement-flavored comments per link so the
    hydrated corpus is non-trivial and the synthesized report reads believably.
    Mirrors the ``_FakeComments`` shape in the e2e test.
    """

    _BODIES: tuple[tuple[str, int], tuple[str, int]] = (
        (
            "I've tried so many focus supplements and the jitters always kill it for me. "
            "Something stim-free that actually works would be an instant buy.",
            44,
        ),
        (
            "Honestly I'd pay for a clean focus product if it didn't wreck my sleep or cost "
            "$60 a bottle. The afternoon crash is the real problem.",
            17,
        ),
    )

    def comments_for_links(self, link_ids: Sequence[str]) -> Iterator[list[dict[str, Any]]]:
        for lid in link_ids:
            yield [
                {
                    "id": f"c_{lid}_a",
                    "link_id": f"t3_{lid}",
                    "subreddit": "Supplements",
                    "body": self._BODIES[0][0],
                    "author": f"commenter_{lid}_a",
                    "score": self._BODIES[0][1],
                    "created_utc": 0.0,
                },
                {
                    "id": f"c_{lid}_b",
                    "link_id": f"t3_{lid}",
                    "subreddit": "Supplements",
                    "body": self._BODIES[1][0],
                    "author": f"commenter_{lid}_b",
                    "score": self._BODIES[1][1],
                    "created_utc": 0.0,
                },
            ]


def build_demo_chat() -> DemoChatModel:
    """A ``DemoChatModel`` scripted for the WHOLE offline arc.

    Research pipeline (mirrors ``_scripted_chat()`` in the e2e test):
    ``_PickerOutput``, ``_BatchVerdicts``, ``_SynthesisOutput``, ``_LLMOutput``,
    plus one grounded web result. Downstream stages (mirrors each per-stage
    test): ``_WedgePhrasing`` + ``_Entailment`` (positioning), ``_CompetitorList``
    + ``_Harvest`` (landscape), ``_SurfacePhrasing`` + ``_UxPhrasing`` (surface),
    ``_SitePhrasing`` (site), ``_AssetPhrasing`` (launch), ``_BuildPhrasing``
    (build).

    Each type is scripted as a SINGLE instance so a stage calling it repeatedly
    (launch: one ``_AssetPhrasing`` per surface) never exhausts a FIFO queue.
    """
    # Imports are local: these private phrasing types live deep in the pipeline,
    # and `import metalworks` must stay light (no eager pipeline import chain).
    from metalworks.build.spec import _BuildPhrasing, _FeatureDraft
    from metalworks.research.exploration.llm_classifier import _BatchVerdicts, _Verdict
    from metalworks.research.landscape import _CompetitorCand, _CompetitorList, _Harvest
    from metalworks.research.launch import _AssetPhrasing, _ClaimDraft
    from metalworks.research.planner.subreddit_picker import _PickerOutput
    from metalworks.research.site import _ConnectivePhrasing, _SectionPhrasing, _SitePhrasing
    from metalworks.research.surface import (
        _RubricItem,
        _ScreenItem,
        _SurfacePhrasing,
        _UxPhrasing,
    )
    from metalworks.research.synthesis.cluster_ranker import _CandidateCluster, _SynthesisOutput
    from metalworks.research.synthesis.positioning import _Entailment, _WedgePhrasing
    from metalworks.research.triangulate.triangulator import (
        _LLMCrossReference,
        _LLMOutput,
    )

    chat = DemoChatModel(grounded=True)

    # ── research pipeline ────────────────────────────────────────────────────
    chat.script(_PickerOutput, _PickerOutput(suggestions=[]))
    chat.script(
        _BatchVerdicts,
        _BatchVerdicts(
            verdicts=[_Verdict(batch_index=i, relevant=True, reason="on_topic") for i in range(50)]
        ),
    )
    chat.script(
        _SynthesisOutput,
        _SynthesisOutput(
            clusters=[
                _CandidateCluster(
                    claim="people want stim-free focus that does not wreck sleep",
                    member_comment_indices=[0, 1],
                    quote_comment_indices=[0, 1],
                )
            ]
        ),
    )
    chat.script(
        _LLMOutput,
        _LLMOutput(
            cross_references=[
                _LLMCrossReference(
                    cluster_id="cluster:1",
                    web_finding_ids=["web:1"],
                    agreement="agree",
                    note="both streams show stim-free demand",
                )
            ],
            # Left empty on purpose: the demo brief's must_address text is
            # auto-generated from the question, so a hard-coded resolution would
            # never match and the triangulator would log three retry-validation
            # warnings into the otherwise-clean demo output.
            must_address_resolutions=[],
        ),
    )
    _web_text = "1. CLAIM: the focus supplement market is growing\n   SPECIFICS: +18% in 2025\n"
    chat.grounded_results.append(
        GroundedResult(
            text=_web_text,
            chunks=(GroundingChunk(uri="https://example.com/report", title="Market Report"),),
            supports=(GroundingSupport(start_char=0, end_char=len(_web_text), chunk_indices=(0,)),),
        )
    )

    # ── positioning (Pillar B) ───────────────────────────────────────────────
    # The wedge quotes a verbatim fragment of a DemoComments body so exact-match
    # grounding resolves it; `unique_attribute` is that fragment.
    _frag = "Something stim-free that actually works would be an instant buy"
    chat.script(
        _WedgePhrasing,
        _WedgePhrasing(
            competitive_alternative="generic caffeine-loaded focus stacks",
            unique_attribute=_frag,
            value="stay focused without the jitters or the afternoon crash",
            market_category="stim-free focus supplement",
        ),
    )
    chat.script(
        _Entailment,
        _Entailment(unique_attribute_supported=True, value_supported=True, note="grounded"),
    )

    # ── landscape (Pillar A) ─────────────────────────────────────────────────
    # Gap text exact-matches a DemoComments body so complaint-matching attaches it.
    _gap = (
        "Honestly I'd pay for a clean focus product if it didn't wreck my sleep or cost "
        "$60 a bottle. The afternoon crash is the real problem."
    )
    chat.script(
        _CompetitorList,
        _CompetitorList(
            competitors=[
                _CompetitorCand(
                    name="Generic energy stacks",
                    kind="direct",
                    one_liner="caffeine-forward focus blends",
                )
            ]
        ),
    )
    chat.script(_Harvest, _Harvest(strengths=["cheap"], gaps=[_gap]))

    # ── surface + ux (Pillar C) ──────────────────────────────────────────────
    chat.script(
        _SurfacePhrasing,
        _SurfacePhrasing(
            chosen="web",
            runner_up="mobile",
            rationale="buyers discover and purchase supplements on the web",
            rubric=[
                _RubricItem(name="where_are_the_users", finding=_frag),
                _RubricItem(name="technical_sophistication", finding=_gap),
                _RubricItem(name="usage_frequency", finding="daily, but guessing"),
                _RubricItem(name="realtime_or_hardware", finding="no special needs"),
                _RubricItem(name="distribution", finding="DTC storefront maybe"),
            ],
            trade_offs=["no native mobile reminders at launch"],
        ),
    )
    chat.script(
        _UxPhrasing,
        _UxPhrasing(
            screens=[
                _ScreenItem(
                    name="Landing",
                    purpose=_frag,
                    primary_action="start order",
                    serves_wedge=True,
                ),
                _ScreenItem(
                    name="Product",
                    purpose=_gap,
                    primary_action="add to cart",
                    serves_wedge=True,
                ),
            ]
        ),
    )

    # ── site (Pillar E) ──────────────────────────────────────────────────────
    chat.script(
        _SitePhrasing,
        _SitePhrasing(
            sections=[
                _SectionPhrasing(
                    cluster_rank=1,
                    role="hero",
                    copy=f"{_frag} — that's what we built.",
                    fragment=_frag,
                ),
            ],
            connective=[_ConnectivePhrasing(role="cta", copy="See if it fits your routine.")],
        ),
    )

    # ── launch (Pillar F) ────────────────────────────────────────────────────
    # ONE instance, returned per surface (DEFAULT_SURFACES) — single-instance
    # scripting means the FIFO queue never exhausts across surfaces.
    _claim = f"People tell us: {_frag}"
    _body = f"We built the stim-free focus supplement Reddit asked for. {_claim}. No jitters."
    chat.script(
        _AssetPhrasing,
        _AssetPhrasing(
            title="The stim-free focus supplement Reddit asked for",
            body=_body,
            variants=["Focus without the jitters"],
            claims=[_ClaimDraft(text=_claim, supporting_quote=_frag)],
        ),
    )

    # ── build (Pillar D) ─────────────────────────────────────────────────────
    chat.script(
        _BuildPhrasing,
        _BuildPhrasing(
            features=[
                _FeatureDraft(
                    feature_id="stim-free-formula",
                    title="Stim-free focus formula",
                    rationale="users want focus without caffeine jitters",
                    source_cluster_rank=1,
                )
            ]
        ),
    )

    return chat


__all__ = ["DemoChatModel", "DemoComments", "build_demo_chat"]
