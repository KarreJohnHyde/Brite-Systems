from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from training.data import (
    FOLD_1_IDS,
    FOLD_2_IDS,
    build_training_rows,
    clause_disjoint_folds,
    guarded_negative_ids,
    load_training_cases,
)
from training.metrics import binary_metrics, ranking_metrics


def _expected_ids(cases: list[dict], field: str) -> set[str]:
    return {clause_id for case in cases for clause_id in case[field]}


def test_reviewed_folds_cover_every_case_once_without_clause_leakage(
    project_root: Path,
    chunks,
) -> None:
    cases = load_training_cases(
        [
            project_root / "evaluation" / "questions.json",
            project_root / "evaluation" / "adversarial_questions.json",
        ],
        known_clause_ids={chunk.clause_id for chunk in chunks if chunk.clause_id},
    )

    folds = clause_disjoint_folds(cases)
    fold_1_test = {case["id"] for case in folds["fold_1"]["test"]}
    fold_2_test = {case["id"] for case in folds["fold_2"]["test"]}

    assert fold_1_test == set(FOLD_1_IDS)
    assert fold_2_test == set(FOLD_2_IDS)
    assert fold_1_test.isdisjoint(fold_2_test)
    assert fold_1_test | fold_2_test == {case["id"] for case in cases}
    assert {case["id"] for case in folds["fold_1"]["train"]} == fold_2_test
    assert {case["id"] for case in folds["fold_2"]["train"]} == fold_1_test

    assert Counter(case["expected_decision"] for case in folds["fold_1"]["test"]) == {
        "ANSWER": 8,
        "CONFLICT": 1,
        "REFUSE": 7,
    }
    assert Counter(case["expected_decision"] for case in folds["fold_2"]["test"]) == {
        "ANSWER": 8,
        "CONFLICT": 2,
        "REFUSE": 7,
    }

    for fold in folds.values():
        assert _expected_ids(fold["train"], "expected_evidence_clause_ids").isdisjoint(
            _expected_ids(fold["test"], "expected_evidence_clause_ids")
        )
        assert _expected_ids(fold["train"], "expected_clause_ids").isdisjoint(
            _expected_ids(fold["test"], "expected_clause_ids")
        )


def test_guarded_negatives_exclude_gold_section_neighbors_and_cross_references(
    make_chunk,
) -> None:
    def chunk(clause_id: str, **kwargs):
        return make_chunk(
            chunk_id=f"chunk_{clause_id.replace('.', '_')}",
            clause_id=clause_id,
            **kwargs,
        )

    chunks = [
        chunk("1.0.1", section_id="1.0", source_order=0),
        chunk("1.0.2", section_id="1.0", source_order=1),  # adjacent before
        chunk(
            "1.1.1",
            section_id="1.1",
            source_order=2,
            cross_references=["2.2.1"],
        ),
        chunk("1.2.1", section_id="1.2", source_order=3),  # adjacent after
        chunk("1.1.2", section_id="1.1", source_order=7),  # same section
        chunk("2.2.1", section_id="2.2", source_order=8),  # forward reference
        chunk(
            "3.1.1",
            section_id="3.1",
            source_order=9,
            cross_references=["1.1.1"],  # reverse reference
        ),
        chunk("4.1.1", section_id="4.1", source_order=10),
        chunk("5.1.1", section_id="5.1", source_order=11),
    ]
    case = {"id": "T01", "expected_evidence_clause_ids": ["1.1.1"]}
    ranked = [
        "unknown",
        "1.1.1",
        "1.1.2",
        "1.0.2",
        "1.2.1",
        "2.2.1",
        "3.1.1",
        "4.1.1",
        "4.1.1",
        "5.1.1",
    ]

    assert guarded_negative_ids(case, ranked, chunks, limit=2) == ["4.1.1", "5.1.1"]
    assert guarded_negative_ids(
        case,
        ranked,
        chunks,
        limit=1,
        exclude_clause_ids={"4.1.1"},
    ) == ["5.1.1"]


def test_training_rows_never_duplicate_or_flip_pair_labels(make_chunk) -> None:
    positive = make_chunk(
        chunk_id="chunk_positive",
        clause_id="1.1.1",
        section_id="1.1",
        source_order=0,
    )
    negative_1 = make_chunk(
        chunk_id="chunk_negative_1",
        clause_id="2.1.1",
        section_id="2.1",
        source_order=5,
    )
    negative_2 = make_chunk(
        chunk_id="chunk_negative_2",
        clause_id="3.1.1",
        section_id="3.1",
        source_order=10,
    )
    case = {
        "id": "T02",
        "question": "What is the test rule?",
        "expected_evidence_clause_ids": ["1.1.1"],
    }

    rows = build_training_rows(
        [case],
        [positive, negative_1, negative_2],
        {"T02": ["2.1.1", "3.1.1"]},
        negatives_per_query=2,
    )
    labels_by_key: dict[tuple[str, str], set[float]] = {}
    for pair in rows["pairs"]:
        key = (pair["case_id"], pair["clause_id"])
        labels_by_key.setdefault(key, set()).add(pair["label"])

    assert len(rows["pairs"]) == len(labels_by_key) == 3
    assert labels_by_key == {
        ("T02", "1.1.1"): {1.0},
        ("T02", "2.1.1"): {0.0},
        ("T02", "3.1.1"): {0.0},
    }
    assert len(rows["triplets"]) == 2
    assert all(
        row["positive_clause_id"] != row["negative_clause_id"]
        for row in rows["triplets"]
    )

    with pytest.raises(ValueError, match="also labeled negative"):
        build_training_rows(
            [case],
            [positive],
            {"T02": ["1.1.1"]},
            negatives_per_query=1,
        )


def test_no_evidence_case_builds_only_negative_pairs_and_no_triplets(
    make_chunk,
) -> None:
    negative_1 = make_chunk(
        chunk_id="chunk_negative_1",
        clause_id="2.1.1",
        section_id="2.1",
        source_order=0,
    )
    negative_2 = make_chunk(
        chunk_id="chunk_negative_2",
        clause_id="3.1.1",
        section_id="3.1",
        source_order=4,
    )
    case = {
        "id": "T03",
        "question": "An uncovered policy question",
        "expected_evidence_clause_ids": [],
    }

    rows = build_training_rows(
        [case],
        [negative_1, negative_2],
        {"T03": ["2.1.1", "3.1.1"]},
        negatives_per_query=2,
    )

    assert rows["triplets"] == []
    assert [(row["clause_id"], row["label"]) for row in rows["pairs"]] == [
        ("2.1.1", 0.0),
        ("3.1.1", 0.0),
    ]


def test_toy_ranking_metrics_are_exact_and_deterministic() -> None:
    cases = [
        {"id": "R1", "expected_evidence_clause_ids": ["A", "B"]},
        {"id": "R2", "expected_evidence_clause_ids": ["C"]},
        {"id": "R3", "expected_evidence_clause_ids": []},
    ]
    rankings = {
        "R1": ["A", "X", "B"],
        "R2": ["X", "C"],
        "R3": [],
    }

    first = ranking_metrics(cases, rankings, cutoffs=(1, 2, 3))
    second = ranking_metrics(cases, rankings, cutoffs=(1, 2, 3))

    assert first == second
    assert first == {
        "evaluated_queries": 2,
        "excluded_no_evidence_queries": 1,
        "expected_clauses": 3,
        "mrr": 0.75,
        "recall_at_1": 0.333333,
        "complete_case_recall_at_1": 0.0,
        "hit_rate_at_1": 0.5,
        "ndcg_at_1": 0.5,
        "recall_at_2": 0.666667,
        "complete_case_recall_at_2": 0.5,
        "hit_rate_at_2": 1.0,
        "ndcg_at_2": 0.622038,
        "recall_at_3": 1.0,
        "complete_case_recall_at_3": 1.0,
        "hit_rate_at_3": 1.0,
        "ndcg_at_3": 0.775325,
    }


def test_toy_binary_metrics_are_exact_and_deterministic() -> None:
    labels = [1.0, 1.0, 0.0, 0.0]
    logits = [2.0, -1.0, 1.0, -2.0]

    first = binary_metrics(labels, logits)
    second = binary_metrics(labels, logits)

    assert first == second
    assert first == {
        "examples": 4,
        "positives": 2,
        "negatives": 2,
        "zero_logit_accuracy": 0.5,
        "roc_auc": 0.75,
        "mean_positive_logit": 0.5,
        "mean_negative_logit": -0.5,
    }
