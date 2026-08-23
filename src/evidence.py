"""Independent question-to-clause support assessment."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from src.lexical import STOP_WORDS, conservative_fuzzy_match, tokenize
from src.models import EvidenceAssessment, PolicyChunk, RetrievedClause, SupportType
from src.query_analysis import requested_clause_lookup_ids
from src.retriever import LIST_QUESTION_RE, NUMERIC_PASSAGE_RE, NUMERIC_QUESTION_RE

BOOLEAN_RE = re.compile(r"^\s*(can|could|does|do|is|are|may|must|will|would)\b", re.IGNORECASE)
CLASSIFICATION_RE = re.compile(
    r"\b(count(?:ed)? as|counted|classif(?:y|ied)|disregard(?:ed)?|eligible|eligibility|qualify)\b",
    re.IGNORECASE,
)
CLASSIFICATION_PASSAGE_RE = re.compile(
    r"\b(count(?:ed|able)?|treated as|disregard(?:ed)?|eligible|ineligible|not allowable)\b",
    re.IGNORECASE,
)
EXCEPTION_QUESTION_RE = re.compile(r"\b(exception|including|unless|beyond|over|good cause)\b", re.IGNORECASE)
EXCEPTION_PASSAGE_RE = re.compile(r"\b(except|unless|extended|where|good cause|outside .* control)\b", re.IGNORECASE)
MODALITY_RE = re.compile(r"\b(must|may|shall|is not|are not|eligible|ineligible|required|prohibited)\b", re.IGNORECASE)
CONTINUATION_QUESTION_RE = re.compile(
    r"\b(keep (?:getting|receiving)|continue|still|remain)\b",
    re.IGNORECASE,
)
CONTINUATION_PASSAGE_RE = re.compile(
    r"\b(continues? to satisfy|continues? to be eligible|remains? (?:eligible|a household member))\b",
    re.IGNORECASE,
)
APPLICATION_METHOD_QUESTION_RE = re.compile(
    r"\b(how (?:do|can|may|should) (?:i|we|a person|an applicant) apply|"
    r"ways? (?:to apply|an application may be made)|application methods?)\b",
    re.IGNORECASE,
)
APPLICATION_METHOD_PASSAGE_RE = re.compile(
    r"\ban application may be made\b",
    re.IGNORECASE,
)
SERVICE_ACCESS_QUESTION_RE = re.compile(
    r"\b(?:(?:where|how)\s+(?:can|do|may|should)\s+"
    r"(?:(?:i|we|someone|an? (?:applicant|person)|applicants?|people)\s+)?"
    r"(?:get|find|access|obtain)|who\s+(?:can|do|should|may)\s+"
    r"(?:(?:i|we|someone|an? (?:applicant|person)|applicants?|people)\s+)?"
    r"(?:ask|contact|call))\b",
    re.IGNORECASE,
)
SERVICE_ACCESS_TOPIC_RE = re.compile(
    r"\b(?:support|referral|services?|assistance|help)\b",
    re.IGNORECASE,
)
SERVICE_ACCESS_PASSAGE_RE = re.compile(
    r"\b(?:contact|call|in person|online|by (?:post|mail|telephone|phone|email)|"
    r"through (?:the )?department(?:'s)? (?:online )?portal|at (?:any|a|the) "
    r"(?:district )?office|an application may be made)\b",
    re.IGNORECASE,
)
GENERIC_SUBJECT_TERMS = {
    "manual", "policy", "say", "state", "rule", "question", "exactly", "actually",
    "standard", "include", "including", "apply", "applicable", "hsp", "program",
}
INTENT_TERMS = {
    "amount", "calendar", "day", "deadline", "figure", "how", "limit", "long", "many", "much",
    "month", "monthly", "percentage", "period", "rate", "threshold", "time", "week", "year",
    "what", "when", "where", "which", "who",
}

# These words describe the form of a question, not the policy object that must
# appear in evidence.  Requiring a distinctive concept match prevents generic
# modal language ("must", "may", "is") from supporting an unrelated answer.
NON_SUBJECT_TERMS = GENERIC_SUBJECT_TERMS | INTENT_TERMS | {
    "can", "cannot", "classify", "count", "cover", "do", "does", "few", "get",
    "give", "happen", "include", "includ", "list", "make", "made", "may", "must", "occur", "provide",
    "help", "keep", "receive", "remain", "require", "required", "say", "shall", "should", "tell",
    "treat", "treated", "will", "would",
}
ROLE_TERMS = {"applicant", "department", "household", "member", "person", "recipient"}


def load_findings(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {"conflicts": [], "gaps": []}
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"Policy findings file is missing: {source}")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Policy findings file is unreadable: {source}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Policy findings file must contain a JSON object: {source}")
    if not isinstance(payload.get("conflicts", []), list) or not isinstance(payload.get("gaps", []), list):
        raise ValueError(f"Policy findings conflicts/gaps must be lists: {source}")
    return payload


def finding_matches(question: str, finding: dict[str, Any]) -> bool:
    """Conservatively match a source-verified corpus finding to a question."""

    normalized_question = re.sub(r"[-–—]", " ", question.lower())
    trigger_patterns = finding.get("trigger_patterns", [])
    if trigger_patterns:
        return any(re.search(pattern, normalized_question, re.IGNORECASE) for pattern in trigger_patterns)
    phrases = [re.sub(r"[-–—]", " ", term.lower()) for term in finding.get("topic_terms", [])]
    if any(len(phrase.split()) >= 2 and phrase in normalized_question for phrase in phrases):
        return True
    question_terms = set(tokenize(normalized_question, expand=True))
    topic_terms = {token for phrase in phrases for token in tokenize(phrase, expand=True)}
    overlap = question_terms & topic_terms
    required = 1 if len(topic_terms) <= 2 else (2 if len(topic_terms) <= 5 else 3)
    return len(overlap) >= required


class EvidenceAnalyzer:
    """Label retrieved clauses DIRECT/PARTIAL/RELATED_ONLY/NONE.

    Scores are explicit heuristics, not probabilities. A high retrieval score
    cannot by itself produce DIRECT support.
    """

    def __init__(
        self,
        corpus: list[PolicyChunk],
        *,
        refusal_threshold: float = 0.58,
        direct_coverage_threshold: float = 0.34,
        findings_path: str | Path | None = None,
    ) -> None:
        self.corpus = corpus
        self.refusal_threshold = refusal_threshold
        self.direct_coverage_threshold = direct_coverage_threshold
        self.findings = load_findings(findings_path)
        self.corpus_vocabulary = {
            token
            for chunk in corpus
            for token in tokenize(f"{chunk.section_title or ''} {chunk.text}", expand=False)
        }
        self.query_vocabulary = (
            self.corpus_vocabulary
            | STOP_WORDS
            | GENERIC_SUBJECT_TERMS
            | INTENT_TERMS
            | NON_SUBJECT_TERMS
            | ROLE_TERMS
        )

    def assess(self, question: str, results: list[RetrievedClause]) -> list[EvidenceAssessment]:
        question_terms = set(tokenize(question, expand=False))
        expanded_terms = set(tokenize(question, expand=True))
        expanded_terms.update(
            correction
            for term in question_terms
            if (correction := conservative_fuzzy_match(term, self.corpus_vocabulary)) is not None
        )
        lookup_clause_ids = requested_clause_lookup_ids(question)
        subject_terms = {
            term
            for term in question_terms
            if term not in INTENT_TERMS and term not in GENERIC_SUBJECT_TERMS and term not in STOP_WORDS
        }
        matching_gaps = [gap for gap in self.findings.get("gaps", []) if finding_matches(question, gap)]
        gap_clause_ids = {
            clause_id for gap in matching_gaps for clause_id in gap.get("clause_ids", [])
        }

        assessments: list[EvidenceAssessment] = []
        aspect_term_sets = self._aspect_term_sets(question)
        concept_segments = self._concept_segments(question)
        for result in results:
            chunk = result.chunk
            if chunk.clause_id in lookup_clause_ids:
                assessments.append(
                    EvidenceAssessment(
                        chunk_id=chunk.chunk_id,
                        support_type=SupportType.DIRECT,
                        explanation="The user explicitly requested this existing official clause.",
                        score=1.0,
                        topic_coverage=1.0,
                        answer_alignment=1.0,
                        matched_terms=[chunk.clause_id],
                        missing_terms=[],
                    )
                )
                continue
            document_terms = set(
                tokenize(
                    f"{chunk.part_title or ''} {chunk.section_title or ''} {chunk.text}",
                    expand=False,
                )
            )
            matched = sorted(expanded_terms & document_terms)
            denominator = max(1, len(question_terms - GENERIC_SUBJECT_TERMS))
            coverage = min(1.0, len(matched) / denominator)
            if aspect_term_sets:
                coverage = max(
                    coverage,
                    max(
                        min(1.0, len(aspect_terms & document_terms) / max(1, aspect_size))
                        for aspect_terms, aspect_size in aspect_term_sets
                    ),
                )
            subject_matched = expanded_terms & document_terms & (
                subject_terms | (expanded_terms - question_terms)
            )
            alignment = self._answer_alignment(question, chunk)
            concept_coverage, distinctive_match = self._concept_coverage(
                concept_segments,
                document_terms,
            )
            required_concept_coverage = 0.75 if CLASSIFICATION_RE.search(question) else 0.60
            retrieval_signal = max(
                result.lexical_score or 0.0,
                result.fused_score or 0.0,
                result.reranker_score or 0.0,
            )
            score = min(
                1.0,
                0.50 * coverage
                + 0.20 * (result.lexical_score or 0.0)
                + 0.15 * alignment
                + 0.15 * retrieval_signal,
            )

            if chunk.clause_id in gap_clause_ids:
                support_type = SupportType.PARTIAL if coverage >= 0.18 else SupportType.RELATED_ONLY
                explanation = (
                    "This clause is relevant to a verified manual gap but does not settle the question."
                )
            elif (
                (
                    score >= self.refusal_threshold
                    or (alignment >= 0.95 and retrieval_signal >= 0.55 and coverage >= 0.28)
                )
                and coverage >= min(self.direct_coverage_threshold, 0.28 if alignment >= 0.95 else 1.0)
                and bool(subject_matched)
                and alignment >= 0.55
                and concept_coverage >= required_concept_coverage
                and distinctive_match
            ):
                support_type = SupportType.DIRECT
                explanation = "The clause explicitly supplies a rule, condition, value, or procedure asked for."
            elif coverage >= 0.28 and score >= max(0.35, self.refusal_threshold - 0.20):
                support_type = SupportType.PARTIAL
                explanation = "The clause addresses part of the question or omits a material condition/value."
            elif retrieval_signal >= 0.28 or coverage >= 0.15:
                support_type = SupportType.RELATED_ONLY
                explanation = "The clause is topically related but does not resolve the question."
            else:
                support_type = SupportType.NONE
                explanation = "No material support for the question was found in this clause."

            assessments.append(
                EvidenceAssessment(
                    chunk_id=chunk.chunk_id,
                    support_type=support_type,
                    explanation=explanation,
                    score=round(score, 6),
                    topic_coverage=round(coverage, 6),
                    answer_alignment=round(alignment, 6),
                    matched_terms=matched,
                    missing_terms=sorted(subject_terms - document_terms),
                )
            )
        return assessments

    def _concept_segments(self, question: str) -> list[list[set[str]]]:
        """Return synonym-aware concept groups for each material query aspect."""

        # Ignore a leading instruction-like sentence when a later sentence is
        # the actual policy question.  The original question remains in the
        # trace; this only prevents prompt-injection vocabulary from becoming a
        # required policy concept.
        focused = re.sub(
            r"^.*?\.\s*(?=(?:how|what|when|where|which|who|can|does|is|are)\b)",
            "",
            question,
            flags=re.IGNORECASE,
        )
        parts = (
            re.split(r"\s*,\s*|\s+and\s+|\s+including\s+", focused, flags=re.IGNORECASE)
            if re.search(r",|\band\b|\bincluding\b", focused, re.IGNORECASE)
            else [focused]
        )
        segments: list[list[set[str]]] = []
        for part in parts:
            original_terms = set(tokenize(part, expand=False))
            material = [
                term
                for term in original_terms
                if term not in NON_SUBJECT_TERMS
                and term not in ROLE_TERMS
                and not term.replace(".", "").isdigit()
            ]
            groups: list[set[str]] = []
            for term in material:
                correction = conservative_fuzzy_match(term, self.query_vocabulary)
                if correction in (
                    STOP_WORDS
                    | GENERIC_SUBJECT_TERMS
                    | INTENT_TERMS
                    | NON_SUBJECT_TERMS
                    | ROLE_TERMS
                ):
                    continue
                group = set(tokenize(term, expand=True)) | {term}
                if correction is not None:
                    group.add(correction)
                groups.append(group)
            if groups:
                segments.append(groups)
        return segments

    @staticmethod
    def _concept_coverage(
        segments: list[list[set[str]]],
        document_terms: set[str],
    ) -> tuple[float, bool]:
        if not segments:
            return 1.0, True
        best = 0.0
        matched_any = False
        for groups in segments:
            matches = sum(bool(group & document_terms) for group in groups)
            best = max(best, matches / max(1, len(groups)))
            matched_any = matched_any or matches > 0
        return best, matched_any

    @staticmethod
    def _aspect_term_sets(question: str) -> list[tuple[set[str], int]]:
        if not re.search(r",|\band\b|\bincluding\b", question, re.IGNORECASE):
            return []
        segments = re.split(r"\s*,\s*|\s+and\s+|\s+including\s+", question, flags=re.IGNORECASE)
        aspects: list[tuple[set[str], int]] = []
        for segment in segments:
            segment = re.sub(r"^(?:and|including)\s+", "", segment.strip(), flags=re.IGNORECASE)
            original = set(tokenize(segment, expand=False)) - GENERIC_SUBJECT_TERMS
            if not original:
                continue
            expanded = set(tokenize(segment, expand=True)) - GENERIC_SUBJECT_TERMS
            aspects.append((expanded, len(original)))
        return aspects if len(aspects) > 1 else []

    @staticmethod
    def _answer_alignment(question: str, chunk: PolicyChunk) -> float:
        text = f"{chunk.section_title or ''} {chunk.text}"
        numeric_intent = bool(NUMERIC_QUESTION_RE.search(question))
        list_intent = bool(LIST_QUESTION_RE.search(question))
        classification_intent = bool(
            CLASSIFICATION_RE.search(question)
            and not re.search(r",|\band\b|\bincluding\b", question, re.IGNORECASE)
        )
        boolean_intent = bool(BOOLEAN_RE.search(question))
        continuation_intent = bool(CONTINUATION_QUESTION_RE.search(question))
        application_method_intent = bool(APPLICATION_METHOD_QUESTION_RE.search(question))
        service_access_intent = bool(
            SERVICE_ACCESS_QUESTION_RE.search(question)
            and SERVICE_ACCESS_TOPIC_RE.search(question)
        )

        if numeric_intent:
            if NUMERIC_PASSAGE_RE.search(text):
                return 1.0
            if EXCEPTION_QUESTION_RE.search(question) and EXCEPTION_PASSAGE_RE.search(text):
                return 0.9
            if re.search(r",|\band\b|\bincluding\b", question, re.IGNORECASE) and MODALITY_RE.search(text):
                return 0.75
            return 0.2
        if list_intent:
            if "(a)" in chunk.text or "|" in chunk.raw_text or re.search(r"\bfollowing\b|\bmay be made\b", text, re.IGNORECASE):
                return 1.0
            return 0.35
        if classification_intent:
            return 1.0 if CLASSIFICATION_PASSAGE_RE.search(text) else 0.25
        if application_method_intent:
            return 1.0 if APPLICATION_METHOD_PASSAGE_RE.search(text) else 0.2
        if service_access_intent:
            return 1.0 if SERVICE_ACCESS_PASSAGE_RE.search(text) else 0.2
        if continuation_intent:
            return 1.0 if CONTINUATION_PASSAGE_RE.search(text) else 0.25
        if boolean_intent:
            return 1.0 if MODALITY_RE.search(text) else 0.35
        if EXCEPTION_QUESTION_RE.search(question) and EXCEPTION_PASSAGE_RE.search(text):
            return 0.95
        return 0.8 if MODALITY_RE.search(text) or re.search(r"\bis\b|\bare\b", text, re.IGNORECASE) else 0.55


# Backwards-compatible enums/function names are intentionally omitted: callers
# must use EvidenceAnalyzer so score-domain mistakes cannot silently recur.
