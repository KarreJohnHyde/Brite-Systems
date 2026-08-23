"""Security-sensitive citation construction and claim checks."""

from __future__ import annotations

import re
from collections.abc import Iterable

from src.lexical import STOP_WORDS, tokenize
from src.models import Citation, PolicyChunk, RetrievedClause

CLAUSE_REFERENCE_RE = re.compile(r"(?:Sec\.|§)\s*([A-Za-z0-9\.\(\)-]+)")
ANY_SOURCE_REFERENCE_RE = re.compile(r"(?:Sec\.|§)\s*[A-Za-z0-9\.\(\)-]+")
NUMBER_RE = re.compile(r"\$?\d+(?:,\d{3})*(?:\.\d+)?%?")


class CitationIntegrityError(ValueError):
    """Raised when a citation or substantive claim is not source-backed."""


class CitationValidator:
    """Map opaque source selections back to ingestion-trusted metadata."""

    def __init__(self, retrieved: Iterable[RetrievedClause]) -> None:
        self.retrieved = list(retrieved)
        self._by_id = {item.chunk.chunk_id: item.chunk for item in self.retrieved}

    @property
    def allowed_source_ids(self) -> set[str]:
        return set(self._by_id)

    def validate_source_ids(self, source_ids: Iterable[str], *, require_any: bool = True) -> list[PolicyChunk]:
        ids = list(dict.fromkeys(source_ids))
        if require_any and not ids:
            raise CitationIntegrityError("No supporting source IDs were selected")
        invalid = [source_id for source_id in ids if source_id not in self._by_id]
        if invalid:
            raise CitationIntegrityError(
                "Unretrieved or fabricated source IDs were rejected: " + ", ".join(invalid)
            )
        return [self._by_id[source_id] for source_id in ids]

    def build(self, source_ids: Iterable[str], *, require_any: bool = True) -> list[Citation]:
        chunks = self.validate_source_ids(source_ids, require_any=require_any)
        return [
            Citation(
                chunk_id=chunk.chunk_id,
                clause_id=chunk.clause_id,
                section_id=chunk.section_id,
                section_title=chunk.section_title,
                page=chunk.page,
                line_start=chunk.line_start,
                line_end=chunk.line_end,
                excerpt=chunk.text,
            )
            for chunk in chunks
        ]

    def validate_claims(self, answer: str, source_ids: Iterable[str]) -> None:
        """Reject obvious invented values, clause IDs, and off-source content.

        This deliberately conservative validator is a final safeguard for optional
        LLM prose. The deterministic answer builder uses verbatim source clauses.
        """

        chunks = self.validate_source_ids(source_ids)
        source_text = " ".join(chunk.text for chunk in chunks)
        source_without_refs = ANY_SOURCE_REFERENCE_RE.sub("", source_text)
        answer_without_refs = ANY_SOURCE_REFERENCE_RE.sub("", answer)
        source_numbers = {
            number.replace(",", "") for number in NUMBER_RE.findall(source_without_refs)
        }
        answer_numbers = {
            number.replace(",", "") for number in NUMBER_RE.findall(answer_without_refs)
        }
        invented_numbers = sorted(answer_numbers - source_numbers)
        if invented_numbers:
            raise CitationIntegrityError(
                "Generated answer introduced values absent from its citations: "
                + ", ".join(invented_numbers)
            )

        allowed_clauses = {chunk.clause_id for chunk in chunks if chunk.clause_id}
        referenced_clauses = set(CLAUSE_REFERENCE_RE.findall(answer))
        invented_clauses = sorted(referenced_clauses - allowed_clauses)
        if invented_clauses:
            raise CitationIntegrityError(
                "Generated answer introduced clause IDs absent from its citations: "
                + ", ".join(invented_clauses)
            )

        # Require reasonable content-token grounding without pretending this is
        # statistical entailment. Very short connective language is ignored.
        answer_terms = {
            term for term in tokenize(answer, expand=False) if term not in STOP_WORDS and len(term) > 2
        }
        source_terms = set(tokenize(source_text, expand=True))
        policy_terms = answer_terms - {
            "manual", "state", "clause", "source", "answer", "according", "policy",
        }
        if policy_terms:
            coverage = len(policy_terms & source_terms) / len(policy_terms)
            if coverage < 0.55:
                raise CitationIntegrityError(
                    f"Generated claims have insufficient lexical support ({coverage:.2f})"
                )


def extract_citations_from_answer(answer_text: str) -> list[str]:
    """Compatibility helper; official IDs are never trusted as model selections."""

    return CLAUSE_REFERENCE_RE.findall(answer_text)


def validate_citations(cited_ids: list[str], provided_clauses: list[PolicyChunk]) -> tuple[list[str], list[str]]:
    """Compatibility helper with exact clause-level matching only."""

    allowed = {chunk.clause_id for chunk in provided_clauses}
    return [cid for cid in cited_ids if cid in allowed], [cid for cid in cited_ids if cid not in allowed]
