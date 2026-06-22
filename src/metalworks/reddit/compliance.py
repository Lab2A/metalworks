"""Deterministic compliance gate — the zero-key safety check on reply/post text.

The deterministic compliance heuristic layer.
Pure and dependency-free (no LLM, no network), so it ships as a zero-key MCP
tool and runs on every keystroke if a UI wants it.

Two entry points:
- `heuristic_check(reply_text, subreddit_rules=None)` → ComplianceVerdict for a
  comment/reply. Returns pass/fail + confidence; a confidence < 0.7 is the
  signal for a caller to escalate to the optional LLM judge (which lands with
  the discovery loop, M4).
- `heuristic_check_post(...)` → PostLintVerdict for a self-post draft, with
  structured per-violation codes/severities/spans for inline editor display.

The em-dash homoglyph family and AI-tell phrase lists are deliberately broad:
the gate can't be trivially evaded by telling a model "no em-dashes". The
reply-gate AI-tell denylist lives in `reddit.stylebook` (shared with the
generator prompt) and is a cheap *first pass* — the authentic-voice gate is the
LLM judge (`discovery.judge`), which the discovery pipeline escalates a pass to.
"""

from __future__ import annotations

import re
from typing import Any

from metalworks.contract import ComplianceVerdict, LintViolation, PostLintVerdict
from metalworks.reddit.stylebook import AI_TELL_REGEX as _AI_TELL_REGEX

# ── Comment/reply gate ─────────────────────────────────────────────────────

# The AI-tell phrase denylist (`_AI_TELL_REGEX`) is the single source in
# `reddit.stylebook`, shared with the generator prompt so the two can't drift.
# It is a cheap deterministic first pass, not the authentic-voice gate — that is
# the LLM judge (`discovery.judge`), which the pipeline escalates a pass to.
_CTA_REGEX = re.compile(r"\b(check out|sign up|try (it|us)|click)\b", re.IGNORECASE)


def heuristic_check(reply_text: str, subreddit_rules: list[str] | None = None) -> ComplianceVerdict:
    """Free, deterministic reply check.

    - pass=True, high confidence → ship, skip the LLM judge
    - pass=False, high confidence → reject, regenerate
    - pass=True/False, confidence < ~0.7 → caller should escalate to the LLM judge

    `subreddit_rules` is accepted for parity with the source signature; the
    deterministic layer does not currently key off it (the LLM judge does).
    """
    _ = subreddit_rules  # reserved for the LLM-judge escalation path
    violations: list[str] = []

    if not reply_text or not reply_text.strip():
        return ComplianceVerdict.model_validate(
            {"pass": False, "violations": ["empty"], "confidence": 1.0}
        )

    ai_hits = _AI_TELL_REGEX.findall(reply_text)
    if ai_hits:
        flat = sorted({(m.lower() if isinstance(m, str) else str(m)) for m in ai_hits})
        violations.append(f"AI-tells: {flat[:3]}")

    if "—" in reply_text:
        violations.append("em-dash present (AI-tell)")

    text_lower = reply_text.lower()
    promo = (
        text_lower.count("our product")
        + text_lower.count("our platform")
        + text_lower.count("our tool")
    )
    if promo >= 2:
        violations.append("over-promotional: product mentioned multiple times")

    n_chars = len(reply_text.strip())
    if n_chars < 30:
        violations.append(f"too short ({n_chars} chars)")
    elif n_chars > 3000:
        violations.append(f"too long ({n_chars} chars)")

    if violations:
        return ComplianceVerdict.model_validate(
            {"pass": False, "violations": violations, "confidence": 0.9}
        )

    confidence = 0.95
    if 30 <= n_chars < 80:
        confidence = 0.7  # very short — might be vapid
    if _CTA_REGEX.search(text_lower):
        confidence = 0.6  # CTA verbs — borderline, caller may escalate
    return ComplianceVerdict.model_validate(
        {"pass": True, "violations": [], "confidence": confidence}
    )


# ── Post-draft lint ────────────────────────────────────────────────────────

_TITLE_MIN_CHARS = 30
_TITLE_DEFAULT_MAX_CHARS = 300  # Reddit's hard cap on submission titles
_BODY_MIN_CHARS = 100
_BODY_DEFAULT_MAX_CHARS = 40_000  # Reddit's hard cap on self-post bodies

# Em-dash homoglyph family: em-dash (U+2014), en-dash (U+2013), and " - "
# (spaced hyphen) — all three are one violation type so the lint can't be
# evaded by telling a model "no em-dashes".
_EMDASH_HOMOGLYPHS = re.compile(r"[—–]| - ")  # noqa: RUF001 - the en-dash is the homoglyph we detect

_POST_AI_TELLS = [
    r"\bnavigate the (landscape|complexity|nuances)\b",
    r"\bin today'?s (digital|modern|fast-paced|ever-changing)\b",
    r"\btapestry of\b",
    r"\bdelve into\b",
    r"\bIt is (important|crucial|essential) to (note|understand|recognize)\b",
    r"\bAt the end of the day\b",
    r"\b(crucial|pivotal|robust|comprehensive|nuanced|multifaceted)\b",
    r"\bAs an AI\b",
    r"\bIn conclusion\b",
    r"\b(furthermore|moreover|additionally)\b",
]
_POST_AI_TELL_REGEX = re.compile("|".join(_POST_AI_TELLS), re.IGNORECASE)

_FIRST_PERSON_VERB_REGEX = re.compile(
    r"\bI\s+(am|was|built|made|did|tried|learned|noticed|found|wrote|spent|"
    r"started|launched|shipped|wanted)\b",
    re.IGNORECASE,
)


def _first_sentence(text: str) -> str:
    text = (text or "").lstrip()
    if not text:
        return ""
    m = re.search(r"[.!?](?:\s|$)", text)
    return text[: m.end()] if m else text


def _scan_emdash(field: str, text: str) -> list[LintViolation]:
    out: list[LintViolation] = []
    for m in _EMDASH_HOMOGLYPHS.finditer(text or ""):
        out.append(
            LintViolation(
                code="em_dash_homoglyph",
                severity="error",
                message=f"Em-dash or homoglyph at position {m.start()}: mods read this as AI.",
                span=(m.start(), m.end()),
                field=_field(field),
            )
        )
    return out


def heuristic_check_post(
    *,
    title: str,
    body: str,
    sub_rules: dict[str, Any] | None = None,
    flair_id: str | None = None,
) -> PostLintVerdict:
    """Deterministic lint over a post draft → structured PostLintVerdict.

    `sub_rules` is any dict with the subreddit's submission constraints
    (max_title_chars, max_body_chars, submission_type, flair_required,
    allowed_flairs); missing keys fall back to safe defaults. `error` severity
    blocks publish; `warn` surfaces but allows.
    """
    sub_rules = sub_rules or {}
    title = title or ""
    body = body or ""
    violations: list[LintViolation] = []

    # Title length
    title_max = int(sub_rules.get("max_title_chars") or _TITLE_DEFAULT_MAX_CHARS)
    title_len = len(title.strip())
    if title_len < _TITLE_MIN_CHARS:
        violations.append(
            LintViolation(
                code="title_too_short",
                severity="error",
                message=f"Title is {title_len} chars; aim for at least {_TITLE_MIN_CHARS}.",
                field="title",
            )
        )
    if title_len > title_max:
        violations.append(
            LintViolation(
                code="title_too_long",
                severity="error",
                message=f"Title is {title_len} chars; this sub's max is {title_max}.",
                span=(title_max, title_len),
                field="title",
            )
        )

    # Body length (self/any posts need a body; link posts may omit it)
    body_max = int(sub_rules.get("max_body_chars") or _BODY_DEFAULT_MAX_CHARS)
    body_len = len(body.strip())
    submission_type = sub_rules.get("submission_type") or "any"
    if submission_type in ("self", "any") and body_len < _BODY_MIN_CHARS:
        violations.append(
            LintViolation(
                code="body_too_short",
                severity="error",
                message=f"Body is {body_len} chars; aim for at least {_BODY_MIN_CHARS}.",
                field="body",
            )
        )
    if body_len > body_max:
        violations.append(
            LintViolation(
                code="body_too_long",
                severity="error",
                message=f"Body is {body_len} chars; this sub's max is {body_max}.",
                span=(body_max, body_len),
                field="body",
            )
        )

    # Em-dash homoglyphs
    violations.extend(_scan_emdash("title", title))
    violations.extend(_scan_emdash("body", body))

    # AI-tell phrases (warn)
    for field, text in (("title", title), ("body", body)):
        for m in _POST_AI_TELL_REGEX.finditer(text):
            violations.append(
                LintViolation(
                    code="ai_tell",
                    severity="warn",
                    message=f"Phrase reads as LLM-generated: '{m.group(0)}'",
                    span=(m.start(), m.end()),
                    field=_field(field),
                )
            )

    # First-person verb in the first sentence (warn)
    if body_len >= _BODY_MIN_CHARS:
        first = _first_sentence(body)
        if first and not _FIRST_PERSON_VERB_REGEX.search(first):
            violations.append(
                LintViolation(
                    code="no_first_person_verb",
                    severity="warn",
                    message="First sentence has no first-person verb; 'I built/tried' gets clicks.",
                    span=(0, len(first)),
                    field="body",
                )
            )

    # Flair validation
    if bool(sub_rules.get("flair_required")) and not flair_id:
        violations.append(
            LintViolation(
                code="flair_required",
                severity="error",
                message="This subreddit requires post flair; none selected.",
                field="flair",
            )
        )
    allowed: list[Any] = list(sub_rules.get("allowed_flairs") or [])
    if flair_id and allowed and flair_id not in allowed:
        violations.append(
            LintViolation(
                code="flair_invalid",
                severity="error",
                message=f"Flair '{flair_id}' is not in this subreddit's allowed list.",
                field="flair",
            )
        )

    has_error = any(v.severity == "error" for v in violations)
    return PostLintVerdict.model_validate(
        {"pass": not has_error, "violations": [v.model_dump() for v in violations]}
    )


def _field(name: str) -> Any:
    """Narrow a field name to the LintViolation.field literal type."""
    return name


__all__ = ["heuristic_check", "heuristic_check_post"]
