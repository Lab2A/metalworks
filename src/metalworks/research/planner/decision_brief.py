"""DecisionBrief — one question the conversational planner asks the user.

Ported verbatim from clique-research-api's ``decision_brief.py``. Format
(gstack-style decision brief):

- D<N> header chip
- ELI10 paragraph (>= 80 chars)
- stakes-if-wrong line
- recommendation line with reason
- 2-4 options, each with >= 2 pros (>= 40 chars) and >= 1 con (>= 40 chars)
- net line
- exactly one option marked recommended
- custom-text input always available alongside the picker

Validators enforce these rules at construction, so a malformed brief from the
LLM cannot reach the API surface — the LLM call retries / falls back on
Pydantic ``ValidationError``.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

MIN_PRO_COUNT = 2
MIN_CON_COUNT = 1
MIN_BULLET_CHARS = 40
MIN_OPTIONS = 2
MAX_OPTIONS = 4
MIN_ELI10_CHARS = 80


class Option(BaseModel):
    """One pickable answer to a DecisionBrief."""

    label: str = Field(description="The picker label. Concise, 1-5 words.")
    pros: list[str] = Field(
        description=(
            f"At least {MIN_PRO_COUNT} reasons to pick this, each at least "
            f"{MIN_BULLET_CHARS} chars."
        )
    )
    cons: list[str] = Field(
        description=(
            f"At least {MIN_CON_COUNT} honest reason against, each at least "
            f"{MIN_BULLET_CHARS} chars."
        )
    )
    net: str = Field(description="One-line synthesis of the trade-off if this option is chosen.")
    is_recommended: bool = Field(
        default=False,
        description="Exactly one option per DecisionBrief carries True (enforced at brief level).",
    )

    @field_validator("pros")
    @classmethod
    def validate_pros(cls, v: list[str]) -> list[str]:
        if len(v) < MIN_PRO_COUNT:
            raise ValueError(f"Each option needs at least {MIN_PRO_COUNT} pros, got {len(v)}")
        for i, p in enumerate(v):
            if len(p.strip()) < MIN_BULLET_CHARS:
                raise ValueError(
                    f"Pro #{i + 1} is {len(p.strip())} chars; need at least {MIN_BULLET_CHARS}"
                )
        return v

    @field_validator("cons")
    @classmethod
    def validate_cons(cls, v: list[str]) -> list[str]:
        if len(v) < MIN_CON_COUNT:
            raise ValueError(f"Each option needs at least {MIN_CON_COUNT} con, got {len(v)}")
        for i, c in enumerate(v):
            if len(c.strip()) < MIN_BULLET_CHARS:
                raise ValueError(
                    f"Con #{i + 1} is {len(c.strip())} chars; need at least {MIN_BULLET_CHARS}"
                )
        return v


class DecisionBrief(BaseModel):
    """One question in the planner conversation."""

    decision_id: str = Field(description="'D1' through 'D8'.")
    header: str = Field(description="Header chip text, e.g. 'D2 · Time window'.")
    eli10: str = Field(
        description=(
            f"Plain-English explanation of what's being decided. At least {MIN_ELI10_CHARS} chars."
        )
    )
    stakes: str = Field(description="One sentence on what breaks if we pick wrong.")
    recommendation: str = Field(
        description="One-line recommendation with reason, e.g. 'Recommendation: 12 months…'."
    )
    options: list[Option] = Field(
        description=f"{MIN_OPTIONS}-{MAX_OPTIONS} options. Exactly one has is_recommended=True."
    )
    multi_select: bool = Field(
        default=False,
        description="When True, the user may pick multiple options. Used for D3/D4/D7 (lists).",
    )
    custom_text_allowed: bool = Field(
        default=True,
        description="Always True — the custom-text input is the truth tap.",
    )

    @field_validator("eli10")
    @classmethod
    def validate_eli10(cls, v: str) -> str:
        if len(v.strip()) < MIN_ELI10_CHARS:
            raise ValueError(f"ELI10 is {len(v.strip())} chars; need at least {MIN_ELI10_CHARS}")
        return v

    @field_validator("options")
    @classmethod
    def validate_option_count(cls, v: list[Option]) -> list[Option]:
        if not (MIN_OPTIONS <= len(v) <= MAX_OPTIONS):
            raise ValueError(f"Need {MIN_OPTIONS}-{MAX_OPTIONS} options, got {len(v)}")
        return v

    @model_validator(mode="after")
    def validate_exactly_one_recommended(self) -> DecisionBrief:
        recommended_count = sum(1 for o in self.options if o.is_recommended)
        if recommended_count != 1:
            raise ValueError(
                f"Exactly one option must have is_recommended=True, found {recommended_count}"
            )
        return self
