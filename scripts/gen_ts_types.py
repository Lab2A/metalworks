"""Generate TypeScript types + JSON-schema snapshots from the contract.

Pydantic is the single source of truth. This emits matching TS interfaces so
web UIs and REST consumers can't drift, plus JSON-schema snapshots that CI
diff-gates. Dependency-free and re-runnable — run it whenever anything in
metalworks/contract/ changes.

Usage:

    python scripts/gen_ts_types.py
        # → ts/contract.ts
        # → src/metalworks/contract/schema/demand_report.schema.json
        # → src/metalworks/contract/schema/research_brief.schema.json

    python scripts/gen_ts_types.py --check
        # exits 1 if the generated files on disk don't match what would be
        # generated now (drift alarm for CI)
"""

from __future__ import annotations

import argparse
import enum
import json
import sys
import types
import typing
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))

from metalworks.contract import (  # noqa: E402
    Assessment,
    AudienceAttribute,
    AudienceProfile,
    BuildPersona,
    BuildSpec,
    CandidateWedge,
    Channel,
    ChannelStrategy,
    ChannelSurfaceType,
    CitationRef,
    ClaimCitation,
    Competitor,
    CompetitorMap,
    ComplianceVerdict,
    CorpusStats,
    CrossReference,
    DataReportAsset,
    DataReportItem,
    Decision,
    DecisionLogEntry,
    DemandReport,
    DesignBrief,
    DesignChoice,
    DesignReview,
    DesignSystem,
    DiscoveryContext,
    EvidenceBackedChoice,
    EvidenceRecord,
    EvidenceRef,
    ExistingSolution,
    ExplorationReport,
    FeatureSpec,
    Fork,
    ForkVerdict,
    GapAnalysis,
    GapClaim,
    IdeaSketch,
    IdeationResult,
    InboxItem,
    InsightCluster,
    Landscape,
    LandscapeSignal,
    LintViolation,
    LogoOption,
    LogoSet,
    MarketSizing,
    Opportunity,
    Persona,
    PersonaSet,
    PivotTarget,
    PositioningBrief,
    PostLintVerdict,
    PriceEvidence,
    PriceFinding,
    PriceHypothesis,
    PricingTier,
    ProductType,
    RedditComment,
    RedditPost,
    ReportSummary,
    Research,
    ResearchBrief,
    ResolvedCitation,
    RunSummary,
    Screen,
    SegmentChoice,
    SignalStrength,
    SlotPlan,
    SourceMapEntry,
    StrengthClaim,
    StyleFinding,
    SubredditIntel,
    SynthesisThresholds,
    TargetSubreddit,
    TriageThresholds,
    ValidationResult,
    WebFinding,
    WedgeClaim,
)

ENUMS: list[type[enum.Enum]] = [
    Fork,
    SignalStrength,
    Decision,
    ChannelSurfaceType,
    ProductType,
]

# Models to emit, in dependency order (leaves first).
MODELS: list[type[BaseModel]] = [
    # research
    EvidenceRef,
    EvidenceRecord,
    CitationRef,
    ResolvedCitation,
    InsightCluster,
    SlotPlan,
    AudienceAttribute,
    AudienceProfile,
    EvidenceBackedChoice,
    SegmentChoice,
    CandidateWedge,
    PriceEvidence,
    PriceFinding,
    SourceMapEntry,
    MarketSizing,
    TargetSubreddit,
    TriageThresholds,
    SynthesisThresholds,
    ResearchBrief,
    WebFinding,
    ExplorationReport,
    CorpusStats,
    CrossReference,
    DemandReport,
    Research,
    ReportSummary,
    RunSummary,
    IdeaSketch,
    IdeationResult,
    # landscape (Pillar A)
    StrengthClaim,
    GapClaim,
    Competitor,
    CompetitorMap,
    ExistingSolution,
    Landscape,
    # assess (GO / PIVOT / NO-GO)
    GapAnalysis,
    PivotTarget,
    ForkVerdict,
    Assessment,
    # validate loop
    DecisionLogEntry,
    ValidationResult,
    # positioning (Pillar B)
    WedgeClaim,
    PriceHypothesis,
    PositioningBrief,
    # surface + screens — product-shape primitives the build spec owns
    Screen,
    DesignBrief,
    # design system (visual) — directional grounding, SAFE/RISK, grounding tier
    LandscapeSignal,
    DesignChoice,
    DesignSystem,
    # design review — deterministic audit of a rendered page
    StyleFinding,
    DesignReview,
    # logo (the mark submodule)
    LogoOption,
    LogoSet,
    # distribution (one pillar; pushes + streams; replaces Pillar F + Pillar G).
    # Rebuilt over D1+; carries the salvaged no-cite-no-claim primitive + the
    # audience-derived channel model.
    ClaimCitation,
    Channel,
    ChannelStrategy,
    DataReportItem,
    DataReportAsset,
    # build (Pillar D)
    FeatureSpec,
    BuildPersona,
    PricingTier,
    BuildSpec,
    # reddit
    ComplianceVerdict,
    LintViolation,
    PostLintVerdict,
    RedditPost,
    RedditComment,
    SubredditIntel,
    InboxItem,
    Opportunity,
    Persona,
    PersonaSet,
    DiscoveryContext,
]

_TS_OUT = _REPO / "ts" / "contract.ts"
_SCHEMA_DIR = _REPO / "src" / "metalworks" / "contract" / "schema"
_SCHEMAS: list[tuple[str, type[BaseModel]]] = [
    ("demand_report.schema.json", DemandReport),
    ("research_brief.schema.json", ResearchBrief),
    ("opportunity.schema.json", Opportunity),
    ("discovery_context.schema.json", DiscoveryContext),
]


def _ts_type(annotation: object) -> tuple[str, bool]:
    """Map a Python annotation to (TS type, nullable?). nullable → `| null` + `?`."""
    origin = typing.get_origin(annotation)

    if origin is typing.Literal:
        args = typing.get_args(annotation)
        union = " | ".join(f'"{a}"' if isinstance(a, str) else str(a) for a in args)
        return union, False

    if origin in (typing.Union, types.UnionType):
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        nullable = len(args) != len(typing.get_args(annotation))
        if len(args) == 1:
            inner, _ = _ts_type(args[0])
        else:
            inner = " | ".join(_ts_type(a)[0] for a in args)
        return inner, nullable

    if origin in (list, typing.List):  # noqa: UP006
        inner, _ = _ts_type(typing.get_args(annotation)[0])
        return f"{inner}[]", False

    if origin is tuple:
        inners = [_ts_type(a)[0] for a in typing.get_args(annotation) if a is not Ellipsis]
        return f"[{', '.join(inners)}]", False

    if origin in (dict, typing.Dict):  # noqa: UP006
        value_t, _ = _ts_type(typing.get_args(annotation)[1])
        return f"Record<string, {value_t}>", False

    if annotation is str:
        return "string", False
    if annotation in (int, float):
        return "number", False
    if annotation is bool:
        return "boolean", False
    if annotation is datetime:
        return "string", False  # ISO 8601 over the wire
    if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
        if annotation in ENUMS:
            return annotation.__name__, False
        members = " | ".join(f'"{m.value}"' for m in annotation)
        return members, False
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation.__name__, False

    return "unknown", False


def _emit_enum(e: type[enum.Enum]) -> str:
    members = " | ".join(f'"{m.value}"' for m in e)
    return f"export type {e.__name__} = {members};"


def _emit_interface(model: type[BaseModel]) -> str:
    lines = [f"export interface {model.__name__} {{"]
    for name, field in model.model_fields.items():
        ts, nullable = _ts_type(field.annotation)
        optional = "?" if (nullable or not field.is_required()) else ""
        suffix = " | null" if nullable else ""
        doc = (field.description or "").replace("\n", " ").strip()
        wire_name = field.alias or name
        if doc:
            lines.append(f"  /** {doc} */")
        lines.append(f"  {wire_name}{optional}: {ts}{suffix};")
    # Computed fields (e.g. content-addressed evidence ids) are absent from
    # model_fields but ARE present in the serialized payload (model_dump). The TS
    # twin describes that serialized shape, so emit them. (The JSON-schema
    # snapshots stay validation-mode and omit computed fields — they describe
    # valid *input*, where a computed id is ignored — so the two views differ by
    # design: TS = output shape, schema = input shape.)
    for name, cfield in model.model_computed_fields.items():
        ts, nullable = _ts_type(cfield.return_type)
        suffix = " | null" if nullable else ""
        doc = (cfield.description or "").replace("\n", " ").strip()
        if doc:
            lines.append(f"  /** {doc} */")
        lines.append(f"  {name}: {ts}{suffix};")
    lines.append("}")
    return "\n".join(lines)


def _render() -> tuple[str, dict[str, str]]:
    """Return (typescript_content, {schema_filename: content}) — pure."""
    header = (
        "// GENERATED FILE — do not edit by hand.\n"
        "// Source of truth: metalworks/contract (Python, Pydantic).\n"
        "// Regenerate: python scripts/gen_ts_types.py\n"
    )
    enum_block = "\n".join(_emit_enum(e) for e in ENUMS)
    interface_block = "\n\n".join(_emit_interface(m) for m in MODELS)
    ts = header + "\n" + enum_block + "\n\n" + interface_block + "\n"
    schemas = {
        fname: json.dumps(model.model_json_schema(by_alias=True), indent=2, sort_keys=True) + "\n"
        for fname, model in _SCHEMAS
    }
    return ts, schemas


def cmd_write() -> int:
    ts, schemas = _render()
    _TS_OUT.parent.mkdir(parents=True, exist_ok=True)
    _TS_OUT.write_text(ts)
    _SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"wrote {_TS_OUT}")
    for fname, content in schemas.items():
        (_SCHEMA_DIR / fname).write_text(content)
        print(f"wrote {_SCHEMA_DIR / fname}")
    return 0


def cmd_check() -> int:
    ts, schemas = _render()
    expected: list[tuple[Path, str]] = [(_TS_OUT, ts)]
    expected += [(_SCHEMA_DIR / fname, content) for fname, content in schemas.items()]
    bad = 0
    for path, content in expected:
        if not path.exists():
            print(f"x {path} — does not exist", file=sys.stderr)
            bad += 1
            continue
        if path.read_text() != content:
            print(
                f"x {path} — drifted from the contract.\n    Run: python scripts/gen_ts_types.py",
                file=sys.stderr,
            )
            bad += 1
        else:
            print(f"ok {path.relative_to(_REPO)}")
    if bad:
        return 1
    print(f"\nGENERATED TYPES CHECK PASSED — {len(MODELS)} interfaces + {len(ENUMS)} enums.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Exit 1 on drift.")
    args = parser.parse_args(argv)
    return cmd_check() if args.check else cmd_write()


if __name__ == "__main__":
    sys.exit(main())
