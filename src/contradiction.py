"""Scope-aware contradiction detection over retrieved policy evidence."""

from __future__ import annotations

import hashlib
import re
from itertools import combinations
from pathlib import Path

from src.evidence import finding_matches, load_findings
from src.lexical import tokenize
from src.models import ConflictFinding, EvidenceAssessment, RetrievedClause, SupportType

QUANTITY_RE = re.compile(
    r"(?P<value>\$?\d+(?:,\d{3})*(?:\.\d+)?)\s*"
    r"(?P<unit>calendar\s+days?|working\s+days?|days?|weeks?|months?|years?|per\s+cent|percent|%)",
    re.IGNORECASE,
)
NUMERIC_INTENT_RE = re.compile(
    r"\b(how (?:many|much|long)|deadline|amount|rate|percentage|threshold|limit|"
    r"days?|weeks?|months?|years?|per cent|percent)\b",
    re.IGNORECASE,
)
EXCEPTION_SCOPE_RE = re.compile(r"\b(extended to|except|unless|where|up to|first)\b", re.IGNORECASE)
NEGATIVE_ACTION_RE = re.compile(
    r"\b(?:must not|shall not|may not)\s+(?:be\s+)?(?P<action>[a-z]+)",
    re.IGNORECASE,
)
POSITIVE_ACTION_RE = re.compile(
    r"\b(?:must|shall|may)\s+(?!not\b)(?:be\s+)?(?P<action>[a-z]+)",
    re.IGNORECASE,
)


def _canonical_unit(unit: str) -> str:
    normalized = re.sub(r"\s+", " ", unit.lower()).strip()
    if "day" in normalized:
        return "days"
    if "week" in normalized:
        return "weeks"
    if "month" in normalized:
        return "months"
    if "year" in normalized:
        return "years"
    if normalized in {"per cent", "percent", "%"}:
        return "percent"
    return normalized


def _quantities(text: str) -> dict[str, set[str]]:
    values: dict[str, set[str]] = {}
    for match in QUANTITY_RE.finditer(text):
        unit = _canonical_unit(match.group("unit"))
        value = match.group("value").replace(",", "").lstrip("$")
        values.setdefault(unit, set()).add(value)
    return values


class ContradictionDetector:
    """Find confirmed or high-precision numeric/polarity conflicts."""

    def __init__(self, findings_path: str | Path | None = None) -> None:
        self.findings = load_findings(findings_path)

    def detect(
        self,
        question: str,
        retrieved: list[RetrievedClause],
        evidence: list[EvidenceAssessment],
    ) -> list[ConflictFinding]:
        by_clause = {item.chunk.clause_id: item for item in retrieved if item.chunk.clause_id}
        results: list[ConflictFinding] = []

        for finding in self.findings.get("conflicts", []):
            clause_ids = list(finding.get("clause_ids", []))
            if (
                finding.get("source_verified") is True
                and finding_matches(question, finding)
                and len(clause_ids) >= 2
                and all(clause_id in by_clause for clause_id in clause_ids)
            ):
                results.append(
                    ConflictFinding(
                        finding_id=str(finding.get("id", "CURATED-CONFLICT")),
                        chunk_ids=[by_clause[clause_id].chunk.chunk_id for clause_id in clause_ids],
                        clause_ids=clause_ids,
                        explanation=str(finding.get("explanation", "The relevant clauses are materially incompatible.")),
                        basis="CURATED",
                        confidence=1.0,
                    )
                )

        assessed = {item.chunk_id: item for item in evidence}
        candidates = [
            item
            for item in retrieved
            if assessed.get(item.chunk.chunk_id)
            and assessed[item.chunk.chunk_id].support_type != SupportType.NONE
        ]
        existing_pairs = {frozenset(finding.chunk_ids) for finding in results}
        for left, right in combinations(candidates[:12], 2):
            pair = frozenset((left.chunk.chunk_id, right.chunk.chunk_id))
            if pair in existing_pairs:
                continue
            finding = self._numeric_conflict(question, left, right)
            if finding is None:
                finding = self._polarity_conflict(question, left, right)
            if finding:
                results.append(finding)
                existing_pairs.add(pair)
        return results

    def _numeric_conflict(
        self,
        question: str,
        left: RetrievedClause,
        right: RetrievedClause,
    ) -> ConflictFinding | None:
        if not NUMERIC_INTENT_RE.search(question):
            return None
        left_text = left.chunk.text
        right_text = right.chunk.text
        left_values = _quantities(left_text)
        right_values = _quantities(right_text)
        different_units = [
            unit
            for unit in left_values.keys() & right_values.keys()
            if left_values[unit] != right_values[unit]
        ]
        if not different_units:
            return None

        left_refs_right = (
            right.chunk.clause_id in left.chunk.cross_references
            or right.chunk.section_id in left.chunk.cross_references
        )
        right_refs_left = (
            left.chunk.clause_id in right.chunk.cross_references
            or left.chunk.section_id in right.chunk.cross_references
        )
        left_terms = set(tokenize(left_text, expand=False))
        right_terms = set(tokenize(right_text, expand=False))
        question_terms = set(tokenize(question, expand=True))
        shared_topic = (left_terms & right_terms & question_terms) - {
            "day", "week", "month", "year", "period", "must", "may",
        }
        if not (left_refs_right or right_refs_left or len(shared_topic) >= 2):
            return None

        # Explicit extensions and scoped exceptions are compatible with a
        # general rule unless a source-verified finding says otherwise.
        if left.chunk.section_id == right.chunk.section_id and (
            EXCEPTION_SCOPE_RE.search(left_text) or EXCEPTION_SCOPE_RE.search(right_text)
        ):
            return None

        unit = different_units[0]
        identifier = hashlib.sha256(
            f"{left.chunk.chunk_id}|{right.chunk.chunk_id}|{unit}".encode()
        ).hexdigest()[:10]
        return ConflictFinding(
            finding_id=f"numeric_{identifier}",
            chunk_ids=[left.chunk.chunk_id, right.chunk.chunk_id],
            clause_ids=[left.chunk.clause_id or left.chunk.chunk_id, right.chunk.clause_id or right.chunk.chunk_id],
            explanation=(
                f"The clauses give different {unit} values for the same question: "
                f"{sorted(left_values[unit])} versus {sorted(right_values[unit])}."
            ),
            basis="NUMERIC",
            confidence=0.92 if (left_refs_right or right_refs_left) else 0.82,
        )

    @staticmethod
    def _polarity_conflict(
        question: str,
        left: RetrievedClause,
        right: RetrievedClause,
    ) -> ConflictFinding | None:
        """Detect a narrow positive/negative clash over the same query predicate."""

        left_text = left.chunk.text
        right_text = right.chunk.text
        left_ineligible = bool(re.search(r"\b(?:(?:is|are) not eligible|ineligible|excluded)\b", left_text, re.IGNORECASE))
        right_ineligible = bool(re.search(r"\b(?:(?:is|are) not eligible|ineligible|excluded)\b", right_text, re.IGNORECASE))
        left_eligible = bool(re.search(r"\b(?:is|are) eligible\b", left_text, re.IGNORECASE))
        right_eligible = bool(re.search(r"\b(?:is|are) eligible\b", right_text, re.IGNORECASE))
        eligibility_clash = (left_ineligible and right_eligible) or (right_ineligible and left_eligible)

        left_negative_actions = {
            match.group("action").lower() for match in NEGATIVE_ACTION_RE.finditer(left_text)
        }
        right_negative_actions = {
            match.group("action").lower() for match in NEGATIVE_ACTION_RE.finditer(right_text)
        }
        left_positive_actions = {
            match.group("action").lower() for match in POSITIVE_ACTION_RE.finditer(left_text)
        }
        right_positive_actions = {
            match.group("action").lower() for match in POSITIVE_ACTION_RE.finditer(right_text)
        }
        action_clash = bool(
            (left_negative_actions & right_positive_actions)
            or (right_negative_actions & left_positive_actions)
        )
        if not (eligibility_clash or action_clash):
            return None
        if EXCEPTION_SCOPE_RE.search(left.chunk.text) or EXCEPTION_SCOPE_RE.search(right.chunk.text):
            return None

        ignored = {
            "eligible", "eligibility", "ineligible", "must", "may", "not", "person",
            "applicant", "recipient", "household", "program", "assistance",
        }
        question_terms = set(tokenize(question, expand=True)) - ignored
        shared = (
            set(tokenize(left.chunk.text, expand=False))
            & set(tokenize(right.chunk.text, expand=False))
            & question_terms
        ) - ignored
        if not shared:
            return None

        identifier = hashlib.sha256(
            f"{left.chunk.chunk_id}|{right.chunk.chunk_id}|polarity".encode()
        ).hexdigest()[:10]
        return ConflictFinding(
            finding_id=f"polarity_{identifier}",
            chunk_ids=[left.chunk.chunk_id, right.chunk.chunk_id],
            clause_ids=[
                left.chunk.clause_id or left.chunk.chunk_id,
                right.chunk.clause_id or right.chunk.chunk_id,
            ],
            explanation="The clauses apply opposite positive and negative rules to the same question.",
            basis="POLARITY",
            confidence=0.86,
        )
