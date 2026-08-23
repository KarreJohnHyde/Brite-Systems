"""Validate labels, create clause-disjoint folds, and build guarded pairs."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from evaluation.metrics import load_questions, validate_question_clause_ids
from src.models import PolicyChunk
from src.parser import get_embedding_text


# These folds keep every expected-evidence clause on only one side. Closely
# related paraphrases (for example Q01/A01/A02) stay together as well.
FOLD_1_IDS = frozenset(
    {
        "Q01", "Q03", "Q04", "Q07", "Q08", "Q09", "Q10", "Q13",
        "Q14", "Q18", "A01", "A02", "A06", "A08", "A09", "A12",
    }
)
FOLD_2_IDS = frozenset(
    {
        "Q02", "Q05", "Q06", "Q11", "Q12", "Q15", "Q16", "Q17",
        "A03", "A04", "A05", "A07", "A10", "A11", "A13", "A14", "A15",
    }
)


def load_training_cases(
    paths: Sequence[str | Path],
    *,
    known_clause_ids: set[str],
) -> list[dict[str, Any]]:
    """Load the canonical labels once and reject cross-file duplicates."""

    cases: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_questions: set[str] = set()
    for path in paths:
        source = Path(path).resolve()
        for raw in load_questions(source):
            case_id = str(raw["id"])
            normalized = re.sub(r"\W+", " ", str(raw["question"]).lower()).strip()
            if case_id in seen_ids:
                raise ValueError(f"Duplicate training question ID across files: {case_id}")
            if normalized in seen_questions:
                raise ValueError(f"Duplicate normalized training question across files: {case_id}")
            case = dict(raw)
            case["source_path"] = str(source)
            cases.append(case)
            seen_ids.add(case_id)
            seen_questions.add(normalized)
    validate_question_clause_ids(cases, known_clause_ids)
    return cases


def clause_disjoint_folds(
    cases: Sequence[dict[str, Any]],
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Return two rotating folds where gold evidence clauses never overlap."""

    by_id = {str(case["id"]): case for case in cases}
    expected_ids = FOLD_1_IDS | FOLD_2_IDS
    missing = sorted(expected_ids - set(by_id))
    unexpected = sorted(set(by_id) - expected_ids)
    if missing or unexpected:
        raise ValueError(
            "The reviewed fold definition does not match the canonical questions "
            f"(missing={missing}, unexpected={unexpected})"
        )

    folds: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for name, test_ids in (("fold_1", FOLD_1_IDS), ("fold_2", FOLD_2_IDS)):
        test = [by_id[case_id] for case_id in sorted(test_ids)]
        train = [by_id[case_id] for case_id in sorted(expected_ids - test_ids)]
        train_clauses = {
            clause_id
            for case in train
            for clause_id in case["expected_evidence_clause_ids"]
        }
        test_clauses = {
            clause_id
            for case in test
            for clause_id in case["expected_evidence_clause_ids"]
        }
        overlap = sorted(train_clauses & test_clauses)
        if overlap:
            raise ValueError(f"{name} leaks expected evidence clauses: {overlap}")
        folds[name] = {"train": train, "test": test}
    return folds


def guarded_negative_ids(
    case: dict[str, Any],
    ranked_clause_ids: Iterable[str],
    chunks: Sequence[PolicyChunk],
    *,
    limit: int,
    exclude_clause_ids: Iterable[str] = (),
) -> list[str]:
    """Select hard negatives without treating gold neighbors as negative."""

    by_clause = {chunk.clause_id: chunk for chunk in chunks if chunk.clause_id}
    gold_ids = set(case["expected_evidence_clause_ids"])
    excluded = evidence_guard_ids(gold_ids, chunks) | set(exclude_clause_ids)

    selected: list[str] = []
    for clause_id in ranked_clause_ids:
        if clause_id not in by_clause or clause_id in excluded or clause_id in selected:
            continue
        selected.append(clause_id)
        if len(selected) == limit:
            break
    if len(selected) < limit:
        raise ValueError(
            f"Could not mine {limit} guarded negatives for {case['id']}; found {len(selected)}"
        )
    return selected


def evidence_guard_ids(
    clause_ids: Iterable[str],
    chunks: Sequence[PolicyChunk],
) -> set[str]:
    """Protect evidence plus its local/cross-reference context from false negatives."""

    by_clause = {chunk.clause_id: chunk for chunk in chunks if chunk.clause_id}
    protected = set(clause_ids)
    for clause_id in tuple(protected):
        gold = by_clause[clause_id]
        if gold.section_id:
            protected.update(
                chunk.clause_id
                for chunk in chunks
                if chunk.section_id == gold.section_id and chunk.clause_id
            )
        protected.update(gold.cross_references)
        protected.update(
            chunk.clause_id
            for chunk in chunks
            if chunk.clause_id
            and (
                abs(chunk.source_order - gold.source_order) <= 1
                or clause_id in chunk.cross_references
            )
        )
    return protected


def build_training_rows(
    cases: Sequence[dict[str, Any]],
    chunks: Sequence[PolicyChunk],
    negatives_by_case: dict[str, list[str]],
    *,
    negatives_per_query: int,
) -> dict[str, list[dict[str, Any]]]:
    """Build bi-encoder triplets and binary cross-encoder pairs."""

    by_clause = {chunk.clause_id: chunk for chunk in chunks if chunk.clause_id}
    triplets: list[dict[str, Any]] = []
    pairs: list[dict[str, Any]] = []
    pair_keys: set[tuple[str, str]] = set()

    for case in cases:
        question = str(case["question"])
        case_id = str(case["id"])
        positives = [by_clause[clause_id] for clause_id in case["expected_evidence_clause_ids"]]
        negative_ids = negatives_by_case[case_id][:negatives_per_query]
        negatives = [by_clause[clause_id] for clause_id in negative_ids]

        for positive in positives:
            for negative in negatives:
                triplets.append(
                    {
                        "anchor": question,
                        "positive": get_embedding_text(positive),
                        "negative": get_embedding_text(negative),
                        "case_id": case_id,
                        "positive_clause_id": positive.clause_id,
                        "negative_clause_id": negative.clause_id,
                    }
                )
            key = (case_id, str(positive.clause_id))
            if key not in pair_keys:
                pairs.append(
                    {
                        "query": question,
                        "passage": _cross_encoder_text(positive),
                        "label": 1.0,
                        "case_id": case_id,
                        "clause_id": positive.clause_id,
                    }
                )
                pair_keys.add(key)

        for negative in negatives:
            key = (case_id, str(negative.clause_id))
            if key in pair_keys:
                raise ValueError(f"A gold clause was also labeled negative for {case_id}: {negative.clause_id}")
            pairs.append(
                {
                    "query": question,
                    "passage": _cross_encoder_text(negative),
                    "label": 0.0,
                    "case_id": case_id,
                    "clause_id": negative.clause_id,
                }
            )
            pair_keys.add(key)

    return {"triplets": triplets, "pairs": pairs}


def _cross_encoder_text(chunk: PolicyChunk) -> str:
    return f"{chunk.section_title or chunk.part_title or chunk.document_name}. {chunk.text}"
