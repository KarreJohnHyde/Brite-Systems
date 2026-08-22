from __future__ import annotations

from pathlib import Path

import pytest

from src.decision_engine import DecisionEngine
from src.evidence import EvidenceAnalyzer
from src.models import (
    Decision,
    DecisionTrace,
    EvidenceAssessment,
    SupportType,
)
from src.refusal import load_contacts, refusal_text, select_next_step


def assessment(chunk_id: str, support_type: SupportType, score: float) -> EvidenceAssessment:
    return EvidenceAssessment(
        chunk_id=chunk_id,
        support_type=support_type,
        explanation="test assessment",
        score=score,
        topic_coverage=score,
        answer_alignment=score,
    )


def test_evidence_distinguishes_direct_partial_and_unrelated(make_chunk, make_result) -> None:
    direct = make_chunk(
        chunk_id="direct",
        clause_id="1.1.1",
        section_title="Appeals",
        text="An appeal must be lodged within 30 days of notification.",
    )
    partial = make_chunk(
        chunk_id="partial",
        clause_id="1.1.2",
        section_title="Appeals",
        text="A person may appeal to the Panel.",
    )
    unrelated = make_chunk(
        chunk_id="unrelated",
        clause_id="1.1.3",
        section_title="Resources",
        text="A household resource limit is $4,000.",
    )
    analyzer = EvidenceAnalyzer([direct, partial, unrelated])
    question = "How many days does a person have to appeal?"

    evidence = analyzer.assess(
        question,
        [make_result(direct), make_result(partial), make_result(unrelated)],
    )
    labels = {item.chunk_id: item.support_type for item in evidence}

    assert labels == {
        "direct": SupportType.DIRECT,
        "partial": SupportType.PARTIAL,
        "unrelated": SupportType.RELATED_ONLY,
    }


def test_verified_student_gap_is_partial_not_direct(chunks, findings_path: Path, make_result) -> None:
    student_clause = next(chunk for chunk in chunks if chunk.clause_id == "7.1.3")
    analyzer = EvidenceAnalyzer(chunks, findings_path=findings_path)

    item = analyzer.assess(
        "How is the needs figure calculated for a full-time student?",
        [make_result(student_clause)],
    )[0]

    assert item.support_type == SupportType.PARTIAL
    assert "verified manual gap" in item.explanation


def test_decision_refuses_when_only_related_evidence_exists(make_chunk, make_result) -> None:
    chunk = make_chunk(text="Applications may be made online.")
    result = make_result(chunk)
    evidence = [assessment(chunk.chunk_id, SupportType.RELATED_ONLY, 0.7)]

    trace = DecisionEngine(enable_conflict_check=False).decide(
        "Does cryptocurrency count as income?",
        [result],
        evidence,
    )

    assert trace.decision == Decision.REFUSE
    assert "do not directly settle" in trace.decision_reason


def test_compound_question_refuses_when_one_aspect_is_missing(make_chunk, make_result) -> None:
    chunk = make_chunk(
        text="A person affected by a determination may appeal.",
        section_title="Appeals",
    )
    result = make_result(chunk)
    evidence = [assessment(chunk.chunk_id, SupportType.DIRECT, 0.9)]

    trace = DecisionEngine(enable_conflict_check=False).decide(
        "Can a person appeal and how many days do they have?",
        [result],
        evidence,
    )

    assert trace.decision == Decision.REFUSE
    assert trace.missing_aspects
    assert "part of the question" in trace.decision_reason


def test_individual_eligibility_question_refuses_despite_direct_rule(make_chunk, make_result) -> None:
    chunk = make_chunk(text="A household is not eligible where resources exceed $4,000.")
    result = make_result(chunk)
    evidence = [assessment(chunk.chunk_id, SupportType.DIRECT, 0.95)]

    trace = DecisionEngine(enable_conflict_check=False).decide(
        "Am I eligible if I have $3,000 in savings?",
        [result],
        evidence,
    )

    assert trace.decision == Decision.REFUSE
    assert "case facts" in trace.decision_reason


def test_direct_evidence_below_configured_threshold_refuses(make_chunk, make_result) -> None:
    chunk = make_chunk(text="An appeal must be lodged within 30 days.")
    result = make_result(chunk)
    evidence = [assessment(chunk.chunk_id, SupportType.DIRECT, 0.55)]

    trace = DecisionEngine(refusal_threshold=0.58, enable_conflict_check=False).decide(
        "How many days do I have to appeal?",
        [result],
        evidence,
    )

    assert trace.decision == Decision.REFUSE
    assert "support threshold" in trace.decision_reason


def test_refusal_is_deterministic_and_next_step_is_topic_specific(
    contacts_path: Path,
    make_chunk,
    make_result,
) -> None:
    chunk = make_chunk()
    result = make_result(chunk)
    trace = DecisionTrace(
        question="Can I appeal this decision?",
        retrieved=[result],
        evidence=[assessment(chunk.chunk_id, SupportType.RELATED_ONLY, 0.4)],
        decision=Decision.REFUSE,
        decision_reason="The manual does not settle this case.",
        refusal_threshold=0.58,
    )
    contacts = load_contacts(contacts_path)

    assert refusal_text(trace).startswith("I don't know based on the current policy manual")
    assert "Appeals Panel" in select_next_step(trace.question, contacts)
    assert "supervisor" in select_next_step("Do I qualify based on income?", contacts)
    assert "district offices" in select_next_step("Who should clarify this?", contacts)
    assert "555" not in str(contacts)


def test_explicit_findings_file_failure_does_not_silently_disable_safety(
    tmp_path: Path,
    chunks,
) -> None:
    malformed = tmp_path / "policy-findings.json"
    malformed.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(ValueError, match="findings file is unreadable"):
        EvidenceAnalyzer(chunks, findings_path=malformed)
