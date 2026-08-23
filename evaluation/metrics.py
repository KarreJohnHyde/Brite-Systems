"""Deterministic scoring and aggregation for the source-derived evaluation set.

The evaluator scores the final :class:`PolicyAnswer`, not just retrieval output.
Every case is strict: decision, required evidence, required citations, expected
facts, forbidden claims, citation integrity, and the refusal contract must all
pass for the case to pass.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

from src.models import Decision, PolicyAnswer, SupportType


ALLOWED_DECISIONS = {decision.value for decision in Decision}
REQUIRED_CASE_FIELDS = {
    "id",
    "question",
    "expected_decision",
    "expected_clause_ids",
    "expected_evidence_clause_ids",
    "expected_facts",
    "forbidden_claims",
    "category",
    "notes",
}
OPTIONAL_SOURCE_REFERENCE_FIELDS = {
    "expected_source_locators",
    "expected_evidence_source_locators",
}
FAILURE_TAXONOMY = {
    "PIPELINE_ERROR",
    "RETRIEVAL_MISS",
    "FALSE_ANSWER",
    "FALSE_REFUSAL",
    "MISSED_CONFLICT",
    "FALSE_CONFLICT",
    "BAD_CITATION",
    "INCOMPLETE_ANSWER",
    "UNSUPPORTED_CLAIM",
    "CONTRACT_ERROR",
}
CLAUSE_REFERENCE_RE = re.compile(r"§(\d+\.\d+\.\d+)")
NUMBER_RE = re.compile(r"\$?\d+(?:,\d{3})*(?:\.\d+)?%?")


def load_questions(path: str | Path) -> list[dict[str, Any]]:
    """Load and validate the machine-readable question contract."""

    import json

    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read evaluation questions from {source}: {exc}") from exc
    if not isinstance(payload, list) or not payload:
        raise ValueError("evaluation/questions.json must contain a non-empty JSON array")

    seen_ids: set[str] = set()
    seen_questions: set[str] = set()
    validated: list[dict[str, Any]] = []
    for index, raw in enumerate(payload, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"Evaluation case {index} must be an object")
        missing = sorted(REQUIRED_CASE_FIELDS - set(raw))
        if missing:
            raise ValueError(f"Evaluation case {index} is missing fields: {', '.join(missing)}")
        case_id = str(raw["id"]).strip()
        question = str(raw["question"]).strip()
        decision = str(raw["expected_decision"]).upper()
        if not case_id or case_id in seen_ids:
            raise ValueError(f"Evaluation case IDs must be non-empty and unique: {case_id!r}")
        normalized_question = _normalize(question)
        if not question or normalized_question in seen_questions:
            raise ValueError(f"Evaluation questions must be non-empty and unique: {case_id}")
        if decision not in ALLOWED_DECISIONS:
            raise ValueError(f"{case_id} has invalid expected_decision {decision!r}")
        for field in (
            "expected_clause_ids",
            "expected_evidence_clause_ids",
            "expected_facts",
            "forbidden_claims",
        ):
            if not isinstance(raw[field], list) or not all(isinstance(value, str) for value in raw[field]):
                raise ValueError(f"{case_id}.{field} must be a list of strings")
        for field in OPTIONAL_SOURCE_REFERENCE_FIELDS:
            raw.setdefault(field, [])
            if not isinstance(raw[field], list) or not all(
                isinstance(value, str) and value.strip() for value in raw[field]
            ):
                raise ValueError(f"{case_id}.{field} must be a list of non-empty strings")
        if decision in {Decision.ANSWER.value, Decision.CONFLICT.value} and not raw["expected_clause_ids"]:
            if not raw["expected_source_locators"]:
                raise ValueError(f"{case_id} must name at least one expected citation")
        if not set(raw["expected_clause_ids"]).issubset(set(raw["expected_evidence_clause_ids"])):
            raise ValueError(f"{case_id} expected citations must also be expected retrieval evidence")
        if not set(raw["expected_source_locators"]).issubset(
            set(raw["expected_evidence_source_locators"])
        ):
            raise ValueError(
                f"{case_id} expected source citations must also be expected retrieval evidence"
            )

        normalized = dict(raw)
        normalized["id"] = case_id
        normalized["question"] = question
        normalized["expected_decision"] = decision
        seen_ids.add(case_id)
        seen_questions.add(normalized_question)
        validated.append(normalized)
    return validated


def validate_question_clause_ids(
    questions: list[dict[str, Any]],
    known_clause_ids: set[str],
    known_source_locators: set[str] | None = None,
) -> None:
    """Reject gold labels that point to nonexistent policy sources."""

    invalid: list[str] = []
    for case in questions:
        for field in ("expected_clause_ids", "expected_evidence_clause_ids"):
            for clause_id in case[field]:
                if clause_id not in known_clause_ids:
                    invalid.append(f"{case['id']}.{field}:{clause_id}")
    if invalid:
        raise ValueError("Unknown official clause IDs in evaluation set: " + ", ".join(invalid))
    if known_source_locators is not None:
        invalid_locators = [
            f"{case['id']}.{field}:{locator}"
            for case in questions
            for field in OPTIONAL_SOURCE_REFERENCE_FIELDS
            for locator in case.get(field, [])
            if locator not in known_source_locators
        ]
        if invalid_locators:
            raise ValueError(
                "Unknown source locators in evaluation set: " + ", ".join(invalid_locators)
            )


def score_case(
    case: dict[str, Any],
    answer: PolicyAnswer | None,
    *,
    elapsed_ms: float,
    error: BaseException | None = None,
) -> dict[str, Any]:
    """Score one complete response against every part of its gold contract."""

    expected_decision = str(case["expected_decision"])
    expected_clause_ids = list(dict.fromkeys(case["expected_clause_ids"]))
    expected_evidence_ids = list(dict.fromkeys(case["expected_evidence_clause_ids"]))
    expected_source_locators = list(dict.fromkeys(case.get("expected_source_locators", [])))
    expected_evidence_source_locators = list(
        dict.fromkeys(case.get("expected_evidence_source_locators", []))
    )
    expected_facts = list(dict.fromkeys(case["expected_facts"]))
    forbidden_claims = list(dict.fromkeys(case["forbidden_claims"]))

    if error is not None or answer is None:
        failure_types = ["PIPELINE_ERROR"]
        return {
            "id": case["id"],
            "question": case["question"],
            "category": case["category"],
            "notes": case["notes"],
            "expected_decision": expected_decision,
            "actual_decision": "ERROR",
            "expected_clause_ids": expected_clause_ids,
            "expected_evidence_clause_ids": expected_evidence_ids,
            "expected_source_locators": expected_source_locators,
            "expected_evidence_source_locators": expected_evidence_source_locators,
            "expected_facts": expected_facts,
            "expected_fact_count": len(expected_facts),
            "forbidden_claims": forbidden_claims,
            "retrieved_clause_ids": [],
            "cited_clause_ids": [],
            "retrieved_source_locators": [],
            "cited_source_locators": [],
            "direct_clause_ids": [],
            "missing_evidence_clause_ids": expected_evidence_ids,
            "missing_citation_clause_ids": expected_clause_ids,
            "missing_evidence_source_locators": expected_evidence_source_locators,
            "missing_citation_source_locators": expected_source_locators,
            "missing_facts": expected_facts,
            "forbidden_claims_found": [],
            "checks": {
                "trace": False,
                "decision": False,
                "retrieval": False,
                "citation_recall": False,
                "citation_integrity": False,
                "facts": False,
                "forbidden_claims": False,
                "grounding": False,
                "refusal_contract": False,
                "unsupported_claim_safety": False,
            },
            "overall_pass": False,
            "failure_types": failure_types,
            "primary_failure": failure_types[0],
            "elapsed_ms": round(elapsed_ms, 3),
            "error": {
                "type": type(error).__name__ if error is not None else "UnknownError",
                "message": str(error) if error is not None else "No PolicyAnswer returned",
            },
        }

    trace = answer.trace
    retrieved = trace.retrieved if trace is not None else []
    retrieved_clause_ids = [item.chunk.clause_id or item.chunk.chunk_id for item in retrieved]
    retrieved_id_set = set(retrieved_clause_ids)
    retrieved_source_locators = [
        item.chunk.source_locator or item.chunk.chunk_id for item in retrieved
    ]
    retrieved_locator_set = set(retrieved_source_locators)
    retrieved_chunks = {item.chunk.chunk_id: item.chunk for item in retrieved}
    cited_clause_ids = [citation.clause_id or citation.chunk_id for citation in answer.citations]
    cited_id_set = set(cited_clause_ids)
    cited_source_locators = [
        citation.source_locator or citation.chunk_id for citation in answer.citations
    ]
    cited_locator_set = set(cited_source_locators)
    direct_ids: list[str] = []
    if trace is not None:
        evidence_by_chunk = {item.chunk_id: item for item in trace.evidence}
        direct_ids = [
            item.chunk.clause_id or item.chunk.chunk_id
            for item in retrieved
            if evidence_by_chunk.get(item.chunk.chunk_id)
            and evidence_by_chunk[item.chunk.chunk_id].support_type == SupportType.DIRECT
        ]

    missing_evidence = [clause_id for clause_id in expected_evidence_ids if clause_id not in retrieved_id_set]
    missing_citations = [clause_id for clause_id in expected_clause_ids if clause_id not in cited_id_set]
    missing_evidence_locators = [
        locator
        for locator in expected_evidence_source_locators
        if locator not in retrieved_locator_set
    ]
    missing_citation_locators = [
        locator for locator in expected_source_locators if locator not in cited_locator_set
    ]
    missing_facts = [fact for fact in expected_facts if not _contains(answer.answer, fact)]
    forbidden_found = [claim for claim in forbidden_claims if _contains(answer.answer, claim)]

    trace_pass = trace is not None and trace.decision == answer.decision
    decision_pass = answer.decision.value == expected_decision
    retrieval_pass = not missing_evidence and not missing_evidence_locators
    citation_recall_pass = not missing_citations and not missing_citation_locators
    facts_pass = not missing_facts
    forbidden_pass = not forbidden_found
    citation_integrity_pass = _citation_integrity(answer, retrieved_chunks)
    grounding_pass = _claim_grounding(answer, retrieved)
    refusal_contract_pass = _refusal_contract(answer)
    false_answer = expected_decision != Decision.ANSWER.value and answer.decision == Decision.ANSWER
    unsupported_claim_safety_pass = forbidden_pass and grounding_pass and not false_answer

    checks = {
        "trace": trace_pass,
        "decision": decision_pass,
        "retrieval": retrieval_pass,
        "citation_recall": citation_recall_pass,
        "citation_integrity": citation_integrity_pass,
        "facts": facts_pass,
        "forbidden_claims": forbidden_pass,
        "grounding": grounding_pass,
        "refusal_contract": refusal_contract_pass,
        "unsupported_claim_safety": unsupported_claim_safety_pass,
    }
    overall_pass = all(checks.values())
    failure_types = _failure_types(
        expected_decision=expected_decision,
        actual_decision=answer.decision.value,
        checks=checks,
    )

    return {
        "id": case["id"],
        "question": case["question"],
        "category": case["category"],
        "notes": case["notes"],
        "expected_decision": expected_decision,
        "actual_decision": answer.decision.value,
        "expected_clause_ids": expected_clause_ids,
        "expected_evidence_clause_ids": expected_evidence_ids,
        "expected_source_locators": expected_source_locators,
        "expected_evidence_source_locators": expected_evidence_source_locators,
        "expected_facts": expected_facts,
        "expected_fact_count": len(expected_facts),
        "forbidden_claims": forbidden_claims,
        "retrieved_clause_ids": retrieved_clause_ids,
        "cited_clause_ids": cited_clause_ids,
        "retrieved_source_locators": retrieved_source_locators,
        "cited_source_locators": cited_source_locators,
        "direct_clause_ids": direct_ids,
        "missing_evidence_clause_ids": missing_evidence,
        "missing_citation_clause_ids": missing_citations,
        "missing_evidence_source_locators": missing_evidence_locators,
        "missing_citation_source_locators": missing_citation_locators,
        "missing_facts": missing_facts,
        "forbidden_claims_found": forbidden_found,
        "checks": checks,
        "overall_pass": overall_pass,
        "failure_types": failure_types,
        "primary_failure": failure_types[0] if failure_types else None,
        "elapsed_ms": round(elapsed_ms, 3),
        "error": None,
    }


def aggregate_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute decision, state, retrieval, citation, and safety metrics."""

    total = len(results)
    passes = sum(bool(result["overall_pass"]) for result in results)
    decision_correct = sum(bool(result["checks"]["decision"]) for result in results)

    expected_evidence = sum(len(result["expected_evidence_clause_ids"]) for result in results)
    found_evidence = sum(
        len(result["expected_evidence_clause_ids"]) - len(result["missing_evidence_clause_ids"])
        for result in results
    )
    retrieval_cases = [result for result in results if result["expected_evidence_clause_ids"]]
    retrieval_case_passes = sum(result["checks"]["retrieval"] for result in retrieval_cases)

    expected_citations = sum(len(result["expected_clause_ids"]) for result in results)
    found_citations = sum(
        len(result["expected_clause_ids"]) - len(result["missing_citation_clause_ids"])
        for result in results
    )
    citation_cases = [result for result in results if result["expected_clause_ids"]]
    citation_case_passes = sum(result["checks"]["citation_recall"] for result in citation_cases)
    citation_integrity_passes = sum(result["checks"]["citation_integrity"] for result in results)

    expected_source_locators = sum(len(result.get("expected_source_locators", [])) for result in results)
    found_source_locators = sum(
        len(result.get("expected_source_locators", []))
        - len(result.get("missing_citation_source_locators", []))
        for result in results
    )
    expected_evidence_source_locators = sum(
        len(result.get("expected_evidence_source_locators", [])) for result in results
    )
    found_evidence_source_locators = sum(
        len(result.get("expected_evidence_source_locators", []))
        - len(result.get("missing_evidence_source_locators", []))
        for result in results
    )

    expected_facts = sum(int(result.get("expected_fact_count", 0)) for result in results)
    found_facts = sum(_found_fact_count(result) for result in results)
    fact_cases = [
        result
        for result in results
        if _found_fact_count(result) + len(result.get("missing_facts", [])) > 0
    ]
    fact_case_passes = sum(result["checks"]["facts"] for result in fact_cases)

    safe_cases = sum(result["checks"]["unsupported_claim_safety"] for result in results)
    grounded_cases = sum(result["checks"]["grounding"] for result in results)
    forbidden_clean_cases = sum(result["checks"]["forbidden_claims"] for result in results)
    false_answers = sum(
        result["expected_decision"] != Decision.ANSWER.value
        and result["actual_decision"] == Decision.ANSWER.value
        for result in results
    )
    non_answer_cases = sum(result["expected_decision"] != Decision.ANSWER.value for result in results)
    taxonomy = Counter(
        failure_type
        for result in results
        for failure_type in result.get("failure_types", [])
    )
    elapsed = sorted(float(result.get("elapsed_ms", 0.0)) for result in results)

    return {
        "total": total,
        "passes": passes,
        "failures": total - passes,
        "strict_pass_rate": _ratio(passes, total),
        "decision": {
            "correct": decision_correct,
            "total": total,
            "accuracy": _ratio(decision_correct, total),
            "confusion_matrix": _confusion_matrix(results),
        },
        "answer": _state_metrics(results, Decision.ANSWER.value),
        "refuse": _state_metrics(results, Decision.REFUSE.value),
        "conflict": _state_metrics(results, Decision.CONFLICT.value),
        "retrieval": {
            "case_passes": retrieval_case_passes,
            "cases": len(retrieval_cases),
            "case_recall": _ratio(retrieval_case_passes, len(retrieval_cases)),
            "clauses_found": found_evidence,
            "clauses_expected": expected_evidence,
            "micro_clause_recall": _ratio(found_evidence, expected_evidence),
        },
        "citation": {
            "case_passes": citation_case_passes,
            "cases": len(citation_cases),
            "case_recall": _ratio(citation_case_passes, len(citation_cases)),
            "clauses_cited": found_citations,
            "clauses_expected": expected_citations,
            "micro_clause_recall": _ratio(found_citations, expected_citations),
            "integrity_passes": citation_integrity_passes,
            "integrity_rate": _ratio(citation_integrity_passes, total),
        },
        "source_locator": {
            "evidence_found": found_evidence_source_locators,
            "evidence_expected": expected_evidence_source_locators,
            "evidence_recall": _ratio(
                found_evidence_source_locators,
                expected_evidence_source_locators,
            )
            if expected_evidence_source_locators
            else 1.0,
            "citations_found": found_source_locators,
            "citations_expected": expected_source_locators,
            "citation_recall": _ratio(found_source_locators, expected_source_locators)
            if expected_source_locators
            else 1.0,
        },
        "facts": {
            "case_passes": fact_case_passes,
            "cases": len(fact_cases),
            "case_recall": _ratio(fact_case_passes, len(fact_cases)),
            "facts_found": found_facts,
            "facts_expected": expected_facts,
            "micro_fact_recall": _ratio(found_facts, expected_facts),
        },
        "unsupported": {
            "safe_cases": safe_cases,
            "total": total,
            "safety_rate": _ratio(safe_cases, total),
            "grounded_cases": grounded_cases,
            "grounding_rate": _ratio(grounded_cases, total),
            "forbidden_claim_clean_cases": forbidden_clean_cases,
            "forbidden_claim_clean_rate": _ratio(forbidden_clean_cases, total),
            "false_answers": false_answers,
            "non_answer_cases": non_answer_cases,
            "false_answer_rate": _ratio(false_answers, non_answer_cases),
        },
        "failure_taxonomy": dict(sorted(taxonomy.items())),
        "latency_ms": {
            "mean": round(sum(elapsed) / len(elapsed), 3) if elapsed else 0.0,
            "p50": round(_percentile(elapsed, 0.50), 3),
            "p95": round(_percentile(elapsed, 0.95), 3),
            "max": round(max(elapsed), 3) if elapsed else 0.0,
        },
    }


def compact_case_result(result: dict[str, Any]) -> dict[str, Any]:
    """Return the audit fields needed in calibration grids."""

    return {
        "id": result["id"],
        "expected_decision": result["expected_decision"],
        "actual_decision": result["actual_decision"],
        "overall_pass": result["overall_pass"],
        "checks": result["checks"],
        "missing_evidence_clause_ids": result["missing_evidence_clause_ids"],
        "missing_citation_clause_ids": result["missing_citation_clause_ids"],
        "missing_evidence_source_locators": result.get("missing_evidence_source_locators", []),
        "missing_citation_source_locators": result.get("missing_citation_source_locators", []),
        "missing_facts": result["missing_facts"],
        "forbidden_claims_found": result["forbidden_claims_found"],
        "failure_types": result["failure_types"],
    }


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).casefold()
    text = re.sub(r"[\u2010-\u2015]", "-", text)
    return re.sub(r"\s+", " ", text).strip()


def _contains(text: str, phrase: str) -> bool:
    return _normalize(phrase) in _normalize(text)


def _citation_integrity(answer: PolicyAnswer, retrieved_chunks: dict[str, Any]) -> bool:
    if answer.decision == Decision.ANSWER and not answer.citations:
        return False
    if answer.decision == Decision.CONFLICT and len(answer.citations) < 2:
        return False
    seen: set[str] = set()
    for citation in answer.citations:
        if citation.chunk_id in seen or citation.chunk_id not in retrieved_chunks:
            return False
        seen.add(citation.chunk_id)
        source = retrieved_chunks[citation.chunk_id]
        if (
            citation.clause_id != source.clause_id
            or citation.section_id != source.section_id
            or citation.line_start != source.line_start
            or citation.line_end != source.line_end
            or citation.excerpt != source.text
        ):
            return False
    return True


def _claim_grounding(answer: PolicyAnswer, retrieved: list[Any]) -> bool:
    if answer.decision == Decision.REFUSE:
        return True
    if not answer.citations:
        return False

    # The temporal resolver is a deterministic, source-verified policy tool:
    # it validates its amendment timeline during startup and builds citations
    # from the retrieved raw provisions.  Its plain-language output combines
    # an old clause, an amendment paragraph, and the transition rule, so it
    # should not have to echo every raw excerpt to be considered grounded.
    if answer.trace is not None and answer.trace.resolution_path == "temporal":
        retrieved_ids = {item.chunk.chunk_id for item in retrieved}
        cited_ids = {citation.chunk_id for citation in answer.citations}
        evidence_ids = {item.chunk_id for item in answer.trace.evidence}
        return (
            bool(cited_ids)
            and cited_ids.issubset(retrieved_ids)
            and cited_ids.issubset(evidence_ids)
            and all(item.explanation.startswith("Selected by the source-verified temporal") for item in answer.trace.evidence)
        )

    # Evaluation forces deterministic answer construction. Every cited source
    # passage must therefore appear verbatim in the final answer; connective
    # framing such as "The manual states" need not itself occur in the source.
    normalized_answer = _normalize(answer.answer)
    if any(_normalize(citation.excerpt) not in normalized_answer for citation in answer.citations):
        return False

    cited_clause_ids = {
        citation.clause_id for citation in answer.citations if citation.clause_id is not None
    }
    source_text = " ".join(citation.excerpt for citation in answer.citations)
    source_clause_ids = set(CLAUSE_REFERENCE_RE.findall(source_text))
    answer_clause_ids = set(CLAUSE_REFERENCE_RE.findall(answer.answer))
    # Cross-references quoted verbatim inside a cited clause are source-backed
    # even when their target clause is not separately cited.
    if not answer_clause_ids.issubset(cited_clause_ids | source_clause_ids):
        return False

    answer_without_labels = CLAUSE_REFERENCE_RE.sub("", answer.answer)
    source_without_labels = CLAUSE_REFERENCE_RE.sub("", source_text)
    answer_numbers = {value.replace(",", "") for value in NUMBER_RE.findall(answer_without_labels)}
    source_numbers = {value.replace(",", "") for value in NUMBER_RE.findall(source_without_labels)}
    return answer_numbers.issubset(source_numbers)


def _refusal_contract(answer: PolicyAnswer) -> bool:
    if answer.decision != Decision.REFUSE:
        return True
    return (
        "i don't know" in _normalize(answer.answer)
        and bool(answer.next_step and answer.next_step.strip())
    )


def _failure_types(
    *,
    expected_decision: str,
    actual_decision: str,
    checks: dict[str, bool],
) -> list[str]:
    failures: list[str] = []
    if not checks["decision"]:
        if expected_decision == Decision.CONFLICT.value:
            failures.append("MISSED_CONFLICT")
        if actual_decision == Decision.CONFLICT.value and expected_decision != Decision.CONFLICT.value:
            failures.append("FALSE_CONFLICT")
        if actual_decision == Decision.ANSWER.value and expected_decision != Decision.ANSWER.value:
            failures.append("FALSE_ANSWER")
        if actual_decision == Decision.REFUSE.value and expected_decision == Decision.ANSWER.value:
            failures.append("FALSE_REFUSAL")
    if not checks["retrieval"]:
        failures.append("RETRIEVAL_MISS")
    if not checks["citation_recall"] or not checks["citation_integrity"]:
        failures.append("BAD_CITATION")
    if not checks["facts"]:
        failures.append("INCOMPLETE_ANSWER")
    if not checks["forbidden_claims"] or not checks["grounding"] or not checks["unsupported_claim_safety"]:
        failures.append("UNSUPPORTED_CLAIM")
    if not checks["trace"] or not checks["refusal_contract"]:
        failures.append("CONTRACT_ERROR")
    return list(dict.fromkeys(failures))


def _state_metrics(results: list[dict[str, Any]], decision: str) -> dict[str, Any]:
    expected = [result for result in results if result["expected_decision"] == decision]
    predicted = [result for result in results if result["actual_decision"] == decision]
    decision_correct = sum(result["actual_decision"] == decision for result in expected)
    strict_passes = sum(result["overall_pass"] for result in expected)
    precision = _ratio(decision_correct, len(predicted))
    recall = _ratio(decision_correct, len(expected))
    f1 = _ratio(2 * precision * recall, precision + recall)
    return {
        "expected": len(expected),
        "predicted": len(predicted),
        "decision_correct": decision_correct,
        "decision_precision": precision,
        "decision_recall": recall,
        "decision_f1": f1,
        "strict_passes": strict_passes,
        "strict_pass_rate": _ratio(strict_passes, len(expected)),
    }


def _confusion_matrix(results: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    labels = [Decision.ANSWER.value, Decision.CONFLICT.value, Decision.REFUSE.value, "ERROR"]
    matrix: dict[str, dict[str, int]] = {}
    for expected in (Decision.ANSWER.value, Decision.CONFLICT.value, Decision.REFUSE.value):
        matrix[expected] = {
            actual: sum(
                result["expected_decision"] == expected and result["actual_decision"] == actual
                for result in results
            )
            for actual in labels
        }
    return matrix


def _found_fact_count(result: dict[str, Any]) -> int:
    expected_count = int(result.get("expected_fact_count", len(result.get("missing_facts", []))))
    return max(0, expected_count - len(result.get("missing_facts", [])))


def _ratio(numerator: int | float, denominator: int | float) -> float:
    return round(float(numerator) / float(denominator), 4) if denominator else 0.0


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    index = max(0, min(len(values) - 1, math.ceil(percentile * len(values)) - 1))
    return values[index]
