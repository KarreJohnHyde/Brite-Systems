"""
Contradiction response generation.

When the evidence assessment detects conflicting clauses, this module
generates a structured response that surfaces both sides rather than
silently choosing one.
"""

from src.evidence import EvidenceAssessment
from src.refusal import load_contacts
from src.parser import format_clause_for_context
from typing import Optional


def generate_contradiction_response(
    question: str,
    assessment: EvidenceAssessment,
    contacts: Optional[dict] = None,
) -> dict:
    """
    Generate a structured contradiction response.
    
    Shows both conflicting clauses and recommends escalation.
    
    Returns a dict with:
        - answer: The contradiction explanation
        - state: "conflict"
        - citations: list of cited clause references
        - conflicting_clauses: the actual conflict details
    """
    if contacts is None:
        contacts = load_contacts()

    supervisor = contacts.get("supervisor", contacts["general"])

    answer_parts = [
        "⚠ MANUAL CONFLICT",
        "",
        "The policy manual does not provide a single consistent answer to this question. "
        "The following clauses appear to contradict each other:",
        "",
    ]

    citations = []
    conflicting_details = []

    for clause_a, clause_b in assessment.conflicting_pairs:
        answer_parts.append(f"  Clause §{clause_a.clause.clause_id} ({clause_a.clause.section}):")
        answer_parts.append(f"    \"{clause_a.clause.display_text()[:200]}\"")
        answer_parts.append("")
        answer_parts.append(f"  Clause §{clause_b.clause.clause_id} ({clause_b.clause.section}):")
        answer_parts.append(f"    \"{clause_b.clause.display_text()[:200]}\"")
        answer_parts.append("")

        citations.append({
            "clause_id": clause_a.clause.clause_id,
            "section": clause_a.clause.section,
            "part": clause_a.clause.part,
            "lines": f"{clause_a.clause.line_start}-{clause_a.clause.line_end}",
        })
        citations.append({
            "clause_id": clause_b.clause.clause_id,
            "section": clause_b.clause.section,
            "part": clause_b.clause.part,
            "lines": f"{clause_b.clause.line_start}-{clause_b.clause.line_end}",
        })

        conflicting_details.append({
            "clause_a": clause_a.clause.clause_id,
            "clause_b": clause_b.clause.clause_id,
            "text_a": clause_a.clause.display_text(),
            "text_b": clause_b.clause.display_text(),
        })

    answer_parts.extend([
        "This inconsistency should be escalated. Please contact:",
        f"  {supervisor['name']}",
        f"  Phone: {supervisor.get('phone', 'N/A')}",
        f"  Email: {supervisor.get('email', 'N/A')}",
    ])

    return {
        "answer": "\n".join(answer_parts),
        "state": "conflict",
        "citations": citations,
        "conflicting_clauses": conflicting_details,
        "top_score": assessment.top_score,
    }
