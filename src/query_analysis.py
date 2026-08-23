"""Small deterministic guards for standalone policy questions."""

from __future__ import annotations

import re

from src.lexical import tokenize


POLICY_ID_RE = re.compile(r"§?(\d+\.\d+(?:\.\d+)?)")
SOURCE_LOOKUP_RE = re.compile(
    r"\s*(?:"
    r"(?:please\s+)?(?:show|quote|read|display|summarize|summarise|explain)\s+"
    r"(?:(?:clause|provision)\s+)?§?\d+\.\d+\.\d+"
    r"|"
    r"what\s+does\s+(?:(?:clause|provision)\s+)?§?\d+\.\d+\.\d+\s+"
    r"(?:say|state|mean|contain|provide)"
    r"|"
    r"what\s+is\s+(?:in\s+)?(?:clause|provision)\s+§?\d+\.\d+\.\d+"
    r")\s*[?.!]*\s*",
    re.IGNORECASE,
)
PRONOUN_FOLLOW_UP_RE = re.compile(
    r"^\s*(?:does|is|are|can|could|will|would|should)\s+"
    r"(?:it|this|that|these|those|they|them)\b",
    re.IGNORECASE,
)

# These can describe the requested answer shape, but do not identify which of
# the manual's many deadlines, amounts, exceptions, or procedures is meant.
NON_TOPICAL_TERMS = {
    "about",
    "amount",
    "answer",
    "calendar",
    "day",
    "deadline",
    "detail",
    "exception",
    "few",
    "figure",
    "get",
    "have",
    "help",
    "it",
    "keep",
    "limit",
    "long",
    "many",
    "manual",
    "month",
    "much",
    "period",
    "policy",
    "question",
    "rate",
    "rule",
    "tell",
    "that",
    "them",
    "these",
    "thing",
    "this",
    "threshold",
    "those",
    "time",
    "week",
    "year",
}


def focus_policy_question(question: str) -> str:
    """Ignore a leading instruction-like sentence, not the actual question."""

    return re.sub(
        r"^.*?\.\s*(?=(?:how|what|when|where|which|who|can|could|does|do|is|are|may|must|will|would)\b)",
        "",
        question.strip(),
        count=1,
        flags=re.IGNORECASE,
    )


def referenced_policy_ids(question: str) -> list[str]:
    """Return distinct official-looking IDs in user order."""

    return list(dict.fromkeys(match.group(1) for match in POLICY_ID_RE.finditer(question)))


def requested_clause_lookup_ids(question: str) -> set[str]:
    """Recognize a narrow request to read a named official clause.

    Mentioning a clause while asking a substantive question does not activate
    this path. This prevents an unrelated or forged citation request from being
    treated as evidence for the user's actual policy issue.
    """

    focused = focus_policy_question(question)
    if not SOURCE_LOOKUP_RE.fullmatch(focused):
        return set()
    return {identifier for identifier in referenced_policy_ids(focused) if identifier.count(".") == 2}


def is_underspecified_question(question: str) -> bool:
    """Return True when a standalone query lacks a usable policy anchor."""

    focused = focus_policy_question(question)
    if requested_clause_lookup_ids(focused):
        return False
    if PRONOUN_FOLLOW_UP_RE.search(focused):
        return True
    terms = set(tokenize(focused, expand=False))
    return bool(terms) and not (terms - NON_TOPICAL_TERMS)
