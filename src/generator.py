"""Deterministic source-first answer construction and optional LLM phrasing."""

from __future__ import annotations

import logging
from pathlib import Path

from src.citations import CitationIntegrityError, CitationValidator
from src.evidence import INTENT_TERMS, finding_matches, load_findings
from src.lexical import tokenize
from src.models import (
    Decision,
    DecisionTrace,
    EvidenceAssessment,
    EvidenceLevel,
    PolicyAnswer,
    RetrievedClause,
    SupportType,
)
from src.refusal import load_contacts, refusal_text, select_next_step
from src.query_analysis import requested_clause_lookup_ids
from src.retriever import NUMERIC_PASSAGE_RE, NUMERIC_QUESTION_RE


LOGGER = logging.getLogger("grounded_answer.generator")


class AnswerBuilder:
    """Construct answers only after the decision engine has completed."""

    def __init__(
        self,
        *,
        contacts_path: str | Path | None = None,
        findings_path: str | Path | None = None,
        llm_provider=None,
        enable_claim_validation: bool = True,
    ) -> None:
        self.contacts = load_contacts(contacts_path)
        self.findings = load_findings(findings_path)
        self.llm_provider = llm_provider
        self.enable_claim_validation = enable_claim_validation

    def build(self, trace: DecisionTrace, *, include_trace: bool = False) -> PolicyAnswer:
        if trace.decision == Decision.CONFLICT:
            answer = self._build_conflict(trace)
        elif trace.decision == Decision.REFUSE:
            answer = self._build_refusal(trace)
        else:
            answer = self._build_answer(trace)
        return answer.model_copy(update={"trace": trace if include_trace else None})

    def _build_answer(self, trace: DecisionTrace) -> PolicyAnswer:
        selected = self._select_direct_sources(trace)
        validator = CitationValidator(trace.retrieved)
        source_ids = [item.chunk.chunk_id for item in selected]
        citations = validator.build(source_ids)

        # A request to read a named clause is best served verbatim. The provider
        # intentionally receives opaque IDs, so asking it to infer the official
        # clause label would either force a guess or cause a needless refusal.
        if self.llm_provider is not None and not requested_clause_lookup_ids(trace.question):
            try:
                generated = self.llm_provider.generate_answer(
                    trace.question,
                    [item.chunk for item in trace.retrieved],
                )
                if generated.decision != Decision.ANSWER:
                    raise CitationIntegrityError(
                        f"Generator attempted to change trusted decision to {generated.decision.value}"
                    )
                validator.validate_source_ids(generated.supporting_source_ids)
                if self.enable_claim_validation:
                    validator.validate_claims(generated.answer, generated.supporting_source_ids)
                citations = validator.build(generated.supporting_source_ids)
                answer_text = generated.answer.strip()
            except Exception as exc:
                # The decision and sources were already validated before the
                # optional phrasing call. Never show rejected model text; retain
                # availability by falling back to the exact trusted clauses.
                LOGGER.warning(
                    "Optional answer phrasing failed validation; using trusted source text (%s)",
                    type(exc).__name__,
                )
                answer_text = self._verbatim_answer(selected)
        else:
            answer_text = self._verbatim_answer(selected)

        level = self._evidence_level(trace, source_ids)
        return PolicyAnswer(
            decision=Decision.ANSWER,
            answer=answer_text,
            citations=citations,
            evidence_level=level,
            reason=trace.decision_reason,
        )

    def _build_refusal(self, trace: DecisionTrace) -> PolicyAnswer:
        validator = CitationValidator(trace.retrieved)
        relevant_ids: list[str] = []
        for gap in self.findings.get("gaps", []):
            if finding_matches(trace.question, gap):
                wanted = set(gap.get("clause_ids", []))
                relevant_ids = [
                    item.chunk.chunk_id
                    for item in trace.retrieved
                    if item.chunk.clause_id in wanted
                ]
                break
        citations = validator.build(relevant_ids, require_any=False)
        return PolicyAnswer(
            decision=Decision.REFUSE,
            answer=refusal_text(trace),
            citations=citations,
            evidence_level=EvidenceLevel.LOW,
            reason=trace.decision_reason,
            next_step=select_next_step(trace.question, self.contacts),
        )

    def _build_conflict(self, trace: DecisionTrace) -> PolicyAnswer:
        validator = CitationValidator(trace.retrieved)
        conflict_ids = {
            chunk_id for finding in trace.conflicts for chunk_id in finding.chunk_ids
        }
        # Include a direct applicability clause when it is distinct from the two
        # conflicting consequences (for example, failure to attend an interview).
        direct = self._direct_pairs(trace)
        for result, assessment in direct:
            if result.chunk.chunk_id not in conflict_ids and assessment.score >= 0.62:
                conflict_ids.add(result.chunk.chunk_id)
                break
        ordered_ids = [
            item.chunk.chunk_id for item in trace.retrieved if item.chunk.chunk_id in conflict_ids
        ]
        citations = validator.build(ordered_ids)
        cited_chunks = validator.validate_source_ids(ordered_ids)
        lines = ["The manual contains conflicting guidance for this question."]
        for chunk in cited_chunks:
            lines.append(f"{self._display_reference(chunk)}: {chunk.text}")
        lines.append("Because the manual does not establish which rule controls, I cannot provide a single answer.")
        return PolicyAnswer(
            decision=Decision.CONFLICT,
            answer="\n\n".join(lines),
            citations=citations,
            evidence_level=EvidenceLevel.LOW,
            reason=trace.conflicts[0].explanation,
            next_step=str(self.contacts["conflict"]["next_step"]),
        )

    def _select_direct_sources(self, trace: DecisionTrace) -> list[RetrievedClause]:
        pairs = self._direct_pairs(trace)
        if not pairs:
            raise CitationIntegrityError("Decision was ANSWER but no DIRECT sources remained")

        lookup_ids = requested_clause_lookup_ids(trace.question)
        if lookup_ids:
            exact = [
                result
                for result, _ in pairs
                if result.chunk.clause_id in lookup_ids
            ]
            if exact:
                return sorted(exact, key=lambda item: item.chunk.source_order)

        selected: list[RetrievedClause] = []
        if trace.required_aspects:
            for aspect in trace.required_aspects:
                aspect_terms = set(tokenize(aspect, expand=True))
                selected_sections = {item.chunk.section_id for item in selected}
                ranked = sorted(
                    pairs,
                    key=lambda pair: (
                        self._overlap(aspect_terms, pair[0])
                        + (0.30 if pair[0].chunk.section_id in selected_sections else 0.0)
                        + (0.04 if pair[0].chunk.chunk_id not in {item.chunk.chunk_id for item in selected} else 0.0)
                        + (0.28 if (
                            bool(NUMERIC_QUESTION_RE.search(aspect))
                            and bool(NUMERIC_PASSAGE_RE.search(pair[0].chunk.text))
                        ) else 0.0),
                        pair[1].score,
                        pair[0].ranking_score,
                    ),
                    reverse=True,
                )
                if ranked and self._overlap(aspect_terms, ranked[0][0]) > 0:
                    self._append_unique(selected, ranked[0][0])
        else:
            best = max(pairs, key=lambda pair: (pair[1].score, pair[0].ranking_score))
            selected.append(best[0])

        # "Including exceptions" calls for every direct clause in the selected
        # rule's section so neither the standard nor extended rule is hidden.
        if "exception" in trace.question.lower() and selected:
            sections = {item.chunk.section_id for item in selected}
            for result, assessment in pairs:
                if result.chunk.section_id in sections and assessment.score >= 0.58:
                    self._append_unique(selected, result)

        # A selected cross-reference can be material to a compound answer (for
        # example the review-completion period incorporated by §12.1.3).
        selected_refs = {reference for item in selected for reference in item.chunk.cross_references}
        for result, assessment in pairs:
            if (
                result.chunk.clause_id in selected_refs
                or result.chunk.section_id in selected_refs
            ) and assessment.score >= 0.58:
                self._append_unique(selected, result)

        if not selected:
            selected.append(max(pairs, key=lambda pair: pair[1].score)[0])
        return selected[:6]

    @staticmethod
    def _append_unique(items: list[RetrievedClause], candidate: RetrievedClause) -> None:
        if all(item.chunk.chunk_id != candidate.chunk.chunk_id for item in items):
            items.append(candidate)

    @staticmethod
    def _overlap(aspect_terms: set[str], result: RetrievedClause) -> float:
        document_terms = set(tokenize(f"{result.chunk.section_title or ''} {result.chunk.text}", expand=False))
        full = len(aspect_terms & document_terms) / max(1, len(aspect_terms))
        subject_terms = aspect_terms - INTENT_TERMS
        if not subject_terms:
            return full
        subject = len(subject_terms & document_terms) / len(subject_terms)
        return 0.70 * subject + 0.30 * full

    @staticmethod
    def _direct_pairs(trace: DecisionTrace) -> list[tuple[RetrievedClause, EvidenceAssessment]]:
        by_id = {item.chunk_id: item for item in trace.evidence}
        return [
            (result, by_id[result.chunk.chunk_id])
            for result in trace.retrieved
            if result.chunk.chunk_id in by_id
            and by_id[result.chunk.chunk_id].support_type == SupportType.DIRECT
        ]

    @staticmethod
    def _display_reference(chunk) -> str:
        if chunk.clause_id:
            return f"§{chunk.clause_id}"
        return chunk.source_locator_label or chunk.source_locator or chunk.chunk_id

    @staticmethod
    def _verbatim_answer(selected: list[RetrievedClause]) -> str:
        if len(selected) == 1:
            chunk = selected[0].chunk
            return f"The manual states in {AnswerBuilder._display_reference(chunk)}: {chunk.text}"
        lines = ["The manual states:"]
        lines.extend(
            f"- {AnswerBuilder._display_reference(item.chunk)}: {item.chunk.text}"
            for item in selected
        )
        return "\n".join(lines)

    @staticmethod
    def _evidence_level(trace: DecisionTrace, source_ids: list[str]) -> EvidenceLevel:
        scores = [item.score for item in trace.evidence if item.chunk_id in source_ids]
        if scores and min(scores) >= 0.72:
            return EvidenceLevel.HIGH
        return EvidenceLevel.MEDIUM


# The old AnswerGenerator name remains an alias for imports, but callers should
# instantiate AnswerBuilder and optionally inject an LLMProvider.
AnswerGenerator = AnswerBuilder
