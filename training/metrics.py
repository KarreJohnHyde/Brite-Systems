"""Model-level ranking and binary metrics, before RAG context expansion."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any


def ranking_metrics(
    cases: Sequence[dict[str, Any]],
    rankings: dict[str, list[str]],
    *,
    cutoffs: tuple[int, ...] = (1, 3, 6, 10, 24),
) -> dict[str, Any]:
    """Compute micro recall, full-case recall, MRR, and nDCG."""

    relevant_cases = [case for case in cases if case["expected_evidence_clause_ids"]]
    total_relevant = sum(
        len(set(case["expected_evidence_clause_ids"])) for case in relevant_cases
    )
    results: dict[str, Any] = {
        "evaluated_queries": len(relevant_cases),
        "excluded_no_evidence_queries": len(cases) - len(relevant_cases),
        "expected_clauses": total_relevant,
    }
    reciprocal_ranks: list[float] = []
    ndcg_values: dict[int, list[float]] = {cutoff: [] for cutoff in cutoffs}

    for case in relevant_cases:
        gold = set(case["expected_evidence_clause_ids"])
        ranked = rankings[str(case["id"])]
        rank_by_id = {clause_id: index + 1 for index, clause_id in enumerate(ranked)}
        observed = sorted(
            rank_by_id[clause_id] for clause_id in gold if clause_id in rank_by_id
        )
        reciprocal_ranks.append(1.0 / observed[0] if observed else 0.0)
        for cutoff in cutoffs:
            dcg = sum(
                1.0 / math.log2(rank + 1)
                for clause_id, rank in rank_by_id.items()
                if clause_id in gold and rank <= cutoff
            )
            ideal_count = min(len(gold), cutoff)
            ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_count + 1))
            ndcg_values[cutoff].append(dcg / ideal if ideal else 1.0)

    results["mrr"] = _mean(reciprocal_ranks)
    for cutoff in cutoffs:
        found = 0
        complete = 0
        hit = 0
        for case in relevant_cases:
            gold = set(case["expected_evidence_clause_ids"])
            top = set(rankings[str(case["id"])][:cutoff])
            overlap = len(gold & top)
            found += overlap
            complete += int(overlap == len(gold))
            hit += int(overlap > 0)
        results[f"recall_at_{cutoff}"] = (
            found / total_relevant if total_relevant else 1.0
        )
        results[f"complete_case_recall_at_{cutoff}"] = (
            complete / len(relevant_cases) if relevant_cases else 1.0
        )
        results[f"hit_rate_at_{cutoff}"] = (
            hit / len(relevant_cases) if relevant_cases else 1.0
        )
        results[f"ndcg_at_{cutoff}"] = _mean(ndcg_values[cutoff])
    return {
        key: round(value, 6) if isinstance(value, float) else value
        for key, value in results.items()
    }


def binary_metrics(
    labels: Sequence[float], logits: Sequence[float]
) -> dict[str, float | int]:
    """Evaluate raw cross-encoder logits without fitting a test threshold."""

    if len(labels) != len(logits) or not labels:
        raise ValueError("Binary labels and logits must be non-empty and equally sized")
    positives = [
        score for label, score in zip(labels, logits, strict=True) if label >= 0.5
    ]
    negatives = [
        score for label, score in zip(labels, logits, strict=True) if label < 0.5
    ]
    correct = sum(
        (score >= 0.0) == (label >= 0.5)
        for label, score in zip(labels, logits, strict=True)
    )
    comparisons = 0
    wins = 0.0
    for positive in positives:
        for negative in negatives:
            comparisons += 1
            wins += (
                1.0 if positive > negative else (0.5 if positive == negative else 0.0)
            )
    return {
        "examples": len(labels),
        "positives": len(positives),
        "negatives": len(negatives),
        "zero_logit_accuracy": round(correct / len(labels), 6),
        "roc_auc": round(wins / comparisons, 6) if comparisons else 1.0,
        "mean_positive_logit": round(_mean(positives), 6),
        "mean_negative_logit": round(_mean(negatives), 6),
    }


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0
