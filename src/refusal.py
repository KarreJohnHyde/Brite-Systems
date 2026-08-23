"""Deterministic refusal and escalation selection."""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.models import DecisionTrace


SERVICE_ACCESS_RE = re.compile(
    r"\b(?:where|how|who)\b.*\b(?:get|find|access|obtain|ask|contact|call)\b.*"
    r"\b(?:support|referral|services?|assistance|help)\b",
    re.IGNORECASE,
)


def load_contacts(contacts_path: str | Path | None = None) -> dict:
    """Load configured escalation descriptions (never personal contact data)."""

    path = Path(contacts_path) if contacts_path else Path(__file__).resolve().parent.parent / "data" / "contacts.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "default" not in payload:
        raise ValueError("contacts.json must define a default escalation path")
    return payload


def select_next_step(question: str, contacts: dict) -> str:
    lowered = question.lower()
    if SERVICE_ACCESS_RE.search(question):
        key = "default"
    elif any(term in lowered for term in ("appeal", "review", "hearing", "panel")):
        key = "appeals"
    elif any(term in lowered for term in ("eligible", "eligibility", "qualify", "income", "resource")):
        key = "eligibility"
    else:
        key = "default"
    return str(contacts.get(key, contacts["default"])["next_step"])


def refusal_text(trace: DecisionTrace) -> str:
    return (
        "I don't know based on the current policy manual. "
        "The manual does not clearly settle this question."
    )
