import pytest
from src.retriever import RetrievalResult
from src.parser import PolicyClause
from src.evidence import assess_evidence, AnswerState

def get_dummy_clause(clause_id: str, text: str) -> PolicyClause:
    return PolicyClause(
        clause_id=clause_id,
        text=text,
        part="Part 1",
        section="1.1",
        line_start=1,
        line_end=2
    )

def test_evidence_refusal():
    # Test that weak retrieval results in a REFUSE decision
    clause = get_dummy_clause("1.1.1", "This is an unrelated policy.")
    weak_result = RetrievalResult(
        clause=clause,
        similarity_score=0.3,
        rerank_score=-3.5  # Below the threshold of -1.0
    )
    
    assessment = assess_evidence("Some question", [weak_result])
    assert assessment.state == AnswerState.REFUSE
    assert "confidence threshold" in assessment.reason

def test_evidence_answer():
    # Test that strong retrieval results in an ANSWER decision
    clause = get_dummy_clause("4.2.1", "This explicitly answers the policy question.")
    strong_result = RetrievalResult(
        clause=clause,
        similarity_score=0.9,
        rerank_score=5.0  # Well above the threshold
    )
    
    assessment = assess_evidence("Some question", [strong_result])
    assert assessment.state == AnswerState.ANSWER
    assert "Sufficient supporting evidence found" in assessment.reason
    assert len(assessment.supporting_results) == 1

def test_evidence_gap_detection():
    # Test that known broken cross-references result in a REFUSE
    clause = get_dummy_clause("7.1.3", "See section 5.4 for student needs calculation.")
    broken_result = RetrievalResult(
        clause=clause,
        similarity_score=0.8,
        rerank_score=2.0
    )
    
    assessment = assess_evidence("how to calculate needs for full-time students", [broken_result])
    assert assessment.state == AnswerState.REFUSE
    assert "calculated differently" in assessment.reason
