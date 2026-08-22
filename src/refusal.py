"""
Refusal response generation.

When the evidence assessment determines the manual doesn't cover a question,
this module generates a structured, helpful refusal with next-step guidance.
"""

import json
from pathlib import Path
from typing import Optional

from src.evidence import EvidenceAssessment


def load_contacts(contacts_path: str | Path = None) -> dict:
    """Load contact information for refusal responses."""
    if contacts_path is None:
        contacts_path = Path(__file__).parent.parent / "data" / "contacts.json"
    
    with open(contacts_path, "r", encoding="utf-8") as f:
        return json.load(f)


def generate_refusal(
    question: str,
    assessment: EvidenceAssessment,
    contacts: Optional[dict] = None,
) -> dict:
    """
    Generate a structured refusal response.
    
    Returns a dict with:
        - answer: The refusal message
        - reason: Why the system couldn't answer
        - contact: Who to ask instead
        - state: "refuse"
        - citations: [] (empty — no supporting clauses)
    """
    if contacts is None:
        contacts = load_contacts()

    # Determine the most appropriate contact based on context
    contact = _select_contact(question, contacts)

    answer_parts = [
        "I don't know based on the current policy manual.",
        "",
        f"Reason: {assessment.reason}",
        "",
        "Please contact:",
        f"  {contact['name']}",
        f"  Phone: {contact.get('phone', 'N/A')}",
        f"  Email: {contact.get('email', 'N/A')}",
    ]

    if "district_offices" in contacts:
        answer_parts.append("")
        answer_parts.append(f"  District offices: {', '.join(contacts['district_offices'])}")

    return {
        "answer": "\n".join(answer_parts),
        "reason": assessment.reason,
        "contact": contact,
        "state": "refuse",
        "citations": [],
        "top_score": assessment.top_score,
    }


def _select_contact(question: str, contacts: dict) -> dict:
    """Select the most appropriate contact based on question content."""
    q = question.lower()

    if any(word in q for word in ["appeal", "panel", "hearing"]):
        return contacts.get("appeals", contacts["general"])
    elif any(word in q for word in ["eligible", "qualify", "income", "threshold"]):
        return contacts.get("eligibility", contacts["general"])
    elif any(word in q for word in ["conflict", "contradict", "inconsistent", "supervisor"]):
        return contacts.get("supervisor", contacts["general"])
    else:
        return contacts["general"]
