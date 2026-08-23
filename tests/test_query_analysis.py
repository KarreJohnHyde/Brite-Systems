from __future__ import annotations

import pytest

from src.query_analysis import (
    is_underspecified_question,
    requested_clause_lookup_ids,
)


@pytest.mark.parametrize(
    "question",
    [
        "What does clause 2.4.1 say?",
        "Show clause 2.4.1",
        "Please explain §2.4.1.",
    ],
)
def test_pure_clause_lookup_grammar_is_narrow_and_explicit(question: str) -> None:
    assert requested_clause_lookup_ids(question) == {"2.4.1"}
    assert not is_underspecified_question(question)


@pytest.mark.parametrize(
    "question",
    [
        "What does clause 2.4.1 say about cryptocurrency?",
        "What does clause 2.4.1 say, and does crypto count?",
        "Does clause 2.4.1 cover a second vehicle?",
    ],
)
def test_substantive_questions_cannot_activate_clause_lookup_override(question: str) -> None:
    assert requested_clause_lookup_ids(question) == set()


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("How long do I have?", True),
        ("What about the exceptions?", True),
        ("Does that apply to me?", True),
        ("What about appeal deadlines?", False),
        ("How long is a sanction?", False),
        ("How do I apply?", False),
    ],
)
def test_underspecified_guard_requires_a_policy_anchor(question: str, expected: bool) -> None:
    assert is_underspecified_question(question) is expected
