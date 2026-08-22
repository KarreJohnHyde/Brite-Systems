"""
Evidence analysis: determines whether retrieved clauses support an answer,
reveal a contradiction, or are insufficient (triggering refusal).

This is the core differentiator of the system — it implements the 
three-state output model: ANSWER / CONFLICT / REFUSE.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from src.retriever import RetrievalResult


class AnswerState(Enum):
    """The three possible output states."""
    ANSWER = "answer"       # Sufficient evidence, no conflict
    CONFLICT = "conflict"   # Contradictory clauses found
    REFUSE = "refuse"       # Insufficient evidence


@dataclass
class EvidenceAssessment:
    """Result of evidence analysis."""
    state: AnswerState
    supporting_results: list[RetrievalResult]     # Clauses to use for answer generation
    conflicting_pairs: list[tuple[RetrievalResult, RetrievalResult]] = field(default_factory=list)
    reason: str = ""                               # Human-readable explanation of the assessment
    top_score: float = 0.0                         # Best retrieval score


# Thresholds — these are the "line between answering and refusing"
# Documented in DECISIONS.md with rationale
RELEVANCE_THRESHOLD = 0.45       # Minimum reranker score to consider a clause relevant
MIN_SUPPORTING_CLAUSES = 1       # Need at least 1 relevant clause to attempt an answer
CONFLICT_SCORE_THRESHOLD = 0.30  # Both conflicting clauses must score above this


def assess_evidence(
    question: str,
    results: list[RetrievalResult],
    llm_conflict_checker=None,
) -> EvidenceAssessment:
    """
    Analyze retrieval results to determine the answer state.
    
    Decision logic:
    1. If no results or top score below threshold → REFUSE
    2. If relevant results contain conflicting claims → CONFLICT
    3. If relevant results exist and are consistent → ANSWER
    
    Args:
        question: The user's question
        results: Ranked retrieval results from the retriever
        llm_conflict_checker: Optional callable(question, clause_a, clause_b) -> bool
                              that uses the LLM to detect semantic conflicts
    
    Returns:
        EvidenceAssessment with state, supporting results, and conflict info
    """
    if not results:
        return EvidenceAssessment(
            state=AnswerState.REFUSE,
            supporting_results=[],
            reason="No matching clauses found in the policy manual.",
            top_score=0.0,
        )

    top_score = results[0].final_score

    # Filter to relevant results only
    relevant = [r for r in results if r.final_score >= RELEVANCE_THRESHOLD]

    if len(relevant) < MIN_SUPPORTING_CLAUSES:
        return EvidenceAssessment(
            state=AnswerState.REFUSE,
            supporting_results=[],
            reason=(
                f"The closest matching clauses scored below the confidence threshold "
                f"(best score: {top_score:.2f}, threshold: {RELEVANCE_THRESHOLD}). "
                f"The manual may not address this topic."
            ),
            top_score=top_score,
        )

    # Check for contradictions among relevant results
    conflicts = _detect_contradictions(question, relevant, llm_conflict_checker)

    if conflicts:
        return EvidenceAssessment(
            state=AnswerState.CONFLICT,
            supporting_results=relevant,
            conflicting_pairs=conflicts,
            reason="The manual contains clauses that appear to contradict each other on this topic.",
            top_score=top_score,
        )

    # Sufficient, consistent evidence
    return EvidenceAssessment(
        state=AnswerState.ANSWER,
        supporting_results=relevant,
        reason="Sufficient supporting evidence found.",
        top_score=top_score,
    )


def _detect_contradictions(
    question: str,
    results: list[RetrievalResult],
    llm_checker=None,
) -> list[tuple[RetrievalResult, RetrievalResult]]:
    """
    Check if any pair of relevant clauses contradict each other.
    
    Uses two methods:
    1. Rule-based: known contradiction patterns (cross-reference mismatches)
    2. LLM-based: ask the model if two clauses conflict (if checker provided)
    """
    conflicts = []

    # Rule-based contradiction detection
    for i, r1 in enumerate(results):
        for r2 in results[i + 1:]:
            if _rule_based_conflict(r1.clause, r2.clause):
                conflicts.append((r1, r2))

    # LLM-based contradiction detection (if available)
    if llm_checker and not conflicts:
        for i, r1 in enumerate(results):
            for r2 in results[i + 1:]:
                # Only check pairs where both are reasonably relevant
                if r1.final_score >= CONFLICT_SCORE_THRESHOLD and r2.final_score >= CONFLICT_SCORE_THRESHOLD:
                    try:
                        if llm_checker(question, r1.clause, r2.clause):
                            conflicts.append((r1, r2))
                    except Exception:
                        pass  # Don't fail the whole pipeline on LLM errors

    return conflicts


def _rule_based_conflict(clause_a, clause_b) -> bool:
    """
    Detect known contradiction patterns using rules.
    
    Key pattern: cross-reference mismatch
    When clause A cites clause B but states a different value/requirement
    than what clause B actually says.
    """
    import re

    text_a = clause_a.display_text().lower()
    text_b = clause_b.display_text().lower()

    # Pattern 1: Two clauses about the same topic with different numeric values
    # Look for day counts that differ
    days_pattern = re.compile(r'(\d+)\s*(?:calendar\s+)?days?')

    # Only check if they cross-reference each other or share the same topic area
    a_refs_b = f"§{clause_b.clause_id}" in clause_a.display_text() or \
               f"§{clause_b.clause_id.rsplit('.', 1)[0]}" in clause_a.display_text()
    b_refs_a = f"§{clause_a.clause_id}" in clause_b.display_text() or \
               f"§{clause_a.clause_id.rsplit('.', 1)[0]}" in clause_b.display_text()

    if a_refs_b or b_refs_a:
        # Extract day values from both
        days_a = set(int(m.group(1)) for m in days_pattern.finditer(text_a))
        days_b = set(int(m.group(1)) for m in days_pattern.finditer(text_b))

        # Check if they share a topic keyword but have different day values
        topic_keywords = ["report", "change", "circumstance", "appeal", "review", "notice"]
        shared_topic = any(kw in text_a and kw in text_b for kw in topic_keywords)

        if shared_topic and days_a and days_b:
            # If they reference each other and have different day counts, likely conflict
            if days_a != days_b and (a_refs_b or b_refs_a):
                return True

    return False
