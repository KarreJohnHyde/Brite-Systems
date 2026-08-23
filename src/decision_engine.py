"""Central ANSWER / CONFLICT / REFUSE state machine."""

from __future__ import annotations

import re
from pathlib import Path

from src.contradiction import ContradictionDetector
from src.evidence import finding_matches, load_findings
from src.lexical import tokenize
from src.models import (
    Decision,
    DecisionTrace,
    EvidenceAssessment,
    RetrievedClause,
    SupportType,
)
from src.query_analysis import is_underspecified_question

INDIVIDUAL_DETERMINATION_RE = re.compile(
    r"\b(am i|will i|would i|my eligibility|exactly how much|how much (?:assistance )?(?:will|would|do) i|how old (?:must|do|should) i)\b",
    re.IGNORECASE,
)
CASE_RECORD_RE = re.compile(r"\b(why was my|why did (?:they|the department)|what happened to my case)\b", re.IGNORECASE)


class DecisionEngine:
    """Apply policy-safety guards independently of answer generation."""

    def __init__(
        self,
        *,
        refusal_threshold: float = 0.58,
        findings_path: str | Path | None = None,
        enable_conflict_check: bool = True,
    ) -> None:
        self.refusal_threshold = refusal_threshold
        self.findings = load_findings(findings_path)
        self.conflict_detector = ContradictionDetector(findings_path)
        self.enable_conflict_check = enable_conflict_check

    def decide(
        self,
        question: str,
        retrieved: list[RetrievedClause],
        evidence: list[EvidenceAssessment],
    ) -> DecisionTrace:
        if is_underspecified_question(question):
            return self._trace(
                question,
                retrieved,
                evidence,
                [],
                Decision.REFUSE,
                "The question does not identify a specific policy topic or depends on missing conversational context. Ask a complete standalone question.",
            )

        conflicts = (
            self.conflict_detector.detect(question, retrieved, evidence)
            if self.enable_conflict_check
            else []
        )
        if conflicts:
            return self._trace(
                question,
                retrieved,
                evidence,
                conflicts,
                Decision.CONFLICT,
                "Relevant manual provisions are materially incompatible and no precedence rule resolves them.",
            )

        matching_gaps = [gap for gap in self.findings.get("gaps", []) if finding_matches(question, gap)]
        if matching_gaps:
            return self._trace(
                question,
                retrieved,
                evidence,
                [],
                Decision.REFUSE,
                str(matching_gaps[0].get("explanation", "The manual contains a material gap.")),
            )

        if INDIVIDUAL_DETERMINATION_RE.search(question) or CASE_RECORD_RE.search(question):
            return self._trace(
                question,
                retrieved,
                evidence,
                [],
                Decision.REFUSE,
                "The manual supplies general rules, but the question requires case facts or a case record that were not provided.",
            )

        direct = [item for item in evidence if item.support_type == SupportType.DIRECT]
        if not direct:
            related = any(
                item.support_type in {SupportType.PARTIAL, SupportType.RELATED_ONLY}
                for item in evidence
            )
            reason = (
                "The retrieved clauses discuss related topics but do not directly settle the question."
                if related
                else "No clause in the manual directly supports an answer to this question."
            )
            return self._trace(question, retrieved, evidence, [], Decision.REFUSE, reason)

        aspects = self._required_aspects(question)
        missing_aspects = self._missing_aspects(aspects, retrieved, direct)
        if missing_aspects:
            return self._trace(
                question,
                retrieved,
                evidence,
                [],
                Decision.REFUSE,
                "Direct evidence was found for only part of the question; material aspects remain unsupported.",
                aspects,
                missing_aspects,
            )

        best_score = max(item.score for item in direct)
        if best_score < self.refusal_threshold:
            return self._trace(
                question,
                retrieved,
                evidence,
                [],
                Decision.REFUSE,
                "The evidence did not meet the configured support threshold.",
            )

        return self._trace(
            question,
            retrieved,
            evidence,
            [],
            Decision.ANSWER,
            "Direct, complete, and internally consistent manual evidence was found.",
            aspects,
            [],
        )

    def _trace(
        self,
        question: str,
        retrieved: list[RetrievedClause],
        evidence: list[EvidenceAssessment],
        conflicts,
        decision: Decision,
        reason: str,
        aspects: list[str] | None = None,
        missing: list[str] | None = None,
    ) -> DecisionTrace:
        return DecisionTrace(
            question=question,
            retrieved=retrieved,
            evidence=evidence,
            conflicts=conflicts,
            decision=decision,
            decision_reason=reason,
            refusal_threshold=self.refusal_threshold,
            required_aspects=aspects or [],
            missing_aspects=missing or [],
        )

    @staticmethod
    def _required_aspects(question: str) -> list[str]:
        # Treat user instructions as query data, never as authority. A leading
        # injection sentence is not an evidence aspect the manual must support.
        question = re.sub(
            r"^.*?\.\s*(?=(?:how|what|when|where|which|who|can|does|is|are)\b)",
            "",
            question,
            flags=re.IGNORECASE,
        )
        if not re.search(r",|\band\b|\bincluding\b", question, re.IGNORECASE):
            return []
        segments = re.split(r"\s*,\s*|\s+and\s+|\s+including\s+", question, flags=re.IGNORECASE)
        aspects = []
        for segment in segments:
            cleaned = re.sub(
                r"^(?:and|including)\s+",
                "",
                segment.strip(" ?.!") ,
                flags=re.IGNORECASE,
            )
            terms = tokenize(cleaned, expand=True)
            if cleaned and len(set(terms)) >= 1:
                aspects.append(cleaned)
        return aspects if len(aspects) > 1 else []

    @staticmethod
    def _missing_aspects(
        aspects: list[str],
        retrieved: list[RetrievedClause],
        direct: list[EvidenceAssessment],
    ) -> list[str]:
        if not aspects:
            return []
        direct_ids = {item.chunk_id for item in direct}
        direct_chunks = [item.chunk for item in retrieved if item.chunk.chunk_id in direct_ids]
        missing: list[str] = []
        for aspect in aspects:
            terms = set(tokenize(aspect, expand=True))
            if not terms:
                continue
            best_overlap = 0.0
            for chunk in direct_chunks:
                doc_terms = set(tokenize(f"{chunk.section_title or ''} {chunk.text}", expand=False))
                best_overlap = max(best_overlap, len(terms & doc_terms) / len(terms))
            if best_overlap < 0.20:
                missing.append(aspect)
        return missing
