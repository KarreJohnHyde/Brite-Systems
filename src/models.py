"""Trusted domain models used across the policy evidence pipeline."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Decision(str, Enum):
    ANSWER = "ANSWER"
    CONFLICT = "CONFLICT"
    REFUSE = "REFUSE"


class SupportType(str, Enum):
    DIRECT = "DIRECT"
    PARTIAL = "PARTIAL"
    RELATED_ONLY = "RELATED_ONLY"
    CONTRADICTORY = "CONTRADICTORY"
    NONE = "NONE"


class EvidenceLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class PolicyChunk(BaseModel):
    """One official policy clause plus ingestion-trusted source metadata."""

    model_config = ConfigDict(frozen=True)

    chunk_id: str
    document_id: str
    document_name: str
    document_version: str | None = None
    effective_date: str | None = None
    active: bool = True
    source_kind: Literal["manual", "amendment"] = "manual"
    document_title: str | None = None
    amendment_number: str | None = None
    issued_date: str | None = None

    text: str
    raw_text: str
    normalized_text: str
    source_text: str

    part_id: str | None = None
    part_title: str | None = None
    section_id: str | None = None
    section_title: str | None = None
    clause_id: str | None = None
    official_clause_id: bool = True
    locator_kind: Literal["clause", "paragraph"] = "clause"
    source_locator: str | None = None
    source_locator_label: str | None = None
    amends_clause_ids: list[str] = Field(default_factory=list)
    inserts_clause_ids: list[str] = Field(default_factory=list)

    page: int | None = None
    line_start: int
    line_end: int
    start_offset: int
    end_offset: int
    source_order: int
    document_index: int = 0
    document_order: int | None = None
    cross_references: list[str] = Field(default_factory=list)

    @property
    def source_label(self) -> str:
        if self.source_locator_label:
            return self.source_locator_label
        clause = f"§{self.clause_id}" if self.clause_id else self.chunk_id
        return f"{clause} — {self.section_title or self.part_title or self.document_name}"


class RetrievedClause(BaseModel):
    """A chunk returned by retrieval with every score kept distinct."""

    chunk: PolicyChunk
    vector_score: float | None = None
    lexical_score: float | None = None
    fused_score: float | None = None
    reranker_score: float | None = None
    vector_rank: int | None = None
    lexical_rank: int | None = None
    reranker_rank: int | None = None
    neighbor_of: str | None = None

    @property
    def ranking_score(self) -> float:
        if self.reranker_score is not None:
            return self.reranker_score
        if self.fused_score is not None:
            return self.fused_score
        return max(self.vector_score or 0.0, self.lexical_score or 0.0)


class EvidenceAssessment(BaseModel):
    """Question-to-clause support assessment; relevance is not sufficiency."""

    chunk_id: str
    support_type: SupportType
    explanation: str
    score: float = Field(ge=0.0, le=1.0)
    topic_coverage: float = Field(ge=0.0, le=1.0)
    answer_alignment: float = Field(ge=0.0, le=1.0)
    matched_terms: list[str] = Field(default_factory=list)
    missing_terms: list[str] = Field(default_factory=list)


class Citation(BaseModel):
    """Citation rendered only from trusted chunk metadata."""

    chunk_id: str
    clause_id: str | None = None
    section_id: str | None = None
    section_title: str | None = None
    page: int | None = None
    line_start: int
    line_end: int
    excerpt: str
    document_id: str | None = None
    document_name: str | None = None
    document_title: str | None = None
    source_kind: Literal["manual", "amendment"] | None = None
    amendment_number: str | None = None
    effective_date: str | None = None
    locator_kind: Literal["clause", "paragraph"] | None = None
    source_locator: str | None = None
    source_locator_label: str | None = None


class ConflictFinding(BaseModel):
    finding_id: str
    chunk_ids: list[str] = Field(min_length=2)
    clause_ids: list[str] = Field(min_length=2)
    explanation: str
    basis: Literal["NUMERIC", "POLARITY", "CURATED"]
    confidence: float = Field(ge=0.0, le=1.0)


class DecisionTrace(BaseModel):
    question: str
    retrieved: list[RetrievedClause]
    evidence: list[EvidenceAssessment]
    conflicts: list[ConflictFinding] = Field(default_factory=list)
    decision: Decision
    decision_reason: str
    refusal_threshold: float
    required_aspects: list[str] = Field(default_factory=list)
    missing_aspects: list[str] = Field(default_factory=list)


class PolicyAnswer(BaseModel):
    decision: Decision
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    evidence_level: EvidenceLevel
    reason: str
    next_step: str | None = None
    trace: DecisionTrace | None = None

    @model_validator(mode="after")
    def enforce_state_contract(self) -> PolicyAnswer:
        if self.decision == Decision.ANSWER and not self.citations:
            raise ValueError("ANSWER requires at least one trusted citation")
        if self.decision == Decision.CONFLICT and len(self.citations) < 2:
            raise ValueError("CONFLICT requires at least two trusted citations")
        return self


class GenerationSelection(BaseModel):
    decision: Decision
    answer: str
    supporting_source_ids: list[str] = Field(default_factory=list)
    reason: str


class CoverageGateResult(BaseModel):
    covered: bool
    confidence: float
    matched_clause_ids: list[str] = Field(default_factory=list)
    uncovered_aspect: str | None = None


class IngestionReport(BaseModel):
    document_id: str
    document_name: str
    document_version: str | None
    source_sha256: str
    source_bytes: int
    source_lines: int
    pages: int | None = None
    parts: int
    sections: int
    clauses: int
    chunks: int
    average_chunk_characters: float
    largest_chunk_characters: int
    duplicate_clause_groups: list[list[str]] = Field(default_factory=list)
    unresolved_cross_references: list[str] = Field(default_factory=list)
    parser: str = "markdown-clause-v2"
    document_title: str | None = None
    source_kind: Literal["manual", "amendment"] = "manual"
    effective_date: str | None = None
    issued_date: str | None = None


class CombinedCorpusReport(BaseModel):
    """Deterministic provenance report for an ordered set of policy sources."""

    combined_source_sha256: str
    source_sha256: str
    source_reports: list[IngestionReport]
    documents: int
    source_bytes: int
    source_lines: int
    clauses: int
    chunks: int
    duplicate_source_locators: list[str] = Field(default_factory=list)
    unresolved_cross_references: list[str] = Field(default_factory=list)
    parser: str = "markdown-multisource-v1"
